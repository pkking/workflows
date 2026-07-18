# ADR-006: 根级 GitHub Workflow 耗时分析 Skill

**Status**: Accepted
**Date**: 2026-07-18

## Context / 背景

`github-ci-efficiency-report` 当前位于 `ci-effective-report/.agents/skills/`，其说明同时覆盖数据库分析、PR 生命周期分析和 GitHub API workflow 分析，并依赖子项目中的脚本。这个位置和能力边界使 skill 难以被仓库内其他子项目复用，也造成 skill 脚本与 `ci-effective-report` 入口之间的路径耦合。

## Decision / 决策

将 skill 迁移到仓库根级 `.agents/skills/github-ci-efficiency-report/`，并使其完全自包含：GitHub API 采集、workflow run/job 统计和 Excel 输出所需代码全部位于该 skill 的 `scripts/` 中。

根级 skill 只负责使用 GitHub API、按 workflow run 创建时间生成 workflow 耗时报告。SQLite、Turso、PR 生命周期和多仓对比继续由 `ci-effective-report` 子项目负责，不属于根级 skill。

删除旧 skill 目录和被新入口替代的 `ci-effective-report/workflow_runs_on_date.py`，更新文档、测试及路径引用，不保留兼容包装器。

## Trade-offs / 权衡

- 优点：skill 可从仓库根级复用，能力边界清晰，运行时不依赖子项目内部文件，避免两套 GitHub API 采集实现继续漂移。
- 代价：现有 CLI 路径发生变化，调用方必须迁移到根级 skill；数据库报告和 GitHub API workflow 报告不再由同一个 skill 入口宣称统一提供。

## Alternatives Considered / 备选方案

1. 保留子项目内 skill：路径耦合和复用问题不变。
2. 根级与子项目各保留一份：兼容性较好，但会产生重复实现和长期漂移。
3. 在旧路径保留兼容包装器：降低短期迁移成本，但延续了已决定移除的跨目录依赖。

## Impact / 影响

- 新路径：`.agents/skills/github-ci-efficiency-report/`。
- 原路径和原按日期采集入口被删除。
- README、测试和 skill 文档改用根级入口。
- `ci-effective-report` 保留数据库、PR 生命周期和多仓对比能力。
