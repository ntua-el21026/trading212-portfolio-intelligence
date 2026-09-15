"""Eleven authenticated, bounded scenario routes over one canonical application service."""

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
from trading212_api_contracts import scenarios as wire
from trading212_api_contracts.targets import IdempotencyKey, UUIDString
from trading212_application import scenario as app
from trading212_domain.errors import DomainError
from trading212_observability import AuthenticationMethod
from trading212_security.principals import AuthenticationError, Authorizer, Principal, Scope
from trading212_security.sessions import SessionManager
from trading212_security.settings import SecuritySettings

from .scenario_schemas import scenario_definition, scenario_response, scenario_run
from .target_routes import BoundedTargetRoute, _error

_IDEMPOTENCY = TypeAdapter(IdempotencyKey)
_ERRORS = {
    "NOT_FOUND": (404, "The scenario resource was not found."),
    "ACCESS_DENIED": (403, "Access to the scenario operation is denied."),
    "VALIDATION_FAILED": (422, "The bounded scenario request is invalid."),
    "INPUT_BOUND_EXCEEDED": (422, "The scenario input exceeds its resource bounds."),
    "CONFLICT": (409, "The request identity or retained input conflicts."),
    "INVALID_STATE_TRANSITION": (409, "The scenario job cannot make this transition."),
    "REVISION_MISMATCH": (412, "The current scenario definition revision differs."),
    "REVISION_REQUIRED": (428, "The current scenario definition revision is required."),
    "CURSOR_INVALID": (400, "The history cursor is invalid or expired."),
    "RATE_LIMITED": (429, "The scenario operation reached its configured capacity."),
    "SOURCE_UNAVAILABLE": (503, "The pinned scenario source is unavailable."),
    "SCENARIO_UNAVAILABLE": (503, "The scenario result or service is unavailable."),
    "RUN_EXPIRED": (410, "The scenario run inputs have expired."),
}


class ScenarioApiContext(Protocol):
    @property
    def scenario_service(self) -> app.ScenarioService | None: ...
    @property
    def settings(self) -> SecuritySettings: ...
    @property
    def sessions(self) -> SessionManager: ...
    @property
    def clock(self) -> Callable[[], datetime]: ...


def _revision(request: Request, identifier: UUID) -> int:
    header = request.headers.get("if-match")
    if header is None:
        raise app.ScenarioServiceError(app.ScenarioErrorCode.REVISION_REQUIRED)
    match = re.fullmatch(
        r'"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):([1-9][0-9]{0,2})"',
        header,
    )
    if match is None or int(match[2]) > 512:
        raise app.ScenarioServiceError(app.ScenarioErrorCode.VALIDATION_FAILED)
    if UUID(match[1]) != identifier:
        raise app.ScenarioServiceError(app.ScenarioErrorCode.REVISION_MISMATCH)
    return int(match[2])


