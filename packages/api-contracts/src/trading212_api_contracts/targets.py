"""Bounded P2-01 wire contracts shared by HTTP, MCP and generated web clients."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)


def _uuid(value: str) -> str:
    return str(UUID(value))


def _instant_input(value: object) -> object:
    if (
        not isinstance(value, str)
        or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value
        )
        is None
    ):
        raise ValueError("An aware RFC3339 instant is required.")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An aware RFC3339 instant is required.")
    return value.astimezone(UTC)


def _text(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Text cannot contain NUL.")
    return value


def _weight(value: str) -> str:
    if not Decimal(0) <= Decimal(value) <= Decimal(1):
        raise ValueError("Weight must lie between zero and one.")
    return value


UUIDString = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
    ),
    AfterValidator(_uuid),
    Field(json_schema_extra={"format": "uuid"}),
]
DecimalString = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^-?(?:0|[1-9][0-9]{0,19})(?:\.[0-9]{1,18})?$"),
]
WeightString = Annotated[DecimalString, AfterValidator(_weight)]
CurrencyString = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Z]{3}$")]
StableKey = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=80), AfterValidator(_text)
]
Name = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120),
    AfterValidator(_text),
]
Description = Annotated[str, StringConstraints(strict=True, max_length=2000), AfterValidator(_text)]
Note = Annotated[str, StringConstraints(strict=True, max_length=1000), AfterValidator(_text)]
AwareInstant = Annotated[datetime, BeforeValidator(_instant_input), AfterValidator(_utc)]
Digest = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
Cursor = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=2048, pattern=r"^[A-Za-z0-9_-]+$")
]
IdempotencyKey = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=180, pattern=r"^[A-Za-z0-9._:-]+$")
]
VersionState = Literal["draft", "scheduled", "active", "superseded", "archived"]


class TargetSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TargetRequestedIdentifier(TargetSchema):
    kind: Literal["isin", "provider_key", "mic_ticker"]
    value: StableKey
    provider: StableKey | None = None

    @model_validator(mode="after")
    def provider_matches_kind(self) -> Self:
        if (self.kind == "provider_key") != (self.provider is not None):
            raise ValueError("Provider is required only for a provider key.")
        return self


class TargetHoldingMapping(TargetSchema):
    state: Literal["resolved", "unresolved", "ambiguous"]
    instrument_id: UUIDString | None = None
    listing_id: UUIDString | None = None
    preferred_listing_id: UUIDString | None = None
    requested_identifier: TargetRequestedIdentifier | None = None
    reason: Note | None = None

    @model_validator(mode="after")
    def mapping_shape(self) -> Self:
        if self.state == "resolved" and self.instrument_id is None:
            raise ValueError("Resolved mappings require a canonical instrument.")
        if self.state != "resolved" and (
            self.requested_identifier is None or self.reason is None or not self.reason.strip()
        ):
            raise ValueError("Unresolved mappings require a requested identifier and reason.")
        if self.listing_id is not None and self.preferred_listing_id not in (None, self.listing_id):
            raise ValueError("A listing selector and preference must agree.")
        return self


class TargetNode(TargetSchema):
    key: StableKey
    parent_key: StableKey | None = None
    kind: Literal["group", "holding", "cash"]
    name: Name
    order: Annotated[StrictInt, Field(ge=0, le=255)] = 0
    weight: WeightString
    holding: TargetHoldingMapping | None = None

    @model_validator(mode="after")
    def holding_matches_kind(self) -> Self:
        if (self.kind == "holding") != (self.holding is not None):
            raise ValueError("Only holding nodes require a holding mapping.")
        return self


class TargetConstraint(TargetSchema):
    key: StableKey
    kind: Literal[
        "minimum_funded_amount",
        "amount_increment",
        "minimum_post_weight",
        "maximum_post_weight",
        "minimum_group_funding",
        "maximum_group_funding",
        "cash_reserve",
        "eligible",
        "maximum_funded_lines",
        "priority",
    ]
    node_key: StableKey | None = None
    amount: DecimalString | None = None
    currency: CurrencyString | None = None
    weight: WeightString | None = None
    enabled: StrictBool | None = None
    count: Annotated[StrictInt, Field(ge=0, le=256)] | None = None
    coefficient: DecimalString | None = None

    @model_validator(mode="after")
    def checked_variant(self) -> Self:
        supplied = {
            key
            for key in ("amount", "currency", "weight", "enabled", "count", "coefficient")
            if getattr(self, key) is not None
        }
        amount_kinds = {
            "minimum_funded_amount",
            "amount_increment",
            "minimum_group_funding",
            "maximum_group_funding",
        }
        if self.kind in amount_kinds:
            valid = supplied == {"amount", "currency"} and self.node_key is not None
        elif self.kind in {"minimum_post_weight", "maximum_post_weight"}:
            valid = supplied == {"weight"} and self.node_key is not None
        elif self.kind == "cash_reserve":
            valid = (
                supplied in ({"amount", "currency"}, {"weight"}, {"amount", "currency", "weight"})
                and self.node_key is None
            )
        elif self.kind == "eligible":
            valid = supplied == {"enabled"} and self.node_key is not None
        elif self.kind == "maximum_funded_lines":
            valid = supplied == {"count"} and self.node_key is None
        else:
            valid = supplied == {"coefficient"} and self.node_key is not None
        if not valid:
            raise ValueError("Constraint fields must match their checked variant.")
        if self.amount is not None and (
            Decimal(self.amount) < 0
            or (self.kind == "amount_increment" and Decimal(self.amount) == 0)
        ):
            raise ValueError("Invalid constraint amount.")
        if self.coefficient is not None and not Decimal("0.000001") <= Decimal(
            self.coefficient
        ) <= Decimal("1000"):
            raise ValueError("Invalid priority coefficient.")
        return self


class TargetExclusion(TargetSchema):
    key: StableKey
    node_key: StableKey | None = None
    instrument_id: UUIDString | None = None
    listing_id: UUIDString | None = None
    reason: Note = ""

    @model_validator(mode="after")
    def one_selector(self) -> Self:
        if (
            sum(value is not None for value in (self.node_key, self.instrument_id, self.listing_id))
            != 1
        ):
            raise ValueError("Exactly one exclusion selector is required.")
        return self


class TargetContent(TargetSchema):
    nodes: Annotated[list[TargetNode], Field(max_length=256)]
    constraints: Annotated[list[TargetConstraint], Field(max_length=256)] = Field(
        default_factory=list
    )
    exclusions: Annotated[list[TargetExclusion], Field(max_length=256)] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def unique_keys(self) -> Self:
        for values in (self.nodes, self.constraints, self.exclusions):
            if len({value.key for value in values}) != len(values):
                raise ValueError("Content arrays require unique stable keys.")
        return self


class CreateVirtualPortfolioRequest(TargetSchema):
    name: Name
    reporting_currency: CurrencyString
    account_id: UUIDString | None = None
    description: Description = ""


class UpdateVirtualPortfolioRequest(TargetSchema):
    name: Name | None = None
    description: Description | None = None

    @model_validator(mode="after")
    def at_least_one_value(self) -> Self:
        if self.name is None and self.description is None:
            raise ValueError("Metadata update requires a value.")
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Metadata fields cannot be cleared to null.")
        return self


class CreateTargetVersionRequest(TargetSchema):
    effective_at: AwareInstant
    source_version_id: UUIDString | None = None
    content: TargetContent | None = None

    @model_validator(mode="after")
    def source_or_content(self) -> Self:
        if (self.source_version_id is None) == (self.content is None):
            raise ValueError("Exactly one source version or content is required.")
        return self


class ReplaceTargetDraftRequest(TargetSchema):
    effective_at: AwareInstant
    content: TargetContent


class ValidateTargetRequest(TargetSchema):
    normalize: StrictBool = False


class PublishTargetRequest(TargetSchema):
    validation_id: UUIDString


class EmptyTargetRequest(TargetSchema):
    pass


class TargetPageQuery(TargetSchema):
    cursor: Cursor | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 25


class VirtualPortfolioQuery(TargetPageQuery):
    account_id: UUIDString | None = None
    state: Literal["draft", "active", "archived", "all"] = "active"
    sort: Literal["name_asc", "updated_desc"] = "name_asc"
    search: Annotated[str, StringConstraints(max_length=80), AfterValidator(_text)] | None = None


class TargetVersionQuery(TargetPageQuery):
    state: Literal["draft", "scheduled", "active", "superseded", "archived", "all"] = "all"


class TargetHierarchyQuery(TargetPageQuery):
    parent_node_id: UUIDString | None = None


class TargetComparisonQuery(TargetSchema):
    left_version_id: UUIDString
    right_version_id: UUIDString


class VirtualPortfolioResponse(TargetSchema):
    id: UUIDString
    account_id: UUIDString | None
    name: Name
    description: Description
    reporting_currency: CurrencyString
    revision: Annotated[StrictInt, Field(ge=1)]
    state: Literal["draft", "active", "archived"]
    created_at: AwareInstant
    updated_at: AwareInstant
    active_version_id: UUIDString | None = None


class TargetPageResponse[T](TargetSchema):
    items: Annotated[list[T], Field(max_length=100)]
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: Annotated[StrictInt, Field(ge=0)]


class TargetValidationIssueResponse(TargetSchema):
    code: StableKey
    severity: Literal["error", "warning"]
    message: Note
    node_keys: Annotated[list[StableKey], Field(max_length=256)]
    constraint_keys: Annotated[list[StableKey], Field(max_length=256)]


class TargetNormalizationAdjustmentResponse(TargetSchema):
    node_key: StableKey
    parent_key: StableKey | None
    original_weight: DecimalString
    normalized_weight: WeightString
    original_sibling_sum: DecimalString
    remainder_rank: Annotated[StrictInt, Field(ge=0, le=256)]


class FlattenedTargetNodeResponse(TargetSchema):
    node: TargetNode
    depth: Annotated[StrictInt, Field(ge=1, le=8)]
    ordinal: Annotated[StrictInt, Field(ge=0, le=255)]
    path_keys: Annotated[list[StableKey], Field(min_length=1, max_length=8)]
    path_factors: Annotated[list[WeightString], Field(min_length=1, max_length=8)]
    effective_weight: WeightString


class TargetValidationResponse(TargetSchema):
    id: UUIDString
    version_id: UUIDString
    input_revision: Annotated[StrictInt, Field(ge=1)]
    result_revision: Annotated[StrictInt, Field(ge=1)]
    input_digest: Digest
    result_digest: Digest
    valid: StrictBool
    normalize_requested: StrictBool
    normalization_applied: StrictBool
    issues: Annotated[list[TargetValidationIssueResponse], Field(max_length=1024)]
    adjustments: Annotated[list[TargetNormalizationAdjustmentResponse], Field(max_length=256)]
    evaluated_at: AwareInstant
    method: StableKey
    method_version: StableKey


class TargetVersionResponse(TargetSchema):
    id: UUIDString
    portfolio_id: UUIDString
    version_number: Annotated[StrictInt, Field(ge=1)]
    revision: Annotated[StrictInt, Field(ge=1)]
    reporting_currency: CurrencyString
    effective_at: AwareInstant
    state: VersionState
    content: TargetContent
    created_at: AwareInstant
    updated_at: AwareInstant
    published_at: AwareInstant | None = None
    content_digest: Digest | None = None
    source_version_id: UUIDString | None = None
    latest_validation: TargetValidationResponse | None = None
    flattened_nodes: Annotated[list[FlattenedTargetNodeResponse], Field(max_length=256)]
    effective_weight_rounding_residual: DecimalString | None = None


class TargetVersionEventResponse(TargetSchema):
    id: UUIDString
    version_id: UUIDString
    sequence: Annotated[StrictInt, Field(ge=1)]
    kind: StableKey
    actor_id: Annotated[
        str, StringConstraints(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9._:-]+$")
    ]
    occurred_at: AwareInstant
    effective_at: AwareInstant | None
    validation_id: UUIDString | None


class TargetHierarchyNodeResponse(TargetSchema):
    id: UUIDString
    node: TargetNode


class TargetNodeChangeResponse(TargetSchema):
    key: StableKey
    changed_fields: Annotated[list[StableKey], Field(max_length=10)]
    left: TargetNode | None
    right: TargetNode | None


class TargetConstraintChangeResponse(TargetSchema):
    key: StableKey
    left: TargetConstraint | None
    right: TargetConstraint | None


class TargetExclusionChangeResponse(TargetSchema):
    key: StableKey
    left: TargetExclusion | None
    right: TargetExclusion | None


class TargetComparisonResponse(TargetSchema):
    node_changes: Annotated[list[TargetNodeChangeResponse], Field(max_length=512)]
    constraint_changes: Annotated[list[TargetConstraintChangeResponse], Field(max_length=512)]
    exclusion_changes: Annotated[list[TargetExclusionChangeResponse], Field(max_length=512)]
    effective_time_changed: StrictBool


class TargetVersionComparisonResponse(TargetSchema):
    portfolio_id: UUIDString
    left_version_id: UUIDString
    right_version_id: UUIDString
    left_effective_at: AwareInstant
    right_effective_at: AwareInstant
    comparison: TargetComparisonResponse
