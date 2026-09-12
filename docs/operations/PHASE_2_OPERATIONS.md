# Phase 2 Operations Extension

**Status:** Accepted

**Date:** 2026-09-07

## Service topology and configuration

Retain PostgreSQL, Redis, API, worker, dispatcher, MCP and web. Reuse the fixed
worker and dispatcher for report and alert jobs; a separate scheduler/report
service requires a documented operational reason. PostgreSQL is authoritative
for target revisions, source snapshots, plans, reports, artifacts, rule versions,
evaluations, notifications, jobs and outbox intent. Redis is replaceable transport,
coordination and cache. A successful queue publish is not a completed job.

Default local mode uses deterministic synthetic inputs and existing local-only
authentication. Provider status identifies synthetic, configured, unavailable,
stale, partial and failed separately. Production configuration still fails closed
without the required identity and secret-manager setup. No command silently
switches synthetic inputs into a real account or enables Trading 212 Live.

Use existing `make bootstrap`, `make run-local`, `make migrate`, `make seed-demo`
and `make validate` entry points as the implementation extends them. Seed changes
are deterministic and idempotent; existing Phase 1 economic rows remain unchanged.
Inspect and record the migration/image/source version before starting services.

## Durable work and readiness

Fixed task names cover refresh, contribution planning, report/export generation,
alert evaluation and notification delivery. Artifact/input expiry runs in bounded
dispatcher maintenance calls; it is not a separately registered Celery task.
Requests atomically persist input references and outbox intent. Claims have fenced
leases and bounded attempts; idempotent replay checks semantic input fingerprints.

Distinguish three events: broker publication, transport acknowledgment and durable
application completion. A dispatch acknowledgment records publication under its
claim; it does not certify worker completion. The worker uses late acknowledgments,
but the Phase 2 wrappers can return `not_claimed`, `fenced`, `deferred` or
`recovery_pending` without completing the job. Inspect PostgreSQL job/outbox/attempt
state: expired claims and bounded republication own recovery even if the transport
message was acknowledged. Neither a Celery success label nor a publication counter
proves a saved plan, report artifact or notification receipt. A user's alert
acknowledgment is a separate lifecycle action and does not acknowledge transport.

API readiness checks its configured probe; the deployed database composition uses
a recent healthy **refresh** dispatcher heartbeat. The dispatcher records that
heartbeat before its independent Phase 2 cycles. A report/plan/alert cycle failure
can therefore coexist with refresh readiness. The worker image's Celery
`inspect ping` checks broker/control responsiveness, not completion of each task
family. MCP checks configured authentication and its composed database probe.
Use these as dependency signals and inspect the affected durable family separately.

### Observability signals and interpretation

The retention/telemetry composition exposes the following observations through
the existing redacted JSON log pipeline and private Prometheus registries. These
descriptions define signal semantics; execution and readiness depend on the
evidence recorded for the selected release.

API `/internal/metrics` requires `configuration:read`; the dispatcher's
`:9464/metrics` listener remains internal and is not host-published by default.
Existing publication counters retain their original meaning. Domain observations
do not increment those counters, and no external collector/exporter is installed
implicitly by this implementation.