def register_scenario_routes(
    application: FastAPI,
    principal_dependency: Callable[[Request], Awaitable[Principal]],
    context_provider: Callable[[Request], ScenarioApiContext],
) -> None:
    class AuthorizedScenarioRoute(BoundedTargetRoute):
        def permits_repeated_query(self, key: str) -> bool:
            return (
                key == "run_ids"
                and self.path == "/api/v1/accounts/{account_id}/scenario-comparison"
            )

        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def authenticated(request: Request) -> Response:
                try:
                    context = context_provider(request)
                    principal = await principal_dependency(request)
                    for scope in (
                        Scope.PORTFOLIO_READ,
                        Scope.ANALYTICS_READ,
                        *((Scope.SCENARIOS_WRITE,) if request.method != "GET" else ()),
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
                    request.state.scenario_principal = principal
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
                        request.state.scenario_key = _IDEMPOTENCY.validate_python(
                            request.headers.get("x-idempotency-key")
                        )
                    return await handler(request)
                except (ValidationError, DomainError):
                    return _error(
                        request,
                        422,
                        "VALIDATION_FAILED",
                        "The bounded scenario request is invalid.",
                    )
                except app.ScenarioServiceError as failure:
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
        principal = request.state.scenario_principal
        if not isinstance(principal, Principal):
            raise AuthenticationError("Authentication is required.")
        return principal

    principal_dep = Depends(principal_from_request)
    router = APIRouter(prefix="/api/v1", tags=["scenario"], route_class=AuthorizedScenarioRoute)

    def service(request: Request) -> app.ScenarioService:
        value = context_provider(request).scenario_service
        if value is None:
            raise app.ScenarioServiceError(app.ScenarioErrorCode.SCENARIO_UNAVAILABLE)
        return value

    def command_context(request: Request) -> dict[str, str]:
        return {
            "idempotency_key": request.state.scenario_key,
            "correlation_id": request.state.correlation_id,
        }

    @router.get(
        "/accounts/{account_id}/scenarios",
        response_model=wire.ScenarioPageResponse[wire.ScenarioDefinitionResponse],
        operation_id="list_scenarios",
    )
    async def list_definitions(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.ScenarioPageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_definitions(
            principal,
            UUID(account_id),
            app.ScenarioPageQuery(limit=query.limit, cursor=query.cursor),
        )
        return scenario_response(
            request, value, wire.ScenarioPageResponse[wire.ScenarioDefinitionResponse]
        )

    @router.post(
        "/accounts/{account_id}/scenarios",
        response_model=wire.ScenarioDefinitionResponse,
        status_code=201,
        operation_id="create_scenario",
    )
    async def create_definition(
        request: Request,
        account_id: UUIDString,
        body: wire.CreateScenarioRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).create_definition(
            principal,
            app.CreateScenario(
                account_id=UUID(account_id),
                content=scenario_definition(body.content),
                **command_context(request),
            ),
        )
        return scenario_response(
            request,
            value,
            wire.ScenarioDefinitionResponse,
            etag=f'"{value.id}:{value.revision}"',
            status_code=201,
        )

    @router.get(
        "/scenarios/{scenario_id}",
        response_model=wire.ScenarioDefinitionResponse,
        operation_id="get_scenario",
    )
    async def get_definition(
        request: Request, scenario_id: UUIDString, principal: Principal = principal_dep
    ) -> Response:
        value = await service(request).get_definition(principal, UUID(scenario_id))
        return scenario_response(
            request,
            value,
            wire.ScenarioDefinitionResponse,
            etag=f'"{value.id}:{value.revision}"',
            conditional=True,
        )

    @router.get(
        "/scenarios/{scenario_id}/versions",
        response_model=wire.ScenarioPageResponse[wire.ScenarioVersionResponse],
        operation_id="list_scenario_versions",
    )
    async def list_versions(
        request: Request,
        scenario_id: UUIDString,
        query: Annotated[wire.ScenarioPageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_versions(
            principal,
            UUID(scenario_id),
            app.ScenarioPageQuery(limit=query.limit, cursor=query.cursor),
        )
        return scenario_response(
            request, value, wire.ScenarioPageResponse[wire.ScenarioVersionResponse]
        )

    @router.post(
        "/scenarios/{scenario_id}/versions",
        response_model=wire.ScenarioVersionResponse,
        status_code=201,
        operation_id="create_scenario_version",
    )
    async def create_version(
        request: Request,
        scenario_id: UUIDString,
        body: wire.CreateScenarioVersionRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        identifier = UUID(scenario_id)
        value = await service(request).create_version(
            principal,
            app.CreateScenarioVersion(
                scenario_id=identifier,
                expected_revision=_revision(request, identifier),
                content=scenario_definition(body.content),
                **command_context(request),
            ),
        )
        return scenario_response(
            request,
            value,
            wire.ScenarioVersionResponse,
            etag=f'"{value.definition_id}:{value.version_number}"',
            status_code=201,
        )

    @router.get(
        "/scenario-versions/{version_id}",
        response_model=wire.ScenarioVersionResponse,
        operation_id="get_scenario_version",
    )
    async def get_version(
        request: Request, version_id: UUIDString, principal: Principal = principal_dep
    ) -> Response:
        value = await service(request).get_version(principal, UUID(version_id))
        return scenario_response(request, value, wire.ScenarioVersionResponse, conditional=True)

    @router.get(
        "/accounts/{account_id}/scenario-runs",
        response_model=wire.ScenarioPageResponse[wire.ScenarioOperationalRunResponse],
        operation_id="list_scenario_runs",
    )
    async def list_runs(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.ScenarioPageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_runs(
            principal,
            UUID(account_id),
            app.ScenarioPageQuery(limit=query.limit, cursor=query.cursor),
        )
        return scenario_response(
            request, value, wire.ScenarioPageResponse[wire.ScenarioOperationalRunResponse]
        )

    @router.post(
        "/accounts/{account_id}/scenario-runs",
        response_model=wire.ScenarioOperationalRunResponse,
        status_code=202,
        operation_id="create_scenario_run",
    )
    async def create_run(
        request: Request,
        account_id: UUIDString,
        body: wire.CreateScenarioRunRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).create_run(
            principal,
            scenario_run(
                account_id,
                body,
                key=request.state.scenario_key,
                correlation=request.state.correlation_id,
            ),
        )
        return scenario_response(
            request, value, wire.ScenarioOperationalRunResponse, status_code=202
        )

    @router.get(
        "/scenario-runs/{run_id}",
        response_model=wire.ScenarioRunResponse,
        operation_id="get_scenario_run",
    )
    async def get_run(
        request: Request,
        run_id: UUIDString,
        query: Annotated[wire.ScenarioComponentPageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_run(
            principal,
            UUID(run_id),
            app.ScenarioComponentPageQuery(
                component_limit=query.component_limit, component_cursor=query.component_cursor
            ),
        )
        return scenario_response(request, value, wire.ScenarioRunResponse, conditional=True)

    @router.get(
        "/accounts/{account_id}/scenario-comparison",
        response_model=wire.ScenarioComparisonPage,
        operation_id="compare_scenarios",
    )
    async def compare(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.ScenarioComparisonQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        selection = app.ScenarioComparisonQuery(
            run_ids=(UUID(query.run_ids[0]), UUID(query.run_ids[1])),
            component_limit=query.component_limit,
            component_cursor=query.component_cursor,
        )
        value = await service(request).compare(principal, UUID(account_id), selection)
        return scenario_response(request, value, wire.ScenarioComparisonPage, conditional=True)

    @router.post(
        "/scenario-runs/{run_id}/cancel",
        response_model=wire.ScenarioOperationalRunResponse,
        operation_id="cancel_scenario_run",
    )
    async def cancel_run(
        request: Request,
        run_id: UUIDString,
        body: wire.CancelScenarioRunRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).cancel_run(
            principal, app.CancelScenarioRun(run_id=UUID(run_id), **command_context(request))
        )
        return scenario_response(request, value, wire.ScenarioOperationalRunResponse)

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
                if route.operation_id == "create_scenario_version":
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
                "get_scenario",
                "get_scenario_version",
                "get_scenario_run",
                "compare_scenarios",
            }:
                route.responses.update(
                    {304: {"description": "Authorized representation unchanged"}}
                )
    application.include_router(router)
