# Phase 1 Trusted Foundation Implementation Report

**Release target:** `0.1.0`
**Implementation authority:** `main`
**Imported candidate SHA:** `7119be95ae41d036f1461dd21bfbf10243c64ab0`
**Validated implementation/evidence SHA:** `bba71749096cecbe8732d60e2b5bb1e44c394b7c`
**Later work:** Phase 2 and Phase 3 are `not_started`.

## Linear delivery record

The candidate was fast-forwarded from starting `main`
`c566c080762f9d74996e1bdd19d1254848f8f17f` without a merge commit. Corrections then
continued directly on `main` in this order:

1. `41d3212ca7ab772b8c6c0c0bf5449d1a2af44aae` — restore the owner's main-only
   governance and delete the unaccepted branch-exception decision record;
2. `964cadfc32b7950e092ebb295c9d722d50234fd7` — implement the durable outbox,
   semantic idempotency, stable complete collections, service contracts, MCP queries,
   and paginated web experience;
3. `8f9a0ff681ca9f5757dac669508c11ccb9904a89` — enforce complete service coverage and
   correct dispatcher/consumer operational evidence;
4. `0508f7a300c04134daf743fff012caeaaa8eb4c6` — remove browser retry masking and make
   browser-back pagination evidence deterministic;
5. `cf2d932917f4801577bb6ad90dedc3c5dceeaa1e` — add desktop/mobile API-backed
   canonical-summary parity evidence;
6. `bba71749096cecbe8732d60e2b5bb1e44c394b7c` — align the pinned Trivy license-policy
   configuration with the current scanner schema and validate the exact fresh-checkout
   security matrix.

The subsequent final documentation/status reconciliation is an evidence-only linear
descendant. No published commit was amended, rebased, force-pushed, or merged through a
pull-request merge action.

## Transactional refresh outbox

Migrations `20260901_0004` through `20260901_0007` make PostgreSQL the durable command
boundary. The API stores one ingestion run and one bounded non-secret
`portfolio.refresh` outbox event in the same transaction, then returns the queued run
without depending on broker availability. The event is unique per logical run and holds
only run/account/request metadata and a schema version—never credentials or raw broker
payloads.

An independently supervised dispatcher claims bounded batches using
`FOR UPDATE SKIP LOCKED`, records claim owner/expiry, publishes only the fixed task with
task ID derived from the durable run ID, and records attempts, availability/backoff,
publication time, and sanitized error categories. Expired claims are recovered after
process death. Bounded retry/dead-letter behavior and heartbeat/readiness prevent an
unconfigured dispatcher from appearing production-ready. Metrics cover pending count,
oldest age, attempts, failures, recoveries, and queued runs lacking a deliverable event.

Delivery is at least once. Before work, the consumer validates task run/account/request
metadata against the durable row. Run leases, source-record identity, occurrence
membership, canonical economic uniqueness, snapshot identity, and consumer-terminal
reconciliation make duplicate or ambiguous delivery safe. Scenario 14a, 14b, and 14c
remain separate acceptance predicates; their evidence is recorded in
[PHASE_1_SCENARIO_EVIDENCE.md](PHASE_1_SCENARIO_EVIDENCE.md).

## Semantic idempotency

Each key is scoped by owner/account and bound to a versioned canonical fingerprint of
the requested mode, normalized capability set, fixed create-snapshot behavior, and
request schema. Correlation ID is excluded. Requested semantics are stored separately
from effective/promoted execution semantics, so an initial incremental/current request
promoted to full/all still retries against its original fingerprint.

- Same account, key, and semantic request returns the same durable run before
  publication, during execution, after success, and after retryable publication failure.
- The same textual key is independent across accounts.
- A same-account key reused with different mode/scope returns HTTP 409 with
  `IDEMPOTENCY_KEY_REUSED`, publishes nothing new, and does not disclose the earlier
  request.
- PostgreSQL uniqueness/locking and the deterministic synthetic service implement the
  same concurrent coalescing/conflict behavior.

## Stable complete collections

