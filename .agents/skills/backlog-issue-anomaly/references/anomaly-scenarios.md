# Anomaly Scenarios — Exact Rules

Maps each abnormal state to the [issue lifecycle](https://github.com/opensourceways/backlog/blob/main/context/team/issue-workflow-guide.md) stage and gives the exact boolean the script evaluates. `N` = `--days` (default 7).

## Lifecycle → scenario mapping

```
Stage1 提交  ─┐
Stage2 审核  ─┤  (1)待分类  ─ accept ─► (2)待分配/(3)未排期
Stage3 设计  ─┤                              ─ assign+milestone ─► (5)开发停滞 ─ PR ─► (6)PR卡住 ─ merge ─► (4)未验收 ─ close
Stage4 开发  ─┤                                                                              ▲
Stage5 发布  ─┘                                                              (8)跳过准入(merge w/o accept)
                                                                                              │
                                                          (7)异常关闭(closed, no merged PR)  (9)rejected未关
```

## The 9 scenarios

| # | Name | Rule (boolean) | Anchor for staleness |
|---|------|----------------|----------------------|
| 1 | 待分类 | `state==OPEN AND not accepted AND not rejected AND created_age > N` | `createdAt` |
| 2 | 待分配 | `state==OPEN AND accepted AND assignees==[] AND accept_age > N` | `labeled accepted` event |
| 3 | 未排期 | `state==OPEN AND accepted AND milestone==null AND accept_age > N` | `labeled accepted` event |
| 4 | 未验收 | `state==OPEN AND any linked PR.merged==true` | none (state, not staleness) |
| 5 | 开发停滞 | `state==OPEN AND accepted AND assignees!={} AND milestone!=null AND linked_PRs==[] AND accept_age > N` | `labeled accepted` event |
| 6 | PR 卡住 | `state==OPEN AND any linked PR.state==OPEN AND PR.updated_age > N` | PR `updatedAt` |
| 7 | 异常关闭 | `state==CLOSED AND not any linked PR.merged AND not labeled {wontfix,duplicate,invalid,rejected}` | none |
| 8 | 跳过准入 | `any linked PR.merged==true AND not accepted` (open or closed) | none |
| 9 | rejected 未关 | `state==OPEN AND labeled rejected` | none |

`accept_age` falls back to `created_age` when the `labeled accepted` event is missing (shouldn't happen for accepted issues, but defensive).

## What "linked PR" means here

A pull request appears in an issue's timeline as a `CrossReferencedEvent` — i.e. the PR mentioned the issue (closing keyword like `Fixes #N`, or a manual `backlog#N` reference, or GitHub's auto-link). The script reads `state`, `merged`, `mergedAt`, `updatedAt` off that PR directly from the timeline, so there are **no per-PR API calls** — one paginated GraphQL query covers the whole repo.

## Cross-repo caveat (important for backlog)

The backlog repo tracks work that is **delivered in other repos** (om-datacenter, xihe, community-robots, …). Cross-referenced PRs from those repos *do* appear in the backlog issue timeline **if and only if** the PR referenced the issue. PRs that landed without referencing the issue are invisible to issue-side detection. Consequences:

- **S5 (开发停滞) and S7 (异常关闭) are upper bounds.** An issue flagged here *might* actually have been delivered by an unreferenced cross-repo PR. Treat as "needs review", not "definitely broken".
- **S4 / S6 / S8** only fire on referenced PRs, so they never over-flag — but they can miss unreferenced merged PRs (S8 would under-count skipped-triage cases).

If you need ground truth for a specific issue, run `gh pr list --repo <delivery-repo> --search "<issue#>"` in the likely delivery repo.

## Why these 9 (and not just the original 4)

The original 4 cover the lifecycle **entry** (1: un-triaged), **assignment/scheduling** (2, 3), and **exit** (4: merged-but-not-closed). They skip the **middle** — and the middle is where the most issues actually stall. On the first real run against `opensourceways/backlog` (2026-07-28, N=7, 631 issues scanned):

| Scenario | Count |
|---|---:|
| 1 待分类 | 124 |
| 2 待分配 | 67 |
| 3 未排期 | 117 |
| 4 未验收 | 149 |
| **5 开发停滞** | **23** |
| 6 PR卡住 | 70 |
| 7 异常关闭 | 112 |
| 8 跳过准入 | 77 |
| 9 rejected未关 | 1 |

S5 (the headline gap) found 23 issues that passed triage, were assigned and scheduled, then sat with no PR for 28–77+ days — invisible to the original 4.

## Tuning

- **N too small** → flags brand-new issues that are still in normal triage. Default 7 is a balance; use `--days 14` for a stricter "only truly stuck" view.
- **S4 has no time gate** by design (未验收 is a state, not a staleness). To see only stale un-verified issues, filter the report by the "merged Xd ago" column, or raise `--days` (which doesn't affect S4 but does prune the others, leaving S4/S7/S8/S9 to read more clearly).
- **`--closed` is required for 7 and 8.** Without it the script scans only open issues, so S7 (needs closed issues) and the closed half of S8 are skipped.
