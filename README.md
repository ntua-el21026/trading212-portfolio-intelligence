# Trading 212 Portfolio Intelligence

**Stage A accepted (2026-09-07):** Both audit findings and all local/CI gates passed
at `99df47b6633791c3900a52f46f56d48be922a436`. Phase 2 design closure is accepted and implementation is in progress; Phase 3
is `not_started`. See [the corrected evidence](docs/implementation/PHASE_1_AUDIT_CORRECTIONS.md).

A private, premium, strictly read-only portfolio intelligence platform for Trading 212. It combines auditable brokerage-data ingestion, deterministic financial accounting, reconciliation, historical snapshots, portfolio analytics, a responsive web/PWA application, and a ChatGPT-native MCP app.

> **Historical baseline:** Architecture Design Freeze v0.1 is approved. Phase 1 implementation is complete on `main`, and all 24 locally executable acceptance rows passed at immutable evidence SHA `e13916eca34d8e3be1ed130248d6c3d1ed7e3869`. Release readiness is `blocked_external` only by the documented owner/deployment conditions. Real Trading 212 opening-history coverage remains `unavailable_explicit` and is not inferred from the synthetic scenario 8 acceptance fixture. Phase 2 and Phase 3 are `not_started`.

## Current Phase 2 increment

P2-10 implementation is integrated, with focused verification in progress and fresh immutable acceptance pending. The accepted ledger and all prior source-bound evidence remain unchanged.

P2-09 is complete with P2-S33 authorization evidence at `bd47329cca5c1409486fff40d48e92163ab4a8af`. Phase 2 remains in progress with 9/10 completed packages (90%), 23/29 local rows and 31/40 scenarios complete. P2-MCP-001 and P2-MCP-002 retain their scoped evidence at `d70ab445de38aee255275880c5ef7a105ebbb939`. S32/S34/S38/S39 remain partial. P2-10 is `in_progress`, with its integrated implementation `implemented_unverified`; Phase 3 remains `not_started`. GitHub Actions is owner-deferred with no pass claim, and the final Phase 2 release SHA remains null.

[P209/S33 supplement](docs/implementation/evidence/phase-2-p2-09-s33-bd47329.json); finalized 2026-09-12T19:03:50.016115+00:00. The same-source relevant MCP, PostgreSQL, static, security, Python-build and single-MCP-image gates passed. The d70 full validation and browser/visual evidence remain historical; no new full validation, browser/visual gate or seven-service runtime is claimed.

[P209 scoped evidence](docs/implementation/evidence/phase-2-p2-09-d70ab44.json); finalized 2026-09-12T18:08:53.523669+00:00. The artifact retains actual widget/API browser observations as supporting evidence. It does not claim a new full Compose startup/restart, runtime cleanup, PDF visual gate or live ChatGPT registration.

### Historical P208 acceptance boundary

P2-08 has scoped local acceptance at `bc21516c51aa5090031b39ea56ded3ca94d657d8` for P2-WEB-001 and P2-WEB-002. Phase 2 remains in progress: 8/10 packages (80%), 21/29 local rows and 30/40 scenarios complete. S32/S34/S38/S39 remain partial; S33 is pending. P2-09 and P2-10 remain required and `not_started`; Phase 3 remains `not_started`. GitHub Actions is owner-deferred, not passed. The final Phase 2 release SHA remains null.

[P208 scoped evidence](docs/implementation/evidence/phase-2-p2-08-bc21516.json). P208 evidence covers the actual API-backed web processes. It does not claim a new full Compose startup/restart, runtime cleanup proof or PDF visual gate.

### Historical P207 acceptance boundary

P2-07 has scoped local acceptance at `03c3c5b0b8182aadaaf48ec29131ab7fe83095a7`: versioned alert rules, immutable scheduled evaluation, event deduplication/cooldown, authorized lifecycle/history, bounded delivery and canonical alerts exports. Phase 2 is in progress: 7/10 packages (70%), 19/29 local rows and 30/40 scenarios complete. S31 includes both report/alert durable recovery and actual Redis-loss republication of the same pending alert input. Shared API/DATA/SEC/OPS and S32/S34/S38 predicates remain partial; P2-08 through P2-10 and Phase 3 remain `not_started`. GitHub Actions is owner-deferred and unverified; no CI pass or final Phase 2 release is claimed.

