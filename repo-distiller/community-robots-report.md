# 📋 Integrator Report — community-robots

---

## Part 0: Repomix Context Summary

### 📦 Repository Overview
- **Languages**: Bash (orchestration, deploy), Python (helpers, issue-manage sub), Go (robot submodules), YAML (IaC, Kustomize)
- **Total Files**: 53 files scanned by Repomix
- **Key Directories**:
  - `.ai-flow/` — AI-driven development pipeline: agent specs (`agents/`), deploy scripts (`deploy/`), orchestration (`src/orchestrate.sh`), gates, tests
  - `.claude/` — Claude Code agent settings and skills
  - `templates/` — Document templates (Architecture Design, Bug Report, Requirement Analysis, Test, Release)
  - `issue_docs/` — Per-issue deliverable storage (requirement analysis, design specs, test reports)
  - `.ai-flow/deploy/` — Preview deployment: `preview.sh`, `test-sync/sync.sh`, `test-sync/routes.sh`, `services.yaml`
- **Entry Points**:
  - `.ai-flow/src/orchestrate.sh` — Main orchestrator for AI dev pipeline (highest churn: 10)
  - `.ai-flow/scripts/develop.sh` — Local dev runner
  - `.ai-flow/scripts/analyze.sh` — Requirement analysis generator
  - `.ai-flow/deploy/preview.sh` — Preview environment deployment
  - `robot-universal-*` submodules (Go, robot-framework-lib) — Webhook handlers on port 8888
  - `robot-issue-manage` submodule (Python) — Issue management on port 8080

### 🔍 Secret Scan Results
- **5 plaintext tokens** in `.ai-flow/deploy/services.yaml.subs.robot-universal-*.vault_keys.token` — assign, associate, cla, label, lifecycle
- **Repomix high-severity finding**: `summary` file flagged: *"Be aware that this file may contain sensitive information"*
- Etherpad deployments properly use K8s secrets (`ether-secret`) for DB creds, OAuth secrets, admin passwords — **good practice**
- Hot-topic miners use Vault sidecar injection (`/vault/secrets/conf.yaml`) — **proper pattern**
- Kafka tracker mounts secrets from K8s secret volume — **proper pattern**

### 📋 Notable Patterns
- **AI-driven development pipeline**: Shell-orchestrated multi-agent adversarial workflow (design → dev → review → tester) with automated gates (SAST, secrets, license checks)
- **Hub-and-spoke Kubernetes**: Central `community-hot-topic` cluster with LLM mining pipeline; satellite services (summary, Etherpad, certification, Kafka tracker)
- **Copy-paste IaC**: 12 near-identical miner deployments in `community-hot-topic` — same image, same resources, same probes; only ConfigMap prompts differ
- **Runtime-clone preview**: Preview deployments use `go run .` / `python main.py` in `golang:1.25-bookworm` / `python:3.12-bookworm` containers — no build step for preview
- **Kafka as MQ**: Single-node KRaft Kafka for hook-delivery/dispatcher; shared across all issues
- **Helm-based test archive**: Test deployments in `Open-Infra-Ops/helm-chart-value` with istio VirtualService routing; preview degrades to nginx Ingress
- **Prompt-as-code**: LLM system prompts (2-5KB Chinese text each) embedded in K8s ConfigMaps — prompt changes require 12 separate edits

---

## Part 1: Features & Requirements

### ✅ Agreed Features (Strong Consensus)

1. **Webhook Ingestion & Routing** (`robot-universal-hook-delivery`)
   - **User Problem**: Disconnected webhook handling across community platforms → single ingress point routes events to correct downstream handler
   - **Module**: `robot-universal-hook-delivery` sub (Go, port 8888, handle_path: `gitcode-hook`)
   - **Acceptance Criteria**: (1) Receives webhook on `/gitcode-hook`, returns 200; (2) Routes to correct downstream robot by event type; (3) HMAC validation via Vault-injected `deliverySecrets`
   - **UX Assessment**: CLI/terminal-only; no user-facing UI
   - **Feasibility**: **At-Risk** — no health probes, no NetworkPolicies, Vault token revocation disabled on shutdown

