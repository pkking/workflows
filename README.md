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

**SQLite 直读模式**（ADR-004）：无 Turso 凭证时，自动检测 `~/action-insight/etl/data/{owner-repo}.db` 本地 SQLite 文件直读（0 网络调用、秒级分析）。也可用 `--db-path` 显式指定 db 文件：

```bash
# 自动检测本地 db（无需凭证）
python3 ci-effective-report/ci_analyze.py --repo vllm-project/vllm-ascend

# 显式指定 db 文件
python3 ci-effective-report/ci_analyze.py --db-path ~/action-insight/etl/data/vllm-project-vllm-ascend.db
```

数据源优先级：`--db-path` 显式 SQLite > Turso 凭证 > 自动检测本地 db 目录。

**CLI options:**
- `--repo OWNER/REPO` — repo to analyze (can specify multiple for comparison)
- `--from / --to` — date range (YYYY-MM-DD, default: last 30 days)
- `--workflow NAME` — only analyze workflows whose name contains NAME (substring, case-insensitive; repeatable for several workflows). Matches the workflow **display name**; yaml-filename matching is not available in this DB-backed path (the `runs` table stores no workflow file path).
- `--skip-steps` — skip step-level data for faster queries
- `--step-names` — custom step category mapping JSON
- `--no-excel` — terminal output only
- `-o / --output` — custom output path
- `--db-path PATH` — 本地 SQLite db 文件直读（无需 Turso 凭证，ADR-004）

#### Workflow Duration Skill (GitHub API)

For attempt-aware, exact-workflow duration analysis with auditable Workflow/Run/Job/Step sheets, use the root skill:

```bash
python3 .agents/skills/github-ci-efficiency-report/scripts/github_workflow_duration_report.py \
  --repo OWNER/REPO --workflow E2E --from 2026-07-01 --to 2026-07-17
```

It supports YAML multi-repository configuration, rerun attempts, local-timezone boundaries, resumable API caching, and strict/partial workbook generation. See [.agents/skills/github-ci-efficiency-report/SKILL.md](.agents/skills/github-ci-efficiency-report/SKILL.md).

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
---
### 📊 CI 耗时分析（Duration Analysis）

`ci_analyze.py` 通过 `--success-only` + `--min-duration` + `--insights` 开关切换到耗时分析模式（ADR-005，原 `ci_duration_analysis.py` 已合并）。只统计 `conclusion == success` 且 `run 耗时 > N min` 的 run，排除纯 lint 快速通过的脏样本。

```bash
# 成功耗时分析 + 自动洞察（本地 SQLite，0 API 调用）
python3 ci-effective-report/ci_analyze.py \
  --repo vllm-project/vllm-ascend --workflow E2E \
  --from 2026-06-16 --to 2026-06-30 \
  --success-only --min-duration 10 --insights

# 调整耗时阈值
python3 ci-effective-report/ci_analyze.py \
  --repo OWNER/REPO --workflow NAME \
  --from 2026-06-24 --to 2026-07-01 \
  --success-only --min-duration 15 --insights
```

`--insights` 额外生成 HTML 报告：汇总卡片 + **Top 3 问题**（排队瓶颈、关键路径 job、step 热点，按严重度红/橙/黄，附可验证证据）+ 统计表。Excel 原始明细照常生成。

详见 [ADR-005](docs/decisions/adr-005-merge-ci-analysis-scripts.md)。

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
