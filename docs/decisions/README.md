# Architecture Decision Records (ADRs)

This directory records significant architectural decisions in the workflows project.

## When to write an ADR

Write an ADR when **any** of the following applies:

1. **Technology/Tool Selection** — choosing a database, API, library, or framework
2. **Data Flow / Pipeline Design** — introducing or changing how data moves between systems
3. **New Sub-project or Major Feature** — adding a self-contained project with its own architecture
4. **Breaking Interface Change** — changing output formats, CLI APIs, or data schemas
5. **Trade-off Decision** — making a deliberate choice with known pros/cons
6. **Operational Decision** — deployment, sync cadence, data retention, or infrastructure
7. **Replacing or Deprecating Existing Approach** — documenting why

### When NOT to write an ADR

- Bug fixes or small feature additions
- Configuration changes
- Documentation-only updates
- Dependency version bumps (unless architecturally significant)

## Index

| # | Title | Status | Date |
|---|---|---|---|
| [001](adr-001-turso-based-ci-analysis.md) | 基于 Turso DB 的 CI 效率分析 | Accepted | 2026-06-10 |
| [002](adr-002-topic-researcher-pi-subagent-chain.md) | Topic Researcher: pi subagent chain vs Python project | Accepted | 2026-06-26 |
| [003](adr-003-ci-duration-analysis-purpose-2.md) | CI 耗时分析（目的2）：过滤口径、API 预过滤与 HTML+Excel 双输出 | Accepted | 2026-07-01 |
| [004](adr-004-local-sqlite-direct-read.md) | ci_analyze 支持本地 SQLite 直读（数据源切换） | Accepted | 2026-07-06 |
| [005](adr-005-merge-ci-analysis-scripts.md) | 合并 CI 分析脚本，统一统计逻辑与 success-only 开关 | Accepted | 2026-07-06 |
| [006](adr-006-root-level-github-workflow-duration-skill.md) | 根级 GitHub Workflow 耗时分析 Skill | Accepted | 2026-07-18 |
| [007](adr-007-github-workflow-duration-report-model.md) | GitHub Workflow 耗时报告模型与采集策略 | Accepted | 2026-07-18 |
| [008](adr-008-github-workflow-forensic-timeline.md) | GitHub Workflow 耗时取证时间轴 Skill | Accepted | 2026-07-29 |
