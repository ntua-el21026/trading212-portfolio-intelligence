"""Closed MCP envelopes over the canonical projection HTTP response contracts."""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator
from trading212_api_contracts.projection_inputs import ProjectionSchema
from trading212_api_contracts.projections import (
    GoalAnalysisResponse,
    GoalResponse,
    ProjectionOperationalRunResponse,
    ProjectionPageResponse,
    ProjectionRunResponse,
)


class ProjectionToolError(ProjectionSchema):
    code: Literal[
        "AUTHENTICATION_REQUIRED",
        "ACCESS_DENIED",
        "NOT_FOUND",
        "VALIDATION_FAILED",
        "INPUT_BOUND_EXCEEDED",
        "CONFLICT",
        "REVISION_MISMATCH",
        "REVISION_REQUIRED",
        "RATE_LIMITED",
        "SOURCE_UNAVAILABLE",
        "PROJECTION_UNAVAILABLE",
        "RUN_EXPIRED",
        "INVALID_STATE_TRANSITION",
        "CURSOR_INVALID",
        "REQUEST_TOO_LARGE",
        "RESULT_TOO_LARGE",
        "CALENDAR_OVERFLOW",
        "DATE_OUTSIDE_HORIZON",
        "DATE_NOT_MONTH_BOUNDARY",
        "GOAL_DATE_MISMATCH",
        "INTERNAL_ERROR",
    ]
    message: Annotated[str, Field(min_length=1, max_length=240)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=128)]
    retryable: StrictBool
    remediation: Annotated[str, Field(min_length=1, max_length=240)]


class ProjectionToolEnvelope[PayloadT](ProjectionSchema):
    data: PayloadT | None
    error: ProjectionToolError | None
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def exactly_one_result(self) -> Self:
        if (self.data is None) == (self.error is None):
            raise ValueError("Exactly one projection data or error result is required.")
        return self


class ProjectionListToolResult(ProjectionToolEnvelope[ProjectionPageResponse[GoalResponse]]):
    pass


class ProjectionCreateToolResult(ProjectionToolEnvelope[ProjectionOperationalRunResponse]):
    pass


class ProjectionRunToolResult(ProjectionToolEnvelope[ProjectionRunResponse]):
    pass


class ProjectionGoalToolResult(ProjectionToolEnvelope[GoalAnalysisResponse]):
    pass
