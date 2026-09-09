"""Closed immutable X-ray capture vocabulary; no transport or current principal state."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from trading212_domain.enums import QualityState, ValueOrigin
from trading212_domain.sources import ObservationState
from trading212_domain.values import CurrencyCode, Instant, Money

# Metadata describes closed financial roles, not an extensible expression language.
Amount = Annotated[Decimal, "amount"]
Weight = Annotated[Decimal, "weight"]
RootCoefficient = Annotated[Decimal, "root_coefficient"]
RelativeCoefficient = Annotated[Decimal, "relative_coefficient"]
PathCoefficient = Annotated[Decimal, "path_coefficient"]
AggregateCoefficient = Annotated[Decimal, "aggregate_coefficient"]
SquareCoefficient = Annotated[Decimal, "square_coefficient"]
HhiCoefficient = Annotated[Decimal, "hhi_coefficient"]
ResidualCoefficient = Annotated[Decimal, "residual_coefficient"]


class XrayRecord:
    """Validate each newly built record against its closed field and local invariants."""

    __slots__ = ()

    def __post_init__(self) -> None:
        from trading212_domain.xray_validation import validate_record

        validate_record(self)


class XrayDimension(StrEnum):
    COMPANY = "company"
    SECTOR = "sector"
    INDUSTRY = "industry"
    COUNTRY = "country"
    REGION = "region"
    CURRENCY = "currency"


class XrayReason(StrEnum):
    MISSING_VALUE = "missing_value"
    MISSING_FX = "missing_fx"
    INCOMPLETE_VALUATION = "incomplete_valuation"
    ZERO_DENOMINATOR = "zero_denominator"
    MISSING_MAPPING = "missing_mapping"
    MISSING_SOURCE = "missing_source"
    SOURCE_GAP = "source_gap"
    AMBIGUOUS_SOURCE = "ambiguous_source"
    MISSING_IDENTITY = "missing_identity"
    AMBIGUOUS_IDENTITY = "ambiguous_identity"
    MISSING_CLASSIFICATION = "missing_classification"
    AMBIGUOUS_CLASSIFICATION = "ambiguous_classification"
    SOURCE_REMAINDER = "source_remainder"
    DEPTH_LIMIT = "depth_limit"
    PATH_LIMIT = "path_limit"
    PROOF_LIMIT = "proof_limit"
    CYCLE = "cycle"
    PARTIAL_BASIS = "partial_basis"
    UNCONFIGURED = "unconfigured"
    INCONCLUSIVE_LOWER_BOUND = "inconclusive_lower_bound"
    RECONCILIATION_DIFFERENCE = "reconciliation_difference"


class XrayResidualKind(StrEnum):
    MONEY_PARTITION = "money_partition"
    WEIGHT_PARTITION = "weight_partition"
    PARENT_CHILD = "parent_child"
    UNIT_PARENT_CHILD = "unit_parent_child"
    DIRECT_INDIRECT = "direct_indirect"


class XrayWarningCode(StrEnum):
    SOURCE_DATE_MISMATCH = "source_date_mismatch"
    STALE_SOURCE = "stale_source"
    ESTIMATED_SOURCE = "estimated_source"
    PARTIAL_SOURCE = "partial_source"
    UNRECONCILED_VALUE = "unreconciled_value"
    MISSING_INPUT = "missing_input"
    UNKNOWN_CONFIDENCE = "unknown_confidence"
    BOUNDED_TRAVERSAL = "bounded_traversal"
    AMBIGUOUS_EVIDENCE = "ambiguous_evidence"


class XrayAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class XrayBound(StrEnum):
    EXACT = "exact"
    LOWER_BOUND = "lower_bound"


class XraySourceState(StrEnum):
    AVAILABLE = "available"
    GAP = "gap"


class XraySubjectKind(StrEnum):
    LISTING = "listing"
    INSTRUMENT = "instrument"
    ENTITY = "entity"
    SNAPSHOT_POSITION = "snapshot_position"
    SNAPSHOT_CASH = "snapshot_cash"
    FUND_MAPPING = "fund_mapping"
    POLICY = "policy"
    SOURCE_RECORD = "source_record"


class XrayReferenceKind(StrEnum):
    SNAPSHOT_POSITION = "snapshot_position"
    SNAPSHOT_CASH = "snapshot_cash"
    PORTFOLIO_SNAPSHOT = "portfolio_snapshot"
    CALCULATION_RUN = "calculation_run"
    BROKER_SOURCE_RECORD = "broker_source_record"
    RECONCILIATION_RUN = "reconciliation_run"
    RECONCILIATION_DISCREPANCY = "reconciliation_discrepancy"
    OWNER_POLICY = "owner_policy"
    PRICE_SNAPSHOT = "price_snapshot"
    PRICE_OBSERVATION = "price_observation"
    FX_SNAPSHOT = "fx_snapshot"
    FX_OBSERVATION = "fx_observation"
    FX_COVERAGE_GAP = "fx_coverage_gap"
    FUND_DEFINITION = "fund_definition"
    FUND_MAPPING = "fund_mapping"
    CONSTITUENT_SNAPSHOT = "constituent_snapshot"
    CONSTITUENT_HOLDING = "constituent_holding"
    ENTITY_EVIDENCE_VERSION = "entity_evidence_version"
    ENTITY_EVIDENCE_REFERENCE = "entity_evidence_reference"
    RELATIONSHIP = "relationship"
    CLASSIFICATION_SNAPSHOT = "classification_snapshot"
    CLASSIFICATION_ASSIGNMENT = "classification_assignment"


class XrayDependencyKind(StrEnum):
    VALUATION = "valuation"
    FX = "fx"
    BROKER_FX = "broker_fx"
    FUND_DEFINITION = "fund_definition"
    FUND_MAPPING = "fund_mapping"
    CONSTITUENTS = "constituents"
    IDENTITY = "identity"
    RELATIONSHIP = "relationship"
    CLASSIFICATION = "classification"
    THRESHOLD = "threshold"
    RECONCILIATION = "reconciliation"


class XrayHoldingKind(StrEnum):
    INSTRUMENT = "instrument"
    ENTITY = "entity"
    CASH = "cash"
    UNRESOLVED = "unresolved"


class XrayRelationshipKind(StrEnum):
    LISTING_OF = "listing_of"
    SHARE_CLASS = "share_class_of"
    DEPOSITARY_RECEIPT = "depositary_receipt_of"
    ISSUER_PARENT = "issuer_parent"


class XrayComparison(StrEnum):
    GT = "gt"
    GE = "ge"


@dataclass(frozen=True, slots=True)
class XrayMoneyMetric(XrayRecord):
    value: Money | None
    reason: XrayReason | None
    quality: QualityState
    origin: ValueOrigin
    bound: XrayBound
    availability: XrayAvailability
    confidence: Weight | None
    source_reference_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class XrayRatioMetric(XrayRecord):
    value: Weight | None
    reason: XrayReason | None
    quality: QualityState
    bound: XrayBound
    availability: XrayAvailability
    confidence: Weight | None
    source_reference_ids: tuple[UUID, ...] = ()
    positive_below_quantum: bool = False


@dataclass(frozen=True, slots=True)
class PositionRoot(XrayRecord):
    position_id: UUID
    instrument_id: UUID
    listing_id: UUID | None

    @property
    def key(self) -> str:
        return f"position:{self.position_id}"


@dataclass(frozen=True, slots=True)
class CashRoot(XrayRecord):
    snapshot_cash_id: UUID
    original_currency: CurrencyCode

    @property
    def key(self) -> str:
        return f"cash:{self.snapshot_cash_id}"


@dataclass(frozen=True, slots=True)
class XrayPosition(XrayRecord):
    root: PositionRoot
    original_value: XrayMoneyMetric
    reporting_value: XrayMoneyMetric
    valuation_refs: tuple[UUID, ...]
    fx_refs: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class XrayCash(XrayRecord):
    root: CashRoot
    original_value: XrayMoneyMetric
    reporting_value: XrayMoneyMetric
    valuation_refs: tuple[UUID, ...]
    fx_refs: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class XrayPhysicalReference(XrayRecord):
    kind: XrayReferenceKind
    record_id: UUID
    parent_record_id: UUID | None


@dataclass(frozen=True, slots=True)
class XraySourceDependency(XrayRecord):
    id: UUID
    owner_id: UUID
    account_id: UUID
    snapshot_id: UUID
    kind: XrayDependencyKind
    subject_kind: XraySubjectKind
    subject_id: UUID
    provider_id: str | None
    license_version_id: UUID | None
    content_digest: str
    reference: XrayPhysicalReference


@dataclass(frozen=True, slots=True)
class XrayBrokerFx(XrayRecord):
    """Retained P1 wallet quote; verify the saved amount without converting it again."""

    root_key: str
    source_reference_id: UUID
    calculation_reference_id: UUID
    source_record_id: UUID
    calculation_run_id: UUID
    listing_id: UUID
    base_currency: CurrencyCode
    quote_currency: CurrencyCode
    rate: Amount
    observed_at: Instant
    source_observed_at: Instant
    source: str
    quality: QualityState
    confidence: Weight | None
    operation: Literal["multiply"] = "multiply"


@dataclass(frozen=True, slots=True)
class XrayFxLeg(XrayRecord):
    """One actual quote or coverage gap with its stored direction and receipt time."""

    source_reference_id: UUID
    snapshot_id: UUID
    observation_id: UUID | None
    base_currency: CurrencyCode
    quote_currency: CurrencyCode
    rate: Amount | None
    observed_at: Instant
    first_known_at: Instant
    operation: Literal["multiply", "divide"]
    quality: QualityState
    confidence: Weight | None

    state: ObservationState = ObservationState.AVAILABLE
    coverage_gap_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class XrayLicensedFx(XrayRecord):
    """Conversion of saved snapshot money, never a replacement for original broker FX."""

    consumer_key: str
    input_value: XrayMoneyMetric
    output_currency: CurrencyCode
    legs: tuple[XrayFxLeg, ...]


@dataclass(frozen=True, slots=True)
class XrayEvidence(XrayRecord):
    id: UUID
    source_reference_id: UUID
    effective_at: Instant
    first_known_at: Instant
    valid_until: Instant | None
    revision: int
    state: XraySourceState
    quality: QualityState
    confidence: Weight | None


@dataclass(frozen=True, slots=True)
class XrayProviderSelectionPolicy(XrayRecord):
    id: UUID
    version: str
    provider_order: tuple[str, ...]
    revision_rule: Literal["latest_effective_then_revision_v1"] = (
        "latest_effective_then_revision_v1"
    )
    gap_rule: Literal["preferred_provider_gap_blocks_fallback_v1"] = (
        "preferred_provider_gap_blocks_fallback_v1"
    )


@dataclass(frozen=True, slots=True)
class XrayIdentityPolicy(XrayRecord):
    id: UUID
    version: str
    rule: Literal["explicit_economic_entity_and_receipt_v1"] = (
        "explicit_economic_entity_and_receipt_v1"
    )


@dataclass(frozen=True, slots=True)
class XrayClassificationPolicy(XrayRecord):
    id: UUID
    version: str
    rule: Literal["entity_first_compatible_instrument_consensus_v1"] = (
        "entity_first_compatible_instrument_consensus_v1"
    )


@dataclass(frozen=True, slots=True)
class XrayTaxonomyVersion(XrayRecord):
    dimension: XrayDimension
    taxonomy_id: UUID
    version: str
    key: str


@dataclass(frozen=True, slots=True)
class XrayFreshnessPolicy(XrayRecord):
    id: UUID
    version: str
    stale_after_seconds: int
    evaluation_basis: Literal["valuation_at", "source_cutoff_at"]


@dataclass(frozen=True, slots=True)
class XrayQualityPolicy(XrayRecord):
    id: UUID
    version: str
    rule: Literal["complete_denominator_known_numerator_lower_bound_v1"] = (
        "complete_denominator_known_numerator_lower_bound_v1"
    )


@dataclass(frozen=True, slots=True)
class XrayTraversalPolicy(XrayRecord):
    id: UUID
    version: str
    rule: Literal["xray_position_then_cash_uuid_v1"] = "xray_position_then_cash_uuid_v1"
    max_fund_edges: Literal[4] = 4
    max_visited_paths: Literal[10000] = 10000
    max_identity_decisions: Literal[256] = 256
    max_source_references: Literal[256] = 256


@dataclass(frozen=True, slots=True)
class XrayLimits(XrayRecord):
    positions: Literal[10000] = 10000
    currencies: Literal[32] = 32
    constituent_snapshots: Literal[256] = 256
    constituent_rows: Literal[100000] = 100000
    identity_classification_rows: Literal[100000] = 100000
    selected_uses: Literal[100000] = 100000
    canonical_bytes: Literal[33554432] = 33554432
    singleton_bytes: Literal[2097152] = 2097152


@dataclass(frozen=True, slots=True)
class XrayUnconfiguredThresholds(XrayRecord):
    state: Literal["unconfigured"] = "unconfigured"


@dataclass(frozen=True, slots=True)
class ConcentrationThresholdPolicy(XrayRecord):
    id: UUID
    version: str
    source_reference_id: UUID
    top1_limit: Weight
    top5_limit: Weight
    hhi_limit: Weight
    top1_comparison: XrayComparison
    top5_comparison: XrayComparison
    hhi_comparison: XrayComparison
    state: Literal["configured"] = "configured"


@dataclass(frozen=True, slots=True)
class XrayPolicyVersion(XrayRecord):
    id: UUID
    version: str
    provider_selection_policy: XrayProviderSelectionPolicy
    identity_policy: XrayIdentityPolicy
    classification_policy: XrayClassificationPolicy
    taxonomy_versions: tuple[XrayTaxonomyVersion, ...]
    freshness_policy: XrayFreshnessPolicy
    quality_policy: XrayQualityPolicy
    traversal_policy: XrayTraversalPolicy
    thresholds: XrayUnconfiguredThresholds | ConcentrationThresholdPolicy
    limits: XrayLimits
    method_name: Literal["xray_v1"] = "xray_v1"
    method_version: Literal["1.1.0"] = "1.1.0"
    numeric_policy: Literal["xray_decimal256_exact_q18_v1"] = "xray_decimal256_exact_q18_v1"
    schema_version: Literal["1"] = "1"


@dataclass(frozen=True, slots=True)
class XrayFundDefinition(XrayRecord):
    instrument_id: UUID
    evidence: XrayEvidence


@dataclass(frozen=True, slots=True)
class XrayFundMapping(XrayRecord):
    id: UUID
    fund_instrument_id: UUID
    evidence: XrayEvidence


@dataclass(frozen=True, slots=True)
class XrayConstituentHolding(XrayRecord):
    id: UUID
    kind: XrayHoldingKind
    instrument_id: UUID | None
    listing_id: UUID | None
    weight: Weight
    entity_id: UUID | None
    source_key: str
    source_currency: CurrencyCode
    evidence_key: str | None
    confidence: Weight | None


@dataclass(frozen=True, slots=True)
class XrayConstituentCandidate(XrayRecord):
    id: UUID
    fund_mapping_id: UUID
    evidence: XrayEvidence
    holdings: tuple[XrayConstituentHolding, ...]
    stated_coverage: Weight | None
    unresolved_weight: Weight | None
    cash_weight: Weight | None
    coverage_rule: Literal["header_totals_inclusive_of_rows_v1"] = (
        "header_totals_inclusive_of_rows_v1"
    )
    page_chain_complete: Literal[True] = True


@dataclass(frozen=True, slots=True)
class XrayEntityEvidence(XrayRecord):
    instrument_id: UUID
    listing_id: UUID | None
    entity_id: UUID
    evidence: XrayEvidence


@dataclass(frozen=True, slots=True)
class XrayRelationshipVersion(XrayRecord):
    instrument_id: UUID | None
    underlying_instrument_id: UUID | None
    entity_id: UUID | None
    kind: XrayRelationshipKind
    units_per_receipt: Amount | None
    evidence: XrayEvidence
    listing_id: UUID | None = None
    share_class_id: UUID | None = None
    parent_entity_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class XrayClassificationAssignment(XrayRecord):
    id: UUID
    subject_kind: XraySubjectKind
    subject_id: UUID
    dimension: XrayDimension
    taxonomy_id: UUID
    taxonomy_version: str
    bucket_key: str
    confidence: Weight | None


@dataclass(frozen=True, slots=True)
class XrayClassificationSubject(XrayRecord):
    """A real requested/returned classification target, including empty source gaps."""

    subject_kind: XraySubjectKind
    subject_id: UUID
    dimension: XrayDimension
    taxonomy_id: UUID
    taxonomy_version: str


@dataclass(frozen=True, slots=True)
class XrayClassificationBatch(XrayRecord):
    evidence: XrayEvidence
    assignments: tuple[XrayClassificationAssignment, ...]
    requested_subjects: tuple[XrayClassificationSubject, ...] = ()


@dataclass(frozen=True, slots=True)
class XrayValuationCoverage(XrayRecord):
    complete: bool
    valued_root_keys: tuple[str, ...]
    unavailable_root_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class XrayReconciliation(XrayRecord):
    declared_total: XrayMoneyMetric
    root_total: XrayMoneyMetric
    difference: XrayMoneyMetric
    source_reference_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class XrayInput(XrayRecord):
    owner_id: UUID
    account_id: UUID
    snapshot_id: UUID
    snapshot_digest: str
    valuation_at: Instant
    source_cutoff_at: Instant
    reporting_currency: CurrencyCode
    policy: XrayPolicyVersion
    positions: tuple[XrayPosition, ...]
    cash: tuple[XrayCash, ...]
    portfolio_total: XrayMoneyMetric
    valuation_coverage: XrayValuationCoverage
    reconciliation: XrayReconciliation
    fund_definitions: tuple[XrayFundDefinition, ...]
    fund_mappings: tuple[XrayFundMapping, ...]
    constituent_candidates: tuple[XrayConstituentCandidate, ...]
    entity_evidence: tuple[XrayEntityEvidence, ...]
    relationship_versions: tuple[XrayRelationshipVersion, ...]
    classification_batches: tuple[XrayClassificationBatch, ...]
    source_dependencies: tuple[XraySourceDependency, ...]
    broker_fx: tuple[XrayBrokerFx, ...] = ()
    licensed_fx: tuple[XrayLicensedFx, ...] = ()
