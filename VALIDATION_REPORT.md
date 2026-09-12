# Phase 1 Validation Report

## Current P209 scoped local validation

P2-09 is complete with P2-S33 authorization evidence at `bd47329cca5c1409486fff40d48e92163ab4a8af`. Phase 2 remains in progress with 9/10 completed packages (90%), 23/29 local rows and 31/40 scenarios complete. P2-MCP-001 and P2-MCP-002 retain their scoped evidence at `d70ab445de38aee255275880c5ef7a105ebbb939`. S32/S34/S38/S39 remain partial. P2-10 and Phase 3 remain `not_started`; GitHub Actions is owner-deferred with no pass claim, and the final Phase 2 release SHA remains null.

[P209/S33 supplement](docs/implementation/evidence/phase-2-p2-09-s33-bd47329.json); finalized 2026-09-12T19:03:50.016115+00:00. The same-source relevant MCP, PostgreSQL, static, security, Python-build and single-MCP-image gates passed. The d70 full validation and browser/visual evidence remain historical; no new full validation, browser/visual gate or seven-service runtime is claimed.

[P209 scoped evidence](docs/implementation/evidence/phase-2-p2-09-d70ab44.json); finalized 2026-09-12T18:08:53.523669+00:00. The artifact retains actual widget/API browser observations as supporting evidence. It does not claim a new full Compose startup/restart, runtime cleanup, PDF visual gate or live ChatGPT registration.

The historical d70 artifact records 2545 isolated and 379 service-backed Python tests in its full gate, and 208 browser cases across its supplied reports. These observations are not rerun or attributed to the S33 supplement source. These are recorded populations, not an aggregate of overlapping runs. Python selectors describe source coverage supported by observed whole-file progress; actual widget cases and ROOT visual reviews remain bound in the artifact.

Original P209 tracker values, working failures and visual-review history remain in [the scoped history archive](docs/implementation/evidence/phase-2-p2-09-d70ab44-implementation-history.json).

## Historical P2-09 implementation validation before acceptance

P2-09 implementation is in progress from accepted P208 closure
`9505e2650aadedd504a0a94117c018b0b7ed153f`. The integrated scope covers the exact
25-tool MCP registry, private argument errors and five bounded accessible widget
resources. P209 local acceptance remains pending. Phase 2 retains 8/10 accepted
packages (80%), 21/29 local rows and 30/40 scenarios complete. S32/S34/S38/S39
remain partial; S33 remains pending. P2-10 and Phase 3 remain `not_started`, the
final Phase 2 release SHA remains null, and GitHub Actions stays owner-deferred.

P208 scoped local acceptance remains bound to source
`bc21516c51aa5090031b39ea56ded3ca94d657d8` in the unchanged
[accepted artifact](docs/implementation/evidence/phase-2-p2-08-bc21516.json).
The older P208 observations below retain their original failed/pending status.

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

Retained external task evidence for this regression:

- `gates/p209-private-errors-red-01.json`: SHA-256 `52aed964c9be94230a156f5cca1f7c55af3b08b9a9fe555c88242d9c2675bf3c`.
- `gates/p209-private-errors-red-01.log`: SHA-256 `6d5abc32b1a670a34e2dd09cbf80a616ff4252b5a1b0233a8a1a1c9bc61752a3`.

The planned widget capture matrix is five resources across the existing desktop
and mobile projects. Actual passing cases, image identities and human reviews
must be recorded before they support acceptance; no capture or test count is
claimed here for an unobserved gate.

## P209 immutable full failure and PDF correction

The full `make validate` gate at clean, unchanged
`aa5a5f118ae41d334818621d16330333d5347c46` failed with exit 2 after 2,305.073
seconds. Its service-backed session ended with 363 passed, one failed and 2,551
deselected. Those counts describe the session where validation stopped, not a
completed full-gate total. The failing case was
`tests/integration/test_report_type_matrix_postgres.py::test_snapshot_and_xray_report_types[portfolio_xray]`.
The `Record:xray.path.2Key:` assertion found zero exact markers. The original
failing PDF was not retained. A separate controlled actual-renderer reproduction
confirmed that page framing can interrupt intact record and key lines.

