# Phase 1 Execution Manifest

**Status:** Accepted  
**Release target:** `0.1.0`  
**Execution:** Direct fast-forward commits to `main`

This manifest converts the Phase 1 specification into an ordered implementation program. It does not reduce any acceptance criterion in `PHASE_1_TRUSTED_FOUNDATION.md`.

## Work packages

| ID | Outcome | Dependencies | Mandatory evidence |
|---|---|---|---|
| P1-01 | Reproducible monorepo, toolchains, local stack, CI | Design baseline | Clean bootstrap, lockfiles, real Make targets, CI green |
| P1-02 | Exact domain values/contracts/invariants | P1-01 | Unit/property/architecture tests |
| P1-03 | PostgreSQL schema, repositories, migrations | P1-02 | Empty/upgrade/downgrade-policy tests, constraints |
| P1-04 | Strict Trading 212 GET-only adapter | P1-02 | Exact allowlist and pre-transport negative tests |
| P1-05 | Durable ingestion/pagination/rate coordination | P1-03, P1-04 | Replay/restart/duplicate/partial/schema-drift tests |
| P1-06 | Ledger, reconciliation, immutable snapshots | P1-03, P1-05 | Hand-calculated reconciliation/snapshot fixtures |
| P1-07 | Core accounting, direct allocation, covered returns | P1-06 | Reference/property/quality-gating tests |
| P1-08 | Authn/authz/secrets/redaction | P1-01–P1-07 | Cross-account denial and secret-canary tests |
| P1-09 | Versioned API and generated TypeScript client | P1-07, P1-08 | OpenAPI/client compile, auth/pagination/error tests |
| P1-10 | Responsive accessible Phase 1 web app | P1-09 | Component, visual/responsive, accessibility, E2E tests |
| P1-11 | Authenticated bounded MCP/ChatGPT gateway | P1-07–P1-09 | Schema/auth/negative/API-parity/inspector tests |
| P1-12 | Deployment, observability, hardening, acceptance | all | Clean synthetic E2E, scans, containers, status/report |

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
- OpenAPI, generated client, and MCP schema evidence;
- broker allowlist/default-deny proof;
- reference/property calculation results;
- API/web/MCP E2E and parity evidence;
- security/redaction/scan evidence;
- known coverage limitations;
- explicit external-gate state;
- release notes/changelog for `0.1.0`.
