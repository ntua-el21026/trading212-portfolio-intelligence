# Project Status

**Project:** Trading 212 Portfolio Intelligence

**Repository:** `ntua-el21026/trading212-portfolio-intelligence`

**Implementation branch:** `codex/phase-1-trusted-foundation`

**Base branch:** `main`

**Updated:** 2026-09-01

## Current state

- Architecture Design Freeze v0.1: **Accepted**
- Documentation and Phase 1 readiness: **Approved**
- Phase 1 — Trusted Foundation (`0.1.0`): **Implementation and local runtime evidence present; final release validation pending**
- Phase 2 — Portfolio Intelligence (`0.2.0`): **Not started**
- Phase 3 — Premium Intelligence and Productization (`1.0.0`): **Not started**

P1-01 through P1-12 have implementation artifacts in the working tree. An isolated
Compose build/run, API-backed browser probe, API/MCP parity check, durable queued-run
worker restart, full-stack state-retention restart, latency smoke, and runtime secret
canary passed. All fourteen mandatory synthetic scenarios now have complete working-tree
evidence. Scenario 8 uses a retained synthetic immutable quantity/cash mismatch fixture
through persistence, API/MCP, and actual API-backed desktop/mobile web; it does not claim
that the real Trading 212 provider supplies a valid opening-history basis.

Hardened PostgreSQL and Redis initialized disposable volumes and became healthy as users
`postgres` and `redis`; API, worker, MCP, and web runtime probes passed as non-root after
unused package-manager removal. Working-tree Semgrep, Gitleaks, Trivy filesystem/config/
license, and all six high/critical vulnerability/secret image scans returned clean
results. All workflow actions and external Docker bases are immutable SHA/digest pinned.
The complete `make validate` aggregate also passed in the working tree. The immutable
release-SHA validation and pushed-SHA security reruns remain pending.

The release is not yet accepted: the complete deterministic matrix must pass at the
eventual release-candidate commit, pushed-SHA security jobs must complete, the
branch must be pushed, and a review-only pull request must be opened. No final commit SHA
or pull-request URL exists at this status checkpoint.

## Next action

Complete the release-candidate gate at one exact commit:

1. Preserve scenario 8's synthetic-only evidence boundary; real-provider bridge coverage
   stays unavailable unless valid opening-history evidence exists.
2. Commit the candidate and run every locally executable command recorded in
   `VALIDATION_REPORT.md` at that exact SHA.
3. Resolve every failure without weakening a test or invariant and obtain pushed-SHA
   Semgrep, dependency, secret, Trivy filesystem, and hardened-image results. GitHub
   code-scanning upload is unavailable for this private user-owned repository; do not
   misreport it as a pending runnable gate.
4. Record the final SHA and evidence in the implementation report.
5. Push `codex/phase-1-trusted-foundation` and open the required pull request against
   `main`; do not merge it.

The current task's explicit branch-and-pull-request instruction supersedes the older direct-`main` delivery policy for this execution. Frozen architecture and safety decisions are unchanged; only the delivery mechanism differs.

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

The Demo smoke has not run because no owner credential was supplied. Remote HTTPS/OAuth deployment and ChatGPT Developer Mode registration have not run because no deployed endpoint or production identity configuration was supplied. Live Trading 212 is intentionally not tested.

## Readiness evidence

- `docs/DESIGN_INDEX.md`
- `docs/DESIGN_FREEZE_V0_1.md`
- `docs/implementation/PHASE_1_READINESS_REVIEW.md`
- `docs/implementation/PHASE_1_TECHNICAL_BASELINE.md`
- `docs/implementation/PHASE_1_EXECUTION_MANIFEST.md`
- `docs/implementation/PHASE_1_ACCEPTANCE_MATRIX.md`
- `docs/implementation/PHASE_1_IMPLEMENTATION_REPORT.md`
- `docs/implementation/PHASE_1_SCENARIO_EVIDENCE.md`
- `VALIDATION_REPORT.md`
