"""Read actual artifact formats independently and verify exact values and safe text."""

import csv
import json
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from io import BytesIO, StringIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from pypdf import PdfReader
from pypdf.generic import DictionaryObject
from trading212_application.reports import ReportRenderError
from trading212_domain.enums import QualityState
from trading212_domain.report_manifest import (
    build_report_chunk,
    encode_report_manifest,
    encode_report_proof,
    report_document_digest,
    report_table_digest,
)
from trading212_domain.reports import (
    ReportFailureCode,
    ReportFormat,
    ReportMetricOrigin,
    ReportNoteMembership,
    ReportRow,
    ReportSection,
    ReportTableKey,
)
from trading212_worker.report_renderers import BoundedArtifactBuffer, PrivateReportRenderer
from trading212_worker.report_renderers.pdf import _analytical_order

from tests.unit.domain.report_factories import ReportFixture, document

pytestmark = pytest.mark.unit


class Guard:
    def __init__(self, fail_after: int | None = None) -> None:
        self.calls = 0
        self.fail_after = fail_after

    def check(self) -> None:
        self.calls += 1
        if self.fail_after is not None and self.calls >= self.fail_after:
            raise ReportRenderError(ReportFailureCode.LEASE_EXPIRED)


def render(value: ReportFixture, format: ReportFormat) -> bytes:
    guard = Guard()
    with BoundedArtifactBuffer(guard=guard) as sink:
        receipt = PrivateReportRenderer().render(
            value, format=format, profile=value.manifest.renderer_profile, sink=sink, guard=guard
        )
        artifact = sink.finish(receipt)
    assert artifact.byte_length == len(artifact.content)
    assert artifact.content_digest == sha256(artifact.content).hexdigest()
    assert guard.calls > 10
    return artifact.content


def replace_fixture_row(value: ReportFixture, chunk_index: int, row: ReportRow) -> ReportFixture:
    first = value.chunks[chunk_index]
    chunks = tuple(
        build_report_chunk(first.table, first.ordinal, (row,)) if index == chunk_index else chunk
        for index, chunk in enumerate(value.chunks)
    )
    tables = tuple(
        replace(table, content_digest=report_table_digest(table.table, (row,)))
        if table.table is first.table
        else table
        for table in value.header.tables
    )
    header = replace(value.header, tables=tables)
    header = replace(header, document_digest=report_document_digest(header))
    result = ReportFixture(replace(value.capture, header=header), chunks)
    return replace(
        result,
        capture=replace(
            result.capture,
            canonical_byte_length=sum(len(chunk.canonical_bytes) for chunk in chunks)
            + len(encode_report_manifest(result.manifest)),
        ),
    )


def test_json_preserves_exact_cells_full_manifest_and_explicit_unavailable_states() -> None:
    value = document()
    artifact = json.loads(render(value, ReportFormat.JSON))
    assert artifact["manifest"] == json.loads(encode_report_manifest(value.manifest))
    assert len(artifact["tables"]) == len(value.header.tables)
    totals = artifact["tables"][0]["rows"][0]["cells"]
    assert any(cell["value"] == "0" and cell["state"] == "available" for cell in totals)
    assert any(cell["value"] is None and cell["state"] == "unavailable" for cell in totals)


def test_pdf_discloses_an_outside_period_snapshot_before_showing_totals() -> None:
    value = document()
    note = replace(
        value.capture.proof.notes[0],
        key="snapshot.outside_period",
        code="snapshot_outside_period",
        text="Snapshot totals are not period-end balances.",
    )
    proof = replace(
        value.capture.proof,
        notes=(*value.capture.proof.notes, note),
        note_memberships=(
            *value.capture.proof.note_memberships,
            ReportNoteMembership(note_set_key="notes.snapshot", note_key=note.key),
        ),
    )
    digest = sha256(encode_report_proof(proof)).hexdigest()
    header = replace(value.header, context_digest=digest)
    header = replace(header, document_digest=report_document_digest(header))
    value = replace(
        value, capture=replace(value.capture, proof=proof, proof_digest=digest, header=header)
    )
    value = replace(
        value,
        capture=replace(
            value.capture,
            canonical_byte_length=sum(len(chunk.canonical_bytes) for chunk in value.chunks)
            + len(encode_report_manifest(value.manifest)),
        ),
    )
    first_page = PdfReader(BytesIO(render(value, ReportFormat.PDF))).pages[0].extract_text()
    assert first_page.index(note.text) < first_page.index("Snapshot totals\n")


def test_csv_round_trip_manifest_formula_text_quotes_unicode_and_missing_values() -> None:
    value = document()
    payload = render(value, ReportFormat.CSV)
    assert b"\r\n" in payload
    records = list(csv.DictReader(StringIO(payload.decode(), newline="")))
    fragments = [row["value"][5:] for row in records if row["section"] == "manifest"]
    assert "".join(fragments).encode() == encode_report_manifest(value.manifest)
    texts = [row["value"] for row in records if row["cell_kind"] == "text"]
    assert any(text.startswith("' =SUM(1,2)") and "Ελληνική" in text for text in texts)
    assert any(row["value"] == "" and row["state"] == "unavailable" for row in records)
    assert any(row["value"] == "0" and row["state"] == "available" for row in records)


