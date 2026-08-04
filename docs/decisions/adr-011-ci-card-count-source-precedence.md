# ADR-011: CI 卡数来源优先级

**Status**: Accepted
**Date**: 2026-08-04

## Context / 背景

ADR-010 从 Run 的 `head_sha` 版本 workflow 文件解析 `runs-on` 标签。该方式无法解析 reusable workflow 内运行时生成的 matrix；例如 vllm-ascend 的 Job API 已返回实际分配的 `labels: ["linux-aarch64-310p-4"]`，但顶层 workflow 只有 `${{ matrix.group.runner }}`。

当前采集 Job 的 GitHub REST 响应已包含 `labels`，但适配器未保留该字段。

## Decision / 决策

- 优先从 GitHub Job API 响应的实际 `labels` 中解析 `linux-aarch64-<设备型号>-<卡数>`。
- Job labels 缺少可解析标签时，回退至 ADR-010 规定的、按 Run `head_sha` 固定的 workflow 定义解析。
- 两种来源均无法解析时，保持未知；不从 Job 名、runner 名或时长推断。
- Workflow 定义解析仍按 repository、workflow identity、SHA 缓存，但仅为需要回退的 Run 读取。

## Trade-offs / 权衡

- 实际 Job labels 覆盖 matrix/reusable workflow，且不增加 API 请求；它随既有 Jobs 响应返回。
- labels 缺失时仍保留 SHA 固定 workflow 回退，兼容现有静态配置。
- 两个来源增加少量优先级逻辑，但避免对运行时表达式做不可靠复现。

## Alternatives Considered / 备选方案

1. 解析 Job 名：名称不是资源配置契约，容易随展示文案改变。
2. 递归解释 reusable workflow 和 matrix：运行时 output 无法从定义可靠复现。
3. 由 workflow 生成资源清单 artifact：审计性强，但需要修改每个目标仓库 CI。

## Impact / 影响

- GitHub collector 保存 Job API 的 `labels`，并在 workflow-content 读取之前解析它。
- 对所有 Job 已有可解析 labels 的 Run，不再请求 workflow 内容。
- 报告的卡时、未知计数和展示逻辑不变。
