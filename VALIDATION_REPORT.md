# Phase 1 Validation Report

**Active audit, 2026-09-07:** Stage A corrections are in progress. The results below
remain historical evidence at the stated SHA; they do not close F-01/F-02 or the
corrected-SHA gate. Current commands and limitations are recorded in
[Phase 1 audit corrections](docs/implementation/PHASE_1_AUDIT_CORRECTIONS.md).

**Date:** 2026-09-02
**Repository:** `ntua-el21026/trading212-portfolio-intelligence`
**Validated implementation/evidence SHA:** `e13916eca34d8e3be1ed130248d6c3d1ed7e3869`
**Authority:** `main`; later evidence/governance-only reconciliation commits remain
linear descendants of the immutable implementation/evidence SHA.
**Decision:** All 24 locally executable Phase 1 acceptance rows are complete. Release
readiness remains `blocked_external` only for the explicitly listed external conditions.

## Evidence provenance

The exact implementation SHA has green GitHub Actions runs:

- Phase 1 quality: `33562745986`;
- security and dependency gates: `33562746060`;
- documentation baseline validation: `33562746052`.

The quality browser log records 32 synthetic tests and 6 API-backed tests with
Playwright retries disabled and no flaky result. The corrected Compose observation was
run in isolated project `t212pi_phase1_corrected_20260901` with a new PostgreSQL volume,
unique loopback ports, and all seven long-running services including the dispatcher.
Evidence-only descendants do not change the validated runtime implementation.

## Complete local command matrix

| Command | Result |
|---|---|
| `python scripts/validate_repository.py` | Host has no unqualified `python` executable; the repository's documented bootstrap-safe command, `python3 scripts/validate_repository.py`, passed. |
| `make bootstrap` | Passed with Python `3.13.15`, Node `24.20.0`, pnpm `10.34.5`, frozen `uv`/pnpm locks, and Chromium installed. |
| `make format-check` | Passed: Ruff format and Prettier. |
| `make lint` | Passed: Ruff, ESLint, package architecture, and strict GET-only provider boundary. |
| `make typecheck` | Passed: strict mypy and TypeScript. |
| `make test-unit` | Passed: Python unit suite and 22 Vitest tests. |
| `make test-property` | Passed: 10 Hypothesis invariant tests. |
| `make test-contract` | Passed: 36 contract tests plus workspace/generated-contract checks. |
| `make test-integration` | Passed: 50 PostgreSQL/Redis integration tests excluding migration-marked tests. |
| `make test-migrations` | Passed: 11 migration tests, empty-to-head, repeat upgrade, and ORM/schema drift checks. |
| `make test-security` | Passed: architecture/secret checks and 16 negative security tests. |
| `make test-coverage` | Passed: 338 isolated tests plus 64 migration/integration tests; combined branch coverage 84%, unchanged threshold 70%. |
| `make test-e2e` | Passed with retries disabled: 32 synthetic and 6 API-backed desktop/mobile browser tests. |
| `make docs-check` | Passed repository, link, JSON/YAML, workflow, and workspace validation. |
| `make security-check` | Passed pinned no-upload Semgrep, source secret scan, `pip-audit`, and production pnpm audit. |
| `make build` | Passed all Python distributions and the TypeScript/Next.js workspace build. |
| `make container-build` | Passed hardened PostgreSQL/Redis and non-root API/worker/MCP/web builds; dispatcher uses the identical worker image contract. |
| `make validate` | Passed the complete aggregate local Phase 1 gate. |

The bare `python` lookup is an environment limitation, not a repository check failure:
the repository intentionally specifies `python3` for the dependency-free validator and
`uv run python` for pinned application commands.

## Test, migration, contract, and browser results

- Python: 276 unit, 10 property, 36 contract, and 16 security tests form the 338-test
  isolated suite; 64 migration/integration tests passed under combined coverage.
- PostgreSQL integration: 50 non-migration integration tests passed; the 11-file
  migration suite passed separately. Alembic empty-to-head and repeated upgrade both
  reached `20260901_0007`.
- Web: 22 Vitest tests passed. Playwright ran 32 synthetic and 6 API-backed tests across
  desktop and mobile with `retries: 0`. More-than-50 collection navigation, URL cursor
  state, browser back, insertion stability, no duplicate/skip behavior, preview counts,
  largest-holding ordering, accessibility, and horizontal-overflow checks passed.
- The API-backed overview rendered `248,431.27 EUR`; the REST and MCP canonical value was
  exactly `248431.27` EUR. The API/MCP parity suite, nine-tool registry assertion, web
  rendering, OpenAPI generation check, generated TypeScript client build, and drift check
  all passed.
- Dedicated outbox crash/recovery, semantic-idempotency conflict/concurrency,
  stable-keyset pagination, more-than-10,000-row discoverability, full-period dividend
  aggregation, direct snapshot lookup, service-contract, and API/MCP parity suites passed.

## Corrected Compose, migration, and restart evidence

