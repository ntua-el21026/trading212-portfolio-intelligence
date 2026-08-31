# Master Implementation Plan

**Status:** Accepted  
**Delivery workflow:** Direct fast-forward commits to `main`  
**Release sequence:** `0.1.0` → `0.2.0` → `1.0.0`

## 1. Execution rules

- Implement phases in order.
- Read the entire current documentation baseline before Phase 1 and the active phase specification before each work package.
- Work directly on `main`; no branches or pull requests.
- Use small coherent commits that pass required gates.
- Re-read/synchronize `main` before each commit; never force-push.
- Update status/progress/checklists with implementation evidence.
- Do not implement later-phase behavior early except typed extension ports, schemas, and disabled feature flags explicitly required by the current phase.
- Do not hide missing credentials/provider access by weakening tests or inventing data.
- The Trading 212 boundary remains strictly GET-only throughout all phases.

## 2. Phase sequence

### Phase 1 — Trusted Foundation (`0.1.0`)

Outcome: a secure, runnable, testable foundation that can ingest/mock Trading 212 data, persist canonical history, reconcile/snapshot it, calculate trustworthy core portfolio/accounting/allocation results, and expose consistent basic API, web, and MCP surfaces.

Work packages P1-01 through P1-12 are fully specified in `PHASE_1_TRUSTED_FOUNDATION.md`.

### Phase 2 — Portfolio Intelligence (`0.2.0`)

Outcome: versioned virtual Pies/targets, drift and contribution-only optimization, historical market/benchmark performance, attribution, ETF look-through, reports/exports, alerts, and premium analytical views/tools.

Specified in `PHASE_2_PORTFOLIO_INTELLIGENCE.md`.

### Phase 3 — Premium Intelligence and Productization (`1.0.0`)

Outcome: advanced risk/scenario/projection/goal analysis, research cockpit, rich ChatGPT UI, installable polished PWA, premium provider adapters, extension readiness, security/performance/resilience hardening, and production release evidence.

Specified in `PHASE_3_PREMIUM_PRODUCTIZATION.md`.

## 3. Cross-phase tracks

These are continuous, not deferred cleanup:

- documentation/governance;
- security/privacy;
- data quality/provenance;
- deterministic calculations;
- tests/quality gates;
- observability/operations;
- accessibility/UX;
- API/MCP compatibility;
- dependency/license management;
- performance measurement;
- release/status evidence.

## 4. Dependency map

```text
P1 contracts/domain
  → persistence/migrations
  → provider adapter + ingestion
  → reconciliation/snapshots
  → accounting/allocation
  → application API
  → web + MCP
  → deployment/acceptance

Phase 1 canonical history
  → Phase 2 targets/optimizer
  → market/benchmark/performance
  → X-ray/reports/alerts
  → premium UI/tools

Phase 2 history/exposure/providers
  → Phase 3 risk/scenarios
  → projections/goals
  → research/rich UI
  → product hardening/release
```

Where possible, work packages may overlap only after their dependency contracts are committed and stable.

## 5. Release gates

A phase release requires:

- every mandatory work package accepted;
- progress/status files accurate;
- all locally executable gates green at the exact release SHA;
- migrations/contracts/documentation synchronized;
- no unresolved critical/high security defect;
- no hidden partial/mock-only claim;
- external credential/deployment gates explicitly passed or listed as the only remaining verification, depending on release objective;
- known limitations and data coverage documented;
- reproducible build/container artifacts;
- release notes/change log.

## 6. Change control

A requirement discovered during implementation is handled as follows:

- implementation detail within freeze: document in owning spec and proceed;
- architectural choice not frozen: add accepted ADR before dependent code;
- conflict with design freeze: stop the affected work, document evidence and proposed superseding ADR; do not silently violate the freeze;
- external provider contract change: update official-contract evidence, integration contract, fixtures/tests, and status in one coherent sequence;
- scope expansion: assign to the correct phase; do not absorb into current phase by default.

## 7. Progress accounting

`PROJECT_PROGRESS.json` is the machine-readable source for phase/work-package state. Valid states:

- `not_started`
- `in_progress`
- `blocked_external`
- `blocked_internal`
- `implemented_unverified`
- `complete`

A package becomes `complete` only with linked/recorded evidence in the phase checklist or status document. Progress percentage is derived from accepted package weighting or equal package count until explicit weights are defined.

## 8. Codex usage

The phase prompt is a complete execution instruction but not a substitute for repository inspection. Codex must:

- treat current `main` as source of truth;
- inspect before coding;
- implement, test, document, and commit—not merely plan;
- resolve non-material details using documented principles;
- ask only for genuinely external information that cannot be represented as a safe adapter/mock/gate;
- leave the repository in a runnable, validated state after every commit;
- report exact commands, tests, commit SHAs, remaining external gates, and no unsupported completion claims.
