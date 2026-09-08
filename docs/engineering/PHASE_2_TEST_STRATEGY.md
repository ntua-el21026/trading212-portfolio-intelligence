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

## P2-05 Decimal256, representative and retention obligations

[ADR-0017](../adr/ADR-0017-DECIMAL256-EXACT-XRAY.md) and Methods section 6 define
`xray_v1` 1.1.0 / `xray_decimal256_exact_q18_v1`; this checklist is future evidence,
not a claim that any P2-05 implementation or tests already exist.

- Independently reconstruct complete synthetic graphs with Fraction/integer test
  oracles; production financial coefficients and every operation remain Decimal.
  Check role bounds, exact unit and available-money conservation at every node,
  complete totals, per-original-position duplication and consolidated HHI/min/max.
- Exercise the precision 80 midpoint counterexample, both signed odd/even ties and
  either side, recurring ratios, bounded equivalent zero encodings and huge-exponent
  zero rejection before arithmetic; post-carry NUMERIC overflow at both signs,
  all context traps and hostile ambient/DefaultContext on success and failure.
  Private coefficients never use the ordinary Q18 decoder or leak to public schemas.
- Retain the A=.56/B=.39/unknown=.05, overlap=.50, duplication=.41, HHI=.4657 fixture,
  real position/cash roots, evidenced share-class/ADR/listing paths and saved Money/FX
  without double conversion. Test separate unknown classification dimensions and K=0.
- Zero-valued lowest representative remains selected even if truncated while a later
  occurrence is complete. Prove independent unit conservation, no best-root/union/
  second traversal/backfill, path-specific cycles versus diamonds, depth4/5 and the
  single global 10,000-path/pending-root budget. Complete initial-root overflow fails.
- Separate supported disjoint exact zero, zero lower bound with unknown actual overlap,
  sub-Q18 positive common/unknown, zero/unavailable monetary basis with valid unit
  composition and unestablishable/unauthorized bases. Test exact threshold equality,
  just-below/above, strict/inclusive operators, unconfigured, partial proved breach
  and partial inconclusive states; display residuals never repair missing mass.
- Permute equivalent source input order and project A/B versus A/B/C, Page/Top/view/
  dimension/normalization on one run: exact canonical values, representative keys,
  uses, conversions, primitives/policy identities and source provenance must agree.
  Distinct actual snapshots or transport envelopes are not falsely byte-equivalent.
- Reject same-owner wrong-subject provider pages, changed echoes, incomplete/repeated
  continuation chains, oversummed/negative weights, future-effective or later-known
  sources, conflicting classifications, missing scopes and license revocation.
  Test trusted first knowledge, atomic idempotency, current authorization before
  decode/replay/cursor/cache/304 and exact normalized/canonical row binding.
- Exercise >32 held-fund discovery and successive comparison subsets: <=496/request
  is not lifetime storage. Durable pairs/common entities require active collection
  ownership, charged parent bindings, shared 64/250,000 capacity and original TTL;
  transient MCP Top creates no permanent cache. Expire references and prove bounded
  physical cleanup of all exact-state/canonical/normalized/projection copies under
  shared capture/run plus row/byte budgets. Exhausted cleanup leaves indexed pending
  source work and immediate access denial, never a premature purge-complete marker.
- Maximum legal singleton path proofs fit 2 MiB; larger requested pages reject safely
  without lost membership or hidden truncation and remain reachable at smaller limit.
  Restore all bound data/IDs/canonical values across restart. API/web/MCP use the same
  stored values; P2-06 report parity and P2-07 alerts remain separate acceptance work.
