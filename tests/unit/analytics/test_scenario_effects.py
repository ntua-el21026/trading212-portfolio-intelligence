"""Independent stress-effect references and unavailable/publication boundaries."""

from decimal import ROUND_DOWN, Decimal, localcontext
from fractions import Fraction
from typing import Literal

import pytest
from trading212_analytics._scenario_effects import scenario_value_flow
from trading212_domain.errors import DomainError

D = Decimal


def amount(value: Decimal | None) -> Decimal:
    assert value is not None
    return value


@pytest.mark.parametrize("mode,expected", [("compounded", "82.8"), ("first_order", "82")])
def test_two_position_reference_reconciles_all_channels(
    mode: Literal["first_order", "compounded"], expected: str
) -> None:
    a = scenario_value_flow(D(60), D("-.2"), D(0), D("-.1"), mode)
    b = scenario_value_flow(D(40), D(".1"), D(0), D("-.1"), mode)
    assert amount(a.post) + amount(b.post) == D(expected)
    assert amount(a.price) + amount(b.price) == D(-8)
    assert amount(a.fx) + amount(b.fx) == D(-10)
    assert amount(a.interaction) + amount(b.interaction) == (
        D(".8") if mode == "compounded" else D(0)
    )
    assert a.rounding_residual == b.rounding_residual == D(0)


@pytest.mark.parametrize("mode", ["first_order", "compounded"])
def test_rational_reference_for_separate_sourced_rate_effect(
    mode: Literal["first_order", "compounded"],
) -> None:
    # Rate coefficient -2 per absolute unit, shock +.01, independent of price.
    pre, price, factor, fx = Fraction(125, 2), Fraction(3, 25), Fraction(-2, 100), Fraction(-1, 20)
    expected = (
        pre * (1 + price + factor + fx)
        if mode == "first_order"
        else pre * (1 + price + factor) * (1 + fx)
    )
    result = scenario_value_flow(D("62.5"), D(".12"), D("-.02"), D("-.05"), mode)
    assert Fraction(amount(result.post)) == expected
    assert Fraction(amount(result.price)) == pre * price
    assert Fraction(amount(result.factor)) == pre * factor
    assert Fraction(amount(result.fx)) == pre * fx
    assert result.rounding_residual == 0


def test_unknown_factor_preserves_only_supported_channel_facts() -> None:
    value = scenario_value_flow(D(60), D("-.2"), None, D("-.1"), "compounded")
    assert value.price == D(-12) and value.fx == D(-6)
    assert value.factor is value.interaction is value.post is value.impact is None
    assert value.rounding_residual is None


def test_unknown_original_value_is_not_zero_even_with_zero_assumptions() -> None:
    value = scenario_value_flow(None, D(0), D(0), D(0), "first_order")
    assert value.price is value.factor is value.fx is value.interaction is None
    assert value.post is value.impact is value.rounding_residual is None


def test_exact_zero_and_proved_unchanged_keep_money_available_without_unknown_ratios() -> None:
    zero = scenario_value_flow(D(0), None, None, None, "compounded")
    assert zero.post == zero.impact == zero.rounding_residual == 0
    unchanged = scenario_value_flow(D(40), None, D(0), D(0), "compounded", proved_unchanged=True)
    assert unchanged.post == D(40) and unchanged.impact == 0
    with pytest.raises(DomainError):
        scenario_value_flow(D(40), D(".1"), D(0), None, "compounded", proved_unchanged=True)


def test_channel_rounding_residual_is_separate_from_economic_interaction() -> None:
    value = scenario_value_flow(D(".1"), D("5e-18"), D(0), D("5e-18"), "compounded")
    assert value.post == D(".100000000000000001")
    assert value.price == value.fx == value.factor == value.interaction == 0
    assert value.impact == value.rounding_residual == D("1e-18")


def test_compounded_total_loss_is_supported_but_negative_first_order_fails() -> None:
    assert scenario_value_flow(D(100), D(-1), D(0), D(-1), "compounded").post == 0
    with pytest.raises(DomainError):
        scenario_value_flow(D(100), D(-1), D(0), D(-1), "first_order")
    with pytest.raises(DomainError):
        scenario_value_flow(D(0), D(-1), D(-1), None, "compounded")


@pytest.mark.parametrize("field", ["price", "factor", "fx"])
def test_channel_bounds_and_nonfinite_values_fail(field: str) -> None:
    for amount in (D("5.000000000000000001"), D("-1.000000000000000001"), D("NaN"), D("Infinity")):
        args = {"price": D(0), "factor": D(0), "fx": D(0)}
        args[field] = amount
        with pytest.raises(DomainError):
            scenario_value_flow(D(1), args["price"], args["factor"], args["fx"], "compounded")


def test_hostile_decimal_context_does_not_change_output_or_caller_state() -> None:
    expected = scenario_value_flow(D("62.5"), D(".12"), D("-.02"), D("-.05"), "compounded")
    with localcontext() as caller:
        caller.prec = 3
        caller.rounding = ROUND_DOWN
        before = caller.copy()
        actual = scenario_value_flow(D("62.5"), D(".12"), D("-.02"), D("-.05"), "compounded")
        assert actual == expected
        assert caller.prec == before.prec and caller.rounding == before.rounding
        assert caller.flags == before.flags


def test_public_numeric_overflow_fails_instead_of_clipping() -> None:
    with pytest.raises(DomainError):
        scenario_value_flow(D("99999999999999999999"), D(5), D(0), D(5), "compounded")
