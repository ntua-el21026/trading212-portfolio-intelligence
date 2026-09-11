"""Eleven bounded report/export operations over the shared authorized service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime
from typing import Annotated, Any, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import TypeAdapter, ValidationError
from starlette.responses import JSONResponse
from trading212_api_contracts import reports as wire
from trading212_api_contracts.targets import IdempotencyKey, UUIDString
from trading212_application import reports as application_reports
from trading212_domain import reports as domain
from trading212_domain.errors import DomainError, ErrorCode
from trading212_observability import AuthenticationMethod
from trading212_security.principals import AuthenticationError, Authorizer, Principal, Scope
from trading212_security.sessions import SessionManager
from trading212_security.settings import SecuritySettings

from .report_schemas import (
    export_command,
    report_artifact_response,
    report_command,
    report_response,
)
from .target_routes import BoundedTargetRoute, _error

_IDEMPOTENCY = TypeAdapter(IdempotencyKey)
_GRANT = TypeAdapter(wire.ArtifactToken)
_ERRORS = {
    "NOT_FOUND": (404, "The private report resource was not found."),
    "ACCESS_DENIED": (403, "Access to the private report resource is denied."),
    "VALIDATION_FAILED": (422, "The bounded report request is invalid."),
    "RESULT_TOO_LARGE": (422, "The report exceeds its supported resource bounds."),
    "IDEMPOTENCY_KEY_REUSED": (409, "The idempotency identity belongs to a different request."),
    "INVALID_STATE_TRANSITION": (409, "The report state does not permit this operation."),
    "RATE_LIMITED": (429, "The private report request reached its configured rate limit."),
    "ARTIFACT_EXPIRED": (410, "The private artifact has expired."),
    "REPORT_UNAVAILABLE": (503, "Private reports are temporarily unavailable."),
    "JOB_DISPATCH_UNAVAILABLE": (503, "Private report dispatch is temporarily unavailable."),
}


class ReportApiContext(Protocol):
    @property
    def report_service(self) -> application_reports.ReportService | None: ...

    @property
    def settings(self) -> SecuritySettings: ...

    @property
    def sessions(self) -> SessionManager: ...

    @property
    def clock(self) -> Callable[[], datetime]: ...


class BoundedReportRoute(BoundedTargetRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def checked(request: Request) -> Response:
            for header in ("x-idempotency-key", "x-artifact-grant", "x-csrf-token", "origin"):
                if len(request.headers.getlist(header)) > 1:
                    return _error(request, 422, "VALIDATION_FAILED", "The request is invalid.")
            try:
                return await handler(request)
            except application_reports.ReportServiceError as exc:
                code = {
                    "INPUT_BOUND_EXCEEDED": "RESULT_TOO_LARGE",
                    "CONFLICT": "IDEMPOTENCY_KEY_REUSED",
                }.get(exc.code.value, exc.code.value)
                response_status, message = _ERRORS.get(
                    code, (500, "The private report operation could not complete.")
                )
                if code not in _ERRORS:
                    code = "INTERNAL_ERROR"
                headers = {
                    "Cache-Control": "private, no-store",
                    "X-Content-Type-Options": "nosniff",
                }
                if code == "RATE_LIMITED":
                    # Grant lifetimes are at most five minutes; the additional
                    # owner issuance window is one minute. No private timestamps
                    # or token identities are needed for this conservative delay.
                    headers["Retry-After"] = "300"
                return JSONResponse(
                    status_code=response_status,
                    content={
                        "error": {
                            "code": code,
                            "message": message,
                            "correlation_id": getattr(
                                request.state, "correlation_id", "unavailable"
                            ),
                            "retryable": code == "RATE_LIMITED" or exc.retryable,
                            "details": {},
                        }
                    },
                    headers=headers,
                )
            except DomainError as exc:
                code = (
                    "RESULT_TOO_LARGE"
                    if exc.code == ErrorCode.INPUT_BOUND_EXCEEDED
                    else "VALIDATION_FAILED"
                )
                return _error(request, 422, code, _ERRORS[code][1])
            except ValidationError:
                return _error(
                    request, 422, "VALIDATION_FAILED", "The bounded report request is invalid."
                )

        return checked


def register_report_routes(
    application: FastAPI,
    principal_dependency: Callable[..., Awaitable[Principal]],
    context_provider: Callable[[Request], ReportApiContext],
) -> None:
    principal_dep = Depends(principal_dependency)
    router = APIRouter(prefix="/api/v1", tags=["reports"], route_class=BoundedReportRoute)

    def service(
        request: Request, principal: Principal, *, write: bool = False
    ) -> application_reports.ReportService:
        context = context_provider(request)
        for scope in (
            Scope.PORTFOLIO_READ,
            Scope.REPORTS_WRITE if write else Scope.REPORTS_READ,
            *((Scope.ANALYTICS_READ,) if write else ()),
        ):
            Authorizer().require_scope(principal, scope, now=context.clock())
        if context.report_service is None:
            raise application_reports.ReportServiceError(
                application_reports.ReportServiceErrorCode.REPORT_UNAVAILABLE,
                "Private reports are unavailable.",
                retryable=True,
            )
        return context.report_service

    def section_scopes(request: Request, principal: Principal, sections: set[str]) -> None:
        now = context_provider(request).clock()
        if sections & {"targets", "drift", "contribution_plan"}:
            Authorizer().require_scope(principal, Scope.TARGETS_READ, now=now)
        if sections & {"income", "cash_flows", "activity"}:
            Authorizer().require_scope(principal, Scope.ACTIVITY_READ, now=now)

    async def csrf(request: Request) -> None:
        context = context_provider(request)
        if getattr(request.state, "authentication_method", None) == AuthenticationMethod.SESSION:
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

    @router.post(
        "/report-jobs",
        status_code=202,
        response_model=wire.ReportJobStatus,
        operation_id="generate_portfolio_report",
    )
    async def generate_portfolio_report(
        request: Request, body: wire.GenerateReportRequest, principal: Principal = principal_dep
    ) -> Response:
        reports = service(request, principal, write=True)
        await csrf(request)
        section_scopes(request, principal, set(body.sections))
        key = _IDEMPOTENCY.validate_python(request.headers.get("x-idempotency-key"))
        result = await reports.generate_report(principal, report_command(body, key))
        return report_response(request, result, wire.ReportJobStatus, status_code=202)

    @router.get(
        "/report-jobs/{job_id}",
        response_model=wire.ReportJobStatus,
        operation_id="get_report_status",
    )
    async def get_report_status(
        request: Request,
        job_id: UUIDString,
        query: Annotated[wire.ReportAccountQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        result = await service(request, principal).get_report_status(
            principal, UUID(query.account_id), UUID(job_id)
        )
        return report_response(request, result, wire.ReportJobStatus, conditional=True)

    @router.get("/reports", response_model=wire.ReportPage, operation_id="list_reports")
    async def list_reports(
        request: Request,
        query: Annotated[wire.ReportListQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        result = await service(request, principal).list_reports(
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
        operation_id="get_report_manifest",
    )
    async def get_report_manifest(
        request: Request,
        report_id: UUIDString,
        query: Annotated[wire.ReportAccountQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        result = await service(request, principal).get_report_manifest(
            principal, UUID(query.account_id), UUID(report_id)
        )
        return report_response(request, result, wire.ReportManifest, conditional=True)

    @router.post(
        "/reports/{report_id}/artifacts/{artifact_id}/grants",
        status_code=201,
        response_model=wire.ArtifactGrant,
        operation_id="create_report_download_grant",
    )
    async def create_report_download_grant(
        request: Request,
        report_id: UUIDString,
        artifact_id: UUIDString,
        body: wire.EmptyReportRequest,
        query: Annotated[wire.ReportAccountQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        reports = service(request, principal)
        await csrf(request)
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
        operation_id="download_report_artifact",
    )
    async def download_report_artifact(
        request: Request,
        report_id: UUIDString,
        artifact_id: UUIDString,
        query: Annotated[wire.ReportAccountQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        reports = service(request, principal)
        token = _GRANT.validate_python(request.headers.get("x-artifact-grant"))
        result = await reports.download_report_artifact(
            principal, UUID(query.account_id), UUID(report_id), UUID(artifact_id), grant_token=token
        )
        return report_artifact_response(request, result, artifact_id=UUID(artifact_id))

    @router.post(
        "/exports",
        status_code=202,
        response_model=wire.ExportJobStatus,
        operation_id="create_portfolio_export",
    )
    async def create_portfolio_export(
        request: Request, body: wire.CreateExportRequest, principal: Principal = principal_dep
    ) -> Response:
        reports = service(request, principal, write=True)
        await csrf(request)
        sections = {"targets"} if body.dataset in {"targets", "plans"} else set()
        if body.dataset in {"activity", "dividends"}:
            sections.add("activity")
        section_scopes(request, principal, sections)
        if body.dataset == "alerts":
            Authorizer().require_scope(
                principal, Scope.ALERTS_READ, now=context_provider(request).clock()
            )
        key = _IDEMPOTENCY.validate_python(request.headers.get("x-idempotency-key"))
        result = await reports.create_export(principal, export_command(body, key))
        return report_response(request, result, wire.ExportJobStatus, status_code=202)

    @router.get("/exports", response_model=wire.ExportPage, operation_id="list_portfolio_exports")
    async def list_portfolio_exports(
        request: Request,
        query: Annotated[wire.ExportListQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        result = await service(request, principal).list_exports(
            principal,
            UUID(query.account_id),
            query=application_reports.ExportListQuery(
                limit=query.limit,
                cursor=query.cursor,
                state=domain.ReportJobState(query.state) if query.state != "all" else None,
                dataset=domain.ExportDataset(query.dataset) if query.dataset != "all" else None,
                sort=query.sort,
            ),
        )
        return report_response(request, result, wire.ExportPage, conditional=True)

    @router.get(
        "/exports/{export_id}",
        response_model=wire.ExportJobStatus,
        operation_id="get_export_status",
    )
    async def get_export_status(
        request: Request,
        export_id: UUIDString,
        query: Annotated[wire.ReportAccountQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        result = await service(request, principal).get_export_status(
            principal, UUID(query.account_id), UUID(export_id)
        )
        return report_response(request, result, wire.ExportJobStatus, conditional=True)

    @router.post(
        "/exports/{export_id}/artifacts/{artifact_id}/grants",
        status_code=201,
        response_model=wire.ArtifactGrant,
        operation_id="create_export_download_grant",
    )
    async def create_export_download_grant(
        request: Request,
        export_id: UUIDString,
        artifact_id: UUIDString,
        body: wire.EmptyReportRequest,
        query: Annotated[wire.ReportAccountQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        reports = service(request, principal)
        await csrf(request)
        result = await reports.create_export_download_grant(
            principal, UUID(query.account_id), UUID(export_id), UUID(artifact_id)
        )
        return report_response(request, result, wire.ArtifactGrant, status_code=201)

    @router.get(
        "/exports/{export_id}/artifacts/{artifact_id}/content",
        response_class=Response,
        responses=content_responses,
        operation_id="download_export_artifact",
    )
    async def download_export_artifact(
        request: Request,
        export_id: UUIDString,
        artifact_id: UUIDString,
        query: Annotated[wire.ReportAccountQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        reports = service(request, principal)
        token = _GRANT.validate_python(request.headers.get("x-artifact-grant"))
        result = await reports.download_export_artifact(
            principal, UUID(query.account_id), UUID(export_id), UUID(artifact_id), grant_token=token
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
            if route.operation_id in {"generate_portfolio_report", "create_portfolio_export"}:
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
        elif route.operation_id in {"download_report_artifact", "download_export_artifact"}:
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
