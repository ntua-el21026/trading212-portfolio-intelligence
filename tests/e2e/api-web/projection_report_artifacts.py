"""Inspect four real browser downloads against their independent canonical manifest.

Invoked once by projection-reports.spec.ts after all downloads finish. This helper
opens only the five fixed files in its private temporary directory. It imports
canonical validators, never capture/calculation/renderer implementations.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO, StringIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from pypdf import PdfReader
from trading212_domain import reports as r
from trading212_domain.report_manifest import (
    canonical_report_cell_value,
    decode_report_row,
    encode_report_row,
    encode_report_schema,
    report_table_digest,
)
from trading212_domain.report_manifest_v4 import (
    decode_report_header_v4,
    decode_report_manifest_v4,
    encode_report_manifest_v4,
)
from trading212_domain.report_schema import table_schema
from trading212_domain.report_v4 import ReportManifestV4, ReportProjectionRunBinding
from trading212_domain.values import decimal_string

from tests.report_pdf import report_body_text

_COLUMNS = (
    "section",
    "table",
    "row_key",
    "column_key",
    "cell_kind",
    "value",
    "decimal_role",
    "currency",
    "state",
    "reason_key",
    "bound_key",
    "context_key",
    "quality",
    "origin",
    "coverage_key",
    "confidence",
    "method_key",
    "method_version",
    "provenance_set_key",
    "note_set_key",
)
_NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


@dataclass(frozen=True)
class Document:
    manifest: ReportManifestV4
    tables: dict[r.ReportTableKey, tuple[r.ReportRow, ...]]


def _read(path: Path, maximum: int) -> bytes:
    size = path.stat().st_size
    assert 0 < size <= maximum, "Artifact exceeds its existing encoded-byte bound."
    with path.open("rb") as source:
        content = source.read(maximum + 1)
    assert len(content) == size
    return content


def _json(value: object) -> bytes:
    # Preserve canonical field insertion order from the downloaded document.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _document(content: bytes, manifest_bytes: bytes) -> Document:
    raw = json.loads(content)
    assert type(raw) is dict and set(raw) == {"schema", "manifest", "header", "tables"}
    assert raw["schema"] == "report_document_json_v1"
    manifest = decode_report_manifest_v4(manifest_bytes)
    assert _json(raw["manifest"]) == manifest_bytes == encode_report_manifest_v4(manifest)
    assert decode_report_header_v4(_json(raw["header"])) == manifest.document
    assert manifest.document.selection.profile_version == "report_sections_v4"
    assert manifest.document.document_schema_version == "4.0.0"
    assert isinstance(manifest.document.premium_binding, ReportProjectionRunBinding)
    assert type(raw["tables"]) is list
    tables: dict[r.ReportTableKey, tuple[r.ReportRow, ...]] = {}
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


def _fragments(values: Sequence[tuple[str, str]]) -> bytes:
    assert values
    for index, (ordinal, value) in enumerate(values):
        assert ordinal == f"{index:06d}" and value.startswith("json:") and len(value) <= 4005
    return "".join(value[5:] for _, value in values).encode()


def _csv(content: bytes, manifest: bytes) -> list[dict[str, str]]:
    reader = csv.DictReader(StringIO(content.decode("utf-8"), newline=""))
    assert tuple(reader.fieldnames or ()) == _COLUMNS
    rows = list(reader)
    assert all(
        tuple(row) == _COLUMNS and all(isinstance(v, str) for v in row.values()) for row in rows
    )
    fragments = [
        (row["row_key"], row["value"]) for row in rows if row["table"] == "canonical_manifest"
    ]
    assert _fragments(fragments) == manifest
    return [row for row in rows if row["section"] != "manifest"]


def _xlsx(content: bytes, manifest: bytes, *, table_count: int) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    with ZipFile(BytesIO(content)) as archive:
        infos = archive.infolist()
        assert len(infos) <= 256 and len({item.filename for item in infos}) == len(infos)
        assert sum(item.file_size for item in infos) <= 64 * 1024 * 1024
        assert not any(
            "externalLink" in item.filename or "vbaProject" in item.filename for item in infos
        )
        worksheets = [item for item in infos if item.filename.startswith("xl/worksheets/sheet")]
        assert len(worksheets) == table_count + 1
        assert "xl/worksheets/sheet1.xml" in {item.filename for item in worksheets}
        for item in worksheets:
            # These are actual locally generated synthetic artifacts, never arbitrary XML inputs.
            root = ElementTree.fromstring(archive.read(item))  # noqa: S314
            assert not root.findall(".//s:f", _NS) and not root.findall(".//s:hyperlink", _NS)
            values: list[list[str]] = []
            for row in root.findall("s:sheetData/s:row", _NS):
                cells = row.findall("s:c", _NS)
                assert all(cell.get("t") == "inlineStr" for cell in cells)
                values.append(["".join(cell.itertext()) for cell in cells])
            assert values
            if item.filename == "xl/worksheets/sheet1.xml":
                assert values[0] == ["Fragment ordinal", "Canonical JSON fragment"]
                assert all(len(row) == 2 for row in values[1:])
                assert _fragments([(row[0], row[1]) for row in values[1:]]) == manifest
            else:
                assert tuple(values[0]) == _COLUMNS
                records.extend(dict(zip(_COLUMNS, row, strict=True)) for row in values[1:])
    return records


def _tabular(document: Document, records: list[dict[str, str]], *, csv_escaped: bool) -> None:
    by_table: dict[str, list[dict[str, str]]] = defaultdict(list)
    for item in records:
        by_table[item["table"]].append(item)
    contexts = {item.key: item for item in document.manifest.contexts}
    for descriptor in document.manifest.document.tables:
        actual = by_table.pop(descriptor.table.value, [])
        rows, schema = document.tables[descriptor.table], table_schema(descriptor.table)
        if descriptor.section is not None or descriptor.dataset is not None:
            expected = [
                (row, column, cell)
                for row in rows
                for column, cell in zip(schema.columns, row.cells, strict=True)
            ]
            assert len(actual) == len(expected)
            for item, (row, column, cell) in zip(actual, expected, strict=True):
                assert item["row_key"] == row.key and item["column_key"] == column.key
                value = canonical_report_cell_value(cell)
                accepted = {value}
                if csv_escaped and cell.kind not in {
                    r.CellKind.DECIMAL,
                    r.CellKind.INTEGER,
                    r.CellKind.BOOLEAN,
                }:
                    accepted.add("'" + value)
                assert item["value"] in accepted
                assert item["cell_kind"] == cell.kind.value and item["state"] == cell.state.value
                assert item["currency"] == (cell.currency.value if cell.currency else "")
                assert item["decimal_role"] == (
                    cell.decimal_role.value if cell.decimal_role else ""
                )
                assert item["reason_key"] == (cell.reason_key or "")
                assert item["bound_key"] == (cell.bound_key or "")
                assert item["context_key"] == (cell.context_key or row.context_key)
                context = (
                    contexts[cell.context_key or row.context_key]
                    if cell.kind is r.CellKind.DECIMAL
                    else None
                )
                quality = cell.quality or (context.quality if context else None)
                assert item["quality"] == (quality.value if quality else "")
                assert item["origin"] == (cell.origin.value if cell.origin else "")
                assert item["confidence"] == (
                    decimal_string(cell.confidence) if cell.confidence is not None else ""
                )
                for key, inherited in (
                    ("coverage_key", context.coverage_set_key if context else ""),
                    ("method_key", context.method_key if context else ""),
                    ("method_version", context.method_version if context else ""),
                    ("provenance_set_key", context.provenance_set_key if context else ""),
                    ("note_set_key", context.note_set_key if context else ""),
                ):
                    assert item[key] == (getattr(cell, key) or inherited)
            continue
        fragments: dict[str, list[tuple[str, str]]] = defaultdict(list)
        identities: dict[str, tuple[str, str]] = {}
        for item in actual:
            assert item["section"] == "proof"
            family, *ordinals = item["column_key"].split(".")
            assert family in {"schema", "row"} and len(ordinals) == (1 if family == "schema" else 2)
            group = "schema" if family == "schema" else f"row.{ordinals[0]}"
            identity = (item["row_key"], item["context_key"])
            assert identities.setdefault(group, identity) == identity
            fragments[group].append((ordinals[-1], item["value"]))
        # Even an empty proof table must preserve its fixed schema, not disappear.
        assert _fragments(fragments.pop("schema")) == encode_report_schema(schema)
        for ordinal, row in enumerate(rows):
            group = f"row.{ordinal:06d}"
            assert identities[group] == (row.key, row.context_key)
            assert _fragments(fragments.pop(group)) == encode_report_row(row)
        assert not fragments
    assert not by_table


def _display(cell: r.ReportCell) -> str:
    if cell.state is r.CellState.NOT_APPLICABLE:
        return "Not applicable"
    if cell.value is None:
        return f"{cell.state.value.capitalize()} ({cell.reason_key})"
    value = canonical_report_cell_value(cell)
    if cell.currency:
        value += " " + cell.currency.value
    if cell.state is not r.CellState.AVAILABLE:
        value += f" [{cell.state.value}]"
    if cell.bound_key:
        value += f" [bound: {cell.bound_key}]"
    if cell.reason_key:
        value += f" [reason: {cell.reason_key}]"
    return value


def _compact(value: str) -> str:
    return "".join(value.split())


def _pdf(document: Document, content: bytes, manifest: bytes) -> None:
    pdf = PdfReader(BytesIO(content))
    assert 0 < len(pdf.pages) <= r.MAX_REPORT_PDF_PAGES
    assert dict(pdf.attachments) == {"report-manifest.json": [manifest]}
    text = _compact(report_body_text([page.extract_text() for page in pdf.pages]))
    binding = document.manifest.document.premium_binding
    assert isinstance(binding, ReportProjectionRunBinding)
    for value in (
        sha256(manifest).hexdigest(),
        document.manifest.document.document_digest,
        binding.capture_digest,
        binding.numerical_input_digest,
        binding.result_digest,
        binding.assumption.content_digest,
        binding.report_context.snapshot_digest,
    ):
        assert value in text
    analytical = text.split("Technicalappendix:canonicalevidence", 1)[0]
    assert analytical and analytical != text
    # Record-bounded assertions keep an amount from a different row/appendix
    # from concealing a wrong named financial field in the visible PDF body.
    for descriptor in document.manifest.document.tables:
        key = descriptor.table
        if not key.value.startswith("projection_") or descriptor.section is None:
            continue
        heading = _compact(key.value.replace("_", " ").capitalize())
        assert heading in analytical
        schema = table_schema(key)
        for row in document.tables[key]:
            first_label = _compact(schema.columns[0].key.replace("_", " ").capitalize() + ":")
            marker = _compact(f"Record: {row.key}") + first_label
            assert analytical.count(marker) == 1
            record = first_label + analytical.split(marker, 1)[1].split("Defaultrowcontext:", 1)[0]
            for column, cell in zip(schema.columns, row.cells, strict=True):
                label = column.key.replace("_", " ").replace(".", " / ").capitalize()
                assert _compact(f"{label}: {_display(cell)}") in record


def main() -> None:
    assert len(sys.argv) == 2, "Usage: projection_report_artifacts.py PRIVATE_DOWNLOAD_DIRECTORY"
    directory = Path(sys.argv[1])
    manifest = _read(directory / "manifest.json", r.MAX_REPORT_MANIFEST_BYTES)
    artifacts = {
        key: _read(directory / f"report.{key}", r.MAX_REPORT_ARTIFACT_BYTES)
        for key in ("json", "csv", "xlsx", "pdf")
    }
    assert sum(map(len, artifacts.values())) <= 25 * 1024 * 1024
    document = _document(artifacts["json"], manifest)
    _tabular(document, _csv(artifacts["csv"], manifest), csv_escaped=True)
    _tabular(
        document,
        _xlsx(artifacts["xlsx"], manifest, table_count=len(document.tables)),
        csv_escaped=False,
    )
    _pdf(document, artifacts["pdf"], manifest)
    print(
        "Verified four formats, canonical manifests, table proofs and"
        " named projection and goal values."
    )


if __name__ == "__main__":
    main()
