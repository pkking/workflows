import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "ci_analyze.py"
SPEC = importlib.util.spec_from_file_location("ci_analyze", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules["ci_analyze"] = MODULE
SPEC.loader.exec_module(MODULE)

DUR_MIN = 60  # 测试阈值与默认一致


def _run(rid, name, dur_sec, event="push", created="2026-07-15T10:00:00Z", conclusion="success"):
    return {
        "id": rid, "repo_id": 1, "name": name, "head_branch": "main", "head_sha": "abc",
        "event": event, "status": "completed", "conclusion": conclusion,
        "created_at": created, "updated_at": "2026-07-15T11:30:00Z",
        "html_url": f"https://github.com/o/r/actions/runs/{rid}",
        "duration_seconds": dur_sec, "date": "2026-07-15", "workflow_file": "e2e.yml",
    }


def _job(jid, run_id, name, dur_sec, started="2026-07-15T10:05:00Z"):
    return {
        "id": jid, "run_id": run_id, "name": name, "status": "completed", "conclusion": "success",
        "created_at": "2026-07-15T10:00:00Z", "started_at": started, "completed_at": "2026-07-15T11:00:00Z",
        "html_url": f"https://github.com/o/r/jobs/{jid}", "queue_duration_seconds": 300, "duration_seconds": dur_sec,
    }


def _step(job_id, num, name, dur_sec, conclusion="success"):
    return {
        "job_id": job_id, "number": num, "name": name, "status": "completed", "conclusion": conclusion,
        "started_at": "2026-07-15T10:10:00Z", "completed_at": "2026-07-15T10:40:00Z", "duration_seconds": dur_sec,
    }


class BuildDrilldownDataTests(unittest.TestCase):
    def _repos_data(self):
        # run1: 90min keep; run2: 40min drop; run3: 120min keep (schedule, no PR author)
        runs = [_run(1, "E2E <prod>", 90 * 60), _run(2, "Short", 40 * 60),
                _run(3, "Nightly & CI", 120 * 60, event="schedule")]
        jobs = [_job(10, 1, "build", 70 * 60), _job(11, 1, "test", 30 * 60),
                _job(12, 3, "nightly-1", 110 * 60)]
        # step number 2 sorts after number 1; None-number sorts last
        steps = [_step(10, 2, "Run <tests>", 65 * 60), _step(10, 1, "checkout", 5 * 60),
                 _step(12, None, "no-number step", 100 * 60)]
        pr_metrics = [{"id": 99, "author": "alice", "html_url": "https://github.com/o/r/pull/1",
                       "pr_number": 1, "title": "t", "created_at": "2026-07-15T09:00:00Z",
                       "merged_at": "2026-07-15T12:00:00Z", "ci_completed_at": "2026-07-15T11:30:00Z",
                       "conclusion": "success"}]
        pr_workflows = [{"pr_metric_id": 99, "run_id": 1}]
        return {"o/r": {"runs": runs, "jobs": jobs, "steps": steps,
                        "pr_metrics": pr_metrics, "pr_workflows": pr_workflows}}

    def test_threshold_excludes_short_runs(self):
        data = MODULE.build_drilldown_data(self._repos_data(), None, min_minutes=DUR_MIN)
        self.assertEqual([r["dur"] for r in data["runs"]], [120.0, 90.0])

    def test_runs_sorted_desc_by_duration(self):
        data = MODULE.build_drilldown_data(self._repos_data(), None, min_minutes=DUR_MIN)
        self.assertEqual(data["runs"][0]["dur"], 120.0)
        self.assertEqual(data["runs"][1]["dur"], 90.0)

    def test_author_joined_via_pr_workflows_and_empty_for_non_pr(self):
        data = MODULE.build_drilldown_data(self._repos_data(), None, min_minutes=DUR_MIN)
        by_id = {r["url"]: r for r in data["runs"]}
        self.assertEqual(by_id["https://github.com/o/r/actions/runs/1"]["author"], "alice")
        self.assertEqual(by_id["https://github.com/o/r/actions/runs/3"]["author"], "")

    def test_jobs_sorted_desc_and_steps_sorted_by_number_none_last(self):
        data = MODULE.build_drilldown_data(self._repos_data(), None, min_minutes=DUR_MIN)
        run1 = next(r for r in data["runs"] if r["dur"] == 90.0)
        self.assertEqual([j["name"] for j in run1["jobs"]], ["build", "test"])
        steps = run1["jobs"][0]["steps"]
        self.assertEqual([s["n"] for s in steps], [1, 2])

    def test_step_type_classification(self):
        data = MODULE.build_drilldown_data(self._repos_data(), None, min_minutes=DUR_MIN)
        run1 = next(r for r in data["runs"] if r["dur"] == 90.0)
        types = {s["name"]: s["type"] for s in run1["jobs"][0]["steps"]}
        self.assertEqual(types["checkout"], "构建")
        self.assertEqual(types["Run <tests>"], "执行测试")

    def test_missing_duration_renders_as_none_not_zero(self):
        runs = [_run(1, "E2E", 90 * 60)]
        jobs = [_job(10, 1, "build", 70 * 60)]
        steps = [_step(10, 1, "broken", None)]
        repos = {"o/r": {"runs": runs, "jobs": jobs, "steps": steps, "pr_metrics": [], "pr_workflows": []}}
        data = MODULE.build_drilldown_data(repos, None, min_minutes=DUR_MIN)
        self.assertIsNone(data["runs"][0]["jobs"][0]["steps"][0]["dur"])

    def test_run_with_no_jobs_and_failed_cancelled_conclusions(self):
        # run with zero jobs, plus a run whose job failed and another cancelled
        runs = [_run(1, "no-jobs", 90 * 60), _run(2, "mixed", 90 * 60, conclusion="failure")]
        jobs = [_job(20, 2, "failed-job", 70 * 60)]
        jobs[0]["conclusion"] = "failure"
        cancelled = _job(21, 2, "cancelled-job", 5 * 60)
        cancelled["conclusion"] = "cancelled"
        jobs.append(cancelled)
        steps = [_step(20, 1, "s", 65 * 60, conclusion="failure")]
        repos = {"o/r": {"runs": runs, "jobs": jobs, "steps": steps, "pr_metrics": [], "pr_workflows": []}}
        data = MODULE.build_drilldown_data(repos, None, min_minutes=DUR_MIN)
        nojobs = next(r for r in data["runs"] if r["wf"] == "no-jobs")
        self.assertEqual(nojobs["jobs"], [])  # run with no jobs → empty list, renderJobs shows "无 job 数据"
        mixed = next(r for r in data["runs"] if r["wf"] == "mixed")
        conclusions = {j["name"]: j["conclusion"] for j in mixed["jobs"]}
        self.assertEqual(conclusions["failed-job"], "failure")
        self.assertEqual(conclusions["cancelled-job"], "cancelled")
        self.assertEqual(mixed["conclusion"], "failure")  # run-level failure preserved



class WriteDrilldownHtmlTests(unittest.TestCase):
    def test_html_escapes_names_and_has_no_premature_script_close(self):
        runs = [_run(1, "E2E </script><img>", 90 * 60)]
        jobs = [_job(10, 1, "job</script>x", 70 * 60)]
        steps = [_step(10, 1, "step </script> y", 65 * 60)]
        repos = {"o/r": {"runs": runs, "jobs": jobs, "steps": steps, "pr_metrics": [], "pr_workflows": []}}
        out = "/tmp/test-drilldown.html"
        MODULE.write_drilldown_html(out, repos, "2026-07-01", "2026-07-31", {}, "test", min_minutes=DUR_MIN)
        html = Path(out).read_text(encoding="utf-8")
        blob = html.split("const DATA=", 1)[1].split(";\nfunction esc", 1)[0]
        # our guard turns </ into <\/ so a malicious </script> never closes the tag early
        self.assertNotIn("</script>", blob)
        # the table headers are present and server-rendered
        self.assertIn("代码仓", html)
        self.assertIn("提交人", html)
        self.assertIn("Run URL", html)
        # round-trip: undo the guard and the JSON is valid
        import json
        parsed = json.loads(blob.replace("<\\/", "</"))
        self.assertEqual(parsed["runs"][0]["wf"], "E2E </script><img>")
        self.assertEqual(parsed["runs"][0]["jobs"][0]["name"], "job</script>x")

    def test_empty_repos_data_produces_valid_html(self):
        MODULE.write_drilldown_html("/tmp/test-drilldown-empty.html", {}, "2026-07-01", "2026-07-31", {}, "t", min_minutes=DUR_MIN)
        html = Path("/tmp/test-drilldown-empty.html").read_text(encoding="utf-8")
        self.assertIn("命中 <b>0</b> 个 run", html)


if __name__ == "__main__":
    unittest.main()
