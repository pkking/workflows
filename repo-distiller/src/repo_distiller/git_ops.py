"""Git operations: cloning and history mining."""

import os
from pathlib import Path
from typing import Optional

import pygit2
from rich.console import Console

console = Console()


class GitManager:
    """Handles repository cloning and history access."""

    def __init__(self, repos: list, token: Optional[str], work_dir: Path):
        self.repos = repos
        self.token = token
        self.work_dir = work_dir
        self.cloned_paths = {}

    def clone_all(self, branch: str = "HEAD"):
        for repo_url in self.repos:
            repo_name = repo_url.split("/")[-1].replace(".git", "")
            target = self.work_dir / repo_name
            if target.exists():
                console.print(f"[yellow]Repo {repo_name} already exists, skipping clone.[/yellow]")
                self.cloned_paths[repo_name] = target
                continue
            
            callbacks = pygit2.RemoteCallbacks()
            
            console.print(f"Cloning {repo_url}...")
            try:
                repo = pygit2.clone_repository(repo_url, str(target))
                self.cloned_paths[repo_name] = target
            except Exception as e:
                console.print(f"[red]Failed to clone {repo_url}: {e}[/red]")


