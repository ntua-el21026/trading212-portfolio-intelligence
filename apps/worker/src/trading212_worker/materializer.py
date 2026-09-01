"""Deterministic source-record normalization and canonical portfolio materialization."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from decimal import Decimal, localcontext
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from trading212_analytics import (
    PORTFOLIO_METHOD_ID,
    PORTFOLIO_VERSION,
    RECONCILIATION_VERSION,
    CashComponentInput,
    LedgerProjection,
    ReconciliationIssue,
    ValueBridgeInput,
    ValuedPositionInput,
    aggregate_portfolio,
    build_portfolio_snapshot,
    combine_quality,
    project_ledger,
    reconcile_portfolio,
    summarize_ledger_accounting,
)
from trading212_application.ingestion import FULL_REFRESH_ORDER, IngestionCapability
from trading212_domain import (
    BrokerAccountId,
    CalculationMetadata,
    CalculationRunId,
    CashFlowClassification,
    Coverage,
    CurrencyCode,
    DataQuality,
    DiscrepancyId,
    DiscrepancySeverity,
    DiscrepancyType,
    DomainWarning,
    FxRate,
    Instant,
    ListingId,
    Money,
    ProvenanceReference,
    QualityState,
    Quantity,
    ReconciliationDiscrepancy,
    ReconciliationRun,
    ReconciliationRunId,
    ReconciliationStatus,
    ResolutionState,
    SnapshotId,
    SourceRecordId,
    Transaction,
    TransactionId,
    TransactionStatus,
    TransactionType,
    ValueOrigin,
    canonical_json,
    quantize_boundary,
)
from trading212_persistence.models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    CashBalanceObservationModel,
    CashFlowModel,
    DividendModel,
    IngestionCheckpointModel,
    InstrumentModel,
    LedgerEntryModel,
    ListingModel,
    OrderObservationModel,
    PositionObservationModel,
    SourceRecordModel,
    SourceRecordOccurrenceModel,
    TransactionModel,
)
from trading212_persistence.repositories import (
    ReconciliationDiscrepancyWrite,
    ReconciliationRepository,
    SnapshotRepository,
    SnapshotWriteContext,
)

MAPPING_VERSION = "provider-normalization/1.0.0"
INPUT_SCHEMA_VERSION = "1.0.0"
OUTPUT_SCHEMA_VERSION = "1.0.0"
_PERSISTED_VALUE_QUANTUM = Decimal("0.000000000000000001")
_EXACT_OPERATION_PRECISION = 78
_IDENTITY_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "trading212-portfolio-intelligence/canonical-materialization",
)
_CURRENT_STATE_CAPABILITIES = frozenset(
    {
        IngestionCapability.ACCOUNT,
        IngestionCapability.POSITIONS,
        IngestionCapability.PENDING_ORDERS,
    }
)


class MaterializationError(RuntimeError):
    """Sanitized failure raised when retained source data cannot be normalized safely."""


@dataclass(frozen=True, slots=True)
class MaterializationResult:
    normalized_rows: int
    snapshot_id: UUID
    reconciliation_run_id: UUID


@dataclass(frozen=True, slots=True)
class _PositionInput:
    record: SourceRecordModel
    listing_id: UUID
    quantity: Decimal
    current_price: Decimal | None
    average_price: Decimal | None
    market_value: Decimal
    cost_basis: Decimal | None
    unrealized_pnl: Decimal | None
    valuation_currency: str
    reporting_market_value: Decimal | None
    reporting_cost_basis: Decimal | None
    reporting_unrealized_pnl: Decimal | None
    fx_rate: FxRate | None


@dataclass(frozen=True, slots=True)
class _AccountInput:
    record: SourceRecordModel
    currency: str
    cash: Decimal
    total_value: Decimal
    provider_total_comparable: bool


class PostgresCanonicalMaterializer:
    """Materialize one successful retained-source view inside the caller transaction."""

    def materialize(
        self,
        session: Session,
        *,
        run_id: UUID,
        account_id: UUID,
        now: datetime,
        capabilities: Sequence[IngestionCapability],
    ) -> MaterializationResult:
        timestamp = _utc(now)
        account = session.get(BrokerAccountModel, account_id)
        if account is None:
            raise MaterializationError("materialization account is unavailable")
        connection = session.get(BrokerConnectionModel, account.connection_id)
        if connection is None:
            raise MaterializationError("materialization connection is unavailable")

        selected = frozenset(capabilities)
        if not selected:
            raise MaterializationError("successful refresh selected no capabilities")
        records = _source_records_for_run(session, account_id, run_id, selected)
        if not records:
            raise MaterializationError("successful refresh retained no source records")
        if any(record.provider != connection.provider for record in records):
            raise MaterializationError("source provider does not match the account connection")
        _require_complete_checkpoints(session, account_id, run_id, selected)
        grouped = _group_by_capability(records)

        listings, normalized = self._materialize_instruments(
            session,
            records=grouped.get(IngestionCapability.INSTRUMENTS, ()),
            provider=connection.provider,
            environment=connection.environment,
        )
        account_input = self._account_input(
            grouped,
            account,
            timestamp,
            provider=connection.provider,
        )
        account.base_currency = account_input.currency
        account.last_seen_at = timestamp

        positions, position_count = self._materialize_positions(
            session,
            records=grouped.get(IngestionCapability.POSITIONS, ()),
            account_id=account_id,
            provider=connection.provider,
            environment=connection.environment,
            listings=listings,
            valuation_currency=account_input.currency,
        )
        normalized += position_count
        normalized += self._materialize_cash(session, account_id, account_input)

        transactions, transaction_sources, transaction_count = self._materialize_transactions(
            session,
            account_id=account_id,
            records=grouped.get(IngestionCapability.TRANSACTIONS, ()),
        )
        normalized += transaction_count
        history_complete = _checkpoint_complete(
            session,
            account_id,
            IngestionCapability.TRANSACTIONS,
        )
        ledger = project_ledger(
            transactions,
            account_id=BrokerAccountId(account_id),
            history_complete=history_complete,
        )
        normalized += self._materialize_transaction_ledger(
            session,
            account_id=account_id,
            projection=ledger,
            source_ids=transaction_sources,
        )

        dividend_references, dividend_count = self._materialize_dividends(
            session,
            account_id=account_id,
            records=grouped.get(IngestionCapability.DIVIDENDS, ()),
            provider=connection.provider,
            environment=connection.environment,
            listings=listings,
            transaction_references=frozenset(transaction_sources),
        )
        del dividend_references
        normalized += dividend_count
        normalized += self._materialize_orders(
            session,
            account_id=account_id,
            records=(
                *grouped.get(IngestionCapability.PENDING_ORDERS, ()),
                *grouped.get(IngestionCapability.HISTORICAL_ORDERS, ()),
            ),
            provider=connection.provider,
            environment=connection.environment,
            listings=listings,
        )

        if max(record.observed_at for record in records) > timestamp:
            raise MaterializationError("source observation is later than materialization time")
        source_cutoff = timestamp
        snapshot_id = self._materialize_snapshot(
            session,
            account_id=account_id,
            account=account_input,
            positions=positions,
            ledger_projection=ledger,
            records=records,
            source_cutoff=source_cutoff,
            calculated_at=timestamp,
            run_id=run_id,
        )
        reconciliation_id = self._materialize_reconciliation(
            session,
            account_id=account_id,
            account=account_input,
            positions=positions,
            records=records,
            source_cutoff=source_cutoff,
            calculated_at=timestamp,
            run_id=run_id,
        )
        session.flush()
        return MaterializationResult(
            normalized_rows=normalized + 2,
            snapshot_id=snapshot_id,
            reconciliation_run_id=reconciliation_id,
        )

    def _materialize_instruments(
        self,
        session: Session,
        *,
        records: Sequence[SourceRecordModel],
        provider: str,
        environment: str,
    ) -> tuple[dict[str, UUID], int]:
        listings: dict[str, UUID] = {}
        count = 0
        for record in sorted(records, key=_record_sort_key):
            payload = _payload(record)
            ticker = _text(payload.get("ticker"), field="instrument.ticker", maximum=80)
            provider_id = record.provider_record_id or ticker
            name = _text(payload.get("name"), field="instrument.name", maximum=300)
            instrument_type = _text(
                payload.get("type"), field="instrument.type", maximum=80
            ).casefold()
            currency = _currency(payload.get("currencyCode"))
            isin = _optional_text(payload.get("isin"), field="instrument.isin", maximum=12)
            valid_from = _optional_datetime(payload.get("addedOn")) or record.observed_at
            instrument_id = _upsert_instrument(
                session,
                provider=provider,
                environment=environment,
                provider_id=provider_id,
                canonical_name=name,
                instrument_type=instrument_type,
                isin=isin,
                observed_at=record.observed_at,
            )
            listing_id = _upsert_listing(
                session,
                instrument_id=instrument_id,
                provider=provider,
                environment=environment,
                provider_id=provider_id,
                ticker=ticker,
                currency=currency,
                valid_from=valid_from,
                observed_at=record.observed_at,
            )
            _bind_listing(listings, provider_id, ticker, listing_id)
            count += 2
        return listings, count

    def _account_input(
        self,
        grouped: Mapping[IngestionCapability, tuple[SourceRecordModel, ...]],
        account: BrokerAccountModel,
        now: datetime,
        *,
        provider: str,
    ) -> _AccountInput:
        records = grouped.get(IngestionCapability.ACCOUNT, ())
        if not records:
            raise MaterializationError("account summary source record is unavailable")
        record = max(records, key=lambda item: (item.observed_at, item.created_at, str(item.id)))
        payload = _payload(record)
        currency = _currency(payload.get("currency") or account.base_currency)
        cash_payload = _mapping(payload.get("cash"), field="account.cash")
        total_value = _decimal(payload.get("totalValue"), field="account.totalValue")
        cash = sum(
            (
                _decimal(cash_payload.get("availableToTrade"), field="cash.availableToTrade"),
                _decimal(cash_payload.get("inPies"), field="cash.inPies"),
                _decimal(
                    cash_payload.get("reservedForOrders"),
                    field="cash.reservedForOrders",
                ),
            ),
            Decimal("0"),
        )
        if cash < 0:
            raise MaterializationError("account cash residual is negative")
        if record.observed_at > now:
            raise MaterializationError("account observation is later than materialization time")
        return _AccountInput(
            record,
            currency,
            cash,
            total_value,
            provider_total_comparable=provider == "synthetic",
        )

    def _materialize_positions(
        self,
        session: Session,
        *,
        records: Sequence[SourceRecordModel],
        account_id: UUID,
        provider: str,
        environment: str,
        listings: dict[str, UUID],
        valuation_currency: str,
    ) -> tuple[tuple[_PositionInput, ...], int]:
        values: list[_PositionInput] = []
        count = 0
        for record in sorted(records, key=_record_sort_key):
            payload = _payload(record)
            instrument = _mapping(payload.get("instrument"), field="position.instrument")
            listing_id = _resolve_listing(
                session,
                provider=provider,
                environment=environment,
                reference=instrument,
                record=record,
                listings=listings,
            )
            wallet = _mapping(payload.get("walletImpact"), field="position.walletImpact")
            wallet_currency = _currency(wallet.get("currency") or valuation_currency)
            quantity = _decimal(payload.get("quantity"), field="position.quantity")
            if quantity < 0:
                raise MaterializationError("position quantity is negative")
            current_price = _optional_decimal(payload.get("currentPrice"), field="currentPrice")
            average_price = _optional_decimal(
                payload.get("averagePricePaid"), field="averagePricePaid"
            )
            market_value = _decimal(wallet.get("currentValue"), field="currentValue")
            cost_basis = _optional_decimal(wallet.get("totalCost"), field="totalCost")
            unrealized = _optional_decimal(
                wallet.get("unrealizedProfitLoss"), field="unrealizedProfitLoss"
            )
            fx_rate = _position_fx_rate(
                wallet,
                wallet_currency=wallet_currency,
                reporting_currency=valuation_currency,
                record=record,
            )
            reporting_market_value = _reporting_value(
                market_value,
                source_currency=wallet_currency,
                reporting_currency=valuation_currency,
                fx_rate=fx_rate,
            )
            reporting_cost_basis = _reporting_value(
                cost_basis,
                source_currency=wallet_currency,
                reporting_currency=valuation_currency,
                fx_rate=fx_rate,
            )
            reporting_unrealized = _reporting_value(
                unrealized,
                source_currency=wallet_currency,
                reporting_currency=valuation_currency,
                fx_rate=fx_rate,
            )
            instrument_currency = _currency(instrument.get("currency"))
            persisted_current_price = (
                current_price if instrument_currency == wallet_currency else None
            )
            statement = (
                insert(PositionObservationModel)
                .values(
                    id=_stable_uuid("position-observation", str(record.id)),
                    broker_account_id=account_id,
                    listing_id=listing_id,
                    quantity=quantity,
                    current_price=persisted_current_price,
                    provider_average_price=(
                        average_price if instrument_currency == wallet_currency else None
                    ),
                    provider_market_value=market_value,
                    provider_unrealized_pnl=unrealized,
                    valuation_currency=wallet_currency,
                    observed_at=record.observed_at,
                    source_record_id=record.id,
                )
                .on_conflict_do_nothing(
                    constraint="uq_position_observations_account_listing_observed"
                )
            )
            session.execute(statement)
            values.append(
                _PositionInput(
                    record=record,
                    listing_id=listing_id,
                    quantity=quantity,
                    current_price=persisted_current_price,
                    average_price=average_price,
                    market_value=market_value,
                    cost_basis=cost_basis,
                    unrealized_pnl=unrealized,
                    valuation_currency=wallet_currency,
                    reporting_market_value=reporting_market_value,
                    reporting_cost_basis=reporting_cost_basis,
                    reporting_unrealized_pnl=reporting_unrealized,
                    fx_rate=fx_rate,
                )
            )
            count += 1
        return tuple(values), count

    def _materialize_cash(
        self,
        session: Session,
        account_id: UUID,
        account: _AccountInput,
    ) -> int:
        session.execute(
            insert(CashBalanceObservationModel)
            .values(
                id=_stable_uuid("cash-observation", str(account.record.id)),
                broker_account_id=account_id,
                amount=account.cash,
                currency=account.currency,
                observed_at=account.record.observed_at,
                source_record_id=account.record.id,
            )
            .on_conflict_do_nothing(constraint="uq_cash_observations_account_currency_observed")
        )
        return 1

    def _materialize_transactions(
        self,
        session: Session,
        *,
        account_id: UUID,
        records: Sequence[SourceRecordModel],
    ) -> tuple[tuple[Transaction, ...], dict[str, SourceRecordModel], int]:
        transactions: list[Transaction] = []
        sources: dict[str, SourceRecordModel] = {}
        for record in sorted(records, key=_record_sort_key):
            payload = _payload(record)
            reference = _text(
                payload.get("reference") or record.provider_record_id,
                field="transaction.reference",
                maximum=255,
            )
            transaction_type = _transaction_type(payload.get("type"))
            amount = _decimal(payload.get("amount"), field="transaction.amount")
            currency = _currency(payload.get("currency"))
            occurred_at = _datetime(payload.get("dateTime"), field="transaction.dateTime")
            transaction_id = _stable_uuid("transaction", str(account_id), reference)
            provenance = _provenance(record)
            transaction = Transaction(
                id=TransactionId(transaction_id),
                broker_account_id=BrokerAccountId(account_id),
                provider_transaction_id=reference,
                transaction_type=transaction_type,
                status=TransactionStatus.POSTED,
                net_cash_amount=Money(amount, CurrencyCode(currency)),
                occurred_at=Instant(occurred_at),
                provenance=provenance,
            )
            transactions.append(transaction)
            sources[reference] = record
            session.execute(
                insert(TransactionModel)
                .values(
                    id=transaction_id,
                    broker_account_id=account_id,
                    provider_transaction_id=reference,
                    transaction_type=transaction_type.value,
                    status=TransactionStatus.POSTED.value,
                    instrument_listing_id=None,
                    quantity=None,
                    unit_price=None,
                    gross_amount=None,
                    fees=None,
                    taxes=None,
                    net_cash_amount=amount,
                    currency=currency,
                    occurred_at=occurred_at,
                    settlement_date=None,
                    source_record_id=record.id,
                    mapping_version=MAPPING_VERSION,
                )
                .on_conflict_do_update(
                    constraint="uq_transactions_account_provider_id",
                    set_={
                        "transaction_type": transaction_type.value,
                        "status": TransactionStatus.POSTED.value,
                        "net_cash_amount": amount,
                        "currency": currency,
                        "occurred_at": occurred_at,
                        "source_record_id": record.id,
                        "mapping_version": MAPPING_VERSION,
                    },
                )
            )
        return tuple(transactions), sources, len(transactions)

    def _materialize_transaction_ledger(
        self,
        session: Session,
        *,
        account_id: UUID,
        projection: LedgerProjection,
        source_ids: Mapping[str, SourceRecordModel],
    ) -> int:
        count = 0
        for line in projection.entries:
            record = source_ids[line.provider_transaction_id]
            quality = (
                projection.quality_state.value if line.supported else QualityState.PARTIAL.value
            )
            values = {
                "id": _stable_uuid(
                    "ledger-transaction", str(account_id), line.provider_transaction_id
                ),
                "broker_account_id": account_id,
                "source_transaction_id": cast(UUID, line.transaction_id),
                "source_dividend_id": None,
                "entry_type": line.transaction_type.value,
                "classification": line.classification.value,
                "amount": line.amount.amount,
                "currency": line.amount.currency.value,
                "economic_at": line.occurred_at.value,
                "quality": quality,
                "idempotency_key": _idempotency_key("transaction", line.provider_transaction_id),
                "fx_rate": None,
                "fx_base_currency": None,
                "fx_quote_currency": None,
                "fx_observed_at": None,
                "fx_source": None,
            }
            session.execute(
                insert(LedgerEntryModel)
                .values(**values)
                .on_conflict_do_update(
                    constraint="uq_ledger_entries_account_key",
                    set_={key: value for key, value in values.items() if key != "id"},
                )
            )
            if line.classification is CashFlowClassification.EXTERNAL:
                flow_values = {
                    "id": _stable_uuid("cash-flow", str(account_id), line.provider_transaction_id),
                    "broker_account_id": account_id,
                    "source_transaction_id": cast(UUID, line.transaction_id),
                    "classification": line.classification.value,
                    "flow_type": line.transaction_type.value,
                    "amount": line.amount.amount,
                    "currency": line.amount.currency.value,
                    "occurred_at": line.occurred_at.value,
                    "quality": quality,
                    "active": line.active,
                    "idempotency_key": _idempotency_key("cash-flow", line.provider_transaction_id),
                    "source_record_id": record.id,
                }
                session.execute(
                    insert(CashFlowModel)
                    .values(**flow_values)
                    .on_conflict_do_update(
                        constraint="uq_cash_flows_account_key",
                        set_={key: value for key, value in flow_values.items() if key != "id"},
                    )
                )
            else:
                # A provider may revise an activity while preserving its stable
                # transaction identity. Retain the prior external-flow evidence,
                # but remove it from performance inputs when the canonical
                # classification is no longer external.
                session.execute(
                    update(CashFlowModel)
                    .where(
                        CashFlowModel.broker_account_id == account_id,
                        CashFlowModel.source_transaction_id == cast(UUID, line.transaction_id),
                    )
                    .values(active=False)
                )
            count += 1
        return count

    def _materialize_dividends(
        self,
        session: Session,
        *,
        account_id: UUID,
        records: Sequence[SourceRecordModel],
        provider: str,
        environment: str,
        listings: dict[str, UUID],
        transaction_references: frozenset[str],
    ) -> tuple[frozenset[str], int]:
        references: set[str] = set()
        count = 0
        for record in sorted(records, key=_record_sort_key):
            payload = _payload(record)
            reference = _text(
                payload.get("reference") or record.provider_record_id,
                field="dividend.reference",
                maximum=255,
            )
            instrument = _mapping(payload.get("instrument"), field="dividend.instrument")
            listing_id = _resolve_listing(
                session,
                provider=provider,
                environment=environment,
                reference=instrument,
                record=record,
                listings=listings,
            )
            net = _decimal(payload.get("amount"), field="dividend.amount")
            currency = _currency(payload.get("currency"))
            quantity = _optional_decimal(payload.get("quantity"), field="dividend.quantity")
            per_share = _optional_decimal(
                payload.get("grossAmountPerShare"), field="dividend.grossAmountPerShare"
            )
            gross = per_share * quantity if per_share is not None and quantity is not None else None
            withholding = gross - net if gross is not None and gross >= net else None
            paid_on = _date(payload.get("paidOn"), field="dividend.paidOn")
            dividend_id = _stable_uuid("dividend", str(account_id), reference)
            values = {
                "id": dividend_id,
                "broker_account_id": account_id,
                "provider_dividend_id": reference,
                "instrument_listing_id": listing_id,
                "gross_amount": gross,
                "withholding_tax": withholding,
                "net_amount": net,
                "currency": currency,
                "quantity": quantity,
                "paid_on": paid_on,
                "source_record_id": record.id,
            }
            session.execute(
                insert(DividendModel)
                .values(**values)
                .on_conflict_do_update(
                    constraint="uq_dividends_account_provider_id",
                    set_={key: value for key, value in values.items() if key != "id"},
                )
            )
            if reference not in transaction_references:
                ledger_values = {
                    "id": _stable_uuid("ledger-dividend", str(account_id), reference),
                    "broker_account_id": account_id,
                    "source_transaction_id": None,
                    "source_dividend_id": dividend_id,
                    "entry_type": TransactionType.DIVIDEND.value,
                    "classification": CashFlowClassification.INTERNAL.value,
                    "amount": net,
                    "currency": currency,
                    "economic_at": datetime.combine(paid_on, time.min, tzinfo=UTC),
                    "quality": QualityState.FRESH.value,
                    "idempotency_key": _idempotency_key("dividend", reference),
                    "fx_rate": None,
                    "fx_base_currency": None,
                    "fx_quote_currency": None,
                    "fx_observed_at": None,
                    "fx_source": None,
                }
                session.execute(
                    insert(LedgerEntryModel)
                    .values(**ledger_values)
                    .on_conflict_do_update(
                        constraint="uq_ledger_entries_account_key",
                        set_={key: value for key, value in ledger_values.items() if key != "id"},
                    )
                )
            references.add(reference)
            count += 1
        return frozenset(references), count

    def _materialize_orders(
        self,
        session: Session,
        *,
        account_id: UUID,
        records: Sequence[SourceRecordModel],
        provider: str,
        environment: str,
        listings: dict[str, UUID],
    ) -> int:
        count = 0
        for record in sorted(records, key=_record_sort_key):
            outer = _payload(record)
            payload = (
                _mapping(outer.get("order"), field="historical_order.order")
                if "order" in outer
                else outer
            )
            provider_order_id = _text(
                payload.get("id") or record.provider_record_id,
                field="order.id",
                maximum=255,
            )
            instrument = _mapping(payload.get("instrument"), field="order.instrument")
            listing_id = _resolve_listing(
                session,
                provider=provider,
                environment=environment,
                reference=instrument,
                record=record,
                listings=listings,
            )
            side = _text(payload.get("side"), field="order.side", maximum=10).casefold()
            if side not in {"buy", "sell"}:
                raise MaterializationError("order side is not supported")
            status = _text(payload.get("status"), field="order.status", maximum=80)
            submitted_at = _optional_datetime(payload.get("createdAt"))
            completed_at = (
                record.source_updated_at
                if status.casefold() in {"filled", "cancelled", "rejected"}
                else None
            )
            currency = _optional_currency(payload.get("currency"))
            values = {
                "id": _stable_uuid("order-observation", str(record.id)),
                "broker_account_id": account_id,
                "provider_order_id": provider_order_id,
                "instrument_listing_id": listing_id,
                "side": side,
                "order_type": _text(payload.get("type"), field="order.type", maximum=80),
                "status": status,
                "requested_quantity": _optional_decimal(
                    payload.get("quantity"), field="order.quantity"
                ),
                "requested_value": _optional_decimal(payload.get("value"), field="order.value"),
                "filled_quantity": _optional_decimal(
                    payload.get("filledQuantity"), field="order.filledQuantity"
                ),
                "filled_value": _optional_decimal(
                    payload.get("filledValue"), field="order.filledValue"
                ),
                "currency": currency,
                "submitted_at": submitted_at,
                "provider_updated_at": record.source_updated_at,
                "completed_at": completed_at,
                "observed_at": record.observed_at,
                "source_record_id": record.id,
            }
            session.execute(
                insert(OrderObservationModel)
                .values(**values)
                .on_conflict_do_update(
                    constraint="uq_order_observations_account_order_observed",
                    set_={key: value for key, value in values.items() if key != "id"},
                )
            )
            count += 1
        return count

    def _materialize_snapshot(
        self,
        session: Session,
        *,
        account_id: UUID,
        account: _AccountInput,
        positions: tuple[_PositionInput, ...],
        ledger_projection: LedgerProjection,
        records: tuple[SourceRecordModel, ...],
        source_cutoff: datetime,
        calculated_at: datetime,
        run_id: UUID,
    ) -> UUID:
        reporting_currency = CurrencyCode(account.currency)
        valued_positions = tuple(
            ValuedPositionInput(
                account_id=BrokerAccountId(account_id),
                listing_id=ListingId(position.listing_id),
                quantity=Quantity(position.quantity),
                valuation_currency=CurrencyCode(
                    account.currency
                    if position.reporting_market_value is not None
                    else position.valuation_currency
                ),
                provider_market_value=Money(
                    (
                        position.reporting_market_value
                        if position.reporting_market_value is not None
                        else position.market_value
                    ),
                    CurrencyCode(
                        account.currency
                        if position.reporting_market_value is not None
                        else position.valuation_currency
                    ),
                ),
                provider_cost_basis=(
                    None
                    if position.cost_basis is None
                    else Money(
                        (
                            position.reporting_cost_basis
                            if position.reporting_cost_basis is not None
                            else position.cost_basis
                        ),
                        CurrencyCode(
                            account.currency
                            if position.reporting_cost_basis is not None
                            else position.valuation_currency
                        ),
                    )
                ),
                provider_unrealized_pnl=(
                    None
                    if position.unrealized_pnl is None
                    else Money(
                        (
                            position.reporting_unrealized_pnl
                            if position.reporting_unrealized_pnl is not None
                            else position.unrealized_pnl
                        ),
                        CurrencyCode(
                            account.currency
                            if position.reporting_unrealized_pnl is not None
                            else position.valuation_currency
                        ),
                    )
                ),
            )
            for position in positions
        )
        cash = (
            CashComponentInput(
                account_id=BrokerAccountId(account_id),
                component_key=account.currency,
                amount=Money(account.cash, reporting_currency),
            ),
        )
        valuation = Instant(source_cutoff)
        aggregate = aggregate_portfolio(
            account_id=BrokerAccountId(account_id),
            positions=valued_positions,
            cash_components=cash,
            reporting_currency=reporting_currency,
            fx_quotes=(),
            valuation_at=valuation,
            source_cutoff_at=valuation,
        )
        accounting = summarize_ledger_accounting(
            ledger_projection,
            reporting_currency=reporting_currency,
            fx_quotes=(),
            source_cutoff_at=valuation,
        )
        quality_state = combine_quality((aggregate.quality_state, accounting.quality_state))
        warnings = tuple(dict.fromkeys((*aggregate.warnings, *accounting.warnings)))
        coverage = _coverage(records, end_at=source_cutoff)
        quality = DataQuality(
            state=quality_state,
            evaluated_at=Instant(calculated_at),
            freshness_threshold_seconds=900,
            coverage=coverage,
            warnings=warnings,
            missing_inputs=aggregate.missing_inputs,
        )
        input_fingerprint = _input_fingerprint(records, run_id=run_id)
        calculation_id = CalculationRunId(
            _stable_uuid("calculation", str(account_id), input_fingerprint)
        )
        metadata = CalculationMetadata(
            calculation_name=PORTFOLIO_METHOD_ID,
            version=PORTFOLIO_VERSION,
            run_id=calculation_id,
            calculated_at=Instant(calculated_at),
            valuation_at=valuation,
            source_cutoff_at=valuation,
            reporting_currency=reporting_currency,
            input_ids=tuple(record.id for record in records),
            method="Exact provider observations aggregated without implicit FX or missing-as-zero",
            assumptions=_fx_assumptions(positions, reporting_currency=account.currency),
            data_quality=quality,
            options={
                "fx_policy": "explicit_only",
                "fx_quotes": _fx_options(positions),
            },
        )
        snapshot_id = SnapshotId(_stable_uuid("snapshot", str(account_id), input_fingerprint))
        snapshot = build_portfolio_snapshot(
            aggregate,
            snapshot_id=snapshot_id,
            positions=valued_positions,
            cash_components=cash,
            calculation=metadata,
            accounting=accounting,
        )
        output_fingerprint = _hash_json(
            {
                "cash": _decimal_text(snapshot.cash_total.amount if snapshot.cash_total else None),
                "invested": _decimal_text(
                    snapshot.invested_total.amount if snapshot.invested_total else None
                ),
                "total": _decimal_text(
                    snapshot.portfolio_total.amount if snapshot.portfolio_total else None
                ),
                "positions": [
                    {
                        "listing_id": str(position.listing_id),
                        "quantity": _decimal_text(position.quantity.value),
                        "market_value": _decimal_text(
                            position.market_value.amount if position.market_value else None
                        ),
                    }
                    for position in snapshot.positions
                ],
            }
        )
        position_provenance = {
            ListingId(position.listing_id): _provenance(position.record) for position in positions
        }
        context = SnapshotWriteContext(
            input_schema_version=INPUT_SCHEMA_VERSION,
            output_schema_version=OUTPUT_SCHEMA_VERSION,
            input_fingerprint=input_fingerprint,
            output_fingerprint=output_fingerprint,
            position_currencies={
                valued.listing_id: valued.valuation_currency for valued in valued_positions
            },
            position_provenance=position_provenance,
            cash_provenance={reporting_currency: _provenance(account.record)},
        )
        result = SnapshotRepository(session).persist_immutable(snapshot, context=context)
        return result.snapshot_id

    def _materialize_reconciliation(
        self,
        session: Session,
        *,
        account_id: UUID,
        account: _AccountInput,
        positions: tuple[_PositionInput, ...],
        records: tuple[SourceRecordModel, ...],
        source_cutoff: datetime,
        calculated_at: datetime,
        run_id: UUID,
    ) -> UUID:
        currency = CurrencyCode(account.currency)
        missing_fx_positions = tuple(
            position for position in positions if position.reporting_market_value is None
        )
        provider_total_comparable = account.provider_total_comparable and not missing_fx_positions
        canonical_total = Money(
            (
                account.cash
                if missing_fx_positions
                else account.cash
                + sum(
                    (cast(Decimal, position.reporting_market_value) for position in positions),
                    Decimal("0"),
                )
            ),
            currency,
        )
        result = reconcile_portfolio(
            account_id=BrokerAccountId(account_id),
            value_bridges=(
                ValueBridgeInput(
                    account_id=BrokerAccountId(account_id),
                    canonical_total=canonical_total,
                    provider_total=(
                        None
                        if not provider_total_comparable
                        else Money(account.total_value, currency)
                    ),
                    quality_state=(
                        QualityState.PARTIAL
                        if not provider_total_comparable
                        else QualityState.FRESH
                    ),
                    comparable_valuation=provider_total_comparable,
                ),
            ),
        )
        fx_issues = tuple(
            ReconciliationIssue(
                discrepancy_type=DiscrepancyType.CURRENCY_FX_GAP,
                severity=DiscrepancySeverity.WARNING,
                scope=f"listing:{position.listing_id}",
                expected=None,
                observed=position.market_value,
                residual=None,
                tolerance=None,
                downstream_effect=(
                    "A source-currency position is excluded from the account-currency "
                    "value bridge until an explicit sourced FX rate is available."
                ),
                currency=CurrencyCode(position.valuation_currency),
                listing_id=ListingId(position.listing_id),
            )
            for position in missing_fx_positions
        )
        fx_warnings = tuple(
            DomainWarning(
                "currency_fx_gap",
                "An explicit sourced FX rate is required for portfolio-value reconciliation.",
                (str(position.listing_id), position.valuation_currency, account.currency),
            )
            for position in missing_fx_positions
        )
        provider_semantics_issues = (
            (
                ReconciliationIssue(
                    discrepancy_type=DiscrepancyType.SCHEMA_MAPPING_CHANGE,
                    severity=DiscrepancySeverity.WARNING,
                    scope="account_summary.totalValue",
                    expected=canonical_total.amount,
                    observed=account.total_value,
                    residual=None,
                    tolerance=None,
                    downstream_effect=(
                        "The official account-summary prose and schema assign conflicting "
                        "semantics to totalValue; the field is retained but excluded from "
                        "value reconciliation until Demo behavior is verified."
                    ),
                    currency=currency,
                ),
            )
            if not account.provider_total_comparable
            else ()
        )
        provider_semantics_warnings = (
            (
                DomainWarning(
                    "provider_total_semantics_unverified",
                    "Conflicting official totalValue semantics prevent a comparable value bridge.",
                    ("account_summary.totalValue",),
                ),
            )
            if not account.provider_total_comparable
            else ()
        )
        history_gap = ReconciliationIssue(
            discrepancy_type=DiscrepancyType.PROVIDER_HISTORY_COVERAGE_GAP,
            severity=DiscrepancySeverity.WARNING,
            scope="quantity_cash_history",
            expected=None,
            observed=None,
            residual=None,
            tolerance=None,
            downstream_effect=(
                "Quantity and cash movement bridges remain partial because the provider "
                "history cannot establish opening balances."
            ),
        )
        history_warning = DomainWarning(
            "quantity_cash_history_coverage_gap",
            "Opening quantity and cash balances are unavailable for complete bridge checks.",
        )
        result = replace(
            result,
            coverage_complete=False,
            status=(
                ReconciliationStatus.PARTIAL
                if result.status is ReconciliationStatus.RECONCILED
                else result.status
            ),
            quality_state=(
                QualityState.PARTIAL
                if result.quality_state is QualityState.FRESH
                else result.quality_state
            ),
            discrepancies=(
                *result.discrepancies,
                *fx_issues,
                *provider_semantics_issues,
                history_gap,
            ),
            warnings=(
                *result.warnings,
                *fx_warnings,
                *provider_semantics_warnings,
                history_warning,
            ),
        )
        input_fingerprint = _hash_json(
            {
                "source": _input_fingerprint(records, run_id=run_id),
                "canonical_total": _decimal_text(canonical_total.amount),
                "provider_total": _decimal_text(account.total_value),
                "version": result.version,
            }
        )
        run_id = ReconciliationRunId(
            _stable_uuid("reconciliation", str(account_id), input_fingerprint)
        )
        coverage = _coverage(
            records,
            end_at=source_cutoff,
            complete=result.coverage_complete,
        )
        run = ReconciliationRun(
            id=run_id,
            broker_account_id=BrokerAccountId(account_id),
            as_of=Instant(source_cutoff),
            algorithm_version=RECONCILIATION_VERSION,
            tolerance_version=result.tolerance_version,
            status=result.status,
            coverage=coverage,
            discrepancy_count=len(result.discrepancies),
            warnings=result.warnings,
        )
        provenance = ProvenanceReference(
            source_record_ids=tuple(SourceRecordId(record.id) for record in records),
            mapping_version=MAPPING_VERSION,
            origin=ValueOrigin.DERIVED_DETERMINISTIC,
        )
        discrepancy_writes = tuple(
            ReconciliationDiscrepancyWrite(
                ReconciliationDiscrepancy(
                    id=DiscrepancyId(
                        _stable_uuid(
                            "reconciliation-discrepancy",
                            str(run_id),
                            issue.discrepancy_type.value,
                            issue.scope,
                        )
                    ),
                    reconciliation_run_id=run_id,
                    broker_account_id=BrokerAccountId(account_id),
                    listing_id=issue.listing_id,
                    discrepancy_type=issue.discrepancy_type,
                    severity=issue.severity,
                    resolution_state=ResolutionState.OPEN,
                    first_seen_at=Instant(source_cutoff),
                    last_seen_at=Instant(source_cutoff),
                    expected_value=issue.expected,
                    observed_value=issue.observed,
                    residual=issue.residual,
                    tolerance=issue.tolerance,
                    downstream_effect=issue.downstream_effect,
                    currency=issue.currency,
                ),
                provenance,
            )
            for issue in result.discrepancies
        )
        persisted = ReconciliationRepository(session).persist_immutable(
            run,
            input_fingerprint=input_fingerprint,
            quality_state=result.quality_state,
            provenance=provenance,
            discrepancies=discrepancy_writes,
        )
        del calculated_at
        return persisted.reconciliation_run_id


def _source_records_for_run(
    session: Session,
    account_id: UUID,
    run_id: UUID,
    selected_capabilities: frozenset[IngestionCapability],
) -> tuple[SourceRecordModel, ...]:
    current_capability_values = tuple(
        capability.value for capability in _CURRENT_STATE_CAPABILITIES
    )
    latest: dict[tuple[str, str], SourceRecordModel] = {}
    for capability in sorted(_CURRENT_STATE_CAPABILITIES, key=lambda item: item.value):
        publication_run_id = (
            run_id
            if capability in selected_capabilities
            else _checkpoint_publication_run_id(session, account_id, capability)
        )
        current_candidates = tuple(
            session.scalars(
                select(SourceRecordModel)
                .join(
                    SourceRecordOccurrenceModel,
                    SourceRecordOccurrenceModel.source_record_id == SourceRecordModel.id,
                )
                .where(
                    SourceRecordOccurrenceModel.ingestion_run_id == publication_run_id,
                    SourceRecordModel.broker_account_id == account_id,
                    SourceRecordModel.capability == capability.value,
                )
                .order_by(
                    SourceRecordOccurrenceModel.observed_at.desc(),
                    SourceRecordModel.created_at.desc(),
                    SourceRecordModel.id.desc(),
                )
            )
        )
        for record in current_candidates:
            identity = record.provider_record_id or record.payload_fingerprint
            latest.setdefault((record.capability, identity), record)

    historical_candidates = tuple(
        session.scalars(
            select(SourceRecordModel)
            .join(
                SourceRecordOccurrenceModel,
                SourceRecordOccurrenceModel.source_record_id == SourceRecordModel.id,
            )
            .where(
                SourceRecordModel.broker_account_id == account_id,
                SourceRecordModel.capability.not_in(current_capability_values),
            )
            .order_by(
                SourceRecordOccurrenceModel.observed_at.desc(),
                SourceRecordModel.created_at.desc(),
                SourceRecordModel.id.desc(),
            )
        )
    )
    for record in historical_candidates:
        identity = record.provider_record_id or record.payload_fingerprint
        latest.setdefault((record.capability, identity), record)
    return tuple(sorted(latest.values(), key=_record_sort_key))


def _checkpoint_publication_run_id(
    session: Session,
    account_id: UUID,
    capability: IngestionCapability,
) -> UUID:
    checkpoint = session.scalar(
        select(IngestionCheckpointModel).where(
            IngestionCheckpointModel.broker_account_id == account_id,
            IngestionCheckpointModel.capability == capability.value,
        )
    )
    if (
        checkpoint is None
        or not checkpoint.coverage_complete
        or checkpoint.advanced_by_run_id is None
    ):
        raise MaterializationError(f"no complete publication exists for {capability.value}")
    return checkpoint.advanced_by_run_id


def _group_by_capability(
    records: Sequence[SourceRecordModel],
) -> dict[IngestionCapability, tuple[SourceRecordModel, ...]]:
    grouped: dict[IngestionCapability, list[SourceRecordModel]] = {}
    for record in records:
        try:
            capability = IngestionCapability(record.capability)
        except ValueError:
            continue
        grouped.setdefault(capability, []).append(record)
    return {key: tuple(value) for key, value in grouped.items()}


def _require_complete_checkpoints(
    session: Session,
    account_id: UUID,
    run_id: UUID,
    selected_capabilities: frozenset[IngestionCapability],
) -> None:
    checkpoints = {
        model.capability: model
        for model in session.scalars(
            select(IngestionCheckpointModel).where(
                IngestionCheckpointModel.broker_account_id == account_id
            )
        )
    }
    missing = [
        capability.value
        for capability in FULL_REFRESH_ORDER
        if capability.value not in checkpoints
        or not checkpoints[capability.value].coverage_complete
        or (
            capability in selected_capabilities
            and checkpoints[capability.value].advanced_by_run_id != run_id
        )
    ]
    if missing:
        raise MaterializationError("successful refresh has incomplete capability coverage")


def _checkpoint_complete(
    session: Session,
    account_id: UUID,
    capability: IngestionCapability,
) -> bool:
    value = session.scalar(
        select(IngestionCheckpointModel.coverage_complete).where(
            IngestionCheckpointModel.broker_account_id == account_id,
            IngestionCheckpointModel.capability == capability.value,
        )
    )
    return bool(value)


def _record_sort_key(record: SourceRecordModel) -> tuple[str, str, datetime, str]:
    return (
        record.capability,
        record.provider_record_id or record.payload_fingerprint,
        record.observed_at,
        str(record.id),
    )


def _payload(record: SourceRecordModel) -> dict[str, object]:
    restored = _restore_json(record.sanitized_payload)
    if not isinstance(restored, dict):
        raise MaterializationError("source payload is not an object")
    return cast(dict[str, object], restored)


def _restore_json(value: object) -> object:
    if isinstance(value, Mapping):
        if set(value) == {"$decimal"}:
            raw = value["$decimal"]
            if not isinstance(raw, str):
                raise MaterializationError("persisted decimal marker is invalid")
            try:
                parsed = Decimal(raw)
            except Exception as exc:
                raise MaterializationError("persisted decimal marker is invalid") from exc
            if not parsed.is_finite():
                raise MaterializationError("persisted decimal marker is not finite")
            return parsed
        if set(value) == {"$datetime"}:
            raw = value["$datetime"]
            if not isinstance(raw, str):
                raise MaterializationError("persisted datetime marker is invalid")
            return _utc(datetime.fromisoformat(raw))
        if set(value) == {"$date"}:
            raw = value["$date"]
            if not isinstance(raw, str):
                raise MaterializationError("persisted date marker is invalid")
            return date.fromisoformat(raw)
        return {str(key): _restore_json(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_restore_json(child) for child in value]
    return value


def _mapping(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise MaterializationError(f"{field} is not an object")
    return {str(key): child for key, child in value.items()}


def _position_fx_rate(
    wallet: Mapping[str, object],
    *,
    wallet_currency: str,
    reporting_currency: str,
    record: SourceRecordModel,
) -> FxRate | None:
    raw_quote = wallet.get("fxRate")
    if raw_quote is None:
        return None
    quote = _mapping(raw_quote, field="position.walletImpact.fxRate")
    base_currency = _currency(quote.get("baseCurrency"))
    quote_currency = _currency(quote.get("quoteCurrency"))
    if base_currency != wallet_currency or quote_currency != reporting_currency:
        raise MaterializationError(
            "position FX quote direction does not match wallet and reporting currencies"
        )
    observed_at = _datetime(
        quote.get("observedAt"),
        field="position.walletImpact.fxRate.observedAt",
    )
    if observed_at > record.observed_at:
        raise MaterializationError("position FX quote follows its source observation")
    rate = _decimal(quote.get("rate"), field="position.walletImpact.fxRate.rate")
    if rate <= 0:
        raise MaterializationError("position FX quote rate is not positive")
    if base_currency == quote_currency and rate != Decimal("1"):
        raise MaterializationError("same-currency position FX quote rate is not one")
    source = _text(
        quote.get("source"),
        field="position.walletImpact.fxRate.source",
        maximum=120,
    )
    return FxRate(
        CurrencyCode(base_currency),
        CurrencyCode(quote_currency),
        rate,
        Instant(observed_at),
        source,
    )


def _reporting_value(
    value: Decimal | None,
    *,
    source_currency: str,
    reporting_currency: str,
    fx_rate: FxRate | None,
) -> Decimal | None:
    if value is None:
        return None
    if source_currency == reporting_currency:
        return value
    if fx_rate is None:
        return None
    with localcontext() as context:
        context.prec = _EXACT_OPERATION_PRECISION
        converted = value * fx_rate.rate
    return quantize_boundary(converted, _PERSISTED_VALUE_QUANTUM)


def _fx_options(positions: Sequence[_PositionInput]) -> list[dict[str, str]]:
    return [
        {
            "listing_id": str(position.listing_id),
            "source_record_id": str(position.record.id),
            "base_currency": rate.base_currency.value,
            "quote_currency": rate.quote_currency.value,
            "rate": _decimal_text(rate.rate) or "0",
            "observed_at": rate.observed_at.value.isoformat().replace("+00:00", "Z"),
            "source": rate.source,
        }
        for position in sorted(positions, key=lambda item: str(item.listing_id))
        if (rate := position.fx_rate) is not None
    ]


def _fx_assumptions(
    positions: Sequence[_PositionInput],
    *,
    reporting_currency: str,
) -> tuple[str, ...]:
    assumptions: list[str] = []
    if any(position.valuation_currency == reporting_currency for position in positions):
        assumptions.append("Same-currency provider wallet values are used without FX conversion.")
    if any(position.fx_rate is not None for position in positions):
        assumptions.append(
            "Cross-currency wallet values use explicit sourced FX observed no later "
            "than the source record."
        )
    if any(position.reporting_market_value is None for position in positions):
        assumptions.append(
            "Cross-currency wallet values without an eligible explicit quote remain unavailable."
        )
    assumptions.append(
        "No implicit FX rate is applied and missing values are never treated as zero."
    )
    return tuple(assumptions)


def _text(value: object, *, field: str, maximum: int) -> str:
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise MaterializationError(f"{field} is invalid")
    return value


def _optional_text(value: object, *, field: str, maximum: int) -> str | None:
    if value in {None, ""}:
        return None
    return _text(value, field=field, maximum=maximum)


def _currency(value: object) -> str:
    currency = _text(value, field="currency", maximum=3)
    if len(currency) != 3 or not currency.isalpha() or currency != currency.upper():
        raise MaterializationError("currency is invalid")
    return currency


def _optional_currency(value: object) -> str | None:
    return None if value is None else _currency(value)


def _decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise MaterializationError(f"{field} is not an exact decimal")
    parsed = Decimal(value)
    if not parsed.is_finite():
        raise MaterializationError(f"{field} is not finite")
    return parsed


def _optional_decimal(value: object, *, field: str) -> Decimal | None:
    return None if value is None else _decimal(value, field=field)


def _datetime(value: object, *, field: str) -> datetime:
    parsed = _optional_datetime(value)
    if parsed is None:
        raise MaterializationError(f"{field} is invalid")
    return parsed


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, str):
        try:
            return _utc(datetime.fromisoformat(value))
        except ValueError as exc:
            raise MaterializationError("timestamp is invalid") from exc
    raise MaterializationError("timestamp is invalid")


def _date(value: object, *, field: str) -> date:
    if isinstance(value, datetime):
        return _utc(value).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise MaterializationError(f"{field} is invalid") from exc
    raise MaterializationError(f"{field} is invalid")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MaterializationError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _transaction_type(value: object) -> TransactionType:
    normalized = _text(value, field="transaction.type", maximum=80).casefold().replace("-", "_")
    aliases = {
        "deposit": TransactionType.DEPOSIT,
        "withdrawal": TransactionType.WITHDRAWAL,
        "withdraw": TransactionType.WITHDRAWAL,
        "buy": TransactionType.BUY,
        "sell": TransactionType.SELL,
        "dividend": TransactionType.DIVIDEND,
        "fee": TransactionType.FEE,
        "tax": TransactionType.TAX_WITHHOLDING,
        "tax_withholding": TransactionType.TAX_WITHHOLDING,
        "interest": TransactionType.INTEREST,
        "transfer": TransactionType.TRANSFER,
        "corporate_action": TransactionType.CORPORATE_ACTION,
        "adjustment": TransactionType.ADJUSTMENT,
    }
    return aliases.get(normalized, TransactionType.UNKNOWN_PROVIDER_ACTIVITY)


def _resolve_listing(
    session: Session,
    *,
    provider: str,
    environment: str,
    reference: Mapping[str, object],
    record: SourceRecordModel,
    listings: dict[str, UUID],
) -> UUID:
    ticker = _text(reference.get("ticker"), field="instrument.ticker", maximum=80)
    provider_id = record.provider_record_id or ticker
    listing_id = listings.get(provider_id) or listings.get(ticker)
    if listing_id is not None:
        return listing_id
    existing = session.scalar(
        select(ListingModel.id).where(
            ListingModel.provider == provider,
            ListingModel.environment == environment,
            ListingModel.ticker == ticker,
        )
    )
    if existing is not None:
        _bind_listing(listings, provider_id, ticker, existing)
        return existing
    isin = _optional_text(reference.get("isin"), field="instrument.isin", maximum=12)
    name = _text(reference.get("name"), field="instrument.name", maximum=300)
    currency = _currency(reference.get("currency"))
    instrument_id = _upsert_instrument(
        session,
        provider=provider,
        environment=environment,
        provider_id=ticker,
        canonical_name=name,
        instrument_type="unknown",
        isin=isin,
        observed_at=record.observed_at,
    )
    listing_id = _upsert_listing(
        session,
        instrument_id=instrument_id,
        provider=provider,
        environment=environment,
        provider_id=ticker,
        ticker=ticker,
        currency=currency,
        valid_from=record.observed_at,
        observed_at=record.observed_at,
    )
    _bind_listing(listings, provider_id, ticker, listing_id)
    return listing_id


def _upsert_instrument(
    session: Session,
    *,
    provider: str,
    environment: str,
    provider_id: str,
    canonical_name: str,
    instrument_type: str,
    isin: str | None,
    observed_at: datetime,
) -> UUID:
    proposed_id = _stable_uuid("instrument", isin or f"{provider}:{environment}:{provider_id}")
    values = {
        "id": proposed_id,
        "canonical_name": canonical_name,
        "instrument_type": instrument_type,
        "isin": isin,
        "created_at": observed_at,
        "updated_at": observed_at,
    }
    statement = insert(InstrumentModel).values(**values)
    if isin is None:
        statement = statement.on_conflict_do_update(
            index_elements=[InstrumentModel.id],
            set_={
                "canonical_name": canonical_name,
                "instrument_type": instrument_type,
                "updated_at": observed_at,
            },
        )
    else:
        statement = statement.on_conflict_do_update(
            index_elements=[InstrumentModel.isin],
            set_={
                "canonical_name": canonical_name,
                "instrument_type": instrument_type,
                "updated_at": observed_at,
            },
        )
    resolved = session.scalar(statement.returning(InstrumentModel.id))
    if resolved is None:
        raise MaterializationError("instrument upsert did not return an identity")
    return resolved


def _upsert_listing(
    session: Session,
    *,
    instrument_id: UUID,
    provider: str,
    environment: str,
    provider_id: str,
    ticker: str,
    currency: str,
    valid_from: datetime,
    observed_at: datetime,
) -> UUID:
    values = {
        "id": _stable_uuid("listing", provider, environment, provider_id),
        "instrument_id": instrument_id,
        "provider": provider,
        "environment": environment,
        "provider_instrument_id": provider_id,
        "ticker": ticker,
        "exchange_mic": None,
        "exchange_id": None,
        "trading_currency": currency,
        "status": "active",
        "valid_from": valid_from,
        "valid_to": None,
        "created_at": observed_at,
        "updated_at": observed_at,
    }
    resolved = session.scalar(
        insert(ListingModel)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_listings_provider_environment_instrument",
            set_={
                "instrument_id": instrument_id,
                "ticker": ticker,
                "trading_currency": currency,
                "status": "active",
                "valid_to": None,
                "updated_at": observed_at,
            },
        )
        .returning(ListingModel.id)
    )
    if resolved is None:
        raise MaterializationError("listing upsert did not return an identity")
    return resolved


def _bind_listing(values: dict[str, UUID], provider_id: str, ticker: str, listing_id: UUID) -> None:
    for key in (provider_id, ticker):
        prior = values.get(key)
        if prior is not None and prior != listing_id:
            raise MaterializationError("instrument reference maps to multiple listings")
        values[key] = listing_id


def _provenance(record: SourceRecordModel) -> ProvenanceReference:
    return ProvenanceReference(
        source_record_ids=(SourceRecordId(record.id),),
        mapping_version=MAPPING_VERSION,
        origin=ValueOrigin.NORMALIZED_PROVIDER,
    )


def _coverage(
    records: Sequence[SourceRecordModel],
    *,
    end_at: datetime,
    complete: bool = True,
) -> Coverage:
    start = min((record.source_updated_at or record.observed_at) for record in records)
    return Coverage(Instant(min(start, end_at)), Instant(end_at), complete)


def _input_fingerprint(records: Sequence[SourceRecordModel], *, run_id: UUID) -> str:
    return _hash_json(
        {
            "run_id": str(run_id),
            "records": [
                {
                    "id": str(record.id),
                    "capability": record.capability,
                    "provider_id": record.provider_record_id,
                    "payload": record.payload_fingerprint,
                }
                for record in sorted(records, key=_record_sort_key)
            ],
        }
    )


def _idempotency_key(prefix: str, value: str) -> str:
    candidate = f"{prefix}:{value}"
    if len(candidate) <= 180:
        return candidate
    return f"{prefix}:sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _stable_uuid(kind: str, *parts: str) -> UUID:
    return uuid5(_IDENTITY_NAMESPACE, "/".join((kind, *parts)))


def _hash_json(value: object) -> str:
    rendered = canonical_json(value).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")
