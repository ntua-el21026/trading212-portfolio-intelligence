"""Validated immutable economic evidence for historical portfolio intelligence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from .enums import QualityState
from .errors import fail_validation
from .planning import CoveragePolicy
from .source_details import CorporateActionSnapshot
from .sources import (
    BenchmarkContent,
    BenchmarkSnapshot,
    FxSnapshot,
    PriceBasis,
    PriceSnapshot,
    SourceCalendar,
    SourceSelectionPolicy,
    SourceSnapshot,
    source_id,
    source_integer,
    source_key,
    source_tuple,
)
from .values import CurrencyCode, Money, exact_decimal, require_bounded_text, require_utc

HISTORICAL_SCHEMA_VERSION = "1.0.0"
HISTORICAL_METHOD_VERSION = "1.0.0"
MAX_HISTORICAL_DOCUMENT_BYTES = 33_554_432
MAX_HISTORICAL_EVENTS = 10_000
MAX_HISTORICAL_SOURCES = 8_192
MAX_HISTORICAL_CELLS = 100_000
MAX_HISTORICAL_USES = 400_000
MAX_HISTORICAL_CALENDARS = 256
MAX_HISTORICAL_CALENDAR_SESSIONS = 100_000
MAX_HISTORICAL_POINTS = 3_661


class KnowledgePolicy(StrEnum):
    AS_OF_CUTOFF = "as_of_cutoff"
    POINT_IN_TIME = "point_in_time"


class ReturnMethod(StrEnum):
    TWR = "twr"
    MWR = "mwr"
    MODIFIED_DIETZ = "modified_dietz"


class AttributionMethod(StrEnum):
    TWR = "twr"
    MODIFIED_DIETZ = "modified_dietz"


class HistoricalFrequency(StrEnum):
    DAILY = "daily"
    MONTHLY = "monthly"


class RollingWindow(StrEnum):
    NONE = "none"
    DAYS_30 = "calendar_days_30"
    DAYS_90 = "calendar_days_90"
    DAYS_365 = "calendar_days_365"


class CalendarPeriod(StrEnum):
    NONE = "none"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class HistoricalGrouping(StrEnum):
    HOLDING = "holding"
    GROUP = "group"
    SECTOR = "sector"
    ASSET_CLASS = "asset_class"
    CURRENCY = "currency"


class HistoricalCashFlowKind(StrEnum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    INTEREST = "interest"
    FEE = "fee"
    TAX = "tax"
    INTERNAL_TRANSFER = "internal_transfer"
    FX_CONVERSION = "fx_conversion"
    CORPORATE_ACTION = "corporate_action"
    UNKNOWN = "unknown"


class HistoricalReason(StrEnum):
    OPENING_MISSING = "unavailable_opening_evidence"
    OPENING_UNRECONCILED = "unavailable_opening_reconciliation"
    EVENT_COVERAGE = "unavailable_event_coverage"
    UNKNOWN_EVENT = "unavailable_unknown_economic_effect"
    AMBIGUOUS_REVISION = "unavailable_ambiguous_economic_revision"
    KNOWLEDGE_TRANSITION = "unavailable_unreconciled_knowledge_transition"
    VALUATION_MISSING = "unavailable_valuation"
    PRICE_MISSING = "unavailable_price"
    FX_MISSING = "unavailable_fx"
    ACTION_COVERAGE = "unavailable_corporate_action_coverage"
    ACTION_UNSUPPORTED = "unavailable_corporate_action_accounting"
    MAPPING_MISSING = "unavailable_mapping"
    CLASSIFICATION_MISSING = "unavailable_classification"
    COST_COVERAGE = "unavailable_cost_basis"
    GROSS_UNKNOWN = "unavailable_gross_income"
    WITHHOLDING_UNKNOWN = "unavailable_withholding"
    FEE_UNKNOWN = "unavailable_fee"
    NONPOSITIVE_DENOMINATOR = "unavailable_positive_denominator"
    TWR_FLOW_ANCHOR = "unavailable_exact_flow_valuation"
    NUMERIC_FAILURE = "unavailable_numeric_result"
    XIRR_NONCONVENTIONAL = "unavailable_conventional_xirr_root"
    XIRR_NO_ROOT = "unavailable_xirr_root"
    XIRR_NOT_BRACKETED = "unavailable_xirr_bracket"
    XIRR_NOT_CONVERGED = "unavailable_xirr_convergence"
    SHORT_PERIOD = "unavailable_annualization_period"
    ROLLING_BOUNDARY = "unavailable_rolling_boundary"
    INCOMPLETE_CALENDAR = "unavailable_complete_calendar_period"
    BENCHMARK_MISSING = "unavailable_benchmark_inputs"
    BENCHMARK_GAP = "unavailable_benchmark_alignment"
    BENCHMARK_PRICE_ONLY = "benchmark_price_only_comparison"
    CURRENCY_MISMATCH = "unavailable_reporting_currency_alignment"
    TRACKING_PAIRS = "unavailable_tracking_error_observations"
    NO_POSITIVE_INCOME = "unavailable_positive_income"
    PREVIOUS_PERIOD = "unavailable_comparable_calendar_period"
    CASH_COUNTERFACTUAL = "unavailable_cash_counterfactual_inputs"
    UNSUPPORTED_BASIS = "unavailable_price_quantity_basis"
    PARTIAL_COVERAGE = "partial_covered_subtotal"
    RESTATED = "historical_reconstruction_restated"
    TARGET_COMPARISON = "explicit_target_comparison_grouping"
    ROUNDING = "output_quantization_residual"
    LICENSE_DENIED = "unavailable_source_license"
    SOURCE_EXPIRED = "unavailable_source_retention"
    SOURCE_STALE = "historical_source_stale"
    RESOURCE_LIMIT = "unavailable_resource_capacity"
    UNKNOWN_INCOME_ASSIGNMENT = "unavailable_income_assignment"
    BRINSON_INPUTS = "unavailable_benchmark_constituent_attribution"


class MetricAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class HistoricalAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class HistoricalOrigin(StrEnum):
    PROVIDER = "provider"
    DERIVED = "derived"


class HistoricalCoverageKey(StrEnum):
    OPENING = "opening"
    QUANTITY = "quantity"
    CASH = "cash"
    COST = "cost"
    EVENTS = "events"
    VALUATIONS = "valuation_cells"
    ACTIONS = "actions"
    FX = "fx_cells"
    BENCHMARK = "benchmark_sessions"
    PRIOR_INCOME = "prior_income"


def historical_digest(value: str, field: str = "digest") -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        fail_validation("A canonical SHA-256 digest is required.", field=field)
    return value


def _enum(value: object, kind: type[StrEnum], field: str) -> None:
    if not isinstance(value, kind):
        fail_validation("A closed typed value is required.", field=field)


def _optional_id(value: str | None, field: str) -> None:
    if value is not None:
        source_id(value, field)


def _ids(value: tuple[str, ...], field: str, maximum: int = MAX_HISTORICAL_SOURCES) -> None:
    source_tuple(value, str, field, maximum)
    if len(set(value)) != len(value):
        fail_validation("Repeated canonical references are not permitted.", field=field)
    for item in value:
        source_id(item, field)


def _decimal(value: Decimal, field: str, *, nonnegative: bool = False) -> None:
    if not isinstance(value, Decimal):
        fail_validation("A typed exact Decimal is required.", field=field)
    exact_decimal(value, field=field)
    if nonnegative and value < 0:
        fail_validation("A nonnegative value is required.", field=field)


def _typed(value: object, kind: type[object] | tuple[type[object], ...], field: str) -> None:
    if not isinstance(value, kind):
        fail_validation("A typed immutable value is required.", field=field)


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalIssue:
    reason_code: HistoricalReason
    coverage_key: HistoricalCoverageKey | None = None
    reference_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _enum(self.reason_code, HistoricalReason, "reason_code")
        if self.coverage_key is not None:
            _enum(self.coverage_key, HistoricalCoverageKey, "coverage_key")
        _ids(self.reference_ids, "reference_ids", 64)


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalMoneyMetric:
    value: Money | None
    availability: MetricAvailability
    reason_code: HistoricalReason | None
    quality: QualityState
    coverage_key: HistoricalCoverageKey
    origin: HistoricalOrigin = HistoricalOrigin.DERIVED

    def __post_init__(self) -> None:
        _metric(self)
        if self.value is not None:
            _typed(self.value, Money, "value")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalRatioMetric:
    value: Decimal | None
    availability: MetricAvailability
    reason_code: HistoricalReason | None
    quality: QualityState
    coverage_key: HistoricalCoverageKey
    origin: HistoricalOrigin = HistoricalOrigin.DERIVED

    def __post_init__(self) -> None:
        _metric(self)
        if self.value is not None:
            _decimal(self.value, "value")


def _metric(value: HistoricalMoneyMetric | HistoricalRatioMetric) -> None:
    _enum(value.availability, MetricAvailability, "availability")
    _enum(value.quality, QualityState, "quality")
    _enum(value.coverage_key, HistoricalCoverageKey, "coverage_key")
    _enum(value.origin, HistoricalOrigin, "origin")
    if value.reason_code is not None:
        _enum(value.reason_code, HistoricalReason, "reason_code")
    if (value.value is None) != (value.availability is MetricAvailability.UNAVAILABLE):
        fail_validation("Metric value and availability disagree.", field="value")
    if value.availability is not MetricAvailability.AVAILABLE:
        if value.reason_code is None:
            fail_validation("Incomplete metrics require a reason.", field="reason_code")
        if value.quality is QualityState.FRESH:
            fail_validation(
                "Incomplete metrics cannot claim fresh complete quality.", field="quality"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalCoverageMeasure:
    key: HistoricalCoverageKey
    expected_count: int
    available_count: int
    complete: bool
    reasons: tuple[HistoricalReason, ...] = ()

    def __post_init__(self) -> None:
        _enum(self.key, HistoricalCoverageKey, "key")
        source_integer(self.expected_count, "expected_count", 0, MAX_HISTORICAL_USES)
        source_integer(self.available_count, "available_count", 0, self.expected_count)
        source_tuple(self.reasons, HistoricalReason, "reasons", 64)
        if type(self.complete) is not bool or (
            self.complete and self.available_count != self.expected_count
        ):
            fail_validation("Coverage completeness differs from its counts.", field="complete")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalCoverage:
    measures: tuple[HistoricalCoverageMeasure, ...]

    def __post_init__(self) -> None:
        source_tuple(self.measures, HistoricalCoverageMeasure, "measures", 10)
        if len({x.key for x in self.measures}) != len(self.measures):
            fail_validation("Coverage keys must be unique.", field="measures")

    def complete(self, key: HistoricalCoverageKey) -> bool:
        return any(x.key is key and x.complete for x in self.measures)


@dataclass(frozen=True, slots=True, kw_only=True)
class CalendarRef:
    id: str
    version: str

    def __post_init__(self) -> None:
        source_key(self.id, "calendar_id")
        source_key(self.version, "calendar_version")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalWindow:
    start_date: date
    end_date: date
    source_cutoff_at: datetime
    reporting_currency: CurrencyCode
    coverage_policy: CoveragePolicy = CoveragePolicy.REQUIRE_COMPLETE
    knowledge_policy: KnowledgePolicy = KnowledgePolicy.AS_OF_CUTOFF

    def __post_init__(self) -> None:
        for name in ("start_date", "end_date"):
            value = getattr(self, name)
            if not isinstance(value, date) or isinstance(value, datetime):
                fail_validation("A date is required.", field=name)
        if not 0 <= (self.end_date - self.start_date).days <= 3660 or self.end_date == date.max:
            fail_validation("Historical period exceeds its supported bounds.", field="end_date")
        object.__setattr__(self, "source_cutoff_at", require_utc(self.source_cutoff_at))
        _typed(self.reporting_currency, CurrencyCode, "reporting_currency")
        _enum(self.coverage_policy, CoveragePolicy, "coverage_policy")
        _enum(self.knowledge_policy, KnowledgePolicy, "knowledge_policy")

    @property
    def start_at(self) -> datetime:
        return datetime.combine(self.start_date, time.min, tzinfo=UTC)

    @property
    def end_at(self) -> datetime:
        return datetime.combine(self.end_date + timedelta(days=1), time.min, tzinfo=UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalSupportWindow:
    reason: Literal[
        "rolling_30",
        "rolling_90",
        "rolling_365",
        "previous_calendar_income",
        "opening_bridge",
        "prior_session",
    ]
    start_at: datetime
    end_at: datetime

    def __post_init__(self) -> None:
        if self.reason not in {
            "rolling_30",
            "rolling_90",
            "rolling_365",
            "previous_calendar_income",
            "opening_bridge",
            "prior_session",
        }:
            fail_validation("Unsupported support-window reason.", field="reason")
        object.__setattr__(self, "start_at", require_utc(self.start_at))
        object.__setattr__(self, "end_at", require_utc(self.end_at))
        if not self.start_at < self.end_at or (self.end_at - self.start_at).days > 7322:
            fail_validation("Support-window boundaries are invalid.", field="end_at")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalAccountingPolicy:
    version: str = "1.0.0"
    boundary_convention: str = "utc_accounting_boundaries_v1"
    close_convention: str = "utc_boundary_previous_close_v1"
    annual_session_factor: int = 252
    cost_method: str = "weighted_average_acquisition"
    income_partition_policy: str = "session_closes_and_events_v1"
    event_order_policy: str = "group_equal_instants_v1"

    def __post_init__(self) -> None:
        expected = {
            "version": "1.0.0",
            "boundary_convention": "utc_accounting_boundaries_v1",
            "close_convention": "utc_boundary_previous_close_v1",
            "cost_method": "weighted_average_acquisition",
            "income_partition_policy": "session_closes_and_events_v1",
            "event_order_policy": "group_equal_instants_v1",
        }
        if any(getattr(self, key) != value for key, value in expected.items()):
            fail_validation("Unsupported historical accounting policy.", field="accounting_policy")
        source_integer(self.annual_session_factor, "annual_session_factor", 1, 366)


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalSelectionRequest:
    window: HistoricalWindow
    accounting_policy: HistoricalAccountingPolicy
    source_policy: SourceSelectionPolicy | None
    reporting_calendar_ref: CalendarRef | None
    support_windows: tuple[HistoricalSupportWindow, ...] = ()
    benchmark_version_id: str | None = None
    target_version_id: str | None = None
    grouping_policy: Literal["historical_assignment", "explicit_comparison"] | None = None

    def __post_init__(self) -> None:
        for name, kind in (
            ("window", HistoricalWindow),
            ("accounting_policy", HistoricalAccountingPolicy),
        ):
            _typed(getattr(self, name), kind, name)
        if self.source_policy is not None:
            _typed(self.source_policy, SourceSelectionPolicy, "source_policy")
        if self.reporting_calendar_ref is not None:
            _typed(self.reporting_calendar_ref, CalendarRef, "reporting_calendar_ref")
        if (self.source_policy is None) != (self.reporting_calendar_ref is None):
            fail_validation(
                "Missing historical policy and calendar must agree.", field="source_policy"
            )
        source_tuple(self.support_windows, HistoricalSupportWindow, "support_windows", 8)
        _optional_id(self.benchmark_version_id, "benchmark_version_id")
        _optional_id(self.target_version_id, "target_version_id")
        if self.grouping_policy not in (None, "historical_assignment", "explicit_comparison") or (
            self.target_version_id is None
        ) != (self.grouping_policy is None):
            fail_validation(
                "Target reference and grouping policy must agree.", field="grouping_policy"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalSourceReference:
    kind: Literal[
        "broker_source_record",
        "broker_source_occurrence",
        "portfolio_snapshot",
        "calculation_run",
        "reconciliation_run",
        "price_snapshot",
        "fx_snapshot",
        "corporate_action_snapshot",
        "provider_benchmark_snapshot",
        "instrument_mapping",
        "calendar_version",
        "provider_license_version",
        "benchmark_version",
        "target_version",
        "classification_evidence",
        "historical_evidence",
        "activity_revision_evidence",
        "ingestion_run",
    ]
    id: str
    effective_at: datetime
    first_observed_at: datetime
    semantic_digest: str | None = None
    version: str | None = None
    parent_ids: tuple[str, ...] = ()
    derived_projection_digest: str | None = None
    original_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {
            "broker_source_record",
            "broker_source_occurrence",
            "portfolio_snapshot",
            "calculation_run",
            "reconciliation_run",
            "price_snapshot",
            "fx_snapshot",
            "corporate_action_snapshot",
            "provider_benchmark_snapshot",
            "instrument_mapping",
            "calendar_version",
            "provider_license_version",
            "benchmark_version",
            "target_version",
            "classification_evidence",
            "historical_evidence",
            "activity_revision_evidence",
            "ingestion_run",
        }:
            fail_validation("Unsupported historical source kind.", field="kind")
        source_id(self.id)
        for name in ("effective_at", "first_observed_at"):
            object.__setattr__(self, name, require_utc(getattr(self, name)))
        for name in ("semantic_digest", "derived_projection_digest", "original_fingerprint"):
            value = getattr(self, name)
            if value is not None:
                historical_digest(value, name)
        if self.version is not None:
            source_key(self.version, "version")
        _ids(self.parent_ids, "parent_ids", 16)


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalInstrument:
    listing_id: str
    instrument_id: str
    native_currency: CurrencyCode
    source_series_ids: tuple[str, ...] = ()
    quantity_basis: PriceBasis = PriceBasis.RAW_CLOSE

    def __post_init__(self) -> None:
        source_id(self.listing_id, "listing_id")
        source_id(self.instrument_id, "instrument_id")
        _typed(self.native_currency, CurrencyCode, "native_currency")
        _enum(self.quantity_basis, PriceBasis, "quantity_basis")
        _ids(self.source_series_ids, "source_series_ids", 256)


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalMappingEvidence:
    id: str
    source_ref: str
    instrument_id: str
    listing_id: str | None
    native_currency: CurrencyCode
    asset_type: str
    valid_from: datetime
    valid_to: datetime | None
    first_observed_at: datetime
    state: Literal["resolved", "unresolved", "ambiguous"] = "resolved"

    def __post_init__(self) -> None:
        for name in ("id", "source_ref", "instrument_id"):
            source_id(getattr(self, name), name)
        _optional_id(self.listing_id, "listing_id")
        _typed(self.native_currency, CurrencyCode, "native_currency")
        source_key(self.asset_type, "asset_type")
        _validity(self)
        if self.state not in ("resolved", "unresolved", "ambiguous"):
            fail_validation("Unsupported mapping state.", field="state")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalClassificationEvidence:
    id: str
    instrument_id: str
    dimension: Literal["sector", "asset_class"]
    taxonomy: str
    taxonomy_version: str
    category: str
    valid_from: datetime
    valid_to: datetime | None
    first_observed_at: datetime
    source_refs: tuple[str, ...]
    license_version_id: str

    def __post_init__(self) -> None:
        for name in ("id", "instrument_id", "license_version_id"):
            source_id(getattr(self, name), name)
        if self.dimension not in ("sector", "asset_class"):
            fail_validation("Unsupported direct classification.", field="dimension")
        for name in ("taxonomy", "taxonomy_version", "category"):
            source_key(getattr(self, name), name)
        _ids(self.source_refs, "source_refs", 16)
        _validity(self)


def _validity(value: HistoricalMappingEvidence | HistoricalClassificationEvidence) -> None:
    for name in ("valid_from", "first_observed_at"):
        object.__setattr__(value, name, require_utc(getattr(value, name)))
    if value.valid_to is not None:
        object.__setattr__(value, "valid_to", require_utc(value.valid_to))
        if value.valid_to <= value.valid_from:
            fail_validation("Validity end must follow start.", field="valid_to")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalAnchorPosition:
    listing_id: str
    instrument_id: str
    quantity: Decimal
    market_value: HistoricalMoneyMetric
    acquisition_cost: HistoricalMoneyMetric

    def __post_init__(self) -> None:
        source_id(self.listing_id, "listing_id")
        source_id(self.instrument_id, "instrument_id")
        _decimal(self.quantity, "quantity", nonnegative=True)
        _typed(self.market_value, HistoricalMoneyMetric, "market_value")
        _typed(self.acquisition_cost, HistoricalMoneyMetric, "acquisition_cost")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalReconciliationLine:
    kind: Literal["quantity", "cash", "cost"]
    identity: str
    currency: CurrencyCode | None
    expected: Decimal | None
    observed: Decimal | None
    residual: Decimal | None
    tolerance: Decimal
    state: Literal["reconciled", "unreconciled", "unavailable"]

    def __post_init__(self) -> None:
        if self.kind not in ("quantity", "cash", "cost") or self.state not in (
            "reconciled",
            "unreconciled",
            "unavailable",
        ):
            fail_validation("Unsupported reconciliation discriminator.", field="kind")
        source_key(self.identity, "identity")
        if self.currency is not None:
            _typed(self.currency, CurrencyCode, "currency")
        if (self.kind == "quantity") != (self.currency is None):
            fail_validation("Reconciliation currency differs from measure kind.", field="currency")
        for name in ("expected", "observed", "residual"):
            value = getattr(self, name)
            if value is not None:
                _decimal(value, name)
        _decimal(self.tolerance, "tolerance", nonnegative=True)
        if self.state != "unavailable" and any(
            getattr(self, name) is None for name in ("expected", "observed", "residual")
        ):
            fail_validation("Known reconciliation requires all comparison values.", field="state")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalReconciliationProof:
    policy_version: str
    anchor_refs: tuple[str, ...]
    lines: tuple[HistoricalReconciliationLine, ...]
    outcome: Literal["reconciled", "unreconciled", "unavailable"]

    def __post_init__(self) -> None:
        source_key(self.policy_version, "policy_version")
        _ids(self.anchor_refs, "anchor_refs", 32)
        source_tuple(self.lines, HistoricalReconciliationLine, "lines", 1024)
        if self.outcome not in ("reconciled", "unreconciled", "unavailable"):
            fail_validation("Unsupported reconciliation outcome.", field="outcome")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalValuationAnchor:
    id: str
    at: datetime
    timing: Literal["before_events", "after_events"]
    positions: tuple[HistoricalAnchorPosition, ...]
    cash: tuple[Money, ...]
    origin: HistoricalOrigin
    source_refs: tuple[str, ...]
    coverage: HistoricalCoverage
    reconciliation: HistoricalReconciliationProof
    exact_economic_valuation: bool = True

    def __post_init__(self) -> None:
        source_id(self.id)
        object.__setattr__(self, "at", require_utc(self.at))
        if self.timing not in ("before_events", "after_events"):
            fail_validation("Anchor timing must be explicit.", field="timing")
        source_tuple(self.positions, HistoricalAnchorPosition, "positions", 256)
        source_tuple(self.cash, Money, "cash", 32)
        _enum(self.origin, HistoricalOrigin, "origin")
        _ids(self.source_refs, "source_refs", 64)
        _typed(self.coverage, HistoricalCoverage, "coverage")
        _typed(self.reconciliation, HistoricalReconciliationProof, "reconciliation")
        if type(self.exact_economic_valuation) is not bool:
            fail_validation(
                "Exact valuation convention must be explicit.", field="exact_economic_valuation"
            )
        if len({x.listing_id for x in self.positions}) != len(self.positions) or len(
            {x.currency for x in self.cash}
        ) != len(self.cash):
            fail_validation("Anchor identities must be unique.", field="positions")


@dataclass(frozen=True, slots=True, kw_only=True)
class ObservedHistoricalOpening:
    anchor: HistoricalValuationAnchor
    bridge_coverage: HistoricalCoverage
    kind: Literal["observed"] = "observed"

    def __post_init__(self) -> None:
        if self.kind != "observed":
            fail_validation("Opening discriminator differs.", field="kind")
        _typed(self.anchor, HistoricalValuationAnchor, "anchor")
        _typed(self.bridge_coverage, HistoricalCoverage, "bridge_coverage")


@dataclass(frozen=True, slots=True, kw_only=True)
class InceptionHistoricalOpening:
    inception_at: datetime
    source_refs: tuple[str, ...]
    bridge_coverage: HistoricalCoverage
    kind: Literal["account_inception"] = "account_inception"

    def __post_init__(self) -> None:
        if self.kind != "account_inception":
            fail_validation("Opening discriminator differs.", field="kind")
        object.__setattr__(self, "inception_at", require_utc(self.inception_at))
        _ids(self.source_refs, "source_refs", 32)
        if not self.source_refs:
            fail_validation("Account inception requires evidence.", field="source_refs")
        _typed(self.bridge_coverage, HistoricalCoverage, "bridge_coverage")


@dataclass(frozen=True, slots=True, kw_only=True)
class UnavailableHistoricalOpening:
    reasons: tuple[HistoricalReason, ...]
    partial_anchor_refs: tuple[str, ...] = ()
    kind: Literal["unavailable"] = "unavailable"

    def __post_init__(self) -> None:
        if self.kind != "unavailable" or not self.reasons:
            fail_validation("Unavailable opening requires reasons.", field="reasons")
        source_tuple(self.reasons, HistoricalReason, "reasons", 64)
        _ids(self.partial_anchor_refs, "partial_anchor_refs", 32)


HistoricalOpening = (
    ObservedHistoricalOpening | InceptionHistoricalOpening | UnavailableHistoricalOpening
)


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalEventIdentity:
    economic_key: str
    revision_id: str
    source_record_id: str
    source_occurrence_id: str | None
    economic_at: datetime
    first_observed_at: datetime
    revision_sequence: int | None = None
    supersedes_revision_id: str | None = None
    record_state: Literal["reported", "cancelled"] = "reported"
    quality: QualityState = QualityState.FRESH

    def __post_init__(self) -> None:
        source_key(self.economic_key, "economic_key")
        for name in ("revision_id", "source_record_id"):
            source_id(getattr(self, name), name)
        for name in ("source_occurrence_id", "supersedes_revision_id"):
            _optional_id(getattr(self, name), name)
        for name in ("economic_at", "first_observed_at"):
            object.__setattr__(self, name, require_utc(getattr(self, name)))
        if self.revision_sequence is not None:
            source_integer(self.revision_sequence, "revision_sequence", 0, 2_147_483_647)
        if self.record_state not in ("reported", "cancelled"):
            fail_validation("Unsupported economic record state.", field="record_state")
        _enum(self.quality, QualityState, "quality")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalExternalFlow:
    identity: HistoricalEventIdentity
    kind: Literal["deposit", "withdrawal", "transfer_in", "transfer_out"]
    signed_amount: Money
    scope_proof: Literal["account_boundary", "documented_external_transfer"]

    def __post_init__(self) -> None:
        _typed(self.identity, HistoricalEventIdentity, "identity")
        _typed(self.signed_amount, Money, "signed_amount")
        if self.kind not in (
            "deposit",
            "withdrawal",
            "transfer_in",
            "transfer_out",
        ) or self.scope_proof not in ("account_boundary", "documented_external_transfer"):
            fail_validation("Unsupported external flow classification.", field="kind")
        if (self.kind in ("deposit", "transfer_in") and self.signed_amount.amount < 0) or (
            self.kind in ("withdrawal", "transfer_out") and self.signed_amount.amount > 0
        ):
            fail_validation(
                "External flow sign differs from its classification.", field="signed_amount"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalExecution:
    identity: HistoricalEventIdentity
    order_key: str
    fill_key: str
    instrument_id: str
    listing_id: str
    mapping_id: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    native_price: Money
    gross_value: Money
    cash_impact: Money
    fees: HistoricalMoneyMetric
    taxes: HistoricalMoneyMetric
    explicit_fx: Decimal | None = None
    explicit_fx_source_ref: str | None = None
    kind: Literal["execution"] = "execution"

    def __post_init__(self) -> None:
        _typed(self.identity, HistoricalEventIdentity, "identity")
        if self.kind != "execution" or self.side not in ("buy", "sell"):
            fail_validation("Execution discriminator differs.", field="kind")
        for name in ("order_key", "fill_key"):
            source_key(getattr(self, name), name)
        for name in ("instrument_id", "listing_id", "mapping_id"):
            source_id(getattr(self, name), name)
        _decimal(self.quantity, "quantity", nonnegative=True)
        if self.quantity == 0:
            fail_validation("Executed quantity must be positive.", field="quantity")
        for name in ("native_price", "gross_value", "cash_impact"):
            _typed(getattr(self, name), Money, name)
        if self.native_price.amount <= 0 or self.gross_value.amount < 0:
            fail_validation("Execution price/gross value is invalid.", field="native_price")
        for name in ("fees", "taxes"):
            _typed(getattr(self, name), HistoricalMoneyMetric, name)
        if (self.explicit_fx is None) != (self.explicit_fx_source_ref is None):
            fail_validation("Explicit FX requires its sourced evidence.", field="explicit_fx")
        if self.explicit_fx is not None:
            _decimal(self.explicit_fx, "explicit_fx", nonnegative=True)
            if self.explicit_fx == 0:
                fail_validation("Explicit FX must be positive.", field="explicit_fx")
            _optional_id(self.explicit_fx_source_ref, "explicit_fx_source_ref")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalDividend:
    identity: HistoricalEventIdentity
    dividend_key: str
    instrument_id: str | None
    listing_id: str | None
    net: Money
    gross: HistoricalMoneyMetric
    withholding: HistoricalMoneyMetric
    payment_convention: Literal["exact_provider_instant", "payment_date_utc_start"]
    correction_of: str | None = None
    kind: Literal["dividend"] = "dividend"

    def __post_init__(self) -> None:
        _typed(self.identity, HistoricalEventIdentity, "identity")
        source_key(self.dividend_key, "dividend_key")
        _optional_id(self.instrument_id, "instrument_id")
        _optional_id(self.listing_id, "listing_id")
        _optional_id(self.correction_of, "correction_of")
        _typed(self.net, Money, "net")
        _typed(self.gross, HistoricalMoneyMetric, "gross")
        _typed(self.withholding, HistoricalMoneyMetric, "withholding")
        if self.kind != "dividend" or self.payment_convention not in (
            "exact_provider_instant",
            "payment_date_utc_start",
        ):
            fail_validation("Dividend payment convention is required.", field="payment_convention")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalCashEffect:
    identity: HistoricalEventIdentity
    effect_kind: Literal["fee", "tax", "interest", "internal_transfer", "fx_conversion"]
    signed_amount: Money
    related_event_keys: tuple[str, ...] = ()
    kind: Literal["cash_effect"] = "cash_effect"

    def __post_init__(self) -> None:
        _typed(self.identity, HistoricalEventIdentity, "identity")
        _typed(self.signed_amount, Money, "signed_amount")
        if self.kind != "cash_effect" or self.effect_kind not in (
            "fee",
            "tax",
            "interest",
            "internal_transfer",
            "fx_conversion",
        ):
            fail_validation("Unsupported cash effect.", field="effect_kind")
        source_tuple(self.related_event_keys, str, "related_event_keys", 16)
        for key in self.related_event_keys:
            source_key(key, "related_event_keys")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalCorporateAction:
    identity: HistoricalEventIdentity
    snapshot_id: str
    observation_index: int
    account_effect_evidence: tuple[str, ...] = ()
    kind: Literal["corporate_action"] = "corporate_action"

    def __post_init__(self) -> None:
        _typed(self.identity, HistoricalEventIdentity, "identity")
        source_id(self.snapshot_id, "snapshot_id")
        source_integer(self.observation_index, "observation_index", 0, 99_999)
        _ids(self.account_effect_evidence, "account_effect_evidence", 16)
        if self.kind != "corporate_action":
            fail_validation("Action discriminator differs.", field="kind")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalUnknownActivity:
    identity: HistoricalEventIdentity
    category: Literal[
        "unclassified", "unmatched_transfer", "unmatched_execution", "unmatched_dividend"
    ]
    known_amount: Money | None
    affected_coverage: tuple[HistoricalCoverageKey, ...]
    kind: Literal["unknown"] = "unknown"

    def __post_init__(self) -> None:
        _typed(self.identity, HistoricalEventIdentity, "identity")
        if self.kind != "unknown" or self.category not in (
            "unclassified",
            "unmatched_transfer",
            "unmatched_execution",
            "unmatched_dividend",
        ):
            fail_validation("Unknown activity requires a fixed category.", field="category")
        if self.known_amount is not None:
            _typed(self.known_amount, Money, "known_amount")
        source_tuple(self.affected_coverage, HistoricalCoverageKey, "affected_coverage", 10)


HistoricalEvent = (
    HistoricalExternalFlow
    | HistoricalExecution
    | HistoricalDividend
    | HistoricalCashEffect
    | HistoricalCorporateAction
    | HistoricalUnknownActivity
)
HISTORICAL_EVENT_TYPES = (
    HistoricalExternalFlow,
    HistoricalExecution,
    HistoricalDividend,
    HistoricalCashEffect,
    HistoricalCorporateAction,
    HistoricalUnknownActivity,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PinnedTargetAssignment:
    listing_id: str
    group_key: str
    group_name: str

    def __post_init__(self) -> None:
        source_id(self.listing_id, "listing_id")
        source_key(self.group_key, "group_key")
        require_bounded_text(self.group_name, field="group_name", maximum=160)


@dataclass(frozen=True, slots=True, kw_only=True)
class PinnedTargetGrouping:
    version_id: str
    content_digest: str
    effective_at: datetime
    published_at: datetime
    policy: Literal["historical_assignment", "explicit_comparison"]
    assignments: tuple[PinnedTargetAssignment, ...]

    def __post_init__(self) -> None:
        source_id(self.version_id, "version_id")
        historical_digest(self.content_digest)
        object.__setattr__(self, "effective_at", require_utc(self.effective_at))
        object.__setattr__(self, "published_at", require_utc(self.published_at))
        if self.policy not in ("historical_assignment", "explicit_comparison"):
            fail_validation("Grouping policy must be explicit.", field="policy")
        source_tuple(self.assignments, PinnedTargetAssignment, "assignments", 256)
        if len({x.listing_id for x in self.assignments}) != len(self.assignments):
            fail_validation("Target assignments must be disjoint.", field="assignments")


@dataclass(frozen=True, slots=True, kw_only=True)
class CompositeBenchmarkInput:
    benchmark_version_id: str
    definition_id: str
    content_digest: str
    content: BenchmarkContent
    published_at: datetime
    price_snapshots: tuple[PriceSnapshot, ...] = ()
    benchmark_snapshots: tuple[BenchmarkSnapshot, ...] = ()

    def __post_init__(self) -> None:
        source_id(self.benchmark_version_id, "benchmark_version_id")
        source_id(self.definition_id, "definition_id")
        historical_digest(self.content_digest)
        _typed(self.content, BenchmarkContent, "content")
        object.__setattr__(self, "published_at", require_utc(self.published_at))
        source_tuple(self.price_snapshots, PriceSnapshot, "price_snapshots", 256)
        source_tuple(self.benchmark_snapshots, BenchmarkSnapshot, "benchmark_snapshots", 256)


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalActivityCoverage:
    id: str
    capability: Literal["historical_orders", "historical_transactions", "historical_dividends"]
    start_at: datetime
    end_at: datetime
    first_observed_at: datetime
    ingestion_run_id: str
    coverage_complete: bool

    def __post_init__(self) -> None:
        source_id(self.id)
        source_id(self.ingestion_run_id, "ingestion_run_id")
        if self.capability not in (
            "historical_orders",
            "historical_transactions",
            "historical_dividends",
        ):
            fail_validation("Unsupported activity coverage capability.", field="capability")
        for name in ("start_at", "end_at", "first_observed_at"):
            object.__setattr__(self, name, require_utc(getattr(self, name)))
        if (
            self.end_at < self.start_at
            or self.end_at > self.first_observed_at
            or self.end_at - self.start_at > timedelta(days=7322)
        ):
            fail_validation(
                "Activity coverage cannot prove future or unbounded economics.", field="end_at"
            )
        if type(self.coverage_complete) is not bool:
            fail_validation(
                "Activity coverage completeness must be explicit.", field="coverage_complete"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalInput:
    owner_id: str
    account_id: str
    selection: HistoricalSelectionRequest
    opening: HistoricalOpening
    instruments: tuple[HistoricalInstrument, ...]
    event_candidates: tuple[HistoricalEvent, ...]
    valuation_anchors: tuple[HistoricalValuationAnchor, ...]
    price_snapshots: tuple[PriceSnapshot, ...]
    fx_snapshots: tuple[FxSnapshot, ...]
    action_snapshots: tuple[CorporateActionSnapshot, ...]
    calendars: tuple[SourceCalendar, ...]
    mapping_evidence: tuple[HistoricalMappingEvidence, ...]
    classification_evidence: tuple[HistoricalClassificationEvidence, ...]
    sources: tuple[HistoricalSourceReference, ...]
    coverage: HistoricalCoverage
    warnings: tuple[HistoricalIssue, ...] = ()
    activity_coverage: tuple[HistoricalActivityCoverage, ...] = ()
    benchmark_input: CompositeBenchmarkInput | None = None
    target_grouping: PinnedTargetGrouping | None = None
    schema_version: str = HISTORICAL_SCHEMA_VERSION
    method_version: str = HISTORICAL_METHOD_VERSION

    def __post_init__(self) -> None:
        source_id(self.owner_id, "owner_id")
        source_id(self.account_id, "account_id")
        _typed(self.selection, HistoricalSelectionRequest, "selection")
        _typed(
            self.opening,
            (ObservedHistoricalOpening, InceptionHistoricalOpening, UnavailableHistoricalOpening),
            "opening",
        )
        for name, kind, bound in (
            ("instruments", HistoricalInstrument, 256),
            ("event_candidates", HISTORICAL_EVENT_TYPES, MAX_HISTORICAL_EVENTS),
            ("valuation_anchors", HistoricalValuationAnchor, 10_000),
            ("activity_coverage", HistoricalActivityCoverage, 10_000),
            ("price_snapshots", PriceSnapshot, 256),
            ("fx_snapshots", FxSnapshot, 256),
            ("action_snapshots", CorporateActionSnapshot, 256),
            ("calendars", SourceCalendar, MAX_HISTORICAL_CALENDARS),
            ("mapping_evidence", HistoricalMappingEvidence, 8192),
            ("classification_evidence", HistoricalClassificationEvidence, 8192),
            ("sources", HistoricalSourceReference, MAX_HISTORICAL_SOURCES),
            ("warnings", HistoricalIssue, MAX_HISTORICAL_SOURCES),
        ):
            source_tuple(getattr(self, name), kind, name, bound)
        _typed(self.coverage, HistoricalCoverage, "coverage")
        if self.benchmark_input is not None:
            _typed(self.benchmark_input, CompositeBenchmarkInput, "benchmark_input")
        if self.target_grouping is not None:
            _typed(self.target_grouping, PinnedTargetGrouping, "target_grouping")
        if (
            self.schema_version != HISTORICAL_SCHEMA_VERSION
            or self.method_version != HISTORICAL_METHOD_VERSION
        ):
            fail_validation("Unsupported historical input version.", field="schema_version")
        _input_bounds(self)


def _input_bounds(value: HistoricalInput) -> None:
    calendars = {(x.id, x.version) for x in value.calendars}
    if (
        len(calendars) != len(value.calendars)
        or sum(len(x.sessions) for x in value.calendars) > MAX_HISTORICAL_CALENDAR_SESSIONS
    ):
        fail_validation("Historical calendar bound or uniqueness differs.", field="calendars")
    reporting = value.selection.reporting_calendar_ref
    if reporting is not None and (reporting.id, reporting.version) not in calendars:
        fail_validation("Reporting calendar is not captured.", field="reporting_calendar_ref")
    snapshots: list[SourceSnapshot | CorporateActionSnapshot] = [
        *value.price_snapshots,
        *value.fx_snapshots,
        *value.action_snapshots,
    ]
    if value.benchmark_input is not None:
        snapshots.extend(
            (*value.benchmark_input.price_snapshots, *value.benchmark_input.benchmark_snapshots)
        )
    distinct = {x.id: x for x in snapshots}
    if len(distinct) > 256 or sum(len(x.observations) for x in distinct.values()) > 100_000:
        fail_validation("Historical source observation capacity exceeded.", field="snapshots")
    for snapshot in snapshots:
        if snapshot.owner_id != value.owner_id:
            fail_validation("Captured source ownership differs.", field="owner_id")
        if distinct[snapshot.id] != snapshot:
            fail_validation("Conflicting immutable source identity.", field="snapshots")
    if len({x.listing_id for x in value.instruments}) != len(value.instruments):
        fail_validation("Captured listings must be unique.", field="instruments")
    if len({x.identity.revision_id for x in value.event_candidates}) != len(value.event_candidates):
        fail_validation("Captured economic revisions must be unique.", field="event_candidates")
    if len({(x.kind, x.id) for x in value.sources}) != len(value.sources):
        fail_validation("Captured source references must be unique.", field="sources")
    currencies = {x.native_currency for x in value.instruments}
    if len(currencies) > 32:
        fail_validation("Historical currency capacity exceeded.", field="instruments")


def historical_previous_income_period(window: HistoricalWindow) -> tuple[datetime, datetime]:
    """Equal calendar months when aligned; otherwise the same count of UTC calendar days."""
    start, end = window.start_at, window.end_at
    if start.day == 1 and end.day == 1:
        months = (end.year - start.year) * 12 + end.month - start.month
        previous_month = start.year * 12 + start.month - 1 - months
        if previous_month < 12:
            fail_validation(
                "Prior income period exceeds supported calendar dates.", field="start_date"
            )
        return start.replace(year=previous_month // 12, month=previous_month % 12 + 1), start
    try:
        return start - (end - start), start
    except OverflowError:
        fail_validation("Prior income period exceeds supported calendar dates.", field="start_date")
