# Phase 3 Implementation Report

**Current:** Bounded baseline stabilization and existing P3-08 aggregation recovery;
see the [13 November record](PHASE_3_STABILIZATION_20261113.md). Earlier sections
retain their original component scope and chronology.
**Target:** 1.0.0; independent review pending; production not authorized

Start main d2ebdaf96d1b61aacea5c6492824946540f88803. Governance delivery
30fe2ede666bff35e3e95173abcf34558a729cc1 records owner acceptance for progression
without modifying historical artifact claims. Immutable governance gate passed:
463 targeted tests, strict mypy 605 files, Ruff/repository/workspace/broker/architecture/
secret checks and affected Prettier. Scope is governance, not Phase3 runtime completion.

Design inventory: ten packages,30 local acceptance rows,48 mandatory scenarios.
No package/row/scenario is locally complete at this boundary. Implementation, scenario
execution, full candidate validation and independent acceptance remain separate.
Governance logs/JUnit/commands/source identities reside in the external phase3-20260914
evidence directory; add package evidence only after actual executions.

GitHub Actions deferred_by_owner/unverified. No production/public release, Live,
paid-provider access or public ChatGPT registration has been performed.

## P3-01 numerical foundation

Implemented strict definition/series contracts, isolated Decimal96 arithmetic, PSD/
correlation/shrinkage, modeled Euler contributions, historical/lognormal tails and
complete-case observed/benchmark/rolling estimates. Focused numerical/contract tests
passed (54 tests). Independent references use rational covariance and a different
200-digit positive-series normal integral with Machin pi. This is partial package
implementation at d6bb100: canonical history capture, durable persistence/jobs and
interface delivery remained pending at that numerical foundation boundary. No acceptance row/scenario or package is marked complete.


## P3-01 canonical history and complete calculation object

Added a retained-history builder using canonical TWR at actual captured reporting
session closes, explicit complete month ends, canonical flow anchors, total-return
benchmark/asset sources, FX selections, source cutoff and original drawdown. Raw or
split-adjusted asset prices remain explicitly incompatible with a total-return risk
series; the existing accounting engine still handles supported portfolio actions.
The builder preserves canonical missing reasons and applies a combined preflight
cell bound before valuation. No caller return array enters a service contract.

The immutable calculation now carries observed statistics, the original and explicit
regularized covariance, correlation, historical/lognormal tails, and a distinct
current-weight model. It binds scope/cutoff/snapshot/X-ray digest and the separate
current valuation date. Incomplete selected material exposure, including cash without
an explicit return series, cannot publish full modeled risk. Exact current value
ratios are used before Q18 publication; weight and Euler display residuals are
reported without allocating them. Concentration reuses X-ray issuer partitions and
its exact coefficient ratio for effective holdings, preserving unknown mass/quality.
A fixed-schema private codec verifies the canonical result digest before replay.

Focused execution passed 85 tests across numerical, statistical, history and complete
result modules. Independent references include Fraction covariance, Decimal160 risk,
known direct/indirect issuer partitions and equal-third rounding. A fixture initially
had mismatched X-ray dependency account IDs; correcting its scope made the integrated
case pass. No production boundary was relaxed. Original attempt logs are retained.
These are working-source component checks; durable normalized storage/jobs, current
read/execute/export authorization, REST/generated clients/web/MCP/report integration
and full package acceptance remain pending. The acceptance counts stay at zero.


## P3-01 normalized storage and bounded worker

Migration 0017 extends the existing application command identities and current
principal grants, adds 17 normalized premium/risk tables, and extends the existing
immutable collection snapshots for risk definitions, versions and run metadata.
Calendar references retain the canonical source key/version; persistence resolves
that pair to an owned immutable calendar UUID. Existing Phase 2 financial methods,
report commands and source identities keep their contracts.

Risk definitions have immutable predecessors, revision checks, semantic idempotency,
transactional audit and current-grant checks before replay/cursors. Risk admission
pins owned history, portfolio, optional X-ray and ordered asset mappings. Current
source display/store rights are checked before private decode, and the shortest
applicable source lifetime bounds the run. The same valuation-cell preflight runs
at admission and calculation; combined private input bytes are bounded to 32 MiB.

Runs reserve capacity in PostgreSQL: at most two active jobs per owner, one running
premium job globally, 512 definition versions and 256 MiB retained/reserved payload.
Publication verifies the canonical digest and every fixed normalized projection.
The canonical historical drawdown can retain its partial-value reason. Normalized
storage size is included when releasing the conservative result reservation.

The fixed risk outbox is relayed by the existing dispatcher. Messages carry only
opaque identities and the input digest. Publication claims, consumer leases,
heartbeats, absolute per-attempt deadlines, retry bounds and immutable attempts
fence stale or cancelled workers. Current initiating identity/grants and source
rights are checked again at load/publication. The existing Celery worker starts
one isolated calculation subprocess with a 240-second attempt deadline, 512 MiB
address-space limit, minimal environment, fixed codecs and Linux parent-death kill.
Cancellation/deadline tests verify that the child is killed/reaped without retaining
scratch files. No additional Compose service is introduced.

Working-source component checks passed 44 migration/schema/definition/run/job tests
and 8 process/message tests. They include an actual child publishing through the
fenced PostgreSQL store. Original failed attempts remain retained: a calendar key
was initially mistaken for its storage UUID, and a dispatcher claim initially
failed to clear its dispatcher identity. Both contracts were preserved while fixing
the implementation. These counts are not final candidate validation.

A populated 0016-to-0017 upgrade passed: all 212 legacy tables retained identical
row counts and hashes of every pre-upgrade column, and canonical historical replay
was unchanged after introducing the 17 new tables. A separate real source-rights
test confirmed that current store revocation and a tightened retention limit deny
risk access before private decode, including idempotent replay and worker loading.
This migration proof is not a backup/restore exercise.

REST/generated clients, web/MCP/report integration, shared physical source-retention
hooks, broader adversarial/performance evidence and full P3-01 acceptance remain
pending. The other Phase 3 packages remain pending. No acceptance row/scenario or
package is marked complete, and no public premium MCP tool is registered yet.


## P3-01 REST and generated client

The storage/worker milestone was delivered as
0e0cc02c7dca209707eee59f9d5c0883e42e91df, tree
4667e42603bcac8a5ffeb2678e52537fdf9293d4. Its unchanged working-source
checks passed 2,888 unit/property/contract tests, 47 PostgreSQL tests and 226 security
tests, with generated-contract freshness, Ruff, strict mypy and repository boundary
checks. The gate receipts bind exact pre-commit content; they are not an immutable
post-commit candidate rerun. The exact scope-registry assertion was extended to the
ten frozen premium scopes after its original Phase 2 inventory rejected the change.

Eleven risk operations add eight paths, for 95 paths/106 operations at this milestone.
All 87 old paths and existing component schemas compare unchanged. Public risk views
retain the definition assumptions, canonical historical context and source omissions;
matrix views carry the same immutable financial identity. Financial values use the
existing exact string grammar; available and unavailable metrics are separate closed
wire shapes. Lists carry bounded owned operational metadata without financial arrays.

Authentication and token scopes precede request parsing; persistence checks current
identity, account and grants before cursor/replay/conditional responses. Commands
require semantic idempotency and browser sessions require current CSRF/trusted origin.
Version creation requires the owned aggregate revision. Bodies are bounded to64KiB,
responses to2MiB, and service/network failures use fixed safe categories. The local
synthetic session and trusted synthetic grant seed explicitly add risk:write; no
production token authentication grants new database permissions.

The generated client exposes exactly the eleven fixed methods, reuses historical
and source schemas, preserves decimal strings and rejects extra fields/invalid IDs
before transport. Its private requests disable caching and redirects. The existing
workspace analytics dependency is made explicit at the API composition root; no
third-party dependency or runtime version changes.

