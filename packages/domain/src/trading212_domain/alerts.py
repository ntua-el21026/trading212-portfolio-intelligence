"""Immutable bounded alert rules, captured observations and pure transition records."""

from __future__ import annotations

import re
import types
from dataclasses import dataclass, fields
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from typing import cast, get_args, get_origin, get_type_hints
from uuid import UUID

from .enums import DiscrepancySeverity, QualityState
from .errors import DomainError, ErrorCode, fail_validation
from .historical import HistoricalCashFlowKind
from .ingestion import IngestionCapability
from .reports import ReportSourceKind, ReportType
from .sources import SourceLicense, SourceUse
from .values import CurrencyCode, Money, require_utc

ALERT_SCHEMA_VERSION = "1.0.0"
ALERT_METHOD = "alert_evaluation_v1"
ALERT_METHOD_VERSION = "1.0.0"
MAX_ALERT_INPUT_BYTES = 2 * 1024 * 1024
MAX_ALERT_RESULT_BYTES = 2 * 1024 * 1024
MAX_ALERT_EVENT_CANDIDATES = 10_000
MAX_ALERT_SOURCE_REFERENCES = 8192
MAX_ALERT_CONTEXTS = 256
ALERT_RETENTION_DAYS = 90


class AlertFamily(StrEnum):
    TARGET_DRIFT = "target_drift"
    GROUP_DRIFT = "group_drift"
    HOLDING_DRIFT = "holding_drift"
    CONCENTRATION = "concentration"
    EFFECTIVE_COMPANY_CONCENTRATION = "effective_company_concentration"
    ETF_OVERLAP = "etf_overlap"
    CASH_THRESHOLD = "cash_threshold"
    STALE_DATA = "stale_data"
    MISSING_COVERAGE = "missing_coverage"
    RECONCILIATION_FAILURE = "reconciliation_failure"
    PROVIDER_FAILURE = "provider_failure"
    FAILED_REFRESH = "failed_refresh"
    DIVIDEND_RECEIVED = "dividend_received"
    UNUSUAL_ACTIVITY = "unusual_activity"
    REPORT_OUTCOME = "report_outcome"


class AlertMetric(StrEnum):
    PORTFOLIO_L1_DRIFT = "portfolio_l1_drift"
    GROUP_ABSOLUTE_DRIFT = "group_absolute_drift"
    HOLDING_ABSOLUTE_DRIFT = "holding_absolute_drift"
    DIRECT_MAX_WEIGHT = "direct_max_weight"
    DIRECT_TOP_N_WEIGHT = "direct_top_n_weight"
    DIRECT_HHI = "direct_hhi"
    EFFECTIVE_ENTITY_WEIGHT = "effective_entity_weight"
    EFFECTIVE_TOP_N_WEIGHT = "effective_top_n_weight"
    EFFECTIVE_HHI = "effective_hhi"
    ETF_PAIR_OVERLAP = "etf_pair_overlap"
    PORTFOLIO_DUPLICATED_EXPOSURE = "portfolio_duplicated_exposure"
    CASH_AMOUNT = "cash_amount"
    CASH_WEIGHT = "cash_weight"
    SOURCE_AGE_SECONDS = "source_age_seconds"
    SOURCE_MISSING_SESSIONS = "source_missing_sessions"
    MISSING_COUNT = "missing_count"
    MISSING_FRACTION = "missing_fraction"
    RECONCILIATION_FAILED = "reconciliation_failed"
    RECONCILIATION_DISCREPANCY_COUNT = "reconciliation_discrepancy_count"
    PROVIDER_FAILED = "provider_failed"
    PROVIDER_CONSECUTIVE_FAILURES = "provider_consecutive_failures"
    REFRESH_FAILED = "refresh_failed"
    POSITIVE_DIVIDEND = "positive_dividend"
    ABSOLUTE_EXTERNAL_FLOW_AMOUNT = "absolute_external_flow_amount"
    ACTIVITY_COUNT = "activity_count"
    UNCLASSIFIED_ACTIVITY = "unclassified_activity"
    REPORT_TERMINAL = "report_terminal"


