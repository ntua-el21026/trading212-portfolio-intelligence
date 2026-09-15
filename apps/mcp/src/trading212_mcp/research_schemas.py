"""Closed research MCP envelopes reuse the exact REST financial/provenance DTOs."""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator
from trading212_api_contracts.research import ResearchItemView, ResearchSchema, ResearchSummary


class ResearchToolError(ResearchSchema):
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
        "CURSOR_INVALID",
        "REQUEST_TOO_LARGE",
        "RESULT_TOO_LARGE",
        "INTERNAL_ERROR",
    ]
    message: Annotated[str, Field(min_length=1, max_length=240)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=128)]
    retryable: StrictBool
    remediation: Annotated[str, Field(min_length=1, max_length=240)]


class ResearchToolEnvelope[PayloadT](ResearchSchema):
    data: PayloadT | None
    error: ResearchToolError | None
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def exactly_one_result(self) -> Self:
        if (self.data is None) == (self.error is None):
            raise ValueError("Exactly one research data or error result is required.")
        return self


class ResearchSummaryToolResult(ResearchToolEnvelope[ResearchSummary]):
    pass


class ResearchItemToolResult(ResearchToolEnvelope[ResearchItemView]):
    pass
