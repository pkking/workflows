# ci-effective-report — GitHub CI 效率分析

针对 GitHub Actions 的 CI 耗时分析工具集，三种产出、三套入口，按数据源与需求选用。

## 工具一览

| 工具 | 数据源 | 产出 | 何时用 |
|---|---|---|---|
| `ci_analyze.py` | Turso DB / 本地 SQLite | Excel 多 sheet + CI 效率 HTML（默认） | 有 DB 凭证，跨仓/跨 workflow 聚合统计 |
| `gh_ci_report.py` | GitHub REST API | CI 效率 HTML | 无 DB 凭证，按日直采 GitHub |
| `github-ci-efficiency-report` skill | GitHub REST API | Excel | agent 内调用，attempt-aware 审计统计 |
| `github-workflow-forensics` skill | GitHub REST API | 单 run 时间轴 HTML | 单 run 取证：为什么慢 |

## 1. ci_analyze.py — DB 背书的聚合分析

直接查 Turso DB（无 API 限流、秒级分析百万级 job/step），无凭证时自动检测本地 SQLite 直读（`~/action-insight/etl/data/{owner-repo}.db`，0 网络调用）。数据源优先级：`--db-path` > Turso 凭证 > 自动本地 db。

```bash
# 默认（vllm-ascend，近 30 天）
python3 ci_analyze.py
# 指定仓 + 时间范围 + workflow 子串过滤
python3 ci_analyze.py --repo vllm-project/vllm-ascend --from 2026-07-01 --to 2026-07-31 --workflow E2E
# 多仓对比
python3 ci_analyze.py --repo vllm-project/vllm-ascend --repo modelscope/ms-swift --from 2026-06-01 --to 2026-06-06
```

### Excel 输出（`--no-excel` 跳过）

| Sheet | 内容 |
|---|---|
| 仓库对比 | 多仓汇总（仅多仓模式） |
| 工作流统计 | 每个 workflow 的 run 数 / 平均 / P50 / P90 耗时 |
| 任务统计 | job 级耗时、排队、资源类型 |
| 步骤统计 | step 执行数、平均 / P50 / P90 耗时、成功率、类型 |
| PR 统计 | PR e2e、CI 后评审、workflow 数 |
| PR 详情 | PR→workflow→job→step 层级树 |

### CI 效率 HTML（默认产出，`--no-drilldown` 跳过，ADR-009）

单文件下钻报告：首页表格列出 `duration > --drilldown-min`（默认 60min）的所有 run，每仓一个 tab；展开 run 下钻到 **job Gantt 时间轴**（共享墙钟轴：起=run 触发、止=所有 job 完成；每 job 橙=排队 created→started、蓝=运行 started→completed，按真实开始时间排列揭示串/并行，hover 显示启动/结束/排队/执行耗时，job 名可点开跳 GitHub job 页）；再展开 job 下钻到 step 明细表（step 严格串行，用表格）。

```bash
python3 ci_analyze.py --drilldown-min 30      # 改阈值
python3 ci_analyze.py --no-drilldown          # 跳过 HTML
```

### 耗时分析模式（ADR-005）

`--success-only --min-duration N` 只统计 `conclusion=success` 且 `run 耗时>N min` 的样本，排除快速通过的脏样本。`--insights` 额外输出洞察 HTML：Top 3 问题（排队瓶颈 / 关键路径 job / step 热点，按严重度红橙黄 + 证据）+ 汇总卡片 + 统计表。

```bash
python3 ci_analyze.py --repo vllm-project/vllm-ascend --workflow E2E \
  --from 2026-06-16 --to 2026-06-30 --success-only --min-duration 10 --insights
```

### 常用 CLI

- `--repo OWNER/REPO`（可重复）、`--from/--to`（YYYY-MM-DD）、`--workflow NAME`（显示名子串匹配，可重复）
- `--skip-steps`（加速）、`--step-names PATH`、`-o/--output`、`--db-path PATH`
- `--list-repos` 列出可用仓库

## 2. gh_ci_report.py — 无 DB 凭证直采 GitHub

复用 `ci_analyze.py` 的 `write_drilldown_html`，把 GitHub Actions runs/jobs(steps) 适配成统一模型后渲染同一份下钻 HTML。jobs 接口嵌套 steps，一次调用拿到 job+step；按日期范围过滤 + 并发拉取；502/503/504 自动重试。

```bash
# 单仓
python3 gh_ci_report.py --target vllm-project/vllm-ascend:E2E --from 2026-07-30 --to 2026-07-30
# 多仓（每仓一个 tab）
python3 gh_ci_report.py \
  --target vllm-project/vllm-ascend:E2E \
  --target "sgl-project/sglang:PR Test (NPU)" \
  --from 2026-07-30 --to 2026-07-30 --drilldown-min 60
```

`--target` 接 `OWNER/REPO:WORKFLOW`（显示名精确匹配）或 `OWNER/REPO@WORKFLOW_ID`（名称含特殊字符时更稳）。认证：`GITHUB_TOKEN` → `GH_TOKEN` → `gh auth token`。

> 已知缺口：非 PR 触发的 run（schedule/push）DB/API 在 run 层面无提交人，提交人列回退显示触发事件；补齐需在 ETL 侧入库 `head_commit.author`。

## 3. Agent skills（`gh_ci_report.py`/`ci_analyze.py` 是直跑脚本，不走 skill）

在 pi 等 agent 里，skill 靠 `SKILL.md` frontmatter 的 `description` 作触发信号：启动时扫描各 skill 目录抽取 name/description，任务语义命中即自动 `read` 该 `SKILL.md` 并执行；也可 `/skill:<name>` 强制触发。

| Skill | name | 触发关键字（中文 description） |
|---|---|---|
| GitHub Workflow Duration Report | `github-ci-efficiency-report` | 生成 GitHub Actions 工作流耗时 Excel 报告。用于仓库/工作流对比、重跑 attempt-aware 的 E2E、排队与执行耗时百分位、可审计的 Workflow/Run/Job/Step 统计。 |
| GitHub Workflow Forensics | `github-workflow-forensics` | 对单个 GitHub Actions run 做耗时取证时间轴分析。当用户问某次工作流为什么这么慢、哪个 job/step 占主导、或想要含 runner 排队时间的 job/step 可视化时间轴时使用。 |

用法示例（中文描述任务即可命中）：

```
# 统计 skill（也可 /skill:github-ci-efficiency-report）
“生成 vllm-ascend 的 E2E 从 7-01 到 7-17 的耗时 Excel，按仓库对比重跑 attempt”
# 取证 skill（也可 /skill:github-workflow-forensics）
“分析 https://github.com/vllm-project/vllm-ascend/actions/runs/123 为什么这么慢，出含排队时间的时间轴”
```

详见 [github-ci-efficiency-report/SKILL.md](../.agents/skills/github-ci-efficiency-report/SKILL.md)、[github-workflow-forensics/SKILL.md](../.agents/skills/github-workflow-forensics/SKILL.md)。

## 相关 ADR

- [ADR-001](../docs/decisions/adr-001-turso-based-ci-analysis.md) 基于 Turso DB 的 CI 分析
- [ADR-004](../docs/decisions/adr-004-local-sqlite-direct-read.md) 本地 SQLite 直读
- [ADR-005](../docs/decisions/adr-005-merge-ci-analysis-scripts.md) 合并 CI 分析脚本 + success-only
- [ADR-009](../docs/decisions/adr-009-ci-drilldown-html-report.md) CI 效率下钻 HTML 报告
