"""Immutable, exact inputs and results for manual contribution planning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from .currency_policy import CURRENCY_POLICY_VERSION
from .enums import QualityState
from .errors import fail_validation
from .metadata import CalculationDefinition
from .registry import CalculationRegistry
from .targets import (
    TargetCatalog,
    TargetConstraint,
    TargetConstraintKind,
    TargetContent,
    TargetNodeKind,
)
from .values import CurrencyCode, Money, exact_decimal, require_bounded_text, require_utc

DRIFT_METHOD = "drift_v1"
PLAN_METHOD = "contribution_weighted_drift_v1"
PLANNING_METHOD_VERSION = "1.0.0"
PLANNING_SCHEMA_VERSION = "1.0.0"
PLANNING_QUANTUM = Decimal("0.000000000000000001")
PLANNING_CALCULATION_REGISTRY = CalculationRegistry(
    (
        CalculationDefinition(
            calculation_id=DRIFT_METHOD,
            version=PLANNING_METHOD_VERSION,
            input_schema_version=PLANNING_SCHEMA_VERSION,
            output_schema_version=PLANNING_SCHEMA_VERSION,
            method_summary="Full-denominator direct target drift with exact hierarchy products.",
            quality_policy=(
                "Pinned complete valuation; explicit degraded policy cannot invent money."
            ),
        ),
        CalculationDefinition(
            calculation_id=PLAN_METHOD,
            version=PLANNING_METHOD_VERSION,
            input_schema_version=PLANNING_SCHEMA_VERSION,
            output_schema_version=PLANNING_SCHEMA_VERSION,
            method_summary=(
                "Bounded deterministic contribution-only discrete weighted drift search."
            ),
            quality_policy=(
                "Independent hard-constraint verification; exhaustive proof for optimality."
            ),
        ),
    )
)


class PlanningMode(StrEnum):
    GLOBAL = "global"
    HIERARCHICAL = "hierarchical"
    RESTRICTED = "restricted"
    CASH_ONLY = "cash_only"


class CoveragePolicy(StrEnum):
    REQUIRE_COMPLETE = "require_complete"
    ALLOW_DEGRADED = "allow_degraded"


class PlanOutcome(StrEnum):
    OPTIMAL = "optimal"
    FEASIBLE_NONOPTIMAL = "feasible_nonoptimal"
    INFEASIBLE = "infeasible"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class PlanningAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class DriftBasis(StrEnum):
    DIRECT = "direct"
    EFFECTIVE = "effective"


def planning_id(value: str, field: str = "id") -> str:
    if not isinstance(value, str):
        fail_validation("A canonical UUID string is required.", field=field)
    try:
        parsed = UUID(value)
    except ValueError:
        fail_validation("A canonical UUID string is required.", field=field)
    if str(parsed) != value:
        fail_validation("A canonical UUID string is required.", field=field)
    return value


def planning_digest(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        fail_validation("A lowercase SHA-256 digest is required.", field="content_digest")


def planning_tuple[T](value: tuple[T, ...], kind: type[T], field: str, maximum: int = 256) -> None:
    if (
        not isinstance(value, tuple)
        or len(value) > maximum
        or any(not isinstance(x, kind) for x in value)
    ):
        fail_validation("A bounded immutable typed tuple is required.", field=field)


def _identities(value: tuple[str, ...], field: str) -> None:
    planning_tuple(value, str, field)
    if len(set(value)) != len(value):
        fail_validation("Repeated identities are not allowed.", field=field)
    for item in value:
        planning_id(item, field)


@dataclass(frozen=True, slots=True)
class PlanningSource:
    kind: str
    id: str
    content_digest: str
    version: str
    effective_at: datetime
    first_observed_at: datetime

    def __post_init__(self) -> None:
        if self.kind not in {
            "portfolio_snapshot",
            "target_version",
            "mapping_revision",
            "fx_snapshot",
            "provider_fx_observation",
            "provider_observation",
            "calculation_run",
        }:
            fail_validation("Unsupported planning source kind.", field="source.kind")
        planning_id(self.id, "source.id")
        planning_digest(self.content_digest)
        require_bounded_text(self.version, field="source.version", maximum=80)
        object.__setattr__(self, "effective_at", require_utc(self.effective_at))
        object.__setattr__(self, "first_observed_at", require_utc(self.first_observed_at))


@dataclass(frozen=True, slots=True)
class PlanningFxRate:
    source: PlanningSource
    base: CurrencyCode
    quote: CurrencyCode
    rate: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.source, PlanningSource) or self.source.kind not in {
            "fx_snapshot",
            "provider_fx_observation",
        }:
            fail_validation("A pinned FX source is required.", field="fx.source")
        if not isinstance(self.base, CurrencyCode) or not isinstance(self.quote, CurrencyCode):
            fail_validation("Typed FX currencies are required.", field="fx.currency")
        object.__setattr__(self, "rate", exact_decimal(self.rate))
        if self.rate <= 0:
            fail_validation("FX rate must be positive.", field="fx.rate")


@dataclass(frozen=True, slots=True)
class ValuationPosition:
    listing_id: str
    instrument_id: str | None
    value: Money | None
    quality: QualityState
    fx: PlanningFxRate | None = None

    def __post_init__(self) -> None:
        planning_id(self.listing_id, "listing_id")
        if self.instrument_id is not None:
            planning_id(self.instrument_id, "instrument_id")
        _valuation(self.value, self.quality, self.fx)


@dataclass(frozen=True, slots=True)
class ValuationCash:
    value: Money | None
    quality: QualityState
    fx: PlanningFxRate | None = None

    def __post_init__(self) -> None:
        _valuation(self.value, self.quality, self.fx)


def _valuation(value: Money | None, quality: QualityState, fx: PlanningFxRate | None) -> None:
    if value is not None and not isinstance(value, Money):
        fail_validation("A typed valuation amount is required.", field="value")
    if not isinstance(quality, QualityState):
        fail_validation("A typed valuation quality is required.", field="quality")
    if fx is not None and not isinstance(fx, PlanningFxRate):
        fail_validation("A typed FX observation is required.", field="fx")


@dataclass(frozen=True, slots=True)
class ValuationInput:
    snapshot_id: str
    account_id: str
    reporting_currency: CurrencyCode
    valuation_at: datetime
    source_cutoff_at: datetime
    content_digest: str
    positions: tuple[ValuationPosition, ...]
    cash_components: tuple[ValuationCash, ...]
    portfolio_total: Money | None
    quality: QualityState
    coverage_complete: bool
    reconciled: bool
    missing_inputs: tuple[str, ...] = ()
    sources: tuple[PlanningSource, ...] = ()

    def __post_init__(self) -> None:
        planning_id(self.snapshot_id, "snapshot_id")
        planning_id(self.account_id, "account_id")
        planning_digest(self.content_digest)
        if not isinstance(self.reporting_currency, CurrencyCode):
            fail_validation("A typed reporting currency is required.", field="reporting_currency")
        object.__setattr__(self, "valuation_at", require_utc(self.valuation_at))
        object.__setattr__(self, "source_cutoff_at", require_utc(self.source_cutoff_at))
        if self.source_cutoff_at > self.valuation_at:
            fail_validation("Source cutoff follows valuation.", field="source_cutoff_at")
        planning_tuple(self.positions, ValuationPosition, "positions", 4096)
        planning_tuple(self.cash_components, ValuationCash, "cash_components", 256)
        planning_tuple(self.sources, PlanningSource, "sources", 8191)
        source_index = {(x.kind, x.id): x for x in self.sources}
        snapshot_source = source_index.get(("portfolio_snapshot", self.snapshot_id))
        if (
            len(source_index) != len(self.sources)
            or snapshot_source is None
            or (
                snapshot_source.content_digest != self.content_digest
                or snapshot_source.effective_at != self.valuation_at
            )
        ):
            fail_validation(
                "Unique sources and a matching snapshot reference are required.", field="sources"
            )
        for position in self.positions:
            if (
                position.fx is not None
                and source_index.get((position.fx.source.kind, position.fx.source.id))
                != position.fx.source
            ):
                fail_validation(
                    "FX source must be retained in snapshot provenance.", field="sources"
                )
        for cash in self.cash_components:
            if (
                cash.fx is not None
                and source_index.get((cash.fx.source.kind, cash.fx.source.id)) != cash.fx.source
            ):
                fail_validation(
                    "FX source must be retained in snapshot provenance.", field="sources"
                )
        planning_tuple(self.missing_inputs, str, "missing_inputs", 128)
        for item in self.missing_inputs:
            require_bounded_text(item, field="missing_input", maximum=80)
        if len({x.listing_id for x in self.positions}) != len(self.positions):
            fail_validation("Snapshot listing identities must be unique.", field="positions")
        if not isinstance(self.coverage_complete, bool) or not isinstance(self.reconciled, bool):
            fail_validation("Coverage flags must be boolean.", field="coverage")
        _valuation(self.portfolio_total, self.quality, None)
        if (
            self.portfolio_total is not None
            and self.portfolio_total.currency != self.reporting_currency
        ):
            fail_validation("Snapshot total currency differs.", field="portfolio_total")


@dataclass(frozen=True, slots=True)
class PlanningNodeIdentity:
    id: str
    key: str
    holding_id: str | None = None

    def __post_init__(self) -> None:
        planning_id(self.id, "node_id")
        require_bounded_text(self.key, field="node_key", maximum=80)
        if self.holding_id is not None:
            planning_id(self.holding_id, "holding_id")


@dataclass(frozen=True, slots=True)
class PlanningListingPreference:
    holding_id: str
    listing_id: str

    def __post_init__(self) -> None:
        planning_id(self.holding_id, "holding_id")
        planning_id(self.listing_id, "listing_id")


@dataclass(frozen=True, slots=True)
class PlanningConstraint:
    key: str
    kind: TargetConstraintKind
    node_id: str | None = None
    amount: Decimal | None = None
    currency: CurrencyCode | None = None
    weight: Decimal | None = None
    enabled: bool | None = None
    count: int | None = None
    coefficient: Decimal | None = None

    def __post_init__(self) -> None:
        if self.node_id is not None:
            planning_id(self.node_id, "constraint.node_id")
        scalar = TargetConstraint(
            self.key,
            self.kind,
            amount=self.amount,
            currency=self.currency,
            weight=self.weight,
            enabled=self.enabled,
            count=self.count,
            coefficient=self.coefficient,
        )
        for name in ("amount", "weight", "coefficient"):
            object.__setattr__(self, name, getattr(scalar, name))


@dataclass(frozen=True, slots=True)
class PlanningHoldingConstraint:
    holding_id: str
    minimum_amount: Decimal
    value_increment: Decimal
    maximum_post_weight: Decimal | None = None

    def __post_init__(self) -> None:
        planning_id(self.holding_id, "holding_id")
        for name in ("minimum_amount", "value_increment", "maximum_post_weight"):
            value = getattr(self, name)
            if value is not None or name != "maximum_post_weight":
                object.__setattr__(self, name, exact_decimal(value, field=name))
        if (
            self.minimum_amount < 0
            or self.value_increment <= 0
            or (self.maximum_post_weight is not None and not 0 <= self.maximum_post_weight <= 1)
        ):
            fail_validation("Invalid holding constraint values.", field="holding_constraints")


@dataclass(frozen=True, slots=True)
class PlanningOptions:
    contribution: Money
    mode: PlanningMode
    coverage_policy: CoveragePolicy = CoveragePolicy.REQUIRE_COMPLETE
    eligible_holding_ids: tuple[str, ...] | None = None
    excluded_holding_ids: tuple[str, ...] = ()
    restricted_group_ids: tuple[str, ...] = ()
    listing_preferences: tuple[PlanningListingPreference, ...] = ()
    allocation_constraints: tuple[PlanningConstraint, ...] = ()
    holding_constraints: tuple[PlanningHoldingConstraint, ...] = ()
    cash_reserve: Decimal | None = None
    monetary_quantum: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.contribution, Money) or self.contribution.amount < 0:
            fail_validation("Contribution must be nonnegative typed money.", field="contribution")
        if not isinstance(self.mode, PlanningMode) or not isinstance(
            self.coverage_policy, CoveragePolicy
        ):
            fail_validation("Typed planning mode and policy are required.", field="mode")
        if self.eligible_holding_ids is not None:
            _identities(self.eligible_holding_ids, "eligible_holding_ids")
        _identities(self.excluded_holding_ids, "excluded_holding_ids")
        _identities(self.restricted_group_ids, "restricted_group_ids")
        if self.eligible_holding_ids is not None and set(self.eligible_holding_ids) & set(
            self.excluded_holding_ids
        ):
            fail_validation(
                "A holding cannot be both eligible and excluded.", field="eligible_holding_ids"
            )
        if (self.mode is PlanningMode.RESTRICTED) != bool(self.restricted_group_ids):
            fail_validation(
                "Restricted groups are required only in restricted mode.",
                field="restricted_group_ids",
            )
        planning_tuple(self.listing_preferences, PlanningListingPreference, "listing_preferences")
        if len({x.holding_id for x in self.listing_preferences}) != len(self.listing_preferences):
            fail_validation(
                "A holding permits one listing preference.", field="listing_preferences"
            )
        planning_tuple(self.allocation_constraints, PlanningConstraint, "allocation_constraints")
        planning_tuple(self.holding_constraints, PlanningHoldingConstraint, "holding_constraints")
        if len({x.holding_id for x in self.holding_constraints}) != len(self.holding_constraints):
            fail_validation(
                "Repeated holding constraints are invalid.", field="holding_constraints"
            )
        if len({x.key for x in self.allocation_constraints}) != len(self.allocation_constraints):
            fail_validation("Constraint keys must be unique.", field="allocation_constraints")
        for name in ("cash_reserve", "monetary_quantum"):
            value = getattr(self, name)
            if value is not None:
                value = exact_decimal(value, field=name)
                if value < 0 or (name == "monetary_quantum" and value == 0):
                    fail_validation("Invalid nonnegative planning amount.", field=name)
                object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class PlanningInput:
    valuation: ValuationInput
    virtual_portfolio_id: str
    target_version_id: str
    target_content_digest: str
    target_effective_at: datetime
    target_published_at: datetime
    target_content: TargetContent
    node_identities: tuple[PlanningNodeIdentity, ...]
    catalog: TargetCatalog
    options: PlanningOptions
    method_version: str = PLANNING_METHOD_VERSION
    schema_version: str = PLANNING_SCHEMA_VERSION
    currency_policy_version: str = CURRENCY_POLICY_VERSION

    def __post_init__(self) -> None:
        if (self.method_version, self.schema_version, self.currency_policy_version) != (
            PLANNING_METHOD_VERSION,
            PLANNING_SCHEMA_VERSION,
            CURRENCY_POLICY_VERSION,
        ):
            fail_validation("Unsupported pinned planning policy version.", field="method_version")
        if not isinstance(self.valuation, ValuationInput) or not isinstance(
            self.options, PlanningOptions
        ):
            fail_validation("Typed planning input is required.", field="planning_input")
        planning_id(self.virtual_portfolio_id, "virtual_portfolio_id")
        planning_id(self.target_version_id, "target_version_id")
        planning_digest(self.target_content_digest)
        object.__setattr__(self, "target_effective_at", require_utc(self.target_effective_at))
        object.__setattr__(self, "target_published_at", require_utc(self.target_published_at))
        if not isinstance(self.target_content, TargetContent) or not isinstance(
            self.catalog, TargetCatalog
        ):
            fail_validation(
                "Typed target content and catalog are required.", field="target_content"
            )
        planning_tuple(self.node_identities, PlanningNodeIdentity, "node_identities")
        if len({x.id for x in self.node_identities}) != len(self.node_identities) or len(
            {x.key for x in self.node_identities}
        ) != len(self.node_identities):
            fail_validation("Target identities must be unique.", field="node_identities")
        if {x.key for x in self.node_identities} != {x.key for x in self.target_content.nodes}:
            fail_validation(
                "Target identities must cover exactly the pinned tree.", field="node_identities"
            )
        kinds = {x.key: x.kind for x in self.target_content.nodes}
        holding_ids = [x.holding_id for x in self.node_identities if x.holding_id is not None]
        if len(set(holding_ids)) != len(holding_ids) or any(
            (x.holding_id is not None) != (kinds[x.key] is TargetNodeKind.HOLDING)
            for x in self.node_identities
        ):
            fail_validation(
                "Holding identities must cover exactly the holding leaves.", field="node_identities"
            )


@dataclass(frozen=True, slots=True)
class PlanningExplanation:
    code: str
    message: str
    severity: str = "warning"
    node_keys: tuple[str, ...] = ()
    constraint_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlanningCoverage:
    complete: bool
    denominator: Money | None
    valued_total: Money
    matched_total: Money
    unclassified_total: Money
    matched_weight: Decimal | None
    unclassified_weight: Decimal | None
    unresolved_target_weight: Decimal
    basis: str = "full_reporting_currency_valuation"


@dataclass(frozen=True, slots=True)
class PlanningContext:
    account_id: str
    virtual_portfolio_id: str
    target_version_id: str
    snapshot_id: str
    reporting_currency: str
    as_of: datetime
    source_cutoff_at: datetime
    method: str
    method_version: str
    schema_version: str
    input_digest: str
    sources: tuple[PlanningSource, ...]
    availability: PlanningAvailability
    reason_code: str | None
    quality: QualityState
    coverage_start_at: datetime
    coverage_end_at: datetime
    missing_inputs: tuple[str, ...]
    reconciled: bool
    coverage: PlanningCoverage
    warnings: tuple[PlanningExplanation, ...]
    assumptions: tuple[PlanningExplanation, ...]


@dataclass(frozen=True, slots=True)
class DriftRow:
    key: str
    node_id: str | None
    holding_id: str | None
    kind: str
    parent_key: str | None
    name: str
    depth: int
    listing_id: str | None
    instrument_id: str | None
    target_weight: Decimal
    actual_value: Money | None
    actual_direct_weight: Decimal | None
    effective_weight: Decimal | None
    effective_weight_reason: str
    signed_drift: Decimal | None
    absolute_drift: Decimal | None
    relative_drift: Decimal | None
    relative_drift_reason: str | None
    classification: str | None
    monetary_gap: Money | None
    quality: QualityState


@dataclass(frozen=True, slots=True)
class DriftTotals:
    value: Money | None
    cash: Money | None
    unclassified: Money
    l1_drift: Decimal | None
    weighted_squared_drift: Decimal | None
    effective_weight_rounding_residual: Decimal | None
    frontier_keys: tuple[str, ...]
    group_count: int
    holding_count: int
    unclassified_count: int


@dataclass(frozen=True, slots=True)
class DriftCalculation:
    context: PlanningContext
    totals: DriftTotals
    rows: tuple[DriftRow, ...]


@dataclass(frozen=True, slots=True)
class PlanObjective:
    scores: tuple[Decimal, ...]
    quantum: Decimal = PLANNING_QUANTUM
    rounding: str = "ROUND_HALF_EVEN"
    rounding_error_bound: str = "half_quantum"


@dataclass(frozen=True, slots=True)
class ContributionPlanLine:
    ordinal: int
    node_id: str
    holding_id: str
    node_key: str
    instrument_id: str | None
    listing_id: str | None
    current_value: Money
    target_weight: Decimal
    current_weight: Decimal | None
    recommended_amount: Money
    post_value: Money
    post_weight: Decimal
    minimum_funded_amount: Money
    value_increment: Money
    excluded: bool
    binding_constraint_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContributionPlanResultSummary:
    context: PlanningContext
    outcome: PlanOutcome
    mode: PlanningMode
    contribution: Money
    monetary_quantum: Decimal | None
    currency_policy_version: str
    residual_cash: Money | None
    current_cash: Money | None
    post_cash: Money | None
    post_total: Money | None
    objective_before: PlanObjective | None
    objective_after: PlanObjective | None
    lower_bound: PlanObjective | None
    objective_gap: PlanObjective | None
    bound_kind: str | None
    examined_moves: int
    attempted_assignments: int
    exhaustive: bool
    constraints: tuple[TargetConstraint, ...]
    explanations: tuple[PlanningExplanation, ...]
    excluded_node_keys: tuple[str, ...]
    unresolved_node_keys: tuple[str, ...]
    before_drift: DriftTotals
    after_drift: DriftTotals | None
    execution_allowed: bool = False


@dataclass(frozen=True, slots=True)
class ContributionPlanResult:
    summary: ContributionPlanResultSummary
    lines: tuple[ContributionPlanLine, ...]
