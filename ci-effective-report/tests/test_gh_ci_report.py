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
    def test_a3_card_count_is_halved(self):
        self.assertEqual(MODULE._parse_card_label(["linux-aarch64-a3-4"]), ("a3", 2))
        self.assertEqual(MODULE._parse_card_label(["linux-aarch64-a3-8"]), ("a3", 4))
        self.assertEqual(MODULE._parse_card_label(["linux-aarch64-a2-2"]), ("a2", 2))
        self.assertEqual(MODULE._parse_card_label(["linux-aarch64-310p-4"]), ("310p", 4))
        self.assertEqual(MODULE._parse_card_label(["linux-aarch64-a2b3-1"]), ("a2b3", 1))

    def test_actual_job_label_has_priority_and_needs_no_workflow_content_read(self):
        run = {"id": 1, "head_sha": "abc", "head_branch": "main", "event": "pull_request",
               "status": "completed", "conclusion": "success", "created_at": "2026-08-03T10:00:00Z",
               "updated_at": "2026-08-03T11:00:00Z", "run_started_at": "2026-08-03T10:00:00Z",
               "html_url": "https://example.test/run", "path": ".github/workflows/e2e.yml@main"}
        job = {"id": 2, "name": "matrix job", "status": "completed", "conclusion": "success",
               "created_at": "2026-08-03T10:00:00Z", "started_at": "2026-08-03T10:05:00Z",
               "completed_at": "2026-08-03T11:00:00Z", "html_url": "https://example.test/job",
               "labels": ["self-hosted", "linux-aarch64-310p-4"], "steps": []}

        def get(_token, url):
            if "/runs?" in url:
                return {"workflow_runs": [run]}
            if "/actions/workflows/42" in url:
                return {"name": "E2E", "path": ".github/workflows/e2e.yml"}
            if "/jobs?" in url:
                return {"jobs": [job]}
            self.fail(f"unexpected API read: {url}")

        with patch.object(MODULE, "gh_get", side_effect=get):
            data = MODULE.fetch_repo("token", "o/r", "E2E", 42, "2026-08-03", "2026-08-03")
        self.assertEqual(data["jobs"][0]["card_count"], 4)

    def test_refresh_active_runs_updates_status_and_completion_time(self):
        repos = {"o/r": {"runs": [{"id": 1, "status": "in_progress", "conclusion": "",
                                      "created_at": "2026-08-04T10:00:00Z", "updated_at": ""}]}}
        latest = {"status": "completed", "conclusion": "failure", "updated_at": "2026-08-04T11:00:00Z",
                  "run_started_at": "2026-08-04T10:05:00Z"}
        with patch.object(MODULE, "gh_get", return_value=latest) as get:
            MODULE.refresh_active_runs("token", repos)
        run = repos["o/r"]["runs"][0]
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["conclusion"], "failure")
        self.assertEqual(run["updated_at"], "2026-08-04T11:00:00Z")
        self.assertEqual(run["duration_seconds"], 3300)
        self.assertIn("/actions/runs/1", get.call_args.args[1])

    def test_refresh_failure_keeps_collected_data(self):
        repos = {"o/r": {"runs": [{"id": 1, "status": "in_progress", "conclusion": "",
                                      "updated_at": "old"}]}}
        with patch.object(MODULE, "gh_get", side_effect=RuntimeError("gone")):
            MODULE.refresh_active_runs("token", repos)
        self.assertEqual(repos["o/r"]["runs"][0]["updated_at"], "old")

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
