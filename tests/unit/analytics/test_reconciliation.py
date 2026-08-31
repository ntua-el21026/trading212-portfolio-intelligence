from decimal import Decimal

import pytest
from trading212_analytics import (
    TOLERANCE_POLICY_V1,
    CashBridgeInput,
    QuantityBridgeInput,
    TolerancePolicy,
    ValueBridgeInput,
    reconcile_portfolio,
)
from trading212_domain import (
    DiscrepancyType,
    DomainError,
    Money,
    QualityState,
    Quantity,
    ReconciliationStatus,
)

from .factories import ACCOUNT_ID, LISTING_ID, OTHER_ACCOUNT_ID

pytestmark = pytest.mark.unit


def test_quantity_cash_and_value_bridges_pass_at_v1_tolerance_boundary() -> None:
    result = reconcile_portfolio(
        account_id=ACCOUNT_ID,
        quantity_bridges=(
            QuantityBridgeInput(
                ACCOUNT_ID,
                LISTING_ID,
                Quantity.parse("10"),
                Quantity.parse("11.00000001"),
                buys=(Quantity.parse("2"),),
                sells=(Quantity.parse("1"),),
            ),
        ),
        cash_bridges=(
            CashBridgeInput(
                ACCOUNT_ID,
                Money.parse("100", "EUR"),
                Money.parse("100.01", "EUR"),
                deposits=(Money.parse("50", "EUR"),),
                withdrawals=(Money.parse("10", "EUR"),),
                buy_outflows=(Money.parse("40", "EUR"),),
                sell_inflows=(Money.parse("5", "EUR"),),
                dividends=(Money.parse("2", "EUR"),),
                fees=(Money.parse("1", "EUR"),),
                taxes=(Money.parse("1", "EUR"),),
                signed_adjustments=(Money.parse("-5", "EUR"),),
            ),
        ),
        value_bridges=(
            ValueBridgeInput(
                ACCOUNT_ID,
                Money.parse("150", "EUR"),
                Money.parse("150.01", "EUR"),
            ),
        ),
    )

    assert result.tolerance_version == "v1"
    assert result.status is ReconciliationStatus.RECONCILED
    assert result.quality_state is QualityState.FRESH
    assert all(check.within_tolerance for check in result.checks)
    assert result.discrepancies == ()


def test_residual_beyond_tolerance_creates_visible_discrepancy() -> None:
    result = reconcile_portfolio(
        account_id=ACCOUNT_ID,
        cash_bridges=(
            CashBridgeInput(
                ACCOUNT_ID,
                Money.parse("100", "EUR"),
                Money.parse("100.010000000000000001", "EUR"),
            ),
        ),
    )

    assert result.status is ReconciliationStatus.UNRECONCILED
    assert result.quality_state is QualityState.UNRECONCILED
    assert result.checks[0].residual == Decimal("0.010000000000000001")
    assert result.discrepancies[0].discrepancy_type is DiscrepancyType.CASH_MISMATCH


def test_missing_observation_is_partial_not_zero() -> None:
    result = reconcile_portfolio(
        account_id=ACCOUNT_ID,
        quantity_bridges=(
            QuantityBridgeInput(
                ACCOUNT_ID,
                LISTING_ID,
                Quantity.parse("5"),
                None,
                coverage_complete=False,
            ),
        ),
    )

    assert result.status is ReconciliationStatus.PARTIAL
    assert result.checks[0].observed is None
    assert result.checks[0].within_tolerance is None
    assert result.quality_state is QualityState.PARTIAL


def test_unsupported_activity_blocks_bridge_even_when_residual_is_zero() -> None:
    result = reconcile_portfolio(
        account_id=ACCOUNT_ID,
        quantity_bridges=(
            QuantityBridgeInput(
                ACCOUNT_ID,
                LISTING_ID,
                Quantity.parse("5"),
                Quantity.parse("5"),
                unsupported_activity=True,
            ),
        ),
    )
    assert result.checks[0].within_tolerance is True
    assert result.status is ReconciliationStatus.UNRECONCILED
    assert any(
        issue.discrepancy_type is DiscrepancyType.UNSUPPORTED_CORPORATE_ACTION
        for issue in result.discrepancies
    )


def test_tolerance_policy_rejects_float_and_negative_values() -> None:
    with pytest.raises(DomainError):
        TolerancePolicy("bad", 0.1, Decimal("0.01"), Decimal("0.01"))  # type: ignore[arg-type]
    with pytest.raises(DomainError, match="must not be negative"):
        TolerancePolicy("bad", Decimal("-0.1"), Decimal("0.01"), Decimal("0.01"))
    assert TOLERANCE_POLICY_V1.quantity_absolute == Decimal("0.00000001")


def test_reconciliation_rejects_cross_account_input() -> None:
    with pytest.raises(ValueError, match="different broker account"):
        reconcile_portfolio(
            account_id=ACCOUNT_ID,
            quantity_bridges=(
                QuantityBridgeInput(
                    OTHER_ACCOUNT_ID,
                    LISTING_ID,
                    Quantity.parse(0),
                    Quantity.parse(0),
                ),
            ),
        )
