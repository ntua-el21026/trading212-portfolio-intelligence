"""Fixed, lossless presentation of an already authorized immutable risk calculation.

This module never loads private bytes or runs numerical analytics. The caller must
first authorize REPORT/STORE/DISPLAY, verify normalized storage, and retain a
normalized premium dependency in the same report creation transaction.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from trading212_domain import reports as r
from trading212_domain.enums import QualityState
from trading212_domain.errors import fail_validation
from trading212_domain.historical_serialization import historical_input_digest
from trading212_domain.report_schema import table_schema
from trading212_domain.risk import (
    RISK_METHOD,
    RiskDefinitionContent,
    RiskMetric,
    RiskSeriesStatistics,
)
from trading212_domain.risk_execution import RiskExecutionInput
from trading212_domain.risk_result import (
    RiskCalculation,
    RiskComponent,
    RiskConcentration,
    RiskModel,
    RiskTail,
)
from trading212_domain.risk_serialization import risk_result_digest

from .historical_base import digest
from .report_builder import ReportBuilder
from .report_capture_common import ReportValue, capture_note, capture_row, capture_table
from .report_capture_historical import _metric as historical_metric
from .report_capture_risk_proof import capture_risk_history, capture_risk_trace


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskReportMetadata(r.ReportRecord):
    """Owned sealed metadata supplied by the selected-run persistence loader."""

    run_id: UUID
    result_id: UUID
    result_digest: str
    definition_id: UUID
    definition_version_id: UUID
    definition_version_number: int
    definition_digest: str
    portfolio_snapshot_id: UUID
    historical_input_snapshot_id: UUID
    benchmark_version_id: UUID | None
    xray_run_id: UUID | None
    xray_input_id: UUID | None
    xray_input_digest: str | None
    created_at: datetime
    completed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        if not 1 <= self.definition_version_number <= 512 or not (
            self.created_at <= self.completed_at < self.expires_at
        ):
            fail_validation("Risk report metadata is inconsistent.", field="risk_run_id")
        if (self.xray_run_id is None) != (self.xray_input_id is None) or (
            self.xray_run_id is None
        ) != (self.xray_input_digest is None):
            fail_validation("Risk report X-ray identity is incomplete.", field="risk_run_id")


@dataclass(frozen=True, slots=True)
class RiskReportContexts:
    observed: r.ReportContext
    modeled: r.ReportContext
    concentration: r.ReportContext
    historical: r.ReportContext


type RiskRow = (
    RiskDefinitionContent
    | RiskSeriesStatistics
    | RiskTail
    | RiskModel
    | RiskComponent
    | RiskConcentration
)
type RiskValue = ReportValue | RiskMetric


def risk_metric_cell(
    builder: ReportBuilder,
    context: r.ReportContext,
    *,
    key: str,
    value: RiskMetric,
    role: r.DecimalRole,
    lower_bound: bool = False,
) -> r.ReportCell:
    """Keep the exact number and its reason; never infer a missing number as zero."""
    reason = None
    if value.reason is not None:
        reason = capture_note(
            builder,
            context,
            key=f"{key}.reason",
            code=value.reason.value,
            text=value.reason.value,
        )
    builder.add_bound(
        r.ReportBoundFact(
            key=key,
            family=context.family,
            kind=r.ReportBoundKind.UNAVAILABLE
            if value.value is None
            else r.ReportBoundKind.LOWER_BOUND
            if lower_bound
            else r.ReportBoundKind.EXACT,
            quantum=Decimal("1e-18"),
            rounding="ROUND_HALF_EVEN",
        )
    )
    return r.ReportCell(
        kind=r.CellKind.DECIMAL,
        decimal_role=role,
        value=value.value,
        state=r.CellState.UNAVAILABLE if value.value is None else r.CellState.AVAILABLE,
        context_key=context.key,
        reason_key=reason,
        bound_key=key,
        quality=context.quality,
        origin=r.ReportMetricOrigin.DERIVED_DETERMINISTIC,
        coverage_key=context.coverage_set_key,
        method_key=context.method_key,
        method_version=context.method_version,
        provenance_set_key=context.provenance_set_key,
        note_set_key=context.note_set_key,
    )


def _row(
    builder: ReportBuilder,
    context: r.ReportContext,
    table: r.ReportTableKey,
    key: str,
    source: RiskRow | None = None,
    *,
    extra: Mapping[str, RiskValue] | None = None,
) -> r.ReportRow:
    supplied = extra or {}
    values: dict[str, ReportValue] = {}
    # A closed union plus the literal table registry controls every emitted field.
    for column in table_schema(table).columns:
        value = supplied[column.key] if column.key in supplied else getattr(source, column.key)
        if isinstance(value, RiskMetric):
            if column.decimal_role is None:
                fail_validation("Risk metric has no declared unit.", field="table")
            values[column.key] = risk_metric_cell(
                builder,
                context,
                key=f"{key}.{column.key}",
                value=value,
                role=column.decimal_role,
                lower_bound=isinstance(source, RiskConcentration)
                and source.lower_bound
                and column.key == "hhi",
            )
        else:
            values[column.key] = value
    return capture_row(builder, context, table, key=key, values=values)


def _contexts(builder: ReportBuilder, value: RiskCalculation, prefix: str) -> RiskReportContexts:
    actual = value.history.canonical_performance_context

    def context(name: str, quality: QualityState, *, historical: bool = False) -> r.ReportContext:
        key = f"{prefix}.{name}"
        item = r.ReportContext(
            key=key,
            family=r.ReportFamily.PERFORMANCE if historical else r.ReportFamily.RISK,
            method_key=actual.method.name if historical else RISK_METHOD,
            method_version=actual.method.version if historical else value.method_version,
            valuation_at=value.modeled_valuation_at
            if name in ("modeled", "concentration") and value.modeled_valuation_at is not None
            else actual.window.end_at,
            source_cutoff_at=actual.window.source_cutoff_at,
            quality=quality,
            provenance_set_key=f"{key}.sources",
            coverage_set_key=f"{key}.coverage",
            note_set_key=f"{key}.notes",
            schema_version=r.PREMIUM_REPORT_SCHEMA_VERSION,
        )
        builder.add_context(item)
        return item

    model_quality = actual.quality
    if not value.modeled.complete_universe and model_quality is QualityState.FRESH:
        model_quality = QualityState.PARTIAL
    result = RiskReportContexts(
        observed=context("observed", actual.quality),
        modeled=context("modeled", model_quality),
        concentration=context("concentration", value.concentration.quality),
        historical=context("history", actual.quality, historical=True),
    )
    for key, text in (
        ("numerical_profile", value.numerical_profile),
        (
            "return_basis",
            "Stored intervals are simple total returns; "
            "the definition selects simple or log statistics.",
        ),
        (
            "covariance_units",
            "Covariance is squared periodic return; correlation is dimensionless.",
        ),
        (
            "series_admission",
            "Canonical listwise interval eligibility and exclusions are preserved; "
            "no forward filling or recomputation occurs.",
        ),
        (
            "tail_sign",
            "Positive values denote losses; each tail retains its confidence, "
            "horizon and quantile conventions.",
        ),
    ):
        capture_note(
            builder,
            result.observed,
            key=f"{prefix}.{key}",
            text=text,
            kind=r.ReportNoteKind.ASSUMPTION,
            code=key,
        )
    capture_note(
        builder,
        result.modeled,
        key=f"{prefix}.whole_universe",
        text=(
            "Modeled risk uses the pinned current portfolio's complete selected universe "
            "without renormalizing uncovered positions or cash. "
            "Display residuals are copied exactly."
        ),
        kind=r.ReportNoteKind.ASSUMPTION,
        code="whole_universe_current_weights",
    )
    capture_note(
        builder,
        result.observed,
        key=f"{prefix}.definition_assumptions",
        text=(
            "Risk-free return, minimum acceptable return, confidence, horizon and "
            "regularization are the pinned owner's model assumptions."
        ),
        kind=r.ReportNoteKind.ASSUMPTION,
        code="owner_model_assumptions",
    )
    return result


def _check_selection(
    builder: ReportBuilder,
    value: RiskCalculation,
    execution: RiskExecutionInput,
    metadata: RiskReportMetadata,
) -> None:
    selection, history = builder.selection, value.history
    actual = history.canonical_performance_context
    window = actual.window
    if not isinstance(selection, r.ReportSelection) or (
        r.ReportSection.RISK not in selection.sections or selection.risk_run_id != metadata.run_id
    ):
        fail_validation("An explicit risk report selection is required.", field="risk_run_id")
    if (
        UUID(history.owner_id) != builder.owner_id
        or UUID(history.account_id) != selection.account_id
        or metadata.portfolio_snapshot_id != selection.snapshot_id
        or window.start_date != selection.start_date
        or window.end_date != selection.end_date
        or window.source_cutoff_at != selection.source_cutoff_at
        or window.reporting_currency != selection.reporting_currency
        or execution.historical.selection.window != window
        or history.historical_input_digest != historical_input_digest(execution.historical)
        or value.definition != execution.definition
        or metadata.definition_digest != digest(value.definition)
        or tuple(item.key for item in history.assets)
        != tuple(item.instrument_id for item in execution.assets)
        or value.xray_result_digest
        != (None if execution.xray is None else execution.xray.content_digest)
        or metadata.result_digest != risk_result_digest(value)
        or (metadata.xray_run_id is None) != (execution.xray is None)
        or (
            execution.xray is not None
            and (
                execution.xray.snapshot_id != metadata.portfolio_snapshot_id
                or execution.xray.input_digest != metadata.xray_input_digest
            )
        )
    ):
        fail_validation(
            "Risk report inputs differ from the selected immutable run.", field="risk_run_id"
        )


def project_risk(
    builder: ReportBuilder,
    value: RiskCalculation,
    execution: RiskExecutionInput,
    metadata: RiskReportMetadata,
) -> RiskReportContexts:
    """Copy all retained risk fields and full history trace, with no calculation."""
    _check_selection(builder, value, execution, metadata)
    builder.limit_copy_expiry(min(metadata.expires_at, execution.expires_at))
    prefix = f"risk.{metadata.run_id}"
    contexts = _contexts(builder, value, prefix)
    observed, modeled, concentration = contexts.observed, contexts.modeled, contexts.concentration
    window = value.history.canonical_performance_context.window

    def put(table: r.ReportTableKey, rows: Iterable[r.ReportRow]) -> None:
        capture_table(builder, table, rows)

    def one(
        table: r.ReportTableKey,
        source: RiskRow | None = None,
        *,
        extra: Mapping[str, RiskValue] | None = None,
        context: r.ReportContext = observed,
    ) -> None:
        put(table, (_row(builder, context, table, f"{prefix}.{table.value}", source, extra=extra),))

    one(
        r.ReportTableKey.RISK_BASIS_V1,
        extra={
            "run_id": metadata.run_id,
            "result_id": metadata.result_id,
            "result_digest": metadata.result_digest,
            "input_digest": execution.input_digest,
            "definition_id": metadata.definition_id,
            "definition_version_id": metadata.definition_version_id,
            "definition_version_number": metadata.definition_version_number,
            "definition_digest": metadata.definition_digest,
            "account_id": value.history.account_id,
            "portfolio_snapshot_id": metadata.portfolio_snapshot_id,
            "historical_input_snapshot_id": metadata.historical_input_snapshot_id,
            "historical_input_digest": value.history.historical_input_digest,
            "benchmark_version_id": metadata.benchmark_version_id,
            "xray_run_id": metadata.xray_run_id,
            "xray_input_id": metadata.xray_input_id,
            "xray_input_digest": metadata.xray_input_digest,
            "xray_result_digest": value.xray_result_digest,
            "window_start_date": window.start_date,
            "window_end_date": window.end_date,
            "window_start_at": window.start_at,
            "window_end_at": window.end_at,
            "source_cutoff_at": window.source_cutoff_at,
            "reporting_currency": window.reporting_currency.value,
            "coverage_policy": window.coverage_policy,
            "knowledge_policy": window.knowledge_policy,
            "modeled_portfolio_snapshot_id": value.portfolio_snapshot_id,
            "modeled_valuation_at": value.modeled_valuation_at,
            "run_created_at": metadata.created_at,
            "run_completed_at": metadata.completed_at,
            "run_expires_at": metadata.expires_at,
            "family": value.family,
            "method_key": RISK_METHOD,
            "method_version": value.method_version,
            "schema_version": value.schema_version,
            "numerical_profile": value.numerical_profile,
            "annualization_factor": value.annualization_factor,
            "covariance_degrees_of_freedom": value.covariance_degrees_of_freedom,
        },
    )
    one(r.ReportTableKey.RISK_DEFINITION_V1, value.definition)
    one(
        r.ReportTableKey.RISK_OBSERVED_V1,
        value.observed,
        extra={
            "maximum_drawdown": historical_metric(
                builder,
                contexts.historical,
                row_key=f"{prefix}.risk_observed_v1",
                column_key="maximum_drawdown",
                value=value.history.maximum_drawdown,
                missing_currency=window.reporting_currency,
            ),
        },
    )
    put(
        r.ReportTableKey.RISK_ROLLING_V1,
        (
            _row(
                builder,
                observed,
                r.ReportTableKey.RISK_ROLLING_V1,
                f"{prefix}.rolling.{i}",
                extra={
                    "ordinal": i,
                    "end_at": point.end_at,
                    "observations": point.observations,
                    "volatility": point.volatility,
                },
            )
            for i, point in enumerate(value.observed.rolling)
        ),
    )
    matrix = value.matrix
    one(
        r.ReportTableKey.RISK_MATRIX_SUMMARY_V1,
        extra={
            "asset_count": len(matrix.keys),
            "requested_intervals": matrix.requested_intervals,
            "used_intervals": matrix.used_intervals,
            "omitted_intervals": matrix.omitted_intervals,
            "numerical_zero_pivot_count": len(matrix.numerical_zero_pivots),
        },
    )
    put(
        r.ReportTableKey.RISK_MATRIX_AXES_V1,
        (
            _row(
                builder,
                observed,
                r.ReportTableKey.RISK_MATRIX_AXES_V1,
                f"{prefix}.axis.{i}",
                extra={
                    "ordinal": i,
                    "instrument_id": key,
                    "numerical_zero_pivot": i in matrix.numerical_zero_pivots,
                },
            )
            for i, key in enumerate(matrix.keys)
        ),
    )
    put(
        r.ReportTableKey.RISK_MATRIX_CELLS_V1,
        (
            _row(
                builder,
                observed,
                r.ReportTableKey.RISK_MATRIX_CELLS_V1,
                f"{prefix}.matrix.{i}.{j}",
                extra={
                    "row_ordinal": i,
                    "column_ordinal": j,
                    "row_instrument_id": row_key,
                    "column_instrument_id": column_key,
                    "covariance_periodic": matrix.covariance_periodic[i][j],
                    "regularized_covariance_periodic": matrix.regularized_covariance_periodic[i][j],
                    "correlation": matrix.correlation[i][j],
                },
            )
            for i, row_key in enumerate(matrix.keys)
            for j, column_key in enumerate(matrix.keys)
        ),
    )
    put(
        r.ReportTableKey.RISK_TAILS_V1,
        (
            _row(
                builder,
                observed,
                r.ReportTableKey.RISK_TAILS_V1,
                f"{prefix}.tail.{tail.method}",
                tail,
            )
            for tail in (value.historical_tail, value.parametric_tail)
        ),
    )
    one(r.ReportTableKey.RISK_MODELED_V1, value.modeled, context=modeled)
    put(
        r.ReportTableKey.RISK_COMPONENTS_V1,
        (
            _row(
                builder,
                modeled,
                r.ReportTableKey.RISK_COMPONENTS_V1,
                f"{prefix}.component.{i}",
                component,
                extra={"ordinal": i},
            )
            for i, component in enumerate(value.modeled.components)
        ),
    )
    one(r.ReportTableKey.RISK_CONCENTRATION_V1, value.concentration, context=concentration)
    for role, identifier, content, parent in (
        (r.ReportInputRole.INPUT, metadata.run_id, execution.input_digest, None),
        (r.ReportInputRole.RESULT, metadata.result_id, metadata.result_digest, metadata.run_id),
        (
            r.ReportInputRole.POLICY,
            metadata.definition_version_id,
            metadata.definition_digest,
            metadata.definition_id,
        ),
    ):
        builder.add_binding(
            r.ReportBinding(
                family=r.ReportFamily.RISK,
                role=role,
                subject_id=identifier,
                content_digest=content,
                parent_id=parent,
                method_key=RISK_METHOD,
                method_version=value.method_version,
            )
        )
    builder.add_binding(
        r.ReportBinding(
            family=r.ReportFamily.PERFORMANCE,
            role=r.ReportInputRole.INPUT,
            subject_id=metadata.historical_input_snapshot_id,
            content_digest=value.history.historical_input_digest,
            method_key=contexts.historical.method_key,
            method_version=contexts.historical.method_version,
        )
    )
    capture_risk_history(builder, contexts.historical, observed, value, execution, prefix)
    capture_risk_trace(builder, contexts.historical, value.history)
    if execution.xray is None:
        builder.add_table(r.ReportTableKey.RISK_XRAY_PATHS_V1, ())
    return contexts
