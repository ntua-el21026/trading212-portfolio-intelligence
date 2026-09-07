"""Closed, bounded planning wire contracts shared by HTTP, MCP and web clients."""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from .targets import (
    AwareInstant,
    CurrencyString,
    Cursor,
    DecimalString,
    Digest,
    IdempotencyKey,
    Name,
    StableKey,
    TargetConstraint,
    UUIDString,
    WeightString,
)


def _nonnegative(value: str) -> str:
    if Decimal(value) < 0:
        raise ValueError("A nonnegative decimal amount is required.")
    return value


def _positive(value: str) -> str:
    if Decimal(value) <= 0:
        raise ValueError("A positive decimal amount is required.")
    return value


def _quantum(value: str) -> str:
    number = Decimal(value)
    if number <= 0 or number.normalize().as_tuple().digits != (1,):
        raise ValueError("Monetary quantum must be a positive power of ten.")
    return value


def _unique_ids(value: list[str]) -> list[str]:
    if len(value) != len(set(value)):
        raise ValueError("Repeated identifiers are not permitted.")
    return value


NonnegativeDecimal = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^(?:0|[1-9][0-9]{0,19})(?:\.[0-9]{1,18})?$"),
    AfterValidator(_nonnegative),
]
PositiveDecimal = Annotated[DecimalString, AfterValidator(_positive)]
QuantumString = Annotated[DecimalString, AfterValidator(_quantum)]
UUIDSet = Annotated[list[UUIDString], Field(max_length=256), AfterValidator(_unique_ids)]
PlanMode = Literal["global", "hierarchical", "restricted", "cash_only"]
CoveragePolicy = Literal["require_complete", "allow_degraded"]
JobState = Literal["queued", "running", "succeeded", "failed", "expired", "cancelled"]
PlanOutcome = Literal["optimal", "feasible_nonoptimal", "infeasible", "unavailable", "failed"]


class PlanningSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def no_unknown_field_reflection(cls, value: object) -> object:
        if isinstance(value, dict) and any(key not in cls.model_fields for key in value):
            # SDK validation messages otherwise repeat the caller-controlled field name.
            raise ValueError("The bounded planning object contains unexpected fields.")
        return value


class PlanningMoney(PlanningSchema):
    amount: DecimalString
    currency: CurrencyString


class ContributionMoney(PlanningSchema):
    amount: NonnegativeDecimal
    currency: CurrencyString


class PlanningListingPreference(PlanningSchema):
    holding_id: UUIDString
    listing_id: UUIDString


class PlanningPageQuery(PlanningSchema):
    cursor: Cursor | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 25


class ActualVsTargetQuery(PlanningPageQuery):
    snapshot_id: UUIDString
    virtual_portfolio_id: UUIDString
    target_version_id: UUIDString
    reporting_currency: CurrencyString
    node_id: UUIDString | None = None


class DriftAnalysisQuery(PlanningSchema):
    snapshot_id: UUIDString
    virtual_portfolio_id: UUIDString
    target_version_id: UUIDString
    reporting_currency: CurrencyString
    basis: Literal["direct", "effective"] = "direct"
    top_n: Annotated[int, Field(ge=1, le=50)] = 25


class ContributionPlanQuery(PlanningPageQuery):
    account_id: UUIDString
    plan_id: UUIDString | None = None
    include_revisions: bool = False
    virtual_portfolio_id: UUIDString | None = None
    state: JobState | None = None
    outcome: PlanOutcome | None = None

    @model_validator(mode="after")
    def history_selection(self) -> Self:
        if (self.plan_id is not None) != self.include_revisions:
            raise ValueError("Revision history requires one explicit plan identity.")
        return self


class ContributionPlanDetailQuery(PlanningPageQuery):
    plan_revision_id: UUIDString | None = None


class PlanningConstraint(PlanningSchema):
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
    node_id: UUIDString | None = None
    amount: DecimalString | None = None
    currency: CurrencyString | None = None
    weight: WeightString | None = None
    enabled: StrictBool | None = None
    count: Annotated[StrictInt, Field(ge=0, le=256)] | None = None
    coefficient: DecimalString | None = None

    @model_validator(mode="after")
    def checked_variant(self) -> Self:
        fields = self.model_dump(exclude={"node_id"})
        fields["node_key"] = self.node_id
        TargetConstraint.model_validate(fields)
        return self


