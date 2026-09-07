# P2-03 Market, FX and Benchmark Sources

P2-03 is `implemented_unverified` from synchronized `main` starting SHA
`c9adba4f427cdbee1ebce7fbbb9425d1061c8146`. Its preceding P2-02 evidence commit
passed documentation, security and quality CI. This document records the current
implementation and verification scope, not an acceptance or release claim.

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

## Acceptance still required

Focused domain, policy, parser/replay, API/client, browser-form and PostgreSQL
checks are being run during implementation. Package acceptance still requires
the complete gate, independent review, exact pushed implementation SHA, successful
CI, fresh container runtime and restart evidence, security/privacy checks and
portable assertion records. P2-03 is not complete until those records are retained.
P2-04 through P2-10 remain required. Phase 3 remains not started.
