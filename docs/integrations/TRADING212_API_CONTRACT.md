# Trading 212 Read-Only API Contract

**Status:** Accepted security and integration contract  
**Owner:** `packages/trading212` and Phase 1 integration work  
**Default environment:** Demo

## 1. Boundary

Trading 212 is an untrusted external data provider. The adapter converts explicit read capabilities into validated provider DTOs and then canonical domain records. No caller may supply an arbitrary HTTP method, URL, path, query parameter name, or header.

The contract is default-deny. A request can be dispatched only when its compile-time capability maps to an exact allowed method/path template.

## 2. Base environments

```text
Demo: https://demo.trading212.com/api/v0
Live: https://live.trading212.com/api/v0
```

Configuration uses an enum, not a free-form base URL in normal operation. Test doubles may inject a local URL only through test-specific composition.

## 3. Authentication

The adapter obtains an API key and secret from a server-side secret-provider interface and constructs the provider-required authorization header at dispatch time.

Requirements:

- never persist the secret in domain/application tables;
- never return credentials to API, web, MCP, reports, exceptions, logs, traces, metrics, or test snapshots;
- redact authorization and sensitive query/header values centrally;
- support rotation without code changes;
- fail closed when a credential reference is absent or invalid;
- production credentials must be read-only scoped and should use provider IP restrictions where operationally possible;
- fixtures use synthetic credentials only.

## 4. Phase 1 allowlisted capabilities

Implementation must verify these templates against the current official Trading 212 OpenAPI/documentation while building P1-04 and update this contract in the same commit if an official beta change requires a non-semantic correction. No additional capability is allowed without documentation and security review.

| Capability | Method | Relative path template | Pagination/parameters | Purpose |
|---|---|---|---|---|
| `account_info` | `GET` | `/equity/account/info` | none | Account identity/type/base details |
| `account_cash` | `GET` | `/equity/account/cash` | none | Cash/account value summary |
| `metadata_instruments` | `GET` | `/equity/metadata/instruments` | documented provider parameters only | Listing/instrument reference data |
| `metadata_exchanges` | `GET` | `/equity/metadata/exchanges` | documented provider parameters only | Exchange/reference data |
| `portfolio_positions` | `GET` | `/equity/portfolio` | documented provider parameters only | Current positions |
| `pending_orders` | `GET` | `/equity/orders` | documented provider parameters only | Current/pending order observations |
| `order_detail` | `GET` | `/equity/orders/{order_id}` | strict provider ID validation | One order observation when required for reconciliation |
| `historical_orders` | `GET` | `/equity/history/orders` | explicit cursor/time/status fields only | Historical order observations |
| `historical_transactions` | `GET` | `/equity/history/transactions` | explicit cursor/time/type fields only | Transactions and cash movements |
| `historical_dividends` | `GET` | `/equity/history/dividends` | explicit cursor/time fields only | Dividend history |

If current official documentation removes or renames an endpoint, the adapter must fail contract verification until this table and fixtures are deliberately updated. It must not probe alternate paths automatically.

## 5. Explicitly forbidden endpoint families

Irrespective of provider availability, the production adapter must not implement or dispatch:

- any `POST`, `PUT`, `PATCH`, or `DELETE` broker request;
- market, limit, stop, or stop-limit order endpoints;
- order cancellation/amendment;
- Pie create/update/delete/duplicate/rebalance/cash movement;
- history export creation if it requires a mutating request;
- account transfer/payment endpoints;
- CFD endpoints;
- arbitrary URL/proxy/debug request endpoints;
- a generic `request(method, path, ...)` method exposed outside a private dispatcher that accepts only a sealed capability object.

Static/architecture tests must search for known forbidden path fragments and methods, and runtime negative tests must prove rejection occurs before network transport invocation.

## 6. Client structure

Recommended structure:

```text
Trading212Port                     canonical provider port
Trading212Client                   typed capability methods
Trading212Dispatcher               private sealed allowlist dispatch
Trading212AuthProvider             secret reference → auth material
Trading212RateLimiter              account/environment coordination
Trading212Paginator                capability-specific pagination
Trading212DTOs                     strict Pydantic provider schemas
Trading212Mapper                   DTO → canonical mapping
Trading212ErrorMapper              upstream → stable sanitized categories
```

