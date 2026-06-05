"""Multi-agent orchestration with rebuttal rounds, context projection, and parallelism."""

import json
import shutil
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List

from rich.console import Console

console = Console()

# ─── Role Instructions ──────────────────────────────────────────────────

ROLE_INSTRUCTIONS = {
    "pm": (
        "You are a Project Manager. Analyze the provided code features (AST), Git history, "
        "and deployment context. Identify the main user problems this system solves. "
        "List features prioritized by user value. Highlight contradictions between code and "
        "deployment config."
    ),
    "architect": (
        "You are a Software Architect. Review code structure (AST) and infrastructure (IaC). "
        "Assess technical feasibility. Check tech stack alignment with conventions. "
        "Identify architectural risks — circular dependencies, tight coupling (from Git co-change)."
    ),
    "dfx": (
        "You are a DFX Engineer (Reliability, Maintainability, Observability). "
        "Challenge the proposals. Look for SPOFs in IaC, inadequate logging/error handling "
        "(inferred from AST/imports), and maintainability issues like high-churn files."
    ),
    "ux": (
        "You are a UX Engineer. Focus on user experience. Check for UI consistency patterns "
        "in AST (component reuse). Challenge proposals that degrade performance or break "
        "design consistency. Look for hardcoded values and accessibility gaps."
    ),
    "security": (
        "You are a Security Engineer. Focus on compliance, data privacy, and vulnerabilities. "
        "Check for exposed secrets in IaC. Analyze API endpoints (from AST) for auth patterns. "
        "Challenge proposals that introduce security risks."
    ),
    "integrator": (
        "You are the Integrator. Review all proposals and critiques from PM, Architect, DFX, "
        "UX, and Security. Your job is to produce a comprehensive report that PRESERVES "
        "critical findings from every role — do NOT discard detailed analysis. "
        "Specifically: keep all user problems (PM), all architecture risks (Architect), "
        "all security vulnerabilities (Security), all observability gaps (DFX), "
        "and all UX/performance/accessibility findings (UX). "
        "Resolve conflicts, assign features to modules, define acceptance criteria, "
        "and produce actionable items with file references."
    ),
}

# ─── Structured Output Templates ────────────────────────────────────────

