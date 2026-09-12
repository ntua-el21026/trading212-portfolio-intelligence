# Phase 2 Mandatory Scenario Evidence

**Contract status:** Accepted design closure, 2026-09-07

**Implementation acceptance:** In progress; P2-01 through P2-09 locally complete; 31/40 complete; P2-10 not_started; remaining Phase 2 CI deferred by owner

**P2-01 evidence SHA:** `ecc75154397c8f9d7532fa2df8576846b60bae7c`

**P2-02 evidence SHA:** `f78c9d2917c3ce8c93f9ae5631390c59616abc82`

**P2-03 evidence SHA:** `e258f54bb03a958f7847b310ee882b7f4a54686f`

**P2-04 evidence SHA:** `2a7c89a9b8c37d97006dafbbe97a44eec37b3fe0`

**P2-05 evidence SHA:** `7b102663ea193b4668924a7252180731954f4b00`; final Phase 2 release SHA pending

**P2-07 local evidence SHA:** `03c3c5b0b8182aadaaf48ec29131ab7fe83095a7`; [scoped evidence](evidence/phase-2-p2-07-03c3c5b.json); CI deferred, not passed.

**P2-06 local evidence SHA:** `9e39767b408b38203d88d6e5b41bf0bc1265adfb`; GitHub Actions deferred, not passed; final Phase 2 release SHA remains pending. [Evidence](evidence/phase-2-p2-06-9e39767.json).

**Authority:** Owner assignment, Phase 2 execution manifest and acceptance matrix

All forty owner-required scenarios are preserved below. Each row defines the
required executable predicate; pending rows remain requirements without claimed
execution. P2-S01 through P2-S11 and P2-S13 through P2-S27 have exact tests and retained evidence; S24–27 use the recorded local acceptance scope with owner-deferred CI. Phase 1 acceptance at
`99df47b6633791c3900a52f46f56d48be922a436` is prerequisite evidence only.

## Current owner-authorized CI exception

P2-06 has scoped local acceptance at `9e39767b408b38203d88d6e5b41bf0bc1265adfb`. GitHub Actions is deferred by explicit owner instruction; no CI pass is claimed. The complete required local gates, exact source bindings and deferred startup observations are retained in the P206 acceptance evidence. Remaining Phase 2 implementation continues under that recorded deferral until the owner resumes CI verification.

