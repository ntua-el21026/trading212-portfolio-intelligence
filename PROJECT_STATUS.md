# Project Status

**Project:** Trading 212 Portfolio Intelligence

**Repository:** `ntua-el21026/trading212-portfolio-intelligence`

**Implementation authority:** `main`

**Updated:** 2026-11-13

## Current state

The owner authorized a bounded stabilization and aggregation recovery assignment
on 13 November. The [current record](docs/implementation/PHASE_3_STABILIZATION_20261113.md)
separates reproduced baseline failures, corrections and actual validation from
the historical observations below. The assignment begins at clean synchronized
`64e2057cb9b1ddee11649f605e968b18bd559fcb`; final validation and independent review
remain pending. All 30 Phase 3 acceptance rows and all 48 scenarios remain pending.

The first complete stabilization target failed on stale physical-retention test
expectations. Strengthened focused source/enrichment/risk and migration checks
pass at their recorded sources. The second attempt was interrupted for four
confirmed preflight mismatches; their focused corrections pass. The third has an
incomplete unit-test log with no completion receipt or verified termination cause.
The fourth was interrupted for durable orchestration after 1,198 passing unit
cases and no observed runtime failures. The fifth passed 4,744 Python unit tests,
918 web unit tests, 36 property tests and 357 contract tests, then stopped in
integration with 151 passes and one expired report-fixture failure. Its later
stages were not reached. Fresh runtime-source fixtures preserve historical
financial facts, the full 732-day risk reference trace, explicit availability
cutoffs and negative controls. Three focused report selectors passed; the same
four-selector invocation retained a replay failure exposing a production deadline
clamp that omitted the original physical source's copy limit. The narrow metadata
correction is implemented and six focused deadline/replay cases pass. The broader
43-case run finished with 40 passes and three fixture failures in the scenario
report file. Its FX-adapter and unsucceeded-root setup corrections passed the
separate four-case rerun; those receipts do not constitute a new 43-case pass.
Privacy and bounded cleanup have focused passes.
A new immutable complete target remains pending.
Production guards, historical economic dates and retention budgets remain
unchanged; internal peer review does not replace the pending owner audit.
The current schema retains 364 ORM tables through forward migration `0034`.

The sixth complete target at `6502a5a` passed formatting, linting, typing and 4,744
Python unit cases, then failed the web suite with 917 passes and one owner-layout
retry-test failure. Later stages were not reached. The corrected owner-layout
file passed its four focused cases, but the next full web suite retained a
different scenario retry-test failure with 917 passes and one failure. Test-only
readiness corrections across five form files then passed 32 focused cases and the
complete 918-case/103-file web suite on unchanged source. All 104 original
assertions remain; the three adjacent risk/research/aggregation gaps were static
findings rather than observed runtime failures. A new immutable full target
remains pending. The failed target's Python result and corrected web pass remain
separate evidence.

The seventh complete target at `c907cac` passed static checks, 4,744 Python unit
cases, 918 web unit cases, 36 property cases and 357 contract cases. Integration
then stopped with 353 passes and one signed projection MCP discovery failure;
later stages were not reached. An unchanged-source focused reproduction located
the stale 36-tool assertion. The accepted current contract adds exactly
`get_research_summary` and `get_research_item`, producing 38 authorized tools.
Three current-runtime discovery tests now use an independent exact-name oracle
for the preserved 25-case catalogue and 13 explicitly named additions, including
duplicate rejection. All 50 focused projection/risk/real-JWT cases passed in
138.02 seconds. Historical isolated 32/36-tool contracts, product code and all
authentication, financial-parity, replay, paging and secret assertions remain
unchanged. A new immutable complete target remains pending.

The eighth complete target at `32777c7` passed 4,744 Python unit cases, 918 web
unit cases, 36 property cases and 357 contract cases, then stopped with 284
integration passes and one X-ray partial-cleanup failure. A parent lookup spent
its final inspection allowance before discovering that a returned identity
required another inspection. The corrected production loop checks for both
allowances before SQL and otherwise retains pending work. Two deterministic
one-short regressions failed before the fix; all 31 focused unit cases and nine
PostgreSQL X-ray cases then passed. Original budgets, ownership predicates,
anti-forgery guards, the full-oracle canary and bounded resumption checks remain.
The reason earlier runs avoided this exact remainder is unverified. The next
complete attempt collects all failures within a test stage without changing its
scope, failure exit status or resource limits. Full validation remains pending.

### Historical September save point

The owner requested a resumable checkpoint on 2026-09-30. The aggregation
vertical and saved FX observation picker are preserved as work in progress,
with 364 ORM tables through migration 0030 and 136 API paths/161 operations/578
schemas. At that save point, aggregation run publication failed the PostgreSQL
native-component proof guard; runtime/browser acceptance was pending. The previous
344-table provider/layout observations below remain scoped to their earlier source. See the
[checkpoint and exact resume steps](docs/implementation/PHASE_3_RESUME_20260930.md).
Phase 3 acceptance, production authorization and deferred GitHub Actions status
are unchanged.

Phase 2 is **accepted by the owner for progression** to Phase 3. The accepted
corrected source is `f88b0199b2d8691ff89101b7991e9bb0fea1d1ca`, tree
`5ac0dba52e369a30a32a2d7d5b41409e12fc0911`; its observed delivery and this
assignment's clean starting main are `d2ebdaf96d1b61aacea5c6492824946540f88803`.
The owner-reported independent code review found R-01/R-02 corrected and no new
blocker within its inspected scope. It did not independently inspect the full
local archives or rerun every gate. This decision is progression authority,
not independent full-release verification.

Phase 3 is in progress toward `1.0.0`. P3-01 now has canonical history and a
complete calculation object, normalized storage, bounded durable worker, typed REST
operations, a generated client, shared physical retention and the authenticated risk
workspace. Web component tests and the actual API/isolated-worker browser flow pass;
The three risk MCP tools and sixth resource are implemented with signed transport
and widget component checks. Versioned premium risk reports now share the existing
worker, artifact pipeline and retention controls. Their local component gates pass:
3,371 Python tests, 614 web tests, three real browser viewports and 145
PostgreSQL cases across the broad run and corrected-fixture rerun. Package-wide verification remains pending.
P3-02 now includes immutable scenario versions, retained source-bound runs, a fenced
worker, authenticated REST/web/MCP results, saved comparisons and four-format reports.
At that delivered component, migration 0021 retained 254 normalized tables; the API
had 109 paths/123 operations/441 schemas and MCP had 32 tools/seven resources;
the original contracts and ten broker GETs remain preserved. Explicit report profile3
copies complete saved scenario/risk evidence while default profile2 and V1 remain
compatible. The current report component passed 4,329 Python tests, 707 web tests,
15 final schema/retention PostgreSQL cases and three actual production browser
journeys. Ten distinct additional artifact/source cases have passing executions
across retained gates. P3-03 now includes saved assumptions/goals, normalized capture
and results, an isolated worker, authenticated REST/MCP and a paged web workspace.
At that checkpoint the ORM inventory had 321 normalized tables through migration
0026; the generated API had 127 paths/148 operations/533 schemas, and MCP
has 38 tools/eleven resources. Projection report profile4 passed actual
PDF/CSV/JSON/XLSX browser journeys at three widths, preserving complete saved
values, source proof and legacy profiles. Research now has bounded authorized
PostgreSQL pages, REST/client/web and MCP views; 16 runtime/page/retention cases,
three real web journeys and 17 packaged widget browser cases passed at their
recorded working sources. The complete research summary uses twelve SQL statements;
this is not a claim for all single-item/write operations or latency acceptance.
P3-06 public-only offline support and the account-safe command palette passed three
production browser journeys. Only five public static assets enter its cache;
private HTML/API/reports remain network-only. Owned saved layouts, bounded provider acquisition, provider status and explicit
source fallback were implemented with component validation. That historical
provider/layout component had 344 normalized tables through migration 0029 and
131 API paths/154 operations/550 schemas. Saved layouts and provider settings
passed production browser journeys at three widths, including exact-value parity,
keyboard/overflow and serious/critical axe checks. All five saved-layout PostgreSQL
cases, three provider-status cases and four corrected UTC-rollover/fallback cases
have passing executions at the recorded sources. The rollover test explicitly
simulates a consistent clock in its disposable database; production clock guards
remain unchanged. Aggregation, research reports and alert physical-retention
closure remain in progress. Provider credentials and live access stay unverified. Migration 0026 adds guarded risk/scenario
physical counters and bounded cleanup; 19 actual PostgreSQL cases passed for migration, counter/cleanup and source-copy
regressions, including the concurrent-capture report correction. All 48 additional
compatibility selectors have passing executions across the broad and targeted
receipts, with each failed predecessor preserved. The final isolated checkpoint
passed 5,129 Python tests, 831 web tests and all included static, generated-contract
and repository checks in 506.768 seconds with unchanged source.
These are component observations with exact source boundaries in the implementation
report. All package, acceptance, SLO and independent-review predicates remain pending.
Final local validation remains pending; independent review will remain pending for the new
candidate. GitHub Actions is `deferred_by_owner`, unverified. Production
release/deployment, paid-provider purchases and Live are not authorized.