class McpPlanAllocationConstraint(PlanningSchema):
    holding_id: UUIDString
    minimum_amount: NonnegativeDecimal
    value_increment: PositiveDecimal
    maximum_post_weight: WeightString | None = None


class PlanningRequestOptions(PlanningSchema):
    account_id: UUIDString
    virtual_portfolio_id: UUIDString
    target_version_id: UUIDString
    snapshot_id: UUIDString
    contribution: ContributionMoney
    mode: PlanMode
    coverage_policy: CoveragePolicy = "require_complete"
    eligible_holding_ids: UUIDSet | None = None
    excluded_holding_ids: UUIDSet = Field(default_factory=list)
    restricted_group_ids: UUIDSet = Field(default_factory=list)
    listing_preferences: Annotated[list[PlanningListingPreference], Field(max_length=256)] = Field(
        default_factory=list
    )
    cash_reserve: NonnegativeDecimal | None = None
    monetary_quantum: QuantumString | None = None

    @model_validator(mode="after")
    def consistent_selection(self) -> Self:
        if (self.mode == "restricted") != bool(self.restricted_group_ids):
            raise ValueError("Restricted groups are required only in restricted mode.")
        if set(self.eligible_holding_ids or ()) & set(self.excluded_holding_ids):
            raise ValueError("A holding cannot be both eligible and excluded.")
        if len({item.holding_id for item in self.listing_preferences}) != len(
            self.listing_preferences
        ):
            raise ValueError("A holding permits one listing preference.")
        return self


class CreateContributionPlanRequest(PlanningRequestOptions):
    holding_constraints: Annotated[list[McpPlanAllocationConstraint], Field(max_length=256)] = (
        Field(default_factory=list)
    )
    allocation_constraints: Annotated[list[PlanningConstraint], Field(max_length=256)] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def unique_constraints(self) -> Self:
        if len({item.holding_id for item in self.holding_constraints}) != len(
            self.holding_constraints
        ):
            raise ValueError("A holding permits one allocation constraint override.")
        if len({item.key for item in self.allocation_constraints}) != len(
            self.allocation_constraints
        ):
            raise ValueError("Constraint keys must be unique.")
        return self


class McpCreateContributionPlanRequest(PlanningRequestOptions):
    idempotency_key: IdempotencyKey
    allocation_constraints: Annotated[list[McpPlanAllocationConstraint], Field(max_length=256)] = (
        Field(default_factory=list)
    )

    @model_validator(mode="after")
    def unique_constraints(self) -> Self:
        if len({item.holding_id for item in self.allocation_constraints}) != len(
            self.allocation_constraints
        ):
            raise ValueError("A holding permits one allocation constraint override.")
        return self


PlanningCode = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")
]
PlanningText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=240)]
PlanningQualityState = Literal[
    "fresh", "stale", "partial", "estimated", "unreconciled", "unavailable", "failed"
]
PlanningAvailability = Literal["available", "partial", "unavailable", "failed"]


class PlanningSource(PlanningSchema):
    kind: Literal[
        "portfolio_snapshot",
        "target_version",
        "mapping_revision",
        "fx_snapshot",
        "provider_fx_observation",
        "provider_observation",
        "calculation_run",
    ]
    id: UUIDString
    content_digest: Digest
    version: PlanningCode
    effective_at: AwareInstant
    first_observed_at: AwareInstant


class PlanningExplanation(PlanningSchema):
    code: PlanningCode
    message: PlanningText
    severity: Literal["info", "warning", "error"] = "warning"
    node_keys: Annotated[list[StableKey], Field(max_length=256)] = Field(default_factory=list)
    constraint_keys: Annotated[list[StableKey], Field(max_length=1280)] = Field(
        default_factory=list
    )


class PlanningCoverage(PlanningSchema):
    complete: StrictBool
    denominator: PlanningMoney | None
    valued_total: PlanningMoney
    matched_total: PlanningMoney
    unclassified_total: PlanningMoney
    matched_weight: DecimalString | None
    unclassified_weight: DecimalString | None
    unresolved_target_weight: DecimalString
    basis: Literal["full_reporting_currency_valuation"] = "full_reporting_currency_valuation"


