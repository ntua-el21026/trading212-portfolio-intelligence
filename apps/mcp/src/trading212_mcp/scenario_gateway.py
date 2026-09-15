"""Four authorized scenario operations over saved inputs and bounded public pages."""

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
from trading212_api_contracts import scenarios as wire
from trading212_application import scenario as app
from trading212_domain.errors import DomainError
from trading212_domain.scenario_execution import ScenarioReplaySelection
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
from .scenario_schemas import (
    ScenarioComparisonToolResult,
    ScenarioCreateToolResult,
    ScenarioListToolResult,
    ScenarioRunToolResult,
    ScenarioToolEnvelope,
    ScenarioToolError,
)

MAX_SCENARIO_INPUT_BYTES = 64 * 1024
MAX_SCENARIO_OUTPUT_BYTES = 2 * 1024 * 1024


class ScenarioMcpGateway:
    def __init__(
        self,
        *,
        service: app.ScenarioService | None,
        principals: PrincipalResolver,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._principals = principals
        self._clock = clock or (lambda: datetime.now(UTC))
        self._logger = logging.getLogger("trading212_mcp.audit")

    async def list_scenarios(
        self, account_id: str, query: wire.ScenarioPageQuery, *, context: Context[Any, Any]
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: app.ScenarioService, correlation: str
        ) -> ScenarioListToolResult:
            data = _payload(
                await service.list_definitions(
                    principal,
                    UUID(account_id),
                    app.ScenarioPageQuery(limit=query.limit, cursor=query.cursor),
                ),
                wire.ScenarioPageResponse[wire.ScenarioDefinitionResponse],
            )
            if data.limit != query.limit:
                raise _InvalidResult()
            for item in data.items:
                _account(item.account_id, account_id)
            return ScenarioListToolResult(data=data, error=None)

        return await self._execute(
            "list_scenarios",
            account_id,
            {"account_id": account_id, **query.model_dump(mode="json")},
            context,
            ScenarioListToolResult,
            operation,
        )

    async def create_scenario_run(
        self,
        account_id: str,
        request: wire.CreateScenarioRunRequest,
        idempotency_key: str,
        *,
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: app.ScenarioService, correlation: str
        ) -> ScenarioCreateToolResult:
            data = _payload(
                await service.create_run(
                    principal,
                    scenario_command(
                        account_id,
                        request,
                        idempotency_key=idempotency_key,
                        correlation=correlation,
                    ),
                ),
                wire.ScenarioOperationalRunResponse,
            )
            _account(data.account_id, account_id)
            if (
                data.scenario_version_id != request.scenario_version_id
                or data.portfolio_snapshot_id != request.portfolio_snapshot_id
                or data.xray_run_id != request.xray_run_id
            ):
                raise _InvalidResult()
            return ScenarioCreateToolResult(data=data, error=None)

        return await self._execute(
            "create_scenario_run",
            account_id,
            {
                "account_id": account_id,
                "idempotency_key": idempotency_key,
                **request.model_dump(mode="json"),
            },
            context,
            ScenarioCreateToolResult,
            operation,
            write=True,
        )

    async def get_scenario_result(
        self,
        account_id: str,
        run_id: str,
        query: wire.ScenarioComponentPageQuery,
        *,
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: app.ScenarioService, correlation: str
        ) -> ScenarioRunToolResult:
            data = _payload(
                await service.get_run(
                    principal,
                    UUID(run_id),
                    app.ScenarioComponentPageQuery(
                        component_limit=query.component_limit,
                        component_cursor=query.component_cursor,
                    ),
                    expected_account_id=UUID(account_id),
                ),
                wire.ScenarioRunResponse,
            )
            _account(data.account_id, account_id)
            if data.id != run_id or (
                data.result is not None
                and data.result.components.component_limit != query.component_limit
            ):
                raise _InvalidResult()
            return ScenarioRunToolResult(data=data, error=None)

        return await self._execute(
            "get_scenario_result",
            account_id,
            {"account_id": account_id, "run_id": run_id, **query.model_dump(mode="json")},
            context,
            ScenarioRunToolResult,
            operation,
        )

    async def compare_scenarios(
        self, account_id: str, query: wire.ScenarioComparisonQuery, *, context: Context[Any, Any]
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: app.ScenarioService, correlation: str
        ) -> ScenarioComparisonToolResult:
            data = _payload(
                await service.compare(
                    principal,
                    UUID(account_id),
                    app.ScenarioComparisonQuery(
                        run_ids=(UUID(query.run_ids[0]), UUID(query.run_ids[1])),
                        component_limit=query.component_limit,
                        component_cursor=query.component_cursor,
                    ),
                ),
                wire.ScenarioComparisonPage,
            )
            for side in (data.before, data.after):
                _account(side.pins.account_id, account_id)
            if [
                data.before.run_id,
                data.after.run_id,
            ] != query.run_ids or data.components.component_limit != query.component_limit:
                raise _InvalidResult()
            return ScenarioComparisonToolResult(data=data, error=None)

        return await self._execute(
            "compare_scenarios",
            account_id,
            {"account_id": account_id, **query.model_dump(mode="json")},
            context,
            ScenarioComparisonToolResult,
            operation,
        )

    async def _execute[T: ScenarioToolEnvelope[Any]](
        self,
        name: str,
        account_id: str,
        arguments: dict[str, Any],
        context: Context[Any, Any],
        result_type: type[T],
        operation: Callable[[Principal, app.ScenarioService, str], Awaitable[T]],
        *,
        write: bool = False,
    ) -> CallToolResult:
        correlation = _correlation_id(context)
        outcome = "INTERNAL_ERROR"
        scopes = (
            Scope.PORTFOLIO_READ,
            Scope.ANALYTICS_READ,
            *((Scope.SCENARIOS_WRITE,) if write else ()),
        )
        try:
            principal = await self._principals.resolve()
            for scope in scopes:
                Authorizer().require_scope(principal, scope, now=self._clock())
            if len(json.dumps(arguments, ensure_ascii=False).encode()) > MAX_SCENARIO_INPUT_BYTES:
                raise _InputTooLarge()
            if self._service is None:
                raise app.ScenarioServiceError(app.ScenarioErrorCode.SCENARIO_UNAVAILABLE)
            result = await operation(principal, self._service, correlation)
            for scope in scopes:
                Authorizer().require_scope(principal, scope, now=self._clock())
            response = CallToolResult(
                content=[TextContent(type="text", text=_summary(name, result))],
                structured_content=result.model_dump(mode="json"),
                _meta={"correlationId": correlation},
                is_error=False,
            )
            if len(response.model_dump_json(by_alias=True).encode()) > MAX_SCENARIO_OUTPUT_BYTES:
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
                "mcp_scenario tool=%s outcome=%s account_ref=%s correlation_ref=%s",
                name,
                outcome,
                _reference(account_id),
                _reference(correlation),
            )


