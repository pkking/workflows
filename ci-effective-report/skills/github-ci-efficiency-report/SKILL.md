---
name: github-ci-efficiency-report
description: Generate an Excel/HTML report of GitHub repository CI efficiency for a requested time period. Use when the user provides or asks for a GitHub repo and date range and wants workflow, job, step, pull request, queue time, CI duration, PR e2e, PR review-after-CI, duration bottleneck analysis, or hierarchical PR/workflow/job/step details exported to .xlsx/.html. Supports success-only duration analysis and automatic bottleneck insights.
---

# GitHub CI Efficiency Report

## Overview

Use this skill to collect GitHub Actions data for a repository over a date range, then produce an Excel workbook (and optionally an HTML insights report) with summary sheets and PR-level detail.

The primary script reads from a local SQLite DB or Turso (0 API calls) when available, falling back to the GitHub API. It supports a `--success-only` mode for clean duration analysis (only successful runs/jobs) and `--insights` for automatic bottleneck detection.

```bash
python3 ci-effective-report/ci_analyze.py \
  --repo OWNER/REPO \
  --from 2026-06-01 --to 2026-06-30 \
  --output ci-efficiency.xlsx
```

The script reads `GITHUB_TOKEN`/`GH_TOKEN` (API mode) or `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN` (Turso mode) or auto-detects local SQLite at `~/action-insight/etl/data/{repo}.db`. It requires `openpyxl` for Excel output.

### Data Source & Performance

- **Local SQLite (default)**: auto-detects `~/action-insight/etl/data/{owner-repo}.db`, 0 API calls, seconds-scale (ADR-004)
- **Turso DB**: via `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN`, 0 API calls, multi-repo (ADR-001)
- **GitHub API fallback**: via `GITHUB_TOKEN`, fetches runs/jobs/steps directly (ADR-003)
- Use `--db-path PATH` to explicitly specify a local SQLite file

## Required Inputs

- GitHub repository in `owner/name` form.
- Start and end dates (`--from`/`--to`, YYYY-MM-DD, default: last 30 days).
- Optionally a GitHub token (for API mode) or Turso credentials (for Turso mode).
- Output path, defaulting to `{repo}-ci-report-{from}_to_{to}.xlsx`.

## Modes

### Full efficiency report (default)
All runs (including failure/cancelled), with success-rate columns:
```bash
python3 ci-effective-report/ci_analyze.py --repo vllm-project/vllm-ascend --from 2026-06-01 --to 2026-06-30
```

### Success-only duration analysis (目的2)
Only successful runs/jobs enter duration stats; `--min-duration` excludes short lint-only runs; `--insights` adds an HTML bottleneck report:
```bash
python3 ci-effective-report/ci_analyze.py \
  --repo vllm-project/vllm-ascend --from 2026-06-16 --to 2026-06-30 \
  --workflow E2E --success-only --min-duration 10 --insights
```

## Output

### Excel workbook sheets (always generated unless `--no-excel`)

- `工作流统计`: one row per workflow name with run count, avg/P50/P90 duration, queue times, schedule cycle.
- `任务统计`: one row per workflow/job with job count, avg/P50/P90 duration and queue time, resource type.
- `步骤统计`: one row per step name with step type, count, avg/P50/P90 duration, success rate. Step types: 构建/CI启动/执行测试/排除 (regex fallback when `step-names.json` misses, ADR-005).
- `PR统计`: one row per merged PR with PR e2e time and review-after-CI time.
- `PR详情`: hierarchical rows: PR → workflow → job → step.

### HTML insights report (`--insights` only)

- Summary cards (run count, avg/P50/P90/max duration)
- Top 3 problems with evidence (queue bottleneck, critical-path job, step hotspot), color-coded by severity
- Statistics tables (job_stats, step_stats, preview 50 rows)

With `--success-only`, duration stats only include `conclusion == success` samples; `--min-duration N` additionally filters runs shorter than N minutes.

Use minutes for all duration fields.

## CLI Options

- `--repo OWNER/REPO` — repo to analyze (repeatable for multi-repo comparison)
- `--from / --to` — date range (YYYY-MM-DD, default: last 30 days)
- `--workflow NAME` — only analyze workflows whose name contains NAME (substring, case-insensitive, repeatable)
- `--success-only` — duration stats only count success runs/jobs/steps (目的2)
- `--min-duration N` — exclude runs shorter than N minutes (pairs with `--success-only`)
- `--insights` — additionally output an HTML bottleneck report
- `--db-path PATH` — local SQLite db file (no Turso creds needed)
- `--skip-steps` — skip step data for faster queries
- `--step-names PATH` — step classification JSON (default `step-names.json`)
- `--no-excel` — terminal output only
- `-o / --output` — custom output path


## Setup

```bash
python3 -m pip install openpyxl  # Excel output; requests only needed for Turso/API mode
```

Python 3.10+. The SQLite mode uses only the standard library (`sqlite3`), so no extra dependencies when reading local `.db` files.

## Interpretation Notes

- With `--success-only`, duration stats exclude failure/cancelled (truncated) samples — use this for clean duration analysis (目的2). Without it, all conclusions are included for a full picture including success rates (目的1/3).
- `--min-duration 10` excludes short lint-only runs that didn't trigger the full test matrix (bimodal workflows like vllm-ascend E2E).
- The `--insights` HTML report auto-detects the top 3 bottlenecks (queue, critical-path job, step hotspot) with verifiable evidence.
- GitHub Actions reruns are kept as separate run rows because they consume CI time.
- Data source priority: `--db-path` > Turso creds > auto-detect local SQLite > GitHub API.

For column definitions and edge cases, read `references/report-schema.md` and [ADR-005](../../../docs/decisions/adr-005-merge-ci-analysis-scripts.md).
