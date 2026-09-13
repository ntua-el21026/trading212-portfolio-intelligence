# Phase 2 Implementation Report

**Status: final exact-source local P2-10 acceptance at 3998426aa7e7614e421518efd01b08188e194100; CI owner-deferred and unverified.**

Phase 2 adds virtual targets, contribution planning, historical intelligence,
portfolio X-ray, private reports and alerts to the corrected Phase 1 foundation.
Stage A and P2-01 through P2-09 retain accepted scoped historical records.
P2-10 hardening and lockstep 0.2.0 metadata were delivered at
03105f4d36b0457600dfc5ab6fb13b0308820027. Current source V is
3998426aa7e7614e421518efd01b08188e194100, tree
ff5522eb438a30cfa88aad6bf4e2853fb85ef3a0, following that exact parent and adding
the PostgreSQL/Redis OS security pins and retained failure/status documentation.
P2-10 has final exact-source local acceptance at 3998426aa7e7614e421518efd01b08188e194100. D denotes this later documentation commit. Its SHA and fast-forward delivery are recorded separately after pushing.

[P208 scoped acceptance](evidence/phase-2-p2-08-bc21516.json) remains bound to
bc21516; [P209 MCP001/002 acceptance](evidence/phase-2-p2-09-d70ab44.json) to
d70ab44; and the separate [P209/S33 authorization supplement](evidence/phase-2-p2-09-s33-bd47329.json)
to bd47329. Their scopes and original artifacts are preserved. The S33 closure
was delivered at edc1a51 before V. None supplies a final P210 result.

During preparation, an external successor rebased the 03105f4 report and closure
templates onto V using the retained 35-topic map, actual source inventory and
delivery receipts. This final report incorporates the subsequently reviewed
acceptance observations. The external rebase map is retained under
`${RESUME_ROOT}/p210-report-and-closure-candidate-3998426/rebase-map.json`.
The 03105f4 full-command pass, coverage, source-security pass and image-security
failure remain historical in section 11, including ROOT's observed loss of 70
original /tmp captures. They do not supply new-V acceptance. The companion
rebase-map binds the original inputs and exact document/report changes.
V produced 70 registered captures: 37 directly under
the durable TMPDIR and 33 legacy fixed-/tmp captures preserved byte-for-byte while
F was running. ROOT verified the literal browser-write path to durable copy to
collector chain, including distinct capture/copy times and unchanged hashes;
collector-input original is not a claim of direct browser creation there. Failed
preservation preflights remain retained. Final acceptance and documentation
materialization are separate from the later D delivery receipt.
All 70 original captures now have actual scoped ROOT review. The original blank desktop benchmark plot remains a disclosed limitation; a separately executed same-V production case supplied readable three-series rendering and exact benchmark/attribution assertions. Production probe failures caused by empty hidden React staging tables are retained; only that non-accessible empty markup is excluded from the external production predicate. The first finalizer rejected a dispatch source-hash mismatch in its own wiring. Its separately reviewed successor binds the existing proof to report_job_store.py rather than an unrelated worker file; four actual job proofs pass with the correct hash and reject the wrong one, with all predicate/deadline guards unchanged. The final acceptance passed under that corrected checker without rerunning or relabelling application evidence.

The [execution manifest](PHASE_2_EXECUTION_MANIFEST.md),
[acceptance matrix](PHASE_2_ACCEPTANCE_MATRIX.md) and
[technical baseline](PHASE_2_TECHNICAL_BASELINE.md) govern completion. The final
fields below are bound to actual accepted P210 evidence and explicit ROOT-reviewed summaries; prior scoped histories remain unchanged.

## 1. Source identity and delivery record

| Field | Recorded value |
| --- | --- |
| Actual main at start of this assignment's Stage A | c7b0b7090f60354f0f1f7a3dabdb0030b6f87038, recorded in the Phase 1 audit corrections |
| Corrected immutable Phase 1 evidence source | 99df47b6633791c3900a52f46f56d48be922a436 |
| Accepted P207 implementation source | 03c3c5b0b8182aadaaf48ec29131ab7fe83095a7 |
| Historical P207 closure commit | 7d3a5f59f30fe934953c7e3ab27d8e6ae48c1ca1; retained delivery history |
| Accepted P208 / P209 scoped sources | bc21516c51aa5090031b39ea56ded3ca94d657d8 / d70ab445de38aee255275880c5ef7a105ebbb939 |
| Accepted S33 source and P209 closure | bd47329cca5c1409486fff40d48e92163ab4a8af / edc1a51f5c3497e6722e294fab43955ce8ae4451 |
| Prior P210 implementation source and tree | 03105f4d36b0457600dfc5ab6fb13b0308820027 / 6734b1d2b7d4b5db9bdbbf5b4c2145bc797ba61e |
| Current corrected source V and tree | 3998426aa7e7614e421518efd01b08188e194100 / ff5522eb438a30cfa88aad6bf4e2853fb85ef3a0 |
| Accepted final Phase 2 release and closure D | V is the accepted final Phase 2 source; D is the later documentation delivery |
| V delivery checkout and remote state | New source-delivery record binds parent 03105f4, clean main, pushed main and refreshed origin/main at V |
| Main branch evidence | The final source-main-lineage.json observation records a non-shallow repository with only main locally; V delivery binds the remote main SHA. |
| Ordered actual delivery commits through V | 46 retained commit/push pairs; ordered full SHAs below |
| Direct and fast-forward main delivery evidence | Through-V retained proof below; D delivery is recorded separately after pushing |

D denotes this later documentation commit. Its SHA and fast-forward delivery are recorded separately after pushing.

The [Stage A audit](PHASE_1_AUDIT_CORRECTIONS.md) records this assignment's start.
The earlier foundation start in the [Phase 1 implementation report](PHASE_1_IMPLEMENTATION_REPORT.md)
is a different boundary. The retained topic map binds 44 observed delivery pairs
through edc1a51: the existing 35-pair and seven-pair extracts and their historical
ROOT reviews, followed by the actual S33 source and closure delivery records.
The prior `p210-source-delivery-01/delivery.json` adds pair 45, edc1a51 to 03105f4:
`git commit -m "feat(operations): complete Phase 2 hardening implementation"`
reported `[main 03105f4]`; `git push --porcelain origin HEAD:refs/heads/main`
reported the ordinary `edc1a51..03105f4` update; both exited 0. Its final refs
show main, origin/main and origin/HEAD at 03105f4. The retained internal refs/codex
capture is not a branch. These observations establish the inspected boundaries,
not a claim about unobserved transient refs or a future delivery D.


