"""Authorized P2-01 MCP projections over the shared target application service."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal, TypeVar

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel
from trading212_api_contracts.targets import (
    FlattenedTargetNodeResponse,
    TargetHierarchyNodeResponse,
    TargetValidationResponse,
    VirtualPortfolioResponse,
)
from trading212_application.queries import CollectionSnapshotCapacityError, CursorValidationError
from trading212_application.targets import (
    TargetPageQuery,
    TargetService,
    TargetServiceError,
    TargetServiceErrorCode,
    TargetVersionView,
    VirtualPortfolioQuery,
    VirtualPortfolioSort,
    VirtualPortfolioStateFilter,
)
from trading212_domain.errors import DomainError
from trading212_domain.serialization import canonical_json
from trading212_domain.targets import TargetMappingState
from trading212_security.principals import (
    AuthenticationError,
    AuthorizationError,
    Authorizer,
    Principal,
    Scope,
)

from .auth import PrincipalResolver
from .gateway import _correlation_id
from .target_schemas import (
    TargetPagination,
    TargetReadMethod,
    TargetReadNode,
    TargetReadQuality,
    TargetToolError,
    TargetToolErrorCode,
    TargetVersionMetadata,
    VirtualPieData,
    VirtualPieResult,
    VirtualPiesData,
    VirtualPiesResult,
)

ResultT = TypeVar("ResultT", bound=BaseModel)
MAX_TARGET_INPUT_BYTES = 65_536
MAX_TARGET_OUTPUT_BYTES = 2_097_152


class TargetMcpGateway:
    def __init__(
        self,
        *,
        service: TargetService | None,
        principals: PrincipalResolver,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._principals = principals
        self._clock = clock or (lambda: datetime.now(UTC))
        self._authorizer = Authorizer()
        self._logger = logging.getLogger("trading212_mcp.audit")

    async def list_virtual_pies(
        self,
        account_id: str | None,
        *,
        cursor: str | None,
        limit: int,
        state: Literal["draft", "active", "archived", "all"],
        search: str | None,
        sort: Literal["name_asc", "updated_desc"],
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(principal: Principal, service: TargetService) -> VirtualPiesResult:
            page = await service.list_virtual_portfolios(
                principal,
                query=VirtualPortfolioQuery(
                    account_id=account_id,
                    cursor=cursor,
                    limit=limit,
                    state=VirtualPortfolioStateFilter(state),
                    sort=VirtualPortfolioSort(sort),
                    search=search,
                ),
            )
            # The exact null scope denotes templates, never a cross-account list.
            if any(item.account_id != account_id for item in page.items):
                raise TargetServiceError(TargetServiceErrorCode.NOT_FOUND, "Scope mismatch.")
            values = [
                VirtualPortfolioResponse.model_validate_json(canonical_json(item))
                for item in page.items
            ]
            currencies = {item.reporting_currency for item in page.items}
            updated = max((item.updated_at for item in page.items), default=None)
            return VirtualPiesResult(
                data=VirtualPiesData(portfolios=values),
                as_of=updated,
                reporting_currency=next(iter(currencies)) if len(currencies) == 1 else None,
                data_quality=TargetReadQuality(
                    state="configuration",
                    disclosure="Owner target configuration; no broker freshness is asserted.",
                ),
                calculation=TargetReadMethod(),
                pagination=_pagination(page.next_cursor, page.limit, page.total, len(page.items)),
                error=None,
            )

        return await self._execute(
            "list_virtual_pies",
            account_id,
            context,
            VirtualPiesResult,
            operation,
            {
                "account_id": account_id,
                "cursor": cursor,
                "limit": limit,
                "state": state,
                "search": search,
                "sort": sort,
            },
        )

    async def get_virtual_pie(
        self,
        account_id: str | None,
        virtual_portfolio_id: str,
        *,
        target_version_id: str | None,
        parent_node_id: str | None,
        cursor: str | None,
        limit: int,
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(principal: Principal, service: TargetService) -> VirtualPieResult:
            read = await service.get_virtual_portfolio_targets(
                principal,
                virtual_portfolio_id,
                account_id=account_id,
                target_version_id=target_version_id,
                parent_node_id=parent_node_id,
                query=TargetPageQuery(cursor=cursor, limit=limit),
            )
            portfolio = read.portfolio
            if portfolio.account_id != account_id:
                raise TargetServiceError(TargetServiceErrorCode.NOT_FOUND, "Scope mismatch.")
            selected = read.version
            nodes: list[TargetReadNode] = []
            page = read.nodes
            pagination = _pagination(page.next_cursor, page.limit, page.total, len(page.items))
            if selected is not None:
                if selected.portfolio_id != virtual_portfolio_id:
                    raise TargetServiceError(TargetServiceErrorCode.NOT_FOUND, "Version mismatch.")
                calculated = {item.node.key: item for item in selected.flattened_nodes}
                for item in page.items:
                    flattened = calculated.get(item.node.key)
                    nodes.append(
                        TargetReadNode(
                            hierarchy=TargetHierarchyNodeResponse.model_validate_json(
                                canonical_json(item)
                            ),
                            calculated=FlattenedTargetNodeResponse.model_validate_json(
                                canonical_json(flattened)
                            )
                            if flattened
                            else None,
                        )
                    )
            elif parent_node_id is not None or cursor is not None or page.items:
                raise TargetServiceError(TargetServiceErrorCode.NOT_FOUND, "No selected target.")
            validation = selected.latest_validation if selected else None
            unresolved = (
                sum(
                    1
                    for node in selected.content.nodes
                    if node.holding is not None
                    and node.holding.state is not TargetMappingState.RESOLVED
                )
                if selected
                else 0
            )
            quality_state: Literal[
                "configuration", "unvalidated", "valid", "invalid", "partial"
            ] = "unvalidated"
            if selected is not None and selected.has_current_validation and validation is not None:
                quality_state = (
                    "invalid" if not validation.valid else "partial" if unresolved else "valid"
                )
            return VirtualPieResult(
                data=VirtualPieData(
                    portfolio=VirtualPortfolioResponse.model_validate_json(
                        canonical_json(portfolio)
                    ),
                    target_version=_version_metadata(selected) if selected else None,
                    nodes=nodes,
                    validation=TargetValidationResponse.model_validate_json(
                        canonical_json(validation)
                    )
                    if validation
                    else None,
                    target_availability="available" if selected else "unavailable",
                    target_reason=None if selected else "NO_ACTIVE_TARGET",
                    parent_node_id=parent_node_id,
                ),
                as_of=selected.updated_at if selected else portfolio.updated_at,
                reporting_currency=portfolio.reporting_currency,
                data_quality=TargetReadQuality(
                    state=quality_state,
                    validation_id=validation.id if validation else None,
                    issue_count=len(validation.issues) if validation else 0,
                    unresolved_mapping_count=unresolved,
                    disclosure=(
                        "Target validation describes configuration only; "
                        "valuation, drift, and planning are separate calculations."
                    ),
                ),
                calculation=TargetReadMethod(
                    source_version_id=selected.id if selected else None,
                    source_content_digest=selected.content_digest if selected else None,
                ),
                pagination=pagination,
                error=None,
            )

        return await self._execute(
            "get_virtual_pie",
            account_id,
            context,
            VirtualPieResult,
            operation,
            {
                "account_id": account_id,
                "virtual_portfolio_id": virtual_portfolio_id,
                "target_version_id": target_version_id,
                "parent_node_id": parent_node_id,
                "cursor": cursor,
                "limit": limit,
            },
        )

    async def _execute(
        self,
        tool_name: str,
        account_id: str | None,
        context: Context[Any, Any],
        result_type: type[ResultT],
        operation: Callable[[Principal, TargetService], Awaitable[ResultT]],
        arguments: dict[str, str | int | None],
    ) -> CallToolResult:
        correlation_id = _correlation_id(context)
        outcome = "INTERNAL_ERROR"
        try:
            principal = await self._principals.resolve()
            for scope in (Scope.PORTFOLIO_READ, Scope.TARGETS_READ):
                self._authorizer.require_scope(principal, scope, now=self._clock())
            if (
                len(json.dumps(arguments, ensure_ascii=False).encode("utf-8"))
                > MAX_TARGET_INPUT_BYTES
            ):
                raise _InputTooLargeError()
            if self._service is None:
                raise TargetServiceError(
                    TargetServiceErrorCode.TARGETS_UNAVAILABLE, "Targets unavailable."
                )
            result = await operation(principal, self._service)
            result_type.model_validate(result)
            response = CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text="Retrieved authorized virtual portfolio configuration.",
                    )
                ],
                structured_content=result.model_dump(mode="json"),
                _meta={"correlationId": correlation_id},
                is_error=False,
            )
            if (
                len(response.model_dump_json(by_alias=True).encode("utf-8"))
                > MAX_TARGET_OUTPUT_BYTES
            ):
                raise _OutputTooLargeError()
            outcome = "success"
            return response
        except Exception as exc:
            error = _safe_target_error(exc, correlation_id)
            outcome = error.code
            result = result_type.model_validate(
                {
                    "data": None,
                    "as_of": None,
                    "reporting_currency": None,
                    "data_quality": None,
                    "calculation": None,
                    "pagination": None,
                    "error": error.model_dump(mode="json"),
                }
            )
            return CallToolResult(
                content=[TextContent(type="text", text=f"{error.code}: {error.message}")],
                structured_content=result.model_dump(mode="json"),
                _meta={"correlationId": correlation_id},
                is_error=True,
            )
        finally:
            self._logger.info(
                "mcp_target_read tool=%s outcome=%s account_ref=%s correlation_ref=%s",
                tool_name,
                outcome,
                _reference(account_id or "template"),
                _reference(correlation_id),
            )


class _InputTooLargeError(ValueError):
    pass


class _OutputTooLargeError(ValueError):
    pass


def _reference(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _pagination(cursor: str | None, limit: int, total: int, returned: int) -> TargetPagination:
    return TargetPagination(
        next_cursor=cursor,
        limit=limit,
        total=total,
        truncated=cursor is not None or returned < total,
    )


def _version_metadata(version: TargetVersionView) -> TargetVersionMetadata:
    return TargetVersionMetadata.model_validate_json(
        canonical_json(
            {
                "id": version.id,
                "portfolio_id": version.portfolio_id,
                "version_number": version.version_number,
                "revision": version.revision,
                "reporting_currency": version.reporting_currency,
                "effective_at": version.effective_at,
                "state": version.state,
                "created_at": version.created_at,
                "updated_at": version.updated_at,
                "published_at": version.published_at,
                "content_digest": version.content_digest,
                "source_version_id": version.source_version_id,
                "constraints": version.content.constraints,
                "exclusions": version.content.exclusions,
                "effective_weight_rounding_residual": version.effective_weight_rounding_residual,
            }
        )
    )


def _safe_target_error(exc: Exception, correlation_id: str) -> TargetToolError:
    code: TargetToolErrorCode = "INTERNAL_ERROR"
    message = "The private target read could not be completed."
    retryable = False
    if isinstance(exc, AuthenticationError):
        code, message = "AUTHENTICATION_REQUIRED", "Authentication is required."
    elif isinstance(exc, AuthorizationError):
        code, message = "ACCESS_DENIED", "Required portfolio and target scopes are missing."
    elif isinstance(exc, CursorValidationError):
        code, message = "CURSOR_INVALID", "The scoped pagination cursor is invalid."
    elif isinstance(exc, CollectionSnapshotCapacityError):
        code, message, retryable = (
            "COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED",
            "Active pagination capacity is exhausted.",
            True,
        )
    elif isinstance(exc, _InputTooLargeError):
        code, message = "REQUEST_TOO_LARGE", "The target request exceeds its byte bound."
    elif isinstance(exc, _OutputTooLargeError):
        code, message = "RESULT_TOO_LARGE", "The target result exceeds its byte bound."
    elif isinstance(exc, TargetServiceError):
        if exc.code is TargetServiceErrorCode.NOT_FOUND:
            code, message = "NOT_FOUND", "The requested private target resource was not found."
        elif exc.code is TargetServiceErrorCode.TARGETS_UNAVAILABLE:
            code, message, retryable = (
                "TARGETS_UNAVAILABLE",
                "Target services are unavailable.",
                True,
            )
        elif exc.code is TargetServiceErrorCode.ACCESS_DENIED:
            code, message = "ACCESS_DENIED", "Access denied."
        elif exc.code is TargetServiceErrorCode.RESULT_TOO_LARGE:
            code, message = "RESULT_TOO_LARGE", "The target result exceeds its byte bound."
        elif exc.code is TargetServiceErrorCode.VALIDATION_FAILED:
            code, message = "VALIDATION_FAILED", "The bounded target request is invalid."
    elif isinstance(exc, LookupError):
        code, message = "NOT_FOUND", "The requested private target resource was not found."
    elif isinstance(exc, (ValueError, DomainError)):
        code, message = "VALIDATION_FAILED", "The bounded target request is invalid."
    return TargetToolError(
        code=code,
        message=message,
        correlation_id=correlation_id,
        retryable=retryable,
        remediation=(
            "Use an authorized scope and bounded request; "
            "restart invalid pagination or retry unavailable services."
        ),
    )
