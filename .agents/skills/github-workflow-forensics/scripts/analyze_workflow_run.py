#!/usr/bin/env python3
"""Generate a standalone timing-forensics HTML for GitHub Actions run attempts."""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

UTC = dt.timezone.utc
RUN_URL = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/actions/runs/(\d+)(?:/attempts/(\d+))?/?$")


def parse_time(value: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def seconds(start: dt.datetime | None, end: dt.datetime | None) -> float | None:
    if not start or not end or end < start:
        return None
    return (end - start).total_seconds()


def minutes(value: float | None) -> str:
    return "—" if value is None else f"{value / 60:.1f} min"


def stamp(value: dt.datetime | None) -> str:
    return "unknown" if value is None else value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def token() -> str:
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.getenv(name):
            return os.environ[name]
    try:
        return subprocess.check_output(["gh", "auth", "token"], text=True, stderr=subprocess.DEVNULL).strip()
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("Set GITHUB_TOKEN/GH_TOKEN or authenticate with `gh auth login`.") from exc


class GitHub:
    def __init__(self, auth: str) -> None:
        self.auth = auth
        self.calls = 0

    def get(self, path: str, params: dict[str, Any] | None = None) -> tuple[Any, dict[str, str]]:
        url = "https://api.github.com" + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.auth}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "github-workflow-forensics",
        })
        for attempt in range(5):
            try:
                self.calls += 1
                with urllib.request.urlopen(request, timeout=60) as response:
                    return json.load(response), dict(response.headers)
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 4:
                    body = exc.read().decode("utf-8", "replace")
                    raise RuntimeError(f"GitHub API {exc.code} for {path}: {body[:500]}") from exc
                time.sleep(2 ** attempt)
        raise AssertionError("unreachable")

    def paginate(self, path: str, key: str) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        page = 1
        while True:
            payload, _ = self.get(path, {"per_page": 100, "page": page})
            batch = payload.get(key, [])
            output.extend(batch)
            if len(batch) < 100:
                return output
            page += 1


def parse_target(raw: str, repo: str | None) -> tuple[str, int, int | None]:
    match = RUN_URL.match(raw)
    if match:
        owner, name, run_id, attempt = match.groups()
        return f"{owner}/{name}", int(run_id), int(attempt) if attempt else None
    if raw.isdigit() and repo and re.fullmatch(r"[^/]+/[^/]+", repo):
        return repo, int(raw), None
    raise ValueError(f"Invalid run target: {raw!r}. Use a GitHub run URL or --repo OWNER/REPO with a numeric ID.")


