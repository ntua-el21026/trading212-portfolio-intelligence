"""Six authenticated aggregate routes over current owned, licensed saved records."""

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
from trading212_api_contracts import aggregation as wire
from trading212_api_contracts.targets import IdempotencyKey, UUIDString
from trading212_application import aggregation as app
from trading212_domain.aggregation import AggregateActivityWindow, AggregateFxBinding, AggregateView
from trading212_domain.errors import DomainError
from trading212_domain.values import CurrencyCode
from trading212_observability import AuthenticationMethod
from trading212_security.principals import AuthenticationError, Authorizer, Principal
from trading212_security.sessions import SessionManager
from trading212_security.settings import SecuritySettings

from .aggregation_schemas import aggregate_response, aggregate_selection_content
from .target_routes import BoundedTargetRoute, _error

_IDEMPOTENCY = TypeAdapter(IdempotencyKey)
_ERRORS = {
    "NOT_FOUND": (404, "The aggregate resource was not found."),
    "ACCESS_DENIED": (403, "Access to this aggregate operation is denied."),
    "VALIDATION_FAILED": (422, "The bounded aggregate request is invalid."),
    "INPUT_BOUND_EXCEEDED": (422, "The aggregate input exceeds its resource bounds."),
    "CONFLICT": (409, "The request identity or retained revision conflicts."),
    "REVISION_MISMATCH": (412, "The current aggregate selection revision differs."),
    "REVISION_REQUIRED": (428, "The current aggregate selection revision is required."),
    "CURSOR_INVALID": (400, "The aggregate cursor is invalid or expired."),
    "RATE_LIMITED": (429, "The aggregate operation reached its configured capacity."),
    "SOURCE_UNAVAILABLE": (503, "The retained aggregate source or service is unavailable."),
    "RUN_EXPIRED": (410, "The saved aggregate run has expired."),
    "DEADLINE_EXCEEDED": (503, "The aggregate operation exceeded its execution deadline."),
}


class AggregateApiContext(Protocol):
    @property
    def aggregate_service(self) -> app.AggregateService | None: ...
    @property
    def settings(self) -> SecuritySettings: ...
    @property
    def sessions(self) -> SessionManager: ...
    @property
    def clock(self) -> Callable[[], datetime]: ...


def _revision(request: Request, identifier: UUID) -> int:
    header = request.headers.get("if-match")
    if header is None:
        raise app.AggregateServiceError(app.AggregateErrorCode.REVISION_REQUIRED)
    match = re.fullmatch(
        r'"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):([1-9][0-9]{0,9})"',
        header,
    )
    if match is None or int(match[2]) > 2147483647:
        raise app.AggregateServiceError(app.AggregateErrorCode.VALIDATION_FAILED)
    if UUID(match[1]) != identifier:
        raise app.AggregateServiceError(app.AggregateErrorCode.REVISION_MISMATCH)
    return int(match[2])


