"""Repomix bridge: file discovery, secret scanning, and code compression.

Uses Repomix CLI as an optional subprocess layer to augment repo-distiller's
analysis with git-aware file discovery, Secretlint-based secret detection,
and tree-sitter code compression for token-efficient LLM prompts.

Repomix is NOT a hard dependency — when unavailable, repo-distiller falls
back to its built-in rglob/pygit2 logic transparently.
"""

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from rich.console import Console

console = Console()

# ─── Repomix CLI detection ─────────────────────────────────────────────

def check_repomix_available() -> bool:
    """Check if Repomix CLI is installed and accessible."""
    return shutil.which("repomix") is not None


def check_repomix_version() -> Optional[str]:
    """Get Repomix version string, or None if not available."""
    try:
        result = subprocess.run(
            ["repomix", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


# ─── Data structures ───────────────────────────────────────────────────

@dataclass
class RepomixFileEntry:
    """A single file discovered by Repomix."""
    path: str
    token_count: int = 0


@dataclass
class SecretFinding:
    """A secret detected by Secretlint via Repomix."""
    file: str
    line: int = 0
    rule_id: str = ""
    message: str = ""
    severity: str = "high"


@dataclass
class RepomixResult:
    """Combined result from a Repomix run."""
    files: List[RepomixFileEntry] = field(default_factory=list)
    secrets: List[SecretFinding] = field(default_factory=list)
    compressed_output: Optional[str] = None
    token_total: int = 0
    file_count: int = 0


# ─── File discovery ────────────────────────────────────────────────────

def discover_files(
    repo_path: Path,
    *,
    include: Optional[str] = None,
    ignore: Optional[str] = None,
    include_logs: bool = False,
) -> RepomixResult:
    """Run Repomix in JSON mode to discover files with git-aware filtering.

    Repomix automatically respects .gitignore, .ignore, and .repomixignore.
    Additional include/ignore patterns can be passed as glob strings.

    Args:
        repo_path: Path to the repository root.
        include: Glob patterns to include (e.g. "src/**/*.ts,**/*.md").
        ignore: Glob patterns to ignore (e.g. "**/*.test.ts,**/*.spec.ts").
        include_logs: Whether to include git log context in output.

    Returns:
        RepomixResult with discovered files and metadata.
    """
    cmd = [
        "repomix", str(repo_path),
        "--style", "json",
        "--output", "/dev/stdout",
    ]

    if include:
        cmd.extend(["--include", include])
    if ignore:
        cmd.extend(["--ignore", ignore])
    if include_logs:
        cmd.append("--include-logs")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            console.print(f"[yellow]  Repomix discovery failed: {result.stderr[:300]}[/yellow]")
            return RepomixResult()

        # Repomix may output non-JSON warnings before the JSON blob.
        # Find the first { character and parse from there.
        output = result.stdout
        json_start = output.find("{")
        if json_start < 0:
            console.print("[yellow]  Repomix output contains no JSON.[/yellow]")
            return RepomixResult()

        # Use raw_decode to handle multiple JSON objects concatenated together
        from json import JSONDecoder
        try:
            decoder = JSONDecoder()
            data, _ = decoder.raw_decode(output[json_start:])
        except json.JSONDecodeError as e:
            console.print(f"[yellow]  Repomix JSON parse error: {e}[/yellow]")
            return RepomixResult()
        return _parse_json_result(data)

    except subprocess.TimeoutExpired:
        console.print("[yellow]  Repomix discovery timed out (120s).[/yellow]")
        return RepomixResult()
    except Exception as e:
        console.print(f"[yellow]  Repomix discovery error: {e}[/yellow]")
        return RepomixResult()


def _parse_json_result(data: Dict) -> RepomixResult:
    """Parse Repomix JSON output into a RepomixResult."""
    result = RepomixResult()

    # Extract files — repomix v1.14+ uses dict (path → content), older versions use list
    files_raw = data.get("files", {})
    if isinstance(files_raw, dict):
        # New format: {"path": "content", ...}
        for filepath, content in files_raw.items():
            token_count = len(content) // 4  # rough estimate: ~4 chars/token
            result.files.append(RepomixFileEntry(
                path=filepath,
                token_count=token_count,
            ))
    elif isinstance(files_raw, list):
        # Old format: [{"path": "...", "content": "..."}, ...]
        for file_entry in files_raw:
            filepath = file_entry.get("path", "")
            content = file_entry.get("content", "")
            token_count = len(content) // 4
            result.files.append(RepomixFileEntry(
                path=filepath,
                token_count=token_count,
            ))


    result.file_count = len(result.files)

    # Token totals from fileSummary
    file_summary = data.get("fileSummary") or {}
    token_detail = file_summary.get("tokenSummary") or {}
    result.token_total = token_detail.get("total") or 0

    # Extract secret findings from header/instructions if present
    result.secrets = _extract_secrets_from_output(data)

    return result


def _extract_secrets_from_output(data: Dict) -> List[SecretFinding]:
    """Best-effort extraction of secret warnings from Repomix output.

    Repomix embeds security warnings in the fileSummary notes section.
    """
    findings = []
    file_summary = data.get("fileSummary") or {}
    notes = file_summary.get("notes") or ""

    if "secret" in notes.lower() or "sensitive" in notes.lower():
        # Repomix uses Secretlint — extract structured findings from notes
        # Notes typically look like:
        # "Secretlint found 2 issues in .env"
        for line in notes.split("\n"):
            if "secret" in line.lower() or "sensitive" in line.lower():
                findings.append(SecretFinding(
                    file="see notes",
                    message=line.strip(),
                    severity="high",
                ))

    return findings


# ─── Secret scanning ───────────────────────────────────────────────────

def scan_secrets(repo_path: Path) -> List[SecretFinding]:
    """Run Repomix with secret detection to find hardcoded secrets.

    Uses Repomix's built-in Secretlint integration. Repomix outputs
    secret warnings to stderr during processing.

    Args:
        repo_path: Path to the repository root.

    Returns:
        List of SecretFinding objects.
    """
    cmd = [
        "repomix", str(repo_path),
        "--output", str(repo_path / ".repomix-secret-scan.tmp"),
        "--style", "xml",
    ]

    findings: List[SecretFinding] = []

    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=120,
        )

        # Parse secret warnings from stderr
        # Repomix/Secretlint outputs warnings like:
        # "✖ Found secret: API_KEY in .env line 3"
        findings.extend(_parse_secret_warnings(result.stderr))

        # Also scan the output file header for embedded warnings
        tmp_output = repo_path / ".repomix-secret-scan.tmp"
        if tmp_output.exists():
            content = tmp_output.read_text()
            findings.extend(_parse_secrets_from_content(content))
            tmp_output.unlink()

    except subprocess.TimeoutExpired:
        console.print("[yellow]  Secret scan timed out (120s).[/yellow]")
    except Exception as e:
        console.print(f"[yellow]  Secret scan error: {e}[/yellow]")

    # Cleanup any leftover temp files
    for tmp in repo_path.glob(".repomix-secret-scan.tmp*"):
        try:
            tmp.unlink()
        except OSError:
            pass

    return findings


def _parse_secret_warnings(stderr: str) -> List[SecretFinding]:
    """Extract secret findings from Repomix/Secretlint stderr output."""
    findings = []
    secret_pattern = re.compile(
        r"(?:secret|sensitive|credential|token|password|api[_-]?key)"
        r"[^:\n]*:?\s*(.+)",
        re.IGNORECASE,
    )

    for line in stderr.split("\n"):
        line_lower = line.lower()
        if any(kw in line_lower for kw in ["secret", "sensitive", "credential"]):
            findings.append(SecretFinding(
                file="",
                message=line.strip(),
                severity="high",
            ))

    return findings


def _parse_secrets_from_content(content: str) -> List[SecretFinding]:
    """Extract secret warnings from Repomix output file header.

    Repomix embeds a security notice in the <file_summary> section
    when secrets are detected.
    """
    findings = []

    # Look for secret-related warnings in the summary section
    summary_match = re.search(
        r"<file_summary>(.*?)</file_summary>",
        content, re.DOTALL,
    )
    if summary_match:
        summary = summary_match.group(1)
        for line in summary.split("\n"):
            line_lower = line.lower()
            if any(kw in line_lower for kw in ["secret", "sensitive", "credential"]):
                findings.append(SecretFinding(
                    file="summary",
                    message=line.strip(),
                    severity="high",
                ))

    return findings


# ─── Code compression ─────────────────────────────────────────────────

def compress_code(
    repo_path: Path,
    *,
    include: Optional[str] = None,
    ignore: Optional[str] = None,
    max_output_chars: int = 200_000,
) -> Optional[str]:
    """Run Repomix --compress to produce token-efficient code context.

    Repomix's --compress mode uses tree-sitter to extract key code elements
    (function signatures, class definitions, imports) while stripping
    implementation bodies, preserving structure at a fraction of the tokens.

    Args:
        repo_path: Path to the repository root.
        include: Glob patterns to include.
        ignore: Glob patterns to ignore.
        max_output_chars: Max characters to read from output (safety limit).

    Returns:
        Compressed code string, or None on failure.
    """
    cmd = [
        "repomix", str(repo_path),
        "--compress",
        "--style", "markdown",
        "--output", "/dev/stdout",
    ]

    if include:
        cmd.extend(["--include", include])
    if ignore:
        cmd.extend(["--ignore", ignore])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            console.print(f"[yellow]  Repomix compress failed: {result.stderr[:300]}[/yellow]")
            return None

        output = result.stdout
        if len(output) > max_output_chars:
            return output[:max_output_chars] + "\n... (truncated)"
        return output

    except subprocess.TimeoutExpired:
        console.print("[yellow]  Repomix compress timed out (180s).[/yellow]")
        return None
    except Exception as e:
        console.print(f"[yellow]  Repomix compress error: {e}[/yellow]")
        return None


# ─── Fallback file discovery (when Repomix unavailable) ────────────────

DEFAULT_INCLUDE_EXTS = {
    ".py", ".ts", ".tsx", ".go", ".rs", ".java", ".js",
    ".jsx", ".mjs", ".cjs",
}

DEFAULT_IGNORE_DIRS = {
    "node_modules", ".git", "vendor", "dist", "build",
    "__pycache__", ".next", ".nuxt", "target", "out",
    "coverage", ".cache", "venv", ".venv", "env",
}


def fallback_discover_files(repo_path: Path) -> List[RepomixFileEntry]:
    """Discover files using git ls-files + extension filtering.

    Fallback when Repomix is not available. Uses git's native file tracking
    to respect .gitignore automatically.

    Args:
        repo_path: Path to the repository root.

    Returns:
        List of RepomixFileEntry objects.
    """
    entries = []

    try:
        # Use git ls-files to get tracked files (respects .gitignore)
        result = subprocess.run(
            ["git", "ls-files"],
            capture_output=True, text=True, timeout=30,
            cwd=str(repo_path),
        )
        if result.returncode != 0:
            return _fallback_rglob(repo_path)

        for line in result.stdout.strip().split("\n"):
            filepath = line.strip()
            if not filepath:
                continue
            full_path = repo_path / filepath

            # Check extension
            ext = full_path.suffix.lower()
            if ext not in DEFAULT_INCLUDE_EXTS:
                continue

            # Check ignored directories
            parts = Path(filepath).parts
            if any(p in DEFAULT_IGNORE_DIRS for p in parts):
                continue

            # Estimate token count
            try:
                size = full_path.stat().st_size
                token_count = size // 4
            except OSError:
                token_count = 0

            entries.append(RepomixFileEntry(
                path=filepath,
                token_count=token_count,
            ))

    except Exception:
        return _fallback_rglob(repo_path)

    return entries


def _fallback_rglob(repo_path: Path) -> List[RepomixFileEntry]:
    """Pure Python fallback using rglob — least accurate but always works."""
    entries = []
    for ext in DEFAULT_INCLUDE_EXTS:
        for file in repo_path.rglob(f"*{ext}"):
            # Check ignored directories
            parts = file.relative_to(repo_path).parts
            if any(p in DEFAULT_IGNORE_DIRS for p in parts):
                continue
            try:
                size = file.stat().st_size
                token_count = size // 4
            except OSError:
                token_count = 0
            entries.append(RepomixFileEntry(
                path=file.relative_to(repo_path).as_posix(),
                token_count=token_count,
            ))
    return entries


# ─── Repository pack (full context for LLM) ───────────────────────────

def pack_repo(
    repo_path: Path,
    *,
    include: Optional[str] = None,
    ignore: Optional[str] = None,
    max_chars: int = 100_000,
) -> Optional[str]:
    """Run Repomix to produce a full repository context pack.

    Unlike compress_code (tree-sitter stripped), this produces the complete
    packed output with all file contents — suitable for deep semantic analysis.
    Truncated to max_chars to avoid overwhelming LLM context windows.

    Args:
        repo_path: Path to the cloned repository.
        include: Glob patterns to include.
        ignore: Glob patterns to ignore.
        max_chars: Maximum characters to return (default 100K).

    Returns:
        Packed repository context string, or None on failure.
    """
    cmd = [
        "repomix", str(repo_path),
        "--style", "markdown",
        "--output", "/dev/stdout",
    ]

    if include:
        cmd.extend(["--include", include])
    if ignore:
        cmd.extend(["--ignore", ignore])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            console.print(f"[yellow]  Repomix pack failed: {result.stderr[:300]}[/yellow]")
            return None

        output = result.stdout
        char_count = len(output)
        if char_count > max_chars:
            console.print(f"  [dim]  Repomix pack: {char_count:,} chars → truncated to {max_chars:,}[/dim]")
            return output[:max_chars] + "\n... (truncated)"
        console.print(f"  [green]✓ Repomix pack: {char_count:,} chars[/green]")
        return output

    except subprocess.TimeoutExpired:
        console.print("[yellow]  Repomix pack timed out (300s).[/yellow]")
        return None
    except Exception as e:
        console.print(f"[yellow]  Repomix pack error: {e}[/yellow]")
        return None


# ─── Main entry point ─────────────────────────────────────────────────

def run_repomix_enhancement(
    repo_path: Path,
    *,
    enable_discovery: bool = True,
    enable_secret_scan: bool = True,
    enable_compression: bool = False,
    include: Optional[str] = None,
    ignore: Optional[str] = None,
) -> RepomixResult:
    """Run all enabled Repomix enhancements on a repository.

    This is the main entry point called by repo-distiller's analyzer.

    Args:
        repo_path: Path to the cloned repository.
        enable_discovery: Whether to run git-aware file discovery.
        enable_secret_scan: Whether to run Secretlint secret scanning.
        enable_compression: Whether to generate compressed code context.
        include: Glob patterns to include.
        ignore: Glob patterns to ignore.

    Returns:
        RepomixResult with all findings.
    """
    if not check_repomix_available():
        console.print("[dim]  Repomix not found — using fallback file discovery.[/dim]")
        return RepomixResult(
            files=fallback_discover_files(repo_path),
            file_count=len(fallback_discover_files(repo_path)),
        )

    version = check_repomix_version()
    if version:
        console.print(f"[dim]  Repomix {version} detected — running enhancements.[/dim]")
    else:
        console.print("[dim]  Repomix detected — running enhancements.[/dim]")

    result = RepomixResult()

    # 1. File discovery
    if enable_discovery:
        console.print("  [cyan]→ Repomix file discovery...[/cyan]")
        discovery = discover_files(repo_path, include=include, ignore=ignore)
        result.files = discovery.files
        result.file_count = discovery.file_count
        result.token_total = discovery.token_total
        console.print(
            f"  [green]✓ Found {result.file_count} files "
            f"(~{result.token_total:,} tokens)[/green]"
        )

    # 2. Secret scanning
    if enable_secret_scan:
        console.print("  [cyan]→ Repomix secret scanning...[/cyan]")
        secrets = scan_secrets(repo_path)
        result.secrets = secrets
        if secrets:
            console.print(
                f"  [red]⚠ Found {len(secrets)} potential secret(s)[/red]"
            )
        else:
            console.print("  [green]✓ No secrets detected[/green]")

    # 3. Code compression (optional, disabled by default)
    if enable_compression:
        console.print("  [cyan]→ Repomix code compression...[/cyan]")
        compressed = compress_code(repo_path, include=include, ignore=ignore)
        result.compressed_output = compressed
        if compressed:
            console.print(
                f"  [green]✓ Compressed code: {len(compressed):,} chars[/green]"
            )

    return result
