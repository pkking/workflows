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
        consume_tokens: bool = True,
    ):
        self.repos = repos
        self.token = token
        self.output_dir = Path(output_dir)
        self.branch = branch
        self.path_filter = path_filter
        self.consume_tokens = consume_tokens
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
        
        console.print("[bold green]3. Parsing IaC configurations...[/bold green]")
        self._analyze_iac()
        
        console.print("[bold green]4. Mining Git history...[/bold green]")
        self._analyze_git_history()
        
        console.print("[bold green]5. Generating intermediate JSON...[/bold green]")
        self._generate_intermediate_data()
        
        console.print("[bold green]6. Invoking multi-agent orchestration via pi...[/bold green]")
        self._invoke_pi_agents()
        
        console.print("[bold green]Analysis complete![/bold green]")

    def _analyze_ast(self):
        SUPPORTED_EXTS = {"*.py", "*.ts", "*.tsx", "*.go", "*.rs", "*.java", "*.js"}
        for repo_name, repo_path in self.git_mgr.cloned_paths.items():
            self.analysis_results[repo_name] = {"ast": [], "git": [], "iac": []}
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
