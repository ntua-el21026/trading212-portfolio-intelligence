# Trading 212 Portfolio Intelligence

A private, premium, strictly read-only portfolio intelligence platform for Trading 212. It combines auditable brokerage-data ingestion, deterministic financial accounting, reconciliation, historical snapshots, portfolio analytics, a responsive web/PWA application, and a ChatGPT-native MCP app.

> **Current state:** Architecture Design Freeze v0.1 and the Phase 1 implementation handoff are approved. Application implementation has not started.

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
| 1. Trusted Foundation | `0.1.0` | Monorepo, domain/persistence, GET-only Trading 212 ingestion, reconciliation, snapshots, core accounting/allocation, API, web foundation, MCP tools, CI and operations | Ready to implement |
| 2. Portfolio Intelligence | `0.2.0` | Virtual Pies/targets, contribution optimizer, benchmark performance, attribution, ETF look-through/X-ray, reports and alerts | Not started |
| 3. Premium Intelligence & Productization | `1.0.0` | Advanced risk/scenarios/projections/goals, research cockpit, rich ChatGPT UI, PWA polish, premium providers and production hardening | Not started |

## Phase 1 technical baseline

- Python `3.13.x`, `uv`, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, `httpx`, Celery 5.6
- PostgreSQL `18.x`; optional Redis `8.x` for coordination/cache/jobs
- official MCP Python SDK-compatible remote server
- Node.js `24.x LTS`, pnpm `10.x`, Next.js, React, strict TypeScript
- pytest, Hypothesis, Ruff, strict mypy, Vitest, Playwright
- Docker Compose and GitHub Actions

Exact compatible dependency versions and lockfiles are established in P1-01. See [Phase 1 Technical Baseline](docs/implementation/PHASE_1_TECHNICAL_BASELINE.md).

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

## Direct-main workflow

The owner requires ChatGPT and Codex to commit directly to `main`:

- no branches or pull requests;
- small coherent fast-forward commits;
- synchronize and re-read `main` before every commit;
- run relevant complete gates before committing;
- never force-push or rewrite shared history;
- update documentation and `PROJECT_PROGRESS.json` with implementation reality.

See [AGENTS.md](AGENTS.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Starting Phase 1

Select the repository in Codex and paste the complete prompt from:

```text
docs/implementation/prompts/PHASE_1_CODEX_PROMPT.md
```

Codex is instructed to inspect current `main`, implement all P1-01 through P1-12, validate coherent increments, commit directly to `main`, and stop before Phase 2.

## External gates

Local Phase 1 implementation does not require real credentials. These remain explicit later verification gates:

- user-provided Trading 212 Demo read-only credentials and Demo smoke;
- remote hosting/domain/production authentication/secret-manager selection;
- live ChatGPT app registration against the deployed authenticated MCP endpoint.

No real connectivity or deployment claim is made until the corresponding gate passes.

## License

Private proprietary project. See [LICENSE.md](LICENSE.md). No open-source license is granted.
