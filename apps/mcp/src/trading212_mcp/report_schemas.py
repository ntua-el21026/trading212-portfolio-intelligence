"""Strict report MCP envelopes share the authorized HTTP metadata contracts."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, model_validator
from trading212_api_contracts.reports import ReportJobStatus, ReportPage, ReportSchema
from trading212_api_contracts.targets import Cursor


class ReportToolError(ReportSchema):
    code: Literal[
        "AUTHENTICATION_REQUIRED",
        "ACCESS_DENIED",
        "NOT_FOUND",
        "VALIDATION_FAILED",
        "IDEMPOTENCY_KEY_REUSED",
        "INVALID_STATE_TRANSITION",
        "RATE_LIMITED",
        "ARTIFACT_EXPIRED",
        "REPORT_UNAVAILABLE",
        "JOB_DISPATCH_UNAVAILABLE",
        "REQUEST_TOO_LARGE",
        "RESULT_TOO_LARGE",
        "CURSOR_INVALID",
        "COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED",
        "INTERNAL_ERROR",
    ]
    message: Annotated[str, Field(min_length=1, max_length=240)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=128)]
    retryable: StrictBool
    remediation: Annotated[str, Field(min_length=1, max_length=240)]


class ReportToolPagination(ReportSchema):
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: Annotated[StrictInt, Field(ge=0)]
    returned: Annotated[StrictInt, Field(ge=0, le=100)]
    truncated: StrictBool


class ReportToolEnvelope[PayloadT](ReportSchema):
    data: PayloadT | None
    pagination: ReportToolPagination | None
    error: ReportToolError | None
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def exactly_one_result(self) -> Self:
        if (self.data is None) == (self.error is None):
            raise ValueError("Exactly one report data or error result is required.")
        if self.error is not None and self.pagination is not None:
            raise ValueError("A failed report operation cannot claim a successful page.")
        return self


class ReportStatusToolResult(ReportToolEnvelope[ReportJobStatus]):
    pass


class ReportListToolResult(ReportToolEnvelope[ReportPage]):
    pass


class GenerateReportToolResult(ReportToolEnvelope[ReportJobStatus]):
    pass