Only typed methods such as `get_positions()` exist at the public adapter level. The transport cannot be reached by API/MCP/web code.

## 7. Request policy

- Asynchronous `httpx` client with explicit connect/read/write/pool timeouts.
- TLS verification always enabled outside isolated tests.
- Redirects disabled unless an official endpoint requires and documents them.
- User-Agent identifies application/version without account data.
- Bounded response size where feasible.
- Query parameters constructed from typed models and allowlisted names.
- Provider IDs/path segments encoded and validated.
- Request/response bodies and headers excluded or sanitized in telemetry.

## 8. Retry policy

Automatically retry only safe reads for:

- transient connection failures;
- timeouts under bounded policy;
- explicit rate-limit response;
- selected transient 5xx responses.

Do not retry:

- authentication/authorization failures;
- schema incompatibility;
- invalid configuration;
- non-rate-limit 4xx responses;
- any condition after the total retry/time budget is exhausted.

Use exponential backoff with jitter, honor trustworthy reset/retry headers, and record sanitized attempt metadata.

## 9. Rate limits

Rate coordination is scoped at least by provider environment and broker account. The adapter records available limit/remaining/reset headers without assuming they always exist. Missing headers invoke a conservative configured budget. Background backfills are lower priority than explicit bounded refreshes.

No uncontrolled parallel fan-out is permitted.

## 10. Pagination

Each paginated capability has a dedicated paginator with:

- typed request and response models;
- stable cursor/checkpoint extraction;
- maximum pages/records/elapsed time;
- repeated-page/loop detection;
- safe overlap for incremental history;
- deduplication by provider ID/fingerprint;
- checkpoint advancement only after durable commit;
- persisted coverage and truncation warnings.

## 11. Schema validation and drift

- Required semantic fields are strict.
- Unknown additive fields may be retained/ignored according to DTO configuration without changing semantics.
- Invalid decimals, currencies, identifiers, or timestamps fail the affected atomic unit.
- No conversion from null/missing to zero.
- Schema incompatibility produces `PROVIDER_SCHEMA_INCOMPATIBLE`, preserves sanitized evidence according to retention policy, and does not advance the checkpoint.

## 12. Error mapping

Provider failures map to stable categories:

- `PROVIDER_AUTHENTICATION_FAILED`
- `PROVIDER_AUTHORIZATION_FAILED`
- `PROVIDER_RATE_LIMITED`
- `PROVIDER_TIMEOUT`
- `PROVIDER_UNAVAILABLE`
- `PROVIDER_INVALID_REQUEST`
- `PROVIDER_SCHEMA_INCOMPATIBLE`
- `PROVIDER_PAGINATION_INCONSISTENT`

External error text is never returned unsanitized.

## 13. Required tests

### Static/architecture

- No public generic request method.
- Only `GET` appears in capability registry.
- Exact capability count and path templates match this contract.
- Forbidden order/Pie/export mutation fragments absent from production adapter.
- Domain/analytics modules do not import provider transport.

### Unit/contract

- Authorization construction and complete redaction.
- Correct base environment selection.
- Exact method/path/query generation for every capability.
- Unknown capability/path/parameter rejection before transport.
- Timeout/retry/rate-limit policy.
- Pagination, loop detection, overlap, and checkpoints.
- Strict DTO validation and mapping.
- Sanitized error mapping.

### Integration

- Mock transport full/incremental reads.
- Recorded synthetic/sanitized fixtures.
- Demo smoke tests behind an explicit marker and credential gate.
- A test transport that fails the suite if any request is not `GET` or not allowlisted.

## 14. Live environment gate

Live read-only connectivity may be enabled only after:

1. all local and Demo contract/security tests pass;
2. the user supplies a dedicated read-only key through secret storage;
3. configuration explicitly selects `live`;
4. logs/traces are verified redacted;
5. a minimal smoke test succeeds without broad backfill;
6. the connection can be revoked independently.

No Live credential is needed to complete local Phase 1 code; it is an external deployment gate.
