# Phase 3 Mandatory Scenario Evidence

## Current controlled environment diagnosis, 16 November

The [controlled environment record](PHASE_3_CONTROLLED_ENVIRONMENT_20261116.md) retains three complete original
workload executions at clean main `1e86141984470df6ddfc485d2c41cee3113f8511`.
The bare original command fails admission p95 **1.022774345 s** against **0.750 s**;
read p95 **0.340622338 s**, maximum **12 SQL statements**, and all ten completions pass.
Two off-mode contexts return admission p95 **1.709143293 / 1.076423162 s**.
The same off-mode context does not reproduce the earlier timing level consistently.
First-admission delay is a supported inference; CPU, SQL/commit, GC and host causes
remain unresolved. No production correction is justified, and the three-run budget
is exhausted. Application code, tests, migrations and thresholds remain unchanged.

All **30 acceptance rows** and **48 scenarios** remain pending, **zero accepted**.
Complete Checkpoint B qualification remains **pending_local**; formal P3-10 has not
started. CI, provider credentials, production/Live and distribution remain separate
owner gates. Earlier records below retain their original source qualifications.

## Historical admission diagnosis, preceding 16 November package

The [focused admission record](PHASE_3_ADMISSION_REMEDIATION_20261116.md) starts from clean live/local
main `8adf4806528fc186a0778c9d08d71d636fe1b562`.
**Admission remediation FAILED; Checkpoint B remains incomplete.** The new
uninstrumented 30-read/ten-admission baseline fails p95/max **0.779183911 s**
against **0.750 s**; all ten jobs complete. Read p95 **0.324819180 s** and
maximum **12 SQL statements** pass. Earlier qualifying failures remain historical.

Broad and reduced observers retain every sample and exact source manifests, but
their inflated timings are diagnostic evidence, not qualifying performance.
The unexplained observer/environment/CPU inflation prevents a verified production
cause or justified optimization. No production code, tests or migrations changed;
the bounded investigation stops without another cohort or speculative correction.

All **30 acceptance rows** and **48 scenarios** remain pending, **zero accepted**.
Complete Make/coverage, browser, clean-install/build and expanded recovery/resource
qualification remain **pending_local**, not external blockers. Checkpoint B is not
accepted; formal P3-10 has not started. CI activation, providers/credentials,
production/Live, licensing and distribution retain their separate owner gates.
The 15 November consolidated observations below retain their original sources.

The new observation supplements `P3-OPS-003` / `P3-S47` only; it does not
complete either predicate, another row, or a scenario.

## Historical consolidated Checkpoint B qualification, 15 November

The historical [consolidated qualification record](PHASE_3_CHECKPOINT_B_CONSOLIDATED_20261115.md) follows owner authorization
from clean main `dabd98ff0cb5ff4c954d4465cebc71ea2a9a0267`. Checkpoint B remains
**INCOMPLETE**. Its last genuine 30-read/ten-admission cohort fails admission
p95/max **0.856597051 s** against 0.750 s (p50 0.617076987 s). All ten jobs complete;
read p95 0.344801251 s and all 12-statement counts pass. Its unchanged source
manifest is `3496f8bf9570cbc0152fcd3f4056ae4dbbe4b19531743028a609ed521630e919`,
headed by `250dc7` with manifested working changes, not clean-commit validation.

Forward schema `0036` aligns X-ray's frozen 32-MiB canonical bounds and retains
368 ORM tables. Separate focused observations demonstrate dense projection
heartbeat recovery, 33,508,886-byte report admission with genuine oversized
rollback, and a 2,092-holding retained-X-ray REPORT fallback with DISPLAY,
foreign-owner, expiry and revocation denial. The near-32-MiB JSON job fails
boundedly with no artifact under independent rendering limits; it is not successful
artifact evidence. A later tablet attribution diagnostic is not final browser
qualification. Fresh-build viewport qualification, complete local Make/coverage,
clean installation/build and recovery/resource qualification remain pending.
Focused committed-source regression and security observations are recorded in the
consolidated report; scanner failures retain their actual status.

Complete applicable local Checkpoint B qualification was owner-authorized.
Formal P3-10 has not started; its attempt count remains **0**. All **30 rows** and
**48 scenarios** remain pending, **zero accepted**. CI is owner-deferred/unverified;
production, Live, real credentials, paid providers, release and distribution rights
remain separately unauthorized. Earlier checkpoint results below retain their
historical source and authority.


