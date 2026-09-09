# P2-04 Historical Performance and Income Intelligence

This document preserves the P2-04 acceptance and earlier investigation history.
Then-current package counts and pending statements below remain historical;
[current P2-05 scoped acceptance](P2_05_PORTFOLIO_XRAY.md) is recorded separately.

P2-04 is **complete** at exact implementation SHA `2a7c89a9b8c37d97006dafbbe97a44eec37b3fe0`. Implementation began at `05d01c7a9a9cb6cc3f351c3adbed2036f02b94a9`; P2-03 acceptance remains at `e258f54bb03a958f7847b310ee882b7f4a54686f`. This is scoped package acceptance, not complete Phase 2 release acceptance.

## Authority and implementation scope

The owner assignment, [execution manifest](PHASE_2_EXECUTION_MANIFEST.md),
[methods](../analytics/PHASE_2_METHODS.md),
[data model](../architecture/PHASE_2_DATA_MODEL.md),
[API contracts](../architecture/PHASE_2_API_SERVICE_CONTRACTS.md),
[MCP registry](../integrations/PHASE_2_MCP_TOOL_REGISTRY.md) and
[web information architecture](../architecture/PHASE_2_WEB_INFORMATION_ARCHITECTURE.md)
govern this increment. Required capabilities are historical accounting and
performance, composite benchmarks, residual-aware attribution, income and
cash-flow intelligence. The six additive HTTP reads, four MCP reads and connected
performance/income web views are part of this package.

Historical inputs must retain evidence for opening quantities/cash, economic
revisions, mappings, classifications, calendars, market/FX sources and knowledge
times. Current holdings and mutable activity projections cannot reconstruct the
past. Restated and point-in-time selection remain distinct, including material
correction bridges. Monetary calculations use explicit Decimal precision 80 and
ROUND_HALF_EVEN; persisted authoritative values retain currency and Q18 bounds.

Public results retain per-metric availability, complete coverage counts, financial
identity and once-persisted calculation time. Current source entitlements are
checked before replay, cursor continuation and conditional responses. Complete
public representations have their own ETag; no timestamp or legal-state change
alters the immutable financial digest.

The original `248431.27 EUR` synthetic portfolio remains a regression fixture.
Separate coherent histories exercise annual restatement, prior-period income and
timely point-in-time source knowledge. Their clocks and observations are explicitly
synthetic; they do not constitute validation of real provider access or licensing.

The annual account is `9a85cdf8-eac9-57c7-be38-e500e4b9edb4`, with retained
opening evidence from 2023-12-31 and complete 2024/2025 observations. The timely
account is `3b441096-e447-5dcd-9b53-c3f657ca5d21`; 2026-08-02 through
2026-08-22 has explicitly empty activity, source receipts at daily closes and
separate completed observations at UTC accounting boundaries. These independent
accounts preserve the original portfolio fixture. Their cash/quantity/cost
bookkeeping is separate from the product return calculations.

The intervening `abb655eb7f0e1335e4c74040cc96ad1a0f83bbeb` correction records
one exact historical Gitleaks fingerprint for a verified OpenAPI SHA-256 digest
in the P2-03 evidence artifact. Its quality, documentation and security CI runs
all passed. It changes no executable product behavior or broker capability.

## Implemented surfaces

The six typed HTTP reads are performance summary, performance series, benchmark
comparison, attribution, income, and cash flows. Four frozen MCP reads expose
the bounded performance, benchmark, attribution, and income projections from
the same application service. Source header and observation resources accept
the explicit `composite` benchmark variant; its base-one wealth and component
references remain distinct from raw provider index levels.

The `/performance` and `/income` pages provide date, source-cutoff and knowledge
selection, return methods, rolling/calendar periods, flow overlays, benchmark
comparison and supported partitions. Charts consume authoritative decimal
strings, with exact-value tooltips and named table equivalents. Capture replay
links and page cursors preserve the retained input identity. Historical reads
have a bounded 30-second client read timeout; existing reads and commands keep
their previous transport limits. Private export generation remains part of
the required P2-06 package.

