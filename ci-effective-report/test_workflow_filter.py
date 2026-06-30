#!/usr/bin/env python3
"""Self-check for the workflow-name SQL clause builder (Method A).

Run: python3 test_workflow_filter.py
Covers the only non-trivial logic introduced by --workflow: pattern escaping,
multi-pattern OR-joining, and the empty-pattern no-op.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ci_analyze import _workflow_match_clause


def check():
    # No patterns -> no clause (doesn't perturb the existing query)
    assert _workflow_match_clause(None) == ""
    assert _workflow_match_clause([]) == ""

    # Single pattern -> one LIKE, wrapped in AND (...)
    c = _workflow_match_clause(["build"])
    assert c == " AND (name LIKE '%build%')", c

    # Multiple patterns -> OR-joined inside one AND (...)
    c = _workflow_match_clause(["build", "test"])
    assert c == " AND (name LIKE '%build%' OR name LIKE '%test%')", c

    # Single quotes in a pattern are escaped (anti-injection / don't break SQL)
    c = _workflow_match_clause(["it's"])
    assert c == " AND (name LIKE '%it''s%')", c

    # Mixed case pattern: kept as-is; SQLite LIKE handles ASCII case-insensitivity
    c = _workflow_match_clause(["Build"])
    assert "name LIKE '%Build%'" in c, c

    # Method B helper: substring, case-insensitive, multi-pattern
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent / "skills/github-ci-efficiency-report/scripts"))
    from github_ci_efficiency_report import workflow_matches
    assert workflow_matches("Build and Test", None) is True
    assert workflow_matches("Build and Test", []) is True
    assert workflow_matches("Build and Test", ["build"]) is True       # case-insensitive
    assert workflow_matches("Build and Test", ["BUILD", "lint"]) is True  # second matches
    assert workflow_matches("Build and Test", ["lint"]) is False
    assert workflow_matches("", ["build"]) is False
    assert workflow_matches(None, ["x"]) is False

    # run_matches_workflow: match on display name OR yaml file path (path_cache)
    from github_ci_efficiency_report import WorkflowRunInfo, run_matches_workflow

    def _run(name: str, wid: int | None) -> WorkflowRunInfo:
        return WorkflowRunInfo(
            id=1, name=name, workflow_id=wid, status="", conclusion="",
            event="", html_url="", head_sha="",
            created_at=None, run_started_at=None, updated_at=None,
        )

    pc = {10: ".github/workflows/build.yml"}
    assert run_matches_workflow(_run("CI", 10), ["build.yml"], pc) is True   # path match (full filename)
    assert run_matches_workflow(_run("CI", 10), ["build"], pc) is True      # path substring (basename w/o ext)
    assert run_matches_workflow(_run("CI", 10), ["lint"], pc) is False      # neither name nor path
    assert run_matches_workflow(_run("Build", 10), ["build"], pc) is True   # name match (case-insensitive) wins
    assert run_matches_workflow(_run("CI", 10), [], pc) is True             # no filter -> match all
    assert run_matches_workflow(_run("CI", 10), None, pc) is True
    assert run_matches_workflow(_run("CI", None), ["build.yml"], pc) is False  # no workflow_id -> no path lookup
    assert run_matches_workflow(_run("CI", 99), ["build.yml"], pc) is False    # workflow_id missing from cache

    print("OK: all workflow-filter assertions passed")


if __name__ == "__main__":
    check()
