"""Frozen Phase 1 domain enumerations.

Enum values are lowercase because they are persisted and serialized API contracts.
"""

from enum import StrEnum


class Provider(StrEnum):
    TRADING212 = "trading212"
    SYNTHETIC = "synthetic"


class BrokerEnvironment(StrEnum):
    DEMO = "demo"
    LIVE = "live"
    SYNTHETIC = "synthetic"


class RecordStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DISABLED = "disabled"
    ERROR = "error"


class PrincipalStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class QualityState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    PARTIAL = "partial"
    ESTIMATED = "estimated"
    UNRECONCILED = "unreconciled"
    FAILED = "failed"


class ValueOrigin(StrEnum):
    OBSERVED_PROVIDER = "observed_provider"
    NORMALIZED_PROVIDER = "normalized_provider"
    DERIVED_DETERMINISTIC = "derived_deterministic"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


class TransactionType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    DIVIDEND = "dividend"
    FEE = "fee"
    TAX_WITHHOLDING = "tax_withholding"
    INTEREST = "interest"
    TRANSFER = "transfer"
    CORPORATE_ACTION = "corporate_action"
    ADJUSTMENT = "adjustment"
    UNKNOWN_PROVIDER_ACTIVITY = "unknown_provider_activity"


class TransactionStatus(StrEnum):
    PENDING = "pending"
    POSTED = "posted"
    REVERSED = "reversed"
    UNKNOWN = "unknown"


class CashFlowClassification(StrEnum):
    EXTERNAL = "external"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class IngestionMode(StrEnum):
    FULL = "full"
    INCREMENTAL = "incremental"
    REFRESH = "refresh"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReconciliationStatus(StrEnum):
    RECONCILED = "reconciled"
    UNRECONCILED = "unreconciled"
    PARTIAL = "partial"
    FAILED = "failed"


class DiscrepancyType(StrEnum):
    QUANTITY_MISMATCH = "quantity_mismatch"
    CASH_MISMATCH = "cash_mismatch"
    MISSING_SOURCE_ACTIVITY = "missing_source_activity"
    DUPLICATE_SOURCE_ACTIVITY = "duplicate_source_activity"
    UNMAPPED_INSTRUMENT = "unmapped_instrument"
    UNSUPPORTED_CORPORATE_ACTION = "unsupported_corporate_action"
    CURRENCY_FX_GAP = "currency_fx_gap"
    TIMING_SETTLEMENT_DIFFERENCE = "timing_settlement_difference"
    PROVIDER_HISTORY_COVERAGE_GAP = "provider_history_coverage_gap"
    SCHEMA_MAPPING_CHANGE = "schema_mapping_change"


class DiscrepancySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ResolutionState(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    RESOLVED = "resolved"


class AuditOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    DENIED = "denied"
    FAILED = "failed"