| Retained gate | Actual outcome | Seconds |
|---|---|---|
| p209-immutable-aa5a5f1-full-01 | Failed: 363 service-backed passes, one failure, 2,551 deselected; exit 2 | 2305.073 |
| p209-pdf-pagination-reproduction-01 | Isolated X-ray case passed; pagination-dependent failure did not recur | 41.429 |
| p209-pdf-controlled-seam-01 | Actual two-page renderer output reproduced footer/header interruption; raw adjacency count zero | 1.132 |
| p209-pdf-body-red-01 | Three RED failures with the initial raw-join helper: record/key, wrapped key and wrapped exact value | 1.592 |
| p209-pdf-body-focused-01 | 47 passed: nine new reader cases, 26 renderer unit cases, ten report types and two company cases | 327.098 |

The first three receipts bind the unchanged immutable source. The RED receipt
binds its own unchanged, unaccepted working source containing the new helper and
regression tests. Diagnostic passes do not supersede the failed full gate.

The test-only correction verifies each page's exact outer header, footer and
sequential page number, removes only those framing lines, and joins the remaining
body text. It preserves matching text inside a canonical record and retains the
exact identity, amount, currency and state assertions. Production PDF rendering
and financial calculations are unchanged. The focused correction gate passed all
47 selected tests in 327.098 seconds. All nine reader regressions and static checks passed in
31.129 seconds after formatting-only corrections; a fresh immutable full gate and source/image evidence remain
required. P209 acceptance is pending, with 8/10 packages, 21/29 local rows and
30/40 scenarios complete. P210 and Phase 3 remain not started, the final release
SHA remains null, and GitHub Actions remains owner-deferred.

Exact external receipt/log references (durations are receipt wall times):

- `gates/p209-immutable-aa5a5f1-full-01.json`: SHA-256 `4ba1e093270caf097cea11cc2034eb9ccc0fd0b685e3947aae3c0059efb782ae`; log `gates/p209-immutable-aa5a5f1-full-01.log`: SHA-256 `8df499e09b81c63109f630001c49e6421e5d19d122e81f4fabb50139a2c8158f`.
- `gates/p209-pdf-pagination-reproduction-01.json`: SHA-256 `0edfbb4e5e1c53b82b5ed2e4b045363cd139ff10d9389da35769f13b45fa01a3`; log `gates/p209-pdf-pagination-reproduction-01.log`: SHA-256 `efc168f0dec29401a1f2fe8dbd883f4e3e87271a60abc7d35c3e3e67f7724084`.
- `gates/p209-pdf-controlled-seam-01.json`: SHA-256 `e622715fa737840eeb126bb83dc7746fce88ea5dc7f11727c3a07738baa0f286`; log `gates/p209-pdf-controlled-seam-01.log`: SHA-256 `554a32659506c9c1f0d96939e8f303c4293508f432ce877c9b57dd893098394a`.
- `gates/p209-pdf-body-red-01.json`: SHA-256 `161e5534c57c095d26a4dd95b396494a5e763f58ffc21fa8aa40bee937bac798`; log `gates/p209-pdf-body-red-01.log`: SHA-256 `16ca81de2f1ef0a1c7f6b33a3de780ef012a5263b6f174d9bb4732618ea08791`.

Focused correction receipt `gates/p209-pdf-body-focused-01.json`: SHA-256 `77cb04d274b3e84f523e4b4d4ba4a0763b683256febb17cc3e78199f1a04949f`; log SHA-256 `d522783947d1160746fef5cf8dc57c1fa1b47225ad6cfe140a0dbb7a2af7782f`.

The two preceding static attempts are retained: static01 failed Prettier formatting
on the status JSON files (3.833 seconds); static02 failed a long test string
literal (3.661 seconds). Formatting changed no semantic input or assertion.

- `gates/p209-pdf-body-static-01.json`: SHA-256 `0a246e72cecbcc0fc9e1d83373c6b1db4bc8aade92e62e9564ffc232774632ab`; log SHA-256 `6e1f9d757ca2be71eca1ef3478b521566609f6cf1ee573f3f65e5afc53c2f66e`.
- `gates/p209-pdf-body-static-02.json`: SHA-256 `e870af62bb8faf56ea2b1ea3135d0b7a6024b0034d35d7ed7fdacc7ba262e01d`; log SHA-256 `d3fa2716a1d46406b648e411e8cba08473ed4c34a2ff58792f565980fced9932`.
- `gates/p209-pdf-body-static-03.json`: SHA-256 `fe29080bfdbfaf19f5e0a7ef98c2d74140316280f3f0c80940d8dd6242363965`; log SHA-256 `9264e48c1376249c05f77cf764ff99ee45031db72f39728ed94905450288bf5b`.