| Obligation | Observation and interpretation |
|---|---|
| Target validation | `phase2_operation`, operation `target_validation_response`, outcome `valid` or `invalid`, after the authorized transaction returns. Counts responses, including idempotent replay; not unique validation records. |
| Optimizer duration/outcome/infeasibility | Operation `optimizer_calculation` records actual calculation duration and the canonical fixed outcome, including `infeasible`. It counts calculation attempts, not published plans. Existing consumer/dispatch telemetry remains separate. |
| Market/FX freshness and benchmark coverage | `phase2_source_status_observed` records fixed family, selected availability/freshness and coverage categories for the authorized returned page. It runs after existing owner/license/retention guards and does not decode another graph, fetch a provider, log identities or manufacture a freshness verdict. It counts status observations, not unique sources. |
| Xray coverage/unresolved exposure | `phase2_xray_calculation_quality` observes a verified calculation's company coverage, unresolved and stale exposure as finite buckets. Bound, availability, quality and positive-below-quantum presence are preserved; a zero lower bound is not proof of absence. It exposes no amounts, holdings or source IDs and does not claim a committed run. |
| Report/export duration and failures | Operations `report_render`/`export_render` time the bounded rendering stage, ending on success or failure. Recorded consumer failures use the canonical failure-code catalogue. Rendering completion alone does not certify artifact persistence. |
| Alert evaluation and deduplication | Operation `alert_evaluation_committed` records a completed evaluation after transaction return. Separate event-publication counts identify created events, already-known event decisions, cooldown suppression and a latched episode. Fenced/duplicate job completion does not emit another committed count. |
| Webhook/email delivery | Separate channel operations record initial not-configured destinations and real stored retry/failure/accepted-receipt transitions. These are neither broker publication acknowledgments nor exactly-once recipient acceptance. Default unconfigured transports remain unconfigured. In-app event/feed state retains its existing durable meaning. |
| Queue depth, retries and dead work | `phase2_queue_items` and `phase2_queue_saturated` expose five fixed families and six fixed state predicates: queued, running, consumer retry waiting, publication retry waiting, publication dead and job failed. Each indexed-state query counts at most 1,001 matches and clips at 1,000. Saturation means a lower bound; these are current-state gauges, not cumulative attempt counters. |
| Report/alert/source expiry | `phase2_expiry_completed_total` records completed source, report/export and alert capture expiries after the existing cleanup transaction returns. It is not a row/byte/artifact count. Zero does not establish an empty backlog; partial physical cleanup can retain pending work. |
| Database query duration | `database_query_duration_seconds` observes cursor execution success/failure through explicit engine-local timing in the composed API default and dispatcher. It excludes result fetching, connection/pool time and engines not explicitly instrumented. No SQL, table, parameter, URL or private label is retained or emitted. |
| Readiness dependencies | Existing API/refresh/broker/control probes keep their meaning. `phase2_cycle_ready` reports each Phase 2 cycle's last result separately; a successful cycle is not proof that its workers completed. Queue-observation timestamp/failure state exposes stale samples. |

Queue sampling occurs on the existing dispatcher loop, at most once every
30 seconds after the previous sample finishes, plus an explicit `--once` sample.
It uses normalized state/attempt metadata only and does not select canonical
payloads or hydrate private identities. Queries are read-committed observations,
not an atomic census across families. A failed sample preserves the previous
gauges and timestamp and marks its cycle unsuccessful. Review actual query plans
and durations during P210 verification; bounded returned rows are not a production
capacity claim or a statement that every PostgreSQL plan is optimal.

Database listeners are opt-in for one engine. Failed statements terminate their
timing observation. Disposal detaches query/error listeners and releases the
observer/timing state; explicit adapter closure also unregisters the inert
disposal hook. Dispose after active work finishes. Reusing a disposed engine does
not silently reconnect it to the old metric registry. Engines supplied by an
external deployment composition must explicitly select their own observer.

Log event counts are not durable exactly-once counters: process failure after
commit can omit an observation. Canonical PostgreSQL records remain the authority
for accounting and incident reconstruction. Response/calculation observations may
repeat by design. Aggregate only matching event semantics.

Keep fixed operation/outcome/reason categories. Never label metrics or enrich
these observations with owner/account IDs, instrument lists, report names, URLs,
destinations, email addresses, secrets or user text. Private incident records may
contain authorized opaque references; telemetry does not.

### Contribution calculation

`plans.calculate.v1` is the only planning task. Its transport message contains
five canonical strings: job, request, owner and account UUIDs plus the pinned
input digest. It carries no contribution, holding list, solver expression or
broker instruction. The existing Celery worker consumes it on the default
queue; the existing outbox dispatcher publishes it after the request transaction
commits. PostgreSQL stores the request, source/constraint copies, job, outbox,
attempt events and one immutable finalized result.

