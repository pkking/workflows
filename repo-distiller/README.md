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
