"""Separate ephemeral company views; never fields of persisted DriftCalculation."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from .planning import DriftRow
from .xray import XrayMoneyMetric, XrayRatioMetric
from .xray_result import XrayDimensionSummary

COMPANY_PROJECTION_VERSION: Literal["planning_company_actual_v1"] = "planning_company_actual_v1"

CompanySelectionReason = Literal[
    "available",
    "company_basis_not_selected",
    "company_scope_not_applicable",
    "company_identity_unavailable",
    "company_identity_conflict",
    "company_bucket_unavailable",
    "company_metric_unavailable",
]


@dataclass(frozen=True, slots=True)
class PlanningCompanyWeight:
    row_key: str
    entity_id: UUID | None
    metric: XrayRatioMetric | None
    reason: CompanySelectionReason
    identity_decision_ids: tuple[UUID, ...] = ()
    identity_count: int = 0
    identity_omitted_count: int = 0
    path_keys: tuple[str, ...] = ()
    path_count: int = 0
    path_omitted_count: int = 0
    proof_digest: str | None = None
    semantics: Literal["full_portfolio_company_non_additive"] = (
        "full_portfolio_company_non_additive"
    )
    drift_reason: Literal["effective_exposure_target_unavailable"] = (
        "effective_exposure_target_unavailable"
    )


@dataclass(frozen=True, slots=True)
class PlanningDriftRowView(DriftRow):
    company: PlanningCompanyWeight


@dataclass(frozen=True, slots=True)
class PlanningCompanyBinding:
    planning_run_id: UUID
    planning_input_digest: str
    planning_content_digest: str
    valuation_digest: str
    xray_run_id: UUID
    xray_input_id: UUID
    xray_input_digest: str
    xray_content_digest: str
    account_id: UUID
    snapshot_id: UUID
    reporting_currency: str
    valuation_at: datetime
    source_cutoff_at: datetime
    policy_id: UUID
    policy_digest: str
    total: XrayMoneyMetric
    company_partition: XrayDimensionSummary
    version: Literal["planning_company_actual_v1"] = COMPANY_PROJECTION_VERSION
    method: Literal["xray_v1"] = "xray_v1"
    method_version: Literal["1.1.0"] = "1.1.0"
    numeric_policy: Literal["xray_decimal256_exact_q18_v1"] = "xray_decimal256_exact_q18_v1"


@dataclass(frozen=True, slots=True)
class PlanningCompanyProjection:
    binding: PlanningCompanyBinding | None
    weights: tuple[PlanningCompanyWeight, ...]
    content_digest: str | None


@dataclass(slots=True)
class PlanningCompanyBasisError(Exception):
    reason: Literal["company_pin_mismatch", "valuation_basis_mismatch", "company_result_invalid"]

    def __str__(self) -> str:
        return self.reason


def company_row_view(row: DriftRow, company: PlanningCompanyWeight) -> PlanningDriftRowView:
    """Create an ephemeral row; the original and all direct drift fields stay intact."""
    values: dict[str, Any] = {field.name: getattr(row, field.name) for field in fields(DriftRow)}
    if company.reason in {"company_basis_not_selected", "company_scope_not_applicable"}:
        # The optional company view must preserve legacy unpinned drift semantics.
        # Its separate reason still states why no company metric applies.
        return PlanningDriftRowView(**values, company=company)
    metric = company.metric
    values["effective_weight"] = None if metric is None else metric.value
    values["effective_weight_reason"] = (
        company.reason
        if metric is None
        else metric.reason.value
        if metric.reason is not None
        else "positive_below_quantum"
        if metric.positive_below_quantum
        else "lower_bound"
        if metric.bound.value == "lower_bound"
        else company.reason
    )
    return PlanningDriftRowView(**values, company=company)
