# Repo Distiller

Distill GitHub repositories into feature lists, technical decisions, and bugfixes using AST parsing, Git history mining, IaC analysis, and multi-agent LLM orchestration.

## Dependencies

### Quick Start (mise)

> **Don't have mise?** Install and activate it first:
> ```bash
> curl https://mise.run | sh           # Linux/macOS
> eval "$(~/.local/bin/mise activate)" # ← 必须！将 mise 加入当前 shell
> ```
> Or via Homebrew (auto-activates): `brew install mise`

If you have [mise](https://mise.jdx.dev/) installed, set up everything in one command:

```bash
# Install all tools (Python, Node.js, repomix) + install the package
mise install && mise run setup

# Or use the combined bootstrap task
mise run install-all
```

The `.mise.toml` at project root manages:

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.12 | Runtime (with uv venv auto-create) |
| Node.js | 22 | Required by repomix and pi extensions |
| repomix | 1.14 | Git-aware file discovery + secret scanning |
| tree-sitter + grammars | latest | AST parsing (auto-installed via pip) |
| pi-web-access | latest | Web access extension for pi |
| pi-subagents | latest | Subagent orchestration extension for pi |

Available tasks:

```bash
mise run setup          # pip install -e . + pi extensions
mise run install-all    # mise install + mise run setup (one-command bootstrap)
mise run analyze        # repo-distiller analyze
```

### System Requirements

| Tool | Version | Purpose |
|------|---------|---------|
| Python | >= 3.10 | Runtime |
| rtk | >= 0.40 | Token reduction core engine (required by pi-rtk) |
| pi CLI | any | Multi-agent LLM orchestration (calls `pi --print`) |
| pi-rtk | any (recommended) | Token reduction extension for pi |

### Installation

```bash
# Install repo-distiller
# Option A: Using mise (recommended)
mise install && mise run setup

# Option B: Manual
pip install -e .
```

### Python Dependencies

Declared in `pyproject.toml` and installed automatically via `pip install`:

| Package | Purpose |
|---------|---------|
| tree-sitter + language grammars | AST parsing (Python, TypeScript, Go) |
| pygit2 | Git repository cloning and history mining |
| PyYAML | IaC config parsing (Helm, Kustomize, ArgoCD) |
| click | CLI interface |
| rich | Colored terminal output |
| jinja2 | Template rendering |

## Usage

```bash
# Basic usage (token optimization enabled by default)
repo-distiller analyze https://github.com/owner/repo --token $GITHUB_TOKEN

# Multiple repos
repo-distiller analyze https://github.com/owner/repo1 https://github.com/owner/repo2 -o ./output

# Disable token optimization for full verbose output
repo-distiller analyze https://github.com/owner/repo --no-consume-tokens

# Analyze a specific branch and subdirectory
repo-distiller analyze https://github.com/owner/repo --branch main --path src/

# Without token (public repos only)
repo-distiller analyze https://github.com/owner/repo

# Clean mode: remove intermediates after analysis, keep only final_report.md
repo-distiller analyze https://github.com/owner/repo --clean
```

## Analysis Pipeline

```
Round 1: Proponents (parallel)
  ├─ PM        ───┐
  └─ Architect ───┘

Round 2: Challengers (parallel)
  ├─ DFX ───┐
  ├─ UX  ───┤  (all read Round 1 outputs, independent of each other)
  └─ Security┘

Round 3: Integrator
  └─ Reads all 5 role outputs → Final consensus report
```

Each step:
1. **Clone** — Repositories are cloned to a temporary working directory
2. **AST Analysis** — Source code is parsed with tree-sitter to extract symbols, APIs, imports
3. **IaC Parsing** — Helm charts, Kustomize configs, and ArgoCD applications are parsed
4. **Git History** — Commit history is mined for hotspots, file couplings, fix patterns
5. **Intermediate JSON** — All findings are saved to `context.json`
6. **Multi-Agent Orchestration** — Six LLM agents analyze the context via `pi` and produce a consensus report

## Output

After analysis, the output directory contains three categories of files:

### 🔴 Intermediate (internal pipeline data, safe to delete)

| File | Purpose |
|------|---------|
| `repos/` | Cloned source repositories (~500 MB) |
| `context.json` | Raw AST/Git/IaC structured data for orchestrator (~420 KB) |

### 🟡 Round Outputs (per-role analysis, useful for debugging/tracing)

| File | Content |
|------|---------|
| `pm_output.md` | PM feature discovery |
| `architect_output.md` | Architecture assessment |
| `dfx_output.md` | Reliability & maintainability critique |
| `ux_output.md` | UX & accessibility critique |
| `security_output.md` | Security vulnerability findings |

### 🟢 Final Deliverable (for humans or downstream agents)

| File | Content |
|------|---------|
| `final_report.md` | Consensus report: features, decisions, risks, action items (~12 KB) |

Use `--clean` to keep only the final report:

```bash
# Keep all outputs (default, for debugging)
repo-distiller analyze https://github.com/owner/repo

# Remove intermediates, keep only final_report.md
repo-distiller analyze https://github.com/owner/repo --clean
```

### Using output as a knowledge base for downstream agents

The `final_report.md` includes an **Agent Routing Table** at the top — each agent type only needs to read 1–2 sections to save 80-90% tokens:

| Downstream Task | Read This Part | Token Savings |
|-----------------|---------------|---------------|
| **Requirement analysis** (user value, acceptance criteria) | Part 1: Features & Requirements | ~83% |
| **Technical design** (architecture, risks) | Part 2: Architecture & Technical Decisions | ~93% |
| **Security review** (vulnerabilities, auth) | Part 3: Security & Reliability | ~85% |
| **Code development** (what to change, where) | Part 5: Action Items | ~85% |
| **Test case writing** (what tests are missing) | Part 7: Test Coverage Gaps | ~81% |
| **Documentation writing** (what docs are missing) | Part 8: Documentation Gaps | ~90% |

> **Avoid `context.json`** — it's raw intermediate data (~420 KB), too noisy and verbose for agent consumption. Let downstream agents read source code directly instead.

## Token Optimization

When `--consume-tokens` is enabled (default):

- **Context compaction**: Only summary statistics (file counts, symbol counts, top imports, hotspot lists) are sent to LLM agents instead of full AST/Git data
- **Output truncation**: Previous agent outputs are capped at 3000 characters
- **pi-rtk**: The pi-rtk extension compresses tool output transparently

Use `--no-consume-tokens` when you need full detail in agent prompts (e.g., debugging, deep analysis).

## Repomix Integration (Optional)

Repo Distiller can optionally use [Repomix](https://github.com/yamadashy/repomix) as a **pre-analysis enhancement layer** for git-aware file discovery and secret scanning.

### What it adds

| Enhancement | Description | Benefit |
|---|---|---|
| **File Discovery** | Uses Repomix's git-aware file discovery (respects `.gitignore`, `.ignore`, `.repomixignore`) | Avoids analyzing `node_modules`, build artifacts, and other generated files — reduces 30-50% of useless AST parsing |
| **Secret Scanning** | Runs [Secretlint](https://github.com/secretlint/secretlint) via Repomix to detect hardcoded secrets | Catches API keys, tokens, and passwords that LLM-based security analysis might miss |

### Installation

```bash
# Install Repomix CLI (Node.js required)
npm install -g repomix
```

### Usage

```bash
# Enable Repomix enhancements (file discovery + secret scanning)
repo-distiller analyze https://github.com/owner/repo --with-repomix

# With include/exclude patterns
repo-distiller analyze https://github.com/owner/repo --with-repomix \
  --repomix-include "src/**/*.ts,src/**/*.py" \
  --repomix-ignore "**/*.test.ts,**/*.spec.ts,**/test/**"

# With Repomix + clean mode
repo-distiller analyze https://github.com/owner/repo --with-repomix --clean
```

### Fallback behavior

Repomix is a **hard requirement** when `--with-repomix` is used. If Repomix CLI is not installed, the command will fail immediately with an error message:

```
✗ Error: --with-repomix requires Repomix CLI, but it is not installed.

  Install it with:
    npm install -g repomix

  Or see: https://github.com/yamadashy/repomix
```

### How it works

```
                    ┌─────────────────────┐
                    │     Repomix         │
                    │  (Optional Layer)   │
                    ├─────────────────────┤
                    │ ① File discovery    │
                    │ ② Secretlint scan   │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   repo-distiller    │
                    │  (Analysis Engine)  │
                    ├─────────────────────┤
                    │ AST 深度解析         │
                    │ 调用图 / 错误流      │
                    │ Schema / 状态机      │
                    │ IaC / 部署拓扑       │
                    │ 多 Agent LLM 编排    │
                    └─────────────────────┘
```

1. After cloning, Repomix runs file discovery and secret scanning in parallel
2. Discovered files become an allowlist for AST analysis (only those files are parsed)
3. Secret findings are injected into `context.json` as `repomix_secrets`
4. The Security Agent receives `repomix_secrets` in its context and includes them in the final report
