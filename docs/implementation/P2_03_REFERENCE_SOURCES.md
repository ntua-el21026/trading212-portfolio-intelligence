# P2-03 Market, FX and Benchmark Sources

P2-03 is **complete** at `e258f54bb03a958f7847b310ee882b7f4a54686f`, from
synchronized `main` starting SHA `c9adba4f427cdbee1ebce7fbbb9425d1061c8146`.
The [assertion map](evidence/phase-2-p2-03-e258f54.json) binds P2-03,
P2-SRC-001, P2-SRC-002 and P2-S13 to observed exact-commit acceptance. The complete
Phase 2 release and shared predicates remain pending.

The [execution manifest](PHASE_2_EXECUTION_MANIFEST.md),
[source ADR](../adr/ADR-0012-MARKET-SOURCE-SNAPSHOTS.md),
[provider contract](../integrations/PHASE_2_PROVIDER_CONTRACTS.md),
[methods](../analytics/PHASE_2_METHODS.md) and
[API contract](../architecture/PHASE_2_API_SERVICE_CONTRACTS.md) remain authoritative.

## Adapter and semantic boundaries

`trading212-reference-data` is an isolated workspace package used by the worker.
Canonical domain, analytics, application and persistence layers cannot import its
adapters. The existing transport checker still grants outbound HTTP authority
only to the sealed Trading 212 client. No external reference HTTP adapter or
origin manifest is enabled; real provider configuration and licensing remain an
explicit unavailable gate. Trading 212's ten fixed GET capabilities are unchanged.

Concrete replay providers implement price history and corporate actions, FX,
benchmark series, typed instrument resolution and classification, and ETF
constituent retrieval. The fixture is synthetic, source-controlled and versioned.
Raw close, split-adjusted and total-return prices retain separate series identities
and values. Provider benchmark levels remain distinct from composite wealth.
Explicit replay failure categories cannot turn an unsupported operation into a
successful empty result.

The replay runtime enforces one operation per second with burst two, three
attempts for transient failures, a shared 60-second logical pagination deadline,
100 pages, 1,000 observations per page and 100,000 observations per ingestion.
The JSON decoder independently limits decompressed bytes, nesting, string length
and nodes, rejects duplicate fields and floating-point JSON numbers, and returns
closed failure values. Canonical projection removes unknown fields before source
hashing. Internal continuations bind the typed request, minimized fixture digest,
revision, count, offset, page budget and deadline; public APIs never expose them.
Replay context validation rejects catalog entries that relabel a fixture's
currency, basis, calendar or provider key. ETF metadata uses an explicit
owner-scoped fund and constituent mapping rather than inferring either from
catalog order.

## Source identity, persistence and policies

Owner-scoped provider, immutable license, instrument mapping, source-series and
calendar records precede ingestion. The source-series catalog identifies either
a security price or a provider benchmark series. Benchmark components reference
catalog entries, not observation snapshots or other benchmark definitions.

Normalized snapshots and observations preserve period, basis, currency, adapter,
schema, mapping/license versions and economic revision. Trusted ingestion owns
first knowledge time. Identical minimized content retains one economic snapshot
and appends a retrieval occurrence for a new retrieval command; exact command
replay does not duplicate rows. Corrections append immutable snapshots. Database
ownership and immutability constraints complement application authorization.

Selection applies explicit provider precedence, effective time, first-knowledge
cutoff and revision ordering. Conflicting unordered revisions are unavailable.
Calendars explicitly enumerate sessions; missing open sessions remain gaps.
Closed-session carry requires an explicit policy and preserves the original age.
FX snapshots and requests pin their calendar identity and version, so expected
fixing gaps can be independently checked. FX selection tries a direct pair,
permitted reciprocal and one configured pivot;
pivot legs must share provider, snapshot, batch and fixing date. Missing, stale or
post-cutoff legs cannot substitute zero or one. Decimal arithmetic uses local
precision 80 and the declared output quantum.

