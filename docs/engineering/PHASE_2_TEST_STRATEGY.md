# Phase 2 Test Strategy

**Status:** Accepted

**Date:** 2026-09-07

## Inherited gates

Keep every meaningful Phase 1 test and validator active, including hard collection
capacity, export URL minimization, revision handling, reconciliation, authorized
API/MCP parity and refresh outbox recovery. Current exact evidence is in the
[Phase 1 audit record](../implementation/PHASE_1_AUDIT_CORRECTIONS.md).

Use repository targets: `make bootstrap`, `make format-check`, `make lint`,
`make typecheck`, unit/property/contract/integration/migration/security/coverage
and browser targets, `make docs-check`, `make generated-check`,
`make security-check`, `make build`, `make container-build`, and `make validate`.
Extend actual test discovery and existing CI workflows as Phase 2 arrives. New
contract gates must fail on missing/unknown registry entries, stale generated
schemas, absent acceptance evidence or an unauthorized transport import.

## Calculation and provider tests

Reference fixtures are hand-calculable and independently assert money conservation,
weight/hierarchy normalization, solver constraints, objective/status, stable tie
breaks, missing/zero distinctions, no-sale behavior, currency/period alignment,
external-flow separation, return/attribution residuals and X-ray exposure totals.
Hypothesis covers varied dimensions, increments, currencies, cutoffs and boundary
values with controlled examples/seeds where useful. Do not test only a transcription
of the implementation formula or weaken an invariant to pass.

Typed replay providers include revisions, duplicate observations, non-trading days,
gaps, missing FX, stale inputs, forbidden look-ahead, mixed currencies, conflicting
classifications/licenses and malformed schemas. Unit tests never depend on live
network. Optional live/provider tests are separate credentialed external gates.

## Service, database and durability tests

Use disposable PostgreSQL databases through existing uv-managed fixtures. Verify
empty-to-head, previous accepted head to new head, repeated upgrades, ORM drift,
normalized tables, exact numeric/UTC constraints, immutable input enforcement,
owner/account foreign keys, uniqueness and required indexes. Test concurrent
idempotency/preconditions and report/alert claims with independent sessions.

Kill or pause workers after durable request commit and after confirmed publication;
restart to prove the same job recovers and creates each effect once. Exercise
expired leases, bounded retries, unavailable Redis, dead letters, retention and
access-denied-before-cleanup. Full Compose stop/restart must preserve canonical
values, counts, job/artifact/evaluation IDs and volume identity.

## Web, API and MCP parity

Strict generated OpenAPI/TypeScript compilation is mandatory after each API change.
Test auth, every new scope, CSRF, IDOR, version/idempotency conflicts, typed errors,
bounded durable pagination and state changes during active traversals.

Vitest/Testing Library verifies forms, keyboard behavior and server-value rendering.
Playwright runs desktop/mobile with retries disabled, real API-backed workflows,
search/sort/filter/cursor URL state, browser back/forward, empty/stale/partial/
unavailable/unreconciled/failed states and accessible tabular chart alternatives.
Check WCAG2.2AA-target semantics, focus, labels, contrast, reduced motion and no
horizontal overflow. Keep actual screenshot baselines for important Phase 2 routes;
record platform/font assumptions and review differences rather than blindly update.

All 25 MCP tools require exact schemas/scopes/annotations, unknown-field rejection,
canonical decimal strings/metadata, cross-owner denial and bounded results. Commands
must return persisted IDs and safely replay idempotency. Widgets require versioned
resources, strict CSP, keyboard/table fallbacks and no arbitrary external fetch.
API/web/MCP/report values are compared against the same stored source inputs.

## Security and release acceptance

Run Semgrep, full-history Gitleaks, pip-audit, production pnpm audit, Trivy
filesystem/configuration/license and all six image scans with recorded exact
versions/policies. Preserve package-manager absence, non-root and rootfs hardening.
Canary scans must inspect compressed browser artifacts and all report formats.
Add formula-injection, source-license denial and webhook SSRF/DNS/redirect negatives.

Record actual query plans and representative local timings without claiming
production capacity. All 40 mandatory scenarios require executable evidence at the
same immutable release SHA. Tests not run, external prerequisites and unresolved
failures are named explicitly. Coverage remains branch-aware; the existing 85%
Phase 1 observed result is a regression reference, not a fabricated Phase 2 result.
