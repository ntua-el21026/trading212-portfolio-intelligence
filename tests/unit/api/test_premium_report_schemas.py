"""Versioned premium DTOs retain complete risk proof and frozen legacy boundaries."""

from copy import deepcopy
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError
from trading212_api_contracts import premium_reports as wire
from trading212_api_contracts import reports as legacy
from trading212_domain.serialization import to_primitive

from tests.unit.api.report_factories import ACCOUNT, BODY, JOB, artifact, job

pytestmark = pytest.mark.unit

RISK = "abcdefab-1234-4000-8000-000000000001"
INSTANT = "2026-09-07T12:00:00Z"


def selection() -> dict[str, Any]:
    return {**BODY, "sections": [*BODY["sections"], "risk"], "risk_run_id": RISK}


def note() -> dict[str, Any]:
    return {
        "key": "risk.reason",
        "kind": "unavailable_reason",
        "family": "risk",
        "code": "insufficient_history",
        "text": "insufficient_history",
        "related_provenance_set_key": "risk.sources",
    }


def pin() -> dict[str, Any]:
    return {
        "family": "risk",
        "role": "result",
        "subject_id": RISK,
        "content_digest": "c" * 64,
        "parent_id": None,
        "method_key": "risk_v1",
        "method_version": "1.0.0",
    }


def status() -> dict[str, Any]:
    value: dict[str, Any] = to_primitive(job())
    value["context"].update(profile_version="report_sections_v2", schema_version="2.0.0")
    value["context"]["pins"].append(pin())
    value["context"]["quality"].update(warnings=[note()], warning_count=1, warning_omitted_count=0)
    return value


def manifest() -> dict[str, Any]:
    cell = {
        "kind": "decimal",
        "state": "unavailable",
        "value": None,
        "decimal_role": "ratio",
        "reason_key": "risk.reason",
    }
    return {
        "document": {
            "selection": selection(),
            "owner_id": ACCOUNT,
            "valuation_at": INSTANT,
            "context_digest": "a" * 64,
            "tables": [
                {
                    "table": "risk_observed_v1",
                    "schema_digest": "b" * 64,
                    "row_count": 1,
                    "content_digest": "c" * 64,
                    "section": "risk",
                    "dataset": None,
                    "state": "available",
                    "reason_key": None,
                }
            ],
            "document_digest": "d" * 64,
            "document_schema_version": "2.0.0",
        },
        "renderer_profile": {
            "renderer_versions": [{"format": "json", "name": "json", "version": "1.0.0"}],
            "fonts": [],
            "profile_version": "report_render_v1",
            "template_version": "report_template_v1",
            "locale": "en-GB",
            "timezone": "UTC",
            "chart_order_version": "report_chart_order_v1",
            "accessibility_profile_version": "report_visual_accessibility_v1",
        },
        "bindings": [pin()],
        "contexts": [
            {
                "key": "risk.context",
                "family": "risk",
                "method_key": "risk_v1",
                "method_version": "1.0.0",
                "valuation_at": INSTANT,
                "source_cutoff_at": INSTANT,
                "quality": "partial",
                "provenance_set_key": "risk.sources",
                "coverage_set_key": "risk.coverage",
                "note_set_key": "risk.notes",
                "source_at": None,
                "reconciliation_key": None,
                "schema_version": "2.0.0",
            }
        ],
        "source_references": [],
        "source_memberships": [],
        "note_memberships": [{"note_set_key": "risk.notes", "note_key": "risk.reason"}],
        "license_references": [],
        "coverage": [
            {"set_key": "risk.coverage", "family": "risk", "metric_key": "observed", "value": cell}
        ],
        "bounds": [
            {
                "key": "risk.bound",
                "family": "risk",
                "kind": "unavailable",
                "quantum": None,
                "rounding": None,
                "positive_below_quantum": False,
            }
        ],
        "notes": [note()],
        "proof_relations": [
            {
                "table": "risk_intervals_v1",
                "row": {"key": "risk.interval.0", "context_key": "risk.context", "cells": [cell]},
            }
        ],
        "reconciliation": [],
        "method": "report_manifest_v1",
        "method_version": "1.0.0",
        "escaping_version": "report_csv_text_v1",
    }


