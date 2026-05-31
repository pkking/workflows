"""CLI entry point for repo-distiller."""

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


@main.command()
@click.argument("repos", nargs=-1, required=True)
@click.option("--token", envvar="GITHUB_TOKEN", help="GitHub Personal Access Token")
@click.option("--output", "-o", default="./distill-output", help="Output directory")
@click.option("--branch", default="HEAD", help="Branch or Tag to analyze")
@click.option("--path", default=None, help="Subdirectory to analyze (for large repos)")
@click.option("--consume-tokens/--no-consume-tokens", default=True,
              help="Enable token optimization via pi-rtk (default: enabled). "
                   "Use --no-consume-tokens for full verbose output.")
@click.option("--clean/--no-clean", default=False,
              help="After analysis, remove intermediate files (repos/, context.json, "
                   "per-role outputs). Only final_report.md is kept. Default: --no-clean.")
def analyze(repos, token, output, branch, path, consume_tokens, clean):
    """Analyze one or more repositories."""
    mode = "token-optimized" if consume_tokens else "full-output"
    console.print(f"[bold blue]Starting analysis for {len(repos)} repo(s)...[/bold blue]")
    console.print(f"Repos: {', '.join(repos)}")
    console.print(f"Output: {output}")
    console.print(f"Mode: {mode}")
    
    from repo_distiller.analyzer import Analyzer
    analyzer = Analyzer(repos, token, output, branch, path, consume_tokens)
    analyzer.run()
    
    if clean:
        _clean_intermediate(Path(output), console)


if __name__ == "__main__":
    main()
