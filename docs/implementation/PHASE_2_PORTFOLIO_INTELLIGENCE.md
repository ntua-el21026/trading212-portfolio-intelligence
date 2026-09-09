# Phase 2 — Portfolio Intelligence

**Status:** Accepted roadmap with executable v0.2 design closure; implementation in progress

**Target release:** `0.2.0`

## Objective

Turn the trusted canonical history into a differentiated portfolio intelligence product: broker-independent virtual Pies and target versions, contribution-only optimization, full historical performance and benchmarks, ETF look-through/X-ray, reports/exports, alerts, and premium analytical web/ChatGPT experiences.

## Work packages

### P2-01 — Virtual Pies and target versions

- hierarchical broker-independent portfolio definitions;
- immutable/effective target versions;
- listing/instrument mapping;
- target validation/normalization;
- constraints, cash targets, exclusions, and archived strategies;
- target editor, audit trail, API/MCP reads.

### P2-02 — Drift and contribution optimizer

- drift metrics at portfolio/group/holding level;
- contribution-only/no-sale optimization;
- hierarchical/global/restricted modes;
- minimum/increment/cash/max-weight/eligibility constraints;
- deterministic discrete rounding and residual cash;
- infeasibility/conflict explanation;
- plan persistence, API/web/MCP/report parity;
- explicit no-execution statement and no broker order translation.

### P2-03 — Market, FX, and benchmark data

- provider-neutral adapters and licensing metadata;
- historical adjusted/total-return price policy;
- benchmark definitions and reporting-currency alignment;
- immutable source snapshots, freshness, gaps, and caching;
- graceful operation without premium providers.

### P2-04 — Performance, attribution, dividends, and cash-flow intelligence

- full TWR/MWR/Modified Dietz series;
- benchmark comparison/excess/tracking metrics;
- dividend/income analysis;
- contribution/withdrawal timeline;
- position/group contribution and residual-aware attribution;
- fees/tax/FX decomposition where supported;
- rolling/calendar period views.

### P2-05 — ETF look-through and Portfolio X-ray

- ETF constituent adapters/snapshots;
- instrument/entity/share-class/ADR/listing normalization;
- direct/indirect/effective company exposure;
- ETF overlap;
- sector/industry/country/region/currency classification;
- coverage/confidence/unresolved exposure;
- concentration thresholds and explainable drill-down.

The authority for this package is [ADR-0017](../adr/ADR-0017-DECIMAL256-EXACT-XRAY.md)
and Methods section 6: `xray_v1` 1.1.0 / `xray_decimal256_exact_q18_v1`, independent
unit/money conservation, deterministic real-root representatives and retained exact
state. Pair/common projections are collection-owned and physically purge-bounded;
496 limits one request, not lifetime storage. Four GETs/two MCP reads stay fixed.
This design amendment did not begin implementation or claim test acceptance.
P2-05 subsequently received [scoped exact-source acceptance](P2_05_PORTFOLIO_XRAY.md)
at `7b102663ea193b4668924a7252180731954f4b00`; the remaining roadmap is unchanged.

### P2-06 — Reports and exports

- deterministic PDF monthly/quarterly/annual reports;
- CSV/JSON/XLSX exports;
- generation jobs/status/private storage/expiry;
- methodology/source/quality sections;
- exact parity with canonical API calculations;
- accountant-oriented activity worksheet without tax-advice claims.

### P2-07 — Alerts and rules engine

- versioned rules for drift, concentration, cash, data freshness, reconciliation, dividend/activity, and provider failure;
- scheduled evaluation, deduplication, cooldown, acknowledgment;
- in-app feed and email/webhook adapters as configured;
- no generic price-trading signal automation;
- complete audit and quality context.

### P2-08 — Premium analytical web experience

- target/Pie editor;
- contribution plan workflow;
- performance/benchmark/attribution dashboard;
- X-ray exposure explorer;
- dividend/cash-flow center;
- reports/exports/alerts center;
- accessibility, responsiveness, visual regression, saved views.

### P2-09 — Portfolio-intelligence MCP tools

Add bounded tools for:

- actual-versus-target allocation;
- drift and under/overweight analysis;
- manual contribution plan;
- performance/benchmark/dividend/attribution summaries;
- effective exposure and ETF overlap;
- report generation/status/listing;
- alert summary.

No broker write or generic research/execution tool.

### P2-10 — Hardening and acceptance

- provider failure/coverage testing;
- solver/reference validation;
- report reproducibility;
- performance/load tuning;
- data-license/security/privacy review;
- end-to-end synthetic plus configured provider evidence;
- release `0.2.0` status/changelog.

## Exit criteria

- Phase 1 remains green and migration-compatible.
- Virtual targets are versioned and broker-independent.
- Optimizer conserves contribution, obeys all constraints, explains infeasibility, and cannot execute.
- Performance separates external flows and reconciles within disclosed residual.
- X-ray exposes source date, coverage, confidence, and unresolved exposure.
- Reports, API, web, and MCP return identical authoritative values.
- Alerts deduplicate and never present stale/partial input as fresh.
- All security/accessibility/quality gates pass.
- Provider/license limitations and external gates are explicit.

## Executable authority

The owner-authorized design closure is [Design Delta v0.2](../DESIGN_FREEZE_V0_2.md).
Use the [technical baseline](PHASE_2_TECHNICAL_BASELINE.md),
[execution manifest](PHASE_2_EXECUTION_MANIFEST.md),
[acceptance matrix](PHASE_2_ACCEPTANCE_MATRIX.md), and
[scenario ledger](PHASE_2_SCENARIO_EVIDENCE.md). The roadmap remains scope;
concrete contracts and evidence determine whether a capability is implemented.
