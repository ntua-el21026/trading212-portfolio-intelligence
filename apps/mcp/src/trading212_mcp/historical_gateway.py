"""Four fixed historical reads over authorized immutable canonical service results."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError
from trading212_api_contracts import historical as wire
from trading212_application import historical as app
from trading212_application.queries import CollectionSnapshotCapacityError, CursorValidationError
from trading212_domain import historical as domain
from trading212_domain import historical_results as result
from trading212_domain.errors import DomainError
from trading212_domain.planning import CoveragePolicy
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
from .historical_schemas import (
    HistoricalAttributionToolResult,
    HistoricalBenchmarkToolResult,
    HistoricalDividendToolResult,
    HistoricalPerformanceToolResult,
    HistoricalToolEnvelope,
    HistoricalToolError,
    HistoricalToolSelection,
)


class HistoricalMcpGateway:
    def __init__(
        self,
        *,
        service: app.PerformanceIntelligenceService | None,
        principals: PrincipalResolver,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._principals = principals
        self._clock = clock or (lambda: datetime.now(UTC))
        self._logger = logging.getLogger("trading212_mcp.audit")

    async def get_performance_summary(
        self,
        account_id: str,
        query: wire.HistoricalPerformanceSummaryQuery,
        *,
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: app.PerformanceIntelligenceService
        ) -> HistoricalPerformanceToolResult:
            value = await service.get_performance_summary(
                principal,
                account_id,
                query=app.PerformanceSummaryQuery(
                    window=_window(query),
                    options=result.PerformanceOptions(
                        method=domain.ReturnMethod(query.method),
                        frequency=domain.HistoricalFrequency(query.frequency),
                    ),
                ),
            )
            data = _payload(value, wire.PerformanceIntelligenceResponse, account_id)
            return HistoricalPerformanceToolResult(
                data=data,
                selection=HistoricalToolSelection(
                    total=len(data.series), returned=len(data.series), omitted=0
                ),
                error=None,
            )

        return await self._execute(
            "get_performance_summary",
            account_id,
            query,
            context,
            HistoricalPerformanceToolResult,
            operation,
        )

    async def get_benchmark_comparison(
        self,
        account_id: str,
        query: wire.HistoricalBenchmarkComparisonQuery,
        *,
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: app.PerformanceIntelligenceService
        ) -> HistoricalBenchmarkToolResult:
            value = await service.get_benchmark_comparison(
                principal,
                account_id,
                query=app.BenchmarkComparisonQuery(
                    window=_window(query),
                    benchmark_version_id=query.benchmark_version_id,
                    options=result.ComparisonOptions(
                        frequency=domain.HistoricalFrequency(query.frequency)
                    ),
                ),
            )
            data = _payload(value, wire.BenchmarkComparisonResponse, account_id)
            return HistoricalBenchmarkToolResult(
                data=data,
                selection=HistoricalToolSelection(
                    total=len(data.series), returned=len(data.series), omitted=0
                ),
                error=None,
            )

        return await self._execute(
            "get_benchmark_comparison",
            account_id,
            query,
            context,
            HistoricalBenchmarkToolResult,
            operation,
        )

    async def get_dividend_intelligence(
        self,
        account_id: str,
        query: wire.HistoricalDividendIntelligenceQuery,
        *,
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: app.PerformanceIntelligenceService
        ) -> HistoricalDividendToolResult:
            value = await service.get_dividend_intelligence(
                principal,
                account_id,
                query=app.DividendIntelligenceQuery(window=_window(query), top_n=query.top_n),
            )
            data = _payload(value, wire.DividendIntelligenceResponse, account_id)
            return HistoricalDividendToolResult(
                data=data,
                selection=HistoricalToolSelection(
                    total=data.eligible_count, returned=len(data.rows), omitted=data.omitted_count
                ),
                error=None,
            )

        return await self._execute(
            "get_dividend_intelligence",
            account_id,
            query,
            context,
            HistoricalDividendToolResult,
            operation,
            activity=True,
        )

    async def get_attribution_summary(
        self, account_id: str, query: wire.HistoricalAttributionQuery, *, context: Context[Any, Any]
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: app.PerformanceIntelligenceService
        ) -> HistoricalAttributionToolResult:
            value = await service.get_attribution_summary(
                principal,
                account_id,
                query=app.AttributionQuery(
                    window=_window(query),
                    options=result.AttributionOptions(
                        grouping=domain.HistoricalGrouping(query.grouping)
                    ),
                    target_version_id=query.target_version_id,
                    top_n=query.top_n,
                ),
            )
            data = _payload(value, wire.AttributionSummaryResponse, account_id)
            return HistoricalAttributionToolResult(
                data=data,
                selection=HistoricalToolSelection(
                    total=data.eligible_count, returned=len(data.rows), omitted=data.omitted_count
                ),
                error=None,
            )

        return await self._execute(
            "get_attribution_summary",
            account_id,
            query,
            context,
            HistoricalAttributionToolResult,
            operation,
            targets=True,
        )

    async def _execute(
        self,
        name: str,
        account_id: str,
        query: wire.HistoricalSchema,
        context: Context[Any, Any],
        result_type: type[HistoricalToolEnvelope[Any]],
        operation: Callable[
            [Principal, app.PerformanceIntelligenceService], Awaitable[HistoricalToolEnvelope[Any]]
        ],
        *,
        activity: bool = False,
        targets: bool = False,
    ) -> CallToolResult:
        correlation = _correlation_id(context)
        outcome = "INTERNAL_ERROR"
        try:
            principal = await self._principals.resolve()
            scopes = [Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ]
            if activity:
                scopes.append(Scope.ACTIVITY_READ)
            if targets:
                scopes.append(Scope.TARGETS_READ)
            for scope in scopes:
                Authorizer().require_scope(principal, scope, now=self._clock())
            if (
                len(
                    json.dumps({"account_id": account_id, **query.model_dump(mode="json")}).encode()
                )
                > 64 * 1024
            ):
                raise _InputTooLarge()
            if self._service is None:
                raise app.HistoricalServiceError(
                    app.HistoricalServiceErrorCode.HISTORICAL_UNAVAILABLE,
                    "Historical service unavailable.",
                )
            value = await operation(principal, self._service)
            result_type.model_validate(value)
            response = CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=(
                            "Retrieved authorized historical analytics with "
                            "explicit coverage and unavailable metrics."
                        ),
                    )
                ],
                structured_content=value.model_dump(mode="json"),
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
            value = result_type.model_validate(
                {"data": None, "selection": None, "error": error.model_dump(mode="json")}
            )
            return CallToolResult(
                content=[TextContent(type="text", text=f"{error.code}: {error.message}")],
                structured_content=value.model_dump(mode="json"),
                _meta={"correlationId": correlation},
                is_error=True,
            )
        finally:
            self._logger.info(
                "mcp_historical tool=%s outcome=%s account_ref=%s correlation_ref=%s",
                name,
                outcome,
                hashlib.sha256(account_id.encode()).hexdigest()[:16],
                hashlib.sha256(correlation.encode()).hexdigest()[:16],
            )


def _window(value: wire.HistoricalWindowQuery) -> domain.HistoricalWindow:
    return domain.HistoricalWindow(
        start_date=value.start_date,
        end_date=value.end_date,
        source_cutoff_at=value.source_cutoff_at,
        reporting_currency=CurrencyCode(value.reporting_currency),
        coverage_policy=CoveragePolicy.REQUIRE_COMPLETE,
        knowledge_policy=domain.KnowledgePolicy.AS_OF_CUTOFF,
    )


def _payload[T: wire.HistoricalSchema](value: object, schema: type[T], account_id: str) -> T:
    try:
        payload = to_primitive(value)
        if payload["context"]["account_id"] != account_id:
            raise _InvalidResult()
        return schema.model_validate(payload)
    except (KeyError, TypeError, ValueError, DomainError):
        raise _InvalidResult() from None


class _InvalidResult(Exception):
    pass


class _InputTooLarge(Exception):
    pass


class _OutputTooLarge(Exception):
    pass


def _safe_error(exc: Exception, correlation: str) -> HistoricalToolError:
    code: Any = "INTERNAL_ERROR"
    message = "The historical operation could not complete."
    retryable = False
    if isinstance(exc, AuthenticationError):
        code, message = "AUTHENTICATION_REQUIRED", "Authentication is required."
    elif isinstance(exc, AuthorizationError):
        code, message = "ACCESS_DENIED", "Required historical scopes are missing."
    elif isinstance(exc, CursorValidationError):
        code, message = "CURSOR_INVALID", "The scoped pagination cursor is invalid."
    elif isinstance(exc, CollectionSnapshotCapacityError):
        code, message, retryable = (
            "COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED",
            "Active pagination capacity is exhausted.",
            True,
        )
    elif isinstance(exc, _InputTooLarge):
        code, message = "REQUEST_TOO_LARGE", "The historical request exceeds its byte bound."
    elif isinstance(exc, _OutputTooLarge):
        code, message = "RESULT_TOO_LARGE", "The historical result exceeds its byte bound."
    elif isinstance(exc, app.HistoricalServiceError):
        messages = {
            "NOT_FOUND": "The requested historical resource was not found.",
            "ACCESS_DENIED": "Access to this historical resource is denied.",
            "VALIDATION_FAILED": "The historical request is invalid.",
            "INPUT_SNAPSHOT_MISMATCH": "The retained input does not match the requested scope.",
            "HISTORICAL_UNAVAILABLE": "The historical service is unavailable.",
            "RESULT_TOO_LARGE": "The historical result exceeds its byte bound.",
        }
        if exc.code.value in messages:
            code, message = exc.code.value, messages[exc.code.value]
            retryable = code == "HISTORICAL_UNAVAILABLE"
    elif isinstance(exc, (ValueError, DomainError)) and not isinstance(exc, ValidationError):
        code, message = "VALIDATION_FAILED", "The bounded historical request is invalid."
    return HistoricalToolError(
        code=code,
        message=message,
        correlation_id=correlation,
        retryable=retryable,
        remediation=(
            "Use an authorized account and explicit bounded historical dates, "
            "currency and source cutoff."
        ),
    )
