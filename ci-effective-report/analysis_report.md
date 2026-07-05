# Codebase Analysis Report: `ci-effective-report`

This report provides a comprehensive review of the `ci-effective-report` codebase, detailing issues and suggested fixes across four main domains: Code Quality, Performance, Architecture, and Functional Completeness.

> **Implementation Status (2026-07-05)**: This analysis drove the fixes in PR #12. 8 of 14 issues are addressed there (1.1, 1.2, 1.4, 2.1, 2.2, 2.3, 4.1, 4.2); 1 is partially aligned (3.1); 5 remain open (1.3, 2.4, 3.2, 3.3, 4.3). Each fixed issue is marked with a `# Fix N.N` comment in `ci_analyze.py`. Line numbers below refer to the pre-fix state.

---

## 1. Code Quality

### Issue 1.1: Incorrect Aggregation Loop in `analyze_workflow_stats`
* **Location**: `ci_analyze.py` (Lines 283–294 & 304–311)
* **Description**: The function calculates workflow-level statistics such as run count (`"运行次数"`), average E2E duration (`"平均E2E(分钟)"`), and queue times. However, the loop iterates over individual *jobs* instead of *runs*:
  ```python
  for j in jobs:
      run = run_map.get(j["run_id"])
      if not run:
          continue
      wf = run["name"]
      dur = sec_to_min(j.get("duration_seconds"))
      if dur is not None:
          wf_groups[wf]["durations"].append(dur)
      q_dur = sec_to_min(j.get("queue_duration_seconds"))
      if q_dur is not None:
          wf_groups[wf]["queues"].append(q_dur)
  ```
  If a workflow run contains 5 jobs, the length of `durations` increases by 5. Thus, the run count (`len(durs)`) reflects the job count rather than the run count. Similarly, the average E2E duration calculates the average of individual job durations rather than the total run duration.
* **Suggested Fix**: Refactor the aggregation logic to perform run-level aggregation (durations/events) separately from job-level aggregation (queues):
  ```python
  def analyze_workflow_stats(runs, jobs):
      run_map = {r["id"]: r for r in runs}
      wf_groups = defaultdict(lambda: {"durations": [], "queues": [], "events": defaultdict(int)})

      # 1. Aggregate run-level metrics first (runs/events)
      for run in runs:
          wf = run["name"]
          dur = sec_to_min(run.get("duration_seconds"))
          if dur is not None:
              wf_groups[wf]["durations"].append(dur)
          wf_groups[wf]["events"][run.get("event", "unknown")] += 1

      # 2. Aggregate job-level metrics (queues)
      for j in jobs:
          run = run_map.get(j["run_id"])
          if not run:
              continue
          wf = run["name"]
          q_dur = sec_to_min(j.get("queue_duration_seconds"))
          if q_dur is not None:
              wf_groups[wf]["queues"].append(q_dur)
  ```

### Issue 1.2: Environment Variables Usability Bug
* **Location**: `ci_analyze.py` (Lines 735–740)
* **Description**: The configuration loading logic only queries values parsed from a physical `.env` file via a custom dictionary:
  ```python
  env = load_env(ENV_FILE)
  db_url = env.get("TURSO_DATABASE_URL")
  auth_token = env.get("TURSO_AUTH_TOKEN")
  ```
  It does not check standard environment variables (`os.environ`). This causes execution failures in CI/CD pipelines or environments where variables are exported directly to the shell.
* **Suggested Fix**: Fall back to `os.getenv` or `os.environ` if variables are missing from the parsed `.env` file.
  ```python
  db_url = env.get("TURSO_DATABASE_URL") or os.getenv("TURSO_DATABASE_URL")
  auth_token = env.get("TURSO_AUTH_TOKEN") or os.getenv("TURSO_AUTH_TOKEN")
  ```

### Issue 1.3: Zero-Duration Step Filtering Bug
* **Location**: `workflow_runs_on_date.py` (Lines 185–187)
* **Description**: Steps with a duration of `0.0` minutes are filtered out:
  ```python
  for s in j.steps:
      if s.duration_min is None or s.duration_min <= 0:
          continue
  ```
  Steps that complete instantly (e.g., cached actions, setup steps, or immediate failures) have a duration of `0.0`. Excluding them hides failures and distorts step success rates and execution counts.
* **Suggested Fix**: Only skip steps if their duration is `None`.
  ```python
  for s in j.steps:
      if s.duration_min is None:
          continue
  ```

