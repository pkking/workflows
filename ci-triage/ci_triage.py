"""CI triage: GitHub metadata and logs, provisional ownership only."""
import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from typing import Protocol
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent
REPO = r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+"
OWNERS = {"DEVELOPER", "INFRA", "EXTERNAL", "UNKNOWN"}
MAX_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class JobContext:
    repo: str
    job: dict
    log: str


class Analyzer(Protocol):
    def analyze(self, context: JobContext) -> list[dict]: ...


class RuleAnalyzer:
    def __init__(self, path=ROOT / "rules.json"):
        catalog = json.loads(Path(path).read_text(encoding="utf-8"))
        if catalog["version"] != 1:
            raise ValueError("Unsupported catalog")
        self.rules = []
        ids = set()
        for rule in catalog["rules"]:
            if rule["id"] in ids or rule["owner"] not in OWNERS:
                raise ValueError("Invalid or duplicate rule")
            ids.add(rule["id"])
            self.rules.append((rule, re.compile(rule["pattern"], re.IGNORECASE)))

    def analyze(self, context):
        findings = []
        lines = context.log.splitlines()
        for rule, pattern in self.rules:
            matches = []
            for number, line in enumerate(lines, 1):
                if pattern.search(line):
                    matches.append(number)
                    if len(matches) == 3:
                        break
            if matches:
                findings.append({"rule_id": rule["id"], "candidate_owner": rule["owner"],
                                 "symptom": rule["symptom"], "log_lines": matches})
        return findings


def validate_repo(repo):
    if not re.fullmatch(REPO, repo) or repo.split("/")[1] in {".", ".."}:
        raise ValueError("Invalid repository")
    return repo


def parse_job_url(url):
    match = re.fullmatch(r"https://github\.com/(" + REPO + r")/actions/runs/([1-9][0-9]*)/job/([1-9][0-9]*)/?", url)
    if not match:
        raise ValueError("Expected a GitHub Job URL")
    repo, run, job = match.groups()
    return validate_repo(repo), int(run), int(job)


def classify(context, analyzers):
    result = {"repository": context.repo, "job_id": context.job["id"],
              "run_id": context.job["run_id"], "candidate_owner": "UNKNOWN",
              "attribution_status": "UNVERIFIED", "findings": []}
    if context.job.get("status") != "completed" or context.job.get("conclusion") != "failure":
        result["reason"] = "not_a_completed_failed_job"
        return result
    findings = [f for analyzer in analyzers for f in analyzer.analyze(context)]
    result["findings"] = findings
    owners = {f["candidate_owner"] for f in findings}
    if len(owners) == 1 and "UNKNOWN" not in owners:
        result["candidate_owner"] = next(iter(owners))
        result["reason"] = "matching_signatures"
    else:
        result["reason"] = "ambiguous_or_conflicting_signatures" if findings else "no_matching_signature"
    return result


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https":
            raise ValueError("Non-HTTPS redirect")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header("Authorization")
        return redirected


class GitHub:
    def __init__(self, token=None):
        self.token = token
        self.opener = build_opener(SafeRedirect())

    def get(self, path, *, logs=False):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "ci-triage-poc",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request("https://api.github.com" + path, headers=headers)
        with self.opener.open(request, timeout=30) as response:
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("Response exceeds size limit")
        return data.decode("utf-8", errors="replace") if logs else json.loads(data)

    def job(self, repo, run_id, job_id):
        path = f"/repos/{validate_repo(repo)}/actions/jobs/{job_id}"
        job = self.get(path)
        if job["id"] != job_id or job["run_id"] != run_id:
            raise ValueError("Job does not belong to supplied run")
        log = self.get(path + "/logs", logs=True) if (
            job.get("status") == "completed" and job.get("conclusion") == "failure") else ""
        return JobContext(repo, job, log)

    def failed_jobs(self, repo, max_runs=3, max_jobs=10):
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
        query = urlencode({"status": "failure", "created": ">=" + since, "per_page": max_runs})
        runs = self.get(f"/repos/{validate_repo(repo)}/actions/runs?{query}")["workflow_runs"]
        count = 0
        for run in runs[:max_runs]:
            run_id = int(run["id"])
            jobs = self.get(f"/repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100")["jobs"]
            for job in jobs:
                if job.get("status") == "completed" and job.get("conclusion") == "failure":
                    yield run_id, int(job["id"])
                    count += 1
                    if count >= max_jobs:
                        return


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--job-url")
    source.add_argument("--sample-repo")
    parser.add_argument("--rules", type=Path, default=ROOT / "rules.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    api = GitHub(os.getenv("CI_TRIAGE_TOKEN") or os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN"))
    analyzers = [RuleAnalyzer(args.rules)]
    results, errors = [], []
    try:
        if args.job_url:
            repo, run, job = parse_job_url(args.job_url)
            targets = [(run, job)]
        else:
            repo = args.sample_repo
            targets = api.failed_jobs(repo)
        for run, job in targets:
            try:
                results.append(classify(api.job(repo, run, job), analyzers))
            except (URLError, OSError, ValueError, KeyError) as exc:
                errors.append({"run_id": run, "job_id": job, "error": type(exc).__name__,
                               "http_status": getattr(exc, "code", None)})
    except (URLError, OSError, ValueError, KeyError) as exc:
        errors.append({"error": type(exc).__name__, "http_status": getattr(exc, "code", None)})
    report = {"schema_version": 1, "sample": bool(args.sample_repo),
              "generated_at": datetime.now(timezone.utc).isoformat(),
              "counts": dict(Counter(item["candidate_owner"] for item in results)),
              "results": results, "collection_errors": errors}
    output = json.dumps(report, indent=2, ensure_ascii=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
