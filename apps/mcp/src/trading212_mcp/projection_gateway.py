"""Four authorized projection operations over saved inputs and bounded public pages."""

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
from trading212_api_contracts import projections as wire
from trading212_api_contracts.projection_inputs import ProjectionSchema
from trading212_application import projection as app
from trading212_application.projection_calendar import ProjectionCalendarError
from trading212_application.projection_presentation import validate_projection_response_bytes
from trading212_domain.errors import DomainError
from trading212_domain.serialization import to_primitive
from trading212_security.principals import (
    AuthenticationError,
    AuthorizationError,
    Authorizer,
    Principal,
    Scope,
)

from .auth import PrincipalResolver
from .gateway import _correlation_id
from .projection_commands import projection_command
from .projection_schemas import (
    ProjectionCreateToolResult,
    ProjectionGoalToolResult,
    ProjectionListToolResult,
    ProjectionRunToolResult,
    ProjectionToolEnvelope,
    ProjectionToolError,
)

MAX_PROJECTION_INPUT_BYTES = 64 * 1024


class ProjectionMcpGateway:
    def __init__(
        self,
        *,
        service: app.ProjectionService | None,
        principals: PrincipalResolver,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._principals = principals
        self._clock = clock or (lambda: datetime.now(UTC))
        self._logger = logging.getLogger("trading212_mcp.audit")

    async def list_goals(
        self, account_id: str, query: wire.ProjectionPageQuery, *, context: Context[Any, Any]
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: app.ProjectionService, correlation: str
        ) -> ProjectionListToolResult:
            data = _payload(
                await service.list_goals(
                    principal,
                    UUID(account_id),
                    app.ProjectionPageQuery(limit=query.limit, cursor=query.cursor),
                ),
                wire.ProjectionPageResponse[wire.GoalResponse],
            )
            if data.limit != query.limit:
                raise _InvalidResult()
            for item in data.items:
                _account(item.account_id, account_id)
            return ProjectionListToolResult(data=data, error=None)

        return await self._execute(
            "list_goals",
            account_id,
            {"account_id": account_id, **query.model_dump(mode="json")},
            context,
            ProjectionListToolResult,
            operation,
        )

    async def create_projection_run(
        self,
        account_id: str,
        request: wire.CreateProjectionRunRequest,
        idempotency_key: str,
        *,
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: app.ProjectionService, correlation: str
        ) -> ProjectionCreateToolResult:
            data = _payload(
                await service.create_run(
                    principal,
                    projection_command(
                        account_id,
                        request,
                        idempotency_key=idempotency_key,
                        correlation=correlation,
                    ),
                ),
                wire.ProjectionOperationalRunResponse,
            )
            _account(data.account_id, account_id)
            if (
                data.assumption_version_id != request.assumption_version_id
                or data.goal_version_id != request.goal_version_id
            ):
                raise _InvalidResult()
            return ProjectionCreateToolResult(data=data, error=None)

        return await self._execute(
            "create_projection_run",
            account_id,
            {
                "account_id": account_id,
                "idempotency_key": idempotency_key,
                **request.model_dump(mode="json"),
            },
            context,
            ProjectionCreateToolResult,
            operation,
            write=True,
        )

    async def get_projection(
        self,
        account_id: str,
        run_id: str,
        query: wire.ProjectionPointPageQuery,
        *,
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: app.ProjectionService, correlation: str
        ) -> ProjectionRunToolResult:
            data = _payload(
                await service.get_run(
                    principal,
                    UUID(run_id),
                    app.ProjectionPointPageQuery(
                        point_limit=query.point_limit,
                        point_cursor=query.point_cursor,
                    ),
                    expected_account_id=UUID(account_id),
                ),
                wire.ProjectionRunResponse,
            )
            _account(data.account_id, account_id)
            if data.id != run_id or (
                data.result is not None and data.result.points.point_limit != query.point_limit
            ):
                raise _InvalidResult()
            return ProjectionRunToolResult(data=data, error=None)

        return await self._execute(
            "get_projection",
            account_id,
            {"account_id": account_id, "run_id": run_id, **query.model_dump(mode="json")},
            context,
            ProjectionRunToolResult,
            operation,
        )

    async def get_goal_analysis(
        self, account_id: str, run_id: str, *, context: Context[Any, Any]
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: app.ProjectionService, correlation: str
        ) -> ProjectionGoalToolResult:
            data = _payload(
                await service.get_goal_analysis(
                    principal, UUID(run_id), expected_account_id=UUID(account_id)
                ),
                wire.GoalAnalysisResponse,
            )
            _account(data.account_id, account_id)
            if data.run_id != run_id:
                raise _InvalidResult()
            return ProjectionGoalToolResult(data=data, error=None)

        return await self._execute(
            "get_goal_analysis",
            account_id,
            {"account_id": account_id, "run_id": run_id},
            context,
            ProjectionGoalToolResult,
            operation,
        )

    async def _execute[T: ProjectionToolEnvelope[Any]](
        self,
        name: str,
        account_id: str,
        arguments: dict[str, Any],
        context: Context[Any, Any],
        result_type: type[T],
        operation: Callable[[Principal, app.ProjectionService, str], Awaitable[T]],
        *,
        write: bool = False,
    ) -> CallToolResult:
        correlation = _correlation_id(context)
        outcome = "INTERNAL_ERROR"
        scopes = (
            Scope.PORTFOLIO_READ,
            Scope.ANALYTICS_READ,
            *((Scope.PROJECTIONS_WRITE,) if write else ()),
        )
        try:
            principal = await self._principals.resolve()
            for scope in scopes:
                Authorizer().require_scope(principal, scope, now=self._clock())
            if len(json.dumps(arguments, ensure_ascii=False).encode()) > MAX_PROJECTION_INPUT_BYTES:
                raise _InputTooLarge()
            if self._service is None:
                raise app.ProjectionServiceError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
            result = await operation(principal, self._service, correlation)
            for scope in scopes:
                Authorizer().require_scope(principal, scope, now=self._clock())
            response = CallToolResult(
                content=[TextContent(type="text", text=_summary(name, result))],
                structured_content=result.model_dump(mode="json"),
                _meta={"correlationId": correlation},
                is_error=False,
            )
            try:
                validate_projection_response_bytes(
                    response.model_dump_json(by_alias=True).encode("utf-8")
                )
            except app.ProjectionServiceError as failure:
                if failure.code != app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED:
                    raise
                raise _OutputTooLarge() from None
            outcome = "success"
            return response
        except Exception as exc:
            error = _safe_error(exc, correlation)
            outcome = error.code
            result = result_type.model_validate(
                {"data": None, "error": error.model_dump(mode="json")}
            )
            return CallToolResult(
                content=[TextContent(type="text", text=f"{error.code}: {error.message}")],
                structured_content=result.model_dump(mode="json"),
                _meta={"correlationId": correlation},
                is_error=True,
            )
        finally:
            self._logger.info(
                "mcp_projection tool=%s outcome=%s account_ref=%s correlation_ref=%s",
                name,
                outcome,
                _reference(account_id),
                _reference(correlation),
            )


def _summary(name: str, result: ProjectionToolEnvelope[Any]) -> str:
    data = result.data
    if isinstance(result, ProjectionListToolResult) and data is not None:
        return f"Read {len(data.items)} of {data.total} saved goals. Use next_cursor to continue."
    if isinstance(result, ProjectionCreateToolResult) and data is not None:
        return (
            f"Projection request {data.id} is {data.state}. "
            "Read get_projection before using financial results."
        )
    if isinstance(result, ProjectionRunToolResult) and data is not None:
        if data.result is None:
            return (
                f"Projection {data.id} is {data.state}; "
                f"financial result is {data.result_availability}."
            )
        page = data.result.points
        return (
            f"Read saved projection {data.id}: {len(page.items)} of {page.total} "
            "retained points. Exact values, quality and source omissions are preserved."
        )
    if isinstance(result, ProjectionGoalToolResult) and data is not None:
        if data.availability == "unavailable":
            return (
                f"Goal analysis is unavailable: {data.reason}. "
                "No financial goal estimate is returned."
            )
        return (
            f"Read {len(data.variants)} saved goal variants. Probabilities are model estimates; "
            "objective attainment never automatically accepts a goal."
        )
    raise _InvalidResult()


def _payload[T: ProjectionSchema](value: object, schema: type[T]) -> T:
    try:
        return schema.model_validate(to_primitive(value))
    except (DomainError, KeyError, TypeError, ValueError):
        raise _InvalidResult() from None


def _account(actual: str, expected: str) -> None:
    if actual != expected:
        raise app.ProjectionServiceError(app.ProjectionErrorCode.NOT_FOUND)


def _reference(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


class _InvalidResult(Exception):
    pass


class _InputTooLarge(ValueError):
    pass


class _OutputTooLarge(ValueError):
    pass


_ERRORS = {
    "NOT_FOUND": "The projection resource was not found.",
    "ACCESS_DENIED": "Access to the projection operation is denied.",
    "VALIDATION_FAILED": "The bounded projection request is invalid.",
    "INPUT_BOUND_EXCEEDED": "The projection input exceeds its resource bounds.",
    "CONFLICT": "The request identity or retained input conflicts.",
    "INVALID_STATE_TRANSITION": "The projection job cannot make this transition.",
    "REVISION_MISMATCH": "The current projection definition revision differs.",
    "REVISION_REQUIRED": "The current projection definition revision is required.",
    "CURSOR_INVALID": "The scoped cursor is invalid or expired.",
    "RATE_LIMITED": "The projection operation reached its configured capacity.",
    "SOURCE_UNAVAILABLE": "The pinned projection source is unavailable.",
    "PROJECTION_UNAVAILABLE": "The projection result or service is unavailable.",
    "RUN_EXPIRED": "The projection run inputs have expired.",
    "CALENDAR_OVERFLOW": "The projection calendar exceeds supported dates.",
    "DATE_OUTSIDE_HORIZON": "A scheduled date is outside the projection horizon.",
    "DATE_NOT_MONTH_BOUNDARY": "A scheduled date is not a projection month boundary.",
    "GOAL_DATE_MISMATCH": "The goal date differs from the projection horizon.",
}


def _safe_error(exc: Exception, correlation: str) -> ProjectionToolError:
    code: Any = "INTERNAL_ERROR"
    message = "The projection operation could not complete."
    if isinstance(exc, AuthenticationError):
        code, message = "AUTHENTICATION_REQUIRED", "Authentication is required."
    elif isinstance(exc, AuthorizationError):
        code, message = "ACCESS_DENIED", "Required projection scopes are missing."
    elif isinstance(exc, _InputTooLarge):
        code, message = "REQUEST_TOO_LARGE", "The projection request exceeds its byte bound."
    elif isinstance(exc, _OutputTooLarge):
        code, message = "RESULT_TOO_LARGE", "The projection result exceeds its byte bound."
    elif isinstance(exc, (ProjectionCalendarError, app.ProjectionServiceError)):
        code, message = exc.code.value, _ERRORS[exc.code.value]
    elif isinstance(exc, DomainError) or (
        isinstance(exc, ValueError) and not isinstance(exc, ValidationError)
    ):
        code, message = "VALIDATION_FAILED", "The bounded projection request is invalid."
    return ProjectionToolError(
        code=code,
        message=message,
        correlation_id=correlation,
        retryable=code in {"RATE_LIMITED", "PROJECTION_UNAVAILABLE", "SOURCE_UNAVAILABLE"},
        remediation=(
            "Wait before retrying the same operation."
            if code == "RATE_LIMITED"
            else "Use authorized inputs. Reuse the key only for identical requests."
        ),
    )