OUTPUT_TEMPLATES = {
    "pm": """\n
### 📋 Features Identified
1. [Feature name] — [Brief description]

### 🎯 User Problems Solved
- [Problem] → [How the code addresses it]

### ⚠️ Contradictions (Code vs IaC)
- [Contradiction] (or "None found")

### 📊 Confidence
- **Level**: high / medium / low
- **Reasoning**: [Brief explanation]
""",
    "architect": """\n
### 🏗️ Architecture Assessment
- [Overall assessment]

### ✅ Technical Feasibility
1. [Feature] → Feasible / At-Risk — [Reason]

### ⚠️ Architectural Risks
- [Risk type]: [Description] (severity: high / medium / low)

### 🔗 Coupling & Dependencies (from Git)
- [Findings]

### 📊 Confidence
- **Level**: high / medium / low
- **Reasoning**: [Brief explanation]
""",
    "dfx": """\n
### 🔧 Reliability Assessment
- [Findings]

### 📈 Maintainability Issues
- [High-churn files] → [Impact]

### 🚨 Single Points of Failure (from IaC)
- [SPOF findings] (or "None found")

### 📝 Observability Gaps
- [Logging / error handling gaps]

### 📊 Confidence
- **Level**: high / medium / low
- **Reasoning**: [Brief explanation]
""",
    "ux": """\n
### 🎨 UX Assessment
- [Overall UX quality]

### 🧩 UI Consistency Patterns
- [Component reuse findings from AST]

### ⚡ Performance Concerns
- [Issues that degrade UX]

### ♿ Accessibility Gaps
- [Missing accessibility features] (or "Cannot assess without UI code")

### 📊 Confidence
- **Level**: high / medium / low
- **Reasoning**: [Brief explanation]
""",
    "security": """\n
### 🔐 Security Assessment
- [Overall security posture]

### ⚠️ Vulnerabilities Found
- [Type]: [Location] — Severity: critical / high / medium / low

### 🗝️ Secret / Config Risks (from IaC)
- [Exposed secrets or misconfigurations] (or "None found")

### 🛡️ API Auth Patterns
- [Findings from AST API endpoints]

### 📊 Confidence
- **Level**: high / medium / low
- **Reasoning**: [Brief explanation]
""",
    "integrator": """\n
---

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
For each feature, include:
1. **[Feature name]** — [Description]
   - **User Problem**: [Which user problem this solves, from PM analysis]
   - **Module**: [src/app/... or etl/... or ...]
   - **Acceptance Criteria**: [1-3 measurable "Done" conditions]
   - **UX Assessment**: [Is the UX optimal? Any concerns from UX analysis]
   - **Feasibility**: [Feasible / At-Risk — from Architect]

### ⚖️ Features with Conditions
1. **[Feature name]**
   - **Conditions**: [What must be done before this is production-ready]
   - **Module**: [src/app/... or etl/... or ...]
   - **Acceptance Criteria**: [1-3 measurable conditions]

---

## Part 2: Architecture & Technical Decisions

### 🏗️ Architecture Assessment
- [Overall assessment from Architect, preserved verbatim or summarized]

### 🔑 Technical Decisions
- **[Decision]**: [Rationale] — [File reference: src/... or etl/...]

### ⚠️ Architectural Risks (from Architect)
- **[Risk]**: [Description] — Severity: high / medium / low — [File reference]

---

## Part 3: Security & Reliability

### 🔐 Security Vulnerabilities (from Security — ALL findings preserved)
| # | Type | Location | Severity | Detail |
|---|------|----------|----------|--------|
| | [Type] | [File:line or config] | [severity] | [Detail] |

### 🛡️ API Auth Patterns
- [Summary from Security analysis]

### 🔧 Reliability & Observability Gaps (from DFX — ALL gaps preserved)
- [Gap]: [Description] — [File reference or "inferred from imports"]

### 📈 Maintainability Issues (from DFX)
- [File]: [Issue] — [Impact]

---

## Part 4: UX Findings

### ⚡ Performance Concerns (from UX — ALL findings preserved)
- [Concern]: [Description] — [File reference]

### ♿ Accessibility Gaps (from UX — ALL findings preserved)
- [Gap]: [Description] — [File reference or "requires JSX inspection"]

---

## Part 5: Action Items

### 📋 Action Items (prioritized, with file references)
- [ ] **[HIGH]** [Action] — Owner: [role] — File: [src/... or config]
- [ ] **[MEDIUM]** [Action] — Owner: [role] — File: [src/... or config]
- [ ] **[LOW]** [Action] — Owner: [role] — File: [src/... or config]

---

## Part 6: Consensus Summary

- **Full agreement**: X items
- **Partial agreement**: X items
- **Unresolved disputes**: [List or "None"]

---

## Part 7: Test Coverage Gaps

Derive missing test cases from all findings. For each gap, provide test name, scenario, expected outcome, and target file.

### 🔐 Security Regression Tests (from Security vulnerabilities)
| # | Test Name | Scenario | Expected | Target File |
|---|-----------|----------|----------|------------|
| | [Test name] | [Given/When] | [Then] | [File] |

### ⚡ Performance & Integration Tests (from UX + DFX)
| # | Test Name | Scenario | Expected | Target File |
|---|-----------|----------|----------|------------|
| | [Test name] | [Given/When] | [Then] | [File] |

### 🏗️ Architecture & Refactoring Tests (from Architect risks)
| # | Test Name | Scenario | Expected | Target File |
|---|-----------|----------|----------|------------|
| | [Test name] | [Given/When] | [Then] | [File] |

### ♿ Accessibility Tests (from UX gaps)
| # | Test Name | Scenario | Expected | Target File |
|---|-----------|----------|----------|------------|
| | [Test name] | [Given/When] | [Then] | [File] |

### ⚠️ Error Path & Boundary Tests (from DFX + Architect)
| # | Test Name | Scenario | Expected | Target File |
|---|-----------|----------|----------|------------|
| | [Test name] | [Given/When] | [Then] | [File] |

---

## Part 8: Documentation Gaps

Identify missing documentation based on code analysis. For each gap, provide doc type, scope, priority, and source files to reference.

### 📖 Architecture & Design Docs
- **[Doc Type]**: [What to document] — Scope: [What to cover] — Priority: high/medium/low — Reference: [Source files]

### 🔧 API & Integration Docs
- **[Doc Type]**: [What to document] — Scope: [What to cover] — Priority: high/medium/low — Reference: [Source files]

### 🚀 Deployment & Ops Docs
- **[Doc Type]**: [What to document] — Scope: [What to cover] — Priority: high/medium/low — Reference: [Source files / config files]

### 📊 Data Model & Schema Docs
- **[Doc Type]**: [What to document] — Scope: [What to cover] — Priority: high/medium/low — Reference: [schema.sql / types files]

### 🔐 Security & Compliance Docs
- **[Doc Type]**: [What to document] — Scope: [What to cover] — Priority: high/medium/low — Reference: [Source files / config]
""",
}

