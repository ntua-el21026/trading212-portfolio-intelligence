# Project Status

**Project:** Trading 212 Portfolio Intelligence

**Repository:** `ntua-el21026/trading212-portfolio-intelligence`

**Implementation authority:** `main`

**Updated:** 2026-09-07

## Current state

Stage A is **complete** at `99df47b6633791c3900a52f46f56d48be922a436`. F-01 and F-02 are closed;
all 24 locally executable acceptance rows and 14 mandatory synthetic scenarios,
all three workflows, all local gates, and the fresh Compose acceptance passed.
Python verification: 371 isolated plus 73 service-backed tests and 85% coverage.
Migration head: `20260907_0008`; MCP: nine tools; Trading 212: ten GET capabilities.
Phase 2 is `in_progress`: P2-01 is complete at
`ecc75154397c8f9d7532fa2df8576846b60bae7c`, with three of 29 local acceptance rows
and five of 40 scenarios complete. Its domain, persistence, API, web, MCP and
scheduled activation passed full local validation, all three CI workflows and a
fresh seven-service restart. Verification recorded 592 isolated and 103
service-backed Python tests, 86% coverage, 48 web unit tests, 32 synthetic browser
tests and 12 API-backed browser tests, with no browser retries. Migration head is
`20260907_0009`; the implemented MCP registry contains 11 tools. The original
implementation's two Gitleaks test-code false positives were corrected with exact
historical fingerprint exceptions in the accepted SHA and all gates rerun.
See [the P2-01 evidence](docs/implementation/evidence/phase-2-p2-01-ecc7515.json).
P2-02 contribution planning is `in_progress`. Its four-mode Decimal solver,
normalized requests/results, fixed durable job, six API operations, four MCP
tools and drift/planner web routes are committed at
`5fa43b2fe1f671b9e2734c70fd0c13480ae08555`. Exact local validation passed 790
isolated and 124 service-backed Python tests, 87% combined coverage with branch
measurement, 111 web unit tests and 52 browser tests without retries. Seventeen
rational optimizer reference cases and 175 observed property examples passed.
Documentation and security CI passed; quality run `34144309940` failed because
the configured CI browser database was reused across desktop/mobile launches,
exhausting the unchanged owner snapshot quota. The fixture-isolation correction
creates a disposable database for each launch and requires a new exact-SHA run.
The failed candidate is not accepted. Fresh Compose runtime evidence and all
exact pushed-SHA gates remain pending.
P2-02 through P2-10 remain required.
Phase 3 remains `not_started`.

## Previously accepted baseline

- Architecture Design Freeze v0.1: **Accepted**
- Documentation and Phase 1 readiness: **Approved**
- Phase 1 — Trusted Foundation (`0.1.0`): **Implementation complete; 24 locally executable acceptance rows complete; release readiness `blocked_external`**
- Phase 2 — Portfolio Intelligence (`0.2.0`): **Not started**
- Phase 3 — Premium Intelligence and Productization (`1.0.0`): **Not started**

P1-01 through P1-12 and all 24 locally executable acceptance rows are complete. The
immutable implementation/evidence SHA is
`e13916eca34d8e3be1ed130248d6c3d1ed7e3869`. `main` remains the implementation
authority; final governance/evidence reconciliation may advance `main` to a descendant
without changing the commit at which executable evidence was recorded.

The evidence run recorded 84% Python coverage, 338 isolated Python tests, 64
migration/integration tests, 22 web unit tests, 32 synthetic Playwright tests, and 6
API-backed Playwright tests. Alembic head is `20260901_0007`, and the MCP registry contains
exactly nine Phase 1 tools. The durable refresh outbox/API crash-recovery path, semantic
idempotency conflicts, stable complete collection traversal, API/MCP parity, desktop and
mobile pagination, full-stack state retention, non-root containers, and runtime secret
containment passed their locally executable gates.

Hardened PostgreSQL and Redis initialized disposable volumes and became healthy as users
`postgres` and `redis`; API, worker, dispatcher, MCP, and web runtime probes passed as
non-root. Semgrep, Gitleaks complete-history scanning, dependency audits, Trivy
filesystem/config/license scanning, and all application/infrastructure container scans
passed. All workflow actions and external Docker bases are immutable SHA/digest pinned.

Scenario 8 uses a retained synthetic immutable quantity/cash mismatch fixture through
persistence, API/MCP, and actual API-backed desktop/mobile web. It does not claim that
the real Trading 212 provider supplies a valid opening-history basis. That real-provider
coverage condition remains `unavailable_explicit`, with the limitation reported rather
than fabricated.

## Next action

Complete and accept P2-02, then implement P2-03 through P2-10 under the accepted [v0.2 design delta](docs/DESIGN_FREEZE_V0_2.md). Preserve these separate external
owner/deployment conditions without substituting synthetic evidence:

1. Run the owner-controlled Trading 212 Demo smoke when a dedicated read-only Demo
   credential is supplied.
2. Select the production host, identity provider, and secret manager.
3. Deploy the authenticated MCP endpoint over public HTTPS/OAuth and complete ChatGPT
   registration.
4. Continue to report unavailable real-provider opening-history coverage explicitly
   unless valid provider evidence becomes available.

The accepted direct-`main` policy is the only active delivery mechanism. Frozen
architecture and safety decisions remain unchanged. Phase 2 is `in_progress`; Phase 3 remains `not_started`.

## Permanent boundaries

- Trading 212 integration is strict GET-only and default-deny.
- Exact capabilities are frozen in `config/contracts/trading212-read-allowlist.yaml`.
- No broker write, trade execution, Pie mutation, transfer, CFD operation, or generic proxy is allowed.
- Deterministic code—not the language model—performs authoritative financial calculations.
- PostgreSQL is the system of record.
- Web, API, workers, reports, and MCP share canonical application services.

## External gates

These are the only remaining external conditions and do not reopen local Phase 1
implementation:

1. Trading 212 Demo read-only credentials and Demo smoke — `blocked_external`.
2. Production host, identity, and secret-manager selection — `blocked_external`.
3. Public HTTPS/OAuth MCP deployment and ChatGPT registration — `blocked_external`.
4. Real-provider opening-history coverage — `unavailable_explicit`; limitation reporting
   is complete.

No claim of real account connectivity or deployed ChatGPT availability is made until
those gates pass. Trading 212 Live is disabled and untested; it is not an additional
Phase 1 gate.

The Demo smoke has not run because no owner credential was supplied. Production
selection and public HTTPS/OAuth MCP deployment with ChatGPT registration have not run
because those external resources were not supplied.

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
