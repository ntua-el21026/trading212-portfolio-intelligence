# Feature Catalog

**Status:** Accepted product catalog  
**Purpose:** Map user-facing capabilities to delivery phase, authoritative specification, inputs, and safety/data-quality expectations. A listed feature is not implemented until its phase work package is accepted in `PROJECT_PROGRESS.json`.

## Status vocabulary

- `Phase 1` — required for release `0.1.0`.
- `Phase 2` — deferred until Phase 1 acceptance; target release `0.2.0`.
- `Phase 3` — deferred until Phase 2 acceptance; target release `1.0.0`.
- `Permanent boundary` — safety/product rule that applies in every phase.

## Permanent product boundaries

| Capability | Decision |
|---|---|
| Trading 212 data access | Exact allowlisted `GET` capabilities only |
| Order placement, amendment, cancellation | Prohibited |
| Trading 212 Pie mutation/rebalancing | Prohibited |
| Deposits, withdrawals, transfers, payments | Prohibited |
| Arbitrary broker HTTP proxy | Prohibited |
| Autonomous, scheduled, or AI-directed trading | Prohibited |
| Manual contribution recommendation | Allowed from Phase 2; never executed |
| Deterministic financial calculations | Required in every phase |
| ChatGPT explanation of structured results | Allowed; never a substitute for calculation code |

## Phase 1 — Trusted Foundation

### Broker connection and ingestion

| Feature | User value | Acceptance dependency |
|---|---|---|
| Demo-first read-only Trading 212 connection | Safely connect and validate account data before Live use | P1-04, P1-05 |
| Live read-only configuration | Inspect a real Invest account with explicit configuration | P1-04, P1-08, external credential gate |
| Account/cash summary ingestion | Canonical account value and cash visibility | P1-04–P1-06 |
| Instrument and exchange metadata | Stable listing resolution beyond display ticker | P1-04, P1-05 |
| Current positions | Holdings, quantities, prices, values, provider P/L observations | P1-04–P1-07 |
| Pending/current order visibility | Observe outstanding broker orders without mutating them | P1-04, P1-05 |
| Historical order visibility | Reconstruct supported activity and investigate differences | P1-04–P1-06 |
| Transactions and cash movements | Deposits, withdrawals, buys, sells, fees, taxes, unknown activity | P1-04–P1-07 |
| Dividend history | Income and cash-flow visibility | P1-04–P1-07 |
| Full/incremental refresh | Reliable bounded data synchronization | P1-05 |
| Rate-limit, retry, pagination, and checkpoint handling | Safe operation under provider constraints and failures | P1-05 |
| Synthetic/mock provider | Complete local development and tests without private credentials | P1-01, P1-04, P1-05 |

### Canonical history and data trust

| Feature | User value | Acceptance dependency |
|---|---|---|
| Canonical broker-independent domain | Stable analytics independent of provider payload details | P1-02 |
| Exact decimal and currency model | Financial precision and reproducibility | P1-02, P1-07 |
| Immutable provenance/source metadata | Explain where each value came from | P1-03–P1-07 |
| Historical portfolio snapshots | Compare the portfolio across recorded dates | P1-06 |
| Idempotent ledger | Safe re-ingestion without duplicate economic activity | P1-03, P1-05, P1-06 |
| Position quantity reconciliation | Detect unsupported or missing position activity | P1-06 |
| Cash reconciliation | Detect cash-flow gaps and classification errors | P1-06 |
| Data-quality states | Make stale, partial, estimated, unreconciled, and failed data visible | P1-02, P1-05–P1-07 |
| Dataset coverage reporting | Show historical and mapping limitations | P1-05–P1-07 |
| Reconciliation discrepancy drill-down | Explain why a metric is limited or inconsistent | P1-06, P1-09, P1-10, P1-11 |

### Core portfolio analytics

| Feature | User value | Acceptance dependency |
|---|---|---|
| Portfolio, cash, and invested value | Trusted portfolio command-center totals | P1-06, P1-07 |
| Net deposits and withdrawals | Separate contributed capital from portfolio growth | P1-06, P1-07 |
| Dividend/income summary | Understand income received over covered history | P1-07 |
| Provider versus derived P/L distinction | Avoid mixing broker observations with reconstructed accounting | P1-07 |
| Direct holding and cash allocation | Current weights before ETF look-through | P1-07 |
| Snapshot comparison | Explain value, cash, and holding changes between recorded states | P1-07 |
| Coverage-gated MWR/TWR/Modified Dietz summary | Return analysis only when required data exists | P1-07 |
| Calculation metadata and versions | Reproduce and audit every authoritative result | P1-02, P1-07 |

### Interfaces and operations

| Feature | User value | Acceptance dependency |
|---|---|---|
| Versioned authenticated HTTP API | Stable programmatic portfolio interface | P1-08, P1-09 |
| Responsive web application foundation | Inspect the portfolio from desktop and mobile browser | P1-10 |
| Portfolio overview, positions, activity, dividends, history, quality views | Core standalone product workflow | P1-10 |
| Authenticated remote MCP server | Query the portfolio from ChatGPT | P1-11 |
| Core ChatGPT portfolio tools | Summary, snapshot, positions, activity, dividends, allocation, comparison, reconciliation, quality | P1-11 |
| Optional high-level read refresh tool | Request a bounded safe refresh from ChatGPT | P1-11; deploy-time feature flag |
| Docker/local environment | Reproducible development and deployment foundation | P1-01, P1-12 |
| CI, security checks, observability, health | Maintain a trustworthy system as it evolves | P1-01, P1-08, P1-12 |

