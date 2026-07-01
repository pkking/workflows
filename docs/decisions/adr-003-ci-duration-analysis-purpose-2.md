# ADR-003: CI 耗时分析（目的2）— 过滤口径、API 预过滤与 HTML+Excel 双输出

**状态**: Accepted
**日期**: 2026-07-01

## 背景

`ci-effective-report/` 需服务三个目的（PR 开发者体验 / CI 耗时分析 / 仓库级 workflow 时长统计）。本 ADR 仅覆盖**目的2：CI 耗时分析**。

现状缺陷（见代码审查）：
1. 三个 adapter 的结论(conclusion)过滤口径不一致——Turso 全不过滤、by-date 留 success+failure、by-SHA 仅 success(run+job) 但 step 不过滤。failure/cancelled 的耗时是被截断的脏数据，混入统计会拉低 p50、扭曲分布。
2. 无人区分"跑了所有 job 的完整 CI"与"纯 lint 快速通过"。vllm-ascend 的 E2E workflow 双峰明显：77.8% 的 run ≤5min（只跑 lint，未触发硬件测试矩阵），~10% 走完整测试 ~90min。不区分会让 p50 失真到 4min。
3. 只有统计表，无自动分析结论；输出仅 Excel。

## 决策

### 过滤标准
"实际跑了所有 job 的成功 CI" 定义为：**`conclusion == "success"` 且 run 耗时 > 10 分钟**。
- success 保证耗时是完整执行（非 fast-fail 截断）。
- >10min 排除纯 lint 快速通过的 run（E2E 完整路径最短 ~50min，lint 路径 ≤5min，10min 是安全分界）。

### API 预过滤（节约调用）
GitHub API 调用受限，因此**先拉 run 列表（少量分页调用）→ 应用过滤 → 只对命中的 run 抓 jobs（含 steps）**。
- 例：vllm-ascend E2E 过去 7 天 1833 个 run，过滤后约 190 个，API 调用从 ~1833 降至 ~190 + 几次分页。
- jobs 响应已内嵌 steps（GitHub 一次返回），不再单独调 step API——复用已有返回数据。

### 输出
- **HTML**：统计表 + 自动文本洞察（关键路径瓶颈、资源类型分布、step 热点、稳定性 p90/p50）。可读性优先。
- **Excel**：原始明细数据（run_details / job_details / step_details + 聚合表）。供人工下钻。
- 双输出分离：HTML 看结论，Excel 看明细。

### step 分类
复用已有 `step-names.json`（89 条 构建/CI启动/执行测试/排除 映射），洞察按 step 类型汇总，无需 LLM 二次分类。

## 权衡

### 优点
- 过滤口径统一为 success-only，消除 adapter 间不一致。
- 预过滤把 API 调用量降一个数量级，对齐"节约调用"约束。
- 自动洞察把"瓶颈在哪"从人工解读变成数据驱动结论。

### 缺点 / 已知天花板
- 10min 阈值是针对 vllm-ascend E2E 的经验值；其他 workflow 的完整路径可能更短。阈值可配（`--min-duration`），默认 10min。
- success-only 引入幸存者偏差：经常失败的 job 配置不在样本里。本目的只评估"正常执行耗时"，失败稳定性是另一个问题（目的1 的成功率已覆盖）。
- 无 Turso 凭证时走 GitHub API；有凭证时应走 Turso（0 调用），见 ADR-001。本脚本暂以 GitHub API 为数据源。

## 备选方案
1. 在 Turso 层做（SQL `WHERE conclusion='success' AND duration_seconds>600`）——0 API 调用，最优，但当前无 `.env` 凭证且 ci_analyze.py 是仓库级非 workflow 级。待凭证就绪后可切换数据源，分析/输出逻辑不变。
2. 不预过滤、全量抓 jobs 再筛——简单但浪费 ~1600 次调用，违反约束。否决。

## 影响
- 新增脚本 `ci_duration_analysis.py`，复用 by-SHA adapter 的 `GitHubClient`/数据类/`fetch_jobs_for_run` 与 by-date 的 `fetch_workflow_id`/`norm_job_name`。
- 不改动现有三个脚本，避免破坏其既有行为。
- 目的1、目的3 后续单独实现。