Normal exact-source CI requirements remain the default. This dated exception changes only their current prerequisite status, preserves every required local gate and remains explicitly outstanding for verification after owner resumption.

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
| P2-S13 | Ingest synthetic price, FX, and benchmark data with provenance and gaps. | P2-03 | Deterministic replay providers persist prices, FX and benchmark revisions with provenance, source/retrieval times, licenses and explicit gaps. | `tests/integration/test_sources_postgres.py::test_real_seed_idempotent_and_restarted_public_reads`; [exact-SHA assertion map](evidence/phase-2-p2-03-e258f54.json) | `complete` |
| P2-S14 | Reject look-ahead FX or post-cutoff market observations. | P2-03/P2-04 | Boundary fixtures reject naive/post-cutoff observations and prevent look-ahead in direct/inverse/triangulated FX and valuation/benchmark selection. | `tests/integration/test_historical_postgres.py::test_activity_proofs_reject_future_intervals_and_mutation_of_pinned_runs`; [full assertion map and exact-source evidence](evidence/phase-2-p2-04-2a7c89a.json) | `complete` |
| P2-S15 | Align portfolio and benchmark periods/currencies. | P2-04 | Hand-computed portfolio/benchmark calendars, total-return basis and sourced reporting-currency conversion align or return explicit unavailable coverage. | `tests/integration/test_historical_api_postgres.py::test_available_annual_results_pages_scope_projection_and_live_license_recheck`; [full assertion map and exact-source evidence](evidence/phase-2-p2-04-2a7c89a.json) | `complete` |
| P2-S16 | Keep deposits separate from investment gain. | P2-04 | Deposit/withdrawal fixtures change external flows without fabricating gain; internal buys/sells and transfer legs do not become external flows. | `tests/integration/test_historical_api_postgres.py::test_available_annual_results_pages_scope_projection_and_live_license_recheck`; [full assertion map and exact-source evidence](evidence/phase-2-p2-04-2a7c89a.json) | `complete` |
| P2-S17 | Reconcile attribution components to total return plus disclosed residual. | P2-04 | Position/group/fees/tax/FX components reconcile to the frozen total metric plus a disclosed Decimal residual and decomposition coverage. | `tests/integration/test_historical_api_postgres.py::test_available_annual_results_pages_scope_projection_and_live_license_recheck`; [full assertion map and exact-source evidence](evidence/phase-2-p2-04-2a7c89a.json) | `complete` |
| P2-S18 | Degrade performance when valuation, FX, or benchmark coverage is missing. | P2-04 | Missing/stale valuation, FX, benchmark and opening history separately degrade dependent metrics; unrelated metrics retain justified quality. | `tests/unit/analytics/test_historical.py::test_empty_unconfigured_benchmark_never_creates_an_unbacked_composite`; [full assertion map and exact-source evidence](evidence/phase-2-p2-04-2a7c89a.json) | `complete` |
| P2-S19 | Compute dividend summaries across multiple currencies without implicit FX. | P2-04 | Multi-currency dividends retain per-currency totals; missing conversion cannot substitute one, zero or account currency. | `tests/integration/test_historical_api_postgres.py::test_available_annual_results_pages_scope_projection_and_live_license_recheck`; [full assertion map and exact-source evidence](evidence/phase-2-p2-04-2a7c89a.json) | `complete` |
| P2-S20 | Resolve direct plus ETF indirect exposure without double counting. | P2-05 | Direct holding plus multiple ETF indirect paths aggregate one effective company exposure; fund wrappers and indirect constituents are not added twice. Independently prove Decimal256 exact node/root monetary and unit conservation, canonical zero/post-carry bounds, pending-branch capacity and real position/cash path identity. | `tests/integration/test_xray_reads_postgres.py::test_real_snapshot_values_and_full_path_provenance_survive_new_service`; [full assertion map and exact-source evidence](evidence/phase-2-p2-05-7b10266.json) | `complete` |
| P2-S21 | Consolidate documented share classes/ADR exposure correctly. | P2-05 | Dated sourced share-class/ADR mappings consolidate economic exposure; ambiguous/unsupported mappings retain unresolved weight and never guess by ticker. Preserve original monetary roots, sourced FX and receipt semantics; no listing-currency/issuer inference or representative monetary backfill. | `tests/unit/analytics/test_xray.py::test_receipt_ratio_is_evidence_and_never_multiplies_already_valued_money`; [full assertion map and exact-source evidence](evidence/phase-2-p2-05-7b10266.json) | `complete` |
| P2-S22 | Report ETF overlap and unresolved constituent weight explicitly. | P2-05 | Reference ETF overlap reconciles common/residual/unresolved weight and exposes exclusions without renormalizing unknown constituents into certainty. Lowest real position-root representatives include zero values; incomplete unit bases yield computable lower bounds. Same-run pair projections retain exact summaries across Page/Top/subsets and expire under charged collection ownership. | `tests/integration/test_xray_reads_postgres.py::test_page_size_normalization_and_mcp_top_preserve_run_and_exact_pair`; [full assertion map and exact-source evidence](evidence/phase-2-p2-05-7b10266.json) | `complete` |
| P2-S23 | Degrade X-ray quality for stale constituent snapshots. | P2-05 | Stale/partial ETF constituent snapshots affect coverage/confidence/source dates and effective-quality output at the requested cutoff. Enforce trusted first knowledge/effective cutoff and actual subject/page-chain binding; current license/expiry denial precedes decode/reuse/304 and bounded physical purge. | `tests/unit/analytics/test_xray.py::test_source_warnings_and_confidence_use_pinned_evaluation_time`; [full assertion map and exact-source evidence](evidence/phase-2-p2-05-7b10266.json) | `complete` |
| P2-S24 | Generate a deterministic report manifest from canonical inputs. | P2-06 | Identical authorized canonical inputs yield an identical manifest hash and table/chart values; operational PDF metadata is separately disclosed. | `tests/unit/domain/test_reports.py::test_proof_order_canonicalizes_and_source_changes_change_manifest`; [full exact-source local assertion map](evidence/phase-2-p2-06-9e39767.json); CI deferred by owner | `complete` |
| P2-S25 | Enforce report owner authorization and expiry. | P2-06 | Other-owner, mismatched-account, expired/deleted/revoked artifacts are denied on every lookup/download; expiry cleanup is bounded and idempotent. | `tests/integration/test_report_ttl_postgres.py::test_natural_report_ttl_denies_before_bounded_idempotent_physical_cleanup`; `tests/integration/test_report_postgres.py::test_current_reader_is_independent_of_the_disabled_job_initiator`; [full exact-source local assertion map](evidence/phase-2-p2-06-9e39767.json); CI deferred by owner | `complete` |
| P2-S26 | Prove reports contain no secret or provider signed URL. | P2-06 | Inject synthetic runtime/provider/export-URL component canaries; inspect manifests, rendered PDF text/metadata, CSV/JSON and expanded XLSX parts plus logs/traces. | `tests/integration/test_report_privacy_postgres.py::test_four_actual_formats_and_audits_exclude_private_source_and_grant_canaries`; [full exact-source local assertion map](evidence/phase-2-p2-06-9e39767.json); CI deferred by owner | `complete` |
| P2-S27 | Produce safe CSV/JSON/XLSX exports without formula injection. | P2-06 | Adversarial cell prefixes, whitespace/control prefixes and unsafe filenames produce safe CSV/XLSX cell types/escaping and strict typed JSON; no formula executes. | `tests/unit/worker/test_report_text.py::test_formula_initiators_are_neutralized_without_dropping_original_text`; `tests/unit/worker/test_private_report_renderers.py::test_xlsx_contains_only_explicit_text_without_formulas_or_external_links`; [full exact-source local assertion map](evidence/phase-2-p2-06-9e39767.json); CI deferred by owner | `complete` |
| P2-S28 | Evaluate a drift alert once and deduplicate repeated identical evaluations. | P2-07 | Same rule-version/input snapshot/window under repeated/concurrent evaluation creates one event and one delivery intent. | [P207 local evidence](evidence/phase-2-p2-07-03c3c5b.json); `tests/integration/test_alert_drift_dedup_postgres.py::test_actual_target_drift_slot_deduplicates_concurrent_and_restarted_consumers`; source selector mapped to actual full-file execution | `complete` |
| P2-S29 | Enforce cooldown and acknowledgment transitions. | P2-07 | Controlled UTC clock covers cooldown edges and owner-authorized acknowledge/resolve transitions, optimistic concurrency and unchanged historical rule versions. | [P207 local evidence](evidence/phase-2-p2-07-03c3c5b.json); `tests/integration/test_alert_postgres.py::test_acknowledgment_window_asof_counts_and_manual_resolution_do_not_rearm`; source selector mapped to actual full-file execution | `complete` |
| P2-S30 | Reject webhook destinations resolving to private or metadata addresses. | P2-07 | Local fake DNS/transport tests deny loopback/private/link-local/metadata/reserved IPv4/IPv6, rebinding and redirects before disallowed dispatch. | [P207 local evidence](evidence/phase-2-p2-07-03c3c5b.json); `tests/security/test_alert_webhook.py::test_rebinding_private_retry_is_rejected_before_second_connection`; source selector mapped to actual full-file execution | `complete` |
| P2-S31 | Preserve alert and report jobs across worker/dispatcher restart. | P2-06/P2-07 | Atomic enqueue/publication/consumer crash windows, duplicate delivery and worker/dispatcher restart preserve original report/alert jobs and artifacts/events. | [P207 local evidence](evidence/phase-2-p2-07-03c3c5b.json); `tests/integration/test_alert_postgres.py::test_atomic_slot_idempotency_immutable_input_and_real_worker_restart`; source selector mapped to actual full-file execution; [P206 report proof](evidence/phase-2-p2-06-9e39767.json) retained; fresh report/alert restart and same-input pending Redis-loss recovery | `complete` |
| P2-S32 | Deny cross-owner API access. | P2-01–09 | Authenticated owner/account cross-products and missing scopes deny all new list/detail/command/download endpoints without existence/secret disclosure. | [partial P206 local evidence](evidence/phase-2-p2-06-9e39767.json); reporting scope only, remaining shared predicates pending; [P208 scoped evidence](evidence/phase-2-p2-08-bc21516.json); P208 web contribution only; remaining shared scope pending; [partial P209 MCP/widget contribution](evidence/phase-2-p2-09-d70ab44.json); remaining shared predicates pending | `in_progress` |
| P2-S33 | Deny cross-owner MCP access. | P2-09 | All 25 tools reject cross-owner/account and missing-scope invocations; invalid IDs and unknown fields fail before unauthorized services or providers run. | [All25 persisted tool/scope bindings and same-source relevant gates](evidence/phase-2-p2-09-s33-bd47329.json); legacy pre-dispatch failure and correction retained | `complete` |
| P2-S34 | Preserve API, web, MCP, and report canonical value parity. | P2-01–09 | Same owner/account, snapshot/target/source revisions, cutoff/currency/method/parameters produce equal canonical Decimal values across service/API/rendered web/MCP/report. X-ray additionally pins numeric/traversal policies and representative paths; compare canonical semantic bytes including exact state while excluding derived self-digest/generated envelopes. Report parity remains P2-06. | `tests/contract/test_historical_contract.py::test_comparison_widget_has_valid_hash_csp_safe_dom_and_no_network_or_financial_math`; [partial historical API/web/MCP evidence](evidence/phase-2-p2-04-2a7c89a.json); remaining shared scope pending; not a complete scenario; [partial X-ray evidence](evidence/phase-2-p2-05-7b10266.json); remaining release-wide scope pending; not a complete scenario; [partial P206 local evidence](evidence/phase-2-p2-06-9e39767.json); reporting scope only, remaining shared predicates pending; [P208 scoped evidence](evidence/phase-2-p2-08-bc21516.json); P208 web contribution only; remaining shared scope pending; [partial P209 MCP/widget contribution](evidence/phase-2-p2-09-d70ab44.json); remaining shared predicates pending | `in_progress` |
| P2-S35 | Preserve all Phase 1 mandatory scenarios. | P2-10 | Rerun every Phase 1 mandatory predicate including 14a/14b/14c, 2505/>10000 collection traversal, hard-capacity concurrency and export-URL minimization. | Not recorded / none | `pending` |
| P2-S36 | Preserve the exact ten-capability Trading 212 GET-only registry. | P2-03/P2-10 | Registry-count/static architecture checks and transport-spy negatives preserve all ten exact GET templates and reject every unknown method/path/parameter. | Not recorded / none | `pending` |
| P2-S37 | Prove no Phase 2 workflow can place, modify, or cancel a broker order. | P2-10 | Exercise plan/report/alert/provider/web/MCP workflows with sealed broker spies; no place/amend/cancel/Pie/transfer/generic execution API or task is reachable. | Not recorded / none | `pending` |
| P2-S38 | Prove all output states distinguish fresh, stale, partial, unavailable, unreconciled, and failed. | P2-01–10 | Parameterized service/API/web/MCP/report fixtures preserve fresh/stale/partial/unavailable/unreconciled/failed, plus estimated/unsupported when applicable, without zero substitution. X-ray distinguishes disjoint exact zero, partial zero lower bound, sub-Q18 positive unknown, unavailable unit basis and inconclusive partial threshold. | [partial X-ray evidence](evidence/phase-2-p2-05-7b10266.json); remaining release-wide scope pending; not a complete scenario; [partial P206 local evidence](evidence/phase-2-p2-06-9e39767.json); reporting scope only, remaining shared predicates pending; [P208 scoped evidence](evidence/phase-2-p2-08-bc21516.json); P208 web contribution only; remaining shared scope pending; [partial P209 MCP/widget contribution](evidence/phase-2-p2-09-d70ab44.json); remaining shared predicates pending | `in_progress` |
| P2-S39 | Prove desktop/mobile accessibility and no horizontal overflow. | P2-08/P2-09 | Desktop/mobile API-backed Playwright and accessibility assertions cover keyboard/focus, labels, text alternatives, reduced motion, errors, 18 experiences and versioned widgets. | [P208 scoped evidence](evidence/phase-2-p2-08-bc21516.json); P208 web contribution only; remaining shared scope pending; remaining shared accessibility closure pending; [partial P209 MCP/widget contribution](evidence/phase-2-p2-09-d70ab44.json); remaining shared predicates pending | `in_progress` |
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

