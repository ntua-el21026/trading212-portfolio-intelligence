"""Closed X-ray wire contracts shared by HTTP, MCP and generated web clients."""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from .sources import SourceFreshness, SourceKey, SourceLicense, SourceQuality
from .targets import (
    AwareInstant,
    CurrencyString,
    Cursor,
    DecimalString,
    Digest,
    UUIDString,
    WeightString,
)

XrayDimension = Literal["company", "sector", "industry", "country", "region", "currency"]


def _integer_selector(value: object) -> object:
    if type(value) is int:
        return value
    if isinstance(value, str) and len(value) <= 3 and re.fullmatch(r"[1-9][0-9]*", value):
        return int(value)
    raise ValueError("A bounded positive integer selector is required.")


def _boolean_selector(value: object) -> object:
    if type(value) is bool:
        return value
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError("A boolean selector must be true or false.")


XrayPageLimit = Annotated[StrictInt, Field(ge=1, le=100), BeforeValidator(_integer_selector)]
XrayTop = Annotated[StrictInt, Field(ge=1, le=50), BeforeValidator(_integer_selector)]
XrayQueryBoolean = Annotated[StrictBool, BeforeValidator(_boolean_selector)]


class XraySchema(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def no_unknown_field_reflection(cls, value: object) -> object:
        if isinstance(value, dict) and any(key not in cls.model_fields for key in value):
            raise ValueError("The bounded X-ray object contains unexpected fields.")
        return value


class XraySnapshotRequest(XraySchema):
    snapshot_id: UUIDString
    source_cutoff_at: AwareInstant


class XrayRunQuery(XraySnapshotRequest):
    reporting_currency: CurrencyString
    run_id: UUIDString | None = None
    cursor: Cursor | None = None
    limit: XrayPageLimit = 25


class XrayEffectiveExposureQuery(XrayRunQuery):
    view: Literal["exposures", "paths", "held_funds"] = "exposures"
    dimension: XrayDimension | None = Field(
        default=None, description="Defaults to company for exposure and path views."
    )
    normalized_known_only: XrayQueryBoolean | None = Field(
        default=None, description="Defaults to false for exposure and path views."
    )
    exposure_id: UUIDString | None = None

    @model_validator(mode="after")
    def closed_view(self) -> Self:
        if self.view == "held_funds" and any(
            v is not None for v in (self.dimension, self.normalized_known_only, self.exposure_id)
        ):
            raise ValueError("Held-fund discovery does not accept exposure selectors.")
        if self.view != "paths" and self.exposure_id is not None:
            raise ValueError("An exposure filter is valid only for path detail.")
        if self.view == "paths" and self.run_id is None and self.cursor is None:
            raise ValueError("Path detail requires a retained run pin.")
        return self


class XrayEtfOverlapQuery(XrayRunQuery):
    fund_ids: Annotated[list[UUIDString], Field(min_length=2, max_length=32)]
    view: Literal["pairs", "common_entities"] = "pairs"
    left_fund_id: UUIDString | None = None
    right_fund_id: UUIDString | None = None

    @model_validator(mode="after")
    def closed_pair(self) -> Self:
        if len(set(self.fund_ids)) != len(self.fund_ids):
            raise ValueError("Selected fund IDs must be unique.")
        if self.view == "pairs":
            if self.left_fund_id is not None or self.right_fund_id is not None:
                raise ValueError("Pair lists do not accept common-entity selectors.")
        else:
            if (
                self.left_fund_id is None
                or self.right_fund_id is None
                or self.left_fund_id == self.right_fund_id
                or self.left_fund_id not in self.fund_ids
                or self.right_fund_id not in self.fund_ids
            ):
                raise ValueError("Select one distinct pair from the requested held funds.")
            if self.run_id is None and self.cursor is None:
                raise ValueError("Common-entity detail requires a retained run pin.")
        return self


class XrayConstituentSnapshotQuery(XraySchema):
    account_id: UUIDString | None = None
    run_id: UUIDString | None = None

    @model_validator(mode="after")
    def dependent_scope(self) -> Self:
        if (self.account_id is None) != (self.run_id is None):
            raise ValueError("Dependent source detail requires both account and run.")
        return self


class XrayConstituentHoldingsQuery(XrayConstituentSnapshotQuery):
    cursor: Cursor | None = None
    limit: XrayPageLimit = 25


class XrayMcpEffectiveExposureQuery(XraySnapshotRequest):
    reporting_currency: CurrencyString
    dimension: XrayDimension = "company"
    cursor: Cursor | None = None
    limit: XrayPageLimit = 25


class XrayMcpOverlapQuery(XraySnapshotRequest):
    left_fund_id: UUIDString
    right_fund_id: UUIDString
    top_n: XrayTop = 25

    @model_validator(mode="after")
    def distinct_pair(self) -> Self:
        if self.left_fund_id == self.right_fund_id:
            raise ValueError("Select two distinct held funds.")
        return self


XrayReason = Literal[
    "missing_value",
    "missing_fx",
    "incomplete_valuation",
    "zero_denominator",
    "missing_mapping",
    "missing_source",
    "source_gap",
    "ambiguous_source",
    "missing_identity",
    "ambiguous_identity",
    "missing_classification",
    "ambiguous_classification",
    "source_remainder",
    "depth_limit",
    "path_limit",
    "proof_limit",
    "cycle",
    "partial_basis",
    "unconfigured",
    "inconclusive_lower_bound",
    "reconciliation_difference",
]
XrayDependencyKind = Literal[
    "valuation",
    "fx",
    "broker_fx",
    "fund_definition",
    "fund_mapping",
    "constituents",
    "identity",
    "relationship",
    "classification",
    "threshold",
    "reconciliation",
]
XrayWarningCode = Literal[
    "source_date_mismatch",
    "stale_source",
    "estimated_source",
    "partial_source",
    "unreconciled_value",
    "missing_input",
    "unknown_confidence",
    "bounded_traversal",
    "ambiguous_evidence",
]
XrayLabel = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=300, pattern=r"^[^\x00]*$")
]
XrayKey = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=512, pattern=r"^[A-Za-z0-9._:/-]+$"),
]
XrayCount = Annotated[StrictInt, Field(ge=0, le=100_000)]
XrayPathCount = Annotated[StrictInt, Field(ge=0, le=10_000)]
XrayBound = Literal["exact", "lower_bound"]


