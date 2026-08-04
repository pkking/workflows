# ADR-010: CI Run 卡时核算

**Status**: Accepted
**Date**: 2026-08-04

## Context / 背景

CI 效率下钻 HTML 已按仓库 Tab 展示 Run、Job 与墙钟耗时，但不能反映加速卡资源的实际消耗：并行 Job 的墙钟耗时不能直接相加，且失败/取消的执行同样会占用资源。

现有 runs/jobs 数据不保存可靠的卡数。workflow 文件的 Job `runs-on` label 使用 `linux-aarch64-<设备型号>-<卡数>` 格式；workflow 可能在默认分支后来被修改，因此当前版本不能代表历史 Run 的资源配置。

## Decision / 决策

- **卡时**：对一条 Run 的所有 Job 求和：`Job 实际执行时长 × runs-on label 的卡数`。排队时间不计入。
- Job 仅在同时具有 `started_at` 与 `completed_at` 时计入；成功、失败、取消的 Job 均计入。
- 每个 Run 使用其 `head_sha` 版本的 workflow 文件；按 SHA 缓存解析后的 workflow→Job 卡数结果，避免重复读取。
- 无 workflow 文件、缺少匹配格式 label 或无法解析卡数的 Job 标为未知，不以 0 计入；报告展示未知 Job 数。
- 下钻 HTML 的每个仓库 Tab 头部展示报告时间范围内**全部 Run**的总卡时，以及 `failure`/`cancelled` Run 的失败卡时。Run 表展示每条 Run 总卡时，Job 展开视图展示每条 Job 卡时；Run 表原有 `--drilldown-min` 阈值不影响 Tab 汇总口径。

## Trade-offs / 权衡

- 按 `head_sha` 读取准确保留历史配置，但需要额外 GitHub API 调用；SHA 缓存将同一提交的读取降为一次。
- 未知卡数不计入，可能低估总量；以未知数显式暴露不确定性，优于把未知悄悄当作 0 或猜测卡数。
- 失败/取消 Run 纳入总卡时，更接近资源账本；这会与只看成功率或成功耗时的质量指标保持不同样本口径。

## Alternatives Considered / 备选方案

1. 从 Job 名推断卡数：名称不稳定，且无法作为资源核算依据。
2. 读取默认分支当前 workflow：实现简单，但 workflow 变更后会重写历史 Run 的卡时。
3. 未知卡数按单卡或 0 计入：会产生不可见的系统性误差。
4. 只统计成功 Run：遗漏失败和取消已实际消耗的资源。

## Impact / 影响

- 下钻报告采集路径需额外取得与 Run `head_sha` 对应的 workflow 文件，并维护本地 SHA 缓存。
- 下钻数据模型和 HTML 将增加 Tab、Run、Job 三层的卡时与未知卡数标记。
- 不改变现有 E2E、排队和执行耗时的定义；卡时是独立资源指标。
