# Phase 2 Mandatory Scenario Evidence

**Contract status:** Accepted design closure, 2026-09-07

**Implementation acceptance:** In progress; P2-01 and P2-02 complete; 11/40 complete

**P2-01 evidence SHA:** `ecc75154397c8f9d7532fa2df8576846b60bae7c`

**P2-02 evidence SHA:** `f78c9d2917c3ce8c93f9ae5631390c59616abc82`; final Phase 2 release SHA pending

**Authority:** Owner assignment, Phase 2 execution manifest and acceptance matrix

All forty owner-required scenarios are preserved below. Each row defines the
required executable predicate; pending rows remain requirements without claimed
execution. P2-S01 through P2-S11 have exact tests and retained evidence. Phase 1 acceptance at
`99df47b6633791c3900a52f46f56d48be922a436` is prerequisite evidence only.

## Mandatory predicates

| ID | Owner-required outcome | Package | Required executable/retained evidence | Exact test nodes / evidence SHA | State |
|---|---|---|---|---|---|
| P2-S01 | Create a hierarchical virtual Pie with cash and holding targets. | P2-01 | PostgreSQL/API hierarchy with cash, nested groups and holding targets; persist/reload canonical order and owner/account scope. | `tests/integration/test_virtual_targets.py::test_constraint_exclusion_roundtrip_and_invalid_relational_input_rolls_back`; [full assertion map and exact-SHA results](evidence/phase-2-p2-01-ecc7515.json) | `complete` |
| P2-S02 | Publish target version V1 and prove it is immutable. | P2-01 | Publish V1; reject update/delete through public commands and persistence constraints; assert content/hash unchanged. | `tests/integration/test_virtual_targets.py::test_normalize_publish_clone_and_database_immutability`; [full assertion map and exact-SHA results](evidence/phase-2-p2-01-ecc7515.json) | `complete` |
| P2-S03 | Publish V2 and compare it deterministically with V1. | P2-01 | Publish changed V2 with precondition; compare stable identifiers/weights and effective versions in both directions. | `tests/integration/test_virtual_targets.py::test_published_version_comparison_is_exact_bidirectional_and_restart_stable`; [full assertion map and exact-SHA results](evidence/phase-2-p2-01-ecc7515.json) | `complete` |
| P2-S04 | Reject invalid target sums and contradictory constraints. | P2-01 | Exact-sum tolerance boundaries, negative/overfull weights, cycles, duplicate nodes and conflicting constraints fail atomically. | `tests/unit/domain/test_targets.py::test_ancestor_funding_and_post_weight_conflicts_and_exclusions`; [full assertion map and exact-SHA results](evidence/phase-2-p2-01-ecc7515.json) | `complete` |
| P2-S05 | Preserve unresolved instrument mappings explicitly. | P2-01 | Unresolved listing/entity fixtures retain unresolved state, coverage/warnings and cannot become invented mappings. | `tests/integration/test_virtual_targets.py::test_unresolved_mapping_is_explicit_and_publishable_with_warning`; [full assertion map and exact-SHA results](evidence/phase-2-p2-01-ecc7515.json) | `complete` |
| P2-S06 | Calculate actual-versus-target drift from an immutable portfolio snapshot. | P2-02 | Hand-calculated cash/group/holding drift references use explicit immutable snapshot and target version; later mutations do not alter result. | `tests/unit/analytics/test_planning.py::test_nonzero_group_holding_cash_drift_matches_independent_reference`; [full assertion map and exact-SHA results](evidence/phase-2-p2-02-f78c9d2.json) | `complete` |
| P2-S07 | Produce a no-sale contribution plan that conserves the contribution exactly. | P2-02 | Decimal property and reference cases prove non-negative allocations, no sales and exact contribution = allocations + residual. | `tests/property/test_planning_properties.py::test_discrete_global_optimum_matches_independent_rational_enumeration`; [full assertion map and exact-SHA results](evidence/phase-2-p2-02-f78c9d2.json) | `complete` |
| P2-S08 | Obey minimum allocations, increments, exclusions, and maximum weights. | P2-02 | Reference/exhaustive small constrained cases and randomized properties cover minimums, increments, eligibility, exclusions, hierarchy and maximum weights. | `tests/property/test_planning_properties.py::test_constrained_hierarchy_matches_independent_rational_exhaustion`; [full assertion map and exact-SHA results](evidence/phase-2-p2-02-f78c9d2.json) | `complete` |
| P2-S09 | Return a deterministic residual-cash amount. | P2-02 | Ties, non-divisible contributions and cash-reserve boundaries yield identical exact residual cash and stable line order. | `tests/property/test_planning_properties.py::test_permutations_preserve_hash_and_result_and_exact_conservation`; [full assertion map and exact-SHA results](evidence/phase-2-p2-02-f78c9d2.json) | `complete` |
| P2-S10 | Return a structured infeasibility explanation for impossible constraints. | P2-02 | Impossible hard constraints produce stable conflict codes/explanations without a fabricated feasible plan or hidden relaxation. | `tests/unit/analytics/test_planning.py::test_infeasibility_proof_names_only_supporting_constraints`; [full assertion map and exact-SHA results](evidence/phase-2-p2-02-f78c9d2.json) | `complete` |
| P2-S11 | Produce identical plan output for identical canonical inputs. | P2-02 | Repeated and concurrent canonical requests preserve byte-equivalent plan data and semantic identity; operational timestamps/IDs are tested separately. | `tests/integration/test_planning_api_postgres.py::test_actual_drift_and_saved_plan_match_mcp_with_real_worker_and_revision_history`; [full assertion map and exact-SHA results](evidence/phase-2-p2-02-f78c9d2.json) | `complete` |
| P2-S12 | Prevent a contribution plan from calling any Trading 212 transport method. | P2-02/P2-09 | Broker transport spy raises on every invocation; successful/invalid/retried plan creation invokes it zero times and creates no order payload. | Not recorded / none | `pending` |
| P2-S13 | Ingest synthetic price, FX, and benchmark data with provenance and gaps. | P2-03 | Deterministic replay providers persist prices, FX and benchmark revisions with provenance, source/retrieval times, licenses and explicit gaps. | Not recorded / none | `pending` |
| P2-S14 | Reject look-ahead FX or post-cutoff market observations. | P2-03/P2-04 | Boundary fixtures reject naive/post-cutoff observations and prevent look-ahead in direct/inverse/triangulated FX and valuation/benchmark selection. | Not recorded / none | `pending` |
| P2-S15 | Align portfolio and benchmark periods/currencies. | P2-04 | Hand-computed portfolio/benchmark calendars, total-return basis and sourced reporting-currency conversion align or return explicit unavailable coverage. | Not recorded / none | `pending` |
| P2-S16 | Keep deposits separate from investment gain. | P2-04 | Deposit/withdrawal fixtures change external flows without fabricating gain; internal buys/sells and transfer legs do not become external flows. | Not recorded / none | `pending` |
| P2-S17 | Reconcile attribution components to total return plus disclosed residual. | P2-04 | Position/group/fees/tax/FX components reconcile to the frozen total metric plus a disclosed Decimal residual and decomposition coverage. | Not recorded / none | `pending` |
| P2-S18 | Degrade performance when valuation, FX, or benchmark coverage is missing. | P2-04 | Missing/stale valuation, FX, benchmark and opening history separately degrade dependent metrics; unrelated metrics retain justified quality. | Not recorded / none | `pending` |
| P2-S19 | Compute dividend summaries across multiple currencies without implicit FX. | P2-04 | Multi-currency dividends retain per-currency totals; missing conversion cannot substitute one, zero or account currency. | Not recorded / none | `pending` |
| P2-S20 | Resolve direct plus ETF indirect exposure without double counting. | P2-05 | Direct holding plus multiple ETF indirect paths aggregate one effective company exposure; fund wrappers and indirect constituents are not added twice. | Not recorded / none | `pending` |
| P2-S21 | Consolidate documented share classes/ADR exposure correctly. | P2-05 | Dated sourced share-class/ADR mappings consolidate economic exposure; ambiguous/unsupported mappings retain unresolved weight and never guess by ticker. | Not recorded / none | `pending` |
| P2-S22 | Report ETF overlap and unresolved constituent weight explicitly. | P2-05 | Reference ETF overlap reconciles common/residual/unresolved weight and exposes exclusions without renormalizing unknown constituents into certainty. | Not recorded / none | `pending` |
| P2-S23 | Degrade X-ray quality for stale constituent snapshots. | P2-05 | Stale/partial ETF constituent snapshots affect coverage/confidence/source dates and effective-quality output at the requested cutoff. | Not recorded / none | `pending` |
| P2-S24 | Generate a deterministic report manifest from canonical inputs. | P2-06 | Identical authorized canonical inputs yield an identical manifest hash and table/chart values; operational PDF metadata is separately disclosed. | Not recorded / none | `pending` |
| P2-S25 | Enforce report owner authorization and expiry. | P2-06 | Other-owner, mismatched-account, expired/deleted/revoked artifacts are denied on every lookup/download; expiry cleanup is bounded and idempotent. | Not recorded / none | `pending` |
| P2-S26 | Prove reports contain no secret or provider signed URL. | P2-06 | Inject synthetic runtime/provider/export-URL component canaries; inspect manifests, rendered PDF text/metadata, CSV/JSON and expanded XLSX parts plus logs/traces. | Not recorded / none | `pending` |
| P2-S27 | Produce safe CSV/JSON/XLSX exports without formula injection. | P2-06 | Adversarial cell prefixes, whitespace/control prefixes and unsafe filenames produce safe CSV/XLSX cell types/escaping and strict typed JSON; no formula executes. | Not recorded / none | `pending` |
| P2-S28 | Evaluate a drift alert once and deduplicate repeated identical evaluations. | P2-07 | Same rule-version/input snapshot/window under repeated/concurrent evaluation creates one event and one delivery intent. | Not recorded / none | `pending` |
| P2-S29 | Enforce cooldown and acknowledgment transitions. | P2-07 | Controlled UTC clock covers cooldown edges and owner-authorized acknowledge/resolve transitions, optimistic concurrency and unchanged historical rule versions. | Not recorded / none | `pending` |
| P2-S30 | Reject webhook destinations resolving to private or metadata addresses. | P2-07 | Local fake DNS/transport tests deny loopback/private/link-local/metadata/reserved IPv4/IPv6, rebinding and redirects before disallowed dispatch. | Not recorded / none | `pending` |
| P2-S31 | Preserve alert and report jobs across worker/dispatcher restart. | P2-06/P2-07 | Atomic enqueue/publication/consumer crash windows, duplicate delivery and worker/dispatcher restart preserve original report/alert jobs and artifacts/events. | Not recorded / none | `pending` |
| P2-S32 | Deny cross-owner API access. | P2-01–09 | Authenticated owner/account cross-products and missing scopes deny all new list/detail/command/download endpoints without existence/secret disclosure. | Not recorded / none | `pending` |
| P2-S33 | Deny cross-owner MCP access. | P2-09 | All 25 tools reject cross-owner/account and missing-scope invocations; invalid IDs and unknown fields fail before unauthorized services or providers run. | Not recorded / none | `pending` |
| P2-S34 | Preserve API, web, MCP, and report canonical value parity. | P2-01–09 | Same owner/account, snapshot/target/source revisions, cutoff/currency/method/parameters produce equal canonical Decimal values across service/API/rendered web/MCP/report. | Not recorded / none | `pending` |
| P2-S35 | Preserve all Phase 1 mandatory scenarios. | P2-10 | Rerun every Phase 1 mandatory predicate including 14a/14b/14c, 2505/>10000 collection traversal, hard-capacity concurrency and export-URL minimization. | Not recorded / none | `pending` |
| P2-S36 | Preserve the exact ten-capability Trading 212 GET-only registry. | P2-03/P2-10 | Registry-count/static architecture checks and transport-spy negatives preserve all ten exact GET templates and reject every unknown method/path/parameter. | Not recorded / none | `pending` |
| P2-S37 | Prove no Phase 2 workflow can place, modify, or cancel a broker order. | P2-10 | Exercise plan/report/alert/provider/web/MCP workflows with sealed broker spies; no place/amend/cancel/Pie/transfer/generic execution API or task is reachable. | Not recorded / none | `pending` |
| P2-S38 | Prove all output states distinguish fresh, stale, partial, unavailable, unreconciled, and failed. | P2-01–10 | Parameterized service/API/web/MCP/report fixtures preserve fresh/stale/partial/unavailable/unreconciled/failed, plus estimated/unsupported when applicable, without zero substitution. | Not recorded / none | `pending` |
| P2-S39 | Prove desktop/mobile accessibility and no horizontal overflow. | P2-08/P2-09 | Desktop/mobile API-backed Playwright and accessibility assertions cover keyboard/focus, labels, text alternatives, reduced motion, errors, 18 experiences and versioned widgets. | Not recorded / none | `pending` |
| P2-S40 | Preserve state through full Compose restart without duplicate economic, plan, report, or alert records. | P2-10 | Observe all services stopped, retain volume identity, restart and compare exact economic/plan/report/alert counts, immutable hashes, parity, queue readiness and no duplicate logical work. | Not recorded / none | `pending` |

