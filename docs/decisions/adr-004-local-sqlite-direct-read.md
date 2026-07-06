# ADR-004: ci_analyze 支持本地 SQLite 直读（数据源切换）

**状态**: Accepted
**日期**: 2026-07-06

## 背景

`ci_analyze.py`（ADR-001）通过 Turso HTTP API 查询 libSQL DB，需要 `TURSO_DATABASE_URL` + `TURSO_AUTH_TOKEN` 凭证。`~/action-insight/etl/data/` 下已存放各项目的本地 SQLite 文件（如 `vllm-project-vllm-ascend.db`，125MB，含 37394 runs / 190212 jobs / 373575 steps），schema 与 Turso 库完全一致（同一套 ETL 写入）。

当前问题：无 Turso 凭证时无法分析；而有本地 db 文件却用不了。

## 决策

给 `ci_analyze.py` 增加本地 SQLite 直读模式，与 Turso 模式共存，通过参数/自动检测切换。

### 数据源选择
- `--db-path PATH` 显式指定本地 db 文件 → SQLite 模式
- 无 `--db-path` 但有 Turso 凭证 → Turso 模式（原行为不变）
- 都没有 → 自动检测 `~/action-insight/etl/data/{repo}.db`，命中则 SQLite 模式

### 接口设计
新增 `SqliteClient`，实现与 `TursoClient` 相同的 `query(sql) -> list[dict]` 接口（Python 标准库 `sqlite3`）。所有 `fetch_*` 函数零改动——它们只依赖 `client.query(sql)` 这一个方法。这是 seam（ADR-001 的核心模型）的直接体现。

### 多仓库差异
- Turso：单库多 repo，`repo_id IN (...)` 跨仓库查
- SQLite：每个 repo 一个 db 文件，`--db-path` 指向单库；多仓库对比时每仓查各自的 db

## 权衡

### 优点
- 0 网络调用、0 API、无需凭证，本地秒级分析
- schema 一致，SQL 查询语句不改，只换 client
- `SqliteClient` 用标准库 `sqlite3`，无新依赖

### 缺点 / 已知天花板
- 本地 db 依赖 ETL 同步（和 Turso 一样的时效性问题）
- 多仓库对比需逐库查再合并，不像 Turso 一条 SQL 跨库（但 ponytail：多仓库是少数场景，逐库查可接受）
- `sqlite3` 只读本地文件，不支持远程 libSQL 协议（Turso 模式仍保留用于远程场景）

## 备选方案
1. 只保留 Turso 模式，让用户配凭证——违反"本地有数据却用不了"的现状。否决。
2. 把 SQLite 文件导入 Turso 再查——多此一举，本地文件已是同 schema。否决。

## 影响
- `ci_analyze.py` 新增 `SqliteClient` + `--db-path` 参数 + 数据源选择逻辑
- `TursoClient` 保留不动，Turso 模式行为不变
- README 更新两种数据源的用法
