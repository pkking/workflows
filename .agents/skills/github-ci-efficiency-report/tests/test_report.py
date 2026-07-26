import datetime as dt
import importlib.util
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "github_workflow_duration_report.py"
SPEC = importlib.util.spec_from_file_location("duration_report", SCRIPT)
REPORT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["duration_report"] = REPORT
SPEC.loader.exec_module(REPORT)


UTC = dt.timezone.utc


def stamp(minutes: int) -> dt.datetime:
    return dt.datetime(2026, 7, 2, tzinfo=UTC) + dt.timedelta(minutes=minutes)


def attempt(conclusion="success", attempt_number=1):
    target = REPORT.Target("o/r", "E2E", "o", "E2E", 10)
    jobs = [
        REPORT.JobRecord(1, "test (a)", "completed", conclusion, stamp(0), stamp(5), stamp(25), [
            REPORT.StepRecord("run", "completed", "success", 1, stamp(6), stamp(20)),
        ]),
        REPORT.JobRecord(2, "test (b)", "completed", "success", stamp(2), stamp(8), stamp(30), []),
    ]
    return REPORT.AttemptRecord(target, 42, "E2E", 100, attempt_number, "completed", conclusion,
                                "push", "main", stamp(0), stamp(31), "https://example/100", jobs)


class ReportTests(unittest.TestCase):
    def test_percentile_inc_and_invalid_durations(self):
        self.assertEqual(REPORT.percentile_inc([0, 10, 20, 30, 40], .9), 36)
        self.assertIsNone(REPORT.seconds_between(stamp(2), stamp(1)))

    def test_attempt_e2e_uses_job_boundaries_and_rerun_is_distinct(self):
        record = attempt()
        self.assertEqual(record.e2e_seconds, 30 * 60)
        self.assertEqual(record.key, (100, 1))
        self.assertNotEqual(record.key, attempt(attempt_number=2).key)

    def test_workflow_threshold_only_filters_workflow_duration(self):
        records = [attempt(), attempt("failure")]
        rows = REPORT.workflow_rows(records)
        self.assertEqual(rows[0]["执行次数"], 2)
        self.assertEqual(rows[0]["有效耗时样本数"], 1)
        self.assertEqual(len(REPORT.job_rows(records)), 2)

    def test_collect_uses_definition_name_not_run_display_name(self):
        class FakeClient:
            def paginate(self, path, item_key, ttl_seconds=REPORT.LIST_TTL_SECONDS):
                if path.endswith("/actions/workflows"):
                    return [{"id": 7, "name": "PR Test Base"}]
                if path.endswith("/actions/workflows/7/runs"):
                    return [{
                        "id": 8,
                        "name": "PR #123 - a change",
                        "run_attempt": 1,
                        "status": "completed",
                        "conclusion": "success",
                        "run_started_at": "2026-07-02T00:00:00Z",
                        "updated_at": "2026-07-02T00:05:00Z",
                    }]
                if path.endswith("/attempts/1/jobs"):
                    return []
                raise AssertionError(path)

            def get(self, path, params=None, ttl_seconds=REPORT.LIST_TTL_SECONDS):
                raise AssertionError(path)

        target = REPORT.Target("o/r", "PR Test Base", "o", "PR", 10)
        records, errors = REPORT.collect(
            FakeClient(), [target], stamp(0), stamp(1440), concurrency=1
        )
        self.assertEqual(errors, [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].workflow_name, "PR Test Base")

    def test_config_precedence_and_repo_root(self):
        args = Namespace(config=None, repo="o/r", workflow=["E2E"], min_e2e_minutes=12)
        self.assertEqual(REPORT.load_targets(args)[0].min_e2e_minutes, 12)
        self.assertEqual(REPORT.repo_root(), Path(__file__).parents[5])

    def test_workbook_has_six_sheets_and_minutes(self):
        records = [attempt()]
        args = Namespace(date_from="2026-07-02", date_to="2026-07-02")
        cache = REPORT.Cache(Path(tempfile.mkdtemp()))
        client = REPORT.GitHubClient("token", cache)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.xlsx"
            REPORT.write_workbook(output, records, [], args, UTC, "UTC", stamp(0), stamp(1440), client, False)
            openpyxl = __import__("openpyxl")
            workbook = openpyxl.load_workbook(output, read_only=True)
            self.assertEqual(workbook.sheetnames, ["报告信息", "指标定义", "Workflow统计", "Run明细", "Job统计", "Step统计"])
            self.assertEqual(workbook["Run明细"]["O2"].value, 30.0)


if __name__ == "__main__":
    unittest.main()
