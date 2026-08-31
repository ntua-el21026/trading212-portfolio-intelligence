"""Exact portfolio aggregation, cost accounting, allocation, and comparison."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from trading212_domain import (
    BrokerAccountId,
    CalculationMetadata,
    CurrencyCode,
    DomainError,
    DomainWarning,
    ErrorCode,
    FxRate,
    Instant,
    ListingId,
    Money,
    PortfolioSnapshot,
    Price,
    QualityState,
    Quantity,
    Ratio,
    SnapshotCash,
    SnapshotId,
    SnapshotPosition,
    TransactionType,
    ValueOrigin,
)

from ._decimal import add, divide, multiply, persisted_decimal, ratio, subtract, total
from .ledger import LedgerProjection
from .quality import combine_quality, degrade_quality

PORTFOLIO_METHOD_ID = "portfolio_snapshot"
PORTFOLIO_VERSION = "1.0.0"
ALLOCATION_METHOD_ID = "direct_allocation"
ALLOCATION_VERSION = "1.0.0"
COST_METHOD_ID = "weighted_average_acquisition"
COST_VERSION = "1.0.0"
COMPARISON_METHOD_ID = "snapshot_change"
COMPARISON_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class FxQuote:
    rate: FxRate
    quality_state: QualityState = QualityState.FRESH


@dataclass(frozen=True, slots=True)
class FxConversion:
    source_value: Money
    reporting_currency: CurrencyCode
    converted_value: Money | None
    rate: FxRate | None
    inverted: bool
    quality_state: QualityState
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ValuedPositionInput:
    account_id: BrokerAccountId
    listing_id: ListingId
    quantity: Quantity
    valuation_currency: CurrencyCode
    provider_market_value: Money | None = None
    derived_market_value: Money | None = None
    provider_cost_basis: Money | None = None
    derived_acquisition_cost: Money | None = None
    provider_unrealized_pnl: Money | None = None
    derived_unrealized_pnl: Money | None = None
    mapped: bool = True
    quality_state: QualityState = QualityState.FRESH

    def __post_init__(self) -> None:
        values = (
            self.provider_market_value,
            self.derived_market_value,
            self.provider_cost_basis,
            self.derived_acquisition_cost,
            self.provider_unrealized_pnl,
            self.derived_unrealized_pnl,
        )
        if any(value is not None and value.currency != self.valuation_currency for value in values):
            raise DomainError(
                ErrorCode.CURRENCY_MISMATCH,
                "position values must use valuation_currency",
                "valuation_currency",
            )


@dataclass(frozen=True, slots=True)
class CashComponentInput:
    account_id: BrokerAccountId
    component_key: str
    amount: Money
    quality_state: QualityState = QualityState.FRESH

    def __post_init__(self) -> None:
        if not self.component_key or len(self.component_key) > 180:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                "cash component key is required and bounded",
                "component_key",
            )


@dataclass(frozen=True, slots=True)
class PortfolioComponent:
    component_key: str
    component_type: Literal["position", "cash"]
    listing_id: ListingId | None
    source_value: Money | None
    reporting_value: Money | None
    value_origin: ValueOrigin
    mapped: bool
    quality_state: QualityState
    fx_rate: FxRate | None
    fx_inverted: bool


@dataclass(frozen=True, slots=True)
class CoveredMoneyMetric:
    value: Money | None
    known_subtotal: Money
    complete: bool
    quality_state: QualityState
    missing_components: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CostPnlSummary:
    method_id: str
    version: str
    provider_cost_basis: CoveredMoneyMetric
    derived_acquisition_cost: CoveredMoneyMetric
    provider_unrealized_pnl: CoveredMoneyMetric
    derived_unrealized_pnl: CoveredMoneyMetric


@dataclass(frozen=True, slots=True)
class PortfolioAggregate:
    method_id: str
    version: str
    account_id: BrokerAccountId
    valuation_at: Instant
    source_cutoff_at: Instant
    reporting_currency: CurrencyCode
    components: tuple[PortfolioComponent, ...]
    cash_total: Money | None
    invested_total: Money | None
    portfolio_total: Money | None
    known_cash_subtotal: Money
    known_invested_subtotal: Money
    known_portfolio_subtotal: Money
    component_sum_residual: Money | None
    cost_and_pnl: CostPnlSummary
    quality_state: QualityState
    warnings: tuple[DomainWarning, ...]
    missing_inputs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AccountingSummary:
    account_id: BrokerAccountId
    reporting_currency: CurrencyCode
    gross_deposits: CoveredMoneyMetric
    gross_withdrawals: CoveredMoneyMetric
    net_external_contributions: CoveredMoneyMetric
    dividends: CoveredMoneyMetric
    fees_and_taxes: CoveredMoneyMetric
    quality_state: QualityState
    warnings: tuple[DomainWarning, ...]


@dataclass(frozen=True, slots=True)
class AllocationLine:
    component_key: str
    component_type: Literal["position", "cash"]
    listing_id: ListingId | None
    value: Money
    weight: Ratio
    mapped: bool


@dataclass(frozen=True, slots=True)
class DirectAllocation:
    method_id: str
    version: str
    account_id: BrokerAccountId
    reporting_currency: CurrencyCode
    available: bool
    lines: tuple[AllocationLine, ...]
    residual: Ratio | None
    quality_state: QualityState
    warnings: tuple[DomainWarning, ...]
    missing_inputs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SnapshotValue:
    account_id: BrokerAccountId
    valuation_at: Instant
    reporting_currency: CurrencyCode
    calculation_version: str
    portfolio_total: Money | None
    quality_state: QualityState

    def __post_init__(self) -> None:
        if (
            self.portfolio_total is not None
            and self.portfolio_total.currency != self.reporting_currency
        ):
            raise DomainError(
                ErrorCode.CURRENCY_MISMATCH,
                "snapshot total must use reporting currency",
                "portfolio_total",
            )


@dataclass(frozen=True, slots=True)
class SnapshotComparison:
    method_id: str
    version: str
    account_id: BrokerAccountId
    reporting_currency: CurrencyCode
    beginning_at: Instant
    ending_at: Instant
    beginning_value: Money | None
    ending_value: Money | None
    total_change: Money | None
    net_external_contributions: Money | None
    investment_gain: Money | None
    reconciliation_residual: Money | None
    quality_state: QualityState
    warnings: tuple[DomainWarning, ...]
    missing_inputs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TradeAccountingEvent:
    account_id: BrokerAccountId
    listing_id: ListingId
    transaction_type: TransactionType
    quantity: Quantity
    gross_trade_value: Money
    fees: Money
    taxes: Money
    occurred_at: Instant
    event_key: str = ""
    quality_state: QualityState = QualityState.FRESH

    def __post_init__(self) -> None:
        if self.transaction_type not in (TransactionType.BUY, TransactionType.SELL):
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                "weighted-average events must be buys or sells",
                "transaction_type",
            )
        if self.quantity.value <= 0:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                "trade quantity must be positive",
                "quantity",
            )
        values = (self.gross_trade_value, self.fees, self.taxes)
        if any(value.currency != self.gross_trade_value.currency for value in values):
            raise DomainError(
                ErrorCode.CURRENCY_MISMATCH,
                "trade accounting values must use one currency",
                "currency",
            )
        if any(value.amount < 0 for value in values):
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                "trade accounting value magnitudes must not be negative",
                "amount",
            )
        if len(self.event_key) > 180:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                "event key must be bounded",
                "event_key",
            )


@dataclass(frozen=True, slots=True)
class WeightedAverageCostResult:
    method_id: str
    version: str
    account_id: BrokerAccountId
    listing_id: ListingId
    currency: CurrencyCode | None
    ending_quantity: Quantity | None
    acquisition_cost: Money | None
    average_unit_cost: Price | None
    realized_pnl: Money | None
    history_complete: bool
    quality_state: QualityState
    warnings: tuple[DomainWarning, ...]
    missing_inputs: tuple[str, ...]
    assumptions: tuple[str, ...]


def calculate_position_market_value(quantity: Quantity, price: Price) -> Money:
    """Multiply without intermediate rounding, then persist at NUMERIC(38,18)."""

    return Money(persisted_decimal(multiply(quantity.value, price.value)), price.quote_currency)


def calculate_unrealized_pnl(market_value: Money, acquisition_cost: Money) -> Money:
    if market_value.currency != acquisition_cost.currency:
        raise DomainError(
            ErrorCode.CURRENCY_MISMATCH,
            "market value and acquisition cost currencies differ",
            "currency",
        )
    return Money(
        persisted_decimal(subtract(market_value.amount, acquisition_cost.amount)),
        market_value.currency,
    )


def _eligible_quotes(
    quotes: tuple[FxQuote, ...],
    base: CurrencyCode,
    quote: CurrencyCode,
    cutoff: Instant,
) -> tuple[tuple[FxQuote, bool], ...]:
    candidates: list[tuple[FxQuote, bool]] = []
    for candidate in quotes:
        rate = candidate.rate
        if rate.observed_at > cutoff:
            continue
        if rate.base_currency == base and rate.quote_currency == quote:
            candidates.append((candidate, False))
        elif rate.base_currency == quote and rate.quote_currency == base:
            candidates.append((candidate, True))
    return tuple(candidates)


def convert_money(
    value: Money,
    *,
    reporting_currency: CurrencyCode,
    fx_quotes: tuple[FxQuote, ...],
    source_cutoff_at: Instant,
) -> FxConversion:
    """Convert with the latest explicit on-or-before-cutoff directional FX observation."""

    if value.currency == reporting_currency:
        return FxConversion(
            source_value=value,
            reporting_currency=reporting_currency,
            converted_value=Money(persisted_decimal(value.amount), reporting_currency),
            rate=None,
            inverted=False,
            quality_state=QualityState.FRESH,
        )

    candidates = _eligible_quotes(
        fx_quotes,
        value.currency,
        reporting_currency,
        source_cutoff_at,
    )
    if not candidates:
        return FxConversion(
            source_value=value,
            reporting_currency=reporting_currency,
            converted_value=None,
            rate=None,
            inverted=False,
            quality_state=QualityState.PARTIAL,
            unavailable_reason="missing_fx_rate_at_source_cutoff",
        )

    latest_at = max(item[0].rate.observed_at for item in candidates)
    latest = tuple(item for item in candidates if item[0].rate.observed_at == latest_at)
    effective_rates = tuple(
        divide(Decimal(1), item.rate.rate) if inverted else item.rate.rate
        for item, inverted in latest
    )
    if len(set(effective_rates)) != 1:
        return FxConversion(
            source_value=value,
            reporting_currency=reporting_currency,
            converted_value=None,
            rate=None,
            inverted=False,
            quality_state=QualityState.UNRECONCILED,
            unavailable_reason="ambiguous_fx_rates_at_source_cutoff",
        )

    selected, inverted = min(
        latest,
        key=lambda item: (item[0].rate.source, str(item[0].rate.rate), item[1]),
    )
    effective_rate = divide(Decimal(1), selected.rate.rate) if inverted else selected.rate.rate
    converted = Money(
        persisted_decimal(multiply(value.amount, effective_rate)),
        reporting_currency,
    )
    return FxConversion(
        source_value=value,
        reporting_currency=reporting_currency,
        converted_value=converted,
        rate=selected.rate,
        inverted=inverted,
        quality_state=combine_quality(item[0].quality_state for item in latest),
    )


def _selected_position_value(position: ValuedPositionInput) -> tuple[Money | None, ValueOrigin]:
    if position.provider_market_value is not None:
        return position.provider_market_value, ValueOrigin.OBSERVED_PROVIDER
    if position.derived_market_value is not None:
        return position.derived_market_value, ValueOrigin.DERIVED_DETERMINISTIC
    return None, ValueOrigin.UNAVAILABLE


def _covered_metric(
    *,
    named_values: tuple[tuple[str, Money | None, QualityState], ...],
    reporting_currency: CurrencyCode,
    fx_quotes: tuple[FxQuote, ...],
    source_cutoff_at: Instant,
    base_quality: QualityState,
) -> CoveredMoneyMetric:
    known: list[Decimal] = []
    missing: list[str] = []
    states: list[QualityState] = [base_quality]
    for key, value, state in named_values:
        states.append(state)
        if value is None:
            missing.append(key)
            continue
        conversion = convert_money(
            value,
            reporting_currency=reporting_currency,
            fx_quotes=fx_quotes,
            source_cutoff_at=source_cutoff_at,
        )
        states.append(conversion.quality_state)
        if conversion.converted_value is None:
            missing.append(f"{key}:fx")
        else:
            known.append(conversion.converted_value.amount)
    subtotal = Money(persisted_decimal(total(known)), reporting_currency)
    complete = not missing
    quality = combine_quality(states)
    if not complete:
        quality = degrade_quality(quality, QualityState.PARTIAL)
    return CoveredMoneyMetric(
        value=subtotal if complete else None,
        known_subtotal=subtotal,
        complete=complete,
        quality_state=quality,
        missing_components=tuple(missing),
    )


def summarize_cost_and_pnl(
    positions: tuple[ValuedPositionInput, ...],
    *,
    reporting_currency: CurrencyCode,
    fx_quotes: tuple[FxQuote, ...],
    source_cutoff_at: Instant,
) -> CostPnlSummary:
    base_quality = combine_quality(position.quality_state for position in positions)

    def values_for(attribute: str) -> tuple[tuple[str, Money | None, QualityState], ...]:
        return tuple(
            (
                f"position:{position.listing_id}",
                getattr(position, attribute),
                position.quality_state,
            )
            for position in sorted(positions, key=lambda item: str(item.listing_id))
        )

    return CostPnlSummary(
        method_id=COST_METHOD_ID,
        version=COST_VERSION,
        provider_cost_basis=_covered_metric(
            named_values=values_for("provider_cost_basis"),
            reporting_currency=reporting_currency,
            fx_quotes=fx_quotes,
            source_cutoff_at=source_cutoff_at,
            base_quality=base_quality,
        ),
        derived_acquisition_cost=_covered_metric(
            named_values=values_for("derived_acquisition_cost"),
            reporting_currency=reporting_currency,
            fx_quotes=fx_quotes,
            source_cutoff_at=source_cutoff_at,
            base_quality=base_quality,
        ),
        provider_unrealized_pnl=_covered_metric(
            named_values=values_for("provider_unrealized_pnl"),
            reporting_currency=reporting_currency,
            fx_quotes=fx_quotes,
            source_cutoff_at=source_cutoff_at,
            base_quality=base_quality,
        ),
        derived_unrealized_pnl=_covered_metric(
            named_values=values_for("derived_unrealized_pnl"),
            reporting_currency=reporting_currency,
            fx_quotes=fx_quotes,
            source_cutoff_at=source_cutoff_at,
            base_quality=base_quality,
        ),
    )


def aggregate_portfolio(
    *,
    account_id: BrokerAccountId,
    positions: tuple[ValuedPositionInput, ...],
    cash_components: tuple[CashComponentInput, ...],
    reporting_currency: CurrencyCode,
    fx_quotes: tuple[FxQuote, ...],
    valuation_at: Instant,
    source_cutoff_at: Instant,
) -> PortfolioAggregate:
    """Aggregate one account without treating missing values or FX as zero."""

    if source_cutoff_at > valuation_at:
        raise ValueError("source cutoff cannot follow valuation")
    if any(item.account_id != account_id for item in positions) or any(
        item.account_id != account_id for item in cash_components
    ):
        raise ValueError("portfolio input contains a different broker account")
    position_keys = tuple(str(item.listing_id) for item in positions)
    cash_keys = tuple(item.component_key for item in cash_components)
    if len(set(position_keys)) != len(position_keys):
        raise ValueError("portfolio input contains a duplicate listing")
    if len(set(cash_keys)) != len(cash_keys):
        raise ValueError("portfolio input contains a duplicate cash component key")

    components: list[PortfolioComponent] = []
    warnings: list[DomainWarning] = []
    missing: list[str] = []
    states: list[QualityState] = []

    for position in sorted(positions, key=lambda item: str(item.listing_id)):
        source_value, origin = _selected_position_value(position)
        reporting_value: Money | None = None
        fx_rate: FxRate | None = None
        fx_inverted = False
        component_quality = position.quality_state
        key = f"position:{position.listing_id}"
        if source_value is None:
            missing.append(f"{key}:market_value")
            component_quality = degrade_quality(component_quality, QualityState.PARTIAL)
        else:
            conversion = convert_money(
                source_value,
                reporting_currency=reporting_currency,
                fx_quotes=fx_quotes,
                source_cutoff_at=source_cutoff_at,
            )
            reporting_value = conversion.converted_value
            fx_rate = conversion.rate
            fx_inverted = conversion.inverted
            component_quality = combine_quality((component_quality, conversion.quality_state))
            if reporting_value is None:
                missing.append(f"{key}:fx")
                warnings.append(
                    DomainWarning(
                        conversion.unavailable_reason or "missing_fx_rate",
                        "Position value is excluded from the reporting-currency total.",
                        (str(position.listing_id),),
                    )
                )
        if not position.mapped:
            component_quality = degrade_quality(component_quality, QualityState.PARTIAL)
            warnings.append(
                DomainWarning(
                    "unmapped_instrument",
                    "Observed value remains in totals but classification is unavailable.",
                    (str(position.listing_id),),
                )
            )
        states.append(component_quality)
        components.append(
            PortfolioComponent(
                component_key=key,
                component_type="position",
                listing_id=position.listing_id,
                source_value=source_value,
                reporting_value=reporting_value,
                value_origin=origin,
                mapped=position.mapped,
                quality_state=component_quality,
                fx_rate=fx_rate,
                fx_inverted=fx_inverted,
            )
        )

    for cash in sorted(cash_components, key=lambda item: item.component_key):
        conversion = convert_money(
            cash.amount,
            reporting_currency=reporting_currency,
            fx_quotes=fx_quotes,
            source_cutoff_at=source_cutoff_at,
        )
        key = f"cash:{cash.component_key}"
        component_quality = combine_quality((cash.quality_state, conversion.quality_state))
        if conversion.converted_value is None:
            missing.append(f"{key}:fx")
            warnings.append(
                DomainWarning(
                    conversion.unavailable_reason or "missing_fx_rate",
                    "Cash value is excluded from the reporting-currency total.",
                    (cash.component_key,),
                )
            )
        states.append(component_quality)
        components.append(
            PortfolioComponent(
                component_key=key,
                component_type="cash",
                listing_id=None,
                source_value=cash.amount,
                reporting_value=conversion.converted_value,
                value_origin=ValueOrigin.OBSERVED_PROVIDER,
                mapped=True,
                quality_state=component_quality,
                fx_rate=conversion.rate,
                fx_inverted=conversion.inverted,
            )
        )

    cash_amounts = [
        item.reporting_value.amount
        for item in components
        if item.component_type == "cash" and item.reporting_value is not None
    ]
    invested_amounts = [
        item.reporting_value.amount
        for item in components
        if item.component_type == "position" and item.reporting_value is not None
    ]
    known_cash = Money(persisted_decimal(total(cash_amounts)), reporting_currency)
    known_invested = Money(persisted_decimal(total(invested_amounts)), reporting_currency)
    known_total = Money(
        persisted_decimal(add(known_cash.amount, known_invested.amount)),
        reporting_currency,
    )
    cash_complete = all(
        item.reporting_value is not None for item in components if item.component_type == "cash"
    )
    invested_complete = all(
        item.reporting_value is not None for item in components if item.component_type == "position"
    )
    cash_total = known_cash if cash_complete else None
    invested_total = known_invested if invested_complete else None
    portfolio_total = known_total if cash_complete and invested_complete else None
    residual = (
        Money(
            persisted_decimal(
                subtract(portfolio_total.amount, add(known_cash.amount, known_invested.amount))
            ),
            reporting_currency,
        )
        if portfolio_total is not None
        else None
    )
    quality = combine_quality(states)
    if missing:
        quality = degrade_quality(quality, QualityState.PARTIAL)

    cost_and_pnl = summarize_cost_and_pnl(
        positions,
        reporting_currency=reporting_currency,
        fx_quotes=fx_quotes,
        source_cutoff_at=source_cutoff_at,
    )
    return PortfolioAggregate(
        method_id=PORTFOLIO_METHOD_ID,
        version=PORTFOLIO_VERSION,
        account_id=account_id,
        valuation_at=valuation_at,
        source_cutoff_at=source_cutoff_at,
        reporting_currency=reporting_currency,
        components=tuple(components),
        cash_total=cash_total,
        invested_total=invested_total,
        portfolio_total=portfolio_total,
        known_cash_subtotal=known_cash,
        known_invested_subtotal=known_invested,
        known_portfolio_subtotal=known_total,
        component_sum_residual=residual,
        cost_and_pnl=cost_and_pnl,
        quality_state=quality,
        warnings=tuple(warnings),
        missing_inputs=tuple(missing),
    )


def build_portfolio_snapshot(
    aggregate: PortfolioAggregate,
    *,
    snapshot_id: SnapshotId,
    positions: tuple[ValuedPositionInput, ...],
    cash_components: tuple[CashComponentInput, ...],
    calculation: CalculationMetadata,
    accounting: AccountingSummary | None = None,
) -> PortfolioSnapshot:
    """Materialize the immutable domain snapshot after metadata is assigned."""

    if calculation.calculation_name != PORTFOLIO_METHOD_ID:
        raise ValueError("calculation metadata is not for a portfolio snapshot")
    if calculation.version != aggregate.version:
        raise ValueError("calculation version does not match aggregate version")
    if (
        calculation.valuation_at != aggregate.valuation_at
        or calculation.source_cutoff_at != aggregate.source_cutoff_at
        or calculation.reporting_currency != aggregate.reporting_currency
    ):
        raise ValueError("calculation time/currency metadata does not match aggregate")
    if any(position.account_id != aggregate.account_id for position in positions) or any(
        cash.account_id != aggregate.account_id for cash in cash_components
    ):
        raise ValueError("snapshot input contains a different broker account")
    expected_position_ids = {
        component.listing_id
        for component in aggregate.components
        if component.component_type == "position"
    }
    expected_cash_keys = {
        component.component_key.removeprefix("cash:")
        for component in aggregate.components
        if component.component_type == "cash"
    }
    if {position.listing_id for position in positions} != expected_position_ids:
        raise ValueError("snapshot positions differ from aggregated positions")
    if {cash.component_key for cash in cash_components} != expected_cash_keys:
        raise ValueError("snapshot cash components differ from aggregated cash")
    required_quality = aggregate.quality_state
    if accounting is not None:
        if accounting.account_id != aggregate.account_id:
            raise ValueError("snapshot accounting belongs to a different broker account")
        if accounting.reporting_currency != aggregate.reporting_currency:
            raise ValueError("snapshot accounting uses a different reporting currency")
        required_quality = combine_quality((required_quality, accounting.quality_state))
    if (
        combine_quality((calculation.data_quality.state, required_quality))
        != calculation.data_quality.state
    ):
        raise ValueError("calculation metadata overstates snapshot quality")

    components_by_listing = {
        component.listing_id: component
        for component in aggregate.components
        if component.component_type == "position"
    }
    snapshot_positions: list[SnapshotPosition] = []
    for position in sorted(positions, key=lambda item: str(item.listing_id)):
        component = components_by_listing[position.listing_id]
        if component.value_origin is ValueOrigin.OBSERVED_PROVIDER:
            cost_basis = position.provider_cost_basis
            unrealized_pnl = position.provider_unrealized_pnl
        elif component.value_origin is ValueOrigin.DERIVED_DETERMINISTIC:
            cost_basis = position.derived_acquisition_cost
            unrealized_pnl = position.derived_unrealized_pnl
        else:
            cost_basis = None
            unrealized_pnl = None
        snapshot_positions.append(
            SnapshotPosition(
                listing_id=position.listing_id,
                quantity=position.quantity,
                market_value=component.source_value,
                quality=component.quality_state,
                origin=component.value_origin,
                cost_basis=cost_basis,
                unrealized_pnl=unrealized_pnl,
            )
        )
    cash_by_currency: dict[CurrencyCode, list[CashComponentInput]] = {}
    for cash in cash_components:
        cash_by_currency.setdefault(cash.amount.currency, []).append(cash)
    snapshot_cash = tuple(
        SnapshotCash(
            amount=Money(
                persisted_decimal(total(item.amount.amount for item in cash_by_currency[currency])),
                currency,
            ),
            quality=combine_quality(item.quality_state for item in cash_by_currency[currency]),
            origin=ValueOrigin.OBSERVED_PROVIDER,
        )
        for currency in sorted(cash_by_currency, key=str)
    )
    net_contributions = (
        accounting.net_external_contributions.value if accounting is not None else None
    )
    warnings = list(aggregate.warnings)
    if accounting is not None:
        warnings.extend(accounting.warnings)
    warnings.extend(calculation.data_quality.warnings)
    unique_warnings = tuple(dict.fromkeys(warnings))
    return PortfolioSnapshot(
        id=snapshot_id,
        broker_account_id=aggregate.account_id,
        valuation_at=aggregate.valuation_at,
        source_cutoff_at=aggregate.source_cutoff_at,
        reporting_currency=aggregate.reporting_currency,
        cash_total=aggregate.cash_total,
        invested_total=aggregate.invested_total,
        portfolio_total=aggregate.portfolio_total,
        net_contributions=net_contributions,
        positions=tuple(snapshot_positions),
        cash_components=snapshot_cash,
        calculation=calculation,
        quality=calculation.data_quality,
        warnings=unique_warnings,
    )


def _ledger_metric(
    projection: LedgerProjection,
    attribute: str,
    *,
    reporting_currency: CurrencyCode,
    fx_quotes: tuple[FxQuote, ...],
    source_cutoff_at: Instant,
) -> CoveredMoneyMetric:
    values = tuple(
        (
            f"currency:{summary.currency}",
            getattr(summary, attribute),
            projection.quality_state,
        )
        for summary in projection.currency_summaries
    )
    return _covered_metric(
        named_values=values,
        reporting_currency=reporting_currency,
        fx_quotes=fx_quotes,
        source_cutoff_at=source_cutoff_at,
        base_quality=projection.quality_state,
    )


def summarize_ledger_accounting(
    projection: LedgerProjection,
    *,
    reporting_currency: CurrencyCode,
    fx_quotes: tuple[FxQuote, ...],
    source_cutoff_at: Instant,
) -> AccountingSummary:
    """Convert ledger submetrics independently so one gap does not imply zero."""

    metrics = {
        name: _ledger_metric(
            projection,
            name,
            reporting_currency=reporting_currency,
            fx_quotes=fx_quotes,
            source_cutoff_at=source_cutoff_at,
        )
        for name in (
            "gross_deposits",
            "gross_withdrawals",
            "net_external_contributions",
            "dividends",
            "fees_and_taxes",
        )
    }
    quality = combine_quality(metric.quality_state for metric in metrics.values())
    warnings = list(projection.warnings)
    for name, metric in metrics.items():
        if not metric.complete:
            warnings.append(
                DomainWarning(
                    "accounting_metric_partial",
                    "An accounting submetric is unavailable because inputs or FX are missing.",
                    (name,),
                )
            )
    return AccountingSummary(
        account_id=projection.account_id,
        reporting_currency=reporting_currency,
        gross_deposits=metrics["gross_deposits"],
        gross_withdrawals=metrics["gross_withdrawals"],
        net_external_contributions=metrics["net_external_contributions"],
        dividends=metrics["dividends"],
        fees_and_taxes=metrics["fees_and_taxes"],
        quality_state=quality,
        warnings=tuple(warnings),
    )


def calculate_direct_allocation(aggregate: PortfolioAggregate) -> DirectAllocation:
    total_value = aggregate.portfolio_total
    if total_value is None or total_value.amount <= 0:
        warning = DomainWarning(
            "allocation_unavailable",
            "Direct allocation requires a complete, strictly positive portfolio total.",
            ("portfolio_total",),
        )
        return DirectAllocation(
            method_id=ALLOCATION_METHOD_ID,
            version=ALLOCATION_VERSION,
            account_id=aggregate.account_id,
            reporting_currency=aggregate.reporting_currency,
            available=False,
            lines=(),
            residual=None,
            quality_state=degrade_quality(aggregate.quality_state, QualityState.PARTIAL),
            warnings=(*aggregate.warnings, warning),
            missing_inputs=("positive_complete_portfolio_total",),
        )

    lines: list[AllocationLine] = []
    for component in aggregate.components:
        if component.reporting_value is None:
            raise AssertionError("complete portfolio contains an unconverted component")
        lines.append(
            AllocationLine(
                component_key=component.component_key,
                component_type=component.component_type,
                listing_id=component.listing_id,
                value=component.reporting_value,
                weight=ratio(divide(component.reporting_value.amount, total_value.amount)),
                mapped=component.mapped,
            )
        )
    weight_sum = total(line.weight.value for line in lines)
    residual = Ratio(persisted_decimal(subtract(Decimal(1), weight_sum)))
    return DirectAllocation(
        method_id=ALLOCATION_METHOD_ID,
        version=ALLOCATION_VERSION,
        account_id=aggregate.account_id,
        reporting_currency=aggregate.reporting_currency,
        available=True,
        lines=tuple(lines),
        residual=residual,
        quality_state=aggregate.quality_state,
        warnings=aggregate.warnings,
        missing_inputs=aggregate.missing_inputs,
    )


def compare_snapshots(
    beginning: SnapshotValue,
    ending: SnapshotValue,
    *,
    net_external_contributions: Money | None,
    external_flow_coverage_complete: bool,
) -> SnapshotComparison:
    if beginning.account_id != ending.account_id:
        raise ValueError("snapshot comparison crosses broker accounts")
    if ending.valuation_at < beginning.valuation_at:
        raise ValueError("ending snapshot precedes beginning snapshot")

    warnings: list[DomainWarning] = []
    missing: list[str] = []
    quality = combine_quality((beginning.quality_state, ending.quality_state))
    compatible = True
    if beginning.reporting_currency != ending.reporting_currency:
        compatible = False
        missing.append("reporting_currency_transformation")
        warnings.append(
            DomainWarning(
                "snapshot_currency_mismatch",
                "Snapshot totals use different reporting currencies.",
                ("reporting_currency",),
            )
        )
    if beginning.calculation_version != ending.calculation_version:
        compatible = False
        missing.append("calculation_version_transformation")
        warnings.append(
            DomainWarning(
                "snapshot_version_mismatch",
                "Snapshot totals use different calculation versions.",
                ("calculation_version",),
            )
        )
    if beginning.portfolio_total is None:
        missing.append("beginning_portfolio_total")
    if ending.portfolio_total is None:
        missing.append("ending_portfolio_total")
    if (
        net_external_contributions is not None
        and net_external_contributions.currency != ending.reporting_currency
    ):
        raise DomainError(
            ErrorCode.CURRENCY_MISMATCH,
            "external contributions must use snapshot reporting currency",
            "net_external_contributions",
        )

    total_change: Money | None = None
    if compatible and beginning.portfolio_total is not None and ending.portfolio_total is not None:
        total_change = ending.portfolio_total - beginning.portfolio_total

    reliable_values = quality not in (
        QualityState.PARTIAL,
        QualityState.UNRECONCILED,
        QualityState.FAILED,
    )
    flow_reliable = external_flow_coverage_complete and net_external_contributions is not None
    if not external_flow_coverage_complete:
        missing.append("complete_external_flow_history")
    elif net_external_contributions is None:
        missing.append("net_external_contributions")
    investment_gain: Money | None = None
    residual: Money | None = None
    if total_change is not None and flow_reliable and reliable_values:
        assert net_external_contributions is not None
        investment_gain = total_change - net_external_contributions
        residual = Money.zero(ending.reporting_currency)
    else:
        warnings.append(
            DomainWarning(
                "investment_gain_unavailable",
                "Investment gain requires comparable reliable values and complete external flows.",
                ("investment_gain",),
            )
        )
    if missing:
        quality = degrade_quality(quality, QualityState.PARTIAL)

    return SnapshotComparison(
        method_id=COMPARISON_METHOD_ID,
        version=COMPARISON_VERSION,
        account_id=beginning.account_id,
        reporting_currency=ending.reporting_currency,
        beginning_at=beginning.valuation_at,
        ending_at=ending.valuation_at,
        beginning_value=beginning.portfolio_total,
        ending_value=ending.portfolio_total,
        total_change=total_change,
        net_external_contributions=(
            net_external_contributions if external_flow_coverage_complete else None
        ),
        investment_gain=investment_gain,
        reconciliation_residual=residual,
        quality_state=quality,
        warnings=tuple(warnings),
        missing_inputs=tuple(dict.fromkeys(missing)),
    )


def calculate_weighted_average_cost(
    *,
    account_id: BrokerAccountId,
    listing_id: ListingId,
    events: tuple[TradeAccountingEvent, ...],
    history_complete: bool,
    unsupported_activity: bool = False,
) -> WeightedAverageCostResult:
    """Derive non-tax weighted-average acquisition cost for straightforward trades."""

    assumptions = (
        "non-tax weighted-average acquisition method",
        "buy fees and taxes increase acquisition cost",
        "sell fees and taxes reduce disposal proceeds",
        "only covered straightforward buys and sells are supported",
    )

    if any(event.account_id != account_id for event in events):
        raise ValueError("cost input contains a different broker account")
    if any(event.listing_id != listing_id for event in events):
        raise ValueError("cost input contains a different listing")
    currencies = {event.gross_trade_value.currency for event in events}
    if len(currencies) > 1:
        raise DomainError(
            ErrorCode.CURRENCY_MISMATCH,
            "cost events must use one currency",
            "currency",
        )
    input_quality = combine_quality(event.quality_state for event in events)
    reliable_inputs = input_quality in (QualityState.FRESH, QualityState.STALE)
    if not history_complete or unsupported_activity or not reliable_inputs:
        limitation = QualityState.UNRECONCILED if unsupported_activity else QualityState.PARTIAL
        code = "unsupported_cost_activity" if unsupported_activity else "partial_cost_history"
        return WeightedAverageCostResult(
            method_id=COST_METHOD_ID,
            version=COST_VERSION,
            account_id=account_id,
            listing_id=listing_id,
            currency=next(iter(currencies), None),
            ending_quantity=None,
            acquisition_cost=None,
            average_unit_cost=None,
            realized_pnl=None,
            history_complete=False,
            quality_state=degrade_quality(input_quality, limitation),
            warnings=(
                DomainWarning(
                    code,
                    (
                        "Acquisition cost and realized P/L are unavailable for incomplete "
                        "or unsupported history."
                    ),
                    (str(listing_id),),
                ),
            ),
            missing_inputs=("complete_supported_trade_history",),
            assumptions=assumptions,
        )

    quantity = Decimal(0)
    cost = Decimal(0)
    realized = Decimal(0)
    ordered = sorted(
        events,
        key=lambda item: (
            item.occurred_at.value,
            item.event_key,
            item.transaction_type.value,
            str(item.quantity.value),
            str(item.gross_trade_value.amount),
            str(item.fees.amount),
            str(item.taxes.amount),
        ),
    )
    for event in ordered:
        charges = add(event.fees.amount, event.taxes.amount)
        if event.transaction_type is TransactionType.BUY:
            quantity = add(quantity, event.quantity.value)
            cost = add(cost, add(event.gross_trade_value.amount, charges))
            continue
        if event.quantity.value > quantity:
            return WeightedAverageCostResult(
                method_id=COST_METHOD_ID,
                version=COST_VERSION,
                account_id=account_id,
                listing_id=listing_id,
                currency=event.gross_trade_value.currency,
                ending_quantity=None,
                acquisition_cost=None,
                average_unit_cost=None,
                realized_pnl=None,
                history_complete=False,
                quality_state=QualityState.UNRECONCILED,
                warnings=(
                    DomainWarning(
                        "sale_exceeds_supported_holdings",
                        "A disposal exceeds the quantity established by covered trade history.",
                        (str(listing_id),),
                    ),
                ),
                missing_inputs=("opening_or_prior_acquisition_history",),
                assumptions=assumptions,
            )
        disposed_cost = multiply(cost, divide(event.quantity.value, quantity))
        net_proceeds = subtract(event.gross_trade_value.amount, charges)
        realized = add(realized, subtract(net_proceeds, disposed_cost))
        quantity = subtract(quantity, event.quantity.value)
        cost = subtract(cost, disposed_cost)
        if quantity == 0:
            cost = Decimal(0)

    currency = next(iter(currencies), None)
    if currency is None:
        return WeightedAverageCostResult(
            method_id=COST_METHOD_ID,
            version=COST_VERSION,
            account_id=account_id,
            listing_id=listing_id,
            currency=None,
            ending_quantity=Quantity.parse(0),
            acquisition_cost=None,
            average_unit_cost=None,
            realized_pnl=None,
            history_complete=False,
            quality_state=QualityState.PARTIAL,
            warnings=(
                DomainWarning(
                    "trade_currency_unavailable",
                    "No covered trade establishes the acquisition-cost currency.",
                    (str(listing_id),),
                ),
            ),
            missing_inputs=("trade_currency",),
            assumptions=assumptions,
        )
    ending_quantity = Quantity(persisted_decimal(quantity))
    acquisition_cost = Money(persisted_decimal(cost), currency)
    average_price = (
        Price(persisted_decimal(divide(cost, quantity)), currency) if quantity > 0 else None
    )
    return WeightedAverageCostResult(
        method_id=COST_METHOD_ID,
        version=COST_VERSION,
        account_id=account_id,
        listing_id=listing_id,
        currency=currency,
        ending_quantity=ending_quantity,
        acquisition_cost=acquisition_cost,
        average_unit_cost=average_price,
        realized_pnl=Money(persisted_decimal(realized), currency),
        history_complete=True,
        quality_state=input_quality,
        warnings=(),
        missing_inputs=(),
        assumptions=assumptions,
    )