The [transition decision](docs/implementation/evidence/phase-3-owner-authorization-20260914.json)
and [ADR-0018](docs/adr/ADR-0018-OWNER-AUTHORIZED-PHASE-TRANSITION.md) authorize
all P3-01 through P3-10. The additive [Phase 3 freeze](docs/DESIGN_FREEZE_V1_0.md) now defines ten packages,
30 acceptance rows and 48 scenarios. No package has
local acceptance yet. The unchanged baseline has migration `20260911_0016`,
87 API paths / 95 operations, 25 MCP tools and exactly ten Trading 212 GET
capabilities, observed by local runtime introspection before edits.

### Current and historical machine selectors

[PROJECT_STATUS.json](PROJECT_STATUS.json) and
[PROJECT_PROGRESS.json](PROJECT_PROGRESS.json) use schema version 2.

| Selector | Meaning |
| --- | --- |
| `phase_transition` | Closed owner decision, progression scope, accepted f88b019 source/tree, d2ebdaf delivery and immutable evidence binding. |
| `current_candidate` | Phase 3 / 1.0.0; implementation in progress, final local validation pending, independent review pending. |
| `current_evidence` | Only this Phase 3 candidate's actual evidence; null while pending. No old pass is copied into it. |
| `production_readiness` | `not_authorized`, independent of local implementation and owner progression. |
| `historical_evidence.phase_2` | Original 3998426 local report, not the corrected source or Phase 3 result. |
| `phase_transition.evidence` | Retains corrected f88b019 local evidence separately from the narrower owner-reported independent code review. |
| Legacy Phase 2 acceptance / packages / percentage | Preserved 10 packages, 29 acceptance rows and 40 scenarios at their original source. |
| Legacy Phase 2 `current_implementation` / `candidate_validation` | Historical f88b019 remediation observations, explicitly scoped by `legacy_evidence_scopes`. |
| Legacy Stage A identity and `release_readiness` | Historical source and external-condition observations, unchanged. |

The closed candidate/evidence fields from schema 1 remain compatible, now
identifying Phase 3 and an empty remediation findings list. The baseline is
observed d2ebdaf. Null source requires null tree/delivery and pending validation
with no artifact. A local pass requires a new immutable source/tree and a
repository JSON reference with exact path/SHA256/byte binding and matching
source/tree/result. It sets `implemented_pending_independent_review`, never
owner or independent acceptance. New completed packages require scoped evidence.

Documentation delivery is separate from the implementation SHA and remains null
inside its own commit; record its actual hash and content/type/mode equivalence
externally after delivery. Retained artifacts and the
[prior selectors](docs/implementation/evidence/phase-3-start-d2ebdaf.json) preserve
what was reported before this explicit transition. The
[validator](scripts/validate_repository.py) checks consistency, not execution or
reviewer approval. Its historical schema-1 regression fixtures retain the old
pending-remediation rules.

### Delivery recommendation

A main ruleset is recommended and **not configured**: allow ordinary direct
pushes, prohibit force pushes and deletion, and require linear history. This is
nonblocking; no repository administration change is claimed.

### Historical reported local release and prior observations

The retained statements below describe prior local reports at their original
sources and observation times. Their completion/acceptance language does not
establish unconditional independent Phase 2 acceptance or validate R-01/R-02.
Immutable artifacts, test counts and coverage retain their original provenance.

