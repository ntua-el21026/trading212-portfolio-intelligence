"""Closed historical tool envelopes reuse the canonical HTTP financial result models."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, model_validator
from trading212_api_contracts.historical import (
    AttributionSummaryResponse,
    BenchmarkComparisonResponse,
    DividendIntelligenceResponse,
    HistoricalSchema,
    PerformanceIntelligenceResponse,
)


class HistoricalToolError(HistoricalSchema):
    code: Literal[
        "AUTHENTICATION_REQUIRED",
        "ACCESS_DENIED",
        "NOT_FOUND",
        "VALIDATION_FAILED",
        "INPUT_SNAPSHOT_MISMATCH",
        "HISTORICAL_UNAVAILABLE",
        "RESULT_TOO_LARGE",
        "REQUEST_TOO_LARGE",
        "CURSOR_INVALID",
        "COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED",
        "INTERNAL_ERROR",
    ]
    message: Annotated[str, Field(min_length=1, max_length=240)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=128)]
    retryable: StrictBool
    remediation: Annotated[str, Field(min_length=1, max_length=240)]


class HistoricalToolSelection(HistoricalSchema):
    total: Annotated[StrictInt, Field(ge=0, le=10000)]
    returned: Annotated[StrictInt, Field(ge=0, le=3661)]
    omitted: Annotated[StrictInt, Field(ge=0, le=10000)]

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        if self.returned + self.omitted != self.total:
            raise ValueError("Historical selection counts disagree.")
        return self


class HistoricalToolEnvelope[T](HistoricalSchema):
    data: T | None
    selection: HistoricalToolSelection | None
    error: HistoricalToolError | None

    @model_validator(mode="after")
    def one_result(self) -> Self:
        if (self.data is None) == (self.error is None):
            raise ValueError("Exactly one historical data or error result is required.")
        if (self.selection is None) != (self.error is not None):
            raise ValueError("Only successful historical results have selection counts.")
        return self


class HistoricalPerformanceToolResult(HistoricalToolEnvelope[PerformanceIntelligenceResponse]):
    pass


class HistoricalBenchmarkToolResult(HistoricalToolEnvelope[BenchmarkComparisonResponse]):
    pass


class HistoricalDividendToolResult(HistoricalToolEnvelope[DividendIntelligenceResponse]):
    pass


class HistoricalAttributionToolResult(HistoricalToolEnvelope[AttributionSummaryResponse]):
    pass
