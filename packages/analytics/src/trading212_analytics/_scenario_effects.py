"""Finite-precision stress cash effects with an explicit publication residual."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from trading212_domain.errors import fail_validation

from ._premium_numeric import ONE, ZERO, arithmetic, finite, q18


@dataclass(frozen=True, slots=True)
class ScenarioValueFlow:
    price: Decimal | None
    factor: Decimal | None
    fx: Decimal | None
    interaction: Decimal | None
    post: Decimal | None
    impact: Decimal | None
    rounding_residual: Decimal | None


def scenario_value_flow(
    pre: Decimal | None,
    price: Decimal | None,
    factor: Decimal | None,
    fx: Decimal | None,
    mode: Literal["first_order", "compounded"],
    *,
    proved_unchanged: bool = False,
) -> ScenarioValueFlow:
    """Unknown channels remain absent unless the caller proves unchanged money.

    The proof belongs to the complete selector/source treatment, including every
    possible lower-priority rule. This function never substitutes a zero ratio.
    """
    if mode not in ("first_order", "compounded") or type(proved_unchanged) is not bool:
        fail_validation("Unsupported scenario effect policy.", field="mode")
    for name, value in (("price", price), ("factor", factor), ("fx", fx)):
        if value is not None and not Decimal("-1") <= finite(value, name) <= Decimal("5"):
            fail_validation("Scenario channel effect exceeds its bound.", field=name)
    if pre is not None and finite(pre, "pre") < ZERO:
        fail_validation("Scenario original money cannot be negative.", field="pre")
    if proved_unchanged and any(
        value is not None and value != ZERO for value in (price, factor, fx)
    ):
        fail_validation("An unchanged effect proof conflicts with a known channel.", field="shocks")
    with arithmetic():
        local = None if price is None or factor is None else ONE + price + factor
        if mode == "compounded" and local is not None and local < ZERO:
            fail_validation("Scenario local multiplier cannot be negative.", field="shocks")
        total = None if local is None or fx is None else local + fx
        if mode == "first_order" and total is not None and total < ZERO:
            fail_validation("Scenario combined multiplier cannot be negative.", field="shocks")
        if pre is None:
            return ScenarioValueFlow(None, None, None, None, None, None, None)
        if pre == ZERO or proved_unchanged:
            return ScenarioValueFlow(ZERO, ZERO, ZERO, ZERO, q18(pre), ZERO, ZERO)
        price_money = None if price is None else q18(pre * price)
        factor_money = None if factor is None else q18(pre * factor)
        fx_money = None if fx is None else q18(pre * fx)
        interaction = (
            ZERO
            if mode == "first_order"
            else (None if local is None or fx is None else q18(pre * (local - ONE) * fx))
        )
        if local is None or fx is None:
            return ScenarioValueFlow(
                price_money, factor_money, fx_money, interaction, None, None, None
            )
        multiplier = total if mode == "first_order" else local * (ONE + fx)
        assert multiplier is not None
        post = q18(pre * multiplier)
        impact = q18(post - pre)
        assert (
            price_money is not None
            and factor_money is not None
            and fx_money is not None
            and interaction is not None
        )
        residual = q18(impact - price_money - factor_money - fx_money - interaction)
        return ScenarioValueFlow(
            price_money, factor_money, fx_money, interaction, post, impact, residual
        )
