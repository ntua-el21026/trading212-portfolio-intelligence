"""Four fixed planning tools; commands persist manual proposals and never call providers."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError
from trading212_api_contracts import planning as wire
from trading212_application import planning as application
from trading212_application.queries import CollectionSnapshotCapacityError, CursorValidationError
from trading212_domain import planning as domain
from trading212_domain.errors import DomainError
from trading212_domain.serialization import to_primitive
from trading212_domain.values import CurrencyCode, Money
from trading212_security.principals import (
    AuthenticationError,
    AuthorizationError,
    Authorizer,
    Principal,
    Scope,
)

from .auth import PrincipalResolver
from .gateway import _correlation_id
from .planning_schemas import (
    ActualVsTargetToolResult,
    ContributionPlanToolResult,
    CreateContributionPlanToolResult,
    DriftAnalysisToolResult,
    PlanningToolEnvelope,
    PlanningToolError,
    PlanningToolPagination,
)

MAX_PLANNING_INPUT_BYTES = 64 * 1024
MAX_PLANNING_OUTPUT_BYTES = 2 * 1024 * 1024


class PlanningMcpGateway:
    def __init__(
        self,
        *,
        service: application.PlanningService | None,
        principals: PrincipalResolver,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._principals = principals
        self._clock = clock or (lambda: datetime.now(UTC))
        self._logger = logging.getLogger("trading212_mcp.audit")

    async def get_actual_vs_target(
        self, account_id: str, query: wire.ActualVsTargetQuery, *, context: Context[Any, Any]
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: application.PlanningService
        ) -> ActualVsTargetToolResult:
            value = await service.get_actual_vs_target(
                principal,
                account_id,
                query=application.ActualVsTargetQuery(
                    **query.model_dump(exclude={"reporting_currency"}),
                    reporting_currency=CurrencyCode(query.reporting_currency),
                ),
            )
            data = _payload(value, wire.ActualVsTargetResult)
            _account(data.context.account_id, account_id)
            page = data.rows
            return ActualVsTargetToolResult(
                data=data,
                pagination=_pagination(page.next_cursor, page.limit, page.total, len(page.items)),
                error=None,
            )

        return await self._execute(
            "get_actual_vs_target",
            account_id,
            {"account_id": account_id, **query.model_dump(mode="json")},
            context,
            ActualVsTargetToolResult,
            operation,
            targets=True,
        )

    async def get_drift_analysis(
        self, account_id: str, query: wire.DriftAnalysisQuery, *, context: Context[Any, Any]
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: application.PlanningService
        ) -> DriftAnalysisToolResult:
            value = await service.get_drift_analysis(
                principal,
                account_id,
                query=application.DriftAnalysisQuery(
                    **query.model_dump(exclude={"reporting_currency", "basis"}),
                    reporting_currency=CurrencyCode(query.reporting_currency),
                    basis=domain.DriftBasis(query.basis),
                ),
            )
            data = _payload(value, wire.DriftAnalysisResult)
            _account(data.context.account_id, account_id)
            return DriftAnalysisToolResult(
                data=data,
                pagination=_pagination(
                    None, data.top_n, data.eligible_rows, data.eligible_rows - data.omitted_rows
                ),
                error=None,
            )

        return await self._execute(
            "get_drift_analysis",
            account_id,
            {"account_id": account_id, **query.model_dump(mode="json")},
            context,
            DriftAnalysisToolResult,
            operation,
            targets=True,
        )

    async def get_contribution_plan(
        self,
        account_id: str,
        plan_id: str,
        query: wire.ContributionPlanDetailQuery,
        *,
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: application.PlanningService
        ) -> ContributionPlanToolResult:
            value = await service.get_contribution_plan(
                principal,
                plan_id,
                query=application.ContributionPlanDetailQuery(
                    account_id=account_id, **query.model_dump()
                ),
            )
            data = _payload(value, wire.ContributionPlanDetail)
            _account(data.job.account_id, account_id)
            if data.job.plan_id != plan_id:
                raise application.PlanningServiceError(
                    application.PlanningServiceErrorCode.NOT_FOUND, "Plan mismatch."
                )
            page = data.lines
            return ContributionPlanToolResult(
                data=data,
                pagination=_pagination(page.next_cursor, page.limit, page.total, len(page.items)),
                error=None,
            )

        return await self._execute(
            "get_contribution_plan",
            account_id,
            {"account_id": account_id, "plan_id": plan_id, **query.model_dump(mode="json")},
            context,
            ContributionPlanToolResult,
            operation,
        )

    async def create_contribution_plan(
        self, request: wire.McpCreateContributionPlanRequest, *, context: Context[Any, Any]
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: application.PlanningService
        ) -> CreateContributionPlanToolResult:
            value = await service.create_contribution_plan(
                principal,
                _command(request),
                idempotency_key=request.idempotency_key,
                correlation_id=_correlation_id(context),
            )
            data = _payload(value, wire.ContributionPlanJob)
            _account(data.account_id, request.account_id)
            if (data.virtual_portfolio_id, data.target_version_id, data.snapshot_id) != (
                request.virtual_portfolio_id,
                request.target_version_id,
                request.snapshot_id,
            ):
                raise application.PlanningServiceError(
                    application.PlanningServiceErrorCode.NOT_FOUND, "Input mismatch."
                )
            return CreateContributionPlanToolResult(data=data, pagination=None, error=None)

        return await self._execute(
            "create_contribution_plan",
            request.account_id,
            request.model_dump(mode="json"),
            context,
            CreateContributionPlanToolResult,
            operation,
            targets=True,
            write=True,
        )

    async def _execute[T: PlanningToolEnvelope[Any]](
        self,
        name: str,
        account_id: str,
        arguments: dict[str, Any],
        context: Context[Any, Any],
        result_type: type[T],
        operation: Callable[[Principal, application.PlanningService], Awaitable[T]],
        *,
        targets: bool = False,
        write: bool = False,
    ) -> CallToolResult:
        correlation = _correlation_id(context)
        outcome = "INTERNAL_ERROR"
        try:
            principal = await self._principals.resolve()
            scopes = [Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ]
            if targets:
                scopes.append(Scope.TARGETS_READ)
            if write:
                scopes.append(Scope.PLANS_WRITE)
            for scope in scopes:
                Authorizer().require_scope(principal, scope, now=self._clock())
            if (
                len(json.dumps(arguments, ensure_ascii=False).encode("utf-8"))
                > MAX_PLANNING_INPUT_BYTES
            ):
                raise _InputTooLarge()
            if self._service is None:
                raise application.PlanningServiceError(
                    application.PlanningServiceErrorCode.PLANNING_UNAVAILABLE,
                    "Planning unavailable.",
                )
            result = await operation(principal, self._service)
            result_type.model_validate(result)
            response = CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text="Saved an authorized manual planning request; execution is disabled."
                        if write
                        else "Retrieved authorized canonical planning data; execution is disabled.",
                    )
                ],
                structured_content=result.model_dump(mode="json"),
                _meta={"correlationId": correlation},
                is_error=False,
            )
            if (
                len(response.model_dump_json(by_alias=True).encode("utf-8"))
                > MAX_PLANNING_OUTPUT_BYTES
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
                "mcp_planning tool=%s outcome=%s account_ref=%s correlation_ref=%s",
                name,
                outcome,
                _reference(account_id),
                _reference(correlation),
            )


def _payload[T: wire.PlanningSchema](value: object, schema: type[T]) -> T:
    try:
        return schema.model_validate(wire.canonical_planning_payload(to_primitive(value), schema))
    except (KeyError, TypeError, ValueError):
        raise _InvalidResult() from None


def _account(actual: str, expected: str) -> None:
    if actual != expected:
        raise application.PlanningServiceError(
            application.PlanningServiceErrorCode.NOT_FOUND, "Scope mismatch."
        )


def _reference(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _pagination(
    cursor: str | None, limit: int, total: int, returned: int
) -> PlanningToolPagination:
    return PlanningToolPagination(
        next_cursor=cursor,
        limit=limit,
        total=total,
        returned=returned,
        truncated=cursor is not None or returned < total,
    )


def _command(
    value: wire.McpCreateContributionPlanRequest,
) -> application.CreateContributionPlanCommand:
    currency = CurrencyCode(value.contribution.currency)
    return application.CreateContributionPlanCommand(
        account_id=value.account_id,
        virtual_portfolio_id=value.virtual_portfolio_id,
        target_version_id=value.target_version_id,
        snapshot_id=value.snapshot_id,
        options=domain.PlanningOptions(
            contribution=Money(Decimal(value.contribution.amount), currency),
            mode=domain.PlanningMode(value.mode),
            coverage_policy=domain.CoveragePolicy(value.coverage_policy),
            eligible_holding_ids=tuple(value.eligible_holding_ids)
            if value.eligible_holding_ids is not None
            else None,
            excluded_holding_ids=tuple(value.excluded_holding_ids),
            restricted_group_ids=tuple(value.restricted_group_ids),
            listing_preferences=tuple(
                domain.PlanningListingPreference(item.holding_id, item.listing_id)
                for item in value.listing_preferences
            ),
            holding_constraints=tuple(
                domain.PlanningHoldingConstraint(
                    holding_id=item.holding_id,
                    minimum_amount=Decimal(item.minimum_amount),
                    value_increment=Decimal(item.value_increment),
                    maximum_post_weight=Decimal(item.maximum_post_weight)
                    if item.maximum_post_weight is not None
                    else None,
                )
                for item in value.allocation_constraints
            ),
            cash_reserve=Decimal(value.cash_reserve) if value.cash_reserve is not None else None,
            monetary_quantum=Decimal(value.monetary_quantum)
            if value.monetary_quantum is not None
            else None,
        ),
    )


class _InvalidResult(Exception):
    pass


class _InputTooLarge(ValueError):
    pass


class _OutputTooLarge(ValueError):
    pass


def _safe_error(exc: Exception, correlation: str) -> PlanningToolError:
    code: Any = "INTERNAL_ERROR"
    message = "The private planning operation could not be completed."
    retryable = False
    if isinstance(exc, AuthenticationError):
        code, message = "AUTHENTICATION_REQUIRED", "Authentication is required."
    elif isinstance(exc, AuthorizationError):
        code, message = "ACCESS_DENIED", "Required planning scopes are missing."
    elif isinstance(exc, CursorValidationError):
        code, message = "CURSOR_INVALID", "The scoped pagination cursor is invalid."
    elif isinstance(exc, CollectionSnapshotCapacityError):
        code, message, retryable = (
            "COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED",
            "Active pagination capacity is exhausted.",
            True,
        )
    elif isinstance(exc, _InputTooLarge):
        code, message = "REQUEST_TOO_LARGE", "The planning request exceeds its byte bound."
    elif isinstance(exc, _OutputTooLarge):
        code, message = "RESULT_TOO_LARGE", "The planning result exceeds its byte bound."
    elif isinstance(exc, application.PlanningServiceError):
        code = exc.code.value
        message = {
            "NOT_FOUND": "The requested private planning resource was not found.",
            "ACCESS_DENIED": "Access denied.",
            "PLANNING_UNAVAILABLE": "Planning services are unavailable.",
            "IDEMPOTENCY_KEY_REUSED": "The idempotency identity belongs to a different command.",
            "REVISION_REQUIRED": "The current plan revision is required.",
            "REVISION_MISMATCH": "The plan revision changed.",
            "IMMUTABLE_VERSION": "Finalized plans cannot be modified.",
            "INVALID_STATE_TRANSITION": "This planning lifecycle transition is unavailable.",
            "CURRENCY_MISMATCH": "The contribution currency does not match its pinned inputs.",
            "RESULT_TOO_LARGE": "The planning result exceeds its byte bound.",
            "VALIDATION_FAILED": "The bounded planning request is invalid.",
        }[code]
        retryable = code == "PLANNING_UNAVAILABLE"
    elif isinstance(exc, LookupError):
        code, message = "NOT_FOUND", "The requested private planning resource was not found."
    elif isinstance(exc, (ValueError, DomainError)) and not isinstance(exc, ValidationError):
        code, message = "VALIDATION_FAILED", "The bounded planning request is invalid."
    return PlanningToolError(
        code=code,
        message=message,
        correlation_id=correlation,
        retryable=retryable,
        remediation=(
            "Use authorized immutable inputs and bounded fields; preserve the "
            "idempotency key when retrying an identical command."
        ),
    )
