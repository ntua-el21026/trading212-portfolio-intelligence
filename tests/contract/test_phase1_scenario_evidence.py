"""Traceability guard for the fourteen mandatory Phase 1 synthetic scenarios.

This module validates the evidence ledger; it intentionally does not pretend to execute
the scenario behaviors referenced by that ledger.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs/implementation/PHASE_1_EXECUTION_MANIFEST.md"
LEDGER = ROOT / "docs/implementation/PHASE_1_SCENARIO_EVIDENCE.md"


@dataclass(frozen=True, slots=True)
class ScenarioEvidence:
    scenario_id: int
    expected_text: str
    state: str
    nodes: tuple[str, ...]


SCENARIOS = (
    ScenarioEvidence(
        1,
        "Fresh account ingestion and canonical snapshot.",
        "implemented_evidence",
        (
            "tests/integration/test_worker_materialization.py::"
            "test_seed_and_refreshes_materialize_changed_and_empty_current_state",
        ),
    ),
    ScenarioEvidence(
        2,
        "Repeated identical refresh creates no duplicate economic records.",
        "implemented_evidence",
        (
            "tests/integration/test_phase1_synthetic_acceptance.py::"
            "test_identical_production_refresh_does_not_duplicate_economic_records",
            "tests/integration/test_worker_ingestion_store.py::"
            "test_postgres_refresh_is_coalesced_idempotent_and_retains_revisions",
        ),
    ),
    ScenarioEvidence(
        3,
        "Incremental refresh adds one transaction, dividend, and position change.",
        "implemented_evidence",
        (
            "tests/integration/test_phase1_synthetic_acceptance.py::"
            "test_incremental_production_refresh_adds_transaction_dividend_and_position_change",
        ),
    ),
    ScenarioEvidence(
        4,
        "Transient provider failure retries and recovers within budget.",
        "implemented_evidence",
        (
            "tests/integration/test_phase1_synthetic_acceptance.py::"
            "test_transient_failure_reuses_durable_run_and_recovers_within_retry_budget",
            "tests/unit/worker/test_worker_configuration.py::"
            "test_celery_refresh_retries_once_after_retryable_refresh_error",
            "tests/unit/trading212/test_client.py::test_retry_exhaustion_sanitizes_provider_body",
        ),
    ),
    ScenarioEvidence(
        5,
        "Rate limit pauses and resumes safely.",
        "implemented_evidence",
        (
            "tests/integration/test_worker_materialization.py::"
            "test_redis_rate_limit_waits_and_duplicate_page_is_idempotently_persisted",
            "tests/unit/application/test_phase1_ingestion_acceptance.py::"
            "test_rate_limited_page_pauses_then_resumes_and_commits_successfully",
            "tests/unit/trading212/test_client.py::test_rate_limit_retries_are_bounded",
        ),
    ),
    ScenarioEvidence(
        6,
        "One capability fails and aggregate state becomes explicitly partial.",
        "implemented_evidence",
        (
            "tests/integration/test_api_mcp_postgres_parity.py::"
            "test_postgres_backed_api_and_mcp_return_identical_canonical_values",
            "tests/unit/application/test_ingestion.py::"
            "test_partial_capability_failure_never_reports_success",
            "tests/unit/analytics/test_phase1_scenarios.py::"
            "test_partial_capability_output_degrades_only_dependent_portfolio_metric",
        ),
    ),
    ScenarioEvidence(
        7,
        "Schema incompatibility fails the atomic unit and does not advance checkpoint.",
        "implemented_evidence",
        (
            "tests/unit/application/test_phase1_ingestion_acceptance.py::"
            "test_schema_incompatible_page_preserves_last_atomic_checkpoint",
            "tests/unit/trading212/test_client.py::"
            "test_malformed_or_missing_contract_data_fails_closed",
            "tests/integration/test_worker_ingestion_store.py::"
            "test_failed_page_transaction_does_not_advance_checkpoint",
        ),
    ),
    ScenarioEvidence(
        8,
        "Quantity/cash mismatch is persisted and visible as unreconciled.",
        "passed_working_tree",
        (
            "tests/integration/test_api_mcp_postgres_parity.py::"
            "test_postgres_backed_api_and_mcp_return_identical_canonical_values",
        ),
    ),
    ScenarioEvidence(
        9,
        "Multi-currency valuation uses sourced FX and degrades explicitly when FX is missing.",
        "passed_working_tree",
        (
            "tests/integration/test_worker_materialization.py::"
            "test_provider_wallet_currency_is_retained_and_missing_fx_fails_closed",
            "tests/unit/analytics/test_portfolio.py::"
            "test_multi_currency_aggregation_uses_explicit_fx_and_weights_reconcile",
            "tests/unit/analytics/test_portfolio.py::"
            "test_missing_or_post_cutoff_fx_is_not_treated_as_one_or_zero",
        ),
    ),
    ScenarioEvidence(
        10,
        "Unauthorized cross-owner/account API and MCP access is denied.",
        "implemented_evidence",
        (
            "tests/unit/api/test_api_auth_and_routes.py::"
            "test_cross_account_and_invalid_cursor_fail_without_private_detail",
            "tests/unit/mcp/test_gateway.py::test_cross_account_access_is_safely_denied",
            "tests/unit/analytics/test_portfolio.py::"
            "test_portfolio_rejects_cross_account_components",
        ),
    ),
    ScenarioEvidence(
        11,
        ("Canary secrets are absent from logs, traces, errors, API/MCP/web output, and artifacts."),
        "passed_working_tree",
        (
            "tests/unit/api/test_api_security_audit.py::"
            "test_denial_audits_never_capture_credentials_or_resource_ids",
            "tests/unit/api/test_api_security_audit.py::"
            "test_default_structured_audit_log_is_redacted_and_schema_bounded",
            "tests/unit/api/test_api_security_audit.py::"
            "test_audit_sink_failure_does_not_weaken_authentication_denial",
            "tests/unit/trading212/test_client.py::"
            "test_successful_basic_auth_decimal_parse_and_redacted_logging",
            "tests/security/test_mcp_security.py::"
            "test_internal_failure_and_hostile_correlation_value_are_structured_and_redacted",
            "tests/security/test_architecture_foundation.py::"
            "test_repository_contains_no_high_confidence_secret",
        ),
    ),
    ScenarioEvidence(
        12,
        "Non-GET/unknown provider capability is rejected before transport.",
        "implemented_evidence",
        (
            "tests/unit/trading212/test_client.py::test_non_read_methods_fail_before_transport",
            "tests/unit/trading212/test_allowlist.py::"
            "test_naive_transaction_time_and_unknown_query_fail_closed",
            "tests/unit/mcp/test_gateway.py::"
            "test_unknown_input_and_unknown_tool_fail_before_application_dispatch",
            "tests/security/test_architecture_foundation.py::"
            "test_trading212_production_boundary_is_statically_get_only",
        ),
    ),
    ScenarioEvidence(
        13,
        "API/web/MCP return identical canonical values for the same fixture/cutoff.",
        "passed_working_tree",
        (
            "tests/integration/test_api_mcp_postgres_parity.py::"
            "test_postgres_backed_api_and_mcp_return_identical_canonical_values",
        ),
    ),
    ScenarioEvidence(
        14,
        "Process/container restart preserves state and safely resumes jobs.",
        "passed_working_tree",
        (
            "tests/integration/test_worker_ingestion_store.py::"
            "test_api_queue_persists_before_publish_and_worker_resumes_same_run",
        ),
    ),
)


def _manifest_scenarios() -> tuple[tuple[int, str], ...]:
    text = MANIFEST.read_text(encoding="utf-8")
    section = text.split("## Mandatory synthetic end-to-end scenarios", maxsplit=1)[1]
    section = section.split("## External gates", maxsplit=1)[0]
    return tuple(
        (int(match.group("id")), match.group("text").strip())
        for match in re.finditer(
            r"^(?P<id>\d+)\. (?P<text>.+)$",
            section,
            flags=re.MULTILINE,
        )
    )


def test_evidence_ledger_tracks_the_authoritative_fourteen_scenarios_exactly() -> None:
    expected = tuple((item.scenario_id, item.expected_text) for item in SCENARIOS)
    assert _manifest_scenarios() == expected
    assert tuple(item.scenario_id for item in SCENARIOS) == tuple(range(1, 15))


def test_every_cited_python_test_node_exists() -> None:
    for scenario in SCENARIOS:
        for node in scenario.nodes:
            path_text, function_name = node.split("::", maxsplit=1)
            path = ROOT / path_text
            assert path.is_file(), f"scenario {scenario.scenario_id}: missing {path_text}"
            source = path.read_text(encoding="utf-8")
            assert re.search(
                rf"^(?:async )?def {re.escape(function_name)}\(",
                source,
                flags=re.MULTILINE,
            ), f"scenario {scenario.scenario_id}: missing node {node}"


def test_ledger_states_are_explicit_and_working_tree_evidence_is_qualified() -> None:
    ledger = LEDGER.read_text(encoding="utf-8")
    allowed_states = {
        "implemented_evidence",
        "partial_evidence",
        "missing_test",
        "runtime_pending",
        "passed_working_tree",
    }
    assert {item.state for item in SCENARIOS} <= allowed_states
    assert {item.scenario_id for item in SCENARIOS if item.state == "implemented_evidence"} == {
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        10,
        12,
    }
    assert not {item.scenario_id for item in SCENARIOS if item.state == "missing_test"}
    assert not {item.scenario_id for item in SCENARIOS if item.state == "runtime_pending"}
    assert {item.scenario_id for item in SCENARIOS if item.state == "passed_working_tree"} == {
        8,
        9,
        11,
        13,
        14,
    }
    for item in SCENARIOS:
        assert f"| {item.scenario_id} |" in ledger
        assert f"`{item.state}`" in ledger
    normalized_ledger = " ".join(ledger.split())
    assert "All fourteen scenarios have complete working-tree evidence" in normalized_ledger
    assert "no working-tree result substitutes for the immutable release-SHA rerun" in (
        normalized_ledger
    )
