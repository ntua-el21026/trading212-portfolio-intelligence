"""Read-only status inventory for retained intelligence; no financial values."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from trading212_domain.values import require_utc
from trading212_security.principals import Principal, Scope

from .sources import SourceFreshnessState, SourceFreshnessView
from .views import Availability, ViewQuality

MAX_QUALITY_SOURCES = 8192
MAX_QUALITY_BYTES = 2 * 1024 * 1024


class IntelligenceKind(StrEnum):
    VALUATION = "valuation"
    ACTUAL_VS_TARGET = "actual_vs_target"
    DRIFT = "drift"
    PERFORMANCE = "performance"
    BENCHMARK = "benchmark"
    INCOME = "income"
    ATTRIBUTION = "attribution"
    CASH_FLOW = "cash_flow"
    XRAY = "xray"


SUPPORTED_KINDS = tuple(IntelligenceKind)

# Producer field names are an explicit contract, never a client-provided path.
METRIC_KEYS: dict[IntelligenceKind, tuple[str, ...]] = {
    IntelligenceKind.VALUATION: (
        "portfolio_total",
        "positions",
        "cash",
        "current_price",
        "direct_allocation",
    ),
    IntelligenceKind.ACTUAL_VS_TARGET: (
        "value",
        "cash",
        "unclassified",
        "l1_drift",
        "weighted_squared_drift",
        "effective_weight_rounding_residual",
        "frontier_keys",
        "group_count",
        "holding_count",
        "unclassified_count",
    ),
    IntelligenceKind.DRIFT: (
        "value",
        "cash",
        "unclassified",
        "l1_drift",
        "weighted_squared_drift",
        "effective_weight_rounding_residual",
        "frontier_keys",
        "group_count",
        "holding_count",
        "unclassified_count",
    ),
    IntelligenceKind.PERFORMANCE: (
        "beginning_value",
        "ending_value",
        "deposits",
        "withdrawals",
        "net_contributions",
        "investment_gain",
        "income",
        "fees",
        "withholding_taxes",
        "realized_profit_loss",
        "unrealized_profit_loss",
        "time_weighted_return",
        "money_weighted_return",
        "modified_dietz_return",
        "annualized_time_weighted_return",
        "annualized_modified_dietz_return",
        "maximum_drawdown",
    ),
    IntelligenceKind.BENCHMARK: (
        "portfolio_return",
        "benchmark_return",
        "excess_return",
        "tracking_difference",
        "relative_wealth_return",
        "annualized_portfolio_return",
        "annualized_benchmark_return",
        "annualized_tracking_difference",
        "tracking_error",
        "paired_observation_count",
        "comparable_total_return_basis",
    ),
    IntelligenceKind.INCOME: (
        "net_income",
        "gross_income",
        "withholding",
        "positive_income",
        "negative_corrections",
        "mean_invested_value",
        "income_yield",
        "previous_period_income",
        "dividend_growth",
        "event_count",
    ),
    IntelligenceKind.ATTRIBUTION: (
        "investment_gain",
        "attributed_amount",
        "residual",
        "uncovered_residual",
        "quantization_residual",
        "portfolio_return",
        "attributed_return",
        "residual_return",
        "dietz_denominator",
        "cash_drag",
        "brinson_allocation",
        "brinson_selection",
    ),
    IntelligenceKind.CASH_FLOW: (
        "event_count",
        "filtered_count",
        "external_count",
        "internal_count",
        "unresolved_count",
    ),
    IntelligenceKind.XRAY: (
        "total",
        "company_known_weight",
        "cash_weight",
        "unresolved_weight",
        "duplicated_exposure",
        "top_concentrations",
        "hhi",
        "thresholds",
        "quality_coverage",
    ),
}


class QualityReason(StrEnum):
    NOT_CALCULATED = "not_calculated"
    INPUT_MISSING = "input_missing"
    RECORDED_UNAVAILABLE = "recorded_unavailable"
    COMPUTATION_FAILED = "computation_failed"
    SOURCE_NOT_CONFIGURED = "source_not_configured"
    SOURCE_MISSING = "source_missing"
    SOURCE_STALE = "source_stale"
    FRESHNESS_POLICY_MISSING = "freshness_policy_missing"
    SOURCE_LICENSE_DENIED = "source_license_denied"
    SOURCE_LICENSE_UNKNOWN = "source_license_unknown"
    SOURCE_EXPIRED = "source_expired"
    SOURCE_PURGED = "source_purged"
    RECONCILIATION_MISSING = "reconciliation_missing"
    RECONCILIATION_INCOMPLETE = "reconciliation_incomplete"
    INTEGRITY_MISMATCH = "integrity_mismatch"
    METADATA_UNAVAILABLE = "metadata_unavailable"


class QualitySourceKind(StrEnum):
    PORTFOLIO_SNAPSHOT = "portfolio_snapshot"
    POSITION = "snapshot_position"
    CASH = "snapshot_cash"
    CALCULATION = "calculation_run"
    INGESTION = "ingestion_run"
    BROKER_RECORD = "broker_source_record"
    BROKER_OCCURRENCE = "broker_source_occurrence"
    RECONCILIATION = "reconciliation_run"
    PRICE = "price_snapshot"
    FX = "fx_snapshot"
    BENCHMARK = "provider_benchmark_snapshot"
    ACTION = "corporate_action_snapshot"
    MAPPING = "instrument_mapping"
    CALENDAR = "calendar_version"
    LICENSE = "provider_license_version"
    BENCHMARK_VERSION = "benchmark_version"
    TARGET = "target_version"
    CLASSIFICATION = "classification_evidence"
    EVIDENCE = "historical_evidence"
    REVISION = "activity_revision_evidence"
    ENTITY = "entity_evidence_version"
    XRAY_CLASSIFICATION = "classification_snapshot"
    FUND = "fund_definition"
    FUND_MAPPING = "fund_mapping"
    CONSTITUENT = "constituent_snapshot"
    XRAY_POLICY = "xray_policy"


@dataclass(frozen=True, slots=True, kw_only=True)
class IntelligenceDataQualityQuery:
    analytics_kind: IntelligenceKind = IntelligenceKind.VALUATION
    cursor: str | None = None
    limit: int = 25

    def __post_init__(self) -> None:
        if not isinstance(self.analytics_kind, IntelligenceKind):
            raise ValueError("A supported intelligence kind is required.")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ValueError("Page limit must be between 1 and 100.")
        if self.cursor is not None and (
            not isinstance(self.cursor, str) or not 1 <= len(self.cursor) <= 2048
        ):
            raise ValueError("A bounded opaque cursor is required.")


@dataclass(frozen=True, slots=True, kw_only=True)
class QualitySelection:
    kind: Literal["valuation", "analytics"]
    id: UUID
    input_id: UUID | None
    input_kind: Literal["historical", "xray"] | None
    input_digest: str
    content_digest: str
    method_version: str
    reporting_currency: str
    valuation_at: datetime
    source_cutoff_at: datetime
    created_at: datetime
    period_start: date | None = None
    period_end: date | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MetricQuality:
    key: str
    recorded_availability: Availability | None
    recorded_quality: ViewQuality | None
    quality_basis: Literal["metric", "result_context", "input_context", "unavailable"]
    current_usability: Literal["usable", "blocked", "unavailable"]
    freshness: SourceFreshnessState
    freshness_basis: Literal["metric_context", "required_sources", "unavailable"]
    missing_input: Literal["complete", "missing", "unknown"]
    license_applicability: Literal["licensed", "not_applicable", "unknown"]
    reasons: tuple[QualityReason, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class QualitySourceIdentity:
    kind: QualitySourceKind
    id: UUID
    parent_id: UUID | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class QualitySource:
    identity: QualitySourceIdentity
    provider_id: UUID | None = None
    license_version_id: UUID | None = None
    content_digest: str | None = None
    effective_at: datetime | None = None
    first_observed_at: datetime | None = None
    expires_at: datetime | None = None
    recorded_quality: ViewQuality | None = None
    expected_count: int | None = None
    available_count: int | None = None
    freshness: SourceFreshnessView = field(default_factory=SourceFreshnessView)
    current_usability: Literal["usable", "blocked", "unavailable"] = "unavailable"
    retention: Literal["retained", "expired", "purged", "unavailable"] = "unavailable"
    license_applicability: Literal["licensed", "not_applicable", "unknown"] = "unknown"
    reasons: tuple[QualityReason, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class QualitySourcePage:
    items: tuple[QualitySource, ...]
    exact_total: int
    limit: int
    next_cursor: str | None
    expires_at: datetime | None


@dataclass(frozen=True, slots=True, kw_only=True)
class QualityReconciliation:
    visibility: Literal["visible", "permission_required"]
    id: UUID | None = None
    as_of: datetime | None = None
    status: Literal["reconciled", "unreconciled", "partial", "failed"] | None = None
    complete: bool | None = None
    discrepancy_count: int | None = None
    reason: QualityReason | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class IntelligenceQualityPermissionRequired:
    account_id: UUID
    analytics_kind: IntelligenceKind
    checked_at: datetime
    missing_scope: Scope
    supported_kinds: tuple[IntelligenceKind, ...] = SUPPORTED_KINDS
    state: Literal["permission_required"] = "permission_required"


@dataclass(frozen=True, slots=True, kw_only=True)
class IntelligenceDataQuality:
    account_id: UUID
    analytics_kind: IntelligenceKind
    checked_at: datetime
    selection_at: datetime
    selection: QualitySelection | None
    selection_state: Literal["retained", "not_available", "unavailable"]
    metrics: tuple[MetricQuality, ...]
    reconciliation: QualityReconciliation
    sources: QualitySourcePage
    activity_visibility: Literal["visible", "permission_required"]
    targets_visibility: Literal["visible", "permission_required"]
    supported_kinds: tuple[IntelligenceKind, ...] = SUPPORTED_KINDS
    schema_version: Literal["1.0.0"] = "1.0.0"
    state: Literal["quality"] = "quality"

    def __post_init__(self) -> None:
        require_utc(self.checked_at)
        require_utc(self.selection_at)
        if tuple(row.key for row in self.metrics) != METRIC_KEYS[self.analytics_kind]:
            raise ValueError("Every fixed metric must appear exactly once in canonical order.")
        if not 0 <= self.sources.exact_total <= MAX_QUALITY_SOURCES:
            raise ValueError("Source membership exceeds its bound.")
        if len(self.sources.items) > self.sources.limit:
            raise ValueError("Source page exceeds its bound.")


type IntelligenceQualityResult = IntelligenceDataQuality | IntelligenceQualityPermissionRequired


class IntelligenceQualityError(ValueError):
    def __init__(self, code: Literal["RESULT_TOO_LARGE", "QUALITY_UNAVAILABLE"]) -> None:
        self.code = code
        super().__init__("Intelligence quality is unavailable.")


class IntelligenceDataQualityService(Protocol):
    async def get_intelligence_data_quality(
        self, principal: Principal, account_id: str, *, query: IntelligenceDataQualityQuery
    ) -> IntelligenceQualityResult: ...