## P2-03 observed evidence

P2-03, P2-SRC-001, P2-SRC-002 and P2-S13 passed at
`e258f54bb03a958f7847b310ee882b7f4a54686f`. The [assertion map](evidence/phase-2-p2-03-e258f54.json),
[fresh runtime record](evidence/phase-2-p2-03-e258f54-runtime.json),
[security scans](evidence/phase-2-p2-03-e258f54-security.json) and
[compatibility comparison](evidence/phase-2-p2-03-e258f54-compatibility.json) retain actual
local/CI results, exact synthetic observations, immutable history, cursor reuse
and seven-service restart. The two failed harness attempts (cursor issue-time comparison and aggregate
pagination capacity) are retained separately from the corrected fresh runtime. Three packages, eight
local rows and twelve scenarios are complete; P2-S14/P2-S36 and later/shared
predicates remain pending. Phase 3 remains `not_started`.

## P2-04 observed evidence

P2-04 is complete at `2a7c89a9b8c37d97006dafbbe97a44eec37b3fe0`. The [accepted assertion map](evidence/phase-2-p2-04-2a7c89a.json) closes P2-PERF-001, P2-PERF-002, P2-INC-001 and P2-S14 through P2-S19. Shared P2-S34 remains `in_progress`: historical API/web/MCP parity is partial evidence; report/export and remaining shared scope are outstanding.