### Issue 1.4: Sorting Type Comparison Bug and Crash Risks
* **Location**: `ci_analyze.py` (Line 499 & Lines 537–539)
* **Description**:
  1. Steps are sorted using `key=lambda x: x.get("number", 0)`. If `"number"` is present but `None` in the database, `x.get("number", 0)` evaluates to `None` instead of `0`. Sorting a list containing `None` and integers raises a `TypeError` in Python 3.
  2. List comprehensions in `analyze_comparison` convert values using `float()` without exception handling, risking runtime crashes on malformed/empty string fields.
* **Suggested Fix**:
  1. Enforce integer defaults for sorting keys even when they evaluate to `None`:
     ```python
     key=lambda x: x.get("number") if x.get("number") is not None else 0
     ```
  2. Protect type conversions with robust utility functions or handlers.

---

## 2. Performance

### Issue 2.1: Silent Data Truncation Risk in Database Queries
* **Location**: `ci_analyze.py` (Lines 130–152, 170–173, 208–209)
* **Description**: Turso DB limits return result sets to 5,000 rows. The batch size for fetching jobs is set to 5,000 `run_ids`. Since each run contains multiple jobs, querying jobs for 5,000 runs yields significantly more than 5,000 rows, causing Turso to silently truncate results. Similar truncation risks affect steps (batched at 500 `job_ids`) and PR-workflows (batched at 5,000 `pr_metric_ids`).
* **Suggested Fix**: 
  - *Option A (Database JOIN/Subquery Optimization - Recommended)*: Push the filtering to SQLite/Turso using subqueries or JOINs. Instead of querying run IDs in Python and executing chunked queries, run a single query using subqueries:
    ```sql
    SELECT id, run_id, name, status, conclusion, created_at, started_at, completed_at, html_url, queue_duration_seconds, duration_seconds 
    FROM jobs 
    WHERE run_id IN (
        SELECT id FROM runs 
        WHERE repo_id IN ({repo_id_list}) 
        AND date >= '{date_from}' AND date < '{date_to_next}'
        {wf_clause}
    )
    ```
    This eliminates data truncation risk and reduces network latency by avoiding multiple round-trips.
  - *Option B (Chunk Reduction)*: If Python-side chunking is kept, reduce batch sizes to guarantee result counts stay safely below 5,000 rows:
    * **Jobs**: batch size of `500` `run_ids` (typically ~2,500 jobs).
    * **Steps**: batch size of `250` `job_ids` (typically ~2,000 steps).
    * **PR-workflows**: batch size of `1000` `pr_metric_ids`.

### Issue 2.2: Inefficient Index-Disabling Date Range Queries
* **Location**: `ci_analyze.py` (Lines 139–141 & 197–198)
* **Description**: Date range filters use `LIKE` and `OR` wildcards on string-based date columns:
  ```python
  AND (date LIKE '{date_from}%' OR date LIKE '{date_to}%' 
       OR (date >= '{date_from}' AND date <= '{date_to}'))
  ```
  This combination prevents the database query planner from utilizing index range scans, forcing full table scans on `runs` (~190,000 rows) and `pr_metrics` (~1,340 rows).
* **Suggested Fix**: Compute the exclusive next-day boundary in Python and perform a clean range scan using standard inequalities:
  ```python
  # Compute exclusive next day boundary
  from datetime import datetime, timedelta
  date_to_next = (datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
  # Use range scan in SQL
  query = f"AND date >= '{date_from}' AND date < '{date_to_next}'"
  ```

### Issue 2.3: Redundant DB Fetching and Python-Side Filtering
* **Location**: `ci_analyze.py` (Lines 702–710)
* **Description**: When a workflow pattern is specified, the script fetches all repository PR metrics and associated workflow links, only to filter them in Python against the filtered `run_ids`. This transfers large volumes of irrelevant records across the network.
* **Suggested Fix**: Perform database-side filtering. Fetch only those PR-workflow links and PR metrics that match the filtered `run_ids` using subqueries or JOINs.

### Issue 2.4: Excel In-Memory Handling Bloat
* **Location**: `ci_analyze.py` (Lines 576–586)
* **Description**: The script uses `openpyxl.Workbook()` in default in-memory mode. When generating reports for large repositories, sheets like `PR详情` contain hundreds of thousands of cells. Default in-memory mode stores all cells as Python objects, consuming gigabytes of RAM and risking Out-Of-Memory (OOM) crashes.
* **Suggested Fix**: Configure `openpyxl` to use `write_only=True` streaming mode. This streams worksheet contents directly to disk, keeping the memory footprint flat.

