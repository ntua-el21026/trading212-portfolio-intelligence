"""Bounded closed canonical codecs; no transport or operational state in financial bytes."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import fields
from decimal import Decimal
from hashlib import sha256
from types import UnionType
from typing import Any, Literal, TypeAliasType, Union, cast, get_args, get_origin, get_type_hints

from . import projection as d
from . import projection_result as r
from .errors import DomainError, ErrorCode, fail_validation
from .values import CurrencyCode, Money, decimal_string, exact_decimal

_RECORDS = frozenset(
    (
        d.ProjectionSourcePin,
        d.ProjectionAsset,
        d.ProjectionAllocation,
        d.ProjectionAssumptions,
        d.ProjectionInitialBasis,
        d.ProjectionScheduleEntry,
        d.ProjectionSchedule,
        d.ProjectionSensitivity,
        d.ProjectionGoal,
        d.ProjectionInput,
        r.ProjectionAssetValue,
        r.ProjectionPoint,
        r.ProjectionPath,
        r.ProjectionChunk,
        r.ProjectionQuantiles,
        r.ProjectionDistributionPoint,
        r.ProjectionHistogramBin,
        r.ProjectionHistogram,
        r.ProjectionGoalResult,
        r.ProjectionVariantResult,
        r.ProjectionCalculation,
        Money,
    )
)


def _value(value: object) -> object:
    if value is None or type(value) in (str, bool, int):
        return value
    if isinstance(value, Decimal):
        return decimal_string(value)
    if isinstance(value, CurrencyCode):
        return value.value
    if isinstance(value, tuple):
        return [_value(item) for item in value]
    if type(value) in _RECORDS:
        return {
            field.name: _value(getattr(value, field.name)) for field in fields(cast("Any", value))
        }
    fail_validation("Unknown canonical projection record.", field="projection.codec")


def projection_canonical_bytes(value: object) -> bytes:
    payload = json.dumps(
        _value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    if len(payload) > d.PROJECTION_MAX_BYTES:
        fail_validation(
            "Projection canonical payload exceeds its byte bound.", field="projection.bytes"
        )
    return payload


def projection_input_digest(value: d.ProjectionInput) -> str:
    if not isinstance(value, d.ProjectionInput):
        fail_validation("Canonical projection inputs are required.", field="inputs")
    return sha256(b"t212pi.projection.input.v1\0" + projection_canonical_bytes(value)).hexdigest()


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            fail_validation("Repeated canonical projection field.", field="projection.codec")
        result[key] = value
    return result


def _decode(value: object, target: object) -> object:
    if isinstance(target, TypeAliasType):
        return _decode(value, target.__value__)
    origin, args = get_origin(target), get_args(target)
    if origin in (Union, UnionType):
        for option in args:
            try:
                return _decode(value, option)
            except DomainError:
                continue
        fail_validation("Projection union variant is invalid.", field="projection.codec")
    if origin is Literal:
        if any(type(value) is type(option) and value == option for option in args):
            return value
    elif origin is tuple:
        if isinstance(value, list) and len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode(item, args[0]) for item in value)
    elif target is type(None):
        if value is None:
            return None
    elif target is Decimal:
        if isinstance(value, str):
            return exact_decimal(value)
    elif target is CurrencyCode:
        if isinstance(value, str):
            return CurrencyCode(value)
    elif target in (str, bool, int):
        if type(value) is target:
            return value
    elif target in _RECORDS and isinstance(value, dict):
        constructor = cast("Callable[..., object]", target)
        hints = get_type_hints(constructor)
        if set(value) == set(hints):
            return constructor(**{name: _decode(item, hints[name]) for name, item in value.items()})
    fail_validation("Invalid canonical projection field.", field="projection.codec")


def _load(payload: bytes, target: type[object]) -> object:
    if not isinstance(payload, bytes) or len(payload) > d.PROJECTION_MAX_BYTES:
        fail_validation("Projection payload is outside its byte bound.", field="projection.bytes")
    try:
        raw = json.loads(payload, object_pairs_hook=_object)
        result = _decode(raw, target)
        if projection_canonical_bytes(result) != payload:
            fail_validation("Projection payload is not canonical.", field="projection.codec")
        return result
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED, "Invalid canonical projection payload.", "projection.codec"
        ) from exc


def decode_projection_input(payload: bytes) -> d.ProjectionInput:
    return cast("d.ProjectionInput", _load(payload, d.ProjectionInput))


def decode_projection_chunk(payload: bytes) -> r.ProjectionChunk:
    return cast("r.ProjectionChunk", _load(payload, r.ProjectionChunk))


def decode_projection_result(payload: bytes) -> r.ProjectionCalculation:
    return cast("r.ProjectionCalculation", _load(payload, r.ProjectionCalculation))
