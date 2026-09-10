"""Typed adapters from canonical scalar records to the fixed report schemas."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from trading212_application.views import MetricView
from trading212_domain import reports as r
from trading212_domain.enums import QualityState
from trading212_domain.errors import fail_validation
from trading212_domain.report_schema import report_tables, section_tables, table_schema
from trading212_domain.sources import SourceAvailability
from trading212_domain.values import CurrencyCode, Money

from .report_builder import ReportBuilder

type ReportScalar = str | Decimal | int | bool | date | datetime | UUID | Enum | None
type ReportValue = ReportScalar | Money | MetricView | r.ReportCell


def capture_note(
    builder: ReportBuilder,
    context: r.ReportContext,
    *,
    key: str,
    text: str,
    kind: r.ReportNoteKind = r.ReportNoteKind.UNAVAILABLE_REASON,
    code: str = "missing_input",
) -> str:
    builder.add_note(
        r.ReportNote(
            key=key,
            kind=kind,
            family=context.family,
            code=code,
            text=text,
            related_provenance_set_key=context.provenance_set_key,
        ),
        note_set_key=context.note_set_key,
    )
    return key


def capture_stored_warnings(
    builder: ReportBuilder,
    context: r.ReportContext,
    values: Sequence[object],
    *,
    key: str,
) -> None:
    """Copy every persisted DomainWarning field without a public preview cap."""
    r.report_limit(len(values) <= r.MAX_REPORT_DATASET_ROWS, "warnings")
    for ordinal, value in enumerate(values):
        fields: Sequence[object] = ()
        if isinstance(value, str):
            code, message = "source_warning", value
        elif isinstance(value, dict) and set(value) <= {"code", "message", "affected_fields"}:
            raw_code, raw_message = value.get("code"), value.get("message")
            raw_fields = value.get("affected_fields", ())
            if (
                not isinstance(raw_code, str)
                or not isinstance(raw_message, str)
                or not isinstance(raw_fields, (list, tuple))
            ):
                fail_validation(
                    "Stored warning differs from its canonical schema.", field="warnings"
                )
            fields = raw_fields
            code, message = raw_code, raw_message
        else:
            fail_validation("Stored warning differs from its canonical schema.", field="warnings")
        capture_note(
            builder,
            context,
            key=f"{key}.{ordinal}",
            text=message,
            kind=r.ReportNoteKind.WARNING,
            code=code,
        )
        r.report_limit(len(fields) <= 32, "warning_fields")
        for index, affected in enumerate(fields):
            if not isinstance(affected, str):
                fail_validation("Stored warning field must be text.", field="warnings")
            capture_note(
                builder,
                context,
                key=f"{key}.{ordinal}.field.{index}",
                text=f"Affected field: {affected}",
                kind=r.ReportNoteKind.WARNING,
                code=code,
            )


def capture_row(
    builder: ReportBuilder,
    context: r.ReportContext,
    table: r.ReportTableKey,
    *,
    key: str,
    values: Mapping[str, ReportValue],
    currency: CurrencyCode | None = None,
    reasons: Mapping[str, str] | None = None,
    quality: QualityState | None = None,
    origins: Mapping[str, r.ReportMetricOrigin] | None = None,
) -> r.ReportRow:
    """Copy scalars; unavailable values never receive invented zeroes or FX."""
    schema = table_schema(table)
    if set(values) != {column.key for column in schema.columns}:
        fail_validation("Canonical report projection differs from its fixed columns.", field="row")
    cells = []
    for column in schema.columns:
        item = values[column.key]
        if isinstance(item, r.ReportCell):
            cells.append(item)
            continue
        if column.kind is None:
            fail_validation("A scalar-union column requires an explicit typed cell.", field="row")
        money_currency = currency
        availability = r.CellState.AVAILABLE
        reason = (reasons or {}).get(column.key)
        value: ReportScalar
        if isinstance(item, MetricView):
            value = item.value
            money_currency = CurrencyCode(item.currency)
            availability = r.CellState(item.availability.value)
            reason = item.unavailable_reason or reason
            for ordinal, assumption in enumerate(item.assumptions):
                capture_note(
                    builder,
                    context,
                    key=f"{key}.{column.key}.assumption.{ordinal}",
                    text=assumption,
                    kind=r.ReportNoteKind.ASSUMPTION,
                    code="source_assumption",
                )
            for ordinal, label in enumerate(item.provenance):
                capture_note(
                    builder,
                    context,
                    key=f"{key}.{column.key}.provenance.{ordinal}",
                    text=label,
                    kind=r.ReportNoteKind.ASSUMPTION,
                    code="canonical_provenance",
                )
            capture_note(
                builder,
                context,
                key=f"{key}.{column.key}.methodology",
                text=item.methodology,
                kind=r.ReportNoteKind.ASSUMPTION,
                code="canonical_methodology",
            )
        elif isinstance(item, Money):
            value, money_currency = item.amount, item.currency
        else:
            value = item
        if isinstance(value, UUID):
            value = str(value)
        elif isinstance(value, Enum):
            value = str(value.value)
        reason_key = None
        if value is None:
            availability = (
                r.CellState.NOT_APPLICABLE
                if column.optional and reason is None
                else r.CellState.UNAVAILABLE
            )
        if availability in {r.CellState.UNAVAILABLE, r.CellState.PARTIAL}:
            reason_key = capture_note(
                builder,
                context,
                key=f"{key}.{column.key}.reason",
                text=reason or "The canonical source does not provide this value.",
            )
        cells.append(
            r.ReportCell(
                kind=column.kind,
                value=value,
                state=availability,
                decimal_role=column.decimal_role,
                currency=money_currency
                if column.decimal_role in {r.DecimalRole.MONEY, r.DecimalRole.PRICE}
                else None,
                context_key=context.key,
                reason_key=reason_key,
                # Nonfinancial scalar fields inherit the same named row context.
                # Material decimal values also retain direct metric metadata.
                quality=(quality or context.quality) if column.kind is r.CellKind.DECIMAL else None,
                coverage_key=context.coverage_set_key
                if column.kind is r.CellKind.DECIMAL
                else None,
                method_key=context.method_key if column.kind is r.CellKind.DECIMAL else None,
                method_version=(
                    item.calculation_version
                    if isinstance(item, MetricView)
                    else context.method_version
                )
                if column.kind is r.CellKind.DECIMAL
                else None,
                origin=(origins or {}).get(column.key),
                provenance_set_key=context.provenance_set_key
                if column.kind is r.CellKind.DECIMAL
                else None,
                note_set_key=context.note_set_key if column.kind is r.CellKind.DECIMAL else None,
            )
        )
    return r.ReportRow(
        key=key,
        context_key=context.key,
        cells=tuple(_compact_cell(cell, context) for cell in cells),
    )


def _compact_cell(cell: r.ReportCell, context: r.ReportContext) -> r.ReportCell:
    """Factor only metadata identical to the explicitly named row context."""
    if cell.context_key is not None and cell.context_key != context.key:
        return cell
    if cell.kind is not r.CellKind.DECIMAL:
        return replace(cell, context_key=None) if cell.context_key is not None else cell
    inherited_method = (cell.method_key, cell.method_version) == (
        context.method_key,
        context.method_version,
    )
    return replace(
        cell,
        context_key=None,
        quality=None if cell.quality == context.quality else cell.quality,
        coverage_key=None if cell.coverage_key == context.coverage_set_key else cell.coverage_key,
        method_key=None if inherited_method else cell.method_key,
        method_version=None if inherited_method else cell.method_version,
        provenance_set_key=None
        if cell.provenance_set_key == context.provenance_set_key
        else cell.provenance_set_key,
        note_set_key=None if cell.note_set_key == context.note_set_key else cell.note_set_key,
    )


def capture_table(
    builder: ReportBuilder,
    table: r.ReportTableKey,
    rows: Iterable[r.ReportRow],
    *,
    state: SourceAvailability = SourceAvailability.AVAILABLE,
    reason_key: str | None = None,
) -> None:
    if table not in report_tables(builder.selection):
        fail_validation("The table was not selected for this report.", field="table")
    section = None
    dataset = None
    if isinstance(builder.selection, r.ReportSelection):
        section = next(
            section for section in builder.selection.sections if table in section_tables(section)
        )
    else:
        dataset = builder.selection.dataset
    builder.add_table(
        table, rows, section=section, dataset=dataset, state=state, reason_key=reason_key
    )