---

## 3. Architecture

### Issue 3.1: Alignment with Architecture Decision Records (ADRs)
* **ADR-001 (Turso DB based CI analysis)**:
  * *Alignment*: The primary module `ci_analyze.py` successfully implements SQL queries against the Turso database to bypass GitHub rate limits. The date-centric adapter (`workflow_runs_on_date.py`) is designed as a REST-based, run-centric adapter (one of three adapters behind the seam defined in `CONTEXT.md`), not a violation of ADR-001.
* **ADR-002 (Topic Researcher as pi Subagent Chain)**:
  * *Alignment*: ADR-002 applies exclusively to the Topic Researcher agent chain. It does not govern the structure of `ci-effective-report`. Therefore, ADR-002 is out of scope.
  - *Sub-project boundary constraints*: The repository layout guidelines in `AGENTS.md` require each sub-project to be independently installable and self-contained. The dynamic path injection in `workflow_runs_on_date.py` (see Issue 3.2) violates these modularity guidelines.

### Issue 3.2: Dynamic Path Injection Violation
* **Location**: `workflow_runs_on_date.py` (Lines 28–31)
* **Description**: The module dynamically inserts a path into `sys.path` to import files from a metadata `skills/` folder:
  ```python
  SCRIPT_DIR = Path(__file__).parent
  SKILL_SCRIPTS = SCRIPT_DIR / "skills" / "github-ci-efficiency-report" / "scripts"
  sys.path.insert(0, str(SKILL_SCRIPTS))
  from github_ci_efficiency_report import GitHubClient, WorkflowRunInfo, JobInfo, ...
  ```
  This dynamic path manipulation violates architectural boundaries and couples the sub-project to metadata folders.
* **Suggested Fix**: Move the shared clients and data models out of metadata/skills into a common, importable package or local module, in alignment with `AGENTS.md` sub-project guidelines.

### Issue 3.3: Missing Shared Seam and Core Modules
* **Location**: Throughout the codebase
* **Description**: The "three adapters behind one seam" pattern described in `CONTEXT.md` is not realized:
  - There are no shared, typed core models. `ci_analyze.py` manipulates raw dictionaries directly, whereas other adapters use dataclasses.
  - Algorithms for calculating statistics (e.g., averages, percentiles) and Excel writing logic are duplicated across scripts, causing code bloat.
  - Business rules are inconsistent: step duration thresholds differ across adapters (e.g., `>= 3` min in SHA-centric vs `> 0` min in date-centric vs no filter in Turso).
* **Suggested Fix**: Extract calculations, Excel writing logic, and models into a shared core module. Enforce consistent filtering parameters across all three adapters.

---

## 4. Functional Completeness

### Issue 4.1: PR E2E Duration Calculation Bug
* **Location**: `ci_analyze.py` (Lines 406–407 & 454–455)
* **Description**: `"PR E2E(分钟)"` is populated using the active CI execution duration (`ci_duration_seconds`) instead of calculating the actual elapsed PR lead time (`merged_at - created_at`):
  ```python
  "PR E2E(分钟)": sec_to_min(ci_dur) if ci_dur else None,
  ```
  This skews the PR E2E reports, representing only the CI run time instead of the overall PR lifecycle.
* **Suggested Fix**: Compute the duration between `merged_at` and `created_at` in minutes.

### Issue 4.2: Schedule Cycle (调度周期) Logic Bug
* **Location**: `ci_analyze.py` (Line 311)
* **Description**: `"调度周期(分钟)"` calculates the difference between the longest and shortest execution durations:
  ```python
  "调度周期(分钟)": round(max(durs) - min(durs), 3) if durs else 0,
  ```
  This is a mathematical bug. The schedule cycle should represent the frequency/interval of consecutive runs. In comparison, `github_ci_efficiency_report.py` implements a parser `cron_to_interval_minutes` to resolve interval rates from cron expressions.
* **Suggested Fix**: Parse the scheduling cycle based on timestamps of consecutive runs or cron analysis.

### Issue 4.3: Output Schema Mismatches
* **Location**: `workflow_runs_on_date.py`
* **Description**: The worksheet produced by the date-centric adapter is missing the `"步骤类型"` (Step Type) column, which is present in reports generated by other adapters.
* **Suggested Fix**: Introduce the static step type mapping (or a shared step classifier) into `workflow_runs_on_date.py` to ensure schema consistency.