## Historical P209 observed focused gates

Each gate below completed on its own unchanged, unaccepted working source based
on closure `9505e2650aadedd504a0a94117c018b0b7ed153f`. Durations are receipt wall
times; counts are per-gate populations and must not be summed across reruns.

| Gate | Outcome | Cases | Seconds |
|---|---|---|---|
| p209-private-errors-red-01 | failed | 9 failed, 16 passed, 35 deselected | 6.354 |
| p209-registry-focused-01 | passed | 62 passed | 11.522 |
| p209-legacy-mcp-focused-01 | passed | 228 passed | 40.642 |
| p209-durable-mcp-focused-01 | failed | 1 failed, 1 passed | 15.37 |
| p209-durable-mcp-focused-02 | failed | 1 failed, 1 passed | 17.294 |
| p209-durable-mcp-focused-03 | passed | 2 passed | 18.326 |
| p209-static-focused-01 | failed | static checks | 13.167 |
| p209-static-focused-02 | failed | static checks | 11.702 |
| p209-static-focused-03 | passed | static checks | 31.338 |

The first durable failure was an incorrect expected idempotency error code; the
second was a keyword-only constructor misuse in the new test setup. Both test
corrections preserve canonical production behavior. Static01 found six inferred
result-model typing errors. The explicit `RESULT_MODELS: dict[str, type[BaseModel]]`
annotation then exposed two redundant casts in existing gateway tests; static02
is retained and static03 passed after their removal. No data or wire change was
introduced by these typing corrections.

Exact external receipt/log hashes (relative names refer to retained task evidence):

- `gates/p209-registry-focused-01.json`: SHA-256 `9227408284df4332e5af2155bf78cac9c7b8a41259789b01e1bbc33c928c202d`; log SHA-256 `0370c372e3c788a33888eb0ac4709a71e2450aba49a6ab2604405f39942b13ef`.
- `gates/p209-legacy-mcp-focused-01.json`: SHA-256 `d3bffc5739a6cf1255251aed50ffd2ea62596e941fe3651c221620bd3d687e07`; log SHA-256 `01da6a62ff8c20a50210cbfdf0fdd227e4feac98d13491c6e7553c00895cd54a`.
- `gates/p209-durable-mcp-focused-01.json`: SHA-256 `dbef57ec14d69ab11c470ddca605bd03d670727247f5d42d92dd962fa77268aa`; log SHA-256 `476796587b7b5220896f1beceba432f0c406902765e2ecb905514f9dc422e3b1`.
- `gates/p209-durable-mcp-focused-02.json`: SHA-256 `6dd299a7e266439cf5d54a0f0582a150189db21d82184fc3303dae9f6ef3ba9a`; log SHA-256 `a2726530a97f678306c30ff238b1e4c106e4a798c58900beec94812c13cda244`.
- `gates/p209-durable-mcp-focused-03.json`: SHA-256 `d94567d1e8e67d0ccc3af5aff6237480b917b6584257b15499e4bcf75d98dae9`; log SHA-256 `1e0521de15ac45db832e155ca7c52146a50f6938a05bb177f3d98fe89d2dcd06`.
- `gates/p209-static-focused-01.json`: SHA-256 `3072cd80758970bb714b623216a4172bbe6c7ab60c8fe59c66e88bafa75f4713`; log SHA-256 `58328266c59c7016ac28983716c12f346211ae808b7f8e9cd819f75d98ba11cf`.
- `gates/p209-static-focused-02.json`: SHA-256 `d9e0b799974527b552e28bc2f37eb0cff848b922b71777357a4cda12d1c0b0cc`; log SHA-256 `52a0eae04bb433bf0cbf1785c5c8dc238fce0818e45584c93cf7951b2bcbc6a5`.
- `gates/p209-static-focused-03.json`: SHA-256 `61088708b69e3bfefd334262f675c35ece925110963f083ad7b227899f9b1d6a`; log SHA-256 `92595590e67d2167e2c507c44e86e735eb12d16507ad479bd0233ef81090883b`.

## Historical P209 widget correction and review

The first focused browser/build gate passed 74 cases in 80.034 seconds, but ROOT
rejected its mobile planning image because the Recommended value heading painted
into the Post-plan value column. The corrected CSS permits long headers to wrap;
a rendered text-bound assertion now checks headings in every widget CSP case.
The second gate passed all 74 cases and the production web build in 75.866 seconds.
ROOT inspected the two corrected planning images; the other eight PNGs match the
previously inspected images byte for byte. These remain working-source observations.

