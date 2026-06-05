# 🧪 Repo-Distiller — Integrator Report

> **🗺️ Agent Routing Table** — Read only the parts relevant to your task to save tokens.
>
> | Your Goal | Read These Sections |
> |-----------|--------------------|
> | **Requirement Analysis** (user value, acceptance criteria, module assignment, UX quality) | Part 1: Features & Requirements |
> | **Technical Design** (architecture, risks, decisions) | Part 2: Architecture & Technical Decisions |
> | **Security Review** (vulnerabilities, auth, secrets) | Part 3: Security & Reliability (vulnerabilities table + auth patterns) |
> | **Code Development** (what to change, where) | Part 5: Action Items (with file references) |
> | **Test Case Writing** (what tests are missing) | Part 7: Test Coverage Gaps |
> | **Documentation Writing** (what docs are missing) | Part 8: Documentation Gaps |
> | **Full audit / comprehensive review** | Read all Parts 1–8 |

---

## Part 1: Features & Requirements

### ✅ Agreed Features (Strong Consensus)

1. **Multi-Repo Analysis Pipeline** — Clones 1+ GitHub repos, runs AST parsing, Git history mining, and IaC analysis, then generates a structured report via multi-agent LLM orchestration.
   - **User Problem**: Understanding unfamiliar codebases quickly + finding technical debt hotspots before refactoring + multi-perspective code review at scale.
   - **Module**: `src/repo_distiller/analyzer.py` (pipeline coordinator), `src/repo_distiller/cli.py` (entry point)
   - **Acceptance Criteria**:
     1. Given a list of repo URLs, the pipeline produces a `final_report.md` with AST, Git, IaC, and LLM analysis sections.
     2. Failed repo clones are reported with non-zero exit code (currently silently swallowed — see Action Items).
     3. `--clean` flag removes all intermediate artifacts leaving only `final_report.md`.
   - **UX Assessment**: Pipeline has numbered step console output but no progress bars for long operations (cloning ~500MB repos, parsing thousands of files). `--clean` is destructive without confirmation.
   - **Feasibility**: **Feasible** — architecture is sound; reliability gaps exist but are fixable.

2. **AST-Based Code Extraction** — Parses Python, TypeScript, TSX, and Go files using tree-sitter to extract symbols, API endpoints, data models, imports, and entry points.
   - **User Problem**: Understanding unfamiliar codebases quickly without reading every file manually.
   - **Module**: `src/repo_distiller/ast_parser.py` (extractors), `src/repo_distiller/analyzer.py` (file discovery via `SUPPORTED_EXTS`)
   - **Acceptance Criteria**:
     1. Files matching registered extensions (.py, .ts, .tsx, .go) produce non-empty `ExtractorResult` with symbols, APIs, and imports.
     2. `SUPPORTED_EXTS` in `analyzer.py` matches exactly the keys in `LANGUAGES`, `PARSERS`, and `EXTRACTORS` in `ast_parser.py` — no silent no-ops.
     3. Malformed files are logged (currently silently dropped via blanket `except Exception`).
   - **UX Assessment**: Good OOP pattern (`LanguageExtractor` base class → language-specific subclasses). However, silent inconsistency: `.rs`, `.java`, `.js` declared in `SUPPORTED_EXTS` but have no extractors — users won't know these are ignored.
   - **Feasibility**: **At-Risk** — declared languages (Rust, Java, JavaScript) have no extractor implementations, causing silent data loss.

3. **Git History Mining** — Identifies file churn hotspots, file co-change couplings (capped at 20 files/commit for O(n²)), and fix-pattern commits using fast `git log --name-status`.
   - **User Problem**: Finding technical debt hotspots before refactoring — reveals which files change together (regression risk) and which have highest churn (instability).
   - **Module**: `src/repo_distiller/git_analyzer.py`
   - **Acceptance Criteria**:
     1. Git log parsing completes within timeout for repos with up to 100 commits (default limit).
     2. Co-change couplings are correctly computed and capped (count > 3 threshold, top 10 returned).
     3. 30s timeout on `git log` produces a warning if fired (currently silent truncation).
   - **UX Assessment**: No progress indication during git history mining on large repos.
   - **Feasibility**: **Feasible** — algorithm is correct; timeout silently truncating data is a reliability gap.

