# Phase 2 Provider Contracts

**Status:** Accepted

**Date:** 2026-09-07

**Release:** 0.2.0 design contract; implementation evidence is separate

This extends [provider adapters](PROVIDER_ADAPTERS.md) under accepted
[ADR-0009](../adr/ADR-0009-PROVIDER-TRANSPORT-ISOLATION.md). Domain and financial
methods consume canonical immutable records, never a provider SDK, HTTP DTO,
response body, URL, credential, or transport exception. PostgreSQL is the source
of truth; replay is the default for reproducible local operation. External
configuration is an explicit gate on that adapter, not a gate on local engineering.

## 1. Isolation and sealed broker boundary

The existing Trading 212 client and ten capabilities in
`config/contracts/trading212-read-allowlist.yaml` remain unchanged: account
summary, instrument/exchange metadata, positions, pending orders, order detail,
historical orders/transactions/dividends/export metadata. All dispatch GET
through existing fixed typed templates; demo remains default. Historical export
metadata remains the minimized safe field selection from Stage A, including
`download_available` without retaining the URL or its raw-payload hash. No Phase 2
provider adds a broker capability, method, path, parameter, redirect, raw export
download, broker report creation, Pie mutation, or generic request primitive.

Dedicated packages/adapters own price, FX, benchmark, constituent/enrichment,
notification, and report storage concerns. A concrete adapter module may use an
outbound library only if explicitly registered for its family in the architecture
allowlist with tests. The checker continues to reject transport imports in
domain, analytics, application use cases, API routes, MCP, and web. A general
provider namespace exemption or shared arbitrary `request(method, path)` service
is prohibited. The Trading 212 transport cannot be reused for other origins.
Provider configuration/credentials never flow through ordinary API inputs.

## 2. Typed ports and concrete replay implementations

Each port has a closed request/result schema. The following names are normative
use-case boundaries; language idiom may change class casing, not capabilities.

| Port and typed operation | Request | Canonical result |
|---|---|---|
| `MarketPriceHistoryProvider.get_price_history` | `PriceHistoryRequest`: authorized mapped instrument/listing, date range, `raw_close|split_adjusted|total_return` basis, source cutoff, opaque continuation | `PriceHistoryPage`: observations with date/UTC close instant, positive exact price or explicit missing state, currency, basis, source/version, coverage and typed continuation |
| `MarketPriceHistoryProvider.get_corporate_actions` | `CorporateActionsRequest`: mapped instrument, period/cutoff and continuation | `CorporateActionPage`: `split|cash_distribution|merger|spinoff` variants with exact ratio/amount, effective date, currency when monetary, correction/version and unsupported-field state |
| `FxReferenceProvider.get_rates` | `FxRatesRequest`: 1..32 unique base/quote pairs, period/cutoff and continuation | `FxRatePage`: positive exact rates, pair, effective UTC instant, source/revision and gaps; never implicit binary floats |
| `BenchmarkProvider.get_series` | `BenchmarkSeriesRequest`: authorized fixed series key or immutable benchmark version, period, declared return basis/currency and continuation | `BenchmarkSeriesPage`: dated exact levels, basis, source currency/version, distribution treatment, calendar, coverage and gaps |
| `InstrumentEnrichmentProvider.resolve_instrument` | `InstrumentResolutionRequest`: one typed ISIN, provider key, or MIC+ticker identifier | `InstrumentResolutionResult`: zero..20 typed candidates, canonical instrument/listing references, evidence, valid interval, confidence, `resolved|ambiguous|unresolved` state |
| `InstrumentEnrichmentProvider.get_classifications` | `ClassificationRequest`: 1..100 resolved identities, taxonomy/version and cutoff | `ClassificationPage`: fixed entity/security/listing relationships and sector/industry/country/region/economic-currency assignments with effective dates/evidence/confidence |
| `ETFConstituentProvider.get_constituents` | `ConstituentRequest`: authorized fund mapping, effective date at/before cutoff and continuation | `ConstituentPage`: source constituent keys, exact weights, known/unresolved/cash status, instrument/entity evidence, stated coverage and publication/retrieval times |
| `ReportStorageProvider.put_artifact` | `PutArtifactRequest`: owner/job/artifact IDs, fixed format/MIME, expected digest, bounded byte stream, expiry | `StoredArtifact`: opaque storage key, verified size/digest and expiry |
| `ReportStorageProvider.open_artifact` | `OpenArtifactRequest`: authorized owner/artifact identity and expected digest | `ArtifactContent`: fixed MIME and bounded verified byte stream, or typed unavailable/expired result |
| `ReportStorageProvider.delete_artifact` | `DeleteArtifactRequest`: authorized expired artifact identity | `ArtifactDeletion`: `deleted|already_deleted`, safe audit metadata |
| `NotificationProvider.deliver` | `NotificationDeliveryRequest`: owner/event/destination version IDs, fixed payload schema/template, provider idempotency key | `NotificationReceipt`: opaque receipt ID, `accepted|delivered|unavailable|failed|unknown` state, safe category and time |