class XrayMetric(XraySchema):
    reason: XrayReason | None
    quality: SourceQuality
    bound: XrayBound
    availability: Literal["available", "unavailable"]
    confidence: WeightString | None
    source_reference_ids: Annotated[list[UUIDString], Field(max_length=64)]
    source_count: XrayCount
    source_omitted_count: XrayCount

    @model_validator(mode="after")
    def source_preview(self) -> Self:
        if len(self.source_reference_ids) + self.source_omitted_count != self.source_count:
            raise ValueError("Metric source preview counts disagree.")
        if (self.availability == "unavailable") != (getattr(self, "value", None) is None):
            raise ValueError("Metric availability and value disagree.")
        return self


class XrayMoney(XraySchema):
    amount: DecimalString
    currency: CurrencyString


class XrayMoneyMetric(XrayMetric):
    value: XrayMoney | None
    origin: Literal[
        "observed_provider",
        "normalized_provider",
        "derived_deterministic",
        "estimated",
        "unavailable",
    ]


class XrayRatioMetric(XrayMetric):
    value: WeightString | None
    positive_below_quantum: StrictBool

    @model_validator(mode="after")
    def positive_quantum(self) -> Self:
        if self.positive_below_quantum and self.value not in ("0", "0.000000000000000000"):
            raise ValueError("A below-quantum metric must have a zero display value.")
        return self


class XraySourceReference(XraySchema):
    id: UUIDString
    kind: XrayDependencyKind
    subject_id: UUIDString
    content_digest: Digest
    source_at: AwareInstant | None
    first_observed_at: AwareInstant | None
    provider_id: SourceKey | None
    provider_name: XrayLabel | None
    license_version_id: UUIDString | None
    confidence: WeightString | None
    quality: SourceQuality