**Design:** Accepted; implementation and execution evidence pending

**Inventory:** 48 distinct scenarios; none complete at design freeze

The material admission failure stops this bounded package before further
performance cohorts or long Make, coverage, complete browser or clean-install
qualification. Those checks remain **pending local**, not externally blocked.
Narrow source-affected regression and security checks have executed at `cb50452`;
the linked report records their exact scope and failed/recovered exits. Complete
qualification remains pending. Formal P3-10 remains unstarted.

## Historical bounded remediation, 15 November

The owner-authorized [Checkpoint B package](PHASE_3_CHECKPOINT_B_20261115.md)
starts from verified clean/live main `8fa5db7d0009ffd18f790ed4c9f498d130e86675`.
Its final qualifying attempt collects all 30 reads and ten admissions/jobs,
but admission p95/max 0.772447935 s still exceeds 0.750 s. Admission p50 is
0.544712408 s; read p95 0.314842558 s and all 12-statement counts pass. The retained diagnostic desktop fails research LCP p75 at 4,972 ms. Later
qualifying desktop/mobile pass at 2,448/1,592 ms; tablet fails at 2,724 ms against
2,500 ms. All 15 research pagination journeys complete. The tablet failure is
material local work and independently keeps Checkpoint B INCOMPLETE. Actual near-32-MiB report and large retained-X-ray reader attempts also fail
before their required boundaries: source-worker FENCED behavior and a verified
32-MiB design versus inherited 8-MiB schema conflict remain local gaps. New risk/scenario queued recovery passes separately. Checkpoint B is
INCOMPLETE; P3-10 is excluded from this package and its complete-attempt count is 0.
All 30 rows and 48 scenarios remain pending, zero accepted. Later code corrections,
final committed-source scans, cleanup and archive results require actual evidence.

The Batch 1/2 observations below retain their historical scope. New focused
results, retained failures, code/test paths and source qualifications are recorded
in the linked report; they do not complete a row or scenario.

The fixture and predicate column is normative. Actual selector pointers below identify
implemented tests; a pointer is not an assertion that its full predicate passed.
A row may become complete
only when its actual selectors, successful commands and immutable source-bound evidence
are recorded. Keep deterministic references separate from statistical tolerances.

