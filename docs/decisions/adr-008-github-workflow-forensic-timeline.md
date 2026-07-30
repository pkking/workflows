# ADR-008: GitHub Workflow 耗时取证时间轴 Skill

**Status**: Accepted
**Date**: 2026-07-29

## Context / 背景

现有 `github-ci-efficiency-report` skill 面向日期范围和跨 Workflow 统计，能列出 Job/Step 耗时，却不能把单次 Workflow attempt 的排队、并行 Job 和 Step 放在同一时间轴上，因此难以快速定位超时由排队、长任务还是并行尾部造成。

## Decision / 决策

新增根级 `.agents/skills/github-workflow-forensics/`，专门分析一个或多个 GitHub Actions run attempt：

- 输入 GitHub run URL，或 `owner/repo + run ID`；attempt 独立分析。
- 通过 GitHub REST API 获取 run、job 和 step 时间戳。
- 生成单文件 HTML，展示按真实墙钟对齐的 Workflow Job 时间轴，以及每个 Job 的 Step 时间轴；Job 排队与执行使用不同区段。
- 根据时间戳输出排队瓶颈、最长执行 Job、最长 Step、尾部 Job 和未被 Step 覆盖的 Job 开销。结论标为“耗时定位”，不宣称没有日志证据的语义根因或真实依赖关键路径。
- 使用 Python 标准库和原生 HTML/CSS/SVG，不新增运行时依赖。认证顺序沿用 `GITHUB_TOKEN`、`GH_TOKEN`、`gh auth token`。
- 保持与统计 skill 的边界：统计 skill 负责筛选异常 run；本 skill 负责对已选 run 做逐次取证可视化。

## Trade-offs / 权衡

- 单文件 HTML 易分享且无需前端构建，但图表交互能力弱于 Plotly 等库。
- REST 时间戳可以可靠定位耗时区段，却不包含 Job 依赖图；报告只能给出关键路径代理和时间证据。
- 不默认下载日志可减少 API、存储和敏感信息风险，但无法判断下载慢、测试挂起等日志语义原因。

## Alternatives Considered / 备选方案

1. 扩展现有 Excel skill：会混合总体统计与单次取证两种调用分支，并打破其“仅 Excel”边界。
2. 引入 Plotly：图表能力更强，但为简单时间轴增加了依赖和输出体积。
3. 默认下载并分析日志：信息更丰富，但成本、敏感信息和非确定性显著增加，应在确有需求时单独扩展。

## Impact / 影响

- 新增一个可独立调用、也可承接统计报告 Run ID 的 model-invoked skill。
- 输出新增 HTML 时间轴格式，不改变现有 Excel schema 或 CLI。
