"""Exact aggregate command conversion and bounded conditional responses."""

from hashlib import sha256
from uuid import UUID

from fastapi import Request, Response
from pydantic import BaseModel, ValidationError
from trading212_api_contracts import aggregation as wire
from trading212_domain.aggregation import (
    MAX_AGGREGATE_RESPONSE_BYTES,
    AggregateMember,
    AggregateSelectionContent,
)
from trading212_domain.serialization import to_primitive
from trading212_domain.values import CurrencyCode

from .target_routes import _error


def aggregate_selection_content(value: wire.AggregateSelectionContent) -> AggregateSelectionContent:
    return AggregateSelectionContent(
        name=value.name,
        members=tuple(
            AggregateMember(
                account_id=UUID(item.account_id),
                portfolio_snapshot_id=UUID(item.portfolio_snapshot_id),
            )
            for item in value.members
        ),
        reporting_currency=CurrencyCode(value.reporting_currency),
        source_cutoff_at=value.source_cutoff_at,
        economic_identity_policy=value.economic_identity_policy,
    )


def aggregate_response[T: BaseModel](
    request: Request,
    value: object,
    schema: type[T],
    *,
    status_code: int = 200,
    etag: str | None = None,
    conditional: bool = False,
) -> Response:
    # The service has completed current scope/account/capability/license checks.
    # Validate and bound the complete response before any conditional 304 path.
    try:
        payload = schema.model_validate(to_primitive(value)).model_dump_json().encode("utf-8")
    except (ValidationError, TypeError, ValueError):
        return _error(request, 500, "INTERNAL_ERROR", "The aggregate operation failed.")
    if len(payload) > MAX_AGGREGATE_RESPONSE_BYTES:
        return _error(
            request, 422, "RESULT_TOO_LARGE", "The aggregate response exceeds its byte bound."
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