2. **Hook Dispatch via Kafka** (`robot-hook-dispatcher`)
   - **User Problem**: Reliable event distribution to multiple robot handlers
   - **Module**: `robot-hook-dispatcher` sub (Go, port 8888, handle_path: `webhook`)
   - **Acceptance Criteria**: (1) Consumes from Kafka topic; (2) Dispatches to registered handlers; (3) Config from Vault `dispatcher` key
   - **UX Assessment**: N/A (backend service)
   - **Feasibility**: **At-Risk** — Kafka topic auto-creation only; no explicit topic provisioning in IaC

3. **Universal Robots** (assign, associate, cla, label, lifecycle)
   - **User Problem**: Manual issue management across projects → centralized automation
   - **Module**: `robot-universal-assign`, `robot-universal-associate`, `robot-universal-cla`, `robot-universal-label`, `robot-universal-lifecycle` (all Go, port 8888)
   - **Acceptance Criteria**: (1) Each robot responds on `/gitcode-hook`; (2) Token from Vault `token` key; (3) Performs designated action (assign/label/lifecycle/CLA check)
   - **UX Assessment**: N/A (backend service)
   - **Feasibility**: **At-Risk** — 5 plaintext tokens in services.yaml; all share same port/handle_path pattern

4. **Issue Management** (`robot-issue-manage`)
   - **User Problem**: Fragmented issue lifecycle tracking
   - **Module**: `robot-issue-manage` sub (Python, port 8080)
   - **Acceptance Criteria**: (1) `pip install -r requirements.txt` succeeds; (2) `python main.py` starts on port 8080; (3) Config from `config.yaml` or `config.template.yaml`
   - **UX Assessment**: N/A (backend service)
   - **Feasibility**: **Feasible** — simplest deployment pattern, no Vault dependency

5. **LLM Community Topic Mining Pipeline** (12 community miners + hot-topic server)
   - **User Problem**: No automated extraction of hot topics/issues from community repos
   - **Module**: `community-hot-topic` namespace — 12 data-clean miners + 1 `hotopic-server-deployment`
   - **Acceptance Criteria**: (1) Each miner runs scheduled LLM summary + rerank; (2) Results published to hot-topic-server via `/internal/v1/topic-review/<community>`; (3) Closed solutions posted to `/internal/v1/hot-topic/<community>/solution`
   - **UX Assessment**: N/A (backend pipeline)
   - **Feasibility**: **At-Risk** — hardcoded SiliconFlow API dependency, ConfigMap prompt bloat, single-replica server

6. **Preview Deployment Pipeline** (`.ai-flow/deploy/preview.sh` + `test-sync/`)
   - **User Problem**: No safe preview environment for testing changes before merge
   - **Module**: `.ai-flow/deploy/preview.sh`, `test-sync/sync.sh`, `test-sync/routes.sh`
   - **Acceptance Criteria**: (1) `preview.sh` creates ns, detects changed subs; (2) `sync.sh` syncs test形态 → preview形态 per sub; (3) `routes.sh` generates merged nginx Ingress; (4) Tester can access preview URL
   - **UX Assessment**: Terminal-only deployment scripts; no dashboard
   - **Feasibility**: **At-Risk** — known blocking: `robot-framework-lib` GitHub 404 for private deps

7. **Community Summary Dashboards** (6 communities)
   - **User Problem**: No centralized community activity summaries
   - **Module**: `community-summary` namespace — openubmc, openlookeng (replicas:0), opengauss, openeuler, mindspore, cann
   - **Acceptance Criteria**: (1) Each community has deployment + service + ingress; (2) OAuth proxy enabled; (3) Accessible at `summary-<community>.test.osinfra.cn`
   - **UX Assessment**: **No web UI analysis possible** — deployments exist but frontend code not in this repo
   - **Feasibility**: **Feasible** — standard deployment pattern

8. **Community Etherpad** (4 communities)
   - **User Problem**: No collaborative document editing for communities
   - **Module**: `community-etherpad` namespace — openubmc (replicas:1), openlookeng/openeuler/mindspore (replicas:0)
   - **Acceptance Criteria**: (1) OIDC auth for openubmc; (2) DB connected via secrets; (3) Accessible at `etherpad.<community-domain>`
   - **UX Assessment**: Third-party app (Etherpad Lite) — UX not configurable here
   - **Feasibility**: **At-Risk** — no health probes, Recreate strategy causes downtime

