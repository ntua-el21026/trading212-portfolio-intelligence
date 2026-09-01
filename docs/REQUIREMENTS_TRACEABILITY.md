# Requirements Traceability

**Status:** Accepted baseline

This matrix links product requirements to implementation phases and verification evidence. Detailed acceptance criteria remain authoritative in the phase specifications and acceptance matrix.

| Requirement | Phase | Primary authority | Verification class |
|---|---:|---|---|
| Strictly read-only Trading 212 integration | 1 | Trading 212 contract, design freeze | Static allowlist, runtime-negative transport tests |
| Canonical provider-independent portfolio model | 1 | Domain/data model | Unit/property/architecture tests |
| Auditable ingestion and source provenance | 1 | Jobs/ingestion, domain model | Integration, replay, checkpoint tests |
| Atomic durable refresh dispatch and crash recovery | 1 | Jobs/ingestion, Phase 1 spec | Outbox migration, API-crash restart, expired-claim, duplicate-delivery tests |
| Semantic refresh idempotency | 1 | Phase 1 spec, API/service contracts | Lifecycle retry, promoted-semantics, conflict and concurrency tests |
| Stable complete collection traversal | 1 | API/service contracts, Phase 1 spec | More-than-10,000-row, cursor-binding, exact-total, mutation-stability tests |
| Historical snapshots and change comparison | 1 | Phase 1 spec | Repository/integration/reference tests |
| Cash/position reconciliation | 1 | Data quality/reconciliation | Reference and discrepancy tests |
| Correct deposits-versus-performance separation | 1 | Performance accounting | Hand-calculated fixtures/property tests |
| Direct allocation and core portfolio summary | 1 | Financial policy, Phase 1 | API/MCP/web parity fixtures |
| Secure authenticated API and MCP | 1 | Security, API/MCP contracts | Authz, bounds, negative, canary tests |
| Canonical Phase 1 application-service coverage | 1 | API/service contracts | PostgreSQL/synthetic parity, broker/instrument/performance/quality tests |
| Nine-tool MCP server-side query semantics | 1 | ChatGPT MCP contract | Full-filtered-set aggregation, direct lookup, API-parity tests |
| Responsive accessible web foundation | 1 | Phase 1 spec | URL cursor/back-navigation, desktop/mobile accessibility, Playwright tests |
| Dispatcher readiness and bounded queue telemetry | 1 | Jobs/ingestion, deployment operations | Heartbeat/readiness and outbox backlog/age/attempt/failure/recovery tests |
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
- `P1-DATA-001`: idempotent full/incremental canonical ingestion and semantic refresh
  identity; identical retries coalesce while mismatched account/key semantics conflict.
- `P1-DATA-002`: checkpoints advance only after durable atomic success, and a refresh run
  plus its fixed non-secret dispatch event commit in one transaction for crash recovery.
- `P1-DATA-003`: schema, provider pagination, rate-limit, outbox retry, and collection
  cursor/filter/total failures are bounded, stable, complete, and explicit.
- `P1-REC-001`: explicit quantity/cash reconciliation and discrepancy history.
- `P1-SNAP-001`: immutable versioned snapshots with source cutoff.
- `P1-CALC-001`: deposits excluded from investment gain.
- `P1-CALC-002`: core values and direct allocations reconcile exactly.
- `P1-CALC-003`: return metrics are coverage-gated and never invent missing data.
- `P1-API-001`: versioned, typed, bounded, authorized, stable API backed by canonical
  broker-connection, instrument, snapshot, performance, reconciliation, quality, and
  collection use cases; mutable collections use integrity-protected stable cursors.
- `P1-API-002`: generated TypeScript client matches OpenAPI and compiles.
- `P1-WEB-001`: responsive accessible Phase 1 views with route-specific typed loaders and
  URL-backed cursor/filter state for accessible page/load-more and browser history.
- `P1-WEB-002`: web exposes timestamps, methodology, quality, warnings, and explicit
  preview returned/full counts without authoritative recalculation.
- `P1-MCP-001`: exactly nine authenticated, bounded, typed, allowlisted MCP tools using
  dedicated server-side queries rather than capped collect-then-filter behavior.
- `P1-MCP-002`: MCP and API results and quality states match canonical full-filtered-set
  fixtures exactly while returned payloads remain bounded.
- `P1-OPS-001`: clean-clone bootstrap, migrate, seed, run, test, and build.
- `P1-OPS-002`: containers, telemetry including dispatcher readiness/outbox health,
  migrations through `20260901_0007`, and backup/incident runbooks.
- `P1-E2E-001`: all fourteen mandatory synthetic scenarios pass, with scenario 14
  independently proving API commit-before-publication recovery, worker restart after
  confirmed publication, and full-stack state retention.
- `P1-EXT-001`: Trading 212 Demo smoke passes or remains explicitly `blocked_external`.
- `P1-EXT-002`: deployed ChatGPT app registration passes or remains explicitly `blocked_external`.

`docs/implementation/PHASE_1_ACCEPTANCE_MATRIX.md` maps these identifiers to concrete evidence.
