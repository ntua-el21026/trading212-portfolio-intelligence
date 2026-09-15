"""Validate saved scenario money relationships without reselecting source evidence."""

from __future__ import annotations

from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    FloatOperation,
    InvalidOperation,
    Overflow,
    Underflow,
    localcontext,
)
from typing import TYPE_CHECKING

from .enums import QualityState
from .errors import fail_validation

if TYPE_CHECKING:
    from .scenario_result import (
        ScenarioCalculation,
        ScenarioComparison,
        ScenarioComponent,
        ScenarioMoneyMetric,
        ScenarioRatioMetric,
    )

_ZERO = Decimal(0)
_Q18 = Decimal("1e-18")
_TOLERANCE = Decimal("1e-60")
_QUALITY_ORDER = {
    QualityState.FRESH: 0,
    QualityState.STALE: 1,
    QualityState.ESTIMATED: 2,
    QualityState.UNRECONCILED: 3,
    QualityState.PARTIAL: 4,
    QualityState.FAILED: 5,
}
_CONTEXT = Context(
    prec=96,
    rounding=ROUND_HALF_EVEN,
    Emin=-999,
    Emax=999,
    capitals=1,
    clamp=0,
    flags=[],
    traps=[InvalidOperation, DivisionByZero, Overflow, Underflow, FloatOperation],
)


def _amount(value: ScenarioMoneyMetric) -> Decimal | None:
    return None if value.value is None else value.value.amount


def _total(values: tuple[ScenarioMoneyMetric, ...]) -> Decimal | None:
    if any(item.value is None for item in values):
        return None
    return sum((item.value.amount for item in values if item.value is not None), _ZERO)


def _expect(value: ScenarioMoneyMetric, expected: Decimal | None, field: str) -> None:
    if _amount(value) != expected:
        fail_validation("Saved scenario money differs from its retained components.", field=field)


def scenario_minimum_quality(*qualities: QualityState) -> QualityState:
    """A modeled result cannot improve the quality of its contributing evidence."""
    return max((QualityState.ESTIMATED, *qualities), key=_QUALITY_ORDER.__getitem__)


def _quality(value: ScenarioMoneyMetric | ScenarioRatioMetric, *qualities: QualityState) -> None:
    minimum = scenario_minimum_quality(
        *qualities,
        QualityState.PARTIAL if value.value is None else QualityState.ESTIMATED,
    )
    if _QUALITY_ORDER[value.quality] < _QUALITY_ORDER[minimum]:
        fail_validation("Derived scenario quality improves its retained evidence.", field="quality")


def _sum_quality(value: ScenarioMoneyMetric, inputs: tuple[ScenarioMoneyMetric, ...]) -> None:
    _quality(value, *(item.quality for item in inputs))


def _zero_exception(component: ScenarioComponent) -> bool:
    return component.partition == "excluded" or component.money_basis in (
        "zero_pre_value",
        "provably_zero_effect",
    )


def _component_channels(component: ScenarioComponent, pre: Decimal | None) -> None:
    effects = component.effects
    minimum = scenario_minimum_quality(
        component.exposure.quality,
        component.exposure.pre_value.quality,
        *(item.effect_ratio.quality for item in component.sensitivity_uses),
        QualityState.PARTIAL if component.partition == "uncovered" else QualityState.ESTIMATED,
    )
    for name in ("price", "factor", "fx"):
        ratio = getattr(effects, name + "_ratio")
        money = getattr(effects, name)
        _quality(ratio, minimum)
        _quality(money, minimum)
        if ratio.value is not None and not Decimal(-1) <= ratio.value <= Decimal(5):
            fail_validation("Retained scenario channel ratio exceeds its bound.", field=name)
        amount = _amount(money)
        if pre is None:
            _expect(money, None, name)
        elif ratio.value is None:
            _expect(money, _ZERO if _zero_exception(component) else None, name)
        elif amount is None:
            fail_validation("A retained known ratio requires its channel money.", field=name)
        else:
            expected = pre * ratio.value
            # Ratios (notably replay/factor ratios) and money round independently.
            envelope = (pre + 1) * _Q18 / 2
            tolerance = _TOLERANCE * max(Decimal(1), pre, abs(expected), abs(amount))
            if abs(amount - expected) > envelope + tolerance:
                fail_validation(
                    "Scenario channel money differs from its retained ratio.", field=name
                )
    for value in (
        effects.interaction,
        component.post_value,
        component.impact,
        component.rounding_residual,
    ):
        _quality(value, minimum)
    if pre is None:
        _expect(effects.interaction, None, "interaction")


