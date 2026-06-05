### 🔧 Reliability Assessment

1. **52 unhandled errors, 15 swallowed validations** — Error flow analysis shows `52 errors created with zero consumption handlers` across `utils/`, `watch/`, and `softwarepkg/domain/`. Additionally, 15 `Validate()` calls have their errors captured but never returned or acted upon (e.g., `main.go:60`, `config/config.go:31`, `config/config.go:132`, `message-server/main.go:65`, `watch/main.go:54`, `cacheagent/agent.go:57/63`). This means config validation failures, domain invariant violations, and cache load failures can silently pass — services boot with broken state.

2. **No liveness/readiness probes on 7 of 9 components** — Only `server` and `website` have probes. `message-server`, `watch`, `hook-delivery`, `hook-delivery-gitcode`, `github-server`, `gitee-robot`, `gitcode-robot`, and `gateway` have **zero probes**. Kubernetes cannot detect hung Kafka consumers, stalled git watchers, or crashed webhook handlers.

3. **`Recreate` deployment strategy on 6 components** — `server`, `message`, `hook-delivery`, `hook-delivery-gitcode`, `github-server`, `gitee-robot`, `gitcode-robot` all use `type: Recreate`. Every update causes full downtime. Combined with no replicas, this means **the API goes offline during every deploy**.

4. **`replicas: null` everywhere** — No component declares a replica count. Single-pod deployments mean any node drain, OOM kill, or crash brings that component down entirely. The Kafka consumer group in `message-server` has no standby.

5. **Shared Kubernetes secret (`software-pkg-secret`) as blast radius amplifier** — Every service mounts keys from the same Secret. A single leaked secret key or rotation error takes down all 9+ components simultaneously.

6. **`skip_cert_verify: true` in message-server** — Kafka TLS certificate verification is explicitly disabled. Combined with `msg_cert: /opt/kafka-certs/phy_ca.crt` being mounted, this is a contradictory configuration that suggests MITM vulnerability or broken cert rotation.

7. **`TEST_MODE: "true"` in server and message-server** — Debug flags enabled in the test environment deployment may expose internal state, disable auth, or change error handling behavior. If this pattern leaks to production, it's a reliability + security risk.

8. **Docker build-time credentials (`$USER`/`$PASS`)** — All 3 Dockerfiles use build args for GitHub credentials, writing them to `/root/.netrc`. These persist in build cache and image history. If the image is ever pushed to a registry, credentials are extractable.

### 📈 Maintainability Issues

- **No high-churn files detected** — All listed hotspots have churn=1 (infrastructure files: `CLAUDE.md`, `Dockerfile`, `LICENSE`, `Makefile`, `README.md`, and initial commits). This is unusual for a production system — it suggests either a **stale repo** (low active development) or that churn data is incomplete. Either way, the absence of code churn hotspots means we can't identify which modules are fragile from edit frequency.

- **`softwarepkg/domain/software_pkg.go` (398+ lines)** — The architect flagged this as a fat domain layer mixing state machine transitions, business rules, and review logic. Single-file domain logic of this size is a maintainability risk for merge conflicts and regression bugs.

- **Duplicate `cloneRepo` implementations** — `softwarepkg/infrastructure/pkgciimpl/impl.go` and `watch/infrastructure/pullrequestimpl/impl.go` contain near-identical git clone logic. Divergence risk: when one is fixed for a new platform quirk, the other silently breaks.

- **Config struct duplication across 3 services** — `server`, `message-server`, and `watch` each define their own `Config` struct with overlapping fields (`postgresql`, `mongo`, `kafka`, `software_pkg`, `encryption`). Adding a new shared config field requires editing 3 files — guaranteed to drift.

- **Shell script coupling in `pkgciimpl`/`pullrequestimpl`** — Git operations executed via `RunCmd` shell invocations (`clone`, `push`, `lfs`) are platform-dependent, untestable in unit tests, and break if `git` isn't in `$PATH` in the container.

### 🚨 Single Points of Failure (from IaC)

