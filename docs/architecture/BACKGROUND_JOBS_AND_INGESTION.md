# Background Jobs and Ingestion

**Status:** Accepted

## 1. Objectives

The ingestion subsystem must safely turn mutable, paginated, rate-limited broker observations into durable canonical history. It must survive retries, process restarts, duplicate records, partial endpoint failures, schema drift, and concurrent refresh requests without duplicating economic activity or silently losing coverage.

## 2. Job taxonomy

Phase 1 jobs:

- reference instruments/exchanges refresh;
- account summary refresh;
- current positions refresh;
- pending/current order observation refresh;
- historical order backfill/incremental refresh;
- transaction backfill/incremental refresh;
- dividend backfill/incremental refresh;
- normalization/mapping;
- account reconciliation;
- portfolio snapshot creation;
- source-retention cleanup according to policy;
- health/telemetry aggregation.

## 3. Job contract

Every job has:

- stable job type and version;
- owner/account scope;
- idempotency key;
- attempt number;
- scheduled/started/heartbeat/completed timestamps;
- lease owner and expiration;
- input parameters without secrets;
- status (`queued`, `running`, `succeeded`, `partial`, `failed`, `cancelled`);
- structured counts, warnings, and sanitized failure category;
- correlation ID and parent run ID.

## 4. Concurrency

- At most one active full/account refresh lease per broker account unless a documented capability is safe to parallelize.
- Reference-data refresh may be shared across accounts/environments where provider semantics allow.
- Concurrent identical refresh requests coalesce or return the active run.
- Lease expiration permits recovery after worker failure; ownership changes are audited.
- Database uniqueness remains the final idempotency boundary even when locks fail.

## 5. Pagination and checkpoints

Each capability defines an explicit pagination adapter. Checkpoint state may include cursor, last source timestamp, last provider ID, page fingerprint, and overlap window.

Rules:

- checkpoint advances only after all records in the atomic page/unit are durable;
- incremental reads use a safe overlap window to capture late updates;
- overlaps are deduplicated by provider ID and/or stable payload fingerprint;
- unstable ordering is detected where possible;
- loops/repeated pages and maximum-page bounds fail visibly;
- full backfills can resume without corrupting incremental state;
- coverage start/end and truncation warnings are persisted.

## 6. Retry policy

Only idempotent reads and safe internal jobs retry automatically.

- retry transient network errors, timeouts, selected 5xx responses, and explicit rate-limit responses;
- honor provider retry/reset headers when trustworthy;
- exponential backoff with jitter and configured ceiling;
- bounded attempts and total elapsed time;
- no retry for authentication failures, contract/schema incompatibility, invalid configuration, or permanent 4xx errors;
- retry decisions are observable and tested.

## 7. Rate-limit coordination

A central account/provider limiter records:

- endpoint/capability budget when known;
- remaining/reset observations;
- next eligible request time;
- in-flight requests;
- adaptive conservative fallback when headers are missing.

Interactive refresh cannot starve scheduled reconciliation, and background backfills must yield to higher-priority bounded refreshes according to explicit policy.

## 8. Atomicity and partial failure

A refresh run is composed of capability steps. One failed capability does not erase successful independent steps, but the account's aggregate quality becomes `PARTIAL` or `FAILED` according to dependency impact.

Examples:

- positions succeed, dividends fail: current valuation may be available; income/performance coverage is partial;
- instruments fail but cached mapping is fresh: positions may remain usable with a warning;
- transaction backfill fails before checkpoint commit: no checkpoint advance; prior durable data remains;
- reconciliation fails: snapshot may be stored as `UNRECONCILED` or withheld according to calculation policy.

## 9. Schema incompatibility

Provider DTO validation is strict for required semantics and tolerant only for retained unknown fields. When a payload cannot be mapped safely:

- record a sanitized schema-incompatible failure;
- retain/fingerprint the source according to privacy policy;
- do not partially coerce invalid money, identifiers, quantities, or timestamps;
- do not advance checkpoint for the affected atomic unit;
- expose a data-quality warning;
- alert through telemetry.

## 10. Snapshot scheduling

Snapshots are created:

- after a successful/usable refresh when requested;
- on a configurable daily schedule;
- manually through an authorized high-level action;
- never more than once for an equivalent account/source-cutoff/calculation-version key unless explicitly creating a revised version.

A snapshot records the source cutoff and component freshness. It is not falsely labeled current merely because calculation occurred recently.

## 11. Mock and replay modes

The provider port supports:

- deterministic fixture responses;
- injected latency/transient/permanent failures;
- pagination/rate-limit simulations;
- recorded sanitized contract fixtures;
- replay into an empty database;
- clock control for timestamp/freshness testing.

No real account payload is committed.

## 12. Acceptance tests

Phase 1 must test:

- duplicate refreshes and concurrent locks;
- crash before/after durable page commit;
- repeated/looping pagination;
- late and updated provider records;
- malformed identifiers, decimals, and timestamps;
- rate-limit responses and header adaptation;
- bounded retries and non-retryable failures;
- partial capability failure and aggregate quality;
- checkpoint restoration;
- full replay determinism;
- snapshot deduplication/version behavior;
- explicit rejection of non-allowlisted/write requests before dispatch.
