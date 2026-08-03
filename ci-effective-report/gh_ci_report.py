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

认证：GITHUB_TOKEN → GH_TOKEN → gh auth token。
"""
from __future__ import annotations

import importlib.util
import json
import os
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
DEFAULT_MIN = 60.0


def gh_token() -> str:
    for n in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.getenv(n):
            return os.environ[n]
    return subprocess.check_output(["gh", "auth", "token"], text=True).strip()


def gh_get(token: str, url: str) -> dict:
    import time
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "ci-report-gh",
    })
    # 502/503/504 是 GitHub 偶发错误，重试 3 次（指数退避）
    last_exc = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last_exc = e
            if e.code not in (502, 503, 504):
                raise
            time.sleep(2 ** attempt)
    raise last_exc  # ponytail: 重试耗尽后抛出，调用方记录为 collection_error


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
    # workflow 显示名：用定义里的 name 作聚合名，避免 run-level run-name 干扰
    if not wf_name:
        wf_def = gh_get(token, f"https://api.github.com/repos/{repo}/actions/workflows/{wf_id}")
        wf_name = str(wf_def.get("name") or f"workflow {wf_id}")
    print(f"  {repo} / {wf_name} (id={wf_id}): 拉 runs...", file=sys.stderr)
    runs_raw: list[dict] = []
    page = 1
    while True:
        url = (f"https://api.github.com/repos/{repo}/actions/workflows/{wf_id}/runs"
               f"?created=%3E%3D{date_from}&per_page=100&page={page}")
        batch = gh_get(token, url).get("workflow_runs", [])
        runs_raw.extend(batch)
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
            "date": (r.get("created_at") or "")[:10], "workflow_file": "",
        })
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = {ex.submit(_jobs, r): r for r in runs_raw}
        done = 0
        for f in as_completed(futs):
            j, s = f.result()
            all_j.extend(j)
            all_s.extend(s)
            done += 1
            if done % 50 == 0 or done == len(futs):
                print(f"    jobs 进度: {done}/{len(futs)} runs", file=sys.stderr)
    print(f"    {len(all_j)} jobs, {len(all_s)} steps", file=sys.stderr)
    return {"runs": runs, "jobs": all_j, "steps": all_s, "pr_metrics": [], "pr_workflows": []}


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="gh → CI 效率报告 HTML（无需 DB 凭证）")
    p.add_argument("--target", action="append", required=True,
                   help="OWNER/REPO:WORKFLOW（显示名精确匹配）或 OWNER/REPO@WORKFLOW_ID；可多次指定")
    p.add_argument("--from", dest="date_from", required=True, help="起始日期 YYYY-MM-DD（含）")
    p.add_argument("--to", dest="date_to", required=True, help="结束日期 YYYY-MM-DD（含）")
    p.add_argument("--drilldown-min", type=float, default=DEFAULT_MIN, help="run 耗时阈值(分钟)，默认 60")
    p.add_argument("--output", "-o", help="输出 HTML 路径（默认 reports/ci-drilldown-{from}_to_{to}.html）")
    p.add_argument("--concurrency", type=int, default=16, help="jobs 并发数，默认 16")
    args = p.parse_args()

    token = gh_token()
    targets = [parse_target(t) for t in args.target]
    repos_data: dict[str, dict] = {}
    for repo, wf_name, wf_id in targets:
        d = fetch_repo(token, repo, wf_name, wf_id, args.date_from, args.date_to)
        if repo in repos_data:
            for k in ("runs", "jobs", "steps"):
                repos_data[repo][k].extend(d[k])
        else:
            repos_data[repo] = d

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
