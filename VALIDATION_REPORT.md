# Phase 1 Release-Candidate Validation Report

**Date:** 2026-09-01

**Repository:** `ntua-el21026/trading212-portfolio-intelligence`

**Authority:** `main`

**Base SHA:** `c566c080762f9d74996e1bdd19d1254848f8f17f`

**Imported Phase 1 SHA:** `7119be95ae41d036f1461dd21bfbf10243c64ab0`

**Corrected final main SHA:** Pending while corrections are in progress

**Result:** Implementation and all fourteen working-tree scenario evidence assembled;
final release-SHA validation and pushed-SHA CI security remain pending

## 1. Result boundary

P1-01 through P1-12 have source, tests, configuration, containers, and runbook
artifacts. The isolated Compose stack, API-backed browser path, API/MCP parity,
durable queued-run recovery, full-stack restart, and runtime canary checks passed in
the current working tree. This is not yet release approval: the complete gate must run
against the immutable corrected `main` SHA with the pushed-SHA CI security jobs. Scenario 8's
synthetic pass does not establish real Trading 212 opening-history coverage.

No claim is made that Trading 212 Demo credentials worked, that Live was tested, that a production deployment exists, or that ChatGPT connected to a deployed MCP endpoint.

## 2. Intermediate focused evidence

The implementation agents reported the following focused results while building the working tree. These results must be rerun by the final gate and are not release-SHA evidence.

| Subsystem | Intermediate result |
|---|---|
| Domain, persistence, analytics | 94 focused tests passed; focused Ruff, mypy, and package builds passed |
| Worker/ingestion | Focused ingestion, monotonic high-water/overlap, stable pagination-filter, atomic checkpoint, and cross-run resume tests passed; focused Ruff and mypy passed |
| API/MCP | 29 MCP tests and 2 health checks passed; focused Ruff, mypy, package build, and widget browser validation passed |
| Web | Prettier, ESLint, TypeScript, 13 Vitest tests, production build, and 16 desktop/mobile Playwright tests passed |
| Operations smoke unit tests | 12 Demo-smoke tests passed without real credentials |
| Migrations | 7 focused migration tests passed, including repeated upgrade and Alembic drift check |
| Redis coordination | Focused real-Redis coordination integration test passed |
| Security negatives | 13 security tests and focused API audit/provider/MCP redaction tests passed; runtime canary result is recorded below |
| Application images | API, worker, MCP, and web images rebuilt and exercised in the isolated runtime described below |
| Hardened runtime probe | PostgreSQL and Redis initialized disposable volumes and became healthy as users `postgres` and `redis`; API, worker, MCP, and web runtime/import probes passed as non-root with package-manager binaries removed |
| Hardened-image scans | Pinned Trivy `0.74.0` high/critical vulnerability and secret scans returned exit `0` with no findings for PostgreSQL, Redis, API, worker, MCP, and web |
| Filesystem/config/license scan | Trivy `0.74.0` returned exit `0` for vulnerability, secret, misconfiguration, and license scanning; lockfiles and all six Dockerfiles were clean under `trivy.yaml`, including the documented private-release LGPL acceptance |
| Repository history secrets | Pre-evidence Gitleaks `8.30.1` scan returned exit `0` across 54 commits and 2,156,648 bytes; final-head scan remains required |
| Deterministic SAST | Semgrep CE `1.175.0` evaluated 7 repository-local rules over 142 targets and returned 0 findings |

## 3. Retained working-tree runtime evidence

The isolated runtime used Compose project `t212pi_phase1_final_20260831` and these
loopback host ports:

| Service | Host port | Image ID | Runtime result |
|---|---:|---|---|
| PostgreSQL | `25432` | pinned service image | Healthy; authoritative named volume retained across restart |
| Redis | `26379` | pinned service image | Healthy; coordination only |
| API | `28000` | `6f77d1324278` | Healthy; UID `10001` |
| Worker | n/a | `9487a06c3a18` | Healthy; UID `10001` |
| MCP | `28001` | `0f91ab24cddd` | Healthy; UID `10001` |
| Web | `23000` | `a60e2a057146` | Healthy; UID `10001` |

### 3.1 API-backed browser and protocol parity

- Local sign-in redirected and authenticated successfully.
- API, MCP, and API-backed web exposed the same canonical total: `248431.27` EUR.
- The web exposed `provider_history_coverage_gap` rather than hiding incomplete
  opening-history coverage.
- Desktop and mobile inspection found no mobile overflow and zero console errors.
- The local session cookie was `HttpOnly` and `SameSite=Strict`.
- Retained screenshots:
  [desktop overview](docs/implementation/evidence/api-backed-overview-desktop.png) and
  [mobile quality state](docs/implementation/evidence/api-backed-quality-mobile.png).

