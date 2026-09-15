"""Seventeen authenticated, bounded projection and goal routes over one service."""

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
from trading212_api_contracts import projections as wire
from trading212_api_contracts.targets import IdempotencyKey, UUIDString
from trading212_application import projection as app
from trading212_application.projection_calendar import ProjectionCalendarError
from trading212_domain.errors import DomainError
from trading212_observability import AuthenticationMethod
from trading212_security.principals import AuthenticationError, Authorizer, Principal, Scope
from trading212_security.sessions import SessionManager
from trading212_security.settings import SecuritySettings

from .projection_schemas import (
    projection_assumptions,
    projection_goal,
    projection_metadata,
    projection_response,
    projection_run,
)
from .target_routes import BoundedTargetRoute, _error

_IDEMPOTENCY = TypeAdapter(IdempotencyKey)
_ERRORS = {
    "NOT_FOUND": (404, "The projection resource was not found."),
    "ACCESS_DENIED": (403, "Access to the projection operation is denied."),
    "VALIDATION_FAILED": (422, "The bounded projection request is invalid."),
    "INPUT_BOUND_EXCEEDED": (422, "The projection input exceeds its resource bounds."),
    "CONFLICT": (409, "The request identity or retained input conflicts."),
    "INVALID_STATE_TRANSITION": (409, "The projection job cannot make this transition."),
    "REVISION_MISMATCH": (412, "The current projection definition revision differs."),
    "REVISION_REQUIRED": (428, "The current projection definition revision is required."),
    "CURSOR_INVALID": (400, "The projection cursor is invalid or expired."),
    "RATE_LIMITED": (429, "The projection operation reached its configured capacity."),
    "SOURCE_UNAVAILABLE": (503, "The pinned projection source is unavailable."),
    "PROJECTION_UNAVAILABLE": (503, "The projection result or service is unavailable."),
    "RUN_EXPIRED": (410, "The projection run inputs have expired."),
    "CALENDAR_OVERFLOW": (422, "The projection calendar exceeds supported dates."),
    "DATE_OUTSIDE_HORIZON": (422, "A scheduled date falls outside the projection horizon."),
    "DATE_NOT_MONTH_BOUNDARY": (422, "A scheduled date is not a projection month boundary."),
    "GOAL_DATE_MISMATCH": (422, "The goal date differs from the selected projection horizon."),
}


class ProjectionApiContext(Protocol):
    @property
    def projection_service(self) -> app.ProjectionService | None: ...
    @property
    def settings(self) -> SecuritySettings: ...
    @property
    def sessions(self) -> SessionManager: ...
    @property
    def clock(self) -> Callable[[], datetime]: ...


def _revision(request: Request, identifier: UUID) -> int:
    header = request.headers.get("if-match")
    if header is None:
        raise app.ProjectionServiceError(app.ProjectionErrorCode.REVISION_REQUIRED)
    match = re.fullmatch(
        r'"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):([1-9][0-9]{0,2})"',
        header,
    )
    if match is None or int(match[2]) > 512:
        raise app.ProjectionServiceError(app.ProjectionErrorCode.VALIDATION_FAILED)
    if UUID(match[1]) != identifier:
        raise app.ProjectionServiceError(app.ProjectionErrorCode.REVISION_MISMATCH)
    return int(match[2])


