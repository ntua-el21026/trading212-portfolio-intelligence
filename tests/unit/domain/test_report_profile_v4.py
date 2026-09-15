"""Nullable projection clocks belong only to the explicit fourth profile."""

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from trading212_domain import reports as r
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError
from trading212_domain.report_manifest import (
    decode_report_context,
    decode_report_context_v3,
    decode_report_selection,
    decode_report_selection_v3,
    encode_report_selection,
)
from trading212_domain.report_manifest_v4 import (
    decode_report_context_v4,
    decode_report_selection_v4,
    encode_report_context_v4,
    encode_report_selection_v4,
)
from trading212_domain.report_projection_schema import PROJECTION_TABLE_COLUMNS
from trading212_domain.report_v4 import ReportContextV4, promote_report_context_v4, report_tables_v4

from tests.unit.domain.report_factories import document
from tests.unit.domain.report_v3_factories import selection_v3
from tests.unit.domain.test_premium_report_versions import _capture as capture_v2
from tests.unit.domain.test_report_v3_compatibility import _bytes as original_bytes
from tests.unit.persistence.projection_report_factories import case

pytestmark = pytest.mark.unit
AT = datetime(2025, 2, 1, tzinfo=UTC)


def context() -> ReportContextV4:
    return ReportContextV4(
        key="projection.actual_run",
        family=r.ReportFamily.PROJECTION,
        method_key="projection_v1",
        method_version="1.0.0",
        valuation_at=None,
        source_cutoff_at=None,
        quality=QualityState.ESTIMATED,
        provenance_set_key="projection.sources",
        coverage_set_key="projection.coverage",
        note_set_key="projection.notes",
    )


def test_nullable_original_clocks_require_v4_and_preserve_explicit_null_bytes() -> None:
    value = context()
    payload = encode_report_context_v4(value)
    assert b'"valuation_at":null,"source_cutoff_at":null' in payload
    assert decode_report_context_v4(payload) == value
    for decode in (decode_report_context, decode_report_context_v3):
        with pytest.raises(DomainError):
            decode(payload)
    with pytest.raises(DomainError):
        r.ReportContext(
            key="old",
            family=r.ReportFamily.SNAPSHOT,
            method_key="snapshot_v1",
            method_version="1.0.0",
            valuation_at=None,  # type: ignore[arg-type]  # negative legacy constructor probe
            source_cutoff_at=AT,
            quality=QualityState.FRESH,
            provenance_set_key="sources",
            coverage_set_key="coverage",
            note_set_key="notes",
        )
    with pytest.raises(DomainError):
        replace(value, family=r.ReportFamily.SNAPSHOT)
    with pytest.raises(DomainError):
        replace(value, quality=QualityState.FRESH)
    old = document().capture.proof.contexts[0]
    promoted = promote_report_context_v4(old)
    assert promoted.valuation_at == old.valuation_at
    assert promoted.source_cutoff_at == old.source_cutoff_at
    assert promoted.method_key == old.method_key


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "3.0.0"),
        ("family", "scenario"),
        ("extra", "ignored"),
        ("valuation_at", 0.5),
    ],
)
def test_v4_context_unknown_fields_types_and_foreign_profiles_fail(
    field: str, value: object
) -> None:
    raw = json.loads(encode_report_context_v4(context()))
    raw[field] = value
    with pytest.raises(DomainError):
        decode_report_context_v4(json.dumps(raw).encode())


def test_projection_selection_has_one_actual_run_and_complete_fixed_tables() -> None:
    chosen = case().builder.selection
    payload = encode_report_selection_v4(chosen)
    assert decode_report_selection_v4(payload) == chosen
    assert b'"profile_version":"report_sections_v4"' in payload
    assert b'"family":"projection"' in payload
    assert set(PROJECTION_TABLE_COLUMNS) <= set(report_tables_v4(chosen))
    for decode in (decode_report_selection, decode_report_selection_v3):
        with pytest.raises(DomainError):
            decode(payload)
    for family in ("risk", "scenario", "research"):
        raw = json.loads(payload)
        raw["premium_run"]["family"] = family
        with pytest.raises(DomainError):
            decode_report_selection_v4(json.dumps(raw).encode())
    raw = json.loads(payload)
    raw["premium_run"] = [raw["premium_run"], raw["premium_run"]]
    with pytest.raises(DomainError):
        decode_report_selection_v4(json.dumps(raw).encode())