The new `p210-os-fix-source-delivery-01/delivery.json` adds pair 46,
03105f4 to V. The actual
`git commit -m "fix(security): pin database image OS security updates"`
reported `[main 3998426]` with seven changed files; the explicit parent and
committed-tree records match section 1. The subsequent command was:

```bash
git push --porcelain origin HEAD:refs/heads/main
```

It recorded the ordinary `03105f4..3998426` update, exit 0. Clean post-commit status, remote main and
refreshed origin/main at V are retained. No later acceptance or delivery D is
inferred from this actual source-fix delivery.

The ordered delivered commits from c7b0b709 through V are:

1. `99df47b6633791c3900a52f46f56d48be922a436`
2. `1d185febe17c3e8741dfd56c024da054e7bf38a3`
3. `b663a3cf083516160f018c4866be6b8ea21f0c58`
4. `6dde264e865dd5fdfc8e3116a35b1661a48a68fd`
5. `ecc75154397c8f9d7532fa2df8576846b60bae7c`
6. `c9aeebe8e0481fee6f7d897bd3fb89b3a7fdfaed`
7. `5fa43b2fe1f671b9e2734c70fd0c13480ae08555`
8. `f78c9d2917c3ce8c93f9ae5631390c59616abc82`
9. `c9adba4f427cdbee1ebce7fbbb9425d1061c8146`
10. `e258f54bb03a958f7847b310ee882b7f4a54686f`
11. `05d01c7a9a9cb6cc3f351c3adbed2036f02b94a9`
12. `abb655eb7f0e1335e4c74040cc96ad1a0f83bbeb`
13. `6a2074141d9c7bdd8aa64e1710777d153c4996f5`
14. `92dc0e445809737a766c7f211c5dfef42adf9f6a`
15. `a573343bf2a17aa01642e9764d97eb74f77fcd27`
16. `f37e8de843419288bc7e4b7531de6cc9d4c9cedc`
17. `4aa1e235a5abe0432ca00060d2b35ce31fb705fe`
18. `2a7c89a9b8c37d97006dafbbe97a44eec37b3fe0`
19. `c19933ff6ce824b857b591cd6a4e4f7b73d226fd`
20. `0ebbfa29253f418084835335eb2ee66f1b898679`
21. `b9b75ec54fe94fdcec627d8e31ca94700ccb08ad`
22. `b2b0466cc150ac14cd3893fd823a7b84b084d7d9`
23. `c84ecee2278a1f32d41c2e9640692001fae6fcf8`
24. `7b102663ea193b4668924a7252180731954f4b00`
25. `5ff85b4436ec9be886639e6e2cf0c722fc0c4a73`
26. `8636ab4be5a3801d126246cc66322355b65b69b4`
27. `e145229491cddff37c58eb86eef7cf120b1956c7`
28. `93ce926bce4d3f1f35137dd4ee0b1f14d88fd0bc`
29. `a2f2e3c533e6079766beac90f3f97279c622de40`
30. `9e39767b408b38203d88d6e5b41bf0bc1265adfb`
31. `2cdb4095eabcf0db92370becfa9952004583e776`
32. `0d7aa9bd4eccb987f2485c35f57b809ddedd2900`
33. `0df988ce4fb785c44d28868d9936d2dbae18c99d`
34. `03c3c5b0b8182aadaaf48ec29131ab7fe83095a7`
35. `7d3a5f59f30fe934953c7e3ab27d8e6ae48c1ca1`
36. `ff884065e896209563d1966865602e73b3622fd6`
37. `7201b5396c14ece3055710749ead3807b4e5652a`
38. `57eba18bff82051124b09f0970f7ec5494a84d61`
39. `bc21516c51aa5090031b39ea56ded3ca94d657d8`
40. `9505e2650aadedd504a0a94117c018b0b7ed153f`
41. `aa5a5f118ae41d334818621d16330333d5347c46`
42. `d70ab445de38aee255275880c5ef7a105ebbb939`
43. `bd47329cca5c1409486fff40d48e92163ab4a8af`
44. `edc1a51f5c3497e6722e294fab43955ce8ae4451`
45. `03105f4d36b0457600dfc5ab6fb13b0308820027`
46. `3998426aa7e7614e421518efd01b08188e194100`

Full raw commands and outputs remain external under the companion rebase-map's
references; this report does not duplicate bulky logs. D's actual delivery and
final branch/clean-state proof are recorded separately after pushing, without
changing these historical pairs. No unobserved `git pull --ff-only` command is inferred.

The [changelog](../../CHANGELOG.md) declares semantic versioning and
[ADR-0008](../adr/ADR-0008-THREE-PHASE-DELIVERY.md) assigns Phase 2 release 0.2.0.
V contains lockstep 0.2.0 metadata in 13 Python and four JavaScript manifests,
the internal Python pins, runtime/version exports, uv.lock and OpenAPI info.version.
ROOT selected that cohort under the owner's Phase 2 release request; an explicit
owner choice of internal package versioning is not claimed. The Docker guide's
four application-image example tags are also 0.2.0. Working and precommit generated
checks passed, with their own source snapshots retained in section 11. Final immutable validation passed generation-drift checks and Python, web and six-image builds.
API route v1, stable MCP/widget identities, calculation
methods, report renderer profiles and persisted schema/codec versions remain
independent contracts; historical bytes must not be relabelled.

## 2. Stage A corrections and historical revalidation

The authoritative correction narrative and exact selectors are in the
[Phase 1 audit corrections](PHASE_1_AUDIT_CORRECTIONS.md), with retained runtime
evidence in [phase-1-audit-99df47b.json](evidence/phase-1-audit-99df47b.json).
The following results belong to 99df47b; they are not final Phase 2 receipts.

### F-01: hard collection quotas

The collection writer checks remaining owner capacity under its existing
transaction-scoped advisory lock before consuming the iterable, including the
first owner collection. It reads at most remaining member capacity plus one.
A savepoint rolls back all newly inserted rows, including earlier flushed
batches, when capacity is exceeded even if the caller catches the error.
Overflow publishes neither a cursor nor a fabricated exact total. Successful
collections preserve their exact scope, filters, ordering, immutable membership,
source binding and signed expiry.

Expired snapshots do not consume active quota even when bounded cleanup skips
locked rows. Retained snapshots remain subject to the existing physical cleanup
and authorization rules.