class XrayWarning(XraySchema):
    code: XrayWarningCode
    reason: XrayReason | None
    source_reference_ids: Annotated[list[UUIDString], Field(max_length=64)]
    source_count: XrayCount
    source_omitted_count: XrayCount
    path_keys: Annotated[list[XrayKey], Field(max_length=64)]
    path_count: XrayPathCount
    path_omitted_count: XrayPathCount

    @model_validator(mode="after")
    def preview_counts(self) -> Self:
        if (
            len(self.source_reference_ids) + self.source_omitted_count != self.source_count
            or len(self.path_keys) + self.path_omitted_count != self.path_count
        ):
            raise ValueError("Warning preview counts disagree.")
        return self


class XrayResidual(XraySchema):
    key: XrayKey
    value: DecimalString
    currency: CurrencyString | None
    kind: Literal[
        "money_partition",
        "weight_partition",
        "parent_child",
        "unit_parent_child",
        "direct_indirect",
    ]
    consumer_key: XrayKey
    child_count: XrayPathCount
    parent_separately_rounded: StrictBool


class XrayMethod(XraySchema):
    name: Literal["xray_v1"]
    version: Literal["1.1.0"]
    numeric_policy: Literal["xray_decimal256_exact_q18_v1"]
    traversal_policy: Literal["xray_position_then_cash_uuid_v1"]


class XrayPolicyReference(XraySchema):
    kind: Literal[
        "calculation",
        "provider_selection",
        "identity",
        "classification",
        "freshness",
        "quality",
        "traversal",
        "threshold",
    ]
    id: SourceKey
    version: SourceKey


class XrayAccess(XraySchema):
    reproducibility: Literal["reproducible", "inputs_expired", "license_restricted"]
    status_reference_at: AwareInstant | None


class XrayContext(XraySchema):
    account_id: UUIDString
    snapshot_id: UUIDString
    run_id: UUIDString
    input_snapshot_id: UUIDString
    input_digest: Digest
    content_digest: Digest
    valuation_at: AwareInstant
    source_cutoff_at: AwareInstant
    reporting_currency: CurrencyString
    calculated_at: AwareInstant
    quality_evaluated_at: AwareInstant
    method: XrayMethod
    policies: Annotated[list[XrayPolicyReference], Field(max_length=8)]
    sources: Annotated[list[XraySourceReference], Field(max_length=64)]
    source_count: XrayCount
    source_omitted_count: XrayCount
    warnings: Annotated[list[XrayWarning], Field(max_length=64)]
    warning_count: XrayCount
    warning_omitted_count: XrayCount
    residuals: Annotated[list[XrayResidual], Field(max_length=64)]
    residual_count: XrayCount
    residual_omitted_count: XrayCount
    access: XrayAccess

    @model_validator(mode="after")
    def preview_counts(self) -> Self:
        for items, count, omitted in (
            (self.sources, self.source_count, self.source_omitted_count),
            (self.warnings, self.warning_count, self.warning_omitted_count),
            (self.residuals, self.residual_count, self.residual_omitted_count),
        ):
            if len(items) + omitted != count:
                raise ValueError("X-ray context preview counts disagree.")
        return self


class XrayTopConcentration(XraySchema):
    count: Annotated[StrictInt, Field(ge=1, le=50)]
    entity_ids: Annotated[list[UUIDString], Field(max_length=50)]
    weight: XrayRatioMetric


class XrayThresholdConclusion(XraySchema):
    metric: SourceKey
    breached: StrictBool | None
    reason: XrayReason | None
    bound: XrayBound


class XrayQualityCoverage(XraySchema):
    root_count: XrayPathCount
    valued_root_count: XrayPathCount
    direct_portfolio_value: XrayMoneyMetric
    direct_portfolio_weight: XrayRatioMetric
    inferred_mapping_count: XrayCount
    inferred_value: XrayMoneyMetric
    inferred_weight: XrayRatioMetric
    stale_value: XrayMoneyMetric
    stale_weight: XrayRatioMetric

    @model_validator(mode="after")
    def valued_roots_are_bounded(self) -> Self:
        if self.valued_root_count > self.root_count:
            raise ValueError("Valued roots exceed the complete root inventory.")
        return self


class XrayPortfolioSummary(XraySchema):
    total: XrayMoneyMetric
    company_known_weight: XrayRatioMetric
    cash_weight: XrayRatioMetric
    unresolved_weight: XrayRatioMetric
    duplicated_exposure: XrayRatioMetric
    top_concentrations: Annotated[list[XrayTopConcentration], Field(max_length=50)]
    hhi: XrayRatioMetric
    thresholds: Annotated[list[XrayThresholdConclusion], Field(max_length=52)]
    quality_coverage: XrayQualityCoverage