9. **Community Certification System**
   - **User Problem**: No automated talent certification for community contributors
   - **Module**: `community-certification-system` / `community-talent-certification-it-system`
   - **Acceptance Criteria**: (1) 2 replicas with RollingUpdate; (2) Health probes on port 8080; (3) Accessible at `talent-assessment.<community-domain>`
   - **UX Assessment**: **No web UI analysis possible** — frontend not in this repo
   - **Feasibility**: **Feasible** — well-configured deployment

### ⚖️ Features with Conditions

1. **Kafka Community Tracker** (`community-tracker-om-collect`)
   - **Conditions**: Add liveness/readiness probes; add resource limits; verify Kafka topic provisioning
   - **Module**: `infra-common/common-applications/infra-test-cluster/hk/om-kafka/community-tracker/deployment.yaml`
   - **Acceptance Criteria**: (1) Pod has liveness + readiness probes; (2) Memory and CPU limits set; (3) Kafka consumer processes messages within acceptable lag

2. **AI Development Pipeline Orchestration** (`.ai-flow/src/orchestrate.sh`)
   - **Conditions**: Add structured logging; add error propagation; migrate from shell to typed language or add comprehensive test harness
   - **Module**: `.ai-flow/src/orchestrate.sh`
   - **Acceptance Criteria**: (1) All script exits propagate error codes; (2) Structured log output for each pipeline stage; (3) Test coverage for gate failure paths

3. **Hot-Topic Server Aggregation**
   - **Conditions**: Add HPA or at minimum replica > 1; add NetworkPolicies for `/internal/v1/*` endpoints; add circuit breaker for SiliconFlow API
   - **Module**: `infra-common/common-applications/infra-test-cluster/hk/community-hot-topic/server/deployment.yaml`
   - **Acceptance Criteria**: (1) At least 2 replicas; (2) NetworkPolicy restricts `/internal/v1/*` to miner pods only; (3) Request retry/fallback logic for LLM API failures

---

## Part 2: Architecture & Technical Decisions

### 🏗️ Architecture Assessment
This is an **IaC-managed Kubernetes platform** hosting a community analytics/mining system across 9 test environments. The architecture follows a **hub-and-spoke pattern**: a central `community-hot-topic` cluster with an LLM-powered data processing pipeline, surrounded by satellite services. All infrastructure lives in a single `infra-common` repo using **Kustomize**. The codebase itself is shell-driven (`src/orchestrate.sh` is the top churn file), with heavy reliance on **Claude/Claude Code agent workflows** — much logic is prompt/agent-based rather than traditional compiled code.

### 🔑 Technical Decisions
- **Kustomize over Helm for IaC**: All deployments use Kustomize; no Helm charts in this repo. Test archive uses Helm in external `Open-Infra-Ops/helm-chart-value` — **File**: `infra-common/**/kustomization.yaml`
- **Runtime-clone for preview**: Preview pods `git clone` + `go run .` / `python main.py` instead of building images — **File**: `.ai-flow/deploy/test-sync/sync.sh`
- **Shell orchestration for AI pipeline**: Multi-agent workflow orchestrated by `.ai-flow/src/orchestrate.sh` — **File**: `.ai-flow/src/orchestrate.sh`
- **Vault Agent sidecar for secrets** (hot-topic miners only): `/vault/secrets/conf.yaml` injected — **File**: miner deployment `env.SECRET_CONFIG: /vault/secrets/conf.yaml`
- **K8s secrets for Etherpad creds**: `ether-secret` referenced properly — **File**: `community-etherpad/**/deployment.yaml`
- **Kafka KRaft single-node**: No ZooKeeper; `auto.create.topics.enable: true` — **File**: `.ai-flow/deploy/preview.sh` (kafka Deployment)
- **nginx Ingress for preview, istio VirtualService for test**: Preview cluster uses nginx; test uses istio — **File**: `test-sync/routes.sh`