class PlanningMethod(PlanningSchema):
    name: Literal["drift_v1", "contribution_weighted_drift_v1"]
    version: Literal["1.0.0"]


class PlanningDataQuality(PlanningSchema):
    state: PlanningQualityState
    coverage_start_at: AwareInstant
    coverage_end_at: AwareInstant
    missing_inputs: Annotated[list[PlanningCode], Field(max_length=128)]
    evaluated_at: AwareInstant
    reconciled: StrictBool
    warnings: Annotated[list[PlanningExplanation], Field(max_length=1280)]


class PlanningResultContext(PlanningSchema):
    account_id: UUIDString
    virtual_portfolio_id: UUIDString
    target_version_id: UUIDString
    snapshot_id: UUIDString
    reporting_currency: CurrencyString
    as_of: AwareInstant
    source_cutoff_at: AwareInstant
    calculated_at: AwareInstant
    method: PlanningMethod
    schema_version: Literal["1.0.0"]
    input_digest: Digest
    sources: Annotated[list[PlanningSource], Field(max_length=8192)]
    availability: PlanningAvailability
    reason_code: PlanningCode | None
    data_quality: PlanningDataQuality
    coverage: PlanningCoverage
    warnings: Annotated[list[PlanningExplanation], Field(max_length=1280)]
    assumptions: Annotated[list[PlanningExplanation], Field(max_length=256)]


class PlanningDriftRow(PlanningSchema):
    key: StableKey
    node_id: UUIDString | None
    holding_id: UUIDString | None
    kind: Literal["group", "holding", "cash", "unclassified"]
    parent_key: StableKey | None
    name: Name
    depth: Annotated[StrictInt, Field(ge=0, le=8)]
    listing_id: UUIDString | None
    instrument_id: UUIDString | None
    target_weight: DecimalString
    actual_value: PlanningMoney | None
    actual_direct_weight: DecimalString | None
    effective_weight: DecimalString | None
    effective_weight_reason: PlanningCode
    signed_drift: DecimalString | None
    absolute_drift: DecimalString | None
    relative_drift: DecimalString | None
    relative_drift_reason: PlanningCode | None
    classification: Literal["underweight", "on_target", "overweight"] | None
    monetary_gap: PlanningMoney | None
    quality: PlanningQualityState


class PlanningDriftTotals(PlanningSchema):
    value: PlanningMoney | None
    cash: PlanningMoney | None
    unclassified: PlanningMoney
    l1_drift: DecimalString | None
    weighted_squared_drift: DecimalString | None
    effective_weight_rounding_residual: DecimalString | None
    frontier_keys: Annotated[list[StableKey], Field(max_length=4353)]
    group_count: Annotated[StrictInt, Field(ge=0, le=256)]
    holding_count: Annotated[StrictInt, Field(ge=0, le=256)]
    unclassified_count: Annotated[StrictInt, Field(ge=0, le=4096)]


class PlanningPage[ItemT](PlanningSchema):
    items: Annotated[list[ItemT], Field(max_length=100)]
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: Annotated[StrictInt, Field(ge=0)]

    @model_validator(mode="after")
    def bounded_page(self) -> Self:
        if len(self.items) > self.limit or len(self.items) > self.total:
            raise ValueError("Returned page membership exceeds its declared bound.")
        return self


class PlanningNodeIdentity(PlanningSchema):
    id: UUIDString
    key: StableKey
    holding_id: UUIDString | None = None


class ActualVsTargetResult(PlanningSchema):
    context: PlanningResultContext
    calculated_at: AwareInstant
    totals: PlanningDriftTotals
    rows: PlanningPage[PlanningDriftRow]
    target_identities: Annotated[list[PlanningNodeIdentity], Field(max_length=256)]
    content_digest: Digest
    node_id: UUIDString | None = None