`make seed-demo` seeds the original portfolio and both historical accounts via
the normal ingestion/materialization and typed source/evidence services. Repeated
seeding preserves immutable IDs, financial bytes and actual synthetic knowledge
times. Each history has a two-component 60/40 benchmark and a published two-group
target. The annual target is an explicit comparison with its earlier history;
the timely target was known at the opening observation. Annual history requests
use 2025-01-01 through 2025-12-31, and timely requests use 2026-08-02 through
2026-08-22 with `point_in_time` knowledge.

Source expiration denies access immediately. Bounded cleanup removes licensed
copies from retained input documents, canonical analytics inputs/results,
normalized amounts and FX rates, and composite values before deleting the
original source payload. Immutable IDs, digests and nonfinancial retention
evidence remain; a tombstone never fabricates replayable financial content.

## Observed package acceptance

P2-04 is complete at `2a7c89a9b8c37d97006dafbbe97a44eec37b3fe0`. The [accepted assertion map](evidence/phase-2-p2-04-2a7c89a.json) closes P2-PERF-001, P2-PERF-002, P2-INC-001 and P2-S14 through P2-S19. Shared P2-S34 remains `in_progress`: historical API/web/MCP parity is partial evidence; report/export and remaining shared scope are outstanding.

The clean exact-source `make validate` passed in 1165.723 seconds: 1,346 isolated and 175 service-backed Python tests, 88% combined statement/branch coverage, 203 web unit tests and 66 browser checks. A separate unchanged-source `env CI=1 PW_TEST_REPORTER=list T212PI_E2E_TIMINGS=1 make test-e2e build-web` passed in 366.184 seconds, retaining all 66 named browser passes and a successful web build with clean source before and after. The original full-gate GitHub reporter lacked individual browser names; the supplement adds that evidence without replacing the full gate or its image-build provenance. Pytest selectors are assertion inventory bound to observed complete test-file execution.

Exact pushed-source CI passed: Quality `34272112673`, Documentation `34272112714`, Security `34272112661`. Eight source/history/image scans passed under their retained scanner policies. Fresh runtime attempt 003 passed in 170.757 seconds: six historical HTTP reads, four MCP reads, configured web journeys and identical retained rows across all 101 inventoried tables after all seven services stopped/restarted. Task containers, volume and network were removed, with cleanup verified. Migration head is `20260907_0012`; the implemented inventory is 66 HTTP operations and 19 MCP tools; Trading 212 remains the exact ten GET-only capabilities.

See [runtime](evidence/phase-2-p2-04-2a7c89a-runtime.json), [security](evidence/phase-2-p2-04-2a7c89a-security.json) and [compatibility](evidence/phase-2-p2-04-2a7c89a-compatibility.json). Phase 2 remains `in_progress`: four of ten packages (40%), eleven of 29 local rows and eighteen of 40 scenarios complete. P2-05 through P2-10 and Phase 3 remain `not_started`; no final Phase 2 release SHA is claimed.

## Interrupted candidate and correction

The following entries preserve candidate-specific history. Their pending-acceptance statements describe those earlier candidates; their failures remain unaccepted.

