from decimal import Decimal
from uuid import UUID

import pytest
from trading212_analytics import (
    CashComponentInput,
    DatedExternalFlow,
    FxQuote,
    PortfolioAggregate,
    SnapshotValue,
    TradeAccountingEvent,
    ValuedPositionInput,
    aggregate_portfolio,
    build_portfolio_snapshot,
    calculate_direct_allocation,
    calculate_position_market_value,
    calculate_unrealized_pnl,
    calculate_weighted_average_cost,
    compare_snapshots,
    project_ledger,
    summarize_ledger_accounting,
)
from trading212_domain import (
    BrokerAccountId,
    CalculationMetadata,
    CalculationRunId,
    Coverage,
    CurrencyCode,
    DataQuality,
    FxRate,
    ListingId,
    Money,
    Price,
    QualityState,
    Quantity,
    SnapshotId,
    TransactionType,
)

from .factories import (
    ACCOUNT_ID,
    END,
    LISTING_ID,
    MID,
    OTHER_ACCOUNT_ID,
    SECOND_LISTING_ID,
    START,
    transaction,
)

pytestmark = pytest.mark.unit
EUR = CurrencyCode("EUR")
USD = CurrencyCode("USD")


def _position(
    listing_id: ListingId = LISTING_ID,
    *,
    account_id: BrokerAccountId = ACCOUNT_ID,
    currency: CurrencyCode = EUR,
    market_value: str | None = "100",
    mapped: bool = True,
    quality: QualityState = QualityState.FRESH,
) -> ValuedPositionInput:
    return ValuedPositionInput(
        account_id,
        listing_id,
        Quantity.parse("1.5"),
        currency,
        provider_market_value=(
            Money.parse(market_value, currency) if market_value is not None else None
        ),
        mapped=mapped,
        quality_state=quality,
    )


def _aggregate(
    positions: tuple[ValuedPositionInput, ...],
    cash: tuple[CashComponentInput, ...] = (),
    fx: tuple[FxQuote, ...] = (),
) -> PortfolioAggregate:
    return aggregate_portfolio(
        account_id=ACCOUNT_ID,
        positions=positions,
        cash_components=cash,
        reporting_currency=EUR,
        fx_quotes=fx,
        valuation_at=END,
        source_cutoff_at=END,
    )


def test_position_market_value_and_unrealized_pnl_use_exact_boundary_rounding() -> None:
    value = calculate_position_market_value(
        Quantity.parse("123.45"),
        Price.parse("0.876543210987654321", "EUR"),
    )
    assert value.amount == Decimal("108.209259396425925927")
    assert calculate_unrealized_pnl(value, Money.parse("100", "EUR")).amount == Decimal(
        "8.209259396425925927"
    )


def test_empty_eur_account_has_known_zero_totals_and_unavailable_allocation() -> None:
    aggregate = aggregate_portfolio(
        account_id=ACCOUNT_ID,
        positions=(),
        cash_components=(),
        reporting_currency=EUR,
        fx_quotes=(),
        valuation_at=END,
        source_cutoff_at=END,
    )
    assert aggregate.cash_total == Money.parse(0, "EUR")
    assert aggregate.invested_total == Money.parse(0, "EUR")
    assert aggregate.portfolio_total == Money.parse(0, "EUR")
    assert aggregate.component_sum_residual == Money.parse(0, "EUR")
    allocation = calculate_direct_allocation(aggregate)
    assert not allocation.available
    assert allocation.residual is None


def test_multi_currency_aggregation_uses_explicit_fx_and_weights_reconcile() -> None:
    fx = FxQuote(FxRate(USD, EUR, Decimal("0.8"), MID, "reference-fixture"))
    aggregate = aggregate_portfolio(
        account_id=ACCOUNT_ID,
        positions=(
            _position(LISTING_ID, market_value="100"),
            _position(SECOND_LISTING_ID, currency=USD, market_value="50"),
        ),
        cash_components=(CashComponentInput(ACCOUNT_ID, "available", Money.parse("10", "EUR")),),
        reporting_currency=EUR,
        fx_quotes=(fx,),
        valuation_at=END,
        source_cutoff_at=END,
    )

    assert aggregate.invested_total == Money.parse("140", "EUR")
    assert aggregate.cash_total == Money.parse("10", "EUR")
    assert aggregate.portfolio_total == Money.parse("150", "EUR")
    assert aggregate.component_sum_residual == Money.parse(0, "EUR")
    allocation = calculate_direct_allocation(aggregate)
    assert allocation.available
    assert allocation.residual is not None
    weight_sum = sum((line.weight.value for line in allocation.lines), Decimal(0))
    assert weight_sum + allocation.residual.value == Decimal(1)


