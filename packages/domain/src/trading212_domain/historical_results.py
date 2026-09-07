"""Complete typed historical outputs; public projections preserve exact metric values."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import Decimal
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from .enums import QualityState
from .errors import fail_validation
from .historical import (
    HISTORICAL_SCHEMA_VERSION,
    MAX_HISTORICAL_EVENTS,
    MAX_HISTORICAL_POINTS,
    MAX_HISTORICAL_SOURCES,
    MAX_HISTORICAL_USES,
    AttributionMethod,
    CalendarPeriod,
    CalendarRef,
    HistoricalAvailability,
    HistoricalCashFlowKind,
    HistoricalCoverage,
    HistoricalFrequency,
    HistoricalGrouping,
    HistoricalIssue,
    HistoricalMoneyMetric,
    HistoricalRatioMetric,
    HistoricalReason,
    HistoricalSourceReference,
    HistoricalWindow,
    ReturnMethod,
    RollingWindow,
    historical_digest,
)
from .sources import (
    BenchmarkRebalanceRule,
    FxOperation,
    PriceBasis,
    source_id,
    source_integer,
    source_key,
)
from .values import CurrencyCode, exact_decimal, require_utc

_RESULT_TYPE_HINTS: dict[type[object], dict[str, Any]] = {}


def _result_type_hints(kind: type[object]) -> dict[str, Any]:
    """Cache fixed constructor metadata only; no input or result values are retained."""
    if kind in _RESULT_TYPE_HINTS:
        return _RESULT_TYPE_HINTS[kind]
    result = get_type_hints(kind)
    if len(_RESULT_TYPE_HINTS) < 128:
        _RESULT_TYPE_HINTS[kind] = result
    return result


@dataclass(frozen=True, slots=True, kw_only=True)
class _HistoricalResultRecord:
    """Validate runtime scalar/container shapes, including nested discriminated unions."""

    def __post_init__(self) -> None:
        hints = _result_type_hints(type(self))
        for field in fields(self):
            _check_shape(getattr(self, field.name), hints[field.name], field.name)


def _check_shape(value: object, kind: object, field: str) -> None:
    origin = get_origin(kind)
    if origin in (UnionType, Union):
        for choice in get_args(kind):
            if _shape_matches(value, choice):
                _check_shape(value, choice, field)
                return
        fail_validation("Historical result union is invalid.", field=field)
    if origin is Literal:
        if value not in get_args(kind):
            fail_validation("Historical result discriminator is invalid.", field=field)
        return
    if origin is tuple:
        if not isinstance(value, tuple) or len(value) > MAX_HISTORICAL_USES:
            fail_validation("Historical result collection exceeds its bound.", field=field)
        for item in value:
            _check_shape(item, get_args(kind)[0], field)
        return
    if kind is datetime:
        require_utc(value)  # type: ignore[arg-type]
    elif kind is date:
        if not isinstance(value, date) or isinstance(value, datetime):
            fail_validation("Historical result date is invalid.", field=field)
    elif kind is Decimal:
        if not isinstance(value, Decimal):
            fail_validation("Historical result decimal is invalid.", field=field)
        exact_decimal(value, field=field)
    elif kind in (str, int, bool, type(None)):
        if type(value) is not kind:
            fail_validation("Historical result scalar is invalid.", field=field)
        if type(value) is int and not 0 <= value <= MAX_HISTORICAL_USES:
            fail_validation("Historical result count exceeds its bound.", field=field)
        if isinstance(value, str) and len(value) > 2048:
            fail_validation("Historical result text exceeds its bound.", field=field)
    elif isinstance(kind, type) and not isinstance(value, kind):
        fail_validation("Historical result typed field is invalid.", field=field)


def _shape_matches(value: object, kind: object) -> bool:
    origin = get_origin(kind)
    if origin is Literal:
        return value in get_args(kind)
    if kind is type(None):
        return value is None
    return isinstance(kind, type) and isinstance(value, kind)


@dataclass(frozen=True, slots=True, kw_only=True)
class PerformanceOptions(_HistoricalResultRecord):
    method: ReturnMethod = ReturnMethod.TWR
    frequency: HistoricalFrequency = HistoricalFrequency.MONTHLY
    rolling_window: RollingWindow = RollingWindow.NONE
    calendar_period: CalendarPeriod = CalendarPeriod.NONE


@dataclass(frozen=True, slots=True, kw_only=True)
class ComparisonOptions(_HistoricalResultRecord):
    frequency: HistoricalFrequency = HistoricalFrequency.MONTHLY
    rolling_window: RollingWindow = RollingWindow.NONE
    calendar_period: CalendarPeriod = CalendarPeriod.NONE


@dataclass(frozen=True, slots=True, kw_only=True)
class IncomeOptions(_HistoricalResultRecord):
    grouping: HistoricalGrouping = HistoricalGrouping.HOLDING

    def __post_init__(self) -> None:
        _HistoricalResultRecord.__post_init__(self)
        if self.grouping not in (HistoricalGrouping.HOLDING, HistoricalGrouping.GROUP):
            fail_validation("Income grouping must be holding or group.", field="grouping")


@dataclass(frozen=True, slots=True, kw_only=True)
class AttributionOptions(_HistoricalResultRecord):
    grouping: HistoricalGrouping = HistoricalGrouping.HOLDING
    method: AttributionMethod = AttributionMethod.TWR


@dataclass(frozen=True, slots=True, kw_only=True)
class CashFlowOptions(_HistoricalResultRecord):
    frequency: HistoricalFrequency = HistoricalFrequency.MONTHLY
    kind: HistoricalCashFlowKind | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalMethod(_HistoricalResultRecord):
    name: str
    version: str

    def __post_init__(self) -> None:
        _HistoricalResultRecord.__post_init__(self)
        source_key(self.name, "name")
        source_key(self.version, "version")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalResultContext(_HistoricalResultRecord):
    account_id: str
    window: HistoricalWindow
    method: HistoricalMethod
    primitive_methods: tuple[HistoricalMethod, ...]
    input_digest: str
    source_policy_version: str | None
    accounting_policy_version: str
    coverage: HistoricalCoverage
    quality: QualityState
    availability: HistoricalAvailability
    reconstruction: Literal["point_in_time", "restated"]
    sources: tuple[HistoricalSourceReference, ...]
    warnings: tuple[HistoricalIssue, ...] = ()
    assumptions: tuple[
        Literal[
            "utc_accounting_boundaries",
            "previous_completed_session_close",
            "explicit_target_comparison",
            "price_only_benchmark",
            "act_365",
            "income_holdings_and_fx_may_change",
        ],
        ...,
    ] = ()
    schema_version: str = HISTORICAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _HistoricalResultRecord.__post_init__(self)
        source_id(self.account_id, "account_id")
        historical_digest(self.input_digest, "input_digest")
        source_key(self.accounting_policy_version, "accounting_policy_version")
        if self.source_policy_version is not None:
            source_key(self.source_policy_version, "source_policy_version")
        if (
            len(self.sources) > MAX_HISTORICAL_SOURCES
            or len(self.warnings) > MAX_HISTORICAL_SOURCES
            or len(self.primitive_methods) > 8
            or len(self.assumptions) > 16
        ):
            fail_validation("Historical context exceeds its bounds.", field="context")
        if self.schema_version != HISTORICAL_SCHEMA_VERSION:
            fail_validation("Historical output schema is unsupported.", field="schema_version")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalUseConsumer(_HistoricalResultRecord):
    kind: Literal["holding", "cash", "event", "group", "benchmark", "portfolio"]
    listing_id: str | None = None
    instrument_id: str | None = None
    event_revision_id: str | None = None
    group_key: str | None = None
    component_source_id: str | None = None

    def __post_init__(self) -> None:
        _HistoricalResultRecord.__post_init__(self)
        for name in ("listing_id", "instrument_id", "event_revision_id", "component_source_id"):
            if (value := getattr(self, name)) is not None:
                source_id(value, name)
        if self.group_key is not None:
            source_key(self.group_key, "group_key")
        required = {
            "holding": self.listing_id,
            "event": self.event_revision_id,
            "group": self.group_key,
            "benchmark": self.component_source_id,
        }
        if self.kind in required and required[self.kind] is None:
            fail_validation("Source-use consumer identity is incomplete.", field="consumer")


HistoricalUseRole = Literal[
    "holding_valuation",
    "cash_valuation",
    "event_conversion",
    "benchmark_component",
    "attribution_boundary",
    "opening",
    "classification",
    "action",
    "mapping",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalConversionLeg(_HistoricalResultRecord):
    conversion_key: str
    ordinal: int
    direction: Literal["direct", "inverse"]
    base: CurrencyCode
    quote: CurrencyCode

    def __post_init__(self) -> None:
        _HistoricalResultRecord.__post_init__(self)
        source_key(self.conversion_key, "conversion_key")
        source_integer(self.ordinal, "ordinal", 0, 1)


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalObservationUse(_HistoricalResultRecord):
    use_key: str
    role: HistoricalUseRole
    use_at: datetime
    knowledge_cutoff_at: datetime
    source_kind: Literal["price", "fx", "corporate_action", "provider_benchmark"]
    snapshot_id: str
    observation_index: int
    consumer: HistoricalUseConsumer
    conversion_leg: HistoricalConversionLeg | None = None
    kind: Literal["observation"] = "observation"

    def __post_init__(self) -> None:
        _HistoricalResultRecord.__post_init__(self)
        source_key(self.use_key, "use_key")
        source_id(self.snapshot_id, "snapshot_id")
        source_integer(self.observation_index, "observation_index", 0, 99_999)


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalEvidenceUse(_HistoricalResultRecord):
    use_key: str
    role: HistoricalUseRole
    use_at: datetime
    knowledge_cutoff_at: datetime
    reference_kind: Literal[
        "mapping",
        "classification",
        "event_revision",
        "opening",
        "calendar",
        "license",
        "action_coverage",
    ]
    reference_id: str
    consumer: HistoricalUseConsumer
    kind: Literal["evidence"] = "evidence"

    def __post_init__(self) -> None:
        _HistoricalResultRecord.__post_init__(self)
        source_key(self.use_key, "use_key")
        source_id(self.reference_id, "reference_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalExpectedSeries(_HistoricalResultRecord):
    series_id: str
    kind: Literal["series"] = "series"

    def __post_init__(self) -> None:
        _HistoricalResultRecord.__post_init__(self)
        source_id(self.series_id, "series_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalExpectedFx(_HistoricalResultRecord):
    base: CurrencyCode
    quote: CurrencyCode
    kind: Literal["fx_pair"] = "fx_pair"


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalMissingUse(_HistoricalResultRecord):
    use_key: str
    role: HistoricalUseRole
    use_at: datetime
    knowledge_cutoff_at: datetime
    expected: HistoricalExpectedSeries | HistoricalExpectedFx
    calendar_ref: CalendarRef
    expected_session: date | None
    reason: HistoricalReason
    candidate_snapshot_ids: tuple[str, ...]
    consumer: HistoricalUseConsumer
    kind: Literal["missing"] = "missing"

    def __post_init__(self) -> None:
        _HistoricalResultRecord.__post_init__(self)
        source_key(self.use_key, "use_key")
        if len(self.candidate_snapshot_ids) > 256:
            fail_validation(
                "Missing-source candidates exceed the bound.", field="candidate_snapshot_ids"
            )
        for value in self.candidate_snapshot_ids:
            source_id(value, "candidate_snapshot_ids")


HistoricalSourceUse = HistoricalObservationUse | HistoricalEvidenceUse | HistoricalMissingUse


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalConversionUse(_HistoricalResultRecord):
    conversion_key: str
    use_at: datetime
    base: CurrencyCode
    quote: CurrencyCode
    operation: FxOperation
    rate: Decimal
    leg_use_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        _HistoricalResultRecord.__post_init__(self)
        source_key(self.conversion_key, "conversion_key")
        if self.rate <= 0 or len(self.leg_use_keys) > 2:
            fail_validation("Conversion operation is invalid.", field="rate")
        for key in self.leg_use_keys:
            source_key(key, "leg_use_keys")


@dataclass(frozen=True, slots=True, kw_only=True)
class PerformanceMetrics(_HistoricalResultRecord):
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


@dataclass(frozen=True, slots=True, kw_only=True)
class PerformancePoint(_HistoricalResultRecord):
    ordinal: int
    date: date
    valuation_at: datetime
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
    flow_count: int
    flow_revision_ids: tuple[str, ...]
    flow_revision_omitted_count: int = 0

    def __post_init__(self) -> None:
        _HistoricalResultRecord.__post_init__(self)
        source_integer(self.ordinal, "ordinal", 0, MAX_HISTORICAL_POINTS - 1)
        source_integer(self.flow_count, "flow_count", 0, MAX_HISTORICAL_EVENTS)
        source_integer(
            self.flow_revision_omitted_count, "flow_revision_omitted_count", 0, self.flow_count
        )
        if len(self.flow_revision_ids) + self.flow_revision_omitted_count != self.flow_count:
            fail_validation("Flow references exceed count.", field="flow_revision_ids")
        for identifier in self.flow_revision_ids:
            source_id(identifier, "flow_revision_ids")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalPeriodReturn(_HistoricalResultRecord):
    period_start_at: datetime
    period_end_at: datetime
    kind: Literal[
        "rolling_30",
        "rolling_90",
        "rolling_365",
        "calendar_month",
        "calendar_quarter",
        "calendar_year",
    ]
    method: ReturnMethod
    value: HistoricalRatioMetric
    annualized_value: HistoricalRatioMetric


@dataclass(frozen=True, slots=True, kw_only=True)
class PerformanceCalculation(_HistoricalResultRecord):
    context: HistoricalResultContext
    options: PerformanceOptions
    summary: PerformanceMetrics
    points: tuple[PerformancePoint, ...]
    rolling_returns: tuple[HistoricalPeriodReturn, ...]
    calendar_returns: tuple[HistoricalPeriodReturn, ...]
    source_uses: tuple[HistoricalSourceUse, ...]
    conversions: tuple[HistoricalConversionUse, ...] = ()
    family: Literal["performance"] = "performance"

    def __post_init__(self) -> None:
        _HistoricalResultRecord.__post_init__(self)
        _calculation_bounds(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class CompositeBenchmarkPoint(_HistoricalResultRecord):
    ordinal: int
    session_date: date
    effective_at: datetime
    wealth: HistoricalRatioMetric
    interval_return: HistoricalRatioMetric


@dataclass(frozen=True, slots=True, kw_only=True)
class CompositeBenchmarkComponentRef(_HistoricalResultRecord):
    source_id: str
    weight: Decimal
    snapshot_ids: tuple[str, ...]
    license_version_ids: tuple[str, ...]
    calendar_ref: CalendarRef


@dataclass(frozen=True, slots=True, kw_only=True)
class CompositeBenchmarkSnapshot(_HistoricalResultRecord):
    benchmark_version_id: str
    reporting_currency: CurrencyCode
    return_basis: PriceBasis
    calendar_ref: CalendarRef
    rebalance_rule: BenchmarkRebalanceRule
    window: HistoricalWindow
    input_digest: str
    method: HistoricalMethod
    coverage: HistoricalCoverage
    inputs: tuple[CompositeBenchmarkComponentRef, ...]
    observations: tuple[CompositeBenchmarkPoint, ...]
    kind: Literal["composite"] = "composite"


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkComparisonMetrics(_HistoricalResultRecord):
    portfolio_return: HistoricalRatioMetric
    benchmark_return: HistoricalRatioMetric
    excess_return: HistoricalRatioMetric
    tracking_difference: HistoricalRatioMetric
    relative_wealth_return: HistoricalRatioMetric
    annualized_portfolio_return: HistoricalRatioMetric
    annualized_benchmark_return: HistoricalRatioMetric
    annualized_tracking_difference: HistoricalRatioMetric
    tracking_error: HistoricalRatioMetric
    paired_observation_count: int
    comparable_total_return_basis: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkComparisonPoint(_HistoricalResultRecord):
    ordinal: int
    date: date
    valuation_at: datetime
    portfolio_return: HistoricalRatioMetric
    benchmark_return: HistoricalRatioMetric
    excess_return: HistoricalRatioMetric
    portfolio_wealth: HistoricalRatioMetric
    benchmark_wealth: HistoricalRatioMetric
    relative_wealth: HistoricalRatioMetric


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalBenchmarkPeriodReturn(_HistoricalResultRecord):
    period_start_at: datetime
    period_end_at: datetime
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


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkCalculation(_HistoricalResultRecord):
    context: HistoricalResultContext
    options: ComparisonOptions
    summary: BenchmarkComparisonMetrics
    composite: CompositeBenchmarkSnapshot | None
    points: tuple[BenchmarkComparisonPoint, ...]
    source_uses: tuple[HistoricalSourceUse, ...]
    conversions: tuple[HistoricalConversionUse, ...] = ()
    rolling_returns: tuple[HistoricalBenchmarkPeriodReturn, ...] = ()
    calendar_returns: tuple[HistoricalBenchmarkPeriodReturn, ...] = ()
    family: Literal["benchmark"] = "benchmark"

    def __post_init__(self) -> None:
        _HistoricalResultRecord.__post_init__(self)
        _calculation_bounds(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrencyIncomeTotals(_HistoricalResultRecord):
    currency: CurrencyCode
    net: HistoricalMoneyMetric
    gross: HistoricalMoneyMetric
    withholding: HistoricalMoneyMetric
    positive_income: HistoricalMoneyMetric
    negative_corrections: HistoricalMoneyMetric
    event_count: int
    positive_event_count: int
    correction_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class IncomeMetrics(_HistoricalResultRecord):
    net_income: HistoricalMoneyMetric
    gross_income: HistoricalMoneyMetric
    withholding: HistoricalMoneyMetric
    positive_income: HistoricalMoneyMetric
    negative_corrections: HistoricalMoneyMetric
    mean_invested_value: HistoricalMoneyMetric
    income_yield: HistoricalRatioMetric
    previous_period_income: HistoricalMoneyMetric
    dividend_growth: HistoricalRatioMetric
    event_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class IncomeComponent(_HistoricalResultRecord):
    key: str
    label: str
    instrument_id: str | None
    group_key: str | None
    currency: CurrencyCode
    net: HistoricalMoneyMetric
    gross: HistoricalMoneyMetric
    withholding: HistoricalMoneyMetric
    positive_income: HistoricalMoneyMetric
    negative_corrections: HistoricalMoneyMetric
    concentration: HistoricalRatioMetric
    event_count: int
    unresolved: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class IncomePeriod(_HistoricalResultRecord):
    start_date: date
    end_date: date
    totals: tuple[CurrencyIncomeTotals, ...]
    reporting_net: HistoricalMoneyMetric


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalCashFlowPoint(_HistoricalResultRecord):
    ordinal: int
    event_revision_id: str
    economic_key: str
    economic_at: datetime
    kind: HistoricalCashFlowKind
    classification: Literal["external", "internal", "unresolved"]
    native_amount: HistoricalMoneyMetric
    reporting_amount: HistoricalMoneyMetric
    instrument_id: str | None
    listing_id: str | None
    group_key: str | None
    correction_of: str | None
    source_ref_ids: tuple[str, ...]
    source_ref_omitted_count: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class IncomeCalculation(_HistoricalResultRecord):
    context: HistoricalResultContext
    options: IncomeOptions
    summary: IncomeMetrics
    native_currency_totals: tuple[CurrencyIncomeTotals, ...]
    reporting_totals: CurrencyIncomeTotals
    instrument_rows: tuple[IncomeComponent, ...]
    group_rows: tuple[IncomeComponent, ...]
    period_rows: tuple[IncomePeriod, ...]
    events: tuple[HistoricalCashFlowPoint, ...]
    source_uses: tuple[HistoricalSourceUse, ...]
    conversions: tuple[HistoricalConversionUse, ...] = ()
    family: Literal["income"] = "income"

    def __post_init__(self) -> None:
        _HistoricalResultRecord.__post_init__(self)
        _calculation_bounds(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class AttributionEffect(_HistoricalResultRecord):
    kind: Literal["price", "income", "fees", "taxes", "fx", "interaction", "cash_fx"]
    amount: HistoricalMoneyMetric
    return_contribution: HistoricalRatioMetric


@dataclass(frozen=True, slots=True, kw_only=True)
class AttributionComponent(_HistoricalResultRecord):
    key: str
    label: str
    instrument_id: str | None
    listing_id: str | None
    group_key: str | None
    currency: CurrencyCode | None
    amount: HistoricalMoneyMetric
    return_contribution: HistoricalRatioMetric
    effects: tuple[AttributionEffect, ...]
    unresolved: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class AttributionMetrics(_HistoricalResultRecord):
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


@dataclass(frozen=True, slots=True, kw_only=True)
class AttributionCalculation(_HistoricalResultRecord):
    context: HistoricalResultContext
    options: AttributionOptions
    summary: AttributionMetrics
    rows: tuple[AttributionComponent, ...]
    effects: tuple[AttributionEffect, ...]
    source_uses: tuple[HistoricalSourceUse, ...]
    conversions: tuple[HistoricalConversionUse, ...] = ()
    family: Literal["attribution"] = "attribution"

    def __post_init__(self) -> None:
        _HistoricalResultRecord.__post_init__(self)
        _calculation_bounds(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrencyCashFlowTotals(_HistoricalResultRecord):
    currency: CurrencyCode
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
    external_count: int
    internal_count: int
    unresolved_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CashFlowMetrics(_HistoricalResultRecord):
    event_count: int
    filtered_count: int
    external_count: int
    internal_count: int
    unresolved_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CashFlowPeriod(_HistoricalResultRecord):
    start_date: date
    end_date: date
    native_totals: tuple[CurrencyCashFlowTotals, ...]
    reporting_totals: CurrencyCashFlowTotals


@dataclass(frozen=True, slots=True, kw_only=True)
class CashFlowCalculation(_HistoricalResultRecord):
    context: HistoricalResultContext
    options: CashFlowOptions
    summary: CashFlowMetrics
    native_currency_totals: tuple[CurrencyCashFlowTotals, ...]
    reporting_totals: CurrencyCashFlowTotals
    period_rows: tuple[CashFlowPeriod, ...]
    events: tuple[HistoricalCashFlowPoint, ...]
    source_uses: tuple[HistoricalSourceUse, ...]
    conversions: tuple[HistoricalConversionUse, ...] = ()
    family: Literal["cash_flows"] = "cash_flows"

    def __post_init__(self) -> None:
        _HistoricalResultRecord.__post_init__(self)
        _calculation_bounds(self)


HistoricalCalculation = (
    PerformanceCalculation
    | BenchmarkCalculation
    | IncomeCalculation
    | AttributionCalculation
    | CashFlowCalculation
)


def _calculation_bounds(value: HistoricalCalculation) -> None:
    if len(value.source_uses) > MAX_HISTORICAL_USES or len(value.conversions) > MAX_HISTORICAL_USES:
        fail_validation("Historical selected-use capacity exceeded.", field="source_uses")
    if len({x.use_key for x in value.source_uses}) != len(value.source_uses):
        fail_validation("Historical source-use keys must be unique.", field="source_uses")
    if (
        isinstance(value, (PerformanceCalculation, BenchmarkCalculation))
        and len(value.points) > MAX_HISTORICAL_POINTS
    ):
        fail_validation("Historical point capacity exceeded.", field="points")
    if (
        isinstance(value, (IncomeCalculation, CashFlowCalculation))
        and len(value.events) > MAX_HISTORICAL_EVENTS
    ):
        fail_validation("Historical event capacity exceeded.", field="events")