def _interaction(component: ScenarioComponent, mode: str) -> None:
    pre = _amount(component.exposure.pre_value)
    value = component.effects.interaction
    price = component.effects.price_ratio.value
    factor = component.effects.factor_ratio.value
    fx = component.effects.fx_ratio.value
    if price is not None and factor is not None:
        local = 1 + price + factor
        if mode == "compounded":
            tolerance = _TOLERANCE * max(Decimal(1), abs(local))
            if local < -_Q18 - tolerance:
                fail_validation(
                    "Retained scenario local multiplier is negative.", field="multiplier"
                )
        elif fx is not None:
            total = local + fx
            tolerance = _TOLERANCE * max(Decimal(1), abs(total))
            if total < -3 * _Q18 / 2 - tolerance:
                fail_validation(
                    "Retained scenario combined multiplier is negative.", field="multiplier"
                )
    if pre is None:
        _expect(value, None, "interaction")
        return
    if mode == "first_order" or _zero_exception(component):
        _expect(value, _ZERO, "interaction")
        return
    if price is None or factor is None or fx is None:
        _expect(value, None, "interaction")
        return
    amount = _amount(value)
    if amount is None:
        fail_validation("Known scenario channels require interaction money.", field="interaction")
    local = price + factor
    expected = pre * local * fx
    half = _Q18 / 2
    # |d(local)| <= 2h, |d(fx)| <= h, followed by one money rounding.
    envelope = pre * (abs(local) * half + abs(fx) * 2 * half + 2 * half * half) + half
    tolerance = _TOLERANCE * max(Decimal(1), pre, abs(expected), abs(amount))
    if abs(amount - expected) > envelope + tolerance:
        fail_validation(
            "Scenario interaction differs from its retained ratios.", field="interaction"
        )


def validate_scenario_component_money(component: ScenarioComponent) -> None:
    pre, post = _amount(component.exposure.pre_value), _amount(component.post_value)
    if (pre is not None and pre < 0) or (post is not None and post < 0):
        fail_validation("Scenario wealth cannot be negative.", field="component")
    with localcontext(_CONTEXT):
        _component_channels(component, pre)
        if post is None:
            _expect(component.rounding_residual, None, "rounding_residual")
            return
        if pre is None:
            fail_validation("A complete scenario value requires original money.", field="pre")
        _expect(component.impact, post - pre, "impact")
        effects = component.effects
        channels = (effects.price, effects.factor, effects.fx, effects.interaction)
        total = _total(channels)
        if total is None:
            fail_validation("Complete scenario money requires every channel.", field="effects")
        residual = post - pre - total
        _expect(component.rounding_residual, residual, "rounding_residual")
        # One rounded post amount and four independently rounded channel effects.
        # Original Q18 money is never reconstructed from the published ratios.
        if abs(residual) > 5 * _Q18:
            fail_validation("Scenario rounding residual exceeds its envelope.", field="residual")
        if _zero_exception(component) and (
            post != pre or any(_amount(item) != 0 for item in channels)
        ):
            fail_validation("Unchanged scenario money has nonzero effects.", field="effects")