Focused checks include50 risk schema/route tests, two contract tests, five generated
client tests and a real signed-JWT/PostgreSQL/subprocess HTTP lifecycle. That lifecycle
checks exact issuer/audience, malformed claims, foreign-owner denial, current-grant
revocation before304/replay and canonical API/matrix parity after atomic publication.
The full Phase 3 candidate, web/MCP/report consumers and physical retention remain
pending. Acceptance and scenario completion counts remain zero.


## P3-01 physical retention implementation

REST/client delivery is 3b930a92c067ebe5a6e76a7f132fb61ee9b6a4a4, tree
04f1e30ebab7b203b33e994f1bf461e15171bcd0. The unchanged pre-commit source passed
3,166 Python unit/property/contract/security tests, 11 PostgreSQL tests and 544 web
unit tests, plus formatting, lint, typing and boundary/contract gates. Original
risk-api-working-02 receipts and the earlier failed inventory assertion are retained
under phase3-20260914. This is component evidence, not final candidate certification.

Migration 0018 adds immutable license lineage and preserves existing financial
payloads. Risk maintenance now participates in the common source purge allowance,
including current license revocation and shortened copy retention. Pending work
fences active jobs before physical deletion, removes normalized children before the
canonical result, and releases retained/reserved byte capacity only upon completion.
Future licenses are excluded. Metadata lists disclose expired retention without
loading financial arrays; replay/detail authorization continues to precede decode.

Seven PostgreSQL regression tests passed in 177.25 seconds for physical expiry,
bounded resumption, active-worker fencing, source-cleanup ordering, future policy,
busy owners and populated 0017 upgrade. The original passing log is identified in
retention-component.json in that evidence directory. Broader regression verification is in progress. Web,
MCP, reports, full P3-01 acceptance and all other Phase 3 packages remain pending.

The small-budget regression exposed a pre-existing shared purge helper defect:
metadata selection could consume all remaining row inspections and leave no room
for clearing, so repeated small passes never progressed. The helper now reserves
space for both inspections without raising any row/byte bound or skipping a pending
prefix. Earlier failed attempts and their corrections remain separately recorded.

## P3-01 authenticated web workspace

Physical retention was delivered as e94339ed5c60d9ddf3090d8e813e211f66f6745c,
tree ba244400f8b4fee37183b2c12576d0b214ed8bbf. The unchanged pre-commit source
passed3,167 Python unit/property/contract/security tests and70 real PostgreSQL
migration/retention/service tests, plus Ruff, strict typing, boundary and contract
gates. Original receipts remain in phase3-20260914; this is component validation.

The risk route extends the existing authenticated account shell. Owners can create
immutable assumptions, inspect version history, pin an owned snapshot and historical
window, optionally select a benchmark/X-ray, select bounded sourced total-return
assets, submit a durable analysis and inspect or cancel its job. Existing worker and
PostgreSQL services execute the analysis. The browser fixture uses a bounded in-memory
message transport into the real dispatcher, leases and isolated calculation child;
it does not emulate the financial API or require another container.

Canonical results display observed estimates separately from current-weight modeling,
rolling volatility with gaps and paginated table alternatives, tail conventions,
matrices, component reconciliation, concentration availability and retained source
identity. Decimal strings remain authoritative; browser conversions occur only in
existing chart geometry and presentation. An absent X-ray does not claim an HHI lower
bound was calculated. Historical chart consumers retain the original default caption.

URL selectors reject unknown/duplicate fields, invalid UUIDs, dates and signed-cursor
syntax. Account changes retain only valid dates and mask the previous account view.
Each server action reauthenticates the session and checks origin/CSRF, then dispatches
one of four closed generated operations. Forms preserve command identity on retry,
reset it when inputs change, discard late responses after navigation and disclose
write-scope restrictions. Status polling is bounded to48 automatic refreshes.

Thirty new unit regressions passed. The real signed local-session browser journey
passed at1440,768 and360 pixels (web-browser-05,125.639 seconds): immutable version
creation, actual worker completion, exact API volatility parity, matrix selection,
missing-data labeling, keyboard focus, account switching/back navigation, foreign
account/result denial and malformed filters. All three journeys had no browser
warnings/errors and no document horizontal overflow in input and result views.
Fifteen synthetic screenshots are retained; desktop and mobile captures were visually
inspected. Browser plugin is unavailable; existing pinned Playwright was used.
These checks do not claim the final Phase3 accessibility/performance budgets.

Original failed browser attempts remain alongside their source bindings:01 rejected
a fixture cursor key below256bits;02 expected the wrong existing page title and also
recorded Next's generated dev-type imports;03 caught duplicate sibling React keys.
The fixture key, expectation and panel identities were corrected.04 passed all three
viewports before the concentration wording correction and expanded form captures.
The source-bound web-working-01 gate passed in341.872 seconds:3,167 Python tests,
574 web tests, three real API/worker browser journeys, Ruff, strict Python/TypeScript,
repository/architecture/secrets/broker/generated-contract checks and production build.
After two presentation-only chart caption/date changes, web-final-01 passed in145.194
seconds: all574 web tests, all three browser viewports, lint/typecheck and production
build. Both receipts record unchanged source during execution. Fifteen final captures
remain with the original logs; the compact mobile chart was visually inspected.
These are unchanged working-tree component receipts, not a final immutable release run.
Full P3-01 acceptance, MCP/report integration, all other
packages and immutable final-candidate validation remain pending; completion counts
are unchanged. GitHub Actions remains deferred_by_owner and unverified.


## P3-01 MCP tools and risk resource

The web workspace was delivered at e27f8b408c6613ea8f1b6762877840a328e70b42,
tree2e0e14b3d6ec1e894932ba732567ecac7a6a50dc. Its source-bound component receipts
and reviewed patch are retained in web-delivery.json. Inactive Next development
outputs of233,442,692 logical bytes were removed after checking consumers; the
production build, dependencies and evidence were preserved.

The MCP registry now appends create_risk_run, get_risk_summary and get_risk_matrix
to the original25 names, with exactly6 resources. The gateway uses the canonical
PostgreSQL risk service, existing current grants/licenses and the unchanged pinned
SDK. Scope, strict nested input, output schema, source/owner identity,64KiB input
and2MiB complete output bounds are enforced. Malformed server result objects fail
as INTERNAL_ERROR, not as user validation errors. Audit logs contain only fixed
operation/outcome names and hashed account/correlation references. The only lock
change adds the existing workspace analytics package to MCP composition.

The risk resource uses the stable MCP Apps2026-01-26 postMessage lifecycle with
host-capability negotiation. Refresh calls only the two frozen risk reads, with one
pending request, a15-second timeout and account/run generation checks. Standard
structuredContent and compatibility callTool/toolOutput are supported. Canonical
Decimal strings, unavailable reasons, source/omission counts, regularization,
contribution residuals and risk conventions are rendered through textContent;
no browser financial recomputation, private persisted state or network requests.
Tables have captions, focusable scroll regions, keyboard controls and reduced motion.
The complete UTF-8 envelope is bounded before rendering.

Focused evidence:38 new unit cases passed, plus the original registry contract
checks. risk-mcp-widget-02 passed7 iframe host tests in6.5 seconds, including
1440/768/360-pixel presentation, exact values, keyboard/reduced motion, closed reads,
late foreign-account replies, malformed inputs, cancellation, timeout, teardown and
compatibility fallback. Three real PostgreSQL/signed SDK tests passed in81.16 seconds
under risk-mcp-postgres-03 (82.859-second harness): concurrent semantic replay,
actual isolated worker, HTTP/MCP/canonical parity, revoked current scopes, strict
issuer/audience/expiry claims, denied source rights before private decode, and a
real X-ray capture pinned through the worker and returned digest. The latter
registers the required policy; it does not invent missing issuer/source coverage.

Original failed attempts remain retained. The first widget attempt found a fixture
using Locator.evaluate's element argument as its supplied payload. The first PG
attempt found lazy SDK lifespan initialization and missing X-ray policy setup;
the second found that the SDK validates OAuth expiry against real wall time.
Authentication tests now mint current ephemeral tokens with the real authentication
clock, while source/calculation time stays fixed. Rights-revocation cases use
separate disposable databases in the same PostgreSQL container. No authentication
check or financial source policy was weakened. The broader final component gate
and UTF-8/absent-result browser follow-up are recorded separately before delivery.
Risk reports, full P3-01 acceptance, P3-02..P3-10 and final immutable validation remain
pending; no package/acceptance/scenario completion count is advanced. CI remains
deferred_by_owner/unverified and independent review is pending.


