"""Six fixed V2 methods import frozen V1 cells and reject operation expansion."""

from copy import deepcopy

import pytest
from trading212_api_contracts.typescript import (
    ReportClientGenerator,
    render_premium_report_client,
    render_report_client,
)

from tests.contract.test_report_client_generation import contract

pytestmark = pytest.mark.contract


def test_premium_client_has_exact_methods_and_preserves_legacy_generation() -> None:
    source = contract()
    original = deepcopy(source)
    generated = render_premium_report_client(source)
    assert source == original
    assert generated == render_premium_report_client(deepcopy(source))
    expected = {
        "generate_premium_portfolio_report",
        "get_premium_report_status",
        "list_premium_reports",
        "get_premium_report_manifest",
        "create_premium_report_download_grant",
        "download_premium_report_artifact",
    }
    assert all(f"async {name}(" in generated for name in expected)
    assert "class PremiumReportApiClient" in generated
    assert "new ReportTransport(options, 2)" in generated
    assert 'from "./reports.generated"' in generated
    assert "export const ReportArtifactMetadataSchema" not in generated
    assert "export const ReportRowSchema" not in generated
    assert "PremiumReportManifestSchema" in generated
    assert "z.any(" not in generated and "z.unknown(" not in generated
    assert "options: ReportGrantOptions = {}" in generated
    assert "options: ReportDownloadOptions" in generated
    assert "Promise<ReportArtifactResponse>" in generated
    assert "/api/v1/" not in generated and "exports" not in generated
    legacy = render_report_client(source)
    assert "Premium" not in legacy and "/api/v2/" not in legacy
    assert "new ReportTransport(options)" in legacy


@pytest.mark.parametrize("change", ["path", "method", "name", "extra", "missing"])
def test_premium_generator_rejects_every_unregistered_operation_change(change: str) -> None:
    source = contract()
    path = "/api/v2/reports/{report_id}/artifacts/{artifact_id}/content"
    operation = source["paths"][path]["get"]
    if change == "path":
        source["paths"][path + "/extra"] = source["paths"].pop(path)
    elif change == "method":
        source["paths"][path]["post"] = source["paths"][path].pop("get")
    elif change == "name":
        operation["operationId"] = "download_report_artifact"
    elif change == "extra":
        source["paths"]["/api/v2/exports"] = {"get": operation}
    else:
        del source["paths"][path]
    with pytest.raises(ValueError, match="fixed premium report operation inventory"):
        render_premium_report_client(source)


def test_binary_generator_cannot_cross_contract_versions() -> None:
    source = contract()
    path = "/api/v2/reports/{report_id}/artifacts/{artifact_id}/content"
    operation = source["paths"][path]["get"]
    with pytest.raises(ValueError, match="fixed version"):
        ReportClientGenerator(source).operation(path, "get", operation)
    with pytest.raises(ValueError, match="fixed path or method"):
        ReportClientGenerator(source, premium=True).operation(
            path.replace("/api/v2/", "/api/v1/"), "get", operation
        )
