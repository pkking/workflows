"""Core analysis engine."""

import json
from pathlib import Path
from typing import List, Optional

from rich.console import Console

from .git_ops import GitManager
from .ast_parser import ASTAnalyzer
from .git_analyzer import GitAnalyzer
from .iac_parser import IaCAnalyzer

console = Console()


class Analyzer:
    """Orchestrates the analysis pipeline."""

    def __init__(
        self,
        repos: List[str],
        token: Optional[str],
        output_dir: str,
        branch: str,
        path_filter: Optional[str],
    ):
        self.repos = repos
        self.token = token
        self.output_dir = Path(output_dir)
        self.branch = branch
        self.path_filter = path_filter
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.work_dir = self.output_dir / "repos"
        self.work_dir.mkdir(exist_ok=True)
        
        self.git_mgr = GitManager(repos, token, self.work_dir)
        self.ast_analyzer = ASTAnalyzer()
        self.iac_analyzer = IaCAnalyzer()
        self.analysis_results = {}

    def run(self):
        """Execute the full analysis pipeline."""
        console.print("[bold green]1. Cloning repositories...[/bold green]")
        self.git_mgr.clone_all(self.branch)
        
        console.print("[bold green]2. Analyzing code structure (AST)...[/bold green]")
        self._analyze_ast()
        
        console.print("[bold green]3. Mining Git history...[/bold green]")
        self._analyze_git_history()
        
        console.print("[bold green]4. Generating intermediate JSON...[/bold green]")
        self._generate_intermediate_data()
        
        console.print("[bold green]5. Invoking multi-agent orchestration via pi...[/bold green]")
        self._invoke_pi_agents()
        
        console.print("[bold green]Analysis complete![/bold green]")

    def _analyze_ast(self):
        for repo_name, repo_path in self.git_mgr.cloned_paths.items():
            self.analysis_results[repo_name] = {"ast": [], "git": []}
            for file in repo_path.rglob("*.py"):
                if self.path_filter and str(self.path_filter) not in str(file):
                    continue
                result = self.ast_analyzer.analyze_file(file)
                if result:
                    self.analysis_results[repo_name]["ast"].append(result)

    def _analyze_git_history(self):
        for repo_name, repo_path in self.git_mgr.cloned_paths.items():
            analyzer = GitAnalyzer(repo_path)
            history_data = analyzer.analyze(limit=500)
            if repo_name in self.analysis_results:
                self.analysis_results[repo_name]["git"] = history_data

    def _analyze_iac(self):
        for repo_name, repo_path in self.git_mgr.cloned_paths.items():
            iac_data = self.iac_analyzer.analyze(repo_path)
            if repo_name in self.analysis_results:
                self.analysis_results[repo_name]["iac"] = iac_data

    def _generate_intermediate_data(self):
        context_file = self.output_dir / "context.json"
        context_file.write_text(json.dumps(self.analysis_results, indent=2, default=str))
        console.print(f"[green]Intermediate data saved to {context_file}[/green]")

    def _invoke_pi_agents(self):
        from .orchestrator import Orchestrator
        context_file = self.output_dir / "context.json"
        orch = Orchestrator(context_file, self.output_dir)
        orch.run()
