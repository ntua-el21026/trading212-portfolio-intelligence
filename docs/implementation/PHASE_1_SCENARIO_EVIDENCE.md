# Phase 1 Mandatory Scenario Evidence

**Authority:** `docs/implementation/PHASE_1_EXECUTION_MANIFEST.md`

**Correction state:** in progress directly on `main`

**Audit date:** 2026-09-01

This ledger maps the fourteen mandatory synthetic end-to-end scenarios to exact,
executable evidence. It deliberately distinguishes a component test from an end-to-end
acceptance result. A row is not release evidence until its listed commands pass at the
immutable corrected `main` SHA.

The fourteen entries in `trading212_analytics.fixtures.PHASE_1_SCENARIOS` are analytics
reference fixtures with a different numbering and purpose. The metadata check in
`tests/unit/analytics/test_phase1_scenarios.py` therefore does **not** satisfy this
manifest gate.

## Evidence-state vocabulary

- `implemented_evidence`: the required behavior is exercised through the material
  production boundary, but still needs the final release-SHA run.
- `passed_working_tree`: the defining behavior passed in the current working tree,
  including runtime observation where the scenario requires it, but must still be
  repeated at the immutable release SHA.
- `partial_evidence`: useful component or composite tests exist, but at least one
  required transition, persistence boundary, or client surface is not exercised.
- `missing_test`: no test exercises the scenario's defining state transition.
- `runtime_pending`: acceptance requires an observed process/container operation and
  cannot be inferred from source or a unit test.

## Scenario ledger

