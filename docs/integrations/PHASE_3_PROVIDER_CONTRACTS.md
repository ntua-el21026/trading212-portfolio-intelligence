# Phase 3 Provider Contracts

**Status:** Accepted implementation contract; live integrations unverified

[ADR-0021](../adr/ADR-0021-PREMIUM-PROVIDERS-AND-LICENSES.md) selects these adapters.
Preserve Phase 2 transport, secret-manager and license boundaries. No acquisition
from public caller URL/function/credential/symbol; trusted immutable canonical mappings
resolve allowed subjects. Primary documentation checked on 2026-09-14:
[AV API](https://www.alphavantage.co/documentation/),
[AV terms](https://www.alphavantage.co/terms_of_service/),
[ECB rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html),
[ECB copyright](https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html).

Public documentation supports selection, not account licensing. AV terms restrict
personal/noncommercial use; account-specific commercial/storage/export permissions
need explicit entitlement evidence. ECB requires attribution, accurate reproduction,
changes marked and freely-available-original disclosure for paid redistribution.
No logo/endorsement inference. Missing rights means blocked_external, not connected.

## Closed GET acquisition registry

| Provider/capability | Fixed origin/route | Strict selectors and normalized meaning |
| --- | --- | --- |
| alpha_vantage / daily_adjusted | https://www.alphavantage.co/query | function=TIME_SERIES_DAILY_ADJUSTED, trusted symbol, outputsize=full, datatype=json; daily raw/adjusted close, dividend and split |
| alpha_vantage / etf_profile | https://www.alphavantage.co/query | function=ETF_PROFILE, trusted symbol; metrics/holdings with coverage disclosure |
| alpha_vantage / company_overview | https://www.alphavantage.co/query | function=OVERVIEW, trusted symbol; normalized issuer facts/classification |
| alpha_vantage / news_sentiment | https://www.alphavantage.co/query | function=NEWS_SENTIMENT, one trusted ticker, bounded time_from/time_to, sort=LATEST, limit<=100; minimized events/citations |
| ecb / reference_fx | https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml | No query/caller path; EUR-base dated reference rates within actual feed coverage |

AV apikey resolves immediately before transport through the secret port. Never log or
persist request URL/query/auth. Never follow article/banner URLs. Reject redirects,
private/mixed DNS, unapproved TLS peer/host or changed origin before body acquisition.
Use existing validated/pinned transport; method/path/query rejection precedes DNS.

## Parsing, basis and provenance

AV decoded body <=8 MiB; requested daily rows<=3661, ETF holdings<=10000, news<=100
items with minimized item<=16 KiB and text fields<=4096 chars. Reject duplicate JSON
keys, nonfinite/binary financial numbers, wrong subject/currency, conflicting dates,
missing required fields and excess nesting/rows. Provider rate/error envelopes are
typed failures, not empty successful finance. Select only documented needed fields;
discard raw metadata and article URLs. No raw-body retention.

Daily adjusted data preserves raw versus adjusted price/dividend/split semantics.
Do not assume undocumented reinvestment timing or economic currency. Canonical
historical action/total-return policy must authorize consumption. Date-only market
observations require trusted exchange calendar/session end and first-known retrieval
time. Missing timing metadata is unavailable for then-known analytics. Current ETF
holdings without an as-of date are observed-at-retrieval, never historical constituents.
Company classifications require explicit economic identity mapping. News UTC provider
timestamps must satisfy publication<=retrieval cutoff; retain publisher/title, source
identity and internal citation ID, not provider URLs.

ECB XML<=1 MiB, <=100 dates, <=40 currencies/date. Require expected namespaces/Cube
structure. Reject DTD/entities/external references before XML parsing, duplicate
currency/date, nonpositive/oversized rates and invalid dates. One EUR equals quoted
currency amount; cross-rate divides common EUR-base legs with both sources retained.
Date-only first-known time is retrieval, not invented historical publication time.
No weekend fill or claim of history beyond the selected 90-day feed.

## Costs, failover and retention

Outbound default disabled. Enabled AV requires credential, licensed capability policy
and positive durable daily allowance; local cap 25/day and one in flight. ECB cap 24/day
and one in flight. Every attempt reserves per-provider/owner budget before transport.
Connect/read/total deadlines5/10/20 seconds, <=3 attempts with deterministic1s/2s
backoff. Honor Retry-After<=60s through scheduled retry, not worker sleeping; total
budget wins. No retries for credential/schema/entitlement/policy denial.

Pin provider, adapter/method/request digest, observed/retrieved/first-known times,
coverage, source policy and entitlement version. Fallback needs an explicit compatible
ordered source set and returns source/rejection/coverage comparison. Never substitute
incompatible currency/calendar/basis/cutoff. Reauthorize license/owner before retained
replay/export. Default source retention<=30 days or actual stricter grant; material
derivatives inherit minimum expiry. Revocation denies reads immediately, then bounded
physical cleanup removes forbidden copies.

States: not_configured, blocked_external, ready_unverified, verified_live, degraded,
unavailable. Synthetic fixtures approximate documented payload shape and never set
verified_live. Production configuration/smoke is distinct from local adapter completion.


### Status and compatible fallback clarification (accepted 2026-09-15)

GetPremiumProviderStatus exposes the fixed two providers/five capabilities after
current account and portfolio/analytics authorization. It performs no credential
lookup or provider request. A configured Alpha Vantage credential port proves
configuration presence only; it never establishes that a secret exists or works.
Absent port configuration is not_configured. Metadata-eligible configured
capabilities remain ready_unverified, with credential/live verification unavailable.
Synthetic fixtures never establish verified_live. Subject, mapping, licence evidence
and credential identifiers are not part of the public status representation.

Disabled-by-default fallback accepts at most four explicitly ordered retained
canonical price or FX candidates plus at most one matching fixed-provider
acquisition. Exact currency, calendar and version, basis, period and then-known
cutoff must agree. Differing periods reject unless independently supported bounded
coverage is actually read. Compare actual full-request coverage, original source
identity/quality/lifetime and fixed examined/rejected/unexamined outcomes. Do not
blend partial rows or present unexamined coverage as measured. A requested live
source never receives a synthetic replacement. Alpha Vantage and ECB serve distinct
families and are not interchangeable alternatives. Acquisition preserves its
original request group, digest, quota and deadline across retry; fallback never
creates a new group to evade them. No provider or public acquisition route is added.
