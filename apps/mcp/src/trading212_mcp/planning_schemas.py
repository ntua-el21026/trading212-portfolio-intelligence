"""Strict planning MCP envelopes over the same bounded HTTP result models."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, model_validator
from trading212_api_contracts.planning import (
    ActualVsTargetResult,
    ContributionPlanDetail,
    ContributionPlanJob,
    DriftAnalysisResult,
    PlanningSchema,
)
from trading212_api_contracts.targets import Cursor


class PlanningToolError(PlanningSchema):
    code: Literal[
        "AUTHENTICATION_REQUIRED",
        "ACCESS_DENIED",
        "NOT_FOUND",
        "VALIDATION_FAILED",
        "CURRENCY_MISMATCH",
        "IMMUTABLE_VERSION",
        "IDEMPOTENCY_KEY_REUSED",
        "REVISION_REQUIRED",
        "REVISION_MISMATCH",
        "INVALID_STATE_TRANSITION",
        "RESULT_TOO_LARGE",
        "REQUEST_TOO_LARGE",
        "PLANNING_UNAVAILABLE",
        "CURSOR_INVALID",
        "COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED",
        "INTERNAL_ERROR",
    ]
    message: Annotated[str, Field(min_length=1, max_length=240)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=128)]
    retryable: StrictBool
    remediation: Annotated[str, Field(min_length=1, max_length=240)]


class PlanningToolPagination(PlanningSchema):
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: Annotated[StrictInt, Field(ge=0)]
    returned: Annotated[StrictInt, Field(ge=0, le=100)]
    truncated: StrictBool


class PlanningToolEnvelope[PayloadT](PlanningSchema):
    data: PayloadT | None
    pagination: PlanningToolPagination | None
    error: PlanningToolError | None
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def exactly_one_result(self) -> Self:
        if (self.data is None) == (self.error is None):
            raise ValueError("Exactly one planning data or error result is required.")
        if self.error is not None and self.pagination is not None:
            raise ValueError("Errors cannot claim a successful page.")
        return self


class ActualVsTargetToolResult(PlanningToolEnvelope[ActualVsTargetResult]):
    pass


class DriftAnalysisToolResult(PlanningToolEnvelope[DriftAnalysisResult]):
    pass


class ContributionPlanToolResult(PlanningToolEnvelope[ContributionPlanDetail]):
    pass


class CreateContributionPlanToolResult(PlanningToolEnvelope[ContributionPlanJob]):
    pass