The clean exact-source `make validate` passed in 1165.723 seconds: 1,346 isolated and 175 service-backed Python tests, 88% combined statement/branch coverage, 203 web unit tests and 66 browser checks. A separate unchanged-source `env CI=1 PW_TEST_REPORTER=list T212PI_E2E_TIMINGS=1 make test-e2e build-web` passed in 366.184 seconds, retaining all 66 named browser passes and a successful web build with clean source before and after. The original full-gate GitHub reporter lacked individual browser names; the supplement adds that evidence without replacing the full gate or its image-build provenance. Pytest selectors are assertion inventory bound to observed complete test-file execution.

Exact pushed-source CI passed: Quality `34272112673`, Documentation `34272112714`, Security `34272112661`. Eight source/history/image scans passed under their retained scanner policies. Fresh runtime attempt 003 passed in 170.757 seconds: six historical HTTP reads, four MCP reads, configured web journeys and identical retained rows across all 101 inventoried tables after all seven services stopped/restarted. Task containers, volume and network were removed, with cleanup verified. Migration head is `20260907_0012`; the implemented inventory is 66 HTTP operations and 19 MCP tools; Trading 212 remains the exact ten GET-only capabilities.

See [runtime](evidence/phase-2-p2-04-2a7c89a-runtime.json), [security](evidence/phase-2-p2-04-2a7c89a-security.json) and [compatibility](evidence/phase-2-p2-04-2a7c89a-compatibility.json). At this P2-04 acceptance boundary, Phase 2 had four of ten packages (40%), eleven of 29 local rows and eighteen of 40 scenarios complete; later packages and Phase 3 were not_started. Current P2-05 acceptance is recorded below; no final Phase 2 release SHA is claimed.

