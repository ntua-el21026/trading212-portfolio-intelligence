"""Typed collection queries and signed opaque keyset cursors."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any


class PositionSort(StrEnum):
    MARKET_VALUE_DESC = "market_value_desc"
    TICKER_ASC = "ticker_asc"
    WEIGHT_DESC = "weight_desc"


class ActivityTypeFilter(StrEnum):
    ALL = "all"
    BUY = "buy"
    SELL = "sell"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    DIVIDEND = "dividend"
    INTEREST = "interest"
    FEE = "fee"
    TAX = "tax"
    FX_CONVERSION = "fx_conversion"
    UNKNOWN = "unknown"


_CANONICAL_ACTIVITY_TYPE_MEMBERSHIP: dict[ActivityTypeFilter, frozenset[str] | None] = {
    ActivityTypeFilter.ALL: None,
    ActivityTypeFilter.BUY: frozenset({"buy"}),
    ActivityTypeFilter.SELL: frozenset({"sell"}),
    ActivityTypeFilter.DEPOSIT: frozenset({"deposit"}),
    ActivityTypeFilter.WITHDRAWAL: frozenset({"withdrawal"}),
    ActivityTypeFilter.DIVIDEND: frozenset({"dividend"}),
    ActivityTypeFilter.INTEREST: frozenset({"interest"}),
    ActivityTypeFilter.FEE: frozenset({"fee"}),
    ActivityTypeFilter.TAX: frozenset({"tax_withholding"}),
    # Phase 1 does not persist a distinct FX-conversion transaction type. Do
    # not guess that a transfer or another canonical activity is an FX event.
    ActivityTypeFilter.FX_CONVERSION: frozenset(),
    ActivityTypeFilter.UNKNOWN: frozenset({"unknown_provider_activity"}),
}


def canonical_activity_type_membership(
    requested: ActivityTypeFilter,
) -> frozenset[str] | None:
    """Map the public filter vocabulary to canonical transaction membership.

    ``None`` means all canonical transaction types. An empty set is a supported
    public filter with no independently identifiable canonical member.
    """

    if not isinstance(requested, ActivityTypeFilter):
        raise ValueError("invalid activity type")
    return _CANONICAL_ACTIVITY_TYPE_MEMBERSHIP[requested]


@dataclass(frozen=True, slots=True)
class PageQuery:
    cursor: str | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if isinstance(self.limit, bool) or not 1 <= self.limit <= 100:
            raise ValueError("limit must be between 1 and 100")


@dataclass(frozen=True, slots=True)
class PositionQuery(PageQuery):
    sort: PositionSort = PositionSort.MARKET_VALUE_DESC
    search: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.sort, PositionSort):
            raise ValueError("invalid position sort")
        if self.search is not None:
            normalized = self.search.strip()
            if not normalized or len(normalized) > 80:
                raise ValueError("position search must contain between 1 and 80 characters")


@dataclass(frozen=True, slots=True)
class ActivityQuery(PageQuery):
    start_date: date | None = None
    end_date: date | None = None
    activity_type: ActivityTypeFilter = ActivityTypeFilter.ALL

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_period(self.start_date, self.end_date)
        if not isinstance(self.activity_type, ActivityTypeFilter):
            raise ValueError("invalid activity type")


@dataclass(frozen=True, slots=True)
class DividendQuery(PageQuery):
    start_date: date | None = None
    end_date: date | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_period(self.start_date, self.end_date)


@dataclass(frozen=True, slots=True)
class InstrumentQuery(PageQuery):
    search: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.search is not None:
            normalized = self.search.strip()
            if not normalized or len(normalized) > 80:
                raise ValueError("instrument search must contain between 1 and 80 characters")


@dataclass(frozen=True, slots=True)
class DividendSummaryQuery:
    start_date: date
    end_date: date
    recent_limit: int = 20

    def __post_init__(self) -> None:
        _validate_period(self.start_date, self.end_date)
        if isinstance(self.recent_limit, bool) or not 1 <= self.recent_limit <= 100:
            raise ValueError("recent_limit must be between 1 and 100")


@dataclass(frozen=True, slots=True)
class DirectAllocationQuery:
    top_n: int = 25

    def __post_init__(self) -> None:
        if isinstance(self.top_n, bool) or not 1 <= self.top_n <= 50:
            raise ValueError("top_n must be between 1 and 50")


class CursorValidationError(ValueError):
    """A cursor is malformed, unauthenticated, mismatched, or outside its lifetime."""


class CollectionSnapshotCapacityError(RuntimeError):
    """The owner has exhausted bounded durable collection-traversal capacity."""

    code = "COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED"

    def __init__(self) -> None:
        super().__init__("active collection snapshot capacity exhausted")


class CursorCodec:
    """Encode authenticated cursor state without exposing a mutable offset."""

    _VERSION = 1
    _MAC_BYTES = 24
    _MAX_TOKEN_BYTES = 2048

    def __init__(
        self,
        signing_key: bytes,
        *,
        clock: Callable[[], datetime] | None = None,
        ttl_seconds: int = 3_600,
        future_skew_seconds: int = 30,
    ) -> None:
        key = signing_key
        if len(key) < 32:
            raise ValueError("cursor signing key must contain at least 256 bits")
        if isinstance(ttl_seconds, bool) or not 60 <= ttl_seconds <= 86_400:
            raise ValueError("cursor TTL must be between 60 and 86400 seconds")
        if isinstance(future_skew_seconds, bool) or not 0 <= future_skew_seconds <= 300:
            raise ValueError("cursor future skew must be between 0 and 300 seconds")
        self._key = bytes(key)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ttl_seconds = ttl_seconds
        self._future_skew_seconds = future_skew_seconds

    def encode(
        self,
        *,
        resource: str,
        binding: str,
        read_cutoff: datetime,
        key: tuple[str, ...],
    ) -> str:
        cutoff = _utc(read_cutoff)
        payload = json.dumps(
            {
                "b": _binding_digest(binding),
                "c": cutoff.isoformat().replace("+00:00", "Z"),
                "i": _utc(self._clock()).isoformat().replace("+00:00", "Z"),
                "k": list(key),
                "r": resource,
                "v": self._VERSION,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        signature = hmac.new(self._key, payload, hashlib.sha256).digest()[: self._MAC_BYTES]
        return base64.urlsafe_b64encode(payload + signature).rstrip(b"=").decode("ascii")

    def decode(
        self,
        token: str,
        *,
        resource: str,
        binding: str,
        key_size: int,
    ) -> tuple[datetime, tuple[str, ...]]:
        if not token or len(token) > self._MAX_TOKEN_BYTES:
            raise CursorValidationError("invalid cursor")
        try:
            padded = token + "=" * (-len(token) % 4)
            raw = base64.b64decode(padded, altchars=b"-_", validate=True)
            payload, signature = raw[: -self._MAC_BYTES], raw[-self._MAC_BYTES :]
            expected = hmac.new(self._key, payload, hashlib.sha256).digest()[: self._MAC_BYTES]
            if not payload or not hmac.compare_digest(signature, expected):
                raise CursorValidationError("invalid cursor")
            value: Any = json.loads(payload)
            if not isinstance(value, dict):
                raise CursorValidationError("invalid cursor")
            key = value.get("k")
            if (
                value.get("v") != self._VERSION
                or value.get("r") != resource
                or value.get("b") != _binding_digest(binding)
                or not isinstance(key, list)
                or len(key) != key_size
                or any(not isinstance(item, str) for item in key)
            ):
                raise CursorValidationError("invalid cursor")
            cutoff_text = value.get("c")
            issued_text = value.get("i")
            if not isinstance(cutoff_text, str) or not isinstance(issued_text, str):
                raise CursorValidationError("invalid cursor")
            cutoff = datetime.fromisoformat(cutoff_text.replace("Z", "+00:00"))
            cutoff = _utc(cutoff)
            issued_at = _utc(datetime.fromisoformat(issued_text.replace("Z", "+00:00")))
            age_seconds = (_utc(self._clock()) - issued_at).total_seconds()
            if age_seconds > self._ttl_seconds or age_seconds < -self._future_skew_seconds:
                raise CursorValidationError("invalid cursor")
            return cutoff, tuple(key)
        except CursorValidationError:
            raise
        except (UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise CursorValidationError("invalid cursor") from exc


def cursor_binding(*parts: object) -> str:
    """Return a canonical binding for account, immutable read set, and filters."""

    values: list[str] = []
    for part in parts:
        if isinstance(part, (date, datetime)):
            values.append(part.isoformat())
        elif isinstance(part, StrEnum):
            values.append(part.value)
        elif part is None:
            values.append("")
        else:
            values.append(str(part))
    return "\x1f".join(values)


def _binding_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cursor cutoff must be timezone-aware")
    return value.astimezone(UTC)


def _validate_period(start: date | None, end: date | None) -> None:
    if start is not None and end is not None and end < start:
        raise ValueError("end_date must not precede start_date")