The 2026-09-15 component follow-up retained the initial broad-gate failure:
3,204 Python cases passed and one stale assertion still expected the original25th
tool to be last. The corrected contract verifies that original position plus all
three appended names. A read-only internal review then found and corrected two
edge cases: complete invalid/uppercase input notifications could lose widget
account/run guards, and MCP accepts128-character correlation IDs while durable
audit storage permits120. The widget now canonicalizes valid UUIDs, blocks invalid
or incomplete pins and verifies nullable X-ray pins. Longer MCP correlation IDs
use a full SHA-256 audit reference; response metadata retains the original ID.
HTTP keeps its existing120-character acceptance rule. No migration or financial
identity changed. New tests cover these boundaries and current replay semantics.

risk-mcp-final-local-04 retained unchanged source throughout: all3,208 Python
unit/property/contract/security cases passed in193.61 seconds, all19 iframe widget
cases passed in24.3 seconds (including9 risk cases), and the MCP sdist/wheel built.
Ruff, strict typing (665 files), generated-contract freshness, web lint/typecheck,
repository/workspace/architecture/secrets/broker-boundary checks passed. The harness
exit was2 solely because git diff --check found a trailing documentation blank
line; that line was removed without changing executable bytes. The original
failed receipt is preserved, not relabelled. The final360-pixel capture was visually
inspected; three widths have actual captures and no-overflow/keyboard checks.

The MCP final PostgreSQL gate05 then passed51 real PostgreSQL cases in114.54 seconds:
three risk SDK/worker cases,46 preserved signed-JWT transport cases and two API/MCP
parity cases. The risk command case also checks the actual persisted bounded audit
reference and unchanged semantic replay under a different accepted correlation ID.
The earlier resumed PG attempt failed before execution because Docker was stopped.
Desktop recovery moved only obsolete runtime sockets and restored process-local
Windows executable lookup. The same sole PostgreSQL container became healthy,
with1 CPU/1 GiB limits; no volumes/images/configuration were reset or replaced.
Recovery originals and receipts live in the portable Windows artifacts directory.

The exact pre-documentation file hash/mode manifest and gate receipts are retained
outside the checkout. Only this report and the widget documentation whitespace
changed after the broad local gate; the PostgreSQL gate uses the final executable
bytes. These are component pre-commit checks, not an immutable final-candidate run.
Risk report delivery and all Phase3 package acceptance remain pending.

## P3-01 versioned premium risk reports

The MCP milestone was delivered at4d747f6c1281a2914c84f18a02554c18f612e249,
tree68a3714f1f464555ede984225f0178d7fa3762a4. Its unchanged working-source
receipts and reviewed patch remain in risk-mcp-delivery.json. ADR-0024 introduces
report_sections_v2 and document/context schema2.0.0 for premium reports while
retaining report_template_v1, its renderer versions and all25 original MCP tool
descriptors. Six fixed APIv2 routes use a separate generated client; V1/V2 SQL
collections, direct IDs and idempotency namespaces are isolated before decoding.

Migration0019 adds normalized report contract versions and one immutable owned
premium-run dependency. Admission binds the selected succeeded risk run to its
exact portfolio snapshot, historical window, reporting currency, cutoff and input/
result digests. Seventeen fixed analytical/proof tables retain canonical values,
unavailable reasons, assumptions, source memberships, complete return intervals,
FX conversions and selected X-ray terminal paths. No calculation is repeated.
Current and pinned STORE/DISPLAY/REPORT rights and transitive activity/target
scopes are checked before private reads, including replay, workers and downloads.
Dependent report artifacts and grants are cleared before physical premium-source
completion, using the existing bounded purge budget and owner lock ordering.

Initial component checks passed292 focused Python cases and strict mypy over692
files. Three PostgreSQL retention tests passed in77.00 seconds; three later privacy
tests passed in128.85 seconds, using payload SELECT tripwires for revoked rights,
foreign/mismatched pins and V1 access to real V2 identifiers. The real isolated
report worker produced all four formats for complete31-day history in54.68 seconds;
downloads checked artifact/table hashes and exact risk-value parity. These are
development checks, not final source-bound candidate acceptance.

The first complete annual fixture had31,664 proof rows; its PDF correctly failed
when it required page1,001. The existing1,000-page,10MiB-per-artifact and25MiB-total
renderer ceilings remain unchanged. Document/manifest/license/row admission bounds
also remain unchanged. The complete monthly case fits; proof is never truncated to
make a report succeed. Original failed attempts and the direct-renderer diagnostic
are retained separately; that diagnostic does not claim process isolation evidence.
An internal review also identified a source deadline crossed between authorization
and the final source traversal. The source denial now preserves the safe report
error contract; its regression passed in the focused and full Python gates.

The premium web route selects an owned retained risk run and derives its immutable
pins server-side, then uses the shared bounded status, manifest and private download
components. Final component verification passed as detailed below. No package,
acceptance row or mandatory scenario is marked complete;
P3-02 through P3-10 and final immutable validation remain required. CI stays
deferred_by_owner and unverified.


Final report component gates used the unchanged working source based on
4d747f6c1281a2914c84f18a02554c18f612e249. The local gate04 passed in239.829 seconds:
3,371 Python unit/property/contract/security tests in194.21 seconds,614 web tests,
strict mypy695 files, formatting/lint/types, repository/workspace/architecture/
GET-boundary/secret/webhook/generated-contract checks, production Next build and
all12 Python distributions. PostgreSQL gate01 completed in1557.32 seconds with
144 passed and one fixture failure. The old report-creation authorization fixture
used generic dataclass serialization, leaking a new internal optional risk field
into its strictly unchanged V1 request schema. Switching that fixture to the canonical
selection encoder restored its original valid request; the focused rerun passed.
All145 distinct PostgreSQL cases therefore have observed passing executions across
these two attempts, covering clean/upgrade migrations, all four premium report formats with and without
selected X-ray, authorization before payload reads, retention and legacy reports,
API/MCP signed-JWT transport and canonical parity. These receipts remain component
checks, not final immutable Phase3 acceptance or measured performance/SLO evidence.

The final real API/isolated-worker browser cases passed at1440,768 and360 pixels.
They exercise report creation, all four authenticated downloads with hash checks,
account navigation, collection isolation, native keyboard visibility, overflow and
browser errors. Six selection/completed screenshots were inspected. Their local02
receipt retains its overall failure from five stale Python contract expectations;
those exact inventory/error expectations were corrected before the passing local04
run. Earlier failed attempts are preserved. No numerical or browser implementation
changed after those final captures. The reviewed OpenAPI comparison has101 paths/
112 operations and367 schemas: all95 old paths and352 old schemas remain unchanged.
All25 original MCP descriptor fingerprints pass; total MCP remains28 tools/6 resources.
Migration head is20260915_0019. Contributor reviews found no remaining actionable
findings in their scope; they are not independent acceptance.

Receipts, logs, JUnit, screenshots and reviewed source bindings reside in the external
phase3-20260914 evidence directory. premium-report-final-local-04.json and
premium-report-final-postgres-01.json bind the same working source. The latter
remains a failed overall attempt. premium-report-authorization-fixture-02.json
records the corrected single-case rerun. The pre-fix file manifest and
premium-report-executable-equivalence.json prove the only executable change was
that integration-test serializer; application code, all other tests and subsequent
non-documentation content/type/mode remain identical through documentation delivery. No post-commit immutable
rerun or full make validate is claimed at this component boundary.

Scoped housekeeping removed25 obsolete project Python build-cache records (about
5.774GB), eight web build-cache records (about1.533GB), and12 inactive generated
cache directories (309,301,248 allocated bytes). Exact IDs, fresh ownership/reclaimable
checks and removals are recorded externally. One PostgreSQL container is reused;
both the task and unrelated database volumes remain intact. Runtime cleanup is still
required after all dependent Phase3 verification. CI remains owner-deferred/unverified.

