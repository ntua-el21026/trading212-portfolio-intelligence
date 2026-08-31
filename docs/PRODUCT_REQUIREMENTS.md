# Product Requirements

**Status:** Accepted for Design Freeze v0.1

## 1. Product objective

Create a private, premium portfolio intelligence platform for a Trading 212 Invest user that is materially more trustworthy and analytically capable than a broker dashboard while remaining safe, explainable, and convenient from both a standalone web/PWA interface and normal ChatGPT web conversations.

The platform must answer three classes of question:

1. **What do I own and what changed?**
2. **How has the portfolio actually performed after accounting for cash flows, currency, dividends, and data quality?**
3. **How should I analyze, monitor, and manually allocate future contributions without delegating trade execution?**

## 2. Primary user

The initial product is a single-user private deployment for an advanced retail investor using Trading 212 Invest, reporting primarily in EUR, investing through direct equities and ETFs, maintaining target portfolios/Pies, and using monthly contributions.

The architecture must preserve explicit account and owner boundaries so later multi-account and multi-user support does not require rewriting the core domain.

## 3. Core product principles

- Correctness before feature count.
- Deterministic calculations before language-model interpretation.
- Read-only safety before convenience.
- Visible provenance and uncertainty before false precision.
- One canonical backend for every interface.
- Provider-neutral domain models around provider-specific adapters.
- Mobile-accessible but information-dense financial UX.
- Reproducible analytics and simulations.
- Graceful degradation when data is stale, partial, estimated, or unreconciled.

## 4. Functional requirements by capability

### 4.1 Account and broker data

The system shall:

- connect to Trading 212 Demo by default and Live only when explicitly configured;
- obtain account metadata and cash/account summary through allowlisted read calls;
- obtain instrument and exchange reference data;
- obtain current positions;
- obtain pending/current order information for visibility only;
- obtain historical order data;
- obtain transactions and cash movements;
- obtain dividend history;
- preserve provider IDs, source timestamps, ingestion timestamps, payload fingerprints, and pagination/checkpoint state;
- expose data freshness and reconciliation status;
- retry only safe idempotent reads according to bounded policy;
- coordinate around provider rate limits;
- never expose or implement broker mutations.

### 4.2 Canonical portfolio history

The system shall:

- normalize provider data into canonical account, instrument, position, cash-flow, transaction, order, dividend, and snapshot models;
- maintain immutable/auditable ingestion provenance;
- create repeatable portfolio snapshots;
- retain enough information to reconstruct position and cash-flow history subject to source-data availability;
- reconcile current positions against normalized activity and explicitly record discrepancies;
- distinguish observed, derived, estimated, and unavailable values;
- support safe replay/re-ingestion without duplication.

### 4.3 Core accounting and allocation

The system shall calculate deterministically:

- total portfolio value;
- cash and invested value;
- net deposits and withdrawals;
- current position market value;
- weighted average acquisition information when source data permits;
- realized and unrealized profit/loss with method and coverage stated;
- dividends and other cash income;
- direct holding weights;
- reporting-currency values with FX source/coverage stated;
- account and portfolio changes across recorded snapshots;
- initial money-weighted and time-weighted performance only when input coverage meets the documented standard.

### 4.4 Virtual Pies and target allocations — Phase 2

The system shall provide broker-independent, versioned target portfolios supporting:

- nested groups/Pies;
- target weights at group and holding levels;
- effective dates and archived target versions;
- identifier mapping independent of display ticker;
- constraints, exclusions, cash targets, and maximum weights;
- actual-versus-target comparison;
- drift measurement with multiple documented metrics.

Trading 212's native Pie API must not be the canonical source because the product domain must remain stable even if that API changes or is deprecated.

### 4.5 Contribution planning — Phase 2

The system shall produce explainable manual contribution plans that:

- accept an available contribution amount;
- support contribution-only/no-sale optimization;
- allocate across groups first and holdings second when requested;
- minimize a documented drift objective;
- respect minimum amounts, instrument exclusions, cash reserves, maximum weights, and optional priorities;
- handle infeasible constraints explicitly;
- return pre- and post-contribution weights, residual drift, rounded amounts, and warnings;
- never submit an order.

### 4.6 Portfolio X-ray — Phase 2

With sufficient licensed/provider data, the system shall:

- resolve direct and indirect company exposure through ETFs;
- measure ETF overlap;
- aggregate multiple listings, ADRs, share classes, and parent-company exposure when mapping confidence is adequate;
- calculate effective sector, country, region, and currency exposure;
- expose constituent coverage, dates, source, mapping confidence, and unsupported instruments;
- avoid claiming full look-through where coverage is incomplete.

### 4.7 Performance and attribution — Phase 2

The system shall support:

- money-weighted return/XIRR;
- time-weighted return;
- Modified Dietz for explicitly bounded reporting periods where appropriate;
- nominal and reporting-currency performance;
- benchmark comparisons on aligned valuation/cash-flow periods;
- contribution, dividend, realized/unrealized, fee, and FX decomposition where data supports it;
- position and group contribution attribution with residual/reconciliation reporting;
- methodology/version disclosure.

