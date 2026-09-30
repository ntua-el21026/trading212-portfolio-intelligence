"""Bounded whole-row aggregation pages, with activity data in its own closed variant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from trading212_domain.aggregation import (
    AggregateActivityWindow,
    AggregateMoney,
    AggregateReason,
    AggregateRecord,
    aggregate_bound,
)
from trading212_domain.aggregation_inputs import AggregateSnapshotPin
from trading212_domain.aggregation_results import (
    AggregateAccountTotal,
    AggregateComponent,
    AggregateFlowCurrencyTotal,
    AggregateFlowLeg,
    AggregateHolding,
    AggregateTransferMatch,
)
from trading212_domain.errors import fail_validation
from trading212_domain.values import CurrencyCode

if TYPE_CHECKING:
    from .aggregation import AggregateRunReceipt


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateHoldingsContext(AggregateRecord):
    input_digest: str
    result_digest: str
    reporting_currency: CurrencyCode
    source_cutoff_at: datetime
    snapshots: tuple[AggregateSnapshotPin, ...]
    securities: AggregateMoney
    cash: AggregateMoney
    total: AggregateMoney
    rounding_residual: Decimal | None
    method: Literal["account_aggregation_v1"] = "account_aggregation_v1"
    method_version: Literal["1.0.0"] = "1.0.0"
    schema_version: Literal["1.0.0"] = "1.0.0"
    numeric_profile: Literal["premium_decimal96_q18_v1"] = "premium_decimal96_q18_v1"


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateHoldingPage:
    context: AggregateHoldingsContext
    items: tuple[AggregateHolding, ...]
    total: int
    next_cursor: str | None
    view: Literal["holdings"] = "holdings"


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateComponentPage:
    context: AggregateHoldingsContext
    items: tuple[AggregateComponent, ...]
    total: int
    next_cursor: str | None
    view: Literal["components"] = "components"


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateAccountPage:
    context: AggregateHoldingsContext
    items: tuple[AggregateAccountTotal, ...]
    total: int
    next_cursor: str | None
    view: Literal["accounts"] = "accounts"


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateTransferRow:
    leg: AggregateFlowLeg
    match: AggregateTransferMatch | None


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateTransferPage:
    holdings_input_digest: str
    input_digest: str | None
    result_digest: str | None
    window: AggregateActivityWindow | None
    items: tuple[AggregateTransferRow, ...]
    currency_totals: tuple[AggregateFlowCurrencyTotal, ...]
    complete: bool
    reasons: tuple[AggregateReason, ...]
    candidate_count: int
    selected_count: int
    total: int
    next_cursor: str | None
    view: Literal["transfers"] = "transfers"


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateRunPage:
    run: AggregateRunReceipt
    page: (
        AggregateHoldingPage
        | AggregateComponentPage
        | AggregateAccountPage
        | AggregateTransferPage
        | None
    )
    view_digest: str

    def __post_init__(self) -> None:
        if self.page is not None:
            aggregate_bound(len(self.page.items) <= 100, "page")
            if self.page.total < len(self.page.items):
                fail_validation("Aggregate page count is invalid.")
