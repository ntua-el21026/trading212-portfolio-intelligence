# Phase 3 Implementation Report

**Current:** P3-01 calculation, storage, worker, REST and generated client implemented; web/MCP/report delivery and retention verification in progress
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

risk-mcp-final-postgres-05 then passed51 real PostgreSQL cases in114.54 seconds:
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
