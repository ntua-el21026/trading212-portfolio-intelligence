"""Closed inputs and honest report metadata at every public serialization boundary."""

from dataclasses import replace
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError
from trading212_api.report_schemas import report_command
from trading212_api_contracts import reports as wire
from trading212_domain import reports as domain
from trading212_domain.errors import DomainError
from trading212_domain.serialization import to_primitive
from trading212_mcp.report_gateway import report_command as mcp_command

from tests.unit.api.report_factories import ACCOUNT, BODY, artifact, job


@pytest.mark.parametrize(
    "extra", ["html", "destination", "owner_id", "xray_run_id", "input_digest"]
)
def test_unknown_report_fields_fail_without_reflecting_input(extra: str) -> None:
    with pytest.raises(ValidationError) as failure:
        wire.GenerateReportRequest.model_validate({**BODY, extra: "private-test-content"})
    assert extra not in str(failure.value)
    assert "private-test-content" not in str(failure.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("ttl_days", True),
        ("ttl_days", 0),
        ("ttl_days", 31),
        ("formats", ["json", "json"]),
        ("sections", ["overview", "overview"]),
        ("formats", ["html"]),
    ],
)
def test_invalid_selector_types_and_duplicates_fail(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        wire.GenerateReportRequest.model_validate({**BODY, field: value})


def test_http_and_exact_mcp_request_normalize_to_one_identical_command() -> None:
    http = report_command(wire.GenerateReportRequest.model_validate(BODY), "same-report")
    mcp = mcp_command(
        wire.McpGenerateReportRequest.model_validate(
            {
                **{key: value for key, value in BODY.items() if key != "formats"},
                "format": "json",
                "idempotency_key": "same-report",
            }
        )
    )
    assert http == mcp and http.ttl_days == 7
    assert http.selection.formats == (domain.ReportFormat.JSON,)
    schema = wire.McpGenerateReportRequest.model_json_schema()
    assert set(schema["required"]) == {
        "account_id",
        "idempotency_key",
        "start_date",
        "end_date",
        "source_cutoff_at",
        "snapshot_id",
        "reporting_currency",
        "report_type",
        "format",
        "sections",
    }
    assert set(schema["properties"]) - set(schema["required"]) == {
        "target_version_id",
        "plan_revision_id",
        "benchmark_version_id",
        "constituent_snapshot_id",
    }


@pytest.mark.parametrize(
    "change",
    [{"sections": ["overview"]}, {"report_type": "monthly"}, {"target_version_id": ACCOUNT}],
)
def test_domain_selection_rejects_incomplete_calendar_sections_and_irrelevant_pins(
    change: dict[str, Any],
) -> None:
    with pytest.raises(DomainError):
        report_command(wire.GenerateReportRequest.model_validate({**BODY, **change}), "invalid")


def test_expired_tombstone_keeps_safe_artifact_identity_with_no_licensed_context() -> None:
    download = artifact()
    expired = replace(
        job(),
        state=domain.ReportJobState.EXPIRED,
        context=None,
        report_id=job().job_id,
        artifacts=(download.metadata,),
        manifest_digest="d" * 64,
    )
    result = wire.ReportJobStatus.model_validate(to_primitive(expired))
    assert result.context is None and result.report_id == str(job().job_id)
    assert result.artifacts[0].content_digest == download.metadata.content_digest
    assert '"content":' not in result.model_dump_json()


@pytest.mark.parametrize(
    "alter",
    [{"state": "succeeded"}, {"context": None}, {"artifacts": [to_primitive(artifact().metadata)]}],
)
def test_unsealed_or_missing_context_status_never_becomes_a_success(alter: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        wire.ReportJobStatus.model_validate({**to_primitive(job()), **alter})


def test_unknown_manifest_cell_types_float_and_missing_money_currency_fail() -> None:
    adapter: TypeAdapter[wire.ReportCell] = TypeAdapter(wire.ReportCell)
    base = {
        "kind": "decimal",
        "state": "available",
        "value": "0",
        "decimal_role": "money",
        "currency": "EUR",
        "context_key": None,
        "reason_key": None,
        "bound_key": None,
    }
    assert adapter.validate_python(base).value == "0"
    for change in ({"value": 0.1}, {"value": None}, {"currency": None}, {"kind": "formula"}):
        with pytest.raises(ValidationError):
            adapter.validate_python({**base, **change})


def test_cell_quality_origin_and_method_survive_without_numeric_coercion() -> None:
    payload = {
        "kind": "decimal",
        "state": "partial",
        "value": "0.000000000000000001",
        "decimal_role": "ratio",
        "currency": None,
        "context_key": "context.one",
        "reason_key": "reason.partial",
        "bound_key": "bound.lower",
        "quality": "estimated",
        "origin": "derived_deterministic",
        "coverage_key": "coverage.one",
        "confidence": "0.999999999999999999",
        "method_key": "xray_v1",
        "method_version": "1.1.0",
        "provenance_set_key": "sources.one",
        "note_set_key": "notes.one",
    }
    parsed = wire.ReportDecimalCell.model_validate(payload)
    assert parsed.model_dump(mode="json") == payload
    for change in (
        {"confidence": 0.5},
        {"confidence": "1.000000000000000001"},
        {"confidence": "0.0000000000000000001"},
        {"method_version": None},
        {"origin": "fabricated"},
    ):
        with pytest.raises(ValidationError):
            wire.ReportDecimalCell.model_validate({**payload, **change})


def test_canonical_cell_optional_omission_preserves_required_state_value_and_decimal_role() -> None:
    adapter: TypeAdapter[wire.ReportCell] = TypeAdapter(wire.ReportCell)
    text = {"kind": "text", "state": "available", "value": "Synthetic holding"}
    parsed = adapter.validate_python(text)
    assert parsed.model_dump(mode="json", exclude_none=True) == text
    for required in ("kind", "state", "value"):
        with pytest.raises(ValidationError):
            adapter.validate_python({key: value for key, value in text.items() if key != required})
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "decimal", "state": "available", "value": "1"})
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "text", "state": "unavailable", "value": None})
