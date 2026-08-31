from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from trading212_domain import (
    Instant,
    Money,
    canonical_json,
    decimal_string,
    exact_decimal,
    quantize_boundary,
)

pytestmark = pytest.mark.property

exact_decimals = st.decimals(
    min_value=Decimal("-99999999999999999999.999999999999999999"),
    max_value=Decimal("99999999999999999999.999999999999999999"),
    places=18,
    allow_nan=False,
    allow_infinity=False,
)
EUR = Money.parse(0, "EUR").currency


@given(a=exact_decimals, b=exact_decimals, c=exact_decimals)
def test_same_currency_money_addition_is_associative_when_result_fits(
    a: Decimal, b: Decimal, c: Decimal
) -> None:
    try:
        left = (Money(a, EUR) + Money(b, EUR)) + Money(c, EUR)
        right = Money(a, EUR) + (Money(b, EUR) + Money(c, EUR))
    except Exception as exc:
        # Values individually fit NUMERIC(38,18), while an aggregate can exceed it.
        if "NUMERIC" in str(exc):
            return
        raise
    assert left == right


@given(value=exact_decimals)
def test_decimal_canonical_text_round_trips_exactly(value: Decimal) -> None:
    rendered = decimal_string(value)
    assert exact_decimal(rendered) == value
    assert "e" not in rendered.lower()


@given(value=exact_decimals)
def test_authoritative_json_encodes_decimal_as_string(value: Decimal) -> None:
    rendered = canonical_json({"value": value})
    assert rendered == '{"value":"' + decimal_string(value) + '"}'


@given(
    left=st.decimals(
        min_value=Decimal("-9999999.999999999999999999"),
        max_value=Decimal("9999999.999999999999999999"),
        places=18,
        allow_nan=False,
        allow_infinity=False,
    ),
    right=st.decimals(
        min_value=Decimal("-9.999999999999999999"),
        max_value=Decimal("9.999999999999999999"),
        places=18,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_explicit_boundary_rounds_high_scale_decimal_products(
    left: Decimal, right: Decimal
) -> None:
    product = left * right
    rounded = quantize_boundary(product, Decimal("0.000000000000000001"))
    exponent = rounded.as_tuple().exponent
    assert isinstance(exponent, int)
    assert exponent >= -18


@given(offset_hours=st.integers(min_value=-12, max_value=14))
def test_aware_instants_normalize_to_same_utc_timeline(offset_hours: int) -> None:
    utc_value = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    local = utc_value.astimezone(timezone(timedelta(hours=offset_hours)))
    assert Instant(local).value == utc_value
