"""Bounded presentation traversal over the sealed canonical report reader."""

from __future__ import annotations

from collections.abc import Iterator
from hashlib import sha256

from trading212_application.reports import (
    BoundedArtifactSink,
    ReportDocumentReader,
    ReportRenderError,
    ReportRenderGuard,
)
from trading212_domain.errors import DomainError
from trading212_domain.report_manifest import (
    canonical_report_cell_value,
    encode_report_chunk,
    encode_report_manifest,
    encode_report_row,
    encode_report_schema,
)
from trading212_domain.report_schema import table_schema
from trading212_domain.report_v4 import ReportContextV4
from trading212_domain.reports import (
    CellKind,
    CellState,
    ReportCell,
    ReportContext,
    ReportFailureCode,
    ReportRow,
    ReportTableDescriptor,
)
from trading212_domain.values import decimal_string

METRIC_COLUMNS = (
    "quality",
    "origin",
    "coverage_key",
    "confidence",
    "method_key",
    "method_version",
    "provenance_set_key",
    "note_set_key",
)


def metric_metadata(
    cell: ReportCell, context: ReportContext | ReportContextV4 | None = None
) -> tuple[str, ...]:
    """Expand declared context inheritance; cell-specific metadata always wins."""
    if cell.kind is not CellKind.DECIMAL:
        context = None
    quality = cell.quality if cell.quality is not None else context.quality if context else None
    return (
        quality.value if quality else "",
        cell.origin.value if cell.origin else "",
        cell.coverage_key or (context.coverage_set_key if context else ""),
        decimal_string(cell.confidence) if cell.confidence is not None else "",
        cell.method_key or (context.method_key if context else ""),
        cell.method_version or (context.method_version if context else ""),
        cell.provenance_set_key or (context.provenance_set_key if context else ""),
        cell.note_set_key or (context.note_set_key if context else ""),
    )


def section_name(descriptor: ReportTableDescriptor) -> str:
    if descriptor.section is not None:
        return descriptor.section.value
    return "dataset" if descriptor.dataset is not None else "proof"


def write(sink: BoundedArtifactSink, content: bytes, guard: ReportRenderGuard) -> None:
    guard.check()
    if sink.write(content) != len(content):
        raise ReportRenderError(ReportFailureCode.STORAGE_UNAVAILABLE)


def rows(
    document: ReportDocumentReader,
    descriptor: ReportTableDescriptor,
    guard: ReportRenderGuard,
) -> Iterator[ReportRow]:
    """Verify the reader's bounded traversal without recomputing any financial result."""
    count = 0
    schema = table_schema(descriptor.table)
    schema_bytes = encode_report_schema(schema)
    if sha256(schema_bytes).hexdigest() != descriptor.schema_digest:
        raise ReportRenderError(ReportFailureCode.INPUT_CHANGED)
    digest = sha256()
    digest.update(len(schema_bytes).to_bytes(8, "big"))
    digest.update(schema_bytes)
    for ordinal, chunk in enumerate(document.iter_chunks(descriptor.table)):
        guard.check()
        if chunk.table is not descriptor.table or chunk.ordinal != ordinal:
            raise ReportRenderError(ReportFailureCode.INPUT_CHANGED)
        try:
            encode_report_chunk(chunk)
        except DomainError:
            raise ReportRenderError(ReportFailureCode.INPUT_CHANGED) from None
        for row in chunk.rows:
            count += 1
            if count > descriptor.row_count or len(row.cells) != len(schema.columns):
                raise ReportRenderError(ReportFailureCode.INPUT_CHANGED)
            encoded = encode_report_row(row)
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            yield row
    if count != descriptor.row_count or digest.hexdigest() != descriptor.content_digest:
        raise ReportRenderError(ReportFailureCode.INPUT_CHANGED)
    guard.check()


def display_cell(cell: ReportCell) -> str:
    if cell.state is CellState.NOT_APPLICABLE:
        return "Not applicable"
    if cell.value is None:
        return f"{cell.state.value.capitalize()} ({cell.reason_key})"
    value = canonical_report_cell_value(cell)
    if cell.currency is not None:
        value += " " + cell.currency.value
    if cell.state is not CellState.AVAILABLE:
        value += f" [{cell.state.value}]"
    if cell.bound_key:
        value += f" [bound: {cell.bound_key}]"
    if cell.reason_key:
        value += f" [reason: {cell.reason_key}]"
    return value


def manifest_fragments(document: ReportDocumentReader) -> Iterator[tuple[str, str]]:
    """Lossless, bounded text cells; the fixed prefix prevents formula interpretation.

    Join fragments in ordinal order after removing each literal ``json:`` prefix
    to recover exactly the independent canonical manifest, including full proof.
    """
    manifest = encode_report_manifest(document.manifest).decode("utf-8")
    for ordinal, offset in enumerate(range(0, len(manifest), 4000)):
        yield f"{ordinal:06d}", "json:" + manifest[offset : offset + 4000]


def proof_fragment_records(
    document: ReportDocumentReader,
    descriptor: ReportTableDescriptor,
    guard: ReportRenderGuard,
) -> Iterator[tuple[str, ...]]:
    """Keep complete proof schemas/rows without repeating identifiers for every cell.

    The fixed column-key grammar separates schema fragments from ordered row
    fragments. Joining each contiguous fragment group after its literal json:
    prefix reproduces the exact canonical bytes bound by the manifest.
    """

    def fragments(
        payload: bytes, *, row_key: str, prefix: str, context_key: str
    ) -> Iterator[tuple[str, ...]]:
        value = payload.decode("utf-8")
        for ordinal, offset in enumerate(range(0, len(value), 4000)):
            yield (
                "proof",
                descriptor.table.value,
                row_key,
                f"{prefix}.{ordinal:06d}",
                "text",
                "json:" + value[offset : offset + 4000],
                "",
                "",
                "available",
                "",
                "",
                context_key,
                *("" for _ in METRIC_COLUMNS),
            )

    yield from fragments(
        encode_report_schema(table_schema(descriptor.table)),
        row_key=descriptor.table.value,
        prefix="schema",
        context_key="schema",
    )
    for ordinal, row in enumerate(rows(document, descriptor, guard)):
        yield from fragments(
            encode_report_row(row),
            row_key=row.key,
            prefix=f"row.{ordinal:06d}",
            context_key=row.context_key,
        )