Storage, display, report and export permissions are separate immutable license
inputs. Unknown permission denies use. Expiry is checked during reads before
conditional responses or page continuations; retention cleanup preserves only
permitted safe audit identity and explicitly records loss of reproducibility.
Historical coverage and current freshness are separate assessments. The synthetic
freshness policy uses the observation effective time, never the latest retrieval.

## Public vertical and local operation

Fourteen fixed API operations expose account source status, three snapshot kinds
with paginated observations, and benchmark definition list/create/detail/version/
archive. Read authorization and current display licensing precede data, ETag and
cursor responses. Mutable membership uses the existing shared owner quotas.
Provider revision ordinals use exact decimal integer strings on the JavaScript
wire. Large gap lists expose their true count and an explicitly truncated bounded
preview instead of an unbounded header.

Benchmark creation atomically publishes an immutable first version. Further
versions require the aggregate revision token, exact weights and explicit
normalization consent where applicable. Archive retains used history. Exact
command replay returns the original closed response and immutable version
references even after subsequent publication or archive. Definition
commands do not calculate or fabricate composite benchmark observations; that
calculation belongs to P2-04.

The source browser and benchmark editor use the generated typed API client.
Account, filter, selected version and page state are URL-backed. Source details
show exact observations, currency/direction, coverage, first knowledge, retrieval,
revision and licensing. Benchmark edits preserve exact string weights and reuse
the same request identity on retries; conflicts preserve unsaved inputs.

API browser specs run in separate disposable databases for each spec file and
viewport. The 26-version benchmark pagination regression originally exhausted
the existing shared 64-view owner quota when unrelated browser scenarios reused
one database. Isolating their runtime lifecycles preserves that production quota
and all original assertions; no retries, capacity increases or shortened cursor
lifetimes are used.

The existing `make seed-demo` production path now also registers and ingests the
synthetic reference fixtures through authorized source services. Fixed synthetic
time and request identities make repeated seeding reproducible. No broker economics
are rewritten by source ingestion. The external reference provider is explicitly
unconfigured, while local replay data remains usable.

## Observed acceptance

`COMPOSE_PROJECT_NAME=t212pi_stage_a_20260907 make validate` passed from a clean
checkout at the accepted SHA and left it clean: 1,004 isolated Python tests,
156 PostgreSQL/migration tests, 145 web unit tests, 36 synthetic and 20 API-backed
browser tests, and 88% combined coverage with branch measurement. A separate
observed Hypothesis run passed 140 generated cases with no failing/invalid cases.
All three exact-SHA CI workflows passed on attempt one.

The [runtime record](evidence/phase-2-p2-03-e258f54-runtime.json) retains the
fresh stack, repeated idempotent seed, activation, one global plan with Redis-loss recovery,
all fourteen source HTTP operations, exact price/FX/benchmark observation parity,
immutable benchmark history and original-cursor continuation through a full
seven-service stop/restart. The first runtime harness attempt stopped before
shutdown because it compared newly issued signed cursor bytes. The second attempt
passed cursor checks but exceeded the 64-view quota while repeating the full
earlier-package journeys. Both failed logs are retained. The accepted fresh
journey authenticates stable cursor payloads, submits original opaque tokens and
retains all new source checks while limiting the planning regression to one
immutable global plan. Comprehensive four-mode coverage remains in the accepted
P2-02 evidence and full exact suite. No production code, quota or expiry policy changed.

The [security record](evidence/phase-2-p2-03-e258f54-security.json) binds complete-history
Gitleaks, Trivy source and six immutable-image scans to the clean build. All eight
passed. Post-build canary scanning passed across twelve contract/web/test/screenshot
paths. Desktop/mobile source and benchmark views were visually inspected.
The [compatibility record](evidence/phase-2-p2-03-e258f54-compatibility.json) proves
all 46 previously accepted HTTP operations, 98 schemas, 15 MCP descriptors and
ten fixed GET broker capabilities remain unchanged.

Acceptance is synthetic/local. Real licensed providers, Demo credentials and
deployment/OAuth remain separately unavailable. P2-04 through P2-10 and shared
P2-S14/P2-S36 predicates remain required. Phase 3 remains not started.