4. **Multi-Agent LLM Orchestration (3 Rounds)** — Round 1: PM + Architect propose features (parallel). Round 2: DFX + UX + Security critique them (parallel). Round 3: Integrator produces consensus report.
   - **User Problem**: Multi-perspective code review at scale — 5 independent LLM roles provide diverse critiques a single review pass would miss.
   - **Module**: `src/repo_distiller/orchestrator.py`
   - **Acceptance Criteria**:
     1. Each round completes with non-empty output from all agents; empty outputs trigger retry or early-exit.
     2. Context projection correctly slices data per role (verified: `_project_context` returns role-specific dicts).
     3. Per-agent timing is recorded and displayed (verified: `timings` dict with 4 entries).
   - **UX Assessment**: Users watch blank terminal for up to 10 minutes per agent (600s timeout) with no intermediate feedback, no ETA, and no progress callbacks from `ThreadPoolExecutor`.
   - **Feasibility**: **Feasible** — `ThreadPoolExecutor` correctly used with appropriate worker counts; zero error recovery is a reliability gap.

5. **Token Optimization via Context Projection** — Each LLM agent receives a role-specific data slice (not raw `context.json`); output truncation to 3000 chars for challenger roles.
   - **User Problem**: Managing LLM token costs on large repos — context projection sends only summaries per role.
   - **Module**: `src/repo_distiller/orchestrator.py` (`_project_context`, `_build_prompt`)
   - **Acceptance Criteria**:
     1. With `--consume-tokens` (default), projected context is strictly smaller than raw `context.json`.
     2. Integrator role receives full prior outputs (verified: no truncation for `role == "integrator"`).
     3. Token savings are recorded/reported (currently not — see Action Items).
   - **UX Assessment**: No token usage telemetry — users cannot audit LLM costs or detect budget blowouts.
   - **Feasibility**: **Feasible** — implementation is correct but lacks observability.

6. **IaC Parsing (Helm/Kustomize/ArgoCD)** — Detects and parses Helm charts (`Chart.yaml` + `values.yaml`), Kustomize configs (`kustomization.yaml`/`.yml`), and ArgoCD applications.
   - **User Problem**: Detecting infrastructure misconfiguration + identifying security surface area via IaC.
   - **Module**: `src/repo_distiller/iac_parser.py`
   - **Acceptance Criteria**:
     1. Helm chart detection finds `Chart.yaml` anywhere in repo tree (uses `rglob` — verified).
     2. Kustomize detection finds both `.yaml` and `.yml` variants (verified).
     3. ArgoCD app detection finds `Application.yaml`, `Application.yml`, `application.yaml` (verified — but fragile, see contradictions below).
   - **UX Assessment**: Not user-facing; output is structured JSON for downstream LLM agents.
   - **Feasibility**: **Feasible** — covers three major GitOps tools; ArgoCD detection is filename-fragile.

7. **Clean Mode Output Management** — `--clean` flag removes all intermediate artifacts (~500MB repos + context.json) after analysis, keeping only `final_report.md`.
   - **User Problem**: Disk space management after analysis runs.
   - **Module**: `src/repo_distiller/cli.py` (`_clean_intermediate`)
   - **Acceptance Criteria**:
     1. After `--clean`, only `final_report.md` remains in the output directory.
     2. Clean mode is idempotent (safe to run if files already missing).
   - **UX Assessment**: Destructive without confirmation — no `--dry-run` or `--confirm` option.
   - **Feasibility**: **Feasible** — correctly handles both files and directories via `shutil.rmtree`/`unlink`.

