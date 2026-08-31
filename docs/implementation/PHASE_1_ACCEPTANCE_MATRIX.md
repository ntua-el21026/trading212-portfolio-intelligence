# Phase 1 Acceptance Matrix

**Status:** Accepted  
**Release target:** `0.1.0`

A row is complete only when the implementation records reproducible evidence at the exact release SHA.

| ID | Acceptance condition | Evidence required | State |
|---|---|---|---|
| P1-SAFE-001 | Registry contains exactly the documented ten Trading 212 GET capabilities | Static registry test and machine allowlist comparison | Not started |
| P1-SAFE-002 | Unknown/non-GET/path-injected request fails before transport | Runtime-negative transport spy tests | Not started |
| P1-SAFE-003 | No order/Pie/transfer/CFD/export-creation code path exists | Architecture/static scans and code review evidence | Not started |
| P1-SEC-001 | Secrets remain server-side and redacted | Canary tests across logs/traces/errors/API/MCP/web/artifacts | Not started |
| P1-AUTH-001 | Every owner/account use case is authorized | Cross-owner/account denial tests | Not started |
| P1-DOM-001 | Money/quantity/price/FX/ratio use exact decimal semantics | Unit/property tests; no Decimal-from-float paths | Not started |
| P1-DOM-002 | Timestamps are aware UTC and quality states are distinct | Boundary/property/serialization tests | Not started |
| P1-DATA-001 | Full/incremental ingestion is idempotent | Duplicate/replay/restart integration tests | Not started |
| P1-DATA-002 | Checkpoints advance only after durable atomic success | Crash/failure/checkpoint tests | Not started |
| P1-DATA-003 | Schema/pagination/rate-limit failures are bounded and explicit | Contract/integration tests | Not started |
| P1-REC-001 | Position and cash discrepancies are first-class and versioned | Reference reconciliation fixtures | Not started |
| P1-SNAP-001 | Snapshots are immutable, reproducible, and source-cutoff aware | Repository/reference tests | Not started |
| P1-CALC-001 | Deposits/withdrawals are separated from investment gain | Hand-calculated fixtures and properties | Not started |
| P1-CALC-002 | Core values and direct allocations reconcile exactly | Reference/property tests | Not started |
| P1-CALC-003 | Return metrics are coverage-gated and never invent missing data | Incomplete-history/FX/fee/cost-basis tests | Not started |
| P1-API-001 | `/api/v1` is typed, bounded, authorized, and stable | OpenAPI/auth/pagination/error tests | Not started |
| P1-API-002 | Generated TypeScript client matches OpenAPI and compiles | Generation diff and TypeScript build | Not started |
| P1-WEB-001 | Phase 1 views are responsive and accessible | Component, Playwright, accessibility-smoke evidence | Not started |
| P1-WEB-002 | Web displays timestamps/method/quality/warnings without recalculating | API parity and UI-state tests | Not started |
| P1-MCP-001 | MCP tools are authenticated, bounded, typed, and allowlisted | Schema/auth/negative tests | Not started |
| P1-MCP-002 | MCP and API results match canonical fixtures exactly | API/MCP parity tests | Not started |
| P1-OPS-001 | Clean clone can bootstrap, migrate, seed, run, test, and build | CI clean-environment workflow | Not started |
| P1-OPS-002 | Containers, telemetry, migrations, backup/incident runbooks exist | Smoke/scans/runbook validation | Not started |
| P1-E2E-001 | All 14 mandatory synthetic scenarios pass | End-to-end report at release SHA | Not started |
| P1-EXT-001 | Trading 212 Demo smoke | Passed or explicitly `blocked_external` with no fabricated claim | Not started |
| P1-EXT-002 | Deployed ChatGPT app registration | Passed or explicitly `blocked_external` | Not started |

## Global release rule

Release `0.1.0` requires every locally executable row to be complete, no unresolved critical/high security defect, synchronized status/progress/docs, and only the explicitly permitted external gates remaining blocked.