P2-S34 has no completed evidence key in PROJECT_PROGRESS.json. Its partial historical evidence does not close report/export parity. P2-S38/P2-S39 and other release-wide predicates retain their existing states.

## P2-05 historical observed evidence

At the P205 closure boundary: P2-05 is **complete** at `7b102663ea193b4668924a7252180731954f4b00`. The [accepted assertion map](evidence/phase-2-p2-05-7b10266.json) closes P2-XRAY-001/002 and P2-S20 through P2-S23. Phase 2 has five of ten packages (50%), thirteen of 29 local rows and twenty-two of 40 scenarios complete. P2-S34 and P2-S38 remain `in_progress`; report/export parity and the remaining release-wide predicates are outstanding. P2-06 through P2-10 and Phase 3 remain `not_started`.

The clean exact-source `make validate` passed in 2339.747 seconds: 1,642 isolated and 234 service/migration Python tests, 88% combined statement/branch coverage, 223 web unit tests and 76 browser checks without retries. Assertion selectors are source mappings bound to completed test-file observations.

Exact-source CI passed: Quality `34347516142`, Documentation `34347516068`, Security `34347516074`. Eight source/history/image scans passed under the recorded scanner policies. The fresh runtime passed in 146.262241 seconds, preserving identical retained rows across all 167 compared tables and API/MCP replay after all seven services stopped/restarted. Task containers, volumes and networks were removed, with absence verified. All eight exact-gate screenshots received the recorded visual review.

