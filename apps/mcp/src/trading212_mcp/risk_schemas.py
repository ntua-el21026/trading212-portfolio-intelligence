"""Closed MCP envelopes over the canonical risk HTTP response contracts."""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator
from trading212_api_contracts.risk import RiskMatrixResponse, RiskRunResponse, RiskSchema


class RiskToolError(RiskSchema):
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
        "RISK_UNAVAILABLE",
        "RUN_EXPIRED",
        "INVALID_STATE_TRANSITION",
        "CURSOR_INVALID",
        "REQUEST_TOO_LARGE",
        "RESULT_TOO_LARGE",
        "INTERNAL_ERROR",
    ]
    message: Annotated[str, Field(min_length=1, max_length=240)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=128)]
    retryable: StrictBool
    remediation: Annotated[str, Field(min_length=1, max_length=240)]


class RiskToolEnvelope[PayloadT](RiskSchema):
    data: PayloadT | None
    error: RiskToolError | None
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def exactly_one_result(self) -> Self:
        if (self.data is None) == (self.error is None):
            raise ValueError("Exactly one risk data or error result is required.")
        return self


class RiskRunToolResult(RiskToolEnvelope[RiskRunResponse]):
    pass


class RiskMatrixToolResult(RiskToolEnvelope[RiskMatrixResponse]):
    pass
