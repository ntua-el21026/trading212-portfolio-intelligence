"""Shared structural validation for the closed scenario dataclasses."""

from __future__ import annotations

import re
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from types import UnionType
from typing import Any, Literal, TypeAliasType, Union, get_args, get_origin, get_type_hints

from .errors import DomainError, ErrorCode, fail_validation
from .scenario import MAX_SCENARIO_SENSITIVITY_ROWS, ScenarioRecord
from .values import exact_decimal, require_bounded_text, require_utc


def scenario_bound(condition: bool, field: str) -> None:
    if not condition:
        raise DomainError(ErrorCode.INPUT_BOUND_EXCEEDED, "Scenario capacity exceeded.", field)


@lru_cache(maxsize=96)
def scenario_hints(kind: type[object]) -> dict[str, Any]:
    return get_type_hints(kind)


def checked(value: object, annotation: Any, field: str) -> None:
    if isinstance(annotation, TypeAliasType):
        checked(value, annotation.__value__, field)
        return
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin in (UnionType, Union):
        for option in arguments:
            try:
                checked(value, option, field)
                return
            except DomainError:
                pass
        fail_validation("Scenario union type differs.", field=field)
    if origin is Literal:
        if not any(type(value) is type(item) and value == item for item in arguments):
            fail_validation("Scenario discriminator differs.", field=field)
    elif origin is tuple:
        if type(value) is not tuple:
            fail_validation("A scenario tuple is required.", field=field)
        scenario_bound(len(value) <= MAX_SCENARIO_SENSITIVITY_ROWS, field)
        for item in value:
            checked(item, arguments[0], field)
    elif annotation is type(None):
        if value is not None:
            fail_validation("Scenario null type differs.", field=field)
    elif annotation is Decimal:
        if type(value) is not Decimal:
            fail_validation("A canonical Decimal is required.", field=field)
        exact_decimal(value, field=field)
    elif annotation is datetime:
        if (
            type(value) is not datetime
            or require_utc(value) != value
            or value.utcoffset() != timedelta(0)
        ):
            fail_validation("A UTC scenario instant is required.", field=field)
    elif annotation is date:
        if type(value) is not date:
            fail_validation("A scenario calendar date is required.", field=field)
    elif annotation is str:
        if type(value) is not str:
            fail_validation("A scenario string is required.", field=field)
        require_bounded_text(value, field=field, maximum=1024, allow_empty=field == "description")
        if field.endswith("digest") and not re.fullmatch(r"[0-9a-f]{64}", value):
            fail_validation("A scenario digest is required.", field=field)
    elif annotation is int:
        if type(value) is not int or not 0 <= value <= MAX_SCENARIO_SENSITIVITY_ROWS:
            fail_validation("A bounded scenario count is required.", field=field)
    elif isinstance(annotation, type):
        if type(value) is not annotation:
            fail_validation("Scenario record type differs.", field=field)
    else:
        fail_validation("Unsupported scenario type.", field=field)


def validate_scenario_record(value: ScenarioRecord) -> None:
    if not is_dataclass(value):
        fail_validation("A scenario dataclass is required.", field="record")
    hints = scenario_hints(type(value))
    for item in fields(value):
        checked(getattr(value, item.name), hints[item.name], item.name)
    confidence = getattr(value, "confidence", None)
    if confidence is not None and not Decimal(0) <= confidence <= Decimal(1):
        fail_validation("Scenario confidence exceeds its bounds.", field="confidence")


def unique(values: tuple[object, ...], field: str) -> None:
    if len(set(values)) != len(values):
        fail_validation("Scenario identities are duplicated.", field=field)
