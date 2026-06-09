"""Git operations: cloning and history mining."""

import os
import getpass
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
            # Check if it's a local path that already exists
            local_path = Path(repo_url)
            if local_path.exists() and local_path.is_dir() and (local_path / ".git").exists():
                repo_name = local_path.name
                console.print(f"[green]Using local repo: {repo_url}[/green]")
                self.cloned_paths[repo_name] = local_path
                continue

            repo_name = repo_url.split("/")[-1].replace(".git", "")
            target = self.work_dir / repo_name
            if target.exists():
                console.print(f"[yellow]Repo {repo_name} already exists, skipping clone.[/yellow]")
                self.cloned_paths[repo_name] = target
                continue

            console.print(f"Cloning {repo_url}...")
            cloned = False
            for attempt in range(2):  # max 2 attempts: no-token + with-token
                try:
                    callbacks = None
                    if self.token:
                        callbacks = pygit2.RemoteCallbacks(
                            credentials=pygit2.credentials.UserPass(
                                "x-access-token", self.token
                            )
                        )
                    repo = pygit2.clone_repository(
                        repo_url, str(target), callbacks=callbacks
                    )
                    self.cloned_paths[repo_name] = target
                    cloned = True
                    break
                except Exception as e:
                    err_str = str(e).lower()
                    if attempt == 0 and ("authentication" in err_str or "403" in err_str or "timed out" in err_str):
                        if not self.token:
                            console.print(f"[yellow]💡 Clone failed — this repo may require a GitHub token.[/yellow]")
                            try:
                                token = getpass.getpass("GitHub Token: ")
                                if token.strip():
                                    self.token = token.strip()
                                    console.print("[green]Retrying with provided token...[/green]")
                                    continue
                                else:
                                    console.print("[red]No token provided.[/red]")
                            except (EOFError, KeyboardInterrupt):
                                console.print("[yellow]Token input cancelled.[/yellow]")
                    console.print(f"[red]Failed to clone {repo_url}: {e}[/red]")
                    break

            if not cloned:
                raise RuntimeError(f"Clone failed for {repo_url}")


