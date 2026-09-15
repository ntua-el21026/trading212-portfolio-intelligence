"""The projection profile adds one closed branch to each of the six existing operations."""

from copy import deepcopy
from typing import Any

import pytest
from trading212_api_contracts.typescript import render_premium_report_client, render_report_client

from tests.contract.test_premium_report_profile_contract import BASE, contract

pytestmark = pytest.mark.contract


def test_projection_profile_keeps_original_component_schemas_and_legacy_client_exact() -> None:
    source = contract()
    for name, expected in BASE["components"].items():
        assert source["components"]["schemas"][name] == expected
    stripped = deepcopy(source)
    for path, operations in stripped["paths"].items():
        if not path.startswith("/api/v2/"):
            continue
        for operation in operations.values():
            if "premium-reports" not in operation.get("tags", []):
                continue
            operation["parameters"] = [
                item for item in operation["parameters"] if item["name"] != "profile"
            ]
    assert render_report_client(source) == render_report_client(stripped)
    rendered = render_premium_report_client(source)
    assert rendered.count("async ") == 6
    for name in (
        "GeneratePremiumReportRequestV4",
        "PremiumReportJobStatusV4",
        "PremiumReportPageV4",
        "PremiumReportManifestV4",
    ):
        assert name + "Schema" in rendered
    assert "z.any(" not in rendered and "z.unknown(" not in rendered


@pytest.mark.parametrize(
    "mutation", ["missing_four", "fifth", "duplicate_four", "default_four", "untyped", "foreign"]
)
def test_projection_profile_generator_rejects_any_unreviewed_branch(mutation: str) -> None:
    source = contract()
    operation = source["paths"]["/api/v2/report-jobs"]["post"]
    selector = next(item for item in operation["parameters"] if item["name"] == "profile")
    schema: dict[str, Any] = operation["requestBody"]["content"]["application/json"]["schema"]
    if mutation == "missing_four":
        selector["schema"]["enum"].remove("report_sections_v4")
    elif mutation == "fifth":
        selector["schema"]["enum"].append("report_sections_v5")
    elif mutation == "duplicate_four":
        selector["schema"]["enum"].append("report_sections_v4")
    elif mutation == "default_four":
        selector["schema"]["default"] = "report_sections_v4"
    elif mutation == "untyped":
        schema["anyOf"].append({"type": "object"})
    else:
        schema["anyOf"][-1] = {"$ref": "#/components/schemas/GenerateReportRequest"}
    with pytest.raises(ValueError):
        render_premium_report_client(source)