def register_aggregation_routes(
    application: FastAPI,
    principal_dependency: Callable[[Request], Awaitable[Principal]],
    context_provider: Callable[[Request], AggregateApiContext],
) -> None:
    class AuthorizedAggregateRoute(BoundedTargetRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def authenticated(request: Request) -> Response:
                try:
                    context = context_provider(request)
                    principal = await principal_dependency(request)
                    scopes = (
                        app.AGGREGATE_READ_SCOPES
                        if request.method == "GET"
                        else app.AGGREGATE_WRITE_SCOPES
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
                    request.state.aggregate_principal = principal
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
                        request.state.aggregate_key = _IDEMPOTENCY.validate_python(
                            request.headers.get("x-idempotency-key")
                        )
                    return await handler(request)
                except (ValidationError, DomainError):
                    return _error(
                        request,
                        422,
                        "VALIDATION_FAILED",
                        "The bounded aggregate request is invalid.",
                    )
                except app.AggregateServiceError as failure:
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
        principal = request.state.aggregate_principal
        if not isinstance(principal, Principal):
            raise AuthenticationError("Authentication is required.")
        return principal

    principal_dep = Depends(principal_from_request)
    router = APIRouter(prefix="/api/v1", tags=["aggregate"], route_class=AuthorizedAggregateRoute)

    def service(request: Request) -> app.AggregateService:
        value = context_provider(request).aggregate_service
        if value is None:
            raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
        return value

    def command_context(request: Request) -> dict[str, str]:
        return {
            "idempotency_key": request.state.aggregate_key,
            "correlation_id": request.state.correlation_id,
        }

    @router.get(
        "/aggregate-selections",
        response_model=wire.AggregatePageResponse[wire.AggregateSelectionResponse],
        operation_id="list_aggregate_selections",
    )
    async def list_aggregate_selections(
        request: Request,
        query: Annotated[wire.AggregatePageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_selections(
            principal, app.AggregatePageQuery(limit=query.limit, cursor=query.cursor)
        )
        return aggregate_response(
            request, value, wire.AggregatePageResponse[wire.AggregateSelectionResponse]
        )

    @router.post(
        "/aggregate-selections",
        response_model=wire.AggregateSelectionResponse,
        operation_id="create_aggregate_selection",
        status_code=201,
    )
    async def create_aggregate_selection(
        request: Request,
        body: wire.CreateAggregateSelectionRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).create_selection(
            principal,
            app.CreateAggregateSelection(
                content=aggregate_selection_content(body.content), **command_context(request)
            ),
        )
        return aggregate_response(
            request,
            value,
            wire.AggregateSelectionResponse,
            status_code=201,
            etag=f'"{value.selection_id}:{value.revision}"',
        )

    @router.get(
        "/aggregate-selections/{selection_id}",
        response_model=wire.AggregateSelectionResponse,
        operation_id="get_aggregate_selection",
    )
    async def get_aggregate_selection(
        request: Request, selection_id: UUIDString, principal: Principal = principal_dep
    ) -> Response:
        value = await service(request).get_selection(principal, UUID(selection_id))
        return aggregate_response(
            request,
            value,
            wire.AggregateSelectionResponse,
            conditional=True,
            etag=f'"{value.selection_id}:{value.revision}"',
        )

    @router.get(
        "/aggregate-selections/{selection_id}/runs",
        response_model=wire.AggregatePageResponse[wire.AggregateRunReceipt],
        operation_id="list_aggregate_runs",
    )
    async def list_aggregate_runs(
        request: Request,
        selection_id: UUIDString,
        query: Annotated[wire.AggregatePageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_runs(
            principal,
            UUID(selection_id),
            app.AggregatePageQuery(limit=query.limit, cursor=query.cursor),
        )
        return aggregate_response(
            request, value, wire.AggregatePageResponse[wire.AggregateRunReceipt]
        )

    @router.post(
        "/aggregate-selections/{selection_id}/runs",
        response_model=wire.AggregateRunReceipt,
        operation_id="create_aggregate_run",
        status_code=201,
    )
    async def create_aggregate_run(
        request: Request,
        selection_id: UUIDString,
        body: wire.CreateAggregateRunRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        identifier = UUID(selection_id)
        value = await service(request).create_run(
            principal,
            app.CreateAggregateRun(
                selection_id=identifier,
                expected_revision=_revision(request, identifier),
                fx_bindings=tuple(
                    AggregateFxBinding(
                        account_id=UUID(item.account_id),
                        currency=CurrencyCode(item.currency),
                        fx_observation_id=UUID(item.fx_observation_id),
                    )
                    for item in body.fx_bindings
                ),
                activity_window=None
                if body.activity_window is None
                else AggregateActivityWindow(
                    start_at=body.activity_window.start_at, end_at=body.activity_window.end_at
                ),
                **command_context(request),
            ),
        )
        return aggregate_response(request, value, wire.AggregateRunReceipt, status_code=201)

    @router.get(
        "/aggregate-runs/{run_id}",
        response_model=wire.AggregateRunResponse,
        operation_id="get_aggregate_run",
    )
    async def get_aggregate_run(
        request: Request,
        run_id: UUIDString,
        query: Annotated[wire.AggregateRunQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_run(
            principal,
            UUID(run_id),
            app.AggregateRunQuery(
                view=AggregateView(query.view), limit=query.limit, cursor=query.cursor
            ),
        )
        return aggregate_response(request, value, wire.AggregateRunResponse, conditional=True)

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
                if route.operation_id == "create_aggregate_run":
                    parameters.append(
                        {
                            "name": "If-Match",
                            "in": "header",
                            "required": True,
                            "schema": {"type": "string", "maxLength": 2048},
                        }
                    )
                route.openapi_extra = {"parameters": parameters}
            elif route.operation_id in {"get_aggregate_selection", "get_aggregate_run"}:
                route.responses.update(
                    {304: {"description": "Authorized representation unchanged"}}
                )
    application.include_router(router)
