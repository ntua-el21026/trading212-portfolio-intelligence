# Phase 2 Acceptance Matrix

**Contract status:** Accepted design closure, 2026-09-07

**Implementation acceptance:** In progress; P2-01 through P2-03 complete

**Target release:** `0.2.0`

**P2-01 evidence SHA:** `ecc75154397c8f9d7532fa2df8576846b60bae7c`

**P2-02 evidence SHA:** `f78c9d2917c3ce8c93f9ae5631390c59616abc82`

**P2-03 evidence SHA:** `e258f54bb03a958f7847b310ee882b7f4a54686f`; final Phase 2 release SHA pending

The owner assignment authorizes P2-01 through P2-10 after corrected Phase 1
acceptance at `99df47b6633791c3900a52f46f56d48be922a436`. That SHA proves Stage A;
it does not prove any Phase 2 behavior. The design contract is accepted while
P2-01 through P2-03 have passed their scoped acceptance; later and shared predicates remain `pending`.

## Evidence and state rules

`pending` means implementation or required evidence is absent. `in_progress`
means work has begun without complete acceptance. `complete` requires exact
executable test nodes, observed command results, retained non-secret artifacts,
and an immutable implementation SHA. `blocked_external` and
`unavailable_explicit` describe external predicates only; neither counts as a
local pass. Tests and evidence paths must exist before a row cites them.

The [scenario ledger](PHASE_2_SCENARIO_EVIDENCE.md) defines all 40 mandatory
predicates. A package may complete only after its relevant vertical capability,
negative tests, migration/generated-contract changes, interfaces, documentation,
and real gates pass. Full Phase 2 acceptance additionally requires all 40
scenarios, the complete registry, all Phase 1 regressions, exact-SHA local and CI
gates, and final release evidence. A design commit cannot close a runtime row.

## Locally executable acceptance rows