The clean isolated runtime started PostgreSQL, Redis, API, worker, dispatcher, MCP, and
web. Migration and seed one-shots exited zero. The migration head was
`20260901_0007`; repeating migration and seed preserved the exact baseline
`10|10|1|1|2|1|1|2|1|1|3` across source records, source occurrences, snapshots, runs,
transactions, cash flows, dividends, order observations, position observations, cash
observations, and ledger entries.

- **14a, atomic API publication crash:** the integration suite commits a run and outbox
  event, stops before publication, restarts the dispatcher, publishes/executes the same
  logical run, reconciles ambiguous broker acceptance, and verifies no duplicate
  economic data. Pending-outbox telemetry returns to zero.
- **14b, confirmed publication then worker recovery:** with the worker stopped, the API
  committed run `1b092b41-5037-4066-910f-6edcf2546862`; the dispatcher confirmed one
  publication/attempt and Redis retained broker depth one. Restarting the worker
  completed that run. An identical retry returned the same run, retained one outbox
  event/attempt, and left counts `11|20|2|2|2|1|1|2|1|1|3` unchanged.
- **14c, full-stack state retention:** all seven long-running services stopped and
  restarted without volume deletion. Counts remained
  `11|20|2|2|2|1|1|2|1|1|3`; API summary and data-quality JSON and MCP canonical
  structured content were unchanged; summary SHA-256 remained
  `3384103de93e8958c414db023e45131cfac8ea6de58629337f96ac8609b91566`;
  API/MCP/web remained at `248431.27`/`248,431.27` EUR; and the MCP registry remained
  exactly nine tools.

After recovery, dispatcher readiness was `1`; pending outbox and queued-runs-without-
deliverable-event gauges were zero; the database contained no pending/publishing outbox
event and no stranded queued run.

## Security, dependency, and container matrix

| Control | Result |
|---|---|
| Semgrep CE | Passed pinned `1.175.0` repository-local rules with network disabled, metrics off, strict/error mode, and no upload. |
| Gitleaks | Passed the complete Git history scan; repository high-confidence secret scan also passed. |
| Python dependencies | Frozen production export passed `pip-audit 2.10.1`. |
| Node dependencies | `pnpm audit --audit-level high --prod` passed. |
| Trivy filesystem/config/license | Pinned Trivy `0.74.0` scan passed for vulnerability, secret, misconfiguration, and license policy. |
| PostgreSQL image | Hardened `18.6` image built, ran unprivileged, and passed high/critical vulnerability and secret scan. |
| Redis image | Hardened `8.10.1` image built, ran unprivileged, and passed high/critical vulnerability and secret scan. |
| API image | Non-root minimized image passed build, runtime controls, canary, and high/critical vulnerability/secret scan. |
| Worker/dispatcher image | Non-root minimized worker image (also used by the independently supervised dispatcher) passed build, runtime controls, canary, and high/critical vulnerability/secret scan. |
| MCP image | Non-root minimized image passed build, runtime controls, canary, and high/critical vulnerability/secret scan. |
| Web image | Non-root minimized image passed build, build-artifact/runtime canary, and high/critical vulnerability/secret scan. |

The pre-existing, time-bounded `LGPL-3.0-or-later` policy was moved from legacy
top-level keys to Trivy `0.74.0`'s `license.ignored` schema; the exception scope and
review deadline were not broadened. The fresh-checkout-equivalent scan then passed.

A final security-diff review reproduced one evidence-integrity weakness in the earlier
token-only acceptance validator, classified it Medium/P2, and corrected it before the
validated SHA. Structured acceptance-row parsing now binds local and external states,
machine-readable readiness, counts, and remaining conditions; adversarial regression
tests reject relabeling or false external-readiness promotion. The sealed rescan had no
open finding.

API, worker, dispatcher, MCP, and web ran as UID `10001` with read-only root
filesystems, all Linux capabilities dropped, `no-new-privileges`, and package managers
absent. PostgreSQL and Redis ran as their unprivileged service users. The injected
runtime canary was absent from five application logs/filesystems and API/MCP/web
artifacts across 14 checked paths. No error/traceback was present in the retained runtime
log. Workflow actions and external Docker bases remain immutable SHA/digest pinned.

## External states not claimed as passed

| ID | State | Reason |
|---|---|---|
| P1-EXT-001 | `blocked_external` | No owner-supplied Trading 212 Demo read-only credential; the credential-dependent smoke remains explicitly skipped/not run. |
| P1-EXT-002 | `blocked_external` | No production host, identity, or secret-manager authority/configuration was supplied. |
| P1-EXT-003 | `blocked_external` | No public HTTPS OAuth-protected MCP endpoint was supplied for ChatGPT registration. |
| P1-EXT-004 | `unavailable_explicit` | A real-provider opening-history basis for the quantity/cash bridge is unavailable; the limitation is explicitly reported. |

Trading 212 Live remains disabled and untested. The synthetic reconciliation fixture is
local acceptance evidence only and is not substituted for real-provider opening history.
Phase 2 and Phase 3 remain `not_started`.
