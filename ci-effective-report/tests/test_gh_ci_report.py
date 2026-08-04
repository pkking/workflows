import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "gh_ci_report.py"
SPEC = importlib.util.spec_from_file_location("gh_ci_report", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules["gh_ci_report"] = MODULE
SPEC.loader.exec_module(MODULE)


class WorkflowCardCountTests(unittest.TestCase):
    def test_report_date_range_includes_both_boundaries(self):
        self.assertTrue(MODULE._in_report_range("2026-08-01T00:00:00Z", "2026-08-01", "2026-08-31"))
        self.assertTrue(MODULE._in_report_range("2026-08-31T23:59:59Z", "2026-08-01", "2026-08-31"))
        self.assertFalse(MODULE._in_report_range("2026-09-01T00:00:00Z", "2026-08-01", "2026-08-31"))

    def test_sha_pinned_definition_maps_jobs_and_reuses_cache(self):
        workflow = """\
name: E2E
jobs:
  single:
    name: Single card
    runs-on: linux-aarch64-ascend910b-1
  multi:
    name: Multi card
    runs-on: [self-hosted, linux-aarch64-ascend910b-8]
  unknown:
    runs-on: ubuntu-latest
"""
        response = {"content": __import__("base64").b64encode(workflow.encode()).decode()}
        cache = {}
        with patch.object(MODULE, "gh_get", return_value=response) as get:
            resolved = MODULE.workflow_card_counts("token", "o/r", 42, ".github/workflows/e2e.yml", "abc", cache)
            repeated = MODULE.workflow_card_counts("token", "o/r", 42, ".github/workflows/e2e.yml", "abc", cache)

        self.assertEqual(resolved, {"Single card": 1, "Multi card": 8})
        self.assertEqual(repeated, resolved)
        self.assertEqual(get.call_count, 1)
        self.assertIn("ref=abc", get.call_args.args[1])

    def test_definition_lookup_failure_is_cached_as_unknown(self):
        cache = {}
        with patch.object(MODULE, "gh_get", side_effect=RuntimeError("not found")) as get:
            self.assertEqual(MODULE.workflow_card_counts("token", "o/r", 42, ".github/workflows/e2e.yml", "abc", cache), {})
            self.assertEqual(MODULE.workflow_card_counts("token", "o/r", 42, ".github/workflows/e2e.yml", "abc", cache), {})
        self.assertEqual(get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
