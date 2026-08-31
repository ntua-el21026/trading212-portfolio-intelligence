"""Exact financial and temporal value objects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from typing import Any, Self

from .errors import DomainError, ErrorCode, fail_validation, reject_float

_DECIMAL_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
MAX_PRECISION = 38
MAX_SCALE = 18
DEFAULT_ROUNDING = ROUND_HALF_EVEN
_OPERATION_PRECISION = MAX_PRECISION * 2 + 2


def _add_exact(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = _OPERATION_PRECISION
        return left + right


def _subtract_exact(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = _OPERATION_PRECISION
        return left - right


def _multiply_exact(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = _OPERATION_PRECISION
        return left * right


def _divide_exact(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = _OPERATION_PRECISION
        return left / right


def exact_decimal(value: Decimal | int | str, *, field: str = "value") -> Decimal:
    """Parse an exact decimal while excluding ambiguous/binary representations.

    Canonical strings are ordinary base-10 notation: no exponent, whitespace,
    leading plus, locale separators, or redundant leading zeroes.
    """

    reject_float(value, field=field)
    if isinstance(value, bool):
        fail_validation(f"{field} must be an exact decimal", field=field)
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, str):
        if not _DECIMAL_PATTERN.fullmatch(value):
            fail_validation(f"{field} must be a canonical decimal string", field=field)
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:  # pragma: no cover - regex already narrows this
            raise DomainError(ErrorCode.VALIDATION_FAILED, f"invalid {field}", field) from exc
    else:
        fail_validation(f"{field} must be Decimal, int, or canonical decimal string", field=field)

    if not parsed.is_finite():
        fail_validation(f"{field} must be finite", field=field)

    _, digits, exponent = parsed.as_tuple()
    # Decimal typing retains special exponent literals after the finite check.
    if not isinstance(exponent, int):
        fail_validation(f"{field} must be finite", field=field)
    fractional_digits = max(-exponent, 0)
    integer_digits = max(len(digits) + exponent, 0)
    precision = max(integer_digits + fractional_digits, 1)
    if fractional_digits > MAX_SCALE or precision > MAX_PRECISION:
        fail_validation(
            f"{field} exceeds NUMERIC({MAX_PRECISION},{MAX_SCALE})",
            field=field,
        )
    return parsed


def decimal_string(value: Decimal) -> str:
    """Return deterministic non-exponent decimal JSON text."""

    parsed = exact_decimal(value)
    if parsed.is_zero():
        return "0"
    rendered = format(parsed, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def quantize_boundary(value: Decimal, quantum: Decimal | str) -> Decimal:
    """Round only at an explicitly named output/accounting boundary."""

    reject_float(value, field="value")
    if not isinstance(value, Decimal) or not value.is_finite():
        fail_validation("value must be a finite Decimal intermediate", field="value")
    parsed_quantum = exact_decimal(quantum, field="quantum")
    if parsed_quantum <= 0:
        fail_validation("quantum must be positive", field="quantum")
    try:
        with localcontext() as context:
            context.prec = _OPERATION_PRECISION
            rounded = value.quantize(parsed_quantum, rounding=DEFAULT_ROUNDING)
    except InvalidOperation as exc:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            "rounded value exceeds the supported exact numeric boundary",
            "value",
        ) from exc
    return exact_decimal(rounded)


@dataclass(frozen=True, slots=True, order=True)
class CurrencyCode:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not _CURRENCY_PATTERN.fullmatch(self.value):
            fail_validation("currency must be an uppercase ISO-4217-style code", field="currency")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Quantity:
    value: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", exact_decimal(self.value, field="quantity"))

    @classmethod
    def parse(cls, value: Decimal | int | str) -> Self:
        return cls(exact_decimal(value, field="quantity"))


@dataclass(frozen=True, slots=True)
class Ratio:
    """A dimensionless fraction, not percentage points."""

    value: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", exact_decimal(self.value, field="ratio"))

    @classmethod
    def parse(cls, value: Decimal | int | str) -> Self:
        return cls(exact_decimal(value, field="ratio"))


@dataclass(frozen=True, slots=True)
class Percentage:
    """Percentage points, so 12.5 means 12.5%, not 0.125."""

    points: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "points", exact_decimal(self.points, field="percentage_points"))

    @classmethod
    def parse(cls, value: Decimal | int | str) -> Self:
        return cls(exact_decimal(value, field="percentage_points"))

    def as_ratio(self) -> Ratio:
        return Ratio(_divide_exact(self.points, Decimal(100)))


@dataclass(frozen=True, slots=True)
class Price:
    value: Decimal
    quote_currency: CurrencyCode

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", exact_decimal(self.value, field="price"))
        if self.value < 0:
            fail_validation("price must not be negative", field="price")
        if not isinstance(self.quote_currency, CurrencyCode):
            fail_validation("quote_currency must be a CurrencyCode", field="quote_currency")

    @classmethod
    def parse(cls, value: Decimal | int | str, currency: str | CurrencyCode) -> Self:
        return cls(
            exact_decimal(value, field="price"),
            currency if isinstance(currency, CurrencyCode) else CurrencyCode(currency),
        )


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: CurrencyCode

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", exact_decimal(self.amount, field="amount"))
        if not isinstance(self.currency, CurrencyCode):
            fail_validation("currency must be a CurrencyCode", field="currency")

    @classmethod
    def parse(cls, amount: Decimal | int | str, currency: str | CurrencyCode) -> Self:
        return cls(
            exact_decimal(amount, field="amount"),
            currency if isinstance(currency, CurrencyCode) else CurrencyCode(currency),
        )

    @classmethod
    def zero(cls, currency: str | CurrencyCode) -> Self:
        return cls.parse(0, currency)

    def _require_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise DomainError(
                ErrorCode.CURRENCY_MISMATCH,
                f"currency mismatch: {self.currency} and {other.currency}",
                "currency",
            )

    def __add__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return Money(_add_exact(self.amount, other.amount), self.currency)

    def __sub__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return Money(_subtract_exact(self.amount, other.amount), self.currency)

    def scale(self, multiplier: Decimal | int | str) -> Money:
        parsed_multiplier = exact_decimal(multiplier, field="multiplier")
        return Money(_multiply_exact(self.amount, parsed_multiplier), self.currency)


def require_utc(value: datetime, *, field: str = "instant") -> datetime:
    if not isinstance(value, datetime):
        fail_validation(f"{field} must be a datetime", field=field)
    if value.tzinfo is None or value.utcoffset() is None:
        fail_validation(f"{field} must be timezone-aware", field=field)
    return value.astimezone(UTC)


def utc_string(value: datetime) -> str:
    normalized = require_utc(value)
    return normalized.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True, order=True)
class Instant:
    value: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", require_utc(self.value))

    @classmethod
    def parse(cls, value: str | datetime) -> Self:
        if isinstance(value, datetime):
            return cls(value)
        if not isinstance(value, str) or not value.endswith(("Z", "+00:00")):
            fail_validation("instant must be an RFC 3339 UTC timestamp", field="instant")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DomainError(ErrorCode.VALIDATION_FAILED, "invalid instant", "instant") from exc
        return cls(parsed)


@dataclass(frozen=True, slots=True)
class DateRange:
    start_inclusive: date
    end_exclusive: date

    def __post_init__(self) -> None:
        if not isinstance(self.start_inclusive, date) or isinstance(self.start_inclusive, datetime):
            fail_validation("start_inclusive must be a date", field="start_inclusive")
        if not isinstance(self.end_exclusive, date) or isinstance(self.end_exclusive, datetime):
            fail_validation("end_exclusive must be a date", field="end_exclusive")
        if self.end_exclusive < self.start_inclusive:
            fail_validation("end_exclusive must not precede start_inclusive", field="end_exclusive")


@dataclass(frozen=True, slots=True)
class FxRate:
    base_currency: CurrencyCode
    quote_currency: CurrencyCode
    rate: Decimal
    observed_at: Instant
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "rate", exact_decimal(self.rate, field="fx_rate"))
        if self.rate <= 0:
            fail_validation("fx_rate must be positive", field="fx_rate")
        if self.base_currency == self.quote_currency and self.rate != Decimal(1):
            fail_validation("same-currency FX rate must equal one", field="fx_rate")
        if not self.source or len(self.source) > 120:
            fail_validation("FX source is required and bounded", field="source")

    def convert(self, money: Money) -> Money:
        if money.currency != self.base_currency:
            raise DomainError(
                ErrorCode.CURRENCY_MISMATCH,
                f"FX base {self.base_currency} does not match {money.currency}",
                "currency",
            )
        return Money(_multiply_exact(money.amount, self.rate), self.quote_currency)

    def inverse(self) -> FxRate:
        return FxRate(
            self.quote_currency,
            self.base_currency,
            _divide_exact(Decimal(1), self.rate),
            self.observed_at,
            self.source,
        )


def require_bounded_text(value: Any, *, field: str, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        fail_validation(f"{field} must be text", field=field)
    if (not allow_empty and not value) or len(value) > maximum or "\x00" in value:
        fail_validation(f"{field} must contain 1..{maximum} safe characters", field=field)
    return value
