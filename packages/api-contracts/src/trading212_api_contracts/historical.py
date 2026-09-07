"""Closed historical intelligence wire contracts shared by HTTP, MCP and web."""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)

from .sources import CalendarDate, SourceKey, SourceQuality
from .targets import AwareInstant, CurrencyString, Cursor, DecimalString, Digest, UUIDString

HistoricalMethod = Literal["twr", "mwr", "modified_dietz"]
HistoricalAttributionMethod = Literal["twr", "modified_dietz"]
HistoricalFrequency = Literal["daily", "monthly"]
HistoricalKnowledgePolicy = Literal["as_of_cutoff", "point_in_time"]
HistoricalCoveragePolicy = Literal["require_complete", "allow_degraded"]
HistoricalRollingWindow = Literal[
    "none", "calendar_days_30", "calendar_days_90", "calendar_days_365"
]
HistoricalCalendarPeriod = Literal["none", "month", "quarter", "year"]
HistoricalGrouping = Literal["holding", "group", "sector", "asset_class", "currency"]
HistoricalCashFlowKind = Literal[
    "deposit",
    "withdrawal",
    "transfer_in",
    "transfer_out",
    "buy",
    "sell",
    "dividend",
    "interest",
    "fee",
    "tax",
    "internal_transfer",
    "fx_conversion",
    "corporate_action",
    "unknown",
]


def _integer_query(value: object) -> object:
    if type(value) is int:
        return value
    if isinstance(value, str) and len(value) <= 6 and re.fullmatch(r"[1-9][0-9]*", value):
        return int(value)
    raise ValueError("A bounded integer selector is required.")


HistoricalPageLimit = Annotated[StrictInt, Field(ge=1, le=100), BeforeValidator(_integer_query)]
HistoricalTop = Annotated[StrictInt, Field(ge=1, le=50), BeforeValidator(_integer_query)]


class HistoricalSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def no_unknown_field_reflection(cls, value: object) -> object:
        if isinstance(value, dict) and any(key not in cls.model_fields for key in value):
            raise ValueError("The bounded historical object contains unexpected fields.")
        return value


class HistoricalWindowQuery(HistoricalSchema):
    start_date: CalendarDate
    end_date: CalendarDate
    source_cutoff_at: AwareInstant
    reporting_currency: CurrencyString
    coverage_policy: HistoricalCoveragePolicy = "require_complete"
    knowledge_policy: HistoricalKnowledgePolicy = "as_of_cutoff"
    input_snapshot_id: UUIDString | None = None

    @model_validator(mode="after")
    def inclusive_window(self) -> Self:
        if not 0 <= (self.end_date - self.start_date).days <= 3660:
            raise ValueError("The historical period exceeds its inclusive date bounds.")
        return self


class HistoricalPerformanceSummaryQuery(HistoricalWindowQuery):
    method: HistoricalMethod = "twr"
    frequency: HistoricalFrequency = "monthly"
    rolling_window: HistoricalRollingWindow = "none"
    calendar_period: HistoricalCalendarPeriod = "none"


class HistoricalPerformanceSeriesQuery(HistoricalPerformanceSummaryQuery):
    cursor: Cursor | None = None
    limit: HistoricalPageLimit = 25


class HistoricalBenchmarkComparisonQuery(HistoricalWindowQuery):
    benchmark_version_id: UUIDString
    frequency: HistoricalFrequency = "monthly"
    rolling_window: HistoricalRollingWindow = "none"
    calendar_period: HistoricalCalendarPeriod = "none"


class HistoricalAttributionQuery(HistoricalWindowQuery):
    grouping: HistoricalGrouping = "holding"
    method: HistoricalAttributionMethod = "twr"
    benchmark_version_id: UUIDString | None = None
    target_version_id: UUIDString | None = None
    grouping_policy: Literal["historical_assignment", "explicit_comparison"] | None = None
    top_n: HistoricalTop = 25

    @model_validator(mode="after")
    def group_has_target(self) -> Self:
        if self.grouping == "group" and self.target_version_id is None:
            raise ValueError("Group attribution requires an explicit target version.")
        if self.grouping_policy is not None and self.target_version_id is None:
            raise ValueError("A grouping policy requires an explicit target version.")
        return self


