"""Closed MCP envelopes over the canonical scenario HTTP response contracts."""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator
from trading212_api_contracts.scenarios import (
    ScenarioComparisonPage,
    ScenarioDefinitionResponse,
    ScenarioOperationalRunResponse,
    ScenarioPageResponse,
    ScenarioRunResponse,
    ScenarioSchema,
)


class ScenarioToolError(ScenarioSchema):
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
        "SCENARIO_UNAVAILABLE",
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


class ScenarioToolEnvelope[PayloadT](ScenarioSchema):
    data: PayloadT | None
    error: ScenarioToolError | None
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def exactly_one_result(self) -> Self:
        if (self.data is None) == (self.error is None):
            raise ValueError("Exactly one scenario data or error result is required.")
        return self


class ScenarioListToolResult(
    ScenarioToolEnvelope[ScenarioPageResponse[ScenarioDefinitionResponse]]
):
    pass


class ScenarioCreateToolResult(ScenarioToolEnvelope[ScenarioOperationalRunResponse]):
    pass


class ScenarioRunToolResult(ScenarioToolEnvelope[ScenarioRunResponse]):
    pass


class ScenarioComparisonToolResult(ScenarioToolEnvelope[ScenarioComparisonPage]):
    pass
