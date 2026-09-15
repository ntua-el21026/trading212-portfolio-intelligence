"""Three private report operations with exact scopes and no artifact grant capability."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError
from trading212_api_contracts import reports as wire
from trading212_application import reports as application
from trading212_application.queries import CollectionSnapshotCapacityError, CursorValidationError
from trading212_domain import reports as domain
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.serialization import to_primitive
from trading212_domain.values import CurrencyCode
from trading212_security.principals import (
    AuthenticationError,
    AuthorizationError,
    Authorizer,
    Principal,
    Scope,
)

from .auth import PrincipalResolver
from .gateway import _correlation_id
from .report_schemas import (
    GenerateReportToolResult,
    ReportListToolResult,
    ReportStatusToolResult,
    ReportToolEnvelope,
    ReportToolError,
    ReportToolPagination,
)

MAX_REPORT_INPUT_BYTES = 64 * 1024
MAX_REPORT_OUTPUT_BYTES = 2 * 1024 * 1024


class ReportMcpGateway:
    def __init__(
        self,
        *,
        service: application.ReportService | None,
        principals: PrincipalResolver,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._principals = principals
        self._clock = clock or (lambda: datetime.now(UTC))
        self._logger = logging.getLogger("trading212_mcp.audit")

    async def get_report_status(
        self, account_id: str, report_job_id: str, *, context: Context[Any, Any]
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: application.ReportService
        ) -> ReportStatusToolResult:
            value = await service.get_report_status(
                principal, UUID(account_id), UUID(report_job_id)
            )
            data = _payload(value, wire.ReportJobStatus)
            _account(data.account_id, account_id)
            if data.job_id != report_job_id:
                raise _InvalidResult()
            return ReportStatusToolResult(data=data, pagination=None, error=None)

        return await self._execute(
            "get_report_status",
            account_id,
            {"account_id": account_id, "report_job_id": report_job_id},
            context,
            ReportStatusToolResult,
            operation,
        )

    async def list_reports(
        self, query: wire.ReportListQuery, *, context: Context[Any, Any]
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: application.ReportService
        ) -> ReportListToolResult:
            value = await service.list_reports(
                principal,
                UUID(query.account_id),
                query=application.ReportListQuery(
                    limit=query.limit,
                    cursor=query.cursor,
                    state=domain.ReportJobState(query.state) if query.state != "all" else None,
                    report_type=domain.ReportType(query.report_type)
                    if query.report_type != "all"
                    else None,
                    sort=query.sort,
                ),
            )
            data = _payload(value, wire.ReportPage)
            for item in data.items:
                _account(item.account_id, query.account_id)
            return ReportListToolResult(
                data=data,
                pagination=ReportToolPagination(
                    next_cursor=data.next_cursor,
                    limit=data.limit,
                    total=data.total,
                    returned=len(data.items),
                    truncated=data.next_cursor is not None,
                ),
                error=None,
            )

        return await self._execute(
            "list_reports",
            query.account_id,
            query.model_dump(mode="json"),
            context,
            ReportListToolResult,
            operation,
        )

    async def generate_portfolio_report(
        self, request: wire.McpGenerateReportRequest, *, context: Context[Any, Any]
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: application.ReportService
        ) -> GenerateReportToolResult:
            value = await service.generate_report(principal, report_command(request))
            data = _payload(value, wire.ReportJobStatus)
            _account(data.account_id, request.account_id)
            if data.report_type != request.report_type or data.formats != [request.format]:
                raise _InvalidResult()
            if data.context is not None and (
                data.context.snapshot_id != request.snapshot_id
                or data.context.source_cutoff_at != request.source_cutoff_at
                or data.context.reporting_currency != request.reporting_currency
            ):
                raise _InvalidResult()
            return GenerateReportToolResult(data=data, pagination=None, error=None)

        return await self._execute(
            "generate_portfolio_report",
            request.account_id,
            request.model_dump(mode="json"),
            context,
            GenerateReportToolResult,
            operation,
            write=True,
        )

    async def _execute[T: ReportToolEnvelope[Any]](
        self,
        name: str,
        account_id: str,
        arguments: dict[str, Any],
        context: Context[Any, Any],
        result_type: type[T],
        operation: Callable[[Principal, application.ReportService], Awaitable[T]],
        *,
        write: bool = False,
    ) -> CallToolResult:
        correlation = _correlation_id(context)
        outcome = "INTERNAL_ERROR"
        try:
            principal = await self._principals.resolve()
            scopes = (
                (
                    Scope.PORTFOLIO_READ,
                    Scope.ANALYTICS_READ,
                    Scope.REPORTS_WRITE,
                    Scope.ACTIVITY_READ,
                    Scope.TARGETS_READ,
                )
                if write
                else (Scope.PORTFOLIO_READ, Scope.REPORTS_READ)
            )
            for scope in scopes:
                Authorizer().require_scope(principal, scope, now=self._clock())
            if (
                len(json.dumps(arguments, ensure_ascii=False).encode("utf-8"))
                > MAX_REPORT_INPUT_BYTES
            ):
                raise _InputTooLarge()
            if self._service is None:
                raise application.ReportServiceError(
                    application.ReportServiceErrorCode.REPORT_UNAVAILABLE,
                    "Private report services are unavailable.",
                    retryable=True,
                )
            result = await operation(principal, self._service)
            response = CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text="Saved an authorized private report request."
                        if write
                        else "Retrieved authorized private report metadata.",
                    )
                ],
                structured_content=result.model_dump(mode="json"),
                _meta={"correlationId": correlation},
                is_error=False,
            )
            if (
                len(response.model_dump_json(by_alias=True).encode("utf-8"))
                > MAX_REPORT_OUTPUT_BYTES
            ):
                raise _OutputTooLarge()
            outcome = "success"
            return response
        except Exception as exc:
            error = _safe_error(exc, correlation)
            outcome = error.code
            result = result_type.model_validate(
                {"data": None, "pagination": None, "error": error.model_dump(mode="json")}
            )
            return CallToolResult(
                content=[TextContent(type="text", text=f"{error.code}: {error.message}")],
                structured_content=result.model_dump(mode="json"),
                _meta={"correlationId": correlation},
                is_error=True,
            )
        finally:
            self._logger.info(
                "mcp_report tool=%s outcome=%s account_ref=%s correlation_ref=%s",
                name,
                outcome,
                _reference(account_id),
                _reference(correlation),
            )


def _payload[T: wire.ReportSchema](value: object, schema: type[T]) -> T:
    try:
        if schema is wire.ReportManifest:
            from trading212_domain.report_manifest import encode_report_manifest
            from trading212_domain.reports import ReportManifest

            if not isinstance(value, ReportManifest):
                raise TypeError
            return schema.model_validate_json(encode_report_manifest(value))
        return schema.model_validate(to_primitive(value))
    except (KeyError, TypeError, ValueError):
        raise _InvalidResult() from None


def _account(actual: str, expected: str) -> None:
    if actual != expected:
        raise _InvalidResult()


def _reference(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def report_command(value: wire.McpGenerateReportRequest) -> application.GenerateReportCommand:
    return application.GenerateReportCommand(
        selection=application.ReportSelection(
            account_id=UUID(value.account_id),
            start_date=value.start_date,
            end_date=value.end_date,
            source_cutoff_at=value.source_cutoff_at,
            snapshot_id=UUID(value.snapshot_id),
            reporting_currency=CurrencyCode(value.reporting_currency),
            report_type=domain.ReportType(value.report_type),
            sections=tuple(domain.ReportSection(item) for item in value.sections),
            formats=(domain.ReportFormat(value.format),),
            target_version_id=UUID(value.target_version_id) if value.target_version_id else None,
            xray_run_id=UUID(value.xray_run_id) if value.xray_run_id else None,
            plan_revision_id=UUID(value.plan_revision_id) if value.plan_revision_id else None,
            benchmark_version_id=UUID(value.benchmark_version_id)
            if value.benchmark_version_id
            else None,
            constituent_snapshot_id=UUID(value.constituent_snapshot_id)
            if value.constituent_snapshot_id
            else None,
        ),
        idempotency_key=value.idempotency_key,
    )


class _InvalidResult(Exception):
    pass


class _InputTooLarge(ValueError):
    pass


class _OutputTooLarge(ValueError):
    pass


def _safe_error(exc: Exception, correlation: str) -> ReportToolError:
    code: Any = "INTERNAL_ERROR"
    message = "The private report operation could not complete."
    retryable = False
    if isinstance(exc, AuthenticationError):
        code, message = "AUTHENTICATION_REQUIRED", "Authentication is required."
    elif isinstance(exc, AuthorizationError):
        code, message = "ACCESS_DENIED", "Required report scopes are missing."
    elif isinstance(exc, CursorValidationError):
        code, message = "CURSOR_INVALID", "The scoped pagination cursor is invalid."
    elif isinstance(exc, CollectionSnapshotCapacityError):
        code, message, retryable = (
            "COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED",
            "Active pagination capacity is exhausted.",
            True,
        )
    elif isinstance(exc, _InputTooLarge):
        code, message = "REQUEST_TOO_LARGE", "The report request exceeds its byte bound."
    elif isinstance(exc, _OutputTooLarge):
        code, message = "RESULT_TOO_LARGE", "The report result exceeds its byte bound."
    elif isinstance(exc, application.ReportServiceError):
        code = {
            "INPUT_BOUND_EXCEEDED": "RESULT_TOO_LARGE",
            "CONFLICT": "IDEMPOTENCY_KEY_REUSED",
        }.get(exc.code.value, exc.code.value)
        message = {
            "NOT_FOUND": "The requested private report resource was not found.",
            "ACCESS_DENIED": "Access to the report resource is denied.",
            "VALIDATION_FAILED": "The bounded report request is invalid.",
            "RESULT_TOO_LARGE": "The report exceeds its supported resource bounds.",
            "IDEMPOTENCY_KEY_REUSED": "The idempotency identity belongs to a different request.",
            "INVALID_STATE_TRANSITION": "The report state does not permit this operation.",
            "RATE_LIMITED": "The private report request reached its configured rate limit.",
            "ARTIFACT_EXPIRED": "The private artifact has expired.",
            "REPORT_UNAVAILABLE": "Private reports are temporarily unavailable.",
            "JOB_DISPATCH_UNAVAILABLE": "Private report dispatch is temporarily unavailable.",
        }[code]
        retryable = code == "RATE_LIMITED" or exc.retryable
    elif isinstance(exc, DomainError):
        code = (
            "RESULT_TOO_LARGE"
            if exc.code == ErrorCode.INPUT_BOUND_EXCEEDED
            else "VALIDATION_FAILED"
        )
        message = "The bounded report request is invalid."
    elif isinstance(exc, ValueError) and not isinstance(exc, ValidationError):
        code, message = "VALIDATION_FAILED", "The bounded report request is invalid."
    return ReportToolError(
        code=code,
        message=message,
        correlation_id=correlation,
        retryable=retryable,
        remediation={
            "INVALID_STATE_TRANSITION": "Check job status before requesting completed resources.",
            "RATE_LIMITED": "Wait five minutes before retrying the same operation.",
        }.get(
            code,
            "Use authorized immutable inputs and the same idempotency key "
            "when retrying an identical request.",
        ),
    )
