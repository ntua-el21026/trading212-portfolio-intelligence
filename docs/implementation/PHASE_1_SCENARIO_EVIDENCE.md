# Phase 1 Mandatory Scenario Evidence

**Authority:** `docs/implementation/PHASE_1_EXECUTION_MANIFEST.md`
**Validated implementation SHA:** `bba71749096cecbe8732d60e2b5bb1e44c394b7c`
**Status:** Complete synthetic evidence

This ledger maps the fourteen mandatory synthetic outcomes to executable evidence. All
rows are complete at the validated SHA; the ledger does not claim real-provider history
where the required provider evidence is unavailable.

| # | Mandatory outcome | Exact evidence | State |
|---:|---|---|---|
| 1 | Fresh account ingestion and canonical snapshot | `tests/integration/test_worker_materialization.py::test_seed_and_refreshes_materialize_changed_and_empty_current_state` | `complete` |
| 2 | Repeated identical refresh creates no duplicate economic records | `tests/integration/test_phase1_synthetic_acceptance.py::test_identical_production_refresh_does_not_duplicate_economic_records`; `tests/integration/test_worker_ingestion_store.py::test_postgres_refresh_is_coalesced_idempotent_and_retains_revisions` | `complete` |
| 3 | Incremental refresh adds one transaction, dividend, and position change | `tests/integration/test_phase1_synthetic_acceptance.py::test_incremental_production_refresh_adds_transaction_dividend_and_position_change` | `complete` |
| 4 | Transient provider failure retries and recovers within budget | `tests/integration/test_phase1_synthetic_acceptance.py::test_transient_failure_reuses_durable_run_and_recovers_within_retry_budget`; `tests/unit/worker/test_worker_configuration.py::test_retryable_economic_failure_defers_durably_without_celery_retry_publication`; `tests/unit/trading212/test_client.py::test_retry_exhaustion_sanitizes_provider_body` | `complete` |
| 5 | Rate limit pauses and resumes safely | `tests/integration/test_worker_materialization.py::test_redis_rate_limit_waits_and_duplicate_page_is_idempotently_persisted`; `tests/unit/application/test_phase1_ingestion_acceptance.py::test_rate_limited_page_pauses_then_resumes_and_commits_successfully`; `tests/unit/trading212/test_client.py::test_rate_limit_retries_are_bounded` | `complete` |
| 6 | One capability fails and aggregate state becomes explicitly partial | `tests/integration/test_api_mcp_postgres_parity.py::test_postgres_backed_api_and_mcp_return_identical_canonical_values`; `tests/unit/application/test_ingestion.py::test_partial_capability_failure_never_reports_success`; `tests/unit/analytics/test_phase1_scenarios.py::test_partial_capability_output_degrades_only_dependent_portfolio_metric` | `complete` |
| 7 | Schema incompatibility fails the atomic unit and does not advance checkpoint | `tests/unit/application/test_phase1_ingestion_acceptance.py::test_schema_incompatible_page_preserves_last_atomic_checkpoint`; `tests/unit/trading212/test_client.py::test_malformed_or_missing_contract_data_fails_closed`; `tests/integration/test_worker_ingestion_store.py::test_failed_page_transaction_does_not_advance_checkpoint` | `complete` |
| 8 | Quantity/cash mismatch is persisted and visible as unreconciled | `tests/integration/test_api_mcp_postgres_parity.py::test_postgres_backed_api_and_mcp_return_identical_canonical_values` | `complete_synthetic` |
| 9 | Multi-currency valuation uses sourced FX and degrades explicitly when FX is missing | `tests/integration/test_worker_materialization.py::test_provider_wallet_currency_is_retained_and_missing_fx_fails_closed`; `tests/unit/analytics/test_portfolio.py::test_multi_currency_aggregation_uses_explicit_fx_and_weights_reconcile`; `tests/unit/analytics/test_portfolio.py::test_missing_or_post_cutoff_fx_is_not_treated_as_one_or_zero` | `complete` |
| 10 | Unauthorized cross-owner/account API and MCP access is denied | `tests/unit/api/test_api_auth_and_routes.py::test_cross_account_and_invalid_cursor_fail_without_private_detail`; `tests/unit/mcp/test_gateway.py::test_cross_account_access_is_safely_denied`; `tests/unit/analytics/test_portfolio.py::test_portfolio_rejects_cross_account_components` | `complete` |
| 11 | Canary secrets are absent from logs, traces, errors, API/MCP/web output, and artifacts | `tests/unit/api/test_api_security_audit.py::test_denial_audits_never_capture_credentials_or_resource_ids`; `tests/unit/api/test_api_security_audit.py::test_default_structured_audit_log_is_redacted_and_schema_bounded`; `tests/unit/api/test_api_security_audit.py::test_audit_sink_failure_does_not_weaken_authentication_denial`; `tests/unit/trading212/test_client.py::test_successful_basic_auth_decimal_parse_and_redacted_logging`; `tests/security/test_mcp_security.py::test_internal_failure_and_hostile_correlation_value_are_structured_and_redacted`; `tests/security/test_architecture_foundation.py::test_repository_contains_no_high_confidence_secret` | `complete` |
| 12 | Non-GET/unknown provider capability is rejected before transport | `tests/unit/trading212/test_client.py::test_non_read_methods_fail_before_transport`; `tests/unit/trading212/test_allowlist.py::test_naive_transaction_time_and_unknown_query_fail_closed`; `tests/unit/mcp/test_gateway.py::test_unknown_input_and_unknown_tool_fail_before_application_dispatch`; `tests/security/test_architecture_foundation.py::test_trading212_production_boundary_is_statically_get_only` | `complete` |
| 13 | API/web/MCP return identical canonical values for the same fixture/cutoff | `tests/integration/test_api_mcp_postgres_parity.py::test_postgres_backed_api_and_mcp_return_identical_canonical_values`; `tests/e2e/api-web/reconciliation.spec.ts::API-backed overview renders canonical 248431.27 EUR` | `complete` |
| 14 | Process/container restart preserves state and safely resumes jobs | `tests/integration/test_worker_ingestion_store.py::test_api_queue_persists_before_publish_and_worker_resumes_same_run`; `tests/integration/test_worker_ingestion_store.py::test_scenario_14_outbox_dispatcher_restart_executes_committed_run_once`; `tests/integration/test_worker_ingestion_store.py::test_dispatcher_restart_reconciles_consumer_observed_terminal_delivery_without_redelivery`; `tests/integration/test_worker_ingestion_store.py::test_expired_ambiguous_dispatch_republishes_same_task_before_both_copies_are_consumed`; `tests/integration/test_worker_ingestion_store.py::test_confirmed_publication_is_terminal_until_worker_recovers` | `complete` |

