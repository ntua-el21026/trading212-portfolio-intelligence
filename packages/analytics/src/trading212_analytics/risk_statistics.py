"""Risk estimators over aligned canonical intervals; no public return-array input."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from trading212_domain.enums import QualityState
from trading212_domain.risk import (
    RiskDefinitionContent,
    RiskInterval,
    RiskMetric,
    RiskReason,
    RiskRollingPoint,
    RiskSeries,
    RiskSeriesStatistics,
)

from ._premium_numeric import ONE, ZERO, arithmetic, invalid, q18, sample_covariance


@dataclass(frozen=True, slots=True)
class AlignedRiskSeries:
    keys: tuple[str, ...]
    boundaries: tuple[tuple[datetime, datetime], ...]
    values: tuple[tuple[Decimal, ...], ...]
    requested_intervals: int
    omitted_intervals: int


def _basis(series: RiskSeries) -> tuple[object, ...]:
    return (
        series.reporting_currency,
        series.calendar_id,
        series.calendar_version,
        series.frequency,
        series.source_cutoff_at,
        series.basis,
    )


def _return(interval: RiskInterval, kind: Literal["simple", "log"]) -> Decimal | None:
    value = interval.simple_return
    if value is None or interval.quality is not QualityState.FRESH:
        return None
    if kind == "simple":
        return value
    if value == -ONE:
        return None
    return (ONE + value).ln()


def align_series(
    series: tuple[RiskSeries, ...],
    return_kind: Literal["simple", "log"],
) -> AlignedRiskSeries:
    if (
        not isinstance(series, tuple)
        or not 1 <= len(series) <= 32
        or any(not isinstance(row, RiskSeries) for row in series)
    ):
        invalid("risk.series")
    if return_kind not in ("simple", "log") or len({row.key for row in series}) != len(series):
        invalid("risk.series.identity")
    if any(_basis(row) != _basis(series[0]) for row in series):
        invalid("risk.series.basis")
    if sum(len(row.intervals) for row in series) > 100000:
        invalid("risk.series.cells")
    ordered = tuple(sorted(series, key=lambda row: row.key))
    with arithmetic():
        candidates = tuple(
            {(item.start_at, item.end_at): _return(item, return_kind) for item in row.intervals}
            for row in ordered
        )
        requested = set().union(*(set(row) for row in candidates))
        if len(requested) > 3660:
            invalid("risk.series.window")
        aligned: list[tuple[datetime, datetime]] = []
        columns: list[list[Decimal]] = [[] for _ in ordered]
        for key in sorted(requested):
            values = tuple(row.get(key) for row in candidates)
            if any(value is None for value in values):
                continue
            aligned.append(key)
            for column, value in zip(columns, values, strict=True):
                assert value is not None
                column.append(value)
        return AlignedRiskSeries(
            tuple(row.key for row in ordered),
            tuple(aligned),
            tuple(tuple(row) for row in columns),
            len(requested),
            len(requested) - len(aligned),
        )


def _metric(
    value: Decimal | None, reason: RiskReason = RiskReason.INSUFFICIENT_HISTORY
) -> RiskMetric:
    return (
        RiskMetric(value=q18(value), reason=None)
        if value is not None
        else RiskMetric(value=None, reason=reason)
    )


def _periodic(annual: Decimal, factor: int, kind: Literal["simple", "log"]) -> Decimal:
    log_rate = (ONE + annual).ln() / factor
    return log_rate if kind == "log" else log_rate.exp() - ONE


def _moments(values: tuple[Decimal, ...]) -> tuple[Decimal, Decimal] | None:
    if len(values) < 20:
        return None
    mean = sum(values, ZERO) / len(values)
    variance = sum(((value - mean) ** 2 for value in values), ZERO) / (len(values) - 1)
    return mean, variance


def _benchmark(
    portfolio: RiskSeries,
    benchmark: RiskSeries | None,
    definition: RiskDefinitionContent,
    factor: int,
) -> tuple[RiskMetric, RiskMetric, int]:
    if benchmark is None:
        missing = _metric(None, RiskReason.BENCHMARK_UNAVAILABLE)
        return missing, missing, 0
    if not isinstance(benchmark, RiskSeries) or benchmark.key == portfolio.key:
        invalid("risk.benchmark")
    if _basis(portfolio) != _basis(benchmark):
        missing = _metric(None, RiskReason.INCOMPATIBLE_BASIS)
        return missing, missing, 0
    aligned = align_series((portfolio, benchmark), definition.return_kind)
    count = len(aligned.boundaries)
    if count < 20:
        return _metric(None), _metric(None), count
    pi, bi = aligned.keys.index(portfolio.key), aligned.keys.index(benchmark.key)
    covariance = sample_covariance(aligned.values)
    if covariance[bi][bi] == ZERO:
        missing = _metric(None, RiskReason.ZERO_DENOMINATOR)
        return missing, missing, count
    beta = covariance[pi][bi] / covariance[bi][bi]
    risk_free = _periodic(definition.annual_risk_free, factor, definition.return_kind)
    excess_portfolio = sum(aligned.values[pi], ZERO) / count - risk_free
    excess_benchmark = sum(aligned.values[bi], ZERO) / count - risk_free
    alpha = factor * (excess_portfolio - beta * excess_benchmark)
    return _metric(beta), _metric(alpha), count


def calculate_risk_statistics(
    portfolio: RiskSeries,
    definition: RiskDefinitionContent,
    *,
    benchmark: RiskSeries | None = None,
) -> RiskSeriesStatistics:
    if not isinstance(portfolio, RiskSeries) or not isinstance(definition, RiskDefinitionContent):
        invalid("risk.definition")
    if (portfolio.calendar_id, portfolio.calendar_version, portfolio.frequency) != (
        definition.calendar_id,
        definition.calendar_version,
        definition.frequency,
    ):
        invalid("risk.definition.basis")
    factor = 252 if definition.frequency == "daily" else 12
    with arithmetic():
        returns = tuple(_return(item, definition.return_kind) for item in portfolio.intervals)
        valid = tuple(value for value in returns if value is not None)
        moments = _moments(valid)
        mean = sigma = annual_sigma = downside = None
        if moments is not None:
            mean, variance = moments
            sigma, annual_sigma = variance.sqrt(), (variance * factor).sqrt()
            mar = _periodic(
                definition.annual_minimum_acceptable_return, factor, definition.return_kind
            )
            downside = (
                factor * sum((min(value - mar, ZERO) ** 2 for value in valid), ZERO) / len(valid)
            ).sqrt()
        beta, alpha, pairs = _benchmark(portfolio, benchmark, definition, factor)
        rolling: list[RiskRollingPoint] = []
        for index, interval in enumerate(portfolio.intervals):
            start = max(0, index + 1 - definition.rolling_window)
            window = tuple(value for value in returns[start : index + 1] if value is not None)
            estimate = _moments(window)
            rolling.append(
                RiskRollingPoint(
                    end_at=interval.end_at,
                    observations=len(window),
                    volatility=_metric((estimate[1] * factor).sqrt() if estimate else None),
                )
            )
        return RiskSeriesStatistics(
            requested_observations=len(returns),
            used_observations=len(valid),
            omitted_observations=len(returns) - len(valid),
            outlier_observations=sum(
                item.simple_return is not None
                and item.simple_return.copy_abs() > ONE
                and item.quality is QualityState.FRESH
                for item in portfolio.intervals
            ),
            mean_periodic_return=_metric(mean),
            volatility_periodic=_metric(sigma),
            volatility_annualized=_metric(annual_sigma),
            downside_annualized=_metric(downside),
            beta=beta,
            alpha_annualized=alpha,
            benchmark_pairs=pairs,
            rolling=tuple(rolling),
        )
