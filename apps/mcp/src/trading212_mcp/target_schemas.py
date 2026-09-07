"""Strict configuration-read MCP results, separate from Phase 1 financial schemas."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, model_validator
from trading212_api_contracts.targets import (
    AwareInstant,
    CurrencyString,
    Cursor,
    DecimalString,
    Digest,
    FlattenedTargetNodeResponse,
    TargetConstraint,
    TargetExclusion,
    TargetHierarchyNodeResponse,
    TargetSchema,
    TargetValidationResponse,
    UUIDString,
    VersionState,
    VirtualPortfolioResponse,
)

type TargetToolErrorCode = Literal[
    "AUTHENTICATION_REQUIRED",
    "ACCESS_DENIED",
    "NOT_FOUND",
    "VALIDATION_FAILED",
    "CURSOR_INVALID",
    "COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED",
    "TARGETS_UNAVAILABLE",
    "RESULT_TOO_LARGE",
    "REQUEST_TOO_LARGE",
    "INTERNAL_ERROR",
]


class TargetToolError(TargetSchema):
    code: TargetToolErrorCode
    message: Annotated[str, Field(min_length=1, max_length=240)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=128)]
    retryable: StrictBool
    remediation: Annotated[str, Field(min_length=1, max_length=240)]


class TargetReadQuality(TargetSchema):
    state: Literal["configuration", "unvalidated", "valid", "invalid", "partial"]
    validation_id: UUIDString | None = None
    issue_count: Annotated[StrictInt, Field(ge=0, le=1024)] = 0
    unresolved_mapping_count: Annotated[StrictInt, Field(ge=0, le=256)] = 0
    disclosure: Annotated[str, Field(min_length=1, max_length=240)]


class TargetReadMethod(TargetSchema):
    name: Literal["target_configuration_read_v1"] = "target_configuration_read_v1"
    version: Literal["1.0.0"] = "1.0.0"
    source_version_id: UUIDString | None = None
    source_content_digest: Digest | None = None


class TargetPagination(TargetSchema):
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: Annotated[StrictInt, Field(ge=0)]
    truncated: StrictBool


class VirtualPiesData(TargetSchema):
    portfolios: Annotated[list[VirtualPortfolioResponse], Field(max_length=100)]
    read_only: Literal[True] = True


class TargetVersionMetadata(TargetSchema):
    id: UUIDString
    portfolio_id: UUIDString
    version_number: Annotated[StrictInt, Field(ge=1)]
    revision: Annotated[StrictInt, Field(ge=1)]
    reporting_currency: CurrencyString
    effective_at: AwareInstant
    state: VersionState
    created_at: AwareInstant
    updated_at: AwareInstant
    published_at: AwareInstant | None
    content_digest: Digest | None
    source_version_id: UUIDString | None
    constraints: Annotated[list[TargetConstraint], Field(max_length=256)]
    exclusions: Annotated[list[TargetExclusion], Field(max_length=256)]
    effective_weight_rounding_residual: DecimalString | None


class TargetReadNode(TargetSchema):
    hierarchy: TargetHierarchyNodeResponse
    calculated: FlattenedTargetNodeResponse | None


class VirtualPieData(TargetSchema):
    portfolio: VirtualPortfolioResponse
    target_version: TargetVersionMetadata | None
    nodes: Annotated[list[TargetReadNode], Field(max_length=100)]
    validation: TargetValidationResponse | None
    target_availability: Literal["available", "unavailable"]
    target_reason: Literal["NO_ACTIVE_TARGET"] | None
    parent_node_id: UUIDString | None
    read_only: Literal[True] = True


class TargetToolEnvelope[PayloadT](TargetSchema):
    data: PayloadT | None
    as_of: AwareDatetime | None
    reporting_currency: CurrencyString | None
    data_quality: TargetReadQuality | None
    calculation: TargetReadMethod | None
    pagination: TargetPagination | None
    error: TargetToolError | None

    @model_validator(mode="after")
    def exactly_one_result(self) -> Self:
        if (self.data is None) == (self.error is None):
            raise ValueError("exactly one data or error result is required")
        if self.data is not None and (
            self.data_quality is None or self.calculation is None or self.pagination is None
        ):
            raise ValueError("configuration reads require typed quality, method, and pagination")
        return self


class VirtualPiesResult(TargetToolEnvelope[VirtualPiesData]):
    pass


class VirtualPieResult(TargetToolEnvelope[VirtualPieData]):
    pass
