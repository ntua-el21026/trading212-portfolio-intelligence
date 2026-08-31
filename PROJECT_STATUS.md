# Project Status

**Project:** Trading 212 Portfolio Intelligence  
**Repository:** `ntua-el21026/trading212-portfolio-intelligence`  
**Branch:** `main`  
**Updated:** 2026-08-31

## Current state

- Architecture Design Freeze v0.1: **Accepted**
- Documentation and Phase 1 readiness: **Approved**
- Phase 1 — Trusted Foundation (`0.1.0`): **Not started**
- Phase 2 — Portfolio Intelligence (`0.2.0`): **Not started**
- Phase 3 — Premium Intelligence and Productization (`1.0.0`): **Not started**

The repository is documentation-first. Application source, migrations, generated contracts, test suites, containers, and operational artifacts are produced by the approved Phase 1 Codex execution.

## Next action

Run the complete prompt in:

`docs/implementation/prompts/PHASE_1_CODEX_PROMPT.md`

Codex must implement P1-01 through P1-12, commit directly to `main`, and stop before Phase 2.

## Permanent boundaries

- Trading 212 integration is strict GET-only and default-deny.
- Exact capabilities are frozen in `config/contracts/trading212-read-allowlist.yaml`.
- No broker write, trade execution, Pie mutation, transfer, CFD operation, or generic proxy is allowed.
- Deterministic code—not the language model—performs authoritative financial calculations.
- PostgreSQL is the system of record.
- Web, API, workers, reports, and MCP share canonical application services.

## External gates

These do not block local Phase 1 implementation:

1. Trading 212 Demo read-only credentials and real Demo smoke.
2. Remote hosting/domain/production authentication and secret-manager selection.
3. Live ChatGPT registration against a deployed authenticated MCP endpoint.

No claim of real account connectivity or deployed ChatGPT availability is made until those gates pass.

## Readiness evidence

- `docs/DESIGN_INDEX.md`
- `docs/DESIGN_FREEZE_V0_1.md`
- `docs/implementation/PHASE_1_READINESS_REVIEW.md`
- `docs/implementation/PHASE_1_TECHNICAL_BASELINE.md`
- `docs/implementation/PHASE_1_EXECUTION_MANIFEST.md`
- `docs/implementation/PHASE_1_ACCEPTANCE_MATRIX.md`
- `VALIDATION_REPORT.md`
