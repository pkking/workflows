---
name: github-ci-efficiency-report
description: Generate an Excel report of GitHub repository CI efficiency for a requested time period. Use when the user provides or asks for a GitHub repo and date range and wants workflow, job, pull request, queue time, CI duration, PR e2e, PR review-after-CI, or hierarchical PR/workflow/job/step details exported to .xlsx while minimizing GitHub API calls.
---

# GitHub CI Efficiency Report

## Overview

Use this skill to collect merged PRs and GitHub Actions data for a repository over a date range, then produce an Excel workbook with summary sheets and PR-level detail.

Prefer the bundled script unless the user explicitly asks for a custom implementation:

```bash
python3 scripts/github_ci_efficiency_report.py \
  --repo OWNER/REPO \
  --since YYYY-MM-DD \
  --until YYYY-MM-DD \
  --output ci-efficiency.xlsx \
  --concurrency 5
```

The script reads `GITHUB_TOKEN` or `GH_TOKEN`; pass `--token` only when the user provides a token for this run. It requires `openpyxl`.

### Performance Features

- **Concurrent API requests**: `--concurrency N` (default: 5) parallelizes PR, run, and job fetching
- **API call estimation**: `--estimate-only` previews total API calls before running
- **Rate limit awareness**: warns when remaining API quota drops below 100
- **Resilient execution**: individual PR/run failures emit warnings but don't abort the report
- **Progress reporting**: phased summary with elapsed time and requests/sec

## Required Inputs

Collect these values if they are missing:

- GitHub repository in `owner/name` form.
- Start and end dates for the statistics period.
- GitHub token with access to the repo and Actions metadata. For private repos, use a token with repo read access. For public repos, unauthenticated requests are too rate-limited for this report, so still ask for a token.
- Output path, defaulting to `ci-efficiency-OWNER-REPO-YYYY-MM-DD-to-YYYY-MM-DD.xlsx`.

## Output Workbook

Create one `.xlsx` workbook with these sheets:

- `workflow_stats`: one row per workflow name with run count, average duration, p50 duration, and p90 duration.
- `job_stats`: one row per workflow/job name with job count, average/p50/p90 duration, and average/p50/p90 queue time. Queue time is `job.started_at - job.created_at` when GitHub returns both fields.
- `step_stats`: one row per unique step name with step type (构建/CI启动/执行测试), execution count, average/p50/p90 duration, and success rate. Step type classification rules:
  - **构建**: 下载代码、下载依赖、编译、安装、checkout、cache、setup python 等
  - **CI启动**: Set up job、Initialize containers、以及非构建非测试的所有步骤
  - **执行测试**: 名称包含 test/e2e/mypy/pre-commit/linkcheck 等测试步骤
  - **排除**（不计入统计）: Post xxx 清理步骤、Stop containers、Complete job
  Step type classification is a two-phase process:
  1. Run with `--export-step-names step-names.json` to export unique step names
  2. Feed the JSON to an LLM to fill in types, then pass back via `--step-types step-names.json`
  Without `--step-types`, the type column will be blank.
- `pr_stats`: one row per merged PR with PR e2e time and review-after-CI time, plus summary rows. PR e2e time is `merged_at - created_at`. Review-after-CI time is `merged_at - latest completed workflow run time`.
- `pr_details`: hierarchical rows. Each PR is a top-level row, workflow runs are child rows, jobs are child rows under workflows, and steps are child rows under jobs.

Use minutes for all duration fields unless the user requests another unit.

## API Efficiency Rules

Use the fewest calls that still preserve required detail:

1. Search merged PRs with one date-bounded query: `repo:OWNER/REPO is:pr is:merged merged:SINCE..UNTIL`.
2. Fetch each PR once for exact `merged_at`, `created_at`, head SHA, refs, and author.
3. Fetch workflow runs once per unique PR head SHA and cache by SHA.
4. Fetch jobs once per workflow run and cache by run ID. Job responses include steps, so do not make separate step calls.
5. Warn the user to split the date range if the search result exceeds GitHub Search's 1000-result window.

For very large repositories, offer `--max-prs` for a sample run or split the period by week/month and combine outputs later.

## Running The Script

From the skill directory:

```bash
export GITHUB_TOKEN=...
python3 scripts/github_ci_efficiency_report.py \
  --repo pkking/action-insight \
  --since 2026-05-01 \
  --until 2026-05-22 \
  --output ci-efficiency-pkking-action-insight.xlsx
```

If `openpyxl` is missing, install it in the active environment:

```bash
python3 -m pip install openpyxl
```

Use `--sleep 0.2` if the repository is large and secondary rate limits occur.

Use `--concurrency N` to control parallelism (default: 5). Higher values speed up execution but increase the risk of secondary rate limits.

Use `--workflow NAME` (repeatable) to restrict the report to workflow runs whose **display name OR yaml file path** contains `NAME` (case-insensitive substring). So `--workflow build` matches a workflow named "Build" or whose file is `build.yml`. Runs that don't match are dropped before job/schedule fetching, so it also cuts API usage (at the cost of one extra call per unique workflow to resolve its file path). PRs with no matching workflows are omitted from the output.

Use `--estimate-only` to preview estimated API calls before running the full report.

## Interpretation Notes

- PR "submit" time is the PR `created_at` timestamp, not the first commit time, to avoid extra per-PR commit API calls.
- CI completion time is the latest completed workflow run associated with the PR head SHA.
- Review-after-CI can be negative if a workflow completes after merge; preserve the signed value because it exposes that ordering.
- GitHub Actions reruns are kept as separate workflow run rows because they consume CI time and affect PR readiness.

For column definitions and edge cases, read `references/report-schema.md`.
