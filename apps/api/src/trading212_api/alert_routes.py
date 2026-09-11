"""Thirteen bounded alert operations over the authorized application service."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime
from typing import Annotated, Any, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import TypeAdapter
from starlette.responses import JSONResponse
from trading212_api_contracts import alerts as wire
from trading212_api_contracts.targets import IdempotencyKey, UUIDString
from trading212_application import alerts as app
from trading212_domain import alerts as domain
from trading212_observability import AuthenticationMethod
from trading212_security.principals import AuthenticationError, Authorizer, Principal, Scope
from trading212_security.sessions import SessionManager
from trading212_security.settings import SecuritySettings

from .alert_schemas import alert_definition, alert_response
from .target_routes import BoundedTargetRoute, _error

_IDEMPOTENCY = TypeAdapter(IdempotencyKey)
_ERRORS = {
    "NOT_FOUND": (404, "The alert resource was not found."),
    "ACCESS_DENIED": (403, "Access to the alert operation is denied."),
    "VALIDATION_FAILED": (422, "The bounded alert request is invalid."),
    "RESULT_TOO_LARGE": (422, "The alert result exceeds its resource bounds."),
    "CURRENCY_MISMATCH": (422, "The alert currency differs from its sourced inputs."),
    "IDEMPOTENCY_KEY_REUSED": (409, "The request identity belongs to a different command."),
    "INVALID_STATE_TRANSITION": (409, "The alert lifecycle does not permit this transition."),
    "IMMUTABLE_VERSION": (409, "Saved rule content is immutable."),
    "SOURCE_REVISION_CONFLICT": (409, "The selected source revision changed."),
    "REVISION_MISMATCH": (412, "The current alert revision differs."),
    "REVISION_REQUIRED": (428, "The current alert revision is required."),
    "CURSOR_INVALID": (400, "The history cursor is invalid or expired."),
    "RATE_LIMITED": (429, "The alert operation reached its configured rate limit."),
    "ALERTS_UNAVAILABLE": (503, "The alert service is temporarily unavailable."),
    "JOB_DISPATCH_UNAVAILABLE": (503, "Alert dispatch is temporarily unavailable."),
}


class AlertApiContext(Protocol):
    @property
    def alert_service(self) -> app.AlertService | None: ...

    @property
    def settings(self) -> SecuritySettings: ...

    @property
    def sessions(self) -> SessionManager: ...

    @property
    def clock(self) -> Callable[[], datetime]: ...


class BoundedAlertRoute(BoundedTargetRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def checked(request: Request) -> Response:
            for name in (
                "x-idempotency-key",
                "if-match",
                "if-none-match",
                "x-csrf-token",
                "origin",
            ):
                if len(request.headers.getlist(name)) > 1:
                    return _error(request, 422, "VALIDATION_FAILED", "The request is invalid.")
            try:
                return await handler(request)
            except app.AlertServiceError as error:
                code = (
                    "RESULT_TOO_LARGE"
                    if error.code.value == "INPUT_BOUND_EXCEEDED"
                    else error.code.value
                )
                status, message = _ERRORS.get(code, (500, "The alert operation failed."))
                headers = {"Cache-Control": "private, no-store"}
                if status == 429:
                    headers["Retry-After"] = "60"
                return JSONResponse(
                    status_code=status,
                    content={
                        "error": {
                            "code": code,
                            "message": message,
                            "correlation_id": getattr(
                                request.state, "correlation_id", "unavailable"
                            ),
                            "retryable": error.retryable,
                            "details": {},
                        }
                    },
                    headers=headers,
                )

        return checked


def _revision(request: Request, identifier: UUID) -> int:
    header = request.headers.get("if-match")
    if header is None:
        raise app.AlertServiceError(app.AlertServiceErrorCode.REVISION_REQUIRED)
    match = re.fullmatch(
        r'"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):([1-9][0-9]{0,18})"',
        header,
    )
    if match is None or int(match[2]) > 2**63 - 1:
        raise app.AlertServiceError(app.AlertServiceErrorCode.VALIDATION_FAILED)
    if UUID(match[1]) != identifier:
        raise app.AlertServiceError(app.AlertServiceErrorCode.REVISION_MISMATCH)
    return int(match[2])


def register_alert_routes(
    application: FastAPI,
    principal_dependency: Callable[..., Awaitable[Principal]],
    context_provider: Callable[[Request], AlertApiContext],
) -> None:
    principal_dep = Depends(principal_dependency)
    router = APIRouter(prefix="/api/v1", tags=["alerts"], route_class=BoundedAlertRoute)

    def service(request: Request, principal: Principal, *, write: bool = False) -> app.AlertService:
        context = context_provider(request)
        for scope in (
            Scope.PORTFOLIO_READ,
            Scope.ALERTS_WRITE if write else Scope.ALERTS_READ,
            *((Scope.ANALYTICS_READ,) if write else ()),
        ):
            Authorizer().require_scope(principal, scope, now=context.clock())
        if context.alert_service is None:
            raise app.AlertServiceError(
                app.AlertServiceErrorCode.ALERTS_UNAVAILABLE, retryable=True
            )
        return context.alert_service

    async def command(request: Request, principal: Principal) -> tuple[app.AlertService, str, str]:
        alerts = service(request, principal, write=True)
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
        return alerts, key, request.state.correlation_id

    @router.get("/alert-rules", response_model=wire.AlertRulePage, operation_id="list_alert_rules")
    async def list_alert_rules(
        request: Request,
        query: Annotated[wire.AlertRuleListQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request, principal).list_rules(
            principal,
            query=app.AlertRuleListQuery(
                account_id=UUID(query.account_id),
                cursor=query.cursor,
                limit=query.limit,
                state=domain.AlertLifecycle(query.state) if query.state != "all" else None,
                family=domain.AlertFamily(query.family) if query.family != "all" else None,
            ),
        )
        return alert_response(request, value, wire.AlertRulePage)

    @router.post(
        "/alert-rules",
        response_model=wire.AlertRuleDetail,
        status_code=201,
        operation_id="create_alert_rule",
    )
    async def create_alert_rule(
        request: Request, body: wire.CreateAlertRuleRequest, principal: Principal = principal_dep
    ) -> Response:
        alerts, key, correlation = await command(request, principal)
        value = await alerts.create_rule(
            principal,
            app.CreateAlertRuleCommand(
                account_id=UUID(body.account_id), definition=alert_definition(body.definition)
            ),
            idempotency_key=key,
            correlation_id=correlation,
        )
        return alert_response(
            request, value, wire.AlertRuleDetail, status_code=201, etag=value.etag
        )

    @router.get(
        "/alert-rules/{rule_id}", response_model=wire.AlertRuleDetail, operation_id="get_alert_rule"
    )
    async def get_alert_rule(
        request: Request,
        rule_id: UUIDString,
        query: Annotated[wire.AlertRuleDetailQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request, principal).get_rule(
            principal,
            UUID(rule_id),
            query=app.AlertRuleDetailQuery(
                evaluation_cursor=query.evaluation_cursor,
                evaluation_limit=query.evaluation_limit,
                version_cursor=query.version_cursor,
                version_limit=query.version_limit,
            ),
        )
        return alert_response(request, value, wire.AlertRuleDetail, etag=value.etag)

    @router.post(
        "/alert-rules/{rule_id}/versions",
        response_model=wire.AlertRuleVersionDetail,
        status_code=201,
        operation_id="create_alert_rule_version",
    )
    async def create_alert_rule_version(
        request: Request,
        rule_id: UUIDString,
        body: wire.AlertRuleVersionRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        alerts, key, correlation = await command(request, principal)
        identifier = UUID(rule_id)
        value = await alerts.create_rule_version(
            principal,
            identifier,
            app.AlertRuleVersionCommand(definition=alert_definition(body.definition)),
            idempotency_key=key,
            expected_revision=_revision(request, identifier),
            correlation_id=correlation,
        )
        return alert_response(
            request,
            value,
            wire.AlertRuleVersionDetail,
            status_code=201,
            etag=f'"{rule_id}:{value.rule_revision}"',
        )

    @router.post(
        "/alert-rules/{rule_id}/activate",
        response_model=wire.AlertRuleDetail,
        operation_id="activate_alert_rule",
    )
    async def activate_alert_rule(
        request: Request,
        rule_id: UUIDString,
        body: wire.ActivateAlertRuleRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        alerts, key, correlation = await command(request, principal)
        identifier = UUID(rule_id)
        value = await alerts.activate_rule(
            principal,
            identifier,
            UUID(body.version_id),
            idempotency_key=key,
            expected_revision=_revision(request, identifier),
            correlation_id=correlation,
        )
        return alert_response(request, value, wire.AlertRuleDetail, etag=value.etag)

    @router.post(
        "/alert-rules/{rule_id}/pause",
        response_model=wire.AlertRuleDetail,
        operation_id="pause_alert_rule",
    )
    async def pause_alert_rule(
        request: Request,
        rule_id: UUIDString,
        body: wire.EmptyAlertRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        alerts, key, correlation = await command(request, principal)
        identifier = UUID(rule_id)
        value = await alerts.pause_rule(
            principal,
            identifier,
            idempotency_key=key,
            expected_revision=_revision(request, identifier),
            correlation_id=correlation,
        )
        return alert_response(request, value, wire.AlertRuleDetail, etag=value.etag)

    @router.post(
        "/alert-rules/{rule_id}/archive",
        response_model=wire.AlertRuleDetail,
        operation_id="archive_alert_rule",
    )
    async def archive_alert_rule(
        request: Request,
        rule_id: UUIDString,
        body: wire.EmptyAlertRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        alerts, key, correlation = await command(request, principal)
        identifier = UUID(rule_id)
        value = await alerts.archive_rule(
            principal,
            identifier,
            idempotency_key=key,
            expected_revision=_revision(request, identifier),
            correlation_id=correlation,
        )
        return alert_response(request, value, wire.AlertRuleDetail, etag=value.etag)

    @router.get(
        "/alert-events", response_model=wire.AlertEventPage, operation_id="list_alert_events"
    )
    async def list_alert_events(
        request: Request,
        query: Annotated[wire.AlertEventListQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request, principal).list_events(
            principal,
            query=app.AlertEventListQuery(
                account_id=UUID(query.account_id),
                rule_id=UUID(query.rule_id) if query.rule_id else None,
                state=app.AlertStateFilter(query.state),
                severity=app.AlertSeverityFilter(query.severity),
                start_date=query.start_date,
                end_date=query.end_date,
                cursor=query.cursor,
                limit=query.limit,
            ),
        )
        return alert_response(request, value, wire.AlertEventPage)

    @router.get(
        "/alert-events/{event_id}",
        response_model=wire.AlertEventDetail,
        operation_id="get_alert_event",
    )
    async def get_alert_event(
        request: Request, event_id: UUIDString, principal: Principal = principal_dep
    ) -> Response:
        value = await service(request, principal).get_event(principal, UUID(event_id))
        return alert_response(request, value, wire.AlertEventDetail, etag=value.etag)

    @router.post(
        "/alert-events/{event_id}/acknowledgments",
        response_model=wire.AlertAcknowledgment,
        status_code=201,
        operation_id="acknowledge_alert_event",
    )
    async def acknowledge_alert_event(
        request: Request,
        event_id: UUIDString,
        body: wire.AlertEventNoteRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        alerts, key, correlation = await command(request, principal)
        identifier = UUID(event_id)
        value = await alerts.acknowledge_event(
            principal,
            identifier,
            note=body.note,
            idempotency_key=key,
            expected_revision=_revision(request, identifier),
            correlation_id=correlation,
        )
        return alert_response(
            request,
            value,
            wire.AlertAcknowledgment,
            status_code=201,
            etag=f'"{event_id}:{value.event_revision}"',
        )

    @router.post(
        "/alert-events/{event_id}/resolve",
        response_model=wire.AlertEventDetail,
        operation_id="resolve_alert_event",
    )
    async def resolve_alert_event(
        request: Request,
        event_id: UUIDString,
        body: wire.AlertEventNoteRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        alerts, key, correlation = await command(request, principal)
        identifier = UUID(event_id)
        value = await alerts.resolve_event(
            principal,
            identifier,
            note=body.note,
            idempotency_key=key,
            expected_revision=_revision(request, identifier),
            correlation_id=correlation,
        )
        return alert_response(request, value, wire.AlertEventDetail, etag=value.etag)

    @router.get(
        "/accounts/{account_id}/alert-summary",
        response_model=wire.AlertSummary,
        operation_id="get_alert_summary",
    )
    async def get_alert_summary(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.AlertSummaryQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request, principal).get_summary(
            principal,
            UUID(account_id),
            query=app.AlertSummaryTopQuery(
                state=app.AlertStateFilter(query.state),
                severity=app.AlertSeverityFilter(query.severity),
                top_n=query.top_n,
            ),
        )
        return alert_response(request, value, wire.AlertSummary)

    @router.get(
        "/notification-destinations",
        response_model=wire.NotificationDestinationPage,
        operation_id="list_notification_destinations",
    )
    async def list_notification_destinations(
        request: Request,
        query: Annotated[wire.NotificationDestinationQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request, principal).list_notification_destinations(
            principal,
            UUID(query.account_id),
            query=app.AlertPageQuery(cursor=query.cursor, limit=query.limit),
        )
        return alert_response(request, value, wire.NotificationDestinationPage)

    for route in router.routes:
        if not isinstance(route, APIRoute) or "POST" not in (route.methods or set()):
            continue
        parameters: list[dict[str, Any]] = [
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
                "description": "Required for session-cookie commands with a trusted Origin.",
                "schema": {"type": "string", "maxLength": 2048},
            },
        ]
        if route.operation_id != "create_alert_rule":
            parameters.append(
                {
                    "name": "If-Match",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string", "maxLength": 2048},
                }
            )
        route.openapi_extra = {"parameters": parameters}
    application.include_router(router)
