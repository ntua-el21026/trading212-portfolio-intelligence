"""Strict semantic DTOs for the frozen Trading 212 read contract."""

from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


def _provider_decimal(value: object) -> Decimal:
    if isinstance(value, (bool, float)):
        raise ValueError("provider financial numbers must not pass through binary floating point")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    else:
        raise ValueError("provider financial numbers must be JSON numbers, not numeric strings")
    if not result.is_finite():
        raise ValueError("provider financial number must be finite")
    return result


ProviderDecimal = Annotated[Decimal, BeforeValidator(_provider_decimal)]


class ProviderModel(BaseModel):
    """Unknown additive fields are retained, never interpreted as known semantics."""

    model_config = ConfigDict(extra="allow", frozen=True, populate_by_name=True)


class CurrencyMixin(ProviderModel):
    currency: str

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("currency must be an uppercase ISO-4217-style code")
        return value


class AccountCashDTO(ProviderModel):
    available_to_trade: ProviderDecimal = Field(alias="availableToTrade")
    in_pies: ProviderDecimal = Field(alias="inPies")
    reserved_for_orders: ProviderDecimal = Field(alias="reservedForOrders")


class AccountInvestmentsDTO(ProviderModel):
    current_value: ProviderDecimal = Field(alias="currentValue")
    realized_profit_loss: ProviderDecimal = Field(alias="realizedProfitLoss")
    total_cost: ProviderDecimal = Field(alias="totalCost")
    unrealized_profit_loss: ProviderDecimal = Field(alias="unrealizedProfitLoss")


class AccountSummaryDTO(CurrencyMixin):
    id: int
    cash: AccountCashDTO
    investments: AccountInvestmentsDTO
    total_value: ProviderDecimal = Field(alias="totalValue")

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: int) -> int:
        if isinstance(value, bool) or value < 0:
            raise ValueError("account id must be a non-negative provider integer")
        return value