def register_projection_routes(
    application: FastAPI,
    principal_dependency: Callable[[Request], Awaitable[Principal]],
    context_provider: Callable[[Request], ProjectionApiContext],
) -> None:
    class AuthorizedProjectionRoute(BoundedTargetRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def authenticated(request: Request) -> Response:
                try:
                    context = context_provider(request)
                    principal = await principal_dependency(request)
                    write_scope = (
                        Scope.GOALS_WRITE
                        if self.operation_id in {"create_goal", "create_goal_version"}
                        else Scope.PROJECTIONS_WRITE
                    )
                    for scope in (
                        Scope.PORTFOLIO_READ,
                        Scope.ANALYTICS_READ,
                        *((write_scope,) if request.method != "GET" else ()),
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
                    request.state.projection_principal = principal
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
                        request.state.projection_key = _IDEMPOTENCY.validate_python(
                            request.headers.get("x-idempotency-key")
                        )
                    return await handler(request)
                except (ValidationError, DomainError):
                    return _error(
                        request,
                        422,
                        "VALIDATION_FAILED",
                        "The bounded projection request is invalid.",
                    )
                except ProjectionCalendarError as failure:
                    status, message = _ERRORS[failure.code.value]
                    return _error(request, status, failure.code.value, message)
                except app.ProjectionServiceError as failure:
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
        principal = request.state.projection_principal
        if not isinstance(principal, Principal):
            raise AuthenticationError("Authentication is required.")
        return principal

    principal_dep = Depends(principal_from_request)
    router = APIRouter(prefix="/api/v1", tags=["projection"], route_class=AuthorizedProjectionRoute)

    def service(request: Request) -> app.ProjectionService:
        value = context_provider(request).projection_service
        if value is None:
            raise app.ProjectionServiceError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        return value

    def command_context(request: Request) -> dict[str, str]:
        return {
            "idempotency_key": request.state.projection_key,
            "correlation_id": request.state.correlation_id,
        }

    @router.get(
        "/accounts/{account_id}/assumption-sets",
        response_model=wire.ProjectionPageResponse[wire.AssumptionSetResponse],
        operation_id="list_assumption_sets",
    )
    async def list_assumption_sets(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.ProjectionPageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_assumption_sets(
            principal,
            UUID(account_id),
            app.ProjectionPageQuery(limit=query.limit, cursor=query.cursor),
        )
        return projection_response(
            request, value, wire.ProjectionPageResponse[wire.AssumptionSetResponse]
        )

    @router.post(
        "/accounts/{account_id}/assumption-sets",
        response_model=wire.AssumptionSetResponse,
        status_code=201,
        operation_id="create_assumption_set",
    )
    async def create_assumption_set(
        request: Request,
        account_id: UUIDString,
        body: wire.CreateAssumptionSetRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).create_assumption_set(
            principal,
            app.CreateAssumptionSet(
                account_id=UUID(account_id),
                metadata=projection_metadata(body.metadata),
                content=projection_assumptions(body.content),
                **command_context(request),
            ),
        )
        return projection_response(
            request,
            value,
            wire.AssumptionSetResponse,
            etag=f'"{value.id}:{value.revision}"',
            status_code=201,
        )

    @router.get(
        "/assumption-sets/{set_id}",
        response_model=wire.AssumptionSetResponse,
        operation_id="get_assumption_set",
    )
    async def get_assumption_set(
        request: Request,
        set_id: UUIDString,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_assumption_set(principal, UUID(set_id))
        return projection_response(
            request,
            value,
            wire.AssumptionSetResponse,
            etag=f'"{value.id}:{value.revision}"',
            conditional=True,
        )

    @router.get(
        "/assumption-sets/{set_id}/versions",
        response_model=wire.ProjectionPageResponse[wire.AssumptionVersionResponse],
        operation_id="list_assumption_versions",
    )
    async def list_assumption_versions(
        request: Request,
        set_id: UUIDString,
        query: Annotated[wire.ProjectionPageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_assumption_versions(
            principal, UUID(set_id), app.ProjectionPageQuery(limit=query.limit, cursor=query.cursor)
        )
        return projection_response(
            request, value, wire.ProjectionPageResponse[wire.AssumptionVersionResponse]
        )

    @router.post(
        "/assumption-sets/{set_id}/versions",
        response_model=wire.AssumptionVersionResponse,
        status_code=201,
        operation_id="create_assumption_version",
    )
    async def create_assumption_version(
        request: Request,
        set_id: UUIDString,
        body: wire.CreateAssumptionVersionRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        identifier = UUID(set_id)
        value = await service(request).create_assumption_version(
            principal,
            app.CreateAssumptionVersion(
                set_id=identifier,
                expected_revision=_revision(request, identifier),
                metadata=projection_metadata(body.metadata),
                content=projection_assumptions(body.content),
                **command_context(request),
            ),
        )
        return projection_response(
            request,
            value,
            wire.AssumptionVersionResponse,
            etag=f'"{value.set_id}:{value.version_number}"',
            status_code=201,
        )

    @router.get(
        "/assumption-versions/{version_id}",
        response_model=wire.AssumptionVersionResponse,
        operation_id="get_assumption_version",
    )
    async def get_assumption_version(
        request: Request,
        version_id: UUIDString,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_assumption_version(principal, UUID(version_id))
        return projection_response(request, value, wire.AssumptionVersionResponse, conditional=True)

    @router.get(
        "/accounts/{account_id}/goals",
        response_model=wire.ProjectionPageResponse[wire.GoalResponse],
        operation_id="list_goals",
    )
    async def list_goals(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.ProjectionPageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_goals(
            principal,
            UUID(account_id),
            app.ProjectionPageQuery(limit=query.limit, cursor=query.cursor),
        )
        return projection_response(request, value, wire.ProjectionPageResponse[wire.GoalResponse])

    @router.post(
        "/accounts/{account_id}/goals",
        response_model=wire.GoalResponse,
        status_code=201,
        operation_id="create_goal",
    )
    async def create_goal(
        request: Request,
        account_id: UUIDString,
        body: wire.CreateGoalRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).create_goal(
            principal,
            app.CreateGoal(
                account_id=UUID(account_id),
                metadata=projection_metadata(body.metadata),
                content=projection_goal(body.content),
                **command_context(request),
            ),
        )
        return projection_response(
            request,
            value,
            wire.GoalResponse,
            etag=f'"{value.id}:{value.revision}"',
            status_code=201,
        )

    @router.get("/goals/{goal_id}", response_model=wire.GoalResponse, operation_id="get_goal")
    async def get_goal(
        request: Request,
        goal_id: UUIDString,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_goal(principal, UUID(goal_id))
        return projection_response(
            request,
            value,
            wire.GoalResponse,
            etag=f'"{value.id}:{value.revision}"',
            conditional=True,
        )

    @router.get(
        "/goals/{goal_id}/versions",
        response_model=wire.ProjectionPageResponse[wire.GoalVersionResponse],
        operation_id="list_goal_versions",
    )
    async def list_goal_versions(
        request: Request,
        goal_id: UUIDString,
        query: Annotated[wire.ProjectionPageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_goal_versions(
            principal,
            UUID(goal_id),
            app.ProjectionPageQuery(limit=query.limit, cursor=query.cursor),
        )
        return projection_response(
            request, value, wire.ProjectionPageResponse[wire.GoalVersionResponse]
        )

    @router.post(
        "/goals/{goal_id}/versions",
        response_model=wire.GoalVersionResponse,
        status_code=201,
        operation_id="create_goal_version",
    )
    async def create_goal_version(
        request: Request,
        goal_id: UUIDString,
        body: wire.CreateGoalVersionRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        identifier = UUID(goal_id)
        value = await service(request).create_goal_version(
            principal,
            app.CreateGoalVersion(
                goal_id=identifier,
                expected_revision=_revision(request, identifier),
                metadata=projection_metadata(body.metadata),
                content=projection_goal(body.content),
                **command_context(request),
            ),
        )
        return projection_response(
            request,
            value,
            wire.GoalVersionResponse,
            etag=f'"{value.goal_id}:{value.version_number}"',
            status_code=201,
        )

    @router.get(
        "/goal-versions/{version_id}",
        response_model=wire.GoalVersionResponse,
        operation_id="get_goal_version",
    )
    async def get_goal_version(
        request: Request,
        version_id: UUIDString,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_goal_version(principal, UUID(version_id))
        return projection_response(request, value, wire.GoalVersionResponse, conditional=True)

    @router.get(
        "/accounts/{account_id}/projection-runs",
        response_model=wire.ProjectionPageResponse[wire.ProjectionOperationalRunResponse],
        operation_id="list_projection_runs",
    )
    async def list_runs(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.ProjectionPageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_runs(
            principal,
            UUID(account_id),
            app.ProjectionPageQuery(limit=query.limit, cursor=query.cursor),
        )
        return projection_response(
            request, value, wire.ProjectionPageResponse[wire.ProjectionOperationalRunResponse]
        )

    @router.post(
        "/accounts/{account_id}/projection-runs",
        response_model=wire.ProjectionOperationalRunResponse,
        status_code=202,
        operation_id="create_projection_run",
    )
    async def create_run(
        request: Request,
        account_id: UUIDString,
        body: wire.CreateProjectionRunRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).create_run(
            principal,
            projection_run(
                account_id,
                body,
                key=request.state.projection_key,
                correlation=request.state.correlation_id,
            ),
        )
        return projection_response(
            request, value, wire.ProjectionOperationalRunResponse, status_code=202
        )

    @router.get(
        "/projection-runs/{run_id}",
        response_model=wire.ProjectionRunResponse,
        operation_id="get_projection_run",
    )
    async def get_run(
        request: Request,
        run_id: UUIDString,
        query: Annotated[wire.ProjectionPointPageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_run(
            principal,
            UUID(run_id),
            app.ProjectionPointPageQuery(
                point_limit=query.point_limit, point_cursor=query.point_cursor
            ),
        )
        return projection_response(request, value, wire.ProjectionRunResponse, conditional=True)

    @router.get(
        "/projection-runs/{run_id}/goal-analysis",
        response_model=wire.GoalAnalysisResponse,
        operation_id="get_goal_analysis",
    )
    async def get_goal_analysis(
        request: Request,
        run_id: UUIDString,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_goal_analysis(principal, UUID(run_id))
        return projection_response(request, value, wire.GoalAnalysisResponse, conditional=True)

    @router.post(
        "/projection-runs/{run_id}/cancel",
        response_model=wire.ProjectionOperationalRunResponse,
        operation_id="cancel_projection_run",
    )
    async def cancel_run(
        request: Request,
        run_id: UUIDString,
        body: wire.CancelProjectionRunRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).cancel_run(
            principal, app.CancelProjectionRun(run_id=UUID(run_id), **command_context(request))
        )
        return projection_response(request, value, wire.ProjectionOperationalRunResponse)

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
                if route.operation_id in {"create_assumption_version", "create_goal_version"}:
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
                "get_assumption_set",
                "get_assumption_version",
                "get_goal",
                "get_goal_version",
                "get_projection_run",
                "get_goal_analysis",
            }:
                route.responses.update(
                    {304: {"description": "Authorized representation unchanged"}}
                )
    application.include_router(router)
