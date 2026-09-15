"""Eight authenticated research routes over current owned, licensed saved records."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime
from typing import Annotated, Any, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import TypeAdapter, ValidationError
from starlette.responses import JSONResponse
from trading212_api_contracts import research as wire
from trading212_api_contracts.targets import IdempotencyKey, UUIDString
from trading212_application import research as app
from trading212_domain.errors import DomainError
from trading212_domain.research import ResearchEventKind, ResearchReviewState
from trading212_observability import AuthenticationMethod
from trading212_security.principals import AuthenticationError, Authorizer, Principal
from trading212_security.sessions import SessionManager
from trading212_security.settings import SecuritySettings

from .research_schemas import research_note_content, research_response
from .target_routes import BoundedTargetRoute, _error

_IDEMPOTENCY = TypeAdapter(IdempotencyKey)
_ERRORS = {
    "NOT_FOUND": (404, "The research resource was not found."),
    "ACCESS_DENIED": (403, "Access to this research operation is denied."),
    "VALIDATION_FAILED": (422, "The bounded research request is invalid."),
    "INPUT_BOUND_EXCEEDED": (422, "The research input exceeds its resource bounds."),
    "CONFLICT": (409, "The request identity or retained revision conflicts."),
    "REVISION_MISMATCH": (412, "The current research note revision differs."),
    "REVISION_REQUIRED": (428, "The current research note revision is required."),
    "CURSOR_INVALID": (400, "The research cursor is invalid or expired."),
    "RATE_LIMITED": (429, "The research operation reached its configured capacity."),
    "SOURCE_UNAVAILABLE": (503, "The retained research source or service is unavailable."),
}


class ResearchApiContext(Protocol):
    @property
    def research_service(self) -> app.ResearchService | None: ...
    @property
    def settings(self) -> SecuritySettings: ...
    @property
    def sessions(self) -> SessionManager: ...
    @property
    def clock(self) -> Callable[[], datetime]: ...


def _revision(request: Request, identifier: UUID) -> int:
    header = request.headers.get("if-match")
    if header is None:
        raise app.ResearchServiceError(app.ResearchErrorCode.REVISION_REQUIRED)
    match = re.fullmatch(
        r'"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):([1-9][0-9]{0,2})"',
        header,
    )
    if match is None or int(match[2]) > 512:
        raise app.ResearchServiceError(app.ResearchErrorCode.VALIDATION_FAILED)
    if UUID(match[1]) != identifier:
        raise app.ResearchServiceError(app.ResearchErrorCode.REVISION_MISMATCH)
    return int(match[2])


def register_research_routes(
    application: FastAPI,
    principal_dependency: Callable[[Request], Awaitable[Principal]],
    context_provider: Callable[[Request], ResearchApiContext],
) -> None:
    class AuthorizedResearchRoute(BoundedTargetRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def authenticated(request: Request) -> Response:
                try:
                    context = context_provider(request)
                    principal = await principal_dependency(request)
                    scopes = (
                        app.RESEARCH_READ_SCOPES
                        if request.method == "GET"
                        else app.RESEARCH_WRITE_SCOPES
                    )
                    for scope in scopes:
                        Authorizer().require_scope(principal, scope, now=context.clock())
                    for name in (
                        "x-idempotency-key",
                        "if-match",
                        "if-none-match",
                        "x-csrf-token",
                        "origin",
                    ):
                        if len(request.headers.getlist(name)) > 1:
                            return _error(
                                request, 422, "VALIDATION_FAILED", "The request is invalid."
                            )
                    request.state.research_principal = principal
                    if request.method != "GET":
                        if (
                            getattr(request.state, "authentication_method", None)
                            == AuthenticationMethod.SESSION
                        ):
                            cookie, csrf = (
                                request.cookies.get("t212pi_session"),
                                request.headers.get("x-csrf-token"),
                            )
                            if (
                                not cookie
                                or len(cookie) > 2048
                                or not csrf
                                or len(csrf) > 2048
                                or request.headers.get("origin")
                                not in context.settings.allowed_origins
                            ):
                                raise AuthenticationError(
                                    "Session command authentication is required."
                                )
                            await context.sessions.validate_csrf(cookie, csrf)
                        request.state.research_key = _IDEMPOTENCY.validate_python(
                            request.headers.get("x-idempotency-key")
                        )
                    return await handler(request)
                except (ValidationError, DomainError):
                    return _error(
                        request,
                        422,
                        "VALIDATION_FAILED",
                        "The bounded research request is invalid.",
                    )
                except app.ResearchServiceError as failure:
                    status, message = _ERRORS[failure.code.value]
                    headers = {"Cache-Control": "private, no-store"}
                    if status == 429:
                        headers["Retry-After"] = "60"
                    return JSONResponse(
                        status_code=status,
                        headers=headers,
                        content={
                            "error": {
                                "code": failure.code.value,
                                "message": message,
                                "correlation_id": getattr(
                                    request.state, "correlation_id", "unavailable"
                                ),
                                "retryable": status == 503,
                                "details": {},
                            }
                        },
                    )

            return authenticated

    async def principal_from_request(request: Request) -> Principal:
        principal = request.state.research_principal
        if not isinstance(principal, Principal):
            raise AuthenticationError("Authentication is required.")
        return principal

    principal_dep = Depends(principal_from_request)
    router = APIRouter(prefix="/api/v1", tags=["research"], route_class=AuthorizedResearchRoute)

    def service(request: Request) -> app.ResearchService:
        value = context_provider(request).research_service
        if value is None:
            raise app.ResearchServiceError(app.ResearchErrorCode.SOURCE_UNAVAILABLE)
        return value

    def command_context(request: Request) -> dict[str, str]:
        return {
            "idempotency_key": request.state.research_key,
            "correlation_id": request.state.correlation_id,
        }

    @router.get(
        "/accounts/{account_id}/research",
        response_model=wire.ResearchSummary,
        operation_id="get_research_summary",
    )
    async def get_research_summary(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.ResearchSummaryQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_research_summary(
            principal,
            app.ResearchSummaryQuery(
                account_id=UUID(account_id),
                xray_run_id=UUID(query.xray_run_id),
                source_cutoff_at=query.source_cutoff_at,
                entity_id=None if query.entity_id is None else UUID(query.entity_id),
                event_kind=None
                if query.event_kind is None
                else ResearchEventKind(query.event_kind),
                review_state=ResearchReviewState(query.review_state),
                limit=query.limit,
                cursor=query.cursor,
            ),
        )
        return research_response(request, value, wire.ResearchSummary, conditional=True)

    @router.get(
        "/research/items/{item_id}",
        response_model=wire.ResearchItemView,
        operation_id="get_research_item",
    )
    async def get_research_item(
        request: Request, item_id: UUIDString, principal: Principal = principal_dep
    ) -> Response:
        value = await service(request).get_research_item(principal, UUID(item_id))
        return research_response(request, value, wire.ResearchItemView, conditional=True)

    @router.get(
        "/accounts/{account_id}/research/notes",
        response_model=wire.ResearchNotePage,
        operation_id="list_research_notes",
    )
    async def list_research_notes(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.ResearchPageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_research_notes(
            principal,
            UUID(account_id),
            app.ResearchPageQuery(limit=query.limit, cursor=query.cursor),
        )
        return research_response(request, value, wire.ResearchNotePage)

    @router.post(
        "/accounts/{account_id}/research/notes",
        response_model=wire.ResearchNoteRevision,
        operation_id="create_research_note",
        status_code=201,
    )
    async def create_research_note(
        request: Request,
        account_id: UUIDString,
        body: wire.CreateResearchNoteRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).create_research_note(
            principal,
            app.CreateResearchNote(
                account_id=UUID(account_id),
                entity_id=UUID(body.entity_id),
                content=research_note_content(body.content),
                **command_context(request),
            ),
        )
        return research_response(
            request,
            value,
            wire.ResearchNoteRevision,
            status_code=201,
            etag=f'"{value.note_id}:{value.revision}"',
        )

    @router.get(
        "/research/notes/{note_id}",
        response_model=wire.ResearchNoteRevision,
        operation_id="get_research_note",
    )
    async def get_research_note(
        request: Request, note_id: UUIDString, principal: Principal = principal_dep
    ) -> Response:
        value = await service(request).get_research_note(principal, UUID(note_id))
        return research_response(
            request,
            value,
            wire.ResearchNoteRevision,
            conditional=True,
            etag=f'"{value.note_id}:{value.revision}"',
        )

    @router.get(
        "/research/notes/{note_id}/versions",
        response_model=wire.ResearchNotePage,
        operation_id="list_research_note_versions",
    )
    async def list_research_note_versions(
        request: Request,
        note_id: UUIDString,
        query: Annotated[wire.ResearchPageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_research_note_versions(
            principal, UUID(note_id), app.ResearchPageQuery(limit=query.limit, cursor=query.cursor)
        )
        return research_response(request, value, wire.ResearchNotePage)

    @router.post(
        "/research/notes/{note_id}/versions",
        response_model=wire.ResearchNoteRevision,
        operation_id="create_research_note_version",
        status_code=201,
    )
    async def create_research_note_version(
        request: Request,
        note_id: UUIDString,
        body: wire.CreateResearchNoteVersionRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        identifier = UUID(note_id)
        value = await service(request).create_research_note_version(
            principal,
            app.CreateResearchNoteVersion(
                note_id=identifier,
                expected_revision=_revision(request, identifier),
                content=research_note_content(body.content),
                **command_context(request),
            ),
        )
        return research_response(
            request,
            value,
            wire.ResearchNoteRevision,
            status_code=201,
            etag=f'"{value.note_id}:{value.revision}"',
        )

    @router.post(
        "/research/events/{event_id}/review",
        response_model=wire.ResearchReviewAcknowledgment,
        operation_id="review_research_event",
    )
    async def review_research_event(
        request: Request,
        event_id: UUIDString,
        body: wire.ReviewResearchEventRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).review_research_event(
            principal,
            app.ReviewResearchEvent(
                event_id=UUID(event_id),
                revision_id=UUID(body.revision_id),
                revision_digest=body.revision_digest,
                **command_context(request),
            ),
        )
        return research_response(request, value, wire.ResearchReviewAcknowledgment)

    for route in router.routes:
        if isinstance(route, APIRoute):
            if "POST" in (route.methods or set()):
                parameters = [
                    {
                        "name": "X-Idempotency-Key",
                        "in": "header",
                        "required": True,
                        "schema": _IDEMPOTENCY.json_schema(),
                    }
                ]
                if route.operation_id == "create_research_note_version":
                    parameters.append(
                        {
                            "name": "If-Match",
                            "in": "header",
                            "required": True,
                            "schema": {"type": "string", "maxLength": 2048},
                        }
                    )
                route.openapi_extra = {"parameters": parameters}
            elif route.operation_id in {
                "get_research_summary",
                "get_research_item",
                "get_research_note",
            }:
                route.responses.update(
                    {304: {"description": "Authorized representation unchanged"}}
                )
    application.include_router(router)
