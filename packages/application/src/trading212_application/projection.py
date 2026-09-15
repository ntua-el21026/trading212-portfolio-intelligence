"""Closed projection/goal service ports; these contracts confer no source authority."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from trading212_analytics._premium_numeric import semidefinite_factor
from trading212_domain.errors import fail_validation
from trading212_domain.projection import PROJECTION_MAX_WORK, ProjectionAssumptions
from trading212_domain.sources import source_integer
from trading212_domain.values import require_bounded_text
from trading212_security.principals import Principal

from .projection_calendar import ProjectionCalendar
from .projection_capture import ProjectionGoalVersionContent, ProjectionRunSelection
from .projection_views import (
    AssumptionSetView,
    AssumptionVersionView,
    GoalAnalysisView,
    GoalVersionView,
    GoalView,
    ProjectionOperationalRunView,
    ProjectionRunView,
    ProjectionVersionMetadata,
)
from .targets import TargetServiceError, validate_target_idempotency_key
from .views import Page


class ProjectionErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INPUT_BOUND_EXCEEDED = "INPUT_BOUND_EXCEEDED"
    CONFLICT = "CONFLICT"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    PROJECTION_UNAVAILABLE = "PROJECTION_UNAVAILABLE"
    RUN_EXPIRED = "RUN_EXPIRED"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    CURSOR_INVALID = "CURSOR_INVALID"
    CALENDAR_OVERFLOW = "CALENDAR_OVERFLOW"
    DATE_OUTSIDE_HORIZON = "DATE_OUTSIDE_HORIZON"
    DATE_NOT_MONTH_BOUNDARY = "DATE_NOT_MONTH_BOUNDARY"
    GOAL_DATE_MISMATCH = "GOAL_DATE_MISMATCH"


@dataclass(slots=True)
class ProjectionServiceError(Exception):
    code: ProjectionErrorCode
    message: str = "The projection operation cannot be completed."

    def __str__(self) -> str:
        return self.message


def _ids(*values: UUID) -> None:
    if any(type(value) is not UUID for value in values):
        fail_validation("Canonical UUID identities are required.", field="id")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionCommand:
    idempotency_key: str
    correlation_id: str

    def __post_init__(self) -> None:
        try:
            validate_target_idempotency_key(self.idempotency_key)
        except TargetServiceError:
            fail_validation("Invalid projection idempotency key.", field="idempotency_key")
        require_bounded_text(self.correlation_id, field="correlation_id", maximum=120)


def _assumptions(content: ProjectionAssumptions, metadata: ProjectionVersionMetadata) -> None:
    if (
        type(content) is not ProjectionAssumptions
        or type(metadata) is not ProjectionVersionMetadata
    ):
        fail_validation(
            "Canonical immutable assumptions and metadata are required.", field="content"
        )
    # The same Decimal96 singular-PSD acceptance is used by projection admission.
    semidefinite_factor(content.correlation)


def _goal(content: ProjectionGoalVersionContent, metadata: ProjectionVersionMetadata) -> None:
    if (
        type(content) is not ProjectionGoalVersionContent
        or type(metadata) is not ProjectionVersionMetadata
    ):
        fail_validation(
            "Canonical immutable goal content and metadata are required.", field="content"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateAssumptionSet(ProjectionCommand):
    account_id: UUID
    metadata: ProjectionVersionMetadata
    content: ProjectionAssumptions

    def __post_init__(self) -> None:
        ProjectionCommand.__post_init__(self)
        _ids(self.account_id)
        _assumptions(self.content, self.metadata)


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateAssumptionVersion(ProjectionCommand):
    set_id: UUID
    expected_revision: int
    metadata: ProjectionVersionMetadata
    content: ProjectionAssumptions

    def __post_init__(self) -> None:
        ProjectionCommand.__post_init__(self)
        _ids(self.set_id)
        source_integer(self.expected_revision, "expected_revision", 1, 512)
        _assumptions(self.content, self.metadata)


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateGoal(ProjectionCommand):
    account_id: UUID
    metadata: ProjectionVersionMetadata
    content: ProjectionGoalVersionContent

    def __post_init__(self) -> None:
        ProjectionCommand.__post_init__(self)
        _ids(self.account_id)
        _goal(self.content, self.metadata)


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateGoalVersion(ProjectionCommand):
    goal_id: UUID
    expected_revision: int
    metadata: ProjectionVersionMetadata
    content: ProjectionGoalVersionContent

    def __post_init__(self) -> None:
        ProjectionCommand.__post_init__(self)
        _ids(self.goal_id)
        source_integer(self.expected_revision, "expected_revision", 1, 512)
        _goal(self.content, self.metadata)


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateProjectionRun(ProjectionCommand):
    selection: ProjectionRunSelection

    def __post_init__(self) -> None:
        ProjectionCommand.__post_init__(self)
        if type(self.selection) is not ProjectionRunSelection:
            fail_validation("A canonical saved-input selection is required.", field="selection")
        selected = self.selection
        variants = 3 if selected.sensitivity is not None else 1
        if (
            len(selected.allocation) * selected.months * selected.paths * variants
            > PROJECTION_MAX_WORK
        ):
            fail_validation("Projection exceeds the shared work bound.", field="projection.work")
        if selected.initial.kind == "modeled_value":
            anchor = selected.initial.modeled_anchor_date
            assert anchor is not None
            calendar = ProjectionCalendar(anchor_date=anchor, months=selected.months)
            selected.schedule.resolve(calendar)
        # Owned snapshots, immutable goal agreement, calibrated source membership,
        # all sensitivity variants and actual 32 MiB admission need authorized capture.


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelProjectionRun(ProjectionCommand):
    run_id: UUID

    def __post_init__(self) -> None:
        ProjectionCommand.__post_init__(self)
        _ids(self.run_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionPageQuery:
    limit: int = 25
    cursor: str | None = None

    def __post_init__(self) -> None:
        source_integer(self.limit, "limit", 1, 100)
        if self.cursor is not None:
            require_bounded_text(self.cursor, field="cursor", maximum=2048)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionPointPageQuery:
    point_limit: int = 25
    point_cursor: str | None = None

    def __post_init__(self) -> None:
        source_integer(self.point_limit, "point_limit", 1, 100)
        if self.point_cursor is not None:
            require_bounded_text(self.point_cursor, field="point_cursor", maximum=2048)


class ProjectionService(Protocol):
    """The frozen 17 operations; no transport, provider or broker dispatch port.

    Require portfolio:read + analytics:read and current durable grants before private
    versions, source proofs, cursor parsing, conditional reads or idempotent replay.
    Assumption/run writes add projections:write; goal writes add goals:write. Saved
    calibration/snapshot source membership and pinned/current licenses are authority,
    never caller labels. Reauthorize immediately before every returned financial view.

    Version commands atomically compare revision, retain immutable metadata/content,
    bind every material field in idempotency, and append safe audit. Goal objective_met
    never changes goal lifecycle state. Admission calls authorized ProjectionCapturePlan
    before reserving full three-variant work/bytes and publishing root/input/job/outbox
    atomically. Two shared active jobs per owner and the global execution slot remain
    persistence obligations. Failure/cancel releases job slots but retains byte charges
    for all copied financial data until actual retention deletion completes.

    Current actor issuer+subject/account, capture/numerical/result digests, point limit,
    view/resource and all source/run expiries bind immutable point cursors. Optional
    expected_account_id pins the caller's requested account before private access.
    """

    async def create_assumption_set(
        self, principal: Principal, command: CreateAssumptionSet
    ) -> AssumptionSetView: ...
    async def get_assumption_set(self, principal: Principal, set_id: UUID) -> AssumptionSetView: ...
    async def list_assumption_sets(
        self, principal: Principal, account_id: UUID, query: ProjectionPageQuery
    ) -> Page[AssumptionSetView]: ...
    async def create_assumption_version(
        self, principal: Principal, command: CreateAssumptionVersion
    ) -> AssumptionVersionView: ...
    async def get_assumption_version(
        self, principal: Principal, version_id: UUID
    ) -> AssumptionVersionView: ...
    async def list_assumption_versions(
        self, principal: Principal, set_id: UUID, query: ProjectionPageQuery
    ) -> Page[AssumptionVersionView]: ...
    async def create_goal(self, principal: Principal, command: CreateGoal) -> GoalView: ...
    async def get_goal(self, principal: Principal, goal_id: UUID) -> GoalView: ...
    async def list_goals(
        self, principal: Principal, account_id: UUID, query: ProjectionPageQuery
    ) -> Page[GoalView]: ...
    async def create_goal_version(
        self, principal: Principal, command: CreateGoalVersion
    ) -> GoalVersionView: ...
    async def get_goal_version(self, principal: Principal, version_id: UUID) -> GoalVersionView: ...
    async def list_goal_versions(
        self, principal: Principal, goal_id: UUID, query: ProjectionPageQuery
    ) -> Page[GoalVersionView]: ...
    async def create_run(
        self, principal: Principal, command: CreateProjectionRun
    ) -> ProjectionOperationalRunView: ...
    async def list_runs(
        self, principal: Principal, account_id: UUID, query: ProjectionPageQuery
    ) -> Page[ProjectionOperationalRunView]: ...
    async def get_run(
        self,
        principal: Principal,
        run_id: UUID,
        query: ProjectionPointPageQuery,
        *,
        expected_account_id: UUID | None = None,
    ) -> ProjectionRunView: ...
    async def get_goal_analysis(
        self, principal: Principal, run_id: UUID, *, expected_account_id: UUID | None = None
    ) -> GoalAnalysisView: ...
    async def cancel_run(
        self, principal: Principal, command: CancelProjectionRun
    ) -> ProjectionOperationalRunView: ...