- `gates/p209-focused-widgets-01.json`: SHA-256 `67fd609ad0c769d1aa01bae9af15c587de31fceec3081d39ebd923ddf1112e7d`.
- `gates/p209-focused-widgets-02.json`: SHA-256 `708893821ae7bd4bf0032d4f03ccb81d77a244f581aca7feb9e2fcbaf95fbd70`.
- `p209-focused-widget-visual-review-01.json`: SHA-256 `96973ecbcab89f854feaaf41a920b77d66c36f221492d937e48d291ecd179ef5`.
- `p209-focused-widget-visual-review-02.json`: SHA-256 `f1b70aafe818a67a71d48323d9d53e91626ce09b7c7027cb584724fcb192a2e8`.

## Retained Phase 1 acceptance

**Corrected Phase 1 acceptance (2026-09-07):** `99df47b6633791c3900a52f46f56d48be922a436`
passed all local gates and all three workflows: Quality `34121465069` (attempt 2),
Security `34121465107`, Documentation `34121465071`. Python: 371 isolated plus 73
service-backed tests, 85% branch-aware coverage; web: 22 unit, 32 synthetic browser,
six API-backed browser tests. Head: `20260907_0008`. Both F-01/F-02 are closed.
The [audit record](docs/implementation/PHASE_1_AUDIT_CORRECTIONS.md) contains the
command matrix, runtime IDs, restart and canary evidence, and external limits.

## Historical accepted baseline

**Date:** 2026-09-02
**Repository:** `ntua-el21026/trading212-portfolio-intelligence`
**Validated implementation/evidence SHA:** `e13916eca34d8e3be1ed130248d6c3d1ed7e3869`
**Authority:** `main`; later evidence/governance-only reconciliation commits remain
linear descendants of the immutable implementation/evidence SHA.
**Decision:** All 24 locally executable Phase 1 acceptance rows are complete. Release
readiness remains `blocked_external` only for the explicitly listed external conditions.

## Evidence provenance

The exact implementation SHA has green GitHub Actions runs:

- Phase 1 quality: `33562745986`;
- security and dependency gates: `33562746060`;
- documentation baseline validation: `33562746052`.

The quality browser log records 32 synthetic tests and 6 API-backed tests with
Playwright retries disabled and no flaky result. The corrected Compose observation was
run in isolated project `t212pi_phase1_corrected_20260901` with a new PostgreSQL volume,
unique loopback ports, and all seven long-running services including the dispatcher.
Evidence-only descendants do not change the validated runtime implementation.

## Complete local command matrix

| Command | Result |
|---|---|
| `python scripts/validate_repository.py` | Host has no unqualified `python` executable; the repository's documented bootstrap-safe command, `python3 scripts/validate_repository.py`, passed. |
| `make bootstrap` | Passed with Python `3.13.15`, Node `24.20.0`, pnpm `10.34.5`, frozen `uv`/pnpm locks, and Chromium installed. |
| `make format-check` | Passed: Ruff format and Prettier. |
| `make lint` | Passed: Ruff, ESLint, package architecture, and strict GET-only provider boundary. |
| `make typecheck` | Passed: strict mypy and TypeScript. |
| `make test-unit` | Passed: Python unit suite and 22 Vitest tests. |
| `make test-property` | Passed: 10 Hypothesis invariant tests. |
| `make test-contract` | Passed: 36 contract tests plus workspace/generated-contract checks. |
| `make test-integration` | Passed: 50 PostgreSQL/Redis integration tests excluding migration-marked tests. |
| `make test-migrations` | Passed: 11 migration tests, empty-to-head, repeat upgrade, and ORM/schema drift checks. |
| `make test-security` | Passed: architecture/secret checks and 16 negative security tests. |
| `make test-coverage` | Passed: 338 isolated tests plus 64 migration/integration tests; combined branch coverage 84%, unchanged threshold 70%. |
| `make test-e2e` | Passed with retries disabled: 32 synthetic and 6 API-backed desktop/mobile browser tests. |
| `make docs-check` | Passed repository, link, JSON/YAML, workflow, and workspace validation. |
| `make security-check` | Passed pinned no-upload Semgrep, source secret scan, `pip-audit`, and production pnpm audit. |
| `make build` | Passed all Python distributions and the TypeScript/Next.js workspace build. |
| `make container-build` | Passed hardened PostgreSQL/Redis and non-root API/worker/MCP/web builds; dispatcher uses the identical worker image contract. |
| `make validate` | Passed the complete aggregate local Phase 1 gate. |

