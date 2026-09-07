"""Exact source command conversion and license-authorized closed response projection."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any

from fastapi import Request, Response
from pydantic import BaseModel
from trading212_api_contracts import sources as wire
from trading212_application import sources as application_sources
from trading212_application.views import Page
from trading212_domain import sources as domain
from trading212_domain.serialization import to_primitive
from trading212_domain.values import CurrencyCode

from .target_routes import RESPONSE_BYTE_LIMIT, _error


def benchmark_content(value: wire.BenchmarkContent) -> domain.BenchmarkContent:
    return domain.BenchmarkContent(
        reporting_currency=CurrencyCode(value.reporting_currency),
        effective_at=value.effective_at,
        return_basis=domain.PriceBasis(value.return_basis),
        calendar_id=value.calendar_id,
        calendar_version=value.calendar_version,
        rebalance_rule=domain.BenchmarkRebalanceRule(value.rebalance_rule),
        components=tuple(
            domain.BenchmarkComponent(source_id=item.source_id, weight=Decimal(item.weight))
            for item in value.components
        ),
    )


def source_status_query(value: wire.SourceStatusQuery) -> application_sources.SourceStatusQuery:
    return application_sources.SourceStatusQuery(
        **value.model_dump(exclude={"start", "end", "currency", "basis"}),
        currency=CurrencyCode(value.currency) if value.currency else None,
        basis=domain.PriceBasis(value.basis) if value.basis else None,
        period=domain.SourcePeriod(start=value.start, end=value.end)
        if value.start is not None and value.end is not None
        else None,
    )


def fx_status_query(value: wire.FxSourceStatusQuery) -> application_sources.FxSourceStatusQuery:
    return application_sources.FxSourceStatusQuery(
        **value.model_dump(exclude={"start", "end", "base", "quote"}),
        base=CurrencyCode(value.base) if value.base else None,
        quote=CurrencyCode(value.quote) if value.quote else None,
        period=domain.SourcePeriod(start=value.start, end=value.end)
        if value.start is not None and value.end is not None
        else None,
    )


def _payload(value: object) -> Any:
    payload = to_primitive(value)
    if isinstance(
        value,
        (
            application_sources.PriceSnapshotHeaderView,
            application_sources.FxSnapshotHeaderView,
            application_sources.BenchmarkSnapshotHeaderView,
        ),
    ):
        ordinal = value.provenance.revision_order
        payload["provenance"]["revision_order"] = str(ordinal) if ordinal is not None else None
    if isinstance(value, application_sources.BenchmarkDefinitionDetailView):
        payload["definition"]["revision_etag"] = value.definition.etag
    elif isinstance(value, Page):
        for item, row in zip(value.items, payload["items"], strict=True):
            if isinstance(item, application_sources.BenchmarkDefinitionSummaryView):
                row["revision_etag"] = item.etag
    return payload


def source_response[T: BaseModel](
    request: Request,
    value: object,
    schema: type[T],
    *,
    status_code: int = 200,
    etag: str | None = None,
) -> Response:
    try:
        # License and owner authorization already completed in the service. Validate
        # and bound the complete representation before considering a conditional GET.
        payload = schema.model_validate(_payload(value)).model_dump_json().encode("utf-8")
    except (KeyError, TypeError, ValueError):
        return _error(request, 500, "INTERNAL_ERROR", "The source operation could not complete.")
    if len(payload) > RESPONSE_BYTE_LIMIT:
        return _error(request, 422, "RESULT_TOO_LARGE", "The requested result is too large.")
    conditional = request.method == "GET"
    if conditional:
        etag = '"' + hashlib.sha256(payload).hexdigest() + '"'
    headers = {"Cache-Control": "private, no-store"}
    if etag is not None:
        headers["ETag"] = etag
        supplied = request.headers.get("if-none-match", "")
        tags = {item.strip().removeprefix("W/") for item in supplied.split(",")}
        if conditional and (etag in tags or "*" in tags):
            return Response(status_code=304, headers=headers)
    return Response(
        payload, status_code=status_code, media_type="application/json", headers=headers
    )
