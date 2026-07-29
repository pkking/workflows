---
name: github-workflow-forensics
description: Forensic timeline analysis for a specific GitHub Actions run. Use when the user asks why a workflow took so long, which jobs or steps dominated, or wants a visual job/step timeline including runner queue time.
---

# GitHub Workflow Forensics

Treat the run as a **flight recorder**: localize wall-clock loss before naming a cause.

## 1. Select attempts

Accept GitHub run URLs, including `/attempts/N`, or numeric run IDs with `--repo owner/name`. Preserve each attempt separately.

When the user starts from a duration workbook, read `Run明细` and pass only the requested/threshold-matching Run URLs to this skill.

**Complete when:** every requested attempt has one input URL or `run_id + attempt` identity.

## 2. Generate the report

Authentication is `GITHUB_TOKEN`, then `GH_TOKEN`, then `gh auth token`.

```bash
python3 .agents/skills/github-workflow-forensics/scripts/analyze_workflow_run.py \
  https://github.com/OWNER/REPO/actions/runs/RUN_ID \
  --output reports/workflow-forensics-RUN_ID.html
```

Multiple URLs produce one report. For numeric IDs:

```bash
python3 .agents/skills/github-workflow-forensics/scripts/analyze_workflow_run.py \
  --repo OWNER/REPO RUN_ID
```

**Complete when:** the command exits successfully and the HTML contains every requested attempt.

## 3. Read the flight recorder

Report findings in this order:

1. wall-clock duration and status;
2. runner queue bottleneck;
3. longest Job execution and the Job finishing last;
4. longest Step and large Job time not covered by Step timestamps;
5. parallel tail: work that extends the final completion despite other Jobs finishing earlier.

Call these **timing causes**. GitHub timestamps do not expose the dependency graph or explain log semantics, so label true dependency critical paths and causes such as network slowness as hypotheses unless logs prove them.

**Complete when:** every claimed cause names a Job/Step, minutes, share of workflow wall time, and its evidence strength.

## Output contract

The standalone HTML must show:

- one common wall-clock axis per attempt;
- every Job with separate queue and execution bars;
- every Step nested under its Job;
- exact timestamps/durations in labels or tooltips;
- ranked timing causes and links back to GitHub;
- incomplete timestamps as visible data gaps, never zero duration.