| # | Mandatory outcome | Exact candidate evidence | Current state and unresolved predicate |
|---:|---|---|---|
| 1 | Fresh account ingestion and canonical snapshot | `tests/integration/test_worker_materialization.py::test_seed_and_refreshes_materialize_changed_and_empty_current_state` | `implemented_evidence` — production ingestion, PostgreSQL source evidence, canonical facts, immutable snapshots, and reconciliation are exercised. Final release-SHA integration run remains required. |
| 2 | Repeated identical refresh creates no duplicate economic records | `tests/integration/test_phase1_synthetic_acceptance.py::test_identical_production_refresh_does_not_duplicate_economic_records`; `tests/integration/test_worker_ingestion_store.py::test_postgres_refresh_is_coalesced_idempotent_and_retains_revisions` | `implemented_evidence` — a second production-path refresh preserves exact canonical economic row counts while retaining a distinct immutable observation snapshot; durable run coalescing/revision behavior is covered separately. Final release-SHA integration run remains required. |
| 3 | Incremental refresh adds one transaction, dividend, and position change | `tests/integration/test_phase1_synthetic_acceptance.py::test_incremental_production_refresh_adds_transaction_dividend_and_position_change` | `implemented_evidence` — one incremental production-path refresh adds exactly one canonical transaction, dividend, position observation, cash flow, and resulting snapshot with exact totals. Final release-SHA integration run remains required. |
| 4 | Transient provider failure retries and recovers within budget | `tests/integration/test_phase1_synthetic_acceptance.py::test_transient_failure_reuses_durable_run_and_recovers_within_retry_budget`; `tests/unit/worker/test_worker_configuration.py::test_retryable_economic_failure_defers_durably_without_celery_retry_publication`; `tests/unit/trading212/test_client.py::test_retry_exhaustion_sanitizes_provider_body` | `implemented_evidence` — the production coordinator/PostgreSQL store recovers on the same durable run within two attempts, while a retryable consumer failure durably returns dispatch to the bounded outbox retry path before the current delivery is acknowledged. Sanitized provider retry exhaustion is covered separately. Final release-SHA runs remain required. |
| 5 | Rate limit pauses and resumes safely | `tests/integration/test_worker_materialization.py::test_redis_rate_limit_waits_and_duplicate_page_is_idempotently_persisted`; `tests/unit/application/test_phase1_ingestion_acceptance.py::test_rate_limited_page_pauses_then_resumes_and_commits_successfully`; `tests/unit/trading212/test_client.py::test_rate_limit_retries_are_bounded` | `implemented_evidence` — the real Redis coordinator and PostgreSQL materializer pause a two-page read to the reset, resume, and persist the repeated record exactly once; the deterministic reference coordinator and bounded HTTP retry are also covered. Final release-SHA runs remain required. |
| 6 | One capability fails and aggregate state becomes explicitly partial | `tests/integration/test_api_mcp_postgres_parity.py::test_postgres_backed_api_and_mcp_return_identical_canonical_values`; `tests/unit/application/test_ingestion.py::test_partial_capability_failure_never_reports_success`; `tests/unit/analytics/test_phase1_scenarios.py::test_partial_capability_output_degrades_only_dependent_portfolio_metric`; `tests/e2e/web/states.spec.ts` | `implemented_evidence` — a newer persisted partial refresh overlays the retained canonical snapshot as partial in the PostgreSQL service, REST summary/data-quality output, and MCP quality tool with the failed capability named; analytics dependency degradation and the web partial state are covered separately. Final release-SHA integration/browser runs remain required. |
| 7 | Schema incompatibility fails the atomic unit and does not advance checkpoint | `tests/unit/application/test_phase1_ingestion_acceptance.py::test_schema_incompatible_page_preserves_last_atomic_checkpoint`; `tests/unit/trading212/test_client.py::test_malformed_or_missing_contract_data_fails_closed`; `tests/integration/test_worker_ingestion_store.py::test_failed_page_transaction_does_not_advance_checkpoint` | `implemented_evidence` — one synthetic schema-drift workflow commits a valid first page, rejects the incompatible next page as a contract failure, and preserves the last atomic checkpoint/source state; PostgreSQL rollback is covered independently. Final release-SHA runs remain required. |
| 8 | Quantity/cash mismatch is persisted and visible as unreconciled | `tests/integration/test_api_mcp_postgres_parity.py::test_postgres_backed_api_and_mcp_return_identical_canonical_values`; `tests/e2e/api-web/reconciliation.spec.ts`; `apps/worker/src/trading212_worker/scenarios.py::persist_quantity_cash_mismatch_scenario` | `passed_working_tree` — one retained synthetic, immutable reconciliation fixture runs the real quantity and cash bridge algorithms, persists both discrepancy types through PostgreSQL, and exposes the same unreconciled issues through REST, MCP, and the actual API-backed web experience on desktop and mobile. This acceptance-only fixture does not assert that Trading 212 provides a real opening-history basis. Final release-SHA integration/browser runs remain required. |
| 9 | Multi-currency valuation uses sourced FX and degrades explicitly when FX is missing | `tests/integration/test_worker_materialization.py::test_provider_wallet_currency_is_retained_and_missing_fx_fails_closed`; `tests/unit/analytics/test_portfolio.py::test_multi_currency_aggregation_uses_explicit_fx_and_weights_reconcile`; `tests/unit/analytics/test_portfolio.py::test_missing_or_post_cutoff_fx_is_not_treated_as_one_or_zero` | `passed_working_tree` — the production persistence/materialization path retains the source-currency observation and a provenance-bearing directional FX quote. With the explicit USD/EUR `0.9` quote, invested value is exactly `212400` EUR and the calculation records the rate, source record, observation time, and source. Without an eligible quote, totals remain unavailable/partial and `currency_fx_gap` is persisted; no implicit rate or missing-as-zero fallback is used. |
| 10 | Unauthorized cross-owner/account API and MCP access is denied | `tests/unit/api/test_api_auth_and_routes.py::test_cross_account_and_invalid_cursor_fail_without_private_detail`; `tests/unit/mcp/test_gateway.py::test_cross_account_access_is_safely_denied`; `tests/unit/analytics/test_portfolio.py::test_portfolio_rejects_cross_account_components` | `implemented_evidence` — both public protocols deny before returning private detail, and analytics rejects mixed-account inputs. Final release-SHA unit/security runs remain required. |
| 11 | Canary secrets are absent from logs, traces, errors, API/MCP/web output, and artifacts | `tests/security/test_secret_canary_acceptance.py::test_secret_canary_is_absent_from_api_mcp_errors_and_logs`; `tests/security/test_secret_canary_acceptance.py::test_secret_canary_scanner_covers_repository_and_available_web_artifacts`; `tests/unit/api/test_api_security_audit.py::test_denial_audits_never_capture_credentials_or_resource_ids`; `tests/unit/api/test_api_security_audit.py::test_default_structured_audit_log_is_redacted_and_schema_bounded`; `tests/unit/api/test_api_security_audit.py::test_audit_sink_failure_does_not_weaken_authentication_denial`; `tests/unit/security/test_secrets_and_redaction.py`; `tests/unit/trading212/test_client.py::test_successful_basic_auth_decimal_parse_and_redacted_logging`; `tests/security/test_mcp_security.py::test_internal_failure_and_hostile_correlation_value_are_structured_and_redacted`; `tests/security/test_architecture_foundation.py::test_repository_contains_no_high_confidence_secret`; `apps/web/tests/refresh-control.test.tsx` | `passed_working_tree` — controlled failure-path tests cover API, MCP, web, audit, provider, error, and build-output redaction. The runtime canary was absent from API/worker/MCP/web logs and from `/app` and `/opt/venv` in all four rebuilt images. This does not substitute for the pending final-SHA secret, dependency, Semgrep, and Trivy gates. |
| 12 | Non-GET/unknown provider capability is rejected before transport | `tests/unit/trading212/test_client.py::test_non_read_methods_fail_before_transport`; `tests/unit/trading212/test_allowlist.py::test_naive_transaction_time_and_unknown_query_fail_closed`; `tests/unit/mcp/test_gateway.py::test_unknown_input_and_unknown_tool_fail_before_application_dispatch`; `tests/security/test_architecture_foundation.py::test_trading212_production_boundary_is_statically_get_only` | `implemented_evidence` — transport spies remain untouched and static architecture rejects a generic/provider write surface. Final release-SHA unit/security runs remain required. |
| 13 | API/web/MCP return identical canonical values for the same fixture/cutoff | `tests/integration/test_api_mcp_postgres_parity.py::test_postgres_backed_api_and_mcp_return_identical_canonical_values`; browser files under `tests/e2e/web/`; `docs/implementation/evidence/api-backed-overview-desktop.png`; `docs/implementation/evidence/api-backed-quality-mobile.png` | `passed_working_tree` — the API and MCP returned the same canonical total, `248431.27` EUR, and the API-backed web rendered that value and the explicit `provider_history_coverage_gap`. Desktop/mobile browser inspection found no overflow or console errors. The retained screenshots show the API-backed overview and mobile quality state. |
| 14 | Process/container restart preserves state and safely resumes jobs | 14a: `tests/integration/test_worker_ingestion_store.py::test_scenario_14_outbox_dispatcher_restart_executes_committed_run_once` and `tests/integration/test_worker_ingestion_store.py::test_expired_ambiguous_dispatch_republishes_same_task_before_both_copies_are_consumed`; 14b: `tests/integration/test_worker_ingestion_store.py::test_confirmed_publication_is_terminal_until_worker_recovers` and `tests/integration/test_worker_ingestion_store.py::test_api_queue_persists_before_publish_and_worker_resumes_same_run`; 14c: retained Compose runtime record summarized below | `passed_working_tree` — the retained worker-restart and full-stack state-retention observations remain separate from the corrected API commit-before-publication/outbox-restart and ambiguous duplicate-delivery tests. Every subcase must pass again at the immutable release SHA before this row is release evidence. |

