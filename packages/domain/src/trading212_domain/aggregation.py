"""Closed account aggregation vocabulary and immutable selection; no source lookup."""

from __future__ import annotations

import re
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from types import UnionType
from typing import Any, Literal, TypeAliasType, Union, get_args, get_origin, get_type_hints
from uuid import UUID

from .enums import QualityState, ValueOrigin
from .errors import DomainError, ErrorCode, fail_validation
from .values import CurrencyCode, exact_decimal, require_bounded_text, require_utc

AGGREGATION_METHOD = "account_aggregation_v1"
AGGREGATION_VERSION = "1.0.0"
AGGREGATION_NUMERIC_PROFILE = "premium_decimal96_q18_v1"
MAX_AGGREGATE_ACCOUNTS = 8
MAX_AGGREGATE_HOLDINGS = 10000
MAX_AGGREGATE_CURRENCIES = 32
MAX_AGGREGATE_FX_BINDINGS = 256
MAX_AGGREGATE_ACTIVITY = 10000
MAX_AGGREGATE_BYTES = 32 * 1024 * 1024
MAX_AGGREGATE_RESPONSE_BYTES = 2 * 1024 * 1024


class AggregateReason(StrEnum):
    VALUE_UNAVAILABLE = "value_unavailable"
    FX_MISSING = "fx_missing"
    NOT_REQUESTED = "not_requested"
    COVERAGE_INCOMPLETE = "coverage_incomplete"
    UNMATCHED_TRANSFER = "unmatched_transfer"
    AMBIGUOUS_TRANSFER = "ambiguous_transfer"
    TRANSFER_PROOF_INCOMPLETE = "transfer_proof_incomplete"
    AMBIGUOUS_REVISION = "ambiguous_revision"
    UNKNOWN_ACTIVITY = "unknown_activity"
    ZERO_TOTAL = "zero_total"


class AggregateView(StrEnum):
    HOLDINGS = "holdings"
    COMPONENTS = "components"
    ACCOUNTS = "accounts"
    TRANSFERS = "transfers"


def aggregate_bound(condition: bool, field: str) -> None:
    if not condition:
        raise DomainError(ErrorCode.INPUT_BOUND_EXCEEDED, "Aggregation capacity exceeded.", field)


def aggregate_digest(value: str) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        fail_validation("An aggregation digest is required.", field="digest")


def aggregate_unique(values: tuple[object, ...], field: str) -> None:
    if len(set(values)) != len(values):
        fail_validation("Aggregation identities are duplicated.", field=field)


@lru_cache(maxsize=64)
def aggregate_hints(kind: type[object]) -> dict[str, Any]:
    return get_type_hints(kind)


def _typed(value: object, annotation: Any) -> bool:
    if isinstance(annotation, TypeAliasType):
        return _typed(value, annotation.__value__)
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, UnionType):
        return any(_typed(value, item) for item in args)
    if origin is Literal:
        return any(type(value) is type(item) and value == item for item in args)
    if origin is tuple:
        return (
            type(value) is tuple
            and len(value) <= MAX_AGGREGATE_ACTIVITY + 256
            and all(_typed(item, args[0]) for item in value)
        )
    return isinstance(annotation, type) and type(value) is annotation


class AggregateRecord:
    __slots__ = ()

    def __post_init__(self) -> None:
        if not is_dataclass(self):
            fail_validation("A closed aggregation record is required.")
        hints = aggregate_hints(type(self))
        for field in fields(self):
            value = getattr(self, field.name)
            if not _typed(value, hints[field.name]):
                fail_validation("Aggregation field type differs.", field=field.name)
            if type(value) is datetime:
                object.__setattr__(self, field.name, require_utc(value))
            elif type(value) is Decimal:
                exact_decimal(value, field=field.name)
            elif type(value) is str:
                require_bounded_text(value, field=field.name, maximum=256)
                if field.name.endswith("digest"):
                    aggregate_digest(value)
            elif type(value) is int:
                aggregate_bound(0 <= value <= 2147483647, field.name)


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateMember(AggregateRecord):
    account_id: UUID
    portfolio_snapshot_id: UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateSelectionContent(AggregateRecord):
    name: str
    members: tuple[AggregateMember, ...]
    reporting_currency: CurrencyCode
    source_cutoff_at: datetime
    economic_identity_policy: Literal["canonical_instrument_v1"] = "canonical_instrument_v1"

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        require_bounded_text(self.name, field="name", maximum=120)
        aggregate_bound(1 <= len(self.members) <= MAX_AGGREGATE_ACCOUNTS, "members")
        aggregate_unique(tuple(x.account_id for x in self.members), "members.account")
        aggregate_unique(tuple(x.portfolio_snapshot_id for x in self.members), "members.snapshot")


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateFxBinding(AggregateRecord):
    account_id: UUID
    currency: CurrencyCode
    fx_observation_id: UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateActivityWindow(AggregateRecord):
    start_at: datetime
    end_at: datetime

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        if self.start_at >= self.end_at:
            fail_validation("An ordered aggregation activity window is required.")
        aggregate_bound((self.end_at - self.start_at).total_seconds() <= 3660 * 86400, "window")


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateMoney(AggregateRecord):
    currency: CurrencyCode
    value: Decimal | None
    known_value: Decimal
    known_count: int
    total_count: int
    quality: QualityState
    reason: AggregateReason | None
    origin: ValueOrigin = ValueOrigin.DERIVED_DETERMINISTIC

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        if (
            self.known_count > self.total_count
            or ((self.value is not None) != (self.known_count == self.total_count))
            or ((self.value is None) != (self.reason is not None))
        ):
            fail_validation("Aggregation money availability differs from coverage.")
        if self.value is not None and self.value != self.known_value:
            fail_validation("Complete aggregation money must equal the known sum.")
        if self.value is None and self.quality not in (
            QualityState.PARTIAL,
            QualityState.UNRECONCILED,
            QualityState.FAILED,
        ):
            fail_validation("Incomplete aggregation money cannot claim complete quality.")