## P3-02 and P3-03 numerical foundations

ADR-0025 now specifies original total-return source membership and dated holdings
for historical replay; ADR-0027 fixes canonical projection paths and the monthly
calendar representation. The earlier scenario design was delivered at 3819134; ADR-0027 records the
accepted projection and calendar policy for this foundation.
Neither decision accepts a completed package.

Scenario execution retains the complete original X-ray input/result, exact terminal
partition, sensitivity memberships and optional historical input in bounded codecs.
No fund wrapper is counted alongside its constituents. Economic currency requires
selected evidence; explicit cash never becomes a security sensitivity subject.
Exclusions and price precedence preserve unknown applicability, and missing positive
shocked mass denies complete money. Zero-effect exceptions require an unchanged
outcome under every admissible treatment. Coefficients, dates, source aliases, units,
FX and known negative multipliers are validated before calculation. Derived source
confidence propagates conservatively. Reporting-currency FX cannot receive a nonzero
shock. Channel amounts, compound interactions, original-value partitions and rounding
residuals remain separate. Saved comparisons retain incompatible sides without deltas.

Replay resolves only the original captured total-return series membership and sourced
FX at the fixed historical engine boundaries. Missing or ambiguous mappings remain
unavailable; reporting-return series cannot be converted twice. Current and historical
holdings retain actual evidence and knowledge dates. Point-in-time mode rejects later
known holdings. Explicit cash uses a fixed principal and sourced currency movement;
its assumption is disclosed. There is no current lookup or invented FX identity.

Projection paths use the frozen SHA-256 counter/polar sampler with Decimal96 evolution,
canonical asset axes, absolute path identities, three bounded sensitivity variants,
Q18 checkpoints and a separate ever-unpaid flag. Deterministic flows, optional fee/tax,
inflation and rebalance timing are explicit. Saved paths drive nearest-rank percentiles,
enclosing histograms and Wilson intervals. Complete path/chunk inventories are required;
no checkpoint prefix becomes a final result. Strict decoding rejects material residuals,
wrong initial allocation or schedule totals, inconsistent inflation, and summaries or
probabilities contradicting retained paths. This validates retained relationships,
not a cryptographic proof that every return came from the declared random stream.

Calendar capture keeps the observed snapshot's actual UTC timestamp or an explicit
modeled anchor. Independently clamped calendar anniversaries preserve the original day;
flows must lie on supported month-start boundaries and immutable goals must agree with
the exact terminal date and complete schedule. Capture identity includes original dates
and source pins separately from numerical input identity. It does not grant ownership
or source rights; those remain the forthcoming transactional service's responsibility.

The unchanged working-source foundation gate passed 3,520 Python unit/property/contract/
security tests in 198.39 seconds, strict typing, format/lint, closed broker/architecture/
secret checks and all 12 Python package builds. It preceded the final calculator and
integrity changes. The subsequent scenario/projection integrity gate passed 163 focused
cases in 2.46 seconds; the scenario retained-money gate passed 99 cases in 3.46 seconds.
These populations overlap and are not added into a fabricated test total. Receipts
`scenario-projection-foundation-local-01`, `scenario-calculator-projection-integrity-01`
and `scenario-retained-integrity-01` bind their actual working-tree content externally
under `phase3-20260914`. Earlier fixture/type/format failures are retained. Independent
contributor review found the corrected projection integrity gaps; it does not establish
independent package acceptance. The final component delivery receipt records subsequent
confidence and static corrections without relabeling these earlier executions.
The subsequent confidence gate passed 58 cases in 2.72 seconds and complete replay
orchestration passed 23 in 1.62 seconds. The final focused scenario integrity gate
passed 128 in 5.18 seconds: independently rounded channel/interaction envelopes,
known partial effects, absent original money, negative multipliers and conservative
quality are checked on retained records. Large-value and negative-thirds rational
references prevent false rejection from multiplying rounded published ratios.
These additional populations also overlap and do not represent package acceptance.

The unchanged-source gate `scenario-projection-foundation-local-03` passed
3,625 Python tests in 204.58 seconds, strict mypy across 737 source files, Ruff,
repository/generated-contract/architecture/broker/secret checks, formatting and
all 12 Python package builds. Total gate duration was 230.407 seconds. Attempt
`scenario-projection-foundation-local-02` stopped on one formatting check before
tests or builds; its failed receipt remains intact. Subsequent independent contributor
review found three retained-identity gaps: definition content versus its source pin,
resolved sensitivity coefficients versus Q18 effects, and funding failure without a
positive scheduled withdrawal. All three are corrected with focused regressions;
the combined retained-integrity files passed 68 cases in 2.10 seconds. The final full
component gate `scenario-projection-foundation-local-04` then passed 3,638 Python
tests in 204.14 seconds, all static/contract checks and 12 package builds. Its total
duration was 230.184 seconds, with unchanged source content, type and mode recorded
in a complete file manifest. Final documentation is checked separately; the delivery
receipt binds executable files to this passing gate. This is foundation verification,
not completion of either vertical package.

Scenario schema/runtime work remains external staging until its private capture,
retention, fenced worker and real PostgreSQL checks are integrated. No migration 0020
or new public route/tool is claimed at this foundation boundary. Current inventory
remains 0019,231 tables,101 REST paths/112 operations,28 MCP tools/six resources and
exactly ten sealed broker GETs. P3-02/P3-03/P3-05 are in progress; all 30 acceptance rows,
48 scenarios and ten package completions remain pending. CI is owner-deferred and
unverified. Full candidate validation, SLO/load evidence and genuine backup/restore
remain required. Docker recovery retained the same sole scoped PostgreSQL container;
no database, volume or configuration reset occurred.

## P3-02 persisted scenarios and public interfaces

Migration `20260915_0020` adds the normalized scenario source, definition/version,
run/input/result and component records (254 total tables). Published inputs and
saved results retain canonical digests, owner/account/snapshot identity and original
source lifetimes. Final authorization checks cover every original observation and
membership before private decoding and again after potentially time-consuming reads.
Replay proof binds the original total-return membership, FX legs, calendar closes and
knowledge dates. Revoked or expired sources fail closed; derived financial copies
are physically drained within the existing shared retention budget before parents.

Admission uses existing semantic command identities, transactional outbox, owner
locks and shared premium capacity: two active jobs per owner, one globally running,
512 versions, 32 MiB per run and 256 MiB per owner. Isolated scenario execution has
an absolute 240-second lifetime across retries, 60-second leases/15-second renewal,
bounded dispatcher batches and a 512 MiB address-space limit. Cancellation and
expired leases fence final publication. These are enforced limits; peak RSS and
load SLOs have not yet been measured.

Eight new paths/eleven operations expose immutable scenario revisions, saved runs,
complete paged components and comparisons. The total inventory is 109 REST paths,
123 operations and 419 schemas. ADR-0028 bounds financial pages to 1 MiB, envelopes
to 2 MiB and whole components to 25 by default/100 maximum. Sixteen source previews
carry exact omission counts; canonical full proof stays retained. Cursors bind
principal, account, ordered results/digests, page size and current expiry. Current
authorization precedes cursor decoding and conditional 304 responses.

The four scenario MCP tools bring the implemented registry to 32 tools/seven
resources; only internal `create_scenario_run` adds a write. Prior 28 tool descriptors
and six resources retain byte-bound compatibility. Signed transport, private errors,
closed input schemas, source/account boundaries and the 2 MiB response cap have
regressions. The scenario resource provides named tables, keyboard scrolling and
three-width browser captures. The web workspace implements editing/version history,
saved X-ray input selection, bounded polling/cancellation, comparison, exact API
financial strings, browser URL state and account-safe selection clearing.

