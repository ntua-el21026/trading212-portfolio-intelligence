# Phase 1 Execution Manifest

**Status:** Accepted  
**Release target:** `0.1.0`  
**Execution:** Direct fast-forward commits to `main`

This manifest converts the Phase 1 specification into an ordered implementation program. It does not reduce any acceptance criterion in `PHASE_1_TRUSTED_FOUNDATION.md`.

Every implementation increment and correction lands directly on `main`; release labels,
examples, and task-local prose do not create an alternate Git workflow.

## Work packages

| ID | Outcome | Dependencies | Mandatory evidence |
|---|---|---|---|
| P1-01 | Reproducible monorepo, toolchains, local stack, CI | Design baseline | Clean bootstrap, lockfiles, real Make targets, CI green |
| P1-02 | Exact domain values/contracts/invariants | P1-01 | Unit/property/architecture tests |
| P1-03 | PostgreSQL schema, repositories, migrations through `20260901_0007` | P1-02 | Empty/upgrade/repeat/downgrade-policy tests, constraints and ORM drift check |
| P1-04 | Strict Trading 212 GET-only adapter | P1-02 | Exact allowlist and pre-transport negative tests |
| P1-05 | Durable ingestion, transactional dispatch, semantic idempotency, provider pagination/rate coordination | P1-03, P1-04 | API-crash/outbox recovery, concurrent idempotency, replay/restart/duplicate/partial/schema-drift tests |
| P1-06 | Ledger, reconciliation, immutable snapshots | P1-03, P1-05 | Hand-calculated reconciliation/snapshot fixtures |
| P1-07 | Core accounting, direct allocation, covered returns | P1-06 | Reference/property/quality-gating tests |
| P1-08 | Authn/authz/secrets/redaction | P1-01–P1-07 | Cross-account denial and secret-canary tests |
| P1-09 | Versioned API, complete application contracts, stable collection queries, generated TypeScript client | P1-07, P1-08 | OpenAPI/client compile, auth/keyset stability/filter/total/error tests |
| P1-10 | Responsive accessible Phase 1 web app with route-specific cursor loaders | P1-09 | More-than-50-row desktop/mobile paging, back-navigation, mutation-stability, accessibility E2E tests |
| P1-11 | Authenticated bounded nine-tool MCP/ChatGPT gateway using server-side queries | P1-07–P1-09 | Schema/auth/negative/full-filtered-set/API-parity/inspector tests |
| P1-12 | Deployment, observability, hardening, acceptance | all | Clean synthetic E2E, scans, containers, status/report |

## Correction-specific Phase 1 contracts

These requirements refine the existing Phase 1 packages; they do not add a later-phase
work package or feature.

### Durable dispatch and semantic idempotency

- Creating a refresh commits its durable run and one bounded, non-secret, fixed
  `portfolio.refresh` outbox event atomically. API correctness does not depend on a
  `send_task` call in the request process.
- An independent dispatcher uses `FOR UPDATE SKIP LOCKED`, leased claims, bounded
  retry/backoff, sanitized error codes, and the deterministic run-derived Celery task ID.
  It recovers expired `publishing` claims and safely reconciles consumer/terminal evidence
  after ambiguous broker acceptance.
- The worker validates run, owner/account, requested/effective semantics, and task
  metadata before execution. At-least-once publication and duplicate delivery retain one
  logical run and idempotent canonical economic state.
- The same account/key/request returns the same run in every lifecycle state. The same
  account/key with a different requested mode, normalized capability set, snapshot
  behavior, or schema version returns sanitized `IDEMPOTENCY_KEY_REUSED`/HTTP `409` and
  publishes nothing. Requested semantics remain distinct from promoted effective
  execution semantics; the correlation ID is not part of identity.
- Deployed readiness fails when no live dispatcher is configured. Metrics cover pending
  count, oldest pending age, delivery attempts/failures, recovered claims, and queued
  runs without a deliverable outbox event.

### Complete bounded collections and canonical services

- Mutable collections use versioned integrity-protected cursors bound to resource,
  authorized scope, sort, normalized filters, immutable result membership or read cutoff,
  deterministic key/tie-breaker, and schema version. SQL filtering precedes `limit + 1`
  paging; there is no offset cursor, collect-then-filter prefix, or silent 10,000-row cap,
  and totals are exact for the full filtered result.
