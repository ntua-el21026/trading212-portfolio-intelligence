"""Exact risk selectors and authorized private response serialization."""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from fastapi import Request, Response
from pydantic import BaseModel, ValidationError
from trading212_api_contracts import risk as wire
from trading212_application import risk as app
from trading212_domain.historical import HistoricalWindow, KnowledgePolicy
from trading212_domain.planning import CoveragePolicy
from trading212_domain.risk import RiskDefinitionContent
from trading212_domain.risk_history import RiskAssetSource
from trading212_domain.serialization import to_primitive
from trading212_domain.values import CurrencyCode

from .target_routes import RESPONSE_BYTE_LIMIT, _error


def risk_definition(value: wire.RiskDefinitionContent) -> RiskDefinitionContent:
    return RiskDefinitionContent(
        name=value.name,
        description=value.description,
        calendar_id=value.calendar_id,
        calendar_version=value.calendar_version,
        frequency=value.frequency,
        return_kind=value.return_kind,
        annual_risk_free=Decimal(value.annual_risk_free),
        annual_minimum_acceptable_return=Decimal(value.annual_minimum_acceptable_return),
        rolling_window=value.rolling_window,
        confidence=Decimal(value.confidence),
        horizon=value.horizon,
        regularization=value.regularization,
        shrinkage=Decimal(value.shrinkage),
        method_version=value.method_version,
    )


def risk_run(
    account_id: str, value: wire.CreateRiskRunRequest, *, key: str, correlation: str
) -> app.CreateRiskRun:
    window = value.window
    return app.CreateRiskRun(
        account_id=UUID(account_id),
        definition_version_id=UUID(value.definition_version_id),
        portfolio_snapshot_id=UUID(value.portfolio_snapshot_id),
        historical_input_snapshot_id=UUID(value.historical_input_snapshot_id),
        window=HistoricalWindow(
            start_date=window.start_date,
            end_date=window.end_date,
            source_cutoff_at=window.source_cutoff_at,
            reporting_currency=CurrencyCode(window.reporting_currency),
            coverage_policy=CoveragePolicy(window.coverage_policy),
            knowledge_policy=KnowledgePolicy(window.knowledge_policy),
        ),
        assets=tuple(
            RiskAssetSource(instrument_id=x.instrument_id, series_id=x.series_id)
            for x in value.assets
        ),
        benchmark_version_id=None
        if value.benchmark_version_id is None
        else UUID(value.benchmark_version_id),
        xray_run_id=None if value.xray_run_id is None else UUID(value.xray_run_id),
        idempotency_key=key,
        correlation_id=correlation,
    )


def risk_response[T: BaseModel](
    request: Request,
    value: object,
    schema: type[T],
    *,
    status_code: int = 200,
    etag: str | None = None,
    conditional: bool = False,
) -> Response:
    # A conditional result is considered only after the service reauthorizes every input.
    try:
        payload = schema.model_validate(to_primitive(value)).model_dump_json().encode()
    except (ValidationError, TypeError, ValueError):
        return _error(request, 500, "INTERNAL_ERROR", "The risk operation failed.")
    if len(payload) > RESPONSE_BYTE_LIMIT:
        return _error(request, 422, "RESULT_TOO_LARGE", "The risk result exceeds its byte bound.")
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
