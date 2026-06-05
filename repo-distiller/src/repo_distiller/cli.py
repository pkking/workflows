"""CLI entry point for repo-distiller."""

import getpass
import re
import shutil
from pathlib import Path

import click
from rich.console import Console

console = Console()


def _clean_intermediate(output_dir: Path, console: Console):
    """Remove intermediate files, keeping only final_report.md."""
    intermediate = [
        "repos",                    # cloned repos (~500MB)
        "context.json",             # raw AST/Git/IaC data
        "pm_output.md",             # role outputs
        "architect_output.md",
        "dfx_output.md",
        "ux_output.md",
        "security_output.md",
        "integrator_output.md",     # same as final_report.md
    ]
    removed = 0
    for name in intermediate:
        target = output_dir / name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            console.print(f"  [dim]removed: {name}[/dim]")
            removed += 1
    if removed:
        console.print(f"  [green]Cleaned: {removed} intermediate items removed, only final_report.md kept[/green]")


@click.group()
@click.version_option()
def main():
    """Repo Distiller: Analyze GitHub repos and generate feature/decision reports."""
    pass


def _needs_infra_analysis(repos: list) -> bool:
    """Check if any repo is from opensourceways org (needs infra analysis)."""
    for repo in repos:
        if 'opensourceways' in repo.lower():
            return True
        # Also check bare repo names that might be opensourceways repos
        if repo.startswith('http') and 'opensourceways' in repo:
            return True
    return False


def _ensure_github_token(token: str) -> str:
    """Ensure we have a GitHub token, prompting if necessary."""
    if token:
        return token

    console.print("[yellow][/yellow]")
    console.print("[bold yellow]GitHub Token Required[/bold yellow]")
    console.print("  Infra deployment analysis requires access to private infra-xxx repositories.")
    console.print("  Please provide a GitHub Personal Access Token with 'repo' scope.")
    console.print("  Create one at: https://github.com/settings/tokens")
    console.print("")

    try:
        token = getpass.getpass("GitHub Token: ")
        if not token.strip():
            console.print("[red]No token provided. Infra deployment analysis will be skipped.[/red]")
            return ""
        return token.strip()
    except (EOFError, KeyboardInterrupt):
        console.print("[yellow]Token input cancelled. Infra deployment analysis will be skipped.[/yellow]")
        return ""


@main.command()
@click.argument("repos", nargs=-1, required=True)
@click.option("--token", default=None, envvar="GITHUB_TOKEN",
              help="GitHub Personal Access Token (will prompt if opensourceways repos)")
@click.option("--output", "-o", default="./distill-output", help="Output directory")
@click.option("--branch", default="HEAD", help="Branch or Tag to analyze")
@click.option("--path", default=None, help="Subdirectory to analyze (for large repos)")
@click.option("--consume-tokens/--no-consume-tokens", default=True,
              help="Enable token optimization via pi-rtk (default: enabled). "
                   "Use --no-consume-tokens for full verbose output.")
@click.option("--clean/--no-clean", default=False,
              help="After analysis, remove intermediate files (repos/, context.json, "
                   "per-role outputs). Only final_report.md is kept. Default: --no-clean.")
@click.option("--skip-infra/--no-skip-infra", default=False,
              help="Skip infra deployment analysis even for opensourceways repos.")
def analyze(repos, token, output, branch, path, consume_tokens, clean, skip_infra):
    """Analyze one or more repositories."""
    mode = "token-optimized" if consume_tokens else "full-output"
    console.print(f"[bold blue]Starting analysis for {len(repos)} repo(s)...[/bold blue]")
    console.print(f"Repos: {', '.join(repos)}")
    console.print(f"Output: {output}")
    console.print(f"Mode: {mode}")

    # Check if infra analysis is needed
    needs_infra = not skip_infra and _needs_infra_analysis(repos)
    if needs_infra:
        token = _ensure_github_token(token)
        if token:
            console.print(f"[green]✓ GitHub token provided — infra analysis enabled[/green]")
        else:
            console.print("[yellow]⚠ No token — skipping infra deployment analysis[/yellow]")
            needs_infra = False

    from repo_distiller.analyzer import Analyzer
    analyzer = Analyzer(repos, token, output, branch, path, consume_tokens, needs_infra)
    analyzer.run()

    if clean:
        _clean_intermediate(Path(output), console)


if __name__ == "__main__":
    main()
