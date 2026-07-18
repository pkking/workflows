# ADR-007: GitHub Workflow 耗时报告模型与采集策略

**Status**: Accepted
**Date**: 2026-07-18

## Context / 背景

根级 `github-ci-efficiency-report` skill 需要在不依赖 SQLite/Turso 的前提下，通过 GitHub API 对多个仓库、多个 workflow 的耗时进行横向分析。GitHub workflow rerun 以 attempt 表示，Job 与 Step 的时间字段不同，大规模采集还会触发 REST API 限流，因此必须统一执行记录、统计样本、Excel schema 和恢复策略。

## Decision / 决策

### 输入与配置

- 支持互斥的 `--config` 与 `--repo + --workflow` 两种目标来源；未显式指定时读取仓库根目录 `.github-ci-efficiency.yaml`。
- YAML 使用 PyYAML。每个 repo 可配置多个 workflow、`comparison_group`，每个 workflow 可配置 `comparison_name` 和 `min_e2e_minutes`。
- workflow 显示名只做不区分大小写的完整匹配；同名但不同 `workflow_id` 分开统计。
- 最短 E2E 阈值优先级为 CLI > workflow 配置 > YAML defaults > 内置 10 分钟。比较项可使用不同阈值，但 Excel 必须显示阈值并标记可比性提示。
- 日期按本地时区解释，可用 `--timezone` 覆盖；attempt 按自身 `run_started_at` 归期。

### 执行记录与指标

- 一个 workflow attempt 是一条独立的 Workflow 执行记录；rerun 分别计数，唯一键为 `run_id + run_attempt`。
- Workflow 实际 E2E = attempt 中最晚 Job 完成时间 - 最早 Job 创建时间；无可用 Job 时间时回退到 attempt run 时间。
- Workflow 排队耗时 = attempt 内 `job.started_at - job.created_at` 的最大值。
- Workflow 执行耗时 = attempt 内 `job.completed_at - job.started_at` 的最大值。
- 三项指标彼此独立，不要求 E2E 等于排队加执行。
- Workflow 执行次数只统计 completed attempts；未完成记录只进入 Run 明细。耗时分布只统计 success 且达到 workflow 阈值的记录。
- Job 成功率为 `success / (success + failure)`；排队耗时可包含成功和失败 Job，执行耗时只统计成功 Job。
- Step 没有排队指标；成功率为 `success / (success + failure)`，执行耗时只统计成功 Step。
- P50/P90 使用 Excel `PERCENTILE.INC` 等价线性插值。内部用秒计算，Excel 以分钟显示一位小数。

### Excel 输出

- 仅生成 Excel，默认路径为 `reports/github-workflow-duration-{from}_to_{to}.xlsx`。
- 工作表包含：报告信息、指标定义、Workflow统计、Run明细、Job统计、Step统计。
- Workflow 通过 `comparison_group + comparison_name` 相邻展示，不计算基准变化率；未配置比较组时使用 GitHub owner。
- Job 按 `repo + workflow_id + 原始 Job 名` 聚合；Step 按 `repo + workflow_id + 原始 Job 名 + Step 名` 聚合。
- Job/Step 使用全部 completed attempts，不受 Workflow 最短 E2E 阈值影响，并按 P90 长尾、失败率和样本量进行风险优先排序。

### 采集与缓存

- token 获取顺序：`GITHUB_TOKEN` > `GH_TOKEN` > `gh auth token`，不提供 `--token`。
- 使用 `.cache/github-ci-efficiency/` 保存可恢复的原始 API 响应；已完成 attempt 的 jobs/steps 永久复用，未完成 run 每次刷新，workflow/run 列表页缓存 15 分钟。
- 遇到 GitHub rate limit 自动等待到 reset 后继续；`--refresh` 忽略缓存；损坏缓存自动重取。

### 运行环境

- skill 使用自身目录内的 `.venv`，依赖通过 `pyproject.toml + uv.lock` 声明并锁定。
- 入口缺少依赖时只检测 uv：存在 uv 则自动执行项目同步并用 skill 虚拟环境重新运行；不存在 uv 时仅提示缺少的依赖，不自动修改系统 Python。
- 不支持 mise，不自动安装 uv，也不自动修改调用者的 shell 环境。

## Trade-offs / 权衡

- 直接使用 GitHub API 能获得 attempt/job/step 的权威原始数据，但大规模 Job/Step 分析调用量高，需要持久缓存并可能跨限流窗口运行。
- attempt 按自身启动时间归期能正确计入旧 run 在本期发生的 rerun，但要求扫描 workflow 可见历史，而不能只使用 run created 日期过滤。
- 不同 workflow 阈值允许反映各自有效执行基线，但会降低横向可比性，因此选择显式警告而不是阻止生成。
- 仅生成 Excel 减少多格式口径漂移，但不再提供旧 skill 宣称的 HTML 洞察页。

## Alternatives Considered / 备选方案

1. 只分析父 run 的最新 attempt：会漏掉 rerun 的资源消耗和失败记录。
2. 按父 run `created_at` 归期：会漏掉旧 run 在本期发生的 rerun。
3. 使用数据库缓存：查询更高效，但违反本 skill 只使用 GitHub API 和文件缓存的边界。
4. 让 Job/Step 继承 Workflow 最短 E2E 过滤：API 调用更少，但会丢失短 run 和失败 run 的质量信号。

## Impact / 影响

- 新增根目录 YAML 配置、reports 输出目录和文件缓存目录。
- 新增 skill 内部 uv 项目和虚拟环境引导；`.venv` 不进入版本控制。
- Excel schema 与旧报告不兼容，调用方需使用新的工作表和列定义。
- 大范围、多 workflow 报告可能自动等待 GitHub 限流后继续。
