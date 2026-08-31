"""Versioned, duplicate-safe canonical ledger projection."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from trading212_domain import (
    BrokerAccountId,
    CashFlowClassification,
    CurrencyCode,
    DomainWarning,
    Instant,
    ListingId,
    Money,
    QualityState,
    Transaction,
    TransactionId,
    TransactionStatus,
    TransactionType,
    canonical_json,
)

from ._decimal import add, total
from .quality import degrade_quality

LEDGER_METHOD_ID = "canonical_ledger"
LEDGER_VERSION = "1.0.0"

_STATUS_RANK = {
    TransactionStatus.UNKNOWN: 0,
    TransactionStatus.PENDING: 1,
    TransactionStatus.POSTED: 2,
    TransactionStatus.REVERSED: 3,
}

_INTERNAL_TYPES = {
    TransactionType.BUY,
    TransactionType.SELL,
    TransactionType.DIVIDEND,
    TransactionType.FEE,
    TransactionType.TAX_WITHHOLDING,
    TransactionType.INTEREST,
}
_UNSUPPORTED_TYPES = {
    TransactionType.TRANSFER,
    TransactionType.CORPORATE_ACTION,
    TransactionType.ADJUSTMENT,
    TransactionType.UNKNOWN_PROVIDER_ACTIVITY,
}


@dataclass(frozen=True, slots=True)
class LedgerLine:
    transaction_id: TransactionId
    broker_account_id: BrokerAccountId
    provider_transaction_id: str
    transaction_type: TransactionType
    classification: CashFlowClassification
    amount: Money
    occurred_at: Instant
    listing_id: ListingId | None
    active: bool
    supported: bool
    economic_fingerprint: str


@dataclass(frozen=True, slots=True)
class CurrencyLedgerSummary:
    currency: CurrencyCode
    gross_deposits: Money
    gross_withdrawals: Money
    net_external_contributions: Money | None
    dividends: Money
    fees_and_taxes: Money
    net_cash_delta: Money | None


@dataclass(frozen=True, slots=True)
class LedgerProjection:
    method_id: str
    version: str
    account_id: BrokerAccountId
    entries: tuple[LedgerLine, ...]
    currency_summaries: tuple[CurrencyLedgerSummary, ...]
    duplicate_count: int
    conflicting_duplicate_keys: tuple[str, ...]
    history_complete: bool
    quality_state: QualityState
    warnings: tuple[DomainWarning, ...]


def _economic_payload(transaction: Transaction) -> dict[str, object]:
    return {
        "account_id": transaction.broker_account_id,
        "provider_transaction_id": transaction.provider_transaction_id,
        "transaction_type": transaction.transaction_type,
        "net_cash_amount": transaction.net_cash_amount,
        "occurred_at": transaction.occurred_at,
        "instrument_listing_id": transaction.instrument_listing_id,
        "quantity": transaction.quantity,
        "unit_price": transaction.unit_price,
        "gross_amount": transaction.gross_amount,
        "fees": transaction.fees,
        "taxes": transaction.taxes,
        "settlement_date": transaction.settlement_date,
    }


def _fingerprint(transaction: Transaction) -> str:
    payload = canonical_json(_economic_payload(transaction)).encode("utf-8")
    return sha256(payload).hexdigest()


def _classification(transaction_type: TransactionType) -> CashFlowClassification:
    if transaction_type in (TransactionType.DEPOSIT, TransactionType.WITHDRAWAL):
        return CashFlowClassification.EXTERNAL
    if transaction_type in _INTERNAL_TYPES:
        return CashFlowClassification.INTERNAL
    return CashFlowClassification.UNKNOWN


def _sign_is_valid(transaction: Transaction) -> bool:
    amount = transaction.net_cash_amount.amount
    if transaction.transaction_type is TransactionType.DEPOSIT:
        return amount >= 0
    if transaction.transaction_type in (
        TransactionType.WITHDRAWAL,
        TransactionType.BUY,
        TransactionType.FEE,
        TransactionType.TAX_WITHHOLDING,
    ):
        return amount <= 0
    if transaction.transaction_type in (
        TransactionType.SELL,
        TransactionType.DIVIDEND,
        TransactionType.INTEREST,
    ):
        return amount >= 0
    return True


def _line(transaction: Transaction, fingerprint: str) -> LedgerLine:
    classification = _classification(transaction.transaction_type)
    supported = transaction.transaction_type not in _UNSUPPORTED_TYPES and _sign_is_valid(
        transaction
    )
    return LedgerLine(
        transaction_id=transaction.id,
        broker_account_id=transaction.broker_account_id,
        provider_transaction_id=transaction.provider_transaction_id,
        transaction_type=transaction.transaction_type,
        classification=classification,
        amount=transaction.net_cash_amount,
        occurred_at=transaction.occurred_at,
        listing_id=transaction.instrument_listing_id,
        active=transaction.status is not TransactionStatus.REVERSED,
        supported=supported,
        economic_fingerprint=fingerprint,
    )


def _summary_for_currency(
    currency: CurrencyCode,
    entries: tuple[LedgerLine, ...],
    *,
    external_history_reliable: bool,
    cash_history_reliable: bool,
) -> CurrencyLedgerSummary:
    active = tuple(entry for entry in entries if entry.active and entry.amount.currency == currency)
    deposits = total(
        entry.amount.amount
        for entry in active
        if entry.supported and entry.transaction_type is TransactionType.DEPOSIT
    )
    withdrawals_signed = total(
        entry.amount.amount
        for entry in active
        if entry.supported and entry.transaction_type is TransactionType.WITHDRAWAL
    )
    dividends = total(
        entry.amount.amount
        for entry in active
        if entry.supported and entry.transaction_type is TransactionType.DIVIDEND
    )
    fees_and_taxes = total(
        entry.amount.amount
        for entry in active
        if entry.supported
        and entry.transaction_type in (TransactionType.FEE, TransactionType.TAX_WITHHOLDING)
    )
    net_external = None
    if external_history_reliable:
        net_external = Money(add(deposits, withdrawals_signed), currency)
    net_cash = None
    if cash_history_reliable:
        net_cash = Money(total(entry.amount.amount for entry in active), currency)
    return CurrencyLedgerSummary(
        currency=currency,
        gross_deposits=Money(deposits, currency),
        gross_withdrawals=Money(-withdrawals_signed, currency),
        net_external_contributions=net_external,
        dividends=Money(dividends, currency),
        fees_and_taxes=Money(fees_and_taxes, currency),
        net_cash_delta=net_cash,
    )


def project_ledger(
    transactions: tuple[Transaction, ...],
    *,
    account_id: BrokerAccountId,
    history_complete: bool,
    input_quality: QualityState = QualityState.FRESH,
) -> LedgerProjection:
    """Project one account's canonical transactions into an economic ledger.

    Provider identity and economic content are separate: repeated identical events
    coalesce, status-only updates resolve deterministically, and conflicting updates
    are excluded rather than silently selected.
    """

    foreign = tuple(item for item in transactions if item.broker_account_id != account_id)
    if foreign:
        raise ValueError("ledger input contains a different broker account")

    groups: dict[tuple[UUID, str], list[Transaction]] = defaultdict(list)
    for transaction in transactions:
        groups[(transaction.broker_account_id, transaction.provider_transaction_id)].append(
            transaction
        )

    lines: list[LedgerLine] = []
    warnings: list[DomainWarning] = []
    conflicts: list[str] = []
    duplicate_count = 0
    quality = input_quality
    for key in sorted(groups, key=lambda value: (str(value[0]), value[1])):
        candidates = groups[key]
        by_fingerprint: dict[str, list[Transaction]] = defaultdict(list)
        for candidate in candidates:
            by_fingerprint[_fingerprint(candidate)].append(candidate)
        duplicate_count += len(candidates) - 1
        if len(by_fingerprint) != 1:
            conflict_key = f"{key[0]}:{key[1]}"
            conflicts.append(conflict_key)
            warnings.append(
                DomainWarning(
                    "conflicting_duplicate_activity",
                    "Conflicting observations share one provider transaction identity.",
                    (key[1],),
                )
            )
            quality = degrade_quality(quality, QualityState.UNRECONCILED)
            continue
        fingerprint, duplicates = next(iter(by_fingerprint.items()))
        selected = max(
            duplicates,
            key=lambda item: (_STATUS_RANK[item.status], str(item.id)),
        )
        line = _line(selected, fingerprint)
        lines.append(line)
        if not line.supported:
            limitation = (
                QualityState.UNRECONCILED
                if _classification(line.transaction_type) is not CashFlowClassification.UNKNOWN
                else QualityState.PARTIAL
            )
            quality = degrade_quality(quality, limitation)
            warnings.append(
                DomainWarning(
                    "unsupported_or_invalid_activity",
                    "Activity is retained but excluded from unsupported accounting claims.",
                    (line.provider_transaction_id,),
                )
            )

    if not history_complete:
        quality = degrade_quality(quality, QualityState.PARTIAL)
        warnings.append(
            DomainWarning(
                "partial_transaction_history",
                (
                    "External-contribution and cash-delta totals are unavailable "
                    "for incomplete history."
                ),
            )
        )

    ordered_lines = tuple(
        sorted(
            lines,
            key=lambda item: (
                item.occurred_at.value,
                item.provider_transaction_id,
                str(item.transaction_id),
            ),
        )
    )
    active_lines = tuple(item for item in ordered_lines if item.active)
    external_reliable = (
        history_complete
        and not conflicts
        and all(
            item.supported and item.classification is not CashFlowClassification.UNKNOWN
            for item in active_lines
        )
    )
    cash_reliable = (
        history_complete and not conflicts and all(item.supported for item in active_lines)
    )
    currencies = tuple(sorted({item.amount.currency for item in active_lines}, key=str))
    summaries = tuple(
        _summary_for_currency(
            currency,
            ordered_lines,
            external_history_reliable=external_reliable,
            cash_history_reliable=cash_reliable,
        )
        for currency in currencies
    )
    return LedgerProjection(
        method_id=LEDGER_METHOD_ID,
        version=LEDGER_VERSION,
        account_id=account_id,
        entries=ordered_lines,
        currency_summaries=summaries,
        duplicate_count=duplicate_count,
        conflicting_duplicate_keys=tuple(conflicts),
        history_complete=history_complete,
        quality_state=quality,
        warnings=tuple(warnings),
    )
