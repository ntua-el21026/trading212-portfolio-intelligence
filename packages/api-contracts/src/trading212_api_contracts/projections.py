"""Projection/goal DTO entrypoint for the existing frozen 17 REST operations."""

from __future__ import annotations

import json
from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, model_validator

from .projection_inputs import (
    AssumptionVersionContent as AssumptionVersionContent,
)
from .projection_inputs import (
    CancelProjectionRunRequest as CancelProjectionRunRequest,
)
from .projection_inputs import (
    CreateAssumptionSetRequest as CreateAssumptionSetRequest,
)
from .projection_inputs import (
    CreateAssumptionVersionRequest as CreateAssumptionVersionRequest,
)
from .projection_inputs import (
    CreateGoalRequest as CreateGoalRequest,
)
from .projection_inputs import (
    CreateGoalVersionRequest as CreateGoalVersionRequest,
)
from .projection_inputs import (
    CreateProjectionRunRequest as CreateProjectionRunRequest,
)
from .projection_inputs import (
    GoalVersionContent as GoalVersionContent,
)
from .projection_inputs import (
    ProjectionName,
    ProjectionRevision,
    ProjectionSchema,
    ProjectionVersionMetadata,
)
from .projection_inputs import (
    ProjectionPageQuery as ProjectionPageQuery,
)
from .projection_inputs import (
    ProjectionPointPageQuery as ProjectionPointPageQuery,
)
from .projection_results import (
    ProjectionGoalEstimateView,
    ProjectionNonnegativeQuantilesView,
    ProjectionResultContextView,
    ProjectionResultPage,
    ProjectionVariant,
)
from .targets import AwareInstant, Cursor, Digest, UUIDString

