"""Strict Phase 1 MCP wire schemas with decimal strings and explicit quality."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .historical_schemas import (
    HistoricalAttributionToolResult,
    HistoricalBenchmarkToolResult,
    HistoricalDividendToolResult,
    HistoricalPerformanceToolResult,
)
from .planning_schemas import (
    ActualVsTargetToolResult,
    ContributionPlanToolResult,
    CreateContributionPlanToolResult,
    DriftAnalysisToolResult,
)
from .target_schemas import VirtualPieResult, VirtualPiesResult
from .xray_schemas import XrayExposureToolResult, XrayOverlapToolResult

DecimalString = Annotated[str, Field(pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
OpaqueId = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9._:-]+$")]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PositionSort(StrEnum):
    MARKET_VALUE_DESC = "market_value_desc"
    WEIGHT_DESC = "weight_desc"
    TICKER_ASC = "ticker_asc"


class ActivityTypeFilter(StrEnum):
    ALL = "all"
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    INTEREST = "interest"
    FEE = "fee"
    TAX = "tax"
    FX_CONVERSION = "fx_conversion"
    UNKNOWN = "unknown"


class ErrorDetail(StrictSchema):
    code: Literal[
        "AUTHENTICATION_REQUIRED",
        "ACCESS_DENIED",
        "DATA_REFRESH_PENDING",
        "PROVIDER_RATE_LIMITED",
        "PROVIDER_UNAVAILABLE",
        "DATA_INCOMPLETE",
        "CALCULATION_UNAVAILABLE",
        "VALIDATION_FAILED",
        "CURSOR_INVALID",
        "COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED",
        "NOT_FOUND",
        "INTERNAL_ERROR",
    ]
    message: Annotated[str, Field(min_length=1, max_length=240)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=128)]
    retryable: bool
    remediation: Annotated[str, Field(min_length=1, max_length=240)]


class DataQuality(StrictSchema):
    state: Literal["fresh", "stale", "partial", "estimated", "unreconciled", "failed"]
    warnings: Annotated[list[Annotated[str, Field(max_length=240)]], Field(max_length=20)]
    missing_inputs: Annotated[list[Annotated[str, Field(max_length=120)]], Field(max_length=20)]
    source_cutoff_at: datetime
    freshness_threshold_seconds: Annotated[int, Field(ge=0, le=31_536_000)]


class Calculation(StrictSchema):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    version: Annotated[str, Field(min_length=1, max_length=120)]
    calculated_at: datetime
    assumptions: Annotated[list[Annotated[str, Field(max_length=240)]], Field(max_length=20)]


class Pagination(StrictSchema):
    next_cursor: Annotated[str, Field(max_length=2048)] | None
    limit: Annotated[int, Field(ge=1, le=100)]
    total: Annotated[int, Field(ge=0)]
    truncated: bool


class Metric(StrictSchema):
    value: DecimalString | None
    reporting_currency: CurrencyCode
    availability: Literal["available", "partial", "unavailable"]
    calculation_version: Annotated[str, Field(min_length=1, max_length=120)]
    methodology: Annotated[str, Field(min_length=1, max_length=240)]
    provenance: Annotated[list[Annotated[str, Field(max_length=120)]], Field(max_length=20)]
    assumptions: Annotated[list[Annotated[str, Field(max_length=240)]], Field(max_length=20)]
    unavailable_reason: Annotated[str, Field(max_length=240)] | None


class Account(StrictSchema):
    id: OpaqueId
    display_name: Annotated[str, Field(min_length=1, max_length=120)]
    provider: Annotated[str, Field(min_length=1, max_length=40)]
    environment: Annotated[str, Field(min_length=1, max_length=40)]
    account_type: Annotated[str, Field(min_length=1, max_length=40)]
    reporting_currency: CurrencyCode
    connection_state: Annotated[str, Field(min_length=1, max_length=80)]
    last_refresh_at: datetime | None


class ReconciliationSummary(StrictSchema):
    status: Annotated[str, Field(min_length=1, max_length=40)]
    evaluated_at: datetime
    discrepancy_count: Annotated[int, Field(ge=0)]


class AccountSummaryData(StrictSchema):
    account: Account
    total_value: Metric
    cash_balance: Metric
    invested_value: Metric
    net_contributions: Metric
    dividends_received: Metric
    realized_profit_loss: Metric
    unrealized_profit_loss: Metric
    position_count: Annotated[int, Field(ge=0)]
    reconciliation: ReconciliationSummary
    read_only: Literal[True] = True


class SnapshotData(StrictSchema):
    id: OpaqueId
    valuation_at: datetime
    source_cutoff_at: datetime
    reporting_currency: CurrencyCode
    total_value: Metric
    cash_value: Metric
    invested_value: Metric
    net_contributions: Metric
    dividends_received: Metric
    realized_profit_loss: Metric
    unrealized_profit_loss: Metric
    read_only: Literal[True] = True
    synthetic_data: bool
    quality_disclosure: Annotated[str, Field(min_length=1, max_length=240)]


class PositionRow(StrictSchema):
    id: OpaqueId
    ticker: Annotated[str, Field(min_length=1, max_length=40)]
    name: Annotated[str, Field(min_length=1, max_length=160)]
    instrument_type: Annotated[str, Field(min_length=1, max_length=40)]
    quantity: DecimalString
    trading_currency: CurrencyCode
    current_price: DecimalString | None
    market_value: Metric
    provider_cost_basis: Metric
    provider_unrealized_profit_loss: Metric
    direct_weight: DecimalString | None
    data_quality: DataQuality


class PositionsData(StrictSchema):
    positions: Annotated[list[PositionRow], Field(max_length=50)]
    sort: PositionSort
    search: Annotated[str, Field(max_length=80)] | None
    read_only: Literal[True] = True


class ActivityRow(StrictSchema):
    id: OpaqueId
    occurred_at: datetime
    activity_type: Annotated[str, Field(min_length=1, max_length=80)]
    direction: Annotated[str, Field(min_length=1, max_length=80)]
    amount: Metric
    ticker: Annotated[str, Field(max_length=40)] | None
    quantity: DecimalString | None
    description: Annotated[str, Field(max_length=240)]
    data_quality: DataQuality


class TransactionsData(StrictSchema):
    transactions: Annotated[list[ActivityRow], Field(max_length=50)]
    period_start: date
    period_end: date
    type_filter: ActivityTypeFilter
    read_only: Literal[True] = True


class DividendRow(StrictSchema):
    id: OpaqueId
    paid_on: date
    ticker: Annotated[str, Field(min_length=1, max_length=40)]
    net_amount: Metric
    gross_amount: Metric
    withholding_tax: Metric
    quantity: DecimalString | None
    data_quality: DataQuality


class DividendCurrencyTotal(StrictSchema):
    currency: CurrencyCode
    net_amount: DecimalString | None
    gross_amount: DecimalString | None
    withholding_tax: DecimalString | None


class DividendSummaryData(StrictSchema):
    period_start: date
    period_end: date
    totals_by_currency: Annotated[list[DividendCurrencyTotal], Field(max_length=20)]
    recent_dividends: Annotated[list[DividendRow], Field(max_length=25)]
    covered_record_count: Annotated[int, Field(ge=0)]
    totals_truncated: bool
    omitted_currency_count: Annotated[int, Field(ge=0)]
    read_only: Literal[True] = True


class AllocationRow(StrictSchema):
    id: OpaqueId
    label: Annotated[str, Field(min_length=1, max_length=160)]
    asset_type: Annotated[str, Field(min_length=1, max_length=40)]
    market_value: Metric
    weight: DecimalString | None
    weight_availability: Literal["available", "partial", "unavailable"]


class DirectAllocationData(StrictSchema):
    allocations: Annotated[list[AllocationRow], Field(max_length=51)]
    returned_count: Annotated[int, Field(ge=0, le=51)]
    includes_cash: bool
    etf_look_through: Literal[False] = False
    methodology: Literal["direct_provider_observed_positions_and_cash"]
    read_only: Literal[True] = True


class SnapshotCore(StrictSchema):
    id: OpaqueId
    valuation_at: datetime
    source_cutoff_at: datetime
    reporting_currency: CurrencyCode
    total_value: Metric
    cash_value: Metric
    invested_value: Metric
    net_contributions: Metric
    data_quality: DataQuality


class SnapshotComparisonData(StrictSchema):
    start: SnapshotCore
    end: SnapshotCore
    value_change: Metric
    net_external_flows: Metric
    investment_result: Metric
    reconciliation_residual: Metric
    attribution_available: Literal[False] = False
    read_only: Literal[True] = True


class ReconciliationIssue(StrictSchema):
    id: OpaqueId
    issue_type: Annotated[str, Field(min_length=1, max_length=80)]
    severity: Annotated[str, Field(min_length=1, max_length=40)]
    status: Annotated[str, Field(min_length=1, max_length=40)]
    summary: Annotated[str, Field(min_length=1, max_length=240)]
    expected_value: DecimalString | None
    observed_value: DecimalString | None
    residual: DecimalString | None
    tolerance: DecimalString | None
    currency: CurrencyCode | None


class ReconciliationData(StrictSchema):
    status: Annotated[str, Field(min_length=1, max_length=40)]
    evaluated_at: datetime
    algorithm_version: Annotated[str, Field(min_length=1, max_length=120)]
    tolerance_version: Annotated[str, Field(min_length=1, max_length=120)]
    discrepancy_count: Annotated[int, Field(ge=0)]
    issues: Annotated[list[ReconciliationIssue], Field(max_length=50)]
    remediation_guidance: Annotated[str, Field(min_length=1, max_length=240)]
    read_only: Literal[True] = True


class CapabilityQuality(StrictSchema):
    capability: Literal[
        "account_summary",
        "portfolio_snapshots",
        "positions",
        "activity",
        "dividends",
        "reconciliation",
    ]
    data_quality: DataQuality


class RefreshStepQuality(StrictSchema):
    capability: Annotated[str, Field(min_length=1, max_length=100)]
    status: Annotated[str, Field(min_length=1, max_length=40)]
    warnings: Annotated[list[Annotated[str, Field(max_length=500)]], Field(max_length=20)]


class RefreshRunQuality(StrictSchema):
    id: OpaqueId
    status: Annotated[str, Field(min_length=1, max_length=40)]
    started_at: datetime
    completed_at: datetime | None
    steps: Annotated[list[RefreshStepQuality], Field(max_length=20)]


class CheckpointQuality(StrictSchema):
    capability: Annotated[str, Field(min_length=1, max_length=100)]
    version: Annotated[int, Field(ge=1)]
    coverage_start_at: datetime | None
    coverage_end_at: datetime | None
    coverage_complete: bool


class DataQualitySummaryData(StrictSchema):
    capabilities: Annotated[list[CapabilityQuality], Field(min_length=6, max_length=6)]
    failed_or_partial_runs: Annotated[list[OpaqueId], Field(max_length=20)]
    latest_refresh_run: RefreshRunQuality | None
    latest_runs_by_status: Annotated[list[RefreshRunQuality], Field(max_length=3)]
    checkpoints: Annotated[list[CheckpointQuality], Field(max_length=20)]
    latest_snapshot_id: OpaqueId | None
    latest_snapshot_source_cutoff_at: datetime | None
    materialization_state: Literal["available", "partial", "missing"]
    reconciliation_status: Annotated[str, Field(min_length=1, max_length=40)]
    missing_fx_record_count: Annotated[int, Field(ge=0)]
    unknown_mapping_record_count: Annotated[int, Field(ge=0)]
    read_only: Literal[True] = True


class ToolEnvelope[PayloadT](StrictSchema):
    data: PayloadT | None
    as_of: datetime | None
    reporting_currency: CurrencyCode | None
    data_quality: DataQuality | None
    calculation: Calculation | None
    pagination: Pagination | None
    error: ErrorDetail | None

    @model_validator(mode="after")
    def exactly_one_result(self) -> ToolEnvelope[PayloadT]:
        if (self.data is None) == (self.error is None):
            raise ValueError("exactly one of data or error is required")
        if self.data is not None and (
            self.as_of is None
            or self.reporting_currency is None
            or self.data_quality is None
            or self.calculation is None
        ):
            raise ValueError("successful results require common financial metadata")
        return self


class AccountSummaryResult(ToolEnvelope[AccountSummaryData]):
    pass


class PortfolioSnapshotResult(ToolEnvelope[SnapshotData]):
    pass


class PositionsResult(ToolEnvelope[PositionsData]):
    pass


class TransactionsResult(ToolEnvelope[TransactionsData]):
    pass


class DividendSummaryResult(ToolEnvelope[DividendSummaryData]):
    pass


class DirectAllocationResult(ToolEnvelope[DirectAllocationData]):
    pass


class SnapshotComparisonResult(ToolEnvelope[SnapshotComparisonData]):
    pass


class ReconciliationResult(ToolEnvelope[ReconciliationData]):
    pass


class DataQualitySummaryResult(ToolEnvelope[DataQualitySummaryData]):
    pass


RESULT_MODELS = {
    "get_account_summary": AccountSummaryResult,
    "get_portfolio_snapshot": PortfolioSnapshotResult,
    "list_positions": PositionsResult,
    "list_recent_transactions": TransactionsResult,
    "get_dividend_summary": DividendSummaryResult,
    "get_direct_allocation": DirectAllocationResult,
    "compare_portfolio_snapshots": SnapshotComparisonResult,
    "get_reconciliation_status": ReconciliationResult,
    "get_data_quality_summary": DataQualitySummaryResult,
    "list_virtual_pies": VirtualPiesResult,
    "get_virtual_pie": VirtualPieResult,
    "get_actual_vs_target": ActualVsTargetToolResult,
    "get_drift_analysis": DriftAnalysisToolResult,
    "get_contribution_plan": ContributionPlanToolResult,
    "create_contribution_plan": CreateContributionPlanToolResult,
    "get_effective_exposure": XrayExposureToolResult,
    "get_etf_overlap": XrayOverlapToolResult,
    "get_performance_summary": HistoricalPerformanceToolResult,
    "get_benchmark_comparison": HistoricalBenchmarkToolResult,
    "get_dividend_intelligence": HistoricalDividendToolResult,
    "get_attribution_summary": HistoricalAttributionToolResult,
}
