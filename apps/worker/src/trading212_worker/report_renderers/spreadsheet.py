"""Explicit-text XLSX with private, conservatively budgeted assembly scratch."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import xlsxwriter  # type: ignore[import-untyped]
from trading212_application.reports import (
    BoundedArtifactSink,
    ReportDocumentReader,
    ReportRenderError,
    ReportRenderGuard,
)
from trading212_domain.report_manifest import canonical_report_cell_value
from trading212_domain.report_schema import table_schema
from trading212_domain.reports import MAX_REPORT_SCRATCH_BYTES, ReportFailureCode
from xlsxwriter.worksheet import Worksheet  # type: ignore[import-untyped]

from .common import (
    manifest_fragments,
    metric_metadata,
    proof_fragment_records,
    rows,
    section_name,
    write,
)
from .structured import CSV_COLUMNS


class _TextWorksheet(Worksheet):  # type: ignore[misc]
    """Disable XlsxWriter 3.2.9's implicit rich-XML detection for ordinary strings."""

    def _xml_rich_inline_string(
        self, string: str, attributes: Sequence[tuple[str, object]] = ()
    ) -> None:
        # In constant-memory mode the pinned writer treats even write_string's
        # literal <r>...</r> as markup. This export never uses rich text. Route
        # that internal branch through the normal escaping writer as well.
        self._xml_inline_string(string, True, attributes)


class _ZipSink:
    """An explicitly unseekable ZIP destination, compatible with the bounded port."""

    def __init__(self, sink: BoundedArtifactSink, guard: ReportRenderGuard) -> None:
        self.sink, self.guard = sink, guard
        self.offset = 0
        self.failed = False

    def write(self, content: bytes) -> int:
        if self.failed:
            # ZipFile finalization may run after its first write raised. Discard
            # that cleanup output; the original exception prevents publication.
            return len(content)
        try:
            write(self.sink, content, self.guard)
        except BaseException:
            self.failed = True
            raise
        self.offset += len(content)
        return len(content)

    def tell(self) -> int:
        return self.offset

    def flush(self) -> None:
        self.guard.check()


class _ScratchBudget:
    def __init__(self, directory: Path, guard: ReportRenderGuard) -> None:
        self.directory = directory
        self.guard = guard
        self.reserved = 1024 * 1024

    def reserve(self, values: Sequence[str]) -> None:
        self.guard.check()
        # The pinned writer can expand a control byte to seven ASCII bytes.
        # Its inline-string wrapper (including preserved whitespace, seven-digit
        # row indices and our two styles) is <96 bytes; row markup is <128.
        # Assembly can temporarily hold both streamed rows and worksheet XML.
        self.reserved += 2 * (sum(7 * len(value.encode("utf-8")) + 96 for value in values) + 128)
        if self.reserved > MAX_REPORT_SCRATCH_BYTES:
            raise ReportRenderError(ReportFailureCode.LIMIT_EXCEEDED)

    def check(self) -> None:
        self.guard.check()
        size = sum(path.stat().st_size for path in self.directory.iterdir() if path.is_file())
        if size > MAX_REPORT_SCRATCH_BYTES:
            raise ReportRenderError(ReportFailureCode.LIMIT_EXCEEDED)


def render_xlsx(
    document: ReportDocumentReader, sink: BoundedArtifactSink, guard: ReportRenderGuard
) -> None:
    with TemporaryDirectory(prefix="t212pi-report-") as temporary:
        directory = Path(temporary)
        directory.chmod(0o700)
        budget = _ScratchBudget(directory, guard)
        workbook = xlsxwriter.Workbook(
            _ZipSink(sink, guard),
            {
                "constant_memory": True,
                "tmpdir": temporary,
                "strings_to_formulas": False,
                "strings_to_urls": False,
                "strings_to_numbers": False,
            },
        )
        workbook.set_properties(
            {
                "title": "Private portfolio report",
                "author": "Portfolio Intelligence",
                # Spreadsheet metadata is fixed independently of the canonical manifest.
                "created": datetime(2000, 1, 1),
                "comments": "Exact values are text. No tax classification is asserted.",
            }
        )
        heading = workbook.add_format(
            {"bold": True, "bg_color": "#17324D", "font_color": "#FFFFFF", "text_wrap": True}
        )
        body = workbook.add_format({"text_wrap": True, "valign": "top", "num_format": "@"})

        def sheet(name: str, headers: Sequence[str]) -> Any:
            result = workbook.add_worksheet(name, worksheet_class=_TextWorksheet)
            result.freeze_panes(1, 0)
            result.set_column(0, len(headers) - 1, 24)
            result.set_row(0, 30)
            emit(result, 0, headers, heading)
            return result

        def emit(target: Any, ordinal: int, values: Sequence[str], style: Any) -> None:
            budget.reserve(values)
            for index, value in enumerate(values):
                if len(value) > 4096 or target.write_string(ordinal, index, value, style) != 0:
                    raise ReportRenderError(ReportFailureCode.LIMIT_EXCEEDED)
            budget.check()

        try:
            manifest = sheet("Manifest", ("Fragment ordinal", "Canonical JSON fragment"))
            manifest.set_column(1, 1, 110)
            for index, fragment in enumerate(manifest_fragments(document), 1):
                emit(manifest, index, fragment, body)
            contexts = {context.key: context for context in document.manifest.contexts}
            for index, descriptor in enumerate(document.header.tables, 1):
                target = sheet(f"{index:02d}-{descriptor.table.value[:24]}", CSV_COLUMNS)
                target.set_column(5, 5, 42)
                ordinal = 1
                section = section_name(descriptor)
                if section == "proof":
                    for ordinal, record in enumerate(
                        proof_fragment_records(document, descriptor, guard), 1
                    ):
                        emit(target, ordinal, record, body)
                    continue
                for row in rows(document, descriptor, guard):
                    for column, cell in zip(
                        table_schema(descriptor.table).columns, row.cells, strict=True
                    ):
                        emit(
                            target,
                            ordinal,
                            (
                                section,
                                descriptor.table.value,
                                row.key,
                                column.key,
                                cell.kind.value,
                                canonical_report_cell_value(cell),
                                cell.decimal_role.value if cell.decimal_role else "",
                                cell.currency.value if cell.currency else "",
                                cell.state.value,
                                cell.reason_key or "",
                                cell.bound_key or "",
                                cell.context_key or row.context_key,
                                *metric_metadata(
                                    cell, contexts[cell.context_key or row.context_key]
                                ),
                            ),
                            body,
                        )
                        ordinal += 1
            budget.check()
            workbook.close()
            budget.check()
        except BaseException:
            # Do not call close() on failure: it would publish a partial workbook.
            # Release the library's current XML writers before deleting private scratch.
            for worksheet in workbook.worksheets():
                if worksheet.row_data_fh is not None and not worksheet.row_data_fh.closed:
                    worksheet.row_data_fh.close()
            raise