## Scenario 14 separate predicates

### 14a: atomic outbox crash window

`tests/integration/test_worker_ingestion_store.py::test_scenario_14_outbox_dispatcher_restart_executes_committed_run_once`
proves that the API transaction atomically commits the durable run and its dispatch
event. A dispatcher restart after that commit but before publication recovers the event
and produces one logical execution. The related
`test_expired_ambiguous_dispatch_republishes_same_task_before_both_copies_are_consumed`
test covers ambiguous broker acceptance and duplicate delivery reconciliation.

### 14b: confirmed publication followed by worker recovery

`tests/integration/test_worker_ingestion_store.py::test_confirmed_publication_is_terminal_until_worker_recovers`
proves that a confirmed publication remains terminal while the worker is unavailable,
that periodic dispatcher cycles do not redeliver it, and that the recovered worker later
executes the original deterministic task. The corrected Compose observation below also
stopped the worker, confirmed a published outbox row and broker depth of one, restarted
the worker, and observed the same run succeed. This predicate is separate from 14a and
is not used to infer the atomic commit-before-publication crash window.

### 14c: full-stack retention observation

The corrected runtime observation restarts the full service set without deleting its
authoritative volume. It verifies canonical counts, API/MCP/web parity, and the canonical
summary hash after restart. It is an operational retention predicate, separate from both
14a's atomic crash window and 14b's confirmed-publication worker-recovery predicate.