def validate_scenario_summary_money(result: ScenarioCalculation) -> None:
    with localcontext(_CONTEXT):
        rows = result.components
        summary = result.summary
        for component in rows:
            _interaction(component, result.definition.mode)
        pre = _total(tuple(item.exposure.pre_value for item in rows))
        post = _total(tuple(item.post_value for item in rows))
        _expect(summary.terminal_pre_value, pre, "terminal_pre_value")
        _expect(summary.post_value, post, "post_value")
        _sum_quality(summary.terminal_pre_value, tuple(item.exposure.pre_value for item in rows))
        _sum_quality(summary.post_value, tuple(item.post_value for item in rows))
        impact = None if pre is None or post is None else post - pre
        _expect(summary.impact, impact, "impact")
        _quality(summary.impact, summary.terminal_pre_value.quality, summary.post_value.quality)
        components_impact = _total(tuple(item.impact for item in rows))
        _expect(
            summary.component_sum_residual,
            None if impact is None or components_impact is None else impact - components_impact,
            "component_sum_residual",
        )
        _quality(
            summary.component_sum_residual,
            summary.impact.quality,
            *(item.impact.quality for item in rows),
        )
        for kind in ("covered", "uncovered", "excluded"):
            selected = tuple(item for item in rows if item.partition == kind)
            _expect(
                getattr(summary, kind + "_pre_value"),
                _total(tuple(item.exposure.pre_value for item in selected)),
                kind + "_pre_value",
            )
            _sum_quality(
                getattr(summary, kind + "_pre_value"),
                tuple(item.exposure.pre_value for item in selected),
            )
            if kind != "uncovered":
                _expect(
                    getattr(summary, kind + "_post_value"),
                    _total(tuple(item.post_value for item in selected)),
                    kind + "_post_value",
                )
                _sum_quality(
                    getattr(summary, kind + "_post_value"),
                    tuple(item.post_value for item in selected),
                )
        _expect(
            summary.provably_unchanged_uncovered_value,
            _total(
                tuple(
                    item.post_value
                    for item in rows
                    if item.partition == "uncovered"
                    and item.money_basis in ("zero_pre_value", "provably_zero_effect")
                )
            ),
            "provably_unchanged_uncovered_value",
        )
        _sum_quality(
            summary.provably_unchanged_uncovered_value,
            tuple(
                item.post_value
                for item in rows
                if item.partition == "uncovered"
                and item.money_basis in ("zero_pre_value", "provably_zero_effect")
            ),
        )
        _expect(
            summary.rounding_residual,
            _total(tuple(item.rounding_residual for item in rows)),
            "rounding_residual",
        )
        _sum_quality(summary.rounding_residual, tuple(item.rounding_residual for item in rows))
        for channel in ("price", "factor", "fx", "interaction"):
            amount = _total(tuple(getattr(item.effects, channel) for item in rows))
            _expect(getattr(summary.effects, channel), amount, channel)
            _sum_quality(
                getattr(summary.effects, channel),
                tuple(getattr(item.effects, channel) for item in rows),
            )
            if channel != "interaction":
                ratio = getattr(summary.effects, channel + "_ratio")
                expected = (
                    None
                    if pre is None or pre == 0 or amount is None
                    else (amount / pre).quantize(_Q18)
                )
                if ratio.value != expected:
                    fail_validation("Scenario aggregate ratio differs.", field=channel + "_ratio")
                _quality(
                    ratio,
                    summary.terminal_pre_value.quality,
                    getattr(summary.effects, channel).quality,
                )
        upstream = _amount(result.upstream_portfolio_value)
        _expect(
            result.upstream_partition_difference,
            None if pre is None or upstream is None else pre - upstream,
            "upstream_partition_difference",
        )
        _quality(
            result.upstream_partition_difference,
            summary.terminal_pre_value.quality,
            result.upstream_portfolio_value.quality,
        )


def validate_scenario_comparison_money(result: ScenarioComparison) -> None:
    with localcontext(_CONTEXT):
        for delta in (
            result.post_value,
            result.impact,
            *(item.post_value for item in result.components),
            *(item.impact for item in result.components),
        ):
            before, after = delta.before.value, delta.after.value
            expected = None
            if result.compatible and before is not None and after is not None:
                if before.currency != after.currency:
                    fail_validation("Comparable scenario currencies differ.", field="currency")
                if (
                    delta.difference.value is None
                    or delta.difference.value.currency != before.currency
                ):
                    fail_validation("Scenario difference currency differs.", field="currency")
                expected = after.amount - before.amount
            _expect(delta.difference, expected, "difference")
            _quality(delta.difference, delta.before.quality, delta.after.quality)