[Actual P207 local evidence](docs/implementation/evidence/phase-2-p2-07-03c3c5b.json); the alerts export dataset now has its canonical retained producer. Synthetic/local evidence does not establish real provider, delivery or public deployment readiness.

## Product objective

Build one trustworthy portfolio operating layer that can answer:

- What do I own, what changed, and is the data fresh and reconciled?
- How has the portfolio performed after separating deposits, withdrawals, dividends, fees, FX effects, and investment gain?
- How far am I from a target portfolio, and how should a new contribution be allocated manually without selling?
- What are my true direct and indirect company, ETF, sector, country, region, and currency exposures?
- How does the portfolio behave under risk scenarios and long-horizon assumptions?
- Can the same canonical results be queried from ChatGPT and inspected in a premium standalone dashboard?

## Permanent safety boundary

The Trading 212 integration is **strictly read-only, fixed-allowlist, and default-deny**.

The product does not place, amend, cancel, schedule, recommend for automatic execution, or automate trades; mutate Trading 212 Pies; move money; operate CFDs; expose generic broker/HTTP/SQL/filesystem tools; or provide broker credentials to a browser or language model. Contribution optimization produces a manual proposal only.

The exact broker contract is defined in:

- [Trading 212 Read-Only API Contract](docs/integrations/TRADING212_API_CONTRACT.md)
- [Machine-Readable Trading 212 Allowlist](config/contracts/trading212-read-allowlist.yaml)

## Architecture

```text
ChatGPT / Apps SDK ── MCP over HTTPS ─┐
                                      ├─ Canonical application services
Next.js Web / PWA ───── HTTPS API ────┘          │
                                                  ├─ Deterministic analytics
Worker / scheduler ───────────────────────────────┤
                                                  ├─ PostgreSQL system of record
                                                  └─ GET-only provider adapters
```

API, web, workers, reports, and MCP tools share the same canonical domain, authorization, data-quality model, and financial calculation engine.

## Delivery phases

| Phase | Release | Outcome | Status |
|---|---:|---|---|
| 1. Trusted Foundation | `0.1.0` | Monorepo, domain/persistence, GET-only Trading 212 ingestion, reconciliation, snapshots, core accounting/allocation, API, web foundation, MCP tools, CI and operations | Implementation complete; 24 local acceptance rows complete; external gates remain |
| 2. Portfolio Intelligence | `0.2.0` | Virtual Pies/targets, contribution optimizer, benchmark performance, attribution, ETF look-through/X-ray, reports and alerts | In progress; P2-01 through P2-09 locally complete, 9/10 packages (90%); P2-10 in progress, acceptance pending; CI temporarily deferred by owner |
| 3. Premium Intelligence & Productization | `1.0.0` | Advanced risk/scenarios/projections/goals, research cockpit, rich ChatGPT UI, PWA polish, premium providers and production hardening | Not started |

## Phase 1 technical baseline

- Python `3.13.x`, `uv`, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, `httpx`, Celery 5.6
- PostgreSQL `18.x`; optional Redis `8.x` for coordination/cache/jobs
- official MCP Python SDK-compatible remote server
- Node.js `24.x LTS`, pnpm `10.x`, Next.js, React, strict TypeScript
- pytest, Hypothesis, Ruff, strict mypy, Vitest, Playwright
- Docker Compose and GitHub Actions

Exact compatible dependency versions and lockfiles are established in P1-01. See [Phase 1 Technical Baseline](docs/implementation/PHASE_1_TECHNICAL_BASELINE.md).

## Reproducible local workspace

Prerequisites are pinned to Python `3.13.15`, Node.js `24.20.0`, pnpm `10.34.5`, a current `uv`, Docker with Compose, and GNU Make. Corepack reads the exact pnpm release from `package.json`; `uv` reads the Python release from `.python-version`.

```bash
make bootstrap
make docs-check
make format-check
make lint
make typecheck
make test-unit
make build
```

Start only pinned PostgreSQL 18.6 and non-authoritative Redis 8.10.1 with `make run-dependencies`, or build, migrate, seed, and start the complete container stack with `make run-local`. PostgreSQL remains the sole authoritative financial system of record. `make dev` migrates/seeds the local database and starts the API/web host processes with loopback synthetic authentication. See the [P1-01 dependency baseline](docs/implementation/P1_01_DEPENDENCY_BASELINE.md) for registry evidence and exact pins and the [Phase 1 operations runbook](docs/operations/LOCAL_AND_DEPLOYMENT.md) for deployment, recovery, and health procedures.

