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

## Context
## Decision
## Trade-offs
## Alternatives Considered
## Impact
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
