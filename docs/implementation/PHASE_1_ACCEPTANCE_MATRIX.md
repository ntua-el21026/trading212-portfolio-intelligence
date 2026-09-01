# Phase 1 Acceptance Matrix

**Status:** Complete at validated implementation SHA `bba71749096cecbe8732d60e2b5bb1e44c394b7c`

**Release target:** `0.1.0`

A completed local row has reproducible evidence at the validated SHA. External rows are
complete when their explicit blocked or unavailable predicate is recorded; that state is
not converted into a local pass.

| ID | Acceptance condition | Evidence | State |
|---|---|---|---|
| P1-SAFE-001 | Exact ten-capability GET registry | Allowlist, boundary validator, tests | Complete |
| P1-SAFE-002 | Unknown/non-GET/path-injected request fails before transport | Transport-spy and security negatives | Complete |
| P1-SAFE-003 | No broker write path exists | Static boundary and architecture checks | Complete |
| P1-SEC-001 | Secrets remain server-side and redacted | Canary, scanner, API/MCP negatives, artifact scan | Complete |
| P1-AUTH-001 | Owner/account use cases are authorized | Session, CSRF, ownership tests | Complete |
| P1-DOM-001 | Financial values use exact decimals | Domain, persistence, unit/property tests | Complete |
| P1-DOM-002 | UTC timestamps and quality states are explicit | Domain/provider tests | Complete |
| P1-DATA-001 | Full/incremental ingestion is idempotent | PostgreSQL duplicate, revision, overlap, replay tests | Complete |
| P1-DATA-002 | Checkpoints and refresh dispatch commit atomically | Atomic rollback, durable outbox, crash-window and restart tests | Complete |
| P1-DATA-003 | Provider and collection failures are bounded | DTO, pagination, retry, Redis, cursor tests | Complete |
| P1-REC-001 | Discrepancies are first-class and versioned | Persistence, API/MCP parity, API-backed web | Complete |
| P1-SNAP-001 | Snapshots are immutable and cutoff-aware | Repository and integration tests | Complete |
| P1-CALC-001 | External flows are separated from gain | Ledger/performance fixtures and properties | Complete |
| P1-CALC-002 | Core values and allocations reconcile | Portfolio reference/property tests | Complete |
| P1-CALC-003 | Returns are coverage-gated | Missing-history and missing-FX tests | Complete |
| P1-API-001 | `/api/v1` is typed, bounded, authorized, stable | Route/auth/error and integration tests | Complete |
| P1-API-002 | OpenAPI client is synchronized | Generated-contract drift check and TypeScript compile | Complete |
| P1-WEB-001 | Views are responsive and accessible | 22 Vitest tests; 32 desktop/mobile synthetic Playwright tests | Complete |
| P1-WEB-002 | Web preserves canonical quality semantics | API-backed desktop/mobile suite (6 tests) | Complete |
| P1-MCP-001 | MCP tools are authenticated, bounded, typed, allowlisted | Descriptor/auth/negative/contract tests | Complete |
| P1-MCP-002 | MCP and API are canonically equivalent | API/MCP parity and restart retention evidence | Complete |
| P1-OPS-001 | Clean clone can bootstrap, migrate, test, build | Locks, Make targets, CI, Compose | Complete |
| P1-OPS-002 | Operations controls and migrations exist | Non-root images, runbooks, migrations through `20260901_0007` | Complete |
| P1-E2E-001 | All 14 mandatory synthetic scenarios pass | Scenario ledger and tested predicates | Complete |
| P1-EXT-001 | Trading 212 Demo smoke | Owner credential is absent | `blocked_external` |
| P1-EXT-002 | Production deployment prerequisites | No hosted deployment/identity/secret-manager authority supplied | `blocked_external` |
| P1-EXT-003 | Public HTTPS/OAuth MCP and ChatGPT registration | No public HTTPS OAuth-protected MCP endpoint is supplied for ChatGPT registration | `blocked_external` |
| P1-EXT-004 | Real-provider quantity/cash opening-history bridge | Provider opening-history basis is unavailable; synthetic scenario 8 is not substituted as real-provider evidence | `unavailable_explicit` |

## Validated evidence boundary

- Validated implementation SHA: `bba71749096cecbe8732d60e2b5bb1e44c394b7c`.
- Migrations were validated through `20260901_0007`.
- Python evidence: 335 isolated tests and 64 migration/integration tests; combined
  branch coverage was 84% against the unchanged 70% gate.
- Web evidence: 22 unit tests, 32 synthetic desktop/mobile Playwright tests, and 6
  API-backed desktop/mobile Playwright tests.
- GitHub Actions at the validated SHA: Phase 1 quality run `33559034274`, security run
  `33559034279`, and documentation run `33559034182` were green.

## Release rule

Phase 1 is complete for all locally executable rows. The three `blocked_external` rows
and the one `unavailable_explicit` real-provider predicate remain explicit limits and
do not authorize any unverified external claim.