def collect(client: GitHub, repo: str, run_id: int, requested_attempt: int | None) -> dict[str, Any]:
    latest, _ = client.get(f"/repos/{repo}/actions/runs/{run_id}")
    attempt = requested_attempt or int(latest.get("run_attempt") or 1)
    run = latest
    if attempt != int(latest.get("run_attempt") or 1):
        run, _ = client.get(f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}")
    jobs = client.paginate(f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
    return analyze(repo, run, jobs, dt.datetime.now(UTC))


def analyze(repo: str, run: dict[str, Any], jobs: list[dict[str, Any]], now: dt.datetime) -> dict[str, Any]:
    normalized = []
    for raw in jobs:
        created = parse_time(raw.get("created_at"))
        started = parse_time(raw.get("started_at"))
        completed = parse_time(raw.get("completed_at"))
        effective_end = completed or (now if raw.get("status") != "completed" and started else None)
        steps = []
        for step in raw.get("steps") or []:
            step_start = parse_time(step.get("started_at"))
            step_end = parse_time(step.get("completed_at"))
            step_effective_end = step_end or (now if step.get("status") != "completed" and step_start else None)
            step_duration = seconds(step_start, step_effective_end)
            timestamp_error = step_duration is not None and (
                (started is not None and step_start < started)
                or (effective_end is not None and step_effective_end > effective_end)
            )
            steps.append({
                "name": str(step.get("name") or "unnamed step"),
                "number": step.get("number"),
                "status": str(step.get("status") or ""),
                "conclusion": str(step.get("conclusion") or ""),
                "start": step_start,
                "end": step_end,
                "effective_end": step_effective_end,
                "duration": None if timestamp_error else step_duration,
                "timestamp_error": timestamp_error,
            })
        execution = seconds(started, effective_end)
        covered = sum(step["duration"] or 0 for step in steps)
        normalized.append({
            "name": str(raw.get("name") or "unnamed job"),
            "id": raw.get("id"),
            "status": str(raw.get("status") or ""),
            "conclusion": str(raw.get("conclusion") or ""),
            "created": created,
            "started": started,
            "completed": completed,
            "effective_end": effective_end,
            "queue": seconds(created, started),
            "execution": execution,
            "step_overhead": max(0, execution - covered) if execution is not None else None,
            "steps": steps,
            "url": raw.get("html_url") or "",
        })
    starts = [job["created"] for job in normalized if job["created"]]
    ends = [job["effective_end"] for job in normalized if job["effective_end"]]
    run_start = min(starts) if starts else parse_time(run.get("run_started_at")) or parse_time(run.get("created_at"))
    run_end = max(ends) if ends else parse_time(run.get("updated_at"))
    wall = seconds(run_start, run_end)
    completed_jobs = [job for job in normalized if job["effective_end"]]
    longest_queue = max(normalized, key=lambda j: j["queue"] if j["queue"] is not None else -1, default=None)
    longest_execution = max(normalized, key=lambda j: j["execution"] if j["execution"] is not None else -1, default=None)
    all_steps = [(job, step) for job in normalized for step in job["steps"] if step["duration"] is not None]
    longest_step = max(all_steps, key=lambda pair: pair[1]["duration"], default=None)
    tail = max(completed_jobs, key=lambda j: j["effective_end"], default=None)
    ordered_ends = sorted((job["effective_end"] for job in completed_jobs), reverse=True)
    tail_gap = seconds(ordered_ends[1], ordered_ends[0]) if len(ordered_ends) > 1 else wall
    overhead_job = max(normalized, key=lambda j: j["step_overhead"] if j["step_overhead"] is not None else -1, default=None)
    findings = []
    if longest_queue and longest_queue["queue"] is not None:
        findings.append(finding("Runner queue", longest_queue["name"], longest_queue["queue"], wall, "created_at → started_at", "direct"))
    if longest_execution and longest_execution["execution"] is not None:
        findings.append(finding("Job execution", longest_execution["name"], longest_execution["execution"], wall, "started_at → completed_at", "direct"))
    if longest_step:
        job, step = longest_step
        findings.append(finding("Step execution", f"{job['name']} / {step['name']}", step["duration"], wall, "step timestamps", "direct"))
    if tail and tail_gap and tail_gap >= 1:
        findings.append(finding("Parallel tail", tail["name"], tail_gap, wall, "gap between final and penultimate Job completion", "proxy"))
    if overhead_job and overhead_job["step_overhead"] and overhead_job["step_overhead"] >= 1:
        findings.append(finding("Uninstrumented Job time", overhead_job["name"], overhead_job["step_overhead"], wall, "Job execution minus summed Step durations", "proxy"))
    return {
        "repo": repo,
        "run_id": int(run["id"]),
        "attempt": int(run.get("run_attempt") or 1),
        "name": str(run.get("display_title") or run.get("name") or f"Run {run['id']}"),
        "workflow": str(run.get("name") or "Workflow"),
        "status": str(run.get("status") or ""),
        "conclusion": str(run.get("conclusion") or ""),
        "event": str(run.get("event") or ""),
        "url": str(run.get("html_url") or f"https://github.com/{repo}/actions/runs/{run['id']}/attempts/{run.get('run_attempt', 1)}"),
        "start": run_start,
        "end": run_end,
        "wall": wall,
        "jobs": sorted(normalized, key=lambda j: (j["created"] or now, j["name"])),
        "findings": findings,
    }


def finding(kind: str, subject: str, duration: float, wall: float | None, evidence: str, strength: str) -> dict[str, Any]:
    return {"kind": kind, "subject": subject, "duration": duration, "share": duration / wall if wall else None, "evidence": evidence, "strength": strength}


def bar(start: dt.datetime | None, end: dt.datetime | None, axis_start: dt.datetime, axis_end: dt.datetime, css: str, label: str) -> str:
    if not start or not end or end < start or axis_end <= axis_start:
        return ""
    total = (axis_end - axis_start).total_seconds()
    left = max(0, min(100, (start - axis_start).total_seconds() / total * 100))
    width = max(.18, min(100 - left, (end - start).total_seconds() / total * 100))
    title = html.escape(f"{label}: {minutes((end-start).total_seconds())} · {stamp(start)} → {stamp(end)}", quote=True)
    return f'<span class="bar {css}" style="left:{left:.4f}%;width:{width:.4f}%" title="{title}"></span>'


def job_timeline(run: dict[str, Any]) -> str:
    if not run["start"] or not run["end"] or run["end"] <= run["start"]:
        return '<p class="gap">No valid Job timestamps.</p>'
    rows = []
    for job in run["jobs"]:
        queue = bar(job["created"], job["started"], run["start"], run["end"], "queue", "Queue")
        execution = bar(job["started"], job["effective_end"], run["start"], run["end"], "execution incomplete" if not job["completed"] else "execution", "Execution")
        gap = '<span class="missing">timestamp gap</span>' if not job["created"] or (job["status"] != "queued" and not job["started"]) else ""
        job_name = html.escape(job["name"])
        job_label = f'<a href="{html.escape(job["url"], quote=True)}">{job_name}</a>' if job["url"] else job_name
        rows.append(f'''<div class="timeline-row">
          <div class="row-label"><b>{job_label}</b><small>{minutes(job["queue"])} queued · {minutes(job["execution"])} running</small></div>
          <div class="track">{queue}{execution}{gap}</div>
        </div>''')
    return ''.join(rows)


def step_details(run: dict[str, Any]) -> str:
    blocks = []
    for job in run["jobs"]:
        axis_start = job["started"] or job["created"]
        axis_end = job["effective_end"] or job["started"] or job["created"]
        step_rows = []
        if axis_start and axis_end and axis_end > axis_start:
            for step in job["steps"]:
                segment = bar(step["start"], step["effective_end"], axis_start, axis_end, "step incomplete" if not step["end"] else "step", step["name"]) if step["duration"] is not None else ""
                missing = '<span class="missing">invalid timestamp</span>' if step["timestamp_error"] else ('<span class="missing">timestamp gap</span>' if step["duration"] is None else "")
                step_rows.append(f'''<div class="timeline-row step-row"><div class="row-label"><b>{html.escape(step["name"])}</b><small>{minutes(step["duration"])}</small></div><div class="track">{segment}{missing}</div></div>''')
        if not step_rows:
            step_rows.append('<p class="gap">No Step timestamps returned by GitHub.</p>')
        job_name = html.escape(job["name"])
        job_label = f'<a href="{html.escape(job["url"], quote=True)}">{job_name}</a>' if job["url"] else job_name
        blocks.append(f'''<details open><summary><span>{job_label}</span><span>{minutes(job["execution"])} · uncovered {minutes(job["step_overhead"])}</span></summary><div class="step-axis"><span>Job start</span><span>Job end</span></div>{''.join(step_rows)}</details>''')
    return ''.join(blocks)


def finding_cards(run: dict[str, Any]) -> str:
    cards = []
    for item in run["findings"]:
        share = "—" if item["share"] is None else f"{item['share']:.0%} of wall time"
        cards.append(f'''<article class="finding"><div class="finding-type">{html.escape(item["kind"])}</div><strong>{html.escape(item["subject"])}</strong><div class="finding-number">{minutes(item["duration"])}</div><small>{share} · {html.escape(item["strength"])} evidence<br>{html.escape(item["evidence"])}</small></article>''')
    return ''.join(cards)


def render(runs: list[dict[str, Any]], generated: dt.datetime, api_calls: int) -> str:
    sections = []
    for run in runs:
        sections.append(f'''<section class="run" id="run-{run['run_id']}-{run['attempt']}">
<header class="run-head"><div><div class="eyebrow">FLIGHT RECORDER · RUN {run['run_id']} · ATTEMPT {run['attempt']}</div><h2>{html.escape(run['name'])}</h2><p>{html.escape(run['repo'])} / {html.escape(run['workflow'])} · {html.escape(run['event'])}</p></div><div class="run-clock"><span>Wall clock</span><b>{minutes(run['wall'])}</b><small>{stamp(run['start'])}<br>→ {stamp(run['end'])}</small></div></header>
<div class="statusline"><span class="pill">{html.escape(run['status'])}</span><span class="pill conclusion">{html.escape(run['conclusion'] or 'in progress')}</span><a href="{html.escape(run['url'], quote=True)}">Open on GitHub ↗</a></div>
<h3>Timing causes</h3><div class="findings">{finding_cards(run)}</div>
<div class="legend"><span><i class="queue"></i>Runner queue</span><span><i class="execution"></i>Job execution</span><span><i class="step"></i>Step</span><span><i class="incomplete"></i>Still running</span></div>
<h3>Workflow / shared wall clock</h3><div class="axis"><span>{stamp(run['start'])}</span><span>{stamp(run['end'])}</span></div><div class="timeline">{job_timeline(run)}</div>
<h3>Job recorders / local execution clock</h3><div class="details">{step_details(run)}</div>
</section>''')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Workflow Flight Recorder</title><style>{CSS}</style></head><body>
<main><header class="hero"><div><div class="eyebrow">GITHUB ACTIONS · TIMING FORENSICS</div><h1>Workflow<br><em>flight recorder</em></h1></div><p>Queue, execution, and every reported Step aligned to real wall clock. Timing evidence localizes where the minutes went; logs are required to prove semantic causes.</p></header>{''.join(sections)}
<footer>Generated {stamp(generated)} · {api_calls} GitHub API calls · incomplete bars are measured through generation time.</footer></main></body></html>'''


CSS = r'''
:root{--ink:#10243e;--paper:#f3f7fa;--panel:#fff;--line:#b8c8d5;--grid:#dce7ee;--queue:#f0a33a;--run:#167d9a;--step:#6949a8;--alert:#d84a3a;--muted:#617487}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:"Aptos","Segoe UI",sans-serif}main{max-width:1500px;margin:auto;padding:42px}.hero{display:grid;grid-template-columns:1.2fr 1fr;gap:60px;align-items:end;border-bottom:4px solid var(--ink);padding:28px 0}.hero h1{font-family:Georgia,serif;font-size:clamp(48px,8vw,112px);line-height:.78;letter-spacing:-.055em;margin:16px 0}.hero h1 em{color:var(--run);font-weight:400}.hero p{font-size:18px;line-height:1.55;max-width:620px}.eyebrow{font:700 12px ui-monospace,SFMono-Regular,Consolas,monospace;letter-spacing:.14em;color:var(--muted)}.run{margin:54px 0 90px}.run-head{display:grid;grid-template-columns:1fr auto;gap:28px;align-items:end}.run-head h2{font:700 clamp(28px,4vw,54px) Georgia,serif;margin:9px 0}.run-head p{color:var(--muted)}.run-clock{border-left:5px solid var(--queue);padding-left:18px;min-width:240px}.run-clock span,.run-clock small{display:block;color:var(--muted)}.run-clock b{font:700 38px ui-monospace,SFMono-Regular,Consolas,monospace}.statusline{display:flex;gap:9px;align-items:center;border-top:1px solid var(--line);padding-top:12px}.statusline a{margin-left:auto;color:var(--run);font-weight:700}.pill{background:var(--ink);color:#fff;border-radius:99px;padding:5px 11px;font:700 11px ui-monospace,monospace;text-transform:uppercase}.pill.conclusion{background:var(--run)}h3{font:700 13px ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase;margin:42px 0 12px}.findings{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px}.finding{background:var(--panel);border-top:4px solid var(--ink);padding:16px;min-height:175px}.finding-type{font:700 11px ui-monospace,monospace;color:var(--muted);text-transform:uppercase;margin-bottom:15px}.finding strong{display:block;min-height:44px}.finding-number{font:700 27px ui-monospace,monospace;color:var(--run);margin:10px 0}.finding small{color:var(--muted);line-height:1.4}.legend{display:flex;flex-wrap:wrap;gap:20px;margin-top:30px;color:var(--muted);font-size:12px}.legend i{display:inline-block;width:20px;height:8px;margin-right:6px}.legend .queue,.bar.queue{background:var(--queue)}.legend .execution,.bar.execution{background:var(--run)}.legend .step,.bar.step{background:var(--step)}.legend .incomplete,.bar.incomplete{background:repeating-linear-gradient(135deg,var(--alert) 0 6px,#f4a49b 6px 12px)}.axis,.step-axis{display:flex;justify-content:space-between;color:var(--muted);font:11px ui-monospace,monospace;margin-left:min(36%,420px);padding:0 4px 6px}.timeline{background:var(--panel);border:1px solid var(--line)}.timeline-row{display:grid;grid-template-columns:minmax(210px,36%) 1fr;min-height:52px;border-bottom:1px solid var(--grid)}.timeline-row:last-child{border-bottom:0}.row-label{padding:9px 12px;min-width:0}.row-label b{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:13px}.row-label a,summary a{color:inherit;text-decoration-color:var(--line);text-underline-offset:2px}.row-label small{color:var(--muted);font:11px ui-monospace,monospace}.track{position:relative;background:repeating-linear-gradient(90deg,transparent 0 calc(10% - 1px),var(--grid) calc(10% - 1px) 10%)}.bar{position:absolute;top:14px;height:23px;min-width:2px;box-shadow:0 0 0 1px rgba(16,36,62,.12) inset}.bar.step{top:15px;height:21px}.missing{position:absolute;left:8px;top:17px;color:var(--alert);font:700 11px ui-monospace,monospace}.details{display:grid;gap:8px}details{background:var(--panel);border:1px solid var(--line)}summary{display:flex;justify-content:space-between;gap:20px;cursor:pointer;padding:14px 16px;font-weight:700}summary span:last-child{color:var(--muted);font:12px ui-monospace,monospace}.step-row{min-height:48px}.step-axis{margin-left:36%;padding:5px 12px}.gap{padding:12px;color:var(--alert)}footer{border-top:4px solid var(--ink);padding:22px 0 60px;color:var(--muted);font:12px ui-monospace,monospace}@media(max-width:760px){main{padding:20px}.hero,.run-head{grid-template-columns:1fr}.timeline-row{grid-template-columns:1fr}.track{height:40px}.axis,.step-axis{margin-left:0}.findings{grid-template-columns:1fr}.run-clock{border-left:0;border-top:5px solid var(--queue);padding:12px 0 0}}
'''


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Visualize queue, Job, and Step timing for GitHub Actions attempts")
    parser.add_argument("targets", nargs="+", help="GitHub run URL(s), or numeric run ID(s) with --repo")
    parser.add_argument("--repo", help="OWNER/REPO for numeric run IDs")
    parser.add_argument("--output", "-o", type=Path, help="Output HTML path")
    args = parser.parse_args(argv)
    targets = [parse_target(value, args.repo) for value in args.targets]
    client = GitHub(token())
    runs = [collect(client, *target) for target in targets]
    output = args.output or Path("reports") / (f"workflow-forensics-{runs[0]['run_id']}.html" if len(runs) == 1 else "workflow-forensics.html")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(runs, dt.datetime.now(UTC), client.calls), encoding="utf-8")
    print(output)
    for run in runs:
        top = max(run["findings"], key=lambda item: item["duration"], default=None)
        if top:
            print(f"{run['repo']} run={run['run_id']} attempt={run['attempt']}: {top['kind']} — {top['subject']} — {minutes(top['duration'])}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
