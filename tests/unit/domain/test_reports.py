import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from trading212_domain import reports as r
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.report_manifest import (
    build_report_chunk,
    canonical_report_cell_value,
    decode_report_capture,
    decode_report_chunk,
    decode_report_manifest,
    decode_report_row,
    decode_report_selection,
    encode_report_capture,
    encode_report_chunk,
    encode_report_manifest,
    encode_report_proof,
    encode_report_row,
    encode_report_selection,
    report_document_digest,
    report_manifest_digest,
    report_table_digest,
    validate_report_references,
)
from trading212_domain.report_schema import dataset_tables, table_schema
from trading212_domain.sources import LicensePermission
from trading212_domain.values import CurrencyCode

from tests.unit.domain.report_factories import AT, document, selection, uid

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("report_type", list(r.ReportType))
def test_every_report_type_requires_its_actual_sections_and_references(
    report_type: r.ReportType,
) -> None:
    sections = tuple(r.ReportSection(item) for item in r._REQUIRED_SECTIONS[report_type])
    kwargs: dict[str, Any] = {"report_type": report_type, "sections": sections}
    if report_type is r.ReportType.QUARTERLY:
        kwargs.update(start_date=date(2026, 7, 1), end_date=date(2026, 9, 30))
    if report_type is r.ReportType.ANNUAL:
        kwargs.update(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
    if r.ReportSection.TARGETS in sections:
        kwargs["target_version_id"] = uid(7)
    if r.ReportSection.CONTRIBUTION_PLAN in sections:
        kwargs["plan_revision_id"] = uid(8)
    if r.ReportSection.BENCHMARK in sections:
        kwargs["benchmark_version_id"] = uid(9)
    value = replace(selection(), **kwargs)
    assert decode_report_selection(encode_report_selection(value)) == value
    with pytest.raises(DomainError):
        replace(value, sections=tuple(x for x in sections if x is not r.ReportSection.OVERVIEW))


@pytest.mark.parametrize(
    ("report_type", "start", "end"),
    [
        (r.ReportType.MONTHLY, date(2026, 8, 2), date(2026, 8, 31)),
        (r.ReportType.MONTHLY, date(2026, 8, 1), date(2026, 8, 30)),
        (r.ReportType.QUARTERLY, date(2026, 8, 1), date(2026, 10, 31)),
        (r.ReportType.QUARTERLY, date(2026, 10, 1), date(2027, 1, 1)),
        (r.ReportType.ANNUAL, date(2026, 1, 1), date(2027, 1, 1)),
    ],
)
def test_calendar_reports_reject_partial_or_shifted_periods(
    report_type: r.ReportType, start: date, end: date
) -> None:
    with pytest.raises(DomainError):
        replace(
            selection(),
            report_type=report_type,
            sections=tuple(r.ReportSection(x) for x in r._REQUIRED_SECTIONS[report_type]),
            start_date=start,
            end_date=end,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"formats": ()},
        {"formats": (r.ReportFormat.JSON, r.ReportFormat.JSON)},
        {"sections": (r.ReportSection.OVERVIEW,)},
        {"target_version_id": uid(7)},
        {"constituent_snapshot_id": uid(8)},
        {"source_cutoff_at": datetime(2026, 8, 31)},
        {"template_version": "user-template"},
        {"reporting_currency": "EUR"},
    ],
)
def test_closed_request_rejects_invalid_or_irrelevant_options(change: dict[str, object]) -> None:
    with pytest.raises(DomainError):
        replace(selection(), **cast(Any, change))


def test_later_knowledge_cutoff_remains_distinct_from_valuation() -> None:
    value = document()
    later = replace(value.header.selection, source_cutoff_at=datetime(2026, 9, 1, tzinfo=UTC))
    assert replace(value.header, selection=later).valuation_at == AT


