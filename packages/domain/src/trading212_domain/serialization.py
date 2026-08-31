"""Canonical domain serialization with decimal strings and UTC timestamps."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from .errors import fail_validation
from .values import CurrencyCode, Instant, decimal_string, utc_string


def to_primitive(value: Any) -> Any:
    """Convert a domain graph to deterministic JSON-compatible values."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        fail_validation("binary floats cannot be serialized as authoritative values")
    if isinstance(value, Decimal):
        return decimal_string(value)
    if isinstance(value, CurrencyCode):
        return value.value
    if isinstance(value, Instant):
        return utc_string(value.value)
    if isinstance(value, datetime):
        return utc_string(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: to_primitive(getattr(value, item.name))
            for item in fields(value)
            if item.metadata.get("serialize", True)
        }
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            fail_validation("serialized mapping keys must be strings")
        return {key: to_primitive(value[key]) for key in sorted(value)}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [to_primitive(item) for item in value]
    fail_validation(f"unsupported serialization type: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        to_primitive(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
