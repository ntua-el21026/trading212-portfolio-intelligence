"""Five authenticated owner preference routes; saved selections never authorize finance."""

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
from trading212_api_contracts import owner_layouts as wire
from trading212_api_contracts.targets import IdempotencyKey, UUIDString
from trading212_application import owner_layouts as app
from trading212_domain.errors import DomainError
from trading212_observability import AuthenticationMethod
from trading212_security.principals import AuthenticationError, Authorizer, Principal
from trading212_security.sessions import SessionManager
from trading212_security.settings import SecuritySettings

from .owner_layout_schemas import layout_content, layout_response
from .target_routes import BoundedTargetRoute, _error

_IDEMPOTENCY = TypeAdapter(IdempotencyKey)
_ERRORS = {
    "NOT_FOUND": (404, "The saved layout resource was not found."),
    "ACCESS_DENIED": (403, "Access to this saved layout operation is denied."),
    "VALIDATION_FAILED": (422, "The bounded saved layout request is invalid."),
    "INPUT_BOUND_EXCEEDED": (422, "The saved layout input exceeds its resource bounds."),
    "CONFLICT": (409, "The request identity or retained revision conflicts."),
    "REVISION_MISMATCH": (412, "The current saved layout revision differs."),
    "REVISION_REQUIRED": (428, "The current saved layout revision is required."),
    "CURSOR_INVALID": (400, "The saved layout cursor is invalid or expired."),
    "SOURCE_UNAVAILABLE": (503, "The retained saved layout source or service is unavailable."),
}


class OwnerLayoutApiContext(Protocol):
    @property
    def owner_layout_service(self) -> app.OwnerLayoutService | None: ...
    @property
    def settings(self) -> SecuritySettings: ...
    @property
    def sessions(self) -> SessionManager: ...
    @property
    def clock(self) -> Callable[[], datetime]: ...


def _revision(request: Request, identifier: UUID) -> int:
    header = request.headers.get("if-match")
    if header is None:
        raise app.OwnerLayoutServiceError(app.OwnerLayoutErrorCode.REVISION_REQUIRED)
    match = re.fullmatch(
        r'"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):([1-9][0-9]{0,2})"',
        header,
    )
    if match is None or int(match[2]) > 129:
        raise app.OwnerLayoutServiceError(app.OwnerLayoutErrorCode.VALIDATION_FAILED)
    if UUID(match[1]) != identifier:
        raise app.OwnerLayoutServiceError(app.OwnerLayoutErrorCode.REVISION_MISMATCH)
    return int(match[2])


