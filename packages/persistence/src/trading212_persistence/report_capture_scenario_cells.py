"""Scenario metric metadata on the unchanged report scalar and row contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from decimal import Decimal
from uuid import UUID

from trading212_domain import reports as r
from trading212_domain.errors import fail_validation
from trading212_domain.report_schema import table_schema
from trading212_domain.scenario import ScenarioRecord
from trading212_domain.scenario_result import ScenarioMoneyMetric, ScenarioRatioMetric
from trading212_domain.sources import SourceLicense

from .historical_base import digest
from .report_builder import ReportBuilder
from .report_capture_common import ReportValue, capture_note, capture_row

type ScenarioValue = ReportValue | ScenarioMoneyMetric | ScenarioRatioMetric


class ScenarioReportWriter:
    """Closed-schema emission; no arbitrary object flattening or numeric conversion."""

    def __init__(self, builder: ReportBuilder, context: r.ReportContext) -> None:
        self.builder, self.context = builder, context

    def key(self, table: r.ReportTableKey, ordinal: str | int = 0) -> str:
        return f"{self.context.key}.{table.value}.{ordinal}"

    def members(self, kind: str, owner: str, field: str, identifiers: Iterable[str | UUID]) -> None:
        for ordinal, identifier in enumerate(identifiers):
            self.builder.add_proof(
                r.ReportProofRelation(
                    table=r.ReportTableKey.SCENARIO_MEMBERS_V1,
                    row=capture_row(
                        self.builder,
                        self.context,
                        r.ReportTableKey.SCENARIO_MEMBERS_V1,
                        key=f"{self.context.key}.member.{digest((kind, owner, field, ordinal))}",
                        values={
                            "owner_kind": kind,
                            "owner_key": owner,
                            "field": field,
                            "ordinal": ordinal,
                            "reference_id": identifier,
                        },
                    ),
                )
            )

    def metric(self, key: str, value: ScenarioMoneyMetric | ScenarioRatioMetric) -> r.ReportCell:
        context, builder = self.context, self.builder
        reason = None
        if value.reason is not None:
            reason = capture_note(
                builder,
                context,
                key=f"{context.key}.reason.{value.reason.value}",
                text=value.reason.value,
                code=value.reason.value,
            )
        missing = value.value is None
        bound_key = f"{context.key}.q18.{'unavailable' if missing else 'exact'}"
        builder.add_bound(
            r.ReportBoundFact(
                key=bound_key,
                family=r.ReportFamily.SCENARIO,
                kind=r.ReportBoundKind.UNAVAILABLE if missing else r.ReportBoundKind.EXACT,
                quantum=Decimal("1e-18"),
                rounding="ROUND_HALF_EVEN",
            )
        )
        money = isinstance(value, ScenarioMoneyMetric)
        provenance = context.provenance_set_key
        confidence = None
        if isinstance(value, ScenarioMoneyMetric):
            if (
                value.value is not None
                and value.value.currency != builder.selection.reporting_currency
            ):
                fail_validation(
                    "Scenario money currency differs from report basis.", field="currency"
                )
            amount = None if value.value is None else value.value.amount
            confidence = value.confidence
            provenance = f"{context.key}.metric.sources.{digest(value.source_reference_ids)}"
            if not value.source_reference_ids:
                builder.add_context(
                    replace(context, key=f"{context.key}.unsourced", provenance_set_key=provenance)
                )
            for identifier in value.source_reference_ids:
                # Money witnesses are canonical X-ray dependency IDs. Sensitivity evidence
                # is retained separately by applied-use/driver memberships, never inferred.
                reference = builder.references.get(f"xray.source.{identifier}")
                if reference is None:
                    fail_validation("Scenario money source witness is unresolved.", field="sources")
                builder.add_reference(reference, provenance_set_key=provenance)
            self.members("metric", key, "source_reference_ids", value.source_reference_ids)
        else:
            amount = value.value
        return r.ReportCell(
            kind=r.CellKind.DECIMAL,
            value=amount,
            state=r.CellState.UNAVAILABLE if missing else r.CellState.AVAILABLE,
            decimal_role=r.DecimalRole.MONEY if money else r.DecimalRole.RATIO,
            currency=builder.selection.reporting_currency if money else None,
            context_key=context.key,
            reason_key=reason,
            bound_key=bound_key,
            quality=value.quality,
            confidence=confidence,
            origin=r.ReportMetricOrigin.DERIVED_DETERMINISTIC,
            coverage_key=context.coverage_set_key,
            method_key=context.method_key,
            method_version=context.method_version,
            provenance_set_key=provenance,
            note_set_key=context.note_set_key,
        )

    def row(
        self,
        table: r.ReportTableKey,
        ordinal: str | int = 0,
        source: ScenarioRecord | SourceLicense | None = None,
        *,
        extra: Mapping[str, ScenarioValue] | None = None,
    ) -> r.ReportRow:
        supplied = extra or {}
        key = self.key(table, ordinal)
        values: dict[str, ReportValue] = {}
        for column in table_schema(table).columns:
            value = supplied[column.key] if column.key in supplied else getattr(source, column.key)
            values[column.key] = (
                self.metric(f"{key}.{column.key}", value)
                if isinstance(value, (ScenarioMoneyMetric, ScenarioRatioMetric))
                else value
            )
        return capture_row(self.builder, self.context, table, key=key, values=values)

    def table(
        self, table: r.ReportTableKey, rows: Iterable[r.ReportRow], *, analytical: bool = False
    ) -> None:
        self.builder.add_table(
            table, rows, section=r.ReportSection.SCENARIO if analytical else None
        )
