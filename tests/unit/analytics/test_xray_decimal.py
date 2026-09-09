from collections.abc import Callable
from decimal import (
    Clamped,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    FloatOperation,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    Subnormal,
    Underflow,
    localcontext,
)
from fractions import Fraction

import pytest
from trading212_analytics._xray_decimal import (
    arithmetic,
    coefficient18,
    path_relative,
    q18,
    threshold,
)
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.xray import XrayComparison
from trading212_domain.xray_validation import decimal_role

pytestmark = pytest.mark.unit


def oracle(value: Fraction) -> Decimal:
    sign = -1 if value < 0 else 1
    scaled = abs(value) * 10**18
    quotient, remainder = divmod(scaled.numerator, scaled.denominator)
    if 2 * remainder > scaled.denominator or (2 * remainder == scaled.denominator and quotient % 2):
        quotient += 1
    digits = str(quotient).zfill(19)
    text = ("-" if sign < 0 and quotient else "") + digits[:-18] + "." + digits[-18:]
    return Decimal(text)


@pytest.mark.parametrize(
    "numerator,denominator",
    [
        (1, 3),
        (1, 7),
        (5, 2 * 10**18),
        (7, 2 * 10**18),
        (-5, 2 * 10**18),
        (-7, 2 * 10**18),
        (0, 1),
        (1, 10**72),
    ],
)
def test_divmod_rounding_matches_independent_integer_ties(numerator: int, denominator: int) -> None:
    actual = q18(Decimal(numerator), Decimal(denominator))
    assert actual == oracle(Fraction(numerator, denominator))
    assert actual.as_tuple().exponent == -18
    assert not actual.is_zero() or not actual.is_signed()


@pytest.mark.parametrize("sign", [-1, 1])
def test_post_round_carry_rejects_numeric_overflow(sign: int) -> None:
    with pytest.raises(DomainError):
        q18(Decimal(sign * (2 * 10**38 - 1)), Decimal(2 * 10**18))
    below = Fraction(sign * ((2 * 10**38 - 1) * 10 - 1), 20 * 10**18)
    assert q18(Decimal(below.numerator), Decimal(below.denominator)) == oracle(below)


def test_precision80_counterexample_rounds_using_the_fourth_edge_tail() -> None:
    with arithmetic():
        numerator = Decimal("1e18") * Decimal("1e90") + Decimal("5e71") + Decimal("1")
        assert q18(numerator, Decimal("1e90")) == Decimal("1000000000000000000.000000000000000001")
    assert path_relative((Decimal("1e-18"),) * 4) == Decimal("1")


def test_maximum_root_coefficient_stress_is_exact_but_cannot_publish_total() -> None:
    amount = Decimal("99999999999999999999.999999999999999999")
    expected = Fraction(amount) * 10_000
    with arithmetic():
        root = coefficient18(amount)
        root_sum = sum((root for _ in range(10_000)), Decimal("0"))
        total = root_sum * Decimal("1e72")
        assert Fraction(root_sum) / 10**18 == expected
        assert Fraction(total) / 10**90 == expected
        assert root_sum < Decimal("1e42") and total < Decimal("1e114")
        with pytest.raises(DomainError, match="NUMERIC") as failure:
            q18(total, Decimal("1e90"))
        assert failure.value.code is ErrorCode.DATA_UNAVAILABLE


@pytest.mark.parametrize(
    "value,role",
    [
        (Decimal("0E+1000"), "amount"),
        (Decimal("0E-19"), "weight"),
        (Decimal("0E+250"), "relative_coefficient"),
        (Decimal("1e38"), "root_coefficient"),
        (Decimal("1e110"), "path_coefficient"),
        (Decimal("1e114"), "aggregate_coefficient"),
        (Decimal("1e228"), "square_coefficient"),
        (Decimal("1e232"), "hhi_coefficient"),
        (Decimal("1e43"), "residual_coefficient"),
        (Decimal("-1"), "relative_coefficient"),
        (Decimal("0.1"), "relative_coefficient"),
        (Decimal("NaN"), "weight"),
    ],
)
def test_role_and_zero_shape_bounds_precede_arithmetic(value: Decimal, role: str) -> None:
    with pytest.raises(DomainError):
        decimal_role(value, role)


