"""Frozen scalar/annotation admission oracle from 7cbc21e before dispatch optimization.

Only function names and required imports differ. Decimal role constants, exact
class checks, union/Literal/tuple order, bounds and error text remain frozen.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from types import UnionType
from typing import Annotated, Any, Literal, NoReturn, Union, get_args, get_origin
from uuid import UUID

from trading212_domain.errors import DomainError, ErrorCode, fail_validation
from trading212_domain.values import CurrencyCode, Instant, Money

ZERO = Decimal("0")


ONE = Decimal("1")


_ROLES = {
    "root_coefficient": (Decimal("1e38"), False, False),
    "relative_coefficient": (Decimal("1e72"), True, False),
    "path_coefficient": (Decimal("1e110"), False, False),
    "aggregate_coefficient": (Decimal("1e114"), False, False),
    "square_coefficient": (Decimal("1e228"), False, False),
    "hhi_coefficient": (Decimal("1e232"), False, False),
    "residual_coefficient": (Decimal("1e43"), False, True),
}


def legacy_invalid(field: str = "xray") -> NoReturn:
    fail_validation("Invalid closed X-ray value or invariant.", field=field)


def legacy_bound(condition: bool, field: str) -> None:
    if not condition:
        raise DomainError(ErrorCode.INPUT_BOUND_EXCEEDED, "X-ray input bound exceeded.", field)


def legacy_decimal_role(value: object, role: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        legacy_invalid(role)
    assert isinstance(value, Decimal)
    shape = value.as_tuple()
    exponent = shape.exponent
    if not isinstance(exponent, int):
        legacy_invalid(role)
    assert isinstance(exponent, int)
    if role in ("amount", "weight"):
        if not -18 <= exponent <= 20 or len(shape.digits) > 38:
            legacy_invalid(role)
        if value.copy_abs() >= Decimal("1e20"):
            legacy_invalid(role)
        if role == "weight" and not ZERO <= value <= ONE:
            legacy_invalid(role)
    else:
        if role not in _ROLES or not 0 <= exponent <= 249 or len(shape.digits) > 250:
            legacy_invalid(role)
        maximum, inclusive, signed = _ROLES[role]
        magnitude = value.copy_abs()
        if (not signed and value < ZERO) or magnitude > maximum:
            legacy_invalid(role)
        if not inclusive and magnitude == maximum:
            legacy_invalid(role)
    return ZERO if value.is_zero() else value


def legacy_checked(value: object, annotation: Any, field: str) -> object:
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is Annotated:
        return legacy_decimal_role(value, arguments[1])
    if origin in (UnionType, Union):
        for option in arguments:
            if value is None and option is type(None):
                return None
            base = get_args(option)[0] if get_origin(option) is Annotated else option
            if isinstance(base, type) and type(value) is base:
                return legacy_checked(value, option, field)
        legacy_invalid(field)
    if origin is Literal:
        if not any(type(value) is type(item) and value == item for item in arguments):
            legacy_invalid(field)
        return value
    if origin is tuple:
        if type(value) is not tuple:
            legacy_invalid(field)
        assert isinstance(value, tuple)
        legacy_bound(len(value) <= 100_000, field)
        for item in value:
            legacy_checked(item, arguments[0], field)
        return value
    if annotation is str:
        if type(value) is not str:
            legacy_invalid(field)
        assert isinstance(value, str)
        if not value or len(value) > 1024 or any(ord(char) < 32 for char in value):
            legacy_invalid(field)
    elif annotation is int:
        if type(value) is not int or not 0 <= value <= 2_147_483_647:
            legacy_invalid(field)
    elif annotation is bool:
        if type(value) is not bool:
            legacy_invalid(field)
    elif annotation is UUID:
        if type(value) is not UUID:
            legacy_invalid(field)
    elif isinstance(annotation, type) and issubclass(annotation, Enum):
        if type(value) is not annotation:
            legacy_invalid(field)
    elif annotation in (Money, CurrencyCode, Instant):
        if type(value) is not annotation:
            legacy_invalid(field)
        if isinstance(value, Money):
            legacy_decimal_role(value.amount, "amount")
    elif isinstance(annotation, type):
        if type(value) is not annotation:
            legacy_invalid(field)
    else:
        legacy_invalid(field)
    return value