Opaque continuations are created/validated inside the adapter. They never contain
user-selectable request URLs and do not cross the public API boundary. Typed
provider results expose provenance fields only from a fixed selection, not
`metadata: dict` escape hatches. These ports return canonical records to ingestion;
ingestion assigns/pins immutable storage snapshot IDs. Read APIs use persisted
snapshots, not synchronous provider fetches.

Local implementations are concrete `ReplayMarketPriceHistoryProvider`,
`ReplayFxReferenceProvider`, `ReplayBenchmarkProvider`,
`ReplayInstrumentEnrichmentProvider`, `ReplayETFConstituentProvider`,
`PostgresReportStorageProvider`, and `InAppNotificationProvider`. Replay adapters
execute the same typed pagination, mapping, cutoff, failure, and license behavior
against versioned synthetic fixtures. They cannot return fabricated successful
empty results for unsupported operations. Explicit unavailable adapters may model
missing external configuration, but do not substitute for the required working
replay adapters and real PostgreSQL/in-app vertical paths.

## 3. Fixed-origin transport manifests

Each concrete HTTP adapter needs a reviewed, committed, family-specific manifest
before enablement. No paid/live provider is selected by this design. The manifest
must freeze adapter/schema version; fixed HTTPS origins; fixed capability/path
templates and method per operation; typed path/query/body fields; authentication
secret references; redirect policy; rate/page/body bounds; timeout/retry budgets;
source/license evidence and permitted deployment environment. Nonbroker market
data operations use read capabilities only. Report storage and notification may
write only through their dedicated fixed-purpose ports and do not inherit access
to broker credentials or transport.

An origin is normalized scheme/host/port, has no userinfo/query/fragment, and is
trusted configuration rather than caller input. Concrete HTTP adapters enforce:

1. HTTPS, certificate/hostname verification, redirects disabled, environment
   proxy inheritance disabled, and no URL accepted from upstream pagination.
2. Explicit allowlisted origin and fixed path templates before every dispatch;
   reject unknown capability, path parameter, query parameter or request field.
3. Resolve and validate every destination address against public-address policy;
   reject loopback, private, link-local, multicast, unspecified, reserved and
   metadata addresses, including IPv4-mapped IPv6 and DNS rebinding. Pin the
   validated address for connection while retaining TLS hostname validation.
4. Connect timeout five seconds, read timeout 20 seconds, total logical operation
   budget 60 seconds; an explicitly stricter provider manifest may reduce them.
5. At most three attempts for safe retryable requests, bounded backoff with
   retry-after capped by the remaining deadline; deterministic injected clock/
   sleeper in replay tests. Never retry invalid schema, unsupported capability,
   authorization or license failures as transient success.
6. A conservative default one request/second and burst two per owner/provider
   credential scope, tightened by the provider's documented policy. Shared Redis
   rate coordination failure defers dispatch; it does not allow unlimited calls.
7. At most 1000 records/page, 100 pages and 100,000 records/logical ingestion,
   decompressed body at most 8 MiB/page, bounded JSON nesting and string sizes.
   A larger requested dataset is split into explicit bounded source snapshots
   with declared completeness; a cap cannot produce a falsely complete prefix.