## Recording acceptance

`PROJECT_PROGRESS.json` stores machine-readable evidence under
`phases.phase_2.acceptance.evidence`, keyed by work-package, local acceptance,
or scenario ID. Each record contains `sha`, nonempty `test_nodes`, successful
`commands` with `command` and integer `exit_code: 0`, and repository-relative
`artifacts`. At least one JSON artifact in the implementation evidence directory
must bind `source_sha`, the relevant `requirements` IDs, and `result: passed`.
The repository validator checks this consistency and that named test nodes and
artifacts exist; it cannot independently attest that the recorded command ran.
Observed logs and immutable local/CI evidence remain required.

Packages record their implemented scope before proceeding. A scenario shared
with a later package remains pending or in progress until the whole predicate
is proved; partial package evidence cannot mark that shared scenario complete.
Final acceptance reruns and binds every package, row and scenario to one SHA.

For every completed row, replace the unrecorded cell with real repository test
nodes and a committed non-secret evidence record. The record must include:

- exact immutable source SHA and whether the checkout was clean;
- command, relevant environment/tool/image versions, exit status and UTC time;
- scenario inputs by synthetic fixture/input snapshot IDs and method versions;
- observed canonical values/counts/hashes and expected predicate;
- API, MCP, web, report or runtime artifacts needed to prove the predicate;
- local/CI distinction, workflow IDs/attempts and any rerun explanation;
- coverage/quality and external limitations without provider credentials/URLs.