# ─── Context Projection ─────────────────────────────────────────────────

def _project_context(context: Dict, role: str) -> Dict:
    """Return only the data slice relevant to a specific role, saving tokens."""
    projected = {}
    for repo_name, data in context.items():
        ast_files = data.get("ast", [])
        git_data = data.get("git", {})
        iac_data = data.get("iac", {})
        dep_data = data.get("dependencies", {})
        config_data = data.get("config", {})
        schema_data = data.get("schema", {})
        deploy_data = data.get("deployment", {})
        cg_data = data.get("call_graph", {})
        ef_data = data.get("error_flow", {})
        infra_data = data.get("infra", {})
        proj: Dict = {}

        if role == "pm":
            proj["api_endpoints"] = _collect_apis(ast_files)
            proj["swagger_docs"] = _collect_swagger(ast_files)
            proj["symbol_summary"] = _summarize_symbols(ast_files)
            proj["models"] = _collect_models(ast_files)[:50]
            proj["fix_commits"] = [
                {"hash": c["hash"], "message": c["message"], "files": len(c.get("files", []))}
                for c in git_data.get("commits", []) if c.get("is_fix")
            ][:20]
            proj["iac_overview"] = _summarize_iac(iac_data)
            proj["external_services"] = dep_data.get("external_services", [])
            proj["dependency_summary"] = dep_data.get("dependency_summary", {})
            proj["service_connections"] = config_data.get("service_connections", [])
            proj["api_schemas"] = schema_data.get("api_schemas", {})
            proj["state_machines"] = schema_data.get("state_machines", [])
            proj["deployment_topology"] = deploy_data.get("topology", {})
            proj["call_graph_summary"] = cg_data.get("summary", {})
            proj["top_callers"] = _top_callers(cg_data, n=15)
            proj["error_flow_summary"] = ef_data.get("summary", {})
            proj["unhandled_errors"] = _unhandled_errors(ef_data, n=10)
            proj["error_patterns"] = ef_data.get("error_patterns", [])[:10]

        elif role == "architect":
            proj["symbols"] = _collect_symbols(ast_files)
            proj["imports"] = _top_imports(ast_files, n=30)
            proj["models"] = _collect_models(ast_files)[:80]
            proj["constants"] = _collect_constants(ast_files)[:50]
            proj["couplings"] = git_data.get("couplings", [])[:10]
            proj["hotspots"] = git_data.get("hotspots", [])[:10]
            proj["iac_overview"] = _summarize_iac(iac_data)
            proj["dependencies"] = dep_data
            proj["config_summary"] = config_data.get("config_summary", {})
            proj["er_diagram"] = schema_data.get("er_diagram", {})
            proj["state_machines"] = schema_data.get("state_machines", [])
            proj["state_machines_ast"] = schema_data.get("state_machines_ast", {})
            proj["deployment"] = deploy_data
            proj["deployment_topology"] = deploy_data.get("topology", {})
            proj["call_graph"] = cg_data
            proj["error_flow"] = ef_data
            proj["infra_deployments"] = infra_data

        elif role == "dfx":
            proj["logging_imports"] = _filter_imports(ast_files, [
                "log", "logging", "logger", "structlog", "logrus", "zap",
                "error", "exception", "traceback",
            ])
            proj["hotspots"] = git_data.get("hotspots", [])[:15]
            proj["large_commits"] = [
                {"hash": c["hash"], "message": c["message"], "insertions": c["insertions"], "deletions": c["deletions"]}
                for c in git_data.get("commits", []) if c.get("is_large")
            ][:10]
            proj["iac_full"] = iac_data
            proj["external_services"] = dep_data.get("external_services", [])
            proj["sensitive_configs"] = config_data.get("sensitive_values", [])
            proj["feature_flags"] = config_data.get("feature_flags", [])[:30]
            proj["deployment"] = deploy_data
            proj["deployment_topology"] = deploy_data.get("topology", {})
            proj["infra_deployments"] = infra_data
            proj["error_flow_summary"] = ef_data.get("summary", {})
            proj["unhandled_errors"] = _unhandled_errors(ef_data, n=15)
            proj["error_patterns"] = ef_data.get("error_patterns", [])[:15]

        elif role == "ux":
            proj["symbols"] = _collect_symbols(ast_files)
            proj["api_endpoints"] = _collect_apis(ast_files)
            proj["swagger_docs"] = _collect_swagger(ast_files)
            proj["api_schemas"] = schema_data.get("api_schemas", {})
            proj["fix_commits"] = [
                {"hash": c["hash"], "message": c["message"]}
                for c in git_data.get("commits", []) if c.get("is_fix")
            ][:15]
            proj["file_count"] = len(ast_files)
            proj["models"] = _collect_models(ast_files)[:30]
            proj["state_machines"] = schema_data.get("state_machines", [])
            proj["api_schemas"] = schema_data.get("api_schemas", {})
            proj["error_flow_summary"] = ef_data.get("summary", {})

        elif role == "security":
            proj["api_endpoints"] = _collect_apis(ast_files)
            proj["swagger_docs"] = _collect_swagger(ast_files)
            proj["iac_full"] = iac_data
            proj["security_imports"] = _filter_imports(ast_files, [
                "auth", "crypto", "hash", "security", "jwt", "token",
                "password", "secret", "ssl", "tls", "https",
                "validate", "sanitize", "csrf", "cors",
            ])
            proj["all_imports_sample"] = _top_imports(ast_files, n=15)
            proj["external_services"] = dep_data.get("external_services", [])
            proj["sensitive_configs"] = config_data.get("sensitive_values", [])
            proj["service_connections"] = config_data.get("service_connections", [])
            proj["version_conflicts"] = dep_data.get("version_conflicts", [])
            proj["api_schemas"] = schema_data.get("api_schemas", {})
            proj["deployment"] = deploy_data
            proj["deployment_topology"] = deploy_data.get("topology", {})
            proj["infra_deployments"] = infra_data
            proj["error_flow_summary"] = ef_data.get("summary", {})
            proj["unhandled_errors"] = _unhandled_errors(ef_data, n=10)
            proj["error_patterns"] = ef_data.get("error_patterns", [])[:10]

        elif role == "integrator":
            proj["summary"] = {
                "total_files_analyzed": len(ast_files),
                "total_symbols": sum(len(f.get("symbols", [])) for f in ast_files),
                "total_apis": sum(len(f.get("apis", [])) for f in ast_files),
                "total_models": sum(len(f.get("models", [])) for f in ast_files),
                "total_constants": sum(len(f.get("constants", [])) for f in ast_files),
                "total_commits": len(git_data.get("commits", [])),
                "fix_ratio": _fix_ratio(git_data.get("commits", [])),
                "hotspots_top5": git_data.get("hotspots", [])[:5],
                "couplings_top5": git_data.get("couplings", [])[:5],
                "iac_summary": _summarize_iac(iac_data),
                "total_entities": schema_data.get("er_diagram", {}).get("total_entities", 0),
                "total_relationships": schema_data.get("er_diagram", {}).get("total_relationships", 0),
                "total_state_machines": len(schema_data.get("state_machines", [])),
                "total_services": deploy_data.get("topology", {}).get("total_services", 0),
                "total_call_graph_symbols": cg_data.get("summary", {}).get("total_symbols", 0),
                "total_call_graph_calls": cg_data.get("summary", {}).get("total_calls", 0),
                "resolved_calls": cg_data.get("summary", {}).get("total_resolved", 0),
                "unhandled_errors": ef_data.get("summary", {}).get("unhandled_errors", 0),
                "infra_environments": infra_data.get("summary", {}).get("total_environments", 0),
                "infra_components": infra_data.get("summary", {}).get("total_components", 0),
            }
            proj["external_services"] = dep_data.get("external_services", [])
            proj["version_conflicts"] = dep_data.get("version_conflicts", [])
            proj["sensitive_configs"] = config_data.get("sensitive_values", [])
            proj["service_connections"] = config_data.get("service_connections", [])
            proj["er_diagram"] = schema_data.get("er_diagram", {})
            proj["state_machines"] = schema_data.get("state_machines", [])
            proj["api_schemas"] = schema_data.get("api_schemas", {})
            proj["deployment_topology"] = deploy_data.get("topology", {})
            proj["infra_deployments"] = infra_data

        projected[repo_name] = proj
    return projected