def test_zero_missing_partial_and_exact_decimal_encoding_remain_distinct() -> None:
    zero = r.ReportCell(
        kind=r.CellKind.DECIMAL,
        value=Decimal("-0.000"),
        decimal_role=r.DecimalRole.MONEY,
        currency=CurrencyCode("EUR"),
    )
    missing = replace(zero, value=None, state=r.CellState.UNAVAILABLE, reason_key="missing")
    partial = replace(
        zero, value=Decimal("0.123456789012345678"), state=r.CellState.PARTIAL, reason_key="partial"
    )
    row = r.ReportRow(key="row", context_key="context", cells=(zero, missing, partial))
    restored = decode_report_row(encode_report_row(row))
    assert restored.cells[0].value == Decimal(0)
    assert restored.cells[1].value is None
    assert restored.cells[2] == partial
    assert canonical_report_cell_value(restored.cells[0]) == "0"
    assert canonical_report_cell_value(partial) == "0.123456789012345678"


@pytest.mark.parametrize(
    "invalid", [0.1, True, Decimal("NaN"), Decimal("Infinity"), Decimal("1e-19")]
)
def test_financial_cells_reject_floats_bool_nonfinite_and_excess_scale(invalid: object) -> None:
    with pytest.raises(DomainError):
        r.ReportCell(
            kind=r.CellKind.DECIMAL,
            value=cast(Any, invalid),
            decimal_role=r.DecimalRole.MONEY,
            currency=CurrencyCode("EUR"),
        )


def test_manifest_and_capture_roundtrip_bind_the_same_canonical_sources() -> None:
    value = document()
    assert encode_report_manifest(
        decode_report_manifest(encode_report_manifest(value.manifest))
    ) == encode_report_manifest(value.manifest)
    assert decode_report_capture(encode_report_capture(value.capture)) == value.capture
    for chunk in value.chunks:
        assert decode_report_chunk(encode_report_chunk(chunk)) == chunk
    raw = json.loads(encode_report_manifest(value.manifest))
    assert raw["document"]["selection"]["reporting_currency"] == "EUR"
    assert raw["source_references"][0]["subject_id"] == str(uid(2))
    assert not {"job_id", "capture_id", "generated_at", "expires_at", "token"} & set(raw)


def test_manifest_rejects_unknown_fields_duplicate_keys_and_numeric_json() -> None:
    payload = encode_report_manifest(document().manifest)
    raw = json.loads(payload)
    raw["expires_at"] = "2026-09-30T00:00:00Z"
    with pytest.raises(DomainError):
        decode_report_manifest(json.dumps(raw).encode())
    with pytest.raises(DomainError):
        decode_report_manifest(b'{"document":{},"document":{}}')
    row = document().chunks[0].rows[0]
    raw_row = json.loads(encode_report_row(row))
    raw_row["cells"][3]["value"] = 0.1
    with pytest.raises(DomainError):
        decode_report_row(json.dumps(raw_row).encode())


@pytest.mark.parametrize("text", ["1e0", "+1", "01", "-0", "1.0"])
def test_noncanonical_decimal_spellings_are_not_replay_aliases(text: str) -> None:
    row = r.ReportRow(
        key="row",
        context_key="context",
        cells=(
            r.ReportCell(
                kind=r.CellKind.DECIMAL, value=Decimal("1"), decimal_role=r.DecimalRole.RATIO
            ),
        ),
    )
    raw = json.loads(encode_report_row(row))
    raw["cells"][0]["value"] = text
    with pytest.raises(DomainError):
        decode_report_row(json.dumps(raw, separators=(",", ":")).encode())


def test_chunk_partition_does_not_change_table_semantics() -> None:
    first = document().chunks[0]
    second_row = replace(first.rows[0], key="second")
    joined = build_report_chunk(first.table, 0, (*first.rows, second_row))
    separate = (first, build_report_chunk(first.table, 1, (second_row,)))
    assert report_table_digest(first.table, joined.rows) == report_table_digest(
        first.table, (row for chunk in separate for row in chunk.rows)
    )
    assert joined.digest != separate[0].digest
    with pytest.raises(DomainError):
        encode_report_chunk(replace(first, digest="f" * 64))


