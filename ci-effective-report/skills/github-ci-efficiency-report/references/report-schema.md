# Report Schema

## `workflow_stats`

One row per workflow name.

- `workflow`: GitHub Actions workflow run name.
- `run_count`: completed or non-completed runs found for merged PR head SHAs.
- `avg_duration_min`, `p50_duration_min`, `p90_duration_min`: duration from `run_started_at` to `updated_at`; falls back to `created_at` when `run_started_at` is absent.

## `job_stats`

One row per `workflow / job` pair.

- `job_count`: number of job executions.
- Duration metrics: `completed_at - started_at`.
- Queue metrics: `started_at - created_at`. If GitHub omits `created_at`, queue metrics are blank.

## `step_stats`

One row per unique step name across all CI runs. Steps classified as "排除" are excluded.

- `步骤名称`: the step name as reported by GitHub Actions.
- `步骤类型`: one of `构建` (下载代码/依赖、编译、安装、checkout、cache 等), `CI启动` (Set up job、Initialize containers、非构建非测试步骤), `执行测试` (test/e2e/mypy/pre-commit 等). Steps marked "排除" (Post xxx 清理、Stop containers、Complete job) are omitted.
- `执行次数`: total number of times this step was executed.
- Duration metrics: `completed_at - started_at` in minutes.
- `成功率`: ratio of steps with `conclusion == "success"` to total executions.

## `pr_stats`

One row per merged PR plus summary rows.

- `pr_e2e_min`: `merged_at - created_at`.
- `ci_completed_at`: latest `updated_at` among completed workflow runs for the PR head SHA.
- `review_after_ci_min`: `merged_at - ci_completed_at`.

## `pr_details`

Hierarchical sheet with one row per PR, workflow run, job, and step.

- `level`: `PR`, `WORKFLOW`, `JOB`, or `STEP`.
- PR columns repeat on child rows so the sheet can be filtered without losing context.
- Workflow, job, and step columns are populated at their corresponding level and lower child levels.

## API Call Model

Approximate calls:

- 1 to N calls for merged PR search pages.
- 1 call per PR for exact pull request metadata.
- 1 call per unique PR head SHA for workflow runs.
- 1 call per workflow run for jobs and embedded steps.

This intentionally avoids fetching PR commits, reviews, timeline events, or check suite details unless a user asks for additional metrics.
