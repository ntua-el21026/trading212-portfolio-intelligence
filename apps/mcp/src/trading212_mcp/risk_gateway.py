"""Authorized, bounded canonical risk operations; no financial recomputation."""

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
from trading212_api_contracts import risk as wire
from trading212_application import risk as app
from trading212_domain.errors import DomainError
from trading212_domain.historical import HistoricalWindow, KnowledgePolicy
from trading212_domain.planning import CoveragePolicy
from trading212_domain.risk_history import RiskAssetSource
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
from .risk_schemas import RiskMatrixToolResult, RiskRunToolResult, RiskToolEnvelope, RiskToolError

MAX_RISK_INPUT_BYTES = 64 * 1024
MAX_RISK_OUTPUT_BYTES = 2 * 1024 * 1024


class RiskMcpGateway:
    def __init__(
        self,
        *,
        service: app.RiskService | None,
        principals: PrincipalResolver,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._principals = principals
        self._clock = clock or (lambda: datetime.now(UTC))
        self._logger = logging.getLogger("trading212_mcp.audit")

    async def create_risk_run(
        self,
        account_id: str,
        request: wire.CreateRiskRunRequest,
        idempotency_key: str,
        *,
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: app.RiskService, correlation: str
        ) -> RiskRunToolResult:
            value = await service.create_run(
                principal,
                risk_command(
                    account_id, request, idempotency_key=idempotency_key, correlation=correlation
                ),
            )
            data = _payload(value, wire.RiskRunResponse)
            _account(data.account_id, account_id)
            if (
                data.definition_version_id != request.definition_version_id
                or data.portfolio_snapshot_id != request.portfolio_snapshot_id
                or data.historical_input_snapshot_id != request.historical_input_snapshot_id
                or data.xray_run_id != request.xray_run_id
            ):
                raise _InvalidResult()
            return RiskRunToolResult(data=data, error=None)

        return await self._execute(
            "create_risk_run",
            account_id,
            {
                "account_id": account_id,
                "idempotency_key": idempotency_key,
                **request.model_dump(mode="json"),
            },
            context,
            RiskRunToolResult,
            operation,
            write=True,
        )

    async def get_risk_summary(
        self, account_id: str, run_id: str, *, context: Context[Any, Any]
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: app.RiskService, correlation: str
        ) -> RiskRunToolResult:
            data = _payload(await service.get_run(principal, UUID(run_id)), wire.RiskRunResponse)
            _account(data.account_id, account_id)
            if data.id != run_id:
                raise _InvalidResult()
            return RiskRunToolResult(data=data, error=None)

        return await self._execute(
            "get_risk_summary",
            account_id,
            {"account_id": account_id, "run_id": run_id},
            context,
            RiskRunToolResult,
            operation,
        )

    async def get_risk_matrix(
        self, account_id: str, run_id: str, *, context: Context[Any, Any]
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: app.RiskService, correlation: str
        ) -> RiskMatrixToolResult:
            data = _payload(
                await service.get_matrix(principal, UUID(run_id)), wire.RiskMatrixResponse
            )
            _account(data.account_id, account_id)
            if data.run_id != run_id:
                raise _InvalidResult()
            return RiskMatrixToolResult(data=data, error=None)

        return await self._execute(
            "get_risk_matrix",
            account_id,
            {"account_id": account_id, "run_id": run_id},
            context,
            RiskMatrixToolResult,
            operation,
        )

    async def _execute[T: RiskToolEnvelope[Any]](
        self,
        name: str,
        account_id: str,
        arguments: dict[str, Any],
        context: Context[Any, Any],
        result_type: type[T],
        operation: Callable[[Principal, app.RiskService, str], Awaitable[T]],
        *,
        write: bool = False,
    ) -> CallToolResult:
        correlation = _correlation_id(context)
        outcome = "INTERNAL_ERROR"
        try:
            principal = await self._principals.resolve()
            for scope in (
                Scope.PORTFOLIO_READ,
                Scope.ANALYTICS_READ,
                *((Scope.RISK_WRITE,) if write else ()),
            ):
                Authorizer().require_scope(principal, scope, now=self._clock())
            if len(json.dumps(arguments, ensure_ascii=False).encode()) > MAX_RISK_INPUT_BYTES:
                raise _InputTooLarge()
            if self._service is None:
                raise app.RiskServiceError(app.RiskErrorCode.RISK_UNAVAILABLE)
            result = await operation(principal, self._service, correlation)
            response = CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=(
                            "Saved a risk request. Read its state before using results."
                            if write
                            else "Read canonical risk estimates and source metadata."
                        ),
                    )
                ],
                structured_content=result.model_dump(mode="json"),
                _meta={"correlationId": correlation},
                is_error=False,
            )
            if len(response.model_dump_json(by_alias=True).encode()) > MAX_RISK_OUTPUT_BYTES:
                raise _OutputTooLarge()
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
                "mcp_risk tool=%s outcome=%s account_ref=%s correlation_ref=%s",
                name,
                outcome,
                _reference(account_id),
                _reference(correlation),
            )


