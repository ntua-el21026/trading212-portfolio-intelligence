# API and Service Contracts

**Status:** Accepted

## 1. Principles

- `/api/v1` is the first versioned HTTP surface.
- OpenAPI is generated from typed application schemas and committed/validated as a build artifact where policy specifies.
- The web client is generated from the same contract.
- MCP tools call application services, not HTTP endpoints by string concatenation and not repositories directly.
- Financial decimals serialize as strings.
- Account ownership/authorization is enforced in application services, not only at routing middleware.
- Responses include source/cutoff timestamps and data-quality metadata.
- Collections are bounded and paginated.
- PostgreSQL-backed and deterministic synthetic services implement the same typed
  use cases and error semantics.

## 2. Common response metadata

Analytical and portfolio responses include:

```json
{
  "as_of": "2026-08-31T12:00:00Z",
  "reporting_currency": "EUR",
  "data_quality": {
    "state": "fresh",
    "evaluated_at": "2026-08-31T12:00:03Z",
    "coverage_start": null,
    "coverage_end": "2026-08-31T12:00:00Z",
    "warnings": [],
    "missing_inputs": []
  },
  "calculation": {
    "name": "portfolio_snapshot",
    "version": "1.0.0",
    "calculated_at": "2026-08-31T12:00:03Z",
    "assumptions": []
  }
}
```

Enum casing and exact schemas are fixed in implementation OpenAPI; this example is semantic.

## 3. Error envelope

```json
{
  "error": {
    "code": "DATA_UNRECONCILED",
    "message": "The requested metric is unavailable because position history does not reconcile.",
    "correlation_id": "...",
    "retryable": false,
    "details": {
      "safe_machine_readable_fields": "only"
    }
  }
}
```

No secret, raw upstream payload, SQL, stack trace, or internal path appears in client errors.

## 4. Phase 1 application use cases

Required service ports:

- `GetSystemHealth`
- `ListBrokerConnections`
- `GetBrokerAccount`
- `ListBrokerAccounts`
- `RefreshBrokerAccount`
- `GetRefreshStatus`
- `GetAccountSummary`
- `SearchInstruments`
- `ListPositions`
- `GetPosition`
- `ListTransactions`
- `ListDividends`
- `GetDividendSummary`
- `ListOrderObservations`
- `GetPortfolioSnapshot`
- `GetPortfolioSnapshotDetail`
- `ListPortfolioSnapshots`
- `ComparePortfolioSnapshots`
- `GetDirectAllocation`
- `GetCorePerformanceSummary` (coverage-gated)
- `GetReconciliationStatus`
- `ListReconciliationDiscrepancies`
- `GetDataQualitySummary`

The exact class/function naming may follow language conventions; the separation of use cases is normative.

## 5. Phase 1 HTTP resource outline

```text
GET  /health/live
GET  /health/ready
GET  /api/v1/me
GET  /api/v1/broker-connections
GET  /api/v1/accounts
GET  /api/v1/accounts/{account_id}
POST /api/v1/accounts/{account_id}/refresh
GET  /api/v1/refresh-runs/{run_id}
GET  /api/v1/accounts/{account_id}/summary
GET  /api/v1/accounts/{account_id}/positions
GET  /api/v1/accounts/{account_id}/positions/{position_id}
GET  /api/v1/accounts/{account_id}/transactions
GET  /api/v1/accounts/{account_id}/dividends
GET  /api/v1/accounts/{account_id}/orders
GET  /api/v1/accounts/{account_id}/snapshots
GET  /api/v1/accounts/{account_id}/snapshots/latest
GET  /api/v1/accounts/{account_id}/snapshots/compare
GET  /api/v1/accounts/{account_id}/snapshots/{snapshot_id}
GET  /api/v1/accounts/{account_id}/allocation
GET  /api/v1/accounts/{account_id}/performance/summary
GET  /api/v1/accounts/{account_id}/reconciliation
GET  /api/v1/accounts/{account_id}/reconciliation/discrepancies
GET  /api/v1/accounts/{account_id}/data-quality
GET  /api/v1/instruments
GET  /api/v1/instruments/{instrument_id}
```

`POST .../refresh` is an application command that causes allowlisted read ingestion. It is not a broker write. It must be authenticated, rate-limited, idempotency-aware, and cannot accept a provider endpoint/path.

`GET /api/v1/broker-connections` returns real owner-scoped connection rows:
stable ID, provider, environment, connection state, read-only posture, safe
`configured`/`not_configured` credential state, and last successful refresh when
available. Credential references and secrets are never serialized.

Instrument resources use canonical instrument identity plus listing identity.
They expose canonical instrument ID, listing ID, ticker, canonical name, type,
optional ISIN, exchange/MIC, trading currency, provider/environment, and listing
status. Search runs against metadata tables and can find unheld instruments.

## 6. Pagination and filtering

- Every page has a default limit of 50 and an inclusive maximum of 100.
- Every page reads `limit + 1` over the complete eligible result; no 10,000-row
  prefix or adapter-side collect-then-filter cap participates in page semantics.
- `Page.total` is the exact full filtered count for the traversal.
- Positions, activity, dividends, and instruments materialize a versioned,
  immutable ordered identity snapshot. Position traversal is also bound to the
  immutable portfolio snapshot used by page 1.
- Activity ordering is `(occurred_at DESC, id DESC)`; date/type filters execute in
  SQL before membership is materialized.
- Dividends use `(paid_on DESC, id DESC)` with SQL date filtering.
- Instruments use provider, environment, normalized ticker, normalized canonical
  name, and listing ID ordering over canonical metadata.
- Positions support `market_value_desc`, `weight_desc`, and `ticker_asc`, with a
  listing/position ID tie-breaker and bounded ticker/name search.
