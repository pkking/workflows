# Repo Distiller — Agent Guidelines

## Configuration Principle

**All pi configuration must be passed via CLI arguments — never inherit local user config.**

Required CLI flags for every `repo-distiller analyze` invocation:
```bash
repo-distiller analyze <repo-url> \
  --pi-provider alibaba-cloud \
  --pi-model qwen3.6-plus \
  --pi-api-key "$DASHSCOPE_API_KEY" \
  --pi-extensions pi-web-access,pi-subagents
```

- `--pi-provider` — Provider name (e.g. `alibaba-cloud`). Maps to pi `--provider`
- `--pi-model` — Model ID (e.g. `qwen3.6-plus`). Maps to pi `--model`
- `--pi-api-key` — API key. Passed to pi via `PI_API_KEY` environment variable (not CLI arg) for security
- `--pi-extensions` — Comma-separated npm package names (default: `pi-web-access,pi-subagents`).
  Installed to project scope (`.pi/npm/`) if missing. Resolved extension `.ts` files are
  loaded via `pi --no-extensions -e <path>`, completely isolating from user-local extensions.
- **Models are defined in `.pi/models.json`** in the repo. At runtime, a temp `.ts` extension
  is auto-generated from this file and loaded via `-e`, registering the custom provider
  directly — **zero writes to `~/.pi/agent/models.json`**.
- **Do NOT rely on the user's local pi configuration** (`~/.pi/agent/settings.json` or `~/.pi/agent/models.json`)
- **Do NOT pass API keys via CLI arguments** — they are injected into subprocess `env=` to avoid exposure in `ps` output
- **Do NOT inherit user-local extensions** — pi runs with `--no-extensions`, only the resolved paths from `--pi-extensions` and the auto-generated model registration extension are loaded
- This ensures reproducible, self-contained agent behavior regardless of who runs the project

## Multi-Agent Architecture (Hybrid)

repo-distiller uses a **hybrid architecture**: Python orchestrator controls the pipeline,
while pi's **subagent chain** executes the agent roles internally.

### Agent Definitions (`.agents/`)

Agent roles are defined as Markdown files — **not in Python code**:
```
.agents/
├── pm.md            ← Product Manager role instructions + output format
├── architect.md     ← Software Architect role instructions + output format
├── dfx.md           ← DFX Engineer role instructions + output format
├── ux.md            ← UX Engineer role instructions + output format
├── security.md      ← Security Engineer role instructions + output format
└── integrator.md    ← Integrator role instructions + output format
```

Each `.md` file uses pi-subagents frontmatter format:
```markdown
---
name: pm
tools: read, grep, find, ls, bash
thinking: high
systemPromptMode: replace
---

You are a Project Manager...
```

### Execution Flow

1. **Python orchestrator** runs the 13-step analysis pipeline (AST, Git, IaC, etc.)
2. **Python** writes agent definitions to `.pi/agents/` for pi to discover
3. **Python** generates a master prompt instructing pi to execute the subagent chain
4. **Python** calls `pi --print` **ONCE** with the master prompt
5. **pi** internally executes the 3-round subagent chain:
   - Round 1: PM + Architect (parallel)
   - Round 2: DFX + UX + Security (parallel, with Round 1 outputs)
   - Round 3: Integrator (serial, with all outputs)
6. Each subagent has **tools** (read, grep, find, ls, bash) to actively explore the codebase
7. **pi** exits, **Python** collects outputs and generates structured docs

### Why Hybrid?

| | Pure Python (之前) | 混合架构 (现在) |
|---|---|---|
| Agent 指令 | Python 字典硬编码 | `.agents/*.md` 文件 |
| Agent 能力 | 纯 LLM 推理（无工具） | 有工具（read, grep, bash） |
| 发现深度 | 取决于 Python 提供的数据 | Agent 自主探索，链式发现 |
| 可行动性 | "可能有问题" | "文件:行号，具体证据" |
| 调用次数 | 6 次 pi 子进程 | 1 次 pi 子进程 |
| 编排控制 | Python ThreadPoolExecutor | pi subagent chain |

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
