"""Two fixed X-ray reads sharing the authorized canonical application service."""

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
from trading212_api_contracts import xray as wire
from trading212_application import xray as app
from trading212_application.queries import CollectionSnapshotCapacityError, CursorValidationError
from trading212_application.xray_projection import xray_public_primitive
from trading212_domain.errors import DomainError
from trading212_domain.values import CurrencyCode
from trading212_domain.xray import XrayDimension
from trading212_security.principals import (
    AuthenticationError,
    AuthorizationError,
    Authorizer,
    Principal,
    Scope,
)

from .auth import PrincipalResolver
from .gateway import _correlation_id
from .xray_schemas import (
    XrayExposureToolResult,
    XrayOverlapToolResult,
    XrayToolEnvelope,
    XrayToolError,
    XrayToolSelection,
)


class XrayMcpGateway:
    def __init__(
        self,
        *,
        service: app.XrayService | None,
        principals: PrincipalResolver,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._principals = principals
        self._clock = clock or (lambda: datetime.now(UTC))
        self._logger = logging.getLogger("trading212_mcp.audit")

    async def get_effective_exposure(
        self,
        account_id: str,
        query: wire.XrayMcpEffectiveExposureQuery,
        *,
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: app.XrayService
        ) -> XrayExposureToolResult:
            value = await service.get_effective_exposure(
                principal,
                account_id,
                query=app.EffectiveExposureQuery(
                    request=app.XrayRunRequest(
                        snapshot_id=query.snapshot_id,
                        source_cutoff_at=query.source_cutoff_at,
                        currency=app.ExplicitCurrency(
                            reporting_currency=CurrencyCode(query.reporting_currency)
                        ),
                    ),
                    options=app.Exposures(dimension=XrayDimension(query.dimension)),
                    cursor=query.cursor,
                    limit=query.limit,
                ),
            )
            data = _payload(value, wire.XrayExposuresResponse, account_id)
            return XrayExposureToolResult(
                data=data,
                error=None,
                selection=XrayToolSelection(
                    total=data.exposures.total,
                    returned=len(data.exposures.items),
                    omitted=data.exposures.total - len(data.exposures.items),
                ),
            )

        return await self._execute(
            "get_effective_exposure", account_id, query, context, XrayExposureToolResult, operation
        )

    async def get_etf_overlap(
        self, account_id: str, query: wire.XrayMcpOverlapQuery, *, context: Context[Any, Any]
    ) -> CallToolResult:
        async def operation(
            principal: Principal, service: app.XrayService
        ) -> XrayOverlapToolResult:
            value = await service.get_etf_overlap(
                principal,
                account_id,
                query=app.EtfOverlapQuery(
                    request=app.XrayRunRequest(
                        snapshot_id=query.snapshot_id,
                        source_cutoff_at=query.source_cutoff_at,
                        currency=app.SnapshotCurrency(),
                    ),
                    options=app.McpTopPair(
                        left_fund_id=query.left_fund_id,
                        right_fund_id=query.right_fund_id,
                        top_n=query.top_n,
                    ),
                ),
            )
            data = _payload(value, wire.XrayMcpTopPairResponse, account_id)
            return XrayOverlapToolResult(
                data=data,
                error=None,
                selection=XrayToolSelection(
                    total=data.total_count, returned=data.returned_count, omitted=data.omitted_count
                ),
            )

        return await self._execute(
            "get_etf_overlap", account_id, query, context, XrayOverlapToolResult, operation
        )

    async def _execute(
        self,
        name: str,
        account_id: str,
        query: wire.XraySchema,
        context: Context[Any, Any],
        result_type: type[XrayToolEnvelope[Any]],
        operation: Callable[[Principal, app.XrayService], Awaitable[XrayToolEnvelope[Any]]],
    ) -> CallToolResult:
        correlation = _correlation_id(context)
        outcome = "INTERNAL_ERROR"
        try:
            principal = await self._principals.resolve()
            scopes = [Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ]
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
                raise app.XrayServiceError(
                    app.XrayServiceErrorCode.XRAY_UNAVAILABLE,
                    "Xray service unavailable.",
                )
            value = await operation(principal, self._service)
            result_type.model_validate(value)
            response = CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=(
                            "Retrieved authorized X-ray analytics with "
                            "explicit coverage, provenance and unresolved exposure."
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
                "mcp_X-ray tool=%s outcome=%s account_ref=%s correlation_ref=%s",
                name,
                outcome,
                hashlib.sha256(account_id.encode()).hexdigest()[:16],
                hashlib.sha256(correlation.encode()).hexdigest()[:16],
            )


def _payload[T: wire.XraySchema](value: object, schema: type[T], account_id: str) -> T:
    try:
        payload = xray_public_primitive(value)
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


def _safe_error(exc: Exception, correlation: str) -> XrayToolError:
    code: Any = "INTERNAL_ERROR"
    message = "The X-ray operation could not complete."
    retryable = False
    if isinstance(exc, AuthenticationError):
        code, message = "AUTHENTICATION_REQUIRED", "Authentication is required."
    elif isinstance(exc, AuthorizationError):
        code, message = "ACCESS_DENIED", "Required X-ray scopes are missing."
    elif isinstance(exc, CursorValidationError):
        code, message = "CURSOR_INVALID", "The scoped pagination cursor is invalid."
    elif isinstance(exc, CollectionSnapshotCapacityError):
        code, message, retryable = (
            "COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED",
            "Active pagination capacity is exhausted.",
            True,
        )
    elif isinstance(exc, _InputTooLarge):
        code, message = "REQUEST_TOO_LARGE", "The X-ray request exceeds its byte bound."
    elif isinstance(exc, _OutputTooLarge):
        code, message = "RESULT_TOO_LARGE", "The X-ray result exceeds its byte bound."
    elif isinstance(exc, app.XrayServiceError):
        messages = {
            "NOT_FOUND": "The requested X-ray resource was not found.",
            "ACCESS_DENIED": "Access to this X-ray resource is denied.",
            "VALIDATION_FAILED": "The X-ray request is invalid.",
            "INPUT_SNAPSHOT_MISMATCH": "The retained input does not match the requested scope.",
            "XRAY_UNAVAILABLE": "The X-ray service is unavailable.",
            "RESULT_TOO_LARGE": "The X-ray result exceeds its byte bound.",
        }
        if exc.code.value in messages:
            code, message = exc.code.value, messages[exc.code.value]
            retryable = code == "XRAY_UNAVAILABLE"
    elif isinstance(exc, (ValueError, DomainError)) and not isinstance(exc, ValidationError):
        code, message = "VALIDATION_FAILED", "The bounded X-ray request is invalid."
    return XrayToolError(
        code=code,
        message=message,
        correlation_id=correlation,
        retryable=retryable,
        remediation=(
            "Use an authorized account, retained snapshot and explicit currency and source cutoff."
        ),
    )
