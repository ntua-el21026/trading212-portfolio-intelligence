"""The closed Decimal256 coefficient algebra of ADR-0017."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Context, Decimal, DecimalException, localcontext

from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.xray import XrayComparison, XrayInput
from trading212_domain.xray_validation import decimal_role, exact_context, invalid

ZERO = Decimal("0")
ONE = Decimal("1")
TWO = Decimal("2")
S = Decimal("1e18")
Q = Decimal("1e-18")
UNIT = Decimal("1e72")
MONEY = Decimal("1e90")
PADDING = tuple(Decimal(text) for text in ("1e72", "1e54", "1e36", "1e18", "1"))


@contextmanager
def arithmetic() -> Iterator[Context]:
    try:
        with localcontext(exact_context()) as context:
            yield context
            if any(context.flags.values()):
                invalid("arithmetic.signal")
    except DecimalException:
        raise DomainError(
            ErrorCode.DATA_UNAVAILABLE, "X-ray exact arithmetic could not be represented.", "xray"
        ) from None


def coefficient18(value: Decimal) -> Decimal:
    value = decimal_role(value, "amount")
    with arithmetic() as context:
        result = context.quantize(context.scaleb(value, Decimal("18")), ONE)
        return ZERO if result.is_zero() else result


def integral(value: Decimal, maximum: Decimal, *, signed: bool = False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        invalid("coefficient")
    shape = value.as_tuple()
    if not isinstance(shape.exponent, int) or not 0 <= shape.exponent <= 249:
        invalid("coefficient.shape")
    if len(shape.digits) > 250 or value.copy_abs() >= maximum:
        invalid("coefficient.bound")
    if not signed and value < ZERO:
        invalid("coefficient.sign")
    return ZERO if value.is_zero() else value


def q18(numerator: Decimal, denominator: Decimal) -> Decimal:
    numerator = integral(numerator, Decimal("1e232"), signed=True)
    denominator = integral(denominator, Decimal("1e228"))
    if denominator == ZERO:
        invalid("denominator")
    with arithmetic() as context:
        scaled = numerator.copy_abs() * S
        quotient, remainder = context.divmod(scaled, denominator)
        if scaled != quotient * denominator + remainder or not ZERO <= remainder < denominator:
            invalid("rounding.reconstruction")
        doubled = TWO * remainder
        if doubled > denominator or (
            doubled == denominator and context.remainder(quotient, TWO) == ONE
        ):
            quotient += ONE
        if quotient >= Decimal("1e38"):
            raise DomainError(
                ErrorCode.DATA_UNAVAILABLE, "X-ray Q18 output exceeds NUMERIC(38,18).", "xray"
            )
        if numerator < ZERO and quotient != ZERO:
            quotient = quotient.copy_negate()
        result = context.scaleb(quotient, Decimal("-18"))
        if result.as_tuple().exponent != -18:
            invalid("rounding.exponent")
        return result.copy_abs() if result.is_zero() else result


def path_relative(weights: tuple[Decimal, ...]) -> Decimal:
    if len(weights) > 4:
        invalid("fund_edges")
    with arithmetic():
        product = ONE
        for weight in weights:
            product *= coefficient18(decimal_role(weight, "weight"))
        return decimal_role(product * PADDING[len(weights)], "relative_coefficient")


def threshold(
    numerator: Decimal, denominator: Decimal, limit: Decimal, comparison: XrayComparison
) -> bool:
    numerator = integral(numerator, Decimal("1e232"))
    denominator = integral(denominator, Decimal("1e228"))
    if denominator <= ZERO:
        invalid("threshold.denominator")
    with arithmetic():
        left = numerator * S
        right = coefficient18(decimal_role(limit, "weight")) * denominator
        return left > right if comparison is XrayComparison.GT else left >= right


def residual(parent: Decimal, children: tuple[Decimal, ...], *, rounded_parent: bool) -> Decimal:
    with arithmetic():
        result = coefficient18(parent) - sum((coefficient18(item) for item in children), ZERO)
        limit = Decimal(len(children)) + (ONE if rounded_parent else ZERO)
        if TWO * result.copy_abs() > limit:
            invalid("display_residual.bound")
        return decimal_role(result, "residual_coefficient")


def verify_broker_fx(value: XrayInput) -> None:
    """Audit retained P1 wallet conversion once; saved reporting money remains the basis.

    Two ingress coefficients are each below 1e38, so the exact product is below
    1e76 and the scaled rounding numerator below 1e94. No intermediate rounding.
    """
    roots = {item.root.key: item for item in value.positions}
    conversions = {item.consumer_key: item for item in value.licensed_fx}
    with arithmetic():
        for quote in value.broker_fx:
            root = roots[quote.root_key]
            conversion = conversions.get(quote.root_key)
            saved = root.reporting_value if conversion is None else conversion.input_value
            original, reporting = root.original_value.value, saved.value
            assert original is not None  # Closed input binding requires the original wallet value.
            if reporting is None:
                continue
            expected = q18(
                coefficient18(original.amount) * coefficient18(quote.rate), Decimal("1e36")
            )
            if expected != reporting.amount:
                invalid("broker_fx.saved_reporting_value")
