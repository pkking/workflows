"""Git history mining: hotspots, couplings, fix patterns.

Uses `git log --name-status` for fast file-change extraction
(avoids per-commit `git diff` which is very slow for large repos).
"""

import subprocess
import pygit2
from pathlib import Path
from typing import Dict, List
from collections import defaultdict

# Generated/vendor files to exclude from churn & coupling analysis
IGNORED_PATTERNS = {
    "node_modules", ".git", "vendor", "dist", "build",
    "package-lock", "yarn.lock", "poetry.lock", "Cargo.lock",
    "pnpm-lock", ".min.", ".map", "__pycache__",
}

# Max files per commit for O(n²) co-changes analysis
MAX_COUPLING_FILES = 20


def _should_ignore(path: str) -> bool:
    lower = path.lower()
    return any(p in lower for p in IGNORED_PATTERNS)


class GitAnalyzer:

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.repo = pygit2.Repository(str(repo_path))

    def analyze(self, limit: int = 100) -> Dict:
        # Get commit hashes and file changes via git log --name-status (fast)
        result = subprocess.run(
            ["git", "log", f"-n{limit}", "--no-merges",
             "--format=COMMIT_START%H %P", "--name-status"],
            cwd=str(self.repo_path),
            capture_output=True, text=True, timeout=30,
        )

        commits = []
        file_churn = defaultdict(int)
        co_changes = defaultdict(lambda: defaultdict(int))

        current_commit = None
        for line in result.stdout.splitlines():
            if line.startswith("COMMIT_START"):
                # Parse: COMMIT_START<hash> <parent1> <parent2> ...
                parts = line[len("COMMIT_START"):].strip().split()
                if not parts:
                    continue
                commit_hash = parts[0]
                parent_hash = parts[1] if len(parts) > 1 else None

                try:
                    commit_obj = self.repo.get(commit_hash)
                except (KeyError, ValueError):
                    current_commit = None
                    continue

                msg = commit_obj.message
                msg_lower = msg.lower()
                current_commit = {
                    "hash": commit_hash[:8],
                    "author": commit_obj.author.name if commit_obj.author else "unknown",
                    "message": msg.strip()[:100],
                    "files": [],
                    "is_fix": any(k in msg_lower for k in ["fix", "bug", "issue", "revert", "patch"]),
                    "is_large": False,
                    "insertions": 0,
                    "deletions": 0,
                }
                commits.append(current_commit)

            elif current_commit and line.strip():
                # File change line: <status>\t<filepath>
                parts = line.strip().split("\t")
                if len(parts) >= 2:
                    status = parts[0]
                    filepath = parts[1]
                    if not _should_ignore(filepath):
                        current_commit["files"].append(filepath)
                        file_churn[filepath] += 1

        # Trim file lists for display
        for c in commits:
            c["total_files"] = len(c["files"])
            c["files"] = c["files"][:50]
            c["is_large"] = c["total_files"] > 10

        # Co-changes analysis (capped)
        for c in commits:
            coupling_files = c["files"][:MAX_COUPLING_FILES]
            for f in coupling_files:
                for other in coupling_files:
                    if f != other:
                        co_changes[f][other] += 1

        hotspots = sorted(file_churn.items(), key=lambda x: x[1], reverse=True)[:10]

        couplings = []
        for f1, others in co_changes.items():
            for f2, cnt in others.items():
                if cnt > 3:
                    couplings.append({"file1": f1, "file2": f2, "count": cnt})
        couplings.sort(key=lambda x: x["count"], reverse=True)

        return {
            "commits": commits,
            "hotspots": [{"file": f, "churn": c} for f, c in hotspots],
            "couplings": couplings[:10],
        }
