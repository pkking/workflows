# ADR-009: CI 耗时下钻 HTML 报告

**Status**: Accepted
**Date**: 2026-07-30

## Context / 背景

`ci_analyze.py` 已有两种输出：Excel 工作簿（多 sheet 统计）与 `--insights` HTML（Top 问题 + 汇总卡片 + 统计表）。两者都是**聚合视角**——按工作流/任务/步骤汇总 P50/P90，回答“哪类工作流慢”。

但定位“某次具体 run 为什么慢”时，聚合视角不够：用户需要先看到时间范围内所有超阈值（如 >60min）的 run，逐条下钻到该 run 的 job，再看每个 job 的 step 耗时。此前只能把超时 run 的 URL 逐个喂给 `github-workflow-forensics` skill（REST API 逐次取数），生成一个把所有 run 平铺渲染的超大 HTML（实测单文件 15MB+），打开即卡顿，且首页没有“代码仓/提交人/创建时间/Run URL”的表格总览。

## Decision / 决策

为 `ci_analyze.py` 新增**默认生成**的下钻 HTML 输出：单文件、三级下钻，复用已从 DB 取到内存的 runs/jobs/steps（无额外 API 调用）。默认随分析一起产出（满足“输出是一个 html”的预期），可用 `--no-drilldown` 跳过，与 `--no-excel` 对齐。

- **首页表格**：列出时间范围内 `duration > --drilldown-min`（默认 60min）的所有 run，列含代码仓、提交人、创建时间、Workflow、耗时、状态、Run URL，前置 ▶ 可下钻。
- **下钻一级 — job Gantt 时间轴**：该 run 下所有 job 按真实开始时间（chronological）排列，共享一条墙钟时间轴（轴起=run 触发时间 created_at，轴止=所有 job 完成时间 max(job.completed_at)）。每个 job 是轴上一条微型时间轴：第一段橙色=排队（created_at→started_at），第二段蓝色=运行（started_at→completed_at）。条形在轴上的左右位置直接揭示 job 间的串/并行关系。job 仍用原生 `<details>` 展开下钻到 step。
- **下钻二级 — step 明细**：每个 job 再下钻出该 job 所有 step 的小表（序号、名称、步骤类型、耗时、状态），同样复用 `classify_step` 分类。

技术取舍：

1. **单文件、原生 HTML/CSS + 极少 JS**，不引入图表库或前端框架（沿用 ADR-008 的边界）。
2. **数据内嵌为 JSON + 按需渲染**：首页表格 JS 动态渲染；展开 run 时才渲染该 run 的 job 图与 step 表，初始 DOM 小、可承载上百 run。
3. **提交人经 `pr_workflows → pr_metrics.author` 关联**；非 PR 触发的 run（schedule/push）DB 中无作者，提交人列回退显示触发事件（如 `schedule`），并明确这是 DB schema 的已知缺口，而非 bug。
4. **XSS 防护**：内嵌 JSON 中把 `</` 替换为 `<\/`（`\/` 是合法 JSON 转义，值不变），防止 job/step 名里出现 `</script>` 提前闭合 `<script>`；运行时所有用户值再经 `esc()` 转义。
5. **阈值可调**：`--drilldown-min` 默认 60，可改 30/90 等。
6. **默认输出**：该 HTML 默认随每次分析产出（不藏在开关后），用 `--no-drilldown` 跳过；与 `--no-excel` 对齐。这样“跑一下就拿到 html”符合预期，且不破坏 Excel/insights 既有输出。

## Trade-offs / 权衡

- **Gantt 时间轴 vs 降序条形图**：首版用“按耗时降序的横向条形图”，只能一眼看出哪个 job 最长，丢了 job 间并行/时序。现版改为墙钟 Gantt（每个 job 橙色排队段+蓝色运行段，对齐到 run 的真实时间轴），能看出串/并行与排队瓶颈，更贴近“哪个 job 拖长了 run 墙钟”。代价是需携带 job 的 created/started/completed 时间戳（DB 与 gh 采集均已有）。单 run 的完整依赖图/日志语义仍留给 `github-workflow-forensics` skill。
- **按需渲染 vs 全量预渲染**：按需渲染初始 DOM 小，但引入 ~40 行 JS；换来的是上百 run 也能流畅打开。若未来 run 数恒小，可退化回全量预渲染以去掉 JS。
- **DB 作者缺口**：schedule/push run 无提交人，是 DB schema 限制；若需补齐，应在 ETL 侧把 `head_commit.author` 入库，而非在此处逐 run 调 GitHub API（会引入速率限制与新的取数路径）。
- **复用 DB 数据 vs 调用 forensics skill**：本报告复用已取到的 DB 数据，零额外 API、秒级；但 DB 时间戳精度/完整性取决于 ETL，forensics skill 直连 REST 的时间戳更“原汁原味”。两者互补：本报告做筛选与总览下钻，forensics 做单 run 精确取证。

## Alternatives Considered / 备选方案

1. **扩展现有 `--insights` HTML**：它是聚合统计 + Top 问题，把下钻表硬塞进去会混淆两种调用分支（聚合 vs 单 run 下钻），且打破“insights 只做洞察”的边界。
2. **用 forensics skill 生成超时 run 汇总**：已在用（15MB 平铺 HTML），但无表格总览、无提交人、首页即重；且每个 run 都走 REST，慢且受速率限制。
3. **引入 Plotly/ECharts 做交互图表**：图表更强，但为“横向条形 + 下钻表”这种简单需求增加了依赖与文件体积，违反单文件可分享原则。

## Impact / 影响

- 新增 `build_drilldown_data`（纯数据组装，可单测）、`write_drilldown_html`（HTML 渲染）两个函数，新增 `--no-drilldown`（跳过）/ `--drilldown-min`（阈值）两个 CLI 开关；下钻 HTML 默认生成。
- 不改变现有 Excel schema 或 `--insights` 输出；纯增量（多一个默认产出的 html 文件）。
- 新增 `tests/test_ci_analyze.py` 覆盖阈值过滤、提交人关联、排序、步骤分类、缺失耗时、XSS 防护。
- 与 `github-workflow-forensics` skill 的边界不变：本报告做时间范围内超阈值 run 的表格总览 + 三级下钻；forensics skill 做单 run attempt 的墙钟时间轴取证。