def scenario_command(
    account_id: str, value: wire.CreateScenarioRunRequest, *, idempotency_key: str, correlation: str
) -> app.CreateScenarioRun:
    selected = value.replay
    return app.CreateScenarioRun(
        account_id=UUID(account_id),
        scenario_version_id=UUID(value.scenario_version_id),
        portfolio_snapshot_id=UUID(value.portfolio_snapshot_id),
        xray_run_id=UUID(value.xray_run_id),
        reporting_currency=CurrencyCode(value.reporting_currency),
        source_cutoff_at=value.source_cutoff_at,
        replay=None
        if selected is None
        else ScenarioReplaySelection(
            historical_input_snapshot_id=UUID(selected.historical_input_snapshot_id),
            start_date=selected.start_date,
            end_date=selected.end_date,
            market_knowledge_cutoff_at=selected.market_knowledge_cutoff_at,
            holdings_basis=selected.holdings_basis,
            knowledge_basis=selected.knowledge_basis,
        ),
        idempotency_key=idempotency_key,
        correlation_id=correlation
        if len(correlation) <= 120
        else "sha256:" + hashlib.sha256(correlation.encode()).hexdigest(),
    )


def _summary(name: str, result: ScenarioToolEnvelope[Any]) -> str:
    data = result.data
    if isinstance(result, ScenarioListToolResult) and data is not None:
        return (
            f"Read {len(data.items)} of {data.total} saved scenario definitions. "
            "Use next_cursor to continue."
        )
    if isinstance(result, ScenarioCreateToolResult) and data is not None:
        return (
            f"Scenario request {data.id} is {data.state}. "
            "Read get_scenario_result before using financial results."
        )
    if isinstance(result, ScenarioRunToolResult) and data is not None:
        if data.result is None:
            return (
                f"Scenario {data.id} is {data.state}; "
                f"financial result is {data.result_availability}."
            )
        page = data.result.components
        return (
            f"Read saved scenario {data.id}: {len(page.items)} of {page.total} "
            "financial components. Exact values, quality and source omissions are preserved."
        )
    if isinstance(result, ScenarioComparisonToolResult) and data is not None:
        basis = "compatible" if data.compatible else "incompatible; differences are unavailable"
        return (
            f"Read two saved scenarios. Bases are {basis}. The component page preserves both sides."
        )
    raise _InvalidResult()