def test_proof_order_canonicalizes_and_source_changes_change_manifest() -> None:
    value = document()
    source = value.capture.proof.source_references[0]
    other = replace(source, key="source.other", subject_id=uid(99))
    a = replace(value.capture.proof, source_references=(source, other))
    b = replace(value.capture.proof, source_references=(other, source))
    assert encode_report_proof(a) == encode_report_proof(b)
    changed = replace(value.manifest, source_references=(replace(source, content_digest="1" * 64),))
    with pytest.raises(DomainError):
        encode_report_manifest(changed)
    changed_proof = replace(value.capture.proof, source_references=changed.source_references)
    changed_header = replace(
        changed.document,
        context_digest=hashlib.sha256(encode_report_proof(changed_proof)).hexdigest(),
    )
    changed_header = replace(changed_header, document_digest=report_document_digest(changed_header))
    changed = replace(changed, document=changed_header)
    assert report_manifest_digest(changed) != report_manifest_digest(value.manifest)
    with pytest.raises(DomainError):
        encode_report_manifest(
            replace(
                value.manifest,
                source_memberships=(
                    r.ReportSourceMembership(provenance_set_key="set", source_key="absent"),
                ),
            )
        )


def test_manifest_rejects_header_schema_profile_and_binding_tampering() -> None:
    original = document().manifest
    bad_schema = replace(original.document.tables[0], schema_digest="0" * 64)
    header = replace(original.document, tables=(bad_schema, *original.document.tables[1:]))
    header = replace(header, document_digest=report_document_digest(header))
    bad_values = (
        replace(original, document=replace(original.document, document_digest="0" * 64)),
        replace(original, document=header),
        replace(
            original,
            renderer_profile=replace(
                original.renderer_profile,
                renderer_versions=original.renderer_profile.renderer_versions[:1],
            ),
        ),
        replace(original, bindings=(*original.bindings, *original.bindings)),
    )
    for value in bad_values:
        with pytest.raises(DomainError):
            encode_report_manifest(value)


def test_row_column_text_and_utf8_byte_limits_are_independent() -> None:
    descriptor = document().header.tables[0]
    assert replace(descriptor, row_count=100_000).row_count == 100_000
    with pytest.raises(DomainError) as raised:
        replace(descriptor, row_count=100_001)
    assert raised.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    cell = r.ReportCell(kind=r.CellKind.TEXT, value="\U0001f600" * 4096)
    assert len(canonical_report_cell_value(cell)) == 4096
    with pytest.raises(DomainError):
        replace(cell, value="x" * 4097)
    with pytest.raises(DomainError):
        r.ReportRow(key="row", context_key="context", cells=(cell,) * 65)
    note = document().capture.proof.notes[0]
    proof = r.ReportProof(
        notes=tuple(replace(note, key=f"n{i}", text="\U0001f600" * 4096) for i in range(140))
    )
    with pytest.raises(DomainError) as oversized:
        encode_report_proof(proof)
    assert oversized.value.code is ErrorCode.INPUT_BOUND_EXCEEDED


def test_every_registered_table_is_closed_and_backed_exports_exist() -> None:
    for table in r.ReportTableKey:
        schema = table_schema(table)
        assert 1 <= len(schema.columns) <= 64
        assert len({column.key for column in schema.columns}) == len(schema.columns)
    for dataset in r.ExportDataset:
        if dataset is r.ExportDataset.ALERTS:
            with pytest.raises(DomainError):
                dataset_tables(dataset, r.ExportFieldSet.STANDARD)
        else:
            for field_set in r.ExportFieldSet:
                assert dataset_tables(dataset, field_set)
    with pytest.raises(DomainError):
        table_schema(cast(Any, "arbitrary"))