### ⚠️ Architectural Risks (from Architect)
- **ConfigMap bloat (CRITICAL)**: Each miner's `config.yaml` embeds 2-5KB LLM prompts in ConfigMaps across 12 communities. Any prompt change requires 12 separate edits. **Severity: High** — **File**: `infra-common/.../community-hot-topic/*/configmap.yaml`
- **Single point of failure — hotopic-server**: Single replica, receives from 12 miners, publishes to same endpoint. No HPA. **Severity: High** — **File**: `infra-common/.../community-hot-topic/server/deployment.yaml`
- **Copy-paste infrastructure duplication**: 12 near-identical deployments — same image, resources, probes, strategy. Only ConfigMap content differs. Should be parameterized. **Severity: High** — **File**: `infra-common/.../community-hot-topic/*/deployment.yaml`
- **No health probes on Etherpad**: All 4 Etherpad instances have `liveness_probe: null` and `readiness_probe: null`. **Severity: High** — **File**: `community-etherpad/**/deployment.yaml`
- **Hardcoded external LLM dependency**: All miners → `https://api.siliconflow.cn/v1`. No fallback, no rate-limiting, no circuit breaker. **Severity: High** — **File**: miner ConfigMap `llm.base_url`
- **Shell-based orchestration, no type safety**: `src/orchestrate.sh` highest churn (10), 0 symbols, 0 methods, 0 calls. **Severity: Medium** — **File**: `.ai-flow/src/orchestrate.sh`
- **Secret sprawl**: Etherpad embeds DB credentials, OAuth secrets, admin passwords via K8s secrets; rotation across 4 communities is manual. **Severity: Medium**
- **No test/staging/prod separation**: All 9 environments tagged `test`. No blue/green, no canary. **Severity: Medium**
- **openlookeng summary at `replicas: 0`**: Disabled but still in manifest — dead infrastructure code. **Severity: Low**

---

## Part 3: Security & Reliability

### 🔐 Security Vulnerabilities (from Security — ALL findings preserved)

| # | Type | Location | Severity | Detail |
|---|------|----------|----------|--------|
| 1 | Plaintext tokens | `.ai-flow/deploy/services.yaml` (subs robot-universal-assign/associate/cla/label/lifecycle) | **HIGH** | 5 token keys with `is_plaintext: true` — literal values in YAML, not K8s Secrets or Vault paths |
| 2 | External LLM API key exposure | Miner ConfigMap `llm.base_url: https://api.siliconflow.cn/v1` | **HIGH** | API key presumably via Vault, but unverifiable from IaC alone. If fallback to ConfigMap/env, it's exposed |
| 3 | No NetworkPolicies | All 9 environments | **HIGH** | Zero NetworkPolicies. Any pod can reach any other. hot-topic server's `/internal/v1/*` only protected by obscurity |
| 4 | Repomix secret in summary | `summary` file | **HIGH** | Scan output itself flagged as containing sensitive information |
| 5 | No liveness/readiness probes | Etherpad deployments (4 communities) | **MEDIUM** | openUBMC Etherpad (replicas:1) has null probes — unresponsive pod never restarted or removed from service |
| 6 | No health probes on Kafka consumer | `community-tracker-om-collect` | **MEDIUM** | Zero probes, bare memory request only — crashed consumer silently stops collecting |
| 7 | Mixed HTTP/HTTPS in pipeline URLs | Miner ConfigMap `closed_url` | **MEDIUM** | Most use `http://`, but openeuler uses `https://hotopic-data.test.osinfra.cn` — inconsistent scheme |
| 8 | Vault token revocation disabled | `vault-agent-injector` deployment env `AGENT_INJECT_REVOKE_ON_SHUTDOWN: "false"` | **MEDIUM** | Terminated pods' Vault tokens remain valid until TTL expiry |
| 9 | OAuth proxy inconsistent | Summary deployments | **MEDIUM** | Some have `oauth-proxy.yaml`, others don't. Etherpad openlookeng/openeuler have no OIDC env vars visible |
| 10 | Container images tag-based (mutable) | All deployments | **MEDIUM** | Tag references (e.g., `v1.0.20251212140932`) not SHA256 pinned — compromised registry could serve different image |
| 11 | HTTP health probes | community-hot-topic miners | **LOW** | All use `scheme: "HTTP"` for probes on port 8080 — unencrypted if sensitive data |
| 12 | Debug mode enabled | `imagepullsecret-patcher` env `CONFIG_DEBUG: "true"` | **LOW** | Debug logging may leak registry credentials or pull patterns |

