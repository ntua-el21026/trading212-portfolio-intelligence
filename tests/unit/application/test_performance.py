from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from trading212_application.performance import (
    CorePerformanceInput,
    PerformanceFlowInput,
    PerformanceSnapshotInput,
    calculate_core_performance,
)
from trading212_application.views import Availability, ViewQuality

START = datetime(2026, 1, 1, tzinfo=UTC)
MID = datetime(2026, 7, 2, 12, tzinfo=UTC)
END = datetime(2027, 1, 1, tzinfo=UTC)


def _snapshot(identifier: str, at: datetime, amount: str) -> PerformanceSnapshotInput:
    return PerformanceSnapshotInput(
        snapshot_id=identifier,
        valuation_at=at,
        value=Decimal(amount),
        currency="EUR",
        quality=ViewQuality.FRESH,
    )


def _input(
    *,
    ending: str = "110",
    flows: tuple[PerformanceFlowInput, ...] = (),
    coverage_complete: bool = True,
    reconciled: bool = True,
) -> CorePerformanceInput:
    return CorePerformanceInput(
        snapshots=(_snapshot("start", START, "100"), _snapshot("end", END, ending)),
        external_flows=flows,
        reporting_currency="EUR",
        evaluated_at=END,
        coverage_start_at=START,
        coverage_end_at=END,
        coverage_complete=coverage_complete,
        reconciled=reconciled,
    )


def test_available_performance_preserves_method_metadata_and_exact_values() -> None:
    result = calculate_core_performance(_input())
    metrics = (
        result.money_weighted_return,
        result.time_weighted_return,
        result.modified_dietz_return,
    )

    assert [metric.method_id for metric in metrics] == [
        "xirr",
        "snapshot_subperiod_twr",
        "modified_dietz",
    ]
    assert [metric.value_kind for metric in metrics] == [
        "annual_rate",
        "cumulative_return",
        "cumulative_return",
    ]
    assert all(metric.value == Decimal("0.100000000000000000") for metric in metrics)
    assert all(metric.annualized_value == Decimal("0.100000000000000000") for metric in metrics)
    assert all(metric.availability is Availability.AVAILABLE for metric in metrics)
    assert all(metric.calculation_version == "1.0.0" for metric in metrics)
    assert result.money_weighted_return.converged is True
    assert result.money_weighted_return.iterations is not None
    assert all(metric.assumptions for metric in metrics)
    assert all(not metric.missing_inputs for metric in metrics)
    assert result.quality.state is ViewQuality.FRESH


def test_midperiod_flow_keeps_xirr_and_dietz_but_gates_twr_and_summary() -> None:
    result = calculate_core_performance(
        _input(
            ending="220",
            flows=(
                PerformanceFlowInput(
                    occurred_at=MID,
                    amount=Decimal("100"),
                    currency="EUR",
                    quality=ViewQuality.FRESH,
                ),
            ),
        )
    )

    assert result.money_weighted_return.availability is Availability.AVAILABLE
    assert result.modified_dietz_return.value == Decimal("0.133333333333333333")
    assert result.time_weighted_return.availability is Availability.UNAVAILABLE
    assert "complete_subperiod" in result.time_weighted_return.missing_inputs
    assert result.time_weighted_return.quality_state is ViewQuality.PARTIAL
    assert result.quality.state is ViewQuality.PARTIAL
    assert "complete_subperiod" in result.quality.missing_inputs


def test_partial_boundary_flow_degrades_twr_and_overall_quality() -> None:
    result = calculate_core_performance(
        _input(
            ending="210",
            flows=(
                PerformanceFlowInput(
                    occurred_at=END,
                    amount=Decimal("100"),
                    currency="EUR",
                    quality=ViewQuality.PARTIAL,
                ),
            ),
        )
    )

    assert result.time_weighted_return.availability is Availability.UNAVAILABLE
    assert "reliable_material_inputs" in result.time_weighted_return.missing_inputs
    assert result.time_weighted_return.quality_state is ViewQuality.PARTIAL
    assert result.quality.state is ViewQuality.PARTIAL