def test_xlsx_contains_only_explicit_text_without_formulas_or_external_links() -> None:
    value = document()
    with ZipFile(BytesIO(render(value, ReportFormat.XLSX))) as archive:
        names = archive.namelist()
        assert not any("externalLink" in name or "vbaProject" in name for name in names)
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        sheets = [name for name in names if name.startswith("xl/worksheets/sheet")]
        all_texts: list[str] = []
        for name in sheets:
            root = ElementTree.fromstring(archive.read(name))  # noqa: S314 - generated fixture bytes
            assert not root.findall(".//s:f", ns)
            assert not root.findall(".//s:hyperlink", ns)
            assert all(cell.attrib["t"] == "inlineStr" for cell in root.findall(".//s:c", ns))
            all_texts.extend(node.text or "" for node in root.findall(".//s:t", ns))
        assert any(text.startswith(" =SUM(1,2)") and "Ελληνική" in text for text in all_texts)
        manifest = ElementTree.fromstring(  # noqa: S314 - generated fixture bytes
            archive.read("xl/worksheets/sheet1.xml")
        )
        fragments = []
        for row in manifest.findall("s:sheetData/s:row", ns)[1:]:
            text = row[1].find("s:is/s:t", ns)
            assert text is not None and text.text is not None
            fragments.append(text.text[5:])
        assert "".join(fragments).encode() == encode_report_manifest(value.manifest)


@pytest.mark.parametrize(
    "literal",
    [
        "<r><t>Literal rich-text marker</t></r>",
        '<r><t xml:space="preserve"> alpha &lt; beta </t></r>',
        '<r></is></c><c r="XFD1"><f>1+1</f></c><c t="inlineStr"><is><r></r>',
    ],
)
def test_xlsx_never_interprets_literal_rich_xml_or_injected_cells(literal: str) -> None:
    fixture = document()
    position = fixture.chunks[1].rows[0]
    cells = list(position.cells)
    cells[4] = replace(cells[4], value=literal)
    fixture = replace_fixture_row(fixture, 1, replace(position, cells=tuple(cells)))
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(BytesIO(render(fixture, ReportFormat.XLSX))) as archive:
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet3.xml"))  # noqa: S314 - generated regression artifact
        assert not sheet.findall(".//s:f", ns)
        assert not sheet.findall(".//s:r", ns)
        assert literal in [node.text for node in sheet.findall(".//s:t", ns)]


def test_pdf_embeds_unicode_fonts_and_exposes_selectable_text_and_navigation() -> None:
    value = document()
    reader = PdfReader(BytesIO(render(value, ReportFormat.PDF)))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "Ελληνική εταιρεία" in text
    assert "unavailable" in text and "reason.missing" in text
    assert "Source cutoff:" in text and "Snapshot:" in text
    assert "not certified PDF/UA" in " ".join(text.split())
    assert len(reader.outline) >= 3
    fonts: list[DictionaryObject] = []
    for page in reader.pages:
        resources = page["/Resources"].get_object()
        assert isinstance(resources, DictionaryObject)
        entries = resources["/Font"].get_object()
        assert isinstance(entries, DictionaryObject)
        for reference in entries.values():
            font = reference.get_object()
            assert isinstance(font, DictionaryObject)
            fonts.append(font)
    assert any("/FontFile2" in font.get("/FontDescriptor", {}) for font in fonts)


@pytest.mark.parametrize("inherit_context", [False, True])
def test_every_format_preserves_effective_metric_metadata(inherit_context: bool) -> None:
    value = document()
    first = value.chunks[0]
    original = first.rows[0]
    cells = list(original.cells)
    cells[3] = replace(
        cells[3],
        quality=QualityState.ESTIMATED,
        origin=ReportMetricOrigin.DERIVED_DETERMINISTIC,
        coverage_key="coverage.snapshot",
        confidence=Decimal("0.875"),
        method_key="portfolio_summary",
        method_version="1.0.0",
        provenance_set_key="sources.snapshot",
        note_set_key="notes.snapshot",
    )
    if inherit_context:
        cells[3] = replace(
            cells[3],
            context_key=None,
            coverage_key=None,
            method_key=None,
            method_version=None,
            provenance_set_key=None,
            note_set_key=None,
        )
    changed = replace(original, cells=tuple(cells))
    value = replace_fixture_row(value, 0, changed)
    expected = {
        "quality": "estimated",
        "origin": "derived_deterministic",
        "coverage_key": "coverage.snapshot",
        "confidence": "0.875",
        "method_key": "portfolio_summary",
        "method_version": "1.0.0",
        "provenance_set_key": "sources.snapshot",
        "note_set_key": "notes.snapshot",
    }
    encoded = json.loads(render(value, ReportFormat.JSON))
    direct = encoded["tables"][0]["rows"][0]["cells"][3]
    context = encoded["manifest"]["contexts"][0]
    effective = {
        key: direct.get(key, context.get("coverage_set_key" if key == "coverage_key" else key))
        for key in expected
    }
    assert effective == expected
    if inherit_context:
        assert {"context_key", "method_key", "method_version", "coverage_key"}.isdisjoint(direct)
        assert {key: direct[key] for key in ("quality", "origin", "confidence")} == {
            key: expected[key] for key in ("quality", "origin", "confidence")
        }
    records = csv.DictReader(StringIO(render(value, ReportFormat.CSV).decode(), newline=""))
    total = next(
        row for row in records if row["row_key"] == original.key and row["column_key"] == "total"
    )
    assert {key: total[key] for key in expected} == expected
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(BytesIO(render(value, ReportFormat.XLSX))) as archive:
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet2.xml"))  # noqa: S314 - generated bytes
        rows = [
            [node.text or "" for node in row.findall("s:c/s:is/s:t", ns)]
            for row in sheet.findall("s:sheetData/s:row", ns)
        ]
        entries = [dict(zip(rows[0], row, strict=True)) for row in rows[1:]]
        total = next(row for row in entries if row["column_key"] == "total")
        assert {key: total[key] for key in expected} == expected
    reader = PdfReader(BytesIO(render(value, ReportFormat.PDF)))
    visible = " ".join(page.extract_text() for page in reader.pages).split(
        "Sources, methods and quality", 1
    )[0]
    for text in expected.values():
        assert text in " ".join(visible.split())


