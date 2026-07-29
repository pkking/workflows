---
name: github-ci-efficiency-report
description: Generate a run-centric GitHub Actions workflow duration Excel report from the GitHub API. Use for repository/workflow comparisons, rerun-attempt-aware E2E, queue and execution percentiles, and auditable Workflow/Run/Job/Step statistics.
---

# GitHub Workflow Duration Report

Use this skill to analyze exact workflow display names over a user-timezone date range. It uses the GitHub REST API only; SQLite, Turso, PR lifecycle analysis, and HTML output are outside this skill.

## Run

The public entrypoint is:

```bash
python3 .agents/skills/github-ci-efficiency-report/scripts/github_workflow_duration_report.py \
  --from 2026-07-01 --to 2026-07-17
```

It reads `.github-ci-efficiency.yaml` from the repository root by default. Alternatively:

```bash
python3 .agents/skills/github-ci-efficiency-report/scripts/github_workflow_duration_report.py \
  --repo vllm-project/vllm-ascend --workflow E2E \
  --from 2026-07-01 --to 2026-07-17
```

`--config` and `--repo` are mutually exclusive. `--workflow` is repeatable in CLI mode and matches the workflow display name exactly, case-insensitively.

The script obtains authentication from `GITHUB_TOKEN`, then `GH_TOKEN`, then `gh auth token`. It never accepts a token argument. If dependencies are missing and uv is installed, it automatically runs `uv sync` in this skill and re-executes itself with the skill-local `.venv`. Without uv, it prints the missing dependencies and exits.

## Configuration

Copy `references/repositories.example.yaml` to `.github-ci-efficiency.yaml`. Each repository may contain several workflows. Workflow-specific `min_e2e_minutes` defaults to 10; CLI `--min-e2e-minutes` overrides all configured values.

Comparison rows are adjacent by `comparison_group` and `comparison_name`; no baseline or change-rate calculation is performed. Different thresholds are allowed and visibly marked as only approximately comparable.

## Metrics

- One workflow attempt is one Workflow execution record. Reruns count separately and are assigned to the reporting range by their own `run_started_at` in the report timezone.
- Actual Workflow E2E: latest job completion minus earliest job creation within that attempt; run timestamps are a fallback when job timestamps are unavailable.
- Workflow queue duration: maximum `job.started_at - job.created_at` within the attempt.
- Workflow execution duration: maximum `job.completed_at - job.started_at` within the attempt.
- These three metrics are independent and are not additive.
- Workflow duration distributions use successful attempts meeting the workflow E2E threshold. Job and Step tables use every completed attempt and are not threshold-filtered.

Read `references/report-schema.md` for exact workbook columns and sample rules.

## Outputs and recovery

The default workbook is `reports/github-workflow-duration-{from}_to_{to}.xlsx`. Raw API responses are cached under `.cache/github-ci-efficiency/`; completed attempt data is reusable, list pages have a 15-minute TTL, and `--refresh` bypasses cache. Rate limits are waited out automatically.

Any unrecovered API gap blocks the official report. Use `--allow-partial` only when a clearly marked partial workbook is acceptable.

For root-cause follow-up on selected Run URLs, invoke `github-workflow-forensics`; it renders queue, parallel Job, and nested Step timelines for each attempt.
