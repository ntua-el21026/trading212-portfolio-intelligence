from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from trading212_analytics.alerts import compare_alert_basis, direct_concentration_observation
from trading212_domain import alerts as a
from trading212_domain.values import Money

from tests.unit.analytics.alert_factories import EUR, context, predicate

pytestmark = pytest.mark.property


@given(
    numerator=st.integers(0, 10**180),
    denominator=st.integers(1, 10**180),
    threshold_coefficient=st.integers(0, 10**18),
    operator=st.sampled_from(tuple(a.AlertComparison)),
)
@settings(max_examples=120, deadline=None)
def test_xray_comparison_matches_fraction_oracle_without_ambient_precision(
    numerator: int, denominator: int, threshold_coefficient: int, operator: a.AlertComparison
) -> None:
    basis = a.AlertRatioBasis(numerator=Decimal(numerator), denominator=Decimal(denominator))
    threshold = Decimal(f"{threshold_coefficient // 10**18}.{threshold_coefficient % 10**18:018d}")
    exact = Fraction(numerator, denominator)
    target = Fraction(threshold_coefficient, 10**18)
    expected = {
        a.AlertComparison.GT: exact > target,
        a.AlertComparison.GTE: exact >= target,
        a.AlertComparison.LT: exact < target,
        a.AlertComparison.LTE: exact <= target,
        a.AlertComparison.EQ: exact == target,
    }[operator]
    with localcontext() as ambient:
        ambient.prec = 2
        assert compare_alert_basis(basis, threshold, operator) is expected


@given(
    amounts=st.lists(st.integers(0, 10**12), min_size=1, max_size=50),
    cash=st.integers(1, 10**12),
    include_cash=st.booleans(),
)
@settings(max_examples=60, deadline=None)
def test_direct_hhi_full_universe_matches_independent_quantized_fraction(
    amounts: list[int], cash: int, include_cash: bool
) -> None:
    denominator = sum(amounts) + cash
    selected = amounts + ([cash] if include_cash else [])
    expected = (
        Fraction(sum(value * value for value in selected), denominator * denominator) * 10**18
    )
    coefficient, remainder = divmod(expected.numerator, expected.denominator)
    if remainder * 2 > expected.denominator or (
        remainder * 2 == expected.denominator and coefficient % 2
    ):
        coefficient += 1
    expected_decimal = Decimal(f"{coefficient // 10**18}.{coefficient % 10**18:018d}")
    rule = replace(predicate(a.AlertMetric.DIRECT_HHI), include_cash=include_cash)
    observed = direct_concentration_observation(
        rule,
        positions=tuple(Money(Decimal(value), EUR) for value in amounts),
        cash=(Money(Decimal(cash), EUR),),
        portfolio_total=Money(Decimal(denominator), EUR),
        context=context(),
    )
    assert observed.observed.value == expected_decimal
    assert type(observed.comparison_basis) is Decimal