8. **Branch/Path Filtering** — Analyze a specific branch, tag, or subdirectory to limit scope on large repos.
   - **User Problem**: Scoped analysis on large repos to reduce time/cost.
   - **Module**: `src/repo_distiller/cli.py` (`--branch`, `--path`), `src/repo_distiller/analyzer.py` (`_should_skip`)
   - **Acceptance Criteria**:
     1. `--branch` clones and checks out the specified ref.
     2. `--path` filters AST analysis to files under the specified subdirectory.
   - **UX Assessment**: No feedback when `--path` filter excludes all files (empty analysis silently proceeds).
   - **Feasibility**: **Feasible** — `_should_skip` correctly compares file paths against filter.

9. **Agent Routing Table in Final Report** — Structured report with token-savings guide so downstream agents only read relevant sections.
   - **User Problem**: Knowledge handoff between teams — enables downstream agents (security review, test writing, docs) to consume only relevant sections.
   - **Module**: `src/repo_distiller/orchestrator.py` (OUTPUT_TEMPLATES["integrator"])
   - **Acceptance Criteria**:
     1. `final_report.md` includes a routing table at the top mapping reader goals to report sections.
     2. Each of the 8 parts is clearly labeled and self-contained.
   - **UX Assessment**: Excellent pattern for structured output consumption.
   - **Feasibility**: **Feasible** — template is well-defined.

### ⚖️ Features with Conditions

1. **Declared Multi-Language Support (Rust, Java, JavaScript)**
   - **Conditions**: Must register `LANGUAGES`, `PARSERS`, and `EXTRACTORS` entries for `.rs`, `.java`, `.js` in `ast_parser.py`, or remove them from `SUPPORTED_EXTS` in `analyzer.py` and from `pyproject.toml` dependencies. Currently these are discovered by glob, passed to the parser, and silently return `None`.
   - **Module**: `src/repo_distiller/ast_parser.py`, `src/repo_distiller/analyzer.py`, `pyproject.toml`
   - **Acceptance Criteria**:
     1. Either 3 new extractor classes exist and are registered, OR the globs/dependencies are removed.
     2. `pyproject.toml` dependencies match `SUPPORTED_EXTS` which matches `EXTRACTORS` keys — a single source of truth.
     3. A startup validation warns if declared extensions lack extractors.

2. **ArgoCD Application Detection**
   - **Conditions**: Must broaden ArgoCD manifest detection beyond exact filenames (`Application.yaml`, `Application.yml`, `application.yaml`). In practice, ArgoCD manifests are named arbitrarily (e.g., `my-app.yaml`, `argo-cd/apps/*.yaml`). Should use content-based detection (check for `apiVersion: argoproj.io/v1alpha1` and `kind: Application` in YAML files).
   - **Module**: `src/repo_distiller/iac_parser.py`
   - **Acceptance Criteria**:
     1. ArgoCD detection finds manifests regardless of filename by checking YAML content.
     2. False positives are minimized (only files with `apiVersion: argoproj.io/v1alpha1` + `kind: Application` are detected).

---

## Part 2: Architecture & Technical Decisions

### Architecture Assessment

**Overall** (from Architect): Clean layered architecture with well-separated concerns. The codebase follows a clear pipeline: CLI → Analyzer → [AST Parser | Git Analyzer | IaC Parser] → Orchestrator → Multi-agent LLM analysis. No circular dependencies detected — the import graph is a strict DAG. However, the monolithic `orchestrator.py` (~400 lines) conflates role definitions, context projection, agent invocation, and prompt templating. The project lacks test coverage entirely.

**Integrator assessment**: The architecture is sound for its intended purpose — a small, focused pipeline tool. The layered design (CLI → Analyzer → Parsers → Orchestrator) is clean and each analyzer is independently testable. The primary architectural concern is the `orchestrator.py` God class, which handles six distinct responsibilities in a single file.

### Technical Decisions