def risk_command(
    account_id: str, value: wire.CreateRiskRunRequest, *, idempotency_key: str, correlation: str
) -> app.CreateRiskRun:
    # MCP accepts 128 characters; durable audit IDs retain at most 120.
    # Keep full transport identity in response metadata and never truncate it.
    window = value.window
    return app.CreateRiskRun(
        account_id=UUID(account_id),
        definition_version_id=UUID(value.definition_version_id),
        portfolio_snapshot_id=UUID(value.portfolio_snapshot_id),
        historical_input_snapshot_id=UUID(value.historical_input_snapshot_id),
        window=HistoricalWindow(
            start_date=window.start_date,
            end_date=window.end_date,
            source_cutoff_at=window.source_cutoff_at,
            reporting_currency=CurrencyCode(window.reporting_currency),
            coverage_policy=CoveragePolicy(window.coverage_policy),
            knowledge_policy=KnowledgePolicy(window.knowledge_policy),
        ),
        assets=tuple(
            RiskAssetSource(instrument_id=x.instrument_id, series_id=x.series_id)
            for x in value.assets
        ),
        benchmark_version_id=UUID(value.benchmark_version_id)
        if value.benchmark_version_id
        else None,
        xray_run_id=UUID(value.xray_run_id) if value.xray_run_id else None,
        idempotency_key=idempotency_key,
        correlation_id=correlation
        if len(correlation) <= 120
        else "sha256:" + hashlib.sha256(correlation.encode()).hexdigest(),
    )


def _payload[T: wire.RiskSchema](value: object, schema: type[T]) -> T:
    try:
        return schema.model_validate(to_primitive(value))
    except (DomainError, KeyError, TypeError, ValueError):
        raise _InvalidResult() from None


def _account(actual: str, expected: str) -> None:
    if actual != expected:
        raise app.RiskServiceError(app.RiskErrorCode.NOT_FOUND)


def _reference(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


class _InvalidResult(Exception):
    pass


class _InputTooLarge(ValueError):
    pass


class _OutputTooLarge(ValueError):
    pass


_ERRORS = {
    "NOT_FOUND": "The risk resource was not found.",
    "ACCESS_DENIED": "Access to the risk operation is denied.",
    "VALIDATION_FAILED": "The bounded risk request is invalid.",
    "INPUT_BOUND_EXCEEDED": "The risk input exceeds its resource bounds.",
    "CONFLICT": "The request identity or retained input conflicts.",
    "INVALID_STATE_TRANSITION": "The risk job cannot make this transition.",
    "REVISION_MISMATCH": "The current risk definition revision differs.",
    "REVISION_REQUIRED": "The current risk definition revision is required.",
    "CURSOR_INVALID": "The scoped cursor is invalid or expired.",
    "RATE_LIMITED": "The risk operation reached its configured capacity.",
    "SOURCE_UNAVAILABLE": "The pinned risk source is unavailable.",
    "RISK_UNAVAILABLE": "The risk result or service is unavailable.",
    "RUN_EXPIRED": "The risk run inputs have expired.",
}


def _safe_error(exc: Exception, correlation: str) -> RiskToolError:
    code: Any = "INTERNAL_ERROR"
    message = "The risk operation could not complete."
    if isinstance(exc, AuthenticationError):
        code, message = "AUTHENTICATION_REQUIRED", "Authentication is required."
    elif isinstance(exc, AuthorizationError):
        code, message = "ACCESS_DENIED", "Required risk scopes are missing."
    elif isinstance(exc, _InputTooLarge):
        code, message = "REQUEST_TOO_LARGE", "The risk request exceeds its byte bound."
    elif isinstance(exc, _OutputTooLarge):
        code, message = "RESULT_TOO_LARGE", "The risk result exceeds its byte bound."
    elif isinstance(exc, app.RiskServiceError):
        code, message = exc.code.value, _ERRORS[exc.code.value]
    elif isinstance(exc, DomainError) or (
        isinstance(exc, ValueError) and not isinstance(exc, ValidationError)
    ):
        code, message = "VALIDATION_FAILED", "The bounded risk request is invalid."
    return RiskToolError(
        code=code,
        message=message,
        correlation_id=correlation,
        retryable=code in {"RATE_LIMITED", "RISK_UNAVAILABLE", "SOURCE_UNAVAILABLE"},
        remediation=(
            "Wait before retrying the same operation."
            if code == "RATE_LIMITED"
            else "Use authorized inputs. Reuse the key only for identical requests."
        ),
    )
