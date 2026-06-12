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
@click.option("--repomix-include", default=None,
              help="Repomix glob patterns to include (e.g. 'src/**/*.ts,**/*.md').")
@click.option("--repomix-ignore", default=None,
              help="Repomix glob patterns to ignore (e.g. '**/*.test.ts,**/*.spec.ts').")
@click.option("--output-format", type=click.Choice(["flat", "docs"]), default="flat",
              help="Output format: 'flat' = single final_report.md (default); "
                   "'docs' = structured docs under docs/repo-distill/ + repo-overview.md routing table.")
@click.option("--pi-provider", default=None,
              help="Pi provider name (e.g. 'alibaba-cloud'). Overrides local pi config.")
@click.option("--pi-model", default=None,
              help="Pi model ID (e.g. 'qwen3.6-plus'). Overrides local pi config.")
@click.option("--pi-api-key", default=None,
              help="Pi API key. Overrides local pi config and env vars.")
@click.option("--pi-extensions", default=None,
              help="Comma-separated extension sources to load. "
                   "Uses github:Fornace/pi-alibaba-models@main (context window fix), "
                   "pi-web-access, and pi-subagents. "
                   "Installed to project scope if missing. "
                   "Default: 'github:Fornace/pi-alibaba-models@main,pi-web-access,pi-subagents'.")
def analyze(repos, token, output, branch, path, consume_tokens, clean, skip_infra,
            repomix_include, repomix_ignore, output_format, pi_provider, pi_model, pi_api_key,
            pi_extensions):
    """Analyze one or more repositories."""
    mode = "token-optimized" if consume_tokens else "full-output"
    console.print(f"[bold blue]Starting analysis for {len(repos)} repo(s)...[/bold blue]")
    console.print(f"Repos: {', '.join(repos)}")
    console.print(f"Output: {output}")
    console.print(f"Mode: {mode}")
    if pi_provider and pi_model:
        console.print(f"Pi: provider={pi_provider}, model={pi_model}")
        ext_list = pi_extensions or "github:Fornace/pi-alibaba-models@main,pi-web-access,pi-subagents"
        console.print(f"Pi extensions: {ext_list}")
    else:
        console.print("[yellow]⚠ No --pi-provider/--pi-model specified, using local pi config[/yellow]")
    console.print(f"Repomix: enabled (file discovery + secret scanning)")

    # Soft check — repomix is always enabled, falls back gracefully if not installed
    from repo_distiller.repomix_bridge import check_repomix_available, check_repomix_version
    if check_repomix_available():
        version = check_repomix_version()
        if version:
            console.print(f"  [green]✓ Repomix {version} found[/green]")
        else:
            console.print("  [green]✓ Repomix CLI found[/green]")
    else:
        console.print("  [yellow]⚠ Repomix not installed — falling back to built-in file discovery[/yellow]")
        console.print("  [dim]Install with: npm install -g repomix[/dim]")

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
    analyzer = Analyzer(
        repos, token, output, branch, path, consume_tokens, needs_infra,
        with_repomix=True,  # always enabled by default
        repomix_include=repomix_include,
        repomix_ignore=repomix_ignore,
        output_format=output_format,
        pi_provider=pi_provider,
        pi_model=pi_model,
        pi_api_key=pi_api_key,
        pi_extensions=pi_extensions,
    )
    analyzer.run()

    if clean:
        _clean_intermediate(Path(output), console)


if __name__ == "__main__":
    main()