class XrayDimensionSummary(XraySchema):
    dimension: XrayDimension
    known: XrayMoneyMetric
    cash: XrayMoneyMetric
    unresolved: XrayMoneyMetric
    known_weight: XrayRatioMetric
    cash_weight: XrayRatioMetric
    unresolved_weight: XrayRatioMetric
    complete: StrictBool
    positive_unresolved_below_quantum: StrictBool


class XrayExposureRow(XraySchema):
    id: UUIDString
    dimension: XrayDimension
    bucket_key: XrayKey
    name: XrayLabel
    direct: XrayMoneyMetric
    indirect: XrayMoneyMetric
    effective: XrayMoneyMetric
    direct_weight: XrayRatioMetric
    indirect_weight: XrayRatioMetric
    absolute_weight: XrayRatioMetric
    normalized_known_weight: XrayRatioMetric | None
    path_count: XrayPathCount
    residuals: Annotated[list[XrayResidual], Field(max_length=8)]
    confidence: WeightString | None
    quality: SourceQuality


class XrayPositionRoot(XraySchema):
    position_id: UUIDString
    instrument_id: UUIDString
    listing_id: UUIDString | None


class XrayCashRoot(XraySchema):
    snapshot_cash_id: UUIDString
    original_currency: CurrencyString


class XrayFundEdge(XraySchema):
    origin: Literal["holding", "header_cash", "header_unresolved", "remainder"]
    fund_instrument_id: UUIDString
    mapping_id: UUIDString
    candidate_id: UUIDString
    holding_id: UUIDString | None
    weight: WeightString


class XrayPathClassification(XraySchema):
    dimension: XrayDimension
    bucket_key: XrayKey | None
    decision_key: XrayKey | None
    reason: XrayReason | None
    confidence: WeightString | None


class XrayPathRow(XraySchema):
    id: UUIDString
    key: XrayKey
    root_key: XrayKey
    root: XrayPositionRoot | XrayCashRoot
    instrument_id: UUIDString | None
    entity_id: UUIDString | None
    name: XrayLabel
    explicit_cash: StrictBool
    unresolved_reason: XrayReason | None
    fund_edges: Annotated[list[XrayFundEdge], Field(max_length=4)]
    reporting_value: XrayMoneyMetric
    absolute_weight: XrayRatioMetric
    relative_weight: XrayRatioMetric
    normalized_known_weight: XrayRatioMetric | None
    classification: XrayPathClassification | None
    identity_decision_ids: Annotated[list[UUIDString], Field(max_length=256)]
    source_reference_ids: Annotated[list[UUIDString], Field(max_length=256)]
    sources: Annotated[list[XraySourceReference], Field(max_length=256)]
    residuals: Annotated[list[XrayResidual], Field(max_length=16)]
    quality: SourceQuality
    confidence: WeightString | None

    @model_validator(mode="after")
    def complete_proof(self) -> Self:
        if (
            len(set(self.source_reference_ids)) != len(self.source_reference_ids)
            or set(self.source_reference_ids) != {source.id for source in self.sources}
            or len(self.sources) != len(self.source_reference_ids)
        ):
            raise ValueError("The complete path source proof is required.")
        return self


class XrayHeldFund(XraySchema):
    instrument_id: UUIDString
    name: XrayLabel
    position_count: Annotated[StrictInt, Field(ge=1, le=10_000)]
    composition_root_key: XrayKey
    constituent_snapshot_id: UUIDString | None
    source_at: AwareInstant | None
    unit_coverage: XrayRatioMetric
    cash_weight: XrayRatioMetric
    unresolved_weight: XrayRatioMetric
    complete: StrictBool
    quality: SourceQuality
    confidence: WeightString | None


class XrayOverlapPair(XraySchema):
    id: UUIDString
    left: XrayHeldFund
    right: XrayHeldFund
    overlap: XrayRatioMetric
    common_entity_count: XrayPathCount


class XrayCommonEntity(XraySchema):
    id: UUIDString
    entity_id: UUIDString
    name: XrayLabel
    left_weight: XrayRatioMetric
    right_weight: XrayRatioMetric
    common_weight: XrayRatioMetric