**Historical full-stack web startup observation:** `make run-local` with the complete three-account seed requires the unresolved P2-08 account-configuration/selection closure described below; the accepted scratch override is not the default Compose setup.

The connected local `/pies` route now supports private hierarchical targets,
validation, immutable publication and version comparison. See the
[P2-01 implementation and recovery notes](docs/implementation/P2_01_VIRTUAL_TARGETS.md).
These are internal application targets; Trading 212 remains strictly read-only.
The `/drift` and `/planner` routes provide canonical target comparisons and
durable manual contribution plans with immutable revision history. See the
[P2-02 implementation and exact-SHA evidence](docs/implementation/P2_02_CONTRIBUTION_PLANNING.md).

The same synthetic seed also registers market, FX and benchmark sources through
their typed ingestion service. The connected `/sources` area exposes observations,
coverage, licensing and immutable benchmark definitions. Real reference providers
remain unconfigured. [P2-03 implementation and exact-SHA acceptance](docs/implementation/P2_03_REFERENCE_SOURCES.md)
records this increment's evidence boundary.

P2-04 historical performance, benchmark, attribution, income and cash-flow intelligence has [scoped exact-source acceptance](docs/implementation/P2_04_HISTORICAL_INTELLIGENCE.md) at `2a7c89a9b8c37d97006dafbbe97a44eec37b3fe0`. P2-05 now has [scoped X-ray acceptance](docs/implementation/P2_05_PORTFOLIO_XRAY.md)
at `7b102663ea193b4668924a7252180731954f4b00`: exact direct/indirect exposure, licensed sources, overlap and
canonical API/web/MCP projections. P206 adds private canonical reports and exports with [scoped local acceptance](docs/implementation/evidence/phase-2-p2-06-9e39767.json) at `9e39767b408b38203d88d6e5b41bf0bc1265adfb`. Phase 2 has 23/29 local rows and 31/40 scenarios complete. S32/S34/S38/S39 remain partial; P210 and shared release predicates remain required. GitHub Actions is deferred by explicit owner instruction across remaining Phase 2 until the owner resumes verification; no current CI pass is claimed. P207 now backs the alerts export dataset with canonical retained input and current authorization/retention.

**Historical P204/P205 runtime limitations (original observation retained):**

Source-backed known P2-08 limitations remain: the complete seed now has four accounts including the X-ray fixture, but Compose does not forward the documented T212PI_ACCOUNT_ID setting to web; unconfigured multi-account overview startup is not accepted. The accepted runtime used an explicit baseline-account scratch override. The global header must respect the authorized route account. Sticky-header section positioning, readable mobile labels and table presentation remain P2-08/S39 follow-up work. Configured runtime acceptance does not prove default unconfigured multi-account UI behavior.

**Historical P208 web-scope resolution (original statement):**

Current P208 web-scope resolution: the [P208 scoped evidence](docs/implementation/evidence/phase-2-p2-08-bc21516.json) (`/assertion_map/features`, `/assertion_map/checks`, `/runtime/browsers` and `/screenshots`) records the actual API-backed account-selection/header, mobile-label, keyboard and table workflows. Those observations resolve the web follow-up scope from the historical records above. They do not rewrite those historical runtime results, establish default Compose environment forwarding, or claim a new full Compose run. S39 remains partial for the final shared accessibility closure in P210.

Current P209 contribution: [P209 scoped evidence](docs/implementation/evidence/phase-2-p2-09-d70ab44.json) adds the bounded widget scope. S39 remains partial with final shared accessibility closure required in P210.

## Documentation entry point

Start with [Design Index and Authority Order](docs/DESIGN_INDEX.md).

Critical documents:

