# Phase 3 stabilization checkpoint — 13 November 2026

Status: bounded local verification recorded with explicit limits; delivery record pending; no package or release accepted.

## Current bounded checkpoint — 14 November 2026

The implementation is frozen at `153854f7b32a235a8aa5bdaa13c079bc07407a05`,
tree `2c1e56fcddcb37c7815e6f2d4e83a9b47bb2d45b`. Owner-directed incremental
verification retains each completed scope at its actual source, reruns failed
cases and continues previously unreached groups. Complete Make validation was not
rerun; complete coverage remains pending under that instruction. Earlier complete
attempts retain their failed or interrupted outcomes.

The browser inventory verifies retained passing observations for all 132 required
cases across 69 spec/viewport groups: 67 groups have an actual full-group pass;
intelligence desktop and workspace desktop use explicit case partitions. These
observations span 12 executed source snapshots. No API case was re-executed at
this packaging-only commit. Its single Dockerfile COPY addition leaves the other
1,926 source inputs, including application, test and dependency inputs, identical
to the preceding implementation. This is neither a new whole-suite invocation
nor a same-source matrix pass. Failures, dirty inputs, zero-case setup errors and
process-descriptor visibility limits remain in the inventory.

Nine current runtime image IDs have source-bound nonroot, version, CA, dpkg and
package-manager checks and configured vulnerability/secret scans. Fresh dependency
checks cover 67 active Linux Python requirements and 144 production Node
dependencies with zero reported vulnerabilities/advisories. Two other declared
Python requirements are platform-inactive, not skipped audit work. The exact
source filesystem and history scans recorded below qualify the preceding
`881f283` source; final documentation-source/history scans are separate work.

Ordinary nine-service synthetic startup, the corrected frontdoor browser smoke
and task-only cleanup have actual passing receipts. The failed first smoke and
its missing-public-assets defect remain recorded. The implementation archive
covers 1,927 paths with committed Git modes; actual local permissions are retained
separately. All 30 Phase 3 rows and 48 scenarios remain pending, zero accepted.
Independent owner audit, owner-deferred CI, production and Live authorization
remain unchanged.

The compact [evidence index](evidence/phase-3-stabilization-20261113.json) binds
completed implementation, browser, security, startup and cleanup observations.
Post-documentation scans, source equivalence, fast-forward delivery, actual CI
observation and portable-export integrity belong to the later external delivery
record. No future commit or bundle hash is asserted here. Logical evidence paths
support audit and are not machine-specific clean-clone prerequisites.

## Scope and source

The owner authorized baseline recovery, dependency and build remediation,
contract/browser regressions, and the interrupted P3-08 aggregation vertical.
The assignment excludes new features, remaining Phase 3 feature packages,
Phase 4, production deployment, Live access, release tags and 1.0.0 acceptance.

Starting local and fetched remote `main` were
`64e2057cb9b1ddee11649f605e968b18bd559fcb`, tree
`d4ca30e22e09496c27913456e528d740f4895e21`. The working tree was clean.
GitHub repository metadata identified public visibility. The proprietary
[licensing terms](../../LICENSE.md) remain unchanged. The owner requested the
name spelling **Michail Athanasios Peppas** in current documentation; the README
and copyright notice follow that spelling.

The [September checkpoint](PHASE_3_RESUME_20260930.md) remains a historical
record. Its external operator paths and unfinished staged feature work are not
clean-clone prerequisites and are not incorporated by this stabilization task.

## Reproduced baseline

| Observation | Source and disposition |
| --- | --- |
| Documentation, workspace, Ruff, architecture, broker boundary and generated contracts | Passed at the unchanged starting tree. The adapter still exposes exactly ten GET capabilities. |
| Historical/scenario contract subset | Three failures and four passes at the unchanged starting tree. The accepted aggregation and saved FX read add five paths and seven operations; current canonical generation matches committed artifacts. Historical descriptor and client compatibility require explicit checks of these additions. |
| Original aggregation selector | Reproduced PostgreSQL `aggregate native component proof differs` before its expiry assertion. |
| Native-component diagnosis | Synthetic SQL diagnostics show components inserted before input memberships. Native IDs, values, currencies, snapshot associations, quality and provenance match; membership is absent at the trigger check. SQLAlchemy does not infer trigger-only dependencies. |
| Python dependency audit | Fresh pip-audit 2.10.1 reports 64 advisory records across five packages. This exceeds the 62 records in the cited historical CI run. |
| Node dependency audit | Fresh production audit reports five high and three critical findings, plus moderate/low findings. Remediation and rescanning remain in progress. |

The cited quality and security Actions runs used
`3bbb212aa8742ccc7e2f3bf83d6af42694682714`, an ancestor of the starting source.
Their logs establish historical failures, not results for the stabilization tree.
No workflow is enabled, disabled, retried or weakened by this task.

## Implemented corrections and component evidence

Publication now flushes snapshot membership before native/FX dependants, admitted
FX before converted components, and root activity digests before guarded activity
payloads. These boundaries remain inside the original transaction, with deadline
checks and final authorization/sealing. Provenance, capacity accounting and
rollback remain enforced.

A separate transfer failure came from casting canonical tagged source JSON as
bare scalars. Forward migration `20261113_0034` follows actual head
`20260915_0030` and replaces five source-side casts with strict finite Decimal
and UTC instant decoders. It adds no table, column or index and rewrites no source
record. The original guard comparisons remain intact. Revision `0030` remains
85,363 bytes with SHA-256
`e0a925d63d92a066f116eccd909fb1714fefaff5aea1aa6d74cb1078ec95c3be`.
Reserved handoffs `0031`–`0033` remain unintegrated; future authorized integration
must follow the actual ledger. Populated downgrade is denied.

New PostgreSQL regressions verify source identity/provenance, forged native and
transfer proof rejection, complete copied-row/capacity/command rollback, current
ownership, restart/replay, strict encoding and populated forward-upgrade source
preservation. Newly created aggregation fixtures use actual UTC rather than an
expired August application clock; historical X-ray facts and database clocks
remain unchanged.

Contract tests name exactly the seven accepted additions while retaining the
original schema/client fingerprints. Browser corrections scope semantic locators
and give widget test hosts real viewport metadata; width, focus, overflow,
keyboard and exact-value assertions remain. Production widgets are unchanged.
The historical synchronization timeout has not reproduced; its five-second
assertion is unchanged and its CI root cause remains unverified.

The MCP 2.2 compatibility configuration explicitly retains the existing shared
JWT audience-verification boundary. Nine signed RS256/ES256/EdDSA transport
cases accept the configured audience and reject substituted resource/foreign
audiences. SDK warnings become test errors; no warning is suppressed.

The following are actual precommit working-tree observations. Their full file
manifests bind the tested composition; they do not qualify the unchanged starting
HEAD or constitute an immutable release pass. Failed predecessors remain retained.

