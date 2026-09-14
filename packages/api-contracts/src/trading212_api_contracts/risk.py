"""Closed risk wire contracts; all authoritative financial numbers are decimal strings."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, StringConstraints, model_validator

from . import historical as h
from .sources import CalendarDate, SourceKey, SourceQuality
from .targets import AwareInstant, CurrencyString, Cursor, DecimalString, Digest, UUIDString

RiskReason = Literal[
    "insufficient_history",
    "insufficient_tail",
    "missing_interval",
    "non_observed_interval",
    "nonpositive_gross_return",
    "benchmark_unavailable",
    "zero_denominator",
    "incomplete_universe",
    "unsupported_parametric",
    "incompatible_basis",
]
RiskFailure = Literal[
    "publication_unavailable",
    "consumer_unavailable",
    "lease_expired",
    "invalid_message",
    "input_unavailable",
    "input_changed",
    "access_denied",
    "calculation_failed",
    "storage_unavailable",
    "attempts_exhausted",
    "limit_exceeded",
    "source_restricted",
]
RiskCount = Annotated[StrictInt, Field(ge=0, le=3660)]
RiskName = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=120, pattern=r"^[^\x00]*$")
]
RiskDescription = Annotated[
    str, StringConstraints(strict=True, max_length=1024, pattern=r"^[^\x00]*$")
]


class RiskSchema(h.HistoricalSchema):
    pass


class RiskDefinitionContent(RiskSchema):
    name: RiskName
    description: RiskDescription = ""
    calendar_id: SourceKey
    calendar_version: SourceKey
    frequency: Literal["daily", "monthly"] = "daily"
    return_kind: Literal["simple", "log"] = "simple"
    annual_risk_free: DecimalString = "0"
    annual_minimum_acceptable_return: DecimalString = "0"
    rolling_window: Annotated[StrictInt, Field(ge=20, le=252)] = 20
    confidence: DecimalString = "0.95"
    horizon: Annotated[StrictInt, Field(ge=1, le=20)] = 1
    regularization: Literal["none", "diagonal_shrinkage"] = "none"
    shrinkage: DecimalString = "0"
    method_version: Literal["1.0.0"] = "1.0.0"

    @model_validator(mode="after")
    def supported_assumptions(self) -> Self:
        if not self.name.strip():
            raise ValueError("A risk definition name is required.")
        if any(
            not Decimal(-1) < Decimal(value) <= 1
            for value in (self.annual_risk_free, self.annual_minimum_acceptable_return)
        ):
            raise ValueError("Annual risk assumptions exceed their bounds.")
        if Decimal(self.confidence) not in (Decimal(".90"), Decimal(".95"), Decimal(".99")):
            raise ValueError("Unsupported tail confidence.")
        if not 0 <= Decimal(self.shrinkage) <= 1 or (
            self.regularization == "none" and Decimal(self.shrinkage) != 0
        ):
            raise ValueError("Shrinkage must be explicit and bounded.")
        if self.frequency == "monthly" and (self.rolling_window > 120 or self.horizon > 12):
            raise ValueError("Monthly estimation bounds exceeded.")
        return self


class CreateRiskDefinitionRequest(RiskSchema):
    content: RiskDefinitionContent


class CreateRiskVersionRequest(RiskSchema):
    content: RiskDefinitionContent


class RiskWindow(RiskSchema):
    start_date: CalendarDate
    end_date: CalendarDate
    source_cutoff_at: AwareInstant
    reporting_currency: CurrencyString
    coverage_policy: h.HistoricalCoveragePolicy = "require_complete"
    knowledge_policy: h.HistoricalKnowledgePolicy = "as_of_cutoff"

    @model_validator(mode="after")
    def window_bound(self) -> Self:
        if not 0 <= (self.end_date - self.start_date).days <= 3660:
            raise ValueError("The historical period exceeds its bounds.")
        return self


class RiskAssetSource(RiskSchema):
    instrument_id: UUIDString
    series_id: UUIDString


class CreateRiskRunRequest(RiskSchema):
    definition_version_id: UUIDString
    portfolio_snapshot_id: UUIDString
    historical_input_snapshot_id: UUIDString
    window: RiskWindow
    assets: Annotated[list[RiskAssetSource], Field(max_length=32)] = Field(default_factory=list)
    benchmark_version_id: UUIDString | None = None
    xray_run_id: UUIDString | None = None

    @model_validator(mode="after")
    def unique_mappings(self) -> Self:
        if len({x.instrument_id for x in self.assets}) != len(self.assets) or len(
            {x.series_id for x in self.assets}
        ) != len(self.assets):
            raise ValueError("Risk asset mappings must be unique.")
        return self


class CancelRiskRunRequest(RiskSchema):
    pass


class RiskPageQuery(RiskSchema):
    limit: h.HistoricalPageLimit = 25
    cursor: Cursor | None = None


class RiskDefinitionResponse(RiskSchema):
    id: UUIDString
    account_id: UUIDString
    name: RiskName
    revision: Annotated[StrictInt, Field(ge=1, le=512)]
    archived: StrictBool
    current_version_id: UUIDString
    created_at: AwareInstant
    updated_at: AwareInstant


class RiskVersionResponse(RiskSchema):
    id: UUIDString
    account_id: UUIDString
    definition_id: UUIDString
    version_number: Annotated[StrictInt, Field(ge=1, le=512)]
    predecessor_id: UUIDString | None
    content: RiskDefinitionContent
    content_digest: Digest
    created_at: AwareInstant


class RiskPageResponse[T](RiskSchema):
    items: Annotated[list[T], Field(max_length=100)]
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: Annotated[StrictInt, Field(ge=0, le=250000)]


class RiskAvailableMetric(RiskSchema):
    value: DecimalString
    reason: None


class RiskUnavailableMetric(RiskSchema):
    value: None
    reason: RiskReason


RiskMetric = RiskAvailableMetric | RiskUnavailableMetric


class RiskRollingPoint(RiskSchema):
    end_at: AwareInstant
    volatility: RiskMetric
    observations: Annotated[StrictInt, Field(ge=0, le=252)]


class RiskSeriesStatistics(RiskSchema):
    requested_observations: RiskCount
    used_observations: RiskCount
    omitted_observations: RiskCount
    outlier_observations: RiskCount
    mean_periodic_return: RiskMetric
    volatility_periodic: RiskMetric
    volatility_annualized: RiskMetric
    downside_annualized: RiskMetric
    beta: RiskMetric
    alpha_annualized: RiskMetric
    benchmark_pairs: RiskCount
    rolling: Annotated[list[RiskRollingPoint], Field(max_length=3660)]


class RiskMatrix(RiskSchema):
    keys: Annotated[list[UUIDString], Field(max_length=32)]
    requested_intervals: RiskCount
    used_intervals: RiskCount
    omitted_intervals: RiskCount
    covariance_periodic: Annotated[
        list[Annotated[list[RiskMetric], Field(max_length=32)]], Field(max_length=32)
    ]
    regularized_covariance_periodic: Annotated[
        list[Annotated[list[RiskMetric], Field(max_length=32)]], Field(max_length=32)
    ]
    correlation: Annotated[
        list[Annotated[list[RiskMetric], Field(max_length=32)]], Field(max_length=32)
    ]
    numerical_zero_pivots: Annotated[
        list[Annotated[StrictInt, Field(ge=0, le=31)]], Field(max_length=32)
    ]


class RiskTail(RiskSchema):
    method: Literal["historical", "parametric_lognormal"]
    confidence: DecimalString
    horizon: Annotated[StrictInt, Field(ge=1, le=20)]
    observations: RiskCount
    tail_mass: DecimalString | None
    value_at_risk: RiskMetric
    expected_shortfall: RiskMetric
    loss_sign: Literal["positive_is_loss"]
    quantile: Literal["nearest_rank_fractional_tail", "gaussian_log_wealth"]
    horizon_policy: Literal["overlapping_compounded", "iid_log_returns"]


class RiskComponent(RiskSchema):
    instrument_id: UUIDString
    weight: RiskMetric
    marginal_annualized: RiskMetric
    component_annualized: RiskMetric


class RiskModel(RiskSchema):
    coverage: RiskMetric
    complete_universe: StrictBool
    volatility_annualized: RiskMetric
    diversification_ratio: RiskMetric
    components: Annotated[list[RiskComponent], Field(max_length=32)]
    component_sum: RiskMetric
    component_display_residual: RiskMetric
    weight_display_residual: RiskMetric


class RiskConcentration(RiskSchema):
    hhi: RiskMetric
    effective_holdings: RiskMetric
    company_known_weight: RiskMetric
    cash_weight: RiskMetric
    unresolved_weight: RiskMetric
    lower_bound: StrictBool
    quality: SourceQuality
    basis: Literal["economic_companies_absolute_portfolio"]


class RiskHistoricalContext(RiskSchema):
    account_id: UUIDString
    window: h.HistoricalWindow
    method: h.HistoricalMethodMetadata
    primitive_methods: Annotated[list[h.HistoricalMethodMetadata], Field(max_length=8)]
    input_digest: Digest
    source_policy_version: SourceKey | None
    accounting_policy_version: SourceKey
    coverage: h.HistoricalCoverage
    quality: SourceQuality
    availability: Literal["available", "partial", "unavailable", "failed"]
    reconstruction: Literal["point_in_time", "restated"]
    sources: Annotated[list[h.HistoricalSourceReference], Field(max_length=64)]
    warnings: Annotated[list[h.HistoricalIssue], Field(max_length=64)]
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


class RiskResultResponse(RiskSchema):
    definition: RiskDefinitionContent
    historical_context: RiskHistoricalContext
    omitted_sources: Annotated[StrictInt, Field(ge=0, le=8192)]
    omitted_warnings: Annotated[StrictInt, Field(ge=0, le=8192)]
    observed: RiskSeriesStatistics
    maximum_drawdown: h.HistoricalRatioMetric
    matrix: RiskMatrix
    historical_tail: RiskTail
    parametric_tail: RiskTail
    modeled: RiskModel
    concentration: RiskConcentration
    xray_result_digest: Digest | None
    modeled_valuation_at: AwareInstant | None
    annualization_factor: Literal[12, 252]
    covariance_degrees_of_freedom: Literal[1]
    method_version: Literal["1.0.0"]
    schema_version: Literal["1.0.0"]
    numerical_profile: Literal["premium_decimal96_q18_v1"]
    content_digest: Digest


class RiskRunResponse(RiskSchema):
    id: UUIDString
    account_id: UUIDString
    definition_version_id: UUIDString
    portfolio_snapshot_id: UUIDString
    historical_input_snapshot_id: UUIDString
    xray_run_id: UUIDString | None
    job_id: UUIDString
    state: Literal["queued", "running", "succeeded", "failed", "expired", "cancelled"]
    failure_code: RiskFailure | None
    created_at: AwareInstant
    expires_at: AwareInstant
    completed_at: AwareInstant | None
    input_digest: Digest
    result: RiskResultResponse | None
    result_availability: Literal["pending", "available", "not_loaded", "expired", "unavailable"]


class RiskMatrixResponse(RiskSchema):
    run_id: UUIDString
    account_id: UUIDString
    definition_version_id: UUIDString
    definition: RiskDefinitionContent
    historical_context: RiskHistoricalContext
    omitted_sources: Annotated[StrictInt, Field(ge=0, le=8192)]
    omitted_warnings: Annotated[StrictInt, Field(ge=0, le=8192)]
    content_digest: Digest
    numerical_profile: Literal["premium_decimal96_q18_v1"]
    matrix: RiskMatrix
