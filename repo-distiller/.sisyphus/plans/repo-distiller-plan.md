# Repo Distiller - Development Plan

## Current Status
**Phase 1: Core Analysis Engine & Orchestration (Completed)**
- [x] **CLI Entry Point**: `repo-distiller analyze` command with token/repo/branch options.
- [x] **AST Parser**: Language-specific extraction for Python, TypeScript/TSX, Go.
  - Extracts: Symbols, APIs (Routes/Handlers), Models, Imports.
- [x] **Git Analyzer**: History mining for decision signals.
  - Extracts: Churn hotspots, Co-change coupling, Bugfix classification.
- [x] **IaC Parser**: Infrastructure configuration analysis.
  - Extracts: Helm charts/values, Kustomize bases/patches, ArgoCD applications.
- [x] **Orchestrator**: Multi-agent debate via `pi` CLI.
  - Roles: PM, Architect (Proponents) -> DFX, UX, Security (Challengers) -> Integrator.

## Next Steps

### Phase 2: Robustness & Real-world Testing
1.  **Parallel Execution**:
    - Implement concurrent analysis for multiple repositories to speed up large mono-repos or multi-repo systems.
2.  **Structured Agent Output**:
    - Enforce JSON output format from agents for downstream automation.
    - Add validation layer to parse and merge agent responses.
3.  **Performance Tuning**:
    - Optimize AST parsing for large files (skip node_modules, vendor, etc.).
    - Implement incremental analysis (cache results based on commit hash).
4.  **Real-world Validation**:
    - Run against large open-source repos (e.g., Kubernetes, Prometheus) to validate extraction accuracy.
    - Tune Git analysis thresholds (churn limit, coupling count).

### Phase 3: Reporting & Integration
1.  **Report Generation**:
    - Generate final HTML/PDF reports from the consensus output.
    - Add visualization for service topology and coupling graphs.
2.  **CI/CD Integration**:
    - Package as a GitHub Action.
    - Add support for running as a pre-commit or pre-merge hook.
3.  **LLM Flexibility**:
    - Add support for configuring different LLM backends (OpenAI, Claude, Ollama) via `.env`.