The bare `python` lookup is an environment limitation, not a repository check failure:
the repository intentionally specifies `python3` for the dependency-free validator and
`uv run python` for pinned application commands.

## Test, migration, contract, and browser results

- Python: 276 unit, 10 property, 36 contract, and 16 security tests form the 338-test
  isolated suite; 64 migration/integration tests passed under combined coverage.
- PostgreSQL integration: 50 non-migration integration tests passed; the 11-file
  migration suite passed separately. Alembic empty-to-head and repeated upgrade both
  reached `20260901_0007`.
- Web: 22 Vitest tests passed. Playwright ran 32 synthetic and 6 API-backed tests across
  desktop and mobile with `retries: 0`. More-than-50 collection navigation, URL cursor
  state, browser back, insertion stability, no duplicate/skip behavior, preview counts,
  largest-holding ordering, accessibility, and horizontal-overflow checks passed.
- The API-backed overview rendered `248,431.27 EUR`; the REST and MCP canonical value was
  exactly `248431.27` EUR. The API/MCP parity suite, nine-tool registry assertion, web
  rendering, OpenAPI generation check, generated TypeScript client build, and drift check
  all passed.
- Dedicated outbox crash/recovery, semantic-idempotency conflict/concurrency,
  stable-keyset pagination, more-than-10,000-row discoverability, full-period dividend
  aggregation, direct snapshot lookup, service-contract, and API/MCP parity suites passed.

## Corrected Compose, migration, and restart evidence

The clean isolated runtime started PostgreSQL, Redis, API, worker, dispatcher, MCP, and
web. Migration and seed one-shots exited zero. The migration head was
`20260901_0007`; repeating migration and seed preserved the exact baseline
`10|10|1|1|2|1|1|2|1|1|3` across source records, source occurrences, snapshots, runs,
transactions, cash flows, dividends, order observations, position observations, cash
observations, and ledger entries.

- **14a, atomic API publication crash:** the integration suite commits a run and outbox
  event, stops before publication, restarts the dispatcher, publishes/executes the same
  logical run, reconciles ambiguous broker acceptance, and verifies no duplicate
  economic data. Pending-outbox telemetry returns to zero.
- **14b, confirmed publication then worker recovery:** with the worker stopped, the API
  committed run `1b092b41-5037-4066-910f-6edcf2546862`; the dispatcher confirmed one
  publication/attempt and Redis retained broker depth one. Restarting the worker
  completed that run. An identical retry returned the same run, retained one outbox
  event/attempt, and left counts `11|20|2|2|2|1|1|2|1|1|3` unchanged.
- **14c, full-stack state retention:** all seven long-running services stopped and
  restarted without volume deletion. Counts remained
  `11|20|2|2|2|1|1|2|1|1|3`; API summary and data-quality JSON and MCP canonical
  structured content were unchanged; summary SHA-256 remained
  `3384103de93e8958c414db023e45131cfac8ea6de58629337f96ac8609b91566`;
  API/MCP/web remained at `248431.27`/`248,431.27` EUR; and the MCP registry remained
  exactly nine tools.

After recovery, dispatcher readiness was `1`; pending outbox and queued-runs-without-
deliverable-event gauges were zero; the database contained no pending/publishing outbox
event and no stranded queued run.

## Security, dependency, and container matrix

| Control | Result |
|---|---|
| Semgrep CE | Passed pinned `1.175.0` repository-local rules with network disabled, metrics off, strict/error mode, and no upload. |
| Gitleaks | Passed the complete Git history scan; repository high-confidence secret scan also passed. |
| Python dependencies | Frozen production export passed `pip-audit 2.10.1`. |
| Node dependencies | `pnpm audit --audit-level high --prod` passed. |
| Trivy filesystem/config/license | Pinned Trivy `0.74.0` scan passed for vulnerability, secret, misconfiguration, and license policy. |
| PostgreSQL image | Hardened `18.6` image built, ran unprivileged, and passed high/critical vulnerability and secret scan. |
| Redis image | Hardened `8.10.1` image built, ran unprivileged, and passed high/critical vulnerability and secret scan. |
| API image | Non-root minimized image passed build, runtime controls, canary, and high/critical vulnerability/secret scan. |
| Worker/dispatcher image | Non-root minimized worker image (also used by the independently supervised dispatcher) passed build, runtime controls, canary, and high/critical vulnerability/secret scan. |
| MCP image | Non-root minimized image passed build, runtime controls, canary, and high/critical vulnerability/secret scan. |
| Web image | Non-root minimized image passed build, build-artifact/runtime canary, and high/critical vulnerability/secret scan. |

