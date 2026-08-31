# Domain and Data Model

**Status:** Accepted

## 1. Modeling principles

- Canonical domain names are independent of Trading 212 payload names.
- Provider identifiers are retained, but never treated as universal identifiers.
- Every monetary amount has an explicit currency.
- Every observation has an effective/source timestamp and ingestion provenance.
- Derived values carry method/version/quality metadata.
- Missing, zero, and unknown are distinct.
- Persisted authoritative values use exact decimal/numeric types.
- User-visible tickers are labels, not primary keys.

## 2. Core value objects

### Money

```text
Money(amount: Decimal, currency: CurrencyCode)
```

Rules:

- finite decimal only;
- currency required;
- addition/subtraction require same currency unless an explicit FX conversion is supplied;
- rounding occurs only at declared boundaries using documented policy;
- serialization uses decimal strings, never JSON binary floats for authoritative values.

### Quantity and Price

```text
Quantity(value: Decimal)
Price(value: Decimal, quote_currency: CurrencyCode)
```

Fractional quantities are supported. Scale limits are validated but source precision is not prematurely rounded.

### FX rate

```text
FxRate(base_currency, quote_currency, rate: Decimal, observed_at, source)
```

The direction is explicit. Conversion records the exact rate, source, and timestamp used.

### Percentage/Ratio

Internal ratios use `Decimal`. API serialization defines whether a field is a fraction (`0.125`) or percentage points (`12.5`) in its schema and naming; ambiguity is prohibited.

### Time

- `Instant`: timezone-aware UTC.
- `LocalDate`: date without time where the economic event is date-based.
- `TimeRange`: inclusive/exclusive semantics documented per use case.
- Original provider timezone/offset metadata may be retained for audit.

## 3. Identity model

### Owner

Represents an application principal/user boundary.

### Broker connection

```text
BrokerConnection
- id (UUID)
- owner_id
- provider (`trading212`)
- environment (`demo` | `live`)
- credential_reference (opaque server-side reference)
- status
- created_at / updated_at
```

Secrets are not stored in domain records.

### Broker account

```text
BrokerAccount
- id (UUID)
- connection_id
- provider_account_id
- account_type
- base_currency
- display_name
- status
- first_seen_at / last_seen_at
```

Uniqueness is scoped to provider/environment/connection.

### Instrument and listing

```text
Instrument
- id
- canonical_name
- instrument_type
- isin (nullable)
- issuer/parent mapping fields (later)

Listing
- id
- instrument_id
- provider
- provider_instrument_id
- ticker
- exchange_mic / exchange_id
- trading_currency
- status
- valid_from / valid_to
```

A listing, not a ticker, is the normal position reference. Multiple listings may map to one instrument.

## 4. Provider provenance

### Ingestion run

```text
IngestionRun
- id
- broker_account_id
- capability
- mode (`full` | `incremental` | `refresh`)
- started_at / completed_at
- status
- request_count
- records_received / normalized / rejected
- checkpoint_before / checkpoint_after
- rate_limit observations
- warning/error summaries
- correlation_id
```

### Source record

Stores or references the normalized-safe source representation:

```text
SourceRecord
- id
- ingestion_run_id
- provider
- capability
- provider_record_type
- provider_record_id (nullable)
- payload_fingerprint
- source_updated_at (nullable)
- observed_at
- schema_version
- sanitized_payload or object reference (policy-controlled)
```

Unique keys prevent duplicate processing.

### Provenance reference

Canonical records include references to one or more source records and mapping version.

## 5. Financial activity

### Transaction

Canonical transaction taxonomy is explicit and extensible:

- buy;
- sell;
- deposit;
- withdrawal;
- dividend;
- fee;
- tax/withholding;
- interest;
- transfer;
- corporate action;
- adjustment;
- unknown provider activity.

Unknown activity is retained and flagged; it is not silently coerced.

Core fields:

```text
Transaction
- id
- broker_account_id
- provider_transaction_id
- type
- status
- instrument_listing_id (nullable)
- quantity (nullable)
- unit_price (nullable)
- gross_amount (nullable)
- fees (nullable)
- taxes (nullable)
- net_cash_amount
- currency
- occurred_at
- settlement_date (nullable)
- source/provenance
```

Sign conventions are centrally defined in the financial calculation policy.

### Dividend

A dividend observation may be represented as both a specialized record and a canonical cash-flow/transaction link, preserving provider fields such as instrument, gross/net amount, withholding, currency, ex/pay dates where available.

### Order observation

Orders are read-only observations:

