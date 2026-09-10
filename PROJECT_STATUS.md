# Project Status

**Project:** Trading 212 Portfolio Intelligence

**Repository:** `ntua-el21026/trading212-portfolio-intelligence`

**Implementation authority:** `main`

**Updated:** 2026-09-09

## Current state

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
P2-05 is **complete** at `7b102663ea193b4668924a7252180731954f4b00`. The [accepted assertion map](docs/implementation/evidence/phase-2-p2-05-7b10266.json) closes P2-XRAY-001/002 and P2-S20 through P2-S23. Phase 2 has five of ten packages (50%), thirteen of 29 local rows and twenty-two of 40 scenarios complete. P2-S34 and P2-S38 remain `in_progress`; report/export parity and the remaining release-wide predicates are outstanding. P2-06 is `in_progress`; P2-07 through P2-10 and Phase 3 remain `not_started`.

The clean exact-source `make validate` passed in 2339.747 seconds: 1,642 isolated and 234 service/migration Python tests, 88% combined statement/branch coverage, 223 web unit tests and 76 browser checks without retries. Assertion selectors are source mappings bound to completed test-file observations.

Exact-source CI passed: Quality `34347516142`, Documentation `34347516068`, Security `34347516074`. Eight source/history/image scans passed under the recorded scanner policies. The fresh runtime passed in 146.262241 seconds, preserving identical retained rows across all 167 compared tables and API/MCP replay after all seven services stopped/restarted. Task containers, volumes and networks were removed, with absence verified. All eight exact-gate screenshots received the recorded visual review.

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

## Next action

Complete P2-06, then proceed sequentially through P2-10 under the accepted [v0.2 design delta](docs/DESIGN_FREEZE_V0_2.md). Preserve these separate external
owner/deployment conditions without substituting synthetic evidence:

1. Run the owner-controlled Trading 212 Demo smoke when a dedicated read-only Demo
   credential is supplied.
2. Select the production host, identity provider, and secret manager.
3. Deploy the authenticated MCP endpoint over public HTTPS/OAuth and complete ChatGPT
   registration.
4. Continue to report unavailable real-provider opening-history coverage explicitly
   unless valid provider evidence becomes available.

The accepted direct-`main` policy is the only active delivery mechanism. Frozen
architecture and safety decisions remain unchanged. Phase 2 is `in_progress`; Phase 3 remains `not_started`.

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
Five packages are complete (50%); S34/S38 remain partial. P2-06 is in progress;
P2-07 through P2-10 and Phase 3 remain `not_started`.

## P2-06 implementation in progress

Reports and exports start from synchronized P2-05 closure
`5ff85b4436ec9be886639e6e2cf0c722fc0c4a73`. The
[implementation contract](docs/implementation/P2_06_REPORTS_AND_EXPORTS.md) fixes
bounded canonical capture, durable jobs, private PostgreSQL artifacts, current
principal/source authorization and the four output formats. Focused canonical,
renderer, authorization, licensing, privacy and retention checks have passed on
the uncommitted implementation; full package acceptance is still pending.
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

The PostgreSQL CI job budget is now 90 minutes. The measured local coverage phases
took 311.56 and 1,796.99 seconds; applying the prior accepted P2-05 local-to-CI phase
ratios estimates about 69.18 minutes for that CI job. This is a budget estimate,
not a measured P2-06 CI result. The full test selection and coverage remain unchanged.
Clean exact-source validation, three exact-source CI jobs,
image/security scans, fresh Compose acceptance and reviewed final-source screenshots
and PDF remain outstanding. Validation continues serially in one task Compose project,
using PostgreSQL alone when sufficient and Redis when required. Inactive generated
outputs are removed at check boundaries; September 10 cleanup removed 505,727,234
logical bytes of inactive Next development output after checking for active consumers,
preserving production outputs, dependencies, source and retained evidence.
The alerts dataset requires the real P2-07
producer; it must fail before job creation until that producer exists.
