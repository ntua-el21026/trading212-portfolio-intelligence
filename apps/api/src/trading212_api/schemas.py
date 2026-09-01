"""Typed `/api/v1` schemas with canonical decimal-string serialization."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field
from trading212_application.views import (
    AccountSummaryView,
    AccountView,
    ActivityView,
    AllocationView,
    BrokerConnectionView,
    DataQualitySummaryView,
    DirectAllocationView,
    DividendView,
    InstrumentView,
    MetricView,
    OrderView,
    PerformanceSummaryView,
    PositionView,
    QualityView,
    ReconciliationIssueView,
    ReconciliationView,
    RefreshRunQualityView,
    RefreshRunView,
    ReturnMetricView,
    SnapshotComparisonView,
    SnapshotDetailView,
    SnapshotView,
)
from trading212_domain.values import decimal_string

DecimalString = Annotated[str, Field(pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorBody(StrictSchema):
    code: str
    message: str
    correlation_id: str
    retryable: bool = False
    details: dict[str, str] = Field(default_factory=dict)


class ErrorEnvelope(StrictSchema):
    error: ErrorBody


class QualityResponse(StrictSchema):
    state: str
    as_of: datetime
    source_timestamp: datetime
    freshness_threshold_seconds: int
    warnings: list[str]
    missing_inputs: list[str]

    @classmethod
    def from_view(cls, value: QualityView) -> QualityResponse:
        return cls(
            state=value.state.value,
            as_of=value.as_of,
            source_timestamp=value.source_timestamp,
            freshness_threshold_seconds=value.freshness_threshold_seconds,
            warnings=list(value.warnings),
            missing_inputs=list(value.missing_inputs),
        )


class MetricResponse(StrictSchema):
    value: DecimalString | None
    reporting_currency: str
    availability: str
    calculation_version: str
    methodology: str
    provenance: list[str]
    assumptions: list[str]
    unavailable_reason: str | None

    @classmethod
    def from_view(cls, value: MetricView) -> MetricResponse:
        return cls(
            value=decimal_string(value.value) if value.value is not None else None,
            reporting_currency=value.currency,
            availability=value.availability.value,
            calculation_version=value.calculation_version,
            methodology=value.methodology,
            provenance=list(value.provenance),
            assumptions=list(value.assumptions),
            unavailable_reason=value.unavailable_reason,
        )


class AccountResponse(StrictSchema):
    id: str
    display_name: str
    provider: str
    environment: str
    account_type: str
    reporting_currency: str
    connection_state: str
    last_refresh_at: datetime | None

    @classmethod
    def from_view(cls, value: AccountView) -> AccountResponse:
        return cls.model_validate(value, from_attributes=True)


class AccountSummaryResponse(StrictSchema):
    account: AccountResponse
    total_value: MetricResponse
    cash_balance: MetricResponse
    invested_value: MetricResponse
    net_contributions: MetricResponse
    dividends_received: MetricResponse
    realized_profit_loss: MetricResponse
    unrealized_profit_loss: MetricResponse
    data_quality: QualityResponse
    position_count: int

    @classmethod
    def from_view(cls, value: AccountSummaryView) -> AccountSummaryResponse:
        return cls(
            account=AccountResponse.from_view(value.account),
            total_value=MetricResponse.from_view(value.total_value),
            cash_balance=MetricResponse.from_view(value.cash_balance),
            invested_value=MetricResponse.from_view(value.invested_value),
            net_contributions=MetricResponse.from_view(value.net_contributions),
            dividends_received=MetricResponse.from_view(value.dividends_received),
            realized_profit_loss=MetricResponse.from_view(value.realized_profit_loss),
            unrealized_profit_loss=MetricResponse.from_view(value.unrealized_profit_loss),
            data_quality=QualityResponse.from_view(value.quality),
            position_count=value.position_count,
        )


class PositionResponse(StrictSchema):
    id: str
    ticker: str
    name: str
    instrument_type: str
    quantity: DecimalString
    trading_currency: str
    current_price: DecimalString | None
    market_value: MetricResponse
    provider_cost_basis: MetricResponse
    provider_unrealized_profit_loss: MetricResponse
    direct_weight: DecimalString | None
    data_quality: QualityResponse

    @classmethod
    def from_view(cls, value: PositionView) -> PositionResponse:
        return cls(
            id=value.id,
            ticker=value.ticker,
            name=value.name,
            instrument_type=value.instrument_type,
            quantity=decimal_string(value.quantity),
            trading_currency=value.trading_currency,
            current_price=(
                decimal_string(value.current_price) if value.current_price is not None else None
            ),
            market_value=MetricResponse.from_view(value.market_value),
            provider_cost_basis=MetricResponse.from_view(value.provider_cost_basis),
            provider_unrealized_profit_loss=MetricResponse.from_view(
                value.provider_unrealized_profit_loss
            ),
            direct_weight=(
                decimal_string(value.direct_weight) if value.direct_weight is not None else None
            ),
            data_quality=QualityResponse.from_view(value.quality),
        )


class ActivityResponse(StrictSchema):
    id: str
    occurred_at: datetime
    activity_type: str
    direction: str
    amount: MetricResponse
    ticker: str | None
    quantity: DecimalString | None
    description: str
    data_quality: QualityResponse

    @classmethod
    def from_view(cls, value: ActivityView) -> ActivityResponse:
        return cls(
            id=value.id,
            occurred_at=value.occurred_at,
            activity_type=value.activity_type,
            direction=value.direction,
            amount=MetricResponse.from_view(value.amount),
            ticker=value.ticker,
            quantity=decimal_string(value.quantity) if value.quantity is not None else None,
            description=value.description,
            data_quality=QualityResponse.from_view(value.quality),
        )


class DividendResponse(StrictSchema):
    id: str
    paid_on: date
    ticker: str
    net_amount: MetricResponse
    gross_amount: MetricResponse
    withholding_tax: MetricResponse
    quantity: DecimalString | None
    data_quality: QualityResponse

    @classmethod
    def from_view(cls, value: DividendView) -> DividendResponse:
        return cls(
            id=value.id,
            paid_on=value.paid_on,
            ticker=value.ticker,
            net_amount=MetricResponse.from_view(value.net_amount),
            gross_amount=MetricResponse.from_view(value.gross_amount),
            withholding_tax=MetricResponse.from_view(value.withholding_tax),
            quantity=(decimal_string(value.quantity) if value.quantity is not None else None),
            data_quality=QualityResponse.from_view(value.quality),
        )


class OrderResponse(StrictSchema):
    id: str
    created_at: datetime
    ticker: str
    side: str
    order_type: str
    status: str
    quantity: DecimalString | None
    filled_quantity: DecimalString | None
    limit_price: DecimalString | None
    observed_value: MetricResponse
    data_quality: QualityResponse

    @classmethod
    def from_view(cls, value: OrderView) -> OrderResponse:
        return cls(
            id=value.id,
            created_at=value.created_at,
            ticker=value.ticker,
            side=value.side,
            order_type=value.order_type,
            status=value.status,
            quantity=decimal_string(value.quantity) if value.quantity is not None else None,
            filled_quantity=(
                decimal_string(value.filled_quantity) if value.filled_quantity is not None else None
            ),
            limit_price=(
                decimal_string(value.limit_price) if value.limit_price is not None else None
            ),
            observed_value=MetricResponse.from_view(value.observed_value),
            data_quality=QualityResponse.from_view(value.quality),
        )


class AllocationResponse(StrictSchema):
    id: str
    label: str
    asset_type: str
    market_value: MetricResponse
    weight: DecimalString | None
    weight_availability: str

    @classmethod
    def from_view(cls, value: AllocationView) -> AllocationResponse:
        return cls(
            id=value.id,
            label=value.label,
            asset_type=value.asset_type,
            market_value=MetricResponse.from_view(value.market_value),
            weight=decimal_string(value.weight) if value.weight is not None else None,
            weight_availability=value.weight_availability.value,
        )


class DirectAllocationResponse(StrictSchema):
    items: list[AllocationResponse]
    returned_count: int
    total: int
    limit: int
    truncated: bool

    @classmethod
    def from_view(cls, value: DirectAllocationView, *, limit: int) -> DirectAllocationResponse:
        return cls(
            items=[AllocationResponse.from_view(item) for item in value.items],
            returned_count=len(value.items),
            total=value.total,
            limit=limit,
            truncated=value.truncated,
        )


class SnapshotResponse(StrictSchema):
    id: str
    valuation_at: datetime
    source_cutoff_at: datetime
    reporting_currency: str
    total_value: MetricResponse
    cash_value: MetricResponse
    invested_value: MetricResponse
    net_contributions: MetricResponse
    data_quality: QualityResponse

    @classmethod
    def from_view(cls, value: SnapshotView) -> SnapshotResponse:
        return cls(
            id=value.id,
            valuation_at=value.valuation_at,
            source_cutoff_at=value.source_cutoff_at,
            reporting_currency=value.reporting_currency,
            total_value=MetricResponse.from_view(value.total_value),
            cash_value=MetricResponse.from_view(value.cash_value),
            invested_value=MetricResponse.from_view(value.invested_value),
            net_contributions=MetricResponse.from_view(value.net_contributions),
            data_quality=QualityResponse.from_view(value.quality),
        )


class SnapshotDetailResponse(SnapshotResponse):
    dividends_received: MetricResponse
    realized_profit_loss: MetricResponse
    unrealized_profit_loss: MetricResponse

    @classmethod
    def from_detail(cls, value: SnapshotDetailView) -> SnapshotDetailResponse:
        snapshot = value.snapshot
        return cls(
            id=snapshot.id,
            valuation_at=snapshot.valuation_at,
            source_cutoff_at=snapshot.source_cutoff_at,
            reporting_currency=snapshot.reporting_currency,
            total_value=MetricResponse.from_view(snapshot.total_value),
            cash_value=MetricResponse.from_view(snapshot.cash_value),
            invested_value=MetricResponse.from_view(snapshot.invested_value),
            net_contributions=MetricResponse.from_view(snapshot.net_contributions),
            data_quality=QualityResponse.from_view(snapshot.quality),
            dividends_received=MetricResponse.from_view(value.dividends_received),
            realized_profit_loss=MetricResponse.from_view(value.realized_profit_loss),
            unrealized_profit_loss=MetricResponse.from_view(value.unrealized_profit_loss),
        )


class SnapshotComparisonResponse(StrictSchema):
    start: SnapshotResponse
    end: SnapshotResponse
    value_change: MetricResponse
    net_external_flows: MetricResponse
    investment_result: MetricResponse
    reconciliation_residual: MetricResponse
    data_quality: QualityResponse

    @classmethod
    def from_view(cls, value: SnapshotComparisonView) -> SnapshotComparisonResponse:
        return cls(
            start=SnapshotResponse.from_view(value.start),
            end=SnapshotResponse.from_view(value.end),
            value_change=MetricResponse.from_view(value.value_change),
            net_external_flows=MetricResponse.from_view(value.net_external_flows),
            investment_result=MetricResponse.from_view(value.investment_result),
            reconciliation_residual=MetricResponse.from_view(value.reconciliation_residual),
            data_quality=QualityResponse.from_view(value.quality),
        )


class ReconciliationIssueResponse(StrictSchema):
    id: str
    issue_type: str
    severity: str
    status: str
    summary: str
    expected_value: DecimalString | None
    observed_value: DecimalString | None
    residual: DecimalString | None
    tolerance: DecimalString | None
    currency: str | None

    @classmethod
    def from_view(cls, value: ReconciliationIssueView) -> ReconciliationIssueResponse:
        return cls(
            id=value.id,
            issue_type=value.issue_type,
            severity=value.severity,
            status=value.status,
            summary=value.summary,
            expected_value=(
                decimal_string(value.expected_value) if value.expected_value is not None else None
            ),
            observed_value=(
                decimal_string(value.observed_value) if value.observed_value is not None else None
            ),
            residual=decimal_string(value.residual) if value.residual is not None else None,
            tolerance=decimal_string(value.tolerance) if value.tolerance is not None else None,
            currency=value.currency,
        )


class ReconciliationResponse(StrictSchema):
    status: str
    evaluated_at: datetime
    algorithm_version: str
    tolerance_version: str
    issues: list[ReconciliationIssueResponse]
    discrepancy_count: int
    data_quality: QualityResponse

    @classmethod
    def from_view(cls, value: ReconciliationView) -> ReconciliationResponse:
        return cls(
            status=value.status,
            evaluated_at=value.evaluated_at,
            algorithm_version=value.algorithm_version,
            tolerance_version=value.tolerance_version,
            issues=[ReconciliationIssueResponse.from_view(item) for item in value.issues],
            discrepancy_count=value.discrepancy_count,
            data_quality=QualityResponse.from_view(value.quality),
        )


class RefreshRequest(StrictSchema):
    scope: Literal["all", "current", "history"] = "all"
    mode: Literal["incremental", "full"] = "incremental"
    create_snapshot: Literal[True] = True


class RefreshRunResponse(StrictSchema):
    id: str
    account_id: str
    status: str
    requested_at: datetime
    completed_at: datetime | None
    correlation_id: str
    capabilities: list[str]
    warnings: list[str]

    @classmethod
    def from_view(cls, value: RefreshRunView) -> RefreshRunResponse:
        return cls(
            id=value.id,
            account_id=value.account_id,
            status=value.status,
            requested_at=value.requested_at,
            completed_at=value.completed_at,
            correlation_id=value.correlation_id,
            capabilities=list(value.capabilities),
            warnings=list(value.warnings),
        )


class PageResponse[ResponseItem](BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ResponseItem]
    next_cursor: str | None
    limit: int
    total: int


class PrincipalResponse(StrictSchema):
    principal_id: str
    owner_id: str
    scopes: list[str]


class LocalSessionResponse(StrictSchema):
    principal: PrincipalResponse
    csrf_token: str
    expires_at: datetime


class BrokerConnectionResponse(StrictSchema):
    id: str
    provider: str
    environment: str
    status: str
    state: str
    credential_state: Literal["configured", "not_configured"]
    last_successful_refresh_at: datetime | None
    read_only: Literal[True] = True

    @classmethod
    def from_view(cls, value: BrokerConnectionView) -> BrokerConnectionResponse:
        return cls(
            id=value.id,
            provider=value.provider,
            environment=value.environment,
            status=value.status,
            state=value.status,
            credential_state=("configured" if value.credential_configured else "not_configured"),
            last_successful_refresh_at=value.last_successful_refresh_at,
        )


class InstrumentResponse(StrictSchema):
    id: str
    instrument_id: str
    listing_id: str
    ticker: str
    name: str
    canonical_name: str
    instrument_type: str
    isin: str | None
    exchange_mic: str | None
    exchange_id: str | None
    trading_currency: str
    provider: str
    environment: str
    listing_status: str

    @classmethod
    def from_view(cls, value: InstrumentView) -> InstrumentResponse:
        return cls.model_validate(value, from_attributes=True)


class ReturnMetricResponse(StrictSchema):
    method_id: str
    value_kind: str
    period_start: datetime | None
    period_end: datetime
    value: DecimalString | None
    annualized_value: DecimalString | None
    availability: str
    calculation_version: str
    methodology: str
    converged: bool | None
    iterations: int | None
    missing_inputs: list[str]
    assumptions: list[str]
    warnings: list[str]
    quality_state: str
    unavailable_reason: str | None

    @classmethod
    def from_view(cls, value: ReturnMetricView) -> ReturnMetricResponse:
        return cls(
            method_id=value.method_id,
            value_kind=value.value_kind,
            period_start=value.period_start,
            period_end=value.period_end,
            value=decimal_string(value.value) if value.value is not None else None,
            annualized_value=(
                decimal_string(value.annualized_value)
                if value.annualized_value is not None
                else None
            ),
            availability=value.availability.value,
            calculation_version=value.calculation_version,
            methodology=value.methodology,
            converged=value.converged,
            iterations=value.iterations,
            missing_inputs=list(value.missing_inputs),
            assumptions=list(value.assumptions),
            warnings=list(value.warnings),
            quality_state=value.quality_state.value,
            unavailable_reason=value.unavailable_reason,
        )


class PerformanceSummaryResponse(StrictSchema):
    period_start: date | None
    period_end: date
    money_weighted_return: ReturnMetricResponse
    time_weighted_return: ReturnMetricResponse
    modified_dietz_return: ReturnMetricResponse
    data_quality: QualityResponse

    @classmethod
    def from_view(cls, value: PerformanceSummaryView) -> PerformanceSummaryResponse:
        return cls(
            period_start=value.period_start,
            period_end=value.period_end,
            money_weighted_return=ReturnMetricResponse.from_view(value.money_weighted_return),
            time_weighted_return=ReturnMetricResponse.from_view(value.time_weighted_return),
            modified_dietz_return=ReturnMetricResponse.from_view(value.modified_dietz_return),
            data_quality=QualityResponse.from_view(value.quality),
        )


class CapabilityQualityResponse(StrictSchema):
    capability: str
    data_quality: QualityResponse


class RefreshStepQualityResponse(StrictSchema):
    capability: str
    status: str
    warnings: list[str]


class RefreshRunQualityResponse(StrictSchema):
    id: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    steps: list[RefreshStepQualityResponse]


class CheckpointQualityResponse(StrictSchema):
    capability: str
    version: int
    coverage_start_at: datetime | None
    coverage_end_at: datetime | None
    coverage_complete: bool


class DataQualitySummaryResponse(StrictSchema):
    as_of: datetime
    reporting_currency: str
    data_quality: QualityResponse
    capabilities: list[CapabilityQualityResponse]
    failed_or_partial_runs: list[str]
    latest_refresh_run: RefreshRunQualityResponse | None
    latest_runs_by_status: list[RefreshRunQualityResponse]
    checkpoints: list[CheckpointQualityResponse]
    latest_snapshot_id: str | None
    latest_snapshot_source_cutoff_at: datetime | None
    materialization_state: Literal["available", "partial", "missing"]
    reconciliation_status: str
    missing_fx_record_count: int
    unknown_mapping_record_count: int
    read_only: Literal[True] = True

    @classmethod
    def from_view(cls, value: DataQualitySummaryView) -> DataQualitySummaryResponse:
        def run_response(run: RefreshRunQualityView) -> RefreshRunQualityResponse:
            return RefreshRunQualityResponse(
                id=run.id,
                status=run.status,
                started_at=run.started_at,
                completed_at=run.completed_at,
                steps=[
                    RefreshStepQualityResponse(
                        capability=step.capability,
                        status=step.status,
                        warnings=list(step.warnings),
                    )
                    for step in run.steps
                ],
            )

        return cls(
            as_of=value.as_of,
            reporting_currency=value.reporting_currency,
            data_quality=QualityResponse.from_view(value.quality),
            capabilities=[
                CapabilityQualityResponse(
                    capability=item.capability,
                    data_quality=QualityResponse.from_view(item.quality),
                )
                for item in value.capabilities
            ],
            failed_or_partial_runs=list(value.failed_or_partial_runs),
            latest_refresh_run=(
                None if value.latest_refresh_run is None else run_response(value.latest_refresh_run)
            ),
            latest_runs_by_status=[run_response(item) for item in value.latest_runs_by_status],
            checkpoints=[
                CheckpointQualityResponse(
                    capability=item.capability,
                    version=item.version,
                    coverage_start_at=item.coverage_start_at,
                    coverage_end_at=item.coverage_end_at,
                    coverage_complete=item.coverage_complete,
                )
                for item in value.checkpoints
            ],
            latest_snapshot_id=value.latest_snapshot_id,
            latest_snapshot_source_cutoff_at=value.latest_snapshot_source_cutoff_at,
            materialization_state=cast(
                Literal["available", "partial", "missing"],
                value.materialization_state,
            ),
            reconciliation_status=value.reconciliation_status,
            missing_fx_record_count=value.missing_fx_record_count,
            unknown_mapping_record_count=value.unknown_mapping_record_count,
        )


class HealthResponse(StrictSchema):
    service: str
    status: Literal["ok", "ready"]
