"""Closed-schema reconstruction of canonical persisted planning graphs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum
from types import UnionType
from typing import Any, cast, get_args, get_origin, get_type_hints
from uuid import UUID

from .errors import DomainError, fail_validation
from .planning import ContributionPlanResult, DriftCalculation, PlanningInput
from .serialization import canonical_json
from .targets import canonical_target_content
from .values import CurrencyCode, exact_decimal, require_utc

MAX_PLANNING_DOCUMENT_BYTES = 8_388_608


def canonical_planning_input(value: PlanningInput) -> PlanningInput:
    valuation = replace(
        value.valuation,
        positions=tuple(sorted(value.valuation.positions, key=lambda x: x.listing_id)),
        cash_components=tuple(sorted(value.valuation.cash_components, key=canonical_json)),
        sources=tuple(
            sorted(value.valuation.sources, key=lambda x: (x.kind, x.id, x.content_digest))
        ),
        missing_inputs=tuple(sorted(set(value.valuation.missing_inputs))),
    )
    options = value.options
    return replace(
        value,
        valuation=valuation,
        target_content=canonical_target_content(value.target_content),
        node_identities=tuple(sorted(value.node_identities, key=lambda x: x.key)),
        catalog=replace(
            value.catalog,
            instruments=tuple(
                sorted(value.catalog.instruments, key=lambda x: str(x.instrument_id))
            ),
            listings=tuple(sorted(value.catalog.listings, key=lambda x: str(x.listing_id))),
        ),
        options=replace(
            options,
            eligible_holding_ids=tuple(sorted(options.eligible_holding_ids))
            if options.eligible_holding_ids is not None
            else None,
            excluded_holding_ids=tuple(sorted(options.excluded_holding_ids)),
            restricted_group_ids=tuple(sorted(options.restricted_group_ids)),
            listing_preferences=tuple(
                sorted(options.listing_preferences, key=lambda x: x.holding_id)
            ),
            allocation_constraints=tuple(
                sorted(options.allocation_constraints, key=lambda x: x.key)
            ),
            holding_constraints=tuple(
                sorted(options.holding_constraints, key=lambda x: x.holding_id)
            ),
        ),
    )


def planning_input_digest(value: PlanningInput) -> str:
    return hashlib.sha256(canonical_json(canonical_planning_input(value)).encode()).hexdigest()


def contribution_plan_result_digest(value: ContributionPlanResult) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len({key for key, _ in pairs}) != len(pairs):
        fail_validation("Duplicate canonical document fields.")
    return dict(pairs)


def _nondecimal(_: str) -> None:
    fail_validation("Financial values require decimal strings.")


def _read(value: str | bytes, kind: type[Any]) -> Any:
    if (
        not isinstance(value, (str, bytes))
        or len(value.encode() if isinstance(value, str) else value) > MAX_PLANNING_DOCUMENT_BYTES
    ):
        fail_validation("Canonical planning document exceeds its bound.")
    try:
        raw = json.loads(
            value, object_pairs_hook=_object, parse_float=_nondecimal, parse_constant=_nondecimal
        )
        return _decode(raw, kind, 0)
    except (DomainError, ValueError, TypeError, KeyError, RecursionError):
        # Persisted invalid bytes must never be reflected in an outward error or traceback chain.
        pass
    fail_validation("Canonical planning document is invalid.")


def _decode(value: Any, kind: Any, depth: int) -> Any:
    if depth > 32:
        fail_validation("Canonical planning document nesting exceeds its bound.")
    origin = get_origin(kind)
    if origin is UnionType:
        choices = get_args(kind)
        if value is None and type(None) in choices:
            return None
        for choice in choices:
            if choice is not type(None):
                return _decode(value, choice, depth + 1)
    if origin is tuple:
        if not isinstance(value, list) or len(value) > 8192:
            fail_validation("Canonical collection is invalid.")
        return tuple(_decode(item, get_args(kind)[0], depth + 1) for item in value)
    if kind is Decimal:
        if not isinstance(value, str):
            fail_validation("Canonical decimal must be a string.")
        return exact_decimal(value)
    if kind is CurrencyCode:
        return CurrencyCode(value)
    if kind is UUID:
        return UUID(value)
    if kind is datetime:
        return require_utc(datetime.fromisoformat(value))
    if isinstance(kind, type) and issubclass(kind, Enum):
        return kind(value)
    if kind in (str, bool, int):
        if type(value) is not kind:
            fail_validation("Canonical scalar type differs.")
        return value
    if is_dataclass(kind):
        hints = get_type_hints(kind)
        names = {item.name for item in fields(kind)}
        if not isinstance(value, dict) or set(value) != names:
            fail_validation("Canonical object shape differs.")
        constructor = cast(type[Any], kind)
        return constructor(**{name: _decode(value[name], hints[name], depth + 1) for name in names})
    fail_validation("Unsupported canonical planning type.")


def planning_input_from_json(value: str | bytes) -> PlanningInput:
    return cast(PlanningInput, _read(value, PlanningInput))


def contribution_plan_result_from_json(value: str | bytes) -> ContributionPlanResult:
    return cast(ContributionPlanResult, _read(value, ContributionPlanResult))


def drift_calculation_from_json(value: str | bytes) -> DriftCalculation:
    return cast(DriftCalculation, _read(value, DriftCalculation))
