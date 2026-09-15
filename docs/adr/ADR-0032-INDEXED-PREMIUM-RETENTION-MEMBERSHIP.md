# ADR-0032 — Indexed premium retention membership and physical inspection costs

Status: Accepted design; projection and report integration implemented, runtime validation pending.

## Decision

Keep ADR-0017's independent 4,096 physical rows inspected, 4,096 rows removed,
64 MiB logical copied-payload bytes inspected/removed, 512-row batch, 100-run and
100-capture ceilings. SQL trigger and constraint reads count too. This is a
storage/query implementation amendment; no public financial or source API changes.

A projection stores a closed normalized `projection_retained_source_memberships`
relation, keyed by its exact owner/account/run and source kind/ID. Its seven kinds
are `price`, `fx`, `corporate_action`, `benchmark`, `historical`, `license`, and
`classification`. These are the physical cleanup parents and licensed historical
origins. Other permanent broker/source audit identities remain in the existing
complete immutable source proof; they are not silently discarded or copied into a
new public registry.

The already authorized original source traversal emits membership before capture
seal. Direct calibration and complete admitted historical input -> evidence ->
source lineage are included. Historical evidence -> evidence remains forbidden.
Deduplication retains the earliest applicable original clock for a shared source:
physical header creation; historical header creation as provenance; original
historical creation for an explicit license edge; minimum classification/history
creation for the existing two-origin classification retention rule. Historical
header age alone does not impose a new unlicensed expiry: that copy still uses
premium-root creation plus the existing 30-day maximum.

An independent closed SQL set projection verifies every source identity and clock
at seal, rejecting missing, extra, cross-owner, malformed nested or over-capacity
membership. The aggregate membership limit is 100,000 rows per run, including all
selected calibration sources. The existing 32 MiB actual storage bound may reject
smaller sets. The helper for full source/read authorization remains unchanged in
purpose; neither membership nor a maintenance cursor grants access to private
payloads or replaces current principal/provider rights checks.

Covering indexes support exact owner/kind/source/run membership and bounded
owner/account/run/ID deletion. Physical source-parent SQL guards perform one exact
indexed membership probe. They do not enumerate every premium run, walk historical
dependencies, or reconsider an unbounded prefix of already-clean runs. A source
match maintenance query uses the same exact index. Existing resumable expiry scans
retain their explicitly charged bounded metadata traversal.

All fixed payload participants also have exact owner/account/parent/ID cleanup
indexes. Indirect quantile/bin collections iterate separately charged parent
headers (at most 363 distributions, 6 histograms or 3 goal analyses), then clear
one exact parent's children; no cross-parent sort can consume the whole child
population before LIMIT. Revisited empty parents are charged again. Three extra
FK indexes bound chunk/path/point deletion checks across other retained runs.

Membership remains while any projection financial participant or dependent report
copy remains. Reports are physically drained first; normalized projection
financial rows and canonical documents/chunks are next; membership is last.
Each stage commits bounded progress under the existing sources -> X-ray ->
historical -> premium owner locks. The SQL deletion guard rejects early removal;
profile-four integration also checks its indexed report-copy pending flag directly.
No deletion waits for an owner advisory lock after acquiring a target tuple.

`stored_bytes` includes exact `pg_column_size` membership rows. Separate
trigger-owned `retained_source_rows` and `retained_source_bytes` retain that charge
after financial `payload_rows` reaches zero. Empty result audit headers do not
keep a financial charge merely because membership remains. All counters reject
direct DML. Active jobs continue reserving 32 MiB; terminal/refund accounting reads
actual counters and releases only physically removed bytes. Full aggregate storage
parity remains a publication/verification check; cleanup's deferred capacity
constraint uses the protected counter rather than rescanning financial tables.

`PayloadCopyCost` adds optional physical inspection cost and logical-payload read
multiplicity. Existing defaults retain prior callers' behavior. The reservation
selects a stable prefix by both weighted inspections and removals before mutation;
repeated counter reads consume bytes again. A projection mutation conservatively
reserves 25 physical inspections: target 1, counter at most 6, immutable guard at
most 4, report guard at most 4, deferred capacity at most 2 and up to 8 fixed FK
probes. Scope ancestors are separately charged before metadata queries, including
empty-batch completion probes. Membership deletion reserves 11 inspections; per-run
marker/fence/refund/completion mutation work reserves 64, in addition to explicit
reads. A fresh invocation can still process a largest legal 32 MiB payload and its
one counter reread within 64 MiB. Bounds are conservative ceilings, not throughput
measurements.

Profile-four report integration must also eliminate its completed dependency
prefix: a trigger-owned `copy_pending` flag is initialized for an actual immutable
report binding and cleared only after exact report physical cleanup, with an
indexed pending dependency query. REPORT-only cleanup must carry a concrete source
restriction witness and verify the exact retained member, original physical clock
and pinned/current rights. A mutable maintenance cache is never SQL authority.
An existing exact owned premium retention marker authorizes draining its report
copies without recursively rechecking every source. The separately staged 0023
implementation owns these report-specific changes and their physical row costs.

## Compatibility and validation

No report profile, canonical document bytes, provider capability, numerical method,
worker task, public DTO, command identity or source admission API is widened.
This amends the still-uncommitted projection 0022 schema. Existing stamped local
0022 test databases require a fresh upgrade; a published deployment would require
a separately reviewed upgrade/backfill migration, not migration-file rewriting.