def test_metric_metadata_remains_exact_and_only_empty_optional_fields_are_omitted() -> None:
    from trading212_domain.enums import QualityState

    cell = r.ReportCell(
        kind=r.CellKind.DECIMAL,
        value=Decimal("0"),
        decimal_role=r.DecimalRole.RATIO,
        quality=QualityState.STALE,
        origin=r.ReportMetricOrigin.DERIVED,
        confidence=Decimal("0.900000000000000001"),
        method_key="canonical_method",
        method_version="1.0.0",
        coverage_key="prices",
        provenance_set_key="prices.sources",
    )
    row = r.ReportRow(key="metric", context_key="context", cells=(cell,))
    payload = encode_report_row(row)
    assert decode_report_row(payload) == row
    parsed = json.loads(payload)
    assert parsed["cells"][0]["confidence"] == "0.900000000000000001"
    assert all(
        name not in parsed["cells"][0]
        for name in ("note_set_key", "currency", "context_key", "reason_key", "bound_key")
    )
    assert parsed["cells"][0]["value"] == "0"
    assert parsed["cells"][0]["state"] == "available"
    parsed["cells"][0]["note_set_key"] = None
    with pytest.raises(DomainError):
        decode_report_row(json.dumps(parsed, separators=(",", ":")).encode())
    with pytest.raises(DomainError):
        replace(cell, confidence=Decimal("1.000000000000000001"))
    with pytest.raises(DomainError):
        replace(cell, origin=cast(Any, "invented_origin"))
    with pytest.raises(DomainError):
        replace(cell, method_version=None)


@pytest.mark.parametrize(
    "field",
    [
        "context_key",
        "reason_key",
        "bound_key",
        "provenance_set_key",
        "note_set_key",
        "coverage_key",
    ],
)
@pytest.mark.parametrize("location", ["inline", "coverage"])
def test_manifest_rejects_unresolved_cell_references_before_sealing(
    field: str, location: str
) -> None:
    fixture = document()
    chunk = fixture.chunks[0]
    row = chunk.rows[0]
    cell = replace(row.cells[0], **cast(Any, {field: "missing.reference"}))
    proof = fixture.capture.proof
    if location == "inline":
        proof = replace(
            proof,
            proof_relations=(
                r.ReportProofRelation(
                    table=chunk.table, row=replace(row, cells=(cell, *row.cells[1:]))
                ),
            ),
        )
    else:
        proof = replace(
            proof,
            coverage=(
                r.ReportCoverageFact(
                    set_key="coverage.snapshot",
                    family=r.ReportFamily.SNAPSHOT,
                    metric_key="complete",
                    value=cell,
                ),
            ),
        )
    # Keep every digest coherent: rejection must concern the actual missing link.
    original = fixture.manifest
    header = replace(
        original.document, context_digest=hashlib.sha256(encode_report_proof(proof)).hexdigest()
    )
    header = replace(header, document_digest=report_document_digest(header))
    manifest = replace(
        original, document=header, proof_relations=proof.proof_relations, coverage=proof.coverage
    )
    with pytest.raises(DomainError) as raised:
        encode_report_manifest(manifest)
    assert raised.value.field == field


def test_manifest_rejects_unresolved_inline_row_context() -> None:
    fixture = document()
    chunk = fixture.chunks[0]
    proof = replace(
        fixture.capture.proof,
        proof_relations=(
            r.ReportProofRelation(
                table=chunk.table, row=replace(chunk.rows[0], context_key="absent.context")
            ),
        ),
    )
    with pytest.raises(DomainError) as raised:
        validate_report_references(proof)
    assert raised.value.field == "context_key"


def test_reference_resolution_preserves_declared_empty_and_shared_sets() -> None:
    original = document().capture.proof
    context = original.contexts[0]
    empty = replace(
        original, source_references=(), source_memberships=(), notes=(), note_memberships=()
    )
    validate_report_references(
        empty,
        context_keys=(context.key,),
        provenance_set_keys=(context.provenance_set_key,),
        note_set_keys=(context.note_set_key,),
        coverage_keys=(context.coverage_set_key,),
    )
    shared = replace(
        original,
        source_memberships=(
            *original.source_memberships,
            r.ReportSourceMembership(
                provenance_set_key="shared.sources", source_key="source.snapshot"
            ),
        ),
        note_memberships=(
            *original.note_memberships,
            r.ReportNoteMembership(note_set_key="shared.notes", note_key="reason.missing"),
        ),
        bounds=(
            r.ReportBoundFact(
                key="shared.bound", family=r.ReportFamily.XRAY, kind=r.ReportBoundKind.EXACT
            ),
        ),
    )
    validate_report_references(
        shared,
        provenance_set_keys=("shared.sources",),
        note_set_keys=("shared.notes",),
        reason_keys=("reason.missing",),
        bound_keys=("shared.bound",),
    )


