---
name: ci-drilldown-report
description: >-
  生成 GitHub Actions CI 效率下钻 HTML 报告，含卡时核算、Gantt 时间轴、Timing Causes
  耗时原因排序和 CSV 导出。当用户说"CI 耗时详细分析"、"下钻报告"、"卡时"、"加速卡
  资源消耗"、"为什么这个 run 这么慢"、"job 时间轴"时触发。用于按日期范围批量采集多仓
  多 workflow 的 runs/jobs/steps，展示 NPU/CPU 卡时、型号分布、达标率、排队与执行百分位。
---

# CI Drilldown Report

生成单文件下钻 HTML：首页 >阈值分钟 run 表格 → 展开 run 下钻 job Gantt 时间轴 + Timing Causes → 再展开 job 下钻 step 明细。

## 何时用这个 skill

- 用户要看某个时间范围的 CI 详细耗时（不是 Excel 统计，是可下钻的 HTML）
- 用户问卡时 / 加速卡资源消耗 / NPU 耗时 / CPU 耗时
- 用户问某个 run 为什么慢（Timing Causes 已内置，不需要单独跑 forensics）
- 用户要导出 CSV 做离线计算

## 何时不用

- 要 Excel 跨仓对比 + attempt-aware 统计 → 用 `github-ci-efficiency-report` skill
- 要查 Turso/SQLite DB 已入库数据 → 直接跑 `ci_analyze.py`（本 skill 只走 GitHub API）

## Run

```bash
# 默认：读 ci-effective-report/drilldown-targets.yaml（仅 NPU 仓）
python3 ci-effective-report/gh_ci_report.py --from 2026-08-05 --to 2026-08-05

# 全量配置（含 GPU 仓，对比 GPU/NPU）
python3 ci-effective-report/gh_ci_report.py \
  --config .github-ci-efficiency.yaml \
  --from 2026-08-05 --to 2026-08-05

# 指定单个仓
python3 ci-effective-report/gh_ci_report.py \
  --target vllm-project/vllm-ascend:E2E \
  --from 2026-08-05 --to 2026-08-05

# 筛选 config 里的仓（子串匹配）
python3 ci-effective-report/gh_ci_report.py \
  --from 2026-08-05 --to 2026-08-05 --repo sglang
```

认证：`GITHUB_TOKEN` → `GH_TOKEN` → `gh auth token`。

## 配置

默认读 `ci-effective-report/drilldown-targets.yaml`（仅 NPU 仓）。`--config .github-ci-efficiency.yaml` 切换到含 GPU 的全量配置。`--repo` 子串筛选 config 内的仓。

## 报告内容

### 统计区（每仓一个 tab）

两行表格，NPU 和 CPU 分行：

| | 总机时 | 失败机时 | P50耗时 | P90耗时 | P50排队 | P90排队 | 达标率 |
|---|---|---|---|---|---|---|---|
| NPU | ... | ... | rowspan=2 | rowspan=2 | rowspan=2 | rowspan=2 | rowspan=2 |
| CPU | ... | ... |

- **总机时**：NPU = job 执行时长 × 卡数；CPU = job 墙钟耗时
- **失败机时**：conclusion 为 failure/cancelled 的 run 的机时
- **达标率**：(有效 run < 60min) / (总有效 run)，workflow 级度
- **型号分布**：表格下方显示 `a3 1004.4卡时 ｜ 310p 387.3卡时 ｜ ...`
- a3 标签卡数除以 2 为真实卡数；a2/310p 不变

### Run 表格

每行：代码仓、提交人、创建时间、结束时间、Workflow、耗时(min)、NPU卡时、CPU耗时、状态、Run URL。

### 下钻 detail

展开 run → Gantt 时间轴（橙=排队、蓝=运行）+ Timing Causes（5 类耗时原因按耗时降序）→ 展开 job → step 明细表。

Timing Causes（0 额外 API 调用，从已有数据计算）：
1. Runner queue — 最长排队 job
2. Job execution — 最长执行 job
3. Step execution — 最长 step
4. Parallel tail — 最后完成与倒数第二的 gap
5. Uninstrumented Job time — job 执行 - sum(step durations)

### CSV 导出

每 tab 有"导出 CSV"按钮，导出全量 run（不限阈值）+ 统计摘要，BOM 兼容 Excel。

## 输出

默认输出 `reports/ci-drilldown-{from}_to_{to}.html`，`--output` 可指定路径。

## 卡时核算规则（ADR-010, ADR-011）

- 卡数来源优先级：Job API `labels` → SHA 固定 workflow 定义 fallback（按 repo/workflow/SHA 缓存）
- 仅解析 `linux-aarch64-<型号>-<卡数>` 标签；a3 卡数 ÷ 2
- CPU job（`linux-*-cpu-*`）单独统计，不计入 NPU 卡时
- 缺少 timestamps 或无法解析卡数的 job 不计入数值，标为未知

## 渲染前刷新

多仓采集耗时长，采集早期可能 run 还在 in_progress。渲染前自动刷新非 completed run 的 status/conclusion/updated_at；刷新失败保留采集快照，不中断报告。