Consolidated Batch 1 records supplemental actual selectors and separate execution
receipts in the [current functional-completion record](PHASE_3_BATCH1_20261114.md).
New aggregation predicates contribute to P3-S30–S32; independent log/permutation,
action/outlier, fund equivalence, comparison currency and capacity predicates
contribute to P3-S01/S03/S08/S11/S14/S21. Research exact-selection/domain/REST/web
component checks contribute to P3-S24/S26. Separate PostgreSQL observations now
cover four-format capture (1 pass), remaining exact-selection checks (6 passes)
and physical retention (8 passes). A later migration retry passed two recovered
checks plus populated-downgrade refusal (3 cases); one desktop case covers
navigation/selection without report submission/download. Exact receipt names,
times and the two distinct source manifests are recorded in the
[validation report](../../VALIDATION_REPORT.md#research-report-component-evidence-2026-11-14).
These observations do not complete a scenario or establish a final-source full
validation/CI pass.
All 48 states below remain pending, zero accepted.

**Historical Batch 2 supplement:** The [Batch 2 traceability map](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios)
adds item-specific focused proof, source qualifications and remaining gaps. Latest
complete-capture parity and 420 affected codec cases pass separately; admission p95
.930957544 s>.750 s still fails. Checkpoint B remains pending; the complete attempt count is 0; no full validation or
accepted scenario is inferred. Corrected-height mobile and tablet journeys now pass in separate unchanged-source
invocations. Representative performance remains pending after a partial failure;
no complete gate is inferred.


Performance recovery04 was interrupted after 462.088 s (wrapper exit 1,
Playwright exit 130), after 191.94 s of fixture preparation, without completed SLO
samples. The nested select required an exact role selector rather than
`getByLabel('Sort')`; two focused diagnostics support the harness correction.
Recovery05 subsequently failed after 231.563 s. Five holdings samples completed,
but the first research render returned SOURCE_UNAVAILABLE; no research SLO, LCP
or bundle-budget pass is established. See the
[traceability supplement](PHASE_3_BATCH2_TRACEABILITY.md#subsequent-focused-observations).


Corrected-height report journeys now pass separately: mobile 360×800 in 124.976 s
(`a2-corrected-height-mobile-02`) and tablet 768×1024 in 122.160 s
(`a2-corrected-height-tablet-02`). Both have unchanged complete source manifest
`4a5ce4df0782f6205e02940eebe712300f57f04fdae52a5b970a36d6dc9eb648`.
Desktop 1440×900 evidence is retained by exact relevant-input equivalence; no
unchanged desktop repeat is required. These focused observations do not complete
a row or scenario, establish representative performance, or start the complete
P3-10 attempt. The historical admission p95 failure remains unchanged; the later functional query
recovery and incomplete performance observations are recorded below.

| ID | Package | Scenario | Exact fixture/predicate | Actual primary test selector | State |
| --- | --- | --- | --- | --- | --- |
| P3-S01 | P3-01 | Daily/monthly calendar alignment and simple/log returns; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Pinned complete session tuples; reordered inputs preserve canonical output, missing boundaries never fill. | tests/unit/analytics/test_phase3_risk.py::test_risk_alignment | pending |
| P3-S02 | P3-01 | Explicit reporting FX and source knowledge cutoff; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | 100 USD flat price with EUR per USD .90 to .99 gives .10 EUR return; absent/future FX is unavailable. | tests/unit/analytics/test_risk_history.py::test_fx_changes_are_returns_and_missing_fx_is_unavailable | pending |
| P3-S03 | P3-01 | Cash-flow neutrality and corporate actions; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | 100 opening plus 100 externally deposited with 200 closing gives zero TWR when exact anchors exist; absent anchors/actions degrade. | tests/unit/analytics/test_risk_history.py::test_exact_flow_anchor_excludes_deposit_from_return | pending |
| P3-S04 | P3-01 | Constant and zero-volatility series; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Thirty zero returns give volatility0; zero benchmark variance yields unavailable beta/correlation, not invented zeros. | tests/unit/analytics/test_phase3_risk.py::test_risk_zero | pending |
| P3-S05 | P3-01 | Perfect correlation, anticorrelation and singular PSD; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | B=2A is singular valid; B=-A with equal weights has zero modeled volatility; a non-PSD matrix is rejected. | tests/unit/analytics/test_premium_numeric.py::test_singular_anticorrelation_and_zero_variance_are_supported | pending |
| P3-S06 | P3-01 | Independent volatility, beta and Euler contribution references; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Thirty A returns repeating -.01,0,.01 and B=2A: beta2; sample variance .002/29; equal-weight risk1.5 sigmaA, components .5 and1 sigmaA. | tests/unit/analytics/test_premium_numeric.py::test_rational_covariance_beta_and_euler_components | pending |
| P3-S07 | P3-01 | VaR/ES confidence, tail mass, horizon and sign; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | One-horizon losses 0..99 divided 10000: c=.95 VaR .0094 and ES .0097; c=.99 insufficient tail. Constant +.01 over 2 intervals has loss -.0201. | tests/unit/analytics/test_premium_numeric.py::test_historical_tail_reference_fractional_mass_and_sign | pending |
| P3-S08 | P3-01 | Missing/outlier and hostile numerical context policies; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Nonfinite/oversized encodings rejected before work; hostile outer Decimal context cannot change values or escape restoration. | tests/unit/analytics/test_phase3_risk.py::test_risk_numeric | pending |
| P3-S09 | P3-01 | Direct/indirect concentration and uncovered mass; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Same economic entity across direct and fund paths is combined before HHI; wrapper is excluded, unknown mass retained. | tests/unit/analytics/test_risk_result.py::test_concentration_reuses_direct_plus_indirect_partition_and_lower_bound | pending |
| P3-S10 | P3-02 | Immutable scenario versions and ownership; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Clone changes version/digest; edit of published content and foreign references fail; exact idempotent retry returns one version. | tests/integration/test_scenario_runs_postgres.py::test_definition_versions_use_revision_and_exact_retry | pending |
| P3-S11 | P3-02 | Shock precedence, FX compounding and conservation; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | 60A/40B with -.20/+.10 price shocks and -.10 evidenced FX gives 82.8 post-value, -17.2 effect; equivalent fund partition agrees. | tests/unit/analytics/test_scenario.py::test_original_basis_channel_effects_and_interaction | pending |
| P3-S12 | P3-02 | Rates/factors, exclusions and unsupported sensitivities; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Only evidence-bound sensitivities contribute; equal-priority conflict rejected, missing sensitivity remains explicit uncovered mass. | tests/unit/analytics/test_scenario.py::test_missing_positive_sensitivity_blocks_full_value_and_explicit_exclusion_restores_it | pending |
| P3-S13 | P3-02 | Historical replay and current/historical holdings basis; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Keep separate holding basis and market knowledge cutoff; future revisions/constituents cannot masquerade as then-known evidence. | tests/unit/analytics/test_scenario_replay.py::test_market_point_in_time_rejects_later_known_snapshot_revision | pending |
| P3-S14 | P3-02 | Scenario comparison and report parity; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Compare only authorized saved outputs with disclosed currency/method differences; report shares canonical component values. | tests/unit/analytics/test_scenario_comparison.py::test_currency_mismatch_preserves_native_saved_values_without_delta_or_conversion | pending |
| P3-S15 | P3-03 | Seed, chunk, worker and restart determinism; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Same canonical inputs and absolute path indices reproduce every Q18 financial value across different chunk partitions and retries. | tests/unit/analytics/test_phase3_projections.py::test_projection_identity | pending |
| P3-S16 | P3-03 | Zero-volatility contribution/lump/withdrawal timing; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | 100 initial,10/month,5 lump in month1,20 withdrawal in month2, zero returns yields 105 after 2 months. | tests/unit/analytics/test_phase3_projections.py::test_projection_flows | pending |
| P3-S17 | P3-03 | Fees, inflation and simulated rebalancing conservation; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | 100 initial, zero returns/flows, annual fee .12 and inflation .10 yields nominal88 and real80 after 12 months within declared Q18 bound. | tests/unit/analytics/test_phase3_projections.py::test_projection_fees | pending |
| P3-S18 | P3-03 | Insolvency and unpaid withdrawals; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Withdrawal exceeding wealth cannot create negative holdings; unpaid liability remains visible after later contributions. | tests/unit/analytics/test_phase3_projections.py::test_projection_insolvency | pending |
| P3-S19 | P3-03 | Goals, probabilities, uncertainty and shortfall; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Deterministic all/none success cases have probabilities1/0, with sampling interval convention and exact shortfalls. | tests/unit/analytics/test_phase3_projections.py::test_goal_reference | pending |
| P3-S20 | P3-03 | Contribution and assumption sensitivity; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Common seed is disclosed; zero-volatility contribution increments match analytic sums, monotonicity asserted only under valid assumptions. | tests/unit/analytics/test_phase3_projections.py::test_goal_sensitivity | pending |
| P3-S21 | P3-03 | Admission quotas, bytes and computational bounds; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Reject assets/steps/paths/retained points/work-product and per-owner capacity excess before job/output insertion. | tests/integration/test_projection_admission_postgres.py::test_active_quota_rejection_preserves_all_persistent_admission_state | pending |
| P3-S22 | P3-03 | Timeout, cancellation, leases and crash fencing; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Cancelled/expired lease cannot publish; resume absolute path indices; no incomplete run reported complete. | tests/integration/test_projection_jobs_postgres.py::test_restart_reuses_original_chunks_and_rejects_old_fence | pending |
| P3-S23 | P3-04 | Exposure ranking, event deduplication and revisions; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Effective exposure defines ranking; same minimized source event deduplicates, corrected facts append a dated revision. | tests/unit/domain/test_research_foundation.py::test_absolute_exposure_precedes_review_time_and_unknown_never_becomes_zero | pending |
| P3-S24 | P3-04 | Source facts, owner notes and cited synthesis; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Distinct content types and dates survive reads/exports; synthesis missing evidence or invented numeric facts is rejected. | tests/integration/test_research_reports_postgres.py::test_exact_research_four_formats_preserve_original_sources_and_historical_revisions | pending |
| P3-S25 | P3-04 | Prompt injection and destination containment; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Malicious fetched instructions remain inert text and cannot change scopes, select URLs, reveal secrets or invoke commands. | tests/security/test_phase3_research.py::test_research_injection | pending |
| P3-S26 | P3-04 | Owner/license revocation, retention and exports; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Current owner and source permissions checked on read/export; expiry removes retained and derived forbidden copies. | tests/integration/test_research_report_retention_postgres.py::test_report_only_revocation_drains_all_copies_and_preserves_originals | pending |
| P3-S27 | P3-07 | Typed production adapter replay contracts; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Realistically shaped synthetic market/FX/ETF/reference/research payloads normalize and reject wrong subjects/bases/schema. | tests/unit/reference_data/test_premium_parsing.py::test_daily_preserves_raw_adjusted_action_precision_without_reconstruction | pending |
| P3-S28 | P3-07 | Provider rate limits, timeouts, DNS and redirects; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | No paid call; injected transport proves retry/rate budgets and rejects private/mixed DNS, redirect and arbitrary continuation. | tests/unit/reference_data/test_premium_transport.py::test_any_private_dns_answer_denies_before_connection | pending |
| P3-S29 | P3-07 | Failover source identity, entitlement and cutoff; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Fallback is explicit and source/method-bound; revoked/unknown license and later knowledge cannot supply successful substitute data. | tests/unit/reference_data/test_premium_acquisition.py::test_current_revocation_precedes_private_parse | pending |
| P3-S30 | P3-08 | Authorized account aggregation and explicit FX; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Distinct-account positions/cash consolidate by economic identity with exact FX and preserved source account contributions. | tests/integration/test_aggregation_acceptance_postgres.py::test_eight_owned_native_members_publish_one_economic_holding_with_exact_contributions | pending |
| P3-S31 | P3-08 | Matched, ambiguous and unmatched transfers; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Only evidenced counterpart pairs cancel internal cash flows; unmatched/ambiguous legs remain explicitly degraded. | tests/integration/test_aggregation_acceptance_postgres.py::test_original_counterpart_ambiguity_or_missing_proof_never_cancels_cash | pending |
| P3-S32 | P3-08 | Second broker and unchanged Trading 212 transport; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | A second synthetic read-only adapter populates canonical records; all ten Trading 212 GET capabilities and negatives remain exact. | tests/security/test_premium_transport_boundary.py::test_original_broker_contract_is_byte_exact_and_still_only_ten_gets | pending |
| P3-S33 | P3-05 | Signed JWT, scopes, current grants and cross-owner denial; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Real RS256/ES256/EdDSA transport preserves identity and denies malformed claims, wrong scopes and post-queue revocation. | tests/integration/test_real_jwt_mcp_postgres.py::test_invalid_real_bearer_never_executes_or_persists_commands | pending |
| P3-S34 | P3-05 | Every premium MCP descriptor and command boundary; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Strict schemas/annotations/scopes/bounds for every added tool; same-key conflict and concurrent replay create one logical run. | tests/contract/test_phase3_legacy_mcp_fingerprints.py::test_original_25_complete_tool_descriptors_remain_unchanged | pending |
| P3-S35 | P3-10 | Canonical API/web/MCP/report quality parity; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Available/stale/partial/estimated/unavailable/failed states, money, sources and assumptions agree for the same retained result. | tests/integration/test_api_mcp_postgres_parity.py::test_postgres_backed_api_and_mcp_return_identical_canonical_values | pending |
| P3-S36 | P3-05 | Widget keyboard, mobile, reduced motion and text tables; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | All old/new resources keep keyboard access, text alternatives, source disclosures and strict metadata/CSP. | tests/e2e/web/research-read-widgets.spec.ts::research host read remains closed and malformed money clears whole content | pending |
| P3-S37 | P3-06 | PWA manifest, icons, installation and offline shell; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Installability requirements pass on a local secure origin; offline navigation renders only the public shell with explicit unavailability. | tests/e2e/api-web/pwa.spec.ts::public offline shell never retains account pages or successful private responses | pending |
| P3-S38 | P3-06 | No private caching across logout/account/owner; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Inspect CacheStorage/network/service-worker behavior; private HTML/APIs/reports/tokens never cached, logout clears relevant state. | tests/e2e/api-web/pwa.spec.ts::public offline shell never retains account pages or successful private responses | pending |
| P3-S39 | P3-06 | Navigation, palette, owned saved views and pagination; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Back/forward/reload preserve validated URL state; changing filters resets cursors; saved account references are reauthorized. | tests/e2e/api-web/workspace.spec.ts::account identity survives real API navigation, reload and browser history | pending |
| P3-S40 | P3-06 | Accessible charts, overflow, bundle and web performance; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Desktop/tablet/mobile charts expose canonical tables and gaps; measure frozen local bundle/CWV targets without field-performance claims. | tests/e2e/api-web/operational-performance.spec.ts::production 100-holding 1000-event workload retains five raw lab samples and route byte budgets | pending |
| P3-S41 | P3-09 | Secret and signed-URL artifact canaries; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Scan normalized storage, exceptions/logs, generated clients, browser artifacts and report formats for ephemeral canaries. | tests/security/test_secret_canary_acceptance.py::test_secret_canary_is_absent_from_api_mcp_errors_and_logs | pending |
| P3-S42 | P3-09 | SSRF, filenames/path traversal and formulas; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Closed sources and safe downloads reject traversal/redirect/DNS tricks; CSV/XLSX never execute untrusted formulas. | tests/integration/test_report_privacy_postgres.py::test_four_actual_formats_and_audits_exclude_private_source_and_grant_canaries | pending |
| P3-S43 | P3-10 | All Phase 1/2 and Stage A regressions; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Preserve scenario selectors, collection quotas/export minimization, JWT identity and semantic idempotency at the final source. | tests/contract/test_phase3_legacy_mcp_fingerprints.py::test_original_25_complete_tool_descriptors_remain_unchanged | pending |
| P3-S44 | P3-09 | Full restart, Redis loss, database outage and duplicate dispatch; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Retained IDs/hashes/counts survive complete stop/restart; recovered dispatch/materialization does not duplicate runs or finance. | tests/integration/test_phase3_process_recovery.py::test_sigkill_redis_loss_and_postgres_outage_resume_original_projection_chunk | pending |
| P3-S45 | P3-10 | Empty install, Phase 2 upgrade and repeat migration; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | One linear head after 0016; empty install and0016 upgrade converge; repeated upgrade is a no-op with constraints intact. | tests/integration/test_risk_migration_upgrade.py::test_populated_phase2_upgrade_keeps_rows_values_and_replay | pending |
| P3-S46 | P3-09 | Independent clean-database synthetic backup restoration; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Restore to genuinely empty DB, verify row counts/constraints/canonical hashes/job recovery and measured RTO; no production claim. | tests/integration/test_phase3_operational_recovery.py::test_empty_database_restore_preserves_canonical_state_and_recovers_both_jobs | pending |
| P3-S47 | P3-09 | Measured API/query/job/load budgets and scanner scopes; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Retain workload/host/runtimes, p50/p95 and memory, queue limits and scanner database/version/exception evidence. | tests/integration/test_phase3_operational_budgets.py::test_measured_research_read_query_and_report_admission_budgets | pending |
| P3-S48 | P3-10 | SBOM/signing/provenance and external release boundaries; [proof / gaps](PHASE_3_BATCH2_TRACEABILITY.md#mandatory-scenarios) | Verify local ephemeral signing machinery/source-image binding; actual evidence pack and 1.0.0 candidate never claim production attestation. | tests/unit/test_release_evidence.py::test_ephemeral_signing_performs_no_file_io_and_independent_public_key_verifies | pending |


## Historical bounded checkpoint observations

The production NOT IN/MATERIALIZED query now passes five affected PostgreSQL
cases (88.36 s) and real normal service with 100 EUR10 holdings and 1000 events,
sources and witnesses (203.44 s, including 193.437 s setup). It returns 25 ranked
rows with unknown 0 under the unchanged 5 s statement cap. Both receipts and the
later desktop browser receipt retain unchanged source
`f9bd99d2bb3a2d699432ca8d9d0ab0ad4b8af29c2769846ce61e2acf2b16a230`.
The original capability authority was restored. Profile12 retained28.226935 s
execution with about one billion membership combinations. Prototype13 failed
before query execution in its read-only authorization harness; corrected14 passed
with cold SQL 0.332076825 s/full function 0.34825882 s and unchanged zero statistics.
These diagnostics and functional recovery do not establish a performance gate.

Desktop performance recovery06 failed after 228.775 s: research rendered 25/1000
EUR10 rows, then the Next-link cursor-URL poll failed within 5 s. Five complete
holdings samples and one partial research sample remain: LCP 5596 ms,
interaction 24 ms and CLS 0. There is no complete research p75/bundle/summary gate.
The cause is inconclusive; missing href/request timing prevents assigning a
product or test defect. Slow pending navigation is only an inference. Further
costly performance iterations stopped; mobile/tablet performance remains
pending_local. Separate A2 report journeys at all required viewports remain
qualified; these are distinct from representative performance.

The separate focused runtime receipts bind clean
`da2a6bbe2e8b46716b92074c0ed2f29d4a2b6e2a`, tree
`5f06353778d40c608ba82bd2dfa6256e0812d33f`, with unchanged source manifest
`c3d4bb85b57039202788b1b6dd11ac4039a004309be6c3141ad077c641fa54b0`.
Build 02 passed in 31.445 s, start-recovery02 in 20.452 s and image/source probes 02
in 1.962 s. `a3-full-stack-restart-01` passed with a 48.662 s wrapper and recovery
of 34.635317916 s under 600 s. All nine containers stopped and resumed with the same
identities/images/network/volume: seven long-running services healthy and migrate/
seed exited0. The retained/recovered seven-path modeled projection preserves
canonical inputs, capture/result bytes and counts; all 13 economic table row/hash
records are equal. Real-broker duplicate delivery drained without changing
canonical state. All-premium-family recovery remains unverified. The original
53000-port startup failure remains retained; the authorized recovery uses 53500.

`a3-owned-stack-backup-and-retirement-01` separately passed in 15.489 s at the same
unchanged source. Twelve connectable databases have 70,072,624 B of custom dumps,
individual hashes, readable `pg_restore --list` catalogs and later rehashes. The
nine exact task containers, one task volume and one task network were removed
after backup; zero images were deleted and the two original volumes/nine qualified
image IDs were preserved. These cleanup dumps were not restored.

Configured scoped SAST and the earlier high-confidence source check retain their
separate passes. At clean 71f478324daddbab9b2cf9a4275e18de9eb2997b, source Gitleaks
failed with 56 findings (34.051 s) and all-ref history Gitleaks with two (33.579 s).
The 54 inherited reviewed source findings and two new source-digest findings are
classified nonsecret, with zero unknown observations. The status remains
`REVIEW_COMPLETE_SCANNERS_REMAIN_FAILED`: scanner exits, policy and ignores are
unchanged. Configured filesystem Trivy, fresh Python and production Node audits
passed separately in 29.149 s, 6.486 s and 0.565 s. These observations retain their 71f
source; final-source/complete candidate artifact qualification and private archive remain pending.

The actual admission p95 failure remains0.930957544 s against 0.750 s, retained by
`admission-failed-observation-component-binding-01.json`:1026 application/package
inputs compared, only research_summary_query.py differs; four fixture/test inputs
are equal and the authority is restored. No ten-job timing repeat or new latency
pass is claimed. Checkpoint B remains pending; complete P3-10 attempts 0; all 30
rows/all 48 scenarios remain pending, zero accepted. The admission failure and
incomplete desktop recovery06 performance remain material local gaps. No final-SHA/CI
acceptance, 1.0 candidate, complete Make validation or release is claimed.
See the [qualified runtime and audit observations](PHASE_3_BATCH2_TRACEABILITY.md#focused-nine-service-restart-and-prior-clean-source-audits).

The six retained build02 images subsequently passed the configured vulnerability/
secret checks (`a4-current-image-{api,worker,mcp,web,postgres,redis}-01`), with
zero configured findings at the exact `da2a6bb` image identities. This scope
uses the unchanged HIGH/CRITICAL, fix-available policy; it configures neither
image license nor image misconfiguration scanning. Complete candidate SPDX,
signing, artifact and reproducibility qualification remains separate. These
observations change no acceptance status, licensing right or complete-gate result.
