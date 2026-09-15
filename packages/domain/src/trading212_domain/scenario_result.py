"""Closed scenario output records preserving terminal money and evidence diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    FloatOperation,
    InvalidOperation,
    Overflow,
    Underflow,
    localcontext,
)
from typing import Literal
from uuid import UUID

from .enums import QualityState
from .errors import fail_validation
from .historical import HistoricalReason
from .historical_results import (
    HistoricalConversionUse,
    HistoricalResultContext,
    HistoricalSourceUse,
)
from .scenario import (
    MAX_SCENARIO_COMPONENTS,
    MAX_SCENARIO_SENSITIVITY_ROWS,
    ScenarioAssumption,
    ScenarioReason,
    ScenarioRecord,
    ScenarioVersionContent,
)
from .scenario_execution import ScenarioInputPins, ScenarioReplaySelection
from .scenario_result_validation import (
    validate_scenario_comparison_money,
    validate_scenario_component_money,
    validate_scenario_summary_money,
)
from .scenario_sources import ScenarioDriverReference
from .scenario_validation import scenario_bound, unique
from .values import CurrencyCode, Money
from .xray import XrayReason


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioMoneyMetric(ScenarioRecord):
    value: Money | None
    quality: QualityState
    reason: ScenarioReason | None
    confidence: Decimal | None
    source_reference_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        ScenarioRecord.__post_init__(self)
        if (self.value is None) != (self.reason is not None):
            fail_validation("Scenario money absence requires exactly one reason.")
        if self.value is None and self.quality is QualityState.FRESH:
            fail_validation("Unavailable scenario money cannot have fresh quality.")
        unique(self.source_reference_ids, "source_reference_ids")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioRatioMetric(ScenarioRecord):
    value: Decimal | None
    quality: QualityState
    reason: ScenarioReason | None

    def __post_init__(self) -> None:
        ScenarioRecord.__post_init__(self)
        if (self.value is None) != (self.reason is not None):
            fail_validation("Scenario ratio absence requires exactly one reason.")
        if self.value is None and self.quality is QualityState.FRESH:
            fail_validation("Unavailable scenario ratio cannot have fresh quality.")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioSubjectFact(ScenarioRecord):
    dimension: Literal["instrument", "entity"]
    state: Literal["known", "unknown", "not_applicable"]
    subject_id: UUID | None
    reason: ScenarioReason | None
    upstream_reason: XrayReason | None
    identity_decision_ids: tuple[UUID, ...]
    source_reference_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        ScenarioRecord.__post_init__(self)
        if (self.state == "known") != (self.subject_id is not None) or (
            self.state == "unknown"
        ) != (self.reason is not None):
            fail_validation("Scenario subject evidence state differs.")
        unique(self.identity_decision_ids, "identity_decision_ids")
        unique(self.source_reference_ids, "source_reference_ids")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioClassificationFact(ScenarioRecord):
    dimension: Literal["sector", "region"]
    state: Literal["known", "unknown", "not_applicable"]
    taxonomy_id: UUID | None
    taxonomy_version: str | None
    bucket_key: str | None
    decision_key: str | None
    assignment_ids: tuple[UUID, ...]
    evidence_ids: tuple[UUID, ...]
    source_reference_ids: tuple[UUID, ...]
    reason: ScenarioReason | None
    upstream_reason: XrayReason | None
    confidence: Decimal | None

    def __post_init__(self) -> None:
        ScenarioRecord.__post_init__(self)
        if (self.state == "known") != (self.bucket_key is not None) or (
            self.state == "unknown"
        ) != (self.reason is not None):
            fail_validation("Scenario classification evidence state differs.")
        if self.state == "known" and (
            self.taxonomy_id is None
            or self.taxonomy_version is None
            or self.decision_key is None
            or not self.assignment_ids
        ):
            fail_validation("Known scenario classification requires taxonomy witnesses.")
        for name in ("assignment_ids", "evidence_ids", "source_reference_ids"):
            unique(getattr(self, name), name)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioCurrencyFact(ScenarioRecord):
    state: Literal["known", "unknown"]
    currency: CurrencyCode | None
    basis: Literal["economic_classification", "snapshot_cash", "constituent_cash", "unknown"]
    decision_key: str | None
    taxonomy_id: UUID | None
    taxonomy_version: str | None
    cash_id: UUID | None
    candidate_id: UUID | None
    holding_id: UUID | None
    assignment_ids: tuple[UUID, ...]
    evidence_ids: tuple[UUID, ...]
    source_reference_ids: tuple[UUID, ...]
    reason: ScenarioReason | None
    upstream_reason: XrayReason | None

    def __post_init__(self) -> None:
        ScenarioRecord.__post_init__(self)
        if (
            (self.state == "known") != (self.currency is not None)
            or (self.state == "unknown") != (self.reason is not None)
            or (self.state == "unknown") != (self.basis == "unknown")
        ):
            fail_validation("Scenario economic-currency evidence state differs.")
        if self.basis == "economic_classification" and (
            self.decision_key is None
            or self.taxonomy_id is None
            or self.taxonomy_version is None
            or not self.assignment_ids
        ):
            fail_validation("Economic currency requires pinned classification witnesses.")
        if self.basis == "snapshot_cash" and self.cash_id is None:
            fail_validation("Snapshot cash requires its original root identity.")
        if self.basis == "constituent_cash" and (
            self.candidate_id is None or self.holding_id is None
        ):
            fail_validation("Constituent cash requires exact holding membership.")
        for name in ("assignment_ids", "evidence_ids", "source_reference_ids"):
            unique(getattr(self, name), name)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioTerminalExposure(ScenarioRecord):
    path_key: str
    root_key: str
    root_kind: Literal["position", "cash"]
    position_id: UUID | None
    snapshot_cash_id: UUID | None
    root_instrument_id: UUID | None
    explicit_cash: bool
    instrument: ScenarioSubjectFact
    entity: ScenarioSubjectFact
    sector: ScenarioClassificationFact
    region: ScenarioClassificationFact
    economic_currency: ScenarioCurrencyFact
    pre_value: ScenarioMoneyMetric
    quality: QualityState
    confidence: Decimal | None
    upstream_reason: XrayReason | None
    source_reference_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        ScenarioRecord.__post_init__(self)
        if self.root_kind == "position":
            if self.position_id is None or self.root_instrument_id is None or self.snapshot_cash_id:
                fail_validation("Scenario position root identity differs.")
        elif self.snapshot_cash_id is None or self.position_id or self.root_instrument_id:
            fail_validation("Scenario cash root identity differs.")
        if (
            self.instrument.dimension != "instrument"
            or self.entity.dimension != "entity"
            or self.sector.dimension != "sector"
            or self.region.dimension != "region"
        ):
            fail_validation("Scenario exposure dimensions differ.")
        if self.explicit_cash and any(
            item.state != "not_applicable"
            for item in (self.instrument, self.entity, self.sector, self.region)
        ):
            fail_validation("Explicit cash cannot have security price selectors.")
        unique(self.source_reference_ids, "source_reference_ids")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioSensitivityUse(ScenarioRecord):
    rule_key: str
    driver: ScenarioDriverReference
    version_id: UUID
    candidate_observation_ids: tuple[UUID, ...]
    observation_id: UUID | None
    coefficient: Decimal | None
    shock_size: Decimal
    effect_ratio: ScenarioRatioMetric
    reason: ScenarioReason | None

    def __post_init__(self) -> None:
        ScenarioRecord.__post_init__(self)
        unique(self.candidate_observation_ids, "candidate_observation_ids")
        if not Decimal(-1) <= self.shock_size <= Decimal(1):
            fail_validation("Scenario sensitivity shock exceeds its bound.")
        if self.coefficient is not None and not Decimal(-100) <= self.coefficient <= Decimal(100):
            fail_validation("Scenario sensitivity coefficient exceeds its bound.")
        if self.coefficient is not None and self.observation_id is None:
            fail_validation("A retained sensitivity coefficient requires its selected observation.")
        if (
            self.observation_id is not None
            and self.observation_id not in self.candidate_observation_ids
        ):
            fail_validation("Selected sensitivity observation lacks candidate membership.")
        if self.reason is None and (self.observation_id is None or self.coefficient is None):
            fail_validation("Resolved sensitivity use requires its observation and coefficient.")
        if self.reason is None:
            assert self.coefficient is not None
            # Both inputs are retained Q18 values; their exact product is rounded once.
            # Use the frozen profile so ambient Decimal traps cannot change validation.
            with localcontext(
                Context(
                    prec=96,
                    rounding=ROUND_HALF_EVEN,
                    Emin=-999,
                    Emax=999,
                    capitals=1,
                    clamp=0,
                    flags=[],
                    traps=[InvalidOperation, DivisionByZero, Overflow, Underflow, FloatOperation],
                )
            ):
                expected = (self.coefficient * self.shock_size).quantize(Decimal("1e-18"))
            if self.effect_ratio.value != expected:
                fail_validation("Resolved sensitivity effect differs from its retained product.")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioChannelEffects(ScenarioRecord):
    price_ratio: ScenarioRatioMetric
    factor_ratio: ScenarioRatioMetric
    fx_ratio: ScenarioRatioMetric
    price: ScenarioMoneyMetric
    factor: ScenarioMoneyMetric
    fx: ScenarioMoneyMetric
    interaction: ScenarioMoneyMetric


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioComponent(ScenarioRecord):
    exposure: ScenarioTerminalExposure
    partition: Literal["covered", "uncovered", "excluded"]
    winning_price_rule_key: str | None
    matching_exclusion_keys: tuple[str, ...]
    uncertain_rule_keys: tuple[str, ...]
    sensitivity_uses: tuple[ScenarioSensitivityUse, ...]
    effects: ScenarioChannelEffects
    post_value: ScenarioMoneyMetric
    impact: ScenarioMoneyMetric
    rounding_residual: ScenarioMoneyMetric
    money_basis: Literal["resolved", "zero_pre_value", "provably_zero_effect", "unavailable"]
    diagnostic_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        ScenarioRecord.__post_init__(self)
        if (self.money_basis == "unavailable") != (self.post_value.value is None):
            fail_validation("Scenario money basis differs from complete post value.")
        if (self.impact.value is None) != (self.post_value.value is None):
            fail_validation("Scenario post and impact availability differ.")
        if self.money_basis in ("zero_pre_value", "provably_zero_effect"):
            pre, post, impact = (
                self.exposure.pre_value.value,
                self.post_value.value,
                self.impact.value,
            )
            if pre is None or post != pre or impact is None or impact.amount != 0:
                fail_validation("Provably unchanged money must retain the original amount.")
            if self.money_basis == "zero_pre_value" and pre.amount != 0:
                fail_validation("Zero-pre-value evidence differs.")
        for name in ("matching_exclusion_keys", "uncertain_rule_keys", "diagnostic_keys"):
            unique(getattr(self, name), name)
        unique(tuple(item.rule_key for item in self.sensitivity_uses), "sensitivity_uses")
        validate_scenario_component_money(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioPartitionSummary(ScenarioRecord):
    terminal_pre_value: ScenarioMoneyMetric
    covered_pre_value: ScenarioMoneyMetric
    uncovered_pre_value: ScenarioMoneyMetric
    excluded_pre_value: ScenarioMoneyMetric
    covered_count: int
    uncovered_count: int
    excluded_count: int
    missing_pre_value_count: int
    uncertain_money_count: int
    covered_post_value: ScenarioMoneyMetric
    excluded_post_value: ScenarioMoneyMetric
    provably_unchanged_uncovered_value: ScenarioMoneyMetric
    post_value: ScenarioMoneyMetric
    impact: ScenarioMoneyMetric
    effects: ScenarioChannelEffects
    rounding_residual: ScenarioMoneyMetric
    component_sum_residual: ScenarioMoneyMetric


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioDiagnostic(ScenarioRecord):
    key: str
    reason: ScenarioReason
    path_key: str | None
    rule_key: str | None
    upstream_xray_reason: XrayReason | None
    upstream_historical_reason: HistoricalReason | None
    source_reference_ids: tuple[UUID, ...]
    source_use_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioReplayChange(ScenarioRecord):
    path_key: str
    local_return: ScenarioRatioMetric
    fx_return: ScenarioRatioMetric
    reporting_return: ScenarioRatioMetric
    basis: Literal["local_with_fx", "unavailable"]
    source_use_keys: tuple[str, ...]
    conversion_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioReplayProof(ScenarioRecord):
    selection: ScenarioReplaySelection
    context: HistoricalResultContext
    changes: tuple[ScenarioReplayChange, ...]
    source_uses: tuple[HistoricalSourceUse, ...]
    conversions: tuple[HistoricalConversionUse, ...]
    holdings_evidence_at: datetime
    holdings_knowledge_cutoff_at: datetime
    diagnostics: tuple[ScenarioDiagnostic, ...]

    def __post_init__(self) -> None:
        ScenarioRecord.__post_init__(self)
        unique(tuple(item.path_key for item in self.changes), "replay_changes")
        uses = {item.use_key for item in self.source_uses}
        conversions = {item.conversion_key for item in self.conversions}
        if len(uses) != len(self.source_uses) or len(conversions) != len(self.conversions):
            fail_validation("Scenario replay source proof identities are duplicated.")
        for item in self.changes:
            if (
                not set(item.source_use_keys) <= uses
                or not set(item.conversion_keys) <= conversions
            ):
                fail_validation("Scenario replay change has dangling source proof.")


def _currencies(value: object, currency: CurrencyCode) -> None:
    if isinstance(value, ScenarioMoneyMetric):
        if value.value is not None and value.value.currency != currency:
            fail_validation("Scenario monetary reporting currency differs.")
    elif isinstance(value, tuple):
        for item in value:
            _currencies(item, currency)
    elif isinstance(value, ScenarioRecord) and is_dataclass(value):
        for item in fields(value):
            _currencies(getattr(value, item.name), currency)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioCalculation(ScenarioRecord):
    input_digest: str
    pins: ScenarioInputPins
    definition: ScenarioVersionContent
    valuation_at: datetime
    components: tuple[ScenarioComponent, ...]
    summary: ScenarioPartitionSummary
    upstream_portfolio_value: ScenarioMoneyMetric
    upstream_partition_difference: ScenarioMoneyMetric
    upstream_residual_keys: tuple[str, ...]
    replay: ScenarioReplayProof | None
    diagnostics: tuple[ScenarioDiagnostic, ...]
    assumptions: tuple[ScenarioAssumption, ...]
    sensitivity_source_row_count: int
    family: Literal["scenario"] = "scenario"
    method: Literal["stress_v1"] = "stress_v1"
    method_version: Literal["1.0.0"] = "1.0.0"
    schema_version: Literal["1.0.0"] = "1.0.0"
    numerical_profile: Literal["premium_decimal96_q18_v1"] = "premium_decimal96_q18_v1"

    def __post_init__(self) -> None:
        scenario_bound(
            type(self.components) is tuple and len(self.components) <= MAX_SCENARIO_COMPONENTS,
            "components",
        )
        if (
            type(self.sensitivity_source_row_count) is not int
            or self.sensitivity_source_row_count < 0
        ):
            fail_validation("Scenario sensitivity source count is invalid.")
        total = self.sensitivity_source_row_count
        for item in self.components:
            if type(item) is not ScenarioComponent:
                fail_validation("A canonical scenario component is required.")
            total += len(item.sensitivity_uses)
            scenario_bound(total <= MAX_SCENARIO_SENSITIVITY_ROWS, "sensitivity_rows")
        scenario_bound(total <= MAX_SCENARIO_SENSITIVITY_ROWS, "sensitivity_rows")
        ScenarioRecord.__post_init__(self)
        from .scenario_serialization import scenario_definition_digest

        if self.pins.scenario_version_digest != scenario_definition_digest(self.definition):
            fail_validation("Scenario result definition differs from its source pin.")
        unique(tuple(item.exposure.path_key for item in self.components), "components")
        unique(tuple(item.key for item in self.diagnostics), "diagnostics")
        unique(self.assumptions, "assumptions")
        unique(self.upstream_residual_keys, "upstream_residual_keys")
        _currencies(self, self.pins.reporting_currency)
        counts = tuple(
            sum(item.partition == kind for item in self.components)
            for kind in ("covered", "uncovered", "excluded")
        )
        if counts != (
            self.summary.covered_count,
            self.summary.uncovered_count,
            self.summary.excluded_count,
        ):
            fail_validation("Scenario summary partition counts differ.")
        if self.summary.missing_pre_value_count != sum(
            item.exposure.pre_value.value is None for item in self.components
        ) or self.summary.uncertain_money_count != sum(
            item.post_value.value is None for item in self.components
        ):
            fail_validation("Scenario summary missing-money counts differ.")
        diagnostics = {item.key for item in self.diagnostics}
        if any(not set(item.diagnostic_keys) <= diagnostics for item in self.components):
            fail_validation("Scenario component diagnostic is not retained.")
        if self.replay is not None and self.definition.shocks:
            fail_validation("Scenario replay excludes hypothetical shocks.")
        validate_scenario_summary_money(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioBasisMismatch(ScenarioRecord):
    field: Literal[
        "method",
        "numerical_profile",
        "currency",
        "holdings_basis",
        "holdings_partition",
        "knowledge_basis",
        "market_window",
        "source_cutoff",
    ]
    left: str
    right: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioMetricDelta(ScenarioRecord):
    before: ScenarioMoneyMetric
    after: ScenarioMoneyMetric
    difference: ScenarioMoneyMetric


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioComponentDelta(ScenarioRecord):
    root_key: str
    path_key: str
    post_value: ScenarioMetricDelta
    impact: ScenarioMetricDelta


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioComparison(ScenarioRecord):
    left_result_digest: str
    right_result_digest: str
    compatible: bool
    mismatches: tuple[ScenarioBasisMismatch, ...]
    post_value: ScenarioMetricDelta
    impact: ScenarioMetricDelta
    components: tuple[ScenarioComponentDelta, ...]

    def __post_init__(self) -> None:
        ScenarioRecord.__post_init__(self)
        if self.compatible == bool(self.mismatches):
            fail_validation("Scenario comparison compatibility differs from basis diagnostics.")
        unique(tuple(item.field for item in self.mismatches), "mismatches")
        unique(tuple((item.root_key, item.path_key) for item in self.components), "components")
        if not self.compatible and any(
            item.value is not None
            for item in (
                self.post_value.difference,
                self.impact.difference,
                *(part.post_value.difference for part in self.components),
                *(part.impact.difference for part in self.components),
            )
        ):
            fail_validation("Incompatible scenario bases cannot publish deltas.")
        validate_scenario_comparison_money(self)
