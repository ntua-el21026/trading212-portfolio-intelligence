"""Risk contracts and statistics; canonical capture integration is tested separately."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Context, Decimal, Inexact, localcontext
from typing import Any

import pytest
from trading212_analytics.risk_statistics import align_series, calculate_risk_statistics
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError
from trading212_domain.risk import RiskDefinitionContent, RiskInterval, RiskReason, RiskSeries
from trading212_domain.values import CurrencyCode

D = Decimal
START = datetime(2026, 1, 1, tzinfo=UTC)
pytestmark = pytest.mark.unit


def _series(values: tuple[Decimal | None, ...], key: str = "portfolio") -> RiskSeries:
    return RiskSeries(
        key=key,
        reporting_currency=CurrencyCode("EUR"),
        calendar_id="risk-fixture",
        calendar_version="1",
        frequency="daily",
        source_cutoff_at=START + timedelta(days=3660),
        basis="total_return",
        intervals=tuple(
            RiskInterval(
                start_at=START + timedelta(days=i),
                end_at=START + timedelta(days=i + 1),
                simple_return=value,
                quality=QualityState.FRESH if value is not None else QualityState.PARTIAL,
                reason=None if value is not None else RiskReason.MISSING_INTERVAL,
            )
            for i, value in enumerate(values)
        ),
    )


def _definition(**changes: Any) -> RiskDefinitionContent:
    return replace(
        RiskDefinitionContent(
            name="Risk",
            description="Synthetic definition",
            calendar_id="risk-fixture",
            calendar_version="1",
        ),
        **changes,
    )


def test_risk_alignment() -> None:
    a = _series((D(".01"), None, D(".03")), "a")
    b = _series((D(".02"), D(".03"), D(".04")), "b")
    aligned = align_series((a, b), "simple")
    assert aligned == align_series((b, a), "simple")
    assert aligned.requested_intervals == 3 and aligned.omitted_intervals == 1
    assert aligned.values == ((D(".01"), D(".03")), (D(".02"), D(".04")))
    assert aligned.boundaries == (
        (START, START + timedelta(days=1)),
        (START + timedelta(days=2), START + timedelta(days=3)),
    )
    with pytest.raises(DomainError):
        align_series((a, replace(b, reporting_currency=CurrencyCode("USD"))), "simple")
    with pytest.raises(DomainError):
        align_series((a, replace(b, calendar_version="2")), "simple")
    with pytest.raises(DomainError):
        align_series(
            (a, replace(b, source_cutoff_at=b.source_cutoff_at + timedelta(days=1))), "simple"
        )
    with pytest.raises(DomainError):
        align_series((a, a), "simple")


def test_risk_zero() -> None:
    series = _series((D(0),) * 30)
    result = calculate_risk_statistics(
        series, _definition(), benchmark=replace(series, key="benchmark")
    )
    assert result.volatility_periodic.value == result.volatility_annualized.value == D(0)
    assert result.downside_annualized.value == D(0)
    assert result.beta.value is None and result.beta.reason is RiskReason.ZERO_DENOMINATOR
    assert result.alpha_annualized.value is None
    assert all(point.volatility.value is None for point in result.rolling[:19])
    assert all(point.volatility.value == 0 for point in result.rolling[19:])
    assert result.used_observations == 30 and result.omitted_observations == 0


def test_risk_reference() -> None:
    benchmark = _series((D("-.01"), D(0), D(".01")) * 10, "benchmark")
    portfolio = _series((D("-.02"), D(0), D(".02")) * 10)
    result = calculate_risk_statistics(portfolio, _definition(), benchmark=benchmark)
    assert result.beta.value == D(2) and result.alpha_annualized.value == 0
    assert result.volatility_annualized.value is not None
    assert result.downside_annualized.value is not None
    with localcontext(Context(prec=150)):
        expected_vol = (D(".008") / 29 * 252).sqrt()
        expected_downside = (D(".004") / 30 * 252).sqrt()
        assert abs(result.volatility_annualized.value - expected_vol) <= D(".5e-18")
        assert abs(result.downside_annualized.value - expected_downside) <= D(".5e-18")
    assert result.benchmark_pairs == 30
    # Periodic simple risk-free rate .001 has exact annual assumption (1.001)^252-1,
    # which is rounded only at the explicit input boundary; no annual/periodic mixing.
    with localcontext(Context(prec=150)):
        annual_rf = ((D("1.001") ** 252) - 1).quantize(D("1e-18"))
    excess = calculate_risk_statistics(
        portfolio, _definition(annual_risk_free=annual_rf), benchmark=benchmark
    )
    assert excess.alpha_annualized.value is not None
    assert abs(excess.alpha_annualized.value - D(".252")) <= D("1e-18")


def test_risk_numeric() -> None:
    series = _series((D("-.01"), D(0), D(".01")) * 10)
    definition = _definition(return_kind="log")
    expected = calculate_risk_statistics(series, definition)
    with localcontext(Context(prec=4, Emin=-9, Emax=9)) as hostile:
        hostile.traps[Inexact] = True
        before = hostile.copy()
        assert calculate_risk_statistics(series, definition) == expected
        assert hostile.flags == before.flags and hostile.traps == before.traps
        assert hostile.prec == before.prec and hostile.Emax == before.Emax
    loss = replace(
        series, intervals=(replace(series.intervals[0], simple_return=D(-1)), *series.intervals[1:])
    )
    result = calculate_risk_statistics(loss, definition)
    assert result.used_observations == 29 and result.omitted_observations == 1


def test_missing_stale_and_insufficient_intervals_remain_visible() -> None:
    series = _series((D(".01"),) * 30)
    stale = replace(
        series,
        intervals=tuple(
            replace(item, quality=QualityState.STALE) if i < 11 else item
            for i, item in enumerate(series.intervals)
        ),
    )
    result = calculate_risk_statistics(stale, _definition())
    assert result.used_observations == 19 and result.omitted_observations == 11
    assert result.volatility_annualized.reason is RiskReason.INSUFFICIENT_HISTORY
    assert result.beta.reason is RiskReason.BENCHMARK_UNAVAILABLE
    assert result.rolling[-1].observations == 19 and result.rolling[-1].volatility.value is None
    with pytest.raises(DomainError):
        replace(series, intervals=(series.intervals[0], *series.intervals[2:]))
    with pytest.raises(DomainError):
        replace(series, source_cutoff_at=START)


def test_incompatible_benchmark_does_not_erase_observed_portfolio_risk() -> None:
    series = _series((D(0),) * 30)
    benchmark = replace(series, key="benchmark", frequency="monthly")
    result = calculate_risk_statistics(series, _definition(), benchmark=benchmark)
    assert result.volatility_annualized.value == 0
    assert result.beta.reason is RiskReason.INCOMPATIBLE_BASIS and result.benchmark_pairs == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("annual_risk_free", D(-1)),
        ("annual_risk_free", 0.1),
        ("annual_minimum_acceptable_return", D("NaN")),
        ("confidence", D(".97")),
        ("shrinkage", D(".5")),
        ("regularization", "silent_repair"),
        ("rolling_window", 19),
        ("horizon", True),
        ("horizon", 21),
        ("return_kind", "value_difference"),
        ("frequency", "weekly"),
        ("method_version", "unknown"),
        ("calendar_id", "unbounded " * 1000),
    ],
)
def test_risk_definition_rejects_unsupported_or_unbounded_inputs(field: str, value: Any) -> None:
    with pytest.raises(DomainError):
        _definition(**{field: value})
