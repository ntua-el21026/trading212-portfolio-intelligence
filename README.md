# Trading 212 Portfolio Intelligence

A private, premium, strictly read-only portfolio intelligence platform for Trading 212. It combines deterministic financial accounting, historical portfolio tracking, reconciliation, virtual Pies and contribution optimization, portfolio X-ray, risk/scenario/projection analytics, a responsive web/PWA application, and a ChatGPT-native MCP app.

> **Current state:** Architecture Design Freeze v0.1 is complete. Phase 1 — Trusted Foundation is approved and ready for Codex implementation.

## Product objective

Build one trustworthy portfolio operating layer that can answer:

- What do I own, what changed, and is the data current and reconciled?
- How has the portfolio actually performed after separating deposits, withdrawals, dividends, fees, currency effects, and investment gain?
- How far am I from my target portfolio, and how should a new contribution be allocated manually without selling?
- What are my true direct and indirect company, ETF, sector, country, region, and currency exposures?
- How does the portfolio behave under risk scenarios and long-horizon assumptions?
- Can all of this be queried naturally from a normal ChatGPT conversation and inspected in a premium standalone dashboard?

## Permanent safety boundary

The Trading 212 integration is **strictly read-only and default-deny**.

The product does not place, amend, cancel, schedule, or automate trades; mutate Trading 212 Pies; move money; expose a generic broker proxy; or provide broker credentials to a browser or language model. Contribution optimization produces a manual plan only.

## Interfaces

```text
ChatGPT / Apps SDK ── MCP over HTTPS ─┐
                                      ├─ Canonical application services
Next.js Web / PWA ───── HTTPS API ────┘          │
                                                  ├─ Deterministic analytics
Worker / scheduler ───────────────────────────────┤
                                                  ├─ PostgreSQL system of record
                                                  └─ GET-only provider adapters
```

The web app, API, workers, reports, and MCP tools use the same canonical domain, authorization, data-quality model, and calculation engine.

## Delivery phases

| Phase | Release | Outcome | Status |
|---|---:|---|---|
| 1. Trusted Foundation | `0.1.0` | Monorepo, exact domain/persistence, GET-only Trading 212 ingestion, ledger, reconciliation, snapshots, core accounting/allocation, API, web foundation, MCP tools, CI and operations | Ready to implement |
| 2. Portfolio Intelligence | `0.2.0` | Virtual Pies/targets, contribution optimizer, full performance/benchmarks, ETF look-through/X-ray, reports, alerts, premium analytical views | Not started |
| 3. Premium Intelligence & Productization | `1.0.0` | Advanced risk/scenarios/projections/goals, research cockpit, rich ChatGPT UI, PWA polish, premium providers and production hardening | Not started |

## Documentation

Start with [the design index](docs/DESIGN_INDEX.md).

Critical documents:

- [Architecture Design Freeze v0.1](docs/DESIGN_FREEZE_V0_1.md)
- [Product Requirements](docs/PRODUCT_REQUIREMENTS.md)
- [System Architecture](docs/SYSTEM_ARCHITECTURE.md)
- [Trading 212 GET-only Contract](docs/integrations/TRADING212_API_CONTRACT.md)
- [Financial Calculation Policy](docs/analytics/FINANCIAL_CALCULATION_POLICY.md)
- [Security Architecture](docs/security/SECURITY_ARCHITECTURE.md)
- [Master Implementation Plan](docs/implementation/MASTER_IMPLEMENTATION_PLAN.md)
- [Phase 1 Specification](docs/implementation/PHASE_1_TRUSTED_FOUNDATION.md)
- [Phase 1 Codex Prompt](docs/implementation/prompts/PHASE_1_CODEX_PROMPT.md)
- [Phase 1 Readiness Validation](VALIDATION_REPORT.md)
- [Repository Agent Policy](AGENTS.md)

## Direct-main workflow

The repository owner requires ChatGPT and Codex to commit directly to `main`:

- no feature branches or pull requests;
- small coherent fast-forward commits;
- synchronize/re-read `main` before each commit;
- run relevant complete gates before committing;
- never force-push or rewrite shared history;
- update documentation and `PROJECT_PROGRESS.json` with implementation reality.

## Phase 1 technology baseline

- Python 3.13, `uv`, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, `httpx`
- PostgreSQL 17; optional Redis 7 for coordination/cache/jobs
- official MCP Python SDK-compatible remote server
- Node.js 22 LTS, pnpm, Next.js, React, strict TypeScript
- pytest, Hypothesis, Ruff, mypy, Vitest, Playwright
- Docker Compose and GitHub Actions

Exact compatible versions and lockfiles are established during P1-01.

## Current repository contents

This baseline is documentation-first by design. Application source, migrations, tests, containers, CI, and generated contracts are created through the approved Phase 1 Codex prompt. Real Trading 212 credentials are never stored in the repository; local development uses a deterministic synthetic provider by default.

## License

Private proprietary project. No open-source license is granted.
