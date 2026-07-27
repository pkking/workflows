---
name: backlog-issue-anomaly
description: Scan opensourceways/backlog (or any GitHub repo using the /accepts triage workflow) for issues stuck at any point in their lifecycle — un-triaged, accepted-but-unassigned, accepted-but-unscheduled, stalled development, stale open PRs, merged-but-not-verified, abnormally closed, skipped triage, or rejected-but-still-open. Aggregates by submitter (issue author), resolves real names from opensourceways/opensourceway/community/user-info.yaml, and writes a 3-sheet Excel report. Use when asked to "find abnormal/stuck issues", "find backlog anomalies", "backlog 异常", "backlog异常", "backlog 健康度", "backlog健康度", "backlog 需求分析", "backlog需求分析", "backlog 体检", "哪些 issue 卡住了", "哪些 issue 没人接", "待分配/未排期/未验收 issue", "找卡住的需求", "backlog triage", "triage backlog issues", "stuck issues in backlog", "check backlog health", or to analyze the health/triage state of a backlog repo.
---

# Backlog Issue Anomaly Scanner

Finds issues stuck anywhere in the [issue lifecycle](https://github.com/opensourceways/backlog/blob/main/context/team/issue-workflow-guide.md) (提交 → 审核 → 设计 → 开发合入 → 发布) and writes an Excel report aggregated by submitter. The 4 scenarios most people think of cover only the entry and exit; this skill also catches the middle — which is where the most issues actually stall.

## Run

```bash
python3 .agents/skills/backlog-issue-anomaly/scripts/backlog_issue_anomaly.py \
  --repo opensourceways/backlog --days 7 --closed -o backlog_anomaly_report.xlsx
```

`--repo` defaults to `opensourceways/backlog`. `--days` (default `7`) is the staleness window. `--closed` also scans closed issues — **required** for scenarios 7 (异常关闭) and 8 (跳过准入) to populate; without it the report covers only open issues. `-o` defaults to `backlog_anomaly_report.xlsx`.

## Dependencies (checked at startup)

The script exits with a clear fix-it message if either is missing:

1. **`gh` CLI installed and logged in** — checked via `gh auth token` (env vars `GITHUB_TOKEN`/`GH_TOKEN` take precedence). Fix: `gh auth login`.
2. **`openpyxl`** (Excel writer) — `pip install openpyxl`.

No other dependencies. The rest is Python stdlib. The submitter→name map is fetched live from `opensourceways/opensourceway/community/user-info.yaml` (parsed in-process, no PyYAML needed — the file is simple `github_id:`/`name:` pairs).

## Output — 3 sheets

**Sheet `说明`** — repo, time window, scan counts, generation time, the 9 scenario rules, and the cross-repo caveat.

**Sheet `异常统计(按提交人)`** — one row per submitter who has ≥1 flagged issue, sorted by total desc:
- Col A `提交人` (GitHub login, the issue author)
- Col B `姓名` (from user-info.yaml; falls back to the login if absent)
- Cols C–K `1-待分类` … `9-rejected未关` — count per anomaly type (an issue with N types counts in N columns)
- Col L `合计`
- Final row `合计` — per-type grand totals.

**Sheet `异常issue全集`** — one row per flagged issue (deduplicated; multiple types joined by `, `):
- `提交人` · `姓名` · `Issue链接` · `Issue编号` · `标题` · `异常类型`

## What it detects

Nine abnormal states. 1–4 are the original request; 5–9 are the gaps the analysis surfaced (5 alone caught **23 real issues** in backlog on first run).

| # | Scenario | Rule | Needs `--closed`? |
|---|----------|------|:-:|
| 1 | 待分类 | open, no `accepted`, age > N days | |
| 2 | 待分配 | open, `accepted`, no assignee, accept-age > N days | |
| 3 | 未排期 | open, `accepted`, no milestone, accept-age > N days | |
| 4 | 未验收 | open, a linked PR is merged but the issue is still open | |
| 5 | 开发停滞 | open, `accepted`, has assignee + milestone, no PR, accept-age > N days | |
| 6 | PR 卡住 | open, linked PR is open and stale (updated > N days ago) | |
| 7 | 异常关闭 | closed, no linked PR merged, not closed-as `wontfix`/`duplicate`/`invalid`/`rejected` | ✓ |
| 8 | 跳过准入 | a linked PR is merged but the issue was never `accepted` | ✓ |
| 9 | rejected 未关 | open, carries `rejected` (should have been closed) | |

Exact booleans and the lifecycle→scenario map are in `references/anomaly-scenarios.md`.

## How it works

One paginated GraphQL query pulls every issue (open, and closed with `--closed`) with `author`, labels, assignees, milestone, and `timelineItems` filtered to `LABELED_EVENT` + `CROSS_REFERENCED_EVENT`. PR linkage (state, `merged`, `mergedAt`, `updatedAt`) is read straight off the cross-referenced PRs in the timeline — no per-PR API calls. Accept time = the `LabeledEvent` for `accepted`, falling back to `createdAt`.

## Limitations

- `timelineItems` is capped at 100 items per issue per query. Issues with 100+ label/cross-ref events could miss a PR reference deep in their history. Backlog issues stay well under this in practice.
- **Cross-repo caveat (read this):** backlog tracks work delivered in *other* repos (om-datacenter, xihe, community-robots, …). Cross-referenced PRs from those repos appear in the issue timeline **only if the PR referenced the issue**. PRs that landed without referencing it are invisible to issue-side detection, so **S5 (开发停滞) and S7 (异常关闭) are upper bounds** — an issue flagged here *might* have been delivered by an unreferenced cross-repo PR. Treat as "needs review". For ground truth on one issue, run `gh pr list --repo <delivery-repo> --search "<issue#>"` in the likely delivery repo.
- `accepted` is the triage signal per the workflow doc. `approved` is a PR-side label and is **not** treated as "issue accepted".
- S4 has no time gate by design (未验收 is a state, not a staleness) — freshly-merged issues appear too; raise `--days` to prune the others and let S4/S7/S8/S9 read more clearly.
