"""Closed alert commands, filters and projections for the fixed HTTP/MCP surfaces."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)

from .reports import ReportSourceKind, ReportType
from .sources import CalendarDate, SourceLicense, SourceQuality
from .targets import (
    AwareInstant,
    CurrencyString,
    Cursor,
    DecimalString,
    Description,
    Digest,
    Name,
    Note,
    StableKey,
    UUIDString,
)

AlertFamily = Literal[
    "target_drift",
    "group_drift",
    "holding_drift",
    "concentration",
    "effective_company_concentration",
    "etf_overlap",
    "cash_threshold",
    "stale_data",
    "missing_coverage",
    "reconciliation_failure",
    "provider_failure",
    "failed_refresh",
    "dividend_received",
    "unusual_activity",
    "report_outcome",
]
AlertMetric = Literal[
    "portfolio_l1_drift",
    "group_absolute_drift",
    "holding_absolute_drift",
    "direct_max_weight",
    "direct_top_n_weight",
    "direct_hhi",
    "effective_entity_weight",
    "effective_top_n_weight",
    "effective_hhi",
    "etf_pair_overlap",
    "portfolio_duplicated_exposure",
    "cash_amount",
    "cash_weight",
    "source_age_seconds",
    "source_missing_sessions",
    "missing_count",
    "missing_fraction",
    "reconciliation_failed",
    "reconciliation_discrepancy_count",
    "provider_failed",
    "provider_consecutive_failures",
    "refresh_failed",
    "positive_dividend",
    "absolute_external_flow_amount",
    "activity_count",
    "unclassified_activity",
    "report_terminal",
]
AlertSeverity = Literal["info", "warning", "critical"]
AlertDiscrepancySeverity = Literal["info", "warning", "error", "critical"]
AlertLifecycle = Literal["draft", "active", "paused", "archived"]
AlertComparison = Literal["gt", "gte", "lt", "lte", "eq"]
AlertQualityPolicy = Literal["require_complete", "allow_degraded"]
AlertSourceFamily = Literal["valuation", "history", "price", "fx", "constituent", "classification"]
AlertActivityKind = Literal[
    "deposit",
    "withdrawal",
    "transfer_in",
    "transfer_out",
    "buy",
    "sell",
    "dividend",
    "interest",
    "fee",
    "tax",
    "internal_transfer",
    "fx_conversion",
    "corporate_action",
    "unknown",
]
AlertCapability = Literal[
    "metadata_instruments",
    "metadata_exchanges",
    "account_summary",
    "portfolio_positions",
    "pending_orders",
    "historical_orders",
    "historical_transactions",
    "historical_dividends",
    "historical_exports",
]
AlertSummaryState = Literal["open", "acknowledged", "resolved", "all"]
AlertCount = Annotated[StrictInt, Field(ge=0, le=2**63 - 1)]
AlertWindowSeconds = Annotated[StrictInt, Field(ge=300, le=2678400)]


class AlertSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def no_unknown_field_reflection(cls, value: object) -> object:
        if isinstance(value, dict) and any(key not in cls.model_fields for key in value):
            raise ValueError("The bounded alert object contains unexpected fields.")
        return value


class AlertDecimalPredicate(AlertSchema):
    comparison: AlertComparison
    threshold: DecimalString


class AlertIntegerPredicate(AlertSchema):
    comparison: AlertComparison
    threshold: AlertCount


class AlertBooleanPredicate(AlertSchema):
    comparison: Literal["eq"]
    threshold: StrictBool


class AlertTargetDriftPredicate(AlertDecimalPredicate):
    family: Literal["target_drift"]
    metric: Literal["portfolio_l1_drift"]
    target_version_id: UUIDString
    frontier_depth: Annotated[StrictInt, Field(ge=1, le=8)]


class AlertGroupDriftPredicate(AlertDecimalPredicate):
    family: Literal["group_drift"]
    metric: Literal["group_absolute_drift"]
    target_version_id: UUIDString
    group_node_id: UUIDString


class AlertHoldingDriftPredicate(AlertDecimalPredicate):
    family: Literal["holding_drift"]
    metric: Literal["holding_absolute_drift"]
    target_version_id: UUIDString
    holding_id: UUIDString


class AlertDirectMaxPredicate(AlertDecimalPredicate):
    family: Literal["concentration"]
    metric: Literal["direct_max_weight"]
    include_cash: StrictBool


class AlertDirectTopPredicate(AlertDecimalPredicate):
    family: Literal["concentration"]
    metric: Literal["direct_top_n_weight"]
    include_cash: StrictBool
    top_n: Annotated[StrictInt, Field(ge=1, le=50)] = 25


class AlertDirectHhiPredicate(AlertDecimalPredicate):
    family: Literal["concentration"]
    metric: Literal["direct_hhi"]
    include_cash: StrictBool


class AlertEffectiveEntityPredicate(AlertDecimalPredicate):
    family: Literal["effective_company_concentration"]
    metric: Literal["effective_entity_weight"]
    entity_id: UUIDString


class AlertEffectiveTopPredicate(AlertDecimalPredicate):
    family: Literal["effective_company_concentration"]
    metric: Literal["effective_top_n_weight"]
    top_n: Annotated[StrictInt, Field(ge=1, le=50)] = 25


class AlertEffectiveHhiPredicate(AlertDecimalPredicate):
    family: Literal["effective_company_concentration"]
    metric: Literal["effective_hhi"]


class AlertPairOverlapPredicate(AlertDecimalPredicate):
    family: Literal["etf_overlap"]
    metric: Literal["etf_pair_overlap"]
    left_fund_id: UUIDString
    right_fund_id: UUIDString

    @model_validator(mode="after")
    def ordered_distinct_pair(self) -> Self:
        if self.left_fund_id == self.right_fund_id:
            raise ValueError("Two distinct canonical funds are required.")
        self.left_fund_id, self.right_fund_id = sorted((self.left_fund_id, self.right_fund_id))
        return self


class AlertDuplicatedExposurePredicate(AlertDecimalPredicate):
    family: Literal["etf_overlap"]
    metric: Literal["portfolio_duplicated_exposure"]


class AlertCashAmountPredicate(AlertDecimalPredicate):
    family: Literal["cash_threshold"]
    metric: Literal["cash_amount"]
    currency: CurrencyString


class AlertCashWeightPredicate(AlertDecimalPredicate):
    family: Literal["cash_threshold"]
    metric: Literal["cash_weight"]


class AlertSourceAgePredicate(AlertIntegerPredicate):
    family: Literal["stale_data"]
    metric: Literal["source_age_seconds"]
    source_family: AlertSourceFamily
    source_id: UUIDString | None = None


class AlertMissingSessionsPredicate(AlertIntegerPredicate):
    family: Literal["stale_data"]
    metric: Literal["source_missing_sessions"]
    source_family: AlertSourceFamily
    source_id: UUIDString | None = None
    calendar_version_id: UUIDString


class AlertMissingCountPredicate(AlertIntegerPredicate):
    family: Literal["missing_coverage"]
    metric: Literal["missing_count"]
    domain: AlertSourceFamily
    source_id: UUIDString | None = None


class AlertMissingFractionPredicate(AlertDecimalPredicate):
    family: Literal["missing_coverage"]
    metric: Literal["missing_fraction"]
    domain: AlertSourceFamily
    source_id: UUIDString | None = None


class AlertReconciliationFailedPredicate(AlertBooleanPredicate):
    family: Literal["reconciliation_failure"]
    metric: Literal["reconciliation_failed"]
    discrepancy_severity: AlertDiscrepancySeverity | None = None


class AlertReconciliationCountPredicate(AlertIntegerPredicate):
    family: Literal["reconciliation_failure"]
    metric: Literal["reconciliation_discrepancy_count"]
    discrepancy_severity: AlertDiscrepancySeverity | None = None


class AlertProviderFailedPredicate(AlertBooleanPredicate):
    family: Literal["provider_failure"]
    metric: Literal["provider_failed"]
    provider_id: UUIDString
    window_seconds: AlertWindowSeconds


class AlertProviderConsecutivePredicate(AlertIntegerPredicate):
    family: Literal["provider_failure"]
    metric: Literal["provider_consecutive_failures"]
    provider_id: UUIDString
    window_seconds: AlertWindowSeconds


class AlertRefreshFailedPredicate(AlertSchema):
    family: Literal["failed_refresh"]
    metric: Literal["refresh_failed"]
    capability_family: AlertCapability | None = None


class AlertDividendPredicate(AlertSchema):
    family: Literal["dividend_received"]
    metric: Literal["positive_dividend"]
    instrument_id: UUIDString | None = None
    minimum_net_amount: DecimalString | None = None
    currency: CurrencyString | None = None

    @model_validator(mode="after")
    def positive_currency_minimum(self) -> Self:
        if (self.minimum_net_amount is None) != (self.currency is None):
            raise ValueError("A dividend minimum and currency must be supplied together.")
        if self.minimum_net_amount is not None and Decimal(self.minimum_net_amount) <= 0:
            raise ValueError("The dividend minimum must be positive.")
        return self


class AlertExternalFlowPredicate(AlertDecimalPredicate):
    family: Literal["unusual_activity"]
    metric: Literal["absolute_external_flow_amount"]
    window_seconds: AlertWindowSeconds
    activity_kind: AlertActivityKind | None = None
    currency: CurrencyString


class AlertActivityCountPredicate(AlertIntegerPredicate):
    family: Literal["unusual_activity"]
    metric: Literal["activity_count"]
    window_seconds: AlertWindowSeconds
    activity_kind: AlertActivityKind | None = None


class AlertUnclassifiedPredicate(AlertSchema):
    family: Literal["unusual_activity"]
    metric: Literal["unclassified_activity"]
    window_seconds: AlertWindowSeconds
    activity_kind: AlertActivityKind | None = None


class AlertReportOutcomePredicate(AlertSchema):
    family: Literal["report_outcome"]
    metric: Literal["report_terminal"]
    report_type: ReportType | Literal["all"] = "all"
    outcome: Literal["succeeded", "failed", "either"]


AlertPredicate = Annotated[
    AlertTargetDriftPredicate
    | AlertGroupDriftPredicate
    | AlertHoldingDriftPredicate
    | AlertDirectMaxPredicate
    | AlertDirectTopPredicate
    | AlertDirectHhiPredicate
    | AlertEffectiveEntityPredicate
    | AlertEffectiveTopPredicate
    | AlertEffectiveHhiPredicate
    | AlertPairOverlapPredicate
    | AlertDuplicatedExposurePredicate
    | AlertCashAmountPredicate
    | AlertCashWeightPredicate
    | AlertSourceAgePredicate
    | AlertMissingSessionsPredicate
    | AlertMissingCountPredicate
    | AlertMissingFractionPredicate
    | AlertReconciliationFailedPredicate
    | AlertReconciliationCountPredicate
    | AlertProviderFailedPredicate
    | AlertProviderConsecutivePredicate
    | AlertRefreshFailedPredicate
    | AlertDividendPredicate
    | AlertExternalFlowPredicate
    | AlertActivityCountPredicate
    | AlertUnclassifiedPredicate
    | AlertReportOutcomePredicate,
    Field(discriminator="metric"),
]


class AlertIntervalSchedule(AlertSchema):
    kind: Literal["interval"]
    anchor_at: AwareInstant
    interval_seconds: Annotated[StrictInt, Field(ge=300, le=86400)] = 300


class AlertDailySchedule(AlertSchema):
    kind: Literal["daily_utc"]
    minute_utc: Annotated[StrictInt, Field(ge=0, le=1439)]


AlertSchedule = Annotated[AlertIntervalSchedule | AlertDailySchedule, Field(discriminator="kind")]


class AlertRuleDefinition(AlertSchema):
    name: Name
    predicate: AlertPredicate
    severity: AlertSeverity
    quality_policy: AlertQualityPolicy = "require_complete"
    schedule: AlertSchedule
    cooldown_seconds: Annotated[StrictInt, Field(ge=0, le=604800)] = 0
    destination_ids: Annotated[list[UUIDString], Field(max_length=256)] = Field(
        default_factory=list
    )
    source_policy_version_id: UUIDString | None = None
    remediation: Description = ""

    @model_validator(mode="after")
    def unique_destinations(self) -> Self:
        if len(set(self.destination_ids)) != len(self.destination_ids):
            raise ValueError("Destination references must be unique.")
        return self


class CreateAlertRuleRequest(AlertSchema):
    account_id: UUIDString
    definition: AlertRuleDefinition


class AlertRuleVersionRequest(AlertSchema):
    definition: AlertRuleDefinition


class ActivateAlertRuleRequest(AlertSchema):
    version_id: UUIDString


class EmptyAlertRequest(AlertSchema):
    pass


class AlertEventNoteRequest(AlertSchema):
    note: Note | None = None


def _integer_query(value: object) -> object:
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,2}", value):
        return int(value)
    raise ValueError("A bounded integer selector is required.")


AlertPageLimit = Annotated[StrictInt, Field(ge=1, le=100), BeforeValidator(_integer_query)]
AlertTopLimit = Annotated[StrictInt, Field(ge=1, le=50), BeforeValidator(_integer_query)]


class AlertRuleListQuery(AlertSchema):
    account_id: UUIDString
    state: AlertLifecycle | Literal["all"] = "all"
    family: AlertFamily | Literal["all"] = "all"
    cursor: Cursor | None = None
    limit: AlertPageLimit = 25


class AlertRuleDetailQuery(AlertSchema):
    evaluation_cursor: Cursor | None = None
    evaluation_limit: AlertPageLimit = 25
    version_cursor: Cursor | None = None
    version_limit: AlertPageLimit = 25


class AlertEventListQuery(AlertSchema):
    account_id: UUIDString
    rule_id: UUIDString | None = None
    severity: AlertSeverity | Literal["all"] = "all"
    state: Literal["open", "resolved", "all"] = "all"
    start_date: CalendarDate | None = None
    end_date: CalendarDate | None = None
    cursor: Cursor | None = None
    limit: AlertPageLimit = 25

    @model_validator(mode="after")
    def paired_window(self) -> Self:
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("Both alert history dates are required.")
        if (
            self.start_date is not None
            and self.end_date is not None
            and not 0 <= (self.end_date - self.start_date).days <= 3660
        ):
            raise ValueError("The alert history period exceeds its date bounds.")
        return self


class AlertSummaryQuery(AlertSchema):
    state: AlertSummaryState = "open"
    severity: AlertSeverity | Literal["all"] = "all"
    top_n: AlertTopLimit = 25


class NotificationDestinationQuery(AlertSchema):
    account_id: UUIDString
    cursor: Cursor | None = None
    limit: AlertPageLimit = 25


class McpAlertSummaryRequest(AlertSchema):
    account_id: UUIDString
    start_date: CalendarDate
    end_date: CalendarDate
    source_cutoff_at: AwareInstant
    state: AlertSummaryState = "open"
    severity: AlertSeverity | Literal["all"] = "all"
    cursor: Cursor | None = None
    limit: Annotated[StrictInt, Field(ge=1, le=100)] = 25

    @model_validator(mode="after")
    def bounded_window(self) -> Self:
        if not 0 <= (self.end_date - self.start_date).days <= 3660:
            raise ValueError("The alert period exceeds its date bounds.")
        return self


AlertEvaluationOutcome = Literal["matched", "not_matched", "suppressed", "unavailable", "failed"]
AlertExecutionIntent = Literal["live", "observe_only"]
AlertReason = Literal[
    "missing_input",
    "missing_fx",
    "currency_mismatch",
    "unsupported",
    "ambiguous_source",
    "unknown_identity",
    "unknown_denominator",
    "incomplete_coverage",
    "material_quality",
    "inconclusive_lower_bound",
    "not_configured",
    "no_observations",
    "source_restricted",
    "source_expired",
    "input_bound_exceeded",
    "computation_failed",
    "filtered_out",
    "rule_paused",
    "rule_archived",
    "rule_superseded",
    "lease_expired",
    "attempts_exhausted",
    "publication_unavailable",
    "storage_unavailable",
    "access_denied",
]
AlertOrigin = Literal[
    "observed_provider",
    "normalized_provider",
    "derived_deterministic",
    "estimated",
    "unavailable",
    "provider",
    "derived",
]
AlertCanonicalFamily = Literal[
    "valuation",
    "target",
    "planning",
    "historical",
    "xray",
    "reconciliation",
    "refresh",
    "provider",
    "report",
]
AlertInputRole = Literal[
    "snapshot",
    "input",
    "result",
    "policy",
    "target_version",
    "mapping",
    "calendar",
    "event_revision",
    "license",
]


class AlertObservedBase(AlertSchema):
    metric: AlertMetric
    availability: Literal["available", "partial", "unavailable", "failed"]
    quality: SourceQuality
    origin: AlertOrigin
    context_key: StableKey
    currency: CurrencyString | None = None
    bound: Literal["exact", "lower_bound"] = "exact"
    positive_below_quantum: StrictBool = False
    reason: AlertReason | None = None

    @model_validator(mode="after")
    def truthful_availability(self) -> Self:
        if not isinstance(
            self,
            (
                AlertDecimalObservation,
                AlertIntegerObservation,
                AlertBooleanObservation,
                AlertEventObservation,
            ),
        ):
            raise ValueError("A registered observed metric type is required.")
        value = self.value
        missing = self.availability in {"unavailable", "failed"}
        if (value is None) != missing or (missing and self.reason is None):
            raise ValueError("An unavailable metric requires a reason and no numeric substitute.")
        if self.positive_below_quantum and (not isinstance(value, str) or Decimal(value) != 0):
            raise ValueError("Sub-quantum disclosure requires an actual rounded decimal zero.")
        if (
            self.metric in {"cash_amount", "absolute_external_flow_amount"}
            and value is not None
            and self.currency is None
        ):
            raise ValueError("A monetary metric requires its explicit currency.")
        return self


class AlertDecimalObservation(AlertObservedBase):
    kind: Literal["decimal"]
    value: DecimalString | None


class AlertIntegerObservation(AlertObservedBase):
    kind: Literal["integer"]
    value: AlertCount | None


class AlertBooleanObservation(AlertObservedBase):
    kind: Literal["boolean"]
    value: StrictBool | None


class AlertEventObservation(AlertObservedBase):
    kind: Literal["event"]
    value: StrictBool | None


AlertObservedMetric = Annotated[
    AlertDecimalObservation
    | AlertIntegerObservation
    | AlertBooleanObservation
    | AlertEventObservation,
    Field(discriminator="kind"),
]


class AlertCanonicalBinding(AlertSchema):
    family: AlertCanonicalFamily
    role: AlertInputRole
    subject_id: UUIDString
    content_digest: Digest
    parent_id: UUIDString | None = None
    method_key: StableKey | None = None
    method_version: StableKey | None = None
    numeric_policy_version: StableKey | None = None


class AlertSourceReference(AlertSchema):
    key: StableKey
    kind: ReportSourceKind
    subject_id: UUIDString
    content_digest: Digest
    effective_at: AwareInstant
    first_observed_at: AwareInstant
    parent_id: UUIDString | None = None
    provider_id: UUIDString | None = None
    license_version_id: UUIDString | None = None
    expires_at: AwareInstant | None = None


class AlertCoverageFact(AlertSchema):
    key: StableKey
    expected_count: AlertCount | None
    available_count: AlertCount | None
    complete: StrictBool | None
    covered_fraction: DecimalString | None = None

    @model_validator(mode="after")
    def valid_coverage(self) -> Self:
        if (
            self.expected_count is not None
            and self.available_count is not None
            and self.available_count > self.expected_count
        ):
            raise ValueError("Coverage exceeds its actual denominator.")
        if self.covered_fraction is not None and not Decimal(0) <= Decimal(
            self.covered_fraction
        ) <= Decimal(1):
            raise ValueError("Coverage must lie between zero and one.")
        return self


class AlertWarning(AlertSchema):
    code: StableKey
    message: Description
    source_reference_keys: Annotated[list[StableKey], Field(max_length=8192)] = Field(
        default_factory=list
    )


class AlertResultContext(AlertSchema):
    key: StableKey
    account_id: UUIDString
    source_cutoff_at: AwareInstant
    valuation_at: AwareInstant
    method_key: StableKey
    method_version: StableKey
    quality: SourceQuality
    reporting_currency: CurrencyString | None = None
    source_reference_keys: Annotated[list[StableKey], Field(max_length=8192)] = Field(
        default_factory=list
    )
    coverage: Annotated[list[AlertCoverageFact], Field(max_length=10000)] = Field(
        default_factory=list
    )
    warnings: Annotated[list[AlertWarning], Field(max_length=10000)] = Field(default_factory=list)
    assumptions: Annotated[list[Description], Field(max_length=10000)] = Field(default_factory=list)
    reconciliation_id: UUIDString | None = None


class AlertEventDecision(AlertSchema):
    identity: UUIDString
    revision_id: UUIDString | None
    correction_of: UUIDString | None
    outcome: AlertEvaluationOutcome
    decision: StrictBool | None
    observation: AlertObservedMetric
    deduplication_digest: Digest
    reason: AlertReason | None = None


class AlertEvaluationResult(AlertSchema):
    rule_version_id: UUIDString
    input_digest: Digest
    scheduled_for: AwareInstant
    source_cutoff_at: AwareInstant
    execution_intent: AlertExecutionIntent
    outcome: AlertEvaluationOutcome
    decision: StrictBool | None
    contexts: Annotated[list[AlertResultContext], Field(max_length=256)]
    observation: AlertObservedMetric | None = None
    event_decisions: Annotated[list[AlertEventDecision], Field(max_length=10000)] = Field(
        default_factory=list
    )
    reason: AlertReason | None = None
    schema_version: Literal["1.0.0"] = "1.0.0"
    method_key: Literal["alert_evaluation_v1"] = "alert_evaluation_v1"
    method_version: Literal["1.0.0"] = "1.0.0"

    @model_validator(mode="after")
    def exact_cutoff_and_decision(self) -> Self:
        if self.scheduled_for != self.source_cutoff_at:
            raise ValueError("The source cutoff must equal the scheduled slot.")
        expected = {"matched": True, "not_matched": False}.get(self.outcome)
        if self.decision is not expected or (self.decision is None and self.reason is None):
            raise ValueError("Evaluation state and decision disagree.")
        return self


class AlertEvaluationView(AlertSchema):
    id: UUIDString
    job_id: UUIDString
    rule_id: UUIDString
    rule_version_id: UUIDString
    account_id: UUIDString
    input_digest: Digest
    result_digest: Digest
    rule_content_digest: Digest
    definition: AlertRuleDefinition | None
    source_references: Annotated[list[AlertSourceReference], Field(max_length=8192)]
    canonical_bindings: Annotated[list[AlertCanonicalBinding], Field(max_length=10000)]
    licenses: Annotated[list[SourceLicense], Field(max_length=8192)]
    scheduled_for: AwareInstant
    evaluated_at: AwareInstant
    outcome: AlertEvaluationOutcome
    execution_intent: AlertExecutionIntent
    result: AlertEvaluationResult | None
    reproducibility: Literal["retained", "expired", "source_restricted"]
    expires_at: AwareInstant

    @model_validator(mode="after")
    def retained_result_binding(self) -> Self:
        retained = self.reproducibility == "retained"
        if (self.result is not None) != retained or (self.definition is not None) != retained:
            raise ValueError("A retained evaluation requires its actual result and definition.")
        if not retained and (self.source_references or self.canonical_bindings or self.licenses):
            raise ValueError("A purged evaluation cannot retain licensed proof.")
        if self.result is not None:
            result = self.result
            if (
                result.rule_version_id != self.rule_version_id
                or result.input_digest != self.input_digest
                or result.scheduled_for != self.scheduled_for
                or result.outcome != self.outcome
                or result.execution_intent != self.execution_intent
            ):
                raise ValueError("The evaluation projection differs from its immutable result.")
            sources = {item.key for item in self.source_references}
            contexts = {item.key for item in result.contexts}
            if len(sources) != len(self.source_references) or len(contexts) != len(result.contexts):
                raise ValueError("Evaluation reference identities must be unique.")
            for context in result.contexts:
                if (
                    context.account_id != self.account_id
                    or context.source_cutoff_at != self.scheduled_for
                    or not set(context.source_reference_keys) <= sources
                ):
                    raise ValueError("Evaluation context has an unbound account, cutoff or source.")
                if any(
                    not set(warning.source_reference_keys) <= sources
                    for warning in context.warnings
                ):
                    raise ValueError("Evaluation warning refers to an absent source.")
            observations = [item.observation for item in result.event_decisions]
            if result.observation is not None:
                observations.append(result.observation)
            if any(item.context_key not in contexts for item in observations):
                raise ValueError("Evaluation observation refers to an absent context.")
        return self


class AlertPage[ItemT](AlertSchema):
    items: Annotated[list[ItemT], Field(max_length=100)]
    total: AlertCount
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    next_cursor: Cursor | None

    @model_validator(mode="after")
    def exact_page_bounds(self) -> Self:
        if len(self.items) > min(self.limit, self.total):
            raise ValueError("The alert page exceeds its exact bounds.")
        return self


class AlertEvaluationPage(AlertPage[AlertEvaluationView]):
    pass


class AlertRuleVersion(AlertSchema):
    id: UUIDString
    rule_id: UUIDString
    account_id: UUIDString
    version_number: Annotated[StrictInt, Field(ge=1)]
    created_at: AwareInstant
    content_digest: Digest
    definition: AlertRuleDefinition


class AlertRuleVersionDetail(AlertSchema):
    version: AlertRuleVersion
    rule_revision: Annotated[StrictInt, Field(ge=1)]


class AlertRuleVersionPage(AlertPage[AlertRuleVersion]):
    pass


class AlertRuleDetail(AlertSchema):
    id: UUIDString
    account_id: UUIDString
    revision: Annotated[StrictInt, Field(ge=1)]
    lifecycle: AlertLifecycle
    created_at: AwareInstant
    updated_at: AwareInstant
    latest_version: AlertRuleVersion
    active_version: AlertRuleVersion | None
    next_scheduled_for: AwareInstant | None
    latest_evaluation: AlertEvaluationView | None
    evaluation_page: AlertEvaluationPage
    version_page: AlertRuleVersionPage

    @model_validator(mode="after")
    def same_rule_versions(self) -> Self:
        versions = [
            self.latest_version,
            *([self.active_version] if self.active_version else []),
            *self.version_page.items,
        ]
        if any(item.rule_id != self.id or item.account_id != self.account_id for item in versions):
            raise ValueError("Rule versions must belong to the actual rule/account.")
        evaluations = [
            *self.evaluation_page.items,
            *([self.latest_evaluation] if self.latest_evaluation else []),
        ]
        if any(
            item.rule_id != self.id or item.account_id != self.account_id for item in evaluations
        ):
            raise ValueError("Rule evaluations must belong to the actual rule/account.")
        return self


class AlertRulePage(AlertPage[AlertRuleDetail]):
    pass


class NotificationDestination(AlertSchema):
    id: UUIDString
    channel: Literal["in_app", "email", "webhook"]
    label: Name
    state: Literal["configured", "unavailable", "disabled"]


class NotificationDestinationPage(AlertPage[NotificationDestination]):
    pass


class AlertAcknowledgment(AlertSchema):
    id: UUIDString
    event_id: UUIDString
    principal_id: UUIDString
    acknowledged_at: AwareInstant
    event_revision: Annotated[StrictInt, Field(ge=1)]
    note: Note | None = None


class AlertDeliveryView(AlertSchema):
    id: UUIDString
    destination_id: UUIDString
    destination_version_id: UUIDString
    channel: Literal["in_app", "email", "webhook"]
    state: Literal["queued", "running", "succeeded", "failed", "unavailable", "cancelled"]
    attempts: Annotated[StrictInt, Field(ge=0, le=4)]
    reason: StableKey | None = None


class AlertDeliverySummary(AlertSchema):
    in_app_notification_id: UUIDString
    created_at: AwareInstant
    notification_state: Literal["eligible", "suppressed_cooldown", "external_delivery_unavailable"]
    external: Annotated[list[AlertDeliveryView], Field(max_length=256)] = Field(
        default_factory=list
    )


class AlertEventDetail(AlertSchema):
    id: UUIDString
    account_id: UUIDString
    rule_id: UUIDString
    rule_version_id: UUIDString
    evaluation_id: UUIDString
    revision: Annotated[StrictInt, Field(ge=1)]
    deduplication_digest: Digest
    severity: AlertSeverity
    episode_state: Literal["open", "resolved"]
    occurred_at: AwareInstant
    recorded_at: AwareInstant
    updated_at: AwareInstant
    evaluation: AlertEvaluationView
    delivery: AlertDeliverySummary
    acknowledgment: AlertAcknowledgment | None = None
    resolved_at: AwareInstant | None = None
    resolution_reason: (
        Literal["condition_cleared", "manual", "rule_superseded", "rule_archived"] | None
    ) = None
    correction_of: UUIDString | None = None
    episode_ordinal: Annotated[StrictInt, Field(ge=1)] | None = None
    remediation: Description = ""

    @model_validator(mode="after")
    def event_binding(self) -> Self:
        if (
            self.evaluation.id != self.evaluation_id
            or self.evaluation.rule_id != self.rule_id
            or self.evaluation.rule_version_id != self.rule_version_id
            or self.evaluation.account_id != self.account_id
        ):
            raise ValueError("The event evaluation identity is inconsistent.")
        if self.acknowledgment is not None and self.acknowledgment.event_id != self.id:
            raise ValueError("The acknowledgment belongs to another event.")
        if (self.episode_state == "resolved") != (
            self.resolved_at is not None and self.resolution_reason is not None
        ):
            raise ValueError("Resolved events require their actual transition and reason.")
        return self


class AlertEventPage(AlertPage[AlertEventDetail]):
    pass


class AlertSummaryCounts(AlertSchema):
    total_count: AlertCount
    open_count: AlertCount
    resolved_count: AlertCount
    acknowledged_count: AlertCount

    @model_validator(mode="after")
    def independent_acknowledgment_count(self) -> Self:
        if (
            self.open_count + self.resolved_count != self.total_count
            or self.acknowledged_count > self.total_count
        ):
            raise ValueError("The independent alert counts are inconsistent.")
        return self


class AlertSummary(AlertSchema):
    account_id: UUIDString
    source_cutoff_at: AwareInstant
    counts: AlertSummaryCounts
    items: Annotated[list[AlertEventDetail], Field(max_length=50)]
    top_n: Annotated[StrictInt, Field(ge=1, le=50)]
    returned_count: AlertCount
    omitted_count: AlertCount

    @model_validator(mode="after")
    def exact_top_counts(self) -> Self:
        if (
            len(self.items) != self.returned_count
            or self.returned_count > self.top_n
            or self.returned_count + self.omitted_count != self.counts.total_count
            or any(item.account_id != self.account_id for item in self.items)
        ):
            raise ValueError("The alert summary sample does not match its full-filter counts.")
        return self


class AlertSummaryPage(AlertSchema):
    account_id: UUIDString
    source_cutoff_at: AwareInstant
    counts: AlertSummaryCounts
    page: AlertEventPage

    @model_validator(mode="after")
    def same_page_filter(self) -> Self:
        if self.page.total != self.counts.total_count or any(
            item.account_id != self.account_id for item in self.page.items
        ):
            raise ValueError("The summary page and its full-filter counts disagree.")
        return self