def register_owner_layout_routes(
    application: FastAPI,
    principal_dependency: Callable[[Request], Awaitable[Principal]],
    context_provider: Callable[[Request], OwnerLayoutApiContext],
) -> None:
    class AuthorizedOwnerLayoutRoute(BoundedTargetRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def authenticated(request: Request) -> Response:
                try:
                    context = context_provider(request)
                    principal = await principal_dependency(request)
                    scopes = (
                        app.LAYOUT_READ_SCOPES
                        if request.method == "GET"
                        else app.LAYOUT_WRITE_SCOPES
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
                    request.state.owner_layout_principal = principal
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
                        request.state.owner_layout_key = _IDEMPOTENCY.validate_python(
                            request.headers.get("x-idempotency-key")
                        )
                    return await handler(request)
                except (ValidationError, DomainError):
                    return _error(
                        request,
                        422,
                        "VALIDATION_FAILED",
                        "The bounded saved layout request is invalid.",
                    )
                except app.OwnerLayoutServiceError as failure:
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
        principal = request.state.owner_layout_principal
        if not isinstance(principal, Principal):
            raise AuthenticationError("Authentication is required.")
        return principal

    principal_dep = Depends(principal_from_request)
    router = APIRouter(
        prefix="/api/v1", tags=["owner-layouts"], route_class=AuthorizedOwnerLayoutRoute
    )

    def service(request: Request) -> app.OwnerLayoutService:
        value = context_provider(request).owner_layout_service
        if value is None:
            raise app.OwnerLayoutServiceError(app.OwnerLayoutErrorCode.SOURCE_UNAVAILABLE)
        return value

    def command_context(request: Request) -> dict[str, str]:
        return {
            "idempotency_key": request.state.owner_layout_key,
            "correlation_id": request.state.correlation_id,
        }

    @router.get(
        "/preferences/layouts",
        response_model=wire.OwnerLayoutPage,
        operation_id="list_owner_layouts",
    )
    async def list_owner_layouts(
        request: Request,
        query: Annotated[wire.OwnerLayoutPageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_owner_layouts(
            principal,
            app.OwnerLayoutPageQuery(
                limit=query.limit, cursor=query.cursor, include_archived=query.include_archived
            ),
        )
        return layout_response(request, value, wire.OwnerLayoutPage, conditional=True)

    @router.get(
        "/preferences/layouts/{layout_id}",
        response_model=wire.OwnerLayoutView,
        operation_id="get_owner_layout",
    )
    async def get_owner_layout(
        request: Request,
        layout_id: UUIDString,
        query: Annotated[wire.OwnerLayoutDetailQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_owner_layout(
            principal,
            UUID(layout_id),
            version_id=None if query.version_id is None else UUID(query.version_id),
        )
        return layout_response(request, value, wire.OwnerLayoutView, conditional=True)

    @router.post(
        "/preferences/layouts",
        response_model=wire.OwnerLayoutView,
        operation_id="create_owner_layout",
        status_code=201,
    )
    async def create_owner_layout(
        request: Request, body: wire.CreateOwnerLayoutRequest, principal: Principal = principal_dep
    ) -> Response:
        value = await service(request).create_owner_layout(
            principal,
            app.CreateOwnerLayout(content=layout_content(body.content), **command_context(request)),
        )
        return layout_response(request, value, wire.OwnerLayoutView, status_code=201)

    @router.patch(
        "/preferences/layouts/{layout_id}",
        response_model=wire.OwnerLayoutView,
        operation_id="update_owner_layout",
    )
    async def update_owner_layout(
        request: Request,
        layout_id: UUIDString,
        body: wire.UpdateOwnerLayoutRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).update_owner_layout(
            principal,
            app.UpdateOwnerLayout(
                layout_id=UUID(layout_id),
                expected_revision=_revision(request, UUID(layout_id)),
                content=layout_content(body.content),
                **command_context(request),
            ),
        )
        return layout_response(request, value, wire.OwnerLayoutView)

    @router.post(
        "/preferences/layouts/{layout_id}/archive",
        response_model=wire.OwnerLayoutArchiveReceipt,
        operation_id="archive_owner_layout",
    )
    async def archive_owner_layout(
        request: Request,
        layout_id: UUIDString,
        body: wire.ArchiveOwnerLayoutRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).archive_owner_layout(
            principal,
            app.ArchiveOwnerLayout(
                layout_id=UUID(layout_id),
                expected_revision=_revision(request, UUID(layout_id)),
                **command_context(request),
            ),
        )
        return layout_response(request, value, wire.OwnerLayoutArchiveReceipt)

    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        if (route.methods or set()) & {"POST", "PATCH"}:
            parameters = [
                {
                    "name": "X-Idempotency-Key",
                    "in": "header",
                    "required": True,
                    "schema": _IDEMPOTENCY.json_schema(),
                }
            ]
            if route.operation_id in {"update_owner_layout", "archive_owner_layout"}:
                parameters.append(
                    {
                        "name": "If-Match",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string", "maxLength": 2048},
                    }
                )
            route.openapi_extra = {"parameters": parameters}
        else:
            route.responses.update({304: {"description": "Authorized representation unchanged"}})
    application.include_router(router)