The pre-existing, time-bounded `LGPL-3.0-or-later` policy was moved from legacy
top-level keys to Trivy `0.74.0`'s `license.ignored` schema; the exception scope and
review deadline were not broadened. The fresh-checkout-equivalent scan then passed.

A final security-diff review reproduced one evidence-integrity weakness in the earlier
token-only acceptance validator, classified it Medium/P2, and corrected it before the
validated SHA. Structured acceptance-row parsing now binds local and external states,
machine-readable readiness, counts, and remaining conditions; adversarial regression
tests reject relabeling or false external-readiness promotion. The sealed rescan had no
open finding.

API, worker, dispatcher, MCP, and web ran as UID `10001` with read-only root
filesystems, all Linux capabilities dropped, `no-new-privileges`, and package managers
absent. PostgreSQL and Redis ran as their unprivileged service users. The injected
runtime canary was absent from five application logs/filesystems and API/MCP/web
artifacts across 14 checked paths. No error/traceback was present in the retained runtime
log. Workflow actions and external Docker bases remain immutable SHA/digest pinned.

## External states not claimed as passed

| ID | State | Reason |
|---|---|---|
| P1-EXT-001 | `blocked_external` | No owner-supplied Trading 212 Demo read-only credential; the credential-dependent smoke remains explicitly skipped/not run. |
| P1-EXT-002 | `blocked_external` | No production host, identity, or secret-manager authority/configuration was supplied. |
| P1-EXT-003 | `blocked_external` | No public HTTPS OAuth-protected MCP endpoint was supplied for ChatGPT registration. |
| P1-EXT-004 | `unavailable_explicit` | A real-provider opening-history basis for the quantity/cash bridge is unavailable; the limitation is explicitly reported. |

Trading 212 Live remains disabled and untested. The synthetic reconciliation fixture is
local acceptance evidence only and is not substituted for real-provider opening history.
Phase 2 and Phase 3 remain `not_started`.

## P2-08 overview correction before package acceptance

Immutable ff884065e896209563d1966865602e73b3622fd6 passed make validate in 6771.536 seconds: 2474 isolated and 377 PostgreSQL coverage cases, 88% branch-aware coverage, 534 web unit tests, 52 demo plus 102 API browser checks across 39 API process reports, and all static/documentation/security/build gates. ROOT reviewed all 60 feature captures and found one mobile overview defect, so package acceptance remains false. The overview now preserves reconciliation status and uses the authoritative discrepancy_count independently of the empty summary issues collection. Five new regression cases failed before the fix and all eight overview tests passed afterward. Corrected working validation passed 539 web unit tests, formatting, web lint/types, docs, production build and three focused API browser viewport checks. The first focused browser attempt exposed a fixture count assumption (standalone 2 versus full-sequence 0); the corrected assertion compares the UI to the actual API count. Fresh immutable validation and acceptance evidence for the corrected source remain required; GitHub Actions is owner-deferred.

Retained task-evidence records (external file names, not repository paths):

- gates/p208-immutable-ff88406-full-01.json: SHA-256 adb9591ec25951f56f11c80c79269825513942b0d5697591f49d2e6903a364a6.
- p208-early-visual-review-ff88406-01/workspace-root-reviewed.json: SHA-256 fa4929b2940606c077ef6bcf74cafd0e8b4ccf36e1ff7cf707f11fb452566eb9.
- gates/p208-overview-correction-browser-01.json: SHA-256 6ac2ca0ddeca1db2c2ffa340e2d11ca6d07ef195cbc489c43019abb910489c3f.
- gates/p208-overview-correction-browser-02.json: SHA-256 9fa5282040df6342621c678ee593b362399ea94f5fee3bf0dd33840ae67227e8.
- gates/p208-overview-correction-static-unit-01.json: SHA-256 535bacd92b78925e8267fc65016fe3531ec566ce687752308b88c160cb7ab7aa.
- p208-overview-correction-visual-02/root-reviewed.json: SHA-256 fd970e811b78152ec4567994d34d9f0b774f9e0ce6d558886ec7bc628b266183.

