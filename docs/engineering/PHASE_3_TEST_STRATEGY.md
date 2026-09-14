# Phase 3 Test Strategy

**Status:** Accepted design; execution evidence pending

Ten packages,30 acceptance rows,48 scenarios. Completion requires actual selectors,
commands and retained immutable source-bound evidence. Planned tests are obligations,
not results. Preserve complete Phase1/2/StageA tests without weakened checks.

Numerical fixtures independently cover rational variance/beta/contributions, singular/
anticorrelated matrices, cash-flow/FX, fractional tails and deterministic projection
timing. Validate CDF/inverse/sampler golden values with an independent justified
high-precision oracle, not production helpers. Test hostile Decimal contexts/restoration,
bounds/failures, input permutation, path chunks/retries and conditional conservation.

Real PostgreSQL checks constraints/scopes/immutable versions, concurrent semantic
replay, quotas, revoked licenses, checkpoints/fencing/cleanup. Empty install and upgrade
from 20260911_0016 converge; repeat is idempotent. Restore a genuinely empty DB.
Redis/outbox/worker faults require durable counts/canonical hashes after restart.

Real RS256/ES256/EdDSA API/MCP tests retain exact issuer/audience/identity and malformed
claims/ID regressions; cover every scope and foreign ref. Providers use realistically
shaped synthetic payloads and injected DNS/redirect/status/timeout/budget/rights faults,
without paid/live calls. Generated API/clients, MCP and reports share canonical output.

API-backed browser tests cover old/new journeys and quality states, CSP/injection,
forms/keyboard/charts, desktop/tablet/mobile and actual CacheStorage/network behavior
across offline/logout/owner changes. Mock worker responses alone are insufficient.

Focused gates then milestones, final make validate plus security/image/SBOM/provenance/
signing/restart/clean restore/measured budgets at one immutable source/tree. Preserve
failed attempts/logs/JUnit/coverage/browser originals. Later evidence equivalence checks
content/type/mode; executable governance is not a documentation-only change.

Serial laptop tests, one scoped Compose project, only necessary services. Record exact
versions/fixtures/commands/timing/output hashes. Portable pack separates local validation,
independent review, deferred CI and unverified production. Targets become claims only
when measured.