def _collect_apis(ast_files: list) -> list:
    apis = []
    for f in ast_files:
        for api in f.get("apis", []):
            entry = {"file": f.get("path"), **api}
            # Include swagger summary if present (don't dump full swagger)
            if "swagger" in api:
                sw = api["swagger"]
                entry["swagger"] = {
                    "summary": sw.get("summary", ""),
                    "tags": sw.get("tags", []),
                }
            apis.append(entry)
    return apis


def _collect_swagger(ast_files: list) -> list:
    """Collect swagger documentation from all files."""
    docs = []
    for f in ast_files:
        for doc in f.get("swagger_docs", []):
            docs.append({"file": f.get("path"), **doc})
    return docs


def _collect_models(ast_files: list) -> list:
    """Collect data models (structs, interfaces) with fields."""
    models = []
    for f in ast_files:
        for m in f.get("models", []):
            models.append({"file": f.get("path"), **m})
    return models


def _collect_constants(ast_files: list) -> list:
    """Collect constants (useful for state machine detection)."""
    constants = []
    for f in ast_files:
        for c in f.get("constants", []):
            constants.append({"file": f.get("path"), **c})
    return constants


def _collect_symbols(ast_files: list) -> list:
    symbols = []
    for f in ast_files:
        for sym in f.get("symbols", []):
            symbols.append({"file": f.get("path"), **sym})
    return symbols[:200]  # cap to avoid huge payloads