The focused correction records bind an unaccepted working-tree diff; they do
not replace clean immutable acceptance, security scans, or the retained earlier
failed visual review. P2-09/P2-10 remain required and Phase 3 remains not started.

## P2-08 immutable 7201b53 full gate and failed image security

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

[Failed security evidence](docs/implementation/evidence/phase-2-p2-08-7201b53-failed-security.json) binds the full02 gate
receipt and transcript, all eight ROOT review records, six image-scan result/log
pairs, source/history result/log pairs, image identities, and scanner metadata.
Original external file names and SHA-256 values are preserved in that record.
Working correction gate `p208-pcre2-working-build-scan-01` passed in 62.736 seconds.
It binds all six actual image scans and four runtime package-version probes in
`p208-pcre2-working-image-checks-01/results.json`. Full corrected-source immutable
acceptance remains pending; GitHub Actions stays owner-deferred.

## P2-08 focused canonical parity on security-corrected source

Base commit: `57eba18bff82051124b09f0970f7ec5494a84d61`; these are
unaccepted working-tree checks, with unchanged source during each actual gate.

| Gate | Actual outcome | Seconds |
|---|---|---|
| p208-historical-parity-static-01 | passed | 21.695 |
| p208-historical-parity-browser-01 | passed | 259.298 |
| p208-xray-parity-static-01 | passed | 24.409 |
| p208-xray-report-parity-01 | failed | 42.498 |
| p208-xray-report-parity-02 | passed | 42.586 |
| p208-company-http-mcp-parity-01 | passed | 14.026 |
| p208-xray-parity-browser-01 | passed | 76.014 |
| p208-parity-final-static-01 | failed | 0.029 |
| p208-parity-final-static-02 | passed | 23.245 |
| p208-planning-parity-browser-01 | failed | 37.413 |
| p208-planning-parity-browser-02 | passed | 114.454 |

Historical and X-ray each passed three cases per desktop/tablet/mobile project;
planning passed two per project, for 24 focused browser passes. Each wrapper
then ran make build-web. The report matrix checks actual JSON/CSV/XLSX/PDF
artifacts against manifest-bound X-ray paths. The company test uses actual HTTP
routes and MCP tools with the same optional run pin and canonical service oracle.

The report01 failure was an incorrect test assumption about inherited quality;
the planning01 failure was an overbroad locator including revision history. Both
were corrected and passed in their recorded successors. Static01 stopped on
formatting after the quality assertion edit; formatting was fixed and static02
passed. Exact receipt hashes and the listed failed attempts are retained in the JSON
trackers. These checks do not replace the new full immutable validation, strict
three-project chart gate, source/image scans or 60 fresh reviewed captures.
GitHub Actions remains owner-deferred; P209/P210 and final S34 remain required.

### P2-09 capture-evidence timing correction

The full validation at `d70ab445de38aee255275880c5ef7a105ebbb939` passed in
6,938.446 seconds with 208 browser passes and unchanged clean source. The first
subsequent evidence collection failed before creating an output directory:
`Capture mtime is outside its exact actual case.` This was a collector error,
not an application or browser-test failure.

The installed Playwright 1.62.1 worker starts the first test before its suite's
`beforeAll`, while its reported test duration excludes that hook's separate
slot. Therefore `startTime + duration` was not the first test's wall-clock end.
Each original screenshot lies after that calculation and strictly before the
next actual test start on the same worker. The corrected collector retains the
reported duration as diagnostic data and validates the original capture within
the half-open interval from its own test start to that next same-worker start.
It rejects missing or ambiguous successors and uses no arbitrary time allowance.

The unchanged first collector's actual exit-1 diagnostic is retained at
`${RESUME_ROOT}/p209-d70ab44-capture-timing-diagnostic-01/diagnostic.json`
(SHA-256 `5f99262cd6da6783a496a466af720300b3cbd960de81e27eac6a5febfca23c46`).
The corrected collector is sealed as
`5d61ca347d8720cd4413e412bcc50756935c1cd784593fe7cd3415e695cc6b5d`.
Helper-only checks passed ten original captures, five boundary conditions for
both consumers and nine worker/identity/ambiguity negatives, with all nineteen
protected files unchanged; receipt SHA-256
`33d41187afd636918c9b3e07c33cb49bc939171fc523de68ed0e3d93e99b3c4a`.
Actual discovery02 then passed in 4.898 seconds and collection02 succeeded.
Neither those helper checks nor discovery substitute for full validation or
ROOT acceptance. Original reports, images and their nanosecond timestamps were
preserved, including ROOT's earlier ten-image visual review.

