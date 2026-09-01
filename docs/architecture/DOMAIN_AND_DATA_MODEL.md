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
- credential_reference (nullable opaque server-side reference)
- status
- created_at / updated_at
```

Secrets are not stored in domain records. `NULL` means `not_configured`;
application views expose only that safe credential state, never the reference.
Connection queries are owner-scoped and include the last successful refresh when
one exists.

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
- environment
- provider_instrument_id
- ticker
- exchange_mic / exchange_id
- trading_currency
- status
- valid_from / valid_to
```

A listing, not a ticker, is the normal position reference. Multiple listings may
map to one canonical instrument. Phase 1 instrument search reads the canonical
instrument/listing tables independently of current positions, so an authorized
provider/environment listing can be returned even when it is not held.

## 4. Provider provenance

### Ingestion run

```text
IngestionRun
- id
- broker_account_id
- capability
- mode (`full` | `incremental`) -- effective execution mode
- request_schema_version (`1`)
- requested_mode (`full` | `incremental`)
- requested_capabilities[]
- requested_create_snapshot
- effective_capabilities[]
- request_fingerprint (SHA-256 canonical semantic identity)
- idempotency_key (unique within the broker account)
- started_at / completed_at
- status
- request_count
- records_received / normalized / rejected
- checkpoint_before / checkpoint_after
- rate_limit observations
- warning/error summaries
- correlation_id
```

Requested semantics remain immutable even when an initial incremental/current
request is promoted to a full/all execution. The fingerprint binds owner,
account, requested mode, normalized capability order, create-snapshot behavior,
and request-schema version. It deliberately excludes the correlation ID.

### Refresh dispatch outbox

```text
RefreshDispatchOutbox
- id
- ingestion_run_id (unique)
- task_name (`portfolio.refresh` only)
- task_version (`1`)
- payload {run_id, account_id, request_fingerprint, request_schema_version}
- status (`pending` | `publishing` | `published` | `dead`)
- attempt_count / consecutive_failure_count
- consumer_attempt_count (durably bounded to 0..4)
- available_at
- claim_token / claim_owner / claimed_at / claim_expires_at
- published_at
- last_error_code (sanitized)
- created_at / updated_at
```

The ingestion run and one bounded, non-secret outbox event are inserted in the
same transaction. Dispatcher heartbeats separately record bounded identity,
start/heartbeat/last-success timestamps, `healthy` or `degraded` state, and a
sanitized error code. Neither record accepts arbitrary task names or broker
payloads.

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
- FX conversion used for reporting-currency calculations;
- active revision state; a reversed source transaction deactivates its economic
  cash flow rather than leaving it in performance inputs.

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

## 10. Immutable collection traversal

Mutable collection traversal uses one of two persisted/query-bound forms:

```text
CollectionQuerySnapshot
- id / schema_version (`1`)
- resource and deterministic sort specification
- owner_id / optional broker_account_id
- source_snapshot_id for positions
- filter_fingerprint
- exact_total
- created_at / expires_at

CollectionQuerySnapshotMember
- snapshot_id
- ordinal
- record_id
```

Positions, activity, dividends, and instruments materialize the complete ordered
eligible identity set and then read `limit + 1` members. Positions additionally
bind to one immutable portfolio snapshot. Orders, portfolio snapshots, and
reconciliation discrepancies instead bind a signed keyset to a database read
cutoff and deterministic last key. New or backfilled rows cannot change an active
traversal.

Cursor payloads are versioned and HMAC-authenticated. Their binding covers
resource, authorized owner/account scope, deterministic sort, filter fingerprint,
read cutoff or immutable result snapshot, last ordering key, and tie-breaker.
Malformed, expired, tampered, or cross-binding cursors are invalid.

Active materialized traversal state is bounded per owner (defaults: 64 snapshots
and 250,000 members), expires after the configured cursor TTL, and is cleaned in
bounded non-blocking batches. Capacity exhaustion is explicit; it does not return
a silently truncated result.

## 11. Persistence constraints

At minimum, Phase 1 enforces:

- unique provider account identity;
- unique provider record identity/fingerprint per account/capability;
- unique listing identity within provider/environment;
- non-null currency for money;
- UTC timestamps;
- account-scoped idempotency keys plus canonical request fingerprints;
- one outbox event per ingestion run and a fixed task/payload contract;
- bounded durable publication and consumer attempt counters;
- fenced ingestion leases and expiring dispatcher claims;
- foreign-key ownership boundaries;
- immutable completed ingestion-run metadata except appended resolution/audit fields;
- numeric precision appropriate for fractional shares, FX, prices, and money;
- no secrets in tables designed for domain data;
- immutable collection snapshot membership, exact totals, ownership, expiry, and
  source-snapshot constraints.

The Phase 1 Alembic head is `20260901_0007`. The correction sequence is:

- `20260901_0004`: semantic refresh identity, fenced leases, transactional
  refresh-dispatch outbox, and dispatcher heartbeat;
- `20260901_0005`: nullable broker credential reference for explicit
  `not_configured` state;
- `20260901_0006`: immutable collection-query snapshots and members;
- `20260901_0007`: active external-cash-flow revisions.

## 12. API serialization

- UUIDs as canonical strings.
- decimals as strings in authoritative financial fields, with generated clients providing decimal-safe parsing;
- timestamps as RFC 3339 UTC;
- enums as stable lowercase strings unless schema specifies otherwise;
- nullable/unknown distinguished from zero and empty collection;
- pagination envelopes include an opaque cursor, bounded limit, and exact full
  filtered `total`;
- every analytical result includes `calculation` and `data_quality` blocks.