def test_old_selection_bytes_remain_exact_and_v3_never_defaults_to_v4() -> None:
    for capture in (document().capture, capture_v2()):
        assert encode_report_selection(capture.header.selection) == original_bytes(
            capture.header.selection
        )
    selected = selection_v3()
    expected = {
        "account_id": "00000000-0000-0000-0000-000000000001",
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
        "source_cutoff_at": "2026-08-31T21:00:00Z",
        "snapshot_id": "00000000-0000-0000-0000-000000000002",
        "reporting_currency": "EUR",
        "report_type": "portfolio_summary",
        "sections": ["overview", "allocation", "quality", "scenario"],
        "formats": ["pdf", "csv", "json", "xlsx"],
        "premium_run": {"run_id": "00000000-0000-0000-0000-00000000005a", "family": "scenario"},
        "target_version_id": None,
        "plan_revision_id": None,
        "benchmark_version_id": None,
        "constituent_snapshot_id": None,
        "template_version": "report_template_v1",
        "profile_version": "report_sections_v3",
    }
    payload = json.dumps(expected, ensure_ascii=False, separators=(",", ":")).encode()
    assert encode_report_selection(selected) == payload
    assert decode_report_selection_v3(payload) == selected
    with pytest.raises(DomainError):
        decode_report_selection_v4(payload)


def test_explicit_v4_header_capture_and_flat_manifest_round_trip() -> None:
    from hashlib import sha256

    from trading212_domain.report_manifest import (
        build_report_chunk,
        decode_report_capture_v3,
        decode_report_header_v3,
        decode_report_manifest_v3,
    )
    from trading212_domain.report_manifest_v4 import (
        build_report_manifest_v4,
        decode_report_capture_v4,
        decode_report_header_v4,
        decode_report_manifest_v4,
        encode_report_capture_v4,
        encode_report_header_v4,
        encode_report_manifest_v4,
        encode_report_proof_v4,
        report_document_digest_v4,
    )
    from trading212_domain.report_profile import renderer_profile
    from trading212_domain.report_v4 import (
        ReportCaptureSummaryV4,
        ReportDocumentHeaderV4,
        ReportProofV4,
    )
    from trading212_persistence.report_capture_projection import project_projection

    fixture = case(goal=False, sensitive=False)
    binding = project_projection(fixture.builder, fixture.captured, fixture.saved, fixture.metadata)
    proof = ReportProofV4(
        contexts=tuple(fixture.builder.contexts.values()),
        notes=tuple(fixture.builder.notes.values()),
        note_memberships=tuple(fixture.builder.note_memberships),
    )
    proof_digest = sha256(encode_report_proof_v4(proof)).hexdigest()
    header = ReportDocumentHeaderV4(
        selection=fixture.builder.selection,
        owner_id=fixture.builder.owner_id,
        valuation_at=fixture.builder.valuation_at,
        context_digest=proof_digest,
        tables=fixture.builder.descriptors(),
        document_digest="0" * 64,
        premium_binding=binding,
    )
    header = replace(header, document_digest=report_document_digest_v4(header))
    chunks = tuple(
        build_report_chunk(table, index, rows)
        for index, (table, rows) in enumerate(fixture.builder.rows.items())
        if rows
    )
    capture = ReportCaptureSummaryV4(
        header=header,
        canonical_byte_length=sum(len(chunk.canonical_bytes) for chunk in chunks),
        chunk_count=len(chunks),
        immutable_bindings=tuple(fixture.builder.bindings),
        proof=proof,
        proof_digest=proof_digest,
        renderer_profile=renderer_profile(fixture.builder.selection.formats),
        copy_expires_at=fixture.metadata.expires_at,
    )
    manifest = build_report_manifest_v4(capture)
    for value, encode, decode, prior in (
        (header, encode_report_header_v4, decode_report_header_v4, decode_report_header_v3),
        (capture, encode_report_capture_v4, decode_report_capture_v4, decode_report_capture_v3),
        (manifest, encode_report_manifest_v4, decode_report_manifest_v4, decode_report_manifest_v3),
    ):
        payload = encode(value)  # type: ignore[arg-type]
        assert decode(payload) == value
        with pytest.raises(DomainError):
            prior(payload)
    raw = json.loads(encode_report_manifest_v4(manifest))
    assert "proof" not in raw and "contexts" in raw
    raw["document"]["premium_binding"]["numerical_input_digest"] = "a" * 64
    with pytest.raises(DomainError):
        decode_report_manifest_v4(json.dumps(raw).encode())