| Command or scope | Observed result |
| --- | --- |
| Full formatting, lint, strict typing, documentation and generated-contract checks | Passed; mypy inspected 1,134 files before the subsequent SDK test addition. |
| `pytest tests/unit tests/property tests/contract tests/security` | 5,386 passed, no failures/skips; 107 warnings before the explicit SDK configuration correction. |
| Focused signed JWT/MCP follow-up | 343 passed with no warnings, including nine new cases; Ruff and strict typing passed. |
| `pnpm test:unit` | 918 passed across 103 files. |
| Aggregation, migration, custody and saved-FX PostgreSQL subset | 27 passed; zero failures, errors or skips. |
| Full demo Playwright suite | 196 passed; the subsequent stricter scoped credential-visibility assertion passed both viewport cases. |
| Targeted browser regressions | 18 passed after retained selector/viewport failure proofs. These overlap the full demo suite. |
| Python 3.13.15 runtime requirements / production Node audits | Zero known vulnerabilities / zero findings at every severity. |
| Six runtime image builds and probes | Passed; application UID 10001, PostgreSQL/Redis UID 999; package-manager rejection and retained dpkg metadata verified. |
| Six immutable-ID Trivy vulnerability/secret scans | Zero configured HIGH/CRITICAL findings with available fixes and zero secrets; existing `ignore-unfixed` policy retained. |
| Complete 1,920-file candidate source export | Configured Trivy vulnerability, secret, configuration and license gates passed. |
| Git history / existing secret policy | Zero Gitleaks findings after 38 individually reviewed additions to 19 existing exceptions (57 total); 16 approved-line and 21 negative policy cases passed. Two adjacent-line canaries also remained detected. |
| Host production build and artifact checks | Passed; runtime-only secret and export-URL canaries absent from all five declared artifact paths. |

The additional unfiltered working-directory scan failed three license
classifications in ignored installed third-party files (psycopg notices and a
ReportLab font notice). That distinct result is retained. No license file or
scanner gate was removed; public binary redistribution remains unauthorized.

The first immutable-source `make validate` attempt failed as recorded below. A
new complete target and API-backed production browser qualification remain pending.

## First immutable gate and retention fixture recovery

The first complete target ran at committed `cac650324ef9f74557400fa31199b8d8f59feac8`,
tree `68856b88e7743aa16ffe9464a5f4f7b16bf87ede`. Formatting, lint, strict typing,
4,744 Python unit tests, 918 web unit tests, 36 property tests and 357 contract
tests passed. The integration invocation selected 730 cases; it was interrupted
after two failures and 108 passes to collect the failure tracebacks. The target
failed, its source manifest was unchanged, and later stages were not reached.
Its failed receipt and log remain retained rather than being combined with
subsequent component checks into a complete pass.

The two enrichment failures expected two completed purges from 32 inspections.
Accepted ADR-0032 physical accounting reserves 64 inspections for one payload
mutation, before scheduling and marker/progress/completion costs. Related source
fairness fixtures had the same obsolete expectation. Their expiry ordering also
did not establish the UUID order used by the physical scan. The corrected tests
retain a separate 32-inspection no-removal probe, verify actual payload equality,
and use 257 explicitly ordered busy sources per family against a 256-inspection
allowance. Committed resumes must preserve bounded row/byte work and durable
progress, complete the free owner's exact events while the busy owner remains
locked, and then drain all blocked sources with unchanged identities and hashes.
Production retention code, guards, costs and ceilings are unchanged.

The source partial-purge fixture assumed its one permitted removal must remove
an observation. SQL tracing instead showed one charged deletion of projection
sweep metadata. The corrected fixture retains the one-removal allowance and
requires bounded committed progress until exactly one target observation is
removed, followed by the original parent, completion and replay assertions.

A risk-copy fixture required a downstream marker after a zero-removal source call,
which correctly returns before copy participants. Its zero-removal probe now
checks unchanged canonical bytes, normalized rows and expiry events. A separate
two-removal probe reaches the pending risk marker after the original-source and
historical-copy projection sweep deletions. Direct database queries verify that
the original source observations and canonical risk bytes remain intact; the
original financial-drain and capacity assertions still run. An initial new
one-removal probe could not cross those two metadata removals; that failed attempt
and both diagnostic parser versions remain retained.

The empty-head migration test still expected revision `0029`, despite the
aggregation and decoding migrations. An actual red execution confirmed head
`0034` after repeated upgrade and metadata parity. Only the explicit current-head
expectation changes; historical revision checks and SQL migrations are preserved.

The task stack now uses the documented free loopback ports 5432/6379 because some
legacy fixtures use them directly. Its images and disposable task volume are
identical across the port remap; the earlier high-port configuration remains in
its original evidence. These corrections are test-only follow-ups. The complete
target must be rerun against a new clean committed checkpoint before claiming
complete local validation.

The following actual focused follow-ups passed after their retained red attempts:

| Scope | Observed result |
| --- | --- |
| Strengthened enrichment fairness and full blocked-source drain | Two cases passed in 141.13 seconds; the owned test and production bytes were stable during the run. |
| Complete source dispatch/retention file | Seven cases passed in 346.15 seconds with an unchanged complete source manifest. |
| Empty/repeated current head and ORM parity | One case passed in 3.92 seconds. |
| Zero-removal and source/risk copy boundary | One case passed twice with observational SQL tracing; latest 28.60 seconds, unchanged source manifest. |

## Remaining preflight compatibility corrections

The second complete target ran at clean `2aa6c1b2d09ea701bb89acf6935a57b859cb2a71`,
tree `c2fed51636bbb663b3f087c4a7a6c1d1dc7d9cea`. It was interrupted after
2,814 passing unit cases, with no observed runtime failure, when a read-only
preflight found four further explicit inconsistencies. It is an incomplete
attempt, not a complete validation result. A separate four-case invocation on
that unchanged committed source reproduced all four failures in 38.01 seconds.

The projection populated-downgrade test expected old head `0029`; the failed
transaction correctly retained `0034`. The populated risk upgrade expected 344
current tables, predating the 20 aggregation tables. It now checks exact current
table-name parity with ORM metadata, preserving its original 212-table legacy
fingerprints and complete financial replay assertions. Both corrected migration
cases passed in 25.52 seconds.

A second source-expiry fixture repeated the one-removal/one-observation
assumption. It now retains that allowance while checking bounded committed
progress, exact first-observation removal, no premature expiry, immutable parent
identity, access denial, complete removal and replay. The X-ray capacity fixture
required a collection mutation costing 48 inspections under an allowance of eight.
It retains the eight-inspection no-removal boundary with full physical payload
parity, then verifies an exactly-one-pair partial purge under 64 inspections while
capacity rejection commits progress. Bounded 256-inspection resumes release the
old collection and preserve the original context and financial summary.

Both retention selectors passed in 15.34 seconds. The complete shared source
module then passed all 23 cases in 10.54 seconds. These scopes overlap. One earlier
follow-up command omitted `TEST_DATABASE_URL` and recorded one pass and one setup
error; the corrected explicit synthetic command and original error receipt remain
separate. Common source/X-ray fixture functions and production code are unchanged.
A new complete immutable target remains required.

## Subsequent immutable attempts and report fixture recovery

Attempts 03–05 used implementation
`d61918fa638eb9b1a0bab94642dd12094dc5f3bb`, tree
`26146d194e813748be61e8435816a1501e3cb39c`. None completed the full target.