Meaningful tests include
[application capacity](../../tests/unit/application/test_collection_capacity.py),
[real PostgreSQL collections](../../tests/integration/test_collection_query_snapshots.py)
and the hard-capacity API/MCP case in
[PostgreSQL parity](../../tests/integration/test_api_mcp_postgres_parity.py).
The accepted record covers capacity three versus overflow four, rollback after
a 1,000-member inserted batch, only one remaining member, concurrent first
requests against both quotas, and an expired locked cleanup backlog. These
complement the large stable collections and activity paging cases; a mocked
registry test does not substitute for this database quota proof.

### F-02: minimize historical export metadata

After validation, ingestion retains only reportId, status, timeFrom, timeTo,
dataIncluded booleans and downloadAvailable. The canonical fingerprint derives
from that selected metadata. Rotating a download URL does not create a semantic
revision. Unknown diagnostic fields are discarded; ingestion neither follows
the URL nor creates a broker export.

Migration [20260907_0008](../../migrations/versions/20260907_0008_minimize_export_metadata.py),
following 0007, removes the two historical top-level download-link spellings
only from object-shaped historical_exports metadata. It is null-safe,
idempotent and preserves unrelated fields. It does not copy the URL elsewhere;
downgrade cannot recreate removed sensitive bytes. A retained legacy opaque
fingerprint may produce one selected-metadata revision on first replay, after
which URL-only rotation produces none. Exports are not economic activity.

The audit's synthetic in-memory canary was absent from the inspected 41,822
application files, five service logs, 121 rows across 31 tables, and exercised
API/MCP, rendered web and metrics surfaces. Generated/browser artifacts were
also covered by the retained audit. This is historical scoped proof.
Final V validation also
passed the source URL/SSRF and privacy regressions. The final retained-artifact
canary gate scanned 4,924 files / 298,772,622 bytes, including 25 bounded TAR
archives and 4,899 ordinary scan arguments. It binds current source, generated
contracts/builds, browser outputs, retained test fixtures, coverage, security and
runtime outputs; hashes stayed unchanged during the scan. Synthetic export-URL
parts and held runtime authorization canaries are separate checks. Historical
negative-test fixtures are not silently relabelled as clean output. PDF raw-byte
scanning is complemented by semantic tests and the scoped page review. No canary
value or private URL is reproduced here. Thirty-three fixed-/tmp captures were
preserved byte-for-byte during F; the preservation receipt distinguishes actual
browser-write paths, capture times and copy times from collector input paths.
A separate postvisual canary scan also passed over 65 new files / 3,973,146 bytes, including all supplemental probe outputs, six PDF page renders and completed ROOT/visual reviews. Later closure documents receive separate staged scans.

### Recorded command and result matrix

| Historical validation at 99df47b | Recorded outcome |
| --- | --- |
| make bootstrap validate | Passed, clean exit |
| python3 scripts/validate_repository.py | 62 required files; exact ten broker GET capabilities |
| Isolated Python suite | 371 tests, including 33 security tests |
| PostgreSQL/migration integration | 73 tests |
| Web unit suite | 22 tests |
| make test-coverage, branch measurement enabled | 85% combined coverage; not a separately calculated branch-only percentage |
| make test-e2e, retries disabled | 32 synthetic and six API-backed cases |
| make format-check lint typecheck; make generated-check | Passed; no generated contract drift |
| make build container-build | Python/web distributions and six runtime images passed |
| make docs-check security-check | Documentation, Semgrep, source secrets, pip-audit and production pnpm audit passed |
| Export artifact CLI, nine required paths | Passed across retained/generated/browser surfaces |
| Gitleaks 8.30.1 history; Trivy 0.74.0 source and six immutable images | Recorded policy pass |
| Compose replay, migration, worker recovery and seven-service restart | Recorded pass |

The exact commands, logs, scanner versions and qualification of those outcomes
remain in the audit report. A HIGH/CRITICAL scan with the recorded ignore-unfixed
policy is not a claim that no vulnerabilities exist.