### 3.2 Durable queue and restart

The clean seeded baseline was:

```text
source_records=10 source_occurrences=10 snapshots=1 runs=1 transactions=2 positions=1
```

The worker was stopped. An authenticated all/incremental/snapshot refresh with
idempotency key `phase1-runtime-restart-20260901` was accepted and persisted as queued
run `5b32bbfd-cd5e-45ae-8e6b-8845ec0cf676`. After the worker restarted, the same run
reached `succeeded` and counts became:

```text
source_records=11 source_occurrences=20 snapshots=2 runs=2 transactions=2 positions=1
```

The new source row is refreshed metadata; transactions and positions did not duplicate.
After stopping and restarting API, MCP, web, worker, PostgreSQL, and Redis without
deleting volumes, counts remained `11|20|2|2|2|1`. The canonical API summary SHA-256
remained `81fc4f21d76b0a2f4e80d3cba3ee32afc670ab150f997d630c520372cc09c391`.
API/MCP totals remained exactly `248431.27` EUR; the MCP comparison used correlation
`runtime-restart-parity`.

### 3.3 Runtime security and latency probes

- The secret canary was absent from API, worker, MCP, and web logs and from `/app` and
  `/opt/venv` in every rebuilt application image.
- A separate hardened-runtime probe initialized PostgreSQL and Redis on disposable
  volumes, reached healthy state as users `postgres` and `redis`, and exercised API,
  worker, MCP, and web as non-root after their unused package managers were removed.
- Pinned Trivy `0.74.0` image
  `sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969`
  returned exit `0` and no findings for high/critical vulnerability and secret scans of
  all six current images:

| Image | Working-tree image ID | Result |
|---|---|---|
| Hardened PostgreSQL | `3c0696d80271` | Clean |
| Hardened Redis | `6719aa0759f5` | Clean |
| API | `64ffa5b17148` | Clean |
| Worker | `40e03f273d9a` | Clean |
| MCP | `181f394a8f2d` | Clean |
| Web | `5e1bdd7a93e3` | Clean |

- The Trivy filesystem scan returned exit `0` for vulnerability, secret,
  misconfiguration, and license scanners. Lockfiles and all six Dockerfiles were clean
  under `trivy.yaml`; its `LGPL-3.0-or-later` acceptance is limited to unmodified
  sharp/libvips in this private release.
- A pre-evidence Gitleaks `8.30.1` scan returned exit `0` over 54 commits and
  2,156,648 bytes. The final-head result is recorded in the pull-request evidence so
  this report does not create a self-invalidating hard-coded commit count.
- Pinned Semgrep CE `1.175.0` ran 7 repository-local rules over 142 targets with metrics,
  network access, and external upload disabled; it returned 0 findings.
- Every GitHub Actions dependency is commit-SHA pinned, and every external Docker
  `FROM` reference is digest pinned. These results remain working-tree evidence until
  repeated by CI at the immutable release SHA.
- Forty sequential local observations produced:

| Surface | p50 | p95 |
|---|---:|---:|
| API summary | `7.61 ms` | `9.22 ms` |
| MCP | `9.29 ms` | `10.05 ms` |
| Web overview | `136.35 ms` | `145.52 ms` |

These measurements are local smoke evidence, not production capacity claims.

## 4. Authoritative final command ledger

Every row below remains pending until executed at the corrected final `main` SHA. Results
must include exit status and material counts in the final correction evidence.

| Gate | Exact command | Current state |
|---|---|---|
| Locked bootstrap | `make bootstrap` | Passed working tree; pending final SHA rerun |
| Formatting | `make format-check` | Passed working tree; pending final SHA rerun |
| Lint and architecture | `make lint` | Passed working tree; pending final SHA rerun |
| Python/TypeScript types | `make typecheck` | Passed working tree; pending final SHA rerun |
| Unit tests | `make test-unit` | Passed working tree; pending final SHA rerun |
| Property tests | `make test-property` | Passed working tree; pending final SHA rerun |
| Contract/generated-client tests | `make test-contract` | Passed working tree; pending final SHA rerun |
| PostgreSQL/Redis integration | `make test-integration` | Passed working tree; pending final SHA rerun |
| Clean migration test | `make test-migrations` | Passed working tree; pending final SHA rerun |
| Negative security tests | `make test-security` | Passed working tree; pending final SHA rerun |
| Browser E2E | `make test-e2e` (synthetic web plus actual API-backed desktop/mobile projects) | Passed working tree; pending final SHA rerun |
| Documentation and links | `make docs-check` | Passed working tree; pending final SHA rerun |
| Dependency and secret audits | `make security-check` | Passed working tree; pending final SHA rerun |
| Python/web/MCP builds | `make build` | Passed working tree; pending final SHA rerun |
| Application image builds | `make container-build` | Passed in working tree; pending final SHA rerun |
| Full aggregate gate | `make validate` | Passed working tree; pending final SHA rerun |
| Clean Compose smoke/restart | Isolated Compose build/start, health/API/MCP/web probes, durable queued-run recovery, full-stack restart, and scoped teardown | Passed in working tree; pending final SHA rerun |
| Container vulnerability scans | Trivy `0.74.0` filesystem/config and hardened PostgreSQL, Redis, API, worker, MCP, and web image matrix | Pending final/pushed SHA |
| Static security analysis | Pinned Semgrep CE `1.175.0`, repository-local rules, no network/metrics/external upload | Pending final/pushed SHA |

