from decimal import Decimal

import pytest
from trading212_analytics import project_ledger
from trading212_domain import (
    CashFlowClassification,
    QualityState,
    TransactionStatus,
    TransactionType,
)

from .factories import ACCOUNT_ID, LISTING_ID, OTHER_ACCOUNT_ID, transaction

pytestmark = pytest.mark.unit


def test_ledger_classifies_external_internal_and_summarizes_without_double_counting() -> None:
    projection = project_ledger(
        (
            transaction(1, "deposit", TransactionType.DEPOSIT, "1000"),
            transaction(2, "buy", TransactionType.BUY, "-400", listing_id=LISTING_ID),
            transaction(3, "dividend", TransactionType.DIVIDEND, "10"),
            transaction(4, "fee", TransactionType.FEE, "-1"),
            transaction(5, "withdrawal", TransactionType.WITHDRAWAL, "-100"),
        ),
        account_id=ACCOUNT_ID,
        history_complete=True,
    )

    classifications = {
        line.provider_transaction_id: line.classification for line in projection.entries
    }
    assert classifications["deposit"] is CashFlowClassification.EXTERNAL
    assert classifications["withdrawal"] is CashFlowClassification.EXTERNAL
    assert classifications["buy"] is CashFlowClassification.INTERNAL
    assert classifications["dividend"] is CashFlowClassification.INTERNAL
    summary = projection.currency_summaries[0]
    assert summary.gross_deposits.amount == Decimal("1000")
    assert summary.gross_withdrawals.amount == Decimal("100")
    assert summary.net_external_contributions is not None
    assert summary.net_external_contributions.amount == Decimal("900")
    assert summary.dividends.amount == Decimal("10")
    assert summary.fees_and_taxes.amount == Decimal("-1")
    assert summary.net_cash_delta is not None
    assert summary.net_cash_delta.amount == Decimal("509")
    assert projection.quality_state is QualityState.FRESH


def test_identical_duplicate_and_status_update_create_one_economic_line() -> None:
    pending = transaction(
        10,
        "same-event",
        TransactionType.DEPOSIT,
        "25",
        status=TransactionStatus.PENDING,
    )
    posted = transaction(
        11,
        "same-event",
        TransactionType.DEPOSIT,
        "25",
        status=TransactionStatus.POSTED,
    )
    projection = project_ledger(
        (posted, pending, posted),
        account_id=ACCOUNT_ID,
        history_complete=True,
    )

    assert len(projection.entries) == 1
    assert projection.entries[0].active
    assert projection.duplicate_count == 2
    assert projection.currency_summaries[0].gross_deposits.amount == Decimal("25")


def test_reversal_deactivates_the_same_economic_event() -> None:
    posted = transaction(20, "reversed-event", TransactionType.DEPOSIT, "25")
    reversed_event = transaction(
        21,
        "reversed-event",
        TransactionType.DEPOSIT,
        "25",
        status=TransactionStatus.REVERSED,
    )
    projection = project_ledger(
        (posted, reversed_event),
        account_id=ACCOUNT_ID,
        history_complete=True,
    )

    assert len(projection.entries) == 1
    assert not projection.entries[0].active
    assert projection.currency_summaries == ()


def test_conflicting_provider_identity_is_excluded_and_unreconciled() -> None:
    projection = project_ledger(
        (
            transaction(30, "conflict", TransactionType.DEPOSIT, "25"),
            transaction(31, "conflict", TransactionType.DEPOSIT, "26"),
        ),
        account_id=ACCOUNT_ID,
        history_complete=True,
    )

    assert projection.entries == ()
    assert projection.duplicate_count == 1
    assert len(projection.conflicting_duplicate_keys) == 1
    assert projection.quality_state is QualityState.UNRECONCILED


def test_partial_or_unknown_activity_blocks_unsupported_totals() -> None:
    projection = project_ledger(
        (
            transaction(40, "deposit", TransactionType.DEPOSIT, "25"),
            transaction(41, "unknown", TransactionType.UNKNOWN_PROVIDER_ACTIVITY, "3"),
        ),
        account_id=ACCOUNT_ID,
        history_complete=False,
    )

    summary = projection.currency_summaries[0]
    assert summary.net_external_contributions is None
    assert summary.net_cash_delta is None
    assert projection.quality_state is QualityState.PARTIAL


def test_invalid_known_activity_sign_is_unreconciled() -> None:
    projection = project_ledger(
        (transaction(50, "negative-deposit", TransactionType.DEPOSIT, "-1"),),
        account_id=ACCOUNT_ID,
        history_complete=True,
    )
    assert not projection.entries[0].supported
    assert projection.quality_state is QualityState.UNRECONCILED


def test_ledger_rejects_cross_account_input() -> None:
    with pytest.raises(ValueError, match="different broker account"):
        project_ledger(
            (
                transaction(
                    60,
                    "foreign",
                    TransactionType.DEPOSIT,
                    "1",
                    account_id=OTHER_ACCOUNT_ID,
                ),
            ),
            account_id=ACCOUNT_ID,
            history_complete=True,
        )
