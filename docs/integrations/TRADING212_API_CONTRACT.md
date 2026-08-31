# Trading 212 Read-Only API Contract

**Status:** Accepted security and integration contract  
**Owner:** `packages/trading212` and Phase 1 integration work  
**Default environment:** Demo  
**Official contract reviewed:** 2026-08-31

## 1. Boundary

Trading 212 is an untrusted external data provider. The adapter converts explicit read capabilities into strictly validated provider DTOs and then canonical domain records. No caller may supply an arbitrary HTTP method, URL, path, query-parameter name, or header.

The contract is default-deny. A request can be dispatched only when a sealed compile-time capability maps to an exact allowed `GET` path template in both this document and `config/contracts/trading212-read-allowlist.yaml`.

## 2. Supported account scope

The Public API is treated as a beta external contract. Phase 1 supports Trading 212 Invest and Stocks ISA read data where the official API and the user's account expose it. CFD APIs are excluded.

## 3. Base environments

```text
Demo: https://demo.trading212.com/api/v0
Live: https://live.trading212.com/api/v0
```

Configuration uses a closed enum. A free-form base URL is unavailable in normal operation. Tests may inject a local mock URL only through test-specific composition.

Demo is the default. Live requires explicit configuration, a dedicated read-only credential, successful local and Demo gates, and verified redaction.

## 4. Authentication

The adapter obtains an API key and secret from a server-side secret-provider interface and constructs the provider-required Basic authorization header only at dispatch time.

Requirements:

- never persist the secret in canonical/application tables;
- never return credentials to API, web, MCP, reports, exceptions, logs, traces, metrics, snapshots, or test artifacts;
- centrally redact authorization and sensitive query/header values;
- support rotation without code changes;
- fail closed when a credential reference is missing or invalid;
- production credentials must be scoped read-only and should use provider IP restrictions where operationally possible;
- fixtures use synthetic credentials only.

## 5. Phase 1 exact GET allowlist

The base URLs already include `/api/v0`; paths below are relative to that base.

| Capability | Method | Relative path template | Purpose |
|---|---|---|---|
| `account_summary` | `GET` | `/equity/account/summary` | Cash, invested/portfolio value, P/L and account summary fields exposed by the provider |
| `metadata_instruments` | `GET` | `/equity/metadata/instruments` | Listing/instrument reference data |
| `metadata_exchanges` | `GET` | `/equity/metadata/exchanges` | Exchange/reference data |
| `portfolio_positions` | `GET` | `/equity/positions` | Current open positions |
| `pending_orders` | `GET` | `/equity/orders` | Current/pending order observations |
| `order_detail` | `GET` | `/equity/orders/{order_id}` | One order observation for bounded reconciliation/detail use |
| `historical_orders` | `GET` | `/equity/history/orders` | Historical order observations |
| `historical_transactions` | `GET` | `/equity/history/transactions` | Transactions and cash movements |
| `historical_dividends` | `GET` | `/equity/history/dividends` | Dividend history |
| `historical_exports` | `GET` | `/equity/history/exports` | Existing historical export/report status and metadata only |

Only provider-documented parameters may be represented, using capability-specific typed request models. Provider IDs used in path segments are validated and encoded.

Historical export creation is intentionally not supported because it requires a mutating request. The GET capability may observe already-existing export metadata but can be disabled when unnecessary.

If official documentation removes, renames, or semantically changes an endpoint, contract tests must fail until this document, the machine allowlist, DTOs, fixtures, and exact/negative tests are deliberately updated from primary documentation. The adapter must not probe alternative paths.

## 6. Explicitly forbidden endpoint families

Irrespective of provider availability, production code must not implement or dispatch:

- any Trading 212 `POST`, `PUT`, `PATCH`, or `DELETE`;
- market, limit, stop, or stop-limit order placement;
- order cancellation or amendment;
- Pie create/update/delete/duplicate/rebalance/cash movement;
- historical export/report creation;
- account transfers, payments, withdrawals, or deposits;
- CFD endpoints;
- arbitrary URL/proxy/debug request endpoints;
- a generic public/internal `request(method, path, ...)` surface accepting caller-selected method/path;
- automatic path discovery or fallback probing.

Static/architecture tests must search for known forbidden method/path fragments. Runtime-negative tests must prove rejection occurs before the network transport is invoked.

## 7. Client structure

Recommended boundaries:

```text
Trading212Port                     canonical provider port
Trading212Client                   typed capability methods
Trading212Dispatcher               private sealed allowlist dispatch
Trading212AuthProvider             secret reference -> auth material
Trading212RateLimiter              account/environment coordination
Trading212Paginator                capability-specific pagination
Trading212DTOs                     strict Pydantic provider schemas
Trading212Mapper                   DTO -> canonical mapping
Trading212ErrorMapper              upstream -> stable sanitized categories
```

