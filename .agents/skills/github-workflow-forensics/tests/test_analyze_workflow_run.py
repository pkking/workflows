import datetime as dt
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "analyze_workflow_run.py"
SPEC = importlib.util.spec_from_file_location("workflow_forensics", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules["workflow_forensics"] = MODULE
SPEC.loader.exec_module(MODULE)

UTC = dt.timezone.utc

def t(minute):
    return (dt.datetime(2026, 7, 29, tzinfo=UTC) + dt.timedelta(minutes=minute)).isoformat().replace("+00:00", "Z")

class WorkflowForensicsTests(unittest.TestCase):
    def test_run_url_preserves_attempt(self):
        self.assertEqual(
            MODULE.parse_target("https://github.com/o/r/actions/runs/42/attempts/3", None),
            ("o/r", 42, 3),
        )

    def test_analysis_localizes_queue_execution_step_and_tail(self):
        run = {"id": 42, "run_attempt": 2, "name": "E2E", "display_title": "PR title", "status": "completed", "conclusion": "success", "html_url": "https://example/42"}
        jobs = [
            {"id": 1, "name": "fast", "status": "completed", "conclusion": "success", "created_at": t(0), "started_at": t(10), "completed_at": t(30), "steps": [{"name": "test", "started_at": t(12), "completed_at": t(27), "status": "completed"}]},
            {"id": 2, "name": "tail", "status": "completed", "conclusion": "success", "created_at": t(0), "started_at": t(20), "completed_at": t(80), "steps": [{"name": "suite", "started_at": t(21), "completed_at": t(71), "status": "completed"}]},
        ]
        result = MODULE.analyze("o/r", run, jobs, dt.datetime(2026, 7, 30, tzinfo=UTC))
        self.assertEqual(result["wall"], 80 * 60)
        findings = {item["kind"]: item for item in result["findings"]}
        self.assertEqual(findings["Runner queue"]["subject"], "tail")
        self.assertEqual(findings["Job execution"]["duration"], 60 * 60)
        self.assertEqual(findings["Step execution"]["subject"], "tail / suite")
        self.assertEqual(findings["Parallel tail"]["duration"], 50 * 60)

    def test_html_contains_every_job_step_and_queue_legend(self):
        run = {"id": 1, "run_attempt": 1, "name": "E2E", "status": "completed", "conclusion": "success"}
        jobs = [{"id": 1, "name": "job <matrix>", "html_url": "https://example/jobs/1", "status": "completed", "created_at": t(0), "started_at": t(5), "completed_at": t(10), "steps": [{"name": "step & test", "started_at": t(6), "completed_at": t(9)}]}]
        result = MODULE.analyze("o/r", run, jobs, dt.datetime(2026, 7, 30, tzinfo=UTC))
        page = MODULE.render([result], dt.datetime(2026, 7, 30, tzinfo=UTC), 2)
        self.assertIn("job &lt;matrix&gt;", page)
        self.assertIn("step &amp; test", page)
        self.assertIn("Runner queue", page)
        self.assertIn('href="https://example/jobs/1"', page)
        self.assertNotIn("job <matrix>", page)

    def test_in_progress_and_missing_timestamps_are_visible_not_zero(self):
        run = {"id": 9, "run_attempt": 1, "name": "E2E", "status": "in_progress"}
        jobs = [
            {"id": 1, "name": "running", "status": "in_progress", "created_at": t(0), "started_at": t(10), "completed_at": None, "steps": [{"name": "still testing", "started_at": t(20), "completed_at": None, "status": "in_progress"}]},
            {"id": 2, "name": "missing", "status": "completed", "created_at": t(1), "started_at": None, "completed_at": None, "steps": []},
        ]
        now = MODULE.parse_time(t(70))
        result = MODULE.analyze("o/r", run, jobs, now)
        self.assertEqual(result["jobs"][0]["execution"], 60 * 60)
        self.assertIsNone(result["jobs"][1]["execution"])
        page = MODULE.render([result], now, 1)
        self.assertIn("Still running", page)
        self.assertIn("timestamp gap", page)
        self.assertNotIn("missing</b><small>— queued · 0.0 min running", page)

if __name__ == "__main__":
    unittest.main()
