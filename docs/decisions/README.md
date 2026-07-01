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