def _summarize_symbols(ast_files: list) -> Dict[str, int]:
    types = Counter()
    for f in ast_files:
        for sym in f.get("symbols", []):
            types[sym.get("type", "unknown")] += 1
    return dict(types)


def _top_imports(ast_files: list, n: int = 20) -> list:
    imports = []
    for f in ast_files:
        for imp in f.get("imports", []):
            if isinstance(imp, dict):
                imports.append(imp.get("path", str(imp)))
            else:
                imports.append(imp)
    return [imp for imp, _ in Counter(imports).most_common(n)]


def _filter_imports(ast_files: list, keywords: list) -> list:
    relevant = set()
    for f in ast_files:
        for imp in f.get("imports", []):
            imp_str = imp.get("path", str(imp)) if isinstance(imp, dict) else imp
            imp_lower = imp_str.lower()
            if any(kw in imp_lower for kw in keywords):
                relevant.add(imp_str)
    return sorted(relevant)


def _summarize_iac(iac_data: Dict) -> Dict:
    return {
        "helm_charts": [{"name": c.get("name"), "version": c.get("version")} for c in iac_data.get("helm", [])],
        "kustomize_configs": [{"name": c.get("name")} for c in iac_data.get("kustomize", [])],
        "argocd_apps": [{"name": c.get("name")} for c in iac_data.get("argocd", [])],
    }