See [runtime](evidence/phase-2-p2-05-7b10266-runtime.json), [security](evidence/phase-2-p2-05-7b10266-security.json), [compatibility](evidence/phase-2-p2-05-7b10266-compatibility.json), [screenshots and visual review](evidence/phase-2-p2-05-7b10266-screenshots.json) and [observed count derivation](evidence/phase-2-p2-05-7b10266-counts.json). Earlier failed candidates remain unaccepted. External broker/provider/deployment gates, the documented P2-08 UI follow-ups and the null final Phase 2 release SHA are unchanged.

## Historical P2-06 scoped local acceptance

P2-06 has scoped local acceptance at `9e39767b408b38203d88d6e5b41bf0bc1265adfb`. GitHub Actions is deferred by explicit owner instruction; no CI pass is claimed. The complete required local gates, exact source bindings and deferred startup observations are retained in the P206 acceptance evidence. Remaining Phase 2 implementation continues under that recorded deferral until the owner resumes CI verification.

The [finalized local artifact](evidence/phase-2-p2-06-9e39767.json) closes only the P206-owned rows and scenarios. At that P206 closure, totals were 16/29 local rows and 26/40 scenarios. Reporting contributes partial evidence to shared scenarios; later packages remain pending.

### Historical P206 implementation observations

The following earlier development observations and requirements are retained as history. They are not a new CI obligation during owner deferral or replacement exact-source acceptance evidence.

P2-S24 through P2-S27 were developed under the
[report implementation contract](P2_06_REPORTS_AND_EXPORTS.md). The working remainder
gate passed all 86 serial browser checks alongside 1,914 isolated and 277
service/migration coverage tests at 88% and the remaining documentation/security/build
stages. These results precede the final navigation correction and do not constitute
accepted scenario evidence. The subsequent navigation correction passed 301 web
unit tests, four desktop and four mobile browser journeys, and final web
lint/typecheck/build. The mobile result precedes only the hidden desktop-sidebar
CSS change. Root reviewed eight working screenshots with a documented full-page
mobile capture limitation; immutable acceptance images require their own review.
At that development boundary, clean exact-source validation, CI, scans, fresh runtime and screenshot/PDF review were still pending. Current accepted local proof and the distinct owner CI deferral are recorded above. Shared restart,
parity and output-state scenarios retain their outstanding release-wide scope.
At that historical P206 closure, P2-07 through P2-10 and Phase 3 remained `not_started`.