P2-10 implementation covers the remaining authorization and canonical parity checks, query telemetry, bounded retention, operations evidence and release metadata. Working-tree observations remain in the [validation report](VALIDATION_REPORT.md#p210-working-tree-verification). Final immutable P210 local acceptance is recorded separately in [final P210 local evidence](docs/implementation/evidence/phase-2-p2-10-3998426.json) at 3998426aa7e7614e421518efd01b08188e194100; working-tree observations remain historical.

Prior immutable source `03105f4d36b0457600dfc5ab6fb13b0308820027` passed full `make validate` in 7,298.293 seconds and source security in 36.446 seconds, but image security failed in 8.861 seconds: PostgreSQL 33 High/Critical findings and Redis 12. All 70 original /tmp captures were lost after the WSL reboot, so visual recovery/review remains pending. [Retained failure, coverage and diagnostic evidence](docs/implementation/evidence/phase-2-p2-10-03105f4-failed-security.json) preserves those results without acceptance.

ROOT's subsequent focused PostgreSQL/Redis build passed in 14.706 seconds; patched two-image scans and runtime-image package-manager checks passed in 4.983 seconds. Both gates observed unchanged working trees. These are separate working-source observations. Corrected immutable P210 local acceptance at 3998426aa7e7614e421518efd01b08188e194100 is recorded separately in [final P210 local evidence](docs/implementation/evidence/phase-2-p2-10-3998426.json); earlier working passes and the 03105f4 failed-security/capture-loss observation remain historical.

P2-09 is complete with P2-S33 authorization evidence at `bd47329cca5c1409486fff40d48e92163ab4a8af`. P2-MCP-001 and P2-MCP-002 retain their scoped evidence at `d70ab445de38aee255275880c5ef7a105ebbb939`. Phase 2 is locally complete at 3998426aa7e7614e421518efd01b08188e194100: 10/10 packages (100%), 29/29 local rows and 40/40 scenarios. P2-10 and the shared local predicates are complete under the final same-source acceptance. Phase 3 remains not_started. GitHub Actions remains owner-deferred and unverified, with no CI pass claim. The final Phase 2 release evidence SHA is 3998426aa7e7614e421518efd01b08188e194100. See [final P210 local evidence](docs/implementation/evidence/phase-2-p2-10-3998426.json).

[P209/S33 supplement](docs/implementation/evidence/phase-2-p2-09-s33-bd47329.json); finalized 2026-09-12T19:03:50.016115+00:00. The same-source relevant MCP, PostgreSQL, static, security, Python-build and single-MCP-image gates passed. The d70 full validation and browser/visual evidence remain historical; no new full validation, browser/visual gate or seven-service runtime is claimed.

[P209 scoped evidence](docs/implementation/evidence/phase-2-p2-09-d70ab44.json); finalized 2026-09-12T18:08:53.523669+00:00. The artifact retains actual widget/API browser observations as supporting evidence. It does not claim a new full Compose startup/restart, runtime cleanup, PDF visual gate or live ChatGPT registration.

The historical d70 artifact records 2545 isolated and 379 service-backed Python tests in its full gate, and 208 browser cases across its supplied reports. These observations are not rerun or attributed to the S33 supplement source. These are recorded populations, not an aggregate of overlapping runs. Python selectors describe source coverage supported by observed whole-file progress; actual widget cases and ROOT visual reviews remain bound in the artifact.

Historical P209 tracker values and validation/review history are retained in [the scoped archive](docs/implementation/evidence/phase-2-p2-09-d70ab44-implementation-history.json).

### Historical P209 implementation and focused verification

P2-09 implementation is in progress from accepted P208 closure
`9505e2650aadedd504a0a94117c018b0b7ed153f`. The integrated scope covers the exact
25-tool MCP registry, private argument errors and five bounded accessible widget
resources. P209 local acceptance remains pending. Phase 2 retains 8/10 accepted
packages (80%), 21/29 local rows and 30/40 scenarios complete. S32/S34/S38/S39
remain partial; S33 remains pending. P2-10 and Phase 3 remain `not_started`, the
final Phase 2 release SHA remains null, and GitHub Actions stays owner-deferred.

The tests-first privacy regression produced the intended RED against the original
adapter: nine failures for reflected caller-controlled names/values, 16 passes and
35 deselections (`p209-private-errors-red-01`, exit 1, 6.354 seconds). The source
was unchanged during that working-tree gate. The corrected registry gate passed 62 cases, existing MCP compatibility/security
checks passed 228, and both report/alert PostgreSQL cases passed after two retained
test-authoring failures. Static checks passed after a result-model type annotation
and removal of two redundant test casts; both preceding static failures are retained.
The corrected widget suite passed 74 desktop/mobile cases and the production web
build; ROOT reviewed the ten widget images, including two corrected planning
images. The first immutable full gate subsequently failed at the PDF pagination
assertion described below. A fresh immutable validation and source/image scans
remain pending. These earlier focused observations do not establish package acceptance.

The immutable `aa5a5f118ae41d334818621d16330333d5347c46` full gate failed in
2,305.073 seconds (exit 2), with 363 passes and one failure in the service-backed
session. The X-ray report assertion expected adjacent Record/Key text across a
PDF page boundary. The isolated case then passed in 41.429 seconds; a controlled
two-page renderer example reproduced the framing interruption in 1.132 seconds.
The initial raw-join helper produced three RED failures in 1.592 seconds.

The correction is confined to tests: verify and remove the outer page framing,
then retain exact record identity and metric assertions over the body text.
Identical header/footer text inside a canonical record remains intact. The focused correction gate passed all 47 selected tests in 327.098 seconds.
All nine reader regressions and static checks passed in 31.129 seconds after
formatting-only corrections; production rendering is unchanged.
See the [retained diagnostic chronology](VALIDATION_REPORT.md#p209-immutable-full-failure-and-pdf-correction).

See [P209 registry scope and validation](docs/integrations/P2_09_MCP_REGISTRY_ACCEPTANCE.md)
and [widget presentation boundaries](apps/mcp/WIDGET_PRESENTATION.md).

### Historical P208 scoped closure

P2-08 has scoped local acceptance at `bc21516c51aa5090031b39ea56ded3ca94d657d8` for P2-WEB-001 and P2-WEB-002. Phase 2 remains in progress: 8/10 packages (80%), 21/29 local rows and 30/40 scenarios complete. S32/S34/S38/S39 remain partial; S33 is pending. P2-09 and P2-10 remain required and `not_started`; Phase 3 remains `not_started`. GitHub Actions is owner-deferred, not passed. The final Phase 2 release SHA remains null.

[P208 scoped evidence](docs/implementation/evidence/phase-2-p2-08-bc21516.json); finalized 2026-09-12T14:12:14.532432+00:00. The finalized artifact records 2474 isolated and 377 service-backed Python tests in the full gate, and 157 browser cases across its supplied reports. These are recorded populations, not a new aggregate test count. Actual feature, browser and visual-review bindings remain in the artifact.

P208 evidence covers the actual API-backed web processes. It does not claim a new full Compose startup/restart, runtime cleanup proof or PDF visual gate.

### Historical P208 preparation before scoped closure

The following statements retain the original ff88406 overview failure/correction,
7201b53 full-gate pass and image-security rejection, and subsequent PCRE2 and
canonical-parity working observations recorded in source bc21516. They do not
describe the finalized acceptance artifact. See [archived tracker observations](docs/implementation/evidence/phase-2-p2-08-bc21516-implementation-history.json).

P2-08 implementation has started from P207 closure `7d3a5f59f30fe934953c7e3ab27d8e6ae48c1ca1`. Account navigation, analytical presentation, company exposure/report binding and intelligence-quality changes are integrated for validation. Contracts have been generated; no P208 acceptance is claimed. Seven packages remain locally accepted. GitHub Actions stays owner-deferred, and P209/P210 remain required.

Immutable P208 source `7201b5396c14ece3055710749ead3807b4e5652a` passed
`make validate` full02 in 8,459.812 seconds: 2,474 isolated and 377 PostgreSQL
cases, 88% branch-aware coverage, 539 web unit tests and 154 browser checks
(52 demo, 102 API across 39 API process reports). ROOT reviewed all 60 actual
feature captures. The separate security run `p208-security-7201b53-01` passed
the source/history scans and PostgreSQL/Redis image scans, but failed the API,
worker, MCP and web images. Each contains Debian bookworm `libpcre2-8-0`
`10.42-1`, with CVE-2026-86145 and CVE-2026-89161; the scanner reports
`10.42-1+deb12u1` as fixed. The four runtime Dockerfiles now install that exact
security package before package-manager stripping. Working-tree formatting, documentation, six serial image builds, package-manager
checks, six Trivy image scans and four fixed-package runtime probes passed in
62.736 seconds. Fresh immutable acceptance remains pending; no exceptions were added. P208 is unaccepted, and the accepted
P207 ledger remains 7/10 packages, 19/29 local rows and 30/40 scenarios.

[Failed security evidence with raw record hashes](docs/implementation/evidence/phase-2-p2-08-7201b53-failed-security.json).

The security correction is committed at `57eba18`. Focused canonical-parity checks
passed for 24 actual browser cases across three viewports, company HTTP/MCP run
pinning, and a four-format X-ray report. The planner also exposes exact target
and post-contribution weights alongside their rounded display. Fresh immutable
validation remains required; S34 and P208 acceptance remain partial/pending.

The following overview-correction observations preceded the full02 result.

P2-08 implementation commit ff884065e896209563d1966865602e73b3622fd6 passed
the complete local gate in 6,771.536 seconds, including fresh 88% branch-aware
coverage (2,474 isolated and 377 PostgreSQL cases), 534 web unit tests and 154
browser checks (52 demo, 102 API across 39 process reports). ROOT then reviewed
all 60 feature captures and found a mobile overview defect: an unreconciled
status with zero discrepancy records incorrectly claimed open discrepancies.
The desktop summary also counted the empty embedded issues collection instead
of the authoritative discrepancy count.

The correction preserves the actual status and canonical count in both layouts.
Five new regression cases failed before the fix; all eight overview tests and
all 539 web unit tests now pass. Three focused API browser viewport checks,
production build, formatting, web lint/types and documentation checks passed.
The first focused browser attempt exposed a test fixture assumption: standalone
fixtures contain two discrepancy records, while the full workspace sequence
reaches zero. The corrected browser assertion compares the UI to the actual API
response. Fresh immutable validation and acceptance evidence remain required.
The preceding failed clock-fixture coverage attempt is retained as historical
evidence in the P208 implementation document.

P2-07 has scoped local acceptance at `03c3c5b0b8182aadaaf48ec29131ab7fe83095a7`: versioned alert rules, immutable scheduled evaluation, event deduplication/cooldown, authorized lifecycle/history, bounded delivery and canonical alerts exports. Phase 2 is in progress: 7/10 packages (70%), 19/29 local rows and 30/40 scenarios complete. S31 includes both report/alert durable recovery and actual Redis-loss republication of the same pending alert input. Shared API/DATA/SEC/OPS and S32/S34/S38 predicates remain partial; At the P207 acceptance boundary, P2-08 through P2-10 and Phase 3 were `not_started`. GitHub Actions is owner-deferred and unverified; no CI pass or final Phase 2 release is claimed.

Actual completed gate summaries record 2352 isolated and 338 service-backed Python tests, 88% combined Python coverage with branch measurement, 345 web unit tests and 100 local browser checks. The full gate took 5416.926 seconds; fresh runtime took 256.28724 seconds. All six immutable images and the exact source/history scans passed; all seven runtime services restarted and scoped cleanup verified absence.

[Finalized local evidence](docs/implementation/evidence/phase-2-p2-07-03c3c5b.json). ROOT's closure records local package scope; external conditions and final-release evidence remain unchanged.

### Historical package observations before this closure

The following working/no-acceptance statements retain their original source and observation time. They do not describe the accepted 03c3c5b candidate.

Stage A is **complete** at `99df47b6633791c3900a52f46f56d48be922a436`. F-01 and F-02 are closed;
all 24 locally executable acceptance rows and 14 mandatory synthetic scenarios,
all three workflows, all local gates, and the fresh Compose acceptance passed.
Python verification: 371 isolated plus 73 service-backed tests and 85% coverage.
Migration head: `20260907_0008`; MCP: nine tools; Trading 212: ten GET capabilities.
Phase 2 is `in_progress`: P2-01 is complete at
`ecc75154397c8f9d7532fa2df8576846b60bae7c`. Its three local acceptance rows and
five scenarios passed. Its domain, persistence, API, web, MCP and
scheduled activation passed full local validation, all three CI workflows and a
fresh seven-service restart. Verification recorded 592 isolated and 103
service-backed Python tests, 86% coverage, 48 web unit tests, 32 synthetic browser
tests and 12 API-backed browser tests, with no browser retries. Migration head is
`20260907_0009`; the implemented MCP registry contains 11 tools. The original
implementation's two Gitleaks test-code false positives were corrected with exact
historical fingerprint exceptions in the accepted SHA and all gates rerun.
See [the P2-01 evidence](docs/implementation/evidence/phase-2-p2-01-ecc7515.json).
P2-02 contribution planning is **complete** at
`f78c9d2917c3ce8c93f9ae5631390c59616abc82`. Its four-mode Decimal solver,
normalized requests/results, fixed durable job, six API operations, four MCP
tools and drift/planner web routes passed exact local validation with 790
isolated and 129 service-backed Python tests, 87% combined coverage with branch
measurement, 111 web unit tests and 52 browser tests without retries. Seventeen
rational optimizer reference cases and 175 observed property examples passed.
All three CI workflows and eight source/history/image security scans passed.
Fresh Compose acceptance preserved seven immutable plan revisions through
API/MCP rereads, recovered an actually lost Redis message using the same durable
job, and retained identical hashes for all 44 compared tables after stopping and
restarting all seven services. Migration head is `20260907_0010`; MCP has 15 tools;
Trading 212 remains ten GET capabilities. The initial candidate's failed quality
run `34144309940` is retained separately; the browser database isolation fix is
included in the accepted SHA. See [the P2-02 evidence](docs/implementation/evidence/phase-2-p2-02-f78c9d2.json).
P2-03 reference sources are **complete** at
`e258f54bb03a958f7847b310ee882b7f4a54686f`. Exact validation passed 1,004 isolated and
156 PostgreSQL/migration Python tests, 145 web unit tests, 56 browser tests and
88% combined coverage with branch measurement. All three CI workflows and eight
source/history/image security scans passed. The fresh Compose runtime exercised
all fourteen source HTTP operations, exact observation/database parity, immutable
benchmark history, old cursor continuation and a full seven-service restart.
The retained evidence distinguishes two unsuccessful harness attempts from the
corrected fresh acceptance: reissued cursor timestamps, then shared pagination
capacity exhausted by repeated earlier-package checks. The production source
and 64-view quota did not change.
Migration head is `20260907_0011`; MCP remains 15 tools and Trading 212 ten GET
capabilities. See [the P2-03 evidence](docs/implementation/evidence/phase-2-p2-03-e258f54.json).
P2-05 remains complete at `7b102663ea193b4668924a7252180731954f4b00`; its retained acceptance is unchanged.

P2-06 has scoped local acceptance at `9e39767b408b38203d88d6e5b41bf0bc1265adfb`. GitHub Actions is deferred by explicit owner instruction; no CI pass is claimed. The complete required local gates, exact source bindings and deferred startup observations are retained in the P206 acceptance evidence. Remaining Phase 2 implementation continues under that recorded deferral until the owner resumes CI verification.

Phase 2 has six of ten packages (60%), sixteen of 29 local rows and twenty-six of 40 scenarios complete. S34/S38 and other shared predicates remain partial; P2-07 is `in_progress`; P2-08 through P2-10 and Phase 3 remain `not_started`. [P206 local assertion map](docs/implementation/evidence/phase-2-p2-06-9e39767.json).

P2-07's full working-tree `make validate` passed in 5,242.552 seconds with
unchanged source: 1,988 Python unit, 36 property, 148 contract, 307 integration,
12 migration and 157 security tests; 345 web unit and 100 browser checks.
Combined coverage is 88%, and documentation, dependency audits, builds and six
runtime-image package-manager checks passed. The later review identified a
lifecycle replay authorization gap and temporal activity-proof edge cases.
The lifecycle correction passed all 22 focused PostgreSQL cases, Ruff and mypy.
The temporal correction passed 185 historical, alert, contract and PostgreSQL
regressions, plus Ruff and mypy. Actual failing regressions reproduce earlier-cutoff
ambiguity, late-chain eligibility and future-payment arrival before their fixes.
Raw observation times remain immutable; proof timing and economic eligibility are
separate. Earlier test-fixture failures remain classified in retained receipts.
A WSL restart interrupted the
first corrected lifecycle run; its incomplete log is retained separately from
the subsequent successful run. Earlier focused timeout/revision and browser
evidence remains separate. No P2-07 acceptance is claimed: clean immutable
validation, source/image scans and fresh runtime recovery evidence remain pending.
GitHub Actions remains deferred by owner instruction.

At the completed gate boundary, 544,194,011 bytes of inactive development output
and obsolete raw browser traces were removed after checking consumers and
retained evidence. Redis was removed when no longer needed. The existing task
PostgreSQL container is reused for focused checks; source, dependencies, accepted
evidence, failure records and production build output were preserved.

For the historically accepted P205, the clean exact-source `make validate` passed in 2339.747 seconds: 1,642 isolated and 234 service/migration Python tests, 88% combined statement/branch coverage, 223 web unit tests and 76 browser checks without retries. Assertion selectors are source mappings bound to completed test-file observations.

P205 exact-source CI passed: Quality `34347516142`, Documentation `34347516068`, Security `34347516074`. Eight source/history/image scans passed under the recorded scanner policies. The fresh runtime passed in 146.262241 seconds, preserving identical retained rows across all 167 compared tables and API/MCP replay after all seven services stopped/restarted. Task containers, volumes and networks were removed, with absence verified. All eight exact-gate screenshots received the recorded visual review.

See [runtime](docs/implementation/evidence/phase-2-p2-05-7b10266-runtime.json), [security](docs/implementation/evidence/phase-2-p2-05-7b10266-security.json), [compatibility](docs/implementation/evidence/phase-2-p2-05-7b10266-compatibility.json), [screenshots and visual review](docs/implementation/evidence/phase-2-p2-05-7b10266-screenshots.json) and [observed count derivation](docs/implementation/evidence/phase-2-p2-05-7b10266-counts.json). Earlier failed candidates remain unaccepted. External broker/provider/deployment gates, the documented P2-08 UI follow-ups and the null final Phase 2 release SHA are unchanged.

Real reference provider configuration/licensing remain unavailable.

### Earlier implementation and acceptance history
P2-04 implementation began at synchronized starting SHA
`05d01c7a9a9cb6cc3f351c3adbed2036f02b94a9`; scoped acceptance is recorded below. Earlier failed candidates remain unaccepted. Candidate
`6a2074141d9c7bdd8aa64e1710777d153c4996f5` failed historical browser load
limits and the PostgreSQL coverage job timeout in quality CI run `34165840790`;
its documentation and security workflows passed. The interrupted local exact-SHA
gate has no accepted completion. Correction `92dc0e445809737a766c7f211c5dfef42adf9f6a` passed complete local validation and CI PostgreSQL coverage,
but its monthly MWR browser filter still exceeded the load limit in quality run
`34245765983`. Correction `a573343bf2a17aa01642e9764d97eb74f77fcd27` passed
its complete clean-source local gate and CI PostgreSQL coverage. Its MWR and
income desktop journeys passed in CI, but the first benchmark/year filter still
exceeded the document-load limit. Correction
`f37e8de843419288bc7e4b7531de6cc9d4c9cedc` also passed the full clean-source local
gate and CI PostgreSQL coverage, but CI again received benchmark document headers
without completing the stream within 30 seconds. The same performance-to-benchmark
sequence passed locally with `CI=1`. Diagnostic revision
`4aa1e235a5abe0432ca00060d2b35ce31fb705fe` then identified 13.606 seconds in
benchmark calculation and 7.669 seconds in source-use publication in CI. The
benchmark request completed, but the subsequent composite snapshot heading
exceeded five seconds while two source reads ran consecutively. PostgreSQL
coverage, documentation and security passed; that candidate remained unaccepted. See the
[latest retained failed candidate](docs/implementation/evidence/phase-2-p2-04-4aa1e23-failed-quality.json).

P2-04 is complete at `2a7c89a9b8c37d97006dafbbe97a44eec37b3fe0`. The [accepted assertion map](docs/implementation/evidence/phase-2-p2-04-2a7c89a.json) closes P2-PERF-001, P2-PERF-002, P2-INC-001 and P2-S14 through P2-S19. Shared P2-S34 remains `in_progress`: historical API/web/MCP parity is partial evidence; report/export and remaining shared scope are outstanding.

The clean exact-source `make validate` passed in 1165.723 seconds: 1,346 isolated and 175 service-backed Python tests, 88% combined statement/branch coverage, 203 web unit tests and 66 browser checks. A separate unchanged-source `env CI=1 PW_TEST_REPORTER=list T212PI_E2E_TIMINGS=1 make test-e2e build-web` passed in 366.184 seconds, retaining all 66 named browser passes and a successful web build with clean source before and after. The original full-gate GitHub reporter lacked individual browser names; the supplement adds that evidence without replacing the full gate or its image-build provenance. Pytest selectors are assertion inventory bound to observed complete test-file execution.

Exact pushed-source CI passed: Quality `34272112673`, Documentation `34272112714`, Security `34272112661`. Eight source/history/image scans passed under their retained scanner policies. Fresh runtime attempt 003 passed in 170.757 seconds: six historical HTTP reads, four MCP reads, configured web journeys and identical retained rows across all 101 inventoried tables after all seven services stopped/restarted. Task containers, volume and network were removed, with cleanup verified. Migration head is `20260907_0012`; the implemented inventory is 66 HTTP operations and 19 MCP tools; Trading 212 remains the exact ten GET-only capabilities.

See [runtime](docs/implementation/evidence/phase-2-p2-04-2a7c89a-runtime.json), [security](docs/implementation/evidence/phase-2-p2-04-2a7c89a-security.json) and [compatibility](docs/implementation/evidence/phase-2-p2-04-2a7c89a-compatibility.json). At the P2-04 acceptance boundary, Phase 2 had four of ten packages (40%), eleven of 29 local rows and eighteen of 40 scenarios complete. P2-05 subsequently entered implementation; the current scoped acceptance is recorded above. No final Phase 2 release SHA is claimed.

P2-05 implementation was integrated from synchronized authority SHA
`0ebbfa29253f418084835335eb2ee66f1b898679`; see the
[implementation record](docs/implementation/P2_05_PORTFOLIO_XRAY.md).
Working-tree verification passed formatting, lint, strict typing, 223 web unit
tests and all Python layers. The migration inventory assertion was corrected to
include the new revision, after which all 12 migration tests passed. The remaining
gate passed in 1,519.445 seconds: 1,642 isolated plus 225 service/migration tests,
88% combined statement/branch coverage, all 76 browser checks, documentation,
security checks, native/web builds and six container builds. Source was unchanged
during that gate. Focused cases cover exact arithmetic, real 40-fund discovery,
independent 496-pair selections, sourced FX gaps, cleanup liveness and both deferred
publication seals. Screenshot review corrected two unstyled X-ray buttons using
the shared UI component. Final review then added storage-permission and source-expiry
checks at new run/projection/collection publication boundaries; all nine dedicated
PostgreSQL regressions passed, followed by all 54 X-ray integration cases in
447.68 seconds and strict mypy across 389 files. The subsequent affected gate
passed 279 selected unit/property/contract tests, 100 security tests, six X-ray
browser checks, all static/docs checks, native/web builds, Semgrep and six container
builds with unchanged source in 247.142 seconds. These remain working-tree observations. They did not establish committed-source
acceptance; the separate final accepted evidence is linked above.
The housekeeping policy requires serial verification, one reused task Compose
project, and removal of disposable artifacts at stage boundaries while retaining
source and acceptance evidence.

Initial P2-05 implementation `b9b75ec54fe94fdcec627d8e31ca94700ccb08ad` is
unaccepted: security CI `34340985984` flagged a verified non-secret synthetic
policy label. The exact historical fingerprint exception and redacted CI
diagnostics are documented in the [failed-candidate record](docs/implementation/evidence/phase-2-p2-05-b9b75ec-failed-security.json).
The corrected local history scan passed all 86 commits. Its exact local full gate
was deliberately interrupted after 176 integration passes; completed layers and
interruption evidence are retained, with no full-gate acceptance claimed. The
corrected candidate still required fresh exact-source validation, CI, scans and runtime at that boundary.

Candidate `b2b0466cc150ac14cd3893fd823a7b84b084d7d9` passed security,
documentation and browser CI, but all 54 X-ray integration cases failed during
fixture setup: a bare PostgreSQL URL selected the uninstalled psycopg2 driver.
The fixture now explicitly selects the installed psycopg driver, matching the
existing historical fixture. Its real migration/seed/read regression passed
with both URL forms. The interrupted local full gate remains unaccepted; see the
[retained CI failure](docs/implementation/evidence/phase-2-p2-05-b2b0466-failed-quality.json).
The database CI timeout is now 40 minutes: the failed run spent over 15 minutes
before any X-ray case could execute. Application behavior and dependencies are
unchanged; corrected-source acceptance was still pending at that boundary.

Candidate `c84ecee2278a1f32d41c2e9640692001fae6fcf8` passed the complete CI
Python coverage gate (1,642 isolated and 234 service tests, 88% coverage),
documentation and security. Browser CI reached 73 passes before its 20-minute
job limit cancelled the final three mobile X-ray checks. That job now allows
40 minutes while retaining serial execution and existing test timeouts. The
[timeout record](docs/implementation/evidence/phase-2-p2-05-c84ecee-incomplete-browser.json)
preserves the successful layers and incomplete gate. This candidate remains unaccepted;
the separately accepted implementation is recorded above.

Source-backed known P2-08 limitations remain: the complete seed now includes four accounts with the X-ray fixture, but Compose does not forward the documented T212PI_ACCOUNT_ID setting to web; unconfigured multi-account overview startup is not accepted. The accepted runtime used an explicit baseline-account scratch override. The global header must respect the authorized route account. Sticky-header section positioning, readable mobile labels and table presentation remain P2-08/S39 follow-up work. Configured runtime acceptance does not prove default unconfigured multi-account UI behavior.

Phase 3 remains `not_started`.

## Previously accepted baseline

- Architecture Design Freeze v0.1: **Accepted**
- Documentation and Phase 1 readiness: **Approved**
- Phase 1 — Trusted Foundation (`0.1.0`): **Implementation complete; 24 locally executable acceptance rows complete; release readiness `blocked_external`**
- Phase 2 — Portfolio Intelligence (`0.2.0`): **Not started**
- Phase 3 — Premium Intelligence and Productization (`1.0.0`): **Not started**

P1-01 through P1-12 and all 24 locally executable acceptance rows are complete. The
immutable implementation/evidence SHA is
`e13916eca34d8e3be1ed130248d6c3d1ed7e3869`. `main` remains the implementation
authority; final governance/evidence reconciliation may advance `main` to a descendant
without changing the commit at which executable evidence was recorded.

The evidence run recorded 84% Python coverage, 338 isolated Python tests, 64
migration/integration tests, 22 web unit tests, 32 synthetic Playwright tests, and 6
API-backed Playwright tests. Alembic head is `20260901_0007`, and the MCP registry contains
exactly nine Phase 1 tools. The durable refresh outbox/API crash-recovery path, semantic
idempotency conflicts, stable complete collection traversal, API/MCP parity, desktop and
mobile pagination, full-stack state retention, non-root containers, and runtime secret
containment passed their locally executable gates.

Hardened PostgreSQL and Redis initialized disposable volumes and became healthy as users
`postgres` and `redis`; API, worker, dispatcher, MCP, and web runtime probes passed as
non-root. Semgrep, Gitleaks complete-history scanning, dependency audits, Trivy
filesystem/config/license scanning, and all application/infrastructure container scans
passed. All workflow actions and external Docker bases are immutable SHA/digest pinned.

Scenario 8 uses a retained synthetic immutable quantity/cash mismatch fixture through
persistence, API/MCP, and actual API-backed desktop/mobile web. It does not claim that
the real Trading 212 provider supplies a valid opening-history basis. That real-provider
coverage condition remains `unavailable_explicit`, with the limitation reported rather
than fabricated.

## Historical next action before owner progression

Review the corrected f88b019 candidate and its inspectable local evidence independently.
The prior 3998426 report remains historical. Preserve these external owner/deployment
conditions without substituting synthetic evidence:

1. Run the owner-controlled Trading 212 Demo smoke when a dedicated read-only Demo
   credential is supplied.
2. Select the production host, identity provider, and secret manager.
3. Deploy the authenticated MCP endpoint over public HTTPS/OAuth and complete ChatGPT
   registration.
4. Continue to report unavailable real-provider opening-history coverage explicitly
   unless valid provider evidence becomes available.

The accepted direct-`main` policy is the only active delivery mechanism. Frozen
architecture and safety decisions remain unchanged. Phase 2 is `in_progress`
as an unaccepted phase and awaits independent review; Phase 3 remains `not_started`.

## Permanent boundaries

- Trading 212 integration is strict GET-only and default-deny.
- Exact capabilities are frozen in `config/contracts/trading212-read-allowlist.yaml`.
- No broker write, trade execution, Pie mutation, transfer, CFD operation, or generic proxy is allowed.
- Deterministic code—not the language model—performs authoritative financial calculations.
- PostgreSQL is the system of record.
- Web, API, workers, reports, and MCP share canonical application services.

## External gates

These are the only remaining external conditions and do not reopen local Phase 1
implementation:

1. Trading 212 Demo read-only credentials and Demo smoke — `blocked_external`.
2. Production host, identity, and secret-manager selection — `blocked_external`.
3. Public HTTPS/OAuth MCP deployment and ChatGPT registration — `blocked_external`.
4. Real-provider opening-history coverage — `unavailable_explicit`; limitation reporting
   is complete.

No claim of real account connectivity or deployed ChatGPT availability is made until
those gates pass. Trading 212 Live is disabled and untested; it is not an additional
Phase 1 gate.

The Demo smoke has not run because no owner credential was supplied. Production
selection and public HTTPS/OAuth MCP deployment with ChatGPT registration have not run
because those external resources were not supplied.

## Readiness evidence

- `docs/DESIGN_INDEX.md`
- `docs/DESIGN_FREEZE_V0_1.md`
- `docs/implementation/PHASE_1_READINESS_REVIEW.md`
- `docs/implementation/PHASE_1_TECHNICAL_BASELINE.md`
- `docs/implementation/PHASE_1_EXECUTION_MANIFEST.md`
- `docs/implementation/PHASE_1_ACCEPTANCE_MATRIX.md`
- `docs/implementation/PHASE_1_IMPLEMENTATION_REPORT.md`
- `docs/implementation/PHASE_1_SCENARIO_EVIDENCE.md`
- `VALIDATION_REPORT.md`

## P2-05 scoped acceptance

Accepted authority `0ebbfa29253f418084835335eb2ee66f1b898679` preceded implementation.
P2-05 is complete at `7b102663ea193b4668924a7252180731954f4b00`; see the
[implementation and accepted evidence](docs/implementation/P2_05_PORTFOLIO_XRAY.md).
At the P2-05 closure boundary, five packages were complete (50%) and P2-06 was in progress. This is historical scope; current P206 local acceptance and the owner CI deferral are recorded above.

## P2-06 scoped local acceptance

P2-06 has scoped local acceptance at `9e39767b408b38203d88d6e5b41bf0bc1265adfb`. GitHub Actions is deferred by explicit owner instruction; no CI pass is claimed. The complete required local gates, exact source bindings and deferred startup observations are retained in the P206 acceptance evidence. Remaining Phase 2 implementation continues under that recorded deferral until the owner resumes CI verification.

Observed gate totals are taken from the [finalized evidence](docs/implementation/evidence/phase-2-p2-06-9e39767.json), not estimates or earlier candidates: 1925 isolated Python tests, 277 service-backed tests, 301 web unit tests, 90 serial browser checks, and 88% combined coverage. Runtime, cleanup, images, scanners and actual screenshot/PDF review retain their exact recorded scope. Alerts export still requires P207.

Post-verification housekeeping removed 28 obsolete Buildx records and 514,771,216 logical bytes of inactive development output and archive-equivalent scan extracts. Six obsolete image IDs were already absent. Current images, accepted evidence, archives and required dependencies were preserved; the task stack is absent. The scoped execution receipt has SHA256 `0f0945a22d189f7dd0575c63ddfda4ca7100ddb454708fffbc5b98c78d71385c`.

## P2-06 historical implementation observations

The following working and superseded-candidate observations are retained history, not current pending gates or replacement acceptance proof.

Reports and exports start from synchronized P2-05 closure
`5ff85b4436ec9be886639e6e2cf0c722fc0c4a73`. The
[implementation contract](docs/implementation/P2_06_REPORTS_AND_EXPORTS.md) fixes
bounded canonical capture, durable jobs, private PostgreSQL artifacts, current
principal/source authorization and the four output formats. Focused canonical,
renderer, authorization, licensing, privacy and retention checks passed before
the implementation candidate was committed; full package acceptance is still pending.
Real PostgreSQL capture now produces the complete annual selection and the
performance/benchmark selection within the existing limits. Their report
projection preserves full selected service values, source/license references and
reported valuation/event provenance; private daily calculation traces remain
bound by their immutable input/result hashes. A later snapshot retains its actual
valuation date and an explicit disclosure beside the historical period.

All ten report types passed focused PostgreSQL checks of PDF/CSV/JSON/XLSX
artifacts, canonical values and manifests. Six focused PostgreSQL lifecycle-audit
and privacy tests passed, including a genuine TTL deadline, pre-cleanup denial and
bounded idempotent physical purge. Three standalone export tests passed nine
real jobs covering seven datasets, both field sets and all three export formats.
Actual API-backed report and export journeys passed twice each across desktop and
mobile; the later working remainder gate also exercised their scroll-normalized captures.
The first full gate passed static checks, 1,650 Python unit tests, 270 web unit
tests, 34 property tests, 130 contract tests and 41 integration tests before a
deliberate interruption to address a delayed dispatch callback race found in review.
Both report and export interleavings reproduced the failure before the guard fix;
the corrected cases and related dispatch/lifecycle checks then passed (15 tests).
The restarted run passed all 262 integration tests, including the complete report
type/format matrix. A migration-policy test still counted tables only through
0013; adding the 0014 inventory and ancestry assertions corrected that test, and
all 12 migration tests passed. Production migrations were unchanged by this fix.
The source-canary gate also caught a literal test marker in the report browser
test. Constructing the same marker from components preserves the existing negative
assertion; all 100 security tests then passed with the scanner unchanged.
The remaining-stage run `p206-working-remainder-04` passed on September 9 in
2,828.665 seconds with source unchanged throughout the run: 1,914 isolated coverage
tests, 277 service/migration coverage tests, 88% combined statement/branch coverage,
86 serial browser checks, documentation/security checks, production builds and all
six container images. Together with the preceding observations, this verifies the
working implementation before the subsequent navigation correction; it is not a
passing clean exact-SHA `make validate` or package acceptance.

The subsequent navigation correction passed 45 focused unit cases and the full
web unit suite (301 tests across 37 files). Four desktop browser journeys passed
with ordinary pointer navigation after the sticky sidebar gained vertical
scrolling; four mobile journeys passed before that sole CSS change to the hidden
desktop sidebar. The final web lint, typecheck and production build passed.
The original default-restoration regression, test-selector failure and actual
sidebar-viewport failure remain recorded alongside their corrections. Root reviewed
all eight working screenshots, including supplemental control viewports; the
fixed-footer limitation in long full-page mobile captures remains documented.
Final-source acceptance images require their own review. The OpenAPI comparison
preserved all 70 existing operations and added eleven reporting operations.

Implementation candidate `8636ab4be5a3801d126246cc66322355b65b69b4` was committed
and pushed but remains unaccepted. Its exact-source CI node-unit job passed 300
tests and timed out one 2 MiB + 1 byte artifact comparison at 6,773 ms against
the unchanged 5,000 ms default; navigation tests passed. Documentation run
`34463544398` and Security run `34463544422` succeeded. Quality run `34463544455`
was still running at the recorded observation, with that node-unit job failed;
no overall Quality success is claimed.

The local exact-source gate was deliberately interrupted to correct the expensive
test assertion, ending with exit 2 after 217.295 seconds and source unchanged.
It had passed 1,650 Python unit, 301 web unit, 34 property and 130 contract tests;
32 integration tests passed before the clean interruption (74.79 seconds).
The test-only correction retains the complete artifact and every security assertion,
using native full-byte comparison without increasing the timeout. On one local CPU,
the original test passed in 2,676 ms; that local run did not reproduce the CI timeout.
After correction, all 17 client tests passed, with the large-artifact test at 9 ms;
all 301 web tests then passed in 29.88 seconds, followed by lint and typecheck.
The failed CI log and interrupted gate are preserved. Replacement exact-source
acceptance remains pending.

Candidate `e145229491cddff37c58eb86eef7cf120b1956c7` passed all 301 CI web unit
tests and its Documentation and Security workflows, but its mobile report-navigation
test failed in Quality run `34464507609`: the invalid-selection notice was absent
at the unchanged five-second assertion deadline. CI retained no trace or query
iteration. Native browser history can be changed before Next installs its client
history bridge; this is a source-supported setup-race hypothesis, not a proved
CI root cause. The original local mobile test passed and did not reproduce it.

The local exact-source gate passed 1,650 Python unit, 301 web unit, 34 property,
130 contract, 262 integration, 12 migration and 100 security tests. It was then
deliberately interrupted during isolated coverage, ending with exit 2 after
1,579.701 seconds and clean unchanged source; 629 coverage tests had passed.
Neither completed coverage nor full validation is claimed for that run.
The browser test now observes the native history bridge and verifies real
report/export form transitions before each of the four invalid URL cases,
with per-query step labels and every rejection/recovery assertion preserved.
The corrected full report suite passed all four tests on desktop (40.0 seconds)
and mobile (39.6 seconds); Prettier, web lint and web typecheck passed.
Replacement exact-source acceptance remains pending.

Candidate `93ce926bce4d3f1f35137dd4ee0b1f14d88fd0bc` passed its clean exact-source
`make validate` in 4,395.367 seconds, including 1,914 isolated and 277 service-backed
coverage tests, 88% combined coverage, 301 web unit tests and all 90 browser checks.
Quality `34468332521`, Documentation `34468332516` and Security `34468332475` all
succeeded; all eight source/history/image scans passed. Fresh runtime acceptance
passed in 169.889905 seconds, including restart parity, authorization, expiry and
privacy checks across 186 tables and 8,061 rows. Its seven task containers and
disposable PostgreSQL volume/network were removed with absence verified.

That candidate remains **unaccepted**. Root reviewed eight browser images and six
pages of the actual 14-page PDF. The PDF exposed a metadata defect: numeric position
and allocation cells overrode the effective stale snapshot quality with their stored
fresh row quality, including weights derived from the stale total. Arithmetic and
currencies were unchanged. The four capture sites now combine intrinsic row quality
with the existing effective snapshot quality. Other analytical families
retain their own pinned quality; they must not inherit the snapshot's age wholesale.
The passing automated evidence and failed PDF review are preserved separately.

The new capture regression reproduced three failures before the correction and passed
all eight cases afterward. The affected capture/renderer suite passed 34 tests, and a
real PostgreSQL portfolio-summary job passed all four artifact-format checks. Formatting,
lint, strict mypy across 468 files, architecture, generated contracts, documentation,
100 security tests and Semgrep (zero findings, exit 0) passed on unchanged working
source. These are focused correction results; replacement exact-source acceptance
remains pending.

At this boundary, scoped file cleanup removed 521,701,768 logical bytes
(525,402,112 allocated file bytes): inactive Next development output, a redundant
P2-05 extracted-source copy verified against its retained archive, and one obsolete
task bytecode file. Source, dependencies, accepted evidence and the archive remain.

Scoped cleanup removed 24 inspected obsolete Docker cache records (Docker reported
4.906 GB reclaimed) and 44 obsolete build records. The latest browser boundary
removed six successful traces (19,938,678 bytes) and 209,401,131 logical bytes of
inactive Next development output after checking active consumers. Retained receipts
bind these removals to the inspected task artifacts; no host-disk compaction is claimed.

The PostgreSQL CI job budget is now 90 minutes. The measured local coverage phases
took 311.56 and 1,796.99 seconds; applying the prior accepted P2-05 local-to-CI phase
ratios estimates about 69.18 minutes for that CI job. This is a budget estimate,
not a measured P2-06 CI result. The full test selection and coverage remain unchanged.
At that historical correction boundary, the candidate still required clean exact-source local validation,
image/security scans, fresh Compose acceptance and reviewed final-source screenshots
and PDF. On September 10 the owner deferred GitHub Actions for the remaining Phase 2
work until account limits reset, with no additional payment. CI remains unverified;
all local gates remain required. Validation continues serially in one task Compose project,
using PostgreSQL alone when sufficient and Redis when required. Inactive generated
outputs are removed at check boundaries; September 10 cleanup removed 505,727,234
logical bytes of inactive Next development output after checking for active consumers,
preserving production outputs, dependencies, source and retained evidence.
The alerts dataset requires the real P2-07
producer; it must fail before job creation until that producer exists.

Candidate `a2f2e3c533e6079766beac90f3f97279c622de40` passed its clean exact-source
`make validate` in 4,808.569 seconds: 1,658 Python unit, 301 web unit, 34 property,
130 contract, 262 integration, 12 migration and 100 security tests, followed by
1,922 isolated and 277 service coverage tests (88% combined coverage) and 90 browser
checks. All eight security scans and fresh runtime acceptance passed; restart,
authorization, expiry and privacy checks covered 186 tables and 8,061 rows. Its seven
task containers and disposable volume/network were removed and their absence verified.

The snapshot-quality correction is visible in the fresh PDF. That candidate remains
**unaccepted** because page 3 prints the snapshot row context as the source of a
reconciliation boolean whose canonical cell context is different. The renderer also
omits cell context in coverage and inline proof appendices. The correction exposes
explicit differing cell contexts for all kinds and labels the row context as the
default; canonical capture, values and financial methods remain unchanged. All three
new cases failed against the original renderer and passed after correction; the full
affected PDF/renderer suite passed 26 tests. A real PostgreSQL report job passed all
four formats. Formatting, lint, strict mypy across 468 files, architecture, generated
contracts, documentation, 100 security tests and Semgrep (zero findings) passed.
At that pre-9e39767 boundary, corrected-source acceptance remained pending. The passed automated evidence and
failed visual observation are retained separately.

At that source, Quality `34478450252`, Security `34478450202` and Documentation
`34478450265` failed before any steps because of the account payment/spending-limit
restriction. The owner explicitly instructed continued implementation without Actions
until limits reset. That Phase 2 decision is recorded independently of candidate
validation in both machine status files; these startup failures are historical records,
not evidence that later source revisions ran CI.

This boundary removed 495,021,938 logical file bytes (498,982,912 allocated file
bytes) of inactive Next development output and an obsolete source extraction
verified against its retained archive, plus exactly 12 obsolete P2-06 build records.
Current images, current build records, dependencies and evidence were preserved.
One PostgreSQL container is reused for the corrected-source verification.

## Historical P2-07 preparation and rejected 0d7aa9b/0df988c candidates

The [alerts implementation contract](docs/implementation/P2_07_ALERTS_AND_RULES.md) starts from P206 closure `2cdb409`. Rule/domain, persistence, public interfaces and canonical capture are implemented and undergoing full local validation. The final capture correction retains complete relevant revision groups, filters unrelated activity before quality/FX checks, and preserves canonical linked cash-effect deduplication. Complete-ledger coverage remains explicit. Package acceptance is pending; the owner CI deferral continues, and six packages remain locally accepted.

Exact candidate 0d7aa9bd4eccb987f2485c35f57b809ddedd2900 passed clean
make validate in 5,268.546 seconds, including 2,352 isolated and 338 service
coverage tests, 88% coverage, 345 web unit tests, 100 browser checks, dependency
checks and six image builds/probes. Its fresh runtime passed in 256.500 seconds:
the same pending alert recovered after actual Redis message loss, all seven
services restarted, and authorization, expiry and privacy checks passed.
The task containers and disposable volume/network were removed afterward.

That candidate remains unaccepted: the complete-history Gitleaks scan reported
13 findings in the previously retained P2-06 evidence. Trivy source and all six
immutable-image scans passed. The exact historical report identifier findings
are classified in
[the failed-security record](docs/implementation/evidence/phase-2-p2-07-0d7aa9b-failed-security.json).
The correction preserves the accepted P2-06 evidence and existing exception
fingerprints. A corrected-commit full gate, scans, runtime and artifact review
remain required. Six packages remain accepted; GitHub Actions stays deferred.

The corrected security candidate 0df988ce4fb785c44d28868d9936d2dbae18c99d
remains unaccepted: its full local gate stopped after 4,600.420 seconds at an
Alerts browser minimum-height assertion. The 2,352 isolated and 338 database
coverage cases passed with 88% coverage; 50 demo browser cases and four Alerts
cases passed before the suite reported failure. The [failed-browser record](docs/implementation/evidence/phase-2-p2-07-0df988c-failed-browser.json)
retains the observation separately from earlier successful candidates.

The browser correction waits for the exact saved event revisions and the
completed form transition before measuring layout; pending disabled buttons
alone did not prove that the refreshed UI was ready. The original minimum-height
assertion and zero-retry policy remain intact. All five Alerts cases passed on
desktop and all five passed on mobile after the correction. These focused working
results do not accept P2-07. Fresh immutable validation, security scans, runtime
and artifact review remain pending. Only the shared PostgreSQL container remains
running for browser checks; idle Redis was removed. GitHub Actions stays deferred.

## Provider and layout checkpoint validation (2026-09-22)

`provider-layout-checkpoint-isolated-06` passed 5,335 Python tests, 860 web unit
tests, all configured isolated static/type/format/contract/governance checks and
sealed broker checks in 542.469 seconds with unchanged source. Actual PostgreSQL
and three-viewport production browser component results are recorded in
`VALIDATION_REPORT.md`. Aggregation, explicit research/aggregate reports and final
Phase3 acceptance remain in progress. GitHub Actions stays owner-deferred.

The semantic acquisition replay correction passed17 PostgreSQL cases and preserves
original licensing/expiry. All23 current and populated migration checks passed;
the component inventory is344 tables. Security/build subgate failures and their
scoped corrections remain recorded separately in the validation report.

The final component follow-up passed static/contracts,61 focused tests, configured
security and dependency checks, a147-file changed-source secret scan and24 Python
package builds in195.903s. Final immutable Phase3 validation remains pending.
