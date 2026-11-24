# ci-triage

CI failure triage PoC. Python 3.10+, standard library only.

## Usage

```bash
python3 ci-triage/ci_triage.py --job-url https://github.com/OWNER/REPO/actions/runs/RUN/job/JOB
python3 ci-triage/ci_triage.py --sample-repo vllm-project/vllm-ascend --output report.json
cd ci-triage && python3 -m unittest -v
```

Authentication: optional CI_TRIAGE_TOKEN, GH_TOKEN or GITHUB_TOKEN. Public access may be rate-limited or unavailable. Configure a token with read-only access to intended public repositories if required; never commit tokens.

## Contract

Job metadata and logs -> Analyzer plugins -> findings -> candidate ownership. JSON includes rule IDs, log line numbers and UNVERIFIED attribution status. No raw logs are included. Unknown or conflicting signatures produce UNKNOWN. Log lines are untrusted and may be spoofed; a signature is not proof of root cause. Syntax errors can originate in dependencies; runner disconnects can be caused by workloads. No confirmed owner is emitted.

To extend: add rules in rules.json and regression tests, or implement Analyzer.analyze(JobContext) and register it in main. Add evidence adapters for ARC/K8s/Prometheus before confirmed attribution. EXTERNAL requires a custom rule or more evidence; no built-in external signature.

## GitHub Actions

- PR/push: deterministic regression tests.
- Daily at 01:23 UTC: sample up to three failed runs created in the preceding 24 hours, latest attempt, first 100 jobs per run, at most ten failed jobs.
- Manual workflow_dispatch: single public job URL or the same sample.
- Structured JSON artifact retained 14 days. API failures fail the workflow. Empty samples are valid, not proof of CI health. No upstream comments or automatic reruns.

The daily run is a smoke test, not complete monitoring or an accuracy benchmark. Scheduled runs start only after merge; public repositories may disable schedules after inactivity. Log access, retention and rate limits may prevent collection. Logs larger than 16 MiB are skipped with a collection error. Use public repositories only in this public workflow; reports expose repo/job identifiers and rule IDs. Do not configure tokens with access to private data.

ADR: [012](../docs/decisions/adr-012-ci-failure-triage.md).
