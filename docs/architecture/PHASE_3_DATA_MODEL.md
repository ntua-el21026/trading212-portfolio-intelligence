# Phase 3 Data and Durable Work Contract

**Status:** Accepted implementation design; runtime evidence pending

Extend the existing scoped schema after `20260911_0016`. Existing financial,
source, identity, authorization and immutable-history tables retain their meaning.
Use the actual owner/account foreign keys and composite scope conventions already
present in persistence; no parallel identity or financial ledger is introduced.

## Normalized records

| Family | Required normalized records and constraints |
| --- | --- |
| Risk | risk_definitions and immutable risk_definition_versions; risk_runs pin definition/version, historical capture, portfolio snapshot, benchmark and selected asset/source identities; risk_series/intervals, risk_metrics, covariance cells and risk_components belong to one run and owner/account. Unique run/series/interval and run/matrix/row/column. |
| Stress | scenario_definitions, immutable scenario_versions, normalized scenario_shocks/exclusions and evidence-bound sensitivity mappings; scenario_runs pin version, portfolio/X-ray/history captures and dates; scenario_components retain original root/path exposure exactly once. |
| Projections | assumption_sets, immutable assumption_versions, ordered asset assumptions/correlation cells and schedules; projection_requests and runs pin goal/assumption/source versions, seed and resource admission; path summaries/checkpoints have unique run/absolute-path/point identity. |
| Goals | goals and immutable goal_versions with currency, target/date/basis, probability objective and schedules; goal_analyses reference one immutable projection result and sensitivity runs. |
| Research | research_sources and immutable source_versions, source events/revisions with publication/observation/cutoff and license references; company associations bind canonical economic entities; notes/thesis revisions and review acknowledgments are owner records separate from source facts and optional synthesis. |
| Preferences | owner_layouts and saved_view_versions contain validated fixed widget/route/filter selections, account references, optimistic revision and audit; no credential, arbitrary URL, expression or raw provider payload. |
| Providers | provider_entitlements and immutable entitlement_versions reference actual evidence and fixed capabilities/use/retention policies; current revocation state is separate from pinned source eligibility. Reuse existing source/license records where they express the same relationship. |
| Aggregation | aggregate_selections and ordered account_members pin authorized account/snapshot references; aggregate_runs, source-account components and transfer_matches retain currency/FX and economic/source identity. No modification of broker activity records. |

All monetary/ratio/covariance columns use existing ExactNumeric NUMERIC(38,18),
all instants UTCDateTime, all financial wire values exact decimal strings. Public
and normalized results use the same Q18 canonical projection. Large private
canonical captures may use bounded typed serialized BYTEA with a schema and
verified digest; they do not replace ownership/FK/uniqueness/numeric constraints.
Never use untyped JSON as a financial model or public request/result escape hatch.

Version contents are immutable from successful publication. Creating a corrected
version pins its predecessor and increments the aggregate revision under If-Match.
A duplicate semantic idempotency key returns the existing logical record after
current authorization; a changed payload conflicts before a new insert. Published
source/input/result rows reject mutation through service and database constraints.
Operational lease/state projections may change; financial content may not.

## Shared run identity and publication

Risk, scenario and projection requests are internal application commands. Each
has a typed job and fixed-purpose outbox using existing PostgreSQL transactional
publication patterns. Pin original actor/principal scope, owner/account, immutable
inputs, source cutoff, method/schema/numeric version and semantic input digest.
Use the current application command identity mechanism. A GET never creates a job.

The shared premium_runs/premium_jobs/premium_dispatch_outbox identities use typed
per-family child records (risk_runs first), not untyped financial bodies. These are
normalized equivalents of the family run records above. A partial unique index
enforces the local single-running-job ceiling across premium families.

Fixed task names are `risk.calculate.v1`, `scenarios.calculate.v1` and
`projections.calculate.v1`. Messages contain only bounded opaque job/request/
owner/account references, version and digest. Producers cannot choose a callable,
SQL, URL, filesystem path or arbitrary task. Register only completed handlers.
Reuse the existing dispatcher/worker; add no scheduler/container family.

Execution states are queued, running, succeeded, failed, cancelled and expired.
Claim through SKIP LOCKED with a 60-second fenced lease and 15-second heartbeat;
publish at most eight times and execute at most four attempts across restarts.
Confirmed publication is distinct from worker completion. An expired ambiguous
claim may republish the same task identity. Current grants and source permissions
are checked again before executing and before atomic result publication.

Commit the full canonical result, normalized result rows and terminal job state
atomically. A fenced/cancelled worker cannot publish. Projection checkpoints can
commit bounded absolute path-index chunks under the current fence; they remain
private incomplete work until the requested path set and summaries are complete.
Chunking/worker order/retry cannot alter random identity or calculation inputs.
A failed or timed-out prefix cannot become a successful complete run.

## Resource admission

