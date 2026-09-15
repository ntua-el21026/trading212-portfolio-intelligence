"""Closed scenario REST objects, distinct bounded public views and exact decimal strings."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from . import historical as h
from .risk import RiskFailure
from .sources import CalendarDate, SourceKey, SourceQuality
from .targets import (
    AwareInstant,
    CurrencyString,
    Cursor,
    DecimalString,
    Digest,
    UUIDString,
    WeightString,
)
from .xray import XrayReason

ScenarioText = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=1024, pattern=r"^[^\x00]*$")
]
ScenarioName = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=120, pattern=r"^[^\x00]*$")
]
ScenarioDescription = Annotated[
    str, StringConstraints(strict=True, max_length=1024, pattern=r"^[^\x00]*$")
]
ScenarioCount = Annotated[StrictInt, Field(ge=0, le=100000)]
ScenarioComponentCount = Annotated[StrictInt, Field(ge=0, le=10000)]
ScenarioRevision = Annotated[StrictInt, Field(ge=1, le=512)]


class ScenarioSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def closed_fields(cls, value: object) -> object:
        if isinstance(value, dict) and any(key not in cls.model_fields for key in value):
            raise ValueError("The bounded scenario object contains unexpected fields.")
        return value


class ScenarioInstrumentSelector(ScenarioSchema):
    kind: Literal["instrument"]
    instrument_id: UUIDString


class ScenarioEntitySelector(ScenarioSchema):
    kind: Literal["entity"]
    entity_id: UUIDString


class ScenarioSectorSelector(ScenarioSchema):
    kind: Literal["sector"]
    taxonomy_id: UUIDString
    taxonomy_version: SourceKey
    bucket_key: SourceKey


class ScenarioRegionSelector(ScenarioSchema):
    kind: Literal["region"]
    taxonomy_id: UUIDString
    taxonomy_version: SourceKey
    bucket_key: SourceKey


class ScenarioCurrencySelector(ScenarioSchema):
    kind: Literal["economic_currency"]
    currency: CurrencyString


ScenarioPriceSelector = Annotated[
    ScenarioInstrumentSelector
    | ScenarioEntitySelector
    | ScenarioSectorSelector
    | ScenarioRegionSelector,
    Field(discriminator="kind"),
]
ScenarioComponentSelector = Annotated[
    ScenarioInstrumentSelector
    | ScenarioEntitySelector
    | ScenarioSectorSelector
    | ScenarioRegionSelector
    | ScenarioCurrencySelector,
    Field(discriminator="kind"),
]


class ScenarioSensitivityVersionPin(ScenarioSchema):
    version_id: UUIDString
    content_digest: Digest
    driver_id: UUIDString
    driver_definition_version_id: UUIDString


class ScenarioPriceShock(ScenarioSchema):
    kind: Literal["price"]
    selector: ScenarioPriceSelector
    size: DecimalString

    @model_validator(mode="after")
    def bounded_size(self) -> Self:
        if not Decimal(-1) <= Decimal(self.size) <= 5:
            raise ValueError("Scenario price shock exceeds its bounds.")
        return self


class ScenarioFxShock(ScenarioSchema):
    kind: Literal["fx"]
    selector: ScenarioCurrencySelector
    size: DecimalString

    @model_validator(mode="after")
    def bounded_size(self) -> Self:
        if not Decimal(-1) <= Decimal(self.size) <= 5:
            raise ValueError("Scenario FX shock exceeds its bounds.")
        return self


class ScenarioRateShock(ScenarioSchema):
    kind: Literal["rate"]
    source: ScenarioSensitivityVersionPin
    size: DecimalString

    @model_validator(mode="after")
    def bounded_size(self) -> Self:
        if not Decimal(-1) <= Decimal(self.size) <= 1:
            raise ValueError("Scenario rate shock exceeds its bounds.")
        return self


class ScenarioFactorShock(ScenarioSchema):
    kind: Literal["factor"]
    source: ScenarioSensitivityVersionPin
    size: DecimalString

    @model_validator(mode="after")
    def bounded_size(self) -> Self:
        if not Decimal(-1) <= Decimal(self.size) <= 1:
            raise ValueError("Scenario factor shock exceeds its bounds.")
        return self


ScenarioShock = Annotated[
    ScenarioPriceShock | ScenarioFxShock | ScenarioRateShock | ScenarioFactorShock,
    Field(discriminator="kind"),
]


class ScenarioExclusion(ScenarioSchema):
    selector: ScenarioComponentSelector


class ScenarioVersionContent(ScenarioSchema):
    name: ScenarioName
    description: ScenarioDescription = ""
    mode: Literal["first_order", "compounded"]
    shocks: Annotated[list[ScenarioShock], Field(max_length=128)] = Field(default_factory=list)
    exclusions: Annotated[list[ScenarioExclusion], Field(max_length=128)] = Field(
        default_factory=list
    )
    method_version: Literal["1.0.0"] = "1.0.0"

    @model_validator(mode="after")
    def distinct_rules(self) -> Self:
        if not self.name.strip():
            raise ValueError("A scenario name is required.")
        identities = [
            ("selector", item.selector.model_dump_json())
            if isinstance(item, (ScenarioPriceShock, ScenarioFxShock))
            else ("driver", item.source.driver_id)
            for item in self.shocks
        ]
        exclusions = [item.selector.model_dump_json() for item in self.exclusions]
        if len(set(identities)) != len(identities) or len(set(exclusions)) != len(exclusions):
            raise ValueError("Scenario selectors and drivers must be distinct.")
        return self


class CreateScenarioRequest(ScenarioSchema):
    content: ScenarioVersionContent


class CreateScenarioVersionRequest(ScenarioSchema):
    content: ScenarioVersionContent


class ScenarioReplaySelection(ScenarioSchema):
    historical_input_snapshot_id: UUIDString
    start_date: CalendarDate
    end_date: CalendarDate
    market_knowledge_cutoff_at: AwareInstant
    holdings_basis: Literal["current_holdings", "historical_holdings"]
    knowledge_basis: Literal["point_in_time", "retrospective"]

    @model_validator(mode="after")
    def positive_window(self) -> Self:
        if not 0 < (self.end_date - self.start_date).days <= 3660:
            raise ValueError("Scenario replay requires a bounded positive date window.")
        return self


class CreateScenarioRunRequest(ScenarioSchema):
    scenario_version_id: UUIDString
    portfolio_snapshot_id: UUIDString
    xray_run_id: UUIDString
    reporting_currency: CurrencyString
    source_cutoff_at: AwareInstant
    replay: ScenarioReplaySelection | None = None


class CancelScenarioRunRequest(ScenarioSchema):
    pass


class ScenarioPageQuery(ScenarioSchema):
    limit: h.HistoricalPageLimit = 25
    cursor: Cursor | None = None


class ScenarioComponentPageQuery(ScenarioSchema):
    component_limit: h.HistoricalPageLimit = 25
    component_cursor: Cursor | None = None


class ScenarioComparisonQuery(ScenarioComponentPageQuery):
    run_ids: Annotated[list[UUIDString], Field(min_length=2, max_length=2)]

    @model_validator(mode="after")
    def ordered_distinct_runs(self) -> Self:
        if len(set(self.run_ids)) != 2:
            raise ValueError("Select exactly two distinct ordered scenario runs.")
        return self


class ScenarioInputPins(ScenarioSchema):
    owner_id: UUIDString
    account_id: UUIDString
    scenario_id: UUIDString
    scenario_version_id: UUIDString
    scenario_version_digest: Digest
    portfolio_snapshot_id: UUIDString
    portfolio_snapshot_digest: Digest
    xray_run_id: UUIDString
    xray_input_id: UUIDString
    xray_input_digest: Digest
    xray_result_digest: Digest
    reporting_currency: CurrencyString
    source_cutoff_at: AwareInstant


class ScenarioMoney(ScenarioSchema):
    amount: DecimalString
    currency: CurrencyString


# Public scenario reason and assumption vocabulary.
ScenarioReason = Literal[
    "missing_value",
    "missing_identity",
    "ambiguous_identity",
    "missing_classification",
    "ambiguous_classification",
    "incompatible_taxonomy",
    "missing_economic_currency",
    "unsupported_economic_currency",
    "uncertain_exclusion",
    "uncertain_price_priority",
    "missing_sensitivity",
    "ambiguous_sensitivity",
    "unsupported_sensitivity",
    "incompatible_sensitivity_currency",
    "unknown_driver_equivalence",
    "missing_replay_mapping",
    "ambiguous_replay_mapping",
    "missing_replay_source",
    "fx_decomposition_unavailable",
    "historical_holdings_unavailable",
    "incompatible_basis",
    "uncertain_money",
    "zero_denominator",
]
ScenarioAssumption = Literal[
    "owner_defined_shocks",
    "additional_price_component",
    "first_order_formula",
    "compounded_formula",
    "canonical_terminal_basis",
    "counterfactual_replay",
    "fixed_cash_balance_replay",
    "retrospective_market_knowledge",
    "known_only_subtotals",
    "no_listing_currency_inference",
]


class ScenarioRatioMetric(ScenarioSchema):
    value: DecimalString | None
    quality: SourceQuality
    reason: ScenarioReason | None

    @model_validator(mode="after")
    def exact_absence(self) -> Self:
        if (self.value is None) != (self.reason is not None):
            raise ValueError("Scenario ratio absence requires its reason.")
        return self


class ScenarioPreview[Item](ScenarioSchema):
    items: Annotated[list[Item], Field(max_length=16)]
    omitted_count: ScenarioCount


class ScenarioMoneyView(ScenarioSchema):
    value: ScenarioMoney | None
    quality: SourceQuality
    reason: ScenarioReason | None
    confidence: WeightString | None
    source_reference_ids: ScenarioPreview[UUIDString]

    @model_validator(mode="after")
    def exact_absence(self) -> Self:
        if (self.value is None) != (self.reason is not None):
            raise ValueError("Scenario money absence requires its reason.")
        return self


class ScenarioSubjectView(ScenarioSchema):
    dimension: Literal["instrument", "entity"]
    state: Literal["known", "unknown", "not_applicable"]
    subject_id: UUIDString | None
    reason: ScenarioReason | None
    upstream_reason: XrayReason | None
    identity_decision_ids: ScenarioPreview[UUIDString]
    source_reference_ids: ScenarioPreview[UUIDString]


class ScenarioClassificationView(ScenarioSchema):
    dimension: Literal["sector", "region"]
    state: Literal["known", "unknown", "not_applicable"]
    taxonomy_id: UUIDString | None
    taxonomy_version: SourceKey | None
    bucket_key: SourceKey | None
    decision_key: ScenarioText | None
    assignment_ids: ScenarioPreview[UUIDString]
    evidence_ids: ScenarioPreview[UUIDString]
    source_reference_ids: ScenarioPreview[UUIDString]
    reason: ScenarioReason | None
    upstream_reason: XrayReason | None
    confidence: WeightString | None


class ScenarioCurrencyView(ScenarioSchema):
    state: Literal["known", "unknown"]
    currency: CurrencyString | None
    basis: Literal["economic_classification", "snapshot_cash", "constituent_cash", "unknown"]
    decision_key: ScenarioText | None
    taxonomy_id: UUIDString | None
    taxonomy_version: SourceKey | None
    cash_id: UUIDString | None
    candidate_id: UUIDString | None
    holding_id: UUIDString | None
    assignment_ids: ScenarioPreview[UUIDString]
    evidence_ids: ScenarioPreview[UUIDString]
    source_reference_ids: ScenarioPreview[UUIDString]
    reason: ScenarioReason | None
    upstream_reason: XrayReason | None


class ScenarioExposureView(ScenarioSchema):
    path_key: ScenarioText
    root_key: ScenarioText
    root_kind: Literal["position", "cash"]
    position_id: UUIDString | None
    snapshot_cash_id: UUIDString | None
    root_instrument_id: UUIDString | None
    explicit_cash: StrictBool
    instrument: ScenarioSubjectView
    entity: ScenarioSubjectView
    sector: ScenarioClassificationView
    region: ScenarioClassificationView
    economic_currency: ScenarioCurrencyView
    pre_value: ScenarioMoneyView
    quality: SourceQuality
    confidence: WeightString | None
    upstream_reason: XrayReason | None
    source_reference_ids: ScenarioPreview[UUIDString]


class ScenarioSensitivityView(ScenarioSchema):
    rule_key: ScenarioText
    driver_id: UUIDString
    driver_definition_version_id: UUIDString
    driver_definition_digest: Digest
    driver_kind: Literal["rate", "factor"]
    shock_unit: Literal["absolute_rate_change", "simple_factor_return"]
    driver_evidence_reference_ids: ScenarioPreview[UUIDString]
    version_id: UUIDString
    candidate_observation_ids: ScenarioPreview[UUIDString]
    observation_id: UUIDString | None
    coefficient: DecimalString | None
    shock_size: DecimalString
    effect_ratio: ScenarioRatioMetric
    reason: ScenarioReason | None

    @model_validator(mode="after")
    def retained_coefficient(self) -> Self:
        if (
            self.observation_id is not None
            and self.observation_id not in self.candidate_observation_ids.items
        ):
            raise ValueError("Selected sensitivity observation must remain visible.")
        if self.coefficient is not None and (
            self.observation_id is None or not Decimal(-100) <= Decimal(self.coefficient) <= 100
        ):
            raise ValueError("A bounded coefficient requires its selected observation.")
        if not Decimal(-1) <= Decimal(self.shock_size) <= 1:
            raise ValueError("Sensitivity shock exceeds its bound.")
        if self.reason is None and (self.observation_id is None or self.coefficient is None):
            raise ValueError("Resolved sensitivity requires its coefficient and observation.")
        return self


class ScenarioEffectsView(ScenarioSchema):
    price_ratio: ScenarioRatioMetric
    factor_ratio: ScenarioRatioMetric
    fx_ratio: ScenarioRatioMetric
    price: ScenarioMoneyView
    factor: ScenarioMoneyView
    fx: ScenarioMoneyView
    interaction: ScenarioMoneyView


class ScenarioDiagnosticView(ScenarioSchema):
    key: ScenarioText
    reason: ScenarioReason
    path_key: ScenarioText | None
    rule_key: ScenarioText | None
    upstream_xray_reason: XrayReason | None
    upstream_historical_reason: h.HistoricalReason | None
    source_reference_ids: ScenarioPreview[UUIDString]
    source_use_keys: ScenarioPreview[ScenarioText]


class ScenarioReplayChangeView(ScenarioSchema):
    path_key: ScenarioText
    local_return: ScenarioRatioMetric
    fx_return: ScenarioRatioMetric
    reporting_return: ScenarioRatioMetric
    basis: Literal["local_with_fx", "unavailable"]
    source_use_keys: ScenarioPreview[ScenarioText]
    conversion_keys: ScenarioPreview[ScenarioText]


class ScenarioComponentView(ScenarioSchema):
    exposure: ScenarioExposureView
    partition: Literal["covered", "uncovered", "excluded"]
    winning_price_rule_key: ScenarioText | None
    matching_exclusion_keys: Annotated[list[ScenarioText], Field(max_length=128)]
    uncertain_rule_keys: Annotated[list[ScenarioText], Field(max_length=128)]
    sensitivity_uses: Annotated[list[ScenarioSensitivityView], Field(max_length=128)]
    effects: ScenarioEffectsView
    post_value: ScenarioMoneyView
    impact: ScenarioMoneyView
    rounding_residual: ScenarioMoneyView
    money_basis: Literal["resolved", "zero_pre_value", "provably_zero_effect", "unavailable"]
    diagnostic_keys: ScenarioPreview[ScenarioText]
    replay_change: ScenarioReplayChangeView | None


class ScenarioSummaryView(ScenarioSchema):
    terminal_pre_value: ScenarioMoneyView
    covered_pre_value: ScenarioMoneyView
    uncovered_pre_value: ScenarioMoneyView
    excluded_pre_value: ScenarioMoneyView
    covered_count: ScenarioComponentCount
    uncovered_count: ScenarioComponentCount
    excluded_count: ScenarioComponentCount
    missing_pre_value_count: ScenarioComponentCount
    uncertain_money_count: ScenarioComponentCount
    covered_post_value: ScenarioMoneyView
    excluded_post_value: ScenarioMoneyView
    provably_unchanged_uncovered_value: ScenarioMoneyView
    post_value: ScenarioMoneyView
    impact: ScenarioMoneyView
    effects: ScenarioEffectsView
    rounding_residual: ScenarioMoneyView
    component_sum_residual: ScenarioMoneyView


class ScenarioHistoricalWarningView(ScenarioSchema):
    reason_code: h.HistoricalReason
    coverage_key: h.HistoricalCoverageKey | None
    reference_ids: ScenarioPreview[ScenarioText]


class ScenarioReplayContextView(ScenarioSchema):
    selection: ScenarioReplaySelection
    input_digest: Digest
    window: h.HistoricalWindow
    method: h.HistoricalMethodMetadata
    primitive_methods: Annotated[list[h.HistoricalMethodMetadata], Field(max_length=16)]
    source_policy_version: SourceKey | None
    accounting_policy_version: SourceKey
    coverage: h.HistoricalCoverage
    quality: SourceQuality
    availability: Literal["available", "partial", "unavailable", "failed"]
    reconstruction: Literal["point_in_time", "restated"]
    schema_version: Literal["1.0.0"]
    holdings_evidence_at: AwareInstant
    holdings_knowledge_cutoff_at: AwareInstant
    change_count: ScenarioComponentCount
    source_use_count: ScenarioCount
    conversion_count: ScenarioCount
    source_reference_ids: ScenarioPreview[ScenarioText]
    warnings: ScenarioPreview[ScenarioHistoricalWarningView]
    assumptions: Annotated[list[ScenarioText], Field(max_length=16)]
    diagnostics: ScenarioPreview[ScenarioDiagnosticView]


class ScenarioResultContextView(ScenarioSchema):
    run_id: UUIDString
    result_id: UUIDString
    saved_result_digest: Digest
    input_digest: Digest
    pins: ScenarioInputPins
    definition: ScenarioVersionContent
    valuation_at: AwareInstant
    summary: ScenarioSummaryView
    upstream_portfolio_value: ScenarioMoneyView
    upstream_partition_difference: ScenarioMoneyView
    upstream_residual_keys: ScenarioPreview[ScenarioText]
    replay: ScenarioReplayContextView | None
    diagnostics: ScenarioPreview[ScenarioDiagnosticView]
    assumptions: Annotated[list[ScenarioAssumption], Field(max_length=16)]
    sensitivity_source_row_count: ScenarioCount
    method_version: Literal["1.0.0"]
    schema_version: Literal["1.0.0"]
    numerical_profile: Literal["premium_decimal96_q18_v1"]


class ScenarioComponentPage[Item](ScenarioSchema):
    items: Annotated[list[Item], Field(max_length=100)]
    next_cursor: Cursor | None
    component_limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: ScenarioComponentCount
    start_ordinal: ScenarioComponentCount

    @model_validator(mode="after")
    def whole_page(self) -> Self:
        end = self.start_ordinal + len(self.items)
        if (
            len(self.items) > self.component_limit
            or end > self.total
            or (not self.items and self.total != 0)
        ):
            raise ValueError("Scenario component page bounds differ.")
        if (self.next_cursor is not None) != (end < self.total):
            raise ValueError("Scenario continuation differs from retained row count.")
        return self


class ScenarioResultPage(ScenarioSchema):
    context: ScenarioResultContextView
    components: ScenarioComponentPage[ScenarioComponentView]
    content_digest: Digest
    view_version: Literal["scenario_compact_v1"] = "scenario_compact_v1"

    @model_validator(mode="after")
    def complete_inventory(self) -> Self:
        summary = self.context.summary
        if (
            self.components.total
            != summary.covered_count + summary.uncovered_count + summary.excluded_count
        ):
            raise ValueError("Scenario total differs from its retained partition.")
        return self


class ScenarioDeltaView(ScenarioSchema):
    before: ScenarioMoneyView
    after: ScenarioMoneyView
    difference: ScenarioMoneyView


class ScenarioComparisonComponentView(ScenarioSchema):
    root_key: ScenarioText
    path_key: ScenarioText
    before: ScenarioComponentView | None
    after: ScenarioComponentView | None
    post_value: ScenarioDeltaView
    impact: ScenarioDeltaView


class ScenarioComparisonPage(ScenarioSchema):
    before: ScenarioResultContextView
    after: ScenarioResultContextView
    compatible: StrictBool
    mismatches: Annotated[list[ScenarioBasisMismatch], Field(max_length=8)]
    post_value: ScenarioDeltaView
    impact: ScenarioDeltaView
    components: ScenarioComponentPage[ScenarioComparisonComponentView]
    content_digest: Digest
    view_version: Literal["scenario_compact_v1"] = "scenario_compact_v1"

    @model_validator(mode="after")
    def incompatible_differences(self) -> Self:
        if self.compatible == bool(self.mismatches) or len(
            {item.field for item in self.mismatches}
        ) != len(self.mismatches):
            raise ValueError("Scenario comparison basis diagnostics differ.")
        deltas = (
            self.post_value,
            self.impact,
            *(item.post_value for item in self.components.items),
            *(item.impact for item in self.components.items),
        )
        if not self.compatible and any(item.difference.value is not None for item in deltas):
            raise ValueError("Incompatible scenario bases cannot expose differences.")
        return self


class ScenarioVersionResponse(ScenarioSchema):
    id: UUIDString
    account_id: UUIDString
    definition_id: UUIDString
    version_number: ScenarioRevision
    predecessor_id: UUIDString | None
    content: ScenarioVersionContent
    content_digest: Digest
    created_at: AwareInstant


class ScenarioDefinitionResponse(ScenarioSchema):
    id: UUIDString
    account_id: UUIDString
    name: ScenarioName
    revision: ScenarioRevision
    archived: StrictBool
    current_version_id: UUIDString
    created_at: AwareInstant
    updated_at: AwareInstant


class ScenarioRunResponse(ScenarioSchema):
    id: UUIDString
    account_id: UUIDString
    scenario_version_id: UUIDString
    portfolio_snapshot_id: UUIDString
    xray_run_id: UUIDString
    job_id: UUIDString
    state: Literal["queued", "running", "succeeded", "failed", "expired", "cancelled"]
    failure_code: RiskFailure | None
    created_at: AwareInstant
    expires_at: AwareInstant
    completed_at: AwareInstant | None
    input_digest: Digest
    result: ScenarioResultPage | None
    result_availability: Literal["pending", "available", "not_loaded", "expired", "unavailable"]

    @model_validator(mode="after")
    def atomic_state(self) -> Self:
        active = self.state in ("queued", "running")
        if (self.completed_at is None) != active or self.expires_at <= self.created_at:
            raise ValueError("Scenario operational timestamps disagree.")
        if self.completed_at is not None and self.completed_at < self.created_at:
            raise ValueError("Scenario completion precedes creation.")
        # An active retry retains its previous attempt's fixed failure code.
        if self.state in ("succeeded", "cancelled") and self.failure_code is not None:
            raise ValueError("Scenario failure metadata disagrees with its state.")
        if (self.result is not None) != (self.result_availability == "available"):
            raise ValueError("Scenario financial availability disagrees with its payload.")
        if self.result_availability in ("available", "not_loaded") and self.state != "succeeded":
            raise ValueError("Only succeeded scenarios have retained results.")
        if self.result_availability == "pending" and not active:
            raise ValueError("Only active scenarios have pending results.")
        if self.result is not None:
            context = self.result.context
            pins = context.pins
            if (
                context.run_id != self.id
                or context.input_digest != self.input_digest
                or pins.account_id != self.account_id
                or pins.scenario_version_id != self.scenario_version_id
                or pins.portfolio_snapshot_id != self.portfolio_snapshot_id
                or pins.xray_run_id != self.xray_run_id
            ):
                raise ValueError("Scenario result pins differ from its run.")
        return self


class ScenarioBasisMismatch(ScenarioSchema):
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
    left: ScenarioText
    right: ScenarioText


class ScenarioOperationalRunResponse(ScenarioRunResponse):
    result: None
    result_availability: Literal["pending", "not_loaded", "expired", "unavailable"]


class ScenarioPageResponse[Item](ScenarioSchema):
    items: Annotated[list[Item], Field(max_length=100)]
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: Annotated[StrictInt, Field(ge=0, le=250000)]

    @model_validator(mode="after")
    def bounded_page(self) -> Self:
        if len(self.items) > self.limit or len(self.items) > self.total:
            raise ValueError("Scenario collection page bounds differ.")
        return self


ScenarioComparisonPage.model_rebuild()
