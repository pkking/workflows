# ADR-005: 合并 CI 分析脚本，统一统计逻辑与 success-only 开关

**状态**: Accepted
**日期**: 2026-07-06

## 背景

`ci-effective-report/` 有两个独立演进的 CI 分析脚本，统计逻辑不一致：

| | `ci_analyze.py`（目的1/3） | `ci_duration_analysis.py`（目的2） |
|---|---|---|
| 数据源 | Turso/SQLite DB | GitHub REST API |
| 运行范围 | 仓库级（全 workflow） | 单 workflow |
| conclusion 过滤 | 不过滤（含 failure/cancelled 脏数据） | success-only |
| percentile 约定 | 0-100 制（自实现） | 0-1 制（复用 skill 脚本） |
| step 分类 | `step_names_map.get`（无兜底） | `classify_step`（正则兜底） |
| 输出 | Excel | HTML 洞察 + Excel |
| PR 维度 | 有 | 无 |

问题：同一指标（job 耗时 P50）在两脚本里口径不同；percentile 约定不一致是隐患；step 分类逻辑重复且不统一；统计函数各写一份。

## 决策

### 合并为单一脚本
`ci_analyze.py` 成为唯一入口，吸收 `ci_duration_analysis.py` 的能力：
- **数据源**：DB（Turso/SQLite，ADR-001/004）+ GitHub API（ADR-003 的预过滤路径）共存，按 `--db-path`/凭证/自动检测切换
- **运行范围**：`--workflow NAME` 指定时走单 workflow 的 API 预过滤路径（省调用）；否则 DB 全仓库
- **`--success-only` 开关**：job/workflow 耗时统计只算 `conclusion==success` 的样本（默认 off，保持目的1/3 的全貌统计；on 时对齐目的2 口径）
- **`--min-duration N`**：配合 `--success-only`，排除短 run（目的2 的 >10min 过滤）
- **`--insights`**：输出 HTML 洞察报告（Top 问题+证据），否则只 Excel
- `ci_duration_analysis.py` 删除，功能并入 `ci_analyze.py`

### 统一统计逻辑（一处实现，两处复用）
提取共享统计函数到 `ci_analyze.py` 内部（不单独建模块，避免文件膨胀）：
- **percentile**：统一用 0-1 制（与 github_ci_efficiency_report.py 对齐），删除 ci_analyze 原 0-100 制实现，所有调用点改传 0.5/0.9
- **classify_step**：统一用正则兜底版（ci_duration 的实现），ci_analyze 原 `step_names_map.get` 替换
- **analyze_workflow_stats / analyze_job_stats / analyze_step_stats**：加 `success_only` 参数，过滤逻辑统一在此层
- **generate_top_issues**：从 ci_duration 搬入，DB/API 两种数据源归一化后复用

### 数据模型归一
DB 路径返回原始 dict（`j["duration_seconds"]`）；API 路径返回 dataclass（`j.duration_min`）。统计函数统一操作归一化后的 dict（`{"name", "conclusion", "duration_min", "queue_min", ...}`），两条路径在 fetch 后各自归一化。

## 权衡

### 优点
- 一个脚本、一套口径，消除不一致
- success-only 开关让目的1/3（全貌）和目的2（成功耗时）用同一工具切换
- percentile/step 分类统一，无隐患

### 缺点
- `ci_analyze.py` 体量增大（吸收 ~300 行统计+洞察+HTML 逻辑）
- DB 与 API 两条 fetch 路径共存，归一化层有少量适配代码

## 影响
- 删除 `ci_duration_analysis.py`
- `ci_analyze.py` 新增 `--success-only`/`--min-duration`/`--insights` 参数 + GitHub API fetch 路径
- SKILL.md 更新指向 `ci_analyze.py`
- workflow_runs_on_date.py 的 `fetch_workflow_id`/`norm_job_name` 保留（被 ci_analyze 复用）
