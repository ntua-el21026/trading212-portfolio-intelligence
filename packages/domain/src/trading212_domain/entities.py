"""Immutable provider-neutral Phase 1 domain entities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .enums import (
    AuditOutcome,
    BrokerEnvironment,
    CashFlowClassification,
    DiscrepancySeverity,
    DiscrepancyType,
    IngestionMode,
    OrderSide,
    PrincipalStatus,
    Provider,
    QualityState,
    ReconciliationStatus,
    RecordStatus,
    ResolutionState,
    RunStatus,
    TransactionStatus,
    TransactionType,
    ValueOrigin,
)
from .errors import fail_validation
from .identifiers import (
    AuditEventId,
    BrokerAccountId,
    BrokerConnectionId,
    CalculationRunId,
    CashFlowId,
    CashObservationId,
    DiscrepancyId,
    DividendId,
    IngestionRunId,
    InstrumentId,
    LedgerEntryId,
    ListingId,
    OrderObservationId,
    OwnerId,
    PositionObservationId,
    PrincipalId,
    ReconciliationRunId,
    SnapshotId,
    SourceRecordId,
    TransactionId,
    require_uuid,
)
from .metadata import CalculationMetadata, Coverage, DataQuality, DomainWarning, ProvenanceReference
from .values import (
    CurrencyCode,
    Instant,
    Money,
    Price,
    Quantity,
    exact_decimal,
    require_bounded_text,
)


def _optional_text(value: str | None, *, field_name: str, maximum: int) -> None:
    if value is not None:
        require_bounded_text(value, field=field_name, maximum=maximum)


@dataclass(frozen=True, slots=True)
class Owner:
    id: OwnerId
    created_at: Instant
    display_name: str | None = None

    def __post_init__(self) -> None:
        require_uuid(self.id, field="owner.id")
        _optional_text(self.display_name, field_name="display_name", maximum=200)


@dataclass(frozen=True, slots=True)
class Principal:
    id: PrincipalId
    owner_id: OwnerId
    issuer: str
    subject: str
    status: PrincipalStatus
    created_at: Instant

    def __post_init__(self) -> None:
        require_uuid(self.id, field="principal.id")
        require_uuid(self.owner_id, field="principal.owner_id")
        require_bounded_text(self.issuer, field="issuer", maximum=255)
        require_bounded_text(self.subject, field="subject", maximum=255)


@dataclass(frozen=True, slots=True)
class BrokerConnection:
    id: BrokerConnectionId
    owner_id: OwnerId
    provider: Provider
    environment: BrokerEnvironment
    credential_reference: str = field(repr=False, metadata={"serialize": False})
    status: RecordStatus
    created_at: Instant
    updated_at: Instant

    def __post_init__(self) -> None:
        require_uuid(self.id, field="connection.id")
        require_uuid(self.owner_id, field="connection.owner_id")
        require_bounded_text(self.credential_reference, field="credential_reference", maximum=500)
        if self.updated_at < self.created_at:
            fail_validation("updated_at precedes created_at", field="updated_at")


@dataclass(frozen=True, slots=True)
class BrokerAccount:
    id: BrokerAccountId
    connection_id: BrokerConnectionId
    provider_account_id: str
    account_type: str
    base_currency: CurrencyCode
    display_name: str
    status: RecordStatus
    first_seen_at: Instant
    last_seen_at: Instant

    def __post_init__(self) -> None:
        require_uuid(self.id, field="account.id")
        require_uuid(self.connection_id, field="account.connection_id")
        require_bounded_text(self.provider_account_id, field="provider_account_id", maximum=255)
        require_bounded_text(self.account_type, field="account_type", maximum=80)
        require_bounded_text(self.display_name, field="display_name", maximum=200)
        if self.last_seen_at < self.first_seen_at:
            fail_validation("last_seen_at precedes first_seen_at", field="last_seen_at")


@dataclass(frozen=True, slots=True)
class Instrument:
    id: InstrumentId
    canonical_name: str
    instrument_type: str
    isin: str | None = None

    def __post_init__(self) -> None:
        require_uuid(self.id, field="instrument.id")
        require_bounded_text(self.canonical_name, field="canonical_name", maximum=300)
        require_bounded_text(self.instrument_type, field="instrument_type", maximum=80)
        _optional_text(self.isin, field_name="isin", maximum=12)


@dataclass(frozen=True, slots=True)
class Listing:
    id: ListingId
    instrument_id: InstrumentId
    provider: Provider
    environment: BrokerEnvironment
    provider_instrument_id: str
    ticker: str
    trading_currency: CurrencyCode
    status: RecordStatus
    valid_from: Instant
    exchange_mic: str | None = None
    exchange_id: str | None = None
    valid_to: Instant | None = None

    def __post_init__(self) -> None:
        require_uuid(self.id, field="listing.id")
        require_uuid(self.instrument_id, field="listing.instrument_id")
        require_bounded_text(
            self.provider_instrument_id,
            field="provider_instrument_id",
            maximum=255,
        )
        require_bounded_text(self.ticker, field="ticker", maximum=80)
        _optional_text(self.exchange_mic, field_name="exchange_mic", maximum=16)
        _optional_text(self.exchange_id, field_name="exchange_id", maximum=120)
        if self.valid_to is not None and self.valid_to < self.valid_from:
            fail_validation("valid_to precedes valid_from", field="valid_to")


@dataclass(frozen=True, slots=True)
class IngestionRun:
    id: IngestionRunId
    broker_account_id: BrokerAccountId
    capability: str
    mode: IngestionMode
    status: RunStatus
    started_at: Instant
    correlation_id: str
    request_count: int = 0
    records_received: int = 0
    records_normalized: int = 0
    records_rejected: int = 0
    completed_at: Instant | None = None
    checkpoint_before: Mapping[str, str] | None = None
    checkpoint_after: Mapping[str, str] | None = None
    warnings: tuple[DomainWarning, ...] = ()
    error_code: str | None = None

    def __post_init__(self) -> None:
        require_uuid(self.id, field="ingestion_run.id")
        require_uuid(self.broker_account_id, field="broker_account_id")
        require_bounded_text(self.capability, field="capability", maximum=100)
        require_bounded_text(self.correlation_id, field="correlation_id", maximum=120)
        count_fields = (
            "request_count",
            "records_received",
            "records_normalized",
            "records_rejected",
        )
        for field_name in count_fields:
            if getattr(self, field_name) < 0:
                fail_validation(f"{field_name} must not be negative", field=field_name)
        if self.completed_at is not None and self.completed_at < self.started_at:
            fail_validation("completed_at precedes started_at", field="completed_at")
        _optional_text(self.error_code, field_name="error_code", maximum=100)


@dataclass(frozen=True, slots=True)
class SourceRecord:
    id: SourceRecordId
    ingestion_run_id: IngestionRunId
    broker_account_id: BrokerAccountId
    provider: Provider
    capability: str
    provider_record_type: str
    payload_fingerprint: str
    observed_at: Instant
    schema_version: str
    provider_record_id: str | None = None
    source_updated_at: Instant | None = None
    sanitized_payload: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        require_uuid(self.id, field="source_record.id")
        require_uuid(self.ingestion_run_id, field="ingestion_run_id")
        require_uuid(self.broker_account_id, field="broker_account_id")
        require_bounded_text(self.capability, field="capability", maximum=100)
        require_bounded_text(self.provider_record_type, field="provider_record_type", maximum=100)
        require_bounded_text(self.payload_fingerprint, field="payload_fingerprint", maximum=128)
        require_bounded_text(self.schema_version, field="schema_version", maximum=40)
        _optional_text(self.provider_record_id, field_name="provider_record_id", maximum=255)


@dataclass(frozen=True, slots=True)
class IngestionCheckpoint:
    broker_account_id: BrokerAccountId
    capability: str
    version: int
    state: Mapping[str, str]
    updated_at: Instant
    coverage: Coverage
    advanced_by_run_id: IngestionRunId | None = None

    def __post_init__(self) -> None:
        require_uuid(self.broker_account_id, field="broker_account_id")
        require_bounded_text(self.capability, field="capability", maximum=100)
        if self.version < 1:
            fail_validation("checkpoint version must be positive", field="version")
        if self.advanced_by_run_id is not None:
            require_uuid(self.advanced_by_run_id, field="advanced_by_run_id")


@dataclass(frozen=True, slots=True)
class IngestionLease:
    broker_account_id: BrokerAccountId
    lease_type: str
    lease_owner: str
    acquired_at: Instant
    heartbeat_at: Instant
    expires_at: Instant
    run_id: IngestionRunId | None = None

    def __post_init__(self) -> None:
        require_uuid(self.broker_account_id, field="broker_account_id")
        require_bounded_text(self.lease_type, field="lease_type", maximum=100)
        require_bounded_text(self.lease_owner, field="lease_owner", maximum=200)
        if self.expires_at <= self.acquired_at:
            fail_validation("lease expiry must follow acquisition", field="expires_at")
        if not self.acquired_at <= self.heartbeat_at <= self.expires_at:
            fail_validation("lease heartbeat must be inside lease window", field="heartbeat_at")
        if self.run_id is not None:
            require_uuid(self.run_id, field="run_id")


@dataclass(frozen=True, slots=True)
class Transaction:
    id: TransactionId
    broker_account_id: BrokerAccountId
    provider_transaction_id: str
    transaction_type: TransactionType
    status: TransactionStatus
    net_cash_amount: Money
    occurred_at: Instant
    provenance: ProvenanceReference
    instrument_listing_id: ListingId | None = None
    quantity: Quantity | None = None
    unit_price: Price | None = None
    gross_amount: Money | None = None
    fees: Money | None = None
    taxes: Money | None = None
    settlement_date: date | None = None

    def __post_init__(self) -> None:
        require_uuid(self.id, field="transaction.id")
        require_uuid(self.broker_account_id, field="broker_account_id")
        require_bounded_text(
            self.provider_transaction_id,
            field="provider_transaction_id",
            maximum=255,
        )
        if self.instrument_listing_id is not None:
            require_uuid(self.instrument_listing_id, field="instrument_listing_id")
        for name in ("gross_amount", "fees", "taxes"):
            money = getattr(self, name)
            if money is not None and money.currency != self.net_cash_amount.currency:
                fail_validation(f"{name} currency must match net cash currency", field=name)


@dataclass(frozen=True, slots=True)
class CashFlow:
    id: CashFlowId
    broker_account_id: BrokerAccountId
    source_transaction_id: TransactionId | None
    classification: CashFlowClassification
    flow_type: TransactionType
    amount: Money
    occurred_at: Instant
    quality: QualityState
    provenance: ProvenanceReference

    def __post_init__(self) -> None:
        require_uuid(self.id, field="cash_flow.id")
        require_uuid(self.broker_account_id, field="broker_account_id")
        if self.source_transaction_id is not None:
            require_uuid(self.source_transaction_id, field="source_transaction_id")
        if (
            self.flow_type in (TransactionType.DEPOSIT, TransactionType.WITHDRAWAL)
            and self.classification is not CashFlowClassification.EXTERNAL
        ):
            fail_validation(
                "deposits and withdrawals must be external flows",
                field="classification",
            )
        if (
            self.flow_type in (TransactionType.BUY, TransactionType.SELL, TransactionType.DIVIDEND)
            and self.classification is CashFlowClassification.EXTERNAL
        ):
            fail_validation(
                "buys, sells, and dividends are not external contributions",
                field="classification",
            )


@dataclass(frozen=True, slots=True)
class CashBalanceObservation:
    id: CashObservationId
    broker_account_id: BrokerAccountId
    balance: Money
    observed_at: Instant
    provenance: ProvenanceReference

    def __post_init__(self) -> None:
        require_uuid(self.id, field="cash_observation.id")
        require_uuid(self.broker_account_id, field="broker_account_id")


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    id: LedgerEntryId
    broker_account_id: BrokerAccountId
    entry_type: TransactionType
    classification: CashFlowClassification
    amount: Money
    economic_at: Instant
    quality: QualityState
    idempotency_key: str
    source_transaction_id: TransactionId | None = None
    source_dividend_id: DividendId | None = None

    def __post_init__(self) -> None:
        require_uuid(self.id, field="ledger_entry.id")
        require_uuid(self.broker_account_id, field="broker_account_id")
        require_bounded_text(self.idempotency_key, field="idempotency_key", maximum=180)
        if self.source_transaction_id is not None:
            require_uuid(self.source_transaction_id, field="source_transaction_id")
        if self.source_dividend_id is not None:
            require_uuid(self.source_dividend_id, field="source_dividend_id")


@dataclass(frozen=True, slots=True)
class Dividend:
    id: DividendId
    broker_account_id: BrokerAccountId
    provider_dividend_id: str
    net_amount: Money
    paid_on: date
    provenance: ProvenanceReference
    instrument_listing_id: ListingId | None = None
    gross_amount: Money | None = None
    withholding_tax: Money | None = None
    quantity: Quantity | None = None

    def __post_init__(self) -> None:
        require_uuid(self.id, field="dividend.id")
        require_uuid(self.broker_account_id, field="broker_account_id")
        require_bounded_text(self.provider_dividend_id, field="provider_dividend_id", maximum=255)
        for name in ("gross_amount", "withholding_tax"):
            money = getattr(self, name)
            if money is not None and money.currency != self.net_amount.currency:
                fail_validation(f"{name} currency must match net amount currency", field=name)


@dataclass(frozen=True, slots=True)
class OrderObservation:
    id: OrderObservationId
    broker_account_id: BrokerAccountId
    provider_order_id: str
    instrument_listing_id: ListingId
    side: OrderSide
    order_type: str
    status: str
    observed_at: Instant
    provenance: ProvenanceReference
    submitted_at: Instant | None = None
    updated_at: Instant | None = None
    completed_at: Instant | None = None
    requested_quantity: Quantity | None = None
    requested_value: Money | None = None
    filled_quantity: Quantity | None = None
    filled_value: Money | None = None

    def __post_init__(self) -> None:
        require_uuid(self.id, field="order.id")
        require_uuid(self.broker_account_id, field="broker_account_id")
        require_uuid(self.instrument_listing_id, field="instrument_listing_id")
        require_bounded_text(self.provider_order_id, field="provider_order_id", maximum=255)
        require_bounded_text(self.order_type, field="order_type", maximum=80)
        require_bounded_text(self.status, field="order.status", maximum=80)


@dataclass(frozen=True, slots=True)
class PositionObservation:
    id: PositionObservationId
    broker_account_id: BrokerAccountId
    listing_id: ListingId
    quantity: Quantity
    observed_at: Instant
    provenance: ProvenanceReference
    current_price: Price | None = None
    provider_average_price: Price | None = None
    provider_market_value: Money | None = None
    provider_unrealized_pnl: Money | None = None

    def __post_init__(self) -> None:
        require_uuid(self.id, field="position_observation.id")
        require_uuid(self.broker_account_id, field="broker_account_id")
        require_uuid(self.listing_id, field="listing_id")


@dataclass(frozen=True, slots=True)
class CanonicalPosition:
    broker_account_id: BrokerAccountId
    listing_id: ListingId
    quantity: Quantity
    valuation_currency: CurrencyCode
    valuation_at: Instant
    quality: DataQuality
    provenance: ProvenanceReference
    current_price: Price | None = None
    provider_market_value: Money | None = None
    derived_market_value: Money | None = None
    provider_average_price: Price | None = None
    derived_acquisition_cost: Money | None = None
    provider_unrealized_pnl: Money | None = None
    derived_unrealized_pnl: Money | None = None
    acquisition_method: str | None = None
    acquisition_coverage: Coverage | None = None

    def __post_init__(self) -> None:
        require_uuid(self.broker_account_id, field="broker_account_id")
        require_uuid(self.listing_id, field="listing_id")
        for name in (
            "provider_market_value",
            "derived_market_value",
            "derived_acquisition_cost",
            "provider_unrealized_pnl",
            "derived_unrealized_pnl",
        ):
            money = getattr(self, name)
            if money is not None and money.currency != self.valuation_currency:
                fail_validation(f"{name} must use valuation currency", field=name)
        _optional_text(self.acquisition_method, field_name="acquisition_method", maximum=100)


@dataclass(frozen=True, slots=True)
class SnapshotPosition:
    listing_id: ListingId
    quantity: Quantity
    market_value: Money | None
    quality: QualityState
    origin: ValueOrigin
    current_price: Price | None = None
    cost_basis: Money | None = None
    unrealized_pnl: Money | None = None

    def __post_init__(self) -> None:
        require_uuid(self.listing_id, field="listing_id")
        values = (self.market_value, self.cost_basis, self.unrealized_pnl)
        currencies = {value.currency for value in values if value is not None}
        if len(currencies) > 1:
            fail_validation("snapshot position money currencies differ", field="market_value")


@dataclass(frozen=True, slots=True)
class SnapshotCash:
    amount: Money
    quality: QualityState
    origin: ValueOrigin


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    id: SnapshotId
    broker_account_id: BrokerAccountId
    valuation_at: Instant
    source_cutoff_at: Instant
    reporting_currency: CurrencyCode
    cash_total: Money | None
    invested_total: Money | None
    portfolio_total: Money | None
    net_contributions: Money | None
    positions: tuple[SnapshotPosition, ...]
    cash_components: tuple[SnapshotCash, ...]
    calculation: CalculationMetadata
    quality: DataQuality
    warnings: tuple[DomainWarning, ...] = ()

    def __post_init__(self) -> None:
        require_uuid(self.id, field="snapshot.id")
        require_uuid(self.broker_account_id, field="broker_account_id")
        if self.source_cutoff_at > self.valuation_at:
            fail_validation("source cutoff cannot follow valuation", field="source_cutoff_at")
        for name in ("cash_total", "invested_total", "portfolio_total", "net_contributions"):
            money = getattr(self, name)
            if money is not None and money.currency != self.reporting_currency:
                fail_validation(f"{name} must use reporting currency", field=name)


@dataclass(frozen=True, slots=True)
class ReconciliationRun:
    id: ReconciliationRunId
    broker_account_id: BrokerAccountId
    as_of: Instant
    algorithm_version: str
    tolerance_version: str
    status: ReconciliationStatus
    coverage: Coverage
    discrepancy_count: int
    warnings: tuple[DomainWarning, ...] = ()

    def __post_init__(self) -> None:
        require_uuid(self.id, field="reconciliation.id")
        require_uuid(self.broker_account_id, field="broker_account_id")
        require_bounded_text(self.algorithm_version, field="algorithm_version", maximum=40)
        require_bounded_text(self.tolerance_version, field="tolerance_version", maximum=40)
        if self.discrepancy_count < 0:
            fail_validation("discrepancy_count must not be negative", field="discrepancy_count")


@dataclass(frozen=True, slots=True)
class ReconciliationDiscrepancy:
    id: DiscrepancyId
    reconciliation_run_id: ReconciliationRunId
    broker_account_id: BrokerAccountId
    discrepancy_type: DiscrepancyType
    severity: DiscrepancySeverity
    resolution_state: ResolutionState
    first_seen_at: Instant
    last_seen_at: Instant
    expected_value: Decimal | None
    observed_value: Decimal | None
    residual: Decimal | None
    tolerance: Decimal | None
    downstream_effect: str
    listing_id: ListingId | None = None
    currency: CurrencyCode | None = None
    likely_cause: str | None = None
    resolution_reason: str | None = None

    def __post_init__(self) -> None:
        require_uuid(self.id, field="discrepancy.id")
        require_uuid(self.reconciliation_run_id, field="reconciliation_run_id")
        require_uuid(self.broker_account_id, field="broker_account_id")
        if self.listing_id is not None:
            require_uuid(self.listing_id, field="listing_id")
        if self.last_seen_at < self.first_seen_at:
            fail_validation("last_seen_at precedes first_seen_at", field="last_seen_at")
        for name in ("expected_value", "observed_value", "residual", "tolerance"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, exact_decimal(value, field=name))
        if self.tolerance is not None and self.tolerance < 0:
            fail_validation("tolerance must not be negative", field="tolerance")
        require_bounded_text(self.downstream_effect, field="downstream_effect", maximum=500)
        _optional_text(self.likely_cause, field_name="likely_cause", maximum=200)
        _optional_text(self.resolution_reason, field_name="resolution_reason", maximum=500)


@dataclass(frozen=True, slots=True)
class CalculationRun:
    id: CalculationRunId
    broker_account_id: BrokerAccountId
    metadata: CalculationMetadata
    output_fingerprint: str

    def __post_init__(self) -> None:
        require_uuid(self.id, field="calculation_run.id")
        require_uuid(self.broker_account_id, field="broker_account_id")
        require_bounded_text(self.output_fingerprint, field="output_fingerprint", maximum=128)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: AuditEventId
    owner_id: OwnerId
    action: str
    resource_type: str
    occurred_at: Instant
    outcome: AuditOutcome
    principal_id: PrincipalId | None = None
    broker_account_id: BrokerAccountId | None = None
    resource_id: str | None = None
    correlation_id: str | None = None
    safe_metadata: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        require_uuid(self.id, field="audit_event.id")
        require_uuid(self.owner_id, field="owner_id")
        if self.principal_id is not None:
            require_uuid(self.principal_id, field="principal_id")
        if self.broker_account_id is not None:
            require_uuid(self.broker_account_id, field="broker_account_id")
        require_bounded_text(self.action, field="action", maximum=120)
        require_bounded_text(self.resource_type, field="resource_type", maximum=120)
        _optional_text(self.resource_id, field_name="resource_id", maximum=255)
        _optional_text(self.correlation_id, field_name="correlation_id", maximum=120)