class InstrumentDTO(ProviderModel):
    added_on: datetime = Field(alias="addedOn")
    currency_code: str = Field(alias="currencyCode")
    extended_hours: bool = Field(alias="extendedHours")
    isin: str
    max_open_quantity: ProviderDecimal = Field(alias="maxOpenQuantity")
    name: str
    short_name: str = Field(alias="shortName")
    ticker: str
    type: str
    working_schedule_id: int = Field(alias="workingScheduleId")

    @field_validator("currency_code")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("instrument currency must be uppercase and three letters")
        return value

    @field_validator("isin")
    @classmethod
    def validate_isin(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", value):
            raise ValueError("invalid ISIN syntax")
        return value

    @field_validator("added_on")
    @classmethod
    def validate_added_on(cls, value: datetime) -> datetime:
        return _utc(value)


class TimeEventDTO(ProviderModel):
    date: date
    type: str


class WorkingScheduleDTO(ProviderModel):
    id: int
    time_events: tuple[TimeEventDTO, ...] = Field(alias="timeEvents")


class ExchangeDTO(ProviderModel):
    id: int
    name: str
    working_schedules: tuple[WorkingScheduleDTO, ...] = Field(alias="workingSchedules")


class InstrumentReferenceDTO(ProviderModel):
    currency: str
    isin: str
    name: str
    ticker: str

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("instrument currency must be uppercase and three letters")
        return value


class PositionWalletImpactDTO(CurrencyMixin):
    current_value: ProviderDecimal = Field(alias="currentValue")
    fx_impact: ProviderDecimal = Field(alias="fxImpact")
    total_cost: ProviderDecimal = Field(alias="totalCost")
    unrealized_profit_loss: ProviderDecimal = Field(alias="unrealizedProfitLoss")


class PositionDTO(ProviderModel):
    average_price_paid: ProviderDecimal = Field(alias="averagePricePaid")
    created_at: datetime = Field(alias="createdAt")
    current_price: ProviderDecimal = Field(alias="currentPrice")
    instrument: InstrumentReferenceDTO
    quantity: ProviderDecimal
    quantity_available_for_trading: ProviderDecimal = Field(alias="quantityAvailableForTrading")
    quantity_in_pies: ProviderDecimal = Field(alias="quantityInPies")
    wallet_impact: PositionWalletImpactDTO = Field(alias="walletImpact")

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return _utc(value)


class OrderDTO(ProviderModel):
    created_at: datetime = Field(alias="createdAt")
    currency: str
    extended_hours: bool = Field(alias="extendedHours")
    filled_quantity: ProviderDecimal | None = Field(default=None, alias="filledQuantity")
    filled_value: ProviderDecimal | None = Field(default=None, alias="filledValue")
    id: int
    initiated_from: str = Field(alias="initiatedFrom")
    instrument: InstrumentReferenceDTO
    limit_price: ProviderDecimal | None = Field(default=None, alias="limitPrice")
    quantity: ProviderDecimal | None = None
    side: str
    status: str
    stop_price: ProviderDecimal | None = Field(default=None, alias="stopPrice")
    strategy: str
    ticker: str
    time_in_force: str = Field(alias="timeInForce")
    type: str
    value: ProviderDecimal | None = None

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_ticker_consistency(self) -> OrderDTO:
        if self.ticker != self.instrument.ticker:
            raise ValueError("top-level and instrument order tickers disagree")
        return self


class HistoricalFillWalletImpactDTO(ProviderModel):
    currency: str
    fx_impact: ProviderDecimal = Field(alias="fxImpact")
    net_value: ProviderDecimal = Field(alias="netValue")
    realised_profit_loss: ProviderDecimal | None = Field(default=None, alias="realisedProfitLoss")
    taxes: ProviderDecimal | None = None


class HistoricalFillDTO(ProviderModel):
    id: int
    price: ProviderDecimal
    quantity: ProviderDecimal
    timestamp: datetime
    trading_method: str = Field(alias="tradingMethod")
    type: str
    wallet_impact: HistoricalFillWalletImpactDTO = Field(alias="walletImpact")

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return _utc(value)


class HistoricalOrderDTO(ProviderModel):
    fill: HistoricalFillDTO | None = None
    order: OrderDTO


class TransactionDTO(CurrencyMixin):
    amount: ProviderDecimal
    date_time: datetime = Field(alias="dateTime")
    reference: str
    type: str

    @field_validator("date_time")
    @classmethod
    def validate_date_time(cls, value: datetime) -> datetime:
        return _utc(value)


class DividendDTO(CurrencyMixin):
    amount: ProviderDecimal
    amount_in_euro: ProviderDecimal | None = Field(default=None, alias="amountInEuro")
    gross_amount_per_share: ProviderDecimal = Field(alias="grossAmountPerShare")
    instrument: InstrumentReferenceDTO
    paid_on: date = Field(alias="paidOn")
    quantity: ProviderDecimal
    reference: str
    ticker: str
    ticker_currency: str = Field(alias="tickerCurrency")
    type: str

    @model_validator(mode="after")
    def validate_ticker_consistency(self) -> DividendDTO:
        if self.ticker != self.instrument.ticker:
            raise ValueError("top-level and instrument dividend tickers disagree")
        return self


class HistoricalExportDTO(ProviderModel):
    # Additive export fields can carry alternate download locations. Retaining
    # them would defeat the URL field's exclusion from diagnostic serialization.
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    data_included: dict[str, Any] = Field(alias="dataIncluded")
    download_link: str | None = Field(default=None, alias="downloadLink", repr=False, exclude=True)
    report_id: int = Field(alias="reportId", strict=True, ge=0)
    status: Literal["Queued", "Processing", "Running", "Canceled", "Failed", "Finished"]
    time_from: datetime = Field(alias="timeFrom")
    time_to: datetime = Field(alias="timeTo")

    @field_validator("data_included")
    @classmethod
    def validate_data_included(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key in _EXPORT_DATA_FLAGS:
            if key in value and not isinstance(value[key], bool):
                raise ValueError("export data-inclusion flags must be booleans")
        return {key: value[key] for key in _EXPORT_DATA_FLAGS if key in value}

    def retained_metadata(self) -> dict[str, object]:
        """Select semantics before hashing or crossing the application boundary."""
        return {
            "reportId": self.report_id,
            "status": self.status,
            "timeFrom": self.time_from,
            "timeTo": self.time_to,
            "dataIncluded": {
                key: self.data_included[key]
                for key in _EXPORT_DATA_FLAGS
                if key in self.data_included
            },
            "downloadAvailable": bool(self.download_link),
        }

    @field_validator("time_from", "time_to")
    @classmethod
    def validate_times(cls, value: datetime) -> datetime:
        return _utc(value)


_EXPORT_DATA_FLAGS = (
    "includeDividends",
    "includeInterest",
    "includeOrders",
    "includeTransactions",
)


class PaginatedDTO[ItemT](ProviderModel):
    items: tuple[ItemT, ...]
    next_page_path: str | None = Field(alias="nextPagePath")


class ProviderResponse[ItemT](BaseModel):
    """Validated response plus sanitized source metadata."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    data: ItemT
    observed_at: datetime
    correlation_id: str
    status_code: int
    rate_limit: RateLimitObservation | None = None
    source_sha256: str


class RateLimitObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    limit: int
    period_seconds: int
    remaining: int
    reset_at: datetime
    used: int

    @field_validator("limit", "period_seconds", "remaining", "used")
    @classmethod
    def non_negative(cls, value: int) -> int:
        if isinstance(value, bool) or value < 0:
            raise ValueError("rate-limit values must be non-negative integers")
        return value

    @field_validator("reset_at")
    @classmethod
    def utc_reset(cls, value: datetime) -> datetime:
        return _utc(value)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("provider timestamps must include a timezone offset")
    return value.astimezone(UTC)


def parse_rate_limit_headers(headers: dict[str, str]) -> RateLimitObservation | None:
    names = (
        "x-ratelimit-limit",
        "x-ratelimit-period",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "x-ratelimit-used",
    )
    if not any(name in headers for name in names):
        return None
    if not all(name in headers for name in names):
        raise ValueError("incomplete Trading 212 rate-limit header set")
    try:
        values = [int(headers[name]) for name in names]
    except (TypeError, ValueError) as exc:
        raise ValueError("malformed Trading 212 rate-limit headers") from exc
    if not math.isfinite(float(values[3])):
        raise ValueError("malformed Trading 212 reset timestamp")
    try:
        reset_at = datetime.fromtimestamp(values[3], tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("malformed Trading 212 reset timestamp") from exc
    return RateLimitObservation(
        limit=values[0],
        period_seconds=values[1],
        remaining=values[2],
        reset_at=reset_at,
        used=values[4],
    )
