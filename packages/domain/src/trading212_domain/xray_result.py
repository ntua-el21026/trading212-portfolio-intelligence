"""Immutable semantic calculation and bounded projections from retained compositions."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal
from uuid import UUID

from trading212_domain.enums import QualityState
from trading212_domain.values import CurrencyCode, Instant
from trading212_domain.xray import (
    AggregateCoefficient,
    Amount,
    HhiCoefficient,
    PathCoefficient,
    PositionRoot,
    RelativeCoefficient,
    ResidualCoefficient,
    RootCoefficient,
    SquareCoefficient,
    Weight,
    XrayBound,
    XrayDependencyKind,
    XrayDimension,
    XrayMoneyMetric,
    XrayPolicyVersion,
    XrayRatioMetric,
    XrayReason,
    XrayReconciliation,
    XrayRecord,
    XrayResidualKind,
    XraySourceDependency,
    XrayWarningCode,
)


@dataclass(frozen=True, slots=True)
class XraySelection(XrayRecord):
    key: str
    kind: XrayDependencyKind
    subject_id: UUID
    candidate_evidence_ids: tuple[UUID, ...]
    selected_evidence_ids: tuple[UUID, ...]
    reason: XrayReason | None


@dataclass(frozen=True, slots=True)
class XraySourceUse(XrayRecord):
    consumer_key: str
    kind: XrayDependencyKind
    source_reference_id: UUID
    evidence_id: UUID | None
    subject_id: UUID


@dataclass(frozen=True, slots=True)
class XrayFundEdge(XrayRecord):
    fund_instrument_id: UUID
    mapping_id: UUID
    candidate_id: UUID
    holding_id: UUID | None
    weight: Weight
    origin: Literal["holding", "header_cash", "header_unresolved", "remainder"] = "holding"


@dataclass(frozen=True, slots=True)
class XrayPathClassification(XrayRecord):
    dimension: XrayDimension
    bucket_key: str | None
    decision_key: str | None
    reason: XrayReason | None
    confidence: Weight | None


@dataclass(frozen=True, slots=True)
class XrayClassificationDecision(XrayRecord):
    key: str
    entity_id: UUID
    dimension: XrayDimension
    bucket_key: str | None
    assignment_ids: tuple[UUID, ...]
    evidence_ids: tuple[UUID, ...]
    source_reference_ids: tuple[UUID, ...]
    reason: XrayReason | None
    confidence: Weight | None


@dataclass(frozen=True, slots=True)
class XrayPathDimensionMetric(XrayRecord):
    dimension: XrayDimension
    normalized_known_weight: XrayRatioMetric


@dataclass(frozen=True, slots=True)
class XrayTerminalPath(XrayRecord):
    key: str
    root_key: str
    instrument_id: UUID | None
    entity_id: UUID | None
    explicit_cash: bool
    unresolved_reason: XrayReason | None
    fund_edges: tuple[XrayFundEdge, ...]
    relative_coefficient: RelativeCoefficient
    money_coefficient: PathCoefficient | None
    identity_decision_ids: tuple[UUID, ...]
    source_reference_ids: tuple[UUID, ...]
    classifications: tuple[XrayPathClassification, ...]
    quality: QualityState
    confidence: Weight | None
    reporting_value: XrayMoneyMetric
    absolute_weight: XrayRatioMetric
    relative_weight: XrayRatioMetric
    dimension_weights: tuple[XrayPathDimensionMetric, ...]


@dataclass(frozen=True, slots=True)
class XrayRootExact(XrayRecord):
    root_key: str
    money_coefficient: RootCoefficient | None


@dataclass(frozen=True, slots=True)
class XrayBucketExact(XrayRecord):
    dimension: XrayDimension
    bucket_key: str
    direct_coefficient: AggregateCoefficient
    indirect_coefficient: AggregateCoefficient


@dataclass(frozen=True, slots=True)
class XrayDimensionExact(XrayRecord):
    dimension: XrayDimension
    known_coefficient: AggregateCoefficient
    cash_coefficient: AggregateCoefficient
    unresolved_coefficient: AggregateCoefficient


@dataclass(frozen=True, slots=True)
class XrayExactState(XrayRecord):
    roots: tuple[XrayRootExact, ...]
    portfolio_coefficient: AggregateCoefficient | None
    buckets: tuple[XrayBucketExact, ...]
    dimensions: tuple[XrayDimensionExact, ...]
    duplication_coefficient: AggregateCoefficient
    hhi_coefficient: HhiCoefficient
    portfolio_square_coefficient: SquareCoefficient | None
    visited_paths: int


@dataclass(frozen=True, slots=True)
class XrayExposureBucket(XrayRecord):
    dimension: XrayDimension
    bucket_key: str
    direct: XrayMoneyMetric
    indirect: XrayMoneyMetric
    effective: XrayMoneyMetric
    absolute_weight: XrayRatioMetric
    direct_weight: XrayRatioMetric
    indirect_weight: XrayRatioMetric
    confidence: Weight | None
    normalized_known_weight: XrayRatioMetric
    path_keys: tuple[str, ...]
    source_reference_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class XrayDimensionSummary(XrayRecord):
    dimension: XrayDimension
    known: XrayMoneyMetric
    cash: XrayMoneyMetric
    unresolved: XrayMoneyMetric
    known_weight: XrayRatioMetric
    cash_weight: XrayRatioMetric
    unresolved_weight: XrayRatioMetric
    complete: bool
    positive_unresolved_below_quantum: bool


@dataclass(frozen=True, slots=True)
class XrayTopConcentration(XrayRecord):
    count: int
    entity_ids: tuple[UUID, ...]
    weight: XrayRatioMetric


@dataclass(frozen=True, slots=True)
class XrayThresholdConclusion(XrayRecord):
    metric: str
    breached: bool | None
    reason: XrayReason | None
    bound: XrayBound


@dataclass(frozen=True, slots=True)
class XrayQualityCoverage(XrayRecord):
    """Overlapping quality measures; none is an additional economic partition."""

    root_count: int
    valued_root_count: int
    direct_portfolio_value: XrayMoneyMetric
    direct_portfolio_weight: XrayRatioMetric
    inferred_mapping_count: int
    inferred_value: XrayMoneyMetric
    inferred_weight: XrayRatioMetric
    stale_value: XrayMoneyMetric
    stale_weight: XrayRatioMetric


@dataclass(frozen=True, slots=True)
class XrayPortfolioSummary(XrayRecord):
    total: XrayMoneyMetric
    company_known_weight: XrayRatioMetric
    cash_weight: XrayRatioMetric
    unresolved_weight: XrayRatioMetric
    duplicated_exposure: XrayRatioMetric
    top_concentrations: tuple[XrayTopConcentration, ...]
    hhi: XrayRatioMetric
    thresholds: tuple[XrayThresholdConclusion, ...]
    quality_coverage: XrayQualityCoverage


@dataclass(frozen=True, slots=True)
class XrayDisplayResidual(XrayRecord):
    key: str
    coefficient: ResidualCoefficient
    child_count: int
    parent_separately_rounded: bool
    value: Amount
    currency: CurrencyCode | None
    kind: XrayResidualKind
    consumer_key: str


@dataclass(frozen=True, slots=True)
class XrayHeldFund(XrayRecord):
    instrument_id: UUID
    root_keys: tuple[str, ...]
    composition_root_key: str


@dataclass(frozen=True, slots=True)
class XrayFundEntity(XrayRecord):
    entity_id: UUID
    relative_coefficient: RelativeCoefficient
    weight: XrayRatioMetric
    path_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FundComposition(XrayRecord):
    fund_instrument_id: UUID
    composition_root_key: str
    entities: tuple[XrayFundEntity, ...]
    cash_coefficient: RelativeCoefficient
    unresolved_coefficient: RelativeCoefficient
    cash_weight: XrayRatioMetric
    unresolved_weight: XrayRatioMetric
    coverage: XrayRatioMetric
    complete: bool
    path_keys: tuple[str, ...]
    source_reference_ids: tuple[UUID, ...]
    quality: QualityState
    confidence: Weight | None


@dataclass(frozen=True, slots=True)
class XrayDirectPosition(XrayRecord):
    root: PositionRoot
    reporting_value: XrayMoneyMetric
    absolute_weight: XrayRatioMetric
    is_fund: bool
    source_reference_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class XrayWarning(XrayRecord):
    code: XrayWarningCode
    reason: XrayReason | None
    source_reference_ids: tuple[UUID, ...]
    path_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class XrayCalculation(XrayRecord):
    input_digest: str
    owner_id: UUID
    account_id: UUID
    snapshot_id: UUID
    valuation_at: Instant
    source_cutoff_at: Instant
    quality_evaluated_at: Instant
    warnings: tuple[XrayWarning, ...]
    reporting_currency: CurrencyCode
    policy: XrayPolicyVersion
    selections: tuple[XraySelection, ...]
    classification_decisions: tuple[XrayClassificationDecision, ...]
    typed_source_uses: tuple[XraySourceUse, ...]
    source_dependencies: tuple[XraySourceDependency, ...]
    portfolio_summary: XrayPortfolioSummary
    reconciliation: XrayReconciliation
    direct_positions: tuple[XrayDirectPosition, ...]
    dimensions: tuple[XrayDimensionSummary, ...]
    exposure_buckets: tuple[XrayExposureBucket, ...]
    terminal_paths: tuple[XrayTerminalPath, ...]
    held_funds: tuple[XrayHeldFund, ...]
    fund_compositions: tuple[FundComposition, ...]
    exact_state: XrayExactState
    residuals: tuple[XrayDisplayResidual, ...]

    @property
    def content_digest(self) -> str:
        from trading212_domain.xray_codec import encode_xray_result

        return sha256(encode_xray_result(self)).hexdigest()


@dataclass(frozen=True, slots=True)
class CanonicalFundPair(XrayRecord):
    first_fund_id: UUID
    second_fund_id: UUID


@dataclass(frozen=True, slots=True)
class CanonicalOverlapPair(XrayRecord):
    pair: CanonicalFundPair
    result_digest: str
    overlap_coefficient: RelativeCoefficient
    overlap: XrayRatioMetric
    first_coverage: XrayRatioMetric
    second_coverage: XrayRatioMetric
    first_root_key: str
    second_root_key: str
    common_entity_count: int


@dataclass(frozen=True, slots=True)
class CanonicalCommonEntity(XrayRecord):
    entity_id: UUID
    first_coefficient: RelativeCoefficient
    second_coefficient: RelativeCoefficient
    common_coefficient: RelativeCoefficient
    first_weight: XrayRatioMetric
    second_weight: XrayRatioMetric
    common_weight: XrayRatioMetric


@dataclass(frozen=True, slots=True)
class CanonicalCommonEntities(XrayRecord):
    pair: CanonicalOverlapPair
    entities: tuple[CanonicalCommonEntity, ...]


@dataclass(frozen=True, slots=True)
class CompanyExposureBasis(XrayRecord):
    result_digest: str
    input_digest: str
    reporting_currency: CurrencyCode
    total: XrayMoneyMetric
    coverage: XrayRatioMetric
    exposures: tuple[XrayExposureBucket, ...]
    exact_buckets: tuple[XrayBucketExact, ...]
    source_reference_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class XrayCommonEntitiesTop(XrayRecord):
    items: tuple[CanonicalCommonEntity, ...]
    total_count: int
    returned_count: int
    omitted_count: int
    omitted_common_weight: XrayRatioMetric
