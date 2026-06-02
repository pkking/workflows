# workflows

A collection of automation workflows for developer productivity — multi-agent analysis, repository distillation, and CI efficiency reporting.

## Projects

### 🔬 yt-obsidian — Multi-Agent YouTube → Obsidian Pipeline

Analyzes YouTube videos using a 4-agent challenge/consensus pattern and writes structured, Obsidian-ready notes (concepts, methodologies, and full trace logs).

- **Smart search** across views, date, rating, and relevance
- **Subtitle-first transcription** with Whisper fallback
- **4 specialized agents**: Concept Extractor, Methodology Analyst, Skeptic, Synthesizer
- **Full traceability**: JSON logs + Markdown trace files per stage

```bash
cd yt-obsidian
pip install -e .
yt-obsidian analyze "machine learning fundamentals" --vault ~/ObsidianVault
```

See [yt-obsidian/README.md](yt-obsidian/README.md) for full usage, CLI options, and architecture details.

---

### 📦 repo-distiller — Repository Distiller

Distills GitHub repositories into structured feature lists, architectural decisions, and bugfixes using AST parsing, Git history analysis, and multi-agent orchestration.

- AST-based code parsing (Python, TypeScript, JavaScript, Go, Java, Rust)
- Git history analysis for decision and bugfix extraction
- IaC (Infrastructure as Code) parsing
- Multi-agent orchestration with challenge/consensus pattern

```bash
cd repo-distiller
pip install -e .
repo-distiller distill https://github.com/owner/repo --output ./distilled
```

---

### 📊 ci-effective-report — GitHub CI Efficiency Report

Generates an Excel workbook with detailed CI/CD metrics from GitHub Actions — workflow stats, job stats, step classifications, PR e2e times, and hierarchical PR/workflow/job/step breakdowns.

- **workflow_stats**: run count, avg/p50/p90 duration per workflow
- **job_stats**: job count, durations, queue times
- **step_stats**: execution count, durations, success rate, step type classification (build / CI setup / test)
- **pr_stats**: PR e2e time and review-after-CI time
- **pr_details**: hierarchical tree view of PRs → workflows → jobs → steps

```bash
python3 ci-effective-report/scripts/github_ci_efficiency_report.py \
  --repo pkking/action-insight \
  --since 2026-05-01 \
  --until 2026-05-22 \
  --output ci-efficiency.xlsx
```

Requires `GITHUB_TOKEN` or `GH_TOKEN` environment variable.

---

## Setup

Each sub-project is independently installable:

```bash
# yt-obsidian
pip install -e ./yt-obsidian

# repo-distiller
pip install -e ./repo-distiller

# ci-effective-report
pip install openpyxl  # only dependency for the report script
```

Python 3.10+ required for all projects.

## Environment Variables

| Variable | Used by | Description |
|---|---|---|
| `YOUTUBE_API_KEY` | yt-obsidian | YouTube Data API v3 key |
| `OPENAI_API_KEY` | yt-obsidian | Whisper API / agent LLM access |
| `GITHUB_TOKEN` | ci-effective-report | GitHub API access for Actions metadata |

## License

MIT
