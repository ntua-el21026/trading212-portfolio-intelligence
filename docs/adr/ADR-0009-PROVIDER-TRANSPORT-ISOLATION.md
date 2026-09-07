# ADR-0009 — Provider-Specific Outbound Transport Isolation

**Status:** Accepted

**Date:** 2026-09-07

**Authority:** Current owner's Phase 2 design assignment

## Context

Phase 2 needs market, FX, benchmark, constituent, report-storage and notification
adapters. Phase 1 intentionally confines outbound broker access to ten typed GET
capabilities. Extending that client or exempting a generic provider namespace
from architecture checks would weaken the permanent read-only boundary.

## Decision

Adopt dedicated typed capability ports and family-specific concrete adapters
under [Phase 2 provider contracts](../integrations/PHASE_2_PROVIDER_CONTRACTS.md).
Broker transport, configuration, credentials and its ten-capability allowlist
remain sealed. No generic `request(method, path)`, arbitrary URL proxy, provider
DTO response, or application-accessible transport abstraction is introduced.
Domain/analytics/application/API/MCP/web cannot import outbound HTTP libraries.
Architecture rules grant narrowly named adapter-module exceptions and test that
other modules remain denied.

Before a concrete HTTP adapter is enabled, commit and validate its fixed trusted
HTTPS origins, typed capability/path/method manifest, parameter schemas,
timeouts/retries/rate/page/body bounds, credential references and license policy.
Disable redirects/environment proxies; enforce pre-dispatch allowlists, public
address validation and DNS-rebinding protection. Provider continuation is opaque
adapter state and cannot supply a new URL. Notification/storage writes exist
only through their dedicated internal ports and cannot reach broker credentials.
Webhook destinations are trusted server configuration referenced by opaque IDs.

Default local adapters are working deterministic replay implementations, real
PostgreSQL artifact storage and durable in-app delivery. Missing external
credentials yield explicit unavailable state; no paid provider is required for
local completion. A replay implementation must execute its full typed semantics,
not return a fake successful empty result. Provider DTOs remain transient;
minimization precedes provenance hashing and strips secrets/signed URLs and raw
payload derivatives. Stable errors cannot retain raw exception causes/contexts.

## Consequences

Provider families can evolve without granting a broker write path. Every enabled
adapter needs isolated contract, mapping, privacy/license, SSRF, rate/pagination,
error, canary and architecture tests. Additional package/module boundaries are
deliberate and inspectable. License/configuration gates remain visible while
synthetic fixtures prove the locally executable feature end to end.

## Rejected alternatives

- A general HTTP provider service: allows callers to select unreviewed paths and
  merges broker and nonbroker authority.
- Reusing or widening the Trading 212 client: changes the permanent product
  boundary and risks exposing broker write capabilities.
- Broad transport-import checker exemptions: lose enforceable adapter isolation.
- Requiring live paid credentials before local work: unnecessary because typed
  replay and explicit unavailable configuration preserve truthful behavior.

## Verification obligation

Before implementing dependent provider code, the design commit must contain this
accepted decision. Subsequent acceptance must demonstrate unchanged ten-GET
broker dispatch, denied unknown methods/paths/parameters, isolated transports,
fixed origins, safe error chains, replay parity and real durable local workflows.