1. **No production environment exists** — Only `test` environment is configured in `infra-common`. There is no staging or production Kustomize overlay. If the test cluster goes down, the entire service is unreachable.

2. **Single Kafka cluster dependency** — All 3 Go services + 4 robot/hook components connect to the same Kafka address (`${KAFKA_ADDRESS}` from a single secret key). Kafka outage cascades to API (async events), message processing, watchers, and webhook delivery simultaneously.

3. **Single PostgreSQL + MongoDB pair** — Every service shares the same DB credentials (`${DB_HOST}`, `${DB_NAME}`, etc.). No read replicas, no connection pooler (PgBouncer), no MongoDB replica set configuration visible. DB downtime is total outage.

4. **No autoscaler targets defined** — `autoscaler.yaml` is referenced in every kustomization but the deployment specs show `replicas: null` with no HPA/VPA configuration visible. Traffic spikes have no automatic scaling response.

5. **Gateway has no probes, no replicas, no config volumes** — The `gateway` component uses `--config-file=/vault/secrets/config.yml` (Vault Agent Sidecar Injector) but has no volumes defined, no probes, and no service/ingress. If the Vault injector fails, the gateway crashes with no recovery path.

6. **Ingress path collision risk** — Multiple ingresses share `software-pkg.test.osinfra.cn`: `server` (`/api/v1`, `/swagger`), `hook-delivery` (`/hook-delivery`), `hook-delivery-gitcode` (`/hook-delivery-gitcode`), `gitee-robot` (`/gitee-hook`), `gitcode-robot` (`/gitcode-hook`). If regex path matching is misconfigured, hooks can route to the wrong handler.

### 📝 Observability Gaps

1. **No exposed ports on any Go service Dockerfile** — All 3 Dockerfiles have `exposed_ports: []`. No `/health`, `/metrics`, `/debug/pprof` endpoints are defined in the container image. Prometheus cannot scrape, and operators cannot health-check at the container level.

2. **Logging imports present but no structured logging evidence** — Imports include `logrus`, `logrusutil`, and `allerror` (custom error package), but there's no evidence of:
   - Request/response correlation IDs propagated across Kafka messages
   - Structured log fields (no `log.WithFields` patterns visible in error flow)
   - Log level configuration per environment (all services use `--enable_debug` or `--enable_debug=true`)
   - Error context enrichment — 52 unhandled errors are created but never logged with context (request ID, package ID, SIG name)

3. **No distributed tracing** — Kafka messages lack trace/correlation IDs. A package submission that flows `API → Kafka → message-server → Kafka → watch → git platform` cannot be traced end-to-end. Root cause analysis for "package stuck in ci-waiting" requires grepping logs across 3+ services.

4. **Server healthcheck points at swagger docs** — The `server` liveness/readiness probe hits `/swagger/doc.json`. This verifies the swagger file exists, not that PostgreSQL is reachable, MongoDB is connected, or Kafka consumers are healthy. A server with dead DB connections still passes health checks.

5. **No CI integration tests** — CI workflows include `build-and-coverage`, `trivy`, `gitleaks`, `sast`, `check-label`, `document-gate`, `check-branch-naming`. **No integration test job, no e2e test, no deploy verification**. The CI pipeline cannot catch broken Kafka connectivity, missing DB migrations, or misconfigured webhooks.

6. **Error swallowing at critical junctions** — The 15 swallowed `Validate()` errors are at the most critical initialization points: config loading, options parsing, cache agent startup. If config is invalid (wrong DB host, malformed Kafka address), the service may start with default/zero values and fail at runtime with opaque errors.

### 📊 Confidence

- **Level**: **high**
- **Reasoning**: The findings are derived from concrete data: 52 unhandled errors and 15 swallowed validations from AST-level error flow analysis, 0 healthchecks in 3 Dockerfiles confirmed by IaC parsing, `replicas: null` and `Recreate` strategy from deployment YAMLs, shared secret references from kustomization configs, and the absence of production environment from infra repo inventory. These are structural issues visible in configuration and code analysis, not speculative.
