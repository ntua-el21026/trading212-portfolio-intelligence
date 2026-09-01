"""Strict traceability guard for the validated Phase 1 scenario ledger."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs/implementation/PHASE_1_EXECUTION_MANIFEST.md"
LEDGER = ROOT / "docs/implementation/PHASE_1_SCENARIO_EVIDENCE.md"
REPORT = ROOT / "VALIDATION_REPORT.md"
SHA = "e13916eca34d8e3be1ed130248d6c3d1ed7e3869"


@dataclass(frozen=True, slots=True)
class ScenarioEvidence:
    scenario_id: int
    expected_text: str
    state: str
    nodes: tuple[str, ...]


def node(path: str, name: str) -> str:
    return f"{path}::{name}"


I = "tests/integration/"  # noqa: E741
U = "tests/unit/"
S = "tests/security/"
E = "tests/e2e/api-web/"
API_BACKED_OVERVIEW_NODE = node(
    E + "reconciliation.spec.ts",
    "API-backed overview renders canonical 248431.27 EUR",
)
CONFIRMED_PUBLICATION_RECOVERY_NODE = node(
    I + "test_worker_ingestion_store.py",
    "test_confirmed_publication_is_terminal_until_worker_recovers",
)
SCENARIOS = (
    ScenarioEvidence(
        1,
        "Fresh account ingestion and canonical snapshot.",
        "complete",
        (
            node(
                I + "test_worker_materialization.py",
                "test_seed_and_refreshes_materialize_changed_and_empty_current_state",
            ),
        ),
    ),
    ScenarioEvidence(
        2,
        "Repeated identical refresh creates no duplicate economic records.",
        "complete",
        (
            node(
                I + "test_phase1_synthetic_acceptance.py",
                "test_identical_production_refresh_does_not_duplicate_economic_records",
            ),
            node(
                I + "test_worker_ingestion_store.py",
                "test_postgres_refresh_is_coalesced_idempotent_and_retains_revisions",
            ),
        ),
    ),
    ScenarioEvidence(
        3,
        "Incremental refresh adds one transaction, dividend, and position change.",
        "complete",
        (
            node(
                I + "test_phase1_synthetic_acceptance.py",
                "test_incremental_production_refresh_adds_transaction_dividend_and_position_change",
            ),
        ),
    ),
    ScenarioEvidence(
        4,
        "Transient provider failure retries and recovers within budget.",
        "complete",
        (
            node(
                I + "test_phase1_synthetic_acceptance.py",
                "test_transient_failure_reuses_durable_run_and_recovers_within_retry_budget",
            ),
            node(
                U + "worker/test_worker_configuration.py",
                "test_retryable_economic_failure_defers_durably_without_celery_retry_publication",
            ),
            node(U + "trading212/test_client.py", "test_retry_exhaustion_sanitizes_provider_body"),
        ),
    ),
    ScenarioEvidence(
        5,
        "Rate limit pauses and resumes safely.",
        "complete",
        (
            node(
                I + "test_worker_materialization.py",
                "test_redis_rate_limit_waits_and_duplicate_page_is_idempotently_persisted",
            ),
            node(
                U + "application/test_phase1_ingestion_acceptance.py",
                "test_rate_limited_page_pauses_then_resumes_and_commits_successfully",
            ),
            node(U + "trading212/test_client.py", "test_rate_limit_retries_are_bounded"),
        ),
    ),
    ScenarioEvidence(
        6,
        "One capability fails and aggregate state becomes explicitly partial.",
        "complete",
        (
            node(
                I + "test_api_mcp_postgres_parity.py",
                "test_postgres_backed_api_and_mcp_return_identical_canonical_values",
            ),
            node(
                U + "application/test_ingestion.py",
                "test_partial_capability_failure_never_reports_success",
            ),
            node(
                U + "analytics/test_phase1_scenarios.py",
                "test_partial_capability_output_degrades_only_dependent_portfolio_metric",
            ),
        ),
    ),
    ScenarioEvidence(
        7,
        "Schema incompatibility fails the atomic unit and does not advance checkpoint.",
        "complete",
        (
            node(
                U + "application/test_phase1_ingestion_acceptance.py",
                "test_schema_incompatible_page_preserves_last_atomic_checkpoint",
            ),
            node(
                U + "trading212/test_client.py",
                "test_malformed_or_missing_contract_data_fails_closed",
            ),
            node(
                I + "test_worker_ingestion_store.py",
                "test_failed_page_transaction_does_not_advance_checkpoint",
            ),
        ),
    ),
    ScenarioEvidence(
        8,
        "Quantity/cash mismatch is persisted and visible as unreconciled.",
        "complete_synthetic",
        (
            node(
                I + "test_api_mcp_postgres_parity.py",
                "test_postgres_backed_api_and_mcp_return_identical_canonical_values",
            ),
        ),
    ),
    ScenarioEvidence(
        9,
        "Multi-currency valuation uses sourced FX and degrades explicitly when FX is missing.",
        "complete",
        (
            node(
                I + "test_worker_materialization.py",
                "test_provider_wallet_currency_is_retained_and_missing_fx_fails_closed",
            ),
            node(
                U + "analytics/test_portfolio.py",
                "test_multi_currency_aggregation_uses_explicit_fx_and_weights_reconcile",
            ),
            node(
                U + "analytics/test_portfolio.py",
                "test_missing_or_post_cutoff_fx_is_not_treated_as_one_or_zero",
            ),
        ),
    ),
    ScenarioEvidence(
        10,
        "Unauthorized cross-owner/account API and MCP access is denied.",
        "complete",
        (
            node(
                U + "api/test_api_auth_and_routes.py",
                "test_cross_account_and_invalid_cursor_fail_without_private_detail",
            ),
            node(U + "mcp/test_gateway.py", "test_cross_account_access_is_safely_denied"),
            node(
                U + "analytics/test_portfolio.py", "test_portfolio_rejects_cross_account_components"
            ),
        ),
    ),
    ScenarioEvidence(
        11,
        "Canary secrets are absent from logs, traces, errors, API/MCP/web output, and artifacts.",
        "complete",
        (
            node(
                U + "api/test_api_security_audit.py",
                "test_denial_audits_never_capture_credentials_or_resource_ids",
            ),
            node(
                U + "api/test_api_security_audit.py",
                "test_default_structured_audit_log_is_redacted_and_schema_bounded",
            ),
            node(
                U + "api/test_api_security_audit.py",
                "test_audit_sink_failure_does_not_weaken_authentication_denial",
            ),
            node(
                U + "trading212/test_client.py",
                "test_successful_basic_auth_decimal_parse_and_redacted_logging",
            ),
            node(
                S + "test_mcp_security.py",
                "test_internal_failure_and_hostile_correlation_value_are_structured_and_redacted",
            ),
            node(
                S + "test_architecture_foundation.py",
                "test_repository_contains_no_high_confidence_secret",
            ),
        ),
    ),
    ScenarioEvidence(
        12,
        "Non-GET/unknown provider capability is rejected before transport.",
        "complete",
        (
            node(U + "trading212/test_client.py", "test_non_read_methods_fail_before_transport"),
            node(
                U + "trading212/test_allowlist.py",
                "test_naive_transaction_time_and_unknown_query_fail_closed",
            ),
            node(
                U + "mcp/test_gateway.py",
                "test_unknown_input_and_unknown_tool_fail_before_application_dispatch",
            ),
            node(
                S + "test_architecture_foundation.py",
                "test_trading212_production_boundary_is_statically_get_only",
            ),
        ),
    ),
    ScenarioEvidence(
        13,
        "API/web/MCP return identical canonical values for the same fixture/cutoff.",
        "complete",
        (
            node(
                I + "test_api_mcp_postgres_parity.py",
                "test_postgres_backed_api_and_mcp_return_identical_canonical_values",
            ),
            API_BACKED_OVERVIEW_NODE,
        ),
    ),
    ScenarioEvidence(
        14,
        "Process/container restart preserves state and safely resumes jobs.",
        "complete",
        (
            node(
                I + "test_worker_ingestion_store.py",
                "test_api_queue_persists_before_publish_and_worker_resumes_same_run",
            ),
            node(
                I + "test_worker_ingestion_store.py",
                "test_scenario_14_outbox_dispatcher_restart_executes_committed_run_once",
            ),
            node(
                I + "test_worker_ingestion_store.py",
                "test_dispatcher_restart_reconciles_consumer_observed_terminal_delivery_without_redelivery",
            ),
            node(
                I + "test_worker_ingestion_store.py",
                "test_expired_ambiguous_dispatch_republishes_same_task_before_both_copies_are_consumed",
            ),
            CONFIRMED_PUBLICATION_RECOVERY_NODE,
        ),
    ),
)


def manifest_scenarios() -> tuple[tuple[int, str], ...]:
    section = (
        MANIFEST.read_text(encoding="utf-8")
        .split("## Mandatory synthetic end-to-end scenarios", 1)[1]
        .split("## External gates", 1)[0]
    )
    return tuple(
        (int(m.group("id")), m.group("text").strip())
        for m in re.finditer(r"^(?P<id>\d+)\. (?P<text>.+)$", section, re.MULTILINE)
    )


def test_evidence_ledger_tracks_authoritative_scenarios_exactly() -> None:
    assert manifest_scenarios() == tuple((x.scenario_id, x.expected_text) for x in SCENARIOS)
    assert tuple(x.scenario_id for x in SCENARIOS) == tuple(range(1, 15))


def test_every_cited_test_node_exists_and_is_ledgered() -> None:
    ledger = LEDGER.read_text(encoding="utf-8")
    for scenario in SCENARIOS:
        for cited in scenario.nodes:
            path_text, function_name = cited.split("::", 1)
            path = ROOT / path_text
            assert path.is_file(), f"scenario {scenario.scenario_id}: missing {path_text}"
            if path.suffix == ".py":
                declaration = rf"^(?:async )?def {re.escape(function_name)}\("
            elif path.suffix in {".ts", ".tsx"}:
                declaration = rf'^test\("{re.escape(function_name)}",'
            else:
                raise AssertionError(
                    f"scenario {scenario.scenario_id}: unsupported evidence node {cited}"
                )
            assert re.search(
                declaration,
                path.read_text(encoding="utf-8"),
                re.MULTILINE,
            ), f"scenario {scenario.scenario_id}: missing node {cited}"
            assert cited in ledger, f"scenario {scenario.scenario_id}: ledger omits {cited}"
    assert API_BACKED_OVERVIEW_NODE in SCENARIOS[12].nodes
    assert CONFIRMED_PUBLICATION_RECOVERY_NODE in SCENARIOS[13].nodes


def test_final_states_validated_evidence_and_external_limit_are_explicit() -> None:
    assert {x.scenario_id for x in SCENARIOS if x.state == "complete"} == set(range(1, 15)) - {8}
    assert {x.scenario_id for x in SCENARIOS if x.state == "complete_synthetic"} == {8}
    ledger = LEDGER.read_text(encoding="utf-8")
    report = REPORT.read_text(encoding="utf-8")
    for text in (ledger, report):
        for token in (SHA, "338", "64", "84%", "20260901_0007"):
            assert token in text
    for run_id in ("33562745986", "33562746060", "33562746052"):
        assert run_id in report
    for token in (
        "14a",
        "14b",
        "14c",
        "atomic outbox crash window",
        "P1-EXT-004",
        "unavailable_explicit",
        "opening-history basis",
    ):
        assert token in ledger
