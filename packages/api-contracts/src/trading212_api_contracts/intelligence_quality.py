"""Fixed quality GET contract. Status and provenance only; no financial values."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from .targets import AwareInstant, CurrencyString, Cursor, Digest, UUIDString

IntelligenceKind = Literal[
    "valuation",
    "actual_vs_target",
    "drift",
    "performance",
    "benchmark",
    "income",
    "attribution",
    "cash_flow",
    "xray",
]
Quality = Literal["fresh", "stale", "partial", "estimated", "unreconciled", "failed"]
Availability = Literal["available", "partial", "unavailable"]
Freshness = Literal["fresh", "stale", "unavailable"]
Visibility = Literal["visible", "permission_required"]
Reason = Literal[
    "not_calculated",
    "input_missing",
    "recorded_unavailable",
    "computation_failed",
    "source_not_configured",
    "source_missing",
    "source_stale",
    "freshness_policy_missing",
    "source_license_denied",
    "source_license_unknown",
    "source_expired",
    "source_purged",
    "reconciliation_missing",
    "reconciliation_incomplete",
    "integrity_mismatch",
    "metadata_unavailable",
]
SourceKind = Literal[
    "portfolio_snapshot",
    "snapshot_position",
    "snapshot_cash",
    "calculation_run",
    "ingestion_run",
    "broker_source_record",
    "broker_source_occurrence",
    "reconciliation_run",
    "price_snapshot",
    "fx_snapshot",
    "provider_benchmark_snapshot",
    "corporate_action_snapshot",
    "instrument_mapping",
    "calendar_version",
    "provider_license_version",
    "benchmark_version",
    "target_version",
    "classification_evidence",
    "historical_evidence",
    "activity_revision_evidence",
    "entity_evidence_version",
    "classification_snapshot",
    "fund_definition",
    "fund_mapping",
    "constituent_snapshot",
    "xray_policy",
]
Count = Annotated[StrictInt, Field(ge=0, le=100_000_000)]
BoundedKey = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=160)]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IntelligenceDataQualityQuery(Closed):
    analytics_kind: IntelligenceKind = "valuation"
    cursor: Cursor | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 25


class IntelligenceQualitySelection(Closed):
    kind: Literal["valuation", "analytics"]
    id: UUIDString
    input_id: UUIDString | None
    input_kind: Literal["historical", "xray"] | None
    input_digest: Digest
    content_digest: Digest
    method_version: BoundedKey
    reporting_currency: CurrencyString
    valuation_at: AwareInstant
    source_cutoff_at: AwareInstant
    created_at: AwareInstant
    period_start: date | None
    period_end: date | None


IntelligenceMetricKey = Literal[
    "portfolio_total",
    "positions",
    "cash",
    "current_price",
    "direct_allocation",
    "value",
    "unclassified",
    "l1_drift",
    "weighted_squared_drift",
    "effective_weight_rounding_residual",
    "frontier_keys",
    "group_count",
    "holding_count",
    "unclassified_count",
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
    "attributed_amount",
    "residual",
    "uncovered_residual",
    "quantization_residual",
    "attributed_return",
    "residual_return",
    "dietz_denominator",
    "cash_drag",
    "brinson_allocation",
    "brinson_selection",
    "filtered_count",
    "external_count",
    "internal_count",
    "unresolved_count",
    "total",
    "company_known_weight",
    "cash_weight",
    "unresolved_weight",
    "duplicated_exposure",
    "top_concentrations",
    "hhi",
    "thresholds",
    "quality_coverage",
]

METRIC_KEYS: dict[IntelligenceKind, tuple[IntelligenceMetricKey, ...]] = {
    "valuation": (
        "portfolio_total",
        "positions",
        "cash",
        "current_price",
        "direct_allocation",
    ),
    "actual_vs_target": (
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
    "drift": (
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
    "performance": (
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
    "benchmark": (
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
    "income": (
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
    "attribution": (
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
    "cash_flow": (
        "event_count",
        "filtered_count",
        "external_count",
        "internal_count",
        "unresolved_count",
    ),
    "xray": (
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


class IntelligenceMetricQuality(Closed):
    key: IntelligenceMetricKey
    recorded_availability: Availability | None
    recorded_quality: Quality | None
    quality_basis: Literal["metric", "result_context", "input_context", "unavailable"]
    current_usability: Literal["usable", "blocked", "unavailable"]
    freshness: Freshness
    freshness_basis: Literal["metric_context", "required_sources", "unavailable"]
    missing_input: Literal["complete", "missing", "unknown"]
    license_applicability: Literal["licensed", "not_applicable", "unknown"]
    reasons: Annotated[list[Reason], Field(max_length=16)]


class IntelligenceSourceIdentity(Closed):
    kind: SourceKind
    id: UUIDString
    parent_id: UUIDString | None


class IntelligenceSourceFreshness(Closed):
    state: Freshness
    policy_version: BoundedKey | None
    reference_at: AwareInstant | None
    max_age_seconds: Annotated[StrictInt, Field(ge=0, le=315_360_000)] | None


class IntelligenceQualitySource(Closed):
    identity: IntelligenceSourceIdentity
    provider_id: UUIDString | None
    license_version_id: UUIDString | None
    content_digest: Digest | None
    effective_at: AwareInstant | None
    first_observed_at: AwareInstant | None
    expires_at: AwareInstant | None
    recorded_quality: Quality | None
    expected_count: Count | None
    available_count: Count | None
    freshness: IntelligenceSourceFreshness
    current_usability: Literal["usable", "blocked", "unavailable"]
    retention: Literal["retained", "expired", "purged", "unavailable"]
    license_applicability: Literal["licensed", "not_applicable", "unknown"]
    reasons: Annotated[list[Reason], Field(max_length=16)]


class IntelligenceSourcePage(Closed):
    items: Annotated[list[IntelligenceQualitySource], Field(max_length=100)]
    exact_total: Annotated[StrictInt, Field(ge=0, le=8192)]
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    next_cursor: Cursor | None
    expires_at: AwareInstant | None


class IntelligenceReconciliation(Closed):
    visibility: Visibility
    id: UUIDString | None
    as_of: AwareInstant | None
    status: Literal["reconciled", "unreconciled", "partial", "failed"] | None
    complete: StrictBool | None
    discrepancy_count: Count | None
    reason: Reason | None


class IntelligenceQualityPermissionRequired(Closed):
    state: Literal["permission_required"]
    account_id: UUIDString
    analytics_kind: IntelligenceKind
    checked_at: AwareInstant
    missing_scope: Literal["activity:read", "targets:read"]
    supported_kinds: Annotated[list[IntelligenceKind], Field(min_length=9, max_length=9)]

    @model_validator(mode="after")
    def fixed_permission(self) -> Self:
        required = {
            "income": "activity:read",
            "cash_flow": "activity:read",
            "actual_vs_target": "targets:read",
            "drift": "targets:read",
        }
        if required.get(self.analytics_kind) != self.missing_scope or tuple(
            self.supported_kinds
        ) != tuple(METRIC_KEYS):
            raise ValueError("The permission branch and supported catalogue are fixed.")
        return self


class IntelligenceDataQuality(Closed):
    state: Literal["quality"]
    account_id: UUIDString
    analytics_kind: IntelligenceKind
    checked_at: AwareInstant
    selection_at: AwareInstant
    selection: IntelligenceQualitySelection | None
    selection_state: Literal["retained", "not_available", "unavailable"]
    metrics: Annotated[list[IntelligenceMetricQuality], Field(min_length=1, max_length=64)]
    reconciliation: IntelligenceReconciliation
    sources: IntelligenceSourcePage
    activity_visibility: Visibility
    targets_visibility: Visibility
    supported_kinds: Annotated[list[IntelligenceKind], Field(min_length=9, max_length=9)]
    schema_version: Literal["1.0.0"]

    @model_validator(mode="after")
    def fixed_catalogue(self) -> Self:
        if tuple(row.key for row in self.metrics) != METRIC_KEYS[self.analytics_kind]:
            raise ValueError("Every family metric must appear exactly once in canonical order.")
        if tuple(self.supported_kinds) != tuple(METRIC_KEYS):
            raise ValueError("The supported kind catalogue is fixed.")
        if self.selection is None:
            if self.selection_state != "not_available" or self.sources.exact_total != 0:
                raise ValueError("Absent selection cannot expose source membership.")
        else:
            expected = "valuation" if self.analytics_kind == "valuation" else "analytics"
            expected_input = (
                "historical"
                if self.analytics_kind
                in {
                    "performance",
                    "benchmark",
                    "income",
                    "attribution",
                    "cash_flow",
                }
                else "xray"
                if self.analytics_kind == "xray"
                else None
            )
            if (
                self.selection.kind != expected
                or self.selection.input_kind != expected_input
                or ((self.selection.input_id is None) != (expected_input is None))
            ):
                raise ValueError("Selection must carry the actual typed producer/input pins.")
        if (
            len(self.sources.items) > self.sources.limit
            or len(self.sources.items) > self.sources.exact_total
        ):
            raise ValueError("Source page membership is invalid.")
        return self


IntelligenceQualityResponse = Annotated[
    IntelligenceDataQuality | IntelligenceQualityPermissionRequired, Field(discriminator="state")
]