class AlertComparison(StrEnum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertQualityPolicy(StrEnum):
    REQUIRE_COMPLETE = "require_complete"
    ALLOW_DEGRADED = "allow_degraded"


class AlertLifecycle(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class AlertSourceFamily(StrEnum):
    VALUATION = "valuation"
    HISTORY = "history"
    PRICE = "price"
    FX = "fx"
    CONSTITUENT = "constituent"
    CLASSIFICATION = "classification"


class AlertScheduleKind(StrEnum):
    INTERVAL = "interval"
    DAILY_UTC = "daily_utc"


class AlertReportOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EITHER = "either"


class AlertEvaluationOutcome(StrEnum):
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    SUPPRESSED = "suppressed"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class AlertExecutionIntent(StrEnum):
    LIVE = "live"
    OBSERVE_ONLY = "observe_only"


class AlertAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class AlertMetricKind(StrEnum):
    DECIMAL = "decimal"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    EVENT = "event"


class AlertBound(StrEnum):
    EXACT = "exact"
    LOWER_BOUND = "lower_bound"


class AlertOrigin(StrEnum):
    OBSERVED_PROVIDER = "observed_provider"
    NORMALIZED_PROVIDER = "normalized_provider"
    DERIVED_DETERMINISTIC = "derived_deterministic"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"
    PROVIDER = "provider"
    DERIVED = "derived"


class AlertReason(StrEnum):
    MISSING_INPUT = "missing_input"
    MISSING_FX = "missing_fx"
    CURRENCY_MISMATCH = "currency_mismatch"
    UNSUPPORTED = "unsupported"
    AMBIGUOUS_SOURCE = "ambiguous_source"
    UNKNOWN_IDENTITY = "unknown_identity"
    UNKNOWN_DENOMINATOR = "unknown_denominator"
    INCOMPLETE_COVERAGE = "incomplete_coverage"
    MATERIAL_QUALITY = "material_quality"
    INCONCLUSIVE_LOWER_BOUND = "inconclusive_lower_bound"
    NOT_CONFIGURED = "not_configured"
    NO_OBSERVATIONS = "no_observations"
    SOURCE_RESTRICTED = "source_restricted"
    SOURCE_EXPIRED = "source_expired"
    INPUT_BOUND_EXCEEDED = "input_bound_exceeded"
    COMPUTATION_FAILED = "computation_failed"
    FILTERED_OUT = "filtered_out"
    RULE_PAUSED = "rule_paused"
    RULE_ARCHIVED = "rule_archived"
    RULE_SUPERSEDED = "rule_superseded"
    LEASE_EXPIRED = "lease_expired"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    PUBLICATION_UNAVAILABLE = "publication_unavailable"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    ACCESS_DENIED = "access_denied"


class AlertResolutionReason(StrEnum):
    CONDITION_CLEARED = "condition_cleared"
    MANUAL = "manual"
    RULE_SUPERSEDED = "rule_superseded"
    RULE_ARCHIVED = "rule_archived"


class AlertNotificationState(StrEnum):
    ELIGIBLE = "eligible"
    SUPPRESSED_COOLDOWN = "suppressed_cooldown"
    EXTERNAL_DELIVERY_UNAVAILABLE = "external_delivery_unavailable"


class AlertCanonicalFamily(StrEnum):
    VALUATION = "valuation"
    TARGET = "target"
    PLANNING = "planning"
    HISTORICAL = "historical"
    XRAY = "xray"
    RECONCILIATION = "reconciliation"
    REFRESH = "refresh"
    PROVIDER = "provider"
    REPORT = "report"


class AlertInputRole(StrEnum):
    SNAPSHOT = "snapshot"
    INPUT = "input"
    RESULT = "result"
    POLICY = "policy"
    TARGET_VERSION = "target_version"
    MAPPING = "mapping"
    CALENDAR = "calendar"
    EVENT_REVISION = "event_revision"
    LICENSE = "license"


def alert_require(condition: bool, field: str) -> None:
    if not condition:
        fail_validation("Invalid typed alert value.", field=field)


def alert_limit(condition: bool, field: str) -> None:
    if not condition:
        raise DomainError(ErrorCode.INPUT_BOUND_EXCEEDED, "Alert input exceeds its bound.", field)


def alert_decimal(value: Decimal, *, nonnegative: bool = False) -> Decimal:
    alert_require(type(value) is Decimal and value.is_finite(), "decimal")
    shape = value.as_tuple()
    alert_require(
        isinstance(shape.exponent, int)
        and shape.exponent >= -18
        and value.copy_abs() < Decimal("1e20"),
        "decimal",
    )
    alert_require(not nonnegative or value >= 0, "decimal")
    return value


@lru_cache(maxsize=128)
def alert_hints(kind: type) -> dict[str, object]:
    return get_type_hints(kind)


def alert_typed(value: object, annotation: object) -> bool:
    origin = get_origin(annotation)
    if origin is types.UnionType:
        return any(alert_typed(value, option) for option in get_args(annotation))
    if origin is tuple:
        return type(value) is tuple and all(
            alert_typed(item, get_args(annotation)[0]) for item in value
        )
    return isinstance(annotation, type) and type(value) is annotation


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertRecord:
    def __post_init__(self) -> None:
        hints = alert_hints(cast(type, type(self)))
        for field in fields(self):
            value = getattr(self, field.name)
            alert_require(alert_typed(value, hints[field.name]), field.name)
            if type(value) is str:
                alert_limit(len(value) <= (2048 if "cursor" in field.name else 2000), field.name)
                if field.name.endswith("digest"):
                    alert_require(re.fullmatch(r"[0-9a-f]{64}", value) is not None, field.name)
            elif type(value) is datetime:
                object.__setattr__(self, field.name, require_utc(value))
            elif type(value) is tuple:
                alert_limit(len(value) <= MAX_ALERT_EVENT_CANDIDATES, field.name)
            elif type(value) is Decimal:
                alert_require(value.is_finite(), field.name)
            elif type(value) is int:
                alert_require(-(2**63) < value < 2**63, field.name)


# Exact supported metric family, value kind, required and optional scope fields.
_SPECS: dict[
    AlertMetric, tuple[AlertFamily, AlertMetricKind, tuple[str, ...], tuple[str, ...]]
] = {}


def _spec(
    family: AlertFamily,
    kind: AlertMetricKind,
    metrics: tuple[AlertMetric, ...],
    required: tuple[str, ...] = (),
    optional: tuple[str, ...] = (),
) -> None:
    for metric in metrics:
        _SPECS[metric] = (family, kind, required, optional)


_spec(
    AlertFamily.TARGET_DRIFT,
    AlertMetricKind.DECIMAL,
    (AlertMetric.PORTFOLIO_L1_DRIFT,),
    ("target_version_id", "frontier_depth"),
)
_spec(
    AlertFamily.GROUP_DRIFT,
    AlertMetricKind.DECIMAL,
    (AlertMetric.GROUP_ABSOLUTE_DRIFT,),
    ("target_version_id", "group_node_id"),
)
_spec(
    AlertFamily.HOLDING_DRIFT,
    AlertMetricKind.DECIMAL,
    (AlertMetric.HOLDING_ABSOLUTE_DRIFT,),
    ("target_version_id", "holding_id"),
)
_spec(
    AlertFamily.CONCENTRATION,
    AlertMetricKind.DECIMAL,
    (AlertMetric.DIRECT_MAX_WEIGHT, AlertMetric.DIRECT_HHI),
    ("include_cash",),
)
_spec(
    AlertFamily.CONCENTRATION,
    AlertMetricKind.DECIMAL,
    (AlertMetric.DIRECT_TOP_N_WEIGHT,),
    ("include_cash", "top_n"),
)
_spec(
    AlertFamily.EFFECTIVE_COMPANY_CONCENTRATION,
    AlertMetricKind.DECIMAL,
    (AlertMetric.EFFECTIVE_ENTITY_WEIGHT,),
    ("entity_id",),
)
_spec(
    AlertFamily.EFFECTIVE_COMPANY_CONCENTRATION,
    AlertMetricKind.DECIMAL,
    (AlertMetric.EFFECTIVE_TOP_N_WEIGHT,),
    ("top_n",),
)
_spec(
    AlertFamily.EFFECTIVE_COMPANY_CONCENTRATION,
    AlertMetricKind.DECIMAL,
    (AlertMetric.EFFECTIVE_HHI,),
)
_spec(
    AlertFamily.ETF_OVERLAP,
    AlertMetricKind.DECIMAL,
    (AlertMetric.ETF_PAIR_OVERLAP,),
    ("left_fund_id", "right_fund_id"),
)
_spec(
    AlertFamily.ETF_OVERLAP, AlertMetricKind.DECIMAL, (AlertMetric.PORTFOLIO_DUPLICATED_EXPOSURE,)
)
_spec(
    AlertFamily.CASH_THRESHOLD, AlertMetricKind.DECIMAL, (AlertMetric.CASH_AMOUNT,), ("currency",)
)
_spec(AlertFamily.CASH_THRESHOLD, AlertMetricKind.DECIMAL, (AlertMetric.CASH_WEIGHT,))
_spec(
    AlertFamily.STALE_DATA,
    AlertMetricKind.INTEGER,
    (AlertMetric.SOURCE_AGE_SECONDS,),
    ("source_family", "source_id"),
)
_spec(
    AlertFamily.STALE_DATA,
    AlertMetricKind.INTEGER,
    (AlertMetric.SOURCE_MISSING_SESSIONS,),
    ("source_family", "source_id", "calendar_version_id"),
)
_spec(
    AlertFamily.MISSING_COVERAGE,
    AlertMetricKind.INTEGER,
    (AlertMetric.MISSING_COUNT,),
    ("domain", "source_id"),
)
_spec(
    AlertFamily.MISSING_COVERAGE,
    AlertMetricKind.DECIMAL,
    (AlertMetric.MISSING_FRACTION,),
    ("domain", "source_id"),
)
_spec(
    AlertFamily.RECONCILIATION_FAILURE,
    AlertMetricKind.BOOLEAN,
    (AlertMetric.RECONCILIATION_FAILED,),
)
_spec(
    AlertFamily.RECONCILIATION_FAILURE,
    AlertMetricKind.INTEGER,
    (AlertMetric.RECONCILIATION_DISCREPANCY_COUNT,),
    optional=("discrepancy_severity",),
)
_spec(
    AlertFamily.PROVIDER_FAILURE,
    AlertMetricKind.BOOLEAN,
    (AlertMetric.PROVIDER_FAILED,),
    ("provider_id", "window_seconds"),
)
_spec(
    AlertFamily.PROVIDER_FAILURE,
    AlertMetricKind.INTEGER,
    (AlertMetric.PROVIDER_CONSECUTIVE_FAILURES,),
    ("provider_id", "window_seconds"),
)
_spec(
    AlertFamily.FAILED_REFRESH,
    AlertMetricKind.EVENT,
    (AlertMetric.REFRESH_FAILED,),
    optional=("capability_family",),
)
_spec(
    AlertFamily.DIVIDEND_RECEIVED,
    AlertMetricKind.EVENT,
    (AlertMetric.POSITIVE_DIVIDEND,),
    optional=("instrument_id", "minimum_net_amount"),
)
_spec(
    AlertFamily.UNUSUAL_ACTIVITY,
    AlertMetricKind.DECIMAL,
    (AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT,),
    ("window_seconds", "currency"),
    ("activity_kind",),
)
_spec(
    AlertFamily.UNUSUAL_ACTIVITY,
    AlertMetricKind.INTEGER,
    (AlertMetric.ACTIVITY_COUNT,),
    ("window_seconds",),
    ("activity_kind",),
)
_spec(
    AlertFamily.UNUSUAL_ACTIVITY,
    AlertMetricKind.EVENT,
    (AlertMetric.UNCLASSIFIED_ACTIVITY,),
    ("window_seconds",),
    ("activity_kind",),
)
_spec(
    AlertFamily.REPORT_OUTCOME,
    AlertMetricKind.EVENT,
    (AlertMetric.REPORT_TERMINAL,),
    ("outcome",),
    ("report_type",),
)


def alert_metric_kind(metric: AlertMetric) -> AlertMetricKind:
    return _SPECS[metric][1]


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertPredicate(AlertRecord):
    family: AlertFamily
    metric: AlertMetric
    comparison: AlertComparison | None = None
    threshold: Decimal | int | bool | None = None
    currency: CurrencyCode | None = None
    target_version_id: UUID | None = None
    frontier_depth: int | None = None
    group_node_id: UUID | None = None
    holding_id: UUID | None = None
    include_cash: bool | None = None
    top_n: int | None = None
    entity_id: UUID | None = None
    left_fund_id: UUID | None = None
    right_fund_id: UUID | None = None
    source_family: AlertSourceFamily | None = None
    domain: AlertSourceFamily | None = None
    source_id: UUID | None = None
    calendar_version_id: UUID | None = None
    discrepancy_severity: DiscrepancySeverity | None = None
    provider_id: UUID | None = None
    window_seconds: int | None = None
    capability_family: IngestionCapability | None = None
    instrument_id: UUID | None = None
    minimum_net_amount: Money | None = None
    activity_kind: HistoricalCashFlowKind | None = None
    report_type: ReportType | None = None
    outcome: AlertReportOutcome | None = None

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        family, kind, required, optional = _SPECS[self.metric]
        alert_require(self.family is family, "family")
        if "top_n" in required and self.top_n is None:
            object.__setattr__(self, "top_n", 25)
        for name in required:
            alert_require(getattr(self, name) is not None, name)
        for field in fields(self):
            if field.name not in {
                "family",
                "metric",
                "comparison",
                "threshold",
                *required,
                *optional,
            }:
                alert_require(getattr(self, field.name) is None, field.name)
        expected = {
            AlertMetricKind.DECIMAL: Decimal,
            AlertMetricKind.INTEGER: int,
            AlertMetricKind.BOOLEAN: bool,
        }
        if kind is AlertMetricKind.EVENT:
            alert_require(self.comparison is None and self.threshold is None, "threshold")
        else:
            alert_require(
                self.comparison is not None and type(self.threshold) is expected[kind], "threshold"
            )
            if kind is AlertMetricKind.BOOLEAN:
                alert_require(self.comparison is AlertComparison.EQ, "comparison")
            elif type(self.threshold) is int:
                alert_require(self.threshold >= 0, "threshold")
            elif type(self.threshold) is Decimal:
                alert_decimal(self.threshold)
                if self.metric is AlertMetric.PORTFOLIO_L1_DRIFT:
                    alert_require(0 <= self.threshold <= 2, "threshold")
                elif self.metric not in {
                    AlertMetric.CASH_AMOUNT,
                    AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT,
                }:
                    alert_require(0 <= self.threshold <= 1, "threshold")
                elif self.metric is AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT:
                    alert_require(self.threshold >= 0, "threshold")
        if self.top_n is not None:
            alert_require(1 <= self.top_n <= 50, "top_n")
        if self.frontier_depth is not None:
            alert_require(1 <= self.frontier_depth <= 8, "frontier_depth")
        if self.window_seconds is not None:
            alert_require(300 <= self.window_seconds <= 2678400, "window_seconds")
        if self.left_fund_id is not None:
            alert_require(
                self.right_fund_id is not None and self.left_fund_id != self.right_fund_id,
                "fund_pair",
            )
            if str(self.left_fund_id) > str(self.right_fund_id):
                left, right = self.left_fund_id, self.right_fund_id
                object.__setattr__(self, "left_fund_id", right)
                object.__setattr__(self, "right_fund_id", left)
        if self.minimum_net_amount is not None:
            alert_require(alert_decimal(self.minimum_net_amount.amount) > 0, "minimum_net_amount")


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertIntervalSchedule(AlertRecord):
    anchor_at: datetime
    interval_seconds: int = 300
    kind: AlertScheduleKind = AlertScheduleKind.INTERVAL

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(
            self.kind is AlertScheduleKind.INTERVAL and 300 <= self.interval_seconds <= 86400,
            "schedule",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertDailyUtcSchedule(AlertRecord):
    minute_utc: int
    kind: AlertScheduleKind = AlertScheduleKind.DAILY_UTC

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(
            self.kind is AlertScheduleKind.DAILY_UTC and 0 <= self.minute_utc <= 1439, "schedule"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertRuleDefinition(AlertRecord):
    name: str
    predicate: AlertPredicate
    schedule: AlertIntervalSchedule | AlertDailyUtcSchedule
    severity: AlertSeverity = AlertSeverity.WARNING
    quality_policy: AlertQualityPolicy = AlertQualityPolicy.REQUIRE_COMPLETE
    cooldown_seconds: int = 0
    source_policy_version_id: UUID | None = None
    destination_ids: tuple[UUID, ...] = ()
    remediation: str = ""

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(1 <= len(self.name) <= 120 and bool(self.name.strip()), "name")
        alert_require(0 <= self.cooldown_seconds <= 604800, "cooldown_seconds")
        alert_limit(len(self.destination_ids) <= 256, "destination_ids")
        alert_require(
            len(set(self.destination_ids)) == len(self.destination_ids), "destination_ids"
        )
        object.__setattr__(self, "destination_ids", tuple(sorted(self.destination_ids, key=str)))


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertRuleVersion(AlertRecord):
    id: UUID
    rule_id: UUID
    owner_id: UUID
    account_id: UUID
    version_number: int
    created_at: datetime
    content_digest: str
    definition: AlertRuleDefinition

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(self.version_number >= 1, "version_number")
        from .alert_serialization import alert_record_digest

        alert_require(
            self.content_digest == alert_record_digest(self.definition), "version.content_digest"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertRatioBasis(AlertRecord):
    """Private integral coefficients; compare before any Q18 display rounding."""

    numerator: Decimal
    denominator: Decimal
    numeric_policy_version: str = "xray_decimal256_exact_q18_v1"

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        for name, value, bound in (
            ("numerator", self.numerator, Decimal("1e232")),
            ("denominator", self.denominator, Decimal("1e228")),
        ):
            shape = value.as_tuple()
            alert_require(
                isinstance(shape.exponent, int)
                and 0 <= shape.exponent <= 249
                and len(shape.digits) <= 250
                and 0 <= value < bound,
                name,
            )
        alert_require(
            self.denominator > 0 and self.numeric_policy_version == "xray_decimal256_exact_q18_v1",
            "denominator",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertObservedMetric(AlertRecord):
    metric: AlertMetric
    kind: AlertMetricKind
    value: Decimal | int | bool | None
    availability: AlertAvailability
    quality: QualityState
    origin: AlertOrigin
    context_key: str
    currency: CurrencyCode | None = None
    bound: AlertBound = AlertBound.EXACT
    positive_below_quantum: bool = False
    reason: AlertReason | None = None

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(self.kind is alert_metric_kind(self.metric), "metric.kind")
        unavailable = self.availability in {AlertAvailability.UNAVAILABLE, AlertAvailability.FAILED}
        alert_require((self.value is None) == unavailable, "metric.value")
        alert_require(not unavailable or self.reason is not None, "metric.reason")
        if self.value is not None:
            kind = {
                AlertMetricKind.DECIMAL: Decimal,
                AlertMetricKind.INTEGER: int,
                AlertMetricKind.BOOLEAN: bool,
                AlertMetricKind.EVENT: bool,
            }[self.kind]
            alert_require(type(self.value) is kind, "metric.value")
            if type(self.value) is Decimal:
                alert_decimal(self.value)
            if type(self.value) is int:
                alert_require(self.value >= 0, "metric.value")
        amount = self.metric in {
            AlertMetric.CASH_AMOUNT,
            AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT,
            AlertMetric.POSITIVE_DIVIDEND,
        }
        alert_require(amount or self.currency is None, "metric.currency")
        alert_require(
            not self.positive_below_quantum or (type(self.value) is Decimal and self.value == 0),
            "positive_below_quantum",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertMetricObservation(AlertRecord):
    observed: AlertObservedMetric
    comparison_basis: Decimal | int | bool | AlertRatioBasis | None
    material_complete: bool = True

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        if type(self.comparison_basis) is Decimal:
            alert_decimal(self.comparison_basis)
        unavailable = self.observed.availability in {
            AlertAvailability.UNAVAILABLE,
            AlertAvailability.FAILED,
        }
        alert_require(unavailable == (self.comparison_basis is None), "comparison_basis")
        if isinstance(self.comparison_basis, AlertRatioBasis):
            alert_require(
                self.observed.metric
                in {
                    AlertMetric.EFFECTIVE_ENTITY_WEIGHT,
                    AlertMetric.EFFECTIVE_TOP_N_WEIGHT,
                    AlertMetric.EFFECTIVE_HHI,
                    AlertMetric.ETF_PAIR_OVERLAP,
                    AlertMetric.PORTFOLIO_DUPLICATED_EXPOSURE,
                },
                "comparison_basis.metric",
            )
        elif not unavailable:
            alert_require(
                type(self.comparison_basis) is type(self.observed.value)
                and self.comparison_basis == self.observed.value,
                "comparison_basis.value",
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertCanonicalBinding(AlertRecord):
    family: AlertCanonicalFamily
    role: AlertInputRole
    subject_id: UUID
    content_digest: str
    parent_id: UUID | None = None
    method_key: str | None = None
    method_version: str | None = None
    numeric_policy_version: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertSourceReference(AlertRecord):
    key: str
    kind: ReportSourceKind
    subject_id: UUID
    content_digest: str
    effective_at: datetime
    first_observed_at: datetime
    parent_id: UUID | None = None
    provider_id: UUID | None = None
    license_version_id: UUID | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertCoverageFact(AlertRecord):
    key: str
    expected_count: int | None = None
    available_count: int | None = None
    complete: bool | None = None
    covered_fraction: Decimal | None = None

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(self.expected_count is None or self.expected_count >= 0, "expected_count")
        alert_require(self.available_count is None or self.available_count >= 0, "available_count")
        if self.expected_count is not None and self.available_count is not None:
            alert_require(self.available_count <= self.expected_count, "available_count")
        if self.covered_fraction is not None:
            alert_require(0 <= alert_decimal(self.covered_fraction) <= 1, "covered_fraction")


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertWarning(AlertRecord):
    code: str
    message: str
    source_reference_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertResultContext(AlertRecord):
    key: str
    account_id: UUID
    source_cutoff_at: datetime
    valuation_at: datetime
    method_key: str
    method_version: str
    quality: QualityState
    reporting_currency: CurrencyCode | None = None
    source_reference_keys: tuple[str, ...] = ()
    coverage: tuple[AlertCoverageFact, ...] = ()
    warnings: tuple[AlertWarning, ...] = ()
    assumptions: tuple[str, ...] = ()
    reconciliation_id: UUID | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertObservationWindow(AlertRecord):
    start_at: datetime
    end_at: datetime
    newly_known_revisions: bool
    active_interval_id: UUID | None = None

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(self.start_at <= self.end_at, "window")


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertThresholdInput(AlertRecord):
    observation: AlertMetricObservation


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertEventObservation(AlertRecord):
    identity: UUID
    economic_at: datetime
    first_eligible_at: datetime
    observation: AlertMetricObservation
    revision_id: UUID | None = None
    correction_of: UUID | None = None
    instrument_id: UUID | None = None
    activity_kind: HistoricalCashFlowKind | None = None
    capability_family: IngestionCapability | None = None
    report_type: ReportType | None = None
    report_outcome: AlertReportOutcome | None = None
    net_amount: Money | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertEventBatchInput(AlertRecord):
    events: tuple[AlertEventObservation, ...]
    complete: bool
    reason: AlertReason | None = None

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(self.complete or self.reason is not None, "events.reason")
        keys = [(event.identity, event.revision_id) for event in self.events]
        alert_require(len(set(keys)) == len(keys), "events.identity")
        object.__setattr__(
            self,
            "events",
            tuple(
                sorted(
                    self.events,
                    key=lambda e: (e.first_eligible_at, str(e.identity), str(e.revision_id)),
                )
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertEvaluationInput(AlertRecord):
    version: AlertRuleVersion
    scheduled_for: datetime
    source_cutoff_at: datetime
    observation_window: AlertObservationWindow
    payload: AlertThresholdInput | AlertEventBatchInput
    contexts: tuple[AlertResultContext, ...]
    execution_intent: AlertExecutionIntent = AlertExecutionIntent.LIVE
    canonical_bindings: tuple[AlertCanonicalBinding, ...] = ()
    source_references: tuple[AlertSourceReference, ...] = ()
    licenses: tuple[SourceLicense, ...] = ()
    fx_conversions: tuple[AlertMoneyConversion, ...] = ()
    schema_version: str = ALERT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(self.schema_version == ALERT_SCHEMA_VERSION, "schema_version")
        alert_require(
            self.scheduled_for == self.source_cutoff_at == self.observation_window.end_at, "cutoff"
        )
        alert_require(self.version.created_at <= self.source_cutoff_at, "version.knowledge")
        alert_limit(
            len(self.contexts) <= MAX_ALERT_CONTEXTS
            and len(self.source_references) <= MAX_ALERT_SOURCE_REFERENCES,
            "references",
        )
        contexts = {item.key: item for item in self.contexts}
        sources = {item.key: item for item in self.source_references}
        alert_require(
            len(contexts) == len(self.contexts) and len(sources) == len(self.source_references),
            "references",
        )
        for context in self.contexts:
            alert_require(
                context.account_id == self.version.account_id
                and context.source_cutoff_at == self.source_cutoff_at,
                "context",
            )
            alert_require(set(context.source_reference_keys) <= sources.keys(), "context.sources")
            for warning in context.warnings:
                alert_require(
                    set(warning.source_reference_keys) <= sources.keys(), "warning.sources"
                )
        licenses = {item.id: item for item in self.licenses}
        alert_require(len(licenses) == len(self.licenses), "licenses.identity")
        bindings = {(item.family, item.role, item.subject_id) for item in self.canonical_bindings}
        alert_require(len(bindings) == len(self.canonical_bindings), "bindings.identity")
        for license in self.licenses:
            alert_require(
                license.effective_at <= self.source_cutoff_at
                and license.permits(SourceUse.STORE)
                and license.permits(SourceUse.DISPLAY),
                "license",
            )
        for source in self.source_references:
            if source.license_version_id is not None:
                matched_license = licenses.get(str(source.license_version_id))
                alert_require(
                    matched_license is not None
                    and matched_license.provider_id == str(source.provider_id),
                    "source.license",
                )
        for conversion in self.fx_conversions:
            for leg in conversion.legs:
                fx_source = sources.get(leg.source_reference_key)
                alert_require(fx_source is not None, "fx.sources")
                assert fx_source is not None
                if fx_source.kind is ReportSourceKind.BROKER_SOURCE_RECORD:
                    linked = (
                        leg.provider_id is None
                        and leg.snapshot_id is None
                        and fx_source.provider_id is None
                        and fx_source.parent_id is None
                        and fx_source.license_version_id is None
                    )
                else:
                    linked = (
                        fx_source.kind is ReportSourceKind.FX_OBSERVATION
                        and leg.provider_id is not None
                        and leg.snapshot_id is not None
                        and fx_source.provider_id == leg.provider_id
                        and fx_source.parent_id == leg.snapshot_id
                        and fx_source.license_version_id is not None
                    )
                alert_require(
                    linked and fx_source.effective_at == leg.observed_at,
                    "fx.sources",
                )
        for source in self.source_references:
            alert_require(
                max(source.effective_at, source.first_observed_at) <= self.source_cutoff_at,
                "source.knowledge",
            )
        event_mode = self.version.definition.predicate.metric in {
            AlertMetric.REFRESH_FAILED,
            AlertMetric.POSITIVE_DIVIDEND,
            AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT,
            AlertMetric.UNCLASSIFIED_ACTIVITY,
            AlertMetric.REPORT_TERMINAL,
        }
        alert_require(event_mode == isinstance(self.payload, AlertEventBatchInput), "payload")
        observations = (
            (self.payload.observation,)
            if isinstance(self.payload, AlertThresholdInput)
            else tuple(e.observation for e in self.payload.events)
        )
        for observation in observations:
            alert_require(
                observation.observed.metric is self.version.definition.predicate.metric
                and observation.observed.context_key in contexts,
                "observation",
            )
        if isinstance(self.payload, AlertEventBatchInput):
            for event in self.payload.events:
                alert_require(
                    event.first_eligible_at <= self.source_cutoff_at
                    and event.economic_at <= self.source_cutoff_at,
                    "event.cutoff",
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertEventDecision(AlertRecord):
    identity: UUID
    revision_id: UUID | None
    correction_of: UUID | None
    outcome: AlertEvaluationOutcome
    decision: bool | None
    observation: AlertObservedMetric
    deduplication_digest: str
    reason: AlertReason | None = None

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        expected = {
            AlertEvaluationOutcome.MATCHED: True,
            AlertEvaluationOutcome.NOT_MATCHED: False,
        }.get(self.outcome)
        alert_require(
            self.decision is expected and (self.decision is not None or self.reason is not None),
            "event.decision",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertEvaluationResult(AlertRecord):
    rule_version_id: UUID
    input_digest: str
    scheduled_for: datetime
    source_cutoff_at: datetime
    execution_intent: AlertExecutionIntent
    outcome: AlertEvaluationOutcome
    decision: bool | None
    contexts: tuple[AlertResultContext, ...]
    observation: AlertObservedMetric | None = None
    event_decisions: tuple[AlertEventDecision, ...] = ()
    reason: AlertReason | None = None
    schema_version: str = ALERT_SCHEMA_VERSION
    method_key: str = ALERT_METHOD
    method_version: str = ALERT_METHOD_VERSION

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(self.scheduled_for == self.source_cutoff_at, "cutoff")
        expected = {
            AlertEvaluationOutcome.MATCHED: True,
            AlertEvaluationOutcome.NOT_MATCHED: False,
        }.get(self.outcome)
        alert_require(self.decision is expected, "decision")
        alert_require(self.decision is not None or self.reason is not None, "reason")
        alert_require(
            (self.schema_version, self.method_key, self.method_version)
            == (ALERT_SCHEMA_VERSION, ALERT_METHOD, ALERT_METHOD_VERSION),
            "method",
        )
        contexts = {item.key: item for item in self.contexts}
        alert_limit(len(contexts) <= MAX_ALERT_CONTEXTS, "contexts")
        alert_require(len(contexts) == len(self.contexts), "contexts.identity")
        alert_require(
            all(item.source_cutoff_at == self.source_cutoff_at for item in self.contexts),
            "context.cutoff",
        )
        observations = (
            (self.observation,)
            if self.observation is not None
            else tuple(item.observation for item in self.event_decisions)
        )
        alert_require(not (self.observation is not None and self.event_decisions), "result.payload")
        alert_require(
            all(item.context_key in contexts for item in observations), "observation.context"
        )
        alert_require(
            len({item.deduplication_digest for item in self.event_decisions})
            == len(self.event_decisions),
            "events.identity",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertConditionState(AlertRecord):
    rule_version_id: UUID
    last_applied_scheduled_for: datetime | None = None
    last_conclusive_decision: bool | None = None
    armed: bool = True
    open_episode_id: UUID | None = None
    next_episode_ordinal: int = 1
    last_eligible_notification_at: datetime | None = None

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(self.next_episode_ordinal >= 1, "episode_ordinal")
        alert_require(
            self.open_episode_id is None
            or (not self.armed and self.last_conclusive_decision is True),
            "episode.state",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertTransitionIntent(AlertRecord):
    deduplication_digest: str
    episode_ordinal: int | None
    event_identity: UUID | None
    revision_id: UUID | None
    correction_of: UUID | None
    notification_state: AlertNotificationState


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertTransitionPlan(AlertRecord):
    state: AlertConditionState
    create: tuple[AlertTransitionIntent, ...] = ()
    resolve_episode_id: UUID | None = None
    resolution_reason: AlertResolutionReason | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertFxLeg(AlertRecord):
    base: CurrencyCode
    quote: CurrencyCode
    rate: Decimal | None
    source_reference_key: str
    snapshot_id: UUID | None
    provider_id: UUID | None
    observed_at: datetime
    inverse: bool = False
    reason: AlertReason | None = None

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(self.base != self.quote and bool(self.source_reference_key), "fx")
        alert_require((self.snapshot_id is None) == (self.provider_id is None), "fx.parent")
        if self.rate is None:
            alert_require(self.reason is not None, "fx.reason")
        else:
            alert_require(alert_decimal(self.rate) > 0 and self.reason is None, "fx.rate")


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertMoneyConversion(AlertRecord):
    original: Money
    reporting_currency: CurrencyCode
    converted: Money | None
    comparison_basis: Decimal | None
    legs: tuple[AlertFxLeg, ...]
    reason: AlertReason | None = None

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_limit(len(self.legs) <= 2, "fx.legs")
        alert_require((self.converted is None) == (self.comparison_basis is None), "fx.basis")
        alert_require(
            self.converted is None or self.converted.currency == self.reporting_currency,
            "fx.currency",
        )
        alert_require(self.converted is not None or self.reason is not None, "fx.reason")
        if self.converted is not None:
            alert_require(
                self.comparison_basis == self.converted.amount and self.reason is None, "fx.basis"
            )
        if self.original.currency == self.reporting_currency:
            alert_require(not self.legs and self.converted == self.original, "fx.identity")
        elif self.legs:
            current = self.original.currency
            for leg in self.legs:
                source, target = (leg.quote, leg.base) if leg.inverse else (leg.base, leg.quote)
                alert_require(current == source, "fx.chain")
                current = target
            alert_require(current == self.reporting_currency, "fx.target")
            if len(self.legs) == 2:
                first, second = self.legs
                alert_require(
                    first.snapshot_id is not None
                    and first.provider_id is not None
                    and (first.snapshot_id, first.provider_id, first.observed_at)
                    == (second.snapshot_id, second.provider_id, second.observed_at),
                    "fx.compatibility",
                )
