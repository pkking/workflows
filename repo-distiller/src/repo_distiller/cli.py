"""CLI entry point for repo-distiller."""

import click
from rich.console import Console

console = Console()


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
def analyze(repos, token, output, branch, path):
    """Analyze one or more repositories."""
    console.print(f"[bold blue]Starting analysis for {len(repos)} repo(s)...[/bold blue]")
    console.print(f"Repos: {', '.join(repos)}")
    console.print(f"Output: {output}")
    
    from repo_distiller.analyzer import Analyzer
    analyzer = Analyzer(repos, token, output, branch, path)
    analyzer.run()


if __name__ == "__main__":
    main()
