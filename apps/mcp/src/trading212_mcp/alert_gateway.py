"""Authorized alert WindowPage reads with bounded output and sanitized audit records."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError
from trading212_api_contracts import alerts as wire
from trading212_application import alerts as application
from trading212_application.alert_projection import alert_content
from trading212_application.queries import CollectionSnapshotCapacityError, CursorValidationError
from trading212_domain.errors import DomainError
from trading212_security.principals import (
    AuthenticationError,
    AuthorizationError,
    Authorizer,
    Scope,
)

from .alert_schemas import AlertSummaryToolResult, AlertToolError, AlertToolPagination
from .auth import PrincipalResolver
from .gateway import _correlation_id


class AlertMcpGateway:
    def __init__(
        self,
        *,
        service: application.AlertService | None,
        principals: PrincipalResolver,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._principals = principals
        self._clock = clock or (lambda: datetime.now(UTC))
        self._logger = logging.getLogger("trading212_mcp.audit")

    async def get_alert_summary(
        self, request: wire.McpAlertSummaryRequest, *, context: Context[Any, Any]
    ) -> CallToolResult:
        correlation = _correlation_id(context)
        outcome = "INTERNAL_ERROR"
        try:
            principal = await self._principals.resolve()
            for scope in (Scope.PORTFOLIO_READ, Scope.ALERTS_READ):
                Authorizer().require_scope(principal, scope, now=self._clock())
            if len(request.model_dump_json().encode()) > 64 * 1024:
                raise _InputTooLarge()
            if self._service is None:
                raise application.AlertServiceError(
                    application.AlertServiceErrorCode.ALERTS_UNAVAILABLE, retryable=True
                )
            value = await self._service.get_summary(
                principal,
                UUID(request.account_id),
                query=application.AlertSummaryWindowQuery(
                    start_date=request.start_date,
                    end_date=request.end_date,
                    source_cutoff_at=request.source_cutoff_at,
                    state=application.AlertStateFilter(request.state),
                    severity=application.AlertSeverityFilter(request.severity),
                    cursor=request.cursor,
                    limit=request.limit,
                ),
            )
            try:
                data = wire.AlertSummaryPage.model_validate(alert_content(value))
            except (TypeError, ValueError):
                raise _InvalidResult() from None
            if (
                data.account_id != request.account_id
                or data.source_cutoff_at != request.source_cutoff_at
                or data.page.limit != request.limit
            ):
                raise _InvalidResult()
            result = AlertSummaryToolResult(
                data=data,
                pagination=AlertToolPagination(
                    next_cursor=data.page.next_cursor,
                    limit=data.page.limit,
                    total=data.page.total,
                    returned=len(data.page.items),
                    truncated=data.page.next_cursor is not None,
                ),
                error=None,
            )
            response = CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text="Retrieved authorized alert history and exact filtered counts.",
                    )
                ],
                structured_content=result.model_dump(mode="json"),
                _meta={"correlationId": correlation},
                is_error=False,
            )
            if len(response.model_dump_json(by_alias=True).encode()) > 2 * 1024 * 1024:
                raise _OutputTooLarge()
            outcome = "success"
            return response
        except Exception as exc:
            error = _safe_error(exc, correlation)
            outcome = error.code
            result = AlertSummaryToolResult(data=None, pagination=None, error=error)
            return CallToolResult(
                content=[TextContent(type="text", text=f"{error.code}: {error.message}")],
                structured_content=result.model_dump(mode="json"),
                _meta={"correlationId": correlation},
                is_error=True,
            )
        finally:
            self._logger.info(
                "mcp_alert tool=get_alert_summary outcome=%s account_ref=%s correlation_ref=%s",
                outcome,
                hashlib.sha256(request.account_id.encode()).hexdigest()[:16],
                hashlib.sha256(correlation.encode()).hexdigest()[:16],
            )


class _InputTooLarge(ValueError):
    pass


class _OutputTooLarge(ValueError):
    pass


class _InvalidResult(ValueError):
    pass


def _safe_error(exc: Exception, correlation: str) -> AlertToolError:
    code: Any = "INTERNAL_ERROR"
    message = "The alert summary could not be read."
    retryable = False
    if isinstance(exc, AuthenticationError):
        code, message = "AUTHENTICATION_REQUIRED", "Authentication is required."
    elif isinstance(exc, AuthorizationError):
        code, message = "ACCESS_DENIED", "Required alert scopes are missing."
    elif isinstance(exc, CursorValidationError):
        code, message = "CURSOR_INVALID", "The scoped pagination cursor is invalid."
    elif isinstance(exc, CollectionSnapshotCapacityError):
        code, message, retryable = (
            "COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED",
            "The durable page capacity is currently exhausted.",
            True,
        )
    elif isinstance(exc, _InputTooLarge):
        code, message = "REQUEST_TOO_LARGE", "The alert request exceeds its byte bound."
    elif isinstance(exc, _OutputTooLarge):
        code, message = "RESULT_TOO_LARGE", "The alert result exceeds its byte bound."
    elif isinstance(exc, application.AlertServiceError):
        code = {"INPUT_BOUND_EXCEEDED": "RESULT_TOO_LARGE"}.get(exc.code.value, exc.code.value)
        allowed = {
            "NOT_FOUND",
            "ACCESS_DENIED",
            "VALIDATION_FAILED",
            "CURRENCY_MISMATCH",
            "CURSOR_INVALID",
            "RESULT_TOO_LARGE",
            "RATE_LIMITED",
            "ALERTS_UNAVAILABLE",
        }
        if code not in allowed:
            code = "INTERNAL_ERROR"
        retryable = exc.retryable if code != "INTERNAL_ERROR" else False
        message = {
            "NOT_FOUND": "The requested alert account or retained history was not found.",
            "ACCESS_DENIED": "Access to the alert history is denied.",
            "VALIDATION_FAILED": "The alert filters are invalid.",
            "CURRENCY_MISMATCH": "The alert currencies do not match.",
            "CURSOR_INVALID": "The scoped pagination cursor is invalid.",
            "RESULT_TOO_LARGE": "The alert result exceeds its byte bound.",
            "RATE_LIMITED": "The alert operation is temporarily rate limited.",
            "ALERTS_UNAVAILABLE": "Alert services are unavailable.",
        }.get(code, message)
    elif isinstance(exc, (ValidationError, DomainError)):
        code, message = "VALIDATION_FAILED", "The alert filters are invalid."
    return AlertToolError(
        code=code,
        message=message,
        correlation_id=correlation,
        retryable=retryable,
        remediation="Check access and the bounded filters, then retry the read.",
    )