## Correction evidence bundles

- Durable dispatch: fixed non-secret task metadata, two-dispatcher contention, bounded
  publish failure, expired-claim recovery, consumer terminalization, account-lease
  deferral, and readiness are covered by `tests/integration/test_worker_ingestion_store.py`,
  `tests/unit/worker/test_outbox_dispatcher.py`, and
  `tests/unit/worker/test_worker_configuration.py`.
- Stable collections: immutable membership, cursor integrity/lifetime, SQL filtering,
  exact totals, mutation stability, and browser back navigation are covered by the
  collection-query integration/unit tests and desktop/mobile Playwright suites.
- Migrations: empty-to-head, repeat upgrade, migration tests, and ORM drift validation
  reached `20260901_0007`.

## Corrected Scenario 14b/14c Compose record

On 2026-09-01, isolated project `t212pi_phase1_corrected_20260901` built and started the
corrected PostgreSQL, Redis, API, worker, dispatcher, MCP, and web topology from a new
named volume and unique loopback ports. Migration and seed one-shots exited zero at
`20260901_0007`; repeating both operations preserved the exact seeded counts
`10|10|1|1|2|1|1|2|1|1|3` for source records, source occurrences, snapshots, ingestion
runs, transactions, cash flows, dividends, order observations, position observations,
cash observations, and ledger entries.

For 14b, the worker was stopped before the refresh request. The API committed run
`1b092b41-5037-4066-910f-6edcf2546862`; the independent dispatcher then recorded one
published outbox event with one attempt while Redis broker depth was one. Restarting the
worker completed that same run. Repeating the identical semantic request returned the
same run ID, retained exactly one logical run/outbox event/publication attempt, and left
counts unchanged at `11|20|2|2|2|1|1|2|1|1|3`.

For separate 14c coverage, all seven long-running services were stopped and restarted
without deleting the PostgreSQL volume. Counts remained
`11|20|2|2|2|1|1|2|1|1|3`; the canonical API summary SHA-256 remained
`3384103de93e8958c414db023e45131cfac8ea6de58629337f96ac8609b91566`; API and MCP
canonical fields remained identical at total value `248431.27` EUR; and the web rendered
`248,431.27 EUR`. The nine-tool MCP registry was unchanged. Dispatcher readiness was
`1`, pending outbox and undeliverable-run gauges returned to `0`, and no queued run lacked
a deliverable/terminal event.

All five application processes ran as UID `10001` with read-only root filesystems,
all capabilities dropped, `no-new-privileges`, and no runtime package manager; PostgreSQL
and Redis ran as their unprivileged service users. The injected runtime canary was absent
from five application logs/filesystems and API/MCP/web artifacts (14 paths checked).
This 14b/14c observation remains separate from 14a's automated API-commit-before-
publication crash-window evidence.

## Consolidated commands

```bash
uv run pytest tests/contract/test_phase1_scenario_evidence.py
make test-coverage
corepack pnpm --filter @trading212/web exec playwright test
corepack pnpm --filter @trading212/web exec playwright test --config playwright.api.config.ts
```

## Validated execution summary

- 335 isolated Python tests and 64 migration/integration tests passed with 84% combined
  branch coverage.
- 22 web unit tests, 32 synthetic desktop/mobile Playwright tests, and 6 API-backed
  desktop/mobile Playwright tests passed.
- Migrations were validated through `20260901_0007`.

## Explicit real-provider limitation

Scenario 8 is a retained synthetic acceptance fixture only. `P1-EXT-004` remains
`unavailable_explicit` because a real-provider opening-history basis for quantity/cash
bridge validation is unavailable. No opening balance is assumed or fabricated.
