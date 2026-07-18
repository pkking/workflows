# ci-effective-report — domain glossary

Terms load-bearing for the architecture. Sharpened inline during the design review (2026-06-30).

## Data sources behind one seam
- **Turso adapter** — queries the synced libSQL DB over HTTP (runs/jobs/steps/pr_metrics/pr_workflows). Primary (ADR-001): fast, no rate limit, date-based, multi-repo.
- **Local SQLite adapter** — reads `~/action-insight/etl/data/{repo}.db` directly via stdlib `sqlite3` (ADR-004). Same schema as Turso, same `query(sql)->list[dict]` seam. 0 network calls, seconds-scale; auto-detected when no Turso creds. Per-repo db file, so multi-repo = per-repo connect.
- **GitHub by-SHA adapter** — REST API, fetches runs by merged-PR SHA. Backup (ADR-001): PR-centric, has schedule interval.
- **GitHub by-date adapter** — REST API, fetches runs by creation date. Run-centric, single workflow. Merged into `ci_analyze.py` via `--success-only`/`--insights` mode (ADR-005); `workflow_runs_on_date.py` remains as the fetch primitive.

## Core model (the seam)
- **Run** — one workflow run. Core: id, workflow name, head sha, branch, status, conclusion, event, created_at, duration (minutes).
- **Job** — one job within a run. Core: id, run_id, name, status, conclusion, started_at, completed_at, duration.
- **Step** — one step within a job. Core: id, job_id, name, number, status, conclusion, started_at, completed_at, duration.
- Duration is normalized to minutes at ingestion (Turso stores seconds; GitHub returns timestamps).

## Pattern: core + extensions
- **core** — shared model + shared stats + shared writer + core sheets. Built once.
- **extension** — a per-method addition that plugs into the core. Known extensions:
  - pr_metrics / pr_workflows (Turso)
  - schedule interval + trigger type (by-SHA)
  - resource type from runner labels (by-SHA)
  - normalized job name (by-date)
  - multi-repo comparison 仓库对比 (Turso)
  - per-run / per-job detail sheets run_details / job_details (by-date)
  - step type (see below — candidate for its own module)
- **adapter** — a fetch path that populates the core model (+ its extensions) through one interface.
- **seam** — the interface between adapters and the analytics module: the typed core model. The interface is the test surface.

## Report schema
- **core sheets** (shared by all three): `job_stats`, `step_stats`.
- **scene-specific sheets** (not shared): `workflow_stats` (workflow-centric, A+B), `run_stats` + `run_details` + `job_details` (run-centric, by-date), `仓库对比` (multi-repo, Turso), `pr_stats` + `pr_details` (A+B, different PR computations).

## Workflow duration language
- **Workflow 执行记录** — 一个 workflow run 的一次 attempt。每次 rerun 产生新的执行记录，并按该 attempt 的 `run_started_at` 归属报告日期范围。
- **Workflow 实际 E2E** — 一条 Workflow 执行记录从最早 job 创建到最晚 job 完成的真实墙钟耗时，即 `max(job.completed_at) - min(job.created_at)`；没有可用 job 时间时回退到该 attempt 的 run 时间。_Avoid_: Attempt E2E
- **Workflow 排队耗时** — 一条 Workflow 执行记录内所有 job 排队耗时的最大值；单个 job 的排队耗时是 `job.started_at - job.created_at`。
- **Workflow 执行耗时** — 一条 Workflow 执行记录内所有 job 执行耗时的最大值；单个 job 的执行耗时是 `job.completed_at - job.started_at`。

## step type
- Classification of a step: 构建 / CI启动 / 执行测试 / 排除. Currently split — static JSON map `step-names.json` (Turso) vs LLM two-phase `--export-step-names`/`--step-types` (by-SHA). Candidate for a shared classifier module (review candidate 2).
