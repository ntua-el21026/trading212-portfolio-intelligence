"""Profile-three DTOs remain distinct from the preserved default risk contract."""

import json
from copy import deepcopy
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError
from trading212_api_contracts import premium_reports as v2
from trading212_api_contracts import premium_reports_v3 as wire
from trading212_domain.report_manifest import (
    build_report_manifest,
    encode_report_manifest,
    encode_report_selection,
)

from tests.unit.api.test_premium_report_schemas import selection as selection_v2
from tests.unit.domain.report_v3_factories import capture_v3, selection_v3

pytestmark = pytest.mark.unit


def request_v3(*, risk: bool = False) -> dict[str, Any]:
    value = json.loads(encode_report_selection(selection_v3(risk=risk)))
    assert isinstance(value, dict)
    return value


def manifest_v3(*, risk: bool = False) -> dict[str, Any]:
    value = json.loads(encode_report_manifest(build_report_manifest(capture_v3(risk=risk))))
    assert isinstance(value, dict)
    return value


@pytest.mark.parametrize("risk", [False, True])
def test_v3_request_and_complete_domain_manifest_have_exact_typed_dto_parity(risk: bool) -> None:
    request = wire.GeneratePremiumReportRequestV3.model_validate(request_v3(risk=risk))
    assert request.ttl_days == 7
    assert request.profile_version == "report_sections_v3"
    assert request.premium_run.family == ("risk" if risk else "scenario")
    wire.validate_premium_request_profile("report_sections_v3", request)
    value = manifest_v3(risk=risk)
    parsed = wire.PremiumReportManifestV3.model_validate(value)
    assert parsed.document.premium_binding.family == request.premium_run.family
    assert parsed.document.selection.profile_version == "report_sections_v3"
    assert parsed.document.document_schema_version == "3.0.0"
    assert {item.schema_version for item in parsed.contexts} == {"3.0.0"}
    assert parsed.renderer_profile.template_version == "report_template_v1"
    with pytest.raises(ValidationError):
        v2.GeneratePremiumReportRequest.model_validate(request_v3(risk=risk))
    with pytest.raises(ValidationError):
        v2.PremiumReportManifest.model_validate(value)


@pytest.mark.parametrize("ttl", [0, 31, True, "7", 1.5])
def test_v3_ttl_keeps_the_exact_strict_existing_bound(ttl: object) -> None:
    with pytest.raises(ValidationError):
        wire.GeneratePremiumReportRequestV3.model_validate({**request_v3(), "ttl_days": ttl})


@pytest.mark.parametrize(
    "profile", ["report_sections_v1", "report_sections_v4", "", None, ["report_sections_v3"]]
)
def test_body_profile_is_required_and_never_inferred(profile: object) -> None:
    body = request_v3()
    body["profile_version"] = profile
    with pytest.raises(ValidationError):
        wire.GeneratePremiumReportRequestV3.model_validate(body)
    body.pop("profile_version")
    with pytest.raises(ValidationError):
        wire.GeneratePremiumReportRequestV3.model_validate(body)