- **Decision: ThreadPoolExecutor for parallel agent execution** — Rationale: Round 1 (2 agents) and Round 2 (3 agents) run in parallel, reducing total wall time vs. sequential execution. — File: `src/repo_distiller/orchestrator.py:464-500`
- **Decision: Context projection via `_project_context()`** — Rationale: Each LLM role receives only its data slice (PM gets APIs/symbols/fix commits, Architect gets symbols/imports/couplings, etc.) to reduce token costs. — File: `src/repo_distiller/orchestrator.py:252-330`
- **Decision: `pi --print` subprocess for LLM invocation** — Rationale: Delegates to the `pi` CLI tool for LLM access rather than implementing direct API calls. — File: `src/repo_distiller/orchestrator.py:506-520`
- **Decision: `git log --name-status` for fast history mining** — Rationale: Avoids per-commit `git diff` which is very slow for large repos. — File: `src/repo_distiller/git_analyzer.py:37-41`
- **Decision: Output truncation to 3000 chars for challenger roles** — Rationale: Prevents context bloat when passing Round 1 outputs to Round 2 agents. Integrator gets full output. — File: `src/repo_distiller/orchestrator.py:550-553`
- **Decision: Lazy import of `Orchestrator` inside `_invoke_pi_agents()`** — Rationale: Masks a potential circular dependency between `analyzer.py` and `orchestrator.py`. — File: `src/repo_distiller/analyzer.py:90`

### Architectural Risks (from Architect)

- **Missing test coverage**: No `tests/` directory exists. The entire pipeline (AST parsing, Git mining, IaC parsing, multi-agent orchestration) is untested. — Severity: **high** — File: project root
- **God class — `orchestrator.py`**: Single 400+ line file handles role instructions, output templates, context projection, parallel execution, subprocess invocation, and prompt building. Violates SRP; hard to test in isolation. — Severity: **high** — File: `src/repo_distiller/orchestrator.py`
- **Mismatched language support**: `analyzer.py` lists `*.rs`, `*.java`, `.js` in `SUPPORTED_EXTS` but `ast_parser.py` has no `RustExtractor`, `JavaExtractor`, or JS extractor. These silently produce no results. — Severity: **medium** — Files: `src/repo_distiller/analyzer.py:64`, `src/repo_distiller/ast_parser.py`
- **No pipeline error recovery**: If an LLM agent fails (timeout, subprocess error), `orchestrator.py` stores `""` and continues. Downstream rounds receive empty strings, producing garbage output with no early-exit or retry. — Severity: **medium** — File: `src/repo_distiller/orchestrator.py:506-520`
- **Lazy import code smell**: `analyzer.py` does `from .orchestrator import Orchestrator` inside `_invoke_pi_agents()`, suggesting a circular dependency concern. — Severity: **low** — File: `src/repo_distiller/analyzer.py:90`
- **Unused `os` import in `git_ops.py`**: Minor dead code. — Severity: **low** — File: `src/repo_distiller/git_ops.py:2`
- **Unused `json` import in `iac_parser.py`**: Minor dead code. — Severity: **low** — File: `src/repo_distiller/iac_parser.py:1`

---

## Part 3: Security & Reliability

### Security Vulnerabilities (from Security — ALL findings preserved)

