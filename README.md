# workflows

A collection of automation workflows for developer productivity — multi-agent analysis, repository distillation, and CI efficiency reporting.

## Projects

### 🔬 yt-obsidian — Multi-Agent YouTube → Obsidian Pipeline

Analyzes YouTube videos using a 4-agent challenge/consensus pattern and writes structured, Obsidian-ready notes (concepts, methodologies, and full trace logs).

- **Smart search** across views, date, rating, and relevance
- **Subtitle-first transcription** with Whisper fallback
- **4 specialized agents**: Concept Extractor, Methodology Analyst, Skeptic, Synthesizer
- **Full traceability**: JSON logs + Markdown trace files per stage

```bash
cd yt-obsidian
pip install -e .
yt-obsidian analyze "machine learning fundamentals" --vault ~/ObsidianVault
```

See [yt-obsidian/README.md](yt-obsidian/README.md) for full usage, CLI options, and architecture details.

---

### 📦 repo-distiller — Repository Distiller

Distills GitHub repositories into structured feature lists, architectural decisions, and bugfixes using AST parsing, Git history analysis, and multi-agent orchestration.

- AST-based code parsing (Python, TypeScript, JavaScript, Go, Java, Rust)
- Git history analysis for decision and bugfix extraction
- IaC (Infrastructure as Code) parsing
- Multi-agent orchestration with challenge/consensus pattern

```bash
cd repo-distiller
pip install -e .
repo-distiller distill https://github.com/owner/repo --output ./distilled
```

---

### 📊 ci-effective-report — GitHub CI Efficiency Report

Generates an Excel workbook with detailed CI/CD metrics — workflow stats, job stats, step classifications, PR e2e times, and hierarchical PR/workflow/job/step breakdowns.

#### Method A: Turso DB (Recommended)

Directly queries CI data from Turso DB — no GitHub API rate limits, instant analysis on 81万+ jobs / 164万+ steps.

```bash
# Single repo (default: vllm-ascend, last 30 days)
python3 ci-effective-report/ci_analyze.py

# Specify repo and date range
python3 ci-effective-report/ci_analyze.py \
  --repo vllm-project/vllm-ascend \
  --from 2026-05-01 --to 2026-05-23

# Multi-repo comparison
python3 ci-effective-report/ci_analyze.py \
  --repo vllm-project/vllm-ascend --repo modelscope/ms-swift \
  --from 2026-06-01 --to 2026-06-06

# Skip steps for faster queries
python3 ci-effective-report/ci_analyze.py --skip-steps

# List all available repos
python3 ci-effective-report/ci_analyze.py --list-repos
```

Requires `.env` with `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`.

**CLI options:**
- `--repo OWNER/REPO` — repo to analyze (can specify multiple for comparison)
- `--from / --to` — date range (YYYY-MM-DD, default: last 30 days)
- `--workflow NAME` — only analyze workflows whose name contains NAME (substring, case-insensitive; repeatable for several workflows). Matches the workflow **display name**; yaml-filename matching is not available in this DB-backed path (the `runs` table stores no workflow file path).
- `--skip-steps` — skip step-level data for faster queries
- `--step-names` — custom step category mapping JSON
- `--no-excel` — terminal output only
- `-o / --output` — custom output path

#### Method B: GitHub API

Fetches data directly from GitHub REST API — useful when Turso DB is unavailable.

```bash
# Estimate API calls first (optional)
export GITHUB_TOKEN=$(gh auth token)
python3 ci-effective-report/skills/github-ci-efficiency-report/scripts/github_ci_efficiency_report.py \
  --repo OWNER/REPO \
  --since 2026-06-01 \
  --until 2026-06-10 \
  --estimate-only

# Run the report (concurrent by default)
python3 ci-effective-report/skills/github-ci-efficiency-report/scripts/github_ci_efficiency_report.py \
  --repo OWNER/REPO \
  --since 2026-06-01 \
  --until 2026-06-10 \
  --output ci-efficiency-OWNER-REPO.xlsx \
  --concurrency 5

# Only analyze specific workflows (repeatable; substring, case-insensitive)
python3 ci-effective-report/skills/github-ci-efficiency-report/scripts/github_ci_efficiency_report.py \
  --repo OWNER/REPO --since 2026-06-01 --until 2026-06-10 \
  --workflow "build" --workflow "test" \
  --output ci-efficiency-OWNER-REPO.xlsx
```

Requires `GITHUB_TOKEN`, `GH_TOKEN` environment variable, or `--token` flag.

#### Generated Report

Both methods produce the same Excel workbook with these sheets:

| Sheet | Content |
|---|---|
| 仓库对比 | Multi-repo comparison summary (multi-repo mode only) |
| 工作流统计 | Run count, avg/P50/P90 duration per workflow |
| 任务统计 | Job-level duration, queue times, resource type classification |
| 步骤统计 | Step execution count, avg/P50/P90 duration, success rate, step type |
| PR 统计 | PR e2e time, review-after-CI time, workflow count |
| PR 详情 | Hierarchical tree: PRs → workflows → jobs → steps |

---

## Setup

Each sub-project is independently installable:

```bash
# yt-obsidian
pip install -e ./yt-obsidian

# repo-distiller
pip install -e ./repo-distiller

# ci-effective-report
pip install openpyxl requests  # for Excel output + Turso HTTP API
```

Python 3.10+ required for all projects.

## Environment Variables

| Variable | Used by | Description |
|---|---|---|
| `YOUTUBE_API_KEY` | yt-obsidian | YouTube Data API v3 key |
| `OPENAI_API_KEY` | yt-obsidian | Whisper API / agent LLM access |
| `TURSO_DATABASE_URL` | ci-effective-report (Turso mode) | Turso DB connection URL |
| `TURSO_AUTH_TOKEN` | ci-effective-report (Turso mode) | Turso DB auth token |
| `GITHUB_TOKEN` | ci-effective-report (API mode) | GitHub API access for Actions metadata |

## License

MIT
