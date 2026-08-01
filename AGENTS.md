# AGENTS.md — Development Rules for workflows

This file defines conventions that all agents (human and AI) must follow when working in this repository.

## ADR (Architecture Decision Records)

### Mandatory

When any of the following scenarios occurs, you **MUST** write an ADR before implementing the change:

1. **Technology/Tool Selection** — choosing a database, API, library, or framework
2. **Data Flow / Pipeline Design** — introducing or changing how data moves between systems
3. **New Sub-project or Major Feature** — adding a self-contained project with its own architecture
4. **Breaking Interface Change** — changing output formats, CLI APIs, or data schemas
5. **Trade-off Decision** — making a deliberate choice with known pros/cons that future contributors need to understand
6. **Operational Decision** — deployment, sync cadence, data retention, infrastructure
7. **Replacing or Deprecating Existing Approach** — documenting why the old way is being kept/replaced

### When NOT to write an ADR

- Bug fixes or small feature additions
- Configuration changes (env vars, thresholds)
- Documentation or README updates alone
- Dependency version bumps (unless introducing a new dependency with architectural impact)

### ADR Format

Store ADRs in `docs/decisions/adr-NNN-short-title.md`:

```markdown
# ADR-NNN: Title

**Status**: Proposed | Accepted | Superseded | Deprecated
**Date**: YYYY-MM-DD

## Context / 背景
## Decision / 决策
## Trade-offs / 权衡
## Alternatives Considered / 备选方案
## Impact / 影响
```

### Process

1. Determine if the change warrants an ADR (see criteria above)
2. Check `docs/decisions/README.md` for the next ADR number
3. Write the ADR in `docs/decisions/adr-NNN-short-title.md`
4. Update the index table in `docs/decisions/README.md`
5. Commit the ADR as a separate commit before implementation commits

## Project Structure

```
workflows/
├── README.md
├── AGENTS.md          ← this file
├── docs/
│   └── decisions/     ← ADRs
│       ├── README.md  ← ADR index
│       └── adr-NNN-*.md
├── ci-effective-report/
├── repo-distiller/
├── yt-obsidian/
└── pm-dashboard/
```

Each sub-project is independently installable. See the root README.md for details.

## Secrets

Never commit `.env` files. Use `.gitignore` to exclude them.

## Pull Request Policy (必走 PR)

**`main` 受分支保护：禁止直推，所有变更必须通过 PR 合并。**

agent 与人一样必须遵守：
1. 不准 `git push origin main`（会被远端拒绝，enforce_admins 对 owner 也生效）。
2. 在特性分支上提交：`git switch -c feat/<short-desc>`，推该分支。
3. 开 PR：`gh pr create --base main --head feat/<short-desc>`。
4. 通过 PR 合并后再删特性分支。

ADR 仍须作为独立的先行 commit 进特性分支（见上文 ADR Process）。

例外（可不走 PR、但仍需经允许）：安全紧急回滚、文档纯字改动——即使这些也优先走 PR 除非会延误修复。
