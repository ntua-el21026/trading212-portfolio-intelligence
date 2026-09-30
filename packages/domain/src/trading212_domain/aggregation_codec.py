"""Bounded canonical closed aggregation codecs; no untyped public data surface."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import fields
from datetime import datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from types import UnionType
from typing import Any, Literal, TypeAliasType, Union, cast, get_args, get_origin
from uuid import UUID

from . import aggregation as a
from . import aggregation_inputs as i
from . import aggregation_results as r
from .errors import DomainError, ErrorCode, fail_validation
from .serialization import canonical_json
from .values import CurrencyCode, exact_decimal, require_utc

_RECORDS = frozenset(
    (
        a.AggregateMember,
        a.AggregateSelectionContent,
        a.AggregateFxBinding,
        a.AggregateActivityWindow,
        a.AggregateMoney,
        i.AggregateSnapshotPin,
        i.AggregateNativeComponent,
        i.AggregateFxUse,
        i.AggregateHoldingsInput,
        i.AggregateTransferAttestation,
        i.AggregateActivityCandidate,
        i.AggregateActivityCoverage,
        i.AggregateRevisionWitness,
        i.AggregateActivityInput,
        r.AggregateComponent,
        r.AggregateAccountTotal,
        r.AggregateHolding,
        r.AggregateHoldingsResult,
        r.AggregateFlowLeg,
        r.AggregateTransferMatch,
        r.AggregateFlowCurrencyTotal,
        r.AggregateActivityResult,
        r.AggregateHoldingsSummary,
        r.AggregateActivitySummary,
    )
)
_MAX_NODES = 2000000


def _primitive(value: object, budget: list[int]) -> object:
    budget[0] += 1
    a.aggregate_bound(budget[0] <= _MAX_NODES, "aggregation.nodes")
    if value is None or type(value) in (str, bool, int, Decimal, UUID, datetime, CurrencyCode):
        return value
    if isinstance(value, Enum):
        return value
    if type(value) is tuple:
        a.aggregate_bound(len(value) <= 10256, "aggregation.rows")
        return tuple(_primitive(item, budget) for item in value)
    if type(value) in _RECORDS:
        return {
            field.name: _primitive(getattr(value, field.name), budget)
            for field in fields(cast(Any, value))
        }
    fail_validation("Unknown aggregation record.", field="aggregation.codec")


def aggregation_record_bytes(value: a.AggregateRecord) -> bytes:
    if type(value) not in _RECORDS:
        fail_validation("A closed aggregation record is required.")
    payload = canonical_json(_primitive(value, [0])).encode("utf-8")
    a.aggregate_bound(len(payload) <= a.MAX_AGGREGATE_BYTES, "aggregation.bytes")
    return payload


def aggregation_record_digest(value: a.AggregateRecord) -> str:
    return sha256(b"t212pi.aggregation.record.v1\0" + aggregation_record_bytes(value)).hexdigest()


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            fail_validation("Repeated aggregation field.")
        result[key] = value
    return result


def _decode(value: object, target: Any) -> object:
    if isinstance(target, TypeAliasType):
        return _decode(value, target.__value__)
    origin, args = get_origin(target), get_args(target)
    if origin in (Union, UnionType):
        for option in args:
            try:
                return _decode(value, option)
            except (DomainError, ValueError, TypeError):
                pass
    elif origin is Literal:
        if any(type(value) is type(item) and value == item for item in args):
            return value
    elif origin is tuple:
        if type(value) is list:
            a.aggregate_bound(len(value) <= 10256, "aggregation.rows")
            return tuple(_decode(item, args[0]) for item in value)
    elif target is type(None):
        if value is None:
            return None
    elif target in (str, bool, int):
        if type(value) is target:
            return value
    elif target is Decimal and type(value) is str:
        return exact_decimal(value)
    elif target is CurrencyCode and type(value) is str:
        return CurrencyCode(value)
    elif target is UUID and type(value) is str:
        return UUID(value)
    elif target is datetime and type(value) is str:
        return require_utc(datetime.fromisoformat(value))
    elif isinstance(target, type) and issubclass(target, Enum) and type(value) is str:
        return target(value)
    elif target in _RECORDS and type(value) is dict:
        hints = a.aggregate_hints(target)
        if set(value) == set(hints):
            return cast(Callable[..., object], target)(
                **{key: _decode(item, hints[key]) for key, item in value.items()}
            )
    fail_validation("Invalid closed aggregation field.", field="aggregation.codec")


def _preflight(payload: bytes) -> None:
    depth = nodes = size = 0
    quoted = escaped = False
    for byte in payload:
        if quoted:
            size += 1
            a.aggregate_bound(size <= 2048, "aggregation.string")
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted, size = True, 0
        elif byte in (91, 123):
            depth += 1
            a.aggregate_bound(depth <= 16, "aggregation.depth")
        elif byte in (93, 125):
            depth -= 1
            if depth < 0:
                fail_validation("Invalid aggregation nesting.")
        elif byte in (44, 58):
            nodes += 1
            a.aggregate_bound(nodes <= _MAX_NODES, "aggregation.nodes")


def _load[T: a.AggregateRecord](payload: bytes, target: type[T], expected_digest: str | None) -> T:
    try:
        if type(payload) is not bytes or not 0 < len(payload) <= a.MAX_AGGREGATE_BYTES:
            fail_validation("Aggregation payload exceeds its bound.")
        _preflight(payload)
        value = _decode(json.loads(payload, object_pairs_hook=_pairs), target)
        if not isinstance(value, target) or aggregation_record_bytes(value) != payload:
            fail_validation("Aggregation payload is not canonical.")
        if expected_digest is not None:
            a.aggregate_digest(expected_digest)
            if aggregation_record_digest(value) != expected_digest:
                fail_validation("Aggregation retained digest differs.")
        return value
    except (DomainError, ValueError, TypeError, KeyError, RecursionError, UnicodeError):
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            "Invalid canonical aggregation payload.",
            "aggregation.codec",
        ) from None


def aggregation_selection_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> a.AggregateSelectionContent:
    return _load(payload, a.AggregateSelectionContent, expected_digest)


def aggregation_holdings_input_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> i.AggregateHoldingsInput:
    return _load(payload, i.AggregateHoldingsInput, expected_digest)


def aggregation_activity_input_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> i.AggregateActivityInput:
    return _load(payload, i.AggregateActivityInput, expected_digest)


def aggregation_holdings_result_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> r.AggregateHoldingsResult:
    return _load(payload, r.AggregateHoldingsResult, expected_digest)


def aggregation_activity_result_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> r.AggregateActivityResult:
    return _load(payload, r.AggregateActivityResult, expected_digest)


def aggregation_component_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> r.AggregateComponent:
    return _load(payload, r.AggregateComponent, expected_digest)


def aggregation_holding_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> r.AggregateHolding:
    return _load(payload, r.AggregateHolding, expected_digest)


def aggregation_account_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> r.AggregateAccountTotal:
    return _load(payload, r.AggregateAccountTotal, expected_digest)


def aggregation_flow_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> r.AggregateFlowLeg:
    return _load(payload, r.AggregateFlowLeg, expected_digest)


def aggregation_transfer_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> r.AggregateTransferMatch:
    return _load(payload, r.AggregateTransferMatch, expected_digest)


def aggregation_candidate_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> i.AggregateActivityCandidate:
    return _load(payload, i.AggregateActivityCandidate, expected_digest)


def aggregation_fx_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> i.AggregateFxUse:
    return _load(payload, i.AggregateFxUse, expected_digest)


def aggregation_snapshot_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> i.AggregateSnapshotPin:
    return _load(payload, i.AggregateSnapshotPin, expected_digest)


def aggregation_holdings_summary_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> r.AggregateHoldingsSummary:
    return _load(payload, r.AggregateHoldingsSummary, expected_digest)


def aggregation_activity_summary_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> r.AggregateActivitySummary:
    return _load(payload, r.AggregateActivitySummary, expected_digest)


def aggregation_coverage_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> i.AggregateActivityCoverage:
    return _load(payload, i.AggregateActivityCoverage, expected_digest)


def aggregation_revision_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> i.AggregateRevisionWitness:
    return _load(payload, i.AggregateRevisionWitness, expected_digest)