def test_missing_or_post_cutoff_fx_is_not_treated_as_one_or_zero() -> None:
    future_quote = FxQuote(FxRate(USD, EUR, Decimal("0.8"), END, "future-fixture"))
    aggregate = aggregate_portfolio(
        account_id=ACCOUNT_ID,
        positions=(
            _position(LISTING_ID, market_value="100"),
            _position(SECOND_LISTING_ID, currency=USD, market_value="50"),
        ),
        cash_components=(),
        reporting_currency=EUR,
        fx_quotes=(future_quote,),
        valuation_at=MID,
        source_cutoff_at=MID,
    )

    assert aggregate.invested_total is None
    assert aggregate.portfolio_total is None
    assert aggregate.known_invested_subtotal == Money.parse("100", "EUR")
    assert aggregate.quality_state is QualityState.PARTIAL
    assert any("fx" in item for item in aggregate.missing_inputs)


def test_ambiguous_latest_fx_rates_fail_closed_as_unreconciled() -> None:
    aggregate = aggregate_portfolio(
        account_id=ACCOUNT_ID,
        positions=(_position(currency=USD),),
        cash_components=(),
        reporting_currency=EUR,
        fx_quotes=(
            FxQuote(FxRate(USD, EUR, Decimal("0.8"), MID, "source-a")),
            FxQuote(FxRate(USD, EUR, Decimal("0.81"), MID, "source-b")),
        ),
        valuation_at=END,
        source_cutoff_at=END,
    )
    assert aggregate.portfolio_total is None
    assert aggregate.quality_state is QualityState.UNRECONCILED


def test_unmapped_observed_position_remains_in_total_but_is_partial() -> None:
    aggregate = _aggregate((_position(mapped=False),))
    assert aggregate.portfolio_total == Money.parse("100", "EUR")
    assert aggregate.quality_state is QualityState.PARTIAL
    assert any(warning.code == "unmapped_instrument" for warning in aggregate.warnings)


def test_provider_and_derived_cost_and_pnl_are_never_overwritten() -> None:
    position = ValuedPositionInput(
        ACCOUNT_ID,
        LISTING_ID,
        Quantity.parse("10"),
        EUR,
        provider_market_value=Money.parse("130", "EUR"),
        derived_market_value=Money.parse("129", "EUR"),
        provider_cost_basis=Money.parse("100", "EUR"),
        derived_acquisition_cost=Money.parse("101", "EUR"),
        provider_unrealized_pnl=Money.parse("30", "EUR"),
        derived_unrealized_pnl=Money.parse("28", "EUR"),
    )
    aggregate = _aggregate((position,))
    summary = aggregate.cost_and_pnl
    assert aggregate.portfolio_total == Money.parse("130", "EUR")
    assert summary.provider_cost_basis.value == Money.parse("100", "EUR")
    assert summary.derived_acquisition_cost.value == Money.parse("101", "EUR")
    assert summary.provider_unrealized_pnl.value == Money.parse("30", "EUR")
    assert summary.derived_unrealized_pnl.value == Money.parse("28", "EUR")


def test_aggregate_materializes_an_immutable_versioned_domain_snapshot() -> None:
    position = ValuedPositionInput(
        ACCOUNT_ID,
        LISTING_ID,
        Quantity.parse("10"),
        EUR,
        provider_market_value=Money.parse("130", "EUR"),
        provider_cost_basis=Money.parse("100", "EUR"),
        provider_unrealized_pnl=Money.parse("30", "EUR"),
    )
    cash = CashComponentInput(ACCOUNT_ID, "available", Money.parse("20", "EUR"))
    aggregate = _aggregate((position,), (cash,))
    quality = DataQuality(
        QualityState.FRESH,
        END,
        3600,
        Coverage(START, END, True),
    )
    metadata = CalculationMetadata(
        calculation_name="portfolio_snapshot",
        version="1.0.0",
        run_id=CalculationRunId(UUID(int=7001)),
        calculated_at=END,
        valuation_at=END,
        source_cutoff_at=END,
        reporting_currency=EUR,
        input_ids=(),
        method="Exact component aggregation",
        assumptions=(),
        data_quality=quality,
    )
    snapshot = build_portfolio_snapshot(
        aggregate,
        snapshot_id=SnapshotId(UUID(int=7002)),
        positions=(position,),
        cash_components=(cash,),
        calculation=metadata,
    )
    assert snapshot.portfolio_total == Money.parse("150", "EUR")
    assert snapshot.positions[0].market_value == Money.parse("130", "EUR")
    assert snapshot.positions[0].cost_basis == Money.parse("100", "EUR")
    assert snapshot.cash_components[0].amount == Money.parse("20", "EUR")
    assert snapshot.calculation.version == "1.0.0"


def test_missing_cost_basis_is_unavailable_without_degrading_known_market_value() -> None:
    aggregate = _aggregate((_position(),))
    assert aggregate.portfolio_total == Money.parse("100", "EUR")
    assert aggregate.quality_state is QualityState.FRESH
    assert aggregate.cost_and_pnl.provider_cost_basis.value is None
    assert aggregate.cost_and_pnl.provider_cost_basis.known_subtotal == Money.parse(0, "EUR")