## 5. Acceptance coverage assembled

- Exact ten-capability Trading 212 GET allowlist, pre-transport method rejection, and a repository-wide static boundary scanner.
- Strict provider DTOs, bounded GET retries/pagination, redaction, Demo-safe configuration, durable ingestion, checkpoints, leases, idempotent revisions, and Redis rate coordination.
- Exact-decimal canonical values, deterministic ledger/reconciliation/allocation/accounting, immutable snapshot models, provenance, UTC, freshness, quality, and unavailable states.
- PostgreSQL 18 schema/migrations, repositories, realistic synthetic seed, and credential-reference-only persistence.
- Authenticated and authorized `/api/v1`, CSRF/session handling, stable errors, OpenAPI, and generated TypeScript client.
- Responsive Next.js routes and explicit loading/empty/error/stale/partial/unavailable states.
- Authenticated Streamable HTTP `/mcp`, nine frozen read-only tools, versioned overview widget, strict CSP, and API/MCP parity fixtures.
- Non-root application images, Compose, health/readiness, structured logs, metrics/tracing integration points, backup/restore, deployment, credential, MCP, and troubleshooting runbooks.
- Scenario 9 passes with a persisted provenance-bearing explicit FX quote and a
  fail-closed missing-FX path.
- Scenario 11 passes its working-tree canary tests and runtime log/image scan.
- Scenario 13 passes exact API/MCP/API-backed-web canonical parity in the isolated stack.
- Scenario 14 passes durable queued-run recovery and full-stack state/hash retention.
- Scenario 8 passes with one retained synthetic immutable reconciliation fixture through
  the real bridge algorithms, PostgreSQL, REST/MCP parity, and actual API-backed
  desktop/mobile web. Real Trading 212 opening-history coverage remains unavailable and
  is not fabricated or inferred from that synthetic fixture.

## 6. Security status

Structural, focused negative, and working-tree runtime-canary controls passed. GitHub
code-scanning upload is unavailable for this user-owned private repository under its
current entitlement; the blocking no-upload SAST replacement is pinned Semgrep CE
`1.175.0` with repository-local rules. Hardened PostgreSQL/Redis images patch affected
OpenSSL packages and run unprivileged; application images omit unused package installers.
The complete working-tree Semgrep, Gitleaks, Trivy filesystem/config/license, and
six-image Trivy matrix returned clean results as detailed above. Final release-SHA
repository secret scan, locked dependency audits, negative tests, Semgrep, and Trivy
reruns remain pending in CI. There is no authorization to weaken GET-only,
secret-redaction, authentication, or exact-decimal controls to make a gate pass.

## 7. External gates

| Gate | State | Exact reason |
|---|---|---|
| Trading 212 Demo smoke | `blocked_external` | No owner-provided Demo API key/secret was supplied. The opt-in script was tested only with synthetic transports. |
| Production HTTPS/auth/secret manager | `blocked_external` | No hosting domain, production identity provider, or selected external secret backend was supplied. |
| ChatGPT Developer Mode registration | `blocked_external` | No public HTTPS authenticated MCP deployment exists to register. |
| Trading 212 Live | Not authorized/tested | Live is opt-in and outside required acceptance; Demo remains the safe default. |

## 8. Release decision

**Not yet approved.** Preserve the distinction between scenario 8's synthetic pass and
the unavailable real-provider opening-history basis; finish the corrections directly on
`main`; rerun and record the complete local gate at that SHA; and obtain the pushed-SHA
Semgrep, dependency, secret, and Trivy results.

The earlier documentation-readiness approval remains valid as historical authorization to implement; it is not application acceptance.