| Resource | Hard ceiling |
| --- | ---: |
| HTTP command body / ordinary result | 64 KiB / 2 MiB |
| Risk asset series / combined interval cells | 32 / 100,000 |
| Risk window | 3,661 daily boundary points, within existing 3,660-day span |
| Scenario rules / exclusions / terminal components | 128 / 128 / existing 10,000 X-ray terminal paths |
| Scenario sensitivity observations + memberships + evidence + applied uses | 100,000 aggregate rows per run, also within the 32 MiB complete private bound |
| Projection assets / monthly horizon / paths | 12 / 600 / 4,096 |
| Projection asset-month-path product | 1,000,000 |
| Retained projection time points / cash-flow schedule entries | 121 / 128 |
| Projection checkpoint chunk | 32 absolute paths; reduce chunk size to remaining work/byte allowance |
| Active premium jobs per owner / globally admitted running jobs | 2 / 1 in local configuration |
| Retained canonical input or result per run | 32 MiB private; ordinary public response still 2 MiB |
| Retained premium run payload per owner | 256 MiB, checked before reservation/publication |
| Definition versions per owner, including archived | 512 |
| Research text per source revision / event page | 16 KiB / 100 |
| Owner note/thesis field / fields per revision | 4,096 characters / 8 |
| Saved layouts/views per owner / widgets per layout | 32 / 24 |

Budgets are admission ceilings, not measured performance claims. Reserve owner
capacity transactionally before inserting work. Expiry cannot reset another
active job's reservation or resurrect an idempotent completed identity. Bound
iterators and query work before loading payloads; byte limits also constrain
otherwise valid row counts. No successful truncation to fit a cap.

Each execution attempt has a 240-second wall deadline and bounded deterministic
work. Deadline expiry is an operational failure, not a change in the mathematical
result. Keep successful checkpoints for retry within retention, reauthorize every
resume, and never change seed, paths, horizon or tolerances to obtain success.
Per-owner and global admission use PostgreSQL authority, not Redis-only locks.

Risk calendar content uses the existing canonical source key/version pair. Its
normalized version row references the resolved owner-scoped calendar UUID; neither
identity replaces the other in the calculation digest. Run lists contain bounded
owned operational metadata without decoded financial results. Financial detail,
matrix and replay paths recheck the complete current source authorization.

## Source legality and physical retention

New licensed copies participate in the existing source-expiry and owner-purge
inventory. Access denial is immediate on revocation/expiry, before decode, cursor,
304, download or replay. The shortest applicable source restriction bounds
retained input, normalized result, checkpoint, report and derived projection copies.
Default run retention is30 days, configurable downward to source requirements;
reports keep their existing 7-day default/30-day maximum. Pure owner definitions
and notes remain until authorized erasure within their retained capacity.

Extend the shared bounded cleanup, never create an unbounded cascade. Preserve
the existing 100-capture/100-run and4,096 physical-row/64 MiB inspected/removed
invocation budgets, across all participating families. Indexed pending work remains
until forbidden copies are physically gone. Keep only permitted audit/digest
and command tombstones; collection/report TTL cannot extend source retention.
A deleted source makes dependent replay explicitly unavailable, not silently newer.

Risk runs additionally pin up to 8,192 distinct original license identities in
premium_run_licenses during authorized capture. These owner/account/provider-scoped
references are sealed with admission and remain audit metadata after payload removal.
Migration 0018 backfills the references from normalized historical dependencies
(including registered-evidence dependencies) and X-ray dependencies; it does not
rewrite a financial result. Current license selection uses effective time, version
number and stable ID, matching source authorization, and does not select future policy.

The existing source dispatcher shares its single purge budget with risk maintenance.
Risk cleanup holds sources, X-ray, historical and premium owner locks without waiting
on busy owners. It fences queued/running jobs, deletes normalized children before their
series and clears the canonical result last. Byte capacity remains charged until all
payload phases finish. A pending retention marker survives partial work; metadata
lists then show expired availability and financial reads/replay deny before decode.
Source/enrichment completion waits for eligible risk copies for the same owner.


## Required database and recovery proof

Test cross-owner/account composite FKs, immutable publication, exact numeric/UTC
bounds, version conflicts, idempotency/concurrency, current grant revocation,
quota reservation rollback, bounded physical purge, lease expiry/cancellation,
Redis loss and duplicate dispatch. Compare canonical hashes and normalized row
counts after restart. Upgrade an actual0016 database and a clean empty database,
repeat the head upgrade, and restore a synthetic backup into a genuinely empty
independent database. Verify constraints and recovered job behavior, not only that
pg_restore exits successfully. Production restore remains an external gate.

## Synchronous bounded aggregation

ADR-0034 retains separate normalized aggregate selections, member pins, runs,
account/holding/component/FX/transfer proof and indexed retained-source memberships.
Selections including tombstones count within the shared512 definition ceiling;
run copies reserve32MiB and charge actual canonical+normalized bytes within the
shared256MiB owner ceiling. Aggregate input and all result/proof copies have a
combined32MiB ceiling. This family uses the existing global premium admission slot
in one synchronous transaction, without a new premium job task. The20s cancellation
ceiling covers decoding/serialization and does not replace accepted p95 SLOs.
Source-copy cleanup and owner erasure participate in the same physically bounded
retention composition; immutable metadata survives financial payload deletion.
