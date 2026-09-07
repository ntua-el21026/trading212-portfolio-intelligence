"""Bounded closed-schema historical codecs with explicit semantic hashing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from functools import lru_cache
from types import UnionType
from typing import Any, Literal, Union, cast, get_args, get_origin, get_type_hints
from uuid import UUID

from .errors import DomainError, ErrorCode, fail_validation
from .historical import MAX_HISTORICAL_DOCUMENT_BYTES, HistoricalInput
from .historical_results import (
    AttributionCalculation,
    BenchmarkCalculation,
    CashFlowCalculation,
    HistoricalCalculation,
    IncomeCalculation,
    PerformanceCalculation,
)
from .serialization import canonical_json
from .values import CurrencyCode, Instant, exact_decimal, require_utc


def canonical_historical_input(value: HistoricalInput) -> HistoricalInput:
    """Order unordered candidate identities; preserve ordered source observations."""
    benchmark = value.benchmark_input
    if benchmark is not None:
        benchmark = replace(
            benchmark,
            price_snapshots=tuple(sorted(benchmark.price_snapshots, key=lambda x: x.id)),
            benchmark_snapshots=tuple(sorted(benchmark.benchmark_snapshots, key=lambda x: x.id)),
        )
    grouping = value.target_grouping
    if grouping is not None:
        grouping = replace(
            grouping, assignments=tuple(sorted(grouping.assignments, key=lambda x: x.listing_id))
        )
    return replace(
        value,
        instruments=tuple(sorted(value.instruments, key=lambda x: x.listing_id)),
        activity_coverage=tuple(sorted(value.activity_coverage, key=lambda item: item.id)),
        event_candidates=tuple(
            sorted(
                value.event_candidates,
                key=lambda x: (
                    x.identity.economic_at,
                    x.identity.economic_key,
                    x.identity.revision_id,
                ),
            )
        ),
        valuation_anchors=tuple(
            sorted(value.valuation_anchors, key=lambda x: (x.at, x.timing, x.id))
        ),
        price_snapshots=tuple(sorted(value.price_snapshots, key=lambda x: x.id)),
        fx_snapshots=tuple(sorted(value.fx_snapshots, key=lambda x: x.id)),
        action_snapshots=tuple(sorted(value.action_snapshots, key=lambda x: x.id)),
        calendars=tuple(sorted(value.calendars, key=lambda x: (x.id, x.version))),
        mapping_evidence=tuple(sorted(value.mapping_evidence, key=lambda x: x.id)),
        classification_evidence=tuple(sorted(value.classification_evidence, key=lambda x: x.id)),
        sources=tuple(sorted(value.sources, key=lambda x: (x.kind, x.id))),
        warnings=tuple(sorted(set(value.warnings), key=canonical_json)),
        benchmark_input=benchmark,
        target_grouping=grouping,
    )


def historical_canonical_bytes(value: object) -> bytes:
    result = canonical_json(value).encode()
    if len(result) > MAX_HISTORICAL_DOCUMENT_BYTES:
        raise DomainError(ErrorCode.INPUT_BOUND_EXCEEDED, "Historical document capacity exceeded.")
    return result


def historical_input_digest(value: HistoricalInput) -> str:
    return hashlib.sha256(historical_canonical_bytes(canonical_historical_input(value))).hexdigest()


def historical_result_digest(value: HistoricalCalculation) -> str:
    return hashlib.sha256(historical_canonical_bytes(value)).hexdigest()


def _object(items: list[tuple[str, object]]) -> dict[str, object]:
    if len({key for key, _ in items}) != len(items):
        fail_validation("Duplicate historical document fields.")
    return dict(items)


def _reject_number(_: str) -> None:
    fail_validation("Historical decimal values require canonical strings.")


def historical_value_from_json[T](value: str | bytes, kind: type[T]) -> T:
    """Decode only an internally supplied frozen domain/evidence dataclass type."""
    if not isinstance(value, (str, bytes)):
        fail_validation("A bounded historical document is required.")
    if len(value.encode() if isinstance(value, str) else value) > MAX_HISTORICAL_DOCUMENT_BYTES:
        raise DomainError(ErrorCode.INPUT_BOUND_EXCEEDED, "Historical document capacity exceeded.")
    if not isinstance(kind, type) or not is_dataclass(kind) or not _trusted(kind):
        fail_validation("A trusted fixed historical record type is required.")
    try:
        raw = json.loads(
            value,
            object_pairs_hook=_object,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
        return cast(T, _decode(raw, kind, 0))
    except (DomainError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        pass
    # Never retain invalid persisted bytes in a cause/context traceback or message.
    fail_validation("Canonical historical document is invalid.")


def _trusted(kind: type[object]) -> bool:
    return (
        kind.__module__.startswith("trading212_domain.")
        or kind.__module__ == "trading212_application.historical_evidence"
    )


@lru_cache(maxsize=128)
def _record_type_hints(kind: type[object]) -> dict[str, Any]:
    """Only fixed trusted dataclass annotations enter this bounded metadata cache."""
    return get_type_hints(kind)


def _decode(value: Any, kind: Any, depth: int) -> Any:
    if depth > 32:
        fail_validation("Historical document nesting exceeds its bound.")
    origin = get_origin(kind)
    if origin in (UnionType, Union):
        if value is None and type(None) in get_args(kind):
            return None
        for choice in get_args(kind):
            if choice is type(None):
                continue
            try:
                return _decode(value, choice, depth + 1)
            except (DomainError, ValueError, TypeError, KeyError):
                continue
        fail_validation("Historical document union is invalid.")
    if origin is Literal:
        if not any(type(value) is type(choice) and value == choice for choice in get_args(kind)):
            fail_validation("Historical document discriminator is invalid.")
        return value
    if origin is tuple:
        if not isinstance(value, list) or len(value) > 400_000:
            fail_validation("Historical document collection is invalid.")
        return tuple(_decode(item, get_args(kind)[0], depth + 1) for item in value)
    if kind is Decimal:
        if not isinstance(value, str):
            fail_validation("Historical decimal must be a string.")
        return exact_decimal(value)
    if kind is CurrencyCode:
        return CurrencyCode(value)
    if kind is Instant:
        return Instant(require_utc(datetime.fromisoformat(value)))
    if kind is UUID:
        return UUID(value)
    if kind is datetime:
        return require_utc(datetime.fromisoformat(value))
    if kind is date:
        return date.fromisoformat(value)
    if isinstance(kind, type) and issubclass(kind, Enum):
        return kind(value)
    if kind in (str, int, bool):
        if type(value) is not kind:
            fail_validation("Historical document scalar type differs.")
        return value
    if isinstance(kind, type) and is_dataclass(kind) and _trusted(kind):
        hints = _record_type_hints(kind)
        names = {field.name for field in fields(kind)}
        if not isinstance(value, dict) or set(value) != names:
            fail_validation("Historical document shape differs.")
        return kind(**{name: _decode(value[name], hints[name], depth + 1) for name in names})
    fail_validation("Unsupported historical document type.")


def historical_input_from_json(value: str | bytes) -> HistoricalInput:
    return historical_value_from_json(value, HistoricalInput)


def historical_result_from_json(value: str | bytes) -> HistoricalCalculation:
    if (
        not isinstance(value, (str, bytes))
        or len(value.encode() if isinstance(value, str) else value) > MAX_HISTORICAL_DOCUMENT_BYTES
    ):
        raise DomainError(ErrorCode.INPUT_BOUND_EXCEEDED, "Historical result capacity exceeded.")
    families: dict[str, type[HistoricalCalculation]] = {
        "performance": PerformanceCalculation,
        "benchmark": BenchmarkCalculation,
        "income": IncomeCalculation,
        "attribution": AttributionCalculation,
        "cash_flows": CashFlowCalculation,
    }
    try:
        raw = json.loads(
            value,
            object_pairs_hook=_object,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
        if isinstance(raw, dict) and raw.get("family") in families:
            return historical_value_from_json(value, families[raw["family"]])
    except (DomainError, ValueError, TypeError, KeyError, RecursionError):
        pass
    fail_validation("Canonical historical result is invalid.")