| # | Type | Location | Severity | Detail |
|---|------|----------|----------|--------|
| 1 | Prompt Injection via Untrusted Repo Content | `orchestrator.py:506-520` | high | Cloned arbitrary repo content (comments, variable names, string literals) is fed directly into LLM prompts via `subprocess.run(["pi", "--print"], ...)`. No sanitization or adversarial filtering before LLM consumption. |
| 2 | GitHub Token Leak via Exception Messages | `git_ops.py:34-40` | high | `pygit2.clone_repository()` failures print exception `e` to console. pygit2 errors can contain credentials. Token stored in plaintext in `self.token` with no secure deletion after use. |
| 3 | Token Passed Through Multiple Layers Without Secure Handling | `cli.py → analyzer.py → orchestrator.py` | medium | `GITHUB_TOKEN` envvar read by Click, passed through `Analyzer` → `GitManager`. Never masked in logs, never cleared from memory. If `context.json` captures it during debugging, it persists on disk in plaintext. |
| 4 | No Input Validation on Repository URLs | `git_ops.py:28-43` | medium | `clone_all()` accepts arbitrary URLs: supply chain attacks (malicious repos exploit tree-sitter C parser vulnerabilities), SSRF-adjacent risk (clone from internal URLs), disk exhaustion (large files, deep directories). |
| 5 | IaC Parser Lacks Secret Detection | `iac_parser.py` | medium | `_parse_helm()` flattens `values.yaml` keys but doesn't check for passwords/API keys/tokens. `_parse_kustomize()` reads patches without validating embedded secrets. `_parse_argocd()` doesn't check for `insecure: true` or insecure registries. |
| 6 | Git Path Trust Issue | `git_analyzer.py:37-41` | low | `subprocess.run()` uses list args (good — no `shell=True`), but `cwd` is set to `repo_path` from a cloned repo. Symlink tricks or unexpected characters in cloned repo path could redirect git commands. |
| 7 | LLM Output Truncation Can Mask Security Findings | `orchestrator.py:550-553` | low | When `consume_tokens=True`, challenger outputs truncated to 3000 chars. For Security role, truncated PM/Architect output could omit critical context affecting security analysis quality. |
| 8 | Missing `.gitignore` for Sensitive Output | Project root | low | Output directories (`distill-output/`, `repos/`, `context.json`) not covered by `.gitignore`. If run inside a git-tracked directory, cloned repos (potentially proprietary code) and context data could be accidentally committed. |

### API Auth Patterns

- **No auth on the tool's own interfaces**: This is a CLI tool — no HTTP endpoints, no network server, no API surface to protect.
- **GitHub auth is token-based only**: Uses `x-access-token` username with a PAT via pygit2. Doesn't support GitHub App installations, SSH keys, or OAuth. Token is expected to have `repo` scope but the tool doesn't validate or warn about minimum required scopes.
- **Target repo API endpoints are extracted but not assessed for auth**: `PythonExtractor._extract_apis()` looks for `@route`/`@api` decorators, `TypeScriptExtractor` looks for `.get()`/`.post()`/`.put()`/`.delete()`, `GoExtractor` looks for `HandleFunc`. **None check for auth middleware, guard decorators, or authorization patterns** — only route existence. Security analysis is fully delegated to the LLM.
- **IaC Helm values flattening leaks sensitivity metadata**: `_flatten_dict()` in `iac_parser.py` enumerates all keys including potentially sensitive ones (`database.password`, `redis.auth.token`). These key names are written to `context.json` which persists on disk.

### Reliability & Observability Gaps (from DFX — ALL gaps preserved)

- **Zero structured logging**: No `import logging`, `import structlog`, or equivalent anywhere. Only `rich.console` for colored stdout. No log files, no log levels, no grepability in production. — inferred from imports across all files
- **No error tracking**: Silent `except Exception` in `ast_parser.py:203` (`analyze_file()`), `orchestrator.py:506-520` (`_run_pi()`), `git_ops.py:34-40` (`clone_all()`). Failures invisible to operators.
- **No token usage telemetry**: `_project_context()` reduces payloads but never records tokens saved or consumed. Cannot audit LLM costs or detect budget blowouts. — `orchestrator.py:252-330`
- **No pipeline success metrics**: No counting of files parsed, repos cloned, agents succeeded/failed, output quality. Cannot detect data degradation (e.g., 0 AST results = 0 insight).
- **No correlation IDs**: Multi-repo analysis with no request/correlation ID. Cannot trace which repo's data produced which section of the final report.
- **No health checks on output**: `final_report.md` generated even if all 5 agents failed. Downstream consumers get empty reports with no indication of failure.
- **No exit code semantics**: CLI doesn't set non-zero exit code on partial failures. CI/CD pipelines can't detect analysis failures. — `src/repo_distiller/cli.py`
- **No error recovery in multi-agent pipeline**: `_run_pi()` returns `""` on subprocess failure/timeout, blindly fed into downstream rounds. No early-exit, retry, or alert. — `orchestrator.py:506-520`
- **Silent AST parse failures**: `ASTAnalyzer.analyze_file()` has blanket `except Exception: return None`. Malformed files silently dropped. Pipeline can produce zero AST data without warning. — `ast_parser.py:203`
- **Clone failures silently swallowed**: `GitManager.clone_all()` catches clone errors with `console.print` only. Failed repos silently excluded. No error raised, no exit code reflects failure. — `git_ops.py:34-40`
- **No retry on LLM calls**: 600s hard timeout with zero retries. Transient API hiccup permanently kills agent output. — `orchestrator.py:506-520`
- **No output validation**: Orchestrator doesn't check whether LLM outputs match templates or contain meaningful content. Empty/malformed outputs propagate to integrator. — `orchestrator.py:506-520`
- **Uncatched exception in `GitAnalyzer.__init__`**: `pygit2.Repository(str(repo_path))` throws on corrupted repos with no catch. Crashes entire analysis pipeline for one bad repo. — `git_analyzer.py:33`
- **Git log timeout silently truncates data**: 30s timeout on `git log --name-status` for large repos fires silently, returning partial commit data with no indication of truncation. — `git_analyzer.py:37-41`
- **Operational SPOF: `pi --print` subprocess**: Entire multi-agent analysis depends on `pi` CLI being available and LLM API reachable. No fallback mode (degraded analysis with just AST+Git data). — `orchestrator.py:506-520`
- **Sequential pipeline SPOF**: Pipeline runs: clone → AST → IaC → Git → JSON → Round 1 → Round 2 → Round 3. No checkpointing, no resume-from-failure, no partial results. Crash at Round 2 means restarting from clone. — `src/repo_distiller/analyzer.py:53-76`