def _payload[T: wire.ScenarioSchema](value: object, schema: type[T]) -> T:
    try:
        return schema.model_validate(to_primitive(value))
    except (DomainError, KeyError, TypeError, ValueError):
        raise _InvalidResult() from None


def _account(actual: str, expected: str) -> None:
    if actual != expected:
        raise app.ScenarioServiceError(app.ScenarioErrorCode.NOT_FOUND)


def _reference(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


class _InvalidResult(Exception):
    pass


class _InputTooLarge(ValueError):
    pass


class _OutputTooLarge(ValueError):
    pass


_ERRORS = {
    "NOT_FOUND": "The scenario resource was not found.",
    "ACCESS_DENIED": "Access to the scenario operation is denied.",
    "VALIDATION_FAILED": "The bounded scenario request is invalid.",
    "INPUT_BOUND_EXCEEDED": "The scenario input exceeds its resource bounds.",
    "CONFLICT": "The request identity or retained input conflicts.",
    "INVALID_STATE_TRANSITION": "The scenario job cannot make this transition.",
    "REVISION_MISMATCH": "The current scenario definition revision differs.",
    "REVISION_REQUIRED": "The current scenario definition revision is required.",
    "CURSOR_INVALID": "The scoped cursor is invalid or expired.",
    "RATE_LIMITED": "The scenario operation reached its configured capacity.",
    "SOURCE_UNAVAILABLE": "The pinned scenario source is unavailable.",
    "SCENARIO_UNAVAILABLE": "The scenario result or service is unavailable.",
    "RUN_EXPIRED": "The scenario run inputs have expired.",
}


def _safe_error(exc: Exception, correlation: str) -> ScenarioToolError:
    code: Any = "INTERNAL_ERROR"
    message = "The scenario operation could not complete."
    if isinstance(exc, AuthenticationError):
        code, message = "AUTHENTICATION_REQUIRED", "Authentication is required."
    elif isinstance(exc, AuthorizationError):
        code, message = "ACCESS_DENIED", "Required scenario scopes are missing."
    elif isinstance(exc, _InputTooLarge):
        code, message = "REQUEST_TOO_LARGE", "The scenario request exceeds its byte bound."
    elif isinstance(exc, _OutputTooLarge):
        code, message = "RESULT_TOO_LARGE", "The scenario result exceeds its byte bound."
    elif isinstance(exc, app.ScenarioServiceError):
        code, message = exc.code.value, _ERRORS[exc.code.value]
    elif isinstance(exc, DomainError) or (
        isinstance(exc, ValueError) and not isinstance(exc, ValidationError)
    ):
        code, message = "VALIDATION_FAILED", "The bounded scenario request is invalid."
    return ScenarioToolError(
        code=code,
        message=message,
        correlation_id=correlation,
        retryable=code in {"RATE_LIMITED", "SCENARIO_UNAVAILABLE", "SOURCE_UNAVAILABLE"},
        remediation=(
            "Wait before retrying the same operation."
            if code == "RATE_LIMITED"
            else "Use authorized inputs. Reuse the key only for identical requests."
        ),
    )