- [Architecture Design Freeze v0.1](docs/DESIGN_FREEZE_V0_1.md)
- [Document Governance](docs/DOCUMENT_GOVERNANCE.md)
- [Product Requirements](docs/PRODUCT_REQUIREMENTS.md)
- [System Architecture](docs/SYSTEM_ARCHITECTURE.md)
- [Trading 212 Read-Only API Contract](docs/integrations/TRADING212_API_CONTRACT.md)
- [Financial Calculation Policy](docs/analytics/FINANCIAL_CALCULATION_POLICY.md)
- [Security Architecture](docs/security/SECURITY_ARCHITECTURE.md)
- [Master Implementation Plan](docs/implementation/MASTER_IMPLEMENTATION_PLAN.md)
- [Phase 1 Specification](docs/implementation/PHASE_1_TRUSTED_FOUNDATION.md)
- [Phase 1 Execution Manifest](docs/implementation/PHASE_1_EXECUTION_MANIFEST.md)
- [Phase 1 Acceptance Matrix](docs/implementation/PHASE_1_ACCEPTANCE_MATRIX.md)
- [Phase 1 Readiness Review](docs/implementation/PHASE_1_READINESS_REVIEW.md)
- [Phase 1 Codex Prompt](docs/implementation/prompts/PHASE_1_CODEX_PROMPT.md)
- [Repository Agent Policy](AGENTS.md)
- [Validation Report](VALIDATION_REPORT.md)

## Delivery workflow

The standing repository policy requires ChatGPT and Codex to commit directly to `main`:

- no branches or pull requests;
- small coherent fast-forward commits;
- synchronize and re-read `main` before every commit;
- run relevant complete gates before committing;
- never force-push or rewrite shared history;
- update documentation and `PROJECT_PROGRESS.json` with implementation reality.

See [AGENTS.md](AGENTS.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

This workflow has no task-local or release-specific alternate delivery path. Examples and
historical records cannot authorize work away from `main`; governance must be changed on
`main` before a different workflow can become active.

## Phase 1 status

The completed Phase 1 execution prompt is retained as a historical audit record in:

```text
docs/implementation/prompts/PHASE_1_CODEX_PROMPT.md
```

P1-01 through P1-12 are complete. The immutable implementation/evidence commit is
`99df47b6633791c3900a52f46f56d48be922a436`; `main` is the authority, and later
governance/evidence reconciliation commits may be descendants of that commit. The release evidence records
85% Python coverage, 371 isolated Python tests, 73 migration/integration tests, 22 web
unit tests, 32 synthetic Playwright tests, and 6 API-backed Playwright tests. It also
validates authenticated API-backed web rendering, exact API/MCP canonical parity, the
durable refresh outbox crash/recovery path, full-stack state retention, non-root
containers and runtime secret/export-URL canary containment. See the
[validation report](VALIDATION_REPORT.md) and
[mandatory scenario evidence](docs/implementation/PHASE_1_SCENARIO_EVIDENCE.md).

All 24 locally executable Phase 1 acceptance rows are complete. Release readiness remains
`blocked_external`; this does not reopen local implementation. Scenario 8 passes through one retained
synthetic immutable quantity/cash mismatch fixture across PostgreSQL, API/MCP, and the
actual API-backed desktop/mobile web experience. This synthetic acceptance path does not
erase the real-provider limitation: quantity and cash movement bridges remain
unavailable when Trading 212 opening-history coverage is insufficient. The complete
matrix and the pinned no-upload Semgrep, dependency, secret, Trivy filesystem, and
hardened-image gates passed for the immutable evidence commit.

The complete Semgrep, Gitleaks, Trivy filesystem/config/license, and six-image
high/critical vulnerability/secret matrix returned clean results. Every workflow action
and external Docker base is immutable SHA/digest pinned.

## External gates

Local Phase 1 implementation does not require real credentials. These are the only
remaining external conditions:

- user-provided Trading 212 Demo read-only credentials and Demo smoke (`blocked_external`);
- production host, identity, and secret-manager selection (`blocked_external`);
- public HTTPS/OAuth MCP deployment and ChatGPT registration (`blocked_external`);
- real-provider opening-history coverage (`unavailable_explicit`, with limitation
  reporting complete).

Trading 212 Live remains disabled and untested; it is not an additional Phase 1 gate. No
real connectivity or deployment claim is made until the corresponding gate passes.
The owner procedure for the Demo-only probe is documented in [Credentials and Demo Validation](docs/operations/CREDENTIALS_AND_DEMO_VALIDATION.md); MCP Inspector and ChatGPT Developer Mode are documented separately in [MCP and ChatGPT Validation](docs/operations/MCP_CHATGPT_VALIDATION.md).

## License

Private proprietary project. See [LICENSE.md](LICENSE.md). No open-source license is granted.
