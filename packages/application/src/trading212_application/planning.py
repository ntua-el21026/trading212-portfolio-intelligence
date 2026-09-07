"""Bounded authorized application contracts for drift and durable planning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from trading212_domain.planning import (
    ContributionPlanLine,
    ContributionPlanResultSummary,
    DriftBasis,
    DriftRow,
    DriftTotals,
    PlanningContext,
    PlanningNodeIdentity,
    PlanningOptions,
    PlanOutcome,
    planning_id,
)
from trading212_domain.values import CurrencyCode
from trading212_security.principals import Principal

from .targets import TargetPageQuery, target_etag
from .views import Page


class PlanJobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class PlanningServiceErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    IMMUTABLE_VERSION = "IMMUTABLE_VERSION"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    RESULT_TOO_LARGE = "RESULT_TOO_LARGE"
    PLANNING_UNAVAILABLE = "PLANNING_UNAVAILABLE"


@dataclass(slots=True)
class PlanningServiceError(Exception):
    code: PlanningServiceErrorCode
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True, kw_only=True)
class ActualVsTargetQuery(TargetPageQuery):
    snapshot_id: str
    virtual_portfolio_id: str
    target_version_id: str
    reporting_currency: CurrencyCode
    node_id: str | None = None

    def __post_init__(self) -> None:
        TargetPageQuery.__post_init__(self)
        _pins(
            self.snapshot_id,
            self.virtual_portfolio_id,
            self.target_version_id,
            self.reporting_currency,
        )
        if self.node_id is not None:
            planning_id(self.node_id, "node_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class DriftAnalysisQuery:
    snapshot_id: str
    virtual_portfolio_id: str
    target_version_id: str
    reporting_currency: CurrencyCode
    basis: DriftBasis = DriftBasis.DIRECT
    top_n: int = 25

    def __post_init__(self) -> None:
        _pins(
            self.snapshot_id,
            self.virtual_portfolio_id,
            self.target_version_id,
            self.reporting_currency,
        )
        if not isinstance(self.basis, DriftBasis):
            raise ValueError("Invalid drift basis.")
        if (
            isinstance(self.top_n, bool)
            or not isinstance(self.top_n, int)
            or not 1 <= self.top_n <= 50
        ):
            raise ValueError("top_n must be an integer from one through fifty.")


def _pins(snapshot_id: str, portfolio_id: str, target_id: str, currency: CurrencyCode) -> None:
    planning_id(snapshot_id, "snapshot_id")
    planning_id(portfolio_id, "virtual_portfolio_id")
    planning_id(target_id, "target_version_id")
    if not isinstance(currency, CurrencyCode):
        raise ValueError("A typed reporting currency is required.")


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateContributionPlanCommand:
    account_id: str
    virtual_portfolio_id: str
    target_version_id: str
    snapshot_id: str
    options: PlanningOptions

    def __post_init__(self) -> None:
        planning_id(self.account_id, "account_id")
        if not isinstance(self.options, PlanningOptions):
            raise ValueError("Typed planning options are required.")
        _pins(
            self.snapshot_id,
            self.virtual_portfolio_id,
            self.target_version_id,
            self.options.contribution.currency,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ContributionPlanQuery(TargetPageQuery):
    account_id: str
    virtual_portfolio_id: str | None = None
    state: PlanJobState | None = None
    outcome: PlanOutcome | None = None
    plan_id: str | None = None
    include_revisions: bool = False

    def __post_init__(self) -> None:
        TargetPageQuery.__post_init__(self)
        planning_id(self.account_id, "account_id")
        if (
            not isinstance(self.include_revisions, bool)
            or (self.plan_id is not None) != self.include_revisions
        ):
            raise ValueError("A plan and explicit revision-history mode are required together.")
        if self.plan_id is not None:
            planning_id(self.plan_id, "plan_id")
        if self.virtual_portfolio_id is not None:
            planning_id(self.virtual_portfolio_id, "virtual_portfolio_id")
        if self.state is not None and not isinstance(self.state, PlanJobState):
            raise ValueError("Invalid plan state filter.")
        if self.outcome is not None and not isinstance(self.outcome, PlanOutcome):
            raise ValueError("Invalid plan outcome filter.")


@dataclass(frozen=True, slots=True, kw_only=True)
class ContributionPlanDetailQuery(TargetPageQuery):
    account_id: str | None = None
    plan_revision_id: str | None = None

    def __post_init__(self) -> None:
        TargetPageQuery.__post_init__(self)
        if self.account_id is not None:
            planning_id(self.account_id, "account_id")
        if self.plan_revision_id is not None:
            planning_id(self.plan_revision_id, "plan_revision_id")


@dataclass(frozen=True, slots=True)
class ActualVsTargetResult:
    context: PlanningContext
    calculated_at: datetime
    totals: DriftTotals
    rows: Page[DriftRow]
    content_digest: str
    target_identities: tuple[PlanningNodeIdentity, ...]
    node_id: str | None = None


@dataclass(frozen=True, slots=True)
class DriftAnalysisResult:
    context: PlanningContext
    calculated_at: datetime
    totals: DriftTotals
    groups: tuple[DriftRow, ...]
    leaves: tuple[DriftRow, ...]
    cash_and_unclassified: tuple[DriftRow, ...]
    basis: DriftBasis
    top_n: int
    eligible_rows: int
    omitted_rows: int
    content_digest: str


@dataclass(frozen=True, slots=True)
class ContributionPlanJobView:
    plan_id: str
    account_id: str
    virtual_portfolio_id: str
    target_version_id: str
    snapshot_id: str
    request_id: str
    request_revision: int
    job_id: str
    state: PlanJobState
    outcome: PlanOutcome | None
    requested_at: datetime
    input_digest: str
    plan_revision_id: str | None = None
    failure_code: str | None = None

    @property
    def etag(self) -> str:
        return target_etag(self.plan_id, self.request_revision)


@dataclass(frozen=True, slots=True)
class ContributionPlanSummaryView:
    job: ContributionPlanJobView
    virtual_portfolio_id: str
    target_version_id: str
    snapshot_id: str
    options: PlanningOptions


@dataclass(frozen=True, slots=True)
class ContributionPlanDetailView:
    job: ContributionPlanJobView
    request: CreateContributionPlanCommand
    result: ContributionPlanResultSummary | None
    lines: Page[ContributionPlanLine]
    calculated_at: datetime | None
    content_digest: str | None


class PlanningService(Protocol):
    """Every operation authorizes independently and consumes stored canonical inputs."""

    async def get_actual_vs_target(
        self, principal: Principal, account_id: str, *, query: ActualVsTargetQuery
    ) -> ActualVsTargetResult: ...

    async def get_drift_analysis(
        self, principal: Principal, account_id: str, *, query: DriftAnalysisQuery
    ) -> DriftAnalysisResult: ...

    async def create_contribution_plan(
        self,
        principal: Principal,
        command: CreateContributionPlanCommand,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> ContributionPlanJobView: ...

    async def list_contribution_plans(
        self, principal: Principal, *, query: ContributionPlanQuery
    ) -> Page[ContributionPlanSummaryView]: ...

    async def get_contribution_plan(
        self, principal: Principal, plan_id: str, *, query: ContributionPlanDetailQuery
    ) -> ContributionPlanDetailView: ...

    async def create_contribution_plan_revision(
        self,
        principal: Principal,
        plan_id: str,
        command: CreateContributionPlanCommand,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> ContributionPlanJobView: ...
