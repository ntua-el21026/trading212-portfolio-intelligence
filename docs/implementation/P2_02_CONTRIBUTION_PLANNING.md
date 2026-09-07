# P2-02 Drift and Contribution Planning

P2-02 is complete at `f78c9d2917c3ce8c93f9ae5631390c59616abc82`, following
implementation from `c9aeebe8e0481fee6f7d897bd3fb89b3a7fdfaed`.
The [execution manifest](PHASE_2_EXECUTION_MANIFEST.md),
[optimizer ADR](../adr/ADR-0011-DETERMINISTIC-CONTRIBUTION-OPTIMIZER.md),
[methods](../analytics/PHASE_2_METHODS.md) and
[API contract](../architecture/PHASE_2_API_SERVICE_CONTRACTS.md) define its scope.
The [assertion map](evidence/phase-2-p2-02-f78c9d2.json) binds its three local
acceptance rows and six scenarios to observed tests and exact-SHA gates.

## Calculation and identity

The domain receives an explicitly selected, immutable portfolio snapshot and
published target version. Target nodes, target holdings, instruments and listings
retain their distinct identifiers. The persistence adapter copies stored
positions, cash, FX references, source times, target content and mapping catalog
before committing a request. It does not ask the broker for a new valuation.

Drift reports group/subgroup, holding, cash and unclassified rows, direct weights,
signed/absolute/relative gaps, monetary gaps and availability. Unclassified value
remains in the denominator. Zero target weight and unavailable effective exposure
have explicit reasons. An intentionally selected later-published target carries
an assumption instead of pretending it was known at an earlier financial cutoff.

The four contribution modes are global, hierarchical, restricted and cash-only.
The deterministic bounded search uses exact Decimal arithmetic, a quantized
objective, stable tie ordering and explicit search counters. A valid bounded
incumbent is `feasible_nonoptimal`; absence of an incumbent at the budget is
`unavailable`. Infeasibility requires a contradiction proof or exhausted domain.
An independent result verifier checks input identity, conservation, hard
constraints and derived fields before the result can be stored. It does not
rerun the optimization search or infer optimality from an approximate gap.

The pinned SIX ISO 4217 minor-unit policy has 165 numeric entries. Unknown or
N.A. minor units remain unavailable; explicit precision cannot invent support.
The policy source version and digest are retained with calculation metadata.

## Durable internal work

Migration `20260907_0010` adds normalized plan/request, source/constraint,
job/outbox/attempt, result/line/explanation, audit and idempotency records.
Database ownership and immutability guards complement service authorization.
The request and its outbox intent commit atomically. `plans.calculate.v1` is a
fixed internal task carrying only five bounded identity strings.

The existing dispatcher and Celery worker share the existing default queue.
Publication and consumer attempts are separately bounded at eight and four;
fenced leases and heartbeats suppress duplicate completion and permit recovery.
The [operations extension](../operations/PHASE_2_OPERATIONS.md) records lease,
heartbeat, batch and retry parameters. Redis transports messages; PostgreSQL
retains authoritative requests, progress and results.

Recalculation creates another request/revision under an optimistic precondition.
Finalized revisions remain immutable. A detail representation's HTTP ETag covers
its job state and selected page; `revision_etag` is the separate command token.
History uses the existing bounded plan collection and shared owner quotas.
Identical first-page reads of immutable plan lines and actual/target rows reuse
the same retained membership and expiry. Different sources require a new quota
reservation; expiry and owner, account, filter and ordered-membership checks
remain mandatory. Polling cannot extend retention or bypass the shared limit.

## Interfaces

Six fixed API operations expose actual/target, ranked drift, plan creation,
listing, detail and recalculation. Generated closed TypeScript schemas and the
fixed client share bounded transport with target operations. Old target client
output remains unchanged. Four planning MCP tools extend the eleven accepted
tools to fifteen; the full 25-tool Phase 2 registry remains future work.

Authenticated `/drift`, `/planner` and `/planner/[planId]` routes consume canonical
server calculations. The editor supports all four modes, coverage policy,
eligibility/exclusions, listing preferences, cash reserves, all full constraint
variants and lossless MCP composite overrides. Financial inputs remain strings.
Monetary displays preserve every significant fractional digit, including
sub-cent allocations and residual cash. Source identifiers and content digests
remain available through expandable provenance details.
Failed commands preserve unsaved values and their retry identity. Each action
reauthorizes the session and CSRF context. Source catalogs and history load on
request; navigation disables speculative prefetch. Queued-job polling reads the
durable detail only and stops after sixty checks.
Status refresh pauses while editing to preserve unsaved inputs and the original
revision precondition. Revisions retain the original account and virtual Pie.
A changed target version or currency requires an explicit reset of incompatible
options; a changed currency also requires a newly entered contribution amount.
Snapshot-only revisions preserve all exact options.

## Observed verification and limits

Exact-commit `make validate` passed with 790 isolated Python tests, 129
service-backed integration/migration cases, 87% combined Coverage.py coverage
with branch measurement, 111 web unit tests and 36 synthetic plus 16 API-backed
browser tests, without retries. The reference suite includes 17 independent
rational cases. A separate observed statistics run passed all 175 generated
examples across the three planning properties; no fixed random seed is claimed.
Formatting, lint, strict typing, contracts, architecture, migration/schema,
security, dependency, documentation, production-build and six container gates
passed. The post-build canary scan checked ten paths, including both screenshots.

All three exact-SHA CI workflows passed: documentation `34145884900`, security
`34145884876` and quality `34145884991`. The [security record](evidence/phase-2-p2-02-f78c9d2-security.json)
contains complete-history Gitleaks, Trivy source and six immutable-image scans.
The [fresh runtime record](evidence/phase-2-p2-02-f78c9d2-runtime.json) contains
all four planning modes, identical canonical API/MCP input/result/source proofs,
seven immutable revisions, real Redis message-loss recovery, and all seven
services stopped before restart. All 44 compared tables remained identical,
including the 20 planning tables and retained cache-binding times. Recovery
used the same job, two publications and one consumer attempt. Privacy scans
covered 65 database tables, 518 rows and all seven service logs.

[Desktop](evidence/phase-2-p2-02-f78c9d2-desktop.png) and
[mobile](evidence/phase-2-p2-02-f78c9d2-mobile.png) screenshots show the synthetic
API-backed finalized plan. Effective company exposure remains explicitly
unavailable until P2-05; this package does not claim that later capability.

The first exact candidate passed `make validate`: 790 isolated Python tests,
124 PostgreSQL/migration tests, 87% combined coverage with branch measurement,
111 web unit tests and 36 synthetic plus 16 API-backed browser tests. A separate
Hypothesis statistics run observed 175 passing examples across the three
planning properties. Documentation and security CI passed, but quality run
`34144309940` failed in the mobile browser phase. With `TEST_DATABASE_URL` set,
the browser fixture reused the configured database across viewport launches and
hit the unchanged 64-snapshot owner quota. Local validation used the resettable
default database, so it did not exercise that failing configuration. The fixture
runner now uses a newly created disposable database for each launch, retaining
the configured URL only for connection settings and preserving its base database.
The correction passed the new exact-SHA gates above; the [failed candidate](evidence/phase-2-p2-02-5fa43b2-failed-quality.json)
is retained as history and remains unaccepted.

P2-03 through P2-10 remain required; Phase 3 remains not started.