| ID | Package | Required acceptance | Scenario mapping | State |
|---|---|---|---|---|
| P2-TGT-001 | P2-01 | Owner-scoped hierarchical virtual portfolios include cash, holding/group constraints, exclusions, effective dates, archive/template behavior, stable ordering and explicit unresolved mappings. | 1, 4, 5, 32 | `complete` |
| P2-TGT-002 | P2-01 | Published target versions are immutable; changes create a new version; comparison, optimistic preconditions and audit remain deterministic under concurrency. | 2, 3, 4 | `complete` |
| P2-TGT-003 | P2-01 | Target validation rejects invalid sums/contradictions; normalization follows the accepted exact-decimal tolerance policy and preserves mapping/duplicate-exposure warnings. | 4, 5 | `complete` |
| P2-OPT-001 | P2-02 | Actual-versus-target and drift use immutable target/portfolio references and disclose cash, hierarchy, unmatched exposure, currency, methodology and coverage. | 6, 34, 38 | `complete` |
| P2-OPT-002 | P2-02 | Global, hierarchical, restricted and explicit cash-only planning conserve the contribution, prohibit sales, obey hard constraints and produce deterministic residual cash. | 7, 8, 9, 11 | `complete` |
| P2-OPT-003 | P2-02 | Hand-calculated and exhaustive bounded reference cases validate objective/tie-breaks; infeasibility and degraded inputs remain structured; immutable plans and concurrent safe retries never call a broker. | 10, 11, 12, 37 | `complete` |
| P2-SRC-001 | P2-03 | Typed price/FX/benchmark/metadata adapters provide fixed trusted origins, bounded parsing/retries and isolated egress; deterministic replay works without external credentials. | 13, 14, 36, 37 | `complete` |
| P2-SRC-002 | P2-03 | Immutable sources preserve time, currency, revisions, gaps, corporate-action basis, provenance/license/export policy and cutoff-safe FX precedence. | 13, 14, 18, 38 | `complete` |
| P2-PERF-001 | P2-04 | TWR, MWR and Modified Dietz follow frozen methods, correct external-flow treatment, explicit unavailable roots/coverage and no browser/model financial computation. | 15, 16, 18 | `pending` |
| P2-PERF-002 | P2-04 | Benchmark composition, calendars/currency alignment, excess/rolling metrics and attribution reconcile to total plus disclosed residual without invented precision. | 15, 17, 18, 34 | `pending` |
| P2-INC-001 | P2-04 | Dividend/income, fees/taxes and cash-flow views retain original currencies and sourced conversion; purchases/sales are not investment gain. | 16, 19, 34 | `pending` |
| P2-XRAY-001 | P2-05 | Versioned ETF constituents and explicit entity/share-class/ADR/listing mappings produce direct/indirect/effective exposure without double counting. | 20, 21 | `pending` |
| P2-XRAY-002 | P2-05 | Overlap, classifications and concentration retain unresolved weight, coverage, confidence, source dates and stale/partial quality. | 22, 23, 34, 38 | `pending` |
| P2-RPT-001 | P2-06 | Every required report type and PDF/CSV/JSON/XLSX format has a reproducible canonical manifest, shared service values, source/method/quality/license metadata and bounded private artifacts. | 24, 27, 34 | `pending` |
| P2-RPT-002 | P2-06 | Durable report/export jobs are idempotent, authorized, expiry/cleanup-aware and audited; downloads reauthorize each access; safe filenames/content types and size limits are enforced. | 25, 31, 32, 40 | `pending` |
| P2-RPT-003 | P2-06 | Rendered PDF and structured/archive export content excludes secrets/signed URLs; CSV/XLSX formula injection and restricted-source export attempts are rejected or safely encoded. | 26, 27 | `pending` |
| P2-ALT-001 | P2-07 | Immutable versioned rules cover every approved portfolio/data/report family with deterministic input snapshots, quality gating and no trading signals. | 28, 38 | `pending` |
| P2-ALT-002 | P2-07 | Scheduling, event deduplication, cooldown, acknowledgment/resolution, safe retry/dead-letter and in-app history survive concurrent workers/restart. | 28, 29, 31, 40 | `pending` |
| P2-ALT-003 | P2-07 | Optional email/webhook ports are unavailable when unconfigured; configured destinations are verified, bounded, HTTPS-only outside test mode and protected against SSRF/DNS rebinding/redirects. | 30, 31, 37 | `pending` |
| P2-WEB-001 | P2-08 | All 18 owner-required analytical/editor/report/alert/source/settings experiences use generated clients, canonical services and explicit quality states with durable deep links and navigation. | 34, 38, 39 | `pending` |
| P2-WEB-002 | P2-08 | Desktop/mobile keyboard, focus, accessible names, reduced motion, chart/table alternatives, no horizontal overflow, browser navigation and critical visual regression gates pass. | 39 | `pending` |
| P2-MCP-001 | P2-09 | The exact 25-tool registry preserves nine existing tools and exposes fourteen new reads plus two bounded internal commands with strict schemas, exact scopes and truthful annotations. | 33, 34, 36, 37, 38 | `pending` |
| P2-MCP-002 | P2-09 | Plan/report commands persist authorized durable IDs with idempotency and audit; resources use strict CSP; unknown fields/tools, injection, cross-owner data and broker access fail closed. | 12, 26, 31, 33, 37 | `pending` |
| P2-API-001 | P2-01–09 | Additive typed `/api/v1` resources enforce owner/account scopes, command CSRF/idempotency/preconditions, stable errors, decimal strings and synchronized OpenAPI/TypeScript output. | 32, 34, 38 | `pending` |
| P2-DATA-001 | P2-01–10 | Empty/prior-head/repeated migrations, schema drift, indexes, constraints, exact NUMERIC/UTC, immutable provenance and retention/expiry pass on PostgreSQL. | 2, 14, 25, 31, 40 | `pending` |
| P2-SEC-001 | P2-10 | Every secret/canary/output/archive boundary, owner/scope denial, CSP, provider isolation and webhook SSRF negative passes; no generic SQL/URL/path/shell/browser tool exists. | 26, 27, 30, 32, 33, 36, 37 | `pending` |
| P2-REG-001 | P2-10 | All fourteen Phase 1 scenarios and F-01/F-02 tests remain green; ten GET capabilities and provider metadata minimization remain unchanged. | 35, 36, 37 | `pending` |
| P2-OPS-001 | P2-10 | Fresh Compose runtime, image hardening, readiness, metrics, replay/restart/retention and documented backup procedure pass; local load/query/index evidence states its measured limits. | 31, 40 | `pending` |
| P2-REL-001 | P2-10 | All forty scenarios and relevant lint/type/test/build/docs/security/accessibility gates pass at one immutable SHA; pushed quality/security/docs workflows are green; status/changelog truthfully record limits. | 1–40 | `pending` |

## External predicates, separate from local completion

