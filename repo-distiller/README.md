# Repo Distiller

Distill GitHub repositories into feature lists, technical decisions, and bugfixes using AST parsing, Git history mining, IaC analysis, and multi-agent LLM orchestration.

## Dependencies

All dependencies and pi extensions are managed via [mise](https://mise.jdx.dev/).

### Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| mise | latest | Tool & task manager |
| pi CLI | any | Multi-agent LLM orchestration (calls `pi --print`) |
| pi-rtk | any (recommended) | Token reduction extension for pi |

> **Don't have mise?**
> ```bash
> curl https://mise.run | sh           # Linux/macOS
> eval "$(~/.local/bin/mise activate)" # ← add mise to your shell
> ```
> Or via Homebrew (auto-activates): `brew install mise`

### Quick Start

One command to bootstrap everything:

```bash
mise run install-all
```

This installs:

| Category | Tool | Version | Purpose |
|----------|------|---------|---------|
| Runtime | Python | 3.12 | uv venv auto-create + source |
| Runtime | Node.js | 22 | Required by repomix and pi extensions |
| Tool | repomix | 1.14 | Git-aware file discovery + secret scanning |
| Python | tree-sitter + grammars | latest | AST parsing (auto-installed via pip) |
| Python | pygit2 | — | Git repo cloning and history mining |
| Python | PyYAML, click, rich, jinja2 | — | IaC parsing, CLI, terminal, templates |
| pi ext | pi-alibaba-models | main | Alibaba model provider for pi |
| pi ext | pi-web-access | latest | Web access for pi |
| pi ext | pi-subagents | latest | Subagent orchestration for pi |

Available tasks:

```bash
mise run setup          # pip install -e . + all pi extensions
mise run install-all    # mise install + mise run setup (one-command bootstrap)
mise run analyze        # repo-distiller analyze
```

### Manual Installation

If you prefer not to use mise:

```bash
pip install -e .
pi install github:Fornace/pi-alibaba-models@main -l
pi install npm:pi-web-access -l
pi install npm:pi-subagents -l
```

## Usage

```bash
# 基础分析（Repomix 默认启用）
repo-distiller analyze https://github.com/owner/repo

# 多个仓库
repo-distiller analyze https://github.com/owner/repo1 https://github.com/owner/repo2 -o ./output

# 关闭 token 优化以获取完整输出
repo-distiller analyze https://github.com/owner/repo --no-consume-tokens

# 分析特定分支和子目录
repo-distiller analyze https://github.com/owner/repo --branch main --path src/

# 不使用 token（仅限公开仓库）
repo-distiller analyze https://github.com/owner/repo

# 清理模式：分析后只保留 final_report.md
repo-distiller analyze https://github.com/owner/repo --clean

# Repomix 自定义 include/ignore 模式
repo-distiller analyze https://github.com/owner/repo \
  --repomix-include "src/**/*.ts,src/**/*.py" \
  --repomix-ignore "**/*.test.ts,**/*.spec.ts,**/test/**"
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

## Repomix Integration (内置)

Repomix 文件发现和密钥扫描**默认启用**，无需额外参数。

### 功能

| 增强 | 描述 | 收益 |
|---|---|---|
| **文件发现** | 使用 Repomix 的 git-aware 文件发现（遵循 `.gitignore`, `.ignore`, `.repomixignore`） | 避免分析 `node_modules`、构建产物等无用文件 — 减少 30-50% 无效 AST 解析 |
| **密钥扫描** | 通过 Repomix 运行 [Secretlint](https://github.com/secretlint/secretlint) 检测硬编码密钥 | 捕获 LLM 安全分析可能遗漏的 API key、token 和密码 |

### 依赖安装

```bash
# 安装 Repomix CLI（Node.js 必需）
npm install -g repomix
```

> Repomix 是可选增强：如果未安装，自动回退到内置文件发现。

### 自定义模式

```bash
# 自定义 include/ignore 模式
repo-distiller analyze https://github.com/owner/repo \
  --repomix-include "src/**/*.ts,src/**/*.py" \
  --repomix-ignore "**/*.test.ts,**/*.spec.ts,**/test/**"

# 配合清理模式
repo-distiller analyze https://github.com/owner/repo --clean
```
