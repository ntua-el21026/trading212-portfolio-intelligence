"""Projection distributions and goal analysis from retained canonical path values."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

from trading212_domain.errors import DomainError
from trading212_domain.projection import PROJECTION_PERCENTILES, ProjectionGoal
from trading212_domain.projection_result import (
    ProjectionDistributionPoint,
    ProjectionGoalResult,
    ProjectionHistogram,
    ProjectionHistogramBin,
    ProjectionPath,
    ProjectionQuantiles,
)
from trading212_domain.sources import source_integer, source_tuple

from ._premium_numeric import ONE, Q18, ZERO, arithmetic, finite, invalid, q18

_WILSON_Z = Decimal("1.9599639845400542355245944305205515279555500778695")


def nearest_rank(values: tuple[tuple[int, Decimal], ...], probability: Decimal) -> Decimal:
    """Return an existing value; stable ties use absolute path identity."""
    if not isinstance(values, tuple) or not 1 <= len(values) <= 4096:
        invalid("projection.quantile")
    finite(probability)
    if not ZERO <= probability <= ONE:
        invalid("projection.quantile.probability")
    seen: set[int] = set()
    for pair in values:
        if not isinstance(pair, tuple) or len(pair) != 2:
            invalid("projection.quantile.pair")
        index, value = pair
        source_integer(index, "path.index", 0, 4095)
        finite(value)
        if index in seen:
            invalid("projection.quantile.duplicate")
        seen.add(index)
    ordered = sorted(values, key=lambda pair: (pair[1], pair[0]))
    with arithmetic():
        rank = (
            0
            if probability == ZERO
            else int((probability * len(values)).to_integral_value(rounding=ROUND_CEILING)) - 1
        )
    return ordered[rank][1]


def _quantiles(values: tuple[tuple[int, Decimal], ...]) -> ProjectionQuantiles:
    return ProjectionQuantiles(
        probabilities=PROJECTION_PERCENTILES,
        values=tuple(nearest_rank(values, p) for p in PROJECTION_PERCENTILES),
    )


def histogram(values: tuple[tuple[int, Decimal], ...]) -> ProjectionHistogram:
    low, high = nearest_rank(values, ZERO), nearest_rank(values, ONE)
    if low < ZERO:
        invalid("projection.histogram.negative")
    if low == high:
        return ProjectionHistogram(
            observed_minimum=low,
            observed_maximum=high,
            bins=(
                ProjectionHistogramBin(
                    lower=low, upper=high, upper_inclusive=True, count=len(values)
                ),
            ),
        )
    with arithmetic():
        # Enclose the range with equal Q18 widths; prime spans must not collapse bins.
        count = min(20, len(values))
        while True:
            raw_width = (high - low) / count
            if raw_width < Q18 and count > 1:
                count -= 1
                continue
            width = raw_width.quantize(Q18, rounding=ROUND_CEILING)
            try:
                q18(low + count * width)
            except DomainError:
                if count == 1:
                    raise
                count -= 1
                continue
            break
        counts = [0] * count
        for _, value in values:
            index = min(count - 1, int((value - low) / width))
            counts[index] += 1
        bins = tuple(
            ProjectionHistogramBin(
                lower=q18(low + width * i),
                upper=q18(low + width * (i + 1)),
                upper_inclusive=i == count - 1,
                count=counts[i],
            )
            for i in range(count)
        )
        return ProjectionHistogram(observed_minimum=low, observed_maximum=high, bins=bins)


def wilson_interval(successes: int, paths: int) -> tuple[Decimal, Decimal]:
    source_integer(paths, "paths", 1, 4096)
    source_integer(successes, "successes", 0, paths)
    with arithmetic():
        n = Decimal(paths)
        probability = Decimal(successes) / n
        square = _WILSON_Z * _WILSON_Z
        denominator = ONE + square / n
        center = (probability + square / (2 * n)) / denominator
        radius = (
            _WILSON_Z
            * (probability * (ONE - probability) / n + square / (4 * n * n)).sqrt()
            / denominator
        )
        # Exact all/none endpoints avoid representing computational cancellation as mass.
        low = ZERO if successes == 0 else center - radius
        high = ONE if successes == paths else center + radius
        return q18(low), q18(high)


def summarize_paths(paths: tuple[ProjectionPath, ...]) -> tuple[ProjectionDistributionPoint, ...]:
    source_tuple(paths, ProjectionPath, "paths", 4096)
    if not paths or tuple(p.index for p in paths) != tuple(range(len(paths))):
        invalid("projection.paths.complete")
    months = tuple(point.month for point in paths[0].points)
    if any(
        tuple(p.month for p in path.points) != months
        or path.reporting_currency != paths[0].reporting_currency
        for path in paths
    ):
        invalid("projection.paths.basis")
    result: list[ProjectionDistributionPoint] = []
    with arithmetic():
        for ordinal, month in enumerate(months):
            nominal = tuple((p.index, p.points[ordinal].nominal) for p in paths)
            real = tuple((p.index, p.points[ordinal].real) for p in paths)
            result.append(
                ProjectionDistributionPoint(
                    month=month,
                    nominal_mean=q18(sum((v for _, v in nominal), ZERO) / len(paths)),
                    real_mean=q18(sum((v for _, v in real), ZERO) / len(paths)),
                    nominal=_quantiles(nominal),
                    real=_quantiles(real),
                    funding_failed_paths=sum(p.points[ordinal].funding_failed for p in paths),
                )
            )
    return tuple(result)


def analyze_goal(paths: tuple[ProjectionPath, ...], goal: ProjectionGoal) -> ProjectionGoalResult:
    source_tuple(paths, ProjectionPath, "paths", 4096)
    if (
        not isinstance(goal, ProjectionGoal)
        or not paths
        or tuple(p.index for p in paths) != tuple(range(len(paths)))
    ):
        invalid("projection.goal.paths")
    if any(
        p.reporting_currency != goal.target.currency or p.points[-1].month != goal.months
        for p in paths
    ):
        invalid("projection.goal.basis")
    successes = 0
    shortfalls: list[tuple[int, Decimal]] = []
    with arithmetic():
        for path in paths:
            point = path.points[-1]
            amount = point.nominal if goal.basis == "nominal" else point.real
            successes += amount >= goal.target.amount and not point.funding_failed
            shortfalls.append((path.index, q18(max(ZERO, goal.target.amount - amount))))
        probability = q18(Decimal(successes) / len(paths))
        low, high = wilson_interval(successes, len(paths))
        return ProjectionGoalResult(
            goal_version_id=goal.version_id,
            basis=goal.basis,
            target=goal.target.amount,
            paths=len(paths),
            successes=successes,
            probability=probability,
            interval_low=low,
            interval_high=high,
            probability_objective=goal.probability_objective,
            objective_met=probability >= goal.probability_objective,
            mean_shortfall=q18(sum((v for _, v in shortfalls), ZERO) / len(paths)),
            shortfalls=_quantiles(tuple(shortfalls)),
            funding_failed_paths=sum(p.points[-1].funding_failed for p in paths),
        )