class HistoricalDividendIntelligenceQuery(HistoricalWindowQuery):
    grouping: Literal["holding", "group"] = "holding"
    target_version_id: UUIDString | None = None
    grouping_policy: Literal["historical_assignment", "explicit_comparison"] | None = None
    top_n: HistoricalTop = 25

    @model_validator(mode="after")
    def group_has_target(self) -> Self:
        if self.grouping == "group" and self.target_version_id is None:
            raise ValueError("Group income requires an explicit target version.")
        if self.grouping_policy is not None and self.target_version_id is None:
            raise ValueError("A grouping policy requires an explicit target version.")
        return self


class HistoricalCashFlowIntelligenceQuery(HistoricalWindowQuery):
    frequency: HistoricalFrequency = "monthly"
    kind: HistoricalCashFlowKind | None = None
    cursor: Cursor | None = None
    limit: HistoricalPageLimit = 25


HistoricalReason = Literal[
    "unavailable_opening_evidence",
    "unavailable_opening_reconciliation",
    "unavailable_event_coverage",
    "unavailable_unknown_economic_effect",
    "unavailable_ambiguous_economic_revision",
    "unavailable_unreconciled_knowledge_transition",
    "unavailable_valuation",
    "unavailable_price",
    "unavailable_fx",
    "unavailable_corporate_action_coverage",
    "unavailable_corporate_action_accounting",
    "unavailable_mapping",
    "unavailable_classification",
    "unavailable_cost_basis",
    "unavailable_gross_income",
    "unavailable_withholding",
    "unavailable_fee",
    "unavailable_positive_denominator",
    "unavailable_exact_flow_valuation",
    "unavailable_numeric_result",
    "unavailable_conventional_xirr_root",
    "unavailable_xirr_root",
    "unavailable_xirr_bracket",
    "unavailable_xirr_convergence",
    "unavailable_annualization_period",
    "unavailable_rolling_boundary",
    "unavailable_complete_calendar_period",
    "unavailable_benchmark_inputs",
    "unavailable_benchmark_alignment",
    "benchmark_price_only_comparison",
    "unavailable_reporting_currency_alignment",
    "unavailable_tracking_error_observations",
    "unavailable_positive_income",
    "unavailable_comparable_calendar_period",
    "unavailable_cash_counterfactual_inputs",
    "unavailable_price_quantity_basis",
    "partial_covered_subtotal",
    "historical_reconstruction_restated",
    "explicit_target_comparison_grouping",
    "output_quantization_residual",
    "unavailable_source_license",
    "unavailable_source_retention",
    "historical_source_stale",
    "unavailable_resource_capacity",
    "unavailable_income_assignment",
    "unavailable_benchmark_constituent_attribution",
]


HistoricalCoverageKey = Literal[
    "opening",
    "quantity",
    "cash",
    "cost",
    "events",
    "valuation_cells",
    "actions",
    "fx_cells",
    "benchmark_sessions",
    "prior_income",
]


class HistoricalMoney(HistoricalSchema):
    amount: DecimalString
    currency: CurrencyString


class HistoricalMetric[T](HistoricalSchema):
    value: T | None
    availability: Literal["available", "partial", "unavailable"]
    reason_code: HistoricalReason | None
    quality: SourceQuality
    coverage_key: HistoricalCoverageKey
    origin: Literal["provider", "derived"] = "derived"

    @model_validator(mode="after")
    def value_matches_availability(self) -> Self:
        if (self.value is None) != (self.availability == "unavailable"):
            raise ValueError("Historical metric value and availability disagree.")
        if self.availability != "available" and self.reason_code is None:
            raise ValueError("An incomplete historical metric requires a reason.")
        return self


class HistoricalMoneyMetric(HistoricalMetric[HistoricalMoney]):
    pass


