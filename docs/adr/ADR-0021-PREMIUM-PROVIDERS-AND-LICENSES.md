# ADR-0021: Typed premium providers and explicit entitlements

**Status:** Accepted implementation decision, 2026-09-14

Choose Alpha Vantage market/ETF/reference/news adapters and ECB reference FX, with
existing transport isolation and source-policy/retention services. No arbitrary URL
interface. Exact schemas/routes/bounds are in [provider contracts](../integrations/PHASE_3_PROVIDER_CONTRACTS.md).

AV documentation is not an account license. Default terms restrict personal/noncommercial
use; shared/commercial access needs agreement. No account-specific storage/redistribution
license or credential was provided: production starts blocked_external, local synthetic
contracts remain executable. No subscription or paid call is authorized.

ECB reuse requires attribution, accurate reproduction, marking changes and additional
disclosure for paid redistribution. Pin inspected terms/version and explicit policy
grant; do not extend it to unrelated third-party articles. Rates are reference values.

Adapter implementation, replay validation, configuration and live verification are
separate states. Failover is explicit source selection with coverage comparison and
provenance, never a hidden assumption of equivalent data or permissions.


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
