"""Small typed synthetic report with complete section identity and exact scalar states."""

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from trading212_domain import reports as r
from trading212_domain.enums import QualityState
from trading212_domain.report_manifest import (
    build_report_chunk,
    build_report_manifest,
    encode_report_header,
    encode_report_manifest,
    encode_report_proof,
    encode_report_schema,
    report_document_digest,
    report_table_digest,
)
from trading212_domain.report_profile import renderer_profile
from trading212_domain.report_schema import report_tables, section_tables, table_schema
from trading212_domain.values import CurrencyCode

AT = datetime(2026, 8, 31, 21, tzinfo=UTC)
ZERO_DIGEST = "0" * 64


def uid(value: int) -> UUID:
    return UUID(int=value)


def selection(formats: tuple[r.ReportFormat, ...] = tuple(r.ReportFormat)) -> r.ReportSelection:
    return r.ReportSelection(
        account_id=uid(1),
        snapshot_id=uid(2),
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
        source_cutoff_at=AT,
        reporting_currency=CurrencyCode("EUR"),
        report_type=r.ReportType.PORTFOLIO_SUMMARY,
        sections=(r.ReportSection.OVERVIEW, r.ReportSection.ALLOCATION, r.ReportSection.QUALITY),
        formats=formats,
    )


def _row(table: r.ReportTableKey) -> r.ReportRow:
    cells = []
    for column in table_schema(table).columns:
        key, kind = column.key, column.kind
        assert kind is not None
        value: str | Decimal | int | bool | date | datetime | None
        state = r.CellState.AVAILABLE
        reason = None
        currency = (
            CurrencyCode("EUR")
            if column.decimal_role in {r.DecimalRole.MONEY, r.DecimalRole.PRICE}
            else None
        )
        if kind is r.CellKind.DECIMAL:
            value = Decimal("0")
            if key in {
                "provider_cost_basis",
                "provider_unrealized_profit_loss",
                "realized_profit_loss",
                "unrealized_profit_loss",
                "direct_weight",
            }:
                value, state, reason = None, r.CellState.UNAVAILABLE, "reason.missing"
        elif kind is r.CellKind.INSTANT:
            value = AT
        elif kind is r.CellKind.DATE:
            value = AT.date()
        elif kind is r.CellKind.INTEGER:
            value = 0
        elif kind is r.CellKind.BOOLEAN:
            value = False
        elif kind is r.CellKind.IDENTIFIER:
            value = str(uid(2)) if key.endswith("_id") else "fixture.record"
        elif kind is r.CellKind.ENUM:
            value = "EUR" if "currency" in key else "equity"
        else:
            value = ' =SUM(1,2); "Ελληνική εταιρεία"\nΔοκιμή'  # noqa: RUF001 - real Unicode regression
        cells.append(
            r.ReportCell(
                kind=kind,
                value=value,
                state=state,
                decimal_role=column.decimal_role,
                currency=currency,
                context_key="context.snapshot",
                reason_key=reason,
            )
        )
    return r.ReportRow(
        key=f"fixture.{table.value}", context_key="context.snapshot", cells=tuple(cells)
    )


@dataclass(frozen=True)
class ReportFixture:
    capture: r.ReportCaptureSummary
    chunks: tuple[r.ReportChunk, ...]

    @property
    def header(self) -> r.ReportDocumentHeader:
        return self.capture.header

    @property
    def manifest(self) -> r.ReportManifest:
        return build_report_manifest(self.capture)

    def iter_chunks(self, table: r.ReportTableKey) -> Iterator[r.ReportChunk]:
        return iter(chunk for chunk in self.chunks if chunk.table is table)


def document(formats: tuple[r.ReportFormat, ...] = tuple(r.ReportFormat)) -> ReportFixture:
    chosen = selection(formats)
    context = r.ReportContext(
        key="context.snapshot",
        family=r.ReportFamily.SNAPSHOT,
        method_key="portfolio_summary",
        method_version="1.0.0",
        valuation_at=AT,
        source_cutoff_at=AT,
        quality=QualityState.PARTIAL,
        provenance_set_key="sources.snapshot",
        coverage_set_key="coverage.snapshot",
        note_set_key="notes.snapshot",
    )
    note = r.ReportNote(
        key="reason.missing",
        kind=r.ReportNoteKind.UNAVAILABLE_REASON,
        family=r.ReportFamily.SNAPSHOT,
        code="missing_input",
        text="The source did not supply this value; zero is retained independently.",
    )
    proof = r.ReportProof(
        contexts=(context,),
        notes=(note,),
        source_references=(
            r.ReportSourceReference(
                key="source.snapshot",
                kind=r.ReportSourceKind.PORTFOLIO_SNAPSHOT,
                subject_id=uid(2),
                content_digest=ZERO_DIGEST,
            ),
        ),
        source_memberships=(
            r.ReportSourceMembership(
                provenance_set_key="sources.snapshot", source_key="source.snapshot"
            ),
        ),
        note_memberships=(
            r.ReportNoteMembership(note_set_key="notes.snapshot", note_key="reason.missing"),
        ),
    )
    descriptors, chunks = [], []
    section_by_table = {
        table: section for section in chosen.sections for table in section_tables(section)
    }
    for table in report_tables(chosen):
        rows = (
            (_row(table),)
            if table in {r.ReportTableKey.SNAPSHOT_TOTALS, r.ReportTableKey.POSITIONS}
            else ()
        )
        descriptors.append(
            r.ReportTableDescriptor(
                table=table,
                section=section_by_table[table],
                schema_digest=sha256(encode_report_schema(table_schema(table))).hexdigest(),
                row_count=len(rows),
                content_digest=report_table_digest(table, rows),
            )
        )
        if rows:
            chunks.append(build_report_chunk(table, 0, rows))
    proof_bytes = encode_report_proof(proof)
    header = r.ReportDocumentHeader(
        selection=chosen,
        owner_id=uid(3),
        valuation_at=AT,
        context_digest=sha256(proof_bytes).hexdigest(),
        tables=tuple(descriptors),
        document_digest=ZERO_DIGEST,
    )
    header = replace(header, document_digest=report_document_digest(header))
    capture = r.ReportCaptureSummary(
        header=header,
        canonical_byte_length=sum(len(x.canonical_bytes) for x in chunks)
        + len(proof_bytes)
        + len(encode_report_header(header)),
        chunk_count=len(chunks),
        immutable_bindings=(
            r.ReportBinding(
                family=r.ReportFamily.SNAPSHOT,
                role=r.ReportInputRole.SNAPSHOT,
                subject_id=uid(2),
                content_digest=ZERO_DIGEST,
            ),
        ),
        proof=proof,
        proof_digest=sha256(proof_bytes).hexdigest(),
        renderer_profile=renderer_profile(formats),
    )
    capture = replace(
        capture,
        canonical_byte_length=sum(len(x.canonical_bytes) for x in chunks)
        + len(encode_report_manifest(build_report_manifest(capture))),
    )
    return ReportFixture(capture, tuple(chunks))
