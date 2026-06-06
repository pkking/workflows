# Repo Distiller — Agent Guidelines

## Quick Start

```bash
# 1. Install dependencies via mise
mise install

# 2. Install repomix (required for enhanced analysis)
npm install -g repomix

# 3. Install the package
pip install -e .

# 4. Run analysis
repo-distiller analyze <repo-url> --output docs --output-format docs
```

## Dependencies

- **Python 3.11+** — managed by mise (see `.mise.toml`)
- **repomix CLI** — git-aware file discovery + Secretlint secret scanning (default enabled)
- **pi CLI** — multi-agent LLM orchestration (PM, Architect, DFX, UX, Security, Integrator)

## Output Format

Use `--output-format docs` to generate structured documentation:

```
<repo>/docs/
├── repo-overview.md              ← Agent routing table (entry point)
└── repo-distill/
    ├── metadata.json             ← Generation metadata
    ├── final_report.md           ← Full integrator report (Parts 0–8)
    ├── features.md               ← Part 1: Features & Requirements
    ├── architecture.md           ← Part 2: Architecture & Technical Decisions
    ├── security.md               ← Part 3: Security & Reliability
    ├── ux.md                     ← Part 4: UX Findings
    ├── dfx.md                    ← DFX: Reliability & Observability Gaps
    ├── action-items.md           ← Part 5: Action Items
    ├── test-gaps.md              ← Part 7: Test Coverage Gaps
    └── doc-gaps.md               ← Part 8: Documentation Gaps
```

## Repomix Integration

Repomix is **enabled by default**. It provides:
- Git-aware file discovery (respects `.gitignore` / `.repomixignore`)
- Secretlint-based secret scanning
- Full repository context pack (injected into Integrator agent for Part 0)

If repomix CLI is not installed, the analysis falls back to built-in file discovery.