### Maintainability Issues (from DFX)

| File | Issue | Impact |
|------|-------|--------|
| `orchestrator.py` | God class (~400 lines): role instructions, output templates, context projection, parallel execution, subprocess invocation, and prompt building all in one file. SRP violation makes targeted changes risky. | High blast radius; touched by commit `0f456bf` along with 5 other files. |
| `analyzer.py` | Thin pipeline coordinator with lazy import circular-dependency workaround (`from .orchestrator import Orchestrator` inside `_invoke_pi_agents()`). Masks architectural coupling. | Hides true dependency graph; complicates testing. |
| `git_analyzer.py` | Mixed concerns: subprocess parsing + co-change algorithm + hotspot computation in one class. | Hard to test co-change logic in isolation. |
| `pyproject.toml` | `jinja2` declared as dependency but never imported anywhere. | Dead dependency, unnecessary install time. |
| `__init__.py` | Empty — no public API, no version exposure. | No programmatic API for library consumers. |

---

## Part 4: UX Findings

### Performance Concerns (from UX — ALL findings preserved)

- **600-second subprocess timeout with zero intermediate feedback** — Users watch a blank terminal for up to 10 minutes per agent with no progress indication. — `orchestrator.py:506-520`
- **No estimated time remaining** despite having per-round timing instrumentation — timing summary only appears after everything completes. — `orchestrator.py:456-503`
- **Large operations without progress**: Cloning ~500MB repos, parsing thousands of files, and generating 420KB `context.json` all happen with no progress indication. — `git_ops.py:28-43`, `analyzer.py:64-74`
- **ThreadPoolExecutor without progress callbacks** — Round 1 (2 agents) and Round 2 (3 agents) run in parallel but users can't see which agent is currently working. — `orchestrator.py:464-500`
- **O(n^2) co-change coupling analysis** in git history with no cap on file pairs for large repos (capped at 20 files per commit but no cap on resulting pair count). — `git_analyzer.py:80-87`
- **`--clean` flag behavior** is destructive without confirmation — removes cloned repos and all intermediate data silently. — `cli.py:13-30`
- **Console pattern inconsistency**: `cli.py` and `orchestrator.py` each create their own `Console()` instance — should be injected or shared for consistent formatting/theme. — `cli.py:11`, `orchestrator.py:14`

### Accessibility Gaps (from UX — ALL findings preserved)

