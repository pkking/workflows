"""Multi-agent orchestration with rebuttal rounds, context projection, and subagent chain."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from rich.console import Console

console = Console()

# Agent role IDs (defined as .md files in .agents/)
AGENT_ROLES = ["pm", "architect", "dfx", "ux", "security", "integrator"]

# Chain rounds: which agents run in each round, and their dependencies
CHAIN_ROUNDS = [
    # Round 1: parallel proponents (no dependencies)
    {"parallel": ["pm", "architect"]},
    # Round 2: parallel challengers (depend on Round 1)
    {"parallel": ["dfx", "ux", "security"]},
    # Round 3: integrator (depends on all)
    {"serial": ["integrator"]},
]

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
            repomix_secrets = data.get("repomix_secrets", [])
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
            proj["repomix_secrets"] = repomix_secrets

        elif role == "integrator":
            repomix_secrets = data.get("repomix_secrets", [])
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
                "repomix_secret_count": len(repomix_secrets),
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
            if repomix_secrets:
                proj["repomix_secrets"] = repomix_secrets

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

    # Required pi extensions — reference list; actual installation is handled by `mise run setup`.
    DEFAULT_EXTENSIONS = [
        "github:Fornace/pi-alibaba-models@main",
        "pi-web-access",
        "pi-subagents",
    ]

    def __init__(self, context_file: Path, output_dir: Path, consume_tokens: bool = True,
                 output_format: str = "flat", repo_url: str = "", base_commit: str = "",
                 repomix_pack: str = "",
                 pi_provider: Optional[str] = None, pi_model: Optional[str] = None,
                 pi_api_key: Optional[str] = None, pi_extensions: Optional[str] = None):
        self.context_file = context_file
        self.output_dir = output_dir
        self.consume_tokens = consume_tokens
        self.output_format = output_format  # "flat" or "docs"
        self.repo_url = repo_url
        self.base_commit = base_commit
        self.repomix_pack = repomix_pack
        self.pi_provider = pi_provider
        self.pi_model = pi_model
        self.pi_api_key = pi_api_key
        # Extensions: default uses upstream pi-alibaba-models from Fornace
        ext_str = pi_extensions or ",".join(self.DEFAULT_EXTENSIONS)
        self.pi_extensions = [e.strip() for e in ext_str.split(",") if e.strip()]
        # Resolved extension file paths (populated by _preflight_check)
        self._extension_paths: List[str] = []

    def _sync_models_json(self):
        """Write project's `.pi/models.json` to a temp file.
        Path stored in `self._tmp_models_json` — used by `_run_pi` to tell pi
        to load it via a temp extension that registers the provider."""
        self._tmp_models_json: Optional[str] = None
        repo_root = self._find_repo_root()
        project_models = repo_root / ".pi" / "models.json"
        if not project_models.exists():
            return

        project_data = json.loads(project_models.read_text())
        project_providers = project_data.get("providers", {})
        if not project_providers:
            return

        # Generate a temp .ts extension that registers the providers from models.json
        # using pi's registerProvider API — no user config touched.
        self._tmp_models_json = self._write_model_registration_extension(
            project_providers)
        console.print(
            f"  [green]✓ Models from .pi/models.json registered via temp extension[/green]"
        )

    def _write_model_registration_extension(
        self, providers: Dict
    ) -> str:
        """Generate a minimal .ts extension that registers custom providers
        from the project's models.json. API key is embedded directly (not
        via env var) for reliability in subprocess context."""
        import tempfile

        ts_lines = [
            "// Auto-generated by repo-distiller — registers project models",
            "import type { ExtensionAPI, ProviderModelConfig } from \"@earendil-works/pi-coding-agent\";",
            "",
            "export default async function(pi: ExtensionAPI) {",
        ]

        for name, prov in providers.items():
            base_url = prov.get("baseUrl", "")
            api = prov.get("api", "openai-completions")
            api_key_raw = prov.get("apiKey", "")
            # Resolve env var references ($VAR) in the key
            if api_key_raw.startswith("$"):
                env_var = api_key_raw.lstrip("$")
                api_key = os.environ.get(env_var, api_key_raw)
            else:
                api_key = api_key_raw
            # Fall back to pi_api_key if key is still an unresolved env var
            if api_key.startswith("$"):
                api_key = self.pi_api_key if self.pi_api_key else ""
            auth_header = "authHeader: true," if api_key else ""
            models_list = prov.get("models", [])

            # Build model config objects as TS
            model_entries = []
            for m in models_list:
                parts = [f'id: "{m["id"]}"']
                if "name" in m:
                    parts.append(f'name: "{m["name"]}"')
                if m.get("reasoning"):
                    parts.append("reasoning: true")
                if "input" in m:
                    parts.append(f'input: {json.dumps(m["input"])}')
                if "contextWindow" in m:
                    parts.append(f'contextWindow: {m["contextWindow"]}')
                if "maxTokens" in m:
                    parts.append(f'maxTokens: {m["maxTokens"]}')
                if "cost" in m:
                    parts.append(f'cost: {json.dumps(m["cost"])}')
                if "compat" in m:
                    parts.append(f'compat: {json.dumps(m["compat"])}')
                if "thinkingLevelMap" in m:
                    parts.append(f'thinkingLevelMap: {json.dumps(m["thinkingLevelMap"])}')
                model_entries.append("{" + ", ".join(parts) + "}")

            ts_lines.append(f'  pi.registerProvider("{name}", {{')
            ts_lines.append(f'    baseUrl: "{base_url}",')
            ts_lines.append(f'    api: "{api}",')
            if api_key:
                ts_lines.append(f'    apiKey: "{api_key}",')
            if auth_header:
                ts_lines.append(f'    authHeader: true,')
            ts_lines.append(f'    models: [')
            for entry in model_entries:
                ts_lines.append(f"      {entry},")
            ts_lines.append(f'    ],')
            ts_lines.append(f'  }});')

        ts_lines.append("}")
        ts_content = "\n".join(ts_lines) + "\n"

        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".ts",
            prefix="repo-distiller-models-",
            delete=False,
        )
        tmp.write(ts_content)
        tmp.close()
        return tmp.name

    def _ensure_extensions(self):
        """Resolve extension file paths for use with `pi --no-extensions -e <path>`.
        Extensions must be pre-installed via `mise run setup`. Fails fast if missing."""
        repo_root = self._find_repo_root()

        for pkg in self.pi_extensions:
            if pkg.startswith("github:"):
                pkg_ref = pkg[len("github:"):].split("@")[0]
                pkg_dir = repo_root / ".pi" / "git" / "github.com" / pkg_ref
            elif pkg.startswith("https://"):
                pkg_ref = pkg[len("https:"):].split("@")[0]
                pkg_dir = repo_root / ".pi" / "git" / pkg_ref
            else:
                # Strip @version/@tag suffix, handle scoped packages (@scope/pkg@ver)
                if pkg.startswith("@"):
                    # scoped: @scope/package@version -> @scope/package
                    pkg_name = pkg.rsplit("@", 1)[0] if "@" in pkg[1:] else pkg
                else:
                    # unscoped: package@version -> package
                    pkg_name = pkg.split("@")[0]
                pkg_dir = repo_root / ".pi" / "npm" / "node_modules" / pkg_name

            if not pkg_dir.exists():
                raise RuntimeError(
                    f"Extension '{pkg}' not found in project scope.\n"
                    f"Run 'mise run setup' to install, or manually: pi install {pkg} -l"
                )

            # Resolve extension file paths from package.json
            pkg_json_path = pkg_dir / "package.json"
            if pkg_json_path.exists():
                pkg_json = json.loads(pkg_json_path.read_text())
                ext_files = pkg_json.get("pi", {}).get("extensions", [])
                for ext_rel in ext_files:
                    ext_clean = ext_rel.lstrip("./")
                    ext_full = (pkg_dir / ext_clean).resolve()
                    if ext_full.exists():
                        self._extension_paths.append(str(ext_full))
                        console.print(f"  [green]✓ Extension loaded: {ext_rel}[/green]")
                    else:
                        console.print(f"  [yellow]⚠ Extension file not found: {ext_rel}[/yellow]")
            else:
                console.print(f"  [yellow]⚠ No package.json in {pkg}, skipping extension resolution[/yellow]")

        if not self._extension_paths:
            console.print("  [yellow]⚠ No extension files resolved — pi will run with --no-extensions only[/yellow]")
        else:
            console.print(f"  [green]✓ {len(self._extension_paths)} extension file(s) ready[/green]")

    def _find_repo_root(self) -> Path:
        """Find the repository root (where .git or AGENTS.md lives)."""
        curr = self.output_dir.resolve()
        for _ in range(10):
            if (curr / ".git").exists() or (curr / "AGENTS.md").exists():
                return curr
            parent = curr.parent
            if parent == curr:
                break
            curr = parent
        return self.output_dir.resolve()

    def _preflight_check(self):
        """Verify all prerequisites before starting the pipeline. Fails fast."""
        errors = []

        # Check pi CLI is callable
        try:
            result = subprocess.run(
                ["pi", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                errors.append(f"pi CLI returned non-zero exit code: {result.stderr.strip()}")
            else:
                version = result.stdout.strip()
                console.print(f"  [green]✓ pi {version} available[/green]")
        except FileNotFoundError:
            errors.append("pi CLI not found in PATH — install it before running analysis")
        except subprocess.TimeoutExpired:
            errors.append("pi CLI --version timed out")

        # Merge project models.json into user models.json so pi loads repo-defined models
        self._sync_models_json()

        # Check / install pi extensions
        self._ensure_extensions()

        # Check tree-sitter grammars are available
        try:
            import tree_sitter_python
            console.print("  [green]✓ tree-sitter-python grammar available[/green]")
        except ImportError:
            errors.append("tree-sitter-python grammar not installed — run: pip install tree-sitter-python")

        try:
            import tree_sitter_typescript
            console.print("  [green]✓ tree-sitter-typescript grammar available[/green]")
        except ImportError:
            errors.append("tree-sitter-typescript grammar not installed — run: pip install tree-sitter-typescript")

        try:
            import tree_sitter_go
            console.print("  [green]✓ tree-sitter-go grammar available[/green]")
        except ImportError:
            errors.append("tree-sitter-go grammar not installed — run: pip install tree-sitter-go")

        # Check git is accessible
        try:
            result = subprocess.run(
                ["git", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                errors.append(f"git returned non-zero exit code: {result.stderr.strip()}")
            else:
                console.print(f"  [green]✓ {result.stdout.strip()}[/green]")
        except FileNotFoundError:
            errors.append("git not found in PATH")
        except subprocess.TimeoutExpired:
            errors.append("git --version timed out")

        # Check context file exists
        if not self.context_file.exists():
            errors.append(f"Context file not found: {self.context_file}")
        else:
            console.print(f"  [green]✓ Context file: {self.context_file.name}[/green]")

        if errors:
            console.print("[bold red]Preflight checks failed:[/bold red]")
            for err in errors:
                console.print(f"  [red]✗ {err}[/red]")
            raise RuntimeError(f"Preflight checks failed: {'; '.join(errors)}")

        console.print("  [green]✓ All preflight checks passed[/green]")

    def _create_project_agents(self) -> Path:
        """Write agent definitions from .agents/*.md to `.pi/agents/`
        so pi discovers them as project-level agents."""
        repo_root = self._find_repo_root()
        agents_dir = repo_root / ".pi" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)

        src_agents = repo_root / ".agents"
        for role in AGENT_ROLES:
            src_file = src_agents / f"{role}.md"
            if not src_file.exists():
                raise RuntimeError(f"Agent definition not found: {src_file}")
            dest_file = agents_dir / f"{role}.md"
            dest_file.write_text(src_file.read_text())

        console.print(f"  [green]✓ {len(AGENT_ROLES)} agent definitions written to .pi/agents/[/green]")
        return agents_dir

    def _generate_subagent_prompt(self) -> str:
        """Generate the master prompt that instructs pi to execute the
        subagent chain for the 3-round analysis workflow."""
        lines = [
            "You are the Analysis Orchestrator for repo-distiller.",
            "",
            "Your task is to analyze a codebase using 6 specialized agents",
            "in a 3-round chain process. Use the subagent tool to execute the chain.",
            "",
            "## Context",
            f"The analysis context is in: {self.context_file.name}",
            "",
            "## Workflow",
            "",
            "Execute the following chain using the subagent tool with chain mode.",
            "Each agent should read the context file and write their output to the",
            f"output directory: {self.output_dir}",
            "",
        ]

        # Round descriptions
        round_descriptions = [
            ("Round 1: Proponents (PM + Architect)",
             "Both agents read context.json independently and analyze from their perspective."),
            ("Round 2: Challengers (DFX + UX + Security)",
             "Each agent reads context.json AND the Round 1 outputs (pm_output.md, architect_output.md),"
             " then provides their specialist review."),
            ("Round 3: Integrator",
             "The integrator reads context.json AND ALL 5 previous outputs"
             " (pm_output.md, architect_output.md, dfx_output.md, ux_output.md, security_output.md),"
             " then synthesizes everything into the final report."),
        ]

        for title, desc in round_descriptions:
            lines.append(f"### {title}")
            lines.append(desc)
            lines.append("")

        # Agent instructions
        lines.append("## Agent Instructions")
        lines.append("")
        lines.append("For each agent in the chain, pass their role instructions in the task parameter.")
        lines.append("The agents are defined in .pi/agents/ and have tools: read, grep, find, ls, bash.")
        lines.append("")

        # Repomix pack for integrator
        repomix_section = ""
        if self.repomix_pack:
            repomix_section = (
                "\n\n### Full Repository Context (from Repomix)\n"
                "The following is a complete packed context of the repository generated by Repomix. "
                "The Integrator should use this to verify findings, discover cross-file relationships, "
                "and fill gaps from the structured analysis above.\n\n"
                + self.repomix_pack
            )
            lines.append(f"The Integrator should also read the Repomix context included below.{repomix_section}")

        # Output requirements
        lines.append("")
        lines.append("## Output Requirements")
        lines.append("")
        lines.append("Each agent must write their output to a file in the output directory:")
        lines.append(f"- PM → {self.output_dir}/pm_output.md")
        lines.append(f"- Architect → {self.output_dir}/architect_output.md")
        lines.append(f"- DFX → {self.output_dir}/dfx_output.md")
        lines.append(f"- UX → {self.output_dir}/ux_output.md")
        lines.append(f"- Security → {self.output_dir}/security_output.md")
        lines.append(f"- Integrator → {self.output_dir}/integrator_output.md (final report)")
        lines.append("")
        lines.append("The Integrator's output (integrator_output.md) is the final deliverable.")
        lines.append("It must be a comprehensive report following the Integrator agent's required output format.")
        lines.append("")
        lines.append("## Execution")
        lines.append("")
        lines.append("Execute the chain now. Read the context file, run each agent in sequence,")
        lines.append("and ensure all output files are written.")

        return "\n".join(lines)

    def _run_pi_orchestrator(self) -> str:
        """Run pi ONCE with the master orchestration prompt.
        pi uses subagent tool to execute the full 3-round chain internally.
        Returns the integrator's output."""
        t0 = time.time()
        prompt = self._generate_subagent_prompt()

        console.print("  Running subagent chain orchestration...")
        try:
            cmd = ["pi", "--print", "--no-extensions"]
            if self.pi_provider:
                cmd.extend(["--provider", self.pi_provider])
            if self.pi_model:
                cmd.extend(["--model", self.pi_model])
            # Load extensions
            for ext_path in self._extension_paths:
                cmd.extend(["-e", ext_path])
            # Load project model registration extension
            if getattr(self, "_tmp_models_json", None):
                cmd.extend(["-e", self._tmp_models_json])

            # API key via environment variable (provider reads $DASHSCOPE_API_KEY)
            env = None
            if self.pi_api_key:
                env = {**os.environ, "DASHSCOPE_API_KEY": self.pi_api_key}

            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour for full chain
                env=env,
                cwd=str(self.output_dir),
            )
            elapsed = time.time() - t0
            if result.returncode != 0:
                err = result.stderr[:1000]
                console.print(f"  [red]✗ Orchestrator failed ({elapsed:.1f}s): {err}[/red]")
                raise RuntimeError(f"pi orchestrator failed: {err}")

            # Check that output files were created by the subagent chain
            expected_outputs = ["pm_output.md", "architect_output.md", "dfx_output.md",
                                "ux_output.md", "security_output.md", "integrator_output.md"]
            missing = []
            for f in expected_outputs:
                if not (self.output_dir / f).exists():
                    missing.append(f)

            if missing:
                console.print(f"  [red]✗ Missing output files: {', '.join(missing)}[/red]")
                raise RuntimeError(f"Subagent chain did not produce: {', '.join(missing)}")

            console.print(f"  ✓ Subagent chain completed in {elapsed:.1f}s")
            integrator_output = (self.output_dir / "integrator_output.md").read_text()
            return integrator_output

        except subprocess.TimeoutExpired:
            elapsed = time.time() - t0
            console.print(f"  [red]✗ Orchestrator timed out after {elapsed:.1f}s[/red]")
            raise RuntimeError(f"pi orchestrator timed out after {elapsed:.1f}s")
        except Exception as e:
            elapsed = time.time() - t0
            console.print(f"  [red]✗ Orchestrator error ({elapsed:.1f}s): {e}[/red]")
            raise

    def _load_agent_def(self, role: str) -> Dict:
        """Read agent definition from `.agents/{role}.md`.
        Parses frontmatter (YAML) and body separately."""
        # Try analyzed repo's .agents/ first
        repo_root = self._find_repo_root()
        agent_file = repo_root / ".agents" / f"{role}.md"

        # Fallback: use bundled agent definitions from package
        if not agent_file.exists():
            agent_file = Path(__file__).resolve().parent / "agents" / f"{role}.md"

        if not agent_file.exists():
            raise RuntimeError(f"Agent definition not found: {agent_file}")

        content = agent_file.read_text()
        # Parse frontmatter and body
        parts = content.split("---", 2)
        if len(parts) >= 3:
            import yaml
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
            except ImportError:
                # Fallback: simple key-value parsing
                frontmatter = {}
                for line in parts[1].strip().split("\n"):
                    if ": " in line:
                        k, v = line.split(": ", 1)
                        frontmatter[k.strip()] = v.strip()
            body = parts[2].strip()
        else:
            frontmatter = {}
            body = content.strip()

        return {
            "role": role,
            "file": str(agent_file),
            "frontmatter": frontmatter,
            "system_prompt": body,
        }

    def _build_agent_prompt(self, role: str, context: Dict, previous_outputs: tuple) -> str:
        """Build prompt for a single agent role from .agents/*.md definition."""
        agent_def = self._load_agent_def(role)
        system_prompt = agent_def["system_prompt"]

        # Project context to role-relevant slice
        ctx = _project_context(context, role) if self.consume_tokens else context
        ctx_str = json.dumps(ctx, indent=2, default=str)

        prompt = f"{system_prompt}\n\n### Context Data\n```json\n{ctx_str}\n```"

        # Inject repomix pack for integrator (full repository context)
        # Disabled: Integrator already has 5 agents' analysis; adding 100K chars
        # causes "Cannot continue from message role: assistant" API error
        if False and role == "integrator" and self.repomix_pack:
            prompt += "\n\n### Full Repository Context (from Repomix)\n"
            prompt += "The following is a complete packed context of the repository generated by Repomix. "
            prompt += "Use this to verify findings, discover cross-file relationships, and fill gaps from the structured analysis above.\n\n"
            prompt += self.repomix_pack

        if previous_outputs:
            prompt += "\n\n### Previous Outputs\n"
            for i, output in enumerate(previous_outputs):
                if not output:
                    continue
                # Integrator gets truncated role outputs to avoid context overflow
                if role == "integrator":
                    labels = ["PM", "Architect", "DFX", "UX", "Security"]
                    label = labels[i] if i < len(labels) else f"Output {i + 1}"
                    trimmed = output[:3000] + "\n... (truncated)" if len(output) > 3000 else output
                    prompt += f"\n--- {label} Output ---\n{trimmed}\n"
                else:
                    trimmed = (
                        output[:3000] + "\n... (truncated)"
                        if self.consume_tokens and len(output) > 3000
                        else output
                    )
                    labels = ["PM", "Architect"]
                    label = labels[i] if i < len(labels) else f"Output {i + 1}"
                    prompt += f"\n--- {label} Output ---\n{trimmed}\n"

        return prompt

    def _run_pi_single(self, prompt: str, output_file: Path, label: str) -> str:
        """Run pi --print for a single agent role."""
        t0 = time.time()
        console.print(f"  Running {label}...")
        try:
            cmd = ["pi", "--print", "--no-extensions"]
            if self.pi_provider:
                cmd.extend(["--provider", self.pi_provider])
            if self.pi_model:
                cmd.extend(["--model", self.pi_model])
            # Load all project-scoped extensions
            for ext_path in self._extension_paths:
                cmd.extend(["-e", ext_path])
            # Load project model registration extension
            if getattr(self, "_tmp_models_json", None):
                cmd.extend(["-e", self._tmp_models_json])

            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=1200,
            )
            elapsed = time.time() - t0
            if result.returncode != 0:
                err = result.stderr[:500]
                console.print(f"  [red]✗ {label} failed ({elapsed:.1f}s): {err}[/red]")
                # Write error to output file so downstream can detect it
                output_file.write_text(f"# ERROR: {label} failed\n\n{err}\n")
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

    def _invoke_agent(self, role: str, context: Dict, *previous_outputs: str) -> str:
        output_file = self.output_dir / f"{role}_output.md"
        prompt = self._build_agent_prompt(role, context, previous_outputs)
        return self._run_pi_single(prompt, output_file, role)

    def run(self):
        t_start = time.time()

        # ── Preflight validation ─────────────────────────────────────
        self._preflight_check()

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

        # Copy integrator output to final report (if it exists)
        integrator_file = self.output_dir / "integrator_output.md"
        if integrator_file.exists():
            shutil.copy2(integrator_file, self.output_dir / "final_report.md")
        else:
            console.print("[yellow]⚠ Integrator output not found — final_report.md not generated[/yellow]")
            # Fall back: concatenate all role outputs as final report
            fallback = self.output_dir / "final_report.md"
            with open(fallback, "w") as f:
                for role in ["pm", "architect", "dfx", "ux", "security"]:
                    role_file = self.output_dir / f"{role}_output.md"
                    if role_file.exists():
                        f.write(f"## {role.upper()} Output\n\n")
                        f.write(role_file.read_text())
                        f.write("\n\n---\n\n")
            console.print(f"[yellow]  Created fallback final_report.md from individual role outputs[/yellow]")

        # If output format is "docs", split into structured docs
        if self.output_format == "docs":
            self._write_docs_output(timings)

        # Cleanup temporary models extension
        if getattr(self, "_tmp_models_json", None) and os.path.exists(self._tmp_models_json):
            try:
                os.unlink(self._tmp_models_json)
            except Exception:
                pass

    # ── Docs output format ─────────────────────────────────────────────

    def _write_docs_output(self, timings: Dict[str, float]):
        """Split integrator report into structured docs under docs/repo-distill/."""
        report_path = self.output_dir / "final_report.md"
        if not report_path.exists():
            console.print("[yellow]⚠ final_report.md not found, skipping docs output[/yellow]")
            return

        report_text = report_path.read_text()
        sections = self._split_report_sections(report_text)

        distill_dir = self.output_dir / "repo-distill"
        distill_dir.mkdir(parents=True, exist_ok=True)

        section_files = {
            "repo-context.md": sections.get("part0", ""),
            "features.md": sections.get("part1", ""),
            "architecture.md": sections.get("part2", ""),
            "security.md": sections.get("part3", ""),
            "ux.md": sections.get("part4", ""),
            "dfx.md": sections.get("dfx", ""),
            "action-items.md": sections.get("part5", ""),
            "test-gaps.md": sections.get("part7", ""),
            "doc-gaps.md": sections.get("part8", ""),
        }

        written_count = 0
        for filename, content in section_files.items():
            if content.strip():
                (distill_dir / filename).write_text(content)
                written_count += 1

        (distill_dir / "final_report.md").write_text(report_text)
        console.print(f"[bold green]✓ Structured docs: {distill_dir}/ ({written_count} sections + final_report.md)[/bold green]")

        overview_path = self.output_dir.parent / "repo-overview.md"
        overview_path.write_text(self._generate_overview_md(timings))
        console.print(f"[bold green]✓ Routing table: {overview_path}[/bold green]")

        metadata_path = distill_dir / "metadata.json"
        metadata_path.write_text(self._generate_metadata_json(timings))
        console.print(f"[bold green]✓ Metadata: {metadata_path}[/bold green]")

        agents_path = distill_dir / "AGENTS.md"
        agents_path.write_text(self._generate_agents_md())
        console.print(f"[bold green]✓ Agent guide: {agents_path}[/bold green]")

        claude_path = distill_dir / "CLAUDE.md"
        claude_path.write_text("@AGENTS.md")
        console.print(f"[bold green]✓ Claude entry point: {claude_path}[/bold green]")

    @staticmethod
    def _split_report_sections(report: str) -> Dict[str, str]:
        """Split the integrator report into named sections."""
        parts: Dict[str, str] = {}
        pattern = re.compile(r'^## Part (\d+):\s*(.+)$', re.MULTILINE)
        matches = list(pattern.finditer(report))

        for i, match in enumerate(matches):
            part_num = match.group(1)
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(report)
            parts[f"part{part_num}"] = report[start:end].strip()

        # Extract DFX gaps from Part 3
        part3 = parts.get("part3", "")
        dfx_start = re.search(r'### 🔧 Reliability & Observability Gaps', part3)
        if dfx_start:
            maint_start = re.search(r'### 📈 Maintainability Issues', part3[dfx_start.start():])
            if maint_start:
                parts["dfx"] = part3[dfx_start.start():dfx_start.start() + maint_start.start()].strip()
            else:
                parts["dfx"] = part3[dfx_start.start():].strip()

        return parts

    def _generate_overview_md(self, timings: Dict[str, float]) -> str:
        """Generate repo-overview.md routing table."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        repo_name = self.repo_url.split("/")[-1].replace(".git", "") if self.repo_url else "unknown"

        return f"""# {repo_name} — Repository Multi-Dimension Analysis Index

> Generated by [repo-distiller](https://github.com/Fornace/repo-distiller) on {now}.
> Based on commit: `{self.base_commit or "N/A"}`

## Agent Routing Table

| Your Role | Must-Read Files | Focus Area |
|-----------|----------------|------------|
| **Repo Overview** | `repo-distill/repo-context.md` | Language, structure, key files, secret scan results |
| **Requirement Analysis** | `repo-distill/features.md` | Existing features, user problems, acceptance criteria |
| **Architecture Design** | `repo-distill/architecture.md` | Technical decisions, architectural risks, module boundaries |
| **Code Development** | `repo-distill/architecture.md` + `repo-distill/action-items.md` | Known tech debt, pending fixes, code hotspots |
| **Security Review** | `repo-distill/security.md` | Vulnerability list, auth patterns, secret management |
| **Test Design** | `repo-distill/dfx.md` + `repo-distill/test-gaps.md` | Observability gaps, test coverage blind spots |
| **UX Review** | `repo-distill/ux.md` | Performance bottlenecks, a11y gaps, interaction issues |
| **Comprehensive Audit** | `repo-distill/final_report.md` | Full report (Parts 0–8) |

## Available Reports

| File | Content |
|------|---------|
| `repo-distill/repo-context.md` | Part 0: Repomix context summary (languages, structure, secrets) |
| `repo-distill/features.md` | PM-identified features with user problems and acceptance criteria |
| `repo-distill/architecture.md` | Technical decisions, risks, coupling from Git history |
| `repo-distill/security.md` | Vulnerability table, auth patterns, secret/config risks |
| `repo-distill/ux.md` | Performance concerns, accessibility gaps, UI consistency |
| `repo-distill/dfx.md` | Reliability gaps, observability, maintainability issues |
| `repo-distill/action-items.md` | Prioritized TODOs with file references |
| `repo-distill/test-gaps.md` | Missing tests derived from all findings |
| `repo-distill/doc-gaps.md` | Missing documentation by category |
| `repo-distill/final_report.md` | Complete integrator report (all parts combined) |
| `repo-distill/metadata.json` | Generation time, base commit, agent timings |

## Generation Details

- **Agent Roles**: PM, Architect, DFX, UX, Security, Integrator
- **Round 1** (Proponents): {timings.get('round1_proponents', 0):.1f}s
- **Round 2** (Challengers): {timings.get('round2_challengers', 0):.1f}s
- **Round 3** (Integrator): {timings.get('round3_integrator', 0):.1f}s
- **Total**: {timings.get('total_orchestration', 0):.1f}s

> **Refresh Policy**: Re-run when code changes significantly (>100 commits or >30 days).
"""

    def _generate_metadata_json(self, timings: Dict[str, float]) -> str:
        """Generate docs/repo-distill/metadata.json."""
        metadata = {
            "generator": "repo-distiller",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "base_commit": self.base_commit or "N/A",
            "repo_url": self.repo_url or "",
            "output_format": self.output_format,
            "agent_roles": ["pm", "architect", "dfx", "ux", "security", "integrator"],
            "timings": {
                "round1_proponents": round(timings.get("round1_proponents", 0), 1),
                "round2_challengers": round(timings.get("round2_challengers", 0), 1),
                "round3_integrator": round(timings.get("round3_integrator", 0), 1),
                "total_orchestration": round(timings.get("total_orchestration", 0), 1),
            },
            "files_generated": [
                "repo-overview.md",
                "repo-distill/final_report.md",
                "repo-distill/repo-context.md",
                "repo-distill/features.md",
                "repo-distill/architecture.md",
                "repo-distill/security.md",
                "repo-distill/ux.md",
                "repo-distill/dfx.md",
                "repo-distill/action-items.md",
                "repo-distill/test-gaps.md",
                "repo-distill/doc-gaps.md",
                "repo-distill/metadata.json",
                "repo-distill/AGENTS.md",
                "repo-distill/CLAUDE.md",
            ],
            "expiry_policy": "Re-run when commit diff > 100 or > 30 days since last generation",
        }
        return json.dumps(metadata, indent=2, ensure_ascii=False)

    def _generate_agents_md(self) -> str:
        """Generate AGENTS.md — progressive loading guide for downstream AI agents."""
        return """\
# AGENTS.md — Progressive Loading Guide

> This file tells AI agents which documents to load for each task, and in what order.
> **Rule**: Load files progressively — start with the smallest relevant file, read it, then decide if you need more.

## Quick Start

```python
# Pseudocode for any downstream agent
def analyze(task: str):
    # Step 1: always load the overview
    load("repo-context.md")  # 2-3KB — understand the repo at a glance

    # Step 2: load task-specific file
    if task == "requirement_analysis":
        load("features.md")        # 6-8KB — features, user problems, acceptance criteria
    elif task == "technical_design":
        load("architecture.md")    # 2-5KB — decisions, risks, module boundaries
    elif task == "security_review":
        load("security.md")        # 6-10KB — vulnerabilities, auth, secrets
    elif task == "code_development":
        load("action-items.md")    # 3-5KB — what to change, where
    elif task == "test_writing":
        load("test-gaps.md")       # 5-7KB — missing tests
    elif task == "documentation":
        load("doc-gaps.md")        # 2-4KB — missing docs

    # Step 3: load related files ONLY if needed
    # e.g. after reading features.md, you might need architecture.md for context
    # or action-items.md for implementation guidance
```

## File Reference

| File | Typical Size | Content | Load When |
|------|-------------|---------|----------|
| `repo-context.md` | ~2-3KB | Language, structure, key dirs, entry points, secret scan | **Always first** |
| `features.md` | ~6-8KB | Identified features, user problems, acceptance criteria, feasibility | Requirement analysis, PM tasks |
| `architecture.md` | ~2-5KB | Technical decisions, architectural risks, coupling hotspots | Design, refactoring, tech debt |
| `security.md` | ~6-10KB | Vulnerability table, auth patterns, secret/config risks | Security review, auth changes |
| `ux.md` | ~1-3KB | Performance concerns, accessibility gaps, UI consistency | UX review, frontend changes |
| `dfx.md` | ~1-4KB | Reliability gaps, observability, maintainability issues | SRE tasks, logging, monitoring |
| `action-items.md` | ~3-5KB | Prioritized TODOs (HIGH/MEDIUM/LOW) with file references | Any implementation task |
| `test-gaps.md` | ~5-7KB | Missing security, integration, architecture, a11y tests | Test writing, QA |
| `doc-gaps.md` | ~2-4KB | Missing docs by category (API, deployment, schema, security) | Documentation tasks |
| `final_report.md` | ~30-35KB | Complete integrator report (all parts combined) | Comprehensive audit only |
| `metadata.json` | ~1KB | Generation timestamp, commit, agent timings | Cache validation, staleness check |

## Progressive Loading Decision Tree

```
Start
  │
  ├─ load repo-context.md (always)
  │
  ├─ Task: "What does this repo do?"
  │    └─ STOP — repo-context.md + features.md is enough
  │
  ├─ Task: "Add/modify a feature"
  │    ├─ load features.md → find the feature, check acceptance criteria
  │    ├─ load architecture.md → understand tech decisions and risks
  │    ├─ load action-items.md → check if there are pending fixes for this area
  │    └─ read source code directly (don't rely on context.json)
  │
  ├─ Task: "Security audit"
  │    ├─ load security.md → vulnerability table + auth patterns
  │    ├─ load dfx.md → reliability gaps that affect security
  │    └─ read source code for auth/crypto/sanitization
  │
  ├─ Task: "Write tests"
  │    ├─ load test-gaps.md → already-identified missing tests
  │    ├─ load features.md → acceptance criteria → test cases
  │    └─ load security.md → security regression tests
  │
  └─ Task: "Comprehensive review"
       └─ load final_report.md (or load all individual files)
```

## Anti-Patterns (Don't Do This)

- ❌ **Don't load `final_report.md` for a narrow task** — wastes 80%+ tokens
- ❌ **Don't load `context.json`** — it's raw intermediate data, too noisy
- ❌ **Don't load all files upfront** — use the decision tree above
- ❌ **Don't skip `repo-context.md`** — it provides essential grounding

## Metadata & Staleness Check

Before using these files, check `metadata.json`:

```python
import json, datetime
meta = json.load(open("metadata.json"))
generated = datetime.fromisoformat(meta["generated_at"].replace("Z", "+00:00"))
age_days = (datetime.now(datetime.timezone.utc) - generated).days

if age_days > 30:
    # Report is stale — re-run repo-distiller
    print(f"Report is {age_days} days old, re-run recommended")
```

> **Expiry policy**: Re-run when commit diff > 100 or > 30 days since last generation.
"""
