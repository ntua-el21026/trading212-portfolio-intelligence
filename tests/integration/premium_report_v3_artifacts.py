"""Explicit V3 artifact decoding with the existing complete four-format parity checks.

The earlier report helpers remain unchanged. This fixture shares their scalar/table
verification but selects the explicit V3 decoder and keeps the V3 manifest type.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, replace
from io import BytesIO, StringIO
from uuid import UUID
from xml.etree import ElementTree
from zipfile import ZipFile

from pypdf import PdfReader
from trading212_application import reports as app
from trading212_domain import reports as r
from trading212_domain.report_manifest import (
    canonical_report_cell_value,
    decode_report_manifest_v3,
    decode_report_row,
    encode_report_manifest,
    encode_report_schema,
    report_table_digest,
)
from trading212_domain.report_schema import report_tables, table_schema
from trading212_domain.report_v3 import ReportManifestV3
from trading212_persistence.report_service import PostgresReportService
from trading212_security.principals import Principal

from tests.report_pdf import report_body_text


@dataclass(frozen=True)
class DownloadedReportV3:
    manifest: ReportManifestV3
    tables: dict[r.ReportTableKey, tuple[r.ReportRow, ...]]
    artifacts: dict[r.ReportFormat, bytes]
    csv_records: tuple[dict[str, str], ...] = ()
    pdf_text: str = ""
    pdf_first_page: str = ""
    pdf_body_text: str = ""

    def rows(self, key: r.ReportTableKey) -> tuple[dict[str, r.ReportCell], ...]:
        return tuple(
            dict(
                zip(
                    (column.key for column in table_schema(key).columns),
                    (
                        replace(cell, context_key=cell.context_key or row.context_key)
                        for cell in row.cells
                    ),
                    strict=True,
                )
            )
            for row in self.tables[key]
        )


def _canonical(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


async def download_v3(
    service: PostgresReportService,
    principal: Principal,
    account_id: UUID,
    status: app.ReportJobStatus,
) -> DownloadedReportV3:
    assert status.state is r.ReportJobState.SUCCEEDED
    assert status.context is not None and status.artifacts
    assert len(status.artifacts) == len(r.ReportFormat)
    manifest = await service.get_report_manifest(principal, account_id, status.job_id)
    assert isinstance(manifest, ReportManifestV3)
    assert hashlib.sha256(encode_report_manifest(manifest)).hexdigest() == status.manifest_digest
    artifacts: dict[r.ReportFormat, bytes] = {}
    for metadata in status.artifacts:
        grant = await service.create_report_download_grant(
            principal, account_id, status.job_id, metadata.artifact_id
        )
        artifact = await service.download_report_artifact(
            principal, account_id, status.job_id, metadata.artifact_id, grant_token=grant.token
        )
        assert artifact.metadata == metadata
        assert metadata.mime_type is r.report_mime_type(metadata.format)
        assert 0 < len(artifact.content) == metadata.byte_length <= 10 * 1024 * 1024
        assert hashlib.sha256(artifact.content).hexdigest() == metadata.content_digest
        assert grant.token.encode() not in artifact.content
        artifacts[metadata.format] = artifact.content
    assert sum(map(len, artifacts.values())) <= 25 * 1024 * 1024
    decoded = json.loads(artifacts[r.ReportFormat.JSON])
    assert decoded["schema"] == "report_document_json_v1"
    assert decode_report_manifest_v3(_canonical(decoded["manifest"])) == manifest
    assert decoded["header"] == decoded["manifest"]["document"]
    tables = {
        r.ReportTableKey(item["table"]): tuple(
            decode_report_row(_canonical(row)) for row in item["rows"]
        )
        for item in decoded["tables"]
    }
    assert len(tables) == len(decoded["tables"]) == len(manifest.document.tables)
    assert set(report_tables(manifest.document.selection)) <= set(tables)
    for descriptor in manifest.document.tables:
        rows = tables[descriptor.table]
        assert len(rows) == descriptor.row_count
        assert report_table_digest(descriptor.table, rows) == descriptor.content_digest
    assert manifest.bindings and manifest.contexts and manifest.source_references
    reference_keys = {reference.key for reference in manifest.source_references}
    assert manifest.source_memberships
    assert all(member.source_key in reference_keys for member in manifest.source_memberships)
    return _checked_formats(DownloadedReportV3(manifest, tables, artifacts))


def _tabular_values(report: DownloadedReportV3, records: list[dict[str, str]]) -> None:
    by_table: dict[str, list[dict[str, str]]] = defaultdict(list)
    for record in records:
        by_table[record["table"]].append(record)
    for descriptor in report.manifest.document.tables:
        actual = by_table.pop(descriptor.table.value, [])
        rows = report.tables[descriptor.table]
        schema = table_schema(descriptor.table)
        if descriptor.section is not None or descriptor.dataset is not None:
            expected = [
                (row, column, cell)
                for row in rows
                for column, cell in zip(schema.columns, row.cells, strict=True)
            ]
            assert len(actual) == len(expected)
            for item, (row, column, cell) in zip(actual, expected, strict=True):
                assert item["row_key"] == row.key and item["column_key"] == column.key
                assert item["value"] == canonical_report_cell_value(cell)
                assert item["cell_kind"] == cell.kind.value and item["state"] == cell.state.value
                assert item["currency"] == (cell.currency.value if cell.currency else "")
                assert item["context_key"] == (cell.context_key or row.context_key)
            continue
        fragments: dict[str, list[dict[str, str]]] = defaultdict(list)
        for item in actual:
            assert item["section"] == "proof" and item["value"].startswith("json:")
            assert len(item["value"]) <= 4005
            key = item["column_key"]
            family, *ordinals = key.split(".")
            assert family in {"schema", "row"}
            assert len(ordinals) == (1 if family == "schema" else 2)
            group = "schema" if family == "schema" else f"row.{ordinals[0]}"
            assert key == f"{group}.{len(fragments[group]):06d}"
            fragments[group].append(item)
        if not actual:
            assert not rows
            continue
        schema_bytes = "".join(item["value"][5:] for item in fragments.pop("schema")).encode()
        assert schema_bytes == encode_report_schema(schema)
        reconstructed = []
        for ordinal, row in enumerate(rows):
            pieces = fragments.pop(f"row.{ordinal:06d}")
            assert all(
                item["row_key"] == row.key and item["context_key"] == row.context_key
                for item in pieces
            )
            encoded = "".join(item["value"][5:] for item in pieces).encode()
            reconstructed.append(decode_report_row(encoded))
        assert not fragments and tuple(reconstructed) == rows
        assert report_table_digest(descriptor.table, reconstructed) == descriptor.content_digest
    assert not by_table


def _checked_formats(report: DownloadedReportV3) -> DownloadedReportV3:
    assert set(report.artifacts) == set(r.ReportFormat)
    manifest_bytes = encode_report_manifest(report.manifest)
    csv_rows = list(
        csv.DictReader(StringIO(report.artifacts[r.ReportFormat.CSV].decode(), newline=""))
    )
    fragments = [row["value"] for row in csv_rows if row["table"] == "canonical_manifest"]
    assert fragments and all(value.startswith("json:") for value in fragments)
    assert "".join(value[5:] for value in fragments).encode() == manifest_bytes
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    spreadsheet_records: list[dict[str, str]] = []
    with ZipFile(BytesIO(report.artifacts[r.ReportFormat.XLSX])) as archive:
        root = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))  # noqa: S314 - actual generated synthetic artifact
        fragments = []
        for row in root.findall("s:sheetData/s:row", ns)[1:]:
            value = row[1].find("s:is/s:t", ns)
            assert value is not None and value.text is not None and value.text.startswith("json:")
            fragments.append(value.text[5:])
        assert "".join(fragments).encode() == manifest_bytes
        assert not any(
            "externalLink" in name or "vbaProject" in name for name in archive.namelist()
        )
        for name in archive.namelist():
            if not name.startswith("xl/worksheets/sheet"):
                continue
            sheet = ElementTree.fromstring(archive.read(name))  # noqa: S314 - actual generated synthetic artifact
            assert not sheet.findall(".//s:f", ns) and not sheet.findall(".//s:hyperlink", ns)
            values = [
                [node.text or "" for node in row.findall("s:c/s:is/s:t", ns)]
                for row in sheet.findall("s:sheetData/s:row", ns)
            ]
            if values and values[0][0] == "section":
                spreadsheet_records.extend(
                    dict(zip(values[0], row, strict=True)) for row in values[1:]
                )
    table_csv = [item for item in csv_rows if item["section"] != "manifest"]
    assert len(table_csv) == len(spreadsheet_records)
    for csv_record, xlsx_record in zip(table_csv, spreadsheet_records, strict=True):
        assert csv_record.keys() == xlsx_record.keys()
        for key, xlsx_value in xlsx_record.items():
            csv_value = csv_record[key]
            if key == "value" and csv_record["cell_kind"] not in {"decimal", "integer", "boolean"}:
                assert csv_value in {xlsx_value, "'" + xlsx_value}
            else:
                assert csv_value == xlsx_value
    _tabular_values(report, spreadsheet_records)
    pdf = PdfReader(BytesIO(report.artifacts[r.ReportFormat.PDF]))
    assert 0 < len(pdf.pages) <= r.MAX_REPORT_PDF_PAGES
    assert dict(pdf.attachments) == {"report-manifest.json": [manifest_bytes]}
    pages = [page.extract_text() for page in pdf.pages]
    first = pages[0]
    text = "\n".join(pages)
    assert text.strip()
    assert report.manifest.document.document_digest in " ".join(text.split())
    return replace(
        report,
        csv_records=tuple(csv_rows),
        pdf_text=text,
        pdf_first_page=first,
        pdf_body_text=report_body_text(pages),
    )