### 4.8 Risk, scenarios, and goals — Phase 3

The system shall add, with adequate market history:

- volatility, downside deviation, beta, covariance, correlation, drawdowns, VaR, Expected Shortfall, concentration, and risk contribution;
- deterministic shock scenarios and historical replays;
- scenario versioning and reproducible assumptions;
- Monte Carlo projections with seeded/reproducible runs;
- nominal and inflation-adjusted goal planning;
- contribution growth, pauses, lump sums, withdrawals, and target probabilities;
- explicit separation of observed history from assumptions.

### 4.9 Research cockpit — Phase 3

The system shall support portfolio-aware research without making autonomous investment decisions:

- rank companies/events by effective portfolio exposure;
- save research notes, theses, risks, and thesis-break conditions;
- link cited public sources and source dates;
- distinguish factual source data, deterministic portfolio facts, and model-generated synthesis;
- record research history and material-change reviews;
- never allow research output to trigger execution.

### 4.10 Web/PWA interface

The web application shall provide:

- secure authentication;
- portfolio command center;
- holdings, transactions, dividends, cash flows, data quality, and history views;
- responsive desktop/tablet/mobile layouts;
- accessible keyboard and screen-reader behavior;
- clear loading, empty, stale, partial, and error states;
- source/methodology drill-down;
- Phase 2 target, optimizer, X-ray, report, and alert views;
- Phase 3 risk, scenario, goal, and research views;
- installable PWA behavior in Phase 3;
- no client-side broker credentials.

### 4.11 ChatGPT application

The ChatGPT integration shall:

- expose a remote authenticated MCP endpoint;
- provide explicit, narrow, schema-validated read/fetch analytical tools;
- use the same application services as the web interface;
- include source timestamps, data-quality state, assumptions, and warnings in tool outputs;
- support natural-language requests for account summaries, positions, portfolio snapshots, changes, cash flows, dividends, direct allocation, and Phase 2/3 analytics as implemented;
- provide bounded results and pagination/summary controls;
- never accept arbitrary provider URLs/paths or expose a general database query tool;
- never execute trades or return secrets;
- support rich Apps SDK resources progressively without making core functionality UI-dependent.

### 4.12 Reports and exports — Phase 2

The system shall generate private, reproducible reports/exports in appropriate formats, including PDF, CSV, JSON, and XLSX, with:

- portfolio/account scope;
- report period and valuation timestamp;
- calculation version;
- source freshness and quality warnings;
- methodology notes;
- access control and retention;
- deterministic values consistent with the API and web UI.

## 5. Non-functional requirements

### Correctness

- Exact decimal money arithmetic.
- Explicit currencies and timezones.
- Deterministic/versioned calculations.
- Idempotent ingestion and migrations.
- Reconciliation residuals must be visible.
- Property-based and reference-fixture tests for financial invariants.

### Security

- Strict read-only broker boundary.
- Server-side secret storage and redaction.
- Authentication and authorization on non-public surfaces.
- Rate limiting and bounded payloads.
- Dependency, secret, static, and container scanning.
- Audit records for ingestion, calculation runs, exports, and security-relevant configuration changes.

### Reliability

- Bounded retries with jitter for safe reads.
- Provider rate-limit awareness.
- Job idempotency and lease/lock semantics.
- Health/readiness endpoints.
- Database backup and tested restoration before production readiness.
- Graceful degraded operation when external providers fail.

### Performance

Initial single-user targets under normal cached conditions:

- common dashboard API p95 below 500 ms excluding first external ingestion;
- common MCP summary tool p95 below 2 s excluding explicit refresh;
- interactive dashboard usable within 2.5 s on a typical broadband connection;
- long analytics/report jobs asynchronous with status tracking;
- no unbounded provider or database scans in request paths.

Targets must be measured and may be refined through an ADR based on evidence.

### Accessibility and UX

- WCAG 2.2 AA target for first-party web surfaces.
- No color-only semantic encoding.
- Keyboard-accessible core workflows.
- Reduced-motion support.
- Tables and visualizations must have meaningful text alternatives.
- Financial values must consistently display currency, sign, precision, period, and timestamp.

### Maintainability

- Typed contracts and strict static analysis.
- Provider adapters isolated from domain/application services.
- Generated clients from versioned OpenAPI/schema contracts.
- Clear migration/release process.
- High-value tests rather than superficial coverage targets alone.
- Documentation updated in the same commit as behavior.

## 6. Success criteria

The product succeeds when it can safely and reproducibly answer portfolio questions from both web and ChatGPT, distinguish contributions from investment performance, show the provenance and quality of its conclusions, generate a constraint-aware manual contribution plan, and expose true direct/indirect exposure without creating a broker-write or secret-exposure path.