The unchanged-source `scenario-local-01` gate passed 3,903 Python unit/property/
contract/security cases (252.728 seconds; total gate 279.289 seconds), mypy over 799
files, Ruff over 804 files, generated-contract/secret/architecture/broker checks and
all 12 Python package builds. The subsequent `scenario-web-full-02` passed 662 web
cases, lint/typecheck and the production build. The one-worker Next build passed
`scenario-web-build-03`; production browser fixtures now use the actual standalone
server and symlink its existing static assets without duplicating builds. The
widget table-width correction passed two focused Python and ten browser cases in
`scenario-widget-02`. These later executable differences are retained in the
source manifests and verified by their relevant gates, not attributed retroactively
to the earlier full Python run.

PostgreSQL schema gate `scenario-schema-postgres-04` passed 13 cases covering fresh
head, metadata parity, repeat migration, populated 0019 preservation, downgrade and
re-upgrade. Runtime attempt `scenario-runtime-postgres-02` had 36 passing cases and
two fixture setup errors: a coexisting fixture's DATABASE_URL redirected Alembic to
the wrong database. Scoping DATABASE_URL to the fixture's own migration corrected
this; `scenario-runtime-postgres-03` passed all ten selected cases. Thus 38 distinct
runtime cases have passing executions across those two attempts; the original
failed gate remains failed. The real production API/isolated-worker journey passed
at 1440/768/360 pixels in `scenario-web-browser-04` (223.820 seconds), creating two
immutable versions/runs and checking canonical fields, pagination, comparison,
keyboard clearance, no document overflow and account switching. Earlier browser
attempts preserve the strict-label locator issue, generated Next type-path mutation
and empty hidden React streaming-table diagnostic. Financial parity assertions
were preserved. The final `scenario-delivery-local-01` static/662-web/build gate
passed in 35.671 seconds. Visual review then identified oversized identifier columns;
fixed column widths, wrapped identities and contained disclosures corrected them.
The focused `scenario-web-layout-01` gate passed component tests, lint/typecheck and
production build in 10.299 seconds. The final `scenario-web-browser-06` passed all
three journeys in 220.865 seconds with unchanged source, including new bounded-column
and mobile summary-width assertions. ROOT reviewed the three final result captures.
All 21 journey captures retain their original viewport dimensions; fixed mobile
navigation appears at the viewport boundary in full-page captures. Prior passing
browser05 remains an earlier source observation, not the final layout evidence.

All receipts, commands, source manifests, failed attempts, JUnit/Playwright outputs
and original captures are retained under the task's external `phase3-20260914`
evidence directory. The delivery receipt binds this component commit separately.
No new coverage percentage, final immutable candidate pass, full accessibility audit,
SLO, genuine restore or package acceptance is claimed. All 30 acceptance rows and
48 scenarios remain pending. Scenario reports and projection integration are next;
CI remains owner-deferred/unverified. The same sole task PostgreSQL container is
reused, with each synthetic test database removed by its fixture.

At this delivery boundary, active-consumer checks preceded removal of inactive
Next development output and a superseded Python package build: 213,745,664 allocated
file bytes. The cleanup receipt retains exact paths and SHA256 inventories. Current
production output, required dependencies, source, evidence, handoffs and both database
volumes remain intact. Docker inventory confirms only the existing task PostgreSQL
container is running; it is still required by subsequent Phase 3 runtime checks.

The final staged diff check detected trailing whitespace inside the newly added
migration's SQL literals; earlier unstaged checks did not inspect new files.
Only line-ending whitespace was removed. The failure and exact before/after hash
are retained. The subsequent schema05 gate exposed a missing pytest fixture alias
in the final source (seven passes, one setup error); explicitly registering the
shared risk fixture corrected it. `scenario-schema-postgres-06` then passed all
13 cases in 8.26 seconds (9.475-second gate), with unchanged source. These two paths
are the only executable differences from browser06 and are covered by this fresh
schema gate; final documentation/static checks and the delivery receipt bind them.

The extra migration lint check flagged runtime string construction from the frozen
table tuple. The identical downgrade predicate is now a literal SQL statement and
the new migration is formatted. Final `scenario-schema-postgres-07` passed all 13
cases in 8.15 seconds (9.351 seconds total), plus migration/fixture lint and format.
The preceding documentation02 gate passed mypy/secret/governance/format checks but
remains failed at migration lint. The two final executable differences from
browser06 are covered by schema07; no earlier failing gate is relabelled.


## P3-02 explicit scenario and risk report profile3

ADR-0026 is implemented with the explicit `report_sections_v3` selection and
document schema `3.0.0`. The same six premium routes retain their operation IDs and
default profile2 behavior. V1/default V2 values, original codecs and schemas remain
compatible. The generated premium client chooses its closed schema through an
explicit constructor profile; query/body conflicts, duplicates, cross-profile
IDs, cursors, grants and conditional reads fail before private decoding. Existing
MCP tools continue to use their preserved contracts. The current inventory is
109 paths, 123 operations, 441 schemas, 32 MCP tools/seven resources and ten broker
GETs. Migration `20260915_0021` adds eight normalized actual-run binding fields
without adding tables (254 remain).

Scenario reports copy the complete original saved result through ten analytical
and seventeen proof tables, including unavailable components, factor/rate witnesses,
X-ray paths and original historical replay/FX/calendar evidence. No simulation or
scenario calculation runs during report capture. Original and current STORE,
DISPLAY and REPORT rights precede private data and are checked again before sealing
and artifact reads. Source lifetimes clamp every retained copy; report payloads
drain before scenario/source parents. Profile3 may retain an analysis currency
different from the snapshot currency only while preserving every original money
cell's currency and an explicit warning; V1/V2 currency restrictions remain intact.
Reserved projection/goal/research vocabulary remains unavailable until implemented.

The real EUR and GBP source fixtures compare PDF, CSV, JSON and XLSX back to the
complete canonical report. They preserve exact numbers, quality inheritance,
original IDs/digests, source clocks and all proof membership, with no formula or
external spreadsheet execution. The established 32 MiB document, 2 MiB manifest,
256-license, 100,000-row/table, 10 MiB/artifact and 25 MiB/artifact-set limits remain.
The licensed sensitivity fixture independently expects coefficient -2 times .01
to produce -.02. The historical fixture independently expects total-return
100/110/121 and USD/EUR .8/.84/.88 to produce local .21, FX .1 and reporting .331.
REPORT-only revocation denies new capture and retained report reads before private
decoding while the separately permitted scenario read remains usable.

Final `premium-report-v3-local-04` passed all 4,329 unit/property/contract/security
Python cases (270.413 seconds), all 707 web cases, Ruff 834 files, strict mypy
829 files, workspace/repository/secret/architecture/broker/generated-contract checks
and all twelve Python package builds. Total gate: 310.918 seconds, unchanged source.
`premium-report-v3-postgres-05` passed all 15 cases (140.902 seconds; total
143.245 seconds), including empty/head/repeat/parity, populated 0020 preservation,
exact downgrade guard restoration/re-upgrade, altered source pins, V3 downgrade
denial, shortened original lifetimes, permission revocation and bounded physical
purge with busy-owner exclusion. Eight distinct artifact cases have passing
executions across artifacts02 (seven pass/one fixture failure) and artifacts04
(corrected EUR case). Sources02 passed both actual licensed source cases. These
populations are deduplicated rather than added across overlapping attempts.

The real browser04 gate passed all three 1440/768/360-width journeys in 419.766
seconds using the production standalone web build and actual API/scenario/report
workers against one PostgreSQL container. It checked all four formats, exact values
and proof, profile/account isolation, saved-result selection, keyboard/focus and
no document overflow. Nine original captures remain; ROOT reviewed the three
completed views. Action-to-navigation annotations were 8162/8168/8182 ms. These
include the whole server action/navigation and do not establish the API admission
SLO; performance investigation and the full accessibility audit remain pending.

