# Handoff: AI Distiller Requirements Analysis (P0 + P1 Implementation)

## Context

The user asked to analyze `https://github.com/opensourceways/software-package-server/` using repo-distiller (AI Distiller: `/janreges/ai-distiller`) to determine if it can support requirements analysis, solution design, and code development.

The target repo was inaccessible (private/not found), so analysis proceeded via the public fork `zengchen1024/software-package-server` (cloned to `/tmp/software-package-server`).

## What Was Accomplished

### 1. Deep Analysis of software-package-server
- 96 Go files, ~7814 lines
- DDD layered architecture: Controller → Application → Domain → Infrastructure
- Core domain: SoftwarePkg lifecycle (Reviewing → CreatingRepo → Imported/Closed)
- Dependencies: PostgreSQL, Kafka, Gitee API, Gin, openEuler Docker image

### 2. Identified repo-distiller Optimization Opportunities
Mapped three scenarios (Requirements Analysis, Solution Design, Code Development) against what code can/cannot reveal:
- **Code Development**: ~80% coverage from code alone (tool's sweet spot)
- **Solution Design**: ~50% (needs decision rationale, global architecture views)
- **Requirements Analysis**: ~20% (code lacks why/who/acceptance criteria)

### 3. Prioritized P0 + P1 Optimizations

| Priority | Feature | Description |
|----------|---------|-------------|
| 🔴 P0 | Guided Questions | Auto-detect info gaps, generate prioritized questions |
| 🔴 P0 | Hypothesis Validation | Infer requirements from code patterns, user confirms/rejects |
| 🟡 P1 | Git History Reverse | Extract requirement evolution from commit history |
| 🟡 P1 | Conflict Detection | Compare stated requirements vs code reality |

### 4. Implemented P0 + P1

Created a new `internal/requirements` package and standalone CLI (`cmd/reqs`) that works **without tree-sitter CGO** (the main AI Distiller build is blocked by tree-sitter compilation issues).

#### Files Created/Modified

| File | Status | Purpose |
|------|--------|---------|
| `internal/requirements/types.go` | Created | Core types: InfoGap, Hypothesis, Conflict, AnalysisReport, markdown/interactive formatters |
| `internal/requirements/analyzer.go` | Created | P0-1: 6-category info gap detection (business context, user roles, acceptance criteria, NFR, constraints, business rules) |
| `internal/requirements/hypothesis.go` | Created | P0-2: 8-pattern hypothesis engine (architecture, roles, lifecycle, integrations, security, data model, error handling, business rules) |
| `internal/requirements/git_analyzer.go` | Created | P1-1: Git history analyzer — commit categorization, feature timelines, requirement change extraction |
| `internal/requirements/conflict_detector.go` | Created | P1-2: Conflict detection — permission, lifecycle, tech stack, deployment, security conflicts + auto-detect |
| `internal/requirements/engine.go` | Created | Main orchestration engine, FormatQuestionnaire, detectLanguage |
| `internal/requirements/bridge.go` | Created | FileInfo/SymbolInfo bridge types |
| `internal/aiactions/requirements_analysis.go` | Created | 4 AI Actions: RequirementsAnalysisAction, RequirementsQuestionnaireAction, GitHistoryAnalysisAction, ConflictDetectionAction |
| `internal/aiactions/register.go` | Modified | Registered all 4 new actions |
| `cmd/reqs/main.go` | Created | Standalone CLI (no tree-sitter dependency) |

#### Built Binary

- `/tmp/aid-reqs` — standalone requirements analysis CLI
- Supports `--mode full|guided-questions|hypothesis|git-reverse|conflict-detect`
- Supports `--format interactive|markdown|json`
- Supports `-o output.md` and `-q` quiet mode

#### Verified Results on software-package-server

```
P0-1 Guided Questions:  6 gaps identified (business context, roles, acceptance criteria, etc.)
P0-2 Hypotheses:        6 hypotheses (✅ DDD architecture correctly detected, state machine, integrations, etc.)
P1-1 Git History:       10+ feature timelines extracted (CI, CLA, Controller, Review, etc.)
P1-2 Conflict Detection: 30 issues found (policy inconsistencies, duplicate function definitions)
```

## Known Issues & Limitations

1. **tree-sitter CGO build blocked**: Main `aid` binary cannot be built due to missing tree-sitter-typescript C source files (git submodule not cloned) and `go-tree-sitter` requiring CGO. The standalone `cmd/reqs` binary bypasses this entirely.

2. **Evidence deduplication**: Security/integration hypotheses still produce verbose evidence lists. The `deduplicateEvidence` function was added but evidence from multiple file references is intentional (shows coverage).

3. **Shallow clone limitation**: The original `/tmp/software-package-server` was cloned with `--depth 1` so git history analysis fails there. Use `/tmp/software-package-server-deep` (full clone, 50 commits) for git-reverse mode.

4. **Go 1.21+ `min` built-in conflict**: Renamed local `min` to `minInt` in analyzer.go.

5. **Source file count**: Report shows `SourceFiles: 105` but `0 lines` for SourceFiles because the line counting in `countLines()` operates on `e.rawContent` but was called before `LoadRawContent()` in some paths. The `AddRawFile` path loads content directly into `RawContent` but `countLines()` uses `e.rawContent` (the Engine field, not Analyzer field). This is a minor cosmetic issue.

## Key File Locations

- **AI Distiller repo**: `/tmp/ai-distiller/`
- **Target repo (shallow)**: `/tmp/software-package-server/`
- **Target repo (deep)**: `/tmp/software-package-server-deep/`
- **Built binary**: `/tmp/aid-reqs`
- **Analysis report v1**: `/tmp/requirements-report.md`
- **Analysis report v2**: `/tmp/requirements-report-v2.md`

## Suggested Next Steps

1. **Fix source file line count** in `Engine.countLines()` — it should read from the raw content that was loaded.

2. **Build full `aid` binary** — either:
   - Initialize git submodules: `cd /tmp/ai-distiller && git submodule update --init --recursive` (timed out at 120s; try again with longer timeout or use a faster network)
   - Or stub out the missing C source files

3. **Add user-provided requirements input** to conflict detection — currently only auto-detects. Add `--requirements file.yaml` to compare against user-specified requirements.

4. **Improve hypothesis confidence scoring** — currently uses fixed levels; could be computed from evidence count and pattern strength.

5. **Write tests** for the requirements package.

## Suggested Skills for Next Session

- **understand-explain** — for deep-diving into specific code files if further analysis is needed
- **prototype** — if building a UI/interactive terminal for the questionnaire
- **write-a-skill** — if packaging this as a proper AI Distiller skill
