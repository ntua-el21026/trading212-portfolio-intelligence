"""Fixed selectable-text PDF layout with checked glyphs and bounded pagination."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator
from functools import cache
from typing import Any

from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
from reportlab.pdfbase.ttfonts import TTFont  # type: ignore[import-untyped]
from reportlab.pdfgen.canvas import Canvas  # type: ignore[import-untyped]
from trading212_application.reports import (
    BoundedArtifactSink,
    ReportDocumentReader,
    ReportRenderError,
    ReportRenderGuard,
)
from trading212_domain.report_schema import COMPANY_REPORT_TABLES, section_tables, table_schema
from trading212_domain.report_v3 import is_report_selection
from trading212_domain.reports import (
    MAX_REPORT_PDF_PAGES,
    ExportDataset,
    ReportFailureCode,
    ReportSection,
    ReportTableDescriptor,
    ReportTableKey,
)

from .common import METRIC_COLUMNS, metric_metadata, rows
from .pdf_manifest import attach_manifest, display_contextual_cell, render_manifest_appendix
from .profile import ASSETS, verify_fonts
from .text import label

_REGULAR = "T212-DejaVuSans-2.37"
_BOLD = "T212-DejaVuSans-Bold-2.37"
_WIDTH, _HEIGHT = 595.2756, 841.8898  # A4 geometry only; never used for financial values.
_MARGIN = 42.0
_TEXT_WIDTH = _WIDTH - 2 * _MARGIN


def _analytical_order(descriptor: ReportTableDescriptor) -> tuple[int, int]:
    if descriptor.section is not None:
        tables = section_tables(descriptor.section)
        if descriptor.section is ReportSection.DRIFT:
            # Explicit company pins add analytical tables to drift without changing
            # legacy section selections or any canonical report bytes.
            tables += tuple(table for table in ReportTableKey if table in COMPANY_REPORT_TABLES)
        if descriptor.table not in tables:
            raise ReportRenderError(ReportFailureCode.INVALID_INPUT)
        return (tuple(ReportSection).index(descriptor.section), tables.index(descriptor.table))
    if descriptor.dataset is not None:
        return (
            len(ReportSection) + tuple(ExportDataset).index(descriptor.dataset),
            tuple(ReportTableKey).index(descriptor.table),
        )
    raise ReportRenderError(ReportFailureCode.INVALID_INPUT)


@cache
def _fonts() -> dict[str, frozenset[int]]:
    result = {}
    for name, filename in ((_REGULAR, "DejaVuSans.ttf"), (_BOLD, "DejaVuSans-Bold.ttf")):
        font = TTFont(name, str(ASSETS / filename), validate=1)
        pdfmetrics.registerFont(font)
        result[name] = frozenset(int(codepoint) for codepoint in font.face.charToGlyph)
    return result


def _visible(value: str) -> str:
    # Controls are shown explicitly; markup and URLs are always plain text.
    return "".join(
        f"\\u{ord(character):04x}" if unicodedata.category(character).startswith("C") else character
        for character in value
    )


class _Layout:
    def __init__(self, sink: BoundedArtifactSink, guard: ReportRenderGuard) -> None:
        verify_fonts()
        self.glyphs = _fonts()
        self.guard = guard
        self.pdf: Any = Canvas(sink, pagesize=(_WIDTH, _HEIGHT), pageCompression=1, lang="en-GB")
        self.pdf.setTitle("Private portfolio report")
        self.pdf.setAuthor("Portfolio Intelligence")
        self.pdf.setCreator("Portfolio Intelligence report_template_v1 / ReportLab 5.0.1")
        self.pdf.setSubject("Canonical portfolio values, source provenance and quality")
        self.pdf.setViewerPreference("DisplayDocTitle", "true")
        self.page = 0
        self.y = 0.0
        self._new_page()

    def _new_page(self) -> None:
        self.guard.check()
        if self.page:
            self._footer()
            self.pdf.showPage()
        self.page += 1
        if self.page > MAX_REPORT_PDF_PAGES:
            raise ReportRenderError(ReportFailureCode.LIMIT_EXCEEDED)
        self.y = _HEIGHT - _MARGIN
        self.pdf.setFillColorRGB(0.09, 0.20, 0.30)
        self.pdf.setFont(_BOLD, 9)
        self.pdf.drawString(_MARGIN, self.y, "PORTFOLIO INTELLIGENCE")
        self.pdf.setStrokeColorRGB(0.08, 0.40, 0.44)
        self.pdf.line(_MARGIN, self.y - 12, _WIDTH - _MARGIN, self.y - 12)
        self.y -= 38

    def _footer(self) -> None:
        self.pdf.setFillColorRGB(0.32, 0.37, 0.42)
        self.pdf.setFont(_REGULAR, 8)
        self.pdf.drawString(
            _MARGIN, 25, "Private financial information | Canonical values, no execution"
        )
        self.pdf.drawRightString(_WIDTH - _MARGIN, 25, str(self.page))

    def _lines(self, text: str, font: str, size: float, width: float) -> Iterator[str]:
        text = _visible(text)
        if any(ord(character) not in self.glyphs[font] for character in text):
            raise ReportRenderError(ReportFailureCode.RENDER_FAILED)
        current = ""
        # Binary search each bounded text segment, then prefer a word break. Long
        # opaque IDs still wrap without clipping or dropping any characters.
        while text:
            lo, hi = 1, len(text)
            while lo <= hi:
                midpoint = (lo + hi) // 2
                if pdfmetrics.stringWidth(text[:midpoint], font, size) <= width:
                    lo = midpoint + 1
                else:
                    hi = midpoint - 1
            count = max(1, hi)
            if count < len(text) and (space := text.rfind(" ", 0, count + 1)) > 0:
                count = space + 1
            current, text = text[:count], text[count:]
            yield current
        if not current:
            yield ""

    def text(self, value: str, *, bold: bool = False, size: float = 9.5, indent: float = 0) -> None:
        self.guard.check()
        font = _BOLD if bold else _REGULAR
        for line in self._lines(value, font, size, _TEXT_WIDTH - indent):
            if self.y - size * 1.45 < 48:
                self._new_page()
            self.pdf.setFont(font, size)
            self.pdf.setFillColorRGB(0.09, 0.20, 0.30)
            self.pdf.drawString(_MARGIN + indent, self.y, line)
            self.y -= size * 1.45

    def heading(self, title: str, *, key: str, major: bool = False) -> None:
        if self.y < 125:
            self._new_page()
        self.y -= 12
        self.pdf.bookmarkPage(key)
        self.pdf.addOutlineEntry(title, key, level=0, closed=False)
        self.text(title, bold=True, size=18 if major else 13)
        self.y -= 6

    def finish(self) -> None:
        self.guard.check()
        self._footer()
        self.pdf.save()
        self.guard.check()


def render_pdf(
    document: ReportDocumentReader, sink: BoundedArtifactSink, guard: ReportRenderGuard
) -> None:
    layout = _Layout(sink, guard)
    selection = document.header.selection
    title = (
        label(selection.report_type.value)
        if is_report_selection(selection)
        else label(selection.dataset.value)
    )
    layout.heading(title, key="report", major=True)
    layout.text(f"Reporting currency: {selection.reporting_currency.value}", bold=True, size=12)
    layout.text(f"Period: {selection.start_date.isoformat()} to {selection.end_date.isoformat()}")
    layout.text(f"Valuation: {document.header.valuation_at.isoformat()}")
    layout.text(f"Source cutoff: {selection.source_cutoff_at.isoformat()}")
    layout.text(f"Account: {selection.account_id}")
    layout.text(f"Snapshot: {selection.snapshot_id}")
    for note in document.manifest.notes:
        if note.code == "snapshot_outside_period":
            layout.text(note.text, bold=True)
    layout.text(
        "All financial values are copied from pinned canonical results. Missing and partial "
        "values retain their stated reasons and bounds."
    )
    contexts = {context.key: context for context in document.manifest.contexts}
    analytical = sorted(
        (
            table
            for table in document.header.tables
            if table.section is not None or table.dataset is not None
        ),
        key=_analytical_order,
    )
    proof = [
        table for table in document.header.tables if table.section is None and table.dataset is None
    ]
    # Presentation order is independent of the canonical header and its hashes.
    # Every proof table remains rendered, after the selected analytical sections.
    for index, descriptor in enumerate((*analytical, *proof)):
        if index == len(analytical):
            layout.heading(
                "Technical appendix: canonical evidence", key="technical-evidence", major=True
            )
            layout.text(
                "These complete supporting records retain the canonical input and source details "
                "for the analytical sections above. Their table hashes are listed "
                "in the manifest appendix."
            )
        layout.heading(label(descriptor.table.value), key=f"table-{index}")
        layout.text(f"State: {descriptor.state.value}; canonical rows: {descriptor.row_count}")
        if descriptor.reason_key:
            layout.text(f"Reason: {descriptor.reason_key}")
        for row in rows(document, descriptor, guard):
            layout.y -= 6
            layout.text(f"Record: {row.key}", bold=True)
            compact_proof = descriptor.section is None and descriptor.dataset is None
            proof_fields = []
            for column, cell in zip(table_schema(descriptor.table).columns, row.cells, strict=True):
                field = f"{label(column.key)}: {display_contextual_cell(cell, row.context_key)}"
                metadata = "; ".join(
                    f"{label(name)}: {value}"
                    for name, value in zip(
                        METRIC_COLUMNS,
                        metric_metadata(cell, contexts[cell.context_key or row.context_key]),
                        strict=True,
                    )
                    if value
                )
                if compact_proof:
                    proof_fields.append(field + (f" [{metadata}]" if metadata else ""))
                else:
                    layout.text(field, indent=10)
                    if metadata:
                        layout.text(metadata, size=8, indent=16)
            if compact_proof:
                # Every fixed proof column remains visible; shared context fields
                # are referenced once per record instead of adding empty space.
                layout.text(" | ".join(proof_fields), size=8, indent=10)
            layout.text(f"Default row context: {row.context_key}", size=8, indent=10)
    manifest_digest = attach_manifest(layout.pdf, document.manifest, guard)
    render_manifest_appendix(layout, document.manifest, manifest_digest)
    layout.heading("Reading and reuse", key="limitations")
    layout.text(
        "This PDF provides selectable Unicode text, headings, bookmarks and a logical reading "
        "order. It is not certified PDF/UA or a fully tagged PDF. Structured JSON, CSV and XLSX "
        "preserve the canonical records and explicit states."
    )
    layout.text(
        "The activity records support accounting review. They do not assign tax treatment or "
        "provide tax advice. Manual contribution proposals cannot execute broker transactions."
    )
    layout.finish()
