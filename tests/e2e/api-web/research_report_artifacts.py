"""Inspect real research browser downloads using canonical validators, never renderers."""

from __future__ import annotations

import json
import sys
import unicodedata
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from scenario_report_artifacts import (
    Document,
    _compact,
    _csv,
    _display,
    _json,
    _read,
    _tabular,
    _xlsx,
)
from trading212_domain import reports as r
from trading212_domain.report_manifest import (
    decode_report_header_v3,
    decode_report_manifest_v3,
    decode_report_row,
    encode_report_manifest,
    report_table_digest,
)
from trading212_domain.report_research import ReportResearchBinding
from trading212_domain.report_schema import table_schema

from tests.report_pdf import report_body_text


def document(content: bytes, manifest_bytes: bytes) -> Document:
    raw = json.loads(content)
    assert type(raw) is dict and set(raw) == {"schema", "manifest", "header", "tables"}
    assert raw["schema"] == "report_document_json_v1"
    manifest = decode_report_manifest_v3(manifest_bytes)
    assert _json(raw["manifest"]) == manifest_bytes == encode_report_manifest(manifest)
    assert decode_report_header_v3(_json(raw["header"])) == manifest.document
    assert isinstance(manifest.document.premium_binding, ReportResearchBinding)
    tables = {}
    for table in raw["tables"]:
        assert type(table) is dict and set(table) == {"table", "rows"}
        key = r.ReportTableKey(table["table"])
        assert key not in tables and type(table["rows"]) is list
        tables[key] = tuple(decode_report_row(_json(row)) for row in table["rows"])
    assert tuple(tables) == tuple(item.table for item in manifest.document.tables)
    for descriptor in manifest.document.tables:
        assert len(tables[descriptor.table]) == descriptor.row_count
        assert (
            report_table_digest(descriptor.table, tables[descriptor.table])
            == descriptor.content_digest
        )
    return Document(manifest, tables)


def pdf(document: Document, content: bytes, manifest: bytes) -> None:
    retained = PdfReader(BytesIO(content))
    assert 0 < len(retained.pages) <= r.MAX_REPORT_PDF_PAGES
    assert dict(retained.attachments) == {"report-manifest.json": [manifest]}
    text = _compact(report_body_text([page.extract_text() for page in retained.pages]))
    binding = document.manifest.document.premium_binding
    assert isinstance(binding, ReportResearchBinding)
    for value in (
        sha256(manifest).hexdigest(),
        binding.item_selection_digest,
        binding.event_revision_digest,
        binding.xray.input_digest,
        binding.xray.result_digest,
    ):
        assert value in text
    analytical = text.split("Technicalappendix:canonicalevidence", 1)[0]
    assert analytical and analytical != text
    for key in (
        r.ReportTableKey.RESEARCH_BASIS_V1,
        r.ReportTableKey.RESEARCH_EVENT_V1,
        r.ReportTableKey.RESEARCH_PORTFOLIO_V1,
        r.ReportTableKey.RESEARCH_NOTES_V1,
        r.ReportTableKey.RESEARCH_REVIEW_V1,
    ):
        assert _compact(key.value.replace("_", " ").capitalize()) in analytical
        schema = table_schema(key)
        for row_index, row in enumerate(document.tables[key]):
            first = _compact(schema.columns[0].key.replace("_", " ").capitalize() + ":")
            marker = _compact(f"Record: {row.key}") + first
            assert analytical.count(marker) == 1
            record = first + analytical.split(marker, 1)[1].split("Defaultrowcontext:", 1)[0]
            for column_index, (column, cell) in enumerate(
                zip(schema.columns, row.cells, strict=True)
            ):
                label = column.key.replace("_", " ").replace(".", " / ").capitalize()
                # The existing report_template_v1 prints controls as visible hex escapes.
                # Spell these independently before removing PDF layout whitespace; otherwise
                # compaction incorrectly deletes an original newline from the expected value.
                displayed = "".join(
                    f"\\u{ord(character):04x}"
                    if unicodedata.category(character).startswith("C")
                    else character
                    for character in _display(cell)
                )
                expected = _compact(f"{label}: {displayed}")
                assert expected in record, json.dumps(
                    {
                        "check": "pdf_named_value_parity",
                        "table": key.value,
                        "row_index": row_index,
                        "row_key_sha256": sha256(row.key.encode()).hexdigest(),
                        "column_index": column_index,
                        "column": column.key,
                        "expected_sha256": sha256(expected.encode()).hexdigest(),
                        "record_sha256": sha256(record.encode()).hexdigest(),
                        "expected_characters": len(expected),
                        "record_characters": len(record),
                    },
                    sort_keys=True,
                )


def main() -> None:
    assert len(sys.argv) == 2
    directory = Path(sys.argv[1])
    manifest = _read(directory / "manifest.json", r.MAX_REPORT_MANIFEST_BYTES)
    artifacts = {
        key: _read(directory / f"report.{key}", r.MAX_REPORT_ARTIFACT_BYTES)
        for key in ("json", "csv", "xlsx", "pdf")
    }
    assert sum(map(len, artifacts.values())) <= r.MAX_REPORT_JOB_BYTES
    parsed = document(artifacts["json"], manifest)
    csv_rows = _csv(artifacts["csv"], manifest)
    _tabular(parsed, csv_rows, csv_escaped=True)
    assert any(
        row["table"] == "research_notes_v1"
        and row["column_key"] == "note"
        and row["value"].startswith("'=1+1")
        for row in csv_rows
    )
    _tabular(
        parsed,
        _xlsx(artifacts["xlsx"], manifest, table_count=len(parsed.tables)),
        csv_escaped=False,
    )
    pdf(parsed, artifacts["pdf"], manifest)
    print("Verified research browser four-format bytes, fixed tables and exact named values.")


if __name__ == "__main__":
    main()