| ID | Predicate | Current evidence boundary | State |
|---|---|---|---|
| P2-EXT-001 | Trading 212 Demo smoke with dedicated read-only credential | Stage A external credential gate remains open; Live remains disabled/untested and is not a local acceptance gate. | `blocked_external` |
| P2-EXT-002 | Production host, identity, secret manager and actual backup restoration | No owner-selected hosted deployment or production restore evidence supplied. Local adapters, configuration failure behavior and runbooks remain mandatory. | `blocked_external` |
| P2-EXT-003 | Public HTTPS/OAuth MCP and ChatGPT registration | No configured public endpoint/registration supplied. Local authenticated protocol and widget tests remain mandatory. | `blocked_external` |
| P2-EXT-004 | Real-provider opening-history reconciliation | No complete real-provider opening basis; retain explicit coverage limitations and synthetic evidence provenance. | `unavailable_explicit` |
| P2-EXT-005 | Licensed real market/FX/benchmark/ETF data | No required paid source/credential/license supplied. Synthetic providers and export-restriction enforcement remain local acceptance requirements. | `unavailable_explicit` |
| P2-EXT-006 | Actual email/webhook delivery and remote object storage | No configured verified destination/provider credentials supplied. Local evaluation, in-app delivery, fake-adapter replay and private PostgreSQL artifacts remain required. | `unavailable_explicit` |

## Release accounting

There are **29 local rows**, **40 mandatory scenarios** and **6 separately tracked
external predicates**. At design closure, zero Phase 2 local rows/scenarios are
accepted. No external unavailable predicate blocks secure synthetic/local
implementation. Phase 3 remains `not_started`.

## P2-01 observed evidence

P2-01, P2-TGT-001 through P2-TGT-003, and P2-S01 through P2-S05 passed at
`ecc75154397c8f9d7532fa2df8576846b60bae7c`. The [retained assertion map](evidence/phase-2-p2-01-ecc7515.json)
binds each predicate to exact tests, observed local commands and all three successful CI runs.
The [runtime record](evidence/phase-2-p2-01-ecc7515-runtime.json) contains fresh Compose
activation, API/MCP parity and full restart hashes; the [security record](evidence/phase-2-p2-01-ecc7515-security.json)
retains source/history and six immutable-image scans with their policy limitations.
Shared authorization, parity, accessibility and release-wide restart scenarios remain pending
until their complete Phase 2 predicates pass. Phase 3 remains `not_started`.

## P2-02 observed evidence

P2-02, P2-OPT-001 through P2-OPT-003, and P2-S06 through P2-S11 passed at
`f78c9d2917c3ce8c93f9ae5631390c59616abc82`. The [assertion map](evidence/phase-2-p2-02-f78c9d2.json)
retains 197 collected cases, 17 rational reference cases, 175 observed property
examples, full local validation and all three successful exact-SHA CI runs.
The [runtime record](evidence/phase-2-p2-02-f78c9d2-runtime.json) proves all four
modes, immutable API/MCP revisions, real Redis message-loss recovery and unchanged
44-table state after a full seven-service restart. The [security record](evidence/phase-2-p2-02-f78c9d2-security.json)
binds source/history and six image scans to that clean build. The [earlier failed
CI candidate](evidence/phase-2-p2-02-5fa43b2-failed-quality.json) remains unaccepted.
P2-S12 has a passing broker-transport spy for the planning path; its shared P2-09
predicate remains pending. Later packages and full-release acceptance remain required.

## P2-03 observed evidence

P2-03, P2-SRC-001, P2-SRC-002 and P2-S13 passed at
`e258f54bb03a958f7847b310ee882b7f4a54686f`. The [assertion map](evidence/phase-2-p2-03-e258f54.json),
[fresh runtime record](evidence/phase-2-p2-03-e258f54-runtime.json),
[security scans](evidence/phase-2-p2-03-e258f54-security.json) and
[compatibility comparison](evidence/phase-2-p2-03-e258f54-compatibility.json) retain actual
local/CI results, exact synthetic observations, immutable history, cursor reuse
and seven-service restart. The two failed harness attempts (cursor issue-time comparison and aggregate
pagination capacity) are retained separately from the corrected fresh runtime. Three packages, eight
local rows and twelve scenarios are complete; P2-S14/P2-S36 and later/shared
predicates remain pending. Phase 3 remains `not_started`.