The third attempt stopped during Python unit tests. Its partial log and source
comparison at resumption are retained, but no runner receipt, final test count or
exit code is available. The exact termination cause remains unverified. The
fourth attempt was interrupted to replace attached execution with durable
execution: 1,198 unit tests passed, with no observed runtime failures. Its receipt
records exit 2 after 84.4 seconds and unchanged source. Neither attempt
establishes a complete gate pass.

The fifth attempt ran the existing `make validate` target with pinned tools,
isolated inherited database configuration, the synthetic task database and
provider, Demo defaults, Live disabled, an empty credential bundle and
`PYTEST_ADDOPTS=--maxfail=1`. That option stops on the first failure without
changing successful-target scope or assertions. Its source remained unchanged.
The receipt records exit 2 after 1,586.938 seconds. Before integration, 4,744 Python
unit tests, 918 web unit tests, 36 property tests and 357 contract tests passed.
Integration then stopped with 151 passed, one failed and 5,520 deselected in
1,017.17 seconds. Later target stages were not reached.

The failure was
`test_legacy_report_retention_postgres.py::test_v2_report_only_policy_resumes_and_preserves_saved_risk`.
PostgreSQL rejected the fixture's report-input chunk with `Report capture is
closed`. An unchanged-source diagnostic reproduced the failure: the unsealed,
unpurged header had an October 7 deadline under the actual November 13 database
clock. The expiry guard operated correctly. The narrow fixture correction uses
actual UTC for operational admission, capture and maintenance, with report expiry
clamped below the source root's deadline. This V2 correction preserves financial
windows, valuation times, source knowledge cutoffs, identities, production guards
and retention budgets. Historical helper defaults retain their original clocks.

The original V2 selector then passed once in 28.38 seconds. A broader six-case
follow-up retained two passes and one failure before stopping: the V3 sensitivity
source was also expired under the database clock. Its runtime fixture now advances
operational publication and fresh-run admission through the normal services.
Further source-availability constraints are recorded below. Adjacent report
privacy fixtures exposed the same operational-clock problem and a canary aimed at
a decoder no longer imported by the report service. The canary now targets the
actual domain manifest decoder and retains its authorization, SQL-read, grant,
content and fail-before-decode assertions. The corrected privacy module passed
all three cases in 136.25 seconds with unchanged source during that invocation.
Its original run failed all three cases in 85.15 seconds; a clock-only follow-up
also failed all three in 135.48 seconds at the stale decoder target. Both failed
predecessors remain retained.

The next six-case report-retention invocation finished with four passed and two
failed in 162.22 seconds, with unchanged source during that invocation. V3 source
setup passed its earlier expiry point, but report generation returned
`ACCESS_DENIED`; the premium risk-purge case did not finish in its single final
4,096-inspection maintenance call. A combined boundary/preflight diagnostic then
reproduced five failures in 92.41 seconds with unchanged source.

The V3 capture had a valid basis and restricted sources. All twelve physical
original-source headers were created on August 31 with stored 365-day lifetimes.
The separate 30-day limit for copying original sources into reports still denied
the November capture correctly. A fresh runtime fixture therefore requires newly
published typed source versions and an explicit current availability cutoff.
Selecting newly observed versions under the old cutoff would violate
`first_observed` semantics. The authorized correction preserves historical
economic dates and existing rows; negative old-cutoff coverage and exact financial
parity remain required before claiming success.

The annual risk cleanup diagnostic showed valid partial progress under the
unchanged 4,096-inspection allowance: financial rows decreased from 752 to 632,
with 16 inspections left. The report-pending flag cleared while canonical content
remained and the retention marker was incomplete. A single call need not finish
this work. The fixture must resume within the existing per-call budget and retain
its original completion and physical-erasure assertions.

The same diagnostic reproduced expired positive report fixtures in three
previously untouched scopes:

- `test_report_v3_retention_postgres.py::test_current_report_rights_revoke_read_and_sweep_only_the_report`;
- `test_premium_reports_postgres.py::test_selected_risk_all_formats_and_sql_version_collections[False-2]`;
- `test_premium_reports_v3_postgres.py::test_saved_scenario_four_formats_original_proof_and_ttl_clamping[EUR]`.

Fresh runtime helpers now publish normal typed source versions with actual
`first_observed` times and an explicit current knowledge cutoff. They preserve
historical economic facts and old rows, reject new versions under the old cutoff
and compare selected financial results. An initial risk helper narrowed reference
coverage to the report's month. An actual diagnostic failed once in 30.67 seconds:
all 31 daily valuations were unavailable, with 36 summary and 837 series
differences. The original rows and original calculation had zero differences.
The correction restores the complete original 732-day reference period within the
existing 1,000-day batch ceiling; the 31-day report window is unchanged. It retains
all price, FX and action observations and coverage, full financial summary/series
parity and context checks. No original trace is truncated or parity assertion
dropped. The first fresh-source four-selector invocation failed all four cases
in 58.59 seconds; three failures were a helper inventory-field error and the fourth
was the risk parity mismatch. That failed predecessor remains retained.

A subsequent four-selector invocation finished with three passed and one failed
in 216.78 seconds, with unchanged source during that invocation. Its complete
source manifest is
`b23085472e1f88d590dfa8b1d367f9874c378d1929004cf1e7ab175ccfa7fadc`.
The passing selectors cover V3 incremental cleanup with the 192 budget and
canaries, the selected risk profile2 case with all four report formats and the
complete original 732-day trace, and the EUR scenario case with four formats,
TTL clamping, isolation and revocation. The separate risk-budget resumption
selector passed once in 28.51 seconds. These are focused observations rather than
whole-module passes. An internal fixture review corrected a second report's
selection rebuild to preserve its original financial valuation date; a tentative
one-second-slack concern was withdrawn after verifying the equal frozen fixture
clocks. Internal peer review does not constitute the separate owner audit.

### Confirmed original-source report deadline defect

The remaining historical-replay selector failed at report generation with
`ACCESS_DENIED`. Its first unexpected authorization trace had a valid basis and
restricted sources. The root and capture expired 30 days after root creation,
but the original price and FX versions had been created 9.981752 seconds earlier.
Their stored 365-day lifetimes remained valid. The original-source report-copy
limit ended 9.981752 seconds before the capture's proposed expiry, so the existing
authorization and SQL checks correctly denied it. Later EUR observer denials came
from expected revocation assertions in its passing test.

This exposed a production metadata-clamping defect: the report sink considered
root/copy and stored dependency expiry, but missed the original physical source's
creation time plus the applicable minimum of 30 days and pinned/current licensed
copy limits. The correction follows the existing ADR-0024 and SQL contract in two
production files. The source helper uses scalar headers from nine closed physical
families, validates owner/source/provider/license/digest/expiry proof, and reuses
the already authorized pinned/current license pair. It rejects future origins and
exhausted copy windows, bounds dependency traversal at 100,000 and caches at most
256 license pairs. The sink folds the resulting original-source deadline into its
existing minimum for contract versions 3 and 4 before assigning final expiry and
performing SQL authorization. Physical dependency expiry and its exact proof,
V1/V2 behavior, financial payloads and SQL guards remain unchanged. Fixture
licenses retain their original 365/3,650-day durations.

Five new PostgreSQL regression cases verify the current seven-day and original
30-day limits, forged physical-expiry rejection, a valid new open capture at the
exact boundary, rejection one microsecond beyond it with SQLSTATE `23514`, and
atomic rollback for expired original sources and revoked REPORT permission. The
expired-original API case establishes rollback; it does not establish a new
predecode-denial guarantee. Existing revocation canaries remain in place. The
previously failing replay also passed all four report formats with input and job
expiry exactly at original price creation plus 30 days, before root expiry, while
physical source/dependency proof retained its original 365-day expiry.

The combined five-case regression module and replay selector passed all six cases
in 206.13 seconds, with a 208.172-second runner duration and unchanged source. Its
complete source manifest is
`0ac7cabc7dab06a303088966927c1170d7ef585fd4f524e41759aa357d48c6a3`.
Full Ruff checks passed and strict mypy passed over 1,138 source files in a
4.497-second invocation. Internal patch and regression reviews found no actionable
issue within their inspected scope; they do not replace the owner audit.

The broader 43-case invocation across nine relevant files finished with 40 passed
and three failed in 1,554.46 seconds, with a 1,561.719-second runner duration, exit
1 and unchanged source under the same complete manifest. All three failures were
in `test_premium_reports_v3_postgres.py`: the GBP all-format case and the queued
and cancelled variants of the unsucceeded-scenario case. The GBP helper labeled
an FX page with adapter `fx-v1` while its actual provider declared `replay-v1`.
The two negative cases used expired August 31 roots and therefore correctly
returned `ARTIFACT_EXPIRED` before their intended state check.

The test-only follow-up aligns the new FX adapter literal with its actual
provider. It cancels the original queued run at its original clock, advances
operational time, and normally admits a fresh queued run with a new idempotency
key. Financial fields, source cutoff and X-ray selection are retained, as are the
expected `REPORT_UNAVAILABLE`, canaries and zero-report assertions. The four-case
scenario file then passed all four cases in 232.26 seconds, with a 234.173-second
runner duration, exit 0 and unchanged source under manifest
`ac468377184d30610a8f3f969fbf9dbf36fa1ddfe97e9c8c19ee675d49e0c460`.
Production report bytes are identical to those in the six-case and 43-case
invocations. Ruff, strict mypy over 1,138 files and formatting
over 1,143 files passed after these two fixture-file corrections. The remaining
39 cases require the subsequent complete gate. The retained 40 passes and this
four-case result do not constitute a new 43-case pass.

A new complete target against a clean immutable checkpoint remains required.
No full validation, browser, package or release acceptance is claimed from these
observations.

## Sixth complete target and web retry readiness

The sixth complete target ran at clean
`6502a5afe49408c6d0672583da9e18956ccff8a2`, tree
`31d533ef7e9cf893b5f431ffd7eab7913de62f7e`. It failed with exit 2 after
393.808 seconds, with unchanged source under manifest
`5467fc28bd3e6b6d4f8f526b8c0886a5b4a91352f1182df41475e25d9c9f001d`.
Formatting, linting and typing passed, followed by 4,744 Python unit cases in
359.98 seconds. The web unit suite finished with 917 passed and one failed out of
918 cases, across 102 passing files and one failing file. Property, contract,
database, migration, security, coverage, browser and build stages were not reached.

The failure was the retry/idempotency case in
`apps/web/tests/owner-layout-forms.test.tsx`. Its error alert was already visible
while the form still displayed disabled `Saving` controls. The asynchronous
transition's notice update did not establish that its pending state had settled;
the test requested `Create layout` before that readiness condition. Application
frontend source and locks were byte-identical to the earlier fifth target's
918-case web pass. That earlier receipt does not qualify this failed invocation.
The original file passed all four cases in an isolated 1.07-second invocation,
which did not reproduce the full-suite failure.

The test-only correction awaits the exact enabled `Create layout` control after
each response before retrying, editing or finishing. Original command counts,
idempotency identities, edited content, revision/order and navigation assertions
remain, without timeout changes, artificial sleeps or automatic retries. The
corrected file passed all four cases in 1.11 seconds, with a 1.557-second runner
duration and unchanged source during that invocation.

The subsequent full web-suite invocation retained a different failure: the
scenario editor's retry-identity case expected two submit calls but observed one.
It finished with 917 passed and one failed in 8.64 seconds, with a 9.226-second
runner duration and unchanged source under manifest
`40e5ac611fb85d8e7bbb110007bf5cf2c7a489b4970d1e193106d414471d3163`.
This failed follow-up is retained separately from both owner-layout focused passes.
The original scenario file also passed its seven isolated cases, without
reproducing that full-suite failure. A source audit found similar readiness gaps
in the risk, research and aggregation form tests; these three were static findings,
not reproduced runtime failures.

Corrections are confined to the five form-test files. Each affected sequence now
awaits its actual enabled semantic submit control before retrying, editing or
settling the final response. The aggregation test retains its early `Reload` and
immediate rerender before awaiting the next `Calculate` control. An assertion
comparison retained all 104 original `expect` assertions; the final tests contain
112. Product code, configuration, dependency locks, timeouts and retry policy are
unchanged.

Two authoring negatives remain retained. A new scenario-control literal initially
selected the wrong button and produced ten passes and one failure in a focused
invocation. Separately, TypeScript rejected unsupported `exact: true` role-query
options. The final tests use supported string-name matching and actual enabled
controls; no type suppression or assertion removal was introduced.

The final five-file focused invocation passed all 32 cases in 1.28 seconds, with
a 1.714-second runner duration. The complete web suite then passed all 918 cases
across 103 files in 7.89 seconds, with an 8.369-second runner duration. Both exited
0 with unchanged source under manifest
`d2bbd8574a8bb0a00eb700d2ae30a20699d708feafd05aa0d07e385d4994390e`.
Formatting, lint and TypeScript checks also passed on that composition. These
focused cases overlap the full web suite. The Python pass from the failed sixth
target and this corrected web pass do not constitute a complete validation pass.
A new clean immutable checkpoint and complete target rerun remain required; no
later stage or release acceptance is inferred.

## Seventh complete attempt and exact signed MCP discovery

The seventh complete target ran at clean
`c907cac919535b21b4c57f5f8d5b76020a52ed56`, tree
`35bb8ea9f9b27e0d019c977dd4bbbb46bd36ba16`. It exited 2 after
3189.445 seconds with unchanged source manifest
`b68c689a8e3f94dfd194f762821a3f094fefe18e179fa7b6b4ecb8f44d545531`.
Formatting, lint, strict typing, 4,744 Python unit cases, 918 web unit cases,
36 property cases and 357 contract cases passed. PostgreSQL integration stopped
with 353 passes, one failure and 5,520 deselections in 2,643.46 seconds. The failing
signed projection exchange hid exception values through its existing secret
guard. Later migration, security, coverage, browser and build stages were not
reached; this attempt remains failed.

An external bounded observer reproduced the unchanged test's failure at authored
line 137, `len(descriptors.tools) == 36`, with one failed case in 9.84 seconds.
The observer exposed only a safe authored location and closed tool identifiers;
no bearer, payload, exception text or local variables were persisted. Existing
contract tests already establish the exact research addition from 36 to 38 tools:
`get_research_summary` and `get_research_item`. The projection-only 32-to-36
contract deliberately disables research registration and remains unchanged.

The correction affects three current-runtime signed discovery tests and one new
test-only helper. Its independent oracle combines the preserved 25-case catalogue
with 13 explicitly authored risk/scenario/projection/research names. It asserts
exactly 38 unique names, exact set equality and the final two research names in
order. The real-JWT test's stale 28-name set is corrected by this same closed
oracle. Original descriptor/schema/security checks and all financial parity,
worker execution, replay, paging, current grant, foreign-owner and secret-canary
assertions remain. Product, dependency and historical contract files are unchanged.
Internal static peer review found no blocking issue; owner acceptance remains
pending.

The focused invocation of the complete projection, risk and real-JWT integration
files passed all 50 cases in 138.02 seconds, with a
140.825-second runner duration, exit 0 and unchanged source
manifest `7f7230f1fc699aa71ce589a9aa18ac6d4d17117ef06312d780e7421d935de8ba`.
Its receipt and failed reproduction remain distinct from the failed complete
target. A clean immutable checkpoint and complete target rerun are still required.

## Eighth complete attempt and X-ray inspection boundary

The eighth complete target ran at clean `32777c78af6fb61a4e99bc96241b1602dfe391e8`,
tree `2d729f5bde0e3065b2987587132618bb55451b99`. It exited 2 after
1871.098 seconds with unchanged source manifest
`66ee7ed524fe654b48034224f42bbac646ad174904d170f3aede69762fc9daa3`. Static checks, 4,744
Python unit cases, 918 web unit cases, 36 property cases and 357 contract cases
passed. PostgreSQL integration ended with 284 passes, one failure and 5,520
deselections in 1,340.04 seconds. Report API authorization passed before the failure
in `test_actual_partial_erasure_keeps_membership_and_never_calls_full_oracle`.
Later complete-target stages were not reached.

The existing X-ray parent loop reserved one lookup inspection, performed SQL and
then charged a second inspection if it found a parent identity. An invocation
with exactly one inspection remaining could issue that query and raise instead
of retaining pending cleanup. This is a production budget-precondition defect.
The loop now requires two available inspections before SQL and returns `False`
when they do not fit. Existing charging remains exact: an empty lookup consumes
one row, and a returned parent consumes two. SQL predicates, stable ordering,
`LIMIT 1`, post-fetch invariants, physical mutation costs, limits, financial bytes,
source authorization and anti-forgery guards are unchanged.

Five new deterministic unit cases cover path and composition lookups with one
inspection missing and with the exact allowance, plus empty probes' one-row cost.
Before the production change, both one-short cases failed with the observed
RuntimeError and three controls passed in 1.21 seconds. After the change, all 31
focused shared-budget/physical-retention unit cases passed in 1.23 seconds.
All nine existing PostgreSQL X-ray physical/read cases then passed in
92.28 seconds, with a 94.277-second runner duration.
Both green invocations retained unchanged source manifest
`824d58cb6062d4ffcd67e34872d2d210e0867b8386c5f7bf346a49c8818479a5`. The original 256-row
resume allowance, 256-turn bound, real counter/forgery checks, full-oracle canary,
partial capacity denial and complete drain assertions remain intact. Internal
static review found no blocking issue; owner acceptance remains pending.

Earlier successful invocations did not encounter this exact budget remainder;
the cause of that difference is unverified. Failed complete and focused receipts
remain distinct from these corrected-source passes. The next immutable complete
target uses `--maxfail=0` to collect every failure within a stage, preserving the
existing test selection, nonzero failure status, synthetic scope and single-stack
resource limits. No complete validation pass is inferred from this correction.

## Ninth complete attempt and source-bound retention-fixture recovery

The ninth complete target ran at clean `cd97b577ac063f1dbfa6b7ec64893130d1e37cce`,
tree `dfd1191911dfbb16aa6d6e51569a90d414797cf1`. It began at
`2026-11-13T21:01:44.043503+00:00` and exited 2 after 6,924.124 seconds with unchanged
source manifest `11ccd1a087ddb285c6189bf27aadb0f4459f891ce08916ff165eedf5574bd6ac`.
Static checks, 4,749 Python unit cases, 918 web cases across 103 files,
36 property cases and 357 contract cases passed. All 735 selected integration
cases ran: 723 passed and 12 failed, with 5,525 deselections, in 6,368.70 seconds.
The target failed; migration, security, coverage, browser and build stages were
not reached. The prior X-ray physical and signed projection MCP blockers passed
within this failed attempt. The collect-all setting changes neither test scope
nor failure status.

All twelve failure sites remain recorded, with separate causes and corrections:

| Failed case | Observed cause and correction |
| --- | --- |
| Projection published-result owner erasure | The unchanged aggregate guard rejected the active owner. Prove rejection and full rollback first, then terminate only target synthetic identities and retain original default-budget complete erasure. |
| Projection original source: price | A closed unchanged-source observer reports `RUN_EXPIRED` at assumption admission. Normal fresh publication uses actual PG time and explicit availability while preserving all three original financial observations and the 30-day source-copy ceiling. |
| Projection original source: historical | The same typed `RUN_EXPIRED` precedes the intended policy assertion. Capture the historical copy later than its fresh physical parent with a legal knowledge cutoff, preserving financial dates and the original-source two-day tightening control. |
| Projection original source: nested historical | The direct-original-price dependency assertion failed before admission. Keep the original reachable only through registered evidence and supply a distinct younger direct witness. Existing evidence-to-evidence rejection remains. |
| Projection original source: future price | Admission reported `RUN_EXPIRED` before the intended future-policy assertion. Fresh normal source publication preserves policy activation 30 seconds after maintenance and the exact original-source deadline. |
| Source-driven core report cleanup | Header erasure preceded completion-footer work. Retain the small-budget prefix, independently verify unchanged copies/grants when no marker fits, then use separately bounded adequate source and normal report-maintenance phases. |
| Enrichment-driven core report cleanup | Header erasure also preceded its completion footer. Normal report resumption shares the source invocation's remaining budget; a separately declared report-only phase completes outstanding footer work when needed. |
| Historical price/FX report cleanup | After 256 calls with 64 inspections, no report marker existed. Preserve that report-copy/grant-negative phase; a separate 256-inspection positive retains 64 removals and the 8 KiB byte limits. Require final header and work completion. |
| TTL query-plan capture | The first SQL was a pending-maintenance `TextClause`, before the intended TTL SELECT. A supported two-inspection remainder legitimately excludes the three-inspection prelude, preserving first-SQL/read-only/abort canaries and the explicitly scoped measurements. |
| Queued scenario owner erasure | The unchanged active-owner guard rejected the original lifecycle fixture. Rejection and rollback precede target-only synthetic identity termination, with queued-input, default-budget erasure and audit assertions retained. |
| X-ray source expiry | Its initial 128-inspection call reached source work with two rows and could not reserve the 32-inspection marker. Preserve the negative physical state and use bounded relevant-source rotation; distinguish source work, derivative-event eligibility and later copy completion. |
| Enrichment payload drain | The original 128 calls made continuing progress from 484 to 104 payload rows while completing none of ten work items. Retain this partial prefix, then a separately bounded 128-call continuation with identical allowances and all final event/payload assertions. |

The unchanged-source typed admission diagnostic failed its three selected cases
in 4.81 pytest seconds (7.148 runner seconds), recording only `RUN_EXPIRED`.
A separate unchanged-source metadata diagnostic retained three failures in
63.68 pytest seconds (66.417 runner seconds). Source-family routing and physical
counters distinguish insufficient allowance from continued progress. No canonical
payload, decoder, complete oracle or exception text was captured. These diagnostic
observations do not measure performance.

The correction is confined to six existing integration test files. Production
code, SQL guards, migrations, shared fixtures, global caps, the 30-day copy limit
and historical financial facts are unchanged in this follow-up. Fresh projection
sources use normal typed publication and explicit actual availability. Their
maintenance instant still tests the original physical source's two-day deadline
before the younger historical/direct witness can expire. Neither application
availability nor the database clock is backdated.

The core report fixture preserves its original maximum 128 calls with 64
inspections, 64 removals and 8 KiB inspection/removal limits. If that prefix leaves
no target marker, the test requires exact independent header/chunk/artifact
hash-state and grant-metadata parity and absence of target report work. A separate
positive phase permits at most 128 invocations with 256 inspections while keeping
the same removal and byte limits. The original marker and download-denial
assertions follow either route. Source cleanup then retains its bounded 256-row
phase. Once the header is purged, normal report maintenance first shares that
invocation's remaining allowance. Any remaining footer uses separate transactions
and fresh declared 256-row budgets, capped at 128 report-only invocations. No
allowance is reset within an existing source invocation. The successful run
qualifies its actual route; it does not claim every possible scheduling branch.

The X-ray request already explicitly pins its saved run. A safe reproduction
failed once in 10.20 pytest seconds (12.446 runner seconds), observing SQLSTATE
`23514` in `xray_collection_guard`, line 32. It produced `VALIDATION_FAILED` during
cleanup before the pinned read. The corrected fixture proves that actual
collection TTLs remain after database `CURRENT_TIMESTAMP` while no target
`XrayRetentionEvent` exists. It retains strict early rejection and rollback parity
for input bytes/digest, physical counters, collection members and bindings.
At most five normal 256-row source-maintenance invocations establish the derivative
event; the original pinned `ACCESS_DENIED` assertion remains required afterwards.

The original X-ray 128-invocation copy-drain prefix now independently proves
partial physical progress, unchanged protected input bytes/digest, pending input,
zero completed source events and a positive remaining payload count. A separate
continuation permits at most 128 more calls with the same 256-inspection and
256-removal limits and unchanged byte caps. Its exact final completion and all
canonical-erasure, retained-digest, event and exposure-bucket assertions remain.
This fixture bounds copy draining to 256 invocations, plus at most five separate
event invocations: at most 261 full-budget calls in these two phases. It provides
no general convergence or performance guarantee. The enrichment test separately
retains its 128-call partial prefix and 128-call continuation, with exact final
counts for all ten licensed source headers.

Failed and passing invocations remain separate source-bound observations:

| Evidence ID | Actual result | Pytest / runner seconds |
| --- | --- | --- |
| `retention-fixture-focused-green-01` | 18 passed, two failed; core source-report footer and X-ray guarded cleanup | 234.02 / 237.090 |
| `retention-fixture-remaining-01` | One passed, one failed; X-ray's original 128-call drain remained incomplete | 33.01 / 34.554 |
| `retention-fixture-xray-final-01` | One X-ray case passed after explicit bounded continuation | 18.36 / 19.707 |
| `retention-fixture-focused-green-02` | 19 passed, one failed; core source report had no marker after the small prefix | 238.90 / 241.973 |
| `retention-fixture-focused-green-03` | All 20 cases passed in one invocation | 237.39 / 240.344 |

The final 20-case invocation began at
`2026-11-13T23:44:44.869657+00:00`, exited 0 and retained unchanged source manifest
`2fbaab355989e8e5eb3f8a9b8aa70f27657d8fc7f3180e0ac8e81072de9a9c81`.
Its log SHA-256 is
`58ef29176b564083724102566d13bdb4b5786c2987d7b193d4ea4a112baaece0`.
At execution, Git HEAD still named `cd97b57` with six modified test files;
the passing receipt qualifies that complete working-source composition. It is
not clean-`cd97b57` validation and is not inferred by combining the preceding
19-case and one-case passes.

The final query-plan invocation retained twelve EXPLAIN files for report and
alert TTL candidate SELECTs, with two remaining inspections and `limit=1`.
Each table has 32,768 synthetic metadata rows, with 0, 32 or 8,192 eligible rows;
setup is explicitly warm. This observation does not qualify default-budget
maintenance, batch behavior, latency, a production SLO or index-shape guarantees.

Static peer review of the six exact file hashes found no blocking issue,
retaining 273 original assertions with 371 current assertions. Equivalent owner
UUID calls, strengthened report completion and target-scoped X-ray work selection
have explicit semantic dispositions. The report-core file retains all 94 original
assertion ASTs. This internal static review remains separate from executable
results and independent owner acceptance. An earlier typing check retained two
new-local-variable conflicts; only those locals were renamed. The final strict
mypy invocation passed all six files in 0.739 seconds on the same final working
composition. Current repository-wide static qualification remains pending.

A new clean implementation commit/archive remains pending. The previously
unreached migration, security, browser and build gates will be preflighted at that
clean source before complete attempt 10; none is claimed executed here. Complete
attempt 10 has not started. Final actual-image security scans, synthetic startup
and browser qualification, delivery/CI observations, cleanup and portable export
remain pending. Prepared helpers establish no executed result. All 30 Phase 3
rows and all 48 scenarios remain pending with zero accepted; independent owner
audit and production authorization remain separate.

## Unreached-gate preflight and PostgreSQL lock capacity

The first preflight at clean `730efac5b87d3123db0739d934e9618f719c8cd0` began at
`2026-11-13T23:58:46.887135+00:00` and exited 2 after 7.281 seconds with unchanged
source. Its migration stage had ten passes and two failures in 5.98 seconds;
security, browser and build targets were not reached. Both failures exhausted
PostgreSQL's default shared object-lock capacity during deep atomic downgrades.

Compose now sets `max_locks_per_transaction=256` at PostgreSQL startup. This
raises shared object-lock table capacity and its startup memory allocation; the
additional byte cost and peak memory were not measured. PostgreSQL documents
this as average object-lock capacity, rather than a per-transaction hard limit or
row-lock limit, and requires startup configuration.
See the [PostgreSQL 18 lock settings](https://www.postgresql.org/docs/18/runtime-config-locks.html).
DDL, atomic transaction boundaries, SQL integrity guards and test bodies are unchanged.

All 12 migration cases then passed in 15.90 pytest seconds (18.462 runner seconds),
starting at `2026-11-14T00:00:12.834162+00:00`, on unchanged working-source manifest
`bcc277be603f54110a0615a1b093b33f2cf47d75137f2bf1702f5e7f0be505eb` above `730efac`.
An executed settings probe confirms 256 from the command line with no pending
restart; connections remain 100, prepared transactions zero and shared buffers
128 MiB. This focused pass does not qualify the unreached stages or the whole
target. Preflight 02 and complete attempt 10 remain not started; all acceptance,
independent audit and production boundaries remain unchanged.

## Second preflight and trace-context dependency follow-up

The second preflight at clean `2756314c08de1c59b272a70cb6ba5693f3b21fc9` began at
`2026-11-14T00:04:12.787673+00:00` and failed after 196.766 seconds. It passed
12 migration cases in 15.11 seconds, 258 security cases in 39.15 seconds, seven
SAST rules on 973 files with zero findings, and the existing 16 approved-line /
21 negative secret-policy cases. A later pip-audit reported one finding:
`CVE-2026-126360` in OpenTelemetry API 1.45.1. Node audit, browser and build targets
were not reached. The [upstream advisory](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-mf5v-w3w3-f6cg)
was published on 5 November; the later observation is distinct from publication.

The initial 1.45.1 API/SDK and 0.66b1 semantic-conventions remediation remains
historical evidence. Current exact pins are 1.45.2 / 0.66b2. Only those three
external versions and observability workspace metadata changed among 99 locked
packages. Distribution hashes/sizes match PyPI metadata; offline lock checking
passes and the existing `.venv` inode 291333 is preserved.

Three benign public extractor cases preserve normal and 512-character future
trace-context acceptance and reject a 513-character value. Old 1.45.1 produced
two passes / one failure in 0.09 seconds. Corrected security/observability passed
279 cases in 39.15 seconds; PostgreSQL observability passed eight in 19.77 seconds.
A fresh-cache pip-audit 2.10.1 under Python 3.13.15 then checked 67 dependencies,
with zero findings/skips, in 4.941 runner seconds. All three corrected invocations
retained working-source manifest `42b292c37fad4158f690012b4adeccffb085b8abd2b0652a0e9148e2818c2a3d`.
No exploit, timing benchmark or regex-internal mock was executed. These passes do
not constitute clean-base or complete-target qualification. Preflight 03, full10
and final image/startup/browser/delivery qualification remain pending/not started.

## Owner-directed incremental browser recovery

The owner directed retention of completed scopes and reruns of failed cases only,
with previously unreached gates continued once. Complete attempt 10 is not run;
complete coverage remains pending under this instruction. Earlier passes retain
their actual source bindings rather than becoming a new monolithic pass.

Preflight 03 passed 12 migration cases, 261 security cases, SAST, Python/Node
production audits and 196 Demo browser cases. Its first API-backed aggregation
desktop case failed when the activity request returned `SOURCE_UNAVAILABLE`.
A closed-code-only focused diagnostic confirmed the rejection. The opt-in EUR
fixture retained an order header with no fill evidence; the production guard
correctly rejected it. The fixture now explicitly declares an empty fill collection
and delegates all other capabilities unchanged. Two focused tests preserve exact
collection parity and real rejection of the original unsupported record.

The next focused browser attempt reached logout and exposed a stale Sign out
location. The unchanged financial, coverage and access assertions now navigate
to the selected owned account's Settings page before logout. The final complete
desktop case passed in 18.1 Playwright seconds (18.603 runner seconds), retaining
working-source manifest `de96f9d7b6a64e873002ffad40a59648a9287627f41263f472134e281f31d193`.
The temporary diagnostic was removed. Only Next-generated development type imports
also differ from committed source; normal build qualification remains pending.
Tablet/mobile and the other API suites are continued without repeating Demo or
completed security tests. All 30 rows and 48 scenarios remain pending, zero are
accepted, and production authorization remains false.

## Incremental aggregation accessibility recovery

The continuation preserved the complete desktop pass and passed the tablet group.
Mobile failed the unchanged Axe assertion because aggregation scroll containers
were not keyboard focusable. Six existing table wrappers now have caption-based
region names and native focus stops. An additional check presses an arrow key and
requires actual horizontal scroll movement before framing each screenshot.

The next mobile invocation passed Axe and exposed an expanded source-details
region taller than the unobscured viewport. Aggregation now uses the same
viewport/toolbar/navigation height bound as the shared table style, with both
axes scrollable. No financial rendering, table content, Axe rule or focus-clearance
assertion was removed. The failed mobile group then passed in 18.3 Playwright
seconds (18.804 runner seconds) at unchanged working-source manifest
`4d2bc2919aca382c23e917c5baa3c04a6a53b9c59e494792c6e3121b15cb9be0`.

The normal build passed. Its only generated source change restored Next's
production type imports exactly to committed bytes; all other source inputs
remained unchanged. After the height correction, only the affected frontend was
rebuilt. Desktop/tablet observations remain bound to their earlier sources;
remaining groups continue once, without a new monolithic-pass claim. All Phase 3
acceptance and production-authorization states remain unchanged.

## Subsequent incremental browser corrections and terminal inventory

Historical and intelligence presentation helpers now use computed accessible
names for exposed tables and visible controls. Pagination still requires a
caption. The intelligence company case was an observed failure; eight adjacent
specifications received the same source-inspected correction before their first
execution. Business, financial, authorization, landmark, overflow, keyboard,
image-alt and secret-negative assertions remain. Intelligence desktop retains
its original quality-case pass and separate corrected company-case pass.

The PWA desktop failure showed the first authorized account unavailable. The
lightweight fixture had seeded only the other account. One canonical selector
addition uses the existing complete synthetic X-ray seed for PWA. Its focused
desktop case passed; tablet and mobile passed later. Privacy, offline/cache and
account-authorization assertions were not changed.

Scenario-report desktop then failed with `ACCESS_DENIED`: its synthetic source
parents had historical August physical creation times, exhausting the original
30-day report-copy cap. A context used only when reports and scenarios are both
enabled records actual physical creation before the first INSERT of 12 new
synthetic parents across five exact model classes. It checks the disposable
database, engine, new-object membership, owner/provider/license identities and
original observation clock, and removes listeners in `finally`. Existing rows,
FX/shared seed data, production guards, financial dates, first-observed times,
original expiry and digests are unchanged. The focused desktop pass used source
`a98ab78bf3c91d49acf7c1d7fa02f8ffe447e776e76214acb0545e6a9878bd45`.
The subsequent `25d70785…` source changes only creation-range metadata output
from stdout to stderr. That desktop pass did not execute the logging delta and
was not rerun; later viewport observations retain their own sources.

Workspace desktop retained three passes and two failures from its original
five-case invocation. The first focused pair passed the delayed-account case but
failed the Back case at an unobserved optimistic-account-URL precondition. Only
Back then ran again, with committed Overview URL/heading settlement and exact
account-marker checks. Safe native browser history showed Holdings at index 3,
Overview at index 4 and the held second-account response still at index 4, with
no second-account history entry. Back restored the original Holdings expectation
before and after releasing that response. This qualifies the tested setup and
observed outcome; it does not establish a production defect or the cause of the
earlier failure. Only the test and its safe diagnostics changed.

| Actual invocation | Outcome and runner duration |
| --- | --- |
| `api-browser-resume-04` | Failed, 999.841 s; preceding groups retained; PWA desktop account unavailable. |
| `pwa-desktop-recovery-01` | One focused case passed, 16.886 s; dirty fixture-selector source retained. |
| `api-browser-resume-05` | Failed, 526.247 s; 17 full groups / 29 cases passed before scenario-report desktop. |
| `scenario-report-desktop-recovery-01` | One focused case passed, 139.240 s; two dirty fixture files and logging distinction retained. |
| `api-browser-resume-06` | Failed, 680.203 s; workspace desktop three passes / two failures retained. |
| `workspace-desktop-recovery-01` | One pass / one failure, 33.104 s; delayed-account pass retained at its actual source. |
| `workspace-back-desktop-diagnostic-01` | Back-only case passed, 26.625 s; original Holdings expectation preserved. |
| `api-browser-resume-07` | Passed, 159.636 s at frozen source; five previously unrun groups / 19 cases. |
| `api-inventory-assembly-03` | Metadata-only assembly passed, 1.876 s; 132/132 retained cases, 67 full-group observations and two partitions, zero missing or integrity issues. |

The metadata inventory retains 82 reports with 133 passing and 13 failing case
observations. These observation totals include history and are not a new test
count. It reports process-descriptor access blind spots explicitly; earlier
metadata-only assembly failures remain retained. Full SAST used seven rules on
973 targets with zero findings. The later changed-target SAST checks below retain
their own scope. Metadata assembly does not establish CI or acceptance outcomes.

## Artifact qualification, ordinary startup and cleanup

The `881f283` artifact record binds nine built image IDs and nine configured
HIGH/CRITICAL vulnerability-with-fix and secret scans, all with zero findings.
The existing `ignore-unfixed` policy remains. Runtime probes verify nonroot users,
versions, public CA material, retained dpkg inventory and removed package managers.
The ordinary `make run-local` build/start then produced nine distinct new IDs;
every new ID received its own probes, package-manager check and scan. The final
web packaging correction replaced only the web row; the other eight current
image rows remain qualified by their actual earlier receipts. Image license and
misconfiguration scanners were not configured in this image matrix.

Changed-target SAST ran seven rules on five supported files with zero findings;
its six changed paths include one unsupported CSS path. The input comparison
retains 1,026 unchanged inputs out of the declared 1,032-path SAST scope. The
source `881f283` exact export passed its configured vulnerability, secret,
misconfiguration and license scans; its full-history Gitleaks scan reported zero
findings. The ignore file contains 57 exact unique fingerprints: 19 pre-existing
and 38 additions individually classified in this assignment. No exception was
removed and the file hash remains unchanged during this closure.

Python 3.13.15 / pip-audit 2.10.1 audited all 67 active Linux runtime requirements
from 69 declared requirements with zero missing, unexpected, skipped or vulnerable
dependencies. The two inactive markers target Emscripten and Windows. The fresh
output-bound cache contains 67 responses. The production Node audit covers 144
dependencies with zero advisories. The separate ignored installed-workspace scan
remains failed on three third-party license classifications; public binary
redistribution remains unauthorized. A failed host-tool metadata collection and
its corrected collection are retained without repeating the dependency audits.

Ordinary nine-service `make run-local` startup passed in 44.910 runner seconds at
`881f283`. The first frontdoor smoke failed with five service-worker/public-asset
404 console errors. The standalone web image omitted the existing public tree.
Commit `153854f` adds one COPY instruction; six public assets match their source
bytes inside the image and over HTTP 200. Only the affected web image was rebuilt
(9.405 runner seconds), probed and scanned. The failed frontdoor flow alone was
retried and passed in 1.974 runner seconds at executed source `2649f2a2…`, with no
page errors or console errors/warnings. Its actual HEAD was `881f283` plus the
one dirty Dockerfile line; the complete input dictionary matches commit `153854f`.
No current-source 132-case rerun is inferred.

After that correction, seven runtime services were healthy and migration/seed
one-shots had exited successfully. The synthetic flow covers local sign-in,
authorized account selection, Overview/Holdings at desktop/mobile widths,
Settings and logout. Numeric rendering checks do not establish independent
financial-value parity. The two genuine point-in-time captures retain partial,
stale and unavailable data warnings; desktop is 1440×900 and mobile is a
360×1108 full-page capture from a 360×800 viewport. Source/destination SHA-256
and size are verified in the evidence index.

Task-only stack removal passed in 3.943 runner seconds. The after-cleanup
inspection found no task containers, task network or disposable task volume.
Both original volumes, the existing `.venv` inode 291333, dependencies, tools,
evidence and all nine current qualified images were preserved. The inactive
Next development output removed 549 files / 371,911,400 bytes after consumer
checks. Shared or unproven builder cache was retained; no global prune ran.

The later external delivery record is authoritative for final documentation
source equivalence and post-commit source/history scans, push/CI observations and
portable evidence verification. Those future observations are not represented
as completed by this document or by earlier implementation receipts.

## Reproducible synthetic validation

Use the pinned Python, uv, Node and pnpm versions in the repository version files
and manifests. Bootstrap from the repository itself; no broker credentials,
private archive or historical operator environment is required:

```bash
make bootstrap
make docs-check lint-python architecture-check generated-check
uv run pytest tests/contract/test_historical_contract.py tests/contract/test_scenario_contract.py
```

For database-backed tests, use one task-owned Compose project and a disposable
synthetic database. Set a local-only password consistently for Compose and the
test connection, and bind published services to loopback. Preserve unrelated
volumes and never use global pruning. The repository's current gates are exposed
through `make validate`; successful invocation must be recorded before claiming
that gate passed.

Initial focused SQL checks used the exact pinned PostgreSQL 18.6 upstream image.
Subsequent integration and fixture follow-ups use the built hardened task image
with the same disposable task volume and per-test databases. Image builds and
vulnerability scans retain their separate receipts. Both pre-existing local
database volumes are preserved.

## Evidence and acceptance boundary

Actual command receipts retain the command, UTC start, duration, exit code,
source manifest, HEAD/tree, log hash and source-change indicator. Failed attempts
are retained separately from retries. The baseline environment is Python
3.13.15, uv 0.12.7, Node 24.20.0 and pnpm 10.34.5 on WSL2, with Docker Desktop
29.9.3 and Compose 5.7.0. The initially installed uv 0.12.9 is retained; an
isolated pinned uv invocation supplies 0.12.7 without replacing the existing
project environment.

All 30 [acceptance rows](PHASE_3_ACCEPTANCE_MATRIX.md) and all 48
[scenarios](PHASE_3_SCENARIO_EVIDENCE.md) remain pending. Implemented, locally
validated, independently reviewed, accepted and production-authorized states
remain distinct. The final candidate and independent audit remain pending.

Provider credentials, licensed account access, production identity/secret-manager
selection, hosted MCP/ChatGPT registration and production restore/signing remain
separate external prerequisites. GitHub Actions retains its owner-deferred policy;
historical retrieved runs do not constitute current CI validation.
