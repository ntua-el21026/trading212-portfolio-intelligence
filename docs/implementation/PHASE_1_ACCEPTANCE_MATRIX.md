# Phase 1 Acceptance Matrix

**Status:** Release-candidate evidence review in progress

**Release target:** `0.1.0`

A row is complete only when the implementation records reproducible evidence at the exact release SHA.

The state `Implementation present; final gate pending` means the relevant source and
focused tests exist. `Working-tree runtime passed; final gate pending` additionally means
the material runtime behavior was observed locally. Neither state is complete until the
full command is rerun and recorded at the release-candidate SHA.

| ID | Acceptance condition | Candidate evidence | State |
|---|---|---|---|
| P1-SAFE-001 | Registry contains exactly the documented ten Trading 212 GET capabilities | Packaged/root allowlists; `test_allowlist.py`; workspace and repository validators | Implementation present; final gate pending |
| P1-SAFE-002 | Unknown/non-GET/path-injected request fails before transport | Provider transport-spy negatives; `check_trading212_boundary.py`; security tests | Implementation present; final gate pending |
| P1-SAFE-003 | No order/Pie/transfer/CFD/export-creation code path exists | Repository-wide boundary scanner and architecture tests | Implementation present; final gate pending |
| P1-SEC-001 | Secrets remain server-side and redacted | Central redaction/secret abstractions, canary tests, secret scanner, API/MCP negative tests; runtime log/image canary scan | Working-tree runtime passed; final gate pending |
| P1-AUTH-001 | Every owner/account use case is authorized | Session/CSRF/account ownership tests for API and MCP | Implementation present; final gate pending |
| P1-DOM-001 | Money/quantity/price/FX/ratio use exact decimal semantics | Canonical domain values, exact database types, unit/property tests | Implementation present; final gate pending |
| P1-DOM-002 | Timestamps are aware UTC and quality states are distinct | Domain metadata/serialization tests and provider boundary tests | Implementation present; final gate pending |
| P1-DATA-001 | Full/incremental ingestion is idempotent | In-memory/PostgreSQL duplicate and revision tests; exact transaction high-water plus seven-day overlap; full replay/dedup fallback for order/dividend contracts without a time filter | Implementation present; final gate pending |
| P1-DATA-002 | Checkpoints advance only after durable atomic success | Atomic rollback, interrupted/resumed, monotonic empty-page watermark, stable cursor/filter, and cross-run resumed-materialization tests | Implementation present; final gate pending |
| P1-DATA-003 | Schema/pagination/rate-limit failures are bounded and explicit | Strict DTO, pagination-loop, partial-failure, retry, and Redis coordination tests | Implementation present; final gate pending |
| P1-REC-001 | Position and cash discrepancies are first-class and versioned | Reconciliation reference/property tests, immutable persistence, API/MCP parity, and API-backed desktop/mobile mismatch rendering | Working-tree runtime passed; final gate pending |
| P1-SNAP-001 | Snapshots are immutable, reproducible, and source-cutoff aware | Snapshot repository/reference tests and unique versioned persistence keys | Implementation present; final gate pending |
| P1-CALC-001 | Deposits/withdrawals are separated from investment gain | Ledger/performance hand-calculated fixtures and properties | Implementation present; final gate pending |
| P1-CALC-002 | Core values and direct allocations reconcile exactly | Portfolio aggregation/allocation reference and property tests | Implementation present; final gate pending |
| P1-CALC-003 | Return metrics are coverage-gated and never invent missing data | Partial-history/missing-FX/quality degradation tests | Implementation present; final gate pending |
| P1-API-001 | `/api/v1` is typed, bounded, authorized, and stable | FastAPI route/auth/error tests and generated OpenAPI contract | Implementation present; final gate pending |
| P1-API-002 | Generated TypeScript client matches OpenAPI and compiles | `generate_api_contract.py --check`; strict TypeScript build | Implementation present; final gate pending |
| P1-WEB-001 | Phase 1 views are responsive and accessible | Vitest component/state coverage and desktop/mobile Playwright suite | Implementation present; final gate pending |
| P1-WEB-002 | Web displays timestamps/method/quality/warnings without recalculating | Shared generated client, rendering/state tests, API-backed browser smoke with exact `248431.27` EUR total and explicit coverage gap | Working-tree runtime passed; final gate pending |
| P1-MCP-001 | MCP tools are authenticated, bounded, typed, and allowlisted | Exact nine-tool descriptor/auth/negative tests and `/mcp` contract tests | Implementation present; final gate pending |
| P1-MCP-002 | MCP and API results match canonical fixtures exactly | Contract test plus pre/post-restart API/MCP runtime parity at `248431.27` EUR | Working-tree runtime passed; final gate pending |
| P1-OPS-001 | Clean clone can bootstrap, migrate, seed, run, test, and build | Pinned locks, Make targets, CI workflow, Compose stack | Pending final clean-environment gate |
| P1-OPS-002 | Containers, telemetry, migrations, backup/incident runbooks exist | Non-root Dockerfiles/runbooks plus healthy UID-10001 images, durable worker restart, full-stack restart, state/hash retention, and runtime canary scan | Working-tree runtime passed; final gate pending |
| P1-E2E-001 | All 14 mandatory synthetic scenarios pass | All fourteen scenarios have complete working-tree evidence; scenario 8 uses one retained synthetic immutable mismatch fixture through persistence, API/MCP, and actual API-backed desktop/mobile web | Working-tree scenarios passed; final release-SHA report pending |
| P1-EXT-001 | Trading 212 Demo smoke | Demo-only opt-in script and owner runbook; credential-dependent execution not performed | `blocked_external` |
| P1-EXT-002 | Deployed ChatGPT app registration | Inspector/Developer Mode runbook; public HTTPS/OAuth deployment not supplied | `blocked_external` |