8. Detect repeated continuation keys, page loops, repeated source ordering,
   incorrect currencies/bases and inconsistent source revisions before sealing.
   Cache keys contain safe canonical parameters, owner and source/license version.

The SSRF address policy applies to enabled remote HTTP adapters. Local replay and
PostgreSQL storage use their explicit in-process/database ports and do not need
fake public network addresses. Email/webhook destinations are provisioned by
trusted server configuration, with exact destination origins/addresses and
opaque secrets; API/MCP users select an authorized destination ID only. A webhook
adapter also validates DNS on every attempt and rejects redirects. There is no
public destination URL registration or arbitrary test-delivery endpoint.

## 4. Source, privacy, and error mapping

Every retained source has owner/provider/license identity, adapter and schema
version, requested scope, source effective time, first known/retrieval time,
source revision, canonical semantic digest, currency/basis and coverage. Explicit
retrieval occurrences append observed times without changing the first knowledge
time. Identical canonical records reuse source identity; corrections create a
new immutable snapshot and preserve the old one. The
[source ADR](../adr/ADR-0012-MARKET-SOURCE-SNAPSHOTS.md) defines cutoff/replay.

Transient provider DTOs may accept documented additive fields, but only selected
typed canonical fields cross the minimization boundary. Known fields validate
strictly; unknown status/basis/currency semantics produce invalid/unsupported
state. Raw response bytes, signed URLs, authorization headers, cookies, redirect
locations, webhook addresses, secrets, reversible URL derivatives, and hashes of
unminimized responses never enter database provenance, logs, caches, metrics,
traces, public errors, reports, exports, or fixtures. Semantic hashes are computed
after minimization; credential rotation cannot change economic identity.

Provider errors are closed categories `not_configured`, `unsupported`,
`not_found`, `authentication_failed`, `access_denied`, `rate_limited`, `timeout`,
`transient_failure`, `invalid_schema`, `pagination_invalid`, `license_denied`,
`payload_too_large`, and `permanent_failure`. They include capability, safe
provider key, retryability, optional bounded retry-after, and correlation ID.
Exception cause/context and traceback formatting must not retain the raw response
or secret-bearing SDK exception. Logs emit the safe category and operation
identity; metric labels exclude account IDs, instrument IDs, URLs and errors.
Default unavailable configuration returns `not_configured`, health
`unavailable`, and explicit missing capability, never a success receipt or
synthetic price. Fixture mode is visibly marked `synthetic` everywhere.

## 5. Licensing and reproducible history

License versions declare `store`, `display`, `report`, and `export` permissions,
allowed retention, attribution, redistribution limits and source evidence.
Unknown permissions deny the corresponding use. Storage checks run before
persisting source rows; report/export checks run again at generation and download.
Required attribution is part of visible results and manifests. Expiry prevents
reads before bounded cleanup. If later license changes require deletion, retain
only permitted digests/audit and mark dependent results non-reproducible when
replay inputs are no longer legally retained; never claim a successful replay
from removed data.

Raw close, split-adjusted and total-return series are distinct capabilities; an
adapter cannot relabel one as another. FX rates explicitly name their direction.
Conversions, inversion and triangulation happen in the versioned canonical
method with pinned source observations, never in an undocumented adapter shortcut.
Fund snapshots name constituent effective date, publication/retrieval time and
coverage. Classification mappings expose evidence and confidence; ticker-only
matching cannot claim a resolved high-confidence economic entity.

## 6. Durable storage and delivery

Default artifact storage is real PostgreSQL `BYTEA`, bounded to 10 MiB/artifact,
25 MiB/report job, four formats, seven-day default and 30-day maximum TTL.
Owner-authorized hashed download grants and atomic completion are specified by
the API and data contracts. Storage keys are opaque and not local paths or URLs.
A future private backend requires its own concrete fixed-origin manifest and
the same expiry/license/authorization/digest tests before enablement.