def test_unavailable_prerequisites_preserve_each_method_identity() -> None:
    result = calculate_core_performance(
        CorePerformanceInput(
            snapshots=(_snapshot("only", START, "100"),),
            external_flows=(),
            reporting_currency="EUR",
            evaluated_at=END,
            coverage_start_at=START,
            coverage_end_at=START,
            coverage_complete=False,
            reconciled=False,
        )
    )
    metrics = (
        result.money_weighted_return,
        result.time_weighted_return,
        result.modified_dietz_return,
    )

    assert [metric.method_id for metric in metrics] == [
        "xirr",
        "snapshot_subperiod_twr",
        "modified_dietz",
    ]
    assert [metric.value_kind for metric in metrics] == [
        "annual_rate",
        "cumulative_return",
        "cumulative_return",
    ]
    assert all(metric.availability is Availability.UNAVAILABLE for metric in metrics)
    assert all("two_portfolio_snapshots" in metric.missing_inputs for metric in metrics)
    assert all(metric.period_end == START for metric in metrics)


def test_incomplete_coverage_and_reconciliation_propagate_to_summary() -> None:
    incomplete = calculate_core_performance(_input(coverage_complete=False))
    unreconciled = calculate_core_performance(_input(reconciled=False))

    assert all(
        metric.availability is Availability.UNAVAILABLE
        for metric in (
            incomplete.money_weighted_return,
            incomplete.time_weighted_return,
            incomplete.modified_dietz_return,
        )
    )
    assert "complete_history_coverage" in incomplete.quality.missing_inputs
    assert incomplete.quality.state is ViewQuality.PARTIAL
    assert "reconciled_material_inputs" in unreconciled.quality.missing_inputs
    assert unreconciled.quality.state is ViewQuality.UNRECONCILED


def test_missing_fx_for_external_flow_fails_every_performance_method_closed() -> None:
    result = calculate_core_performance(
        _input(
            ending="220",
            flows=(
                PerformanceFlowInput(
                    occurred_at=MID,
                    amount=Decimal("100"),
                    currency="USD",
                    quality=ViewQuality.FRESH,
                ),
            ),
        )
    )

    metrics = (
        result.money_weighted_return,
        result.time_weighted_return,
        result.modified_dietz_return,
    )
    assert all(metric.availability is Availability.UNAVAILABLE for metric in metrics)
    assert all("external_flow_fx_conversion" in metric.missing_inputs for metric in metrics)
    assert "external_flow_fx_conversion" in result.quality.missing_inputs
    assert result.quality.state is ViewQuality.PARTIAL


def test_multiple_sign_change_xirr_is_explicitly_unavailable() -> None:
    first_flow = datetime(2026, 4, 1, tzinfo=UTC)
    second_flow = datetime(2026, 10, 1, tzinfo=UTC)
    result = calculate_core_performance(
        _input(
            ending="110",
            flows=(
                PerformanceFlowInput(
                    occurred_at=first_flow,
                    amount=Decimal("-300"),
                    currency="EUR",
                    quality=ViewQuality.FRESH,
                ),
                PerformanceFlowInput(
                    occurred_at=second_flow,
                    amount=Decimal("250"),
                    currency="EUR",
                    quality=ViewQuality.FRESH,
                ),
            ),
        )
    )

    xirr = result.money_weighted_return
    assert xirr.availability is Availability.UNAVAILABLE
    assert xirr.converged is False
    assert "unique_conventional_root" in xirr.missing_inputs
    assert any("ambiguous" in warning.casefold() for warning in xirr.warnings)


def test_duplicate_snapshot_valuation_revisions_fail_closed_without_raising() -> None:
    result = calculate_core_performance(
        CorePerformanceInput(
            snapshots=(
                _snapshot("start", START, "100"),
                _snapshot("end-revision-a", END, "110"),
                _snapshot("end-revision-b", END, "111"),
            ),
            external_flows=(),
            reporting_currency="EUR",
            evaluated_at=END,
            coverage_start_at=START,
            coverage_end_at=END,
            coverage_complete=True,
            reconciled=True,
        )
    )

    metrics = (
        result.money_weighted_return,
        result.time_weighted_return,
        result.modified_dietz_return,
    )
    assert all(metric.availability is Availability.UNAVAILABLE for metric in metrics)
    assert all("unique_snapshot_valuation_revisions" in metric.missing_inputs for metric in metrics)
    assert result.quality.state is ViewQuality.PARTIAL