@pytest.mark.parametrize("format", list(ReportFormat))
def test_every_format_checks_artifact_capacity_and_closes_buffer(format: ReportFormat) -> None:
    value, guard = document(), Guard()
    with BoundedArtifactBuffer(guard=guard, limit=128) as sink:
        with pytest.raises(ReportRenderError) as error:
            PrivateReportRenderer().render(
                value,
                format=format,
                profile=value.manifest.renderer_profile,
                sink=sink,
                guard=guard,
            )
        assert error.value.code is ReportFailureCode.LIMIT_EXCEEDED
        assert sink.byte_length <= 128


def test_xlsx_interruption_removes_private_scratch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    value, guard = document(), Guard(fail_after=30)
    with BoundedArtifactBuffer(guard=guard) as sink, pytest.raises(ReportRenderError):
        PrivateReportRenderer().render(
            value,
            format=ReportFormat.XLSX,
            profile=value.manifest.renderer_profile,
            sink=sink,
            guard=guard,
        )
    assert tuple(tmp_path.iterdir()) == ()


def test_renderer_rejects_changed_profile_before_any_artifact_byte() -> None:
    value, guard = document(), Guard()
    profile = value.manifest.renderer_profile
    changed = replace(
        profile,
        renderer_versions=tuple(
            replace(version, version="0.0.0") for version in profile.renderer_versions
        ),
    )
    with BoundedArtifactBuffer(guard=guard) as sink:
        with pytest.raises(ReportRenderError):
            PrivateReportRenderer().render(
                value, format=ReportFormat.JSON, profile=changed, sink=sink, guard=guard
            )
        assert sink.byte_length == 0


@pytest.mark.parametrize("change", ["omit", "replace", "corrupt"])
def test_renderer_refuses_missing_changed_or_corrupt_canonical_rows(change: str) -> None:
    value, guard = document(), Guard()
    first = value.chunks[0]
    if change == "omit":
        changed = replace(value, chunks=value.chunks[1:])
    elif change == "replace":
        row = replace(first.rows[0], key="different.record")
        changed = replace(
            value, chunks=(build_report_chunk(first.table, 0, (row,)), *value.chunks[1:])
        )
    else:
        changed = replace(value, chunks=(replace(first, digest="f" * 64), *value.chunks[1:]))
    with BoundedArtifactBuffer(guard=guard) as sink, pytest.raises(ReportRenderError) as failure:
        PrivateReportRenderer().render(
            changed,
            format=ReportFormat.JSON,
            profile=value.manifest.renderer_profile,
            sink=sink,
            guard=guard,
        )
    assert failure.value.code is ReportFailureCode.INPUT_CHANGED


@pytest.mark.parametrize(
    "table",
    (
        ReportTableKey.PLANNING_COMPANY_ACTUALS_V1,
        ReportTableKey.PLANNING_COMPANY_BASIS_V1,
        ReportTableKey.XRAY_SUMMARY,
        ReportTableKey.XRAY_QUALITY,
        ReportTableKey.XRAY_DIMENSIONS,
        ReportTableKey.XRAY_EXPOSURES,
        ReportTableKey.XRAY_PATHS,
    ),
)
def test_pdf_places_optional_company_tables_after_drift_before_contribution_plan(
    table: ReportTableKey,
) -> None:
    template = document().header.tables[0]
    drift = replace(template, section=ReportSection.DRIFT, table=ReportTableKey.DRIFT_TOTALS)
    company = replace(template, section=ReportSection.DRIFT, table=table)
    plan = replace(
        template, section=ReportSection.CONTRIBUTION_PLAN, table=ReportTableKey.PLAN_SUMMARY
    )
    assert sorted((plan, company, drift), key=_analytical_order) == [drift, company, plan]
