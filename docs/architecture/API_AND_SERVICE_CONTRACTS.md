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
- `RefreshBrokerAccount`
- `GetRefreshStatus`
- `GetAccountSummary`
- `SearchInstruments`
- `ListPositions`
- `GetPosition`
- `ListTransactions`
- `ListDividends`
- `ListOrderObservations`
- `GetPortfolioSnapshot`
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
GET  /api/v1/accounts/{account_id}/allocation
GET  /api/v1/accounts/{account_id}/performance/summary
GET  /api/v1/accounts/{account_id}/reconciliation
GET  /api/v1/accounts/{account_id}/reconciliation/discrepancies
GET  /api/v1/accounts/{account_id}/data-quality
GET  /api/v1/instruments
GET  /api/v1/instruments/{instrument_id}
```

`POST .../refresh` is an application command that causes allowlisted read ingestion. It is not a broker write. It must be authenticated, rate-limited, idempotency-aware, and cannot accept a provider endpoint/path.

## 6. Pagination and filtering

- Cursor pagination is preferred for mutable/large activity collections.
- Default and maximum page sizes are explicit.
- Stable order includes a deterministic tie-breaker.
- Date filters use explicit UTC/date semantics.
- Search inputs are length-bounded and normalized.
- Arbitrary SQL/order-by fields are not accepted.
- API responses state when provider/source history may be incomplete.

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
2. deduplicates/coalesces concurrent refreshes;
3. acquires a lease;
4. schedules/executes safe read jobs;
5. returns a run ID and state;
6. records partial failures per capability;
7. never advances checkpoints for failed atomic units.

## 8. Idempotency

- Refresh commands accept an optional application idempotency key.
- Ingestion uses provider IDs/fingerprints and database uniqueness.
- Snapshot creation uses a declared valuation/source cutoff key and version.
- Repeated identical requests may return the existing run/result.

## 9. Authentication and authorization

Phase 1 supports a local-development mode and a production authentication adapter. Production configuration fails closed when authentication is absent.

Authorization rules:

- every account-scoped request binds owner/principal to account;
- MCP tokens/scopes are narrower than administrative web configuration privileges;
- health liveness is non-sensitive; readiness exposes no credential or provider detail;
- application services enforce ownership even when called outside HTTP.

## 10. MCP service mapping

Phase 1 tools should be coarse, discoverable, and bounded:

- `get_account_summary`
- `get_portfolio_snapshot`
- `list_positions`
- `list_recent_transactions`
- `get_dividend_summary`
- `get_direct_allocation`
- `compare_portfolio_snapshots`
- `get_reconciliation_status`
- `get_data_quality_summary`
- `refresh_portfolio_data` only if the deployment policy enables an authenticated read-refresh command

Each tool invokes an application use case and returns the same canonical values as HTTP. A refresh tool is not a broker mutation and may be omitted/disabled by configuration.

## 11. Contract testing

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