## Current evidence boundary

- Baseline: `c566c080762f9d74996e1bdd19d1254848f8f17f` on `main`.
- Candidate branch: `codex/phase-1-trusted-foundation`.
- Release-candidate SHA: not assigned; changes are still uncommitted at this checkpoint.
- Pull request: not opened at this checkpoint.
- Focused subsystem checks and an isolated Compose runtime/restart exercise have passed in
  the working tree, but the authoritative repository-wide gate at one immutable SHA
  remains pending.
- Compose project `t212pi_phase1_final_20260831` ran rebuilt API, worker, MCP, and web
  images as UID `10001`; queued-run recovery, full-stack state retention, API-backed web,
  API/MCP parity, performance probes, and runtime canary checks passed.
- Mandatory scenarios 8, 9, 11, 13, and 14 are passed in working-tree evidence. Scenario
  8 is deliberately synthetic; real Trading 212 quantity/cash bridge coverage remains
  unavailable without a valid opening-history basis and is still reported explicitly.
- The private repository cannot use GitHub code-scanning upload under the current
  user-owned repository entitlement. The blocking no-upload SAST substitute is pinned
  Semgrep CE `1.175.0` with repository-local rules. Working-tree Semgrep, Gitleaks,
  Trivy filesystem/config/license, and all six hardened-image scans returned clean;
  final-SHA Semgrep, dependency, secret, Trivy filesystem, and hardened-image jobs remain
  pending.
- Real Trading 212 Demo connectivity, production deployment, and ChatGPT Developer Mode registration are not claimed.

See [Phase 1 Implementation Report](PHASE_1_IMPLEMENTATION_REPORT.md) and the root `VALIDATION_REPORT.md` for the release evidence ledger.

## Global release rule

Release `0.1.0` requires every locally executable row to be complete, no unresolved critical/high security defect, synchronized status/progress/docs, and only the explicitly permitted external gates remaining blocked. This rule has not yet been satisfied at the current working-tree checkpoint.
