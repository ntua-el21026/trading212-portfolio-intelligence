# Phase 2 Acceptance Matrix

**Contract status:** Accepted design closure, 2026-09-07

**Implementation acceptance:** In progress; P2-01 through P2-06 locally complete; 16/29 local rows; remaining Phase 2 CI deferred by owner

**Target release:** `0.2.0`

**P2-01 evidence SHA:** `ecc75154397c8f9d7532fa2df8576846b60bae7c`

**P2-02 evidence SHA:** `f78c9d2917c3ce8c93f9ae5631390c59616abc82`

**P2-03 evidence SHA:** `e258f54bb03a958f7847b310ee882b7f4a54686f`

**P2-04 evidence SHA:** `2a7c89a9b8c37d97006dafbbe97a44eec37b3fe0`

**P2-05 evidence SHA:** `7b102663ea193b4668924a7252180731954f4b00`; final Phase 2 release SHA pending

**P2-06 local evidence SHA:** `9e39767b408b38203d88d6e5b41bf0bc1265adfb`; GitHub Actions deferred, not passed; final Phase 2 release SHA remains pending. [Evidence](evidence/phase-2-p2-06-9e39767.json).

The owner assignment authorizes P2-01 through P2-10 after corrected Phase 1
acceptance at `99df47b6633791c3900a52f46f56d48be922a436`. That SHA proves Stage A;
it does not prove any Phase 2 behavior. The design contract is accepted while
P2-01 through P2-05 retain their accepted evidence; P206 has scoped local acceptance with owner-deferred CI. Later/shared predicates remain pending or in progress, including partial P2-S34 and P2-S38.

## Current owner-authorized CI exception

P2-06 has scoped local acceptance at `9e39767b408b38203d88d6e5b41bf0bc1265adfb`. GitHub Actions is deferred by explicit owner instruction; no CI pass is claimed. The complete required local gates, exact source bindings and deferred startup observations are retained in the P206 acceptance evidence. Remaining Phase 2 implementation continues under that recorded deferral until the owner resumes CI verification.

Normal exact-source CI requirements remain the default. This dated exception changes only their current prerequisite status, preserves every required local gate and remains explicitly outstanding for verification after owner resumption.

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
| P2-PERF-001 | P2-04 | TWR, MWR and Modified Dietz follow frozen methods, correct external-flow treatment, explicit unavailable roots/coverage and no browser/model financial computation. [Exact-SHA assertion map](evidence/phase-2-p2-04-2a7c89a.json). | 15, 16, 18 | `complete` |
| P2-PERF-002 | P2-04 | Benchmark composition, calendars/currency alignment, excess/rolling metrics and attribution reconcile to total plus disclosed residual without invented precision. [Exact-SHA assertion map](evidence/phase-2-p2-04-2a7c89a.json). | 15, 17, 18, 34 | `complete` |
| P2-INC-001 | P2-04 | Dividend/income, fees/taxes and cash-flow views retain original currencies and sourced conversion; purchases/sales are not investment gain. [Exact-SHA assertion map](evidence/phase-2-p2-04-2a7c89a.json). | 16, 19, 34 | `complete` |
| P2-XRAY-001 | P2-05 | Versioned ETF constituents and explicit entity/share-class/ADR/listing mappings produce direct/indirect/effective exposure without double counting. ADR-0017 Decimal256/Q18 role bounds, exact money/unit conservation, post-carry NUMERIC limits and lowest real-root representative policy are independently verified, including zero money and the global path budget. [Exact-source assertion map](evidence/phase-2-p2-05-7b10266.json). | 20, 21 | `complete` |
| P2-XRAY-002 | P2-05 | Overlap, classifications and concentration retain unresolved weight, coverage, confidence, source dates and stale/partial quality. Exact thresholds, lower-bound versus unavailable states, per-dimension normalization and same-run projection parity hold; 496 is per request and collection-owned pair/common retention is capacity/TTL/physical-purge bounded. [Exact-source assertion map](evidence/phase-2-p2-05-7b10266.json). | 22, 23, 34, 38 | `complete` |
| P2-RPT-001 | P2-06 | Every required report type and PDF/CSV/JSON/XLSX format has a reproducible canonical manifest, shared service values, source/method/quality/license metadata and bounded private artifacts. [Local exact-source assertion map](evidence/phase-2-p2-06-9e39767.json). | 24, 27, 34 | `complete` |
| P2-RPT-002 | P2-06 | Durable report/export jobs are idempotent, authorized, expiry/cleanup-aware and audited; downloads reauthorize each access; safe filenames/content types and size limits are enforced. [Local exact-source assertion map](evidence/phase-2-p2-06-9e39767.json). | 25, 31, 32, 40 | `complete` |
| P2-RPT-003 | P2-06 | Rendered PDF and structured/archive export content excludes secrets/signed URLs; CSV/XLSX formula injection and restricted-source export attempts are rejected or safely encoded. [Local exact-source assertion map](evidence/phase-2-p2-06-9e39767.json). | 26, 27 | `complete` |
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