Candidate `6a2074141d9c7bdd8aa64e1710777d153c4996f5` is not accepted.
[Quality run 34165840790](https://github.com/ntua-el21026/trading212-portfolio-intelligence/actions/runs/34165840790)
failed three historical browser load waits and the PostgreSQL coverage job limit.
Documentation and security passed; the interrupted exact local gate has no
accepted completion. Corrective profiling identified repeated single-candidate
corporate-action serialization, duplicate pinned-capture decoding and oversized
ORM source-use insert statements. The correction preserves conflict detection,
source/legal checks, immutable bytes, database triggers and existing time limits.

Local validation now reuses one Compose project. PostgreSQL and Redis run only
as required; the full application stack runs temporarily for acceptance. Obsolete
task containers, test volumes, networks and build metadata are removed after use.

Correction `92dc0e445809737a766c7f211c5dfef42adf9f6a` passed its complete
clean-source local gate, all 66 local browser cases and CI PostgreSQL coverage.
Its [quality CI record](evidence/phase-2-p2-04-92dc0e4-failed-quality.json) remains
failed: a monthly MWR filter exceeded the document-load limit, followed by an
unavailable benchmark prompt. The monthly projection computed XIRR for daily
points it never published and recomputed its displayed intervals. A narrower
correction removes those redundant solves while preserving daily valuation,
TWR drawdown and every published return/provenance field. Its exact-source
validation and runtime acceptance remain required.


Correction `a573343bf2a17aa01642e9764d97eb74f77fcd27` passed its complete clean-source
local validation in 1223.038 seconds, including all 66 browser cases and 88%
combined Python coverage. Its [retained CI record](evidence/phase-2-p2-04-a573343-failed-quality.json)
shows successful PostgreSQL coverage, MWR and income desktop journeys, but the
first benchmark/year submission still exceeded the unchanged 30-second document
load wait. The log has no request timing breakdown, so this is not proof of a
specific API or rendering bottleneck.

Fresh serialized profiling measured the annual cold benchmark service at
4.05–4.15 seconds locally. Controlled action-selection A/B measurements retained
identical canonical result, source-use and conversion bytes: benchmark calculation
was 1.60–1.62 seconds before and 1.43–1.44 after; group and sector attribution
were 2.01–2.06 before and 1.67–1.70 after. These are local observations, not CI
latency guarantees. A sole eligible snapshot now avoids constructing and filtering
redundant candidate tuples, while checking its inclusive coverage period. Multiple
snapshots keep the existing revision/conflict selection. Alternative database
insertion probes preserved all normalized rows but were slower, so persistence
keeps its existing bounded batches. Failure-only browser diagnostics retain the
original load predicate, limits and assertions. Exact-source acceptance remains
required before P2-04 can be marked complete.


Correction `f37e8de843419288bc7e4b7531de6cc9d4c9cedc` passed its complete clean-source
local gate in 1194.048 seconds, including all 66 browser cases, 1431 unique Python
tests across the coverage stages and 88% combined coverage. Its
[retained CI record](evidence/phase-2-p2-04-f37e8de-failed-quality.json) records
successful PostgreSQL, documentation and security checks, but another first
benchmark/year document-load timeout. The native request received HTTP 200 headers
at 207 ms and had no completed document or historical form after 30 seconds.
These are Next document headers; they do not establish upstream API completion.

A fresh instrumented local run kept the original performance-then-benchmark test
order, one fixture database, `CI=1`, one browser worker, zero retries and the
existing deadlines. Both tests passed. The cold benchmark API took 4.318 seconds,
including 1.659 seconds in calculation and 1.267 seconds in source-use publication;
its temporary database was verified absent after normal fixture cleanup. This
measurement does not explain the CI timeout. Opt-in fixture diagnostics record
bounded fixed API/worker stages without payloads, raw identifiers, SQL parameters
or exception messages so the next CI run can identify the pending stage. This
is diagnostic work; exact-source package acceptance remains outstanding.


Diagnostic revision `4aa1e235a5abe0432ca00060d2b35ce31fb705fe` produced the first
completed CI stage measurements. Its
[retained CI record](evidence/phase-2-p2-04-4aa1e23-failed-quality.json) shows
1291 isolated Python tests, 174 PostgreSQL tests and 88% combined coverage;
documentation and security passed. The cold annual benchmark API completed in
28.509 seconds, with 13.606 seconds in calculation and 7.669 seconds in source-use
publication. Its worker dispatch wait was below one millisecond. These inclusive
stage measurements establish where this request spent time; they do not quantify
individual SQL statements or promise a particular optimization gain.

The browser subsequently failed the unchanged five-second composite snapshot
heading assertion. Two consecutive source workers took 2.518 and 3.643 seconds.
Source order and timing associate these with header and observation reads, but
the fixed diagnostic route label does not directly identify those endpoints.
Both code paths decode the complete historical result to obtain its composite,
even though the sealed composite is already stored separately. The correction
prepares bounded source/calendar indexes within one calculation and reads that
sealed composite directly, retaining all dependency, permission and expiry checks.
This diagnostic revision received relevant precommit working-tree checks; it did
not receive a new clean-source `make validate` acceptance run. P2-04 remains under
verification and P2-05 remains unstarted.


Controlled local ABBA comparisons against immutable baseline source and pre-edit
canonical goldens measured annual benchmark calculation at 1.458 seconds before
and 1.005 after indexing. Group attribution changed from 1.733 to 1.241 seconds
and sector attribution from 1.754 to 1.276. All twelve results independently
verified and retained identical complete canonical bytes, source uses, conversions
and context. The index belongs to one calculation, keeps at most 256 descriptors
and 100,000 candidates including synthetic gaps, and falls back to the existing
selector when capacity is exhausted or the cutoff varies point in time. The
measured annual fixture retained about 508 KB of traced index/engine allocations;
this is neither process RSS nor a maximum-input memory bound. Local gains do not
establish CI timing or package acceptance.


A separate warm decoder/header comparison used the saved annual result
(4,507,978 bytes) and its identical retained composite (152,537 bytes, 365
observations). Five alternating timed rounds after warmup measured median
255.14 ms for full-result decoding and 9.87 ms for direct composite decoding;
every header matched. This excludes SQL, authorization, pagination and transport.
Focused PostgreSQL tests passed for header and page parity, malformed/mismatching
retained bytes, and revoked-license denial before decoding, including retained
cursor/ETag reads. Full exact-source validation and browser CI remain required.

## Runtime attempts and evidence-writer correction

[Attempt 001](evidence/phase-2-p2-04-2a7c89a-failed-runtime-001.json) failed its initial web login assertion: the complete seed exposed three accounts while the scratch web service lacked an explicit baseline account. Its HTTP status chain was not retained and is not inferred. [Attempt 002](evidence/phase-2-p2-04-2a7c89a-failed-runtime-002.json) passed historical HTTP/MCP/web checks but Compose start traversed removed seed/migrate dependencies. Attempt 003 used the explicit authorized baseline web account and restarted only the seven verified retained containers under the original readiness deadline. Both failed attempts and their verified cleanup remain separately retained.

The runtime evidence writer was corrected for the independently verified empty point-in-time cash-flow period: zero selected event/FX uses are legitimate only for that exact fixture with the empty-list digest, matching canonical identities, available fresh zero metrics and the required empty-period coverage/replay predicates. Four focused writer regressions passed. No source uses were invented; canonical, permission, source/replay and nonempty-result checks were not weakened. This changed scratch evidence validation, not product source or the successful runtime observations.

The [earlier supplemental browser observation](evidence/phase-2-p2-04-2a7c89a-unaccepted-browser-observation.json) reported 66 passing cases but changed two generated next-env.d.ts imports during Next dev execution, so it remains unaccepted. The accepted replacement ran make test-e2e followed by build-web, retaining named browser passes and restoring the exact tracked generated imports before its final clean-source check.

## Remaining P2-08 limitations

Source-backed known P2-08 limitations remain: the normal complete seed has three accounts, but Compose does not forward the documented T212PI_ACCOUNT_ID setting to web; unconfigured multi-account overview startup is not accepted. The accepted runtime used an explicit baseline-account scratch override. The global header must respect the authorized route account. Sticky-header section positioning, readable mobile labels and table presentation remain P2-08/S39 follow-up work. Configured runtime acceptance does not prove default unconfigured multi-account UI behavior.

## Original exact-full-gate screenshots

These ten PNGs are copied byte-for-byte from the original exact full-gate archive, with hashes bound by the acceptance artifact. Supplementary-run screenshots are not substituted. The retained views do not close shared S39 or the limitations above.

- [api-chromium-desktop / benchmark](evidence/t212-p2-04-api-chromium-desktop-benchmark.png)
- [api-chromium-desktop / cash-flows](evidence/t212-p2-04-api-chromium-desktop-cash-flows.png)
- [api-chromium-desktop / income](evidence/t212-p2-04-api-chromium-desktop-income.png)
- [api-chromium-desktop / performance](evidence/t212-p2-04-api-chromium-desktop-performance.png)
- [api-chromium-mobile / benchmark](evidence/t212-p2-04-api-chromium-mobile-benchmark.png)
- [api-chromium-mobile / cash-flows](evidence/t212-p2-04-api-chromium-mobile-cash-flows.png)
- [api-chromium-mobile / income](evidence/t212-p2-04-api-chromium-mobile-income.png)
- [api-chromium-mobile / performance](evidence/t212-p2-04-api-chromium-mobile-performance.png)
- [chromium-desktop / historical-widget](evidence/t212-p2-04-chromium-desktop-historical-widget.png)
- [chromium-mobile / historical-widget](evidence/t212-p2-04-chromium-mobile-historical-widget.png)