def test_exact_threshold_is_independent_of_the_displayed_q18_tie() -> None:
    numerator, denominator = Decimal("499999999999999999999"), Decimal("1e21")
    assert q18(numerator, denominator) == Decimal("0.5")
    assert not threshold(numerator, denominator, Decimal("0.5"), XrayComparison.GE)
    assert threshold(Decimal("1"), Decimal("2"), Decimal("0.5"), XrayComparison.GE)
    assert not threshold(Decimal("1"), Decimal("2"), Decimal("0.5"), XrayComparison.GT)


def test_zero_canonicalization_and_declared_role_limit_inclusivity() -> None:
    assert coefficient18(Decimal("-0E+20")).as_tuple() == Decimal("0").as_tuple()
    assert decimal_role(Decimal("1e72"), "relative_coefficient") == Decimal("1e72")


@pytest.mark.parametrize("comparison", (XrayComparison.GT, XrayComparison.GE))
@pytest.mark.parametrize(
    ("numerator", "denominator", "limit"),
    (
        (0, 10**20, "0"),
        (1, 10**20, "0"),
        (10**20 - 1, 10**20, "1"),
        (10**20, 10**20, "1"),
        (10**20 + 1, 10**20, "1"),
        (5 * 10**20 - 1, 10**21, "0.5"),
        (5 * 10**20 + 1, 10**21, "0.5"),
    ),
)
def test_threshold_endpoints_and_rounded_equal_neighbors_use_exact_comparison(
    numerator: int, denominator: int, limit: str, comparison: XrayComparison
) -> None:
    ratio, boundary = Fraction(numerator, denominator), Fraction(limit)
    expected = ratio > boundary if comparison is XrayComparison.GT else ratio >= boundary
    assert (
        threshold(Decimal(numerator), Decimal(denominator), Decimal(limit), comparison) is expected
    )
    if limit in ("1", "0.5"):
        assert oracle(ratio) == Decimal(limit)


_SIGNAL_OPERATIONS: dict[type[DecimalException], Callable[[Context], Decimal]] = {
    Inexact: lambda context: context.divide(Decimal("1"), Decimal("3")),
    Rounded: lambda context: context.quantize(Decimal("1.00"), Decimal("1")),
    InvalidOperation: lambda context: context.sqrt(Decimal("-1")),
    DivisionByZero: lambda context: context.divide(Decimal("1"), Decimal("0")),
    Overflow: lambda context: context.multiply(Decimal("1e999"), Decimal("10")),
    Underflow: lambda context: context.divide(Decimal("1e-1254"), Decimal("3")),
    Subnormal: lambda context: context.divide(Decimal("1e-999"), Decimal("10")),
    Clamped: lambda context: context.plus(Decimal("0e1000")),
    FloatOperation: lambda context: Decimal(0.5),  # noqa: RUF032 - Exercise the rejected float path.
}


@pytest.mark.parametrize("signal", tuple(_SIGNAL_OPERATIONS), ids=lambda signal: signal.__name__)
def test_every_exact_decimal_trap_fails_closed_and_restores_outer_context(
    signal: type[DecimalException],
) -> None:
    with localcontext() as outer:
        outer.prec = 7
        outer.flags[Rounded] = True
        before = outer.copy()
        signalled = False
        with pytest.raises(DomainError) as failure, arithmetic() as exact:
            assert {kind for kind, enabled in exact.traps.items() if enabled} == set(
                _SIGNAL_OPERATIONS
            )
            assert not any(exact.flags.values())
            # Isolate compound signals so each declared trap is independently exercised.
            exact.clear_traps()
            exact.traps[signal] = True
            try:
                _SIGNAL_OPERATIONS[signal](exact)
            except DecimalException as caught:
                assert type(caught) is signal and exact.flags[signal]
                signalled = True
                raise
        assert signalled and failure.value.code is ErrorCode.DATA_UNAVAILABLE
        assert failure.value.field == "xray"
        assert (
            outer.prec,
            outer.rounding,
            outer.Emin,
            outer.Emax,
            outer.capitals,
            outer.clamp,
            dict(outer.flags),
            dict(outer.traps),
        ) == (
            before.prec,
            before.rounding,
            before.Emin,
            before.Emax,
            before.capitals,
            before.clamp,
            dict(before.flags),
            dict(before.traps),
        )
