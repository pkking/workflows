# GitHub Workflow Duration Report — Implementation Plan

**Status**: In progress  
**Date**: 2026-07-18  
**Decisions**: [ADR-006](../decisions/adr-006-root-level-github-workflow-duration-skill.md), [ADR-007](../decisions/adr-007-github-workflow-duration-report-model.md)

## Goal

Move `github-ci-efficiency-report` to the repository root and make it a self-contained GitHub API skill that generates an auditable Excel report for Workflow, Run attempt, Job, and Step duration analysis. Database, Turso, PR lifecycle, multi-repo database comparison, and HTML reporting remain outside this skill.

This plan covers feature development only. Creating the repository's real `.github-ci-efficiency.yaml` and generating a production report for a real date range happen after the feature is complete and are not part of this implementation plan.

## Target layout

```text
.agents/skills/github-ci-efficiency-report/
├── SKILL.md
├── pyproject.toml
├── uv.lock
├── agents/openai.yaml
├── references/
│   ├── report-schema.md
│   └── repositories.example.yaml
└── scripts/
    └── github_workflow_duration_report.py
```

The old `ci-effective-report/.agents/skills/github-ci-efficiency-report/` directory and `ci-effective-report/workflow_runs_on_date.py` are removed without compatibility wrappers. README and tests move to the root-level entrypoint.

## Inputs

Two mutually exclusive target modes:

1. `--config PATH`, defaulting to root `.github-ci-efficiency.yaml` when no target arguments are provided.
2. `--repo OWNER/NAME` plus one or more exact `--workflow NAME` arguments.

YAML shape:

```yaml
defaults:
  min_e2e_minutes: 10

repositories:
  - repo: vllm-project/vllm-ascend
    comparison_group: vllm
    workflows:
      - name: E2E
        comparison_name: E2E
        min_e2e_minutes: 10
```

Rules:

- Workflow display names match exactly, case-insensitively.
- Each repo supports multiple workflows.
- Different workflow IDs remain separate rows even when their display names match.
- Missing `comparison_group` falls back to GitHub owner.
- Missing `comparison_name` falls back to workflow name.
- Minimum E2E precedence: CLI > workflow YAML > YAML defaults > 10 minutes.
- Different thresholds inside a comparison group are allowed but visibly marked.
- `--from/--to` are inclusive local dates. The default timezone is the current user timezone; `--timezone` makes it reproducible.

## Domain model and metrics

One Workflow execution record is one run attempt. Rerun attempts count separately and enter the reporting range by their own `run_started_at`.

Per attempt:

```text
Workflow actual E2E
= max(job.completed_at) - min(job.created_at)

Workflow queue duration
= max(job.started_at - job.created_at)

Workflow execution duration
= max(job.completed_at - job.started_at)
```

Actual E2E falls back to `run.updated_at - run.run_started_at` only when Job timestamps are unavailable. The three metrics are independent and are not additive.

Workflow aggregation:

- Execution count includes all completed attempts.
- Success rate is `success / (success + failure)`.
- Cancelled and skipped attempts are counted but excluded from the success-rate denominator.
- Duration avg/P50/P90 use successful attempts meeting the effective workflow E2E threshold.
- Incomplete attempts remain in Run details and are excluded from every aggregation denominator.

Job aggregation:

- Key: repo + workflow ID + raw Job name.
- Normalized Job name is informational only.
- Success rate is `success / (success + failure)`.
- Queue duration includes successful and failed Jobs.
- Execution duration includes successful Jobs only.
- Risk sort: execution P90, queue P90, failure rate, execution count — descending.

Step aggregation:

- Key: repo + workflow ID + raw Job name + Step name.
- Steps have no queue metric.
- Success rate is `success / (success + failure)`.
- Execution duration includes successful Steps only.
- Risk sort: execution P90, failure rate, execution count — descending.

P50/P90 use Excel `PERCENTILE.INC`-equivalent inclusive linear interpolation. Calculations use unrounded seconds; Excel displays minutes to one decimal. Missing timestamps and negative durations remain blank and are excluded, never coerced to zero.

## Workbook

The skill generates Excel only, by default:

```text
reports/github-workflow-duration-{from}_to_{to}.xlsx
```

Sheets:

1. `报告信息` — inputs, timezone, UTC boundaries, sample rules, completeness, API/cache counts, errors, generation time.
2. `指标定义` — definitions and sample rules for every metric.
3. `Workflow统计` — adjacent comparison rows grouped by comparison group/name, then repo/workflow/ID.
4. `Run明细` — one row per attempt, including critical queue/execution Jobs and exclusion reason.
5. `Job统计` — queue/execution distributions and success/failure quality signals.
6. `Step统计` — execution distributions and success/failure quality signals.

No baseline, delta, or change-rate columns are calculated. Related Workflow rows are made adjacent for direct comparison.

## GitHub API and recovery

Authentication precedence:

```text
GITHUB_TOKEN > GH_TOKEN > gh auth token
```

There is no `--token` argument.

Because attempts are assigned by their own start time, the collector scans each exact workflow ID's visible run history, expands `run_attempt`, and fetches attempt-specific Jobs/Steps. This includes an old parent run rerun during the requested period.

Cache:

- Location: `.cache/github-ci-efficiency/`.
- Completed attempt Jobs/Steps are reusable indefinitely.
- Workflow and run list pages have a 15-minute TTL.
- Queued/in-progress data is refreshed on every run.
- Corrupt cache entries are discarded and fetched again.
- `--refresh` bypasses cache.
- Rate limits automatically wait until reset and resume.

Any unrecovered API gap blocks an official workbook. `--allow-partial` explicitly permits a `.partial.xlsx` workbook with completeness warnings on the filename and report sheets.

## Runtime

- Skill-local environment: `.agents/skills/github-ci-efficiency-report/.venv/`.
- Dependency metadata: `pyproject.toml + uv.lock`.
- Missing dependencies with uv available: run `uv sync` and re-exec with the skill Python.
- uv unavailable: print dependency guidance and exit; do not modify system Python.
- mise is not supported.

## Implementation sequence

1. Create root-level self-contained skill and single public CLI.
2. Implement YAML/CLI validation, timezone boundaries, exact workflow resolution, attempt expansion, caching, rate-limit waiting, and strict completeness.
3. Implement Workflow/Run/Job/Step aggregations and the six-sheet workbook.
4. Generate and commit `uv.lock`.
5. Remove legacy skill and by-date script; update README, tests, and `.gitignore`.
6. Run unit tests, CLI/config validation tests, cache/retry tests, and fixture-based workbook validation in temporary directories.

## Out of scope until feature completion

- Do not create the repository-root `.github-ci-efficiency.yaml` with real project targets.
- Do not generate the 2026-07-01 through 2026-07-17 production report.
- Do not begin production GitHub API collection for the requested repositories/workflows.

## Acceptance criteria

- Root skill has no runtime import from `ci-effective-report`.
- Exact workflow matching never silently selects E2E-Light/E2E-Full for E2E.
- Same-name workflow IDs are separate rows.
- Every rerun attempt is a distinct Run detail and execution count sample.
- A June parent run rerun on July 2 belongs to the July report.
- Workflow E2E spans earliest Job creation to latest Job completion for that attempt.
- Job queue is `started_at - created_at`; Step has no queue metric.
- Workflow threshold affects only Workflow duration distributions.
- Statistics reproduce `PERCENTILE.INC`; Excel shows one decimal minute values.
- Related repositories/workflows are adjacent, with threshold-comparability warnings.
- API gaps cannot silently produce an official report.
- Cache and uv environment are ignored by git, and a cached rerun resumes without duplicate API work.
