#!/usr/bin/env python3
"""gh → CI 效率报告 HTML（无 DB 凭证时用 GitHub REST API 直采）。

复用 ci_analyze.py 的 write_drilldown_html，把 GitHub Actions runs/jobs(steps)
适配成统一的 dict 模型后渲染下钻 HTML（多仓 tab + Gantt 时间轴）。jobs 接口嵌套
steps，一次调用拿到 job+step；run 按日期范围过滤，jobs 并发拉取。

用法：
  # 单仓单 workflow
  python3 ci-effective-report/gh_ci_report.py \
    --target vllm-project/vllm-ascend:E2E \
    --from 2026-07-30 --to 2026-07-30

  # 多仓（每个 target 一个 tab）
  python3 ci-effective-report/gh_ci_report.py \
    --target vllm-project/vllm-ascend:E2E \
    --target sgl-project/sglang:"PR Test (NPU)" \
    --from 2026-07-30 --to 2026-07-30 --drilldown-min 60

  # 用 workflow id（显示名含特殊字符时更稳）
  python3 ci-effective-report/gh_ci_report.py --target vllm-project/vllm-ascend@280054652 ...

  # 不输 --target：默认读 ci-effective-report/drilldown-targets.yaml（仅 NPU 仓，改此文件调默认集合）
  python3 ci-effective-report/gh_ci_report.py --from 2026-07-30 --to 2026-07-30
  # 临时只选某些仓（子串）或换配置
  python3 ci-effective-report/gh_ci_report.py --from 2026-07-30 --to 2026-07-30 --repo sglang
  python3 ci-effective-report/gh_ci_report.py --from 2026-07-30 --to 2026-07-30 --config ../.github-ci-efficiency.yaml --repo vllm-ascend

认证：GITHUB_TOKEN → GH_TOKEN → gh auth token。
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import re
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CI_ANALYZE = SCRIPT_DIR / "ci_analyze.py"
STEP_NAMES = SCRIPT_DIR / "step-names.json"
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG = SCRIPT_DIR / "drilldown-targets.yaml"
DEFAULT_MIN = 60.0


def gh_token() -> str:
    for n in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.getenv(n):
            return os.environ[n]
    return subprocess.check_output(["gh", "auth", "token"], text=True).strip()


def gh_get(token: str, url: str) -> dict:
    import time, urllib.error
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "ci-report-gh",
    })
    # GitHub 偶发错误（5xx + SSL/超时/连接重置等网络层）重试 5 次（指数退避）
    last_exc = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last_exc = e
            if e.code not in (429, 500, 502, 503, 504):
                raise
            time.sleep(2 ** attempt)
        except (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError) as e:
            # SSL EOF、超时、连接重置等网络层瞬时错误
            last_exc = e
            time.sleep(2 ** attempt)
    raise last_exc  # ponytail: 重试耗尽后抛出，调用方记录为 collection_error


def _in_report_range(created_at: str | None, date_from: str, date_to: str) -> bool:
    return bool(created_at and date_from <= created_at[:10] <= date_to)


def refresh_active_runs(token: str, repos_data: dict[str, dict]) -> None:
    """Refresh statuses collected early in a long multi-repo report before rendering it."""
    for repo, data in repos_data.items():
        for run in data.get("runs", []):
            if run.get("status") == "completed":
                continue
            try:
                latest = gh_get(token, f"https://api.github.com/repos/{repo}/actions/runs/{run['id']}")
            except Exception as e:
                print(f"    ⚠ run {run['id']} 最终状态刷新失败，保留采集快照: {e}", file=sys.stderr)
                continue
            run.update({
                "status": latest.get("status") or run.get("status", ""),
                "conclusion": latest.get("conclusion") or run.get("conclusion", ""),
                "updated_at": latest.get("updated_at") or run.get("updated_at", ""),
            })
            run["duration_seconds"] = _sec(
                latest.get("run_started_at") or run.get("created_at"), run.get("updated_at")
            )


def _sec(a: str | None, b: str | None) -> int | None:
    """ISO timestamps -> 秒数差(b-a)，缺失/反向返回 None。"""
    if not a or not b:
        return None
    try:
        da = datetime.fromisoformat(a.replace("Z", "+00:00"))
        db = datetime.fromisoformat(b.replace("Z", "+00:00"))
        return int((db - da).total_seconds()) if db >= da else None
    except (ValueError, TypeError):
        return None


def card_count_from_labels(labels) -> int | None:
    labels = labels if isinstance(labels, list) else [labels]
    return next((int(label.rsplit("-", 1)[1]) for label in labels
                 if isinstance(label, str) and re.fullmatch(r"linux-aarch64-.+-[1-9][0-9]*", label)), None)


def workflow_card_counts(token: str, repo: str, workflow_id: int, workflow_path: str,
                         sha: str, cache: dict[tuple[str, int, str], dict[str, int]]) -> dict[str, int]:
    """Resolve workflow job display names to card counts from the exact executed revision."""
    key = (repo, workflow_id, sha)
    if key in cache:
        return cache[key]
    if not workflow_path or not sha:
        cache[key] = {}
        return cache[key]
    from urllib.parse import quote
    import yaml

    try:
        payload = gh_get(token, f"https://api.github.com/repos/{repo}/contents/{quote(workflow_path)}?ref={quote(sha)}")
        content = base64.b64decode(payload["content"]).decode("utf-8")
        definition = yaml.safe_load(content) or {}
        counts: dict[str, int] = {}
        for job_id, job in (definition.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            count = card_count_from_labels(job.get("runs-on"))
            if count is not None:
                counts[str(job.get("name") or job_id)] = count
    except Exception:
        counts = {}
    cache[key] = counts
    return counts


def parse_target(spec: str) -> tuple[str, str, int | None]:
    """`OWNER/REPO:WORKFLOW` 或 `OWNER/REPO@WORKFLOW_ID` -> (repo, wf_name_or_empty, wf_id_or_None)。"""
    if "@" in spec:
        repo, wf_id = spec.split("@", 1)
        return repo, "", int(wf_id)
    if ":" not in spec:
        raise ValueError(f"target 必须为 OWNER/REPO:WORKFLOW 或 OWNER/REPO@ID，收到 {spec!r}")
    repo, wf = spec.split(":", 1)
    return repo, wf, None


def workflow_id_by_name(token: str, repo: str, name: str) -> int:
    cf = name.casefold()
    page = 1
    while True:
        d = gh_get(token, f"https://api.github.com/repos/{repo}/actions/workflows?per_page=100&page={page}")
        for w in d.get("workflows", []):
            if str(w.get("name", "")).casefold() == cf:
                return int(w["id"])
        if len(d.get("workflows", [])) < 100:
            break
        page += 1
    raise SystemExit(f"{repo}: 找不到 workflow 显示名 {name!r}（可用 --repo@ID 指定 id）")


def fetch_repo(token: str, repo: str, wf_name: str, wf_id: int | None,
               date_from: str, date_to: str) -> dict:
    if wf_id is None:
        wf_id = workflow_id_by_name(token, repo, wf_name)
    # Run payloads also carry a path; use that when a workflow has been renamed.
    try:
        wf_def = gh_get(token, f"https://api.github.com/repos/{repo}/actions/workflows/{wf_id}")
    except Exception as e:
        print(f"    ⚠ workflow metadata 读取失败，卡时将标为未知: {e}", file=sys.stderr)
        wf_def = {}
    if not wf_name:
        wf_name = str(wf_def.get("name") or f"workflow {wf_id}")
    workflow_path = str(wf_def.get("path") or "")
    print(f"  {repo} / {wf_name} (id={wf_id}): 拉 runs...", file=sys.stderr)
    runs_raw: list[dict] = []
    page = 1
    while True:
        url = (f"https://api.github.com/repos/{repo}/actions/workflows/{wf_id}/runs"
               f"?created={date_from}%2E%2E{date_to}&per_page=100&page={page}")
        batch = gh_get(token, url).get("workflow_runs", [])
        runs_raw.extend(r for r in batch if _in_report_range(r.get("created_at"), date_from, date_to))
        if len(batch) < 100:
            break
        page += 1
    print(f"    {len(runs_raw)} runs", file=sys.stderr)

    def _jobs(r: dict) -> tuple[list[dict], list[dict]]:
        rid = r["id"]
        out_j, out_s = [], []
        jp = 1
        while True:
            jd = gh_get(token, f"https://api.github.com/repos/{repo}/actions/runs/{rid}/jobs?per_page=100&page={jp}")
            jobs = jd.get("jobs", [])
            for j in jobs:
                jid = j.get("id")
                out_j.append({
                    "id": jid, "run_id": rid, "name": j.get("name") or "",
                    "status": j.get("status") or "", "conclusion": j.get("conclusion") or "",
                    "created_at": j.get("created_at") or "", "started_at": j.get("started_at") or "",
                    "completed_at": j.get("completed_at") or "", "html_url": j.get("html_url") or "",
                    "labels": j.get("labels") or [],
                    "queue_duration_seconds": _sec(j.get("created_at"), j.get("started_at")),
                    "duration_seconds": _sec(j.get("started_at"), j.get("completed_at")),
                })
                for s in (j.get("steps") or []):
                    out_s.append({
                        "job_id": jid, "number": s.get("number"), "name": s.get("name") or "",
                        "status": s.get("status") or "", "conclusion": s.get("conclusion") or "",
                        "started_at": s.get("started_at") or "", "completed_at": s.get("completed_at") or "",
                        "duration_seconds": _sec(s.get("started_at"), s.get("completed_at")),
                    })
            if len(jobs) < 100:
                break
            jp += 1
        return out_j, out_s

    runs, all_j, all_s = [], [], []
    for r in runs_raw:
        runs.append({
            "id": r["id"], "repo_id": 0, "name": wf_name,
            "head_branch": r.get("head_branch") or "", "head_sha": r.get("head_sha") or "",
            "event": r.get("event") or "", "status": r.get("status") or "",
            "conclusion": r.get("conclusion") or "",
            "created_at": r.get("created_at") or "", "updated_at": r.get("updated_at") or "",
            "html_url": r.get("html_url") or "",
            "duration_seconds": _sec(r.get("run_started_at") or r.get("created_at"), r.get("updated_at")),
            "date": (r.get("created_at") or "")[:10],
            "workflow_file": str(r.get("path") or workflow_path).split("@", 1)[0],
        })
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = {ex.submit(_jobs, r): r for r in runs_raw}
        done = 0
        for f in as_completed(futs):
            try:
                j, s = f.result()
                all_j.extend(j)
                all_s.extend(s)
            except Exception as e:
                r = futs[f]
                print(f"    ⚠ run {r['id']} jobs 取取失败: {e}", file=sys.stderr)
            done += 1
            if done % 50 == 0 or done == len(futs):
                print(f"    jobs 进度: {done}/{len(futs)} runs", file=sys.stderr)
    print(f"    {len(all_j)} jobs, {len(all_s)} steps", file=sys.stderr)
    for job in all_j:
        job["card_count"] = card_count_from_labels(job.get("labels"))
    # ponytail: actual Job labels are already in the existing Jobs response; only unknowns read workflow content.
    fallback_run_ids = {job["run_id"] for job in all_j if job["card_count"] is None}
    counts_by_run: dict[int, dict[str, int]] = {}
    cache: dict[tuple[str, int, str], dict[str, int]] = {}
    for run in runs:
        if run["id"] not in fallback_run_ids:
            continue
        try:
            counts_by_run[run["id"]] = workflow_card_counts(
                token, repo, wf_id, run["workflow_file"], run["head_sha"], cache
            )
        except Exception as e:
            # ponytail: a failed definition lookup leaves usage unknown, never guessed or retried per Run.
            print(f"    ⚠ run {run['id']} workflow 定义读取失败: {e}", file=sys.stderr)
            cache[(repo, wf_id, run["head_sha"])] = {}
            counts_by_run[run["id"]] = {}
    for job in all_j:
        if job["card_count"] is None:
            job["card_count"] = counts_by_run.get(job["run_id"], {}).get(job["name"])
    return {"runs": runs, "jobs": all_j, "steps": all_s, "pr_metrics": [], "pr_workflows": []}


def load_targets_from_config(path: str, repos_filter: list[str] | None = None) -> list[tuple[str, str, int | None]]:
    """从 .github-ci-efficiency.yaml 读 (repo, workflow_name) 对。

    repos_filter: 只保留这些 owner/repo（子串匹配，不区分大小写）。
    """
    import yaml
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out = []
    for r in data.get("repositories", []) or []:
        repo = str(r.get("repo", "")).strip()
        if not repo or "/" not in repo:
            continue
        if repos_filter and not any(f.casefold() in repo.casefold() for f in repos_filter):
            continue
        for wf in r.get("workflows", []) or []:
            name = str((wf.get("name") if isinstance(wf, dict) else wf) or "").strip()
            if name:
                out.append((repo, name, None))
    if not out:
        raise SystemExit(f"配置 {path} 未解析出任何 repo/workflow")
    return out


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="gh → CI 效率报告 HTML（无需 DB 凭证）")
    p.add_argument("--target", action="append",
                   help="OWNER/REPO:WORKFLOW（显示名精确匹配）或 OWNER/REPO@WORKFLOW_ID；可多次指定。省略则从 --config 读")
    p.add_argument("--config", help="repos 配置（默认 .github-ci-efficiency.yaml）；省略 --target 时必走")
    p.add_argument("--repo", action="append", help="从 config 里只选这些仓（子串匹配，可多次）；仅 --config 模式生效")
    p.add_argument("--from", dest="date_from", required=True, help="起始日期 YYYY-MM-DD（含）")
    p.add_argument("--to", dest="date_to", required=True, help="结束日期 YYYY-MM-DD（含）")
    p.add_argument("--drilldown-min", type=float, default=DEFAULT_MIN, help="run 耗时阈值(分钟)，默认 60")
    p.add_argument("--output", "-o", help="输出 HTML 路径（默认 reports/ci-drilldown-{from}_to_{to}.html）")
    p.add_argument("--concurrency", type=int, default=16, help="jobs 并发数，默认 16")
    args = p.parse_args()

    token = gh_token()
    if args.target:
        targets = [parse_target(t) for t in args.target]
    else:
        cfg = args.config or str(DEFAULT_CONFIG if DEFAULT_CONFIG.exists() else REPO_ROOT / ".github-ci-efficiency.yaml")
        if not Path(cfg).exists():
            p.error(f"未给 --target，且默认配置不存在: {cfg}")
        print(f"📂 从 {cfg} 读取 targets..." + (f" 过滤 repo={args.repo}" if args.repo else ""), file=sys.stderr)
        targets = load_targets_from_config(cfg, args.repo)
    repos_data: dict[str, dict] = {}
    for repo, wf_name, wf_id in targets:
        d = fetch_repo(token, repo, wf_name, wf_id, args.date_from, args.date_to)
        if repo in repos_data:
            for k in ("runs", "jobs", "steps"):
                repos_data[repo][k].extend(d[k])
        else:
            repos_data[repo] = d

    refresh_active_runs(token, repos_data)
    spec = importlib.util.spec_from_file_location("ci_analyze", CI_ANALYZE)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules["ci_analyze"] = m
    spec.loader.exec_module(m)

    step_map = {}
    if STEP_NAMES.exists():
        step_map = json.loads(STEP_NAMES.read_text())

    out = Path(args.output) if args.output else (
        REPO_ROOT / "reports" / f"ci-drilldown-{args.date_from}_to_{args.date_to}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    n = sum(len(d["runs"]) for d in repos_data.values())
    m.write_drilldown_html(str(out), repos_data, args.date_from, args.date_to, step_map,
                           "GitHub REST API (gh auth)", min_minutes=args.drilldown_min)
    print(f"\n{out}  ({n} runs, >{int(args.drilldown_min)}min)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