The fixed bounds are eight publication attempts and four consumer attempts per
logical job, a 30-second publication claim, a 60-second consumer lease and a
15-second heartbeat. Dispatch batches default to 20 and cannot exceed 100;
classified transient failures use exponential delays from one to 60 seconds.
The dispatcher recovers expired claims and unconsumed published messages using
the same job identity. An active consumer lease suppresses republication. Claim
tokens fence acknowledgments, heartbeats, failures and completion; successful
publication does not mark the financial calculation complete. The solver runs
outside the heartbeat event loop and finalized outputs undergo independent
constraint/conservation verification before persistence.

Observe bounded `plan_dispatch` attempt/outcome metrics and safe planning failure
categories. A failed, unavailable or infeasible calculation never creates broker
orders or drops constraints. Existing snapshots and FX values are copied before
the queued request is committed; recovery cannot substitute a later valuation.

Polling immutable plan-line or actual/target membership reuses an unexpired
collection snapshot only when its owner, account, query, source and ordered
membership match. Reuse retains the original expiry and quota reservation.
A different request, finalized result, analytics run or expired membership
requires a fresh reservation under the shared 64-snapshot/250,000-member limits.
Ordinary history and mutable source catalogs retain their existing pagination
behavior. Browser acceptance gives each viewport its own disposable fixture
database so independent suites do not consume one another's owner reservations.

## Recovery procedures

Before changing state, record the affected release/image/configuration revision,
UTC interval, bounded failure code and authorized resource reference in the private
incident record. Use current scopes, immutable pins and existing command
idempotency/If-Match/CSRF requirements. Public reads are not generic repair APIs;
do not edit canonical rows, lease fences, attempt counts or completion flags.

