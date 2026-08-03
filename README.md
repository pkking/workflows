# workflows

自动化工作流集合：多 agent 分析、仓库蒸馏、CI 效率报告。每个子项目可独立安装。

## 项目

### 🔬 yt-obsidian — YouTube → Obsidian 多 agent 管线

4-agent challenge/consensus 模式分析 YouTube 视频，写出结构化 Obsidian 笔记（概念、方法论、完整 trace）。字幕优先转写 + Whisper 兜底。

```bash
cd yt-obsidian && pip install -e .
yt-obsidian analyze "machine learning fundamentals" --vault ~/ObsidianVault
```

详见 [yt-obsidian/README.md](yt-obsidian/README.md)。

---

### 📦 repo-distiller — 仓库蒸馏

把 GitHub 仓库蒸馏成结构化特性清单、架构决策、bugfix：AST 解析（Python/TS/JS/Go/Java/Rust）+ Git 历史 + IaC + 多 agent。

```bash
cd repo-distiller && pip install -e .
repo-distiller distill https://github.com/owner/repo --output ./distilled
```

详见 [repo-distiller/README.md](repo-distiller/README.md)。

---

### 📊 ci-effective-report — GitHub CI 效率分析

针对 GitHub Actions 的 CI 耗时分析：DB 聚合统计（Excel）+ 下钻 Gantt 时间轴 HTML（多仓 tab、job 排队/运行、串/并行一目了然）+ agent skill（attempt-aware 统计 / 单 run 取证）。三种入口按数据源与需求选用——`ci_analyze.py`（DB）、`gh_ci_report.py`（直采 GitHub API）、两个 `SKILL.md`（agent 调用）。

```bash
# DB 背书聚合（有 Turso/SQLite 凭证）
python3 ci-effective-report/ci_analyze.py --repo vllm-project/vllm-ascend --from 2026-07-01 --to 2026-07-31
# 无 DB 凭证直采 GitHub API
python3 ci-effective-report/gh_ci_report.py --target vllm-project/vllm-ascend:E2E --from 2026-07-30 --to 2026-07-30
```

详见 [ci-effective-report/README.md](ci-effective-report/README.md)（工具、CLI、Excel sheet、下钻 HTML、skill 触发关键字、ADR）。

## Setup

子项目各自独立安装，Python 3.10+：

```bash
pip install -e ./yt-obsidian
pip install -e ./repo-distiller
pip install openpyxl requests   # ci-effective-report
```

## 环境变量

| 变量 | 用于 | 说明 |
|---|---|---|
| `YOUTUBE_API_KEY` | yt-obsidian | YouTube Data API v3 |
| `OPENAI_API_KEY` | yt-obsidian | Whisper / agent LLM |
| `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN` | ci-effective-report (DB 模式) | Turso DB 凭证 |
| `GITHUB_TOKEN` | ci-effective-report (API 模式) | GitHub Actions 元数据 |

## License

MIT