Offset cursors and pre-pagination `_MAX_COLLECTION_ROWS` truncation were removed.
Versioned HMAC-protected opaque cursors bind resource, authorized account/owner,
deterministic sort, normalized filter fingerprint, read cutoff or immutable result
snapshot, last ordering key/tie-breaker, and cursor schema version. Malformed, expired,
tampered, or cross-resource/account/sort/filter cursors fail with a stable 400-class
`CURSOR_INVALID` response.

- Positions bind to an immutable portfolio snapshot and support market-value,
  direct-weight, and ticker sorts plus bounded ticker/name search.
- Activity uses SQL filters and stable `(occurred_at DESC, id DESC)` membership snapshots
  so new and backfilled records cannot corrupt an active traversal.
- Dividends filter in SQL, paginate by `(paid_on DESC, id DESC)`, and aggregate the full
  filtered period rather than a capped prefix.
- Orders expose deterministic latest-observation membership; snapshots use
  `(valuation_at DESC, id DESC)`.
- Instruments search canonical instrument/listing metadata—including unheld listings—
  before pagination, with deterministic provider/environment/listing ordering.
- Every collection fetches `LIMIT page_size + 1` over the complete eligible set and
  reports an exact filtered total. MCP output remains bounded without collect-then-filter
  semantics.

## Completed application-service contracts

Both PostgreSQL production and deterministic synthetic services implement typed,
authorized use cases for broker connections, accounts/summary, positions, activity,
dividends/summary, orders, snapshots/list and direct lookup, canonical instrument/listing
search and detail, direct allocation, core performance, reconciliation/status and
discrepancy pagination, data-quality summary, refresh creation/status, and all typed
stable collection queries.

- Broker connections now return owner-scoped canonical connection ID, provider,
  environment, read-only/state, safe `configured`/`not_configured` credential state, and
  last successful refresh without credential references or secrets.
- Instruments no longer depend on held positions. Canonical instrument ID and listing ID,
  ticker/name/type/ISIN, MIC/exchange, currency, provider/environment, and listing status
  disambiguate metadata and allow unheld-instrument discovery.
- Core performance loads an explicit period, beginning/ending snapshots, and covered
  external flows, then invokes coverage-gated XIRR/TWR/Modified Dietz analytics with
  method/version, values/annualization, convergence, missing inputs, assumptions,
  warnings, and quality. Deposits remain external flows, never investment gain.
- Data quality derives from actual run/step/checkpoint/cutoff/materialization/snapshot/
  reconciliation/FX/mapping evidence and safely bounded failed/partial run IDs. REST and
  MCP use the same service result.

## Review-finding closure

| Review comment | Correction and regression evidence |
|---|---|
| `3899170686` | Atomic run/outbox transaction, independent leased dispatcher, ambiguous-delivery and API-crash restart tests. |
| `3899170689` | Versioned requested-semantic fingerprint, 409 conflict behavior, promotion/concurrency/retry tests. |
| `3899170691` | Route-specific typed web loaders, URL cursor/load-more navigation, preview counts/order, desktop/mobile >50/back tests. |
| `3899170693` | Removed 10,000-row pre-truncation; SQL filtering/counting/aggregation and >10,000 discoverability tests. |
| `3899170695` | Resource/account/filter/sort-bound keyset or immutable-membership cursors with tamper and insertion-stability tests. |

All five review threads were answered with corrected commit/test evidence and resolved.

## Validation and scope boundary

The complete command, migration, browser, security, image, and corrected Compose matrix
is in [VALIDATION_REPORT.md](../../VALIDATION_REPORT.md). Alembic head is
`20260901_0007`; API/OpenAPI/generated TypeScript/MCP canonical parity is green; the MCP
registry remains exactly nine Phase 1 tools.

Only P1-EXT-001 through P1-EXT-003 remain `blocked_external`. P1-EXT-004 is
`unavailable_explicit` with its real-provider opening-history limitation reported.
Trading 212 Live is disabled and untested. No Trading 212 write capability exists. No
virtual Pies, targets, contribution optimization, benchmarks, look-through, reports,
alerts, advanced risk/scenarios, Monte Carlo, goals, or research workflow was started.