class DriftAnalysisResult(PlanningSchema):
    context: PlanningResultContext
    calculated_at: AwareInstant
    totals: PlanningDriftTotals
    groups: Annotated[list[PlanningDriftRow], Field(max_length=50)]
    leaves: Annotated[list[PlanningDriftRow], Field(max_length=50)]
    cash_and_unclassified: Annotated[list[PlanningDriftRow], Field(max_length=50)]
    basis: Literal["direct", "effective"]
    top_n: Annotated[StrictInt, Field(ge=1, le=50)]
    eligible_rows: Annotated[StrictInt, Field(ge=0, le=4353)]
    omitted_rows: Annotated[StrictInt, Field(ge=0, le=4353)]
    content_digest: Digest

    @model_validator(mode="after")
    def sample_count(self) -> Self:
        returned = len(self.groups) + len(self.leaves) + len(self.cash_and_unclassified)
        if returned > self.top_n or returned + self.omitted_rows != self.eligible_rows:
            raise ValueError("The bounded drift sample must disclose its full-set count.")
        return self


class PlanningObjective(PlanningSchema):
    scores: Annotated[list[DecimalString], Field(min_length=1, max_length=9)]
    quantum: DecimalString
    rounding: Literal["ROUND_HALF_EVEN"]
    rounding_error_bound: Literal["half_quantum"]


class PlanningEffectiveConstraint(TargetConstraint):
    pass


class ContributionPlanLine(PlanningSchema):
    ordinal: Annotated[StrictInt, Field(ge=0, le=255)]
    node_id: UUIDString
    node_key: StableKey
    holding_id: UUIDString
    instrument_id: UUIDString | None
    listing_id: UUIDString | None
    current_value: PlanningMoney
    target_weight: DecimalString
    current_weight: DecimalString | None
    recommended_amount: PlanningMoney
    post_value: PlanningMoney
    post_weight: DecimalString
    minimum_funded_amount: PlanningMoney
    value_increment: PlanningMoney
    excluded: StrictBool
    binding_constraint_keys: Annotated[list[StableKey], Field(max_length=1280)]


class ContributionPlanResultSummary(PlanningSchema):
    context: PlanningResultContext
    outcome: PlanOutcome
    mode: PlanMode
    contribution: PlanningMoney
    monetary_quantum: DecimalString | None
    currency_policy_version: PlanningCode
    residual_cash: PlanningMoney | None
    current_cash: PlanningMoney | None
    post_cash: PlanningMoney | None
    post_total: PlanningMoney | None
    objective_before: PlanningObjective | None
    objective_after: PlanningObjective | None
    lower_bound: PlanningObjective | None
    objective_gap: PlanningObjective | None
    bound_kind: PlanningCode | None
    examined_moves: Annotated[StrictInt, Field(ge=0, le=10000)]
    attempted_assignments: Annotated[StrictInt, Field(ge=0, le=100000)]
    exhaustive: StrictBool
    constraints: Annotated[list[PlanningEffectiveConstraint], Field(max_length=1280)]
    explanations: Annotated[list[PlanningExplanation], Field(max_length=1280)]
    excluded_node_keys: Annotated[list[StableKey], Field(max_length=256)]
    unresolved_node_keys: Annotated[list[StableKey], Field(max_length=256)]
    before_drift: PlanningDriftTotals
    after_drift: PlanningDriftTotals | None
    execution_allowed: Literal[False] = False


class ContributionPlanJob(PlanningSchema):
    plan_id: UUIDString
    account_id: UUIDString
    virtual_portfolio_id: UUIDString
    target_version_id: UUIDString
    snapshot_id: UUIDString
    request_id: UUIDString
    request_revision: Annotated[StrictInt, Field(ge=1)]
    job_id: UUIDString
    state: JobState
    outcome: PlanOutcome | None
    requested_at: AwareInstant
    input_digest: Digest
    plan_revision_id: UUIDString | None = None
    failure_code: PlanningCode | None = None
    revision_etag: Annotated[
        str,
        StringConstraints(
            strict=True, min_length=40, max_length=80, pattern=r'^"[0-9a-f-]{36}:[1-9][0-9]*"$'
        ),
    ]
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def finalized_identity(self) -> Self:
        if self.state == "succeeded":
            if self.outcome is None or self.plan_revision_id is None:
                raise ValueError("A succeeded job requires its immutable outcome and revision.")
        elif self.outcome is not None or self.plan_revision_id is not None:
            raise ValueError("Unfinished or failed jobs cannot claim finalized plan data.")
        return self