The actual untouched null-image draft and reference-consistent semantic-null
copy each exited 1 at the required missing-review guard, with no accepted output.
Their receipt SHA-256 values are respectively
`36bc50aaf34ce330674b601f359b040e743fb0156204e9308cdd223518dc9302`
and `fab91b2650ed1d77a22385b67c5edc5d0825f8acf79b142b7423868a55efcfb3`.
The genuine reviewed manifest then finalized successfully in 3.975 seconds on
unchanged clean source; its actual gate is
`${RESUME_ROOT}/gates/p209-immutable-d70ab44-finalization-01.json`.

At this verification boundary, scoped housekeeping removed 761,090,048 allocated
bytes of inactive Next development files and six superseded native Docker build
history records. Source, dependencies, production outputs, evidence and current
Docker resources were preserved. Receipt SHA-256:
`f302fd945796a0423a1971442283c318a1b1153db7dc4749e250dc24775e2bd5`.
Docker-native reclaimed storage and Windows VHD compaction were not measured.

### P2-09 completion-projection rejection

The first documentation gate exited 2 because the proposed package completion
left its solely assigned P2-S33 scenario pending. The existing repository
validator correctly rejected that state. The source-bound MCP001/002 artifact
remains unchanged; package progress is restored to 8/10 (80%) until the prepared
persisted authorization matrix is executed and accepted. No scenario ownership
or validator rule was weakened. A generated trailing blank line was also removed.
Failed gate receipt SHA-256: `c6e03a413069860e4bfd9c72307285431573f612b6b2785117080ede9863310c`.

### Historical P2-09 authorization correction under validation

The actual `p209-s33-working-01` matrix passed 95 cases and failed eight. One failure exposed a legacy MCP authorization race: `list_activity` could commit pagination metadata while concurrent `get_summary` rejected a missing portfolio scope. The gateway now checks all declared tool scopes before any service dispatch and uses the runtime authorization clock. All nine legacy tools have exact-scope positive controls and zero-dispatch assertions for missing scopes and expiry; this regression first failed all nine cases against the original production source (`p209-legacy-preauthorization-red-01`). Canonical owner/account authorization remains in application services.

The other seven failures were fixture errors. Six historical controls selected an unfinished inclusive UTC day; selecting the previous closed day passed all six (`p209-s33-closed-day-01`). A single-holding plan correctly had no second page; a second real canonical catalog holding makes both planning cursor cases pass (`p209-s33-plan-cursor-01`). These changes preserve the denial, immutable-state and cursor assertions.

The corrected matrix `p209-s33-working-02` passed all 112 cases in 71.634 seconds, with unchanged working source. These are working-tree results, not immutable acceptance. P2-09 and its S33 scenario remain open pending the correction commit and relevant immutable MCP, PostgreSQL, static, security and build checks. The full d70ab44 validation and its original limited acceptance artifact remain historical evidence at that exact source; no new full browser or deployment result is claimed. GitHub Actions remains owner-deferred.

The follow-up `p209-s33-regression-working-01` passed 576 MCP unit, contract, security and PostgreSQL cases, including canonical API parity, durable commands and collection capacity/rollback. `p209-s33-static-working-03` passed the workspace, format, lint, type, generated-contract and documentation checks. `p209-s33-security-build-working-01` passed `make security-check build-python`: SAST reported zero findings across seven rules and 547 scanned files; configured secrets and Gitleaks exception negatives passed, locked dependency audits passed, and all Python distributions built. These remain working-source checks; immutable correction acceptance follows separately.

The first exact-index Gitleaks scan (`p209-s33-staged-gitleaks-01`) flagged three synthetic X-ray provider/policy/evidence labels as generic API keys. Source review confirmed these were literal fixture metadata passed to typed registrations, with no credential or external transport. They were renamed to the explicit label `synthetic`; no scanner rule, exception, credential or application behavior changed. The failed scan receipt remains retained, and the affected X-ray checks and staged scan are rerun before delivery.
