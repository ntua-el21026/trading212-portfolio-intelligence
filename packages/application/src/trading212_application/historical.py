"""Authorized bounded contracts for immutable historical analytical captures and reads."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol

from trading212_domain.errors import fail_validation
from trading212_domain.historical import (
    HistoricalCoverage,
    HistoricalInput,
    HistoricalSelectionRequest,
    HistoricalWindow,
    historical_digest,
)
from trading212_domain.historical_results import (
    AttributionComponent,
    AttributionEffect,
    AttributionMetrics,
    AttributionOptions,
    BenchmarkComparisonMetrics,
    BenchmarkComparisonPoint,
    CashFlowMetrics,
    CashFlowOptions,
    CashFlowPeriod,
    ComparisonOptions,
    CompositeBenchmarkComponentRef,
    CurrencyCashFlowTotals,
    CurrencyIncomeTotals,
    HistoricalBenchmarkPeriodReturn,
    HistoricalCashFlowPoint,
    HistoricalMethod,
    HistoricalPeriodReturn,
    HistoricalResultContext,
    IncomeComponent,
    IncomeMetrics,
    IncomeOptions,
    IncomePeriod,
    PerformanceMetrics,
    PerformanceOptions,
    PerformancePoint,
)
from trading212_domain.sources import BenchmarkRebalanceRule, PriceBasis, source_id, source_integer
from trading212_domain.values import CurrencyCode, require_utc
from trading212_security.principals import Principal

from .targets import TargetPageQuery
from .views import Page


class HistoricalServiceErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INPUT_SNAPSHOT_MISMATCH = "INPUT_SNAPSHOT_MISMATCH"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    HISTORICAL_UNAVAILABLE = "HISTORICAL_UNAVAILABLE"
    RESULT_TOO_LARGE = "RESULT_TOO_LARGE"


@dataclass(slots=True)
class HistoricalServiceError(Exception):
    code: HistoricalServiceErrorCode
    message: str

    def __str__(self) -> str:
        return self.message


def _scope(window: HistoricalWindow, input_snapshot_id: str | None) -> None:
    if not isinstance(window, HistoricalWindow):
        fail_validation("An exact typed historical window is required.", field="window")
    if input_snapshot_id is not None:
        source_id(input_snapshot_id, "input_snapshot_id")


def _options(value: object, kind: type[object]) -> None:
    if not isinstance(value, kind):
        fail_validation("Typed historical options are required.", field="options")


def _grouping(target_version_id: str | None, grouping_policy: str | None) -> str | None:
    if target_version_id is None:
        if grouping_policy is not None:
            fail_validation("Grouping policy requires a target version.", field="grouping_policy")
        return None
    source_id(target_version_id, "target_version_id")
    if grouping_policy not in (None, "historical_assignment", "explicit_comparison"):
        fail_validation("Unsupported historical grouping policy.", field="grouping_policy")
    return grouping_policy or "explicit_comparison"


@dataclass(frozen=True, slots=True, kw_only=True)
class PerformanceSeriesQuery(TargetPageQuery):
    window: HistoricalWindow
    options: PerformanceOptions = field(default_factory=PerformanceOptions)
    input_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        TargetPageQuery.__post_init__(self)
        _scope(self.window, self.input_snapshot_id)
        _options(self.options, PerformanceOptions)


@dataclass(frozen=True, slots=True, kw_only=True)
class PerformanceSummaryQuery:
    window: HistoricalWindow
    options: PerformanceOptions = field(default_factory=PerformanceOptions)
    input_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        _scope(self.window, self.input_snapshot_id)
        _options(self.options, PerformanceOptions)


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkComparisonQuery:
    window: HistoricalWindow
    benchmark_version_id: str
    options: ComparisonOptions = field(default_factory=ComparisonOptions)
    input_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        _scope(self.window, self.input_snapshot_id)
        source_id(self.benchmark_version_id, "benchmark_version_id")
        _options(self.options, ComparisonOptions)


@dataclass(frozen=True, slots=True, kw_only=True)
class AttributionQuery:
    window: HistoricalWindow
    options: AttributionOptions = field(default_factory=AttributionOptions)
    target_version_id: str | None = None
    benchmark_version_id: str | None = None
    grouping_policy: Literal["historical_assignment", "explicit_comparison"] | None = None
    top_n: int = 25
    input_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        _scope(self.window, self.input_snapshot_id)
        _options(self.options, AttributionOptions)
        source_integer(self.top_n, "top_n", 1, 50)
        if self.benchmark_version_id is not None:
            source_id(self.benchmark_version_id, "benchmark_version_id")
        object.__setattr__(
            self, "grouping_policy", _grouping(self.target_version_id, self.grouping_policy)
        )
        if self.options.grouping.value == "group" and self.target_version_id is None:
            fail_validation(
                "Group attribution requires a pinned target version.", field="target_version_id"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class DividendIntelligenceQuery:
    window: HistoricalWindow
    options: IncomeOptions = field(default_factory=IncomeOptions)
    target_version_id: str | None = None
    grouping_policy: Literal["historical_assignment", "explicit_comparison"] | None = None
    top_n: int = 25
    input_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        _scope(self.window, self.input_snapshot_id)
        _options(self.options, IncomeOptions)
        source_integer(self.top_n, "top_n", 1, 50)
        object.__setattr__(
            self, "grouping_policy", _grouping(self.target_version_id, self.grouping_policy)
        )
        if self.options.grouping.value == "group" and self.target_version_id is None:
            fail_validation(
                "Group income requires a pinned target version.", field="target_version_id"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class CashFlowIntelligenceQuery(TargetPageQuery):
    window: HistoricalWindow
    options: CashFlowOptions = field(default_factory=CashFlowOptions)
    input_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        TargetPageQuery.__post_init__(self)
        _scope(self.window, self.input_snapshot_id)
        _options(self.options, CashFlowOptions)


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalCaptureView:
    id: str
    input_digest: str
    captured_at: datetime
    input: HistoricalInput

    def __post_init__(self) -> None:
        source_id(self.id)
        historical_digest(self.input_digest, "input_digest")
        object.__setattr__(self, "captured_at", require_utc(self.captured_at))
        if not isinstance(self.input, HistoricalInput):
            fail_validation("A complete typed historical input is required.", field="input")


class HistoricalReplayState(StrEnum):
    REPRODUCIBLE = "reproducible"
    INPUTS_EXPIRED = "inputs_expired"
    LICENSE_RESTRICTED = "license_restricted"


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalAccessView:
    reproducibility: HistoricalReplayState = HistoricalReplayState.REPRODUCIBLE
    status_reference_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reproducibility, HistoricalReplayState):
            fail_validation("A typed reproducibility state is required.", field="reproducibility")
        if self.status_reference_at is not None:
            object.__setattr__(self, "status_reference_at", require_utc(self.status_reference_at))


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalRunContext(HistoricalResultContext):
    run_id: str
    input_snapshot_id: str
    content_digest: str
    calculated_at: datetime
    source_count: int
    source_omitted_count: int
    warning_count: int
    warning_omitted_count: int
    access: HistoricalAccessView = field(default_factory=HistoricalAccessView)

    def __post_init__(self) -> None:
        HistoricalResultContext.__post_init__(self)
        source_id(self.run_id, "run_id")
        source_id(self.input_snapshot_id, "input_snapshot_id")
        historical_digest(self.content_digest, "content_digest")
        object.__setattr__(self, "calculated_at", require_utc(self.calculated_at))
        for count, omitted, items in (
            (self.source_count, self.source_omitted_count, self.sources),
            (self.warning_count, self.warning_omitted_count, self.warnings),
        ):
            source_integer(count, "total_count", 0, 8192)
            source_integer(omitted, "omitted_count", 0, count)
            if len(items) > 64 or len(items) + omitted != count:
                fail_validation("Historical preview counts disagree.", field="context")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalEventPreview:
    items: tuple[HistoricalCashFlowPoint, ...]
    total_count: int
    omitted_count: int

    def __post_init__(self) -> None:
        source_integer(self.total_count, "total_count", 0, 10_000)
        source_integer(self.omitted_count, "omitted_count", 0, self.total_count)
        if (
            not isinstance(self.items, tuple)
            or len(self.items) > 16
            or len(self.items) + self.omitted_count != self.total_count
            or any(not isinstance(x, HistoricalCashFlowPoint) for x in self.items)
        ):
            fail_validation("Historical event preview exceeds its bound.", field="items")


@dataclass(frozen=True, slots=True, kw_only=True)
class CompositeBenchmarkHeaderView:
    id: str
    benchmark_version_id: str
    reporting_currency: CurrencyCode
    return_basis: PriceBasis
    calendar_id: str
    calendar_version: str
    rebalance_rule: BenchmarkRebalanceRule
    window: HistoricalWindow
    input_digest: str
    content_digest: str
    calculated_at: datetime
    method: HistoricalMethod
    inputs: tuple[CompositeBenchmarkComponentRef, ...]
    observation_count: int
    coverage: HistoricalCoverage
    access: HistoricalAccessView = field(default_factory=HistoricalAccessView)
    kind: Literal["composite"] = "composite"


@dataclass(frozen=True, slots=True, kw_only=True)
class PerformanceSeriesView:
    context: HistoricalRunContext
    summary: PerformanceMetrics
    points: Page[PerformancePoint]


@dataclass(frozen=True, slots=True, kw_only=True)
class PerformanceIntelligenceView:
    context: HistoricalRunContext
    summary: PerformanceMetrics
    series: tuple[PerformancePoint, ...]
    rolling_returns: tuple[HistoricalPeriodReturn, ...]
    calendar_returns: tuple[HistoricalPeriodReturn, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkComparisonView:
    context: HistoricalRunContext
    summary: BenchmarkComparisonMetrics
    series: tuple[BenchmarkComparisonPoint, ...]
    composite_snapshot: CompositeBenchmarkHeaderView | None

    rolling_returns: tuple[HistoricalBenchmarkPeriodReturn, ...] = ()
    calendar_returns: tuple[HistoricalBenchmarkPeriodReturn, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class AttributionSummaryView:
    context: HistoricalRunContext
    summary: AttributionMetrics
    rows: tuple[AttributionComponent, ...]
    eligible_count: int
    omitted_count: int
    effects: tuple[AttributionEffect, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class DividendIntelligenceView:
    context: HistoricalRunContext
    summary: IncomeMetrics
    native_currency_totals: tuple[CurrencyIncomeTotals, ...]
    reporting_totals: CurrencyIncomeTotals
    rows: tuple[IncomeComponent, ...]
    eligible_count: int
    omitted_count: int
    period_rows: tuple[IncomePeriod, ...]
    event_preview: HistoricalEventPreview


@dataclass(frozen=True, slots=True, kw_only=True)
class CashFlowIntelligenceView:
    context: HistoricalRunContext
    summary: CashFlowMetrics
    native_currency_totals: tuple[CurrencyCashFlowTotals, ...]
    reporting_totals: CurrencyCashFlowTotals
    period_rows: tuple[CashFlowPeriod, ...]
    events: Page[HistoricalCashFlowPoint]
    filtered_count: int


class HistoricalInputStore(Protocol):
    async def capture(
        self, principal: Principal, account_id: str, *, request: HistoricalSelectionRequest
    ) -> HistoricalCaptureView: ...
    async def load(self, principal: Principal, capture_id: str) -> HistoricalCaptureView: ...


class PerformanceIntelligenceService(Protocol):
    async def get_performance_series(
        self, principal: Principal, account_id: str, *, query: PerformanceSeriesQuery
    ) -> PerformanceSeriesView: ...
    async def get_performance_summary(
        self, principal: Principal, account_id: str, *, query: PerformanceSummaryQuery
    ) -> PerformanceIntelligenceView: ...
    async def get_benchmark_comparison(
        self, principal: Principal, account_id: str, *, query: BenchmarkComparisonQuery
    ) -> BenchmarkComparisonView: ...
    async def get_attribution_summary(
        self, principal: Principal, account_id: str, *, query: AttributionQuery
    ) -> AttributionSummaryView: ...
    async def get_dividend_intelligence(
        self, principal: Principal, account_id: str, *, query: DividendIntelligenceQuery
    ) -> DividendIntelligenceView: ...
    async def get_cash_flow_intelligence(
        self, principal: Principal, account_id: str, *, query: CashFlowIntelligenceQuery
    ) -> CashFlowIntelligenceView: ...