def test_versioned_request_requires_risk_preserves_template_and_normalizes_uuid() -> None:
    body = selection()
    body["risk_run_id"] = RISK.upper()
    result = wire.GenerateReportRequest.model_validate(body)
    assert result.risk_run_id == RISK and result.ttl_days == 7
    assert result.template_version == "report_template_v1"
    assert "risk_run_id" in wire.GenerateReportRequest.model_json_schema()["required"]
    with pytest.raises(ValidationError):
        wire.GenerateReportRequest.model_validate(BODY)
    legacy.GenerateReportRequest.model_validate(BODY)
    for change in ({"risk_run_id": RISK}, {"sections": body["sections"]}):
        with pytest.raises(ValidationError):
            legacy.GenerateReportRequest.model_validate({**BODY, **change})


@pytest.mark.parametrize(
    "change",
    [
        {"risk_run_id": None},
        {"risk_run_id": True},
        {"risk_run_id": 1},
        {"risk_run_id": "null"},
        {"sections": BODY["sections"]},
        {"sections": ["risk"]},
        {"sections": [*BODY["sections"], "risk", "risk"]},
        {"sections": [*BODY["sections"], "risk", "unregistered"]},
        {"ttl_days": True},
        {"ttl_days": "7"},
        {"ttl_days": 0},
        {"ttl_days": 31},
        {"formats": ["json", "json"]},
        {"formats": ["html"]},
        {"target_version_id": RISK},
        {"plan_revision_id": RISK},
        {"benchmark_version_id": RISK},
        {"constituent_snapshot_id": RISK},
        {"xray_run_id": RISK},
        {"template_version": "report_template_v2"},
        {"start_date": "2000-01-01"},
        {"end_date": "2026-08-31"},
        {"source_cutoff_at": "2026-09-07"},
        {"reporting_currency": "eur"},
    ],
)
def test_invalid_and_irrelevant_selectors_fail(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        wire.GenerateReportRequest.model_validate({**selection(), **change})


def test_all_fourteen_sections_retain_legacy_pin_requirements() -> None:
    sections = [
        "overview",
        "allocation",
        "targets",
        "drift",
        "contribution_plan",
        "performance",
        "benchmark",
        "income",
        "cash_flows",
        "attribution",
        "xray",
        "quality",
        "activity",
        "risk",
    ]
    body = {
        **selection(),
        "sections": sections,
        "target_version_id": RISK,
        "plan_revision_id": RISK,
        "benchmark_version_id": RISK,
        "constituent_snapshot_id": RISK,
        "xray_run_id": RISK,
        "formats": ["pdf", "csv", "json", "xlsx"],
        "ttl_days": 30,
    }
    assert wire.GenerateReportRequest.model_validate(body).sections == sections
    for field in ("plan_revision_id", "benchmark_version_id"):
        with pytest.raises(ValidationError):
            wire.GenerateReportRequest.model_validate({**body, field: None})
    wire.GenerateReportRequest.model_validate({**body, "target_version_id": None})
    with pytest.raises(ValidationError):
        wire.GenerateReportRequest.model_validate(
            {**body, "target_version_id": None, "plan_revision_id": None}
        )


@pytest.mark.parametrize(
    "kind,start,end,sections,pins",
    [
        (
            "monthly",
            "2024-02-01",
            "2024-02-29",
            "overview allocation performance income cash_flows quality",
            {},
        ),
        (
            "quarterly",
            "2026-10-01",
            "2026-12-31",
            "overview allocation performance income cash_flows quality",
            {},
        ),
        (
            "annual",
            "2026-01-01",
            "2026-12-31",
            "overview allocation performance income cash_flows quality",
            {},
        ),
        ("portfolio_summary", "2026-09-01", "2026-09-07", "overview allocation quality", {}),
        (
            "target_drift",
            "2026-09-01",
            "2026-09-07",
            "overview targets drift quality",
            {"target_version_id": RISK},
        ),
        (
            "contribution_plan",
            "2026-09-01",
            "2026-09-07",
            "overview targets contribution_plan quality",
            {"plan_revision_id": RISK},
        ),
        (
            "performance_benchmark",
            "2026-09-01",
            "2026-09-07",
            "overview performance benchmark quality",
            {"benchmark_version_id": RISK},
        ),
        ("dividend_income", "2026-09-01", "2026-09-07", "overview income cash_flows quality", {}),
        ("portfolio_xray", "2026-09-01", "2026-09-07", "overview xray quality", {}),
        ("quality_reconciliation", "2026-09-01", "2026-09-07", "overview quality activity", {}),
    ],
)
def test_original_required_sections_and_calendar_semantics_survive(
    kind: str, start: str, end: str, sections: str, pins: dict[str, str]
) -> None:
    body = {
        **selection(),
        **pins,
        "report_type": kind,
        "start_date": start,
        "end_date": end,
        "sections": [*sections.split(), "risk"],
    }
    wire.GenerateReportRequest.model_validate(body)
    for section in sections.split():
        with pytest.raises(ValidationError):
            wire.GenerateReportRequest.model_validate(
                {**body, "sections": [s for s in body["sections"] if s != section]}
            )
    if kind in {"monthly", "quarterly", "annual"}:
        with pytest.raises(ValidationError):
            wire.GenerateReportRequest.model_validate({**body, "end_date": end[:-2] + "28"})


@pytest.mark.parametrize("path", ["selection", "pin", "warning", "context", "table", "cell"])
def test_nested_unknown_fields_are_rejected_without_private_reflection(path: str) -> None:
    value = manifest()
    targets = {
        "selection": value["document"]["selection"],
        "pin": value["bindings"][0],
        "warning": value["notes"][0],
        "context": value["contexts"][0],
        "table": value["document"]["tables"][0],
        "cell": value["proof_relations"][0]["row"]["cells"][0],
    }
    targets[path]["private-field-canary"] = "private-value-canary"
    with pytest.raises(ValidationError) as failure:
        wire.ReportManifest.model_validate(value)
    assert "private-field-canary" not in str(failure.value)
    assert "private-value-canary" not in str(failure.value)


def test_complete_v2_graph_preserves_risk_families_and_reuses_exact_cells() -> None:
    value = manifest()
    parsed = wire.ReportManifest.model_validate(value)
    assert parsed.document.selection.risk_run_id == RISK
    assert parsed.document.document_schema_version == "2.0.0"
    assert parsed.renderer_profile.template_version == "report_template_v1"
    assert parsed.bindings[0].family == parsed.contexts[0].family == "risk"
    assert parsed.coverage[0].family == parsed.bounds[0].family == parsed.notes[0].family == "risk"
    assert parsed.proof_relations[0].row.cells[0].reason_key == "risk.reason"
    with pytest.raises(ValidationError):
        legacy.ReportManifest.model_validate(value)
    with pytest.raises(ValidationError):
        wire.ReportManifest.model_validate(
            {**value, "document": {**value["document"], "document_schema_version": "1.0.0"}}
        )
    assert wire.ReportRow is legacy.ReportRow
    assert wire.ReportRendererProfile is legacy.ReportRendererProfile
    for exact in ("0", "-0.000000000000000000", "0.000000000000000001", "-1.5"):
        cell = {"kind": "decimal", "state": "available", "value": exact, "decimal_role": "ratio"}
        value["proof_relations"][0]["row"]["cells"] = [cell]
        assert (
            wire.ReportManifest.model_validate(value).proof_relations[0].row.cells[0].value == exact
        )
    value["proof_relations"][0]["row"]["cells"][0]["value"] = 0.1
    with pytest.raises(ValidationError):
        wire.ReportManifest.model_validate(value)


def test_premium_table_enum_is_exactly_seventeen_additions_to_unchanged_v1() -> None:
    expected = {
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
    old = set(TypeAdapter(legacy.ReportTableKey).json_schema()["enum"])
    new = set(TypeAdapter(wire.ReportTableKey).json_schema()["enum"])
    assert new - old == expected and new == old | expected and not old & expected
    assert set(TypeAdapter(wire.ReportFamily).json_schema()["enum"]) == (
        set(TypeAdapter(legacy.ReportFamily).json_schema()["enum"]) | {"risk"}
    )
    value = manifest()
    value["document"]["tables"][0]["table"] = "risk_unregistered_v1"
    with pytest.raises(ValidationError):
        wire.ReportManifest.model_validate(value)
    value["document"]["tables"][0].update(table="risk_basis_v1", dataset="positions")
    with pytest.raises(ValidationError):
        wire.ReportManifest.model_validate(value)


def test_status_graph_is_strictly_versioned_and_preserves_atomic_results() -> None:
    value = status()
    parsed = wire.ReportJobStatus.model_validate(value)
    assert parsed.context is not None and parsed.context.pins[-1].family == "risk"
    assert parsed.context.quality.warnings[0].code == "insufficient_history"
    with pytest.raises(ValidationError):
        legacy.ReportJobStatus.model_validate(value)
    with pytest.raises(ValidationError):
        wire.ReportJobStatus.model_validate(to_primitive(job()))
    success = {
        **value,
        "state": "succeeded",
        "report_id": JOB,
        "completed_at": INSTANT,
        "manifest_digest": "d" * 64,
        "artifacts": [to_primitive(artifact().metadata)],
    }
    wire.ReportJobStatus.model_validate(success)
    changes: tuple[dict[str, object], ...] = (
        {"state": "queued"},
        {"report_id": RISK},
        {"manifest_digest": None},
        {"completed_at": None},
        {"failure_code": "render_failed"},
        {"artifacts": []},
        {"formats": ["pdf"]},
        {"context": None},
    )
    for change in changes:
        with pytest.raises(ValidationError):
            wire.ReportJobStatus.model_validate({**success, **change})
    expired = wire.ReportJobStatus.model_validate({**success, "state": "expired", "context": None})
    assert expired.context is None and expired.artifacts
    too_late = deepcopy(success)
    too_late["artifacts"][0]["expires_at"] = "2026-10-01T00:00:00Z"
    with pytest.raises(ValidationError):
        wire.ReportJobStatus.model_validate(too_late)


def test_page_warning_pin_and_document_bounds_are_preserved() -> None:
    value = status()
    page = {"items": [value], "next_cursor": None, "limit": 1, "total": 1}
    assert len(wire.ReportPage.model_validate(page).items) == 1
    for change in ({"total": 0}, {"limit": 0}, {"items": [value, value]}, {"limit": True}):
        with pytest.raises(ValidationError):
            wire.ReportPage.model_validate({**page, **change})
    value["context"]["quality"]["warning_count"] = 0
    with pytest.raises(ValidationError):
        wire.ReportJobStatus.model_validate(value)
    value = status()
    value["context"]["pins"] = [pin()] * 257
    with pytest.raises(ValidationError):
        wire.ReportJobStatus.model_validate(value)
    value = manifest()
    value["document"]["tables"] *= 129
    with pytest.raises(ValidationError):
        wire.ReportManifest.model_validate(value)


def test_versions_cannot_be_mixed_inside_a_premium_status_or_manifest() -> None:
    for change in ({"profile_version": "report_sections_v1"}, {"schema_version": "1.0.0"}):
        value = status()
        value["context"].update(change)
        with pytest.raises(ValidationError):
            wire.ReportJobStatus.model_validate(value)
    value = manifest()
    value["contexts"][0]["schema_version"] = "1.0.0"
    with pytest.raises(ValidationError):
        wire.ReportManifest.model_validate(value)
    with pytest.raises(ValidationError) as failure:
        wire.GenerateReportRequest.model_validate(
            {**selection(), "risk_run_id": "private-pin-canary"}
        )
    assert "private-pin-canary" not in str(failure.value)


def test_all_artifact_bytes_count_towards_the_atomic_report_bound() -> None:
    value = status()
    artifacts = []
    for index, (format_name, mime) in enumerate(
        (
            ("pdf", "application/pdf"),
            ("csv", "text/csv; charset=utf-8"),
            ("json", "application/json"),
        )
    ):
        artifacts.append(
            {
                **to_primitive(artifact().metadata),
                "artifact_id": f"00000000-0000-4000-8000-{index:012d}",
                "format": format_name,
                "mime_type": mime,
                "byte_length": 10 * 1024 * 1024,
            }
        )
    value.update(
        state="succeeded",
        report_id=JOB,
        completed_at=INSTANT,
        manifest_digest="d" * 64,
        formats=["pdf", "csv", "json"],
        artifacts=artifacts,
    )
    with pytest.raises(ValidationError):
        wire.ReportJobStatus.model_validate(value)
    artifacts[2]["byte_length"] = 5 * 1024 * 1024
    wire.ReportJobStatus.model_validate(value)
    artifacts[2]["mime_type"] = "text/html"
    with pytest.raises(ValidationError):
        wire.ReportJobStatus.model_validate(value)


def test_manifest_cannot_exceed_the_license_ceiling() -> None:
    license_reference = {
        "version_id": RISK,
        "provider_id": ACCOUNT,
        "license_digest": "a" * 64,
        "attribution": "Synthetic licensed source",
        "pinned_store": "allowed",
        "pinned_display": "allowed",
        "pinned_report": "allowed",
        "pinned_export": "denied",
        "valid_from": INSTANT,
        "expires_at": None,
    }
    value = manifest()
    value["license_references"] = [license_reference] * 257
    with pytest.raises(ValidationError):
        wire.ReportManifest.model_validate(value)
