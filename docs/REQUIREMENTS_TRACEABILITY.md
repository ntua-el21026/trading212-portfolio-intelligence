# Requirements Traceability

**Status:** Accepted baseline

This matrix links product requirements to implementation phases and verification evidence. Detailed acceptance criteria remain authoritative in the phase specifications and acceptance matrix.

| Requirement | Phase | Primary authority | Verification class |
|---|---:|---|---|
| Strictly read-only Trading 212 integration | 1 | Trading 212 contract, design freeze | Static allowlist, runtime-negative transport tests |
| Canonical provider-independent portfolio model | 1 | Domain/data model | Unit/property/architecture tests |
| Auditable ingestion and source provenance | 1 | Jobs/ingestion, domain model | Integration, replay, checkpoint tests |
| Historical snapshots and change comparison | 1 | Phase 1 spec | Repository/integration/reference tests |
| Cash/position reconciliation | 1 | Data quality/reconciliation | Reference and discrepancy tests |
| Correct deposits-versus-performance separation | 1 | Performance accounting | Hand-calculated fixtures/property tests |
| Direct allocation and core portfolio summary | 1 | Financial policy, Phase 1 | API/MCP/web parity fixtures |
| Secure authenticated API and MCP | 1 | Security, API/MCP contracts | Authz, bounds, negative, canary tests |
| Responsive accessible web foundation | 1 | Phase 1 spec | Component, accessibility, Playwright tests |
| Virtual Pies and versioned targets | 2 | Product requirements, Phase 2 | Domain/API/E2E tests |
| Contribution-only optimization | 2 | Optimizer methodology | Solver properties/reference scenarios |
| Benchmark and attribution analytics | 2 | Phase 2 | Reproducible market-data fixtures |
| ETF look-through and true exposure | 2 | Portfolio X-ray | Coverage, identity, residual tests |
| Reports, exports, alerts | 2 | Phase 2 | Rendering/export/rule E2E tests |
| Advanced risk and scenarios | 3 | Risk/stress methodology | Independent reference validation |
| Monte Carlo and goal planning | 3 | Risk/projection methodology | Seeded reproducibility/statistical tests |
| Portfolio-aware research cockpit | 3 | Product requirements, Phase 3 | Citation/provenance/E2E tests |
| Premium ChatGPT rich UI/PWA productization | 3 | ChatGPT/PWA specifications | Apps SDK, visual, accessibility, E2E tests |

## Phase 1 requirement identifiers

- `P1-SAFE-001`: exact GET-only Trading 212 registry.
- `P1-SAFE-002`: no generic provider/request surface.
- `P1-SAFE-003`: no order, Pie, transfer, CFD, or export-creation code path.
- `P1-SEC-001`: secrets remain server-side and redacted.
- `P1-AUTH-001`: owner/account authorization on every scoped use case.
- `P1-DOM-001`: exact decimal semantics for money, quantity, price, FX, and ratios.
- `P1-DOM-002`: timezone-aware UTC and distinct data-quality states.
- `P1-DATA-001`: idempotent full and incremental canonical ingestion.
- `P1-DATA-002`: checkpoints advance only after durable atomic success.
- `P1-DATA-003`: schema, pagination, and rate-limit failures are bounded and explicit.
- `P1-REC-001`: explicit quantity/cash reconciliation and discrepancy history.
- `P1-SNAP-001`: immutable versioned snapshots with source cutoff.
- `P1-CALC-001`: deposits excluded from investment gain.
- `P1-CALC-002`: core values and direct allocations reconcile exactly.
- `P1-CALC-003`: return metrics are coverage-gated and never invent missing data.
- `P1-API-001`: versioned, typed, bounded, authorized, stable API.
- `P1-API-002`: generated TypeScript client matches OpenAPI and compiles.
- `P1-WEB-001`: responsive accessible Phase 1 views.
- `P1-WEB-002`: web exposes timestamps, methodology, quality, and warnings without recalculation.
- `P1-MCP-001`: authenticated, bounded, typed, allowlisted MCP tools.
- `P1-MCP-002`: MCP and API results match canonical fixtures exactly.
- `P1-OPS-001`: clean-clone bootstrap, migrate, seed, run, test, and build.
- `P1-OPS-002`: containers, telemetry, migrations, and backup/incident runbooks.
- `P1-E2E-001`: all fourteen mandatory synthetic scenarios pass.
- `P1-EXT-001`: Trading 212 Demo smoke passes or remains explicitly `blocked_external`.
- `P1-EXT-002`: deployed ChatGPT app registration passes or remains explicitly `blocked_external`.

`docs/implementation/PHASE_1_ACCEPTANCE_MATRIX.md` maps these identifiers to concrete evidence.
