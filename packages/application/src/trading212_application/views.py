"""Canonical Phase 1 application view contracts shared by API and MCP."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum


class ViewQuality(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    PARTIAL = "partial"
    ESTIMATED = "estimated"
    UNRECONCILED = "unreconciled"
    FAILED = "failed"


class Availability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class QualityView:
    state: ViewQuality
    as_of: datetime
    source_timestamp: datetime
    freshness_threshold_seconds: int
    warnings: tuple[str, ...] = ()
    missing_inputs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value in (self.as_of, self.source_timestamp):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("quality timestamps must be timezone-aware")
        if self.freshness_threshold_seconds < 0:
            raise ValueError("freshness threshold must be non-negative")


@dataclass(frozen=True, slots=True)
class MetricView:
    value: Decimal | None
    currency: str
    availability: Availability
    calculation_version: str
    methodology: str
    provenance: tuple[str, ...]
    assumptions: tuple[str, ...] = ()
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("metric currency must be an uppercase three-letter code")
        if self.value is not None and not self.value.is_finite():
            raise ValueError("metric value must be finite")
        if (self.value is None) != (self.availability is Availability.UNAVAILABLE):
            raise ValueError("metric value and availability disagree")


@dataclass(frozen=True, slots=True)
class AccountView:
    id: str
    display_name: str
    provider: str
    environment: str
    account_type: str
    reporting_currency: str
    connection_state: str
    last_refresh_at: datetime | None


@dataclass(frozen=True, slots=True)
class AccountSummaryView:
    account: AccountView
    total_value: MetricView
    cash_balance: MetricView
    invested_value: MetricView
    net_contributions: MetricView
    dividends_received: MetricView
    realized_profit_loss: MetricView
    unrealized_profit_loss: MetricView
    quality: QualityView
    position_count: int


@dataclass(frozen=True, slots=True)
class PositionView:
    id: str
    ticker: str
    name: str
    instrument_type: str
    quantity: Decimal
    trading_currency: str
    current_price: Decimal | None
    market_value: MetricView
    provider_cost_basis: MetricView
    provider_unrealized_profit_loss: MetricView
    direct_weight: Decimal | None
    quality: QualityView


@dataclass(frozen=True, slots=True)
class ActivityView:
    id: str
    occurred_at: datetime
    activity_type: str
    direction: str
    amount: MetricView
    ticker: str | None
    quantity: Decimal | None
    description: str
    quality: QualityView


@dataclass(frozen=True, slots=True)
class DividendView:
    id: str
    paid_on: date
    ticker: str
    net_amount: MetricView
    gross_amount: MetricView
    withholding_tax: MetricView
    quantity: Decimal | None
    quality: QualityView


@dataclass(frozen=True, slots=True)
class OrderView:
    id: str
    created_at: datetime
    ticker: str
    side: str
    order_type: str
    status: str
    quantity: Decimal | None
    filled_quantity: Decimal | None
    limit_price: Decimal | None
    observed_value: MetricView
    quality: QualityView

    def __post_init__(self) -> None:
        utc(self.created_at)
        for value in (self.quantity, self.filled_quantity, self.limit_price):
            if value is not None and not value.is_finite():
                raise ValueError("order numeric observations must be finite")


@dataclass(frozen=True, slots=True)
class AllocationView:
    id: str
    label: str
    asset_type: str
    market_value: MetricView
    weight: Decimal | None
    weight_availability: Availability


@dataclass(frozen=True, slots=True)
class SnapshotView:
    id: str
    valuation_at: datetime
    source_cutoff_at: datetime
    reporting_currency: str
    total_value: MetricView
    cash_value: MetricView
    invested_value: MetricView
    net_contributions: MetricView
    quality: QualityView


@dataclass(frozen=True, slots=True)
class SnapshotComparisonView:
    start: SnapshotView
    end: SnapshotView
    value_change: MetricView
    net_external_flows: MetricView
    investment_result: MetricView
    reconciliation_residual: MetricView
    quality: QualityView


@dataclass(frozen=True, slots=True)
class ReconciliationIssueView:
    id: str
    issue_type: str
    severity: str
    status: str
    summary: str
    expected_value: Decimal | None
    observed_value: Decimal | None
    residual: Decimal | None
    tolerance: Decimal | None
    currency: str | None


@dataclass(frozen=True, slots=True)
class ReconciliationView:
    status: str
    evaluated_at: datetime
    algorithm_version: str
    tolerance_version: str
    issues: tuple[ReconciliationIssueView, ...]
    quality: QualityView


@dataclass(frozen=True, slots=True)
class RefreshRunView:
    id: str
    account_id: str
    status: str
    requested_at: datetime
    completed_at: datetime | None
    correlation_id: str
    capabilities: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Page[PageItem]:
    items: tuple[PageItem, ...]
    next_cursor: str | None
    limit: int
    total: int


def paginate[ItemT](items: Sequence[ItemT], *, cursor: str | None, limit: int) -> Page[ItemT]:
    if isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    offset = 0
    if cursor is not None:
        match = re.fullmatch(r"p1:([0-9]{1,9})", cursor)
        if match is None:
            raise ValueError("invalid cursor")
        offset = int(match.group(1))
    if offset > len(items):
        raise ValueError("cursor is outside the result set")
    selected = tuple(items[offset : offset + limit])
    next_offset = offset + len(selected)
    next_cursor = f"p1:{next_offset}" if next_offset < len(items) else None
    return Page(selected, next_cursor, limit, len(items))


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)
