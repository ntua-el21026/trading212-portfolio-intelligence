"""Closed canonical alert codecs; financial decimals remain text at every boundary."""

from __future__ import annotations

import hashlib
import json
import re
import types
from dataclasses import MISSING, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, cast, get_args, get_origin
from uuid import UUID

from .alerts import (
    MAX_ALERT_INPUT_BYTES,
    AlertConditionState,
    AlertEvaluationInput,
    AlertEvaluationResult,
    AlertRecord,
    AlertRuleDefinition,
    AlertRuleVersion,
    AlertTransitionPlan,
    alert_hints,
    alert_limit,
    alert_require,
)
from .errors import DomainError
from .sources import SourceLicense
from .values import CurrencyCode, Money, require_utc

_ORDERED = {"events", "event_decisions", "create", "items", "legs"}


def _text(value: Decimal) -> str:
    if value.is_zero():
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _encode(value: object, field: str = "", depth: int = 0) -> Any:
    alert_limit(depth <= 32, "document.depth")
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, Decimal):
        alert_require(value.is_finite(), "decimal")
        return _text(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, CurrencyCode):
        return value.value
    if type(value) is datetime:
        return require_utc(value).isoformat().replace("+00:00", "Z")
    if type(value) is date:
        return value.isoformat()
    if type(value) is tuple:
        result = [_encode(item, depth=depth + 1) for item in value]
        if field not in _ORDERED:
            result.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
        return result
    if isinstance(value, (AlertRecord, Money, SourceLicense)) and is_dataclass(value):
        value.__post_init__()
        return {
            item.name: _encode(getattr(value, item.name), item.name, depth + 1)
            for item in fields(value)
            if not (item.default is None and getattr(value, item.name) is None)
        }
    alert_require(False, "document.type")


def encode_alert_record(value: AlertRecord) -> bytes:
    alert_require(isinstance(value, AlertRecord), "document.type")
    payload = json.dumps(
        _encode(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    alert_limit(len(payload) <= MAX_ALERT_INPUT_BYTES, "document.bytes")
    return payload


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        alert_require(key not in result, "document.duplicate_key")
        result[key] = value
    return result


def _integer(text: str) -> int:
    alert_require(
        re.fullmatch(r"-?(?:0|[1-9][0-9]{0,18})", text) is not None and text != "-0",
        "document.integer",
    )
    return int(text)


def _reject(text: str) -> Any:
    alert_require(False, "document.number")


def _decode(value: object, annotation: Any, depth: int = 0) -> Any:
    alert_limit(depth <= 32, "document.depth")
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is types.UnionType:
        if value is None and type(None) in args:
            return None
        for choice in args:
            try:
                return _decode(value, choice, depth + 1)
            except (DomainError, ValueError, TypeError):
                continue
        alert_require(False, "document.union")
    if origin is tuple:
        alert_require(type(value) is list, "document.collection")
        assert isinstance(value, list)
        alert_limit(len(value) <= 10_000, "document.collection")
        return tuple(_decode(item, args[0], depth + 1) for item in value)
    if annotation in (str, int, bool, type(None)):
        alert_require(type(value) is annotation, "document.scalar")
        return value
    if annotation is Decimal:
        alert_require(
            type(value) is str
            and re.fullmatch(r"-?(?:0|[1-9][0-9]{0,249})(?:\.[0-9]{1,18})?", value) is not None,
            "document.decimal",
        )
        assert isinstance(value, str)
        result = Decimal(value)
        alert_require(_text(result) == value, "document.decimal")
        return result
    if annotation is CurrencyCode:
        alert_require(type(value) is str, "document.currency")
        assert isinstance(value, str)
        return CurrencyCode(value)
    if annotation is UUID:
        alert_require(type(value) is str, "document.id")
        assert isinstance(value, str)
        parsed_uuid = UUID(value)
        alert_require(str(parsed_uuid) == value, "document.id")
        return parsed_uuid
    if annotation in (date, datetime):
        alert_require(type(value) is str, "document.time")
        assert isinstance(value, str)
        return (
            date.fromisoformat(value)
            if annotation is date
            else require_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        )
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        alert_require(type(value) is str, "document.enum")
        return annotation(value)
    if (
        isinstance(annotation, type)
        and is_dataclass(annotation)
        and (issubclass(annotation, AlertRecord) or annotation in (Money, SourceLicense))
    ):
        alert_require(type(value) is dict, "document.record")
        assert isinstance(value, dict)
        declared = {item.name: item for item in fields(annotation)}
        alert_require(
            set(value) <= declared.keys()
            and all(
                item.name in value
                or item.default is not MISSING
                or item.default_factory is not MISSING
                for item in declared.values()
            ),
            "document.fields",
        )
        hints = alert_hints(cast(type, annotation))
        return annotation(
            **{key: _decode(item, hints[key], depth + 1) for key, item in value.items()}
        )
    alert_require(False, "document.annotation")


def decode_alert_record[T: AlertRecord](payload: bytes, kind: type[T]) -> T:
    alert_require(type(payload) is bytes and issubclass(kind, AlertRecord), "document.type")
    alert_limit(len(payload) <= MAX_ALERT_INPUT_BYTES, "document.bytes")
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_pairs,
            parse_int=_integer,
            parse_float=_reject,
            parse_constant=_reject,
        )
        result = _decode(value, kind)
        alert_require(
            type(result) is kind and encode_alert_record(result) == payload, "document.canonical"
        )
        return cast(T, result)
    except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
        alert_require(False, "document.invalid")
    raise AssertionError("unreachable")


def alert_record_digest(value: AlertRecord) -> str:
    return hashlib.sha256(encode_alert_record(value)).hexdigest()


def encode_alert_rule_definition(value: AlertRuleDefinition) -> bytes:
    return encode_alert_record(value)


def decode_alert_rule_definition(payload: bytes) -> AlertRuleDefinition:
    return decode_alert_record(payload, AlertRuleDefinition)


def encode_alert_rule_version(value: AlertRuleVersion) -> bytes:
    return encode_alert_record(value)


def decode_alert_rule_version(payload: bytes) -> AlertRuleVersion:
    return decode_alert_record(payload, AlertRuleVersion)


def encode_alert_input(value: AlertEvaluationInput) -> bytes:
    return encode_alert_record(value)


def decode_alert_input(payload: bytes) -> AlertEvaluationInput:
    return decode_alert_record(payload, AlertEvaluationInput)


def alert_input_digest(value: AlertEvaluationInput) -> str:
    return alert_record_digest(value)


def encode_alert_result(value: AlertEvaluationResult) -> bytes:
    return encode_alert_record(value)


def decode_alert_result(payload: bytes) -> AlertEvaluationResult:
    return decode_alert_record(payload, AlertEvaluationResult)


def alert_result_digest(value: AlertEvaluationResult) -> str:
    return alert_record_digest(value)


def encode_alert_condition(value: AlertConditionState) -> bytes:
    return encode_alert_record(value)


def decode_alert_condition(payload: bytes) -> AlertConditionState:
    return decode_alert_record(payload, AlertConditionState)


def encode_alert_transition(value: AlertTransitionPlan) -> bytes:
    return encode_alert_record(value)


def decode_alert_transition(payload: bytes) -> AlertTransitionPlan:
    return decode_alert_record(payload, AlertTransitionPlan)