def _fix_ratio(commits: list) -> float:
    if not commits:
        return 0.0
    fixes = sum(1 for c in commits if c.get("is_fix"))
    return round(fixes / len(commits), 2)


def _top_callers(cg_data: dict, n: int = 15) -> list:
    """Get the most-called functions from call graph data."""
    from collections import Counter
    resolved = cg_data.get("resolved_calls", [])
    targets = Counter()
    for call in resolved:
        if call.get("resolved"):
            key = call.get("target_key", "")
            if key:
                targets[key] += 1
    return [{"target": t, "call_count": c} for t, c in targets.most_common(n)]


def _unhandled_errors(ef_data: dict, n: int = 10) -> list:
    """Get unhandled errors from error flow data."""
    chains = ef_data.get("error_chains", [])
    unhandled = [c for c in chains if not c.get("has_handler")]
    return unhandled[:n]


# ─── Orchestrator ───────────────────────────────────────────────────────

class Orchestrator:

    def __init__(self, context_file: Path, output_dir: Path, consume_tokens: bool = True):
        self.context_file = context_file
        self.output_dir = output_dir
        self.consume_tokens = consume_tokens

    def run(self):
        t_start = time.time()
        context_data = json.loads(self.context_file.read_text())
        results: Dict[str, str] = {}
        timings: Dict[str, float] = {}

        # ── Round 1: Proponents (PM + Architect) — parallel ──────────
        console.print("[bold blue]Round 1: Proponents (PM & Architect) — parallel[/bold blue]")
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(self._invoke_agent, "pm", context_data): "pm",
                executor.submit(self._invoke_agent, "architect", context_data): "architect",
            }
            for future in as_completed(futures):
                role = futures[future]
                results[role] = future.result()
                status = "[green]✓[/green]" if results[role] else "[red]✗[/red]"
                console.print(f"  {status} {role}")
        timings["round1_proponents"] = time.time() - t0

        # ── Round 2: Challengers (DFX, UX, Security) — parallel ──────
        console.print("[bold blue]Round 2: Challengers (DFX, UX, Security) — parallel[/bold blue]")
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(
                    self._invoke_agent, "dfx", context_data,
                    results["pm"], results["architect"]
                ): "dfx",
                executor.submit(
                    self._invoke_agent, "ux", context_data,
                    results["pm"], results["architect"]
                ): "ux",
                executor.submit(
                    self._invoke_agent, "security", context_data,
                    results["pm"], results["architect"]
                ): "security",
            }
            for future in as_completed(futures):
                role = futures[future]
                results[role] = future.result()
                status = "[green]✓[/green]" if results[role] else "[red]✗[/red]"
                console.print(f"  {status} {role}")
        timings["round2_challengers"] = time.time() - t0

        # ── Round 3: Integrator (Final Consensus) ────────────────────
        console.print("[bold blue]Round 3: Integrator (Final Consensus)[/bold blue]")
        t0 = time.time()
        results["integrator"] = self._invoke_agent(
            "integrator", context_data,
            results["pm"], results["architect"],
            results["dfx"], results["ux"], results["security"],
        )
        timings["round3_integrator"] = time.time() - t0

        timings["total_orchestration"] = time.time() - t_start

        console.print("[bold green]✓ Final report generated: final_report.md[/bold green]")
        console.print("")
        console.print("[bold yellow]━━━ Timing Summary ━━━[/bold yellow]")
        console.print(f"  Round 1 (Proponents):  {timings['round1_proponents']:.1f}s")
        console.print(f"  Round 2 (Challengers): {timings['round2_challengers']:.1f}s")
        console.print(f"  Round 3 (Integrator):  {timings['round3_integrator']:.1f}s")
        console.print(f"  [bold]Total:               {timings['total_orchestration']:.1f}s[/bold]")
        console.print("")
        shutil.copy2(self.output_dir / "integrator_output.md", self.output_dir / "final_report.md")

    # ── Agent invocation ──────────────────────────────────────────────

    def _invoke_agent(self, role: str, context: Dict, *previous_outputs: str) -> str:
        output_file = self.output_dir / f"{role}_output.md"
        prompt = self._build_prompt(role, context, previous_outputs)
        return self._run_pi(prompt, output_file, role)

    def _run_pi(self, prompt: str, output_file: Path, label: str) -> str:
        """Run pi with the prompt via stdin. Returns stdout content."""
        t0 = time.time()
        console.print(f"  Running {label}...")
        try:
            result = subprocess.run(
                ["pi", "--print"],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=600,
            )
            elapsed = time.time() - t0
            if result.returncode != 0:
                console.print(f"  [red]✗ {label} failed ({elapsed:.1f}s): {result.stderr[:200]}[/red]")
                return ""
            output_file.write_text(result.stdout)
            console.print(f"  ✓ {label} completed in {elapsed:.1f}s")
            return result.stdout
        except subprocess.TimeoutExpired:
            elapsed = time.time() - t0
            console.print(f"  [red]✗ {label} timed out after {elapsed:.1f}s[/red]")
            return ""
        except Exception as e:
            elapsed = time.time() - t0
            console.print(f"  [red]✗ {label} error ({elapsed:.1f}s): {e}[/red]")
            return ""

    # ── Prompt building ───────────────────────────────────────────────

    def _build_prompt(self, role: str, context: Dict, previous_outputs: tuple) -> str:
        instruction = ROLE_INSTRUCTIONS[role]
        template = OUTPUT_TEMPLATES[role]

        # Project context to role-relevant slice
        ctx = _project_context(context, role) if self.consume_tokens else context
        ctx_str = json.dumps(ctx, indent=2, default=str)

        prompt = f"{instruction}\n\n### Context Data\n```json\n{ctx_str}\n```"

        if previous_outputs:
            prompt += "\n\n### Previous Outputs\n"
            for i, output in enumerate(previous_outputs):
                if not output:
                    continue
                # Integrator gets full role outputs; others get truncated
                if role == "integrator":
                    prompt += f"\n--- {self._role_label(i)} Output ---\n{output}\n"
                else:
                    trimmed = (
                        output[:3000] + "\n... (truncated)"
                        if self.consume_tokens and len(output) > 3000
                        else output
                    )
                    prompt += f"\n--- {self._role_label(i)} Output ---\n{trimmed}\n"

        prompt += f"\n\n### Required Output Format\nPlease structure your response as follows:{template}"
        return prompt

    @staticmethod
    def _role_label(index: int) -> str:
        """Map output index to role name for clarity."""
        labels = ["PM", "Architect", "DFX", "UX", "Security", "PM Rebuttal", "Architect Rebuttal"]
        return labels[index] if index < len(labels) else f"Output {index + 1}"
