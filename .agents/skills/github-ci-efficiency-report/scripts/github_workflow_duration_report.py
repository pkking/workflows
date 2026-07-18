#!/usr/bin/env python3
"""Generate an attempt-aware GitHub Actions workflow duration workbook."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import socket
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


API_ROOT = "https://api.github.com"
LIST_TTL_SECONDS = 15 * 60
BUILTIN_MIN_E2E_MINUTES = 10.0
REQUIRED_MODULES = {"yaml": "PyYAML", "openpyxl": "openpyxl"}


def ensure_runtime() -> None:
    """Bootstrap the skill-local uv environment when dependencies are absent."""
    missing = [package for module, package in REQUIRED_MODULES.items() if importlib.util.find_spec(module) is None]
    if not missing:
        return
    uv = shutil.which("uv")
    skill_dir = Path(__file__).resolve().parents[1]
    if not uv:
        joined = ", ".join(missing)
        print(f"缺少依赖: {joined}。请安装 uv，或手动安装这些 Python 包。", file=sys.stderr)
        raise SystemExit(2)
    print(f"检测到 uv，正在同步 skill 虚拟环境（缺少: {', '.join(missing)}）...", file=sys.stderr)
    result = subprocess.run([uv, "sync", "--project", str(skill_dir)], check=False)
    if result.returncode:
        raise SystemExit(result.returncode)
    env_python = skill_dir / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not env_python.exists():
        print(f"uv 同步完成但未找到 Python: {env_python}", file=sys.stderr)
        raise SystemExit(2)
    os.execv(str(env_python), [str(env_python), str(Path(__file__).resolve()), *sys.argv[1:]])


def parse_dt(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def seconds_between(start: dt.datetime | None, end: dt.datetime | None) -> float | None:
    if start is None or end is None:
        return None
    value = (end - start).total_seconds()
    return value if value >= 0 else None


def percentile_inc(values: Iterable[float], p: float) -> float | None:
    clean = sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    position = (len(clean) - 1) * p
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return clean[lower]
    fraction = position - lower
    return clean[lower] * (1 - fraction) + clean[upper] * fraction


def average(values: Iterable[float]) -> float | None:
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return statistics.fmean(clean) if clean else None


def rate(success: int, failure: int) -> float | None:
    denominator = success + failure
    return success / denominator if denominator else None


def norm_job_name(name: str) -> str:
    value = re.sub(r"\s*card-\([^)]*\)", "", name)
    value = re.sub(r"\s*\([^)]*\)", "", value)
    return re.sub(r"\s+", " ", value).strip(" /") or name


def format_dt(value: dt.datetime | None, timezone: dt.tzinfo) -> str:
    return value.astimezone(timezone).isoformat(timespec="seconds") if value else ""


@dataclass(frozen=True)
class Target:
    repo: str
    workflow_name: str
    comparison_group: str
    comparison_name: str
    min_e2e_minutes: float


@dataclass
class StepRecord:
    name: str
    status: str
    conclusion: str
    number: int | None
    started_at: dt.datetime | None
    completed_at: dt.datetime | None

    @property
    def execution_seconds(self) -> float | None:
        return seconds_between(self.started_at, self.completed_at)


@dataclass
class JobRecord:
    id: int
    name: str
    status: str
    conclusion: str
    created_at: dt.datetime | None
    started_at: dt.datetime | None
    completed_at: dt.datetime | None
    steps: list[StepRecord] = field(default_factory=list)

    @property
    def queue_seconds(self) -> float | None:
        return seconds_between(self.created_at, self.started_at)

    @property
    def execution_seconds(self) -> float | None:
        return seconds_between(self.started_at, self.completed_at)


@dataclass
class AttemptRecord:
    target: Target
    workflow_id: int
    workflow_name: str
    run_id: int
    attempt: int
    status: str
    conclusion: str
    event: str
    branch: str
    run_started_at: dt.datetime | None
    updated_at: dt.datetime | None
    html_url: str
    jobs: list[JobRecord] = field(default_factory=list)
    collection_error: str = ""

    @property
    def key(self) -> tuple[int, int]:
        return self.run_id, self.attempt

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    @property
    def earliest_job_created(self) -> dt.datetime | None:
        values = [j.created_at for j in self.jobs if j.created_at]
        return min(values) if values else None

    @property
    def latest_job_completed(self) -> dt.datetime | None:
        values = [j.completed_at for j in self.jobs if j.completed_at]
        return max(values) if values else None

    @property
    def e2e_seconds(self) -> float | None:
        job_value = seconds_between(self.earliest_job_created, self.latest_job_completed)
        if job_value is not None:
            return job_value
        return seconds_between(self.run_started_at, self.updated_at)

    @property
    def max_queue(self) -> tuple[float | None, str]:
        valid = [(j.queue_seconds, j.name) for j in self.jobs if j.queue_seconds is not None]
        return max(valid, default=(None, ""), key=lambda item: item[0] if item[0] is not None else -1)

    @property
    def max_execution(self) -> tuple[float | None, str]:
        valid = [(j.execution_seconds, j.name) for j in self.jobs if j.execution_seconds is not None]
        return max(valid, default=(None, ""), key=lambda item: item[0] if item[0] is not None else -1)


class Cache:
    def __init__(self, root: Path, refresh: bool = False) -> None:
        self.root = root
        self.refresh = refresh
        self.root.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / digest[:2] / f"{digest}.json"

    def read(self, key: str, ttl_seconds: int | None) -> tuple[Any, dict[str, str]] | None:
        if self.refresh:
            return None
        path = self._path(key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = float(payload["fetched_at"])
            if ttl_seconds is not None and time.time() - fetched_at > ttl_seconds:
                return None
            with self._lock:
                self.hits += 1
            return payload["data"], payload.get("headers", {})
        except FileNotFoundError:
            return None
        except (ValueError, KeyError, TypeError, OSError):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return None

    def write(self, key: str, data: Any, headers: dict[str, str]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"fetched_at": time.time(), "headers": headers, "data": data}
        temp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)
        with self._lock:
            self.misses += 1


class GitHubClient:
    def __init__(self, token: str, cache: Cache) -> None:
        self.token = token
        self.cache = cache
        self.calls = 0
        self._lock = threading.Lock()

    def get(self, path: str, params: dict[str, Any] | None = None, ttl_seconds: int | None = LIST_TTL_SECONDS) -> Any:
        query = urllib.parse.urlencode(params or {})
        url = path if path.startswith("http") else f"{API_ROOT}{path}"
        if query:
            url = f"{url}?{query}"
        cached = self.cache.read(url, ttl_seconds)
        if cached is not None:
            return cached[0]
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "github-workflow-duration-report",
            },
        )
        for attempt in range(6):
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    raw = response.read().decode("utf-8")
                    data = json.loads(raw)
                    headers = {k.lower(): v for k, v in response.headers.items()}
                    with self._lock:
                        self.calls += 1
                    self.cache.write(url, data, headers)
                    return data
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                remaining = exc.headers.get("x-ratelimit-remaining")
                reset = exc.headers.get("x-ratelimit-reset")
                if exc.code in {403, 429} and remaining == "0" and reset and reset.isdigit():
                    delay = max(1, int(reset) - int(time.time()) + 2)
                    print(f"GitHub API 限流，等待 {delay}s 后继续...", file=sys.stderr)
                    time.sleep(delay)
                    continue
                if exc.code in {403, 429, 500, 502, 503, 504} and attempt < 5:
                    delay = min(60, 2**attempt)
                    print(f"GitHub API {exc.code}，{delay}s 后重试: {url}", file=sys.stderr)
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"GitHub API {exc.code}: {url}: {body[:500]}") from exc
            except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
                if attempt < 5:
                    delay = min(60, 2**attempt)
                    print(f"GitHub API 网络错误，{delay}s 后重试: {exc}", file=sys.stderr)
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"GitHub API network error: {url}: {exc}") from exc
        raise RuntimeError(f"GitHub API failed: {url}")

    def paginate(self, path: str, item_key: str, ttl_seconds: int | None = LIST_TTL_SECONDS) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self.get(path, {"per_page": 100, "page": page}, ttl_seconds=ttl_seconds)
            items = data.get(item_key, []) if isinstance(data, dict) else data
            if not isinstance(items, list):
                raise RuntimeError(f"Unexpected paginated response for {path}")
            output.extend(items)
            if len(items) < 100:
                return output
            page += 1


def get_token() -> str:
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.getenv(name)
        if value:
            return value
    gh = shutil.which("gh")
    if gh:
        result = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    print("未找到 GitHub token。请设置 GITHUB_TOKEN/GH_TOKEN，或执行 gh auth login。", file=sys.stderr)
    raise SystemExit(2)


def repo_root() -> Path:
    # scripts/<skill>/<skills>/.agents/<repository root>
    return Path(__file__).resolve().parents[5]


def load_targets(args: argparse.Namespace) -> list[Target]:
    import yaml

    root = repo_root()
    if args.config and args.repo:
        raise ValueError("--config 与 --repo 不能同时使用")
    config_path: Path | None = Path(args.config).resolve() if args.config else None
    if not config_path and not args.repo:
        config_path = root / ".github-ci-efficiency.yaml"
    targets: list[Target] = []
    if config_path:
        if not config_path.exists():
            raise ValueError(f"配置文件不存在: {config_path}")
        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError(f"无法读取 YAML 配置: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("配置根节点必须是 mapping")
        defaults = data.get("defaults") or {}
        if not isinstance(defaults, dict):
            raise ValueError("defaults 必须是 mapping")
        default_min = parse_threshold(defaults.get("min_e2e_minutes", BUILTIN_MIN_E2E_MINUTES), "defaults.min_e2e_minutes")
        repositories = data.get("repositories")
        if not isinstance(repositories, list) or not repositories:
            raise ValueError("配置必须包含非空 repositories 列表")
        for repository in repositories:
            if not isinstance(repository, dict):
                raise ValueError("repositories 中的每一项必须是 mapping")
            repo = str(repository.get("repo", "")).strip()
            if "/" not in repo:
                raise ValueError(f"无效 repo: {repo!r}，必须为 owner/name")
            group = str(repository.get("comparison_group") or repo.split("/", 1)[0])
            workflows = repository.get("workflows")
            if not isinstance(workflows, list) or not workflows:
                raise ValueError(f"{repo} 必须配置非空 workflows")
            for workflow in workflows:
                if isinstance(workflow, str):
                    workflow = {"name": workflow}
                name = str(workflow.get("name", "")).strip()
                if not name:
                    raise ValueError(f"{repo} 存在空 workflow name")
                configured_min = parse_threshold(workflow.get("min_e2e_minutes", default_min), f"{repo}.{name}.min_e2e_minutes")
                targets.append(Target(repo, name, group, str(workflow.get("comparison_name") or name), configured_min))
    else:
        if "/" not in args.repo:
            raise ValueError("--repo 必须为 owner/name")
        if not args.workflow:
            raise ValueError("--repo 模式至少需要一个 --workflow")
        for name in args.workflow:
            targets.append(Target(args.repo, name, args.repo.split("/", 1)[0], name, BUILTIN_MIN_E2E_MINUTES))
    if args.min_e2e_minutes is not None:
        cli_min = parse_threshold(args.min_e2e_minutes, "--min-e2e-minutes")
        targets = [Target(t.repo, t.workflow_name, t.comparison_group, t.comparison_name, cli_min) for t in targets]
    identities = [(t.repo.casefold(), t.workflow_name.casefold()) for t in targets]
    duplicates = [key for key, count in Counter(identities).items() if count > 1]
    if duplicates:
        raise ValueError(f"重复 repo/workflow 配置: {duplicates}")
    return targets


def parse_threshold(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是非负数字") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{label} 必须是非负数字")
    return parsed


def reporting_timezone(name: str | None) -> tuple[dt.tzinfo, str]:
    if name:
        try:
            return ZoneInfo(name), name
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"未知时区: {name}") from exc
    local = dt.datetime.now().astimezone().tzinfo or dt.timezone.utc
    return local, str(local)


def workflow_defs(client: GitHubClient, target: Target) -> list[dict[str, Any]]:
    workflows = client.paginate(f"/repos/{target.repo}/actions/workflows", "workflows")
    matches = [w for w in workflows if str(w.get("name", "")).casefold() == target.workflow_name.casefold()]
    if not matches:
        available = sorted(str(w.get("name", "")) for w in workflows)
        raise RuntimeError(f"{target.repo} 未找到精确 workflow {target.workflow_name!r}；可用: {available}")
    return matches


def attempt_payloads(client: GitHubClient, repo: str, workflow_id: int) -> list[dict[str, Any]]:
    runs = client.paginate(f"/repos/{repo}/actions/workflows/{workflow_id}/runs", "workflow_runs")
    output: list[dict[str, Any]] = []
    # The list endpoint is cached for 15 minutes, but an active attempt must
    # be refreshed on every run. Fetch its attempt payload instead of reusing
    # the potentially stale list item.
    output.extend(r for r in runs if int(r.get("run_attempt") or 1) == 1 and r.get("status") == "completed")

    def fetch_attempt(run_id: int, attempt: int) -> dict[str, Any]:
        return client.get(f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}", ttl_seconds=None)

    tasks: list[tuple[int, int]] = []
    for run in runs:
        run_id = int(run["id"])
        latest = int(run.get("run_attempt") or 1)
        if latest > 1 or run.get("status") != "completed":
            tasks.extend((run_id, attempt) for attempt in range(1, latest + 1))
    if tasks:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(fetch_attempt, run_id, attempt): (run_id, attempt) for run_id, attempt in tasks}
            for future in as_completed(futures):
                output.append(future.result())
    return output


def parse_jobs(payload: Any) -> list[JobRecord]:
    raw_jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    jobs: list[JobRecord] = []
    for raw in raw_jobs:
        steps = [
            StepRecord(
                name=str(step.get("name", "")),
                status=str(step.get("status", "")),
                conclusion=str(step.get("conclusion") or ""),
                number=step.get("number"),
                started_at=parse_dt(step.get("started_at")),
                completed_at=parse_dt(step.get("completed_at")),
            )
            for step in (raw.get("steps") or [])
        ]
        jobs.append(
            JobRecord(
                id=int(raw["id"]),
                name=str(raw.get("name", "")),
                status=str(raw.get("status", "")),
                conclusion=str(raw.get("conclusion") or ""),
                created_at=parse_dt(raw.get("created_at")),
                started_at=parse_dt(raw.get("started_at")),
                completed_at=parse_dt(raw.get("completed_at")),
                steps=steps,
            )
        )
    return jobs


def fetch_attempt_jobs(client: GitHubClient, record: AttemptRecord) -> list[JobRecord]:
    path = f"/repos/{record.target.repo}/actions/runs/{record.run_id}/attempts/{record.attempt}/jobs"
    items = client.paginate(path, "jobs", ttl_seconds=None if record.completed else 0)
    return parse_jobs({"jobs": items})


def collect(
    client: GitHubClient,
    targets: list[Target],
    start_utc: dt.datetime,
    end_utc: dt.datetime,
    concurrency: int,
) -> tuple[list[AttemptRecord], list[str]]:
    records: list[AttemptRecord] = []
    errors: list[str] = []
    for target in targets:
        print(f"解析 {target.repo} / {target.workflow_name}...", file=sys.stderr)
        try:
            definitions = workflow_defs(client, target)
        except Exception as exc:
            errors.append(str(exc))
            continue
        for definition in definitions:
            workflow_id = int(definition["id"])
            try:
                payloads = attempt_payloads(client, target.repo, workflow_id)
            except Exception as exc:
                errors.append(f"{target.repo}/{workflow_id} attempts: {exc}")
                continue
            for raw in payloads:
                started = parse_dt(raw.get("run_started_at"))
                created = parse_dt(raw.get("created_at"))
                belongs = started is not None and start_utc <= started < end_utc
                if started is None:
                    fallback = created or parse_dt(raw.get("updated_at"))
                    belongs = fallback is not None and start_utc <= fallback < end_utc
                if not belongs:
                    continue
                records.append(
                    AttemptRecord(
                        target=target,
                        workflow_id=workflow_id,
                        workflow_name=str(raw.get("name") or definition.get("name") or target.workflow_name),
                        run_id=int(raw["id"]),
                        attempt=int(raw.get("run_attempt") or 1),
                        status=str(raw.get("status", "")),
                        conclusion=str(raw.get("conclusion") or ""),
                        event=str(raw.get("event", "")),
                        branch=str(raw.get("head_branch") or ""),
                        run_started_at=started,
                        updated_at=parse_dt(raw.get("updated_at")),
                        html_url=str(raw.get("html_url", "")),
                    )
                )
            print(f"  workflow_id={workflow_id}: 范围内 {sum(1 for r in records if r.target == target and r.workflow_id == workflow_id)} attempts", file=sys.stderr)

    def attach_jobs(record: AttemptRecord) -> None:
        try:
            record.jobs = fetch_attempt_jobs(client, record)
        except Exception as exc:
            record.collection_error = str(exc)
            errors.append(f"{record.target.repo} run={record.run_id} attempt={record.attempt}: {exc}")

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = [executor.submit(attach_jobs, record) for record in records]
        for index, future in enumerate(as_completed(futures), 1):
            future.result()
            if index % 100 == 0 or index == len(futures):
                print(f"Jobs 采集进度: {index}/{len(futures)}", file=sys.stderr)
    records.sort(key=lambda r: (r.target.comparison_group, r.target.comparison_name, r.target.repo, r.workflow_id, r.run_started_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc), r.run_id, r.attempt))
    return records, errors


def conclusion_counts(values: Iterable[str]) -> Counter[str]:
    return Counter(value or "unknown" for value in values)


def workflow_rows(records: list[AttemptRecord]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[AttemptRecord]] = defaultdict(list)
    for record in records:
        groups[(record.target, record.workflow_id, record.workflow_name)].append(record)
    threshold_sets: dict[str, set[float]] = defaultdict(set)
    for target, _, _ in groups:
        threshold_sets[target.comparison_group].add(target.min_e2e_minutes)
    output: list[dict[str, Any]] = []
    for (target, workflow_id, workflow_name), attempts in groups.items():
        completed = [a for a in attempts if a.completed]
        counts = conclusion_counts(a.conclusion for a in completed)
        successful = [a for a in completed if a.conclusion == "success"]
        short = [a for a in successful if a.e2e_seconds is not None and a.e2e_seconds < target.min_e2e_minutes * 60]
        valid = [a for a in successful if a.e2e_seconds is not None and a.e2e_seconds >= target.min_e2e_minutes * 60]
        e2e = [a.e2e_seconds for a in valid if a.e2e_seconds is not None]
        queues = [a.max_queue[0] for a in valid if a.max_queue[0] is not None]
        executions = [a.max_execution[0] for a in valid if a.max_execution[0] is not None]
        invalid = sum(1 for a in successful if a.e2e_seconds is None) + sum(1 for a in valid if a.max_queue[0] is None or a.max_execution[0] is None)
        output.append({
            "比较组": target.comparison_group,
            "对比Workflow": target.comparison_name,
            "仓库名": target.repo,
            "Workflow名": workflow_name,
            "Workflow ID": workflow_id,
            "执行次数": len(completed),
            "成功数": counts["success"],
            "失败数": counts["failure"],
            "取消数": counts["cancelled"],
            "跳过数": counts["skipped"],
            "成功率": rate(counts["success"], counts["failure"]),
            "最短E2E阈值(分钟)": target.min_e2e_minutes,
            "有效耗时样本数": len(valid),
            "短Run排除数": len(short),
            "无效样本数": invalid,
            "可比性提示": "阈值不同，仅供参考" if len(threshold_sets[target.comparison_group]) > 1 else "",
            "实际E2E平均(分钟)": average(e2e),
            "实际E2E P50(分钟)": percentile_inc(e2e, 0.5),
            "实际E2E P90(分钟)": percentile_inc(e2e, 0.9),
            "排队耗时平均(分钟)": average(queues),
            "排队耗时 P50(分钟)": percentile_inc(queues, 0.5),
            "排队耗时 P90(分钟)": percentile_inc(queues, 0.9),
            "执行耗时平均(分钟)": average(executions),
            "执行耗时 P50(分钟)": percentile_inc(executions, 0.5),
            "执行耗时 P90(分钟)": percentile_inc(executions, 0.9),
        })
    return sorted(output, key=lambda row: (row["比较组"], row["对比Workflow"], row["仓库名"], row["Workflow名"], row["Workflow ID"]))


def run_rows(records: list[AttemptRecord], timezone: dt.tzinfo) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for record in records:
        e2e = record.e2e_seconds
        queue, queue_job = record.max_queue
        execution, execution_job = record.max_execution
        if not record.completed:
            included, reason = False, "未完成"
        elif record.conclusion != "success":
            included, reason = False, f"结论={record.conclusion or 'unknown'}"
        elif e2e is None:
            included, reason = False, "E2E时间无效"
        elif e2e < record.target.min_e2e_minutes * 60:
            included, reason = False, "低于最短E2E阈值"
        else:
            included, reason = True, ""
        output.append({
            "比较组": record.target.comparison_group,
            "对比Workflow": record.target.comparison_name,
            "仓库名": record.target.repo,
            "Workflow名": record.workflow_name,
            "Workflow ID": record.workflow_id,
            "Run ID": record.run_id,
            "Attempt": record.attempt,
            "状态": record.status,
            "结论": record.conclusion,
            "事件": record.event,
            "分支": record.branch,
            "Attempt启动时间": format_dt(record.run_started_at, timezone),
            "最早Job创建时间": format_dt(record.earliest_job_created, timezone),
            "最晚Job完成时间": format_dt(record.latest_job_completed, timezone),
            "实际E2E(分钟)": e2e,
            "最大排队耗时(分钟)": queue,
            "最大排队Job": queue_job,
            "最大执行耗时(分钟)": execution,
            "最大执行Job": execution_job,
            "最短E2E阈值(分钟)": record.target.min_e2e_minutes,
            "进入Workflow耗时统计": "是" if included else "否",
            "排除原因": reason,
            "数据错误": record.collection_error,
            "GitHub链接": record.html_url,
        })
    return output


def job_rows(records: list[AttemptRecord]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[JobRecord]] = defaultdict(list)
    metadata: dict[tuple[Any, ...], tuple[Target, str, int, str]] = {}
    for record in records:
        if not record.completed:
            continue
        for job in record.jobs:
            key = (record.target.repo, record.workflow_id, job.name)
            groups[key].append(job)
            metadata[key] = (record.target, record.workflow_name, record.workflow_id, job.name)
    output: list[dict[str, Any]] = []
    for key, jobs in groups.items():
        target, workflow_name, workflow_id, job_name = metadata[key]
        counts = conclusion_counts(j.conclusion for j in jobs)
        queue_expected = [j for j in jobs if j.conclusion in {"success", "failure"}]
        exec_expected = [j for j in jobs if j.conclusion == "success"]
        queues = [j.queue_seconds for j in queue_expected if j.queue_seconds is not None]
        executions = [j.execution_seconds for j in exec_expected if j.execution_seconds is not None]
        invalid_ids = {j.id for j in queue_expected if j.queue_seconds is None} | {j.id for j in exec_expected if j.execution_seconds is None}
        output.append({
            "比较组": target.comparison_group,
            "对比Workflow": target.comparison_name,
            "仓库名": target.repo,
            "Workflow名": workflow_name,
            "Workflow ID": workflow_id,
            "Job原始名": job_name,
            "Job归一化名": norm_job_name(job_name),
            "执行数": len(jobs),
            "成功数": counts["success"],
            "失败数": counts["failure"],
            "取消数": counts["cancelled"],
            "跳过数": counts["skipped"],
            "成功率": rate(counts["success"], counts["failure"]),
            "失败率": rate(counts["failure"], counts["success"]),
            "排队有效样本数": len(queues),
            "排队平均(分钟)": average(queues),
            "排队 P50(分钟)": percentile_inc(queues, 0.5),
            "排队 P90(分钟)": percentile_inc(queues, 0.9),
            "执行有效样本数": len(executions),
            "执行平均(分钟)": average(executions),
            "执行 P50(分钟)": percentile_inc(executions, 0.5),
            "执行 P90(分钟)": percentile_inc(executions, 0.9),
            "无效样本数": len(invalid_ids),
        })
    def key_fn(row: dict[str, Any]) -> tuple[Any, ...]:
        return (-(row["执行 P90(分钟)"] or -1), -(row["排队 P90(分钟)"] or -1), -(row["失败率"] or -1), -row["执行数"], row["仓库名"], row["Workflow ID"], row["Job原始名"])
    return sorted(output, key=key_fn)


def step_rows(records: list[AttemptRecord]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[StepRecord]] = defaultdict(list)
    metadata: dict[tuple[Any, ...], tuple[Target, str, int, str, str]] = {}
    for record in records:
        if not record.completed:
            continue
        for job in record.jobs:
            for step in job.steps:
                key = (record.target.repo, record.workflow_id, job.name, step.name)
                groups[key].append(step)
                metadata[key] = (record.target, record.workflow_name, record.workflow_id, job.name, step.name)
    output: list[dict[str, Any]] = []
    for key, steps in groups.items():
        target, workflow_name, workflow_id, job_name, step_name = metadata[key]
        counts = conclusion_counts(s.conclusion for s in steps)
        expected = [s for s in steps if s.conclusion == "success"]
        executions = [s.execution_seconds for s in expected if s.execution_seconds is not None]
        output.append({
            "比较组": target.comparison_group,
            "对比Workflow": target.comparison_name,
            "仓库名": target.repo,
            "Workflow名": workflow_name,
            "Workflow ID": workflow_id,
            "Job原始名": job_name,
            "Step名": step_name,
            "执行数": len(steps),
            "成功数": counts["success"],
            "失败数": counts["failure"],
            "取消数": counts["cancelled"],
            "跳过数": counts["skipped"],
            "成功率": rate(counts["success"], counts["failure"]),
            "失败率": rate(counts["failure"], counts["success"]),
            "执行有效样本数": len(executions),
            "执行平均(分钟)": average(executions),
            "执行 P50(分钟)": percentile_inc(executions, 0.5),
            "执行 P90(分钟)": percentile_inc(executions, 0.9),
            "无效样本数": sum(1 for s in expected if s.execution_seconds is None),
        })
    def key_fn(row: dict[str, Any]) -> tuple[Any, ...]:
        return (-(row["执行 P90(分钟)"] or -1), -(row["失败率"] or -1), -row["执行数"], row["仓库名"], row["Workflow ID"], row["Job原始名"], row["Step名"])
    return sorted(output, key=key_fn)


def minutes_for_excel(value: Any, header: str) -> Any:
    if value is None:
        return None
    if "(分钟)" in header and isinstance(value, (int, float)) and "阈值" not in header:
        return round(value / 60.0, 1)
    if "阈值(分钟)" in header and isinstance(value, (int, float)):
        return round(value, 1)
    return value


def write_table_sheet(workbook: Any, name: str, rows: list[dict[str, Any]]) -> None:
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    sheet = workbook.create_sheet(name)
    if not rows:
        sheet.append(["无数据"])
        return
    headers = list(rows[0])
    sheet.append(headers)
    for row in rows:
        sheet.append([minutes_for_excel(row.get(header), header) for header in headers])
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4472C4")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for index, header in enumerate(headers, 1):
        if header in {"成功率", "失败率"}:
            for cell in sheet.iter_cols(min_col=index, max_col=index, min_row=2):
                for item in cell:
                    item.number_format = "0.0%"
        elif "(分钟)" in header:
            for cell in sheet.iter_cols(min_col=index, max_col=index, min_row=2):
                for item in cell:
                    item.number_format = "0.0"
        width = max(len(str(header)), *(len(str(sheet.cell(row=row, column=index).value or "")) for row in range(2, min(sheet.max_row, 200) + 1))) + 2
        sheet.column_dimensions[get_column_letter(index)].width = min(max(width, 10), 60)


def write_key_value_sheet(workbook: Any, name: str, rows: list[tuple[str, Any]]) -> None:
    from openpyxl.styles import Font, PatternFill

    sheet = workbook.create_sheet(name)
    sheet.append(["项目", "值"])
    for key, value in rows:
        sheet.append([key, value])
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4472C4")
    sheet.freeze_panes = "A2"
    sheet.column_dimensions["A"].width = 30
    sheet.column_dimensions["B"].width = 100


def write_workbook(
    output: Path,
    records: list[AttemptRecord],
    errors: list[str],
    args: argparse.Namespace,
    timezone: dt.tzinfo,
    timezone_name: str,
    start_utc: dt.datetime,
    end_utc: dt.datetime,
    client: GitHubClient,
    partial: bool,
) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    targets_text = "; ".join(sorted({f"{r.target.repo}/{r.target.workflow_name}" for r in records}))
    write_key_value_sheet(workbook, "报告信息", [
        ("完整性", "部分报告（数据不完整）" if partial else "完整"),
        ("目标", targets_text),
        ("本地日期范围", f"{args.date_from} .. {args.date_to}（含首尾）"),
        ("报表时区", timezone_name),
        ("UTC查询边界", f"[{start_utc.isoformat()}, {end_utc.isoformat()})"),
        ("Workflow耗时样本", "仅 success 且达到各 workflow 最短 E2E 阈值"),
        ("Job/Step样本", "全部 completed workflow attempts，不受 Workflow 阈值影响"),
        ("未完成Attempt数", sum(1 for r in records if not r.completed)),
        ("API请求数", client.calls),
        ("缓存命中数", client.cache.hits),
        ("缓存写入数", client.cache.misses),
        ("采集错误数", len(errors)),
        ("采集错误", " | ".join(errors)),
        ("生成时间", dt.datetime.now(timezone).isoformat(timespec="seconds")),
        ("数据源", "GitHub REST API"),
    ])
    definitions = [
        {"指标": "Workflow执行记录", "定义": "一个 workflow run attempt；rerun attempt 分别计数，并按自身 run_started_at 归期。", "样本规则": "执行次数仅统计 completed attempts。"},
        {"指标": "Workflow实际E2E", "定义": "max(job.completed_at) - min(job.created_at)；无 Job 时间时回退 run.updated_at - run.run_started_at。", "样本规则": "仅 success 且达到 workflow 阈值。"},
        {"指标": "Workflow排队耗时", "定义": "一次 attempt 内 max(job.started_at - job.created_at)。", "样本规则": "与 Workflow 实际E2E使用相同有效 attempts。"},
        {"指标": "Workflow执行耗时", "定义": "一次 attempt 内 max(job.completed_at - job.started_at)。", "样本规则": "与 Workflow 实际E2E使用相同有效 attempts。"},
        {"指标": "Workflow成功率", "定义": "success / (success + failure)。", "样本规则": "cancelled/skipped 不进入分母。"},
        {"指标": "Job排队耗时", "定义": "job.started_at - job.created_at。", "样本规则": "success 和 failure Job。"},
        {"指标": "Job/Step执行耗时", "定义": "completed_at - started_at。", "样本规则": "仅 success Job/Step。"},
        {"指标": "Job/Step成功率", "定义": "success / (success + failure)。", "样本规则": "cancelled/skipped 不进入分母。"},
        {"指标": "P50/P90", "定义": "Excel PERCENTILE.INC 等价的包含端点线性插值。", "样本规则": "单样本时 P50/P90 等于该样本。"},
        {"指标": "异常时间", "定义": "缺失必要时间戳或负耗时。", "样本规则": "留空并从对应统计排除，不以 0 填充。"},
        {"指标": "可比性提示", "定义": "同一比较组/对比Workflow 使用不同最短 E2E 阈值。", "样本规则": "允许生成，但标记“阈值不同，仅供参考”。"},
    ]
    write_table_sheet(workbook, "指标定义", definitions)
    write_table_sheet(workbook, "Workflow统计", workflow_rows(records))
    write_table_sheet(workbook, "Run明细", run_rows(records, timezone))
    write_table_sheet(workbook, "Job统计", job_rows(records))
    write_table_sheet(workbook, "Step统计", step_rows(records))
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="通过 GitHub API 生成 Workflow 耗时 Excel 报告")
    parser.add_argument("--config", help="YAML 配置路径；与 --repo 互斥")
    parser.add_argument("--repo", help="临时单仓模式 owner/name；与 --config 互斥")
    parser.add_argument("--workflow", action="append", help="精确 Workflow 显示名；--repo 模式可重复")
    parser.add_argument("--from", dest="date_from", required=True, help="本地时区起始日期 YYYY-MM-DD（含）")
    parser.add_argument("--to", dest="date_to", required=True, help="本地时区结束日期 YYYY-MM-DD（含）")
    parser.add_argument("--timezone", help="IANA 时区，如 Asia/Shanghai；默认当前用户时区")
    parser.add_argument("--min-e2e-minutes", type=float, help="覆盖所有 workflow 的最短 E2E 阈值")
    parser.add_argument("--output", "-o", help="Excel 输出路径")
    parser.add_argument("--concurrency", type=int, default=8, help="Jobs API 并发数，默认 8")
    parser.add_argument("--refresh", action="store_true", help="忽略 API 缓存")
    parser.add_argument("--allow-partial", action="store_true", help="采集不完整时仍生成醒目标记的部分报告")
    return parser.parse_args()


def main() -> int:
    ensure_runtime()
    args = parse_args()
    try:
        targets = load_targets(args)
        timezone, timezone_name = reporting_timezone(args.timezone)
        start_date = dt.date.fromisoformat(args.date_from)
        end_date = dt.date.fromisoformat(args.date_to)
        if end_date < start_date:
            raise ValueError("--to 不能早于 --from")
        start_local = dt.datetime.combine(start_date, dt.time.min, tzinfo=timezone)
        end_local = dt.datetime.combine(end_date + dt.timedelta(days=1), dt.time.min, tzinfo=timezone)
    except ValueError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2
    start_utc = start_local.astimezone(dt.timezone.utc)
    end_utc = end_local.astimezone(dt.timezone.utc)
    root = repo_root()
    cache = Cache(root / ".cache" / "github-ci-efficiency", refresh=args.refresh)
    client = GitHubClient(get_token(), cache)
    records, errors = collect(client, targets, start_utc, end_utc, args.concurrency)
    if errors and not args.allow_partial:
        print("采集不完整，拒绝生成正式报告。缓存已保留，修复后可直接重跑：", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    output = Path(args.output).resolve() if args.output else root / "reports" / f"github-workflow-duration-{args.date_from}_to_{args.date_to}.xlsx"
    if errors and args.allow_partial:
        output = output.with_name(f"{output.stem}.partial{output.suffix}")
    write_workbook(output, records, errors, args, timezone, timezone_name, start_utc, end_utc, client, bool(errors))
    print(f"报告已生成: {output}", file=sys.stderr)
    print(f"Attempts={len(records)} API={client.calls} cache_hits={cache.hits}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
