"""Read real PDF bytes to check complete provenance and an inert exact attachment."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from io import BytesIO

import pytest
from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject
from trading212_domain import reports as r
from trading212_domain.report_manifest import (
    build_report_chunk,
    encode_report_manifest,
    encode_report_proof,
    encode_report_schema,
    report_document_digest,
    report_table_digest,
)
from trading212_domain.report_schema import table_schema
from trading212_domain.sources import LicensePermission
from trading212_worker.report_renderers import BoundedArtifactBuffer, PrivateReportRenderer

from tests.unit.domain.report_factories import AT, ReportFixture, document, uid

pytestmark = pytest.mark.unit


class Guard:
    def check(self) -> None:
        pass


def _render(value: ReportFixture) -> PdfReader:
    guard = Guard()
    with BoundedArtifactBuffer(guard=guard) as sink:
        receipt = PrivateReportRenderer().render(
            value,
            format=r.ReportFormat.PDF,
            profile=value.manifest.renderer_profile,
            sink=sink,
            guard=guard,
        )
        result = sink.finish(receipt)
    return PdfReader(BytesIO(result.content), strict=True)


def _rich_document() -> ReportFixture:
    value = document()
    note = r.ReportNote(
        key="assumption.source",
        kind=r.ReportNoteKind.ASSUMPTION,
        family=r.ReportFamily.SNAPSHOT,
        code="capture_assumption",
        text="Synthetic attribution URL remains plain text: https://example.invalid/source",
        related_provenance_set_key="sources.snapshot",
    )
    source = replace(
        value.capture.proof.source_references[0],
        parent_id=uid(4),
        provider_id=uid(5),
        license_version_id=uid(6),
        mapping_version_id=uid(7),
        source_at=AT - timedelta(hours=1),
        first_observed_at=AT,
    )
    license = r.ReportLicenseReference(
        version_id=uid(6),
        provider_id=uid(5),
        license_digest="a" * 64,
        attribution="Synthetic licensed source attribution; no redistribution permission inferred.",
        pinned_store=LicensePermission.ALLOWED,
        pinned_display=LicensePermission.ALLOWED,
        pinned_report=LicensePermission.ALLOWED,
        pinned_export=LicensePermission.DENIED,
        valid_from=AT - timedelta(days=1),
        expires_at=AT + timedelta(days=1),
    )
    proof = replace(
        value.capture.proof,
        contexts=(
            replace(
                value.capture.proof.contexts[0],
                source_at=source.source_at,
                reconciliation_key="reconciliation.snapshot",
            ),
        ),
        source_references=(source,),
        license_references=(license,),
        notes=(*value.capture.proof.notes, note),
        note_memberships=(
            *value.capture.proof.note_memberships,
            r.ReportNoteMembership(note_set_key="notes.snapshot", note_key=note.key),
        ),
        coverage=(
            r.ReportCoverageFact(
                set_key="coverage.snapshot",
                family=r.ReportFamily.SNAPSHOT,
                metric_key="covered_weight",
                value=r.ReportCell(
                    kind=r.CellKind.DECIMAL,
                    state=r.CellState.AVAILABLE,
                    value=Decimal("0.75"),
                    decimal_role=r.DecimalRole.RATIO,
                    context_key="context.snapshot",
                    bound_key="bound.coverage",
                ),
            ),
        ),
        bounds=(
            r.ReportBoundFact(
                key="bound.coverage",
                family=r.ReportFamily.SNAPSHOT,
                kind=r.ReportBoundKind.LOWER_BOUND,
                quantum=Decimal("0.0001"),
                rounding="ROUND_HALF_EVEN",
                positive_below_quantum=True,
            ),
        ),
        reconciliation=(
            r.ReportReconciliationBinding(
                key="reconciliation.snapshot",
                absent=False,
                run_id=uid(8),
                content_digest="b" * 64,
            ),
            r.ReportReconciliationBinding(key="reconciliation.absent", absent=True),
        ),
    )
    proof_digest = sha256(encode_report_proof(proof)).hexdigest()
    header = replace(value.header, context_digest=proof_digest)
    header = replace(header, document_digest=report_document_digest(header))
    value = replace(
        value, capture=replace(value.capture, proof=proof, proof_digest=proof_digest, header=header)
    )
    return replace(
        value,
        capture=replace(
            value.capture,
            canonical_byte_length=sum(len(chunk.canonical_bytes) for chunk in value.chunks)
            + len(encode_report_manifest(value.manifest)),
        ),
    )


@pytest.fixture(scope="module")
def artifact() -> tuple[ReportFixture, PdfReader]:
    value = _rich_document()
    return value, _render(value)


def test_pdf_analytics_precede_complete_proof_without_changing_manifest() -> None:
    value = _rich_document()
    table = r.ReportTableKey.HISTORICAL_OPTIONS
    schema = table_schema(table)
    values = (
        "performance",
        "monthly",
        "time_weighted",
        "none",
        "none",
        "holding",
        "all",
        "require_complete",
        "as_of_cutoff",
        str(uid(9)),
        "calendar-v1",
        "1.0.0",
        "1.0.0",
        "1.0.0",
    )
    cells = []
    for column, item in zip(schema.columns, values, strict=True):
        assert column.kind is not None
        cells.append(r.ReportCell(kind=column.kind, state=r.CellState.AVAILABLE, value=item))
    row = r.ReportRow(
        key="proof.historical.options", context_key="context.snapshot", cells=tuple(cells)
    )
    descriptor = r.ReportTableDescriptor(
        table=table,
        schema_digest=sha256(encode_report_schema(schema)).hexdigest(),
        row_count=1,
        content_digest=report_table_digest(table, (row,)),
    )
    chunk = build_report_chunk(table, 0, (row,))
    header = replace(value.header, tables=(descriptor, *value.header.tables))
    header = replace(header, document_digest=report_document_digest(header))
    value = replace(
        value,
        chunks=(chunk, *value.chunks),
        capture=replace(
            value.capture,
            header=header,
            chunk_count=value.capture.chunk_count + 1,
        ),
    )
    value = replace(
        value,
        capture=replace(
            value.capture,
            canonical_byte_length=sum(len(chunk.canonical_bytes) for chunk in value.chunks)
            + len(encode_report_manifest(value.manifest)),
        ),
    )
    original = encode_report_manifest(value.manifest)
    reader = _render(value)
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert text.index("Snapshot totals\n") < text.index("Technical appendix: canonical evidence\n")
    assert text.index("Technical appendix: canonical evidence\n") < text.index(
        "Historical options\n"
    )
    assert text.index("Historical options\n") < text.index("Sources, methods and quality\n")
    assert "Coverage policy: require_complete" in " ".join(text.split())
    assert value.header.tables[0].table is table
    assert encode_report_manifest(value.manifest) == original
    assert dict(reader.attachments) == {"report-manifest.json": [original]}


def test_pdf_embeds_exact_canonical_manifest_bytes_with_fixed_name_and_mime(
    artifact: tuple[ReportFixture, PdfReader],
) -> None:
    value, reader = artifact
    expected = encode_report_manifest(value.manifest)
    assert dict(reader.attachments) == {"report-manifest.json": [expected]}
    root = reader.trailer["/Root"]
    assert isinstance(root, DictionaryObject)
    catalog_names = root["/Names"]
    assert isinstance(catalog_names, DictionaryObject)
    assert set(catalog_names) == {"/EmbeddedFiles"}
    embedded_files = catalog_names["/EmbeddedFiles"]
    assert isinstance(embedded_files, DictionaryObject)
    names = embedded_files["/Names"]
    assert isinstance(names, ArrayObject)
    assert len(names) == 2 and names[0] == "report-manifest.json"
    specification = names[1].get_object()
    assert set(specification) == {"/Type", "/F", "/Desc", "/EF"}
    assert specification["/Type"] == "/Filespec"
    assert specification["/F"] == "report-manifest.json"
    assert set(specification["/EF"]) == {"/F"}
    stream = specification["/EF"]["/F"]
    assert stream["/Type"] == "/EmbeddedFile"
    assert stream["/Subtype"] == "/application/json"
    assert stream["/Params"]["/Size"] == len(expected)
    assert stream.get_data() == expected


def test_pdf_provenance_is_readable_complete_and_does_not_print_raw_json(
    artifact: tuple[ReportFixture, PdfReader],
) -> None:
    value, reader = artifact
    text = "\n".join(page.extract_text() for page in reader.pages)
    normalized = " ".join(text.split())
    # No indented object dump; every appendix family has a readable label.
    assert '"source_references":' not in text
    for heading in (
        "Immutable input identities",
        "Canonical table inventory",
        "Methods and quality by context",
        "Coverage and numerical bounds",
        "Warnings, assumptions and missing values",
        "Reconciliation",
        "Source register",
        "Source licenses and attribution",
        "Rendering and reproducibility",
    ):
        assert heading in normalized
    manifest = value.manifest
    assert sha256(encode_report_manifest(manifest)).hexdigest() in normalized
    assert manifest.document.document_digest in normalized
    assert manifest.document.context_digest in normalized
    for binding in manifest.bindings:
        assert str(binding.subject_id) in normalized and binding.content_digest in normalized
    for table in manifest.document.tables:
        assert table.schema_digest in normalized and table.content_digest in normalized
    for context in manifest.contexts:
        for literal in (
            context.key,
            context.method_key,
            context.method_version,
            context.quality.value,
            context.valuation_at.isoformat(),
            context.source_cutoff_at.isoformat(),
            context.provenance_set_key,
            context.coverage_set_key,
            context.note_set_key,
        ):
            assert literal in normalized
    for source in manifest.source_references:
        assert source.key in normalized and source.content_digest in normalized
        for identifier in (
            source.subject_id,
            source.parent_id,
            source.provider_id,
            source.license_version_id,
            source.mapping_version_id,
        ):
            assert str(identifier) in normalized
        assert source.source_at is not None and source.source_at.isoformat() in normalized
        assert source.first_observed_at is not None
        assert source.first_observed_at.isoformat() in normalized
    for note in manifest.notes:
        assert note.text in normalized and note.key in normalized and note.code in normalized
    license = manifest.license_references[0]
    assert license.attribution in normalized and license.license_digest in normalized
    assert "Store: allowed; display: allowed; report: allowed; export: denied" in normalized
    assert "covered_weight: 0.75 [bound: bound.coverage]" in normalized
    assert "Quantum: 0.0001; rounding: ROUND_HALF_EVEN; positive below quantum: true" in normalized
    assert "reconciliation.absent | absent" in normalized
    assert "reconciliation.snapshot | recorded" in normalized
    assert "b" * 64 in normalized
    # Existing analytical values and explicit unavailable state remain in the body.
    assert "Ελληνική εταιρεία" in normalized
    assert "unavailable" in normalized.lower() and "reason.missing" in normalized


def test_pdf_attachment_has_no_actions_annotations_or_external_file_reference(
    artifact: tuple[ReportFixture, PdfReader],
) -> None:
    _, reader = artifact
    pending: list[object] = [reader.trailer]
    visited: set[tuple[int, int]] = set()
    forbidden = {
        "/A",
        "/AA",
        "/Annots",
        "/OpenAction",
        "/JS",
        "/JavaScript",
        "/URI",
        "/FS",
        "/Launch",
        "/SubmitForm",
        "/RichMedia",
        "/GoToR",
    }
    while pending:
        item = pending.pop()
        if isinstance(item, IndirectObject):
            identity = (item.idnum, item.generation)
            if identity not in visited:
                visited.add(identity)
                pending.append(item.get_object())
        elif isinstance(item, DictionaryObject):
            assert not forbidden.intersection(item)
            pending.extend(item.values())
        elif isinstance(item, ArrayObject):
            pending.extend(item)
