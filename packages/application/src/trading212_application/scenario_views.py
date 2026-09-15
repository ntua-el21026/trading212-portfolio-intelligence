"""Distinct compact scenario representations; these are never canonical saved results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from trading212_domain.enums import QualityState
from trading212_domain.historical import (
    HistoricalAvailability,
    HistoricalCoverage,
    HistoricalCoverageKey,
    HistoricalReason,
    HistoricalWindow,
)
from trading212_domain.historical_results import HistoricalMethod
from trading212_domain.scenario import ScenarioAssumption, ScenarioReason, ScenarioVersionContent
from trading212_domain.scenario_execution import ScenarioInputPins, ScenarioReplaySelection
from trading212_domain.scenario_result import ScenarioBasisMismatch, ScenarioRatioMetric
from trading212_domain.values import CurrencyCode, Money
from trading212_domain.xray import XrayReason

from .risk import PremiumJobState

SCENARIO_PUBLIC_VIEW_VERSION: Literal["scenario_compact_v1"] = "scenario_compact_v1"


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioPreview[Item]:
    items: tuple[Item, ...]
    omitted_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioMoneyView:
    value: Money | None
    quality: QualityState
    reason: ScenarioReason | None
    confidence: Decimal | None
    source_reference_ids: ScenarioPreview[UUID]


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioSubjectView:
    dimension: Literal["instrument", "entity"]
    state: Literal["known", "unknown", "not_applicable"]
    subject_id: UUID | None
    reason: ScenarioReason | None
    upstream_reason: XrayReason | None
    identity_decision_ids: ScenarioPreview[UUID]
    source_reference_ids: ScenarioPreview[UUID]


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioClassificationView:
    dimension: Literal["sector", "region"]
    state: Literal["known", "unknown", "not_applicable"]
    taxonomy_id: UUID | None
    taxonomy_version: str | None
    bucket_key: str | None
    decision_key: str | None
    assignment_ids: ScenarioPreview[UUID]
    evidence_ids: ScenarioPreview[UUID]
    source_reference_ids: ScenarioPreview[UUID]
    reason: ScenarioReason | None
    upstream_reason: XrayReason | None
    confidence: Decimal | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioCurrencyView:
    state: Literal["known", "unknown"]
    currency: CurrencyCode | None
    basis: Literal["economic_classification", "snapshot_cash", "constituent_cash", "unknown"]
    decision_key: str | None
    taxonomy_id: UUID | None
    taxonomy_version: str | None
    cash_id: UUID | None
    candidate_id: UUID | None
    holding_id: UUID | None
    assignment_ids: ScenarioPreview[UUID]
    evidence_ids: ScenarioPreview[UUID]
    source_reference_ids: ScenarioPreview[UUID]
    reason: ScenarioReason | None
    upstream_reason: XrayReason | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioExposureView:
    path_key: str
    root_key: str
    root_kind: Literal["position", "cash"]
    position_id: UUID | None
    snapshot_cash_id: UUID | None
    root_instrument_id: UUID | None
    explicit_cash: bool
    instrument: ScenarioSubjectView
    entity: ScenarioSubjectView
    sector: ScenarioClassificationView
    region: ScenarioClassificationView
    economic_currency: ScenarioCurrencyView
    pre_value: ScenarioMoneyView
    quality: QualityState
    confidence: Decimal | None
    upstream_reason: XrayReason | None
    source_reference_ids: ScenarioPreview[UUID]


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioSensitivityView:
    rule_key: str
    driver_id: UUID
    driver_definition_version_id: UUID
    driver_definition_digest: str
    driver_kind: Literal["rate", "factor"]
    shock_unit: Literal["absolute_rate_change", "simple_factor_return"]
    driver_evidence_reference_ids: ScenarioPreview[UUID]
    version_id: UUID
    candidate_observation_ids: ScenarioPreview[UUID]
    observation_id: UUID | None
    coefficient: Decimal | None
    shock_size: Decimal
    effect_ratio: ScenarioRatioMetric
    reason: ScenarioReason | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioEffectsView:
    price_ratio: ScenarioRatioMetric
    factor_ratio: ScenarioRatioMetric
    fx_ratio: ScenarioRatioMetric
    price: ScenarioMoneyView
    factor: ScenarioMoneyView
    fx: ScenarioMoneyView
    interaction: ScenarioMoneyView


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioDiagnosticView:
    key: str
    reason: ScenarioReason
    path_key: str | None
    rule_key: str | None
    upstream_xray_reason: XrayReason | None
    upstream_historical_reason: HistoricalReason | None
    source_reference_ids: ScenarioPreview[UUID]
    source_use_keys: ScenarioPreview[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioReplayChangeView:
    path_key: str
    local_return: ScenarioRatioMetric
    fx_return: ScenarioRatioMetric
    reporting_return: ScenarioRatioMetric
    basis: Literal["local_with_fx", "unavailable"]
    source_use_keys: ScenarioPreview[str]
    conversion_keys: ScenarioPreview[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioComponentView:
    exposure: ScenarioExposureView
    partition: Literal["covered", "uncovered", "excluded"]
    winning_price_rule_key: str | None
    matching_exclusion_keys: tuple[str, ...]
    uncertain_rule_keys: tuple[str, ...]
    sensitivity_uses: tuple[ScenarioSensitivityView, ...]
    effects: ScenarioEffectsView
    post_value: ScenarioMoneyView
    impact: ScenarioMoneyView
    rounding_residual: ScenarioMoneyView
    money_basis: Literal["resolved", "zero_pre_value", "provably_zero_effect", "unavailable"]
    diagnostic_keys: ScenarioPreview[str]
    replay_change: ScenarioReplayChangeView | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioSummaryView:
    terminal_pre_value: ScenarioMoneyView
    covered_pre_value: ScenarioMoneyView
    uncovered_pre_value: ScenarioMoneyView
    excluded_pre_value: ScenarioMoneyView
    covered_count: int
    uncovered_count: int
    excluded_count: int
    missing_pre_value_count: int
    uncertain_money_count: int
    covered_post_value: ScenarioMoneyView
    excluded_post_value: ScenarioMoneyView
    provably_unchanged_uncovered_value: ScenarioMoneyView
    post_value: ScenarioMoneyView
    impact: ScenarioMoneyView
    effects: ScenarioEffectsView
    rounding_residual: ScenarioMoneyView
    component_sum_residual: ScenarioMoneyView


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioHistoricalWarningView:
    reason_code: HistoricalReason
    coverage_key: HistoricalCoverageKey | None
    reference_ids: ScenarioPreview[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioReplayContextView:
    selection: ScenarioReplaySelection
    input_digest: str
    window: HistoricalWindow
    method: HistoricalMethod
    primitive_methods: tuple[HistoricalMethod, ...]
    source_policy_version: str | None
    accounting_policy_version: str
    coverage: HistoricalCoverage
    quality: QualityState
    availability: HistoricalAvailability
    reconstruction: Literal["point_in_time", "restated"]
    schema_version: str
    holdings_evidence_at: datetime
    holdings_knowledge_cutoff_at: datetime
    change_count: int
    source_use_count: int
    conversion_count: int
    source_reference_ids: ScenarioPreview[str]
    warnings: ScenarioPreview[ScenarioHistoricalWarningView]
    assumptions: tuple[str, ...]
    diagnostics: ScenarioPreview[ScenarioDiagnosticView]


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioResultContextView:
    run_id: UUID
    result_id: UUID
    saved_result_digest: str
    input_digest: str
    pins: ScenarioInputPins
    definition: ScenarioVersionContent
    valuation_at: datetime
    summary: ScenarioSummaryView
    upstream_portfolio_value: ScenarioMoneyView
    upstream_partition_difference: ScenarioMoneyView
    upstream_residual_keys: ScenarioPreview[str]
    replay: ScenarioReplayContextView | None
    diagnostics: ScenarioPreview[ScenarioDiagnosticView]
    assumptions: tuple[ScenarioAssumption, ...]
    sensitivity_source_row_count: int
    method_version: str
    schema_version: str
    numerical_profile: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioComponentPage[Item]:
    items: tuple[Item, ...]
    next_cursor: str | None
    component_limit: int
    total: int
    start_ordinal: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioResultPage:
    context: ScenarioResultContextView
    components: ScenarioComponentPage[ScenarioComponentView]
    content_digest: str
    view_version: Literal["scenario_compact_v1"] = SCENARIO_PUBLIC_VIEW_VERSION


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioDeltaView:
    before: ScenarioMoneyView
    after: ScenarioMoneyView
    difference: ScenarioMoneyView


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioComparisonComponentView:
    root_key: str
    path_key: str
    before: ScenarioComponentView | None
    after: ScenarioComponentView | None
    post_value: ScenarioDeltaView
    impact: ScenarioDeltaView


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioComparisonPage:
    before: ScenarioResultContextView
    after: ScenarioResultContextView
    compatible: bool
    mismatches: tuple[ScenarioBasisMismatch, ...]
    post_value: ScenarioDeltaView
    impact: ScenarioDeltaView
    components: ScenarioComponentPage[ScenarioComparisonComponentView]
    content_digest: str
    view_version: Literal["scenario_compact_v1"] = SCENARIO_PUBLIC_VIEW_VERSION


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioVersionView:
    id: UUID
    account_id: UUID
    definition_id: UUID
    version_number: int
    predecessor_id: UUID | None
    content: ScenarioVersionContent
    content_digest: str
    created_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioDefinitionView:
    id: UUID
    account_id: UUID
    name: str
    revision: int
    archived: bool
    current_version_id: UUID
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioRunView:
    id: UUID
    account_id: UUID
    scenario_version_id: UUID
    portfolio_snapshot_id: UUID
    xray_run_id: UUID
    job_id: UUID
    state: PremiumJobState
    failure_code: str | None
    created_at: datetime
    expires_at: datetime
    completed_at: datetime | None
    input_digest: str
    result: ScenarioResultPage | None
    result_availability: Literal["pending", "available", "not_loaded", "expired", "unavailable"]
