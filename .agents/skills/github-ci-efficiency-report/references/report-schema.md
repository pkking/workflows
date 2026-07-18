# Workflow duration workbook schema

All durations are calculated from unrounded seconds and displayed as minutes with one decimal. P50 and P90 use the same inclusive linear interpolation as Excel `PERCENTILE.INC`.

## 报告信息

Records repository targets, local reporting range and timezone, UTC boundaries, filters, API/cache counts, completeness, and generation time.

## 指标定义

Defines every count, success-rate denominator, duration, threshold, percentile, invalid-sample rule, and comparison warning used by the workbook.

## Workflow统计

One row per configured repository, exact workflow display name, and workflow ID. Completed attempts are execution records. Success rate is `success / (success + failure)`. Duration distributions contain successful attempts whose actual E2E meets the effective workflow threshold.

Columns: comparison group/name, repository, workflow name/ID, conclusion counts, success rate, threshold/sample-quality fields, and avg/P50/P90 for actual E2E, maximum job queue, and maximum job execution.

## Run明细

One row per attempt assigned to the reporting range by `run_started_at`. Includes run/attempt identity, event and branch, timestamps, actual E2E, the maximum queue/execution durations and their job names, threshold inclusion, exclusion reason, and GitHub URL.

## Job统计

Grouped by repository + workflow ID + raw job name. Matrix variants are not merged. Queue distributions include successful and failed jobs with valid timestamps. Execution distributions include only successful jobs. Success rate is `success / (success + failure)`. Sorted by execution P90, queue P90, failure rate, and count, all descending.

## Step统计

Grouped by repository + workflow ID + raw job name + step name. Steps have no queue metric. Execution distributions include only successful steps. Success rate is `success / (success + failure)`. Sorted by execution P90, failure rate, and count, all descending.