## Correction evidence bundles

The following bundles define the corrected Phase 1 predicates. Their presence is
implementation traceability, not a claim that the final release-head matrix has passed.

### Durable dispatch and idempotency

- Atomic run/outbox commit followed by dispatcher restart and one logical execution:
  `tests/integration/test_worker_ingestion_store.py::test_scenario_14_outbox_dispatcher_restart_executes_committed_run_once`.
- Broker acceptance followed by process interruption, expired-claim same-task-ID
  republication, both deliveries consumed, and one logical/economic result:
  `tests/integration/test_worker_ingestion_store.py::test_expired_ambiguous_dispatch_republishes_same_task_before_both_copies_are_consumed`.
- Fixed sanitized payload/deterministic task identity, durable metadata validation,
  two-dispatcher contention, bounded publish failure, expired-claim recovery, missing
  credentials, consumer failure terminalization, account-lease deferral, and readiness
  are exercised by the focused outbox cases in
  `tests/integration/test_worker_ingestion_store.py`,
  `tests/unit/worker/test_outbox_dispatcher.py`, and
  `tests/unit/worker/test_worker_configuration.py`.
- Account scoping, requested-versus-effective promotion, identical lifecycle retries,
  different-mode/scope conflict, and concurrent identical/mismatched requests are
  exercised by `tests/integration/test_worker_ingestion_store.py`,
  `tests/unit/application/test_ingestion.py`, and
  `tests/unit/api/test_api_auth_and_routes.py::test_refresh_idempotency_key_reuse_with_different_semantics_is_sanitized`.