In-app notifications are durable owner-scoped rows and require no external
credential. Email/webhook are explicitly gated destinations. Delivery jobs,
outboxes, fenced leases and attempts are PostgreSQL authoritative. Retry the same
logical delivery key; adapters use provider idempotency when supported. External
exactly-once delivery cannot be invented: an ambiguous timeout after sending is
`unknown`, with a bounded reconciliation/retry policy and visible duplicate risk
when the provider cannot deduplicate. An accepted provider receipt is not proof
of end-user delivery. Neither notification nor report providers may access broker
transport, place orders, or turn plan lines into broker payloads.

## 7. Required adapter acceptance

Each concrete adapter ships typed capability/coverage declarations and replay
fixtures for happy/empty/partial data; missing dates; stale observations;
unsupported basis; FX direction/missing pair; source correction; duplicate
retrieval; unresolved/ambiguous entity; malformed schema; oversized payload;
pagination loops; rate limits; timeouts; transient/permanent/auth failures;
license-denied storage/display/export; and absent credentials. Negative tests
prove no dispatch on unknown inputs and no boundary bypass through redirect,
DNS, alternate IP representation, proxy environment, arbitrary continuation or
provider response URLs. Canary tests scan exception chains, serialized results,
logs, persistence, caches and report/export bytes.

Fixture manifests include schema version, fixed clock, deterministic ordering,
source/license versions and semantic digests. Committed fixtures are synthetic
or explicitly licensed and sanitized; no real credentials or account data.
Provider selection must not change application/domain methods or weaken the
architecture checker. Local Compose acceptance executes real persistence,
worker restart, replay ingestion, reporting and in-app notification paths;
unconfigured real-provider status is recorded separately from local completion.

## P2-05 constituent and classification publication contract

Keep fund definitions and immutable fund_source_mappings separate from price/
benchmark market_source_series. `ConstituentRequest.fund_series_id` retains its
existing spelling but binds an immutable fund source-mapping ID. ConstituentPage
and ClassificationPage echo the complete typed request, including original subject,
effective_at, source_cutoff_at and continuation; classification requests additionally
bind the exact 1..100 instrument set and taxonomy/version. Requested and actual
snapshot effective dates are distinct fields. Older eligible data can be stale;
future-effective data or first knowledge after cutoff is excluded.

The store assigns trusted first_observed_at/receipt; caller economic dates cannot
backdate knowledge. Select sources effective at/before valuation and known at/before
cutoff, with applicable validity intervals and pinned provider/revision/ambiguity
policy. Explicit eligible entity classification wins; otherwise applicable evidenced
instrument assignments must agree for that entity/taxonomy/version. No issuer-parent,
exchange-country, ticker-only or listing-to-economic-currency inference. Receipt
ratios do not multiply already valued money. Corrections append and restatements
identify their changed cutoff/version; current latest never retargets replay.

Require first continuation null, each next request equal the previous response
continuation, no cycles/duplicates and one final null, at most 100 pages of 1,000
rows and 100,000 total rows. Validate the entire chain before atomic seal: owner,
provider, license, fund mapping, actual normalized subjects, source revision/
provenance, unique row keys and coverage. An echo cannot relabel same-owner F1 as
F2. Nonnegative exact weights must sum <=1; known/cash/unresolved header totals
reconcile to row states and implicit 1-sum missing mass is retained exactly once.
A text evidence key alone is not a registered identity relationship.

Authorized internal principal-first registration/ingestion uses analytics:read plus
targets:write, keyword idempotency_key/correlation_id, closed typed payloads and
atomic header/children/digest/receipt/command-result/audit publication. Same key and
payload replays one result; changed payload conflicts. A separate identical-economic
retrieval reuses the source and appends one receipt without changing first knowledge
or retention. Invalid chains create no partial source or successful command result.
Workers authorize before typed provider fetch; persistence accepts fetched typed
pages and has no transport dependency. Read endpoints use retained data only.

Check pinned and current store/display/report/export permissions at their respective
boundaries. Expiry/revocation denies immediately even during delayed physical purge.
Inventory X-ray canonical/exact-state, normalized and derived projection copies;
share existing expiry budgets and charge additional bounded physical row/byte work.
No provider credentials or raw payloads enter domain inputs, logs or public output.