## Phase 2 — Portfolio Intelligence

### Strategy and contribution planning

| Feature | User value | Acceptance dependency |
|---|---|---|
| Broker-independent virtual Pies | Preserve portfolio strategy independently of deprecated/native broker Pie APIs | P2-01 |
| Nested groups and immutable target versions | Model multi-Pie strategy and historical target changes | P2-01 |
| Actual-versus-target allocation | See overweights and underweights | P2-01, P2-02 |
| Multiple drift metrics | Quantify portfolio deviation at holding and group levels | P2-02 |
| Contribution-only/no-sale optimizer | Allocate new cash to reduce drift without selling | P2-02 |
| Hierarchical, global, and restricted optimization modes | Plan across all Pies or one selected scope | P2-02 |
| Minimum amount, increment, cash reserve, exclusions, maximum weights | Produce feasible manual plans | P2-02 |
| Infeasibility and binding-constraint explanation | Explain why a requested plan cannot satisfy all rules | P2-02 |

### Performance and exposure

| Feature | User value | Acceptance dependency |
|---|---|---|
| Historical market, FX, and benchmark adapters | Reliable comparative analytics | P2-03 |
| Full MWR/TWR/Modified Dietz series | Correct cash-flow-aware performance | P2-03, P2-04 |
| Benchmark comparison and rolling/calendar views | Compare against declared investable references | P2-04 |
| Performance attribution and residual | Identify contributors without hiding unexplained differences | P2-04 |
| Dividend and cash-flow intelligence | Analyze income and contribution patterns | P2-04 |
| ETF constituent snapshots | Foundation for true look-through | P2-05 |
| Direct and indirect company exposure | Reveal effective underlying holdings | P2-05 |
| ETF overlap | Detect duplicated exposure across funds | P2-05 |
| Sector, industry, country, region, and currency exposure | Portfolio-wide X-ray | P2-05 |
| Mapping confidence and unresolved exposure | Prevent false claims of complete look-through | P2-05 |

### Reports, alerts, and premium interfaces

| Feature | User value | Acceptance dependency |
|---|---|---|
| PDF reports | Reproducible monthly/quarterly/annual portfolio review | P2-06 |
| CSV, JSON, and XLSX exports | Inspect or reuse canonical data | P2-06 |
| Private report storage and expiry | Protect sensitive generated artifacts | P2-06 |
| Rules and insight feed | Detect drift, concentration, stale data, reconciliation, and material activity | P2-07 |
| Deduplicated notifications | Avoid repeated or stale alerts | P2-07 |
| Premium target, optimizer, performance, X-ray, report, and alert UI | Complete portfolio-intelligence workflow | P2-08 |
| Expanded MCP analytics tools | Use Phase 2 capabilities naturally from ChatGPT | P2-09 |

## Phase 3 — Premium Intelligence and Productization

### Risk, scenarios, projections, and goals

| Feature | User value | Acceptance dependency |
|---|---|---|
| Volatility, downside deviation, beta, covariance, correlation | Quantify historical risk characteristics | P3-01 |
| Drawdown, VaR, Expected Shortfall | Analyze historical and modeled downside | P3-01 |
| Concentration and risk contribution | Identify what drives portfolio risk | P3-01 |
| Deterministic stress scenarios | Apply explicit market/sector/currency shocks | P3-02 |
| Historical scenario replay | Compare current exposure against selected historical windows | P3-02 |
| Reproducible Monte Carlo projections | Model outcome distributions rather than one forecast | P3-03 |
| Nominal and real goal planning | Estimate target probabilities under explicit assumptions | P3-03 |
| Contribution/withdrawal sensitivity | Understand how behavior changes goal outcomes | P3-03 |

### Research and productization

| Feature | User value | Acceptance dependency |
|---|---|---|
| Portfolio-ranked research cockpit | Focus research on economically material exposures | P3-04 |
| Saved thesis, risks, catalysts, and thesis-break conditions | Maintain an auditable investment research record | P3-04 |
| Cited source and material-change history | Separate public facts, portfolio facts, and model synthesis | P3-04 |
| Rich accessible ChatGPT UI resources | Inspect charts, plans, exposures, scenarios, and goals in ChatGPT | P3-05 |
| Installable premium PWA | High-quality mobile/desktop experience independent of ChatGPT surface limits | P3-06 |
| Premium provider integrations | Improve history, reference, ETF, and research coverage | P3-07 |
| Multi-account/multi-broker readiness | Extend without rewriting the canonical financial engine | P3-08 |
| Security, performance, resilience, backup, and incident hardening | Production-quality private product | P3-09 |
| Reproducible `1.0.0` release | Complete evidence-based product acceptance | P3-10 |

## Cross-cutting output contract

Every financial or analytical feature must expose, as applicable:

- portfolio/account scope;
- valuation and source cutoff timestamps;
- reporting currency;
- calculation/method version;
- input coverage and provenance;
- data-quality state;
- assumptions and warnings;
- unresolved/residual amounts;
- explicit indication when the result is observed, derived, estimated, partial, or unavailable.

## Feature-state rule

This catalog describes intended capability. The machine-readable implementation state is `PROJECT_PROGRESS.json`. Interfaces must not expose a planned feature as production-ready before its package is accepted and enabled.
