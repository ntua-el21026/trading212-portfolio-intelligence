"""Six bounded planning operations over an explicitly injected application service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import TypeAdapter
from trading212_api_contracts import planning as wire
from trading212_api_contracts.targets import IdempotencyKey, UUIDString
from trading212_application import planning as application_planning
from trading212_domain.planning import DriftBasis, PlanOutcome
from trading212_domain.values import CurrencyCode
from trading212_observability import AuthenticationMethod
from trading212_security.principals import AuthenticationError, Authorizer, Principal, Scope
from trading212_security.sessions import SessionManager
from trading212_security.settings import SecuritySettings

from .planning_schemas import planning_command, planning_response
from .target_routes import BoundedTargetRoute

_IDEMPOTENCY = TypeAdapter(IdempotencyKey)


class PlanningApiContext(Protocol):
    @property
    def planning_service(self) -> application_planning.PlanningService | None: ...

    @property
    def settings(self) -> SecuritySettings: ...

    @property
    def sessions(self) -> SessionManager: ...

    @property
    def clock(self) -> Callable[[], datetime]: ...


def register_planning_routes(
    application: FastAPI,
    principal_dependency: Callable[..., Awaitable[Principal]],
    context_provider: Callable[[Request], PlanningApiContext],
) -> None:
    principal_dep = Depends(principal_dependency)
    router = APIRouter(prefix="/api/v1", tags=["planning"], route_class=BoundedTargetRoute)

    def authorized(
        request: Request, principal: Principal, *, targets: bool = False, write: bool = False
    ) -> application_planning.PlanningService:
        context = context_provider(request)
        scopes = [Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ]
        if targets:
            scopes.append(Scope.TARGETS_READ)
        if write:
            scopes.append(Scope.PLANS_WRITE)
        for scope in scopes:
            Authorizer().require_scope(principal, scope, now=context.clock())
        if context.planning_service is None:
            raise application_planning.PlanningServiceError(
                application_planning.PlanningServiceErrorCode.PLANNING_UNAVAILABLE,
                "Planning persistence is unavailable.",
            )
        return context.planning_service

    async def command(
        request: Request, principal: Principal
    ) -> tuple[application_planning.PlanningService, str, str]:
        service = authorized(request, principal, targets=True, write=True)
        context = context_provider(request)
        if getattr(request.state, "authentication_method", None) == AuthenticationMethod.SESSION:
            cookie = request.cookies.get("t212pi_session")
            csrf = request.headers.get("x-csrf-token")
            origin = request.headers.get("origin")
            if (
                not cookie
                or len(cookie) > 2048
                or not csrf
                or len(csrf) > 2048
                or origin not in context.settings.allowed_origins
            ):
                raise AuthenticationError("Session command authentication is required.")
            await context.sessions.validate_csrf(cookie, csrf)
        key = _IDEMPOTENCY.validate_python(request.headers.get("x-idempotency-key"))
        return service, key, request.state.correlation_id

    @router.get(
        "/accounts/{account_id}/actual-vs-target",
        response_model=wire.ActualVsTargetResult,
        operation_id="get_actual_vs_target",
    )
    async def get_actual_vs_target(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.ActualVsTargetQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await authorized(request, principal, targets=True).get_actual_vs_target(
            principal,
            account_id,
            query=application_planning.ActualVsTargetQuery(
                **query.model_dump(exclude={"reporting_currency"}),
                reporting_currency=CurrencyCode(query.reporting_currency),
            ),
        )
        return planning_response(request, value, wire.ActualVsTargetResult, conditional=True)

    @router.get(
        "/accounts/{account_id}/drift",
        response_model=wire.DriftAnalysisResult,
        operation_id="get_drift_analysis",
    )
    async def get_drift_analysis(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.DriftAnalysisQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await authorized(request, principal, targets=True).get_drift_analysis(
            principal,
            account_id,
            query=application_planning.DriftAnalysisQuery(
                **query.model_dump(exclude={"reporting_currency", "basis"}),
                reporting_currency=CurrencyCode(query.reporting_currency),
                basis=DriftBasis(query.basis),
            ),
        )
        return planning_response(request, value, wire.DriftAnalysisResult, conditional=True)

    @router.post(
        "/contribution-plans",
        status_code=202,
        response_model=wire.ContributionPlanJob,
        operation_id="create_contribution_plan",
    )
    async def create_contribution_plan(
        request: Request,
        body: wire.CreateContributionPlanRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        service, key, correlation = await command(request, principal)
        value = await service.create_contribution_plan(
            principal, planning_command(body), idempotency_key=key, correlation_id=correlation
        )
        return planning_response(
            request, value, wire.ContributionPlanJob, status_code=202, etag=value.etag
        )

    @router.get(
        "/contribution-plans",
        response_model=wire.ContributionPlanPage,
        operation_id="list_contribution_plans",
    )
    async def list_contribution_plans(
        request: Request,
        query: Annotated[wire.ContributionPlanQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await authorized(request, principal).list_contribution_plans(
            principal,
            query=application_planning.ContributionPlanQuery(
                **query.model_dump(exclude={"state", "outcome"}),
                state=application_planning.PlanJobState(query.state) if query.state else None,
                outcome=PlanOutcome(query.outcome) if query.outcome else None,
            ),
        )
        return planning_response(request, value, wire.ContributionPlanPage)

    @router.get(
        "/contribution-plans/{plan_id}",
        response_model=wire.ContributionPlanDetail,
        operation_id="get_contribution_plan",
    )
    async def get_contribution_plan(
        request: Request,
        plan_id: UUIDString,
        query: Annotated[wire.ContributionPlanDetailQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await authorized(request, principal).get_contribution_plan(
            principal,
            plan_id,
            query=application_planning.ContributionPlanDetailQuery(**query.model_dump()),
        )
        # A page includes current job/request metadata, so its validator binds the
        # complete representation, not only the immutable full-result digest.
        return planning_response(request, value, wire.ContributionPlanDetail, conditional=True)

    @router.post(
        "/contribution-plans/{plan_id}/revisions",
        status_code=202,
        response_model=wire.ContributionPlanJob,
        operation_id="create_contribution_plan_revision",
    )
    async def create_contribution_plan_revision(
        request: Request,
        plan_id: UUIDString,
        body: wire.CreateContributionPlanRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        service, key, correlation = await command(request, principal)
        value = await service.create_contribution_plan_revision(
            principal,
            plan_id,
            planning_command(body),
            if_match=request.headers.get("if-match"),
            idempotency_key=key,
            correlation_id=correlation,
        )
        return planning_response(
            request, value, wire.ContributionPlanJob, status_code=202, etag=value.etag
        )

    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        parameters: list[dict[str, object]] = []
        if "POST" in (route.methods or set()):
            parameters.extend(
                [
                    {
                        "name": "X-Idempotency-Key",
                        "in": "header",
                        "required": True,
                        "schema": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 180,
                            "pattern": r"^[A-Za-z0-9._:-]+$",
                        },
                    },
                    {
                        "name": "X-CSRF-Token",
                        "in": "header",
                        "required": False,
                        "description": (
                            "Required with a session cookie and configured trusted Origin."
                        ),
                        "schema": {"type": "string", "maxLength": 2048},
                    },
                ]
            )
            if route.operation_id == "create_contribution_plan_revision":
                parameters.append(
                    {
                        "name": "If-Match",
                        "in": "header",
                        "required": False,
                        "description": (
                            "Strong plan revision ETag required for a new command; "
                            "an authorized exact replay resolves first."
                        ),
                        "schema": {"type": "string", "maxLength": 2048},
                    }
                )
        elif route.operation_id == "get_contribution_plan":
            parameters.append(
                {
                    "name": "If-None-Match",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string", "maxLength": 2048},
                }
            )
        route.openapi_extra = {"parameters": parameters}
    application.include_router(router)
