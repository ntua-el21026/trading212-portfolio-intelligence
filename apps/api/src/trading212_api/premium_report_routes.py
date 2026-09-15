"""Six fixed V2 report routes over the version-scoped shared report service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime
from typing import Annotated, Any, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import TypeAdapter, ValidationError
from trading212_api_contracts import premium_reports as wire
from trading212_api_contracts.reports import ArtifactToken
from trading212_api_contracts.targets import IdempotencyKey, UUIDString
from trading212_application import reports as application_reports
from trading212_domain import reports as domain
from trading212_observability import AuthenticationMethod
from trading212_security.principals import AuthenticationError, Authorizer, Principal, Scope
from trading212_security.sessions import SessionManager
from trading212_security.settings import SecuritySettings

from .premium_report_schemas import report_command, report_response
from .report_routes import BoundedReportRoute
from .report_schemas import report_artifact_response
from .target_routes import _error

_IDEMPOTENCY = TypeAdapter(IdempotencyKey)
_GRANT = TypeAdapter(ArtifactToken)


class PremiumReportApiContext(Protocol):
    @property
    def premium_report_service(self) -> application_reports.ReportService | None: ...
    @property
    def settings(self) -> SecuritySettings: ...
    @property
    def sessions(self) -> SessionManager: ...
    @property
    def clock(self) -> Callable[[], datetime]: ...


def register_premium_report_routes(
    application: FastAPI,
    principal_dependency: Callable[[Request], Awaitable[Principal]],
    context_provider: Callable[[Request], PremiumReportApiContext],
) -> None:
    class AuthorizedPremiumReportRoute(BoundedReportRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def authorized(request: Request) -> Response:
                # Authentication, base scopes and CSRF precede body streaming/parsing.
                context = context_provider(request)
                principal = await principal_dependency(request)
                create = self.operation_id == "generate_premium_portfolio_report"
                for scope in (
                    Scope.PORTFOLIO_READ,
                    Scope.REPORTS_WRITE if create else Scope.REPORTS_READ,
                    *((Scope.ANALYTICS_READ, Scope.ACTIVITY_READ) if create else ()),
                ):
                    Authorizer().require_scope(principal, scope, now=context.clock())
                for name in (
                    "x-idempotency-key",
                    "x-artifact-grant",
                    "x-csrf-token",
                    "origin",
                    "if-none-match",
                ):
                    if len(request.headers.getlist(name)) > 1:
                        return _error(request, 422, "VALIDATION_FAILED", "The request is invalid.")
                request.state.premium_report_principal = principal
                if request.method == "POST" and (
                    getattr(request.state, "authentication_method", None)
                    == AuthenticationMethod.SESSION
                ):
                    cookie = request.cookies.get("t212pi_session")
                    token = request.headers.get("x-csrf-token")
                    if (
                        not cookie
                        or len(cookie) > 2048
                        or not token
                        or len(token) > 2048
                        or request.headers.get("origin") not in context.settings.allowed_origins
                    ):
                        raise AuthenticationError("Session command authentication is required.")
                    await context.sessions.validate_csrf(cookie, token)
                try:
                    if create:
                        request.state.premium_report_key = _IDEMPOTENCY.validate_python(
                            request.headers.get("x-idempotency-key")
                        )
                    if self.operation_id == "download_premium_report_artifact":
                        request.state.premium_report_grant = _GRANT.validate_python(
                            request.headers.get("x-artifact-grant")
                        )
                except ValidationError:
                    return _error(
                        request, 422, "VALIDATION_FAILED", "The bounded report request is invalid."
                    )
                return await handler(request)

            return authorized

    async def principal_from_request(request: Request) -> Principal:
        principal = request.state.premium_report_principal
        if not isinstance(principal, Principal):
            raise AuthenticationError("Authentication is required.")
        return principal

    principal_dep = Depends(principal_from_request)
    router = APIRouter(
        prefix="/api/v2", tags=["premium-reports"], route_class=AuthorizedPremiumReportRoute
    )

    def service(request: Request) -> application_reports.ReportService:
        reports = context_provider(request).premium_report_service
        if reports is None:
            raise application_reports.ReportServiceError(
                application_reports.ReportServiceErrorCode.REPORT_UNAVAILABLE,
                "Private reports are unavailable.",
                retryable=True,
            )
        return reports

    def section_scopes(request: Request, principal: Principal, sections: set[str]) -> None:
        now = context_provider(request).clock()
        if sections & {"targets", "drift", "contribution_plan"}:
            Authorizer().require_scope(principal, Scope.TARGETS_READ, now=now)
        if sections & {"income", "cash_flows", "activity"}:
            Authorizer().require_scope(principal, Scope.ACTIVITY_READ, now=now)

    @router.post(
        "/report-jobs",
        status_code=202,
        response_model=wire.ReportJobStatus,
        operation_id="generate_premium_portfolio_report",
    )
    async def generate_premium_portfolio_report(
        request: Request, body: wire.GenerateReportRequest, principal: Principal = principal_dep
    ) -> Response:
        reports = service(request)
        section_scopes(request, principal, set(body.sections))
        key = request.state.premium_report_key
        result = await reports.generate_report(principal, report_command(body, key))
        return report_response(request, result, wire.ReportJobStatus, status_code=202)

    @router.get(
        "/report-jobs/{job_id}",
        response_model=wire.ReportJobStatus,
        operation_id="get_premium_report_status",
    )
    async def get_premium_report_status(
        request: Request,
        job_id: UUIDString,
        query: Annotated[wire.ReportAccountQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        result = await service(request).get_report_status(
            principal, UUID(query.account_id), UUID(job_id)
        )
        return report_response(request, result, wire.ReportJobStatus, conditional=True)

    @router.get("/reports", response_model=wire.ReportPage, operation_id="list_premium_reports")
    async def list_premium_reports(
        request: Request,
        query: Annotated[wire.ReportListQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        result = await service(request).list_reports(
            principal,
            UUID(query.account_id),
            query=application_reports.ReportListQuery(
                limit=query.limit,
                cursor=query.cursor,
                state=domain.ReportJobState(query.state) if query.state != "all" else None,
                report_type=domain.ReportType(query.report_type)
                if query.report_type != "all"
                else None,
                start_date=query.start_date,
                end_date=query.end_date,
                sort=query.sort,
            ),
        )
        return report_response(request, result, wire.ReportPage, conditional=True)

    @router.get(
        "/reports/{report_id}",
        response_model=wire.ReportManifest,
        operation_id="get_premium_report_manifest",
    )
    async def get_premium_report_manifest(
        request: Request,
        report_id: UUIDString,
        query: Annotated[wire.ReportAccountQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        result = await service(request).get_report_manifest(
            principal, UUID(query.account_id), UUID(report_id)
        )
        return report_response(request, result, wire.ReportManifest, conditional=True)

    @router.post(
        "/reports/{report_id}/artifacts/{artifact_id}/grants",
        status_code=201,
        response_model=wire.ArtifactGrant,
        operation_id="create_premium_report_download_grant",
    )
    async def create_premium_report_download_grant(
        request: Request,
        report_id: UUIDString,
        artifact_id: UUIDString,
        body: wire.EmptyReportRequest,
        query: Annotated[wire.ReportAccountQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        reports = service(request)
        result = await reports.create_report_download_grant(
            principal, UUID(query.account_id), UUID(report_id), UUID(artifact_id)
        )
        return report_response(request, result, wire.ArtifactGrant, status_code=201)

    content_responses: dict[int | str, dict[str, Any]] = {
        200: {
            "description": "A verified private artifact of at most 10 MiB.",
            "content": {
                mime: {"schema": {"type": "string", "format": "binary"}}
                for mime in (
                    "application/pdf",
                    "text/csv; charset=utf-8",
                    "application/json",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        }
    }

    @router.get(
        "/reports/{report_id}/artifacts/{artifact_id}/content",
        response_class=Response,
        responses=content_responses,
        operation_id="download_premium_report_artifact",
    )
    async def download_premium_report_artifact(
        request: Request,
        report_id: UUIDString,
        artifact_id: UUIDString,
        query: Annotated[wire.ReportAccountQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        reports = service(request)
        token = request.state.premium_report_grant
        result = await reports.download_report_artifact(
            principal, UUID(query.account_id), UUID(report_id), UUID(artifact_id), grant_token=token
        )
        return report_artifact_response(request, result, artifact_id=UUID(artifact_id))

    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        parameters: list[dict[str, Any]] = []
        if "POST" in (route.methods or set()):
            parameters.append(
                {
                    "name": "X-CSRF-Token",
                    "in": "header",
                    "required": False,
                    "description": "Required with a session cookie and configured trusted Origin.",
                    "schema": {"type": "string", "maxLength": 2048},
                }
            )
            if route.operation_id in {"generate_premium_portfolio_report"}:
                parameters.append(
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
                    }
                )
        elif route.operation_id in {"download_premium_report_artifact"}:
            parameters.append(
                {
                    "name": "X-Artifact-Grant",
                    "in": "header",
                    "required": True,
                    "description": (
                        "Short-lived supplementary grant; ordinary authentication remains required."
                    ),
                    "schema": {
                        "type": "string",
                        "minLength": 32,
                        "maxLength": 512,
                        "pattern": r"^[A-Za-z0-9_-]+$",
                    },
                }
            )
        else:
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
