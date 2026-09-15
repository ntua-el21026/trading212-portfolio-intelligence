"""Fixed scenario command conversion and fully bounded authorized response envelopes."""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from fastapi import Request, Response
from pydantic import BaseModel, ValidationError
from trading212_api_contracts import scenarios as wire
from trading212_application import scenario as app
from trading212_domain import scenario as domain
from trading212_domain.scenario_execution import ScenarioReplaySelection
from trading212_domain.serialization import to_primitive
from trading212_domain.values import CurrencyCode

from .target_routes import RESPONSE_BYTE_LIMIT, _error


def _price_selector(value: wire.ScenarioPriceSelector) -> domain.ScenarioPriceSelector:
    if isinstance(value, wire.ScenarioInstrumentSelector):
        return domain.ScenarioInstrumentSelector(instrument_id=UUID(value.instrument_id))
    if isinstance(value, wire.ScenarioEntitySelector):
        return domain.ScenarioEntitySelector(entity_id=UUID(value.entity_id))
    if isinstance(value, wire.ScenarioSectorSelector):
        return domain.ScenarioSectorSelector(
            taxonomy_id=UUID(value.taxonomy_id),
            taxonomy_version=value.taxonomy_version,
            bucket_key=value.bucket_key,
        )
    return domain.ScenarioRegionSelector(
        taxonomy_id=UUID(value.taxonomy_id),
        taxonomy_version=value.taxonomy_version,
        bucket_key=value.bucket_key,
    )


def _selector(value: wire.ScenarioComponentSelector) -> domain.ScenarioComponentSelector:
    if isinstance(value, wire.ScenarioCurrencySelector):
        return domain.ScenarioCurrencySelector(currency=CurrencyCode(value.currency))
    return _price_selector(value)


def _shock(value: wire.ScenarioShock) -> domain.ScenarioShock:
    if isinstance(value, wire.ScenarioPriceShock):
        return domain.ScenarioPriceShock(
            selector=_price_selector(value.selector), size=Decimal(value.size)
        )
    if isinstance(value, wire.ScenarioFxShock):
        return domain.ScenarioFxShock(
            selector=domain.ScenarioCurrencySelector(
                currency=CurrencyCode(value.selector.currency)
            ),
            size=Decimal(value.size),
        )
    source = domain.ScenarioSensitivityVersionPin(
        version_id=UUID(value.source.version_id),
        content_digest=value.source.content_digest,
        driver_id=UUID(value.source.driver_id),
        driver_definition_version_id=UUID(value.source.driver_definition_version_id),
    )
    if isinstance(value, wire.ScenarioRateShock):
        return domain.ScenarioRateShock(source=source, size=Decimal(value.size))
    return domain.ScenarioFactorShock(source=source, size=Decimal(value.size))


def scenario_definition(value: wire.ScenarioVersionContent) -> domain.ScenarioVersionContent:
    return domain.ScenarioVersionContent(
        name=value.name,
        description=value.description,
        mode=value.mode,
        shocks=tuple(_shock(item) for item in value.shocks),
        exclusions=tuple(
            domain.ScenarioExclusion(selector=_selector(item.selector)) for item in value.exclusions
        ),
        method_version=value.method_version,
    )


def scenario_run(
    account_id: str, value: wire.CreateScenarioRunRequest, *, key: str, correlation: str
) -> app.CreateScenarioRun:
    selected = value.replay
    replay = (
        None
        if selected is None
        else ScenarioReplaySelection(
            historical_input_snapshot_id=UUID(selected.historical_input_snapshot_id),
            start_date=selected.start_date,
            end_date=selected.end_date,
            market_knowledge_cutoff_at=selected.market_knowledge_cutoff_at,
            holdings_basis=selected.holdings_basis,
            knowledge_basis=selected.knowledge_basis,
        )
    )
    return app.CreateScenarioRun(
        account_id=UUID(account_id),
        scenario_version_id=UUID(value.scenario_version_id),
        portfolio_snapshot_id=UUID(value.portfolio_snapshot_id),
        xray_run_id=UUID(value.xray_run_id),
        reporting_currency=CurrencyCode(value.reporting_currency),
        source_cutoff_at=value.source_cutoff_at,
        replay=replay,
        idempotency_key=key,
        correlation_id=correlation,
    )


def scenario_response[T: BaseModel](
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
        return _error(request, 500, "INTERNAL_ERROR", "The scenario operation failed.")
    if len(payload) > RESPONSE_BYTE_LIMIT:
        return _error(
            request, 422, "RESULT_TOO_LARGE", "The scenario result exceeds its byte bound."
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