class HistoricalRatioMetric(HistoricalMetric[DecimalString]):
    pass


class HistoricalIssue(HistoricalSchema):
    reason_code: HistoricalReason
    coverage_key: HistoricalCoverageKey | None = None
    reference_ids: Annotated[list[UUIDString], Field(max_length=64)] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_references(self) -> Self:
        if len(self.reference_ids) != len(set(self.reference_ids)):
            raise ValueError("Historical issue references cannot repeat.")
        return self


class HistoricalCoverageMeasure(HistoricalSchema):
    key: HistoricalCoverageKey
    expected_count: Annotated[StrictInt, Field(ge=0, le=400000)]
    available_count: Annotated[StrictInt, Field(ge=0, le=400000)]
    complete: StrictBool
    reasons: Annotated[list[HistoricalReason], Field(max_length=64)] = Field(default_factory=list)

    @model_validator(mode="after")
    def exact_coverage(self) -> Self:
        if self.available_count > self.expected_count or (
            self.complete and self.available_count != self.expected_count
        ):
            raise ValueError("Historical coverage and completeness disagree.")
        return self


class HistoricalCoverage(HistoricalSchema):
    measures: Annotated[list[HistoricalCoverageMeasure], Field(max_length=10)]

    @model_validator(mode="after")
    def unique_measures(self) -> Self:
        if len({item.key for item in self.measures}) != len(self.measures):
            raise ValueError("Historical coverage measures cannot repeat.")
        return self


class HistoricalSourceReference(HistoricalSchema):
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
        "ingestion_run",
    ]
    id: UUIDString
    effective_at: AwareInstant
    first_observed_at: AwareInstant
    semantic_digest: Digest | None = None
    version: SourceKey | None = None
    parent_ids: Annotated[list[UUIDString], Field(max_length=16)] = Field(default_factory=list)
    derived_projection_digest: Digest | None = None
    original_fingerprint: Digest | None = None

    @model_validator(mode="after")
    def unique_parents(self) -> Self:
        if len(set(self.parent_ids)) != len(self.parent_ids):
            raise ValueError("Historical source parents cannot repeat.")
        return self


HistoricalEventCount = Annotated[StrictInt, Field(ge=0, le=10000)]
HistoricalPointOrdinal = Annotated[StrictInt, Field(ge=0, le=3660)]
HistoricalLabel = Annotated[str, Field(strict=True, min_length=1, max_length=200)]


class HistoricalMethodMetadata(HistoricalSchema):
    name: SourceKey
    version: SourceKey


class HistoricalCalendarRef(HistoricalSchema):
    id: SourceKey
    version: SourceKey


class PerformanceMetrics(HistoricalSchema):
    beginning_value: HistoricalMoneyMetric
    ending_value: HistoricalMoneyMetric
    deposits: HistoricalMoneyMetric
    withdrawals: HistoricalMoneyMetric
    net_contributions: HistoricalMoneyMetric
    investment_gain: HistoricalMoneyMetric
    income: HistoricalMoneyMetric
    fees: HistoricalMoneyMetric
    withholding_taxes: HistoricalMoneyMetric
    realized_profit_loss: HistoricalMoneyMetric
    unrealized_profit_loss: HistoricalMoneyMetric
    time_weighted_return: HistoricalRatioMetric
    money_weighted_return: HistoricalRatioMetric
    modified_dietz_return: HistoricalRatioMetric
    annualized_time_weighted_return: HistoricalRatioMetric
    annualized_modified_dietz_return: HistoricalRatioMetric
    maximum_drawdown: HistoricalRatioMetric


class HistoricalPeriodReturn(HistoricalSchema):
    period_start_at: AwareInstant
    period_end_at: AwareInstant
    kind: Literal[
        "rolling_30",
        "rolling_90",
        "rolling_365",
        "calendar_month",
        "calendar_quarter",
        "calendar_year",
    ]
    method: HistoricalMethod
    value: HistoricalRatioMetric
    annualized_value: HistoricalRatioMetric


