"""Frozen report surface and finite proof unions generate deterministically."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast, get_args

import pytest
from trading212_api_contracts import reports as wire
from trading212_api_contracts.typescript import ReportClientGenerator, render_report_client
from trading212_domain import reports as domain

pytestmark = pytest.mark.contract


def contract() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(Path("packages/api-contracts/openapi/phase1-v1.json").read_text()),
    )


def test_report_surface_is_exact_and_generated_deterministically() -> None:
    source = contract()
    operations = {
        operation["operationId"]
        for methods in source["paths"].values()
        for operation in methods.values()
        if "reports" in operation.get("tags", [])
    }
    assert operations == {
        "generate_portfolio_report",
        "get_report_status",
        "list_reports",
        "get_report_manifest",
        "create_report_download_grant",
        "download_report_artifact",
        "create_portfolio_export",
        "list_portfolio_exports",
        "get_export_status",
        "create_export_download_grant",
        "download_export_artifact",
    }
    rendered = render_report_client(source)
    assert all(f"async {name}(" in rendered for name in operations)
    assert rendered == render_report_client(copy.deepcopy(source))
    assert "z.any(" not in rendered and "z.unknown(" not in rendered
    assert 'z.discriminatedUnion("kind"' in rendered
    assert "options: ReportGrantOptions = {}" in rendered
    assert "options: ReportDownloadOptions" in rendered
    assert "Promise<ReportArtifactResponse>" in rendered


@pytest.mark.parametrize(
    "name",
    [
        "ReportType",
        "ReportFormat",
        "ExportFormat",
        "ReportSection",
        "ExportDataset",
        "ExportFieldSet",
        "ReportJobState",
        "ReportFailureCode",
        "ReportSourceKind",
        "ReportTableKey",
        "ReportInputRole",
        "ReportFamily",
        "ReportMetricOrigin",
    ],
)
def test_public_finite_vocabularies_match_canonical_contract(name: str) -> None:
    premium_tables = {
        "risk_basis_v1",
        "risk_definition_v1",
        "risk_observed_v1",
        "risk_rolling_v1",
        "risk_matrix_summary_v1",
        "risk_matrix_axes_v1",
        "risk_matrix_cells_v1",
        "risk_tails_v1",
        "risk_modeled_v1",
        "risk_components_v1",
        "risk_concentration_v1",
        "risk_run_assets_v1",
        "risk_series_v1",
        "risk_intervals_v1",
        "risk_history_context_v1",
        "risk_history_members_v1",
        "risk_xray_paths_v1",
    }
    scenario_tables = {
        "scenario_basis_v1",
        "scenario_definition_v1",
        "scenario_shocks_v1",
        "scenario_exclusions_v1",
        "scenario_summary_v1",
        "scenario_components_v1",
        "scenario_channels_v1",
        "scenario_applied_sensitivities_v1",
        "scenario_diagnostics_v1",
        "scenario_replay_changes_v1",
        "scenario_subjects_v1",
        "scenario_classifications_v1",
        "scenario_currencies_v1",
        "scenario_members_v1",
        "scenario_sensitivity_versions_v1",
        "scenario_drivers_v1",
        "scenario_sensitivity_observations_v1",
        "scenario_sensitivity_memberships_v1",
        "scenario_sensitivity_evidence_v1",
        "scenario_source_licenses_v1",
        "scenario_replay_basis_v1",
        "scenario_replay_bindings_v1",
        "scenario_replay_methods_v1",
        "scenario_replay_coverage_v1",
        "scenario_replay_warnings_v1",
        "scenario_xray_paths_v1",
        "scenario_source_headers_v1",
    }
    # ADR-0030 adds exactly these V4 tables; prior wire literals remain unchanged.
    projection_tables = {
        "projection_basis_v1",
        "projection_definitions_v1",
        "projection_assumptions_v1",
        "projection_assets_v1",
        "projection_correlations_v1",
        "projection_calendar_v1",
        "projection_schedule_v1",
        "projection_sensitivity_v1",
        "projection_variants_v1",
        "projection_paths_v1",
        "projection_points_v1",
        "projection_point_assets_v1",
        "projection_distributions_v1",
        "projection_quantiles_v1",
        "projection_histograms_v1",
        "projection_histogram_bins_v1",
        "projection_goal_state_v1",
        "projection_goal_definition_v1",
        "projection_goal_results_v1",
        "projection_members_v1",
        "projection_source_headers_v1",
        "projection_source_nodes_v1",
        "projection_source_members_v1",
        "projection_source_scalars_v1",
    }
    premium_only = {
        "ReportSection": {"risk", "scenario", "projection", "goal", "research"},
        "ReportFamily": {"risk", "scenario", "projection", "goal", "research"},
        "ReportTableKey": premium_tables | scenario_tables | projection_tables,
        "ReportSourceKind": {
            "scenario_run",
            "scenario_result",
            "scenario_version",
            "scenario_sensitivity_version",
            "scenario_sensitivity_observation",
            "scenario_sensitivity_evidence",
        },
    }.get(name, set())
    legacy = set(get_args(getattr(wire, name)))
    assert not legacy & premium_only
    assert legacy | premium_only == {item.value for item in getattr(domain, name)}


@pytest.mark.parametrize("field", ["path", "method"])
def test_binary_generation_fails_closed_on_path_or_method_expansion(field: str) -> None:
    source = contract()
    path = "/api/v1/reports/{report_id}/artifacts/{artifact_id}/content"
    operation = source["paths"][path]["get"]
    with pytest.raises(ValueError, match="fixed path or method"):
        ReportClientGenerator(source).operation(
            path + "/other" if field == "path" else path,
            "post" if field == "method" else "get",
            operation,
        )