## P209 authorization acceptance and partial shared contribution

P2-09 is complete with P2-S33 authorization evidence at `bd47329cca5c1409486fff40d48e92163ab4a8af`. Phase 2 remains in progress with 9/10 completed packages (90%), 23/29 local rows and 31/40 scenarios complete. P2-MCP-001 and P2-MCP-002 retain their scoped evidence at `d70ab445de38aee255275880c5ef7a105ebbb939`. S32/S34/S38/S39 remain partial. P2-10 and Phase 3 remain `not_started`; GitHub Actions is owner-deferred with no pass claim, and the final Phase 2 release SHA remains null.

[P209/S33 supplement](evidence/phase-2-p2-09-s33-bd47329.json); finalized 2026-09-12T19:03:50.016115+00:00. The same-source relevant MCP, PostgreSQL, static, security, Python-build and single-MCP-image gates passed. The d70 full validation and browser/visual evidence remain historical; no new full validation, browser/visual gate or seven-service runtime is claimed.

[P209 scoped evidence](evidence/phase-2-p2-09-d70ab44.json); finalized 2026-09-12T18:08:53.523669+00:00. The artifact retains actual widget/API browser observations as supporting evidence. It does not claim a new full Compose startup/restart, runtime cleanup, PDF visual gate or live ChatGPT registration.

## Historical P2-08 partial scenario contribution

P2-08 has scoped local acceptance at `bc21516c51aa5090031b39ea56ded3ca94d657d8` for P2-WEB-001 and P2-WEB-002. Phase 2 remains in progress: 8/10 packages (80%), 21/29 local rows and 30/40 scenarios complete. S32/S34/S38/S39 remain partial; S33 is pending. P2-09 and P2-10 remain required and `not_started`; Phase 3 remains `not_started`. GitHub Actions is owner-deferred, not passed. The final Phase 2 release SHA remains null.

[P208 scoped evidence](evidence/phase-2-p2-08-bc21516.json) binds the actual P208 feature assertions and browser/visual observations. S32/S34/S38/S39 retain their shared owners and remain `in_progress`; S33 remains `pending`. No new completed scenario evidence key is created.

## Historical P2-07 scoped local acceptance

The following observations retain their original P207 boundary and source.

P2-07 has scoped local acceptance at `03c3c5b0b8182aadaaf48ec29131ab7fe83095a7`: versioned alert rules, immutable scheduled evaluation, event deduplication/cooldown, authorized lifecycle/history, bounded delivery and canonical alerts exports. Phase 2 is in progress: 7/10 packages (70%), 19/29 local rows and 30/40 scenarios complete. S31 includes both report/alert durable recovery and actual Redis-loss republication of the same pending alert input. Shared API/DATA/SEC/OPS and S32/S34/S38 predicates remain partial; P2-08 through P2-10 and Phase 3 remain `not_started`. GitHub Actions is owner-deferred and unverified; no CI pass or final Phase 2 release is claimed.

Actual completed gate summaries record 2352 isolated and 338 service-backed Python tests, 88% combined Python coverage with branch measurement, 345 web unit tests and 100 local browser checks. The full gate took 5416.926 seconds; fresh runtime took 256.28724 seconds. All six immutable images and the exact source/history scans passed; all seven runtime services restarted and scoped cleanup verified absence.

[Actual portable evidence](evidence/phase-2-p2-07-03c3c5b.json) records the exact eight requirements. Its source selectors and complete-file pass observations are distinct; no individual parameter pass IDs are inferred. Earlier failures and working observations remain historical in [the archived record](evidence/phase-2-p2-07-03c3c5b-implementation-history.json). All forty scenarios still require final-release same-source mapping at P2-10.