### 🛡️ API Auth Patterns
- **No API schemas or swagger docs detected** (`total_schemas: 0`). Authentication inference from IaC only.
- **Hot-topic server `/internal/v1/*`**: ClusterIP-only, **no visible authentication**, relies on network isolation — ineffective without NetworkPolicies
- **Etherpad openUBMC**: OIDC via `usercenter.openubmc.cn` with `REQUIRE_AUTHENTICATION: "true"` — **authenticated**
- **Other Etherpad instances** (openlookeng, openeuler, mindspore): No OIDC env vars — **auth status unknown**
- **Community summary services**: Reference `oauth-proxy.yaml` in kustomization — **likely OAuth2-authenticated**
- **Talent certification systems**: No visible auth config — **unverified**
- **No API rate limiting, WAF rules, or API gateway** in any ingress/service definition

### 🔧 Reliability & Observability Gaps (from DFX — ALL gaps preserved)
- **Plaintext secrets in IaC (CRITICAL)**: 5 token keys in `.ai-flow/deploy/services.yaml` are `is_plactext: true` for robot-universal-assign/associate/cla/label/lifecycle. Any commit exposes these. — **File**: `.ai-flow/deploy/services.yaml`
- **Zero error handling chains**: `error_flow_summary` reports total_creations: 0, total_propagations: 0, total_consumptions: 0. Code lacks structured error handling. — **Inferred from scanner**
- **No logging instrumentation**: `logging_imports` empty. `src/orchestrate.sh` and `apimagic_table.py` emit no structured logs. — **File**: `.ai-flow/src/orchestrate.sh`, `apimagic_table.py`
- **Stale container images**: `community-summary` deployments use 2022 image tags (~3.5 years old). — **File**: `community-summary/*/deployment.yaml`
- **Missing health probes**: `community-tracker-om-collect` (Kafka consumer) — no probes. Etherpad 4 communities — no probes. `imagepullsecret-patcher` — no probes. — **File**: respective deployment.yaml
- **Recreate strategy on Etherpad**: Full downtime on every rollout. — **File**: `community-etherpad/**/deployment.yaml`
- **`replicas: null` on services**: Falls to K8s default (1) but uncontrolled. — **File**: multiple deployment.yaml
- **No logging imports anywhere**: Zero `import logging`, no structured logging, no shell `trap`/`set -x`. — **Code-wide**
- **No metrics/exporters**: No Prometheus endpoints, no service monitors. Only TCP socket health checks. — **Code-wide**
- **Health probes shallow**: TCP socket or basic HTTP GET only — don't validate downstream deps (Vault, LLM API, DB, Kafka). — **All deployments with probes**
- **No distributed tracing**: Webhook → AI flow → template → issue_docs pipeline — no correlation ID, no request tracing. — **Pipeline-wide**
- **ConfigMap as observability anti-pattern**: LLM prompts in ConfigMaps are unobservable — no way to tell which prompt version produced which result. — **File**: `community-hot-topic/*/configmap.yaml`

### 📈 Maintainability Issues (from DFX)
- **`src/orchestrate.sh` (churn: 10)**: Shell as orchestration layer — no AST, no type safety, no import graph, no testability. — **File**: `.ai-flow/src/orchestrate.sh`
- **`CLAUDE.md` (churn: 9)**: Agent config volatility — business logic in natural-language prompts, untestable, unversionable. — **File**: `CLAUDE.md`, `.claude/settings.json`
- **`robot-universal-assign` / `robot-universal-label` (churn: 3)**: Submodule pointer churn — parent chasing upstream without stable pinned version. — **File**: `.gitmodules`
- **Copy-paste IaC across 12 communities**: Every miner deployment structurally identical. No Kustomize common base, no Helm templating. — **File**: `community-hot-topic/**/deployment.yaml`
- **`skills/README.md` + `src/deployer/README.md` (churn: 2)**: Documentation drift alongside code — unstable interface. — **File**: `skills/README.md`, `.ai-flow/src/deployer/README.md`

---

## Part 4: UX Findings

### ⚡ Performance Concerns (from UX — ALL findings preserved)
- **4-agent challenge/consensus pattern in yt-obsidian**: 4 sequential LLM calls per video — 30s–2min minimum per video without parallelization/caching. — **File**: `yt-obsidian` (external tool, not in this repo directly)
- **Heavy computation in repo-distiller**: AST parsing across 6 languages + Git history + IaC parsing + multi-agent orchestration — blocks on slowest agent. — **File**: `repo-distiller` (external tool)
- **No progress indicators, streaming output, or ETA**: Long silent waits during CLI execution. — **Code-wide CLI tools**
- **No `--dry-run` or `--preview` flags**: Users must commit to full execution. — **CLI tools**
- **`.xlsx` output from ci-effective-report**: Heavy, not diffable or reviewable in terminal/CI. — **File**: `ci-effective-report`