Failed attempts are preserved with their own original source manifests and logs.
Earlier focused/typing gates exposed narrow type and synthetic fixture issues.
Postgres01 rejected an unescaped SQLAlchemy colon inside a quoted SQL string;
later Postgres02/03 fixture corrections were verified and final Postgres05 is green.
Artifacts02's EUR fixture incorrectly required an optional absent FX table; GBP
and the other seven cases passed. Artifacts03 caught an unused transport binding;
artifacts04 passed the corrected EUR case, all static checks and production build.
Sources01 caught fixture constructor/typing errors; sources02 passed both cases.
Browser01's five-second navigation expectation was too short; browser02 introduced
a wait for a Next streaming response to finish even after the actual report had
succeeded; browser03 overlooked canonical inherited quality. Browser04 retains
the real 30-second navigation bound and exact effective-quality assertions.
Local01 stopped on formatting of four new JSON fixtures. Local02 passed 4,327 cases
and failed two old assertions requiring byte-identical premium descriptors despite
the accepted explicit-profile change. The new independent oracle binds the original
six routes and 38 original client declarations, permitting only the closed selector
and V3 variants while preserving all other descriptors. A prematurely started
local03 was explicitly interrupted; it is not a pass. Compatibility01 and local04
passed the corrected oracle. No production behavior was weakened to satisfy tests.

Browser04 and local04 have identical production content/type/mode; the eight
intervening differences are test-only formatting/compatibility-oracle changes.
The final documentation gate and external delivery receipt bind the eventual
commit/tree separately. Original commands, logs, source manifests, JUnit outputs,
Playwright data and screenshots are under the task's external `phase3-20260914`
directory; they will be included in the final portable candidate pack. The bounded
agent code review found no actionable issue in its profile/source/retention/parity
scope, performed no checks and is not external acceptance. No new coverage,
SLO/RSS/load/restore or package acceptance claim is made. All 30 acceptance rows,
48 scenarios and final immutable Phase 3 validation remain pending. CI remains
owner-deferred/unverified; P3-03 integration is next.

At the delivery boundary, scoped consumer checks preceded deletion of unused Next
build cache and the superseded scenario Python build: 218988544 allocated file bytes.
The cleanup receipt preserves every removed file hash and records unrelated system
daemons whose proc descriptors are restricted. Current standalone assets/types,
new package builds, dependencies, source and evidence remain. The sole task
PostgreSQL container is still needed for projection integration; unrelated volumes
are preserved.

## P3-03 projection and profile4 integration checkpoint

Working-tree observations on 2026-09-15; final source acceptance remains pending.
Migration 0022 currently defines 289 tables. Generated OpenAPI currently contains
121 paths, 140 operations and 513 schemas; MCP has 36 tools/eight resources and
exactly ten sealed broker GET capabilities remain unchanged. The accepted
ADR-0029 point-page contract preserves complete retained financial rows, exact
Decimal money strings and bounded owner/account/source-bound cursors. Saved
assumption and goal versions, isolated projection workers, current source rights,
REST/MCP transport and the production web workspace are integrated.

Earlier component receipts include projection-postgres-schema-04 (21 cases),
projection-api-runtime-01 (actual signed-JWT transport), projection-mcp-runtime-03
(actual signed SDK transport), projection-widget-01 (nine viewport checks), and
projection-web-browser-04 (three production journeys with all 84 financial points
across four pages, cancellation, version immutability and account switching).
These source-bound receipts predate later retention/report changes and are not
claims that the final working tree passed their full populations.

The normalized retention frontier, sweep cursor, source-policy epochs and
trigger-maintained physical storage counter have component checks. The PostgreSQL
retention-budget run02 passed seven cases before a fixture-key failure; run03
passed two source cases before an unsupported nested-evidence fixture failed.
Run04 passed the three corrected remaining cases in 11.98 seconds, including
legal historical evidence, future activation and live-owner isolation. The
accepted historical admission rule rejects evidence nesting beyond its supported
level; the fixture now checks that rejection rather than relaxing the rule.
SQL source-parent and report-copy guards still need their indexed membership/
restriction-witness changes before the total 4,096-inspection budget can be accepted.

ADR-0030 profile4 adds explicit projection/goal report composition while preserving
V1/defaultV2/V3 contracts. It copies complete saved paths and all 12 money values,
assets, distributions, goals and original source proofs into 24 fixed tables. Model
dates and optional original observations remain distinct from the separately
selected report-context snapshot. Selection requires actual immutable run IDs;
no caller result arrays or numerical recalculation enter report capture. Original
and current STORE/DISPLAY/REPORT rights precede private decoding and final sealing.
The domain/capture/worker-codec focused gate04 passed 334 tests with strict mypy (925 files).
Transport-focused04 passed 257 Python tests, 221 web tests across 21 files, Ruff,
strict mypy (930 files), all workspace TypeScript, ESLint and
exact generated-contract checking in 47.858 seconds with unchanged source.
The source manifest is authoritative for each gate; prior failed attempts stay
failed. SQL0023, actual report4 PostgreSQL/four-format output and three browser
viewports are still pending; these component checks do not imply runtime acceptance.

ADR-0031 research item/review/retention design is accepted. Its domain and eight
application operations are integrated; research-foundation-focused03 passed all 18
tests in 0.66 seconds, Ruff and strict mypy (941 files) in an unchanged-source 1.211-second
gate. Research persistence/provider authority and public interfaces remain pending.

All originals remain in the external phase3-20260914 evidence directory for the
final portable pack. No package, acceptance row or mandatory scenario is marked
complete. Coverage, SLO, whole-worker RSS, restore and independent review remain
pending; GitHub Actions remains owner-deferred/unverified. At this checkpoint,
consumer checks preceded deletion of 158421949 logical bytes of unused task caches
and temporary pytest metadata. Source, dependencies, accepted evidence and current
build products were preserved. One healthy PostgreSQL container remains in use.

Research runtime modules and shared source-cleanup composition are now integrated;
research-runtime-focused02 passed 23 tests in 1.81 seconds, Ruff and strict mypy
(955 files; 4.762-second unchanged-source gate). Migration 0024 remains externally
staged until its 0023 predecessor is integrated. No research PostgreSQL/schema
result is claimed.


## Projection reports, research pages and retention continuation

This subsequent working-source checkpoint integrates migrations0023/0024/0025 and
317 ORM tables. The generated API has127 paths,148 operations and533 schemas; MCP
remains36 tools/eight resources. All thirty acceptance rows and forty-eight scenarios
remain pending. Earlier checkpoint paragraphs preserve their then-current scope.

`projection-research-postgres-schema-02` passed five fresh/populated/repeat/parity/
downgrade cases through0024 before later research-index and0025 changes. Independent
normalized projection membership and cleanup checks passed17 PostgreSQL cases in
`projection-membership-postgres-01` (85.447-second gate). Research physical cleanup
unit checks passed38 cases in `research-retention-focused-03`; runtime is still pending.

Actual report4 admission found and corrected invalid pin-account column references,
PostgreSQL JSON operator precedence, and an old profile allowlist. Real isolated PDF
rendering then exposed a missing projection/goal analytical section mapping; its fix
preserves the old section registry. `projection-report4-postgres-05` passed both actual
four-format/goal modes and ten PDF tests before failing the subsequent source cleanup
case. The new date-cell assertion compares typed dates to typed calendar boundaries;
financial values are unchanged. Separate original/current rights/copy-witness runtime
checks passed all three cases in `projection-report4-sources-postgres-01` (68.104s).
The report-only cleanup regression retains its80-inspection/10-removal/one-artifact
allowance. Diagnostic-only additional metadata counters showed repeated source scans
starved atomic artifact/grant removal after a permanent marker. Exact pending-copy
resumption resolves it; a unit negative proves it cannot authorize an unmarked sibling.
These PostgreSQL passes predate0025's additional guarded physical dependency flags.

The eight research REST operations, strict DTOs, actual OpenAPI/client generation,
account/session/CSRF/current-source checks and unchanged eleven previous client renders
are integrated. API/schema/contract/PDF tests passed96 cases in the otherwise failing
`research-api-focused-03`; its only remaining failures were four invalid RFC UUID client
fixtures. `research-api-focused-04` passed the corrected five client cases, nineteen
repeated contract cases, exact generation, Ruff, mypy980 and workspace TypeScript.
Bounded research pages now use the actual retained X-ray two-read/final-read helper,
current and original capability batches, exact eligible-set cursor fingerprints and
whole-record envelope packing. The proposed twelve-statement complete summary bound
still requires real PostgreSQL measurement; it is not a latency or whole-service claim.