class BenchmarkComparisonMetrics(HistoricalSchema):
    portfolio_return: HistoricalRatioMetric
    benchmark_return: HistoricalRatioMetric
    excess_return: HistoricalRatioMetric
    tracking_difference: HistoricalRatioMetric
    relative_wealth_return: HistoricalRatioMetric
    annualized_portfolio_return: HistoricalRatioMetric
    annualized_benchmark_return: HistoricalRatioMetric
    annualized_tracking_difference: HistoricalRatioMetric
    tracking_error: HistoricalRatioMetric
    paired_observation_count: Annotated[StrictInt, Field(ge=0, le=3661)]
    comparable_total_return_basis: StrictBool


class BenchmarkComparisonPoint(HistoricalSchema):
    ordinal: HistoricalPointOrdinal
    date: CalendarDate
    valuation_at: AwareInstant
    portfolio_return: HistoricalRatioMetric
    benchmark_return: HistoricalRatioMetric
    excess_return: HistoricalRatioMetric
    portfolio_wealth: HistoricalRatioMetric
    benchmark_wealth: HistoricalRatioMetric
    relative_wealth: HistoricalRatioMetric


class HistoricalBenchmarkPeriodReturn(HistoricalSchema):
    period_start_at: AwareInstant
    period_end_at: AwareInstant
    kind: Literal[
        "rolling_30",
        "rolling_90",
        "rolling_365",
        "calendar_month",
        "calendar_quarter",
        "calendar_year",
    ]
    portfolio_return: HistoricalRatioMetric
    benchmark_return: HistoricalRatioMetric
    excess_return: HistoricalRatioMetric
    relative_wealth_return: HistoricalRatioMetric
    annualized_portfolio_return: HistoricalRatioMetric
    annualized_benchmark_return: HistoricalRatioMetric


class CurrencyIncomeTotals(HistoricalSchema):
    currency: CurrencyString
    net: HistoricalMoneyMetric
    gross: HistoricalMoneyMetric
    withholding: HistoricalMoneyMetric
    positive_income: HistoricalMoneyMetric
    negative_corrections: HistoricalMoneyMetric
    event_count: HistoricalEventCount
    positive_event_count: HistoricalEventCount
    correction_count: HistoricalEventCount


class IncomeMetrics(HistoricalSchema):
    net_income: HistoricalMoneyMetric
    gross_income: HistoricalMoneyMetric
    withholding: HistoricalMoneyMetric
    positive_income: HistoricalMoneyMetric
    negative_corrections: HistoricalMoneyMetric
    mean_invested_value: HistoricalMoneyMetric
    income_yield: HistoricalRatioMetric
    previous_period_income: HistoricalMoneyMetric
    dividend_growth: HistoricalRatioMetric
    event_count: HistoricalEventCount


class IncomeComponent(HistoricalSchema):
    key: SourceKey
    label: HistoricalLabel
    instrument_id: UUIDString | None
    group_key: SourceKey | None
    currency: CurrencyString
    net: HistoricalMoneyMetric
    gross: HistoricalMoneyMetric
    withholding: HistoricalMoneyMetric
    positive_income: HistoricalMoneyMetric
    negative_corrections: HistoricalMoneyMetric
    concentration: HistoricalRatioMetric
    event_count: HistoricalEventCount
    unresolved: StrictBool = False


class IncomePeriod(HistoricalSchema):
    start_date: CalendarDate
    end_date: CalendarDate
    totals: Annotated[list[CurrencyIncomeTotals], Field(max_length=32)]
    reporting_net: HistoricalMoneyMetric


class AttributionEffect(HistoricalSchema):
    kind: Literal["price", "income", "fees", "taxes", "fx", "interaction", "cash_fx"]
    amount: HistoricalMoneyMetric
    return_contribution: HistoricalRatioMetric


class AttributionComponent(HistoricalSchema):
    key: SourceKey
    label: HistoricalLabel
    instrument_id: UUIDString | None
    listing_id: UUIDString | None
    group_key: SourceKey | None
    currency: CurrencyString | None
    amount: HistoricalMoneyMetric
    return_contribution: HistoricalRatioMetric
    effects: Annotated[list[AttributionEffect], Field(max_length=7)]
    unresolved: StrictBool = False