### ♿ Accessibility Gaps (from UX — ALL findings preserved)
- **Terminal-only tools, no alternative interfaces**: No web UI for users who cannot use terminal. — **All CLI tools**
- **Limited output formats**: Only Obsidian markdown, directory structure, `.xlsx` — no JSON, CSV, HTML export. — **All CLI tools**
- **No `NO_COLOR` / `--no-color` flag documented**: Potential issues for screen reader users. — **CLI tools**
- **Error messages English-only**: No localization. — **CLI tools**
- **No `--verbose` or `--json-output` flags**: Cannot enable programmatic accessibility tooling integration. — **CLI tools**
- **Whisper subtitle fallback is positive**: Provides text for audio content. — **yt-obsidian**

---

## Part 5: Action Items

### 📋 Action Items (prioritized, with file references)

- [ ] **[HIGH]** Remove plaintext tokens from `.ai-flow/deploy/services.yaml` — migrate to K8s Secrets or Vault references — Owner: Security/DevOps — File: `.ai-flow/deploy/services.yaml`
- [ ] **[HIGH]** Add NetworkPolicies for `community-hot-topic` namespace — restrict `/internal/v1/*` to miner pods only — Owner: DevOps — File: `infra-common/.../community-hot-topic/server/`
- [ ] **[HIGH]** Add liveness/readiness probes to all Etherpad deployments — Owner: DevOps — File: `community-etherpad/**/deployment.yaml`
- [ ] **[HIGH]** Add liveness/readiness probes to `community-tracker-om-collect` — Owner: DevOps — File: `infra-common/.../om-kafka/community-tracker/deployment.yaml`
- [ ] **[HIGH]** Set replicas > 1 for `hotopic-server-deployment` — add HPA — Owner: DevOps — File: `infra-common/.../community-hot-topic/server/deployment.yaml`
- [ ] **[HIGH]** Parameterize 12 miner deployments — extract common base via Kustomize component or Helm — Owner: DevOps — File: `community-hot-topic/**/` (all 12 miners)
- [ ] **[HIGH]** Add circuit breaker / retry logic for SiliconFlow LLM API — or add fallback model endpoint — Owner: Dev — File: miner ConfigMap `llm.base_url`
- [ ] **[HIGH]** Add structured logging to `src/orchestrate.sh` — use `set -x`, `trap`, or migrate to Python/Go — Owner: Dev — File: `.ai-flow/src/orchestrate.sh`
- [ ] **[MEDIUM]** Fix mixed HTTP/HTTPS in pipeline URLs — standardize `closed_url` scheme across all miners — Owner: DevOps — File: `community-hot-topic/**/configmap.yaml`
- [ ] **[MEDIUM]** Enable Vault token revocation on shutdown — set `AGENT_INJECT_REVOKE_ON_SHUTDOWN: "true"` — Owner: DevOps — File: `openubmc-community-cn4-x86-cluster/vault/deployment.yaml`
- [ ] **[MEDIUM]** Pin container images to SHA256 digests — prevent mutable tag substitution — Owner: DevOps — File: all `deployment.yaml` files
- [ ] **[MEDIUM]** Add OAuth proxy or auth to talent certification and openlookeng/openeuler/mindspore Etherpad — Owner: Security — File: respective ingress/deployment configs
- [ ] **[MEDIUM]** Add resource limits to `community-tracker-om-collect` — prevent OOM without restart — Owner: DevOps — File: `community-tracker/deployment.yaml`
- [ ] **[MEDIUM]** Disable `CONFIG_DEBUG: "true"` in `imagepullsecret-patcher` — Owner: DevOps — File: `image-secret-patcher/deployment.yaml`
- [ ] **[MEDIUM]** Remove or re-enable `openlookeng` summary deployment (`replicas: 0`) — clean dead infrastructure — Owner: DevOps — File: `community-summary/openlookeng/`
- [ ] **[MEDIUM]** Replace `Recreate` strategy with `RollingUpdate` on Etherpad — avoid user-visible downtime — Owner: DevOps — File: `community-etherpad/**/deployment.yaml`
- [ ] **[LOW]** Pin `robot-universal-*` submodule pointers to stable releases — stop chasing upstream — Owner: Dev — File: `.gitmodules`
- [ ] **[LOW]** Standardize `replicas: null` to explicit `replicas: 1` (or appropriate) — remove ambiguity — Owner: DevOps — File: multiple `deployment.yaml`
- [ ] **[LOW]** Add `--help` output examples and `--no-color` flags to CLI tools — Owner: Dev — File: `yt-obsidian`, `repo-distiller`, `ci-effective-report`