Required evidence includes fresh upgrade/parity/downgrade, exact source and
original-clock set agreement, rejection of missing/extra/foreign membership,
original and transitive parent blockers, report-copy-before-membership deletion,
partial physical refunds, source epoch/owner isolation, largest-payload progress,
weighted mixed-family budget tests, and a real PostgreSQL cleanup with recursive
lineage/aggregate helpers replaced by failure canaries. No runtime validation is
claimed by this external source stage.


## Additive legacy report maintenance closure

Report contract2/3 source expiry uses a persisted keyset sweep and fixed metadata
phases over original normalized report, licence, legal history/evidence and
scenario source memberships. Full original recursive/completeness functions stay
at capture and current-authorized reads; they are not candidate predicates or
maintenance-cache authority. A concrete fixed original-row witness independently
rechecks current restriction before a report source marker can be inserted.
Profile2 retains its original premium-root licence clock; profile3 retains its
existing source/header and report/root copy-deadline relationships. No canonical
report bytes, profile semantics or public schemas are rewritten.

Additive migration0025, after0024, places a protected copy_pending flag on existing
physical report dependency rows. Exact indexed pending membership replaces the
completed-copy prefix. After physical report copies disappear, those flags clear
in charged batches before final marker/premium flag completion. A large dependency
set cannot hide an unbounded AFTER-completion update. False flags while any report
bytes or grants remain are rejected independently of maintenance state.

The report scanner pins one active input per owner across busy-owner skips,
resumes ordered cursors, and invalidates partial proof on current owner policy or
known time-boundary changes. It reuses the existing protected owner epoch and
original source indices. Additional enrichment and scenario source marker inserts
advance that same epoch; their one-row upsert/guard cost must be included by their
respective physical purge participants.

This closes the report-specific legacy candidate, source-copy guard and report
mutation path. Separate risk/scenario run cleanup remains subject to its own
physical-inspection audit; neither this amendment nor the projection implementation
claims those distinct participants satisfy the bound without that evidence.

Pending report markers have a separate indexed keyset position in the same
singleton sweep. This resumes flag drainage after header bytes have gone,
including ordinary profile1 reports without a premium dependency. Every
candidate, busy-owner skip and checkpoint is charged; no completed marker
prefix is filtered after the limit.


## Risk/scenario cleanup extension (migration0026)

Risk/scenario maintenance selects physical roots through a protected per-run state
row and evaluates original source metadata in resumable phases. A scheduling
round has durable keyset position; it never applies a full source predicate before
LIMIT. An unfinished proof pins the same absolute root instead of advancing past
it at every budget boundary. Owner-scoped rounds invalidate on policy epoch,
original/current deadline, backwards time or future policy activation. Global
round completion is scheduling progress, not a source permission witness.

A closed immutable parent relation is populated from actual risk/scenario run
rows and their selected sensitivity versions. It covers historical inputs, X-ray
inputs/runs and sensitivity versions. These operational identities remain until
all financial run and dependent report copies are gone. Exact parent probes
replace completed-run prefix scans and the existing historical/X-ray participant
now drains both run families. Original canonical financial representations and
source/read/seal validators remain authoritative and unchanged.

Scenario state tracks the exact existing storage expression and financial row
count. The independent aggregate remains an integrity/test oracle; maintenance
uses the trigger-owned counter. Risk preserves its existing byte charge semantics
and uses only physical row count. No new byte valuation is assigned to risk
identity metadata. State is FK-bound to its exact owner/account/run, direct
counter writes are rejected, and an established retention marker prevents later
payload insertion. Active/terminal reservation semantics are unchanged.

Sensitivity observation headers carry an exact trigger-owned payload-present
bit. Shared evidence links separate logical ownership from confirmed physical
absence; both flags have indexed pending lookups. A marked version releases only
its own links. The evidence-first SQL guard then checks a single indexed remaining
owner and avoids locking every linked version. Physical-absence flags clear one
link at a time after the payload has actually disappeared. A permitted sibling
keeps the shared bytes and leaves the other version truthfully pending.

One source purge allowance remains 4096 inspections/removals, 512 per batch and
64 MiB logical byte inspection/removal. Risk/scenario payload mutations reserve
32 row inspections and sensitivity payloads24, including fixed guard/counter/FK
work. Payload copies reserve two logical inspections where the existing SQL guard
and counter revisit the same bytes. Metadata reads and operational flag writes
are charged separately. New marker producers explicitly reserve the protected
owner-policy upsert cost3. These are source-level cost envelopes pending the
serial unit/PostgreSQL/parity validation recorded by the integrating task.

This extension does not establish whole-system physical-budget acceptance. The
older enrichment retention guard still traverses X-ray input dependencies and
calls xray_payloads_pending when advancing copies to payloads and when inserting
an expiry event; entity-evidence completion also filters cleared prefixes. Its
producer now preserves candidate progress and charges fixed marker/epoch work,
but those transitive SQL paths require a separate exact pending-copy relation and
bounded physical flags. Historical/X-ray/alert/source cleanup participants retain
any separately documented Phase 2 audit obligations. No old immutable guard is
removed or treated as a free inspection to claim closure.
