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