class XrayPage[T](XraySchema):
    items: Annotated[list[T], Field(max_length=100)]
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: XrayCount

    @model_validator(mode="after")
    def page_bounds(self) -> Self:
        if len(self.items) > self.limit or len(self.items) > self.total:
            raise ValueError("X-ray page bounds disagree.")
        return self


class XrayExposuresResponse(XraySchema):
    context: XrayContext
    summary: XrayPortfolioSummary
    dimension_summary: XrayDimensionSummary
    dimension_residuals: Annotated[list[XrayResidual], Field(max_length=8)]
    normalized_known_only: StrictBool
    exposures: XrayPage[XrayExposureRow]
    view: Literal["exposures"]


class XrayPathsResponse(XraySchema):
    context: XrayContext
    summary: XrayPortfolioSummary
    dimension_summary: XrayDimensionSummary
    dimension_residuals: Annotated[list[XrayResidual], Field(max_length=8)]
    normalized_known_only: StrictBool
    paths: XrayPage[XrayPathRow]
    view: Literal["paths"]


class XrayHeldFundsResponse(XraySchema):
    context: XrayContext
    summary: XrayPortfolioSummary
    held_funds: XrayPage[XrayHeldFund]
    view: Literal["held_funds"]


type XrayEffectiveExposureResponse = Annotated[
    XrayExposuresResponse | XrayPathsResponse | XrayHeldFundsResponse, Field(discriminator="view")
]


class XrayOverlapPairsResponse(XraySchema):
    context: XrayContext
    summary: XrayPortfolioSummary
    selected_fund_ids: Annotated[list[UUIDString], Field(min_length=2, max_length=32)]
    pairs: XrayPage[XrayOverlapPair]
    view: Literal["pairs"]


class XrayCommonEntitiesResponse(XraySchema):
    context: XrayContext
    summary: XrayPortfolioSummary
    selected_fund_ids: Annotated[list[UUIDString], Field(min_length=2, max_length=32)]
    pair: XrayOverlapPair
    common_entities: XrayPage[XrayCommonEntity]
    view: Literal["common_entities"]


type XrayEtfOverlapResponse = Annotated[
    XrayOverlapPairsResponse | XrayCommonEntitiesResponse, Field(discriminator="view")
]


class XrayMcpTopPairResponse(XraySchema):
    context: XrayContext
    summary: XrayPortfolioSummary
    pair: XrayOverlapPair
    common_entities: Annotated[list[XrayCommonEntity], Field(max_length=50)]
    total_count: XrayPathCount
    returned_count: Annotated[StrictInt, Field(ge=0, le=50)]
    omitted_count: XrayPathCount
    omitted_common_weight: XrayRatioMetric
    view: Literal["mcp_top_pair"]

    @model_validator(mode="after")
    def exact_counts(self) -> Self:
        if (
            len(self.common_entities) != self.returned_count
            or self.returned_count + self.omitted_count != self.total_count
        ):
            raise ValueError("MCP common-entity preview counts disagree.")
        return self


class XrayConstituentSnapshotHeader(XraySchema):
    id: UUIDString
    fund_instrument_id: UUIDString
    fund_name: XrayLabel
    fund_mapping_id: UUIDString
    source_at: AwareInstant
    first_observed_at: AwareInstant
    content_digest: Digest
    provider_id: UUIDString
    provider_name: XrayLabel
    license: SourceLicense
    holding_count: XrayCount
    known_weight: WeightString | None
    unresolved_weight: WeightString | None
    cash_weight: WeightString | None
    quality: SourceQuality
    confidence: WeightString | None
    freshness: SourceFreshness
    freshness_evaluated_at: AwareInstant
    access: XrayAccess


class XrayConstituentHolding(XraySchema):
    id: UUIDString
    source_key: SourceKey
    weight: WeightString
    state: Literal["resolved", "cash", "unresolved"]
    currency: CurrencyString
    instrument_id: UUIDString | None
    entity_id: UUIDString | None
    name: XrayLabel | None
    confidence: WeightString | None
    evidence_key: SourceKey | None


class XrayConstituentHoldingPage(XrayPage[XrayConstituentHolding]):
    snapshot_id: UUIDString
