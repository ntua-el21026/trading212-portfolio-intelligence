"""Coverage-gated application use case over deterministic analytics primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import pairwise

from trading212_analytics import (
    MODIFIED_DIETZ_METHOD_ID,
    TWR_METHOD_ID,
    XIRR_METHOD_ID,
    DatedExternalFlow,
    ReturnMetric,
    SubperiodReturnInput,
    calculate_modified_dietz,
    calculate_time_weighted_return,
    calculate_xirr,
)
from trading212_domain import Coverage, Instant, Money, QualityState

from .views import (
    Availability,
    PerformanceSummaryView,
    QualityView,
    ReturnMetricView,
    ViewQuality,
)


@dataclass(frozen=True, slots=True)
class PerformanceSnapshotInput:
    snapshot_id: str
    valuation_at: datetime
    value: Decimal | None
    currency: str
    quality: ViewQuality


@dataclass(frozen=True, slots=True)
class PerformanceFlowInput:
    occurred_at: datetime
    amount: Decimal
    currency: str
    quality: ViewQuality


@dataclass(frozen=True, slots=True)
class CorePerformanceInput:
    snapshots: tuple[PerformanceSnapshotInput, ...]
    external_flows: tuple[PerformanceFlowInput, ...]
    reporting_currency: str
    evaluated_at: datetime
    coverage_start_at: datetime | None
    coverage_end_at: datetime | None
    coverage_complete: bool
    coverage_gaps: tuple[str, ...] = ()
    gate_missing_inputs: tuple[str, ...] = ()
    reconciled: bool = True


def calculate_core_performance(value: CorePerformanceInput) -> PerformanceSummaryView:
    ordered_snapshots = tuple(
        sorted(value.snapshots, key=lambda item: (item.valuation_at, item.snapshot_id))
    )
    duplicate_valuations = tuple(
        dict.fromkeys(
            item.valuation_at.isoformat()
            for previous, item in pairwise(ordered_snapshots)
            if previous.valuation_at == item.valuation_at
        )
    )
    # Snapshot revisions may legitimately share a valuation instant (for example,
    # after a calculation-version change). Collapse each instant deterministically
    # before constructing TWR subperiods, but fail the economic gate closed until a
    # canonical revision-selection policy is available. This prevents an equal-time
    # subperiod from raising while avoiding an arbitrary return claim.
    snapshots_by_valuation: dict[datetime, PerformanceSnapshotInput] = {}
    for item in ordered_snapshots:
        snapshots_by_valuation[item.valuation_at] = item
    snapshots = tuple(snapshots_by_valuation.values())
    revision_missing = ("unique_snapshot_valuation_revisions",) if duplicate_valuations else ()
    usable = tuple(item for item in snapshots if item.value is not None)
    effective_period_end = usable[-1].valuation_at if usable else value.evaluated_at
    period_end = effective_period_end.date()
    if len(usable) < 2:
        metrics = _unavailable_metrics(
            period_start=None,
            period_end=effective_period_end,
            missing=(
                "two_portfolio_snapshots",
                *revision_missing,
                *value.gate_missing_inputs,
            ),
            quality=ViewQuality.PARTIAL,
        )
        return PerformanceSummaryView(
            None,
            period_end,
            metrics[0],
            metrics[1],
            metrics[2],
            _quality(value, state=ViewQuality.PARTIAL, missing=metrics[0].missing_inputs),
        )

    beginning, ending = usable[0], usable[-1]
    period_start = Instant(beginning.valuation_at)
    period_finish = Instant(ending.valuation_at)
    gate_missing = [*revision_missing, *value.gate_missing_inputs]
    if any(item.currency != value.reporting_currency for item in usable):
        gate_missing.append("snapshot_reporting_currency_consistency")
    foreign_flows = tuple(
        item for item in value.external_flows if item.currency != value.reporting_currency
    )
    if foreign_flows:
        gate_missing.append("external_flow_fx_conversion")
    if not value.reconciled:
        gate_missing.append("reconciled_material_inputs")
    coverage_gaps = tuple(dict.fromkeys((*value.coverage_gaps, *gate_missing)))
    coverage = Coverage(
        start_at=(
            Instant(value.coverage_start_at) if value.coverage_start_at is not None else None
        ),
        end_at=(Instant(value.coverage_end_at) if value.coverage_end_at is not None else None),
        complete=value.coverage_complete and not coverage_gaps,
        gaps=coverage_gaps,
    )
    quality = _worst_quality(tuple(item.quality for item in usable), reconciled=value.reconciled)
    if gate_missing:
        unavailable = _unavailable_metrics(
            period_start=beginning.valuation_at,
            period_end=ending.valuation_at,
            missing=tuple(dict.fromkeys(gate_missing)),
            quality=quality,
        )
        return PerformanceSummaryView(
            beginning.valuation_at.date(),
            ending.valuation_at.date(),
            unavailable[0],
            unavailable[1],
            unavailable[2],
            _quality(value, state=quality, missing=coverage_gaps),
        )

    flows = tuple(
        DatedExternalFlow(
            amount=Money.parse(item.amount, item.currency),
            occurred_at=Instant(item.occurred_at),
            quality_state=QualityState(item.quality.value),
        )
        for item in value.external_flows
        if beginning.valuation_at <= item.occurred_at <= ending.valuation_at
    )
    beginning_money = Money.parse(beginning.value or Decimal(0), value.reporting_currency)
    ending_money = Money.parse(ending.value or Decimal(0), value.reporting_currency)
    xirr = calculate_xirr(
        beginning_value=beginning_money,
        ending_value=ending_money,
        period_start=period_start,
        period_end=period_finish,
        external_flows=flows,
        coverage=coverage,
        beginning_quality=QualityState(beginning.quality.value),
        ending_quality=QualityState(ending.quality.value),
    )
    dietz = calculate_modified_dietz(
        beginning_value=beginning_money,
        ending_value=ending_money,
        period_start=period_start,
        period_end=period_finish,
        external_flows=flows,
        coverage=coverage,
        beginning_quality=QualityState(beginning.quality.value),
        ending_quality=QualityState(ending.quality.value),
    )
    subperiods: list[SubperiodReturnInput] = []
    for start, end in pairwise(usable):
        subperiod_flows = tuple(
            flow
            for flow in value.external_flows
            if start.valuation_at < flow.occurred_at <= end.valuation_at
        )
        boundary_flows = tuple(
            flow for flow in subperiod_flows if flow.occurred_at == end.valuation_at
        )
        subperiods.append(
            SubperiodReturnInput(
                starts_at=Instant(start.valuation_at),
                ends_at=Instant(end.valuation_at),
                beginning_value=Money.parse(start.value or Decimal(0), value.reporting_currency),
                ending_value=Money.parse(end.value or Decimal(0), value.reporting_currency),
                external_flow_at_end=Money.parse(
                    sum((flow.amount for flow in boundary_flows), Decimal(0)),
                    value.reporting_currency,
                ),
                complete=len(boundary_flows) == len(subperiod_flows),
                quality_state=QualityState(
                    _worst_quality(
                        (
                            start.quality,
                            end.quality,
                            *(flow.quality for flow in subperiod_flows),
                        )
                    ).value
                ),
            )
        )
    twr = calculate_time_weighted_return(subperiods=tuple(subperiods), coverage=coverage)
    xirr_view = _metric_view(xirr)
    twr_view = _metric_view(twr)
    dietz_view = _metric_view(dietz)
    metric_views = (xirr_view, twr_view, dietz_view)
    summary_missing = tuple(
        dict.fromkeys(
            (
                *coverage_gaps,
                *(item for metric in metric_views for item in metric.missing_inputs),
            )
        )
    )
    summary_quality = _worst_quality(
        (quality, *(metric.quality_state for metric in metric_views)),
        reconciled=value.reconciled,
    )
    return PerformanceSummaryView(
        period_start=beginning.valuation_at.date(),
        period_end=ending.valuation_at.date(),
        money_weighted_return=xirr_view,
        time_weighted_return=twr_view,
        modified_dietz_return=dietz_view,
        quality=_quality(value, state=summary_quality, missing=summary_missing),
    )


def _metric_view(value: ReturnMetric) -> ReturnMetricView:
    warning_text = tuple(f"{item.code}: {item.message}" for item in value.warnings)
    return ReturnMetricView(
        method_id=value.method_id,
        value_kind=value.value_kind,
        period_start=value.period_start.value,
        period_end=value.period_end.value,
        value=None if value.value is None else value.value.value,
        annualized_value=(None if value.annualized_value is None else value.annualized_value.value),
        availability=(
            Availability.AVAILABLE if value.value is not None else Availability.UNAVAILABLE
        ),
        calculation_version=value.version,
        methodology=value.method_id,
        converged=value.converged,
        iterations=value.iterations,
        missing_inputs=value.missing_inputs,
        assumptions=value.assumptions,
        warnings=warning_text,
        quality_state=ViewQuality(value.quality_state.value),
        unavailable_reason=warning_text[0] if warning_text else None,
    )


def _unavailable(
    *,
    method_id: str,
    period_start: datetime | None,
    period_end: datetime,
    missing: tuple[str, ...],
    quality: ViewQuality,
) -> ReturnMetricView:
    effective_quality = _worst_quality((quality, ViewQuality.PARTIAL))
    return ReturnMetricView(
        method_id=method_id,
        value_kind=("annual_rate" if method_id == XIRR_METHOD_ID else "cumulative_return"),
        period_start=period_start,
        period_end=period_end,
        value=None,
        annualized_value=None,
        availability=Availability.UNAVAILABLE,
        calculation_version="1.0.0",
        methodology="coverage-gated deterministic performance policy",
        converged=False if method_id == XIRR_METHOD_ID else None,
        iterations=0 if method_id == XIRR_METHOD_ID else None,
        missing_inputs=missing,
        assumptions=("Metrics remain unavailable until every required gate is satisfied.",),
        warnings=("Performance prerequisites are incomplete.",),
        quality_state=effective_quality,
        unavailable_reason="Performance prerequisites are incomplete.",
    )


def _unavailable_metrics(
    *,
    period_start: datetime | None,
    period_end: datetime,
    missing: tuple[str, ...],
    quality: ViewQuality,
) -> tuple[ReturnMetricView, ReturnMetricView, ReturnMetricView]:
    return (
        _unavailable(
            method_id=XIRR_METHOD_ID,
            period_start=period_start,
            period_end=period_end,
            missing=missing,
            quality=quality,
        ),
        _unavailable(
            method_id=TWR_METHOD_ID,
            period_start=period_start,
            period_end=period_end,
            missing=missing,
            quality=quality,
        ),
        _unavailable(
            method_id=MODIFIED_DIETZ_METHOD_ID,
            period_start=period_start,
            period_end=period_end,
            missing=missing,
            quality=quality,
        ),
    )


def _worst_quality(values: tuple[ViewQuality, ...], *, reconciled: bool = True) -> ViewQuality:
    severity = {
        ViewQuality.FRESH: 0,
        ViewQuality.STALE: 1,
        ViewQuality.ESTIMATED: 2,
        ViewQuality.PARTIAL: 3,
        ViewQuality.UNRECONCILED: 4,
        ViewQuality.FAILED: 5,
    }
    state = max(values or (ViewQuality.PARTIAL,), key=severity.__getitem__)
    if not reconciled and severity[state] < severity[ViewQuality.UNRECONCILED]:
        return ViewQuality.UNRECONCILED
    return state


def _quality(
    value: CorePerformanceInput,
    *,
    state: ViewQuality | None = None,
    missing: tuple[str, ...] = (),
) -> QualityView:
    effective = state or _worst_quality(
        tuple(item.quality for item in value.snapshots), reconciled=value.reconciled
    )
    if missing:
        effective = _worst_quality((effective, ViewQuality.PARTIAL))
    return QualityView(
        state=effective,
        as_of=value.evaluated_at,
        source_timestamp=value.coverage_end_at or value.evaluated_at,
        freshness_threshold_seconds=900,
        warnings=("Performance coverage is incomplete.",) if missing else (),
        missing_inputs=missing,
    )
