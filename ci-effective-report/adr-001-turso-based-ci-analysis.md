# ADR-001: 基于 Turso DB 的 CI 效率分析

**状态**: Accepted
**日期**: 2026-06-10

## 背景

原有的 `github_ci_efficiency_report.py` 通过 GitHub REST API 获取 CI 数据：
- 对大型仓库（如 vllm-ascend，数万 runs）需要数千次 API 调用
- 耗时长（10-30 分钟），且易触发 secondary rate limit
- 无法高效支持多仓库对比（需重复调用 API）

同时，我们已将 CI 数据同步到 Turso DB（libSQL），包含完整 runs、jobs、steps、PR metrics 数据。

## 决策

新增 `ci_analyze.py`，通过 Turso HTTP API 直接查询 DB 数据进行分析，替代 GitHub API 调用。

### 技术要点

- 使用 Turso v2/pipeline HTTP API（`/v2/pipeline`），纯 SQL 查询
- 分批获取数据：jobs 每批 5000 run_ids，steps 每批 200 job_ids
- 支持任意仓库、多仓库对比、自定义时间范围
- 输出格式与原方案兼容（相同 Excel sheet 结构）

### 数据流

```
Turso DB → HTTP SQL → Python 分析 → Excel 报告
```

替代了：
```
GitHub REST API → 数千次请求 → Python 分析 → Excel 报告
```

### 数据库覆盖

| 表 | 数据量 | 用途 |
|---|---|---|
| runs | ~19 万 | Workflow 级别指标 |
| jobs | ~82 万 | Job 级别耗时、排队时间 |
| steps | ~165 万 | Step 级别分类、成功率 |
| pr_metrics | ~1,340 | PR CI 时长、评审时长 |
| pr_workflows | ~1.8 万 | PR ↔ Workflow 关联 |

## 权衡

### 优点
- **无 rate limit**：Turso HTTP API 无调用频率限制
- **速度快**：单天数据 < 2 分钟，原方案需 10+ 分钟
- **多仓库对比**：一条查询覆盖多个仓库
- **数据历史完整**：DB 保留了完整的 CI 历史

### 缺点
- **数据时效性依赖同步**：需要定期将 GitHub Actions 数据同步到 Turso
- **新增仓库需等待同步**：未同步的仓库无法分析
- **缺少部分上下文**：如 PR comments、代码 diff 内容（需额外 API 调用）
- **Turso 查询限制**：单次查询最多返回 5000 行，需分批处理

## 备选方案

1. **保留纯 API 方案**：简单但慢，不适合大数据量和多仓库
2. **本地 SQLite dump**：无网络延迟，但需手动维护数据同步
3. **GraphQL API**：比 REST 更高效，但仍有 rate limit 且复杂度高

## 影响

- 原 `github_ci_efficiency_report.py` 保留作为备选（API mode）
- `.env` 需包含 `TURSO_DATABASE_URL` 和 `TURSO_AUTH_TOKEN`
- Excel 输出格式保持兼容，现有分析流程不受影响