class AttributionMetrics(HistoricalSchema):
    investment_gain: HistoricalMoneyMetric
    attributed_amount: HistoricalMoneyMetric
    residual: HistoricalMoneyMetric
    uncovered_residual: HistoricalMoneyMetric
    quantization_residual: HistoricalMoneyMetric
    portfolio_return: HistoricalRatioMetric
    attributed_return: HistoricalRatioMetric
    residual_return: HistoricalRatioMetric
    dietz_denominator: HistoricalMoneyMetric
    cash_drag: HistoricalRatioMetric
    brinson_allocation: HistoricalRatioMetric
    brinson_selection: HistoricalRatioMetric


class CurrencyCashFlowTotals(HistoricalSchema):
    currency: CurrencyString
    external_net: HistoricalMoneyMetric
    deposits: HistoricalMoneyMetric
    withdrawals: HistoricalMoneyMetric
    internal_net: HistoricalMoneyMetric
    income: HistoricalMoneyMetric
    fees: HistoricalMoneyMetric
    taxes: HistoricalMoneyMetric
    purchases: HistoricalMoneyMetric
    sales: HistoricalMoneyMetric
    unresolved_amount: HistoricalMoneyMetric
    external_count: HistoricalEventCount
    internal_count: HistoricalEventCount
    unresolved_count: HistoricalEventCount


class CashFlowMetrics(HistoricalSchema):
    event_count: HistoricalEventCount
    filtered_count: HistoricalEventCount
    external_count: HistoricalEventCount
    internal_count: HistoricalEventCount
    unresolved_count: HistoricalEventCount


class CashFlowPeriod(HistoricalSchema):
    start_date: CalendarDate
    end_date: CalendarDate
    native_totals: Annotated[list[CurrencyCashFlowTotals], Field(max_length=32)]
    reporting_totals: CurrencyCashFlowTotals


class HistoricalWindow(HistoricalSchema):
    start_date: CalendarDate
    end_date: CalendarDate
    source_cutoff_at: AwareInstant
    reporting_currency: CurrencyString
    coverage_policy: HistoricalCoveragePolicy
    knowledge_policy: HistoricalKnowledgePolicy


class HistoricalAccess(HistoricalSchema):
    reproducibility: Literal["reproducible", "inputs_expired", "license_restricted"]
    status_reference_at: AwareInstant | None


class HistoricalRunContext(HistoricalSchema):
    account_id: UUIDString
    window: HistoricalWindow
    method: HistoricalMethodMetadata
    primitive_methods: Annotated[list[HistoricalMethodMetadata], Field(max_length=8)]
    input_digest: Digest
    source_policy_version: SourceKey | None
    accounting_policy_version: SourceKey
    coverage: HistoricalCoverage
    quality: SourceQuality
    availability: Literal["available", "partial", "unavailable", "failed"]
    reconstruction: Literal["point_in_time", "restated"]
    sources: Annotated[list[HistoricalSourceReference], Field(max_length=64)]
    warnings: Annotated[list[HistoricalIssue], Field(max_length=64)]
    assumptions: Annotated[
        list[
            Literal[
                "utc_accounting_boundaries",
                "previous_completed_session_close",
                "explicit_target_comparison",
                "price_only_benchmark",
                "act_365",
                "income_holdings_and_fx_may_change",
            ]
        ],
        Field(max_length=16),
    ]
    schema_version: Literal["1.0.0"]
    run_id: UUIDString
    input_snapshot_id: UUIDString
    content_digest: Digest
    calculated_at: AwareInstant
    source_count: Annotated[StrictInt, Field(ge=0, le=8192)]
    source_omitted_count: Annotated[StrictInt, Field(ge=0, le=8192)]
    warning_count: Annotated[StrictInt, Field(ge=0, le=8192)]
    warning_omitted_count: Annotated[StrictInt, Field(ge=0, le=8192)]
    access: HistoricalAccess

    @model_validator(mode="after")
    def preview_counts(self) -> Self:
        if (
            len(self.sources) + self.source_omitted_count != self.source_count
            or len(self.warnings) + self.warning_omitted_count != self.warning_count
        ):
            raise ValueError("Historical context preview counts disagree.")
        return self