| Failure | Inspect, recover and establish the result |
|---|---|
| Target recovery | Follow [target recovery](../implementation/P2_01_VIRTUAL_TARGETS.md#local-operation-and-recovery): read prior/current versions and events, create a new draft with `source_version_id`, validate and publish with fresh preconditions. Confirm the new activation event. Archiving the active version does not restore an old version. |
| Provider outage | Inspect authorized `/accounts/{account_id}/market-sources` or `fx-sources` under `/api/v1`, and the retained safe provider outcome. Separate unconfigured/unsupported/license denial from an actual completed network failure. Let classified bounded retries respect the provider window; no repeated manual refresh loop. Recovery requires a new actual successful observation, not a successful queue publish. |
| Bad market data | Preserve the offending source revision, cutoff and safe contract category privately. Stop the affected ingestion path; correct the typed adapter/mapping and admit a new validated source revision through the existing service. Never overwrite first-knowledge times, fabricate a coverage gap or patch published bytes. Confirm cutoff selection and reconciliation before using the replacement. See [reference-source contracts](../implementation/P2_03_REFERENCE_SOURCES.md). |
| Benchmark or FX gaps | Inspect `benchmark-sources`, the selected definition version, calendar, return basis, currencies and observation gaps. Preserve the pinned unavailable result. New data may support a new run; changing the benchmark requires a new authorized definition version. Do not fill absent levels/FX with zero/one or align unrelated dates. See [historical intelligence](../implementation/P2_04_HISTORICAL_INTELLIGENCE.md). |
| Optimizer failure/infeasibility | Read the saved plan/job and its input digest, failure code, constraints, outcome and residual. An infeasible completed result is distinct from failed work. Permit bounded transient job recovery; after an intentional input change create an authorized plan revision with If-Match and a new command identity. Do not remove constraints, reset attempts or send orders. See [planning](../implementation/P2_02_CONTRIBUTION_PLANNING.md). |
| Stale or unresolved Xray | Inspect the selected snapshot/run, source cutoff, policy, coverage and lower bounds. Keep the retained result and quality limitations; obtain eligible sources through configured ingestion before selecting a new run. Do not refresh an old run by relabeling its timestamps or silently substitute a more complete source. Current source denial/expiry takes precedence over replay and cursors. See [Xray retention](../implementation/P2_05_PORTFOLIO_XRAY.md#persistence-and-retention). |
| Report/export failure | Inspect `/api/v1/report-jobs/{job_id}` or `/api/v1/exports/{export_id}`, pinned input/manifest identity and safe failure code. Distinguish `publication_unavailable`/`storage_unavailable` from `input_changed`, `source_restricted`, `limit_exceeded` or `render_failed`. Recover transient work through the existing fenced job path. A terminal failure is not reset by replaying its create key; any reviewed replacement is a new authorized command and remains linked in the incident record. Confirm durable artifact metadata/bytes through authorized reads, not Celery state. |
| Object-storage or render-workspace failure | Current private artifact storage is PostgreSQL BYTEA; inspect database availability/space and the worker's bounded private workspace for the relevant failure. Preserve job/capture/manifest identities. Remove only inspected orphan task workspaces after confirming no active consumer. No object-store backend is composed here; a future backend requires separate durable-byte/integrity/access validation. Never issue a grant or invent a signed URL to bypass failed storage. |
| Alert backlog | Separate due-slot admission, evaluation publication/lease, retained evaluation outcome and notification delivery. Inspect authorized rule/event/delivery state and bounded job attempts; use normal expired-lease recovery. An authorized pause limits further evaluation but is not a universal cancellation/recall of already created notifications. Preserve admitted input/window, deduplication and cooldown identities. Verify one durable evaluation/event/delivery transition rather than clearing Redis or acknowledging/resolving events to drain work. |
| Webhook abuse | Contain external notification egress, then disable the affected trusted destination through the server provisioning boundary and verify denial before delivery. Public commands accept opaque destination IDs only. Preserve the in-app feed and safe failure categories; do not log the destination, body or secret. Do not allow redirects/proxies/private addresses or expand origins to make a rejected delivery work. See [delivery boundaries](../implementation/P2_07_ALERTS_AND_RULES.md#actual-provider-observations-and-delivery). |
| Provider credential rotation | Follow [rotation/revocation](CREDENTIALS_AND_DEMO_VALIDATION.md#5-rotation-and-revocation). Pause the affected dispatch path, rotate the opaque secret reference using the authorized provider/secret-manager process and validate only the already approved environment. On suspected exposure revoke first. No available external credential, secret adapter or successful external probe is implied by this runbook. |
| Report artifact deletion | Expired access is denied before cleanup. The dispatcher calls `PostgresReportJobStore.expire_report_artifacts(limit=100)`; preserve safe manifest/tombstone/audit data while bounded cleanup removes forbidden bytes, copies and grants. Verify pending purge work as well as access denial. There is no generic public artifact-delete route: an urgent pre-expiry erasure needs containment and a reviewed deletion plan; do not rewrite expiry, clear a BYTEA alone or restore deleted copies from backup. |
| Migration rollback | Record actual prior/target Alembic revisions and compatible image digests, preserve a verified backup and serialize migration work under the deployment operator's lock. The migration environment itself does not acquire a deployment lock. Prefer a reviewed forward correction; roll back an application image only if compatible with the actual schema. Destructive downgrades and the irreversible export-URL deletion cannot be treated as recovery. |
| Incident response | Follow [security/integrity containment](TROUBLESHOOTING.md#8-security-or-integrity-incident) and [isolated recovery](BACKUP_RESTORE.md#4-incident-recovery). Bound affected owner/account/time/source scope privately; contain ingress, provider/notification egress and affected job producers as needed. Preserve audit/immutable hashes and current revocation/deletion decisions. Reopen only after explicit authorization, integrity and expiry checks; a broker-write attempt is an incident even if rejected upstream. |

External delivery remains unconfigured in the default worker:
`ConfiguredAlertWebhook()` has no destinations/credential port and its packaged
origin list is empty. An email destination category is not an installed email
transport. Preserve `not_configured`/unavailable outcomes. A delivery timeout may
be ambiguous; retry only the same durable delivery identity within the bound,
without claiming exactly-once receipt by an external recipient.

## Retention, migration and backup

Initial private report storage is bounded PostgreSQL BYTEA with explicit expiry;
no persistent signed provider URL is permitted. Cleanup uses bounded non-blocking
batches and owner-safe scope. Retain canonical manifests and audit according to
policy while clearly distinguishing deleted artifact bytes from unavailable input.
An optional object-store adapter must preserve the same authorization/licensing
and atomic-completion contract before deployment.

The dispatcher runs an independent exact-source cleanup cycle in both continuous
and `--once` modes, alongside report/alert and collection maintenance. It calls
`PostgresSourceService.expire_source_snapshots(limit=100)` with the existing shared
physical purge budget across source, enrichment and dependent copy families.
There is no new service, transport task, public maintenance route or provider call.

Source/enrichment participants preserve the sources-then-Xray owner lock order
and use transactional try-locks plus skip-locked source headers. A busy owner stays
eligible for a later bounded pass rather than blocking unrelated dispatcher work.
Copy authorization, physical allowances, immutable parent/tombstone digests and
completion guards remain authoritative. This does not impose a universal SQL
timeout on every downstream operation. Verify real contention, physical removal,
pending-work resumption, current-license denial and parent retention against the
selected release's acceptance evidence. Continuous cleanup errors have a fixed safe
category and retry on the existing cadence; `--once` propagates a failed cleanup.

The returned count records completed source expiries, not all visited/removed
rows or bytes. A zero result does not establish an empty backlog. Retain integration
and execution evidence for this composition with the selected release.

Apply migrations forward from `20260907_0008` and test old/new schema compatibility.
Immutable source and privacy-deletion migrations are not casually reversible.
Document any non-reversible operation before release; application rollback must
not restore signed URL retention or invalidate ownership constraints. Follow the
[existing backup/restore runbook](BACKUP_RESTORE.md); production backup restoration
remains an explicit external gate until actually tested.

## Acceptance and incident evidence

Use an isolated Compose project/ports/volume for stop/restart tests, never delete
unrelated volumes, and confirm all seven service states are stopped before restart.
Compare canonical hashes, economic counts, target/plan/job/evaluation/artifact
identities, and restored volume identity. Scan runtime files, logs, database rows,
metrics and rendered/exported artifacts with dynamically assembled synthetic
secret and URL canaries. Preserve safe evidence with exact source SHA/image IDs.
Do not infer production throughput, credentialed provider connectivity or public
MCP readiness from synthetic local acceptance.

## P2-05 bounded projection and exact-source purge lifecycle

Persist canonical fund compositions. Generate at most 496 pairs for one 2..32-fund
request, without a lifetime pair cache. Pair/common payloads must be owned/referenced
by active collection bindings and charge the shared 64 collections/250,000 members.
Common-entity parents also reserve bounded binding references. First/empty requests
reserve capacity; exact membership reuse keeps original TTL (default 3600 seconds,
existing 60..86400 range). MCP Top may remain transient. Expired references remove
unreferenced projection payloads; deterministic same-run regeneration uses canonical
compositions, with no source reselection or traversal.

Exact-source expiry denies read/replay/cursor/304 immediately regardless of collection
TTL. Extend the existing indexed expiry invocation; share its 100-capture/100-run
budgets across families and add explicit physical projection-row and payload-byte
limits. Charge rows/bytes visited and removed across bindings, pair/common payloads,
normalized/source rows and every copied canonical/exact-state document. Batches are
bounded and indexed. Avoid unbounded cascading deletes and parent markers that
leave child licensed payloads unaccounted for. Exhaustion retains indexed pending
work and the exact source remains purge-pending until all forbidden copies are gone.
Permitted tombstones/digests/audit can remain; replay after required payload deletion
is unavailable. ADR-0017 fixes separate shared ceilings of 4,096 physical rows
inspected and removed, and 64 MiB logical payload bytes inspected and removed,
per invocation. Indexed batches are <=512 and limited by remaining bytes; inspect
bounded size metadata before loading. Payload clearing counts as removal. Path
proofs allow 256 identity decision IDs and 256 source reference IDs, four complete
fund edges and a scalar classification assignment per dimension. Singleton output
must fit 2 MiB without dropping material proof.

Observe sanitized counts/bytes/pending outcomes without raw owner/source IDs or
financial payloads. Retention tests must prove budget accounting, forward progress,
source-denied-before-cleanup, collection expiry, no uncharged lifetime growth and
restart of pending purge work. No new stack, global data cache or production
capacity claim follows from this design amendment.
