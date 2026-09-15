"""Bounded saved projection views, distinct from private canonical path storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from trading212_domain.enums import QualityState
from trading212_domain.errors import fail_validation
from trading212_domain.projection import ProjectionAssumptions, ProjectionVariant
from trading212_domain.values import CurrencyCode, Money, require_bounded_text

from .projection_capture import ProjectionGoalVersionContent, ProjectionRunSelection
from .risk import PremiumJobState

PROJECTION_PUBLIC_VIEW_VERSION: Literal["projection_points_v1"] = "projection_points_v1"
PROJECTION_PUBLIC_PAGE_BYTES = 1024 * 1024
PROJECTION_PUBLIC_RESPONSE_BYTES = 2 * 1024 * 1024

type ProjectionFailure = Literal[
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


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionVersionMetadata:
    """Immutable labels, bound by command identity but outside numerical content digests."""

    name: str
    description: str = ""

    def __post_init__(self) -> None:
        require_bounded_text(self.name, field="name", maximum=120)
        if not self.name.strip():
            fail_validation("A definition name is required.", field="name")
        if (
            not isinstance(self.description, str)
            or len(self.description) > 1024
            or "\0" in self.description
        ):
            fail_validation("Description exceeds its supported bounds.", field="description")


@dataclass(frozen=True, slots=True, kw_only=True)
class AssumptionSetView:
    id: UUID
    account_id: UUID
    name: str
    revision: int
    current_version_id: UUID
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class AssumptionVersionView:
    id: UUID
    account_id: UUID
    set_id: UUID
    version_number: int
    predecessor_id: UUID | None
    metadata: ProjectionVersionMetadata
    content: ProjectionAssumptions
    content_digest: str
    created_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class GoalView:
    id: UUID
    account_id: UUID
    name: str
    revision: int
    current_version_id: UUID
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class GoalVersionView:
    id: UUID
    account_id: UUID
    goal_id: UUID
    version_number: int
    predecessor_id: UUID | None
    metadata: ProjectionVersionMetadata
    content: ProjectionGoalVersionContent
    content_digest: str
    created_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionPreview[Item]:
    items: tuple[Item, ...]
    omitted_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionEvidenceView:
    role: Literal["observed_snapshot", "calibration"]
    subject_id: UUID
    content_digest: str
    quality: QualityState
    source_reference_ids: ProjectionPreview[UUID]


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionQuantilesView:
    probabilities: tuple[Decimal, ...]
    values: tuple[Money, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionAmountSummaryView:
    mean: Money
    quantiles: ProjectionQuantilesView


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionCashFlowSummaryView:
    """Every statistic derives from the complete saved terminal Q18 path values."""

    contributions: ProjectionAmountSummaryView
    withdrawals_requested: ProjectionAmountSummaryView
    withdrawals_funded: ProjectionAmountSummaryView
    unpaid_withdrawals: ProjectionAmountSummaryView
    investment_effect: ProjectionAmountSummaryView
    fees: ProjectionAmountSummaryView
    tax_drag: ProjectionAmountSummaryView
    funding_failed_paths: int
    unpaid_positive_below_quantum_paths: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionDistributionView:
    month: int
    on: date
    nominal_mean: Money
    real_mean: Money
    nominal: ProjectionQuantilesView
    real: ProjectionQuantilesView
    funding_failed_paths: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionHistogramBinView:
    lower: Money
    upper: Money
    upper_inclusive: bool
    count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionHistogramView:
    observed_minimum: Money
    observed_maximum: Money
    bins: tuple[ProjectionHistogramBinView, ...]
    boundary_rule: Literal["q18_enclosing_ceiling_v1"] = "q18_enclosing_ceiling_v1"


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionGoalEstimateView:
    goal_version_id: UUID
    basis: Literal["nominal", "real"]
    target: Money
    paths: int
    successes: int
    probability: Decimal
    interval_low: Decimal
    interval_high: Decimal
    probability_objective: Decimal
    objective_met: bool
    mean_shortfall: Money
    shortfalls: ProjectionQuantilesView
    funding_failed_paths: int
    method: Literal["goal_analysis_v1"] = "goal_analysis_v1"
    interval_method: Literal["wilson_95_v1"] = "wilson_95_v1"
    automatic_goal_acceptance: Literal[False] = False


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionVariantSummaryView:
    variant: ProjectionVariant
    distributions: tuple[ProjectionDistributionView, ...]
    nominal_histogram: ProjectionHistogramView
    real_histogram: ProjectionHistogramView
    cash_flows: ProjectionCashFlowSummaryView
    goal: ProjectionGoalEstimateView | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionAssetValueView:
    key: str
    value: Money


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionPointView:
    """Complete point financials; rounding and funding evidence is never omitted."""

    month: int
    nominal: Money
    real: Money
    assets: tuple[ProjectionAssetValueView, ...]
    contributions: Money
    withdrawals_requested: Money
    withdrawals_funded: Money
    unpaid_withdrawals: Money
    investment_effect: Money
    fees: Money
    tax_drag: Money
    wealth_residual: Money
    allocation_residual: Money
    withdrawal_residual: Money
    funding_failed: bool
    unpaid_positive_below_quantum: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionPointRow:
    ordinal: int
    variant: ProjectionVariant
    path_index: int
    point_index: int
    path_point_count: int
    first_unpaid_month: int | None
    on: date
    point: ProjectionPointView


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionPointPage:
    items: tuple[ProjectionPointRow, ...]
    point_limit: int
    next_cursor: str | None
    total: int
    start_ordinal: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionResultContextView:
    account_id: UUID
    run_id: UUID
    result_id: UUID
    capture_digest: str
    numerical_input_digest: str
    saved_result_digest: str
    assumption_version_digest: str
    goal_version_digest: str | None
    selection: ProjectionRunSelection
    assumptions: ProjectionAssumptions
    anchor_date: date
    terminal_date: date
    snapshot_valuation_at: datetime | None
    source_cutoff_at: datetime | None
    calculated_at: datetime
    reporting_currency: CurrencyCode
    quality: QualityState
    source_evidence: ProjectionPreview[ProjectionEvidenceView]
    warnings: ProjectionPreview[str]
    numerical_zero_pivots: tuple[int, ...]
    method: Literal["projection_v1"] = "projection_v1"
    method_version: Literal["1.0.0"] = "1.0.0"
    schema_version: Literal["1.0.0"] = "1.0.0"
    numeric_profile: Literal["premium_decimal96_q18_v1"] = "premium_decimal96_q18_v1"
    sampler: Literal["sha256_counter_polar_v1"] = "sha256_counter_polar_v1"
    calendar_rule: Literal["calendar_anniversary_clamped_v1"] = "calendar_anniversary_clamped_v1"
    interpretation: Literal["model_estimate_not_guaranteed_forecast"] = (
        "model_estimate_not_guaranteed_forecast"
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionResultPage:
    context: ProjectionResultContextView
    variants: tuple[ProjectionVariantSummaryView, ...]
    points: ProjectionPointPage
    content_digest: str
    view_version: Literal["projection_points_v1"] = "projection_points_v1"


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionRunView:
    id: UUID
    account_id: UUID
    assumption_version_id: UUID
    goal_version_id: UUID | None
    job_id: UUID
    capture_digest: str
    numerical_input_digest: str
    state: PremiumJobState
    result_availability: Literal["pending", "available", "not_loaded", "expired", "unavailable"]
    created_at: datetime
    expires_at: datetime
    completed_at: datetime | None
    failure_code: ProjectionFailure | None
    result: ProjectionResultPage | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionOperationalRunView(ProjectionRunView):
    result: None = None

    def __post_init__(self) -> None:
        if self.result is not None or self.result_availability == "available":
            fail_validation(
                "Operational projection responses cannot include financial results.", field="result"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class GoalVariantAnalysisView:
    variant: ProjectionVariant
    terminal: ProjectionQuantilesView
    estimate: ProjectionGoalEstimateView


@dataclass(frozen=True, slots=True, kw_only=True)
class GoalAnalysisView:
    account_id: UUID
    run_id: UUID
    goal_version_id: UUID | None
    state: PremiumJobState
    result_availability: Literal["pending", "available", "not_loaded", "expired", "unavailable"]
    availability: Literal["available", "unavailable"]
    reason: (
        Literal["no_goal_pinned", "run_pending", "run_failed", "run_expired", "run_cancelled"]
        | None
    )
    context: ProjectionResultContextView | None
    variants: tuple[GoalVariantAnalysisView, ...]
    content_digest: str
    view_version: Literal["goal_analysis_compact_v1"] = "goal_analysis_compact_v1"
