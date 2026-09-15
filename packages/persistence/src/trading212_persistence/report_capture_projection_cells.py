"""One narrow shared-cell seam for the explicit projection report context."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Protocol
from uuid import UUID

from trading212_domain import reports as r
from trading212_domain.report_v3 import ReportSelectionContract
from trading212_domain.report_v4 import ReportContextV4, ReportSelectionV4
from trading212_domain.sources import SourceAvailability

from .report_capture_common import ReportValue, capture_row


class ProjectionReportBuilder(Protocol):
    @property
    def selection(self) -> ReportSelectionContract: ...
    @property
    def owner_id(self) -> UUID: ...
    @property
    def valuation_at(self) -> datetime: ...
    @property
    def bindings(self) -> list[r.ReportBinding]: ...
    @property
    def references(self) -> dict[str, r.ReportSourceReference]: ...
    def add_context(self, context: ReportContextV4) -> None: ...
    def add_binding(self, binding: r.ReportBinding) -> None: ...
    def add_reference(
        self, reference: r.ReportSourceReference, *, provenance_set_key: str
    ) -> None: ...
    def add_license(self, license: r.ReportLicenseReference) -> None: ...
    def add_note(self, note: r.ReportNote, *, note_set_key: str) -> None: ...
    def limit_copy_expiry(self, deadline: datetime) -> None: ...
    def add_table(
        self,
        table: r.ReportTableKey,
        rows: Iterable[r.ReportRow],
        *,
        section: r.ReportSection | None = None,
        dataset: r.ExportDataset | None = None,
        state: SourceAvailability = SourceAvailability.AVAILABLE,
        reason_key: str | None = None,
    ) -> None: ...


class ProjectionReportWriter:
    def __init__(self, builder: ProjectionReportBuilder, context: ReportContextV4) -> None:
        from trading212_domain.errors import fail_validation

        if not isinstance(builder.selection, ReportSelectionV4):
            fail_validation("A projection report selection is required.", field="selection")
        self.builder, self.context = builder, context
        self.selection = builder.selection

    def row(
        self,
        table: r.ReportTableKey,
        ordinal: str | int,
        values: Mapping[str, ReportValue],
        *,
        reasons: Mapping[str, str] | None = None,
    ) -> r.ReportRow:
        return capture_row(
            self.builder,
            self.context,
            table,
            key=f"{self.context.key}.{table.value}.{ordinal}",
            values=values,
            currency=self.selection.reporting_currency,
            reasons=reasons,
        )

    def table(self, table: r.ReportTableKey, rows: Iterable[r.ReportRow]) -> None:
        from trading212_domain.report_projection_schema import (
            GOAL_REPORT_TABLES,
            PROJECTION_REPORT_TABLES,
        )

        section = r.ReportSection.PROJECTION if table in PROJECTION_REPORT_TABLES else None
        if table in GOAL_REPORT_TABLES and r.ReportSection.GOAL in self.selection.sections:
            section = r.ReportSection.GOAL
        self.builder.add_table(table, rows, section=section)
