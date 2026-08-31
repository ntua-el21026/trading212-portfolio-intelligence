# Scope and Non-Goals

**Status:** Accepted

## In scope

### Initial operating scope

- Private, single-user deployment.
- Trading 212 Invest account data.
- Demo and Live read-only environments.
- EUR-first reporting with explicit multi-currency support.
- Current positions, account/cash information, reference instruments/exchanges, pending/historical order visibility, transactions, and dividends.
- Historical snapshots and canonical portfolio ledger.
- Deterministic accounting, allocation, performance, risk, and projection capabilities delivered according to the three phases.
- Standalone responsive web/PWA interface.
- ChatGPT MCP/Apps SDK interface.
- Manual contribution recommendations and portfolio analysis.
- Reports, exports, alerts, and research notes in later phases.
- Provider-neutral extension interfaces for future brokers and data providers.

## Permanently excluded under Design Freeze v0.1

- Order placement of any type.
- Order amendment or cancellation.
- Broker Pie mutation or automatic rebalancing.
- Automated, algorithmic, scheduled, or AI-directed trading.
- Custody, money movement, deposits, withdrawals, transfers, or payments.
- Access to CFD accounts or leveraged broker execution.
- Storage of broker credentials in browsers, mobile clients, prompts, reports, or source control.
- Investment-adviser or fiduciary claims.
- Guaranteed returns, price predictions presented as facts, or personalized tax/legal conclusions.
- Scraping or redistribution that violates provider terms or data licenses.

## Deferred, not prohibited

These capabilities are outside Phase 1 and must not be implemented early, but the architecture may define interfaces for them:

- virtual Pies, targets, and contribution optimization — Phase 2;
- ETF look-through and portfolio X-ray — Phase 2;
- full reporting/alerts — Phase 2;
- advanced risk, stress testing, Monte Carlo, and goals — Phase 3;
- research cockpit and rich ChatGPT UI — Phase 3;
- multi-user SaaS operation;
- additional brokers;
- native iOS/Android applications;
- paid market/ETF data providers;
- household or advisor-client aggregation.

## Scope-control rule

A feature enters an implementation phase only when its requirements, data contract, failure modes, privacy/security effects, tests, and acceptance criteria are documented. Architectural hooks alone must remain inert and must not create unsupported UI, claims, or operational dependencies.