### Stable complete collections and service contracts

- More-than-10,000 activity rows; records beyond ordinary 50/100-row pages; immutable
  position-snapshot traversal; newer activity/order/snapshot mutation; exact filtered
  totals; unheld instrument search; SQL filtering; and API/MCP values are covered by
  `tests/integration/test_stable_collection_queries.py::test_postgres_keysets_are_stable_beyond_ui_sized_collections`.
- Cursor integrity, lifetime, resource/scope/sort/filter binding, immutable membership,
  bounded expiry cleanup, and explicit capacity failure are covered by
  `tests/unit/application/test_queries.py` and
  `tests/integration/test_collection_query_snapshots.py`.
- Broker-connection authorization and safe credential state, canonical instrument
  lookup independent of positions, performance available/unavailable gates, and real
  data-quality scope are covered by `tests/unit/application/test_service_scope_enforcement.py`,
  `tests/unit/application/test_performance.py`,
  `tests/unit/api/test_api_auth_and_routes.py`, and
  `tests/integration/test_api_mcp_postgres_parity.py`.
- The exactly-nine-tool MCP registry, server-side position/transaction/dividend queries,
  direct snapshot lookup, bounded output, partial aggregation semantics, and API parity
  are covered by `tests/unit/mcp/test_gateway.py`, `tests/contract/test_mcp_contract.py`,
  and `tests/integration/test_api_mcp_postgres_parity.py`.
- Route-specific URL cursor/filter state, preview counts/largest-holding ordering,
  more-than-50-row navigation, browser back, mutation stability, accessibility, and
  desktop/mobile overflow are covered by `tests/e2e/web/collections.spec.ts`,
  `tests/e2e/web/quality-pagination.spec.ts`, and
  `tests/e2e/api-web/pagination-stability.spec.ts`.
- Migration evidence must run empty-to-head, repeated upgrade, downgrade policy, and ORM
  drift checks at head `20260901_0007`; the migration files themselves are not a pass.

## Remaining closure conditions

The following work remains mandatory before `P1-E2E-001` and the release can be
complete at an immutable SHA:

1. Preserve the distinction between scenario 8's retained synthetic acceptance fixture
   and real Trading 212 coverage. The synthetic mismatch path is passed; real-provider
   quantity/cash bridge coverage remains unavailable without a valid opening-history
   basis and must stay explicit rather than using an assumed opening balance.
2. Commit the candidate and rerun the complete locally executable matrix, including
   scenarios 8, 9, 11, 13, and 14, at the exact release SHA.