```text
OrderObservation
- id
- broker_account_id
- provider_order_id
- instrument_listing_id
- side
- order_type
- requested_quantity/value fields when present
- filled_quantity/value fields
- status
- submitted_at / updated_at / completed_at
- source/provenance
```

No order command aggregate or mutation method exists.

## 6. Positions and valuations

### Current position observation

Provider current position data is stored as an observation with source timestamp and normalized fields.

### Canonical position

A canonical position is derived for an account/listing/valuation timestamp:

```text
Position
- broker_account_id
- listing_id
- quantity
- average/acquisition fields with method and coverage
- current_price
- market_value
- unrealized_pnl
- valuation_currency
- valuation_at
- quality
- provenance
```

The system distinguishes provider-reported values from internally calculated values.

### Portfolio snapshot

```text
PortfolioSnapshot
- id
- broker_account_id
- valuation_at
- reporting_currency
- cash totals
- invested/position totals
- portfolio total
- net contribution coverage
- calculation_version
- quality
- warnings
- source_cutoff_at
```

Snapshot positions and component values are immutable for the snapshot version. Recalculation creates a new calculation/version record rather than silently changing history.

## 7. Cash-flow ledger

Normalized external cash flows form a ledger used for performance and reconciliation. Each entry defines:

- economic date/time;
- direction/sign;
- amount/currency;
- external versus internal portfolio flow classification;
- link to source transaction/dividend/order where applicable;
- confidence/quality;
- FX conversion used for reporting-currency calculations.

Deposits and withdrawals are external flows. Buys/sells are normally internal exchanges between cash and securities and must not be counted as contributions.

## 8. Reconciliation

### Reconciliation run

```text
ReconciliationRun
- id
- broker_account_id
- as_of
- algorithm_version
- status
- coverage_start/end
- tolerance policy
- residual counts/amounts
- warnings
```

### Reconciliation discrepancy

Types include:

- quantity mismatch;
- cash mismatch;
- missing source activity;
- duplicate source activity;
- unmapped instrument;
- unsupported corporate action;
- currency/FX gap;
- timing/settlement difference;
- provider history coverage gap.

Discrepancies remain first-class records until resolved/accepted with reason.

## 9. Data quality and calculation metadata

```text
DataQuality
- state (`FRESH`, `STALE`, `PARTIAL`, `ESTIMATED`, `UNRECONCILED`, `FAILED`)
- evaluated_at
- freshness_threshold
- coverage_start/end
- warnings[]
- missing_inputs[]

CalculationMetadata
- calculation_name
- version
- run_id
- calculated_at
- valuation_at
- reporting_currency
- input_snapshot/source IDs
- assumptions
- data_quality
```

## 10. Phase 2 domain extensions

- `PortfolioDefinition`
- `PortfolioGroup` / virtual Pie
- `TargetVersion`
- `TargetAllocation`
- `AllocationConstraint`
- `DriftResult`
- `ContributionPlan` and line items
- `BenchmarkDefinition`
- `PerformanceSeries`
- `AttributionResult`
- `ETFConstituentSnapshot`
- `ExposureMapping` with confidence
- `Report`, `Export`, `AlertRule`, `AlertEvent`

These are not Phase 1 functional requirements, though migration namespaces/interfaces may be reserved without creating behavior.

## 11. Phase 3 domain extensions

- `RiskModelRun`
- `ScenarioDefinition` / `ScenarioRun`
- `ProjectionAssumptionSet` / `ProjectionRun`
- `Goal`
- `ResearchEntity`, `ResearchNote`, `InvestmentThesis`, `ThesisCondition`, and `SourceCitation`

## 12. Persistence constraints

At minimum, Phase 1 enforces:

- unique provider account identity;
- unique provider record identity/fingerprint per account/capability;
- unique listing identity within provider/environment;
- non-null currency for money;
- UTC timestamps;
- idempotency keys/checkpoints;
- foreign-key ownership boundaries;
- immutable completed ingestion-run metadata except appended resolution/audit fields;
- numeric precision appropriate for fractional shares, FX, prices, and money;
- no secrets in tables designed for domain data.

## 13. API serialization

- UUIDs as canonical strings.
- decimals as strings in authoritative financial fields, with generated clients providing decimal-safe parsing;
- timestamps as RFC 3339 UTC;
- enums as stable lowercase strings unless schema specifies otherwise;
- nullable/unknown distinguished from zero and empty collection;
- pagination envelopes include cursor and bounded page metadata;
- every analytical result includes `calculation` and `data_quality` blocks.
