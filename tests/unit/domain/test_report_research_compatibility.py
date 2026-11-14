"""Independent pre-research profile-three bytes and earlier-profile rejection."""

import json
from typing import Any

import pytest
from trading212_domain import reports as r
from trading212_domain.errors import DomainError
from trading212_domain.report_manifest import (
    build_report_manifest,
    encode_report_capture,
    encode_report_header,
    encode_report_manifest,
    encode_report_selection,
)

from tests.unit.domain.report_v3_factories import capture_v3
from tests.unit.domain.test_report_v3_compatibility import _legacy

pytestmark = pytest.mark.unit

# Literal fields/order from the pre-research profile3 contract, not dataclass inspection.
_COMMON = (
    "run_id",
    "result_id",
    "input_digest",
    "result_digest",
    "owner_id",
    "account_id",
    "snapshot_id",
    "snapshot_digest",
    "reporting_currency",
    "source_cutoff_at",
    "valuation_at",
    "created_at",
    "completed_at",
    "expires_at",
    "state",
)
_FIELDS = {
    "ReportRiskRunSelection": ("run_id", "family"),
    "ReportScenarioRunSelection": ("run_id", "family"),
    "ReportXrayRunBinding": ("run_id", "input_id", "input_digest", "result_digest"),
    "ReportHistoricalInputBinding": ("input_snapshot_id", "input_digest"),
    "ReportRiskRunBinding": (
        *_COMMON,
        "definition_id",
        "definition_version_id",
        "definition_digest",
        "start_date",
        "end_date",
        "historical",
        "xray",
        "benchmark_version_id",
        "family",
    ),
    "ReportScenarioRunBinding": (
        *_COMMON,
        "scenario_id",
        "scenario_version_id",
        "scenario_version_digest",
        "xray",
        "historical",
        "family",
    ),
    "ReportSelectionV3": (
        "account_id",
        "start_date",
        "end_date",
        "source_cutoff_at",
        "snapshot_id",
        "reporting_currency",
        "report_type",
        "sections",
        "formats",
        "premium_run",
        "target_version_id",
        "plan_revision_id",
        "benchmark_version_id",
        "constituent_snapshot_id",
        "xray_run_id",
        "template_version",
        "profile_version",
    ),
    "ReportDocumentHeaderV3": (
        "selection",
        "owner_id",
        "valuation_at",
        "context_digest",
        "tables",
        "document_digest",
        "premium_binding",
        "document_schema_version",
    ),
    "ReportCaptureSummaryV3": (
        "header",
        "canonical_byte_length",
        "chunk_count",
        "immutable_bindings",
        "proof",
        "proof_digest",
        "renderer_profile",
        "copy_expires_at",
    ),
    "ReportManifestV3": (
        "document",
        "renderer_profile",
        "bindings",
        "contexts",
        "source_references",
        "source_memberships",
        "note_memberships",
        "license_references",
        "coverage",
        "bounds",
        "notes",
        "proof_relations",
        "reconciliation",
        "method",
        "method_version",
        "escaping_version",
    ),
}
_OMIT = {
    "ReportSelectionV3": {"xray_run_id"},
    "ReportRiskRunBinding": {"xray", "benchmark_version_id"},
    "ReportScenarioRunBinding": {"historical"},
}


def _reference(value: object) -> Any:
    if type(value) is tuple:
        return [_reference(item) for item in value]
    name = type(value).__name__
    if name in _FIELDS:
        return {
            field: _reference(getattr(value, field))
            for field in _FIELDS[name]
            if not (field in _OMIT.get(name, set()) and getattr(value, field) is None)
        }
    return _legacy(value)


@pytest.mark.parametrize("risk", [False, True])
def test_earlier_profile3_complete_selection_header_capture_manifest_bytes_stay_exact(
    risk: bool,
) -> None:
    capture = capture_v3(risk=risk)
    manifest = build_report_manifest(capture)
    for value, encoder in (
        (capture.header.selection, encode_report_selection),
        (capture.header, encode_report_header),
        (capture, encode_report_capture),
        (manifest, encode_report_manifest),
    ):
        expected = json.dumps(_reference(value), ensure_ascii=False, separators=(",", ":")).encode()
        assert encoder(value) == expected  # type: ignore[arg-type]
        assert b"note_revision_ids" not in expected
        assert b"review_acknowledgment" not in expected
        assert b"research_" not in expected


@pytest.mark.parametrize("risk", [False, True])
def test_research_table_cannot_hide_in_an_earlier_profile3_descriptor(risk: bool) -> None:
    from dataclasses import replace

    from trading212_domain.report_research_schema import RESEARCH_TABLE_COLUMNS

    original = capture_v3(risk=risk).header
    for table in RESEARCH_TABLE_COLUMNS:
        hidden = r.ReportTableDescriptor(
            table=table, schema_digest="0" * 64, row_count=0, content_digest="0" * 64
        )
        with pytest.raises(DomainError):
            replace(original, tables=(*original.tables, hidden))


@pytest.mark.parametrize("premium", [False, True])
def test_original_v1_v2_reject_research_source_kinds_and_tables(premium: bool) -> None:
    from dataclasses import replace

    from trading212_domain.report_research_schema import RESEARCH_TABLE_COLUMNS

    from tests.unit.domain.report_factories import document, uid
    from tests.unit.domain.test_premium_report_versions import _capture as capture_v2

    capture = capture_v2() if premium else document().capture
    for kind in r.RESEARCH_REPORT_SOURCE_KINDS:
        with pytest.raises(DomainError) as caught:
            replace(
                capture,
                proof=replace(
                    capture.proof,
                    source_references=(
                        r.ReportSourceReference(
                            key="research.hidden",
                            kind=kind,
                            subject_id=uid(80),
                            content_digest="0" * 64,
                        ),
                    ),
                ),
            )
        assert caught.value.field == "family"
    for table in RESEARCH_TABLE_COLUMNS:
        hidden = r.ReportTableDescriptor(
            table=table, schema_digest="0" * 64, row_count=0, content_digest="0" * 64
        )
        with pytest.raises(DomainError) as caught:
            replace(capture.header, tables=(*capture.header.tables, hidden))
        assert caught.value.field == "tables"


def test_projection_profile_rejects_research_source_kinds_and_proof_tables() -> None:
    from dataclasses import replace

    from trading212_domain.report_research_schema import RESEARCH_TABLE_COLUMNS

    from tests.unit.domain.report_factories import _row, uid
    from tests.unit.persistence.projection_report_factories import capture_v4

    capture = capture_v4()
    for kind in r.RESEARCH_REPORT_SOURCE_KINDS:
        with pytest.raises(DomainError) as caught:
            replace(
                capture,
                proof=replace(
                    capture.proof,
                    source_references=(
                        r.ReportSourceReference(
                            key="research.hidden",
                            kind=kind,
                            subject_id=uid(80),
                            content_digest="0" * 64,
                        ),
                    ),
                ),
            )
        assert caught.value.field == "sources"
    for table in RESEARCH_TABLE_COLUMNS:
        with pytest.raises(DomainError) as caught:
            replace(
                capture,
                proof=replace(
                    capture.proof,
                    proof_relations=(r.ReportProofRelation(table=table, row=_row(table)),),
                ),
            )
        assert caught.value.field == "proof_relations"