The accepted historical GitHub Actions runs are Quality **34121465069**
(successful attempt 2; attempt 1's checkout/DNS failure remains history),
Security **34121465107** and Documentation **34121465071**. These IDs were read
from the retained audit, not queried anew. Later owner instructions temporarily
defer Actions. Final Phase 2 CI is **OWNER-DEFERRED / UNVERIFIED**, not passed.

## 3. Architecture and package implementation

The [technical baseline](PHASE_2_TECHNICAL_BASELINE.md) separates domain
invariants and deterministic analytics from application authorization and
orchestration, PostgreSQL persistence, worker execution and API/MCP/web adapters.
Financial inputs and outputs retain canonical decimal strings, explicit
currency, UTC timestamps, missingness, provenance and quality. Ordinary
precision is local Decimal80 with Q18 HALF_EVEN boundaries; target and closed
X-ray precision exceptions are documented, not global context changes.

PostgreSQL holds durable private state. Redis carries replaceable queue/cache
state. Reference-data access is isolated from the Trading 212 connector.
API, web, MCP, reports and alerts consume canonical persisted calculations;
presentation does not recalculate financial truth.

| Package | Implementation and acceptance boundary |
| --- | --- |
| P2-01 | [Virtual targets](P2_01_VIRTUAL_TARGETS.md): account/private-template portfolios, immutable effective target versions, hierarchy, mappings, constraints, normalization, comparison and audit. Accepted historical source ecc75154397c8f9d7532fa2df8576846b60bae7c. |
| P2-02 | [Contribution planning](P2_02_CONTRIBUTION_PLANNING.md): actual/drift projections, bounded deterministic optimizer, durable manual contribution plans and explanation. Accepted f78c9d2917c3ce8c93f9ae5631390c59616abc82. |
| P2-03 | [Reference sources](P2_03_REFERENCE_SOURCES.md): licensed dated price/action, FX, benchmark, classification and ETF source contracts, ingestion/replay and retention. Accepted e258f54bb03a958f7847b310ee882b7f4a54686f. |
| P2-04 | [Historical intelligence](P2_04_HISTORICAL_INTELLIGENCE.md): performance, benchmarks, attribution, dividend/income and cash-flow calculations with PIT/restated replay. Accepted 2a7c89a9b8c37d97006dafbbe97a44eec37b3fe0. |
| P2-05 | [Portfolio X-ray](P2_05_PORTFOLIO_XRAY.md): bounded effective exposures, classification, look-through and selected ETF overlap. Accepted 7b102663ea193b4668924a7252180731954f4b00. |
| P2-06 | [Reports and exports](P2_06_REPORTS_AND_EXPORTS.md): private durable source captures, ten report types, four formats and canonical export datasets. Accepted 9e39767b408b38203d88d6e5b41bf0bc1265adfb. |
| P2-07 | [Alerts and rules](P2_07_ALERTS_AND_RULES.md): immutable scheduled evaluation, eligibility, deduplication, lifecycle, delivery and alert export. Accepted 03c3c5b0b8182aadaaf48ec29131ab7fe83095a7. |
| P2-08 | [Analytical web experience](P2_08_ANALYTICAL_WEB_EXPERIENCE.md): account-safe navigation, exact-value presentation, accessible charts/tables, intelligence quality and explicitly pinned company projections. Scoped local acceptance at bc21516c51aa5090031b39ea56ded3ca94d657d8 for WEB001/002; final release regressions remained required at that package boundary. |
| P2-09 | [MCP registry](../integrations/PHASE_2_MCP_TOOL_REGISTRY.md): exact registry compatibility, strict tools, durable command boundaries and five widget resources. MCP001/002 retain accepted evidence at d70ab44; the distinct real-owner/exact-scope S33 supplement is accepted at bd47329. Closure at edc1a51 completes P209; final V regressions remained required at that package boundary. |
| P2-10 | [Final hardening](PHASE_2_PORTFOLIO_INTELLIGENCE.md): remaining HTTP authorization, query/resource/retention checks, operations, telemetry and 0.2.0 metadata are implemented at V. The original 49 production/package/operations plus 23 test/helper payloads retain their preparation provenance; eight corrected S33 files were inherited, and documented integration corrections are included. V additionally contains the seven PostgreSQL/four Redis direct OS fix pins and prior failure/status evidence. Final same-source full/security/runtime/visual evidence and local acceptance are bound by [final P210 local evidence](evidence/phase-2-p2-10-3998426.json) at 3998426aa7e7614e421518efd01b08188e194100. CI remains owner-deferred; this row does not claim delivery of D. |

Historical package receipts establish their stated package boundaries only.
The accepted P208 ledger records 8/10 packages, 21/29 local rows and 30/40
scenarios. These are its historical scoped totals, not final release totals or
P209 acceptance. The subsequent accepted P209/S33 closure records 9/10 packages
(90%), 23/29 local rows and 31/40 scenarios; S33 is complete there and
S32/S34/S38/S39 remain partial. Those are historical acceptance totals. Final P210 acceptance binds the mapped
regressions at V and completes 10/10 packages, 29/29 local rows and 40/40 scenarios.

## 4. Persistence, API and generated contracts

The [data model](../architecture/PHASE_2_DATA_MODEL.md) describes private
ownership and account bindings, normalized entities and bounded typed payloads.
Principal families are virtual portfolios/target versions and nodes; drift and
planning inputs/results; provider licenses, source records and benchmark
definitions; historical inputs, immutable source references and calculation
runs; X-ray/overlap records; report requests, captures, sections and artifacts;
and alert rule versions, evaluations, events, lifecycle and delivery records.
Composite ownership/account constraints and current grants apply at access
boundaries; an opaque UUID alone is not authorization.

| Migration sequence | Scope |
| --- | --- |
| 20260907_0008 | Stage A export metadata minimization |
| 20260907_0009 | Virtual targets |
| 20260907_0010 | Contribution planning |
| 20260907_0011 | Market sources |
| 20260907_0012 | Historical intelligence |
| 20260909_0013 | X-ray intelligence |
| 20260909_0014 | Private reports |
| 20260910_0015 | Alerts |
| 20260911_0016 | Integrated P208 intelligence-quality selection binding |

The final disposable runtime database applied migration head 20260911_0016.
Final F passed 12 migration tests, PostgreSQL compatibility and replay checks;
all three collection binding constraints remained present. Quality selections use their narrowly typed
stable collection binding; they do not use a PortfolioSnapshot foreign key to
represent an analytical run. All three collection binding constraints must
survive final model/migration composition.
Final V passed that composition check. Restart preserved all 212 retained public tables; no actual backup restoration is claimed.

The detailed endpoint inventory is the
[API service contract](../architecture/PHASE_2_API_SERVICE_CONTRACTS.md) and
[generated OpenAPI](../../packages/api-contracts/openapi/phase1-v1.json):
targets/versions, actual/drift/plans, reference sources and benchmarks,
historical families, X-ray/overlap, reports/exports, and alerts.
The P208 fixed GET /api/v1/accounts/{account_id}/intelligence-data-quality
accepts only analytics_kind, limit and cursor. Its nine canonical kinds expose a closed 75-key metric catalogue
and a bounded page of visible source references. Portfolio and analytics grants
are baseline requirements. Income/cash_flow require activity before family
lookup; actual/drift require targets similarly. Target-bearing baseline runs
are filtered before selection without targets. Safe baseline summaries remain
usable without blanket activity access. Physical current-license and retention
checks precede result-only decoding; protected counts and IDs are not exposed.

Generated consumers live in
[api-contracts](../../packages/api-contracts/src/index.ts), including bounded
target, planning, source, historical, X-ray, report and alert clients. Quality
uses the existing SourceApiClient with sources/intelligence-quality tags and
Intelligence-prefixed public schemas. The OpenAPI filename phase1-v1 and
/api/v1 are retained compatibility identifiers, not release numbers.

The final api-source-inventory.json contains 95 unique operations on 87 paths: 68 GET,
25 POST and two PATCH application operations. These are application interfaces,
not broker-write permissions. The OpenAPI 0.2.0 inventory and generated TypeScript
client are bound to V's source blobs and successful immutable generation-drift
checks. Each method/path/operation identity is retained in the source inventory.

## 5. Providers, benchmarks, FX and ETF data

The [provider contracts](../integrations/PHASE_2_PROVIDER_CONTRACTS.md) keep
market/reference data outside the broker credential and capability boundary.
Typed ports support price bars, corporate actions, FX, benchmark histories and
definitions, instrument classifications and dated ETF holdings. Source
identity, observation/effective times, canonical content, quality, coverage,
licensing and retention remain explicit.

Raw prices, split-adjusted series and total-return series are different inputs.
Provider benchmark levels and composite benchmark wealth are different
calculation paths. Missing opening history or FX is not inferred from today's
holdings or silently converted to zero. ETF holdings and classification evidence
must be dated and licensed for the requested use. Current storage/display/report
permissions and physical expiry are checked before decoding or copying payloads;
immutable calculation identity does not override a later license revocation.

Accepted source work uses concrete replay providers. It does not establish
configured commercial credentials or a production external reference HTTP
adapter. Provider-enabled acceptance requires actual configured origin/license
evidence. Otherwise its result is explicitly unavailable with a stated coverage
limitation, not a synthetic pass rebranded as provider evidence.

## 6. Financial methods and reference evidence

### Contribution planning

[ADR-0011](../adr/ADR-0011-DETERMINISTIC-CONTRIBUTION-OPTIMIZER.md) defines
contribution_weighted_drift_v1. The full denominator is existing value plus the
new contribution; cash and unclassified value remain included, and existing
cash is not silently spent. Nonnegative allocations plus residual cash conserve
the contribution. The global objective is weighted squared post-contribution
drift over nonoverlapping leaf, cash and unclassified components. Ties use the
specified residual and canonical node ordering; hierarchical mode uses its
lexicographic frontiers. Restrictions never shrink the denominator.

Independent validation checks the returned plan against its constraints.
Search budgets are bounded: a feasible incumbent after exhaustion of a search
budget is feasible_nonoptimal, not an asserted optimum; no incumbent at a budget
boundary is unavailable, not a fabricated infeasibility proof. Accepted
[P202 reference/property evidence](P2_02_CONTRIBUTION_PLANNING.md) includes
independent rational reference cases. Final V passed the reference/property, contract, API/MCP and affected PostgreSQL/browser regressions. Runtime replay retained the plan content digest and canonical API/MCP response.
A plan contains manual contribution observations and never
executes an order.

### Historical performance and attribution

The [methods](../analytics/PHASE_2_METHODS.md) and
[P204 evidence](P2_04_HISTORICAL_INTELLIGENCE.md) cover opening/history
requirements, external cash flows, benchmark alignment, income and attribution
with disclosed residuals. PIT includes only information known at its cutoff;
restated replay is separately identified. P207's attested revision correction
preserves raw observation timestamps and validates immutable proof edges before
projection. Late bridges and forward economic dates affect eligibility without
rewriting raw facts or broadening proof-free/native behavior.

Final V passed the historical reference, revision/cutoff, reconciliation,
provider-failure and canonical consumer regressions. The final scenario map
binds each shared consumer predicate to its selected test and browser evidence.
Runtime restart retained the historical input/run state and exact API/MCP data;
report and browser tests separately assert their captured canonical values.
Synthetic fixtures establish these local behaviors, not the completeness of an
unavailable real provider's opening history.

### Portfolio X-ray and overlap

[ADR-0017](../adr/ADR-0017-DECIMAL256-EXACT-XRAY.md) specifies the closed
Decimal256 exact-state calculation and Q18 public boundary. Real held roots
(including cash and zero-valued roots) share the bounded 10,000-path budget;
look-through is limited to four fund edges. Representative identities derive
from real held roots. Ambiguous mappings remain unresolved, dated classification
and snapshot FX stay bound, and unavailable versus incomplete lower-bound
results remain distinct. Exact zero and a positive subquantum amount are not
interchangeable.

[P205](P2_05_PORTFOLIO_XRAY.md) records effective exposure, overlap and replay
evidence. Overlap is bounded to a selected group of at most 32 funds/496 pairs,
not an unbounded persisted all-pairs graph. P208 optionally projects an explicitly
pinned X-ray company view for the same account/snapshot basis. It is non-additive
whole-portfolio information, not company target drift or a post-optimizer
prediction. Its reference-order normalization is limited to the four provenance
ID tuples and preserves multiplicity, all metric fields and stored canonical
bytes. Company HTTP/MCP pin parity and X-ray report path/provenance corrections
are present in the accepted P208 source. Earlier failed candidates remain
historical. P208 does not close all of S34.
Final V separately passed company, report-path/provenance, license-revocation and same-input consumer regressions and closes S34 under its final map. Runtime exact API/MCP X-ray replay and browser source/path assertions supplement the controlled fixture values.

## 7. Private reports, exports and alerts

[P206](P2_06_REPORTS_AND_EXPORTS.md) captures private immutable source manifests
and typed sections for ten report types and four output formats. Renderers
consume those sections; they do not become independent financial calculators.
Artifact byte hashes and canonical semantic digests have different meanings.
No PDF byte-identity, PDF/UA or uninspected-page claim is made. Seven backed
export datasets were followed by the P207 alerts dataset. Access, download,
retry, expiry and deletion must recheck the current private boundary, including
copied source licenses and the shortest applicable payload retention.

P208's optional company sections preserve the captured basis across the typed
report formats PDF/CSV/JSON/XLSX; standalone exports use CSV/JSON/XLSX.
The earlier company/report failures and their corrections remain in P208's
historical record. P209 also retains the aa5a5f1 full-gate PDF record-adjacency
failure and the d70ab44 test correction for records split across PDF pages;
the correction does not change renderer output or establish a final PDF review. Scoped web acceptance is not a final P210 PDF visual review
or a substitute for final-source report/export regressions.
Final V separately passed canonical parity, permission rechecks, expiry/deletion and durable worker recovery. Equivalent-job manifests and CSV/JSON/XLSX bytes matched; PDF bytes differed between equivalent jobs. The actual authorized 14-page PDF retained the exact inert manifest attachment. ROOT visually reviewed pages 1, 2, 6, 9, 13 and 14: summaries, positions, long identifiers, provenance/hash inventories and rendering disclosures remained readable. This six-page review does not cover every page or claim PDF/UA for the untagged document.

[P207](P2_07_ALERTS_AND_RULES.md) implements 15 rule families/27 metric choices,
immutable evaluations, durable event identity, cooldown/lifecycle and bounded
delivery. These inventory counts are not a claim that runtime exercised every
metric. Proof-backed event eligibility combines economic eligibility, original
known time and necessary proof ancestry knowledge. Retrying an evaluation does
not invent a new event. Acknowledgement, resolution and recovery have distinct
lifecycle semantics; webhook delivery is independently authorized and bounded.

[Accepted P207 evidence](evidence/phase-2-p2-07-03c3c5b.json) covers the exact
eight P207/ALT/S28–S31 requirements at 03c3c5b, including report/alert durable
recovery and the demonstrated Redis-loss path. Its results are historical:
2,352 isolated Python, 338 service-backed, 345 web unit and 100 browser tests,
with 88% combined Python coverage measured with branches enabled. Preserve the
earlier failed-security and failed-browser records and their original sources.
Final V passed
alert lifecycle, authorization, privacy, retention/expiry and backlog regressions.
The actual runtime recovered the same pending alert job/input after Redis queue
loss, with one successful consumer attempt and no manual enqueue or SQL repair.
Web checks distinguish evaluation, acknowledgment, resolution and in-app delivery.
External email/webhook delivery remains unavailable. Earlier failed security and
browser evidence keeps its original source identity.

## 8. Web experience and MCP

The current [P208 implementation document](P2_08_ANALYTICAL_WEB_EXPERIENCE.md)
and [web architecture](../architecture/PHASE_2_WEB_INFORMATION_ARCHITECTURE.md)
map the 18 owner experiences onto these routes:

| Routes | Features |
| --- | --- |
| / | Portfolio overview and account-safe entry |
| /pies and /pies/[portfolioId] | Virtual Pies and target editor |
| /drift | Actual-versus-target and drift explorer |
| /planner and /planner/[planId] | Manual contribution planning and durable result |
| /performance | Performance, benchmarks and attribution |
| /sources/benchmarks/[definitionId] | Benchmark definition/version details |
| /income and /dividends | Income, dividend and cash-flow intelligence |
| /xray | Effective exposure and ETF overlap |
| /reports | Private report generation, results and exports |
| /alerts | Rule management and event history |
| /sources | Reference-data configuration and source status |
| /quality | Baseline intelligence quality and separately authorized reconciliation |
| /settings | Account and application settings |

Account switching masks retained values from the prior account, clears dependent
pins and prevents late command completions replacing newer user intent.
Refresh requests use the fixed authorized adapter; pending is not completed.
Exact text and accessible table alternatives accompany plots. Charts use
presentation coordinates only; canonical decimal values remain available.
P208's scoped acceptance binds actual API-backed desktop/tablet/mobile browser
workflows, native keyboard/focus, reduced motion, canonical values and reviewed
images. Its artifact establishes WEB001/002, not a fresh full Compose restart,
default Compose configuration or PDF visual approval. P210 separately retains
new final-source browser and visual evidence.

The [fixed MCP registry](../integrations/PHASE_2_MCP_TOOL_REGISTRY.md) and
[ADR-0016](../adr/ADR-0016-INTERNAL-MCP-COMMANDS.md) define 25 names:

| Group | Exact names | Annotations |
| --- | --- | --- |
| Original nine | get_account_summary; get_portfolio_snapshot; list_positions; list_recent_transactions; get_dividend_summary; get_direct_allocation; compare_portfolio_snapshots; get_reconciliation_status; get_data_quality_summary | readOnlyHint=true |
| Fourteen added reads | list_virtual_pies; get_virtual_pie; get_actual_vs_target; get_drift_analysis; get_contribution_plan; get_performance_summary; get_benchmark_comparison; get_dividend_intelligence; get_attribution_summary; get_effective_exposure; get_etf_overlap; get_report_status; list_reports; get_alert_summary | readOnlyHint=true |
| Two internal commands | create_contribution_plan; generate_portfolio_report | readOnlyHint=false |

For all 25, destructiveHint=false, idempotentHint=true and openWorldHint=false.
The two commands create private durable planning/report work, never broker
writes. Strict input validation, current scopes, account/resource ownership,
canonical serialization, audit and idempotency need their mapped assertions;
annotations alone prove none of them. Original nine compatibility is preserved.

Five widget URIs use the ui://trading212-portfolio/ prefix:
snapshot-v1.html, contribution-plan-v1.html, performance-comparison-v1.html,
xray-v1.html and report-status-v1.html. P209's integrated hardening and tests
cover strict CSP, hostile/unknown host-state handling, bounded resource state
and native keyboard constraints. The accepted d70 artifact binds its actual
widget/browser observations and reviews. Its retained capture-timing failure
and correction use the next actual same-worker test start as an exclusive wall
boundary; raw Playwright duration is not relabelled as wall elapsed time.
Final V acceptance binds original captures, observed cases and ROOT's scoped
visual review per project. The 33 preserved fixed-/tmp captures have explicit
copy provenance. The original blank desktop benchmark plot is qualified by the
separate production rendering observation described above.
It does not imply a public ChatGPT deployment or real host certification.

The historical P209 semantic map distinguishes spies from
PostgreSQL; its scope is MCP001/002. The separate accepted S33 supplement ran
627 relevant tests in one invocation at bd47329, with zero failures/errors/skips.
It includes the legacy gateway correction that checks exact registered scopes
and the injected authorization clock before canonical service callbacks. Its
real-owner tests are inherited by V. That focused supplement is not a full
make validate run or fresh browser/runtime evidence; final V supplies the separate full-file SDK, real PostgreSQL/API parity, durable-command, audit and browser checks. Its registry inventory binds 25 tools and the inherited exact-scope/clock authorization assertions passed.
The pinned SDK's top-level securitySchemes limitation and _meta compatibility
mirror remain explicit; no public host certification is inferred.

## 9. Exact broker boundary

The fixed [Trading 212 allowlist](../../config/contracts/trading212-read-allowlist.yaml)
contains these ten GET capabilities:

| Capability | Broker path |
| --- | --- |
| account_summary | /equity/account/summary |
| metadata_instruments | /equity/metadata/instruments |
| metadata_exchanges | /equity/metadata/exchanges |
| portfolio_positions | /equity/positions |
| pending_orders | /equity/orders |
| order_detail | /equity/orders/{order_id} |
| historical_orders | /equity/history/orders |
| historical_transactions | /equity/history/transactions |
| historical_dividends | /equity/history/dividends |
| historical_exports | /equity/history/exports |

No broker POST/PUT/PATCH/DELETE or generic request escape is authorized.
Fixed-origin and redirect/URL validation remain part of the boundary. Internal
application POST routes for plans, reports or refresh jobs do not authorize
broker writes. Demo is the default; explicit Live read-only configuration is
not a broker-execution feature. Historical export metadata never follows a
download link.

Final V passed the exact-ten Trading 212 GET allowlist/connector regressions,
negative dispatch tests, provider-call traps and export URL/SSRF checks. Unknown
methods, paths and parameters fail before network dispatch; application API/MCP
commands cannot become broker writes. Manual planning output never submits,
modifies or cancels an order. The final source inventory and actual test evidence
jointly support these boundaries; no real Demo or Live connectivity is claimed.

## 10. Operations, recovery and cleanup

The [operations runbook](../operations/PHASE_2_OPERATIONS.md),
[backup/restore procedure](../operations/BACKUP_RESTORE.md) and existing family
runbooks remain the operator entry points. Seven Compose services and six built
images are the inherited topology; the dispatcher reuses the worker image.
PostgreSQL holds durable requests, outboxes, leases, inputs and results.
Queue publication acknowledgement means publication state, not consumer
completion. Completion requires its durable result/terminal state.

V's operations revision covers recovery/outage, bad source data, benchmark
changes, optimizer/X-ray limitations, report/storage failures, alert backlog,
webhook abuse, credential rotation, artifact deletion, migration and incident
boundaries. Backup/restore uses restricted creation permissions, preserves
failed partial output, restores into a new isolated target and rechecks current
authorization/license/retention before resuming work. These procedures do not
establish measured production backup or RPO/RTO performance.

V integrates the O3 retention and O2 telemetry composition, including:

- Exact-source payload purge in dispatcher cleanup, with the existing cadence,
  row/byte/removal budgets, busy-lock skip and parent-retention semantics. A failed
  owner lock is excluded across families for that participant's current pass so
  later free-owner records remain reachable. No additional service is introduced.
- Bounded non-sensitive job outcomes, queue metadata and engine-scoped SQL timing.
  Failed statements finish observations; disposal removes listeners. Labels
  exclude SQL, parameters, table names, private identities and arbitrary errors.
- Alembic preserves existing application logger eligibility by passing
  disable_existing_loggers=False to fileConfig. The change does not promise
  preservation of every caller handler or logging configuration.

The original 72 preparation hashes remain immutable. The integration notes
separately record inherited S33 changes, the server clock/version merge, four O3
payloads, HTTP strict-query fixture correction, formatting/import/type fixes,
safe identifier composition in the TTL fixture, bounded non-lossy bitmap-plan
assertions and timeless operator wording. migrations/env.py is outside the
original 72. Final ROOT integration approval is separately bound by the accepted P210 artifact's assertion_map/integration_review reference; the source records above remain preparation history.

Queue gauges cap returned matches and expose saturation/stale-sample state;
this does not bound every database scan or establish production capacity.
The collection/keyset test accepts direct index and exact non-lossy bitmap
access with the same bounded row requirement and normal planner settings.
The distinct TTL fixture records global report/alert select plans. Working
observations are retained in section 11; final query plans, timings and fixture
limits must come from the immutable full run.

The final runtime passed a seven-service stop/restart using the same container
IDs and PostgreSQL volume, preserving all 212 retained public tables and exact
API/MCP replay. Refresh14b observed an API-admitted queued run, a published
PostgreSQL outbox, exactly one queued Redis envelope and multiple successful
dispatcher cycles while the worker was stopped. The same worker then completed
the original run once; retry preserved economic table hashes. Consumer delivery
ACK remains null: publisher confirmation and durable completion are the observed
facts. A separate pending alert survived Redis queue loss through durable recovery.
Each service was capped at one CPU, with explicit memory limits. Teardown removed
all seven services, their one network and disposable PostgreSQL volume, then
verified absence. Postacceptance generated-file/build-history cleanup has a
separate receipt after D delivery. No global prune, production capacity, actual
backup restore or real provider credentials are claimed.
Cleanup must use verified task-owned resources and preserve accepted evidence;
there is no claim of production deployment, capacity or live credentials.

## 11. Final verification and all 40 scenarios

The [test strategy](../engineering/PHASE_2_TEST_STRATEGY.md) and
[acceptance matrix](PHASE_2_ACCEPTANCE_MATRIX.md) define the final obligations.
The final table records actual command, source/tree,
result/exit, raw output reference/hash and bounded limitations from accepted evidence and ROOT review. No count may be
inferred from parametrization, a partial log, a test inventory or an earlier
source.

### Retained working and precommit observations

The following are completed observations of working snapshots based on edc1a51,
except the explicitly staged-tree secret scans. Each original receipt retains
its command, source/diff binding, times, exit and raw outputs. These results are
not relabelled as immutable V acceptance and overlapping populations are not
summed. The earlier failed receipts remain failed.

| Retained gate under RESUME/gates | Actual observation | Exit |
| --- | --- | ---: |
| p210-o3-prefix-working-red-01 | Four intended busy-owner assertion failures before the two production corrections; 36.883 s | 1 |
| p210-o3-prefix-working-green-01 | Same four cases passed after the corrections; 40.145 s | 0 |
| p210-retention-focused-working-01 | 28 passed, two logging assertions failed because migration configuration disabled existing loggers; 71.946 s | 1 |
| p210-retention-focused-working-02 | Same 30 tests passed after preserving logger eligibility; assertions unchanged; 73.744 s | 0 |
| p210-static-working-01 | Nine typing errors across three test files; 21.202 s | 2 |
| p210-static-working-02 | Workspace, generated, format, lint, type and docs checks passed after test type/import corrections; 30.432 s | 0 |
| p210-focused-working-01 | 189 passed, one overly restrictive keyset-plan assertion failed, seven missing-output-parent setup errors; 262.249 s | 1 |
| p210-output-fixtures-working-01 | Eleven report/TTL cases passed with the output-parent command corrected; 11.449 s | 0 |
| p210-query-plan-working-02 | One keyset case passed with the same bound applied to the observed exact non-lossy bitmap plan; 2.794 s | 0 |
| p210-precommit-static-01 | Workspace/generated/format/lint/type/docs passed; 29.566 s | 0 |
| p210-precommit-regression-security-build-01 | 2,153 Python unit, 539 web unit, 160 contract, 12 migration and 226 security tests passed in their separate targets, followed by configured security-check and build; 318.756 s | 0 |
| p210-precommit-docs-01 | Workspace/format/docs passed; 15.092 s | 0 |
| p210-precommit-docs-02 | Workspace/format/docs passed after the last documentation adjustment; 14.919 s | 0 |
| p210-precommit-staged-gitleaks-01 | Complete added/changed files from staged tree a143674; zero findings under the configured policy | 0 |
| p210-precommit-staged-gitleaks-02 | Complete added/changed files from staged tree 6734b1d (the prior 03105f4 tree); zero findings under the configured policy | 0 |

The actual regression command was `make test-unit test-contract test-migrations
test-security security-check build`; static used `make check-workspace
generated-check format-check lint typecheck docs-check`. Full argv for every
focused invocation and both staged scanner inputs are retained in the hashed
receipts. A successful staged-file scan is not full-history or six-image evidence.
Earlier S33 fixture/authorization/scanner failures, the P209 PDF/capture failures
and their corrections remain in their unchanged historical artifacts and logs.

### Historical 03105f4 validation, security failure and source correction

The committed [03105f4 failure history](evidence/phase-2-p2-10-03105f4-failed-security.json)
binds the original receipts and logs. Full make validate passed, exit 0, in
7,298.293 seconds, ending 2026-09-12T21:49:44.268160Z with unchanged clean
source. Actual populations were 2,575 isolated coverage tests, 510
service/migration coverage tests, 539 web unit tests and 208 browser cases:
106 synthetic and 102 API cases in 40 raw JSON reports. Standalone invocations
overlap coverage and are not added. The final JUnit covers only the 510-case
service/migration coverage invocation.

Its actual coverage export passed in 5.043 seconds with the retained database
unchanged: lines 45,165/49,152 = 91.888427734375%; branch-only
10,132/13,264 = 76.38721351025332%; combined statement-and-branch
88.59427069982056% (console rounds to 89%). These are prior-source results,
not new-V coverage. Source/history security passed in 36.446 seconds.
The subsequent image gate failed, exit 1, in 8.861 seconds: PostgreSQL
33 package/CVE findings (21 High, 12 Critical), Redis 12 (9 High, 3 Critical).
The other four images passed their configured scans. The original image
failures remain failed; no scanner policy was relaxed.

ROOT observed the WSL restart (boot at 2026-09-13 08:46 UTC) and absence of
all 70 original /tmp captures. The first collector failed with FileNotFoundError
before writing outputs. This is ROOT-observed evidence, not an owner report.
Surviving JSON execution records do not supply the missing visual review.

ROOT's disposable PostgreSQL-base APT diagnostic confirmed fixed versions and
simulated ten upgrades, zero new packages and zero removals. The diagnostic
included three OpenSSL-family packages; the selected direct fix pins are seven
for PostgreSQL and four for Redis. The separate working-tree build passed in
14.706 seconds; the patched two-image scans and six runtime-image
package-manager probes passed in 4.983 seconds. Both working gates recorded
unchanged source during their own invocation. These focused results remain
working-source observations and do not turn the original failure into a pass.

The correction was delivered as pair 46 at current V, covering the two runtime
Dockerfiles, the technical baseline and four history/status files. ROOT's
corrected committed artifact is the provenance authority. At that source-delivery
boundary, final full/security/runtime/visual and closure evidence was still
required; the accepted ledger then remained at 9/10 packages, 23/29 local rows
and 31/40 scenarios. The following observations close that local requirement.

### Actual final observations at V

| Final evidence area | Observed result at V |
| --- | --- |
| Immutable full validation | PASS, 7363.975 seconds; source/tree unchanged |
| Python tests | 2,153 unit, 36 property, 160 contract, 495 first PostgreSQL, 12 migration and 226 security tests passed; overlapping groups are not added |
| Coverage executions | 2,575 isolated and 510 service-backed tests passed |
| Web unit tests | 539 passed across 52 files |
| Coverage | Lines 45,165/49,152 = 91.8884%; branches 10,132/13,264 = 76.3872%; combined 88.5943% |
| Browser validation | 208 passed: 106 demo/widget and 102 API-backed; 40 raw reports; no unexpected, flaky or skipped cases |
| Static/generated/build | Typing, lint, generation drift, Python/web builds and six image builds passed |
| Security | Full-history secrets/source checks and all six immutable image scans passed the retained HIGH/CRITICAL fixed-vulnerability policy; final artifact canary passed |
| Query measurements | Actual keyset query and 22 TTL artifacts / 12 EXPLAINs; normal planner, controlled warm-cache fixtures, no production SLA claim |
| Runtime | PASS, 293.675 seconds; refresh recovery, Redis-loss alert recovery, 212-table restart parity and verified scoped teardown |
| Scenario/acceptance ledger | 40/40 Phase 2 scenarios, 29/29 local rows and 10/10 packages; final review also retains 14 Phase 1 scenarios plus F-01/F-02 |
| GitHub Actions | OWNER-DEFERRED / UNVERIFIED |

The line, branch and combined rates are distinct measurements from the single
retained final coverage JSON export. The finalizer binds actual raw cases,
source selectors, query measurements and ROOT reviews; shared tests are not
misrepresented as separate executions.
The finalizer records 211 cases in its supplied reports: 208 from F plus three strict snapshot-chart cases. The additional production benchmark/attribution case is separate and passed. All 70 original captures received scoped ROOT review; the blank desktop benchmark frame is qualified by the separately viewed production chart, never replaced. The finalizer retains a rounded 89 combined display field; the exact line, branch and combined rates above come from the actual retained JSON.

Current scanner exception policy is the recorded **16 approved / 21 negative**
policy, not the older 9/5 policy. Final acceptance binds its actual
script/config/ignore hashes and observed policy results. Original failure logs,
diagnostics and the immutable accepted P206 evidence bytes remain preserved. A classification
exception does not turn the original failed security run into a pass.

All forty mandatory scenarios need concrete predicates, exact source binding
and actual results. Shared API/DATA/SEC/OPS predicates, all-consumer parity,
the practical 25-tool two-owner matrix, and final S32/S34/S38/S39 obligations
cannot be closed by package-only receipts. S33's historical closure rests on its
separate real PostgreSQL authorization supplement, not adapter output or
widget/spied-service assertions. The final source passed its mapped cases. Its new runtime receipt establishes
final release recovery; earlier receipts retain their original source bindings. CI deferral changes the external
execution requirement only; it does not defer mandatory locally executable P210.

Three immutable assertion-map notes retain preparatory wording after their
explicit ROOT passing-F observation: P2-S02 says "awaiting actual selected-case
results", P2-S07 says "neither a current test pass", and P1-S10 says results
"remain unbound". These quoted clauses describe the source-inspection draft
stage and are superseded by the actual F execution bindings and ROOT approval
in those same entries. The accepted artifact bytes remain unchanged. The
small-domain solver and owner/account fixture scope limits still apply.

## 12. External gates and release boundary

The six separately tracked external predicates cover production hosting/identity/
secret management; real Trading 212 Demo credentials/smoke; public HTTPS/OAuth
MCP and ChatGPT registration; complete real-provider opening history; licensed
market/FX/benchmark/ETF inputs; and actual email/webhook delivery or remote object
storage. Configuration, coverage, availability and permission must be recorded
as actually observed, not supplied by synthetic evidence. Live access remains explicitly configured read-only and is not a new
write-capability or acceptance substitute.

Synthetic providers, local browser hosts and local Compose results have their
stated scope. No production readiness, capacity, provider correctness, full PDF
accessibility or public ChatGPT certification is claimed. GitHub Actions is the
owner-deferred external verification. P209/S33 scoped acceptance remains historical. P210 has final same-source local acceptance at 3998426aa7e7614e421518efd01b08188e194100; the documentation closure and its post-push delivery record are separate.

Phase 3 remains **not started**. ROOT reviewed the final source composition and
scope boundaries, actual same-source gates and the individual acceptance map.
The final evidence source is V; the non-shallow source-main-lineage.json observation and retained
ordered delivery receipts establish main-only development through V.
D denotes this later documentation commit. Its SHA and fast-forward delivery are recorded separately after pushing.
