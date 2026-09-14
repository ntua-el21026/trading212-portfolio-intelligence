"""Historical and lognormal tail estimates with explicit loss/sample conventions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Literal

from ._premium_numeric import (
    CONFIDENCES,
    ONE,
    ZERO,
    arithmetic,
    finite,
    invalid,
    normal_cdf,
    normal_quantile,
)


@dataclass(frozen=True, slots=True)
class TailEstimate:
    method: Literal["historical", "parametric_lognormal"]
    confidence: Decimal
    horizon: int
    observations: int
    tail_mass: Decimal | None
    value_at_risk: Decimal | None
    expected_shortfall: Decimal | None
    reason: Literal["insufficient_history", "insufficient_tail", "unsupported_parametric"] | None


def _inputs(
    returns: tuple[Decimal | None, ...],
    confidence: Decimal,
    horizon: int,
    frequency: Literal["daily", "monthly"],
) -> None:
    if not isinstance(returns, tuple) or len(returns) > 3661:
        invalid("premium.tail.series")
    finite(confidence)
    if confidence not in CONFIDENCES:
        invalid("premium.tail.confidence")
    if (
        frequency not in ("daily", "monthly")
        or type(horizon) is not int
        or not 1 <= horizon <= (20 if frequency == "daily" else 12)
    ):
        invalid("premium.tail.horizon")
    for value in returns:
        if value is not None:
            finite(value, "premium.tail.return")


def historical_tail(
    simple_returns: tuple[Decimal | None, ...],
    confidence: Decimal,
    horizon: int,
    frequency: Literal["daily", "monthly"],
) -> TailEstimate:
    """None marks a missing interval; no horizon window can cross one."""
    _inputs(simple_returns, confidence, horizon, frequency)
    with arithmetic():
        for value in simple_returns:
            if value is not None and value < -ONE:
                invalid("premium.tail.simple_return")
        losses: list[Decimal] = []
        for start in range(len(simple_returns) - horizon + 1):
            gross = ONE
            for value in simple_returns[start : start + horizon]:
                if value is None:
                    break
                gross *= ONE + value
            else:
                losses.append(ONE - gross)
        losses.sort()
        count = len(losses)
        mass = (ONE - confidence) * count
        if count < 20 or mass < 5:
            return TailEstimate(
                "historical",
                confidence,
                horizon,
                count,
                mass,
                None,
                None,
                "insufficient_history" if count < 20 else "insufficient_tail",
            )
        rank = int((confidence * count).to_integral_value(rounding=ROUND_CEILING))
        whole = int(mass)
        tail_sum = sum(losses[count - whole :], ZERO)
        fraction = mass - whole
        if fraction:
            tail_sum += fraction * losses[count - whole - 1]
        return TailEstimate(
            "historical", confidence, horizon, count, mass, losses[rank - 1], tail_sum / mass, None
        )


def parametric_tail(
    log_returns: tuple[Decimal | None, ...],
    confidence: Decimal,
    horizon: int,
    frequency: Literal["daily", "monthly"],
) -> TailEstimate:
    _inputs(log_returns, confidence, horizon, frequency)
    values = tuple(value for value in log_returns if value is not None)
    count = len(values)
    if count < 20:
        return TailEstimate(
            "parametric_lognormal",
            confidence,
            horizon,
            count,
            None,
            None,
            None,
            "insufficient_history",
        )
    with arithmetic():
        mean = sum(values, ZERO) / count
        deviation = (sum(((value - mean) ** 2 for value in values), ZERO) / (count - 1)).sqrt()
        if mean.copy_abs() > ONE or deviation > ONE:
            return TailEstimate(
                "parametric_lognormal",
                confidence,
                horizon,
                count,
                None,
                None,
                None,
                "unsupported_parametric",
            )
        m, s = mean * horizon, deviation * Decimal(horizon).sqrt()
        if s == ZERO:
            loss = ONE - m.exp()
            return TailEstimate(
                "parametric_lognormal", confidence, horizon, count, None, loss, loss, None
            )
        z = normal_quantile(confidence)
        argument = -z - s
        if argument.copy_abs() > 8:
            return TailEstimate(
                "parametric_lognormal",
                confidence,
                horizon,
                count,
                None,
                None,
                None,
                "unsupported_parametric",
            )
        var = ONE - (m - s * z).exp()
        es = ONE - (m + s * s / 2).exp() * normal_cdf(argument) / (ONE - confidence)
        return TailEstimate("parametric_lognormal", confidence, horizon, count, None, var, es, None)