- **Color-dependent output**: Heavy reliance on `rich` console colors (bold blue, green, red, dim, yellow) without fallback for terminal colorblind modes or monochrome displays. — `cli.py`, `orchestrator.py`, `analyzer.py` (all use `rich.console`)
- **Emoji/special character usage**: Checkmarks, box-drawing characters, and decorative elements may not render in all terminals or assistive technologies. — `orchestrator.py:471`, `orchestrator.py:493`
- **No structured error output**: Errors are only visible in colored terminal text — no machine-readable error codes or JSON output mode for screen readers or automated accessibility tools. — All console output
- **No `--no-color` or `--json` output options** for accessibility-compliant terminal consumption. — `cli.py`
- **Confidence levels** (high/medium/low) are text-only with no numerical scoring — harder for screen readers to distinguish quickly. — `orchestrator.py` output templates

---

## Part 5: Action Items

### Action Items (prioritized, with file references)

- [ ] **[HIGH]** Add test suite for entire pipeline — AST parsing, Git mining, IaC parsing, orchestrator. — Owner: Developer — File: `tests/` (new)
- [ ] **[HIGH]** Fix silent language support mismatch — either implement `RustExtractor`, `JavaExtractor`, `JavaScriptExtractor` in `ast_parser.py`, OR remove `.rs`, `.java`, `.js` from `SUPPORTED_EXTS` in `analyzer.py` and from `pyproject.toml` dependencies. — Owner: Developer — Files: `src/repo_distiller/ast_parser.py`, `src/repo_distiller/analyzer.py`, `pyproject.toml`
- [ ] **[HIGH]** Add error recovery to multi-agent pipeline — if `_run_pi()` returns `""`, retry once, then fail-fast with non-zero exit code instead of propagating empty strings to downstream rounds. — Owner: Developer — File: `src/repo_distiller/orchestrator.py`
- [ ] **[HIGH]** Sanitize untrusted repo content before feeding to LLM — strip comments, escape special characters, or add prompt injection detection guards. — Owner: Security Engineer — File: `src/repo_distiller/orchestrator.py:506-520`
- [ ] **[HIGH]** Secure GitHub token handling — mask in logs, clear from memory after cloning, add secure deletion. Never print exception messages that could contain credentials. — Owner: Security Engineer — File: `src/repo_distiller/git_ops.py:34-40`
- [ ] **[HIGH]** Add structured logging — replace/augment `rich.console` with `logging` module for error tracking, log levels, and production grepability. — Owner: Developer — Files: all source files
- [ ] **[MEDIUM]** Split `orchestrator.py` into focused modules — `roles.py` (instructions + templates), `context.py` (projection functions), `agent_runner.py` (subprocess invocation), `orchestrator.py` (pipeline coordination only). — Owner: Architect — File: `src/repo_distiller/orchestrator.py`
- [ ] **[MEDIUM]** Add input validation on repository URLs — validate URL format, reject internal/private URLs, enforce size limits, detect symlink attacks. — Owner: Security Engineer — File: `src/repo_distiller/git_ops.py:28-43`
- [ ] **[MEDIUM]** Add IaC secret scanning — detect hardcoded passwords, API keys, tokens in `values.yaml`, Kustomize patches, and ArgoCD specs. — Owner: Security Engineer — File: `src/repo_distiller/iac_parser.py`
- [ ] **[MEDIUM]** Fix ArgoCD manifest detection — use content-based detection (check `apiVersion: argoproj.io/v1alpha1` + `kind: Application`) instead of exact filename matching. — Owner: Developer — File: `src/repo_distiller/iac_parser.py`
- [ ] **[MEDIUM]** Add progress indicators — progress bars for cloning, AST parsing, git history mining; ETA for LLM agents; per-agent progress callbacks in ThreadPoolExecutor. — Owner: UX Engineer — Files: `git_ops.py`, `analyzer.py`, `orchestrator.py`
- [ ] **[MEDIUM]** Add `--json` output mode and `--no-color` flag for accessibility and CI/CD consumption. — Owner: UX Engineer — File: `src/repo_distiller/cli.py`
- [ ] **[MEDIUM]** Add non-zero exit codes on partial failures — CLI should reflect analysis quality (0 = full success, 1 = partial failure, 2 = total failure). — Owner: Developer — File: `src/repo_distiller/cli.py`
- [ ] **[MEDIUM]** Add correlation IDs for multi-repo analysis — trace which repo's data produced which report section. — Owner: DFX Engineer — Files: `orchestrator.py`, `analyzer.py`
- [ ] **[MEDIUM]** Add token usage telemetry — record tokens saved by context projection, tokens consumed per agent, total cost. — Owner: DFX Engineer — File: `src/repo_distiller/orchestrator.py`
- [ ] **[LOW]** Remove unused imports — `os` in `git_ops.py`, `json` in `iac_parser.py`, `jinja2` from `pyproject.toml`. — Owner: Developer — Files: `git_ops.py:2`, `iac_parser.py:1`, `pyproject.toml`
- [ ] **[LOW]** Add `.gitignore` for sensitive output — exclude `distill-output/`, `repos/`, `context.json` from git tracking. — Owner: Developer — File: `.gitignore`
- [ ] **[LOW]** Add confirmation prompt for `--clean` or `--clean --force` pattern to prevent accidental data loss. — Owner: UX Engineer — File: `src/repo_distiller/cli.py`
- [ ] **[LOW]** Unify `Console()` instances — inject a shared console or use a module-level singleton for consistent formatting. — Owner: Developer — Files: `cli.py:11`, `orchestrator.py:14`
- [ ] **[LOW]** Add `--dry-run` flag for pipeline validation without LLM invocation. — Owner: Developer — File: `src/repo_distiller/cli.py`