Only typed methods such as `get_positions()` exist at the adapter boundary. API, MCP, web, analytics, and domain code cannot reach transport.

## 8. Request policy

- Asynchronous `httpx` with explicit connect/read/write/pool timeouts.
- TLS verification enabled outside isolated tests.
- Redirects disabled unless a current official contract explicitly requires them.
- User-Agent identifies application/version without account data.
- Response sizes, page counts, record counts, and elapsed time are bounded.
- Query parameters are constructed from typed, capability-specific models and allowlisted names.
- Request/response bodies and headers are excluded or sanitized in telemetry.
- Transport receives an immutable resolved request produced by the sealed registry.

## 9. Retry policy

Automatically retry only safe reads for:

- transient connection failures;
- bounded timeouts;
- explicit rate-limit responses;
- selected transient 5xx responses.

Do not retry:

- authentication or authorization failures;
- schema incompatibility;
- invalid configuration;
- non-rate-limit 4xx responses;
- repeated-page/pagination inconsistency;
- any condition after total attempt/time budget exhaustion.

Use exponential backoff with jitter, honor trustworthy provider reset/retry headers, coordinate by account/environment, and record sanitized attempt metadata.

## 10. Rate limits

Trading 212 rate limits are treated as per-account/provider constraints. Record documented limit/remaining/reset headers when present. Missing headers invoke a conservative configured budget. Explicit user refreshes are bounded; backfills are lower priority. No uncontrolled parallel fan-out is permitted.

## 11. Pagination and checkpoints

Each paginated capability has a dedicated paginator with:

- typed request and response models;
- stable cursor/checkpoint extraction;
- maximum pages, records, and elapsed time;
- repeated-page and loop detection;
- safe overlap for incremental history;
- deduplication by provider identity or deterministic fingerprint;
- checkpoint advancement only after durable atomic commit;
- persisted coverage, truncation, and warning metadata.

Never assume identical pagination fields or semantics across capabilities. Verify each from the current official OpenAPI.

## 12. Schema validation and drift

- Required semantic fields are strict.
- Unknown additive fields may be retained or ignored without changing semantics.
- Invalid decimals, currencies, identifiers, or timestamps fail the affected atomic unit.
- Null/missing is never silently converted to zero.
- Schema incompatibility produces `PROVIDER_SCHEMA_INCOMPATIBLE`, preserves sanitized evidence under retention policy, and does not advance the checkpoint.
- A capability failure may yield a partial aggregate state only when the domain can preserve the successfully verified capabilities without misrepresentation.

## 13. Stable error mapping

Provider failures map to sanitized categories:

- `PROVIDER_AUTHENTICATION_FAILED`
- `PROVIDER_AUTHORIZATION_FAILED`
- `PROVIDER_RATE_LIMITED`
- `PROVIDER_TIMEOUT`
- `PROVIDER_UNAVAILABLE`
- `PROVIDER_INVALID_REQUEST`
- `PROVIDER_SCHEMA_INCOMPATIBLE`
- `PROVIDER_PAGINATION_INCONSISTENT`

Raw provider error bodies, secrets, stack traces, and private identifiers are not returned to clients.

## 14. Required tests

### Static and architecture

- Exact capability count and method/path templates match the machine allowlist.
- Every capability method is `GET`.
- No public generic request method exists.
- Forbidden order/Pie/export-creation/transfer/CFD fragments are absent from production dispatch code.
- Domain/analytics/application interfaces do not import provider transport.

### Unit and contract

- Authorization construction and complete redaction.
- Demo/Live base environment selection.
- Exact method/path/query generation for every capability.
- Strict path-parameter validation.
- Unknown capability/path/method/parameter rejection before transport.
- Timeout, retry, rate-limit, and error policy.
- Pagination, loop detection, overlap, deduplication, and checkpoints.
- Strict DTO validation and canonical mapping.

### Integration and security

- Mock transport full and incremental reads.
- Synthetic/sanitized recorded fixtures.
- A test transport that fails on every non-GET or non-allowlisted request.
- Crash/restart/idempotency behavior.
- Partial capability and schema-drift behavior.
- Demo smoke tests behind explicit credential and marker gates.

## 15. Live environment gate

Live read-only connectivity may be enabled only after:

1. local exact/negative/security tests pass;
2. Demo contract smoke succeeds with a dedicated read-only key;
3. the user supplies a separate Live read-only key through secret storage;
4. configuration explicitly selects `live`;
5. logs/traces are verified redacted;
6. a minimal bounded smoke succeeds without broad backfill;
7. the connection can be revoked independently.

No Demo or Live credential is required to complete locally resolvable Phase 1 implementation. Those are external verification gates and must not be fabricated.
