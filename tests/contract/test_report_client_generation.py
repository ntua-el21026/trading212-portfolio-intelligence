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
    assert set(get_args(getattr(wire, name))) == {item.value for item in getattr(domain, name)}


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
