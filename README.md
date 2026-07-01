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

### 📊 CI 耗时分析（Duration Analysis）

针对**成功且实际跑了所有 job 的 CI run**，分析 job/step 的具体耗时，输出自动洞察 + 原始明细。区别于上面的效率报告（含全部 run、按结论分组）：本工具只统计 `conclusion == success` 且 `run 耗时 > 10min` 的 run，排除纯 lint 快速通过（未触发完整测试矩阵）的脏样本。

**省 API 调用**：先拉 run 列表 → 过滤 → 只对命中的 run 抓 jobs（含 steps），调用量降一个数量级（例：1843 个 run 过滤后 108 个，仅 131 次调用）。

```bash
export GITHUB_TOKEN=$(gh auth token)

# 分析某 workflow 过去 7 天的成功耗时
python3 ci-effective-report/ci_duration_analysis.py \
  --repo vllm-project/vllm-ascend --workflow E2E \
  --from 2026-06-24 --to 2026-07-01 \
  --output-dir reports

# 调整耗时阈值（默认 10min；不同 workflow 的完整路径长短不同时用）
python3 ci-effective-report/ci_duration_analysis.py \
  --repo OWNER/REPO --workflow NAME \
  --from 2026-06-24 --to 2026-07-01 \
  --min-duration 15
```

生成两个文件（同名前缀）：
- `*-duration-report-*.html` — 汇总卡片 + **自动文本洞察**（关键路径瓶颈、硬件类型对比、step 类型占比、分片不均衡等）+ 统计表（前 50 行预览）
- `*-duration-raw-*.xlsx` — 原始明细：run_details / job_stats / job_details / step_stats / step_details（全量，供人工下钻）

**CLI options:**
- `--repo OWNER/REPO` — 必填
- `--workflow NAME` — workflow 显示名子串（如 `E2E`），必填
- `--from / --to` — 日期范围（YYYY-MM-DD），必填
- `--min-duration N` — 最小耗时阈值分钟，默认 10
- `--output-dir DIR` — 输出目录，默认当前目录
- `--concurrency N` — 并发抓 jobs，默认 8
- `--step-names PATH` — step 分类映射 JSON（默认 `step-names.json`；未映射的 step 用正则兜底分类）

需要 `GITHUB_TOKEN` / `GH_TOKEN` 或 `--token`。详见 [ADR-003](docs/decisions/adr-003-ci-duration-analysis-purpose-2.md)。

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