def test_historical_coverage_base_requires_actual_complete_measure_triplet() -> None:
    proof = document().capture.proof
    facts = tuple(
        r.ReportCoverageFact(
            set_key="coverage.snapshot",
            family=r.ReportFamily.SNAPSHOT,
            metric_key=f"valuation_cells.{label}",
            value=r.ReportCell(
                kind=r.CellKind.BOOLEAN if label == "complete" else r.CellKind.INTEGER,
                value=True if label == "complete" else 0,
            ),
        )
        for label in ("expected_count", "available_count", "complete")
    )
    validate_report_references(
        replace(proof, coverage=facts),
        coverage_keys=("valuation_cells", "valuation_cells.complete", "coverage.snapshot"),
    )
    for actual in (facts[:-1], (*facts[:-1], replace(facts[-1], set_key="different.set"))):
        with pytest.raises(DomainError) as raised:
            validate_report_references(
                replace(proof, coverage=actual), coverage_keys=("valuation_cells",)
            )
        assert raised.value.field == "coverage_key"


def test_streamed_reference_context_bound_fails_before_resolution() -> None:
    with pytest.raises(DomainError) as raised:
        validate_report_references(
            r.ReportProof(), context_keys=tuple(f"context.{i}" for i in range(257))
        )
    assert raised.value.code is ErrorCode.INPUT_BOUND_EXCEEDED


def test_manifest_rejects_unresolved_note_provenance_and_context_reconciliation() -> None:
    original = document().manifest
    cases = (
        (
            replace(
                original,
                notes=(replace(original.notes[0], related_provenance_set_key="missing.sources"),),
            ),
            "provenance_set_key",
        ),
        (
            replace(
                original,
                contexts=(
                    replace(original.contexts[0], reconciliation_key="missing.reconciliation"),
                ),
            ),
            "reconciliation_key",
        ),
    )
    for manifest, expected in cases:
        with pytest.raises(DomainError) as raised:
            encode_report_manifest(manifest)
        assert raised.value.field == expected


def test_note_absence_and_actual_reconciliation_absence_are_explicit_valid_values() -> None:
    original = document().capture.proof
    proof = replace(
        original,
        contexts=(replace(original.contexts[0], reconciliation_key="actual.absence"),),
        reconciliation=(r.ReportReconciliationBinding(key="actual.absence", absent=True),),
    )
    assert proof.notes[0].related_provenance_set_key is None
    validate_report_references(proof)
    validate_report_references(
        replace(
            proof, notes=(replace(proof.notes[0], related_provenance_set_key="sources.snapshot"),)
        )
    )


@pytest.mark.parametrize("kind", ["licenses", "reconciliation"])
def test_manifest_rejects_duplicate_license_and_reconciliation_identity(kind: str) -> None:
    original = document().manifest
    if kind == "licenses":
        license = r.ReportLicenseReference(
            version_id=uid(90),
            provider_id=uid(91),
            license_digest="a" * 64,
            attribution="Synthetic licensed data",
            valid_from=AT,
            pinned_store=LicensePermission.ALLOWED,
            pinned_display=LicensePermission.ALLOWED,
            pinned_report=LicensePermission.ALLOWED,
            pinned_export=LicensePermission.ALLOWED,
        )
        manifest = replace(original, license_references=(license, license))
    else:
        binding = r.ReportReconciliationBinding(key="actual.absence", absent=True)
        manifest = replace(original, reconciliation=(binding, binding))
    with pytest.raises(DomainError) as raised:
        encode_report_manifest(manifest)
    assert raised.value.field == kind


def test_manifest_table_unavailable_reason_must_resolve() -> None:
    original = document().manifest
    table = replace(original.document.tables[0], reason_key="missing.table.reason")
    manifest = replace(
        original, document=replace(original.document, tables=(table, *original.document.tables[1:]))
    )
    with pytest.raises(DomainError) as raised:
        encode_report_manifest(manifest)
    assert raised.value.field == "reason_key"
