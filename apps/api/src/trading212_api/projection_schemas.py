"""Exact projection command conversion and finalized, bounded response envelopes."""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from fastapi import Request, Response
from pydantic import BaseModel, ValidationError
from trading212_api_contracts import projection_inputs as wire
from trading212_application import projection as app
from trading212_application import projection_capture as capture
from trading212_application.projection_presentation import validate_projection_response_bytes
from trading212_application.projection_views import ProjectionVersionMetadata
from trading212_domain import projection as domain
from trading212_domain.serialization import to_primitive
from trading212_domain.values import CurrencyCode, Money

from .target_routes import _error


def projection_metadata(value: wire.ProjectionVersionMetadata) -> ProjectionVersionMetadata:
    return ProjectionVersionMetadata(name=value.name, description=value.description)


def _money(value: wire.ProjectionMoney) -> Money:
    return Money(Decimal(value.amount), CurrencyCode(value.currency))


def projection_assumptions(value: wire.AssumptionVersionContent) -> domain.ProjectionAssumptions:
    return domain.ProjectionAssumptions(
        assets=tuple(
            domain.ProjectionAsset(
                key=item.key,
                annual_mean_log_return=Decimal(item.annual_mean_log_return),
                annual_volatility=Decimal(item.annual_volatility),
                weight=Decimal(item.weight),
            )
            for item in value.assets
        ),
        correlation=tuple(tuple(Decimal(cell) for cell in row) for row in value.correlation),
        reporting_currency=CurrencyCode(value.reporting_currency),
        annual_inflation=Decimal(value.annual_inflation),
        annual_fee=Decimal(value.annual_fee),
        annual_tax_drag=None if value.annual_tax_drag is None else Decimal(value.annual_tax_drag),
        rebalance=value.rebalance,
        calibration_pins=tuple(
            domain.ProjectionSourcePin(
                subject_id=item.subject_id, content_digest=item.content_digest
            )
            for item in value.calibration_pins
        ),
    )


def projection_schedule(value: wire.ProjectionDatedSchedule) -> capture.ProjectionDatedSchedule:
    return capture.ProjectionDatedSchedule(
        base_monthly=_money(value.base_monthly),
        annual_growth=Decimal(value.annual_growth),
        paused_dates=tuple(value.paused_dates),
        entries=tuple(
            capture.ProjectionDatedEntry(
                key=item.key, on=item.on, kind=item.kind, value=_money(item.value)
            )
            for item in value.entries
        ),
    )


def projection_goal(value: wire.GoalVersionContent) -> capture.ProjectionGoalVersionContent:
    return capture.ProjectionGoalVersionContent(
        assumption_version_id=UUID(value.assumption_version_id),
        target=_money(value.target),
        target_date=value.target_date,
        months=value.months,
        basis=value.basis,
        probability_objective=Decimal(value.probability_objective),
        schedule=projection_schedule(value.schedule),
    )


def projection_run(
    account_id: str, value: wire.CreateProjectionRunRequest, *, key: str, correlation: str
) -> app.CreateProjectionRun:
    initial, sensitivity = value.initial_basis, value.sensitivity
    selection = capture.ProjectionRunSelection(
        account_id=UUID(account_id),
        assumption_version_id=UUID(value.assumption_version_id),
        goal_version_id=None if value.goal_version_id is None else UUID(value.goal_version_id),
        initial=capture.ProjectionInitialSelection(
            kind=initial.kind,
            snapshot_id=None if initial.snapshot_id is None else UUID(initial.snapshot_id),
            modeled_value=None if initial.modeled_value is None else _money(initial.modeled_value),
            modeled_anchor_date=initial.modeled_anchor_date,
        ),
        schedule=projection_schedule(value.schedule),
        seed=value.seed,
        months=value.months,
        paths=value.paths,
        retained_months=tuple(value.retained_months),
        allocation=tuple(
            domain.ProjectionAllocation(key=item.key, weight=Decimal(item.weight))
            for item in value.allocation
        ),
        sensitivity=None
        if sensitivity is None
        else domain.ProjectionSensitivity(
            contribution_delta=_money(sensitivity.contribution_delta),
            annual_mean_log_delta=Decimal(sensitivity.annual_mean_log_delta),
        ),
    )
    return app.CreateProjectionRun(
        selection=selection, idempotency_key=key, correlation_id=correlation
    )


def projection_response[T: BaseModel](
    request: Request,
    value: object,
    schema: type[T],
    *,
    status_code: int = 200,
    etag: str | None = None,
    conditional: bool = False,
) -> Response:
    # The service must finish current scope/grant/source authorization before returning.
    # DTO validation preserves the independent complete 1 MiB financial page gate.
    try:
        payload = schema.model_validate(to_primitive(value)).model_dump_json().encode("utf-8")
    except (ValidationError, TypeError, ValueError):
        return _error(request, 500, "INTERNAL_ERROR", "The projection operation failed.")
    try:
        validate_projection_response_bytes(payload)
    except app.ProjectionServiceError as failure:
        if failure.code != app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED:
            raise
        return _error(
            request, 422, "RESULT_TOO_LARGE", "The projection result exceeds its byte bound."
        )
    tag = etag or '"' + sha256(payload).hexdigest() + '"'
    headers = {
        "Cache-Control": "private, no-store",
        "ETag": tag,
        "X-Content-Type-Options": "nosniff",
    }
    matches = {
        item.strip().removeprefix("W/")
        for item in request.headers.get("if-none-match", "").split(",")
    }
    if conditional and (tag in matches or "*" in matches):
        return Response(status_code=304, headers=headers)
    return Response(
        payload, status_code=status_code, media_type="application/json", headers=headers
    )
