"""Canonical JSON and a single normalized RFC4180 CSV schema for every table."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from io import StringIO

from trading212_application.reports import (
    BoundedArtifactSink,
    ReportDocumentReader,
    ReportRenderGuard,
)
from trading212_domain.report_manifest import (
    canonical_report_cell_value,
    encode_report_header,
    encode_report_manifest,
    encode_report_row,
)
from trading212_domain.report_schema import table_schema
from trading212_domain.reports import CellKind

from .common import (
    METRIC_COLUMNS,
    manifest_fragments,
    metric_metadata,
    proof_fragment_records,
    rows,
    section_name,
    write,
)
from .text import csv_text

CSV_COLUMNS = (
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
    *METRIC_COLUMNS,
)


def render_json(
    document: ReportDocumentReader, sink: BoundedArtifactSink, guard: ReportRenderGuard
) -> None:
    write(sink, b'{"schema":"report_document_json_v1","manifest":', guard)
    write(sink, encode_report_manifest(document.manifest), guard)
    write(sink, b',"header":', guard)
    write(sink, encode_report_header(document.header), guard)
    write(sink, b',"tables":[', guard)
    for index, descriptor in enumerate(document.header.tables):
        write(sink, b"," if index else b"", guard)
        key = json.dumps(descriptor.table.value, ensure_ascii=False).encode("utf-8")
        write(sink, b'{"table":' + key + b',"rows":[', guard)
        for row_index, row in enumerate(rows(document, descriptor, guard)):
            write(sink, b"," if row_index else b"", guard)
            write(sink, encode_report_row(row), guard)
        write(sink, b"]}", guard)
    write(sink, b"]}", guard)


def render_csv(
    document: ReportDocumentReader, sink: BoundedArtifactSink, guard: ReportRenderGuard
) -> None:
    def emit(values: Sequence[str]) -> None:
        with StringIO(newline="") as output:
            csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator="\r\n").writerow(values)
            write(sink, output.getvalue().encode("utf-8"), guard)

    emit(CSV_COLUMNS)
    contexts = {context.key: context for context in document.manifest.contexts}
    for ordinal, fragment in manifest_fragments(document):
        emit(
            (
                "manifest",
                "canonical_manifest",
                ordinal,
                "canonical_json_fragment",
                "text",
                fragment,
                "",
                "",
                "available",
                "",
                "",
                "manifest",
                *("" for _ in METRIC_COLUMNS),
            )
        )
    for descriptor in document.header.tables:
        section = section_name(descriptor)
        if section == "proof":
            for record in proof_fragment_records(document, descriptor, guard):
                emit(tuple(csv_text(value) for value in record))
            continue
        for row in rows(document, descriptor, guard):
            for column, cell in zip(table_schema(descriptor.table).columns, row.cells, strict=True):
                value = canonical_report_cell_value(cell)
                if cell.kind not in {CellKind.DECIMAL, CellKind.INTEGER, CellKind.BOOLEAN}:
                    value = csv_text(value)
                emit(
                    (
                        section,
                        descriptor.table.value,
                        csv_text(row.key),
                        column.key,
                        cell.kind.value,
                        value,
                        cell.decimal_role.value if cell.decimal_role else "",
                        cell.currency.value if cell.currency else "",
                        cell.state.value,
                        cell.reason_key or "",
                        cell.bound_key or "",
                        cell.context_key or row.context_key,
                        *metric_metadata(cell, contexts[cell.context_key or row.context_key]),
                    )
                )