@pytest.mark.parametrize(
    "change",
    [
        {"premium_run": {"run_id": "latest", "family": "scenario"}},
        {"premium_run": {"run_id": "00000000-0000-0000-0000-000000000090", "family": "projection"}},
        {"premium_runs": []},
        {"risk_run_id": "00000000-0000-0000-0000-000000000090"},
        {"sections": ["overview", "allocation", "quality", "risk", "scenario"]},
        {"sections": ["overview", "allocation", "quality", "projection"]},
        {"xray_run_id": None},
    ],
)
def test_unknown_partial_multiple_or_unimplemented_selection_fails(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        wire.GeneratePremiumReportRequestV3.model_validate({**request_v3(), **change})


def test_raw_profile_parser_retains_omission_and_checks_actual_duplicate_multi_items() -> None:
    assert wire.premium_report_profile_from_query([]) == "report_sections_v2"
    assert (
        wire.premium_report_profile_from_query([("account_id", "ignored")]) == "report_sections_v2"
    )
    assert (
        wire.premium_report_profile_from_query([("profile", "report_sections_v3")])
        == "report_sections_v3"
    )
    for items in (
        [("profile", "report_sections_v2"), ("profile", "report_sections_v2")],
        [("profile", "report_sections_v2"), ("profile", "report_sections_v3")],
        [("profile", "private-profile-canary")],
    ):
        with pytest.raises(ValueError) as caught:
            wire.premium_report_profile_from_query(items)
        assert "private-profile-canary" not in str(caught.value)


def test_profile_body_mismatch_is_denied_for_both_typed_variants() -> None:
    old = v2.GeneratePremiumReportRequest.model_validate(selection_v2())
    new = wire.GeneratePremiumReportRequestV3.model_validate(request_v3())
    wire.validate_premium_request_profile("report_sections_v2", old)
    with pytest.raises(ValueError):
        wire.validate_premium_request_profile("report_sections_v3", old)
    with pytest.raises(ValueError):
        wire.validate_premium_request_profile("report_sections_v2", new)
    with pytest.raises(ValueError):
        wire.validate_premium_request_profile("unknown", new)  # type: ignore[arg-type]


def test_empty_page_and_expired_job_require_explicit_profile_markers() -> None:
    page: dict[str, object] = {"items": [], "next_cursor": None, "limit": 25, "total": 0}
    assert v2.PremiumReportPage.model_validate(page).items == []
    with pytest.raises(ValidationError):
        wire.PremiumReportPageV3.model_validate(page)
    wire.PremiumReportPageV3.model_validate({**page, "profile_version": "report_sections_v3"})
    old = {
        "account_id": "00000000-0000-0000-0000-000000000001",
        "context": None,
        "job_id": "00000000-0000-0000-0000-000000000090",
        "report_id": None,
        "state": "expired",
        "requested_at": "2026-09-01T00:00:00Z",
        "completed_at": None,
        "expires_at": "2026-09-08T00:00:00Z",
        "failure_code": None,
        "report_type": "portfolio_summary",
        "formats": ["json"],
        "manifest_digest": None,
        "artifacts": [],
    }
    with pytest.raises(ValidationError):
        wire.PremiumReportJobStatusV3.model_validate(old)
    wire.PremiumReportJobStatusV3.model_validate({**old, "profile_version": "report_sections_v3"})
    with pytest.raises(ValidationError):
        v2.PremiumReportJobStatus.model_validate({**old, "profile_version": "report_sections_v3"})


def test_manifest_loses_neither_exact_decimal_strings_nor_strict_proof_pin_checks() -> None:
    value = manifest_v3()
    checked = wire.PremiumReportManifestV3.model_validate(value)
    assert (
        checked.document.premium_binding.result_digest
        == value["document"]["premium_binding"]["result_digest"]
    )
    changed = deepcopy(value)
    changed["bindings"] = changed["bindings"][1:]
    with pytest.raises(ValidationError):
        wire.PremiumReportManifestV3.model_validate(changed)
    changed = deepcopy(value)
    changed["document"]["premium_binding"]["reporting_currency"] = "USD"
    with pytest.raises(ValidationError):
        wire.PremiumReportManifestV3.model_validate(changed)
    changed = deepcopy(value)
    changed["document"]["tables"] = changed["document"]["tables"][:-1]
    with pytest.raises(ValidationError):
        wire.PremiumReportManifestV3.model_validate(changed)


def test_unknown_fields_and_nested_variant_errors_never_reflect_private_input() -> None:
    body = request_v3()
    body["premium_run"]["private-field-canary"] = "private-value-canary"
    with pytest.raises(ValidationError) as caught:
        wire.GeneratePremiumReportRequestV3.model_validate(body)
    assert "private-field-canary" not in str(caught.value)
    assert "private-value-canary" not in str(caught.value)


def test_exact_shared_money_strings_keep_quantum_currency_and_missing_reason() -> None:
    adapter: TypeAdapter[wire.ReportCell] = TypeAdapter(wire.ReportCell)
    raw = {
        "kind": "decimal",
        "value": "-0.000000000000000001",
        "decimal_role": "money",
        "currency": "EUR",
        "state": "available",
    }
    assert adapter.validate_python(raw).value == raw["value"]
    with pytest.raises(ValidationError):
        adapter.validate_python({**raw, "value": -0.1})
    with pytest.raises(ValidationError):
        adapter.validate_python({**raw, "currency": None})
    with pytest.raises(ValidationError):
        adapter.validate_python({**raw, "value": None, "state": "unavailable"})