---

## Part 6: Consensus Summary

- **Full agreement**: 9 items (all roles agree on: plaintext secrets, missing health probes, single-replica SPOFs, copy-paste IaC, no NetworkPolicies, no logging/instrumentation, shell orchestration risk, hardcoded LLM dependency, stale images)
- **Partial agreement**: 3 items (UX findings reference external CLI tools not in this repo; auth status of some services unverifiable without code; prompt-as-code is observable but runtime behavior cannot be statically analyzed)
- **Unresolved disputes**: None — all roles' findings are complementary rather than contradictory. The main tension is between **infrastructure topology confidence** (high, from rich IaC data) and **application code confidence** (low, from empty AST analysis).

---

## Part 7: Test Coverage Gaps

### 🔐 Security Regression Tests (from Security vulnerabilities)
| # | Test Name | Scenario | Expected | Target File |
|---|-----------|----------|----------|------------|
| 1 | Plaintext token detection | Run secret scanner on `.ai-flow/deploy/services.yaml` | 0 plaintext tokens found; all tokens reference K8s Secrets or Vault paths | `.ai-flow/deploy/services.yaml` |
| 2 | NetworkPolicy enforcement | Deploy test pod in `community-hot-topic` namespace, attempt to reach hotopic-server `/internal/v1/*` | Request blocked by NetworkPolicy unless from authorized miner pod | `infra-common/.../community-hot-topic/` |
| 3 | Vault token revocation on pod shutdown | Terminate a miner pod, check if its Vault token is revoked within 5 seconds | Token is revoked; subsequent API calls with old token fail | `vault/deployment.yaml` |
| 4 | Mixed scheme detection | Scan all miner ConfigMap `closed_url` values | All URLs use consistent scheme (all HTTP or all HTTPS) | `community-hot-topic/**/configmap.yaml` |
| 5 | Image digest pinning | Scan all deployment.yaml image references | All images use `@sha256:...` digest format, not mutable tags | All `deployment.yaml` |
| 6 | Debug flag detection | Scan all deployments for `CONFIG_DEBUG` or `enable_debug` | No production-adjacent deployment has debug mode enabled | `image-secret-patcher/deployment.yaml` |

### ⚡ Performance & Integration Tests (from UX + DFX)
| # | Test Name | Scenario | Expected | Target File |
|---|-----------|----------|----------|------------|
| 1 | Miner LLM API resilience | Block SiliconFlow API endpoint, verify miner behavior | Miner retries with backoff; falls back to cached results or fails gracefully (not crash-loop) | Miner `config.yaml` + deployment |
| 2 | Hot-topic server load test | Send concurrent requests from 12 miners to hotopic-server | Server handles load without 5xx; response time < 5s | `server/deployment.yaml` |
| 3 | Kafka consumer lag detection | Produce 10K messages to Kafka topic, verify consumer processes | Consumer processes all within SLA; lag metric exposed | `community-tracker/deployment.yaml` |
| 4 | Preview deploy end-to-end | Run `preview.sh` with a changed submodule | Namespace created, sub deployed, ingress routable, tester can access preview URL | `.ai-flow/deploy/preview.sh` |
| 5 | test-sync pipeline sync | Run `sync.sh` for a Go robot sub | Secret rendered from Vault, runtime-clone pod starts, `go run .` succeeds | `.ai-flow/deploy/test-sync/sync.sh` |

