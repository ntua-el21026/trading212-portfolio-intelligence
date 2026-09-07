"""Bounded replay JSON decoding before the selected-field canonical boundary."""

from __future__ import annotations

import json
from enum import StrEnum

MAX_PAGE_BYTES = 8 * 1024 * 1024
MAX_JSON_DEPTH = 16
MAX_JSON_STRING = 4096
MAX_JSON_NODES = 100_000

type JsonValue = bool | int | str | list[JsonValue] | dict[str, JsonValue] | None


class DecodeFailure(StrEnum):
    INVALID_SCHEMA = "invalid_schema"
    PAYLOAD_TOO_LARGE = "payload_too_large"


def _reject_number(_: str) -> None:
    raise ValueError("replay numbers must be exact decimal strings")


def _unique_object(items: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate replay field")
        result[key] = value
    return result


def decode_replay_json(payload: bytes) -> dict[str, JsonValue] | DecodeFailure:
    """Decode finite bounded objects without exposing parser messages or causes.

    Financial numbers in this provider schema are strings. JSON integers are used
    only for bounded revision ordinals. Raw payloads and unknown fields never form
    source digests; adapter projections select the typed semantic fields afterward.
    """
    if len(payload) > MAX_PAGE_BYTES:
        return DecodeFailure.PAYLOAD_TOO_LARGE
    decoded: object = None
    invalid = False
    try:
        decoded = json.loads(
            payload,
            parse_float=_reject_number,
            parse_constant=_reject_number,
            object_pairs_hook=_unique_object,
        )
    except (ValueError, UnicodeError, RecursionError):
        invalid = True
    if invalid or not isinstance(decoded, dict):
        return DecodeFailure.INVALID_SCHEMA
    pending: list[tuple[object, int]] = [(decoded, 0)]
    count = 0
    while pending:
        value, depth = pending.pop()
        count += 1
        if depth > MAX_JSON_DEPTH or count > MAX_JSON_NODES:
            return DecodeFailure.PAYLOAD_TOO_LARGE
        if isinstance(value, str):
            if len(value) > MAX_JSON_STRING:
                return DecodeFailure.PAYLOAD_TOO_LARGE
        elif isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str) or len(key) > 120:
                    return DecodeFailure.INVALID_SCHEMA
                pending.append((item, depth + 1))
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)
        elif value is not None and type(value) not in {bool, int}:
            return DecodeFailure.INVALID_SCHEMA
    # json.loads has been completely traversed above; no Any-valued public boundary.
    return _json_object(decoded)


def _json_object(value: dict[object, object]) -> dict[str, JsonValue]:
    return {str(key): _json_value(item) for key, item in value.items()}


def _json_value(value: object) -> JsonValue:
    if isinstance(value, dict):
        return _json_object(value)
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, str)):
        return value
    raise ValueError("invalid selected replay value")
