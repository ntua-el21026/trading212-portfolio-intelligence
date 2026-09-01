# Data Quality and Reconciliation

**Status:** Accepted normative contract

## 1. Objective

Prevent stale, incomplete, inconsistent, inferred, or failed data from being presented with false precision. Reconciliation and quality state are product features, not internal diagnostics.

## 2. Quality states

### `FRESH`

All material inputs are within the configured freshness threshold, schema-valid, and reconciled to the required tolerance/coverage.

### `STALE`

Inputs remain structurally valid but are older than the accepted threshold. Calculations may be shown with timestamp and warning when the use case permits.

### `PARTIAL`

One or more expected material datasets/fields are absent or coverage is truncated. The result identifies missing inputs and excludes unsupported components from specific submetrics without excluding their known value from totals.

### `ESTIMATED`

A documented approximation, inferred mapping, interpolated rate, or fallback method contributes materially. The exact assumption and affected fields are listed.

### `UNRECONCILED`

Independent authoritative/derived views disagree beyond the active tolerance, or unsupported activity prevents a trustworthy ledger-to-position/cash bridge.

### `FAILED`

The source or calculation could not be produced safely.

## 3. Dataset quality

Quality is evaluated separately for:

- account summary/cash;
- instruments/exchanges;
- positions;
- current orders;
- historical orders;
- transactions/cash flows;
- dividends;
- FX/reference rates;
- canonical ledger;
- reconciliation;
- portfolio snapshots;
- each calculation and canonical response;

An aggregate portfolio state reports the most material limitations, not a simplistic maximum severity without context.

## 4. Freshness

Freshness uses source cutoff, not only ingestion/calculation time. Thresholds are configurable by dataset and environment and recorded in the evaluation.

Example defaults may be established during implementation, but the API/UI always display actual source timestamps. A recent calculation over old inputs is stale.

## 5. Coverage

Historical datasets record:

- earliest known covered date;
- latest source date/cursor;
- whether provider history is believed complete;
- known pagination/backfill truncation;
- gaps and unsupported activity types;
- mapping coverage by value/count.

Collection `total` is an exact full filtered count. A page boundary or MCP output
bound is not a coverage gap. If a defensive aggregate group bound is reached, the
result records explicit truncation/omission counts, includes the missing input,
and is at least `PARTIAL`; a warning attached to `FRESH` is not sufficient.

Core performance is available only when at least two usable snapshot values,
complete transaction checkpoint coverage, active and unambiguous external-flow
classification, reporting-currency/FX coverage, unique valuation-revision
selection, and current reconciliation gates are satisfied. Otherwise XIRR, TWR,
and Modified Dietz expose explicit unavailable/missing-input state. Deposits and
withdrawals are external flows; buys and sells are internal exchanges and are not
investment gain.

## 6. Reconciliation layers

### 6.1 Source-level deduplication

Verify provider IDs/fingerprints do not create duplicate canonical activity.

### 6.2 Position quantity bridge

For supported activity and a coverage interval:

```text
opening quantity
+ buys/transfers in/corporate additions
- sells/transfers out/corporate removals
= expected closing quantity
```

Compare against current provider position observation by listing/instrument with explicit tolerance.

### 6.3 Cash bridge

```text
opening cash
+ deposits
- withdrawals
- buy cash outflow
+ sell cash inflow
+ dividends/interest
- fees/taxes
± supported adjustments/FX cash effects
= expected closing cash
```

Currency ledgers are reconciled before reporting-currency aggregation where source data permits.

### 6.4 Portfolio value bridge

Compare canonical sum of cash and positions with provider/account summary fields while preserving differences in valuation timing/method. Timing differences may be categorized but not erased.

### 6.5 P/L/component bridge

Where sufficient data exists, compare change in value, external flows, and derived investment result. Report residual.

## 7. Discrepancy model

Each discrepancy contains:

- stable type and severity;
- account/instrument/currency scope;
- observed and expected values;
- residual and tolerance;
- coverage period;
- source/provenance IDs;
- likely cause category;
- first/last seen;
- resolution state and notes;
- effect on downstream metrics.

Types include duplicate/missing activity, quantity mismatch, cash mismatch, unmapped instrument, unsupported corporate action, settlement timing, FX gap, provider-history gap, and schema/mapping change.

## 8. Tolerance policy

- Exact source identity/deduplication has zero tolerance.
- Quantity tolerance depends on source precision and declared scale.
- Currency tolerance uses exact internal values and a small explicit comparison tolerance only for provider-displayed/rounded totals.
- Percentage/value tolerance cannot be used to hide systematic discrepancy.
- Tolerance version is stored with every reconciliation run.

## 9. Propagation and gating

Examples:

- stale positions: current valuation marked stale; historical cash-flow listing may remain usable;
- missing dividends: total value available, income/return decomposition partial;
- quantity mismatch: affected position and portfolio accounting unreconciled; direct observed allocation may still be displayed as provider-observed with warning;
- missing FX: local-currency rows available; reporting-currency aggregate partial/failed;
- unmapped instrument: known value remains visible as unclassified and affected
  calculations are partial;
- failed reconciliation: coverage-gated performance is unavailable or
  unreconciled.

Each calculation defines its gate and quality propagation.

## 10. User experience

Every portfolio surface provides:

- last successful refresh/source cutoff;
- aggregate state;
- concise material warning;
- drill-down by dataset;
- failed/partial run details in safe language;
- unresolved discrepancy count and impact;
- refresh/status action where authorized;
- no green/success presentation for unreconciled data.

## 11. Application summary contract

`GetDataQualitySummary` is the canonical source for the HTTP and MCP quality
surfaces. It requires both `portfolio:read` and `activity:read` and combines:

- the latest ingestion run with capability-step status;
- latest succeeded, partial, and failed run records;
- up to 20 most recent failed/partial/cancelled run IDs;
- checkpoint version, coverage interval, and completeness per capability;
- source cutoff, latest canonical snapshot, and materialization state;
- latest reconciliation state;
- active foreign external flows and unresolved FX-gap counts;
- unknown/unsupported transaction-mapping counts;
- per-capability and aggregate freshness/quality/missing-input state.

No adapter fabricates an empty failed-run list because it lacks a query. The
deterministic synthetic service implements the same typed contract.

Reconciliation summary and discrepancy listing are separate. The summary reports
the exact discrepancy count from the selected run without pretending an embedded
prefix is complete. Discrepancies use a signed read-cutoff keyset ordered by
`(last_seen_at DESC, id DESC)`, bound to account and reconciliation run, with an
exact filtered total.

Dividend summary aggregation is also coverage-aware: SQL aggregates all records
in the selected date period by currency, while only a bounded recent-row sample is
returned. Missing gross/withholding components or omitted currency groups make the
summary `PARTIAL` and identify the missing inputs.

## 12. Acceptance tests

- missing is distinct from zero;
- freshness uses source timestamp;
- duplicate records do not change ledger totals;
- partial endpoint failure degrades only dependent metrics appropriately;
- quantity/cash residual detection around tolerance boundaries;
- unsupported activity persists and blocks relevant accounting;
- unmapped value remains in totals;
- quality metadata parity across API/MCP/web;
- real latest/failed/partial run state appears identically in API and MCP;
- performance available, incomplete-history, missing-FX, reconciliation-failure,
  and non-convergent/invalid XIRR fixtures fail or pass their exact gates;
- discrepancy and dividend totals cover the full filtered set rather than a page
  prefix;
- reconciliation rerun is deterministic and does not erase history;
- resolution audit trail is immutable/attributable.
