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

#### Skill 触发关键字（在 agent 中如何调用）

在 pi 等 agent 里，skill 靠 `SKILL.md` frontmatter 的 `description` 作为触发信号：启动时扫描各 skill 目录抽取 name/description，任务语义命中某条 description 时，agent 自动 `read` 该 `SKILL.md` 并按其命令执行；也可用 `/skill:<name>` 强制触发。本仓库两个相关 skill 的触发关键字：

| Skill | name | 触发关键字（中文 description） | 适用场景 |
|---|---|---|---|
| GitHub Workflow Duration Report | `github-ci-efficiency-report` | “生成 GitHub Actions 工作流耗时 Excel 报告。用于仓库/工作流对比、重跑 attempt-aware 的 E2E、排队与执行耗时百分位、可审计的 Workflow/Run/Job/Step 统计。” | 跨仓/跨 workflow 耗时对比、重跑 attempt-aware 统计、Excel 审计明细 |
| GitHub Workflow Forensics | `github-workflow-forensics` | “对单个 GitHub Actions run 做耗时取证时间轴分析。当用户问某次工作流为什么这么慢、哪个 job/step 占主导、或想要含 runner 排队时间的 job/step 可视化时间轴时使用。” | 单 run 取证：为什么慢、哪个 job/step 主导、含排队的墙钟时间轴 |

在 agent 里用法示例（用中文描述任务即可命中对应 skill）：

```
# 触发耗时统计 skill（也可强制 /skill:github-ci-efficiency-report）
“生成 vllm-ascend 的 E2E 工作流从 7-01 到 7-17 的耗时 Excel，按仓库对比重跑 attempt”

# 触发单 run 取证 skill（也可强制 /skill:github-workflow-forensics）
“分析 https://github.com/vllm-project/vllm-ascend/actions/runs/123 这次 workflow 为什么这么慢，出含排队时间的时间轴”
```

> 边界：统计 skill 只产出 Excel（不做 HTML/PR 生命周期/Turso）；取证 skill 只看单 run 的墙钟时间轴。两者与上面 `gh_ci_report.py` 产出的 CI 效率 HTML（多仓 tab + Gantt 下钻）互补——后者由 `ci_analyze.py`/`gh_ci_report.py` 直跑，不走 agent skill。

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

### 📊 CI 效率报告 HTML（下钻 + Gantt 时间轴，ADR-009）

`ci_analyze.py` 默认额外生成一份**单文件下钻 HTML**：首页表格列出时间范围内 `duration > --drilldown-min`（默认 60min）的所有 run，每个仓一个 tab；展开 run 下钻到 **job Gantt 时间轴**（共享墙钟轴：轴起=run 触发时间、轴止=所有 job 完成时间；每个 job 橙色段=排队 created→started、蓝色段=运行 started→completed，按真实开始时间排列揭示串/并行）；再展开 job 下钻到 step 明细表。

```bash
# 默认即出 HTML（与 Excel 同时产出）
python3 ci-effective-report/ci_analyze.py \
  --repo vllm-project/vllm-ascend --from 2026-07-01 --to 2026-07-30

# 改阈值 / 跳过 HTML
python3 ci-effective-report/ci_analyze.py --drilldown-min 30
python3 ci-effective-report/ci_analyze.py --no-drilldown
```

**无 DB 凭证时**用 `gh_ci_report.py` 直采 GitHub REST API 生成同一份 HTML（复用 `write_drilldown_html`，jobs 接口嵌套 steps，按日期范围过滤 + 并发拉取）：

```bash
# 单仓
python3 ci-effective-report/gh_ci_report.py \
  --target vllm-project/vllm-ascend:E2E \
  --from 2026-07-30 --to 2026-07-30

# 多仓（每仓一个 tab）
python3 ci-effective-report/gh_ci_report.py \
  --target vllm-project/vllm-ascend:E2E \
  --target "sgl-project/sglang:PR Test (NPU)" \
  --from 2026-07-30 --to 2026-07-30 --drilldown-min 60
```

`--target` 接 `OWNER/REPO:WORKFLOW`（workflow 显示名精确匹配）或 `OWNER/REPO@WORKFLOW_ID`（显示名含特殊字符时更稳）。认证：`GITHUB_TOKEN` → `GH_TOKEN` → `gh auth token`。详见 [ADR-009](docs/decisions/adr-009-ci-drilldown-html-report.md)。

> 说明：非 PR 触发的 run（schedule/push）DB/API 在 run 层面无提交人，提交人列回退显示触发事件——这是 DB schema 的已知缺口，补齐需在 ETL 侧入库 `head_commit.author`。

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