- The application layer owns typed authorized use cases for broker connections,
  canonical instrument search/detail, direct snapshot lookup, core performance,
  reconciliation-discrepancy paging, data quality, and each collection query. Both the
  PostgreSQL and deterministic synthetic services implement the contracts.
- The MCP registry remains exactly nine tools. Position search/sort, transaction
  filters, dividend full-period aggregation, direct snapshot lookup, and data quality use
  those server-side application services; bounded output does not imply bounded source
  coverage.
- Overview, holdings, activity, dividends, snapshots, quality/reconciliation,
  synchronization, and settings/connections have route-specific typed server loaders.
  Collection cursors and filters use safe URL state for accessible page/load-more and
  browser back/forward behavior. Overview labels its bounded preview and requests the
  largest holdings in market-value order.

## Required root commands

Codex may refine implementation but must provide functional equivalents of:

```text
make bootstrap
make format
make format-check
make lint
make typecheck
make test-unit
make test-property
make test-contract
make test-integration
make test-migrations
make test-security
make test-e2e
make docs-check
make security-check
make build
make test
make dev
```

No command may be a no-op success placeholder.

## Commit protocol

For each coherent increment:

1. synchronize and record the latest `main` SHA;
2. implement one bounded outcome;
3. run all affected gates plus required regression gates;
4. update status/progress/docs/fixtures/migrations/contracts;
5. commit with a precise Conventional Commit message;
6. verify the pushed head and CI;
7. correct failure with a new forward commit.

## Mandatory synthetic end-to-end scenarios

1. Fresh account ingestion and canonical snapshot.
2. Repeated identical refresh creates no duplicate economic records.
3. Incremental refresh adds one transaction, dividend, and position change.
4. Transient provider failure retries and recovers within budget.
5. Rate limit pauses and resumes safely.
6. One capability fails and aggregate state becomes explicitly partial.
7. Schema incompatibility fails the atomic unit and does not advance checkpoint.
8. Quantity/cash mismatch is persisted and visible as unreconciled.
9. Multi-currency valuation uses sourced FX and degrades explicitly when FX is missing.
10. Unauthorized cross-owner/account API and MCP access is denied.
11. Canary secrets are absent from logs, traces, errors, API/MCP/web output, and artifacts.
12. Non-GET/unknown provider capability is rejected before transport.
13. API/web/MCP return identical canonical values for the same fixture/cutoff.
14. Process/container restart preserves state and safely resumes jobs.

### Scenario 14 required subcases

Scenario 14 is not a single restart shortcut. Its release evidence must report these
three independently:

- **14a API publication crash:** commit the refresh run and outbox event, stop before
  Celery publication, restart the dispatcher/API environment, execute the original run,
  prove no duplicate source/canonical/economic/snapshot state, and observe pending-outbox
  return to zero. Separately cover broker acceptance followed by a crash before outbox
  acknowledgement and consumption of both same-ID deliveries.
- **14b worker restart after confirmed publication:** preserve a successfully published
  message while the worker is unavailable, restart the worker, and execute the original
  logical run without periodic dispatcher redelivery.
- **14c full-stack retention:** restart all application services plus PostgreSQL/Redis
  without deleting volumes and prove canonical/API/MCP/web state remains stable.

## External gates

The following may remain explicitly `blocked_external` without blocking local Phase 1 completion:

- Trading 212 Demo smoke requiring user-provided read-only credentials.
- Remote hosting/domain/production authentication and secret-manager selection.
- Live ChatGPT app registration against a deployed authenticated MCP endpoint.

Nothing else may be silently skipped as “external.”

## Completion package

P1-12 must produce:

- final `PROJECT_STATUS.md` and `PROJECT_PROGRESS.json`;
- exact final SHA and ordered implementation commits;
- command/CI results;
- migration head and schema evidence;
- atomic outbox/restart/duplicate-delivery evidence and dispatcher telemetry/readiness;
- semantic-idempotency equality/conflict/concurrency evidence;
- stable complete collection and desktop/mobile URL-pagination evidence;
- complete canonical application-service inventory;
- OpenAPI, generated client, and MCP schema evidence;
- broker allowlist/default-deny proof;
- reference/property calculation results;
- API/web/MCP E2E and parity evidence;
- security/redaction/scan evidence;
- known coverage limitations;
- explicit external-gate state;
- release notes/changelog for `0.1.0`.