class PerformancePoint(HistoricalSchema):
    ordinal: HistoricalPointOrdinal
    date: CalendarDate
    valuation_at: AwareInstant
    portfolio_value: HistoricalMoneyMetric
    invested_value: HistoricalMoneyMetric
    cash_value: HistoricalMoneyMetric
    external_flow: HistoricalMoneyMetric
    deposits: HistoricalMoneyMetric
    withdrawals: HistoricalMoneyMetric
    net_contributions: HistoricalMoneyMetric
    income: HistoricalMoneyMetric
    fees: HistoricalMoneyMetric
    withholding_taxes: HistoricalMoneyMetric
    interval_return: HistoricalRatioMetric
    cumulative_return: HistoricalRatioMetric
    twr_wealth: HistoricalRatioMetric
    drawdown: HistoricalRatioMetric
    flow_count: HistoricalEventCount
    flow_revision_ids: Annotated[list[UUIDString], Field(max_length=4)]
    flow_revision_omitted_count: HistoricalEventCount = 0

    @model_validator(mode="after")
    def preview_count(self) -> Self:
        if len(self.flow_revision_ids) + self.flow_revision_omitted_count != self.flow_count:
            raise ValueError("Historical flow preview counts disagree.")
        return self


class HistoricalCashFlowPoint(HistoricalSchema):
    ordinal: Annotated[StrictInt, Field(ge=0, le=9999)]
    event_revision_id: UUIDString
    economic_key: SourceKey
    economic_at: AwareInstant
    kind: HistoricalCashFlowKind
    classification: Literal["external", "internal", "unresolved"]
    native_amount: HistoricalMoneyMetric
    reporting_amount: HistoricalMoneyMetric
    instrument_id: UUIDString | None
    listing_id: UUIDString | None
    group_key: SourceKey | None
    correction_of: SourceKey | None
    source_ref_ids: Annotated[list[UUIDString], Field(max_length=4)]
    source_ref_omitted_count: Annotated[StrictInt, Field(ge=0, le=8192)] = 0


class HistoricalEventPreview(HistoricalSchema):
    items: Annotated[list[HistoricalCashFlowPoint], Field(max_length=16)]
    total_count: HistoricalEventCount
    omitted_count: HistoricalEventCount

    @model_validator(mode="after")
    def exact_counts(self) -> Self:
        if len(self.items) + self.omitted_count != self.total_count:
            raise ValueError("Historical event preview counts disagree.")
        return self


class HistoricalPage[T](HistoricalSchema):
    items: Annotated[list[T], Field(max_length=100)]
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: Annotated[StrictInt, Field(ge=0, le=10000)]

    @model_validator(mode="after")
    def page_bounds(self) -> Self:
        if len(self.items) > self.limit or len(self.items) > self.total:
            raise ValueError("Historical page bounds disagree.")
        return self


class CompositeBenchmarkComponentRef(HistoricalSchema):
    source_id: UUIDString
    weight: DecimalString
    snapshot_ids: Annotated[list[UUIDString], Field(max_length=256)]
    license_version_ids: Annotated[list[UUIDString], Field(max_length=256)]
    calendar_ref: HistoricalCalendarRef


class CompositeBenchmarkHeader(HistoricalSchema):
    coverage: HistoricalCoverage
    id: UUIDString
    benchmark_version_id: UUIDString
    reporting_currency: CurrencyString
    return_basis: Literal["raw_close", "split_adjusted", "total_return"]
    calendar_id: SourceKey
    calendar_version: SourceKey
    rebalance_rule: Literal["buy_and_hold", "daily_rebalanced"]
    window: HistoricalWindow
    input_digest: Digest
    content_digest: Digest
    calculated_at: AwareInstant
    method: HistoricalMethodMetadata
    inputs: Annotated[list[CompositeBenchmarkComponentRef], Field(max_length=256)]
    observation_count: Annotated[StrictInt, Field(ge=0, le=3661)]
    kind: Literal["composite"]


