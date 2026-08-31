"""Fixed-context Decimal operations for authoritative analytics."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, localcontext

from trading212_domain import (
    CurrencyCode,
    DomainError,
    ErrorCode,
    Money,
    Ratio,
    exact_decimal,
    quantize_boundary,
)

CALCULATION_PRECISION = 80
RATIO_QUANTUM = Decimal("0.000000000000000001")


def add(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        return left + right


def subtract(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        return left - right


def multiply(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        return left * right


def divide(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "division denominator must not be zero")
    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        return numerator / denominator


def power(base: Decimal, exponent: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        return base**exponent


def product(values: Iterable[Decimal]) -> Decimal:
    result = Decimal(1)
    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        for value in values:
            result *= value
    return result


def total(values: Iterable[Decimal]) -> Decimal:
    result = Decimal(0)
    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        for value in values:
            result += value
    return result


def persisted_decimal(value: Decimal) -> Decimal:
    return quantize_boundary(value, RATIO_QUANTUM)


def ratio(value: Decimal) -> Ratio:
    return Ratio(persisted_decimal(value))


def money(amount: Decimal, currency: str | CurrencyCode) -> Money:
    parsed_currency = currency if isinstance(currency, CurrencyCode) else CurrencyCode(currency)
    return Money(persisted_decimal(amount), parsed_currency)


def require_nonnegative(value: Decimal, *, field: str) -> Decimal:
    parsed = exact_decimal(value, field=field)
    if parsed < 0:
        raise DomainError(ErrorCode.VALIDATION_FAILED, f"{field} must not be negative", field)
    return parsed