---

## Part 6: Consensus Summary

- **Full agreement** (all 5 roles): 11 items
  1. Multi-repo analysis pipeline works as designed
  2. AST parsing for Python/TypeScript/Go is functional
  3. Git history mining with co-change analysis is correct
  4. Multi-agent 3-round orchestration is architecturally sound
  5. Context projection reduces token costs effectively
  6. IaC parsing covers Helm/Kustomize/ArgoCD
  7. Clean mode works correctly
  8. Branch/path filtering is functional
  9. Agent routing table in output is valuable
  10. Zero test coverage is a critical gap (Architect + DFX)
  11. `orchestrator.py` is a God class violating SRP (Architect + DFX)

- **Partial agreement**: 2 items
  1. **Language support mismatch** — PM and Architect identified it as a code/IaC contradiction. DFX confirmed it as a silent feature gap. Security confirmed it as a supply-chain risk (tree-sitter grammars installed but not used, creating false sense of coverage). All agree it must be fixed, but disagree on approach: implement extractors vs. remove declarations.
  2. **ArgoCD detection fragility** — PM identified it as a filename-matching issue. Architect confirmed it as a feasibility concern. Security noted it doesn't affect the tool itself (no IaC of its own) but affects target repo analysis quality. All agree it should be broadened.

- **Unresolved disputes**: None — all findings are complementary rather than contradictory. The only open question is implementation approach for the language support mismatch (add extractors vs. remove declarations), which is a judgment call for the team.

---

## Part 7: Test Coverage Gaps

### Security Regression Tests (from Security vulnerabilities)

| # | Test Name | Scenario | Expected | Target File |
|---|-----------|----------|----------|------------|
| 1 | `test_prompt_injection_sanitization` | Given a repo with prompt injection payloads in comments/strings, when analysis runs, then payloads are stripped or escaped before LLM consumption | Prompt output contains no raw repo content that could manipulate LLM behavior | `orchestrator.py` |
| 2 | `test_token_not_leaked_in_exceptions` | Given a pygit2 clone failure, when exception is caught, then console output does not contain the token or credential material | Exception message is sanitized; token is not printed | `git_ops.py` |
| 3 | `test_token_cleared_from_memory` | Given a successful clone, when cloning completes, then `GitManager.token` is cleared or None | No token reference persists after cloning | `git_ops.py` |
| 4 | `test_repo_url_validation` | Given a malformed or internal URL, when `clone_all()` is called, then the URL is rejected before cloning | Invalid URLs are rejected with clear error; no network call is made | `git_ops.py` |
| 5