One test may prove multiple rows only when its assertions explicitly cover each
predicate. A broad suite success without identifiable assertions is insufficient.
Parameterized cases must name the relevant parameter IDs. Interface parity must
exercise the adapters; calling one shared function four times is insufficient.
Scenarios 31 and 40 require real local PostgreSQL/Redis and process/container
observations in addition to isolated failure-injection tests.

For scenario 26, raw-byte scanning alone cannot prove absence inside compressed
XLSX or PDF content. Decode supported structures with strict size/member bounds,
fail closed on unreadable/unsupported artifacts and scan extracted logical
content without leaking the canary. Report manifest reproducibility does not
imply byte-identical PDF output unless separately demonstrated.

Scenario 35 preserves distinct Phase 1 restart predicates: atomic API commit
before publication, confirmed publication while the worker is unavailable, and
full-stack retention. None substitutes for another. Stage A hard collection
quotas apply even to an owner's first traversal; export signed URLs remain
unretained and unfetched.

## External evidence boundary

All forty scenarios are locally executable using canonical synthetic fixtures,
replay providers and isolated services. Real Demo/Live connectivity, paid-source
coverage, public OAuth/ChatGPT registration, production restore and external
notification delivery require their separate evidence. A synthetic pass never
changes an external `blocked_external` or `unavailable_explicit` predicate.

The [acceptance matrix](PHASE_2_ACCEPTANCE_MATRIX.md) owns release accounting.
Phase 3 remains `not_started`.

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
