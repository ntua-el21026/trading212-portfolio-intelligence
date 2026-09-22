"""Closed preference conversions and bounded private conditional responses."""

from hashlib import sha256
from typing import Literal, cast
from uuid import UUID

from fastapi import Request, Response
from pydantic import BaseModel, ValidationError
from trading212_api_contracts import owner_layouts as wire
from trading212_application import owner_layouts as app
from trading212_domain import owner_layouts as d
from trading212_domain.owner_layout_codec import layout_selection_from_value, owner_layout_bytes
from trading212_domain.serialization import to_primitive

from .target_routes import _error


def layout_content(value: wire.OwnerLayoutContent) -> d.OwnerLayoutContent:
    content = d.OwnerLayoutContent(
        name=value.name,
        description=value.description,
        account_id=None if value.account_id is None else UUID(value.account_id),
        columns=cast(Literal[1, 2, 3], value.columns),
        density=value.density,
        widgets=tuple(
            d.OwnerLayoutWidget(
                id=UUID(widget.id),
                kind=d.LayoutWidgetKind(widget.kind),
                label=widget.label,
                selection=None
                if widget.selection is None
                else layout_selection_from_value(widget.selection.model_dump(mode="json")),
            )
            for widget in value.widgets
        ),
    )
    owner_layout_bytes(content)
    return content


def layout_response[T: BaseModel](
    request: Request,
    value: app.OwnerLayoutView | app.OwnerLayoutPage | app.OwnerLayoutArchiveReceipt,
    schema: type[T],
    *,
    status_code: int = 200,
    conditional: bool = False,
) -> Response:
    # Current owner/account authority has completed before this function can return304.
    try:
        payload = schema.model_validate(to_primitive(value)).model_dump_json().encode("utf-8")
    except (ValidationError, TypeError, ValueError):
        return _error(request, 500, "INTERNAL_ERROR", "The saved layout operation failed.")
    if len(payload) > d.MAX_LAYOUT_RESPONSE_BYTES:
        return _error(
            request, 422, "RESULT_TOO_LARGE", "The layout response exceeds its byte bound."
        )
    # The current editable resource carries its revision token. Historical selections
    # have their own full representation hash; commands still use the current revision.
    tag = (
        f'"{value.id}:{value.revision}"'
        if isinstance(value, app.OwnerLayoutView) and value.version.id == value.versions[-1].id
        else '"' + sha256(payload).hexdigest() + '"'
    )
    headers = {
        "Cache-Control": "private, no-store",
        "ETag": tag,
        "X-Content-Type-Options": "nosniff",
    }
    matches = {
        part.strip().removeprefix("W/")
        for part in request.headers.get("if-none-match", "").split(",")
    }
    if conditional and (tag in matches or "*" in matches):
        return Response(status_code=304, headers=headers)
    return Response(
        payload, status_code=status_code, media_type="application/json", headers=headers
    )