def test_ledger_accounting_keeps_deposits_dividends_and_charges_separate() -> None:
    projection = project_ledger(
        (
            transaction(101, "deposit", TransactionType.DEPOSIT, "100"),
            transaction(102, "withdraw", TransactionType.WITHDRAWAL, "-20"),
            transaction(103, "buy", TransactionType.BUY, "-50"),
            transaction(104, "dividend", TransactionType.DIVIDEND, "5"),
            transaction(105, "fee", TransactionType.FEE, "-1"),
            transaction(106, "tax", TransactionType.TAX_WITHHOLDING, "-0.5"),
        ),
        account_id=ACCOUNT_ID,
        history_complete=True,
    )
    accounting = summarize_ledger_accounting(
        projection,
        reporting_currency=EUR,
        fx_quotes=(),
        source_cutoff_at=END,
    )
    assert accounting.net_external_contributions.value == Money.parse("80", "EUR")
    assert accounting.dividends.value == Money.parse("5", "EUR")
    assert accounting.fees_and_taxes.value == Money.parse("-1.5", "EUR")


def test_snapshot_comparison_subtracts_deposit_from_investment_gain() -> None:
    beginning = SnapshotValue(
        ACCOUNT_ID,
        START,
        EUR,
        "1.0.0",
        Money.parse("100", "EUR"),
        QualityState.FRESH,
    )
    ending = SnapshotValue(
        ACCOUNT_ID,
        END,
        EUR,
        "1.0.0",
        Money.parse("170", "EUR"),
        QualityState.FRESH,
    )
    comparison = compare_snapshots(
        beginning,
        ending,
        net_external_contributions=Money.parse("50", "EUR"),
        external_flow_coverage_complete=True,
    )
    assert comparison.total_change == Money.parse("70", "EUR")
    assert comparison.investment_gain == Money.parse("20", "EUR")
    assert comparison.reconciliation_residual == Money.parse(0, "EUR")


def test_snapshot_investment_gain_is_unavailable_for_partial_flow_history() -> None:
    beginning = SnapshotValue(
        ACCOUNT_ID,
        START,
        EUR,
        "1.0.0",
        Money.parse("100", "EUR"),
        QualityState.FRESH,
    )
    ending = SnapshotValue(
        ACCOUNT_ID,
        END,
        EUR,
        "1.0.0",
        Money.parse("170", "EUR"),
        QualityState.FRESH,
    )
    comparison = compare_snapshots(
        beginning,
        ending,
        net_external_contributions=None,
        external_flow_coverage_complete=False,
    )
    assert comparison.total_change == Money.parse("70", "EUR")
    assert comparison.investment_gain is None
    assert comparison.quality_state is QualityState.PARTIAL


def test_weighted_average_cost_derives_supported_cost_and_realized_pnl() -> None:
    result = calculate_weighted_average_cost(
        account_id=ACCOUNT_ID,
        listing_id=LISTING_ID,
        events=(
            TradeAccountingEvent(
                ACCOUNT_ID,
                LISTING_ID,
                TransactionType.BUY,
                Quantity.parse("10"),
                Money.parse("100", "EUR"),
                Money.parse("1", "EUR"),
                Money.parse(0, "EUR"),
                START,
            ),
            TradeAccountingEvent(
                ACCOUNT_ID,
                LISTING_ID,
                TransactionType.SELL,
                Quantity.parse("4"),
                Money.parse("60", "EUR"),
                Money.parse("1", "EUR"),
                Money.parse(0, "EUR"),
                MID,
            ),
        ),
        history_complete=True,
    )
    assert result.ending_quantity == Quantity.parse("6")
    assert result.acquisition_cost == Money.parse("60.6", "EUR")
    assert result.average_unit_cost == Price.parse("10.1", "EUR")
    assert result.realized_pnl == Money.parse("18.6", "EUR")


def test_weighted_average_cost_fails_closed_for_partial_or_oversold_history() -> None:
    event = TradeAccountingEvent(
        ACCOUNT_ID,
        LISTING_ID,
        TransactionType.SELL,
        Quantity.parse("1"),
        Money.parse("10", "EUR"),
        Money.parse(0, "EUR"),
        Money.parse(0, "EUR"),
        MID,
    )
    partial = calculate_weighted_average_cost(
        account_id=ACCOUNT_ID,
        listing_id=LISTING_ID,
        events=(event,),
        history_complete=False,
    )
    oversold = calculate_weighted_average_cost(
        account_id=ACCOUNT_ID,
        listing_id=LISTING_ID,
        events=(event,),
        history_complete=True,
    )
    assert partial.acquisition_cost is None
    assert partial.quality_state is QualityState.PARTIAL
    assert oversold.acquisition_cost is None
    assert oversold.quality_state is QualityState.UNRECONCILED


def test_portfolio_rejects_cross_account_components() -> None:
    with pytest.raises(ValueError, match="different broker account"):
        aggregate_portfolio(
            account_id=ACCOUNT_ID,
            positions=(_position(account_id=OTHER_ACCOUNT_ID),),
            cash_components=(),
            reporting_currency=EUR,
            fx_quotes=(),
            valuation_at=END,
            source_cutoff_at=END,
        )


def test_dated_external_flow_contract_uses_portfolio_sign_convention() -> None:
    deposit = DatedExternalFlow(Money.parse("10", "EUR"), MID)
    withdrawal = DatedExternalFlow(Money.parse("-5", "EUR"), MID)
    assert deposit.amount.amount > 0
    assert withdrawal.amount.amount < 0
