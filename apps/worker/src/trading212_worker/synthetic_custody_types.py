"""Distinct native custody fixture contract; no Trading212-shaped input or network."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from trading212_domain.aggregation import AggregateRecord, aggregate_bound, aggregate_unique
from trading212_domain.errors import fail_validation
from trading212_domain.values import CurrencyCode


@dataclass(frozen=True, slots=True, kw_only=True)
class CustodyAsset(AggregateRecord):
    native_asset_key: str
    isin: str
    listing_code: str
    name: str
    quote_currency: CurrencyCode

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        if len(self.isin) != 12 or not self.isin.isascii() or not self.isin.isalnum():
            fail_validation("A canonical custody fixture ISIN is required.")
        if len(self.native_asset_key) > 96 or len(self.listing_code) > 32:
            fail_validation("Custody asset identity exceeds its bound.")


@dataclass(frozen=True, slots=True, kw_only=True)
class CustodyPosition(AggregateRecord):
    asset: CustodyAsset
    opened_at: datetime
    units: Decimal
    last_quote: Decimal
    mean_acquisition_quote: Decimal
    native_market_value: Decimal
    native_cost_basis: Decimal
    native_unrealized_pnl: Decimal
    valuation_at: datetime

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        if (
            self.units < 0
            or self.last_quote < 0
            or self.mean_acquisition_quote < 0
            or self.opened_at > self.valuation_at
        ):
            fail_validation("Custody position values or dates are invalid.")


@dataclass(frozen=True, slots=True, kw_only=True)
class CustodyTransferEvidence(AggregateRecord):
    counterparty_account_id: UUID
    transfer_reference: str
    principal: Decimal
    currency: CurrencyCode
    fx_rate: Decimal | None = None
    fx_base_currency: CurrencyCode | None = None
    fx_quote_currency: CurrencyCode | None = None
    fee_native_record_key: str | None = None
    fee_amount: Decimal | None = None
    fee_currency: CurrencyCode | None = None

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        if self.principal == 0 or len(self.transfer_reference) > 128:
            fail_validation("Custody transfer principal/reference is invalid.")
        if any(
            x is not None for x in (self.fx_rate, self.fx_base_currency, self.fx_quote_currency)
        ) and not all(
            x is not None for x in (self.fx_rate, self.fx_base_currency, self.fx_quote_currency)
        ):
            fail_validation("Custody transfer FX evidence is incomplete.")
        if any(
            x is not None for x in (self.fee_native_record_key, self.fee_amount, self.fee_currency)
        ) and not all(
            x is not None for x in (self.fee_native_record_key, self.fee_amount, self.fee_currency)
        ):
            fail_validation("Custody transfer fee evidence is incomplete.")
        if self.fx_rate is not None and self.fx_rate <= 0:
            fail_validation("Custody transfer FX rate must be positive.")


@dataclass(frozen=True, slots=True, kw_only=True)
class CustodyActivity(AggregateRecord):
    native_record_key: str
    kind: Literal[
        "cash_in",
        "cash_out",
        "asset_purchase",
        "asset_sale",
        "custody_transfer",
        "custody_fee",
        "unknown",
    ]
    booked_at: datetime
    published_at: datetime
    signed_cash: Decimal
    currency: CurrencyCode
    transfer: CustodyTransferEvidence | None = None

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        if len(self.native_record_key) > 96 or self.booked_at > self.published_at:
            fail_validation("Custody activity identity/dates are invalid.")
        if (self.kind == "cash_in" and self.signed_cash < 0) or (
            self.kind in ("cash_out", "custody_fee") and self.signed_cash > 0
        ):
            fail_validation("Custody cash direction differs from activity kind.")
        if self.transfer is not None and (
            self.kind != "custody_transfer"
            or self.signed_cash != self.transfer.principal
            or self.currency != self.transfer.currency
        ):
            fail_validation("Custody transfer evidence differs from original principal.")


@dataclass(frozen=True, slots=True, kw_only=True)
class CustodyAccountSnapshot(AggregateRecord):
    account_id: UUID
    currency: CurrencyCode
    valuation_at: datetime
    cash_available: Decimal
    investments_value: Decimal
    investments_cost: Decimal
    unrealized_pnl: Decimal
    net_asset_value: Decimal
    assets: tuple[CustodyAsset, ...]
    positions: tuple[CustodyPosition, ...]
    activity: tuple[CustodyActivity, ...]

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        aggregate_bound(
            len(self.assets) <= 10000
            and len(self.positions) <= 10000
            and len(self.activity) <= 10000,
            "custody.rows",
        )
        aggregate_unique(tuple(x.native_asset_key for x in self.assets), "custody.assets")
        aggregate_unique(tuple(x.listing_code for x in self.assets), "custody.listings")
        aggregate_unique(
            tuple(x.asset.native_asset_key for x in self.positions), "custody.positions"
        )
        aggregate_unique(tuple(x.native_record_key for x in self.activity), "custody.activity")
        assets = {x.native_asset_key: x for x in self.assets}
        if any(
            assets.get(x.asset.native_asset_key) != x.asset or x.valuation_at != self.valuation_at
            for x in self.positions
        ):
            fail_validation("Custody position membership or valuation differs.")
        if any(x.published_at > self.valuation_at for x in self.activity):
            fail_validation("Custody activity was not known at the fixture snapshot.")
        if any(
            x.transfer is not None and x.transfer.counterparty_account_id == self.account_id
            for x in self.activity
        ):
            fail_validation("A custody transfer cannot name its own account as counterpart.")