`research-legacy-focused-04` passed71 focused cases, Ruff1003 files and mypy998 files
in5.725s. It includes exact-source batches, saved-byte X-ray checks, pending-copy sibling
isolation and the newly integrated0025 legacy report sweeps/flags. SQL identifier
composition uses only closed internal registries with bound external values; its few
S608 exceptions are local and documented at those expressions. Actual0025 migration,
research runtime and legacy report PostgreSQL checks are next. The0025 epoch triggers
add three physical inspections to separate enrichment/scenario marker insertion;
that participant accounting and further shared run cleanup remain in progress.

The earlier broad `projection-research-isolated-01` passed4924 Python cases and800
web cases but failed two real projection child memory checks. Linux pre-exec inherited
ru_maxrss caused the incorrect child-only peak measurement; `/proc` VmHWM records the
executed child instead. The fixed512MiB limits remain, and the inherited-memory
regression passed in the102-case focused gate. This is a kernel child estimate, not a
whole-worker RSS/SLO pass. A fresh broad rerun, actual report4 browser verification,
remaining Phase3 work, restore/security/portable evidence and independent review remain
required. CI stays owner-deferred/unverified; no production or live-provider claim.


## Research, report4, widgets and public PWA component evidence

Subsequent unchanged-working-source observations:

| Gate | Observed result | Total seconds |
| --- | --- | ---: |
| research-postgres-03 | 16 runtime, retention and bounded-page PostgreSQL cases | 179.029 |
| research-web-browser-03 | Three production API-backed research journeys | 104.080 |
| projection-report4-browser-04 | Three production journeys; complete original PDF/CSV/JSON/XLSX proof | 208.135 |
| research-mcp-focused-06 | 177 contract/security/unit cases; exact 38 tools and eleven resources | 53.968 |
| research-widget-browser-02 | Four Python and 17 actual iframe browser cases | 12.233 |
| pwa-shell-browser-02 | Three production offline/cache/palette/account/logout journeys | 44.629 |
| premium-retention-static-02 | 22 Python and four web worker-cache tests, Ruff1026, mypy1021, TS/ESLint/build | 14.619 |

The real complete research summary used twelve SQL statements. Single-item/write
paths and latency remain separately unverified. Research browser checks cover exact
saved X-ray amounts, 25+4 pagination, immutable note history, review and account
isolation. A Gzip drain-listener warning remains under investigation; no process
memory or performance acceptance is inferred. Widget checks cover three widths,
current account bindings, cancellation and offset instants without microsecond loss.
Report4 preserves the original saved run, exact dated flows and all older profiles.

PWA checks exercise actual service-worker control, manifest/icon dimensions, only
five public cached assets, network-only private responses, offline unavailability,
keyboard navigation and sign-out. ROOT inspected the mobile offline capture.
An earlier browser attempt selected an account absent from its fixture; the corrected
run enables the existing two-account fixture. An earlier PWA build completed but
rewrote Next's generated route-type imports, so its gate remains unaccepted as
changed-source evidence. The later stable build is recorded above. Earlier incorrect
report/widget oracle and locator attempts remain failed in their original receipts.

`legacy-report-research-postgres-02` passed actual signed SDK/PostgreSQL research
transport and two V2 cases, then failed V3 retention. Its fixture froze maintenance
time before capture. A real concurrent capture can have the same later original
clock: the corrected one-row metadata selection defers captures created after the
sweep timestamp, without weakening SQL witness authority or pre-filtering unbounded
descendants. The regression preserves the actual payload before refreshing the
fixture clock. The subsequent `premium-retention-postgres-02` passed all 19 migration, physical
cleanup, signed research transport, report-copy and bounded-page cases in 284.150
seconds with unchanged source, including this regression.

Migration0026 adds four guarded operational tables, exact original retained-parent
memberships, physical counters, source-owner scheduling and charged risk/scenario/
sensitivity cleanup. Canonical financial bytes and original authority are preserved.
The first actual migration run passed upgrade/repeat/old-byte/downgrade checks before
its expected error text assertion mismatched the exact continuation refusal; the
corrected assertion and final parity/runtime suite passed in the 19-case gate. Phase2 source,
X-ray, historical and alert physical-budget closure remain explicit unfinished work.

Whole-worker RSS, broad isolated rerun, provider acquisition, saved layouts, aggregate
accounts, research reports, final security/restore and portable immutable evidence
remain pending.

The later `pwa-shell-browser-05` rebuilt production and passed all three viewports
with the installed axe-core 4.13.0 auditor: zero serious/critical WCAG findings on
the palette, fully loaded settings and public offline page. The audit first exposed
nested interactive roles in the palette; the fix puts the option role on the link
itself, preserving keyboard and ordinary navigation semantics. The previous failure
remains recorded. Readiness assertions now prevent capturing loading placeholders.
This is scoped accessibility evidence, not the final whole-product audit or CWV gate.

No acceptance row/scenario or final candidate is completed by these
component gates. GitHub Actions remains owner-deferred/unverified.

At a consumer-free boundary, inspected Next cache and pytest metadata totaling
123308310 logical bytes were removed. Source, dependencies, current build, original
proof/captures and PostgreSQL state were preserved. Originals are retained externally
under phase3-20260914 for the final portable pack. One existing PostgreSQL container
remains in use. Receipts do not replace their referenced originals.


## Checkpoint retention compatibility, 2026-09-15

`phase3-checkpoint-isolated-02` passed 5,127 Python tests and all 831 web tests,
plus Ruff, mypy, TypeScript/ESLint and repository/generated-contract boundaries,
but failed two old unit fixtures: a legacy report metadata double omitted its
newly selected `created_at`, and the current ORM profile assertion still excluded
explicit profile4. Their corrected 25-case focused suite passed. The original
failed receipt remains retained. The subsequent `phase3-checkpoint-isolated-03`
passed all 5,129 Python tests and 831 web tests, plus the same complete static,
generated-contract and repository checks, in 506.768 seconds with unchanged source.
Three existing pytest `record_property`/JUnit2 warnings remain recorded; there
were no failed, skipped or errored Python tests. This is an isolated component
checkpoint, not final Phase3 acceptance or a replacement for PostgreSQL/browser
evidence at its recorded source.

`premium-retention-compat-postgres-02` passed 47 cases and failed one in 479.841
seconds. The real annual risk fixture now resumes within each original 4,096-row
allowance because mutation accounting includes SQL guards and counter work. Its
small 96-row allowance is unchanged; the finite pass ceiling accommodates the
365-day fixture's charged mutations. Busy-owner, fencing, source isolation,
canonical-last and final physical-capacity assertions remain enforced.

The remaining scenario test assumed private input survives until terminal metadata
completion. The corrected test keeps its 128 inspected-row/one-removal budget and
independently proves that canonical input can disappear only after all normalized
financial rows and result bytes are gone, with a zero protected financial counter.
The retained capacity charge stays unchanged until indexed parent cleanup and the
terminal marker finish. This stronger regression passed in
`premium-retention-compat-targeted-03` (one test, 13.960 seconds). Thus all 48 distinct
compatibility selectors have passing executions across these two source-bound
receipts; this is not a claim of a single all-green aggregate run. No production
implementation was changed by these compatibility-fixture corrections.

The one existing PostgreSQL container was reused; fixture databases were disposable.
No provider stage, saved-layout stage, paid/live request or remote Actions run was
introduced by this checkpoint verification. Full Phase3 and final acceptance remain
pending, with original failed evidence preserved.

The checkpoint source-security pass found no Semgrep findings after replacing only
three test-local nested type arguments with equivalent named TypeScript aliases;
28 focused web tests, TypeScript and ESLint passed. The strict scan retained all
seven rules and parsed the selected source successfully. Python and production
JavaScript dependency audits reported no known vulnerabilities, and the unchanged
Gitleaks exception-policy regression passed its 16 approved lines/21 negative cases.