class CompositeBenchmarkSnapshotHeader(CompositeBenchmarkHeader):
    access: HistoricalAccess


class PerformanceSeriesResponse(HistoricalSchema):
    context: HistoricalRunContext
    summary: PerformanceMetrics
    points: HistoricalPage[PerformancePoint]


class PerformanceIntelligenceResponse(HistoricalSchema):
    context: HistoricalRunContext
    summary: PerformanceMetrics
    series: Annotated[list[PerformancePoint], Field(max_length=3661)]
    rolling_returns: Annotated[list[HistoricalPeriodReturn], Field(max_length=3661)]
    calendar_returns: Annotated[list[HistoricalPeriodReturn], Field(max_length=121)]


class BenchmarkComparisonResponse(HistoricalSchema):
    context: HistoricalRunContext
    summary: BenchmarkComparisonMetrics
    series: Annotated[list[BenchmarkComparisonPoint], Field(max_length=3661)]
    composite_snapshot: CompositeBenchmarkSnapshotHeader | None
    rolling_returns: Annotated[list[HistoricalBenchmarkPeriodReturn], Field(max_length=3661)]
    calendar_returns: Annotated[list[HistoricalBenchmarkPeriodReturn], Field(max_length=121)]


class AttributionSummaryResponse(HistoricalSchema):
    context: HistoricalRunContext
    summary: AttributionMetrics
    rows: Annotated[list[AttributionComponent], Field(max_length=50)]
    eligible_count: Annotated[StrictInt, Field(ge=0, le=10000)]
    omitted_count: Annotated[StrictInt, Field(ge=0, le=10000)]
    effects: Annotated[list[AttributionEffect], Field(max_length=7)]

    @model_validator(mode="after")
    def top_counts(self) -> Self:
        if len(self.rows) + self.omitted_count != self.eligible_count:
            raise ValueError("Historical attribution row counts disagree.")
        return self


class DividendIntelligenceResponse(HistoricalSchema):
    context: HistoricalRunContext
    summary: IncomeMetrics
    native_currency_totals: Annotated[list[CurrencyIncomeTotals], Field(max_length=32)]
    reporting_totals: CurrencyIncomeTotals
    rows: Annotated[list[IncomeComponent], Field(max_length=50)]
    eligible_count: Annotated[StrictInt, Field(ge=0, le=10000)]
    omitted_count: Annotated[StrictInt, Field(ge=0, le=10000)]
    period_rows: Annotated[list[IncomePeriod], Field(max_length=121)]
    event_preview: HistoricalEventPreview

    @model_validator(mode="after")
    def top_counts(self) -> Self:
        if len(self.rows) + self.omitted_count != self.eligible_count:
            raise ValueError("Historical income row counts disagree.")
        return self


class CashFlowIntelligenceResponse(HistoricalSchema):
    context: HistoricalRunContext
    summary: CashFlowMetrics
    native_currency_totals: Annotated[list[CurrencyCashFlowTotals], Field(max_length=32)]
    reporting_totals: CurrencyCashFlowTotals
    period_rows: Annotated[list[CashFlowPeriod], Field(max_length=3661)]
    events: HistoricalPage[HistoricalCashFlowPoint]
    filtered_count: HistoricalEventCount


class CompositeBenchmarkPoint(HistoricalSchema):
    ordinal: HistoricalPointOrdinal
    session_date: CalendarDate
    effective_at: AwareInstant
    wealth: HistoricalRatioMetric
    interval_return: HistoricalRatioMetric


class CompositeBenchmarkObservationPage(HistoricalPage[CompositeBenchmarkPoint]):
    snapshot_id: UUIDString
    kind: Literal["composite"]