ProjectionJobState = Literal["queued", "running", "succeeded", "failed", "expired", "cancelled"]
ProjectionFailure = Literal[
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


class AssumptionSetResponse(ProjectionSchema):
    id: UUIDString
    account_id: UUIDString
    name: ProjectionName
    revision: ProjectionRevision
    current_version_id: UUIDString
    created_at: AwareInstant
    updated_at: AwareInstant

    @model_validator(mode="after")
    def ordered_time(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("Definition update precedes creation.")
        return self


class AssumptionVersionResponse(ProjectionSchema):
    id: UUIDString
    account_id: UUIDString
    set_id: UUIDString
    version_number: ProjectionRevision
    predecessor_id: UUIDString | None
    metadata: ProjectionVersionMetadata
    content: AssumptionVersionContent
    content_digest: Digest
    created_at: AwareInstant

    @model_validator(mode="after")
    def predecessor(self) -> Self:
        if (self.version_number == 1) != (
            self.predecessor_id is None
        ) or self.predecessor_id == self.id:
            raise ValueError("Immutable version predecessor differs.")
        return self


class GoalResponse(AssumptionSetResponse):
    pass


class GoalVersionResponse(ProjectionSchema):
    id: UUIDString
    account_id: UUIDString
    goal_id: UUIDString
    version_number: ProjectionRevision
    predecessor_id: UUIDString | None
    metadata: ProjectionVersionMetadata
    content: GoalVersionContent
    content_digest: Digest
    created_at: AwareInstant

    @model_validator(mode="after")
    def predecessor(self) -> Self:
        if (self.version_number == 1) != (
            self.predecessor_id is None
        ) or self.predecessor_id == self.id:
            raise ValueError("Immutable goal predecessor differs.")
        return self


class ProjectionPageResponse[T](ProjectionSchema):
    items: Annotated[list[T], Field(max_length=100)]
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: Annotated[StrictInt, Field(ge=0, le=250000)]

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if len(self.items) > min(self.limit, self.total):
            raise ValueError("Collection page bounds differ.")
        return self


class ProjectionRunResponse(ProjectionSchema):
    id: UUIDString
    account_id: UUIDString
    assumption_version_id: UUIDString
    goal_version_id: UUIDString | None
    job_id: UUIDString
    capture_digest: Digest
    numerical_input_digest: Digest
    state: ProjectionJobState
    result_availability: Literal["pending", "available", "not_loaded", "expired", "unavailable"]
    created_at: AwareInstant
    expires_at: AwareInstant
    completed_at: AwareInstant | None
    failure_code: ProjectionFailure | None
    result: ProjectionResultPage | None

    @model_validator(mode="after")
    def atomic_result(self) -> Self:
        active = self.state in ("queued", "running")
        if (
            self.expires_at <= self.created_at
            or (self.completed_at is None) != active
            or (self.completed_at is not None and self.completed_at < self.created_at)
        ):
            raise ValueError("Projection job timestamps disagree with its state.")
        # Retrying queued/running jobs may retain a fixed prior-attempt failure code.
        if self.state in ("succeeded", "cancelled") and self.failure_code is not None:
            raise ValueError("Projection failure metadata disagrees with its state.")
        if (
            (self.result is not None) != (self.result_availability == "available")
            or (
                self.result_availability in ("available", "not_loaded")
                and self.state != "succeeded"
            )
            or (self.result_availability == "pending" and not active)
        ):
            raise ValueError("Projection financial availability disagrees with publication.")
        if self.result is not None:
            context, selected = self.result.context, self.result.context.selection
            if (
                context.run_id != self.id
                or context.account_id != self.account_id
                or context.capture_digest != self.capture_digest
                or context.numerical_input_digest != self.numerical_input_digest
                or selected.assumption_version_id != self.assumption_version_id
                or selected.goal_version_id != self.goal_version_id
            ):
                raise ValueError("Published projection identities differ from the saved run.")
        return self


class ProjectionOperationalRunResponse(ProjectionRunResponse):
    result: None = None
    result_availability: Literal["pending", "not_loaded", "expired", "unavailable"]


class GoalVariantAnalysisView(ProjectionSchema):
    variant: ProjectionVariant
    terminal: ProjectionNonnegativeQuantilesView
    estimate: ProjectionGoalEstimateView

    @model_validator(mode="after")
    def money_basis(self) -> Self:
        if any(value.currency != self.estimate.target.currency for value in self.terminal.values):
            raise ValueError("Goal terminal and target currency differ.")
        return self


class GoalAnalysisResponse(ProjectionSchema):
    account_id: UUIDString
    run_id: UUIDString
    goal_version_id: UUIDString | None
    state: ProjectionJobState
    result_availability: Literal["pending", "available", "not_loaded", "expired", "unavailable"]
    availability: Literal["available", "unavailable"]
    reason: (
        Literal["no_goal_pinned", "run_pending", "run_failed", "run_expired", "run_cancelled"]
        | None
    )
    context: ProjectionResultContextView | None
    variants: Annotated[list[GoalVariantAnalysisView], Field(max_length=3)]
    content_digest: Digest
    view_version: Literal["goal_analysis_compact_v1"] = "goal_analysis_compact_v1"

    @model_validator(mode="after")
    def exact_saved_goal(self) -> Self:
        if self.availability == "unavailable":
            if self.reason is None or self.context is not None or self.variants:
                raise ValueError("Unavailable goal analysis cannot expose financial content.")
            expected = (
                "no_goal_pinned"
                if self.goal_version_id is None
                else "run_expired"
                if self.result_availability == "expired"
                else "run_pending"
                if self.state in ("queued", "running")
                else "run_expired"
                if self.state == "expired"
                else "run_cancelled"
                if self.state == "cancelled"
                else "run_failed"
                if self.state == "failed"
                else None
            )
            if self.reason != expected:
                raise ValueError("Unavailable goal reason disagrees with its saved state.")
        else:
            context = self.context
            if (
                self.state != "succeeded"
                or self.result_availability != "available"
                or self.reason is not None
                or context is None
                or self.goal_version_id is None
            ):
                raise ValueError("Goal analysis requires a published saved goal result.")
            selected = context.selection
            expected_variants = (
                ["baseline", "contribution_delta", "mean_log_delta"]
                if selected.sensitivity is not None
                else ["baseline"]
            )
            if (
                context.run_id != self.run_id
                or context.account_id != self.account_id
                or selected.goal_version_id != self.goal_version_id
                or [variant.variant for variant in self.variants] != expected_variants
            ):
                raise ValueError("Goal analysis identity or sensitivity variants differ.")
            if any(
                variant.estimate.goal_version_id != self.goal_version_id
                or variant.estimate.paths != selected.paths
                or variant.estimate.target.currency != context.reporting_currency
                for variant in self.variants
            ):
                raise ValueError("Goal estimates differ from their saved projection.")
        if (
            len(
                json.dumps(
                    self.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
            )
            > 1024 * 1024
        ):
            raise ValueError("Goal financial view exceeds 1 MiB.")
        return self
