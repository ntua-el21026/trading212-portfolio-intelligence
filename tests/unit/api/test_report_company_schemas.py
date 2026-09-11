"""Strict company report request parity and pin validation."""

import json
from dataclasses import replace
from uuid import UUID

import pytest
from pydantic import ValidationError
from trading212_api.report_schemas import export_command, report_command
from trading212_api_contracts import reports as wire
from trading212_domain.report_manifest import encode_report_selection
from trading212_mcp.report_gateway import report_command as mcp_command

from tests.unit.domain.test_report_company_compatibility import drift_selection, target_export

pytestmark = pytest.mark.unit


def test_exact_http_mcp_optional_pin_and_export_normalization_agree() -> None:
    selection = replace(drift_selection(), xray_run_id=UUID(int=9))
    raw = json.loads(encode_report_selection(selection))
    raw["formats"] = ["json"]
    http = report_command(wire.GenerateReportRequest.model_validate(raw), "company-parity")
    mcp_raw = {
        key: value for key, value in raw.items() if key not in {"formats", "template_version"}
    }
    mcp_raw.update(format="json", idempotency_key="company-parity")
    mcp = mcp_command(wire.McpGenerateReportRequest.model_validate(mcp_raw))
    assert http == mcp
    assert http.selection.xray_run_id == UUID(int=9)
    export = replace(target_export(), xray_run_id=UUID(int=9))
    command = export_command(
        wire.CreateExportRequest.model_validate(json.loads(encode_report_selection(export))),
        "company-export",
    )
    assert command.selection == export


@pytest.mark.parametrize("pin", [True, 42, "latest", "private-company-pin-canary"])
def test_known_pin_rejects_invalid_type_and_hides_private_input(pin: object) -> None:
    raw = json.loads(encode_report_selection(drift_selection()))
    raw["xray_run_id"] = pin
    with pytest.raises(ValidationError) as failure:
        wire.GenerateReportRequest.model_validate(raw)
    assert "private-company-pin-canary" not in str(failure.value)


def test_irrelevant_company_pin_cannot_turn_other_reports_into_company_copies() -> None:
    raw = json.loads(encode_report_selection(replace(drift_selection(), xray_run_id=UUID(int=9))))
    raw["sections"] = ["overview", "allocation", "quality"]
    raw["report_type"] = "portfolio_summary"
    with pytest.raises(ValidationError):
        wire.GenerateReportRequest.model_validate(raw)