## P2-04 observed evidence

P2-04 is complete at `2a7c89a9b8c37d97006dafbbe97a44eec37b3fe0`. The [accepted assertion map](evidence/phase-2-p2-04-2a7c89a.json) closes P2-PERF-001, P2-PERF-002, P2-INC-001 and P2-S14 through P2-S19. Shared P2-S34 remains `in_progress`: historical API/web/MCP parity is partial evidence; report/export and remaining shared scope are outstanding.

The clean exact-source `make validate` passed in 1165.723 seconds: 1,346 isolated and 175 service-backed Python tests, 88% combined statement/branch coverage, 203 web unit tests and 66 browser checks. A separate unchanged-source `env CI=1 PW_TEST_REPORTER=list T212PI_E2E_TIMINGS=1 make test-e2e build-web` passed in 366.184 seconds, retaining all 66 named browser passes and a successful web build with clean source before and after. The original full-gate GitHub reporter lacked individual browser names; the supplement adds that evidence without replacing the full gate or its image-build provenance. Pytest selectors are assertion inventory bound to observed complete test-file execution.

Exact pushed-source CI passed: Quality `34272112673`, Documentation `34272112714`, Security `34272112661`. Eight source/history/image scans passed under their retained scanner policies. Fresh runtime attempt 003 passed in 170.757 seconds: six historical HTTP reads, four MCP reads, configured web journeys and identical retained rows across all 101 inventoried tables after all seven services stopped/restarted. Task containers, volume and network were removed, with cleanup verified. Migration head is `20260907_0012`; the implemented inventory is 66 HTTP operations and 19 MCP tools; Trading 212 remains the exact ten GET-only capabilities.

See [runtime](evidence/phase-2-p2-04-2a7c89a-runtime.json), [security](evidence/phase-2-p2-04-2a7c89a-security.json) and [compatibility](evidence/phase-2-p2-04-2a7c89a-compatibility.json). At this P2-04 acceptance boundary, Phase 2 had four of ten packages (40%), eleven of 29 local rows and eighteen of 40 scenarios complete; later packages and Phase 3 were not_started. Current P2-05 acceptance is recorded below; no final Phase 2 release SHA is claimed.

Source-backed known P2-08 limitations remain: the complete seed now has four accounts including the X-ray fixture, but Compose does not forward the documented T212PI_ACCOUNT_ID setting to web; unconfigured multi-account overview startup is not accepted. The accepted runtime used an explicit baseline-account scratch override. The global header must respect the authorized route account. Sticky-header section positioning, readable mobile labels and table presentation remain P2-08/S39 follow-up work. Configured runtime acceptance does not prove default unconfigured multi-account UI behavior.
P2-05 authority synchronization registers `xray_v1` 1.1.0 and
`xray_decimal256_exact_q18_v1` under [ADR-0017](../adr/ADR-0017-DECIMAL256-EXACT-XRAY.md).
That authority synchronization supplied requirements only; prior scratch arithmetic
results were not implementation acceptance. P2-05 now has the separate exact-source
acceptance recorded below.
P2-S34 remains shared with P2-06 report parity; Phase 3 remains not_started.