The additional entire staged-tree Gitleaks scan retained exit1 with 54 findings in
five unchanged historical files. Exact review independently recomputed the original
API/client SHA256 values, verified existing historical fingerprints against complete
Git blob bytes, and inspected the synthetic report-row/idempotency syntax. All 54
are noncredentials; the raw redacted result and exact classification remain separate
originals. No scanner exception, inherited rule or historical artifact was modified.
The changed-file secret scan and Python package build are recorded separately.

## Saved layouts, provider acquisition and physical source closure (2026-09-22)

Working source extends d29c82f; this is component progress, not Phase 3 acceptance.
Migrations0027–0029 add durable bounded provider reservations/attempts, indexed
Phase2 source-copy closure, and owner layout/version/command/cursor storage. The
observed inventory is344 normalized tables and131 REST paths/154 operations/550
schemas; MCP remains38 tools/11 resources and Trading212 remains ten fixed GETs.
Provider status is metadata-only and does not verify credentials or live access.
Explicit source fallback preserves the selected original successful acquisition,
source/quality/cutoff and current rights instead of silently requesting replacements.

Historical inception capture now retains selected opening provenance references,
including their transitive source dependencies. Physical source, X-ray, historical
and scenario cleanup uses indexed pending work and the shared original budget.
Alert/research-report/aggregation closure remains under implementation.

Evidence lives under the task state directory
`/home/peppasmich/.local/state/t212pi/20260908-resume/phase3-20260914`. Every named gate
retains the exact command, timestamps, source manifest, logs, exit and original test
results. These receipts bind unaccepted working sources, not an immutable candidate.

- `providers-retention-focused-02`:118 Python cases and included static/boundary checks
  passed in4.541s. `historical-composite-postgres-01`:3 actual PostgreSQL cases passed
  in32.105s for direct/transitive historical provenance and composite copy closure.
- `layouts-status-focused-05`:88 Python cases and static/type/lint checks passed;
  its web group had28 passes and one microsecond-clock fixture failure. The corrected
  `layouts-status-web-01` passed all29 web cases. Failed predecessor receipts remain.
- `layouts-status-postgres-03` passed the migration case before an explicit flush
  ordering defect failed layout creation. Root now flushes parent/version/widgets
  and audit receipt in the required atomic FK order. `-05` passed the first two
  layout cases before a negative fixture URL exceeded its scalar bound. Correcting
  that fixture lets `-06` pass the remaining three layout cases and all three status
  cases before the old rollover fixture failed. These broad gates remain failed;
  only their actual passing individual cases are reported here.
- `provider-rollover-fallback-postgres-01`:4 cases passed in37.786s. The rollover
  fixture uses an explicitly simulated consistent Python/SQL clock in its disposable
  DB, restores the exact original SQL function, and proves a Python-only future
  reservation still rejects. Production clock guards and quota/deadline bounds stay
  unchanged. Both actual source-fallback replay cases pass without new acquisition.
- `owner-layout-browser-05`:three production journeys passed in67.161s. The extended
  `owner-layout-browser-07` also passed three journeys in66.687s, adding actual
  provider-status API/settings parity. Desktop1440, tablet768 and mobile360 checks
  cover exact canonical previews, immutable history, original X-ray pins, account
  switches/denial, archive/logout, no private browser cache, keyboard visibility,
  no page overflow and zero serious/critical axe WCAG AA findings. Root inspected
  the retained mobile canonical-preview capture. Earlier failures and screenshots
  preserve locator corrections and the real link/select target-size fixes.

Docker recovery reused the existing healthy PostgreSQL container with1CPU/1GiB.
No additional stack or provider request was created. At the completed browser
boundary, `layouts-unused-cache-cleanup-20260922.json` records162268447 logical bytes
removed from inactive task Next cache/standalone and pytest cache only; source,
dependencies, retained evidence and unrelated Docker data were preserved.
GitHub Actions remains owner-deferred/unverified; all final acceptance/SLO/independent
review and production prerequisites retain their separate pending/external states.

The subsequent `provider-layout-checkpoint-isolated-06` gate passed against an
unchanged working-tree fingerprint in 542.469 seconds: 5,335 Python unit,
property, contract and security tests; 860 web unit tests; Ruff; strict mypy;
workspace TypeScript/ESLint; formatting; generated-contract drift; documentation,
workspace, secret, architecture and sealed Trading212 checks. Three existing
pytest JUnit `record_property` warnings remain. Attempt05 is preserved as failed
(5,332 passes, three failures): two aggregate API inventory assertions needed the
additive layout/status totals, and one mocked source needed its adapter version.
The focused follow-up exposed the second stale operation count before attempt06.
No application behavior or assertion strength was changed for these corrections.
These are component checkpoint results, not Phase3 final acceptance.


The bounded independent checkpoint source review identified a semantic replay defect:
two separately charged acquisitions with identical normalized facts reused one source,
but the second request lacked a replay association. Migration0027 now records an
immutable, content-free attempt-to-original-publication association. Reuse preserves
the original grant, first-known clock and expiry, with current STORE/DISPLAY checks
before decoding and returning retained data. `acquisition-replay-postgres-01` passed
17 actual PostgreSQL cases plus Ruff/format/strict typing in152.907s, including four
new independent-request, original-expiry and SQL denial regressions. The additional
association raises this component inventory to344 tables; public API counts are unchanged.

`provider-layout-migrations-02` passed all23 migration checks in90.597s, including
empty/repeated head, ORM parity, populated accepted0016-to-head preservation and
historical0019/0020 upgrade/downgrade followed by repeated current head. Attempt01
remains failed with21 passes and two stale test assumptions: the static0020 inventory
was compared to current metadata, and an intermediate revision was incorrectly passed
to Alembic's current-head comparison. Historical table counts/fingerprints remain
explicit; actual head tables must equal the full ORM table-name set.

The earlier security/build attempt01 passed configured Semgrep, secret-policy and
dependency checks before its additional changed-file scanner reported two synthetic
fixture-label false positives. Those labels were shortened without adding exceptions;
`historical-composite-postgres-02` then passed all3 cases in32.841s. Attempt02 scanned
142 changed files with zero findings and built all24 wheel/source artifacts, but its
artifact verifier counted uv's `.gitignore` as a package and failed. The separate
`provider-layout-artifact-proof-03` verified those original24 archive hashes/integrity
and build-log successes against the original source manifest in0.173s. Both original
failed gates remain failed; these observations predate the replay correction.


The updated `provider-layout-checkpoint-final-01` passed in195.903s with an unchanged
working-source manifest: Ruff/format, strict mypy over1090 sources,61 focused Python
cases, repository/workspace/secret/architecture/ten-GET checks, generated contract
and formatting checks; configured security checks and both dependency audits; the
complete staged contents of147 changed files with zero Gitleaks findings; and all24
wheel/source builds across12 packages, with verified archive integrity and hashes.
Semgrep ran7 rules on925 files with zero findings; its existing ignore patterns
excluded703 files and its1MiB limit excluded3 files. These limits are retained,
not an exhaustive security assurance. The temporary scanner ran serially while
PostgreSQL was stopped; its automatic removal completed and PostgreSQL restarted.
Only this appended documentation follows that source manifest; executable bytes
are checked for equality before the checkpoint commit. Final immutable Phase3
validation and independent acceptance remain pending.

## Owner-requested aggregation checkpoint — 2026-09-30

The owner requested committing the current implementation so it can resume later.
The integrated aggregation/FX picker source remains in progress: 364 ORM tables,
136 REST paths/161 operations/578 schemas, with the original ten broker GETs and
38 MCP tools/eleven resources unchanged. The most recent PostgreSQL diagnostic
fails during aggregate run publication with `aggregate native component proof differs`.
No aggregation browser, full candidate or package acceptance is claimed. The
[checkpoint handoff](PHASE_3_RESUME_20260930.md) preserves the exact failing selector,
prior component receipts, remaining integration order and local artifact locations.
