"""Eleven authenticated, bounded risk routes over one canonical application service."""

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
from trading212_api_contracts import risk as wire
from trading212_api_contracts.targets import IdempotencyKey, UUIDString
from trading212_application import risk as app
from trading212_observability import AuthenticationMethod
from trading212_security.principals import AuthenticationError, Authorizer, Principal, Scope
from trading212_security.sessions import SessionManager
from trading212_security.settings import SecuritySettings

from .risk_schemas import risk_definition, risk_response, risk_run
from .target_routes import BoundedTargetRoute, _error

_IDEMPOTENCY = TypeAdapter(IdempotencyKey)
_ERRORS = {
    "NOT_FOUND": (404, "The risk resource was not found."),
    "ACCESS_DENIED": (403, "Access to the risk operation is denied."),
    "VALIDATION_FAILED": (422, "The bounded risk request is invalid."),
    "INPUT_BOUND_EXCEEDED": (422, "The risk input exceeds its resource bounds."),
    "CONFLICT": (409, "The request identity or retained input conflicts."),
    "INVALID_STATE_TRANSITION": (409, "The risk job cannot make this transition."),
    "REVISION_MISMATCH": (412, "The current risk definition revision differs."),
    "REVISION_REQUIRED": (428, "The current risk definition revision is required."),
    "CURSOR_INVALID": (400, "The history cursor is invalid or expired."),
    "RATE_LIMITED": (429, "The risk operation reached its configured capacity."),
    "SOURCE_UNAVAILABLE": (503, "The pinned risk source is unavailable."),
    "RISK_UNAVAILABLE": (503, "The risk result or service is unavailable."),
    "RUN_EXPIRED": (410, "The risk run inputs have expired."),
}


class RiskApiContext(Protocol):
    @property
    def risk_service(self) -> app.RiskService | None: ...
    @property
    def settings(self) -> SecuritySettings: ...
    @property
    def sessions(self) -> SessionManager: ...
    @property
    def clock(self) -> Callable[[], datetime]: ...


def _revision(request: Request, identifier: UUID) -> int:
    header = request.headers.get("if-match")
    if header is None:
        raise app.RiskServiceError(app.RiskErrorCode.REVISION_REQUIRED)
    match = re.fullmatch(
        r'"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):([1-9][0-9]{0,2})"',
        header,
    )
    if match is None or int(match[2]) > 512:
        raise app.RiskServiceError(app.RiskErrorCode.VALIDATION_FAILED)
    if UUID(match[1]) != identifier:
        raise app.RiskServiceError(app.RiskErrorCode.REVISION_MISMATCH)
    return int(match[2])