class PersistedPlanningOptions(PlanningSchema):
    contribution: ContributionMoney
    mode: PlanMode
    coverage_policy: CoveragePolicy
    eligible_holding_ids: UUIDSet | None
    excluded_holding_ids: UUIDSet
    restricted_group_ids: UUIDSet
    listing_preferences: Annotated[list[PlanningListingPreference], Field(max_length=256)]
    allocation_constraints: Annotated[list[PlanningConstraint], Field(max_length=256)]
    holding_constraints: Annotated[list[McpPlanAllocationConstraint], Field(max_length=256)]
    cash_reserve: NonnegativeDecimal | None
    monetary_quantum: QuantumString | None


class PersistedPlanningRequest(PlanningSchema):
    account_id: UUIDString
    virtual_portfolio_id: UUIDString
    target_version_id: UUIDString
    snapshot_id: UUIDString
    options: PersistedPlanningOptions


class ContributionPlanSummary(PlanningSchema):
    job: ContributionPlanJob
    virtual_portfolio_id: UUIDString
    target_version_id: UUIDString
    snapshot_id: UUIDString
    options: PersistedPlanningOptions


class ContributionPlanPage(PlanningPage[ContributionPlanSummary]):
    pass


class ContributionPlanDetail(PlanningSchema):
    job: ContributionPlanJob
    request: PersistedPlanningRequest
    result: ContributionPlanResultSummary | None
    lines: PlanningPage[ContributionPlanLine]
    calculated_at: AwareInstant | None
    content_digest: Digest | None
    revision_etag: Annotated[str, StringConstraints(strict=True, min_length=40, max_length=80)]
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def result_lifecycle(self) -> Self:
        ready = self.job.state == "succeeded"
        fields = (self.result, self.calculated_at, self.content_digest)
        if (ready and any(value is None for value in fields)) or (
            not ready and any(value is not None for value in fields)
        ):
            raise ValueError("Only finalized jobs may contain complete immutable results.")
        if not ready and (
            self.lines.items or self.lines.total or self.lines.next_cursor is not None
        ):
            raise ValueError("Unfinished jobs cannot fabricate allocation lines.")
        if (
            self.result is not None
            and self.result.outcome not in {"optimal", "feasible_nonoptimal"}
            and self.lines.items
        ):
            raise ValueError("Nonfeasible outcomes cannot contain allocation recommendations.")
        if self.revision_etag != self.job.revision_etag:
            raise ValueError("The recalculation precondition must match its plan request revision.")
        return self


def canonical_planning_payload(
    value: dict[str, Any], schema: type[PlanningSchema]
) -> dict[str, Any]:
    """Project canonical service metadata into the frozen wire shape without calculations.

    The input is the domain serializer's fresh primitive mapping. Unknown source
    keys remain visible to strict output validation; no source data is discarded.
    """
    payload = copy.deepcopy(value)

    def context(raw: dict[str, Any], calculated_at: object) -> dict[str, Any]:
        result = dict(raw)
        result["method"] = {"name": result.pop("method"), "version": result.pop("method_version")}
        result["calculated_at"] = calculated_at
        result["data_quality"] = {
            "state": result.pop("quality"),
            "coverage_start_at": result.pop("coverage_start_at"),
            "coverage_end_at": result.pop("coverage_end_at"),
            "missing_inputs": result.pop("missing_inputs"),
            "reconciled": result.pop("reconciled"),
            "evaluated_at": calculated_at,
            "warnings": result["warnings"],
        }
        return result

    def job(raw: dict[str, Any]) -> dict[str, Any]:
        result = dict(raw)
        result["revision_etag"] = f'"{result["plan_id"]}:{result["request_revision"]}"'
        result["execution_allowed"] = False
        return result

    if schema in {ActualVsTargetResult, DriftAnalysisResult}:
        payload["context"] = context(payload["context"], payload["calculated_at"])
    elif schema is ContributionPlanJob:
        payload = job(payload)
    elif schema is ContributionPlanPage:
        payload["items"] = [{**item, "job": job(item["job"])} for item in payload["items"]]
    elif schema is ContributionPlanDetail:
        payload["job"] = job(payload["job"])
        payload["revision_etag"] = payload["job"]["revision_etag"]
        payload["execution_allowed"] = False
        if payload["result"] is not None:
            payload["result"]["context"] = context(
                payload["result"]["context"], payload["calculated_at"]
            )
    else:
        raise ValueError("Unsupported fixed planning result schema.")
    return payload