## P2-05 historical observed evidence

At the P205 closure boundary: P2-05 is **complete** at `7b102663ea193b4668924a7252180731954f4b00`. The [accepted assertion map](evidence/phase-2-p2-05-7b10266.json) closes P2-XRAY-001/002 and P2-S20 through P2-S23. Phase 2 has five of ten packages (50%), thirteen of 29 local rows and twenty-two of 40 scenarios complete. P2-S34 and P2-S38 remain `in_progress`; report/export parity and the remaining release-wide predicates are outstanding. P2-06 through P2-10 and Phase 3 remain `not_started`.

The clean exact-source `make validate` passed in 2339.747 seconds: 1,642 isolated and 234 service/migration Python tests, 88% combined statement/branch coverage, 223 web unit tests and 76 browser checks without retries. Assertion selectors are source mappings bound to completed test-file observations.

Exact-source CI passed: Quality `34347516142`, Documentation `34347516068`, Security `34347516074`. Eight source/history/image scans passed under the recorded scanner policies. The fresh runtime passed in 146.262241 seconds, preserving identical retained rows across all 167 compared tables and API/MCP replay after all seven services stopped/restarted. Task containers, volumes and networks were removed, with absence verified. All eight exact-gate screenshots received the recorded visual review.

See [runtime](evidence/phase-2-p2-05-7b10266-runtime.json), [security](evidence/phase-2-p2-05-7b10266-security.json), [compatibility](evidence/phase-2-p2-05-7b10266-compatibility.json), [screenshots and visual review](evidence/phase-2-p2-05-7b10266-screenshots.json) and [observed count derivation](evidence/phase-2-p2-05-7b10266-counts.json). Earlier failed candidates remain unaccepted. External broker/provider/deployment gates, the documented P2-08 UI follow-ups and the null final Phase 2 release SHA are unchanged.

## P2-06 scoped local acceptance

P2-06 has scoped local acceptance at `9e39767b408b38203d88d6e5b41bf0bc1265adfb`. GitHub Actions is deferred by explicit owner instruction; no CI pass is claimed. The complete required local gates, exact source bindings and deferred startup observations are retained in the P206 acceptance evidence. Remaining Phase 2 implementation continues under that recorded deferral until the owner resumes CI verification.

The [finalized local artifact](evidence/phase-2-p2-06-9e39767.json) closes only the P206-owned rows and scenarios. Current totals are 16/29 local rows and 26/40 scenarios. Reporting contributes partial evidence to shared scenarios; later packages remain pending.

### Historical P206 implementation observations

The following earlier development observations and requirements are retained as history. They are not a new CI obligation during owner deferral or replacement exact-source acceptance evidence.

P2-06 began from synchronized `5ff85b4436ec9be886639e6e2cf0c722fc0c4a73`.
The [implementation contract](P2_06_REPORTS_AND_EXPORTS.md) describes the current
working implementation. The September 9 working remainder gate passed 1,914 isolated
and 277 service/migration coverage tests at 88%, 86 serial browser checks and the
remaining documentation/security/build stages. Earlier interrupted and failed gates
remain recorded in [project status](../../PROJECT_STATUS.md). These observations
precede the final navigation correction and do not constitute a clean exact-SHA gate.
Subsequent navigation checks passed 301 web unit tests and four browser journeys
per viewport, with final web lint/typecheck/build passing. The mobile run preceded
only the CSS correction to its hidden desktop sidebar; final-source validation
and visual review remain separate. Root reviewed the eight working screenshots
with their documented full-page mobile capture limitation.
At that earlier boundary, no P2-RPT row was accepted and totals remained thirteen rows and twenty-two scenarios. Current local acceptance uses the complete corrected-source local gates, scans, runtime and visual review, with the separately retained owner CI deferral.
P2-07 through P2-10 and Phase 3 remain `not_started`.