3. Complete the pushed-SHA CI security jobs. External Demo, HTTPS/OAuth, and ChatGPT
   validation remain separate blocked gates.

## Retained scenario 14b/14c runtime record

This retained observation covers the original worker restart after successful API
publication and full-stack state retention. It does **not** cover scenario 14a's API
commit-before-publication crash window; that predicate is supplied by the durable-outbox
test bundle above and still requires the final release-SHA run.

The current working-tree runtime used Compose project
`t212pi_phase1_final_20260831` with loopback host ports PostgreSQL `25432`, Redis
`26379`, API `28000`, MCP `28001`, and web `23000`. Rebuilt image IDs were API
`6f77d1324278`, worker `9487a06c3a18`, MCP `0f91ab24cddd`, and web
`a60e2a057146`; every application container ran as UID `10001` and reported healthy.

The clean seeded baseline counts were:

```text
source_records=10 source_occurrences=10 snapshots=1 runs=1 transactions=2 positions=1
```

The worker was stopped before an authenticated all/incremental/snapshot refresh with
idempotency key `phase1-runtime-restart-20260901` was submitted. Run
`5b32bbfd-cd5e-45ae-8e6b-8845ec0cf676` remained `queued` in PostgreSQL, then reached
`succeeded` after the worker restarted. Counts became:

```text
source_records=11 source_occurrences=20 snapshots=2 runs=2 transactions=2 positions=1
```

The additional source row is refreshed metadata; economic transaction and position
counts did not duplicate. After stopping and restarting API, MCP, web, worker,
PostgreSQL, and Redis without deleting volumes, the counts remained
`11|20|2|2|2|1`. The canonical API summary SHA-256 remained
`81fc4f21d76b0a2f4e80d3cba3ee32afc670ab150f997d630c520372cc09c391`, and API/MCP
totals remained exactly `248431.27` EUR. This is retained working-tree evidence and
must be repeated at the release SHA.

## Consolidated execution commands

The evidence guard checks that this ledger remains synchronized with the manifest and
that every cited test node exists:

```bash
uv run pytest tests/contract/test_phase1_scenario_evidence.py
```

The guard is a traceability check, not a substitute for executing the cited tests. The
current locally executable evidence set is exercised by:

```bash
uv run pytest \
  tests/unit/application/test_ingestion.py \
  tests/unit/application/test_phase1_ingestion_acceptance.py \
  tests/unit/application/test_performance.py \
  tests/unit/application/test_queries.py \
  tests/unit/application/test_service_scope_enforcement.py \
  tests/unit/analytics/test_phase1_scenarios.py \
  tests/unit/analytics/test_portfolio.py \
  tests/unit/analytics/test_reconciliation.py \
  tests/unit/trading212/test_allowlist.py \
  tests/unit/trading212/test_client.py \
  tests/unit/security/test_secrets_and_redaction.py \
  tests/unit/api/test_api_auth_and_routes.py \
  tests/unit/api/test_api_security_audit.py \
  tests/unit/mcp/test_gateway.py \
  tests/unit/worker/test_outbox_dispatcher.py \
  tests/unit/worker/test_worker_configuration.py \
  tests/security/test_architecture_foundation.py \
  tests/security/test_mcp_security.py

TEST_DATABASE_URL="postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio" \
  uv run pytest \
  tests/integration/test_worker_ingestion_store.py \
  tests/integration/test_worker_materialization.py \
  tests/integration/test_phase1_synthetic_acceptance.py \
  tests/integration/test_accounting_repositories.py \
  tests/integration/test_api_mcp_postgres_parity.py \
  tests/integration/test_collection_query_snapshots.py \
  tests/integration/test_stable_collection_queries.py

corepack pnpm --filter @trading212/web test:e2e
```

The final result must report each layer independently. All fourteen scenarios have
complete working-tree evidence, but no working-tree result substitutes for the immutable
release-SHA rerun. Scenario 8's synthetic pass also must not be generalized into a claim
that real Trading 212 opening-history coverage exists.
