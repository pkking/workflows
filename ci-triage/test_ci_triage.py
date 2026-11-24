import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request
from ci_triage import GitHub, JobContext, RuleAnalyzer, SafeRedirect, classify, main, parse_job_url

REPO = "example/repo"
JOB = {"id": 2, "run_id": 1, "status": "completed", "conclusion": "failure"}


class TriageTests(unittest.TestCase):
    def setUp(self):
        self.analyzer = RuleAnalyzer()

    def result(self, log, job=JOB):
        return classify(JobContext(REPO, job, log), [self.analyzer])

    def test_developer(self):
        result = self.result("setup\nSyntaxError: invalid syntax\n")
        self.assertEqual(result["candidate_owner"], "DEVELOPER")
        self.assertEqual(result["findings"][0]["log_lines"], [2])
        self.assertEqual(result["attribution_status"], "UNVERIFIED")

    def test_infra(self):
        self.assertEqual(self.result("The self-hosted runner: node-1 lost communication with the server.")["candidate_owner"], "INFRA")

    def test_ambiguous(self):
        for symptom in ("AssertionError", "OOMKilled", "Could not resolve host", "ImagePullBackOff", "HCCL error"):
            with self.subTest(symptom=symptom):
                result = self.result(symptom)
                self.assertEqual(result["candidate_owner"], "UNKNOWN")
                self.assertTrue(result["findings"])

    def test_conflict(self):
        result = self.result("SyntaxError: invalid syntax\nThe self-hosted runner lost communication with the server")
        self.assertEqual(result["candidate_owner"], "UNKNOWN")

    def test_unmatched(self):
        self.assertEqual(self.result("exit code 1")["reason"], "no_matching_signature")

    def test_success(self):
        self.assertEqual(self.result("SyntaxError: invalid syntax", {**JOB, "conclusion": "success"})["reason"],
                         "not_a_completed_failed_job")

    def test_no_raw_log(self):
        self.assertNotIn("SECRET_MARKER", json.dumps(self.result("SyntaxError: invalid syntax SECRET_MARKER")))

    def test_rule_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            path.write_text(json.dumps({"version": 1, "rules": [
                {"id": "custom", "owner": "EXTERNAL", "symptom": "outage", "pattern": "outage"}]}))
            result = classify(JobContext(REPO, JOB, "outage"), [RuleAnalyzer(path)])
            self.assertEqual(result["candidate_owner"], "EXTERNAL")

    def test_url(self):
        self.assertEqual(parse_job_url("https://github.com/example/repo/actions/runs/1/job/2"), (REPO, 1, 2))
        for url in ("https://evil.test/example/repo/actions/runs/1/job/2", "https://github.com/example/../actions/runs/1/job/2"):
            with self.assertRaises(ValueError):
                parse_job_url(url)

    def test_job_run_mismatch(self):
        api = GitHub()
        with patch.object(api, "get", return_value=JOB):
            with self.assertRaises(ValueError):
                api.job(REPO, 99, 2)

    def test_redirect(self):
        req = Request("https://api.github.com/repos/example/repo/actions/jobs/2/logs",
                      headers={"Authorization": "Bearer secret"})
        redirected = SafeRedirect().redirect_request(req, None, 302, "", {}, "https://storage.example/log")
        self.assertIsNone(redirected.get_header("Authorization"))

    def test_bounded_sample(self):
        api = GitHub()
        with patch.object(api, "get", side_effect=[
            {"workflow_runs": [{"id": 1}]}, {"jobs": [{**JOB, "id": i} for i in range(20)]}]):
            self.assertEqual(len(list(api.failed_jobs(REPO, max_jobs=3))), 3)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            with patch.object(GitHub, "job", return_value=JobContext(REPO, JOB, "SyntaxError: invalid syntax")):
                code = main(["--job-url", "https://github.com/example/repo/actions/runs/1/job/2", "--output", str(path)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(path.read_text())["counts"], {"DEVELOPER": 1})

    def test_collection_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            with patch.object(GitHub, "job", side_effect=ValueError("secret details")):
                code = main(["--job-url", "https://github.com/example/repo/actions/runs/1/job/2", "--output", str(path)])
            self.assertEqual(code, 1)
            self.assertNotIn("secret details", path.read_text())


if __name__ == "__main__":
    unittest.main()
