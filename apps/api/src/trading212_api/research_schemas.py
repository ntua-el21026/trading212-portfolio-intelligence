"""Explicit research conversions, canonical digests and bounded private responses."""

from __future__ import annotations

from hashlib import sha256
from typing import cast
from uuid import UUID

from fastapi import Request, Response
from pydantic import BaseModel, ValidationError
from trading212_api_contracts import research as wire
from trading212_application import research as app
from trading212_application.views import Page
from trading212_domain.research import MAX_RESEARCH_RESPONSE_BYTES
from trading212_domain.research_notes import (
    ResearchNoteContent,
    ResearchNoteRevision,
    ResearchReviewAcknowledgment,
)
from trading212_domain.research_sources import ResearchCitationPin, ResearchEventRevision
from trading212_domain.serialization import to_primitive

from .target_routes import _error


def research_note_content(value: wire.ResearchNoteContent) -> ResearchNoteContent:
    return ResearchNoteContent(
        title=value.title,
        note=value.note,
        thesis=value.thesis,
        risks=value.risks,
        catalysts=value.catalysts,
        break_conditions=value.break_conditions,
        citations=tuple(
            ResearchCitationPin(
                citation_id=UUID(item.citation_id),
                source_version_id=UUID(item.source_version_id),
                source_version_digest=item.source_version_digest,
                citation_digest=item.citation_digest,
            )
            for item in value.citations
        ),
    )


def _object(value: object) -> dict[str, object]:
    result = to_primitive(value)
    if not isinstance(result, dict):
        raise ValueError("A retained research object is required.")
    return cast(dict[str, object], result)


def _note(value: ResearchNoteRevision) -> dict[str, object]:
    return {**_object(value), "content_digest": value.content_digest}


def _source(value: ResearchEventRevision) -> dict[str, object]:
    return {
        **_object(value),
        "content_digest": value.content_digest,
        "expires_at": to_primitive(value.expires_at),
        "citations": [
            {
                **_object(item),
                "content_digest": item.content_digest,
                "source": {**_object(item.source), "content_digest": item.source.content_digest},
            }
            for item in value.citations
        ],
    }


def _item(value: app.ResearchItemView) -> dict[str, object]:
    return {
        **_object(value),
        "source": _source(value.source),
        "owner_revisions": [_note(item) for item in value.owner_revisions],
    }


def research_view(value: object) -> dict[str, object]:
    """Only the eight application ports' known envelopes cross this boundary."""
    if isinstance(value, app.ResearchSummary):
        return {**_object(value), "items": [_item(item) for item in value.items]}
    if isinstance(value, app.ResearchItemView):
        return _item(value)
    if isinstance(value, ResearchNoteRevision):
        return _note(value)
    if isinstance(value, ResearchReviewAcknowledgment):
        return _object(value)
    if isinstance(value, Page) and all(
        isinstance(item, ResearchNoteRevision) for item in value.items
    ):
        return {**_object(value), "items": [_note(item) for item in value.items]}
    raise ValueError("Unknown research response.")


def research_response[T: BaseModel](
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
        payload = schema.model_validate(research_view(value)).model_dump_json().encode("utf-8")
    except (ValidationError, TypeError, ValueError):
        return _error(request, 500, "INTERNAL_ERROR", "The research operation failed.")
    if len(payload) > MAX_RESEARCH_RESPONSE_BYTES:
        return _error(
            request, 422, "RESULT_TOO_LARGE", "The research response exceeds its byte bound."
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
