"""Cross-record validation of retained projection evidence, without path simulation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import (
    ROUND_CEILING,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    FloatOperation,
    InvalidOperation,
    Overflow,
    Underflow,
    localcontext,
)
from typing import TYPE_CHECKING

from .errors import fail_validation
from .projection import PROJECTION_PERCENTILES, ProjectionInput, ProjectionVariant
from .values import exact_decimal

if TYPE_CHECKING:
    from .projection_result import (
        ProjectionGoalResult,
        ProjectionHistogram,
        ProjectionPath,
        ProjectionPoint,
        ProjectionVariantResult,
    )

_ZERO = Decimal(0)
_ONE = Decimal(1)
_Q18 = Decimal("1e-18")
_TOLERANCE = Decimal("1e-60")
_MAXIMUM = Decimal("99999999999999999999.999999999999999999")
_WILSON_Z = Decimal("1.9599639845400542355245944305205515279555500778695")


@contextmanager
def _arithmetic() -> Iterator[None]:
    # Keep the same immutable profile as the kernel, independent of ambient traps.
    context = Context(
        prec=96,
        rounding=ROUND_HALF_EVEN,
        Emin=-999,
        Emax=999,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow, Underflow, FloatOperation],
    )
    try:
        with localcontext(context):
            yield
    except DecimalException:
        fail_validation("Retained projection arithmetic is invalid.", field="projection.result")


def _q18(value: Decimal) -> Decimal:
    rounded = value.quantize(_Q18)
    return exact_decimal(rounded.copy_abs() if rounded.is_zero() else rounded)


def validate_point_envelopes(point: ProjectionPoint) -> None:
    with _arithmetic():
        if (
            abs(point.allocation_residual) > (len(point.assets) + 1) * _Q18
            or abs(point.withdrawal_residual) > 3 * _Q18
        ):
            fail_validation("Retained rounding residual exceeds its envelope.", field="residual")


def validate_wealth_envelope(initial: Decimal, point: ProjectionPoint) -> None:
    with _arithmetic():
        scale = max(
            _ONE,
            initial,
            point.nominal,
            point.contributions,
            point.withdrawals_funded,
            abs(point.investment_effect),
            point.fees,
            point.tax_drag,
        )
        if abs(point.wealth_residual) > 8 * _Q18 + _TOLERANCE * scale:
            fail_validation(
                "Retained wealth residual exceeds its envelope.", field="wealth_residual"
            )


def validate_projection_path_basis(
    inputs: ProjectionInput, path: ProjectionPath, variant: ProjectionVariant
) -> None:
    """Check deterministic input relationships; never regenerate sampled returns."""
    with _arithmetic():
        expected_initial = tuple(
            (a.key, _q18(inputs.initial.value.amount * a.weight)) for a in inputs.assumptions.assets
        )
        if tuple((a.key, a.value) for a in path.points[0].assets) != expected_initial:
            fail_validation("Initial retained allocation differs from its weights.", field="assets")
        schedule = inputs.schedule
        base = schedule.base_monthly.amount
        if variant == "contribution_delta":
            if inputs.sensitivity is None:
                fail_validation("Projection sensitivity is missing.", field="variant")
            base += inputs.sensitivity.contribution_delta.amount
        incoming: dict[int, Decimal] = {}
        requested: dict[int, Decimal] = {}
        for entry in schedule.entries:
            target = incoming if entry.kind == "lump_sum" else requested
            target[entry.month] = target.get(entry.month, _ZERO) + entry.value.amount
        if (
            path.first_unpaid_month is not None
            and requested.get(path.first_unpaid_month, _ZERO) <= _ZERO
        ):
            fail_validation(
                "First unpaid month requires a positive scheduled withdrawal.",
                field="first_unpaid_month",
            )
        retained = {point.month: point for point in path.points}
        contributions = withdrawals = _ZERO
        inflation_log = (_ONE + inputs.assumptions.annual_inflation).ln()
        for month in range(inputs.months + 1):
            if month:
                year = (month - 1) // 12
                growth = _ONE if year == 0 else (_ONE + schedule.annual_growth) ** year
                recurring = _ZERO if month in schedule.paused_months else base * growth
                contributions += recurring + incoming.get(month, _ZERO)
                withdrawals += requested.get(month, _ZERO)
            point = retained.get(month)
            if point is None:
                continue
            if (
                point.contributions != _q18(contributions)
                or point.withdrawals_requested != _q18(withdrawals)
                or (inputs.assumptions.annual_fee == 0 and point.fees != 0)
                or (not inputs.assumptions.annual_tax_drag and point.tax_drag != 0)
            ):
                fail_validation("Retained flows differ from the pinned model.", field="points")
            if inputs.assumptions.annual_inflation == 0:
                if point.real != point.nominal:
                    fail_validation("Zero-inflation wealth bases differ.", field="real")
                continue
            factor = (inflation_log * month / 12).exp()
            # Nominal and real were rounded independently from one unrounded wealth.
            # Comparing q18(nominal/factor) would reject legitimate double-rounding ties.
            residual = point.nominal - point.real * factor
            envelope = (_Q18 / 2) * (_ONE + factor)
            tolerance = _TOLERANCE * max(_ONE, point.nominal, point.real * factor)
            if abs(residual) > envelope + tolerance:
                fail_validation(
                    "Retained real wealth differs from declared inflation.", field="real"
                )


def _quantiles(values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    ordered = sorted(values)
    return tuple(
        ordered[int((p * len(values)).to_integral_value(rounding=ROUND_CEILING)) - 1]
        for p in PROJECTION_PERCENTILES
    )


def _validate_histogram(histogram: ProjectionHistogram, values: tuple[Decimal, ...]) -> None:
    low, high = min(values), max(values)
    edges: tuple[tuple[Decimal, Decimal], ...]
    if (histogram.observed_minimum, histogram.observed_maximum) != (low, high):
        fail_validation("Histogram extrema differ from retained paths.", field="histogram")
    if low == high:
        edges = ((low, high),)
    else:
        count = min(20, len(values))
        while True:
            raw_width = (high - low) / count
            width = raw_width.quantize(_Q18, rounding=ROUND_CEILING)
            if count > 1 and (raw_width < _Q18 or low + count * width > _MAXIMUM):
                count -= 1
                continue
            edges = tuple((low + i * width, low + (i + 1) * width) for i in range(count))
            break
    if tuple((item.lower, item.upper) for item in histogram.bins) != edges:
        fail_validation("Histogram boundaries differ from the canonical rule.", field="histogram")
    for item in histogram.bins:
        count = sum(
            item.lower <= value
            and (value < item.upper or (item.upper_inclusive and value == item.upper))
            for value in values
        )
        if item.count != count:
            fail_validation("Histogram membership differs from retained paths.", field="histogram")


def _validate_goal(goal: ProjectionGoalResult, paths: tuple[ProjectionPath, ...]) -> None:
    values = tuple(
        p.points[-1].nominal if goal.basis == "nominal" else p.points[-1].real for p in paths
    )
    shortfalls = tuple(max(_ZERO, goal.target - value) for value in values)
    probability = Decimal(goal.successes) / len(paths)
    n, z = Decimal(len(paths)), _WILSON_Z
    square = z * z
    denominator = _ONE + square / n
    center = (probability + square / (2 * n)) / denominator
    radius = (
        z * (probability * (_ONE - probability) / n + square / (4 * n * n)).sqrt() / denominator
    )
    low = _ZERO if goal.successes == 0 else _q18(center - radius)
    high = _ONE if goal.successes == len(paths) else _q18(center + radius)
    if (
        goal.probability != _q18(probability)
        or (goal.interval_low, goal.interval_high) != (low, high)
        or goal.mean_shortfall != _q18(sum(shortfalls, _ZERO) / len(paths))
        or goal.shortfalls.values != _quantiles(shortfalls)
    ):
        fail_validation("Goal statistics differ from retained paths.", field="goal")


def validate_projection_summaries(result: ProjectionVariantResult) -> None:
    with _arithmetic():
        months = tuple(p.month for p in result.paths[0].points)
        if any(
            tuple(p.month for p in path.points) != months
            or path.reporting_currency != result.paths[0].reporting_currency
            for path in result.paths
        ):
            fail_validation("Summary path bases differ.", field="paths")
        for ordinal, point in enumerate(result.distributions):
            nominal = tuple(p.points[ordinal].nominal for p in result.paths)
            real = tuple(p.points[ordinal].real for p in result.paths)
            if (
                point.nominal_mean != _q18(sum(nominal, _ZERO) / len(nominal))
                or point.real_mean != _q18(sum(real, _ZERO) / len(real))
                or point.nominal.values != _quantiles(nominal)
                or point.real.values != _quantiles(real)
                or point.funding_failed_paths
                != sum(p.points[ordinal].funding_failed for p in result.paths)
            ):
                fail_validation(
                    "Distribution statistics differ from retained paths.", field="distributions"
                )
        _validate_histogram(
            result.nominal_histogram, tuple(p.points[-1].nominal for p in result.paths)
        )
        _validate_histogram(result.real_histogram, tuple(p.points[-1].real for p in result.paths))
        if result.goal is not None:
            _validate_goal(result.goal, result.paths)