### 🏗️ Architecture & Refactoring Tests (from Architect risks)
| # | Test Name | Scenario | Expected | Target File |
|---|-----------|----------|----------|------------|
| 1 | ConfigMap prompt deduplication | Update one miner's prompt via parameterized template | All 12 miners inherit update without manual edits to each ConfigMap | `community-hot-topic/**/configmap.yaml` |
| 2 | Miner deployment DRY test | Add a 13th community miner via template | Only 1 new file (ConfigMap) needed, not 4 copies | Kustomize base / Helm chart |
| 3 | Submodule pointer stability | Run `develop.sh` with a submodule change | Parent repo pins to specific commit hash, not branch tip | `.gitmodules` |
| 4 | Orchestrate error propagation | Simulate gate failure in `orchestrate.sh` | Pipeline stops, error logged with context, `/tmp/ai/*` contains failure report | `.ai-flow/src/orchestrate.sh` |

### ♿ Accessibility Tests (from UX gaps)
| # | Test Name | Scenario | Expected | Target File |
|---|-----------|----------|----------|------------|
| 1 | CLI `--help` output | Run `yt-obsidian --help`, `repo-distiller --help`, `ci-effective-report --help` | Clear subcommand listing, flag descriptions, usage examples | CLI tool entry points |
| 2 | `--no-color` flag | Run CLI tools with `--no-color` or `NO_COLOR=1` | No ANSI color codes in output | CLI tools |
| 3 | JSON output mode | Run CLI tools with `--json-output` | Machine-parseable JSON output for accessibility tooling | CLI tools |

### ⚠️ Error Path & Boundary Tests (from DFX + Architect)
| # | Test Name | Scenario | Expected | Target File |
|---|-----------|----------|----------|------------|
| 1 | Vault connection failure | Start miner pod with unreachable Vault endpoint | Pod uses `testdata/config.yaml` fallback; logs warning; does not crash-loop | `sync.sh` + miner deployment |
| 2 | Kafka broker unreachable | Start dispatcher with unreachable Kafka broker | Logs error; retries with backoff; does not block other miners | `robot-hook-dispatcher` |
| 3 | GitHub 404 on robot-framework-lib | Runtime-clone `go run .` when `github.com/opensourceways/robot-framework-lib` returns 404 | Build fails gracefully with clear error; pod logs show exact missing dependency | `test-sync/sync.sh` |
| 4 | Orchestrate.sh set -e failure | Trigger non-zero exit in any stage of `orchestrate.sh` | Pipeline halts, `/tmp/ai/gate_out.txt` shows failure, `review_fail.md` generated | `.ai-flow/src/orchestrate.sh` |
| 5 | Missing design.md | Run review stage without `/tmp/ai/design.md` | Review reports hard fail for "改动覆盖度" check; does not proceed | `.ai-flow/agents/review.md` |

---

## Part 8: Documentation Gaps

### 📖 Architecture & Design Docs
- **System Architecture Diagram**: Document hub-and-spoke topology (hot-topic server → 12 miners → summary/Etherpad/certification satellite services) — Scope: All services, data flow, deployment topology — Priority: **high** — Reference: `infra-common/**/deployment.yaml`, `.ai-flow/deploy/services.yaml`
- **Agent Workflow Specification**: Document the multi-agent adversarial pipeline (design → dev → review → tester), gate checks, and failure recovery — Scope: `.ai-flow/src/orchestrate.sh`, all agent role definitions — Priority: **high** — Reference: `.ai-flow/agents/*.md`, `.ai-flow/src/orchestrate.sh`, `.ai-flow/src/gates/*.sh`
- **Preview Deployment Guide**: Document test→preview transformation, runtime-clone pattern, Vault sync, and route merging — Scope: End-to-end preview flow — Priority: **high** — Reference: `.ai-flow/deploy/preview.sh`, `test-sync/sync.sh`, `test-sync/routes.sh`, `test-sync/README.md`

### 🔧 API & Integration Docs
- **Hot-Topic Server API Spec**: Document `/internal/v1/topic-review/<community>` and `/internal/v1/hot-topic/<community>/solution` endpoints — Scope: Request/response schemas, auth requirements — Priority: **high** — Reference: `community-hot-topic/server/deployment.yaml`, miner `data.publish_url` / `data.closed_url`
- **Robot Webhook Contract**: Document webhook payload format, HMAC validation, and routing rules for `/gitcode-hook` and `/webhook` — Scope: All robot submodules — Priority: **high** — Reference: `services.yaml` subs config, robot submodules
- **Kafka Topic Specification**: Document topic names, message schemas, producer/consumer relationships — Scope: hook-delivery → dispatcher → robot handlers — Priority: **medium** — Reference
