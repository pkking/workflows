"""Core analysis engine — Phase 3: enhanced with schema, state machine, and deploy analysis."""

import json
from pathlib import Path
from typing import List, Optional

from rich.console import Console

from .git_ops import GitManager
from .ast_parser import ASTAnalyzer
from .git_analyzer import GitAnalyzer
from .iac_parser import IaCAnalyzer
from .dependency_parser import DependencyParser
from .config_parser import ConfigParser
from .schema_analyzer import SchemaAnalyzer
from .state_machine_analyzer import StateMachineAnalyzer
from .deploy_parser import DeployParser
from .call_graph_analyzer import CallGraphExtractor, ErrorFlowAnalyzer
from .infra_analyzer import InfraAnalyzer

console = Console()


class Analyzer:
    """Orchestrates the full analysis pipeline."""

    def __init__(
        self,
        repos: List[str],
        token: Optional[str],
        output_dir: str,
        branch: str,
        path_filter: Optional[str],
        consume_tokens: bool = True,
        needs_infra: bool = True,
    ):
        self.repos = repos
        self.token = token
        self.output_dir = Path(output_dir)
        self.branch = branch
        self.path_filter = path_filter
        self.consume_tokens = consume_tokens
        self.needs_infra = needs_infra
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.work_dir = self.output_dir / "repos"
        self.work_dir.mkdir(exist_ok=True)

        self.git_mgr = GitManager(repos, token, self.work_dir)
        self.ast_analyzer = ASTAnalyzer()
        self.iac_analyzer = IaCAnalyzer()
        self.dep_parser = DependencyParser()
        self.config_parser = ConfigParser()
        self.schema_analyzer = SchemaAnalyzer()
        self.state_machine_analyzer = StateMachineAnalyzer()
        self.deploy_parser = DeployParser()
        self.call_graph_extractor = CallGraphExtractor()
        self.error_flow_analyzer = ErrorFlowAnalyzer()
        self.infra_analyzer = InfraAnalyzer(token=token if needs_infra else None)
        self.analysis_results = {}

    def run(self):
        """Execute the full analysis pipeline."""
        console.print("[bold green]1. Cloning repositories...[/bold green]")
        self.git_mgr.clone_all(self.branch)

        console.print("[bold green]2. Analyzing code structure (AST)...[/bold green]")
        self._analyze_ast()

        console.print("[bold green]3. Parsing IaC configurations...[/bold green]")
        self._analyze_iac()

        console.print("[bold green]4. Mining Git history...[/bold green]")
        self._analyze_git_history()

        console.print("[bold green]5. Analyzing dependencies...[/bold green]")
        self._analyze_dependencies()

        console.print("[bold green]6. Parsing configurations...[/bold green]")
        self._analyze_configs()

        console.print("[bold green]7. Extracting schema & ER relationships...[/bold green]")
        self._analyze_schema()

        console.print("[bold green]8. Detecting state machines...[/bold green]")
        self._analyze_state_machines()

        console.print("[bold green]9. Analyzing deployment topology...[/bold green]")
        self._analyze_deployment()

        console.print("[bold green]10. Building call graph & error flow...[/bold green]")
        self._analyze_call_graph()

        console.print("[bold green]11. Analyzing infra deployments...[/bold green]")
        if self.needs_infra:
            self._analyze_infra()
        else:
            console.print("  [dim]Skipped (--skip-infra or no GitHub token)[/dim]")

        console.print("[bold green]12. Generating intermediate JSON...[/bold green]")
        self._generate_intermediate_data()

        console.print("[bold green]13. Invoking multi-agent orchestration via pi...[/bold green]")
        self._invoke_pi_agents()

        console.print("[bold green]Analysis complete![/bold green]")

    def _analyze_ast(self):
        SUPPORTED_EXTS = {"*.py", "*.ts", "*.tsx", "*.go", "*.rs", "*.java", "*.js"}
        for repo_name, repo_path in self.git_mgr.cloned_paths.items():
            self.analysis_results[repo_name] = {
                "ast": [], "git": [], "iac": [],
                "dependencies": {}, "config": {},
            }
            for ext in SUPPORTED_EXTS:
                for file in repo_path.rglob(ext):
                    if self._should_skip(file):
                        continue
                    result = self.ast_analyzer.analyze_file(file)
                    if result:
                        self.analysis_results[repo_name]["ast"].append(result)

    def _analyze_git_history(self):
        for repo_name, repo_path in self.git_mgr.cloned_paths.items():
            analyzer = GitAnalyzer(repo_path)
            history_data = analyzer.analyze()
            if repo_name in self.analysis_results:
                self.analysis_results[repo_name]["git"] = history_data

    def _analyze_iac(self):
        for repo_name, repo_path in self.git_mgr.cloned_paths.items():
            iac_data = self.iac_analyzer.analyze(repo_path)
            if repo_name in self.analysis_results:
                self.analysis_results[repo_name]["iac"] = iac_data

    def _analyze_dependencies(self):
        for repo_name, repo_path in self.git_mgr.cloned_paths.items():
            dep_data = self.dep_parser.analyze(repo_path)
            if repo_name in self.analysis_results:
                self.analysis_results[repo_name]["dependencies"] = dep_data

    def _analyze_configs(self):
        for repo_name, repo_path in self.git_mgr.cloned_paths.items():
            config_data = self.config_parser.analyze(repo_path)
            if repo_name in self.analysis_results:
                self.analysis_results[repo_name]["config"] = config_data

    def _analyze_schema(self):
        for repo_name, repo_path in self.git_mgr.cloned_paths.items():
            ast_data = self.analysis_results.get(repo_name, {}).get("ast", [])
            schema_data = self.schema_analyzer.analyze(repo_path, ast_data)
            # Also run source-level state machine analysis
            sm_data = self.state_machine_analyzer.analyze_from_source(repo_path)
            schema_data["state_machines"] = sm_data
            if repo_name in self.analysis_results:
                self.analysis_results[repo_name]["schema"] = schema_data

    def _analyze_state_machines(self):
        # Already done in _analyze_schema, but also do AST-level analysis
        for repo_name, repo_path in self.git_mgr.cloned_paths.items():
            ast_data = self.analysis_results.get(repo_name, {}).get("ast", [])
            sm_ast = self.state_machine_analyzer.analyze(ast_data)
            if repo_name in self.analysis_results:
                if "schema" not in self.analysis_results[repo_name]:
                    self.analysis_results[repo_name]["schema"] = {}
                self.analysis_results[repo_name]["schema"]["state_machines_ast"] = sm_ast

    def _analyze_deployment(self):
        for repo_name, repo_path in self.git_mgr.cloned_paths.items():
            deploy_data = self.deploy_parser.analyze(repo_path)
            # Build topology
            deploy_data["topology"] = self.deploy_parser._build_topology(
                deploy_data.get("dockerfiles", []),
                deploy_data.get("entry_points", []),
            )
            if repo_name in self.analysis_results:
                self.analysis_results[repo_name]["deployment"] = deploy_data

    def _analyze_call_graph(self):
        for repo_name, repo_path in self.git_mgr.cloned_paths.items():
            cg_data = self.call_graph_extractor.analyze_repo(repo_path)
            ef_data = self.error_flow_analyzer.analyze_repo(repo_path)
            if repo_name in self.analysis_results:
                self.analysis_results[repo_name]["call_graph"] = cg_data
                self.analysis_results[repo_name]["error_flow"] = ef_data

    def _analyze_infra(self):
        for repo_name, repo_path in self.git_mgr.cloned_paths.items():
            # Infer target repo name from the URL
            target_name = repo_name.replace(".git", "")
            infra_data = self.infra_analyzer.analyze(target_name)
            if repo_name in self.analysis_results:
                self.analysis_results[repo_name]["infra"] = infra_data

    def _should_skip(self, file: Path) -> bool:
        """Check if a file should be skipped based on path filter."""
        if not self.path_filter:
            return False
        filter_path = Path(self.path_filter)
        try:
            return not file.is_relative_to(self.work_dir / filter_path)
        except (ValueError, TypeError):
            return str(filter_path) not in str(file)

    def _generate_intermediate_data(self):
        context_file = self.output_dir / "context.json"
        context_file.write_text(json.dumps(self.analysis_results, indent=2, default=str))
        console.print(f"[green]Intermediate data saved to {context_file}[/green]")

    def _invoke_pi_agents(self):
        from .orchestrator import Orchestrator
        context_file = self.output_dir / "context.json"
        orch = Orchestrator(context_file, self.output_dir, consume_tokens=self.consume_tokens)
        orch.run()
