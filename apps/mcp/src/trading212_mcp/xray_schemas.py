"""Closed X-ray tool envelopes reuse the canonical HTTP financial result models."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, model_validator
from trading212_api_contracts.xray import XrayExposuresResponse, XrayMcpTopPairResponse, XraySchema


class XrayToolError(XraySchema):
    code: Literal[
        "AUTHENTICATION_REQUIRED",
        "ACCESS_DENIED",
        "NOT_FOUND",
        "VALIDATION_FAILED",
        "INPUT_SNAPSHOT_MISMATCH",
        "XRAY_UNAVAILABLE",
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


class XrayToolSelection(XraySchema):
    total: Annotated[StrictInt, Field(ge=0, le=10000)]
    returned: Annotated[StrictInt, Field(ge=0, le=100)]
    omitted: Annotated[StrictInt, Field(ge=0, le=10000)]

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        if self.returned + self.omitted != self.total:
            raise ValueError("Xray selection counts disagree.")
        return self


class XrayToolEnvelope[T](XraySchema):
    data: T | None
    selection: XrayToolSelection | None
    error: XrayToolError | None

    @model_validator(mode="after")
    def one_result(self) -> Self:
        if (self.data is None) == (self.error is None):
            raise ValueError("Exactly one X-ray data or error result is required.")
        if (self.selection is None) != (self.error is not None):
            raise ValueError("Only successful X-ray results have selection counts.")
        return self


class XrayExposureToolResult(XrayToolEnvelope[XrayExposuresResponse]):
    pass


class XrayOverlapToolResult(XrayToolEnvelope[XrayMcpTopPairResponse]):
    pass