- Order observations return the latest revision per provider order at the signed
  read cutoff and paginate deterministically.
- Portfolio snapshots use `(valuation_at DESC, id DESC)`. Reconciliation
  discrepancies bind to the selected reconciliation run and read cutoff.
- Cursors are opaque, schema-versioned, HMAC-authenticated, TTL-bounded, and bound
  to resource, owner/account scope, sort, filters, immutable membership/read
  cutoff, last ordering key, and deterministic tie-breaker.
- Malformed, expired, tampered, or mismatched cursors return HTTP 400 with
  `CURSOR_INVALID`. Exhausted durable traversal capacity returns HTTP 429 with
  `COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED`; it never returns partial data as exact.
- Date filters use explicit UTC/date semantics; normalized searches are bounded to
  80 characters; arbitrary SQL/order-by fields are not accepted.

## 7. Refresh semantics

A refresh request includes only supported high-level scope, for example:

```json
{
  "scope": "all",
  "mode": "incremental",
  "create_snapshot": true
}
```

Allowed scopes are enums mapped internally to broker capabilities. The service:

1. authorizes the account;
2. canonicalizes requested semantics and locks the account;
3. rejects a reused key whose request fingerprint differs;
4. inserts the queued ingestion run and one `portfolio.refresh` outbox event in
   the same PostgreSQL transaction;
5. returns that durable run without waiting for broker publication;
6. lets the independent dispatcher claim/publish/retry the fixed task;
7. validates task run/account/request metadata against durable rows before work;
8. acquires a fenced execution lease and applies a durable global consumer
   attempt bound;
9. records partial failures per capability and never advances checkpoints for
   failed atomic units.

Publication is at least once. Dispatcher claims use `FOR UPDATE SKIP LOCKED`, a
claim timeout, bounded exponential backoff, and sanitized failure codes. Expired
claims are recoverable. The task ID is the ingestion run ID. Database uniqueness,
source fingerprints, run identity, fenced leases, and snapshot identity keep
duplicate delivery economically idempotent.

## 8. Idempotency

- Refresh commands require an application idempotency key.
- Semantic identity includes owner/account, requested mode, normalized requested
  capabilities, create-snapshot behavior, and request-schema version. It excludes
  correlation ID.
- Requested semantics are stored separately from effective execution semantics,
  so initial-sync promotion to `full`/all capabilities does not change retry
  identity.
- Ingestion uses provider IDs/fingerprints and database uniqueness.
- Snapshot creation uses a declared valuation/source cutoff key and version.
- Same account/key/semantics returns the same durable run before publication,
  during execution, and after terminal completion.
- Same account/key with different semantics returns HTTP 409
  `IDEMPOTENCY_KEY_REUSED`, publishes no event, and discloses no prior request
  details. The same textual key on another account is independent.

## 9. Authentication and authorization

Phase 1 supports a local-development mode and a production authentication adapter. Production configuration fails closed when authentication is absent.

Authorization rules:

- every account-scoped request binds owner/principal to account;
- MCP tokens/scopes are narrower than administrative web configuration privileges;
- health liveness is non-sensitive; readiness exposes no credential or provider detail;
- application services enforce ownership even when called outside HTTP.

## 10. MCP service mapping

Phase 1 exposes exactly nine coarse, discoverable, bounded, read-only tools:

- `get_account_summary`
- `get_portfolio_snapshot`
- `list_positions`
- `list_recent_transactions`
- `get_dividend_summary`
- `get_direct_allocation`
- `compare_portfolio_snapshots`
- `get_reconciliation_status`
- `get_data_quality_summary`

There is no MCP refresh tool. Each tool invokes an authorized application use case
and returns the same canonical values as HTTP. Positions and activity pass typed
search/filter/sort/cursor queries through to PostgreSQL. Dividend totals aggregate
the full covered date range while only a bounded recent sample is returned.
Snapshot ID lookup is direct and owner/account-scoped rather than a bounded scan.

## 11. Performance and quality contracts

`GetCorePerformanceSummary` selects the first and last usable canonical snapshots
and active external flows in the covered period, then invokes deterministic XIRR,
TWR, and Modified Dietz implementations. Every metric exposes method/version,
period, value, annualized value where defined, convergence/iterations, missing
inputs, assumptions, warnings, availability, and quality. It returns unavailable
when snapshot count/value, transaction checkpoint coverage, FX conversion,
activity mapping, snapshot revision, or reconciliation gates fail. Deposits and
withdrawals are external flows; buys and sells are not investment gain.

`GetDataQualitySummary` combines the latest refresh and per-step state, latest
succeeded/partial/failed runs, bounded failed/partial run IDs, capability
checkpoints, source cutoff, latest snapshot and materialization state,
reconciliation, and missing FX/mapping counts. It requires both `portfolio:read`
and `activity:read`. API and MCP call this same service.

## 12. Web contract consumption

The web application uses the generated TypeScript client and route-specific
server loaders. Holdings, activity, dividends, snapshots, and quality expose URL
cursor navigation so back/forward preserves traversal state. Overview cards are
explicit bounded previews with returned and exact total counts; the largest
holdings preview requests a descending value/weight sort. Browser code does no
authoritative financial arithmetic.

## 13. Contract testing

Required:

- OpenAPI schema validation and breaking-change check;
- generated TypeScript client compiles;
- response examples validate against schemas;
- decimal and timezone serialization tests;
- authorization tests at service and route layers;
- pagination stability tests;
- MCP tool schemas validate and reject unknown/unbounded input;
- API and MCP parity fixtures prove common calculations match;
- sanitized error envelope tests.
