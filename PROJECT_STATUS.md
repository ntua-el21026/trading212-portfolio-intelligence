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
Phase 2 now has four of ten packages, eleven of 29 local rows and eighteen of 40
scenarios complete (40%). P2-05 through P2-10 and shared release predicates remain
required. Real reference provider configuration/licensing remain unavailable.
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

See [runtime](docs/implementation/evidence/phase-2-p2-04-2a7c89a-runtime.json), [security](docs/implementation/evidence/phase-2-p2-04-2a7c89a-security.json) and [compatibility](docs/implementation/evidence/phase-2-p2-04-2a7c89a-compatibility.json). Phase 2 remains `in_progress`: four of ten packages (40%), eleven of 29 local rows and eighteen of 40 scenarios complete. P2-05 through P2-10 and Phase 3 remain `not_started`; no final Phase 2 release SHA is claimed.

Source-backed known P2-08 limitations remain: the normal complete seed has three accounts, but Compose does not forward the documented T212PI_ACCOUNT_ID setting to web; unconfigured multi-account overview startup is not accepted. The accepted runtime used an explicit baseline-account scratch override. The global header must respect the authorized route account. Sticky-header section positioning, readable mobile labels and table presentation remain P2-08/S39 follow-up work. Configured runtime acceptance does not prove default unconfigured multi-account UI behavior.

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

Proceed to P2-05 after its authority synchronization, then P2-06 through P2-10 under the accepted [v0.2 design delta](docs/DESIGN_FREEZE_V0_2.md). Preserve these separate external
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