def register_risk_routes(
    application: FastAPI,
    principal_dependency: Callable[[Request], Awaitable[Principal]],
    context_provider: Callable[[Request], RiskApiContext],
) -> None:
    class AuthorizedRiskRoute(BoundedTargetRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def authenticated(request: Request) -> Response:
                try:
                    context = context_provider(request)
                    principal = await principal_dependency(request)
                    for scope in (
                        Scope.PORTFOLIO_READ,
                        Scope.ANALYTICS_READ,
                        *((Scope.RISK_WRITE,) if request.method != "GET" else ()),
                    ):
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
                    request.state.risk_principal = principal
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
                        request.state.risk_key = _IDEMPOTENCY.validate_python(
                            request.headers.get("x-idempotency-key")
                        )
                    return await handler(request)
                except ValidationError:
                    return _error(
                        request, 422, "VALIDATION_FAILED", "The bounded risk request is invalid."
                    )
                except app.RiskServiceError as failure:
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
        principal = request.state.risk_principal
        if not isinstance(principal, Principal):
            raise AuthenticationError("Authentication is required.")
        return principal

    principal_dep = Depends(principal_from_request)
    router = APIRouter(prefix="/api/v1", tags=["risk"], route_class=AuthorizedRiskRoute)

    def service(request: Request) -> app.RiskService:
        value = context_provider(request).risk_service
        if value is None:
            raise app.RiskServiceError(app.RiskErrorCode.RISK_UNAVAILABLE)
        return value

    def command_context(request: Request) -> dict[str, str]:
        return {
            "idempotency_key": request.state.risk_key,
            "correlation_id": request.state.correlation_id,
        }

    @router.get(
        "/accounts/{account_id}/risk-definitions",
        response_model=wire.RiskPageResponse[wire.RiskDefinitionResponse],
        operation_id="list_risk_definitions",
    )
    async def list_definitions(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.RiskPageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_definitions(
            principal, UUID(account_id), app.RiskPageQuery(limit=query.limit, cursor=query.cursor)
        )
        return risk_response(request, value, wire.RiskPageResponse[wire.RiskDefinitionResponse])

    @router.post(
        "/accounts/{account_id}/risk-definitions",
        response_model=wire.RiskDefinitionResponse,
        status_code=201,
        operation_id="create_risk_definition",
    )
    async def create_definition(
        request: Request,
        account_id: UUIDString,
        body: wire.CreateRiskDefinitionRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).create_definition(
            principal,
            app.CreateRiskDefinition(
                account_id=UUID(account_id),
                content=risk_definition(body.content),
                **command_context(request),
            ),
        )
        return risk_response(
            request,
            value,
            wire.RiskDefinitionResponse,
            etag=f'"{value.id}:{value.revision}"',
            status_code=201,
        )

    @router.get(
        "/risk-definitions/{definition_id}",
        response_model=wire.RiskDefinitionResponse,
        operation_id="get_risk_definition",
    )
    async def get_definition(
        request: Request, definition_id: UUIDString, principal: Principal = principal_dep
    ) -> Response:
        value = await service(request).get_definition(principal, UUID(definition_id))
        return risk_response(
            request,
            value,
            wire.RiskDefinitionResponse,
            etag=f'"{value.id}:{value.revision}"',
            conditional=True,
        )

    @router.get(
        "/risk-definitions/{definition_id}/versions",
        response_model=wire.RiskPageResponse[wire.RiskVersionResponse],
        operation_id="list_risk_versions",
    )
    async def list_versions(
        request: Request,
        definition_id: UUIDString,
        query: Annotated[wire.RiskPageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_versions(
            principal,
            UUID(definition_id),
            app.RiskPageQuery(limit=query.limit, cursor=query.cursor),
        )
        return risk_response(request, value, wire.RiskPageResponse[wire.RiskVersionResponse])

    @router.post(
        "/risk-definitions/{definition_id}/versions",
        response_model=wire.RiskVersionResponse,
        status_code=201,
        operation_id="create_risk_version",
    )
    async def create_version(
        request: Request,
        definition_id: UUIDString,
        body: wire.CreateRiskVersionRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        identifier = UUID(definition_id)
        value = await service(request).create_version(
            principal,
            app.CreateRiskVersion(
                definition_id=identifier,
                expected_revision=_revision(request, identifier),
                content=risk_definition(body.content),
                **command_context(request),
            ),
        )
        return risk_response(
            request,
            value,
            wire.RiskVersionResponse,
            etag=f'"{value.definition_id}:{value.version_number}"',
            status_code=201,
        )

    @router.get(
        "/risk-definition-versions/{version_id}",
        response_model=wire.RiskVersionResponse,
        operation_id="get_risk_version",
    )
    async def get_version(
        request: Request, version_id: UUIDString, principal: Principal = principal_dep
    ) -> Response:
        value = await service(request).get_version(principal, UUID(version_id))
        return risk_response(request, value, wire.RiskVersionResponse, conditional=True)

    @router.get(
        "/accounts/{account_id}/risk-runs",
        response_model=wire.RiskPageResponse[wire.RiskRunResponse],
        operation_id="list_risk_runs",
    )
    async def list_runs(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.RiskPageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_runs(
            principal, UUID(account_id), app.RiskPageQuery(limit=query.limit, cursor=query.cursor)
        )
        return risk_response(request, value, wire.RiskPageResponse[wire.RiskRunResponse])

    @router.post(
        "/accounts/{account_id}/risk-runs",
        response_model=wire.RiskRunResponse,
        status_code=202,
        operation_id="create_risk_run",
    )
    async def create_run(
        request: Request,
        account_id: UUIDString,
        body: wire.CreateRiskRunRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).create_run(
            principal,
            risk_run(
                account_id,
                body,
                key=request.state.risk_key,
                correlation=request.state.correlation_id,
            ),
        )
        return risk_response(request, value, wire.RiskRunResponse, status_code=202)

    @router.get(
        "/risk-runs/{run_id}", response_model=wire.RiskRunResponse, operation_id="get_risk_run"
    )
    async def get_run(
        request: Request, run_id: UUIDString, principal: Principal = principal_dep
    ) -> Response:
        value = await service(request).get_run(principal, UUID(run_id))
        return risk_response(request, value, wire.RiskRunResponse, conditional=True)

    @router.get(
        "/risk-runs/{run_id}/matrix",
        response_model=wire.RiskMatrixResponse,
        operation_id="get_risk_matrix",
    )
    async def get_matrix(
        request: Request, run_id: UUIDString, principal: Principal = principal_dep
    ) -> Response:
        value = await service(request).get_matrix(principal, UUID(run_id))
        return risk_response(request, value, wire.RiskMatrixResponse, conditional=True)

    @router.post(
        "/risk-runs/{run_id}/cancel",
        response_model=wire.RiskRunResponse,
        operation_id="cancel_risk_run",
    )
    async def cancel_run(
        request: Request,
        run_id: UUIDString,
        body: wire.CancelRiskRunRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).cancel_run(
            principal, app.CancelRiskRun(run_id=UUID(run_id), **command_context(request))
        )
        return risk_response(request, value, wire.RiskRunResponse)

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
                if route.operation_id == "create_risk_version":
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
                "get_risk_definition",
                "get_risk_version",
                "get_risk_run",
                "get_risk_matrix",
            }:
                route.responses.update(
                    {304: {"description": "Authorized representation unchanged"}}
                )
    application.include_router(router)
