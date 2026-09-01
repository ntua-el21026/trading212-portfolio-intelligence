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
- requested portfolio snapshot creation;
- expired collection-query snapshot cleanup;
- refresh-dispatch heartbeat and telemetry aggregation.

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

The externally created Phase 1 job is always `portfolio.refresh` version 1. Its
message is restricted to dispatch ID, run ID, account ID, request fingerprint,
request-schema version, task name, and task version. It contains no credentials,
raw provider payload, provider URL, or arbitrary task name. The Celery task ID is
the durable ingestion run ID.

## 4. Durable publication

The API does not call the broker as a correctness step. Under one account-scoped
PostgreSQL transaction it:

1. validates canonical requested refresh semantics;
2. creates or returns the account/idempotency-key ingestion run;
3. inserts exactly one `pending` outbox event for a new run;
4. commits both rows before returning the queued run.

An independent dispatcher polls the outbox. It claims available `pending` rows
and expired `publishing` rows with `FOR UPDATE SKIP LOCKED`, records claim owner,
token, and expiry, then publishes outside the transaction. Confirmed broker
acceptance moves the row to `published`; confirmed publication is not periodically
replayed. An expired `publishing` claim is ambiguous and is safely republished
with the same deterministic task ID.

Publication failures increment total and consecutive attempt counters, persist a
sanitized code, and schedule exponential backoff within configured bounds. The
consecutive publication limit defaults to eight in Compose. Exhaustion makes the
event `dead` and the queued run explicitly failed rather than stranded. A broker
error observed after a consumer marker or matching live lease is treated as an
accepted delivery, not a false dead letter.

The consumer validates the complete task contract against the locked outbox/run
rows before loading credentials or economic inputs. Economic execution attempts
are counted durably in the outbox and constrained globally to at most four across
redeliveries/restarts. Transient execution retries are bounded; configuration or
exhausted failures are terminalized with sanitized codes before ACK. If the
terminal-state write is temporarily unavailable, a terminalization-only retry is
used and does not rerun economic work.

## 5. Concurrency

- At most one active full/account refresh lease per broker account unless a documented capability is safe to parallelize.
- Reference-data refresh may be shared across accounts/environments where provider semantics allow.
- Concurrent identical refresh requests coalesce or return the active run.
- Lease expiration permits recovery after worker failure; ownership changes are audited.
- Database uniqueness remains the final idempotency boundary even when locks fail.
- The lease carries a fencing token. A valid delivery blocked by any live account
  lease is durably returned to `pending` until that lease expires; it is not ACKed
  into a permanently published state.
- Consumers explicitly confirm successful/partial/failed terminal delivery in the
  outbox before ACK. Duplicate deliveries return the existing logical run and
  cannot duplicate source records, activity, cash flows, or snapshots.

## 6. Pagination and checkpoints

Each capability defines an explicit pagination adapter. Checkpoint state may include cursor, last source timestamp, last provider ID, page fingerprint, and overlap window.

Rules:

- checkpoint advances only after all records in the atomic page/unit are durable;
- incremental reads use a safe overlap window to capture late updates;
- overlaps are deduplicated by provider ID and/or stable payload fingerprint;
- unstable ordering is detected where possible;
- loops/repeated pages and maximum-page bounds fail visibly;
- full backfills can resume without corrupting incremental state;
- coverage start/end and truncation warnings are persisted.

## 7. Retry policy

Only idempotent reads and safe internal jobs retry automatically.

- retry transient network errors, timeouts, selected 5xx responses, and explicit rate-limit responses;
- honor provider retry/reset headers when trustworthy;
- exponential backoff with jitter and configured ceiling;
- bounded attempts and total elapsed time;
- no retry for authentication failures, contract/schema incompatibility, invalid configuration, or permanent 4xx errors;
- retry decisions are observable and tested.

Broker-publication retry and economic-execution retry are distinct budgets.
Publication uses the outbox's durable consecutive-failure counter. Consumer
execution uses its own database counter, so broker redelivery or process restart
cannot reset the economic attempt limit.

## 8. Rate-limit coordination

A central account/provider limiter records:

- endpoint/capability budget when known;
- remaining/reset observations;
- next eligible request time;
- in-flight requests;
- adaptive conservative fallback when headers are missing.

Interactive refresh cannot starve scheduled reconciliation, and background backfills must yield to higher-priority bounded refreshes according to explicit policy.

## 9. Atomicity and partial failure

A refresh run is composed of capability steps. One failed capability does not erase successful independent steps, but the account's aggregate quality becomes `PARTIAL` or `FAILED` according to dependency impact.

Examples:

- positions succeed, dividends fail: current valuation may be available; income/performance coverage is partial;
- instruments fail but cached mapping is fresh: positions may remain usable with a warning;
- transaction backfill fails before checkpoint commit: no checkpoint advance; prior durable data remains;
- reconciliation fails: snapshot may be stored as `UNRECONCILED` or withheld according to calculation policy.
- API crash after commit but before publication: the queued run and its pending
  outbox event remain atomic; a later dispatcher publishes the original run.
- dispatcher crash after broker acceptance but before acknowledgment: the expired
  claim may republish at least once, while the consumer/run/materializer remain
  idempotent.

## 10. Schema incompatibility

Provider DTO validation is strict for required semantics and tolerant only for retained unknown fields. When a payload cannot be mapped safely:

- record a sanitized schema-incompatible failure;
- retain/fingerprint the source according to privacy policy;
- do not partially coerce invalid money, identifiers, quantities, or timestamps;
- do not advance checkpoint for the affected atomic unit;
- expose a data-quality warning;
- alert through telemetry.

## 11. Snapshot creation

Snapshots are created:

- after a successful/usable refresh when requested;
- never more than once for an equivalent account/source-cutoff/calculation-version key unless explicitly creating a revised version.

A snapshot records the source cutoff and component freshness. It is not falsely labeled current merely because calculation occurred recently.

## 12. Dispatcher readiness and telemetry

The dispatcher upserts a bounded-identity heartbeat containing start,
heartbeat, last healthy-cycle timestamps, healthy/degraded state, and one
sanitized error code. Staging/production configuration fails if a dispatcher is
not explicitly configured. API readiness additionally requires a recent healthy
cycle (30 seconds by default, bounded to five minutes).

Prometheus metrics include pending event count, oldest pending age, publication
attempts by bounded outcome, recovered expired/terminal claims, failed publication
attempts, queued runs without a deliverable event, operation duration/failures,
and dispatcher readiness. Owner/account/run IDs are not metric labels.

## 13. Mock and replay modes

The provider port supports:

- deterministic fixture responses;
- injected latency/transient/permanent failures;
- pagination/rate-limit simulations;
- recorded sanitized contract fixtures;
- replay into an empty database;
- clock control for timestamp/freshness testing.

No real account payload is committed.

## 14. Acceptance tests

Phase 1 must test:

- duplicate refreshes and concurrent locks;
- commit without publication followed by dispatcher restart;
- broker acceptance followed by dispatcher crash before acknowledgment;
- two dispatchers claiming concurrently without corrupting an event;
- expired claim recovery and bounded broker backoff;
- global consumer-attempt exhaustion and terminalization-only recovery;
- same semantic idempotency retry and mismatched-key conflict;
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
