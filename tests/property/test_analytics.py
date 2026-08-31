from decimal import Decimal
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st
from trading212_analytics import (
    CashBridgeInput,
    CashComponentInput,
    ValuedPositionInput,
    aggregate_portfolio,
    calculate_direct_allocation,
    calculate_modified_dietz,
    calculate_position_market_value,
    reconcile_portfolio,
)
from trading212_domain import (
    BrokerAccountId,
    Coverage,
    CurrencyCode,
    Instant,
    ListingId,
    Money,
    Price,
    Quantity,
    ReconciliationStatus,
)

pytestmark = pytest.mark.property
ACCOUNT_ID = BrokerAccountId(UUID(int=9101))
LISTING_ID = ListingId(UUID(int=9201))
EUR = CurrencyCode("EUR")
START = Instant.parse("2026-01-01T00:00:00Z")
END = Instant.parse("2027-01-01T00:00:00Z")

amounts = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("1000000"),
    places=6,
    allow_nan=False,
    allow_infinity=False,
)
positive_amounts = st.decimals(
    min_value=Decimal("0.000001"),
    max_value=Decimal("1000000"),
    places=6,
    allow_nan=False,
    allow_infinity=False,
)


@given(position_value=amounts, cash_value=amounts)
def test_complete_single_currency_aggregation_conserves_components_and_weights(
    position_value: Decimal,
    cash_value: Decimal,
) -> None:
    aggregate = aggregate_portfolio(
        account_id=ACCOUNT_ID,
        positions=(
            ValuedPositionInput(
                ACCOUNT_ID,
                LISTING_ID,
                Quantity.parse("1"),
                EUR,
                provider_market_value=Money(position_value, EUR),
            ),
        ),
        cash_components=(CashComponentInput(ACCOUNT_ID, "cash", Money(cash_value, EUR)),),
        reporting_currency=EUR,
        fx_quotes=(),
        valuation_at=END,
        source_cutoff_at=END,
    )
    assert aggregate.portfolio_total is not None
    assert aggregate.portfolio_total.amount == position_value + cash_value
    assert aggregate.component_sum_residual == Money.parse(0, "EUR")
    allocation = calculate_direct_allocation(aggregate)
    if position_value + cash_value == 0:
        assert not allocation.available
        assert allocation.residual is None
    else:
        assert allocation.residual is not None
        assert sum(
            (line.weight.value for line in allocation.lines), Decimal(0)
        ) + allocation.residual.value == Decimal(1)


@given(
    quantity=st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("10000"),
        places=9,
        allow_nan=False,
        allow_infinity=False,
    ),
    price=positive_amounts,
)
def test_position_market_value_equals_exact_decimal_product_at_output_boundary(
    quantity: Decimal,
    price: Decimal,
) -> None:
    result = calculate_position_market_value(Quantity(quantity), Price(price, EUR))
    exact_product = quantity * price
    assert abs(result.amount - exact_product) <= Decimal("0.0000000000000000005")


@given(opening=amounts, residual=st.decimals(min_value="-0.01", max_value="0.01", places=18))
def test_cash_reconciliation_accepts_exact_v1_tolerance_interval(
    opening: Decimal,
    residual: Decimal,
) -> None:
    result = reconcile_portfolio(
        account_id=ACCOUNT_ID,
        cash_bridges=(
            CashBridgeInput(
                ACCOUNT_ID,
                Money(opening, EUR),
                Money(opening + residual, EUR),
            ),
        ),
    )
    assert result.status is ReconciliationStatus.RECONCILED
    assert result.checks[0].within_tolerance is True


@given(
    beginning=positive_amounts, return_rate=st.decimals(min_value="-0.9", max_value="3", places=6)
)
def test_no_flow_modified_dietz_equals_simple_cumulative_return(
    beginning: Decimal,
    return_rate: Decimal,
) -> None:
    ending = beginning * (Decimal(1) + return_rate)
    result = calculate_modified_dietz(
        beginning_value=Money(beginning, EUR),
        ending_value=Money(ending, EUR),
        period_start=START,
        period_end=END,
        external_flows=(),
        coverage=Coverage(START, END, True),
    )
    assert result.value is not None
    assert abs(result.value.value - return_rate) <= Decimal("0.0000000000000000005")
