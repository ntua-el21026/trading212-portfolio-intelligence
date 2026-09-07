from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from trading212_analytics.source_policy import select_fx
from trading212_domain.sources import (
    BenchmarkComponent,
    normalize_benchmark_content,
    source_snapshot_digest,
)

from tests.unit.analytics.source_factories import AT, EUR, GBP, USD, calendar, fx, policy, uid
from tests.unit.domain.test_sources import benchmark_content

pytestmark = pytest.mark.property


def round18(value: Fraction) -> Decimal:
    units, remainder = divmod(value.numerator * 10**18, value.denominator)
    if 2 * remainder > value.denominator or (2 * remainder == value.denominator and units % 2):
        units += 1
    with localcontext() as context:
        context.prec = 80
        return Decimal(units) * Decimal("0.000000000000000001")


@settings(max_examples=70, deadline=None)
@given(st.integers(1, 10000), st.integers(1, 10000), st.booleans(), st.booleans())
def test_pivot_and_reciprocal_rates_match_independent_rational_arithmetic(
    a: int, b: int, invert_a: bool, invert_b: bool
) -> None:
    first = (EUR, GBP, str(a)) if invert_a else (GBP, EUR, str(a))
    second = (USD, EUR, str(b)) if invert_b else (EUR, USD, str(b))
    snapshot = fx(first, second)
    value = select_fx(
        (snapshot,),
        base=GBP,
        quote=USD,
        at=AT,
        source_cutoff_at=AT,
        policy=policy(),
        calendar=calendar(),
    )
    expected = (Fraction(1, a) if invert_a else Fraction(a)) * (
        Fraction(1, b) if invert_b else Fraction(b)
    )
    assert value.rate == round18(expected)
    reversed_snapshot = replace(snapshot, observations=tuple(reversed(snapshot.observations)))
    assert source_snapshot_digest(snapshot) == source_snapshot_digest(reversed_snapshot)
    assert (
        select_fx(
            (reversed_snapshot,),
            base=GBP,
            quote=USD,
            at=AT,
            source_cutoff_at=AT,
            policy=policy(),
            calendar=calendar(),
        )
        == value
    )


@settings(max_examples=70, deadline=None)
@given(st.integers(1, 999), st.integers(-100, 100))
def test_explicit_benchmark_normalization_matches_exact_largest_remainders(
    numerator: int, residual: int
) -> None:
    with localcontext() as context:
        context.prec = 80
        a = Decimal(numerator) / 1000
        b = 1 - a + Decimal(residual) * Decimal("0.000000000000000001")
    content = replace(
        benchmark_content(),
        components=(
            BenchmarkComponent(source_id=uid(9), weight=a),
            BenchmarkComponent(source_id=uid(10), weight=b),
        ),
    )
    result = normalize_benchmark_content(content, normalize=True)
    fractions = [
        Fraction(a) / (Fraction(a) + Fraction(b)),
        Fraction(b) / (Fraction(a) + Fraction(b)),
    ]
    units = [int(x * 10**18) for x in fractions]
    remainder = 10**18 - sum(units)
    priority = sorted(
        range(2),
        key=lambda i: (-(fractions[i] * 10**18 - units[i]), content.components[i].source_id),
    )
    for i in priority[:remainder]:
        units[i] += 1
    assert [Fraction(x.weight) for x in result.content.components] == [
        Fraction(x, 10**18) for x in units
    ]
    assert sum(Fraction(x.weight) for x in result.content.components) == 1
    assert (
        normalize_benchmark_content(
            replace(content, components=tuple(reversed(content.components))), normalize=True
        )
        == result
    )
