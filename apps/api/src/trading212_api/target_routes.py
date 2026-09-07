"""Bounded authenticated target routes over the shared application service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, TypeAdapter, ValidationError
from starlette.responses import JSONResponse
from trading212_api_contracts.targets import (
    CreateTargetVersionRequest,
    CreateVirtualPortfolioRequest,
    EmptyTargetRequest,
    IdempotencyKey,
    PublishTargetRequest,
    ReplaceTargetDraftRequest,
    TargetComparisonQuery,
    TargetHierarchyNodeResponse,
    TargetHierarchyQuery,
    TargetPageQuery,
    TargetPageResponse,
    TargetValidationResponse,
    TargetVersionComparisonResponse,
    TargetVersionEventResponse,
    TargetVersionQuery,
    TargetVersionResponse,
    UpdateVirtualPortfolioRequest,
    UUIDString,
    ValidateTargetRequest,
    VirtualPortfolioQuery,
    VirtualPortfolioResponse,
)
from trading212_application import targets as application_targets
from trading212_application.targets import TargetService
from trading212_domain.serialization import to_primitive
from trading212_domain.values import CurrencyCode
from trading212_observability import AuthenticationMethod
from trading212_security.principals import AuthenticationError, Authorizer, Principal, Scope
from trading212_security.sessions import SessionManager
from trading212_security.settings import SecuritySettings

from .target_schemas import target_content

REQUEST_BYTE_LIMIT = 64 * 1024
RESPONSE_BYTE_LIMIT = 2 * 1024 * 1024
_IDEMPOTENCY = TypeAdapter(IdempotencyKey)


class TargetApiContext(Protocol):
    """Composition dependencies; routes cannot access persistence or providers."""

    @property
    def target_service(self) -> TargetService | None: ...

    @property
    def settings(self) -> SecuritySettings: ...

    @property
    def sessions(self) -> SessionManager: ...

    @property
    def clock(self) -> Callable[[], datetime]: ...


def _error(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "correlation_id": getattr(request.state, "correlation_id", "unavailable"),
                "retryable": False,
                "details": {},
            }
        },
        headers={"Cache-Control": "private, no-store"},
    )


class BoundedTargetRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def bounded(request: Request) -> Response:
            # Stream before FastAPI parses JSON; a forged or missing Content-Length
            # cannot bypass the bound, and oversized commands never enter the service.
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > REQUEST_BYTE_LIMIT:
                    return _error(
                        request, 413, "REQUEST_TOO_LARGE", "The request body is too large."
                    )
                body.extend(chunk)
            if (
                len(request.headers.get("if-none-match", "")) > 2048
                or len(request.headers.get("if-match", "")) > 2048
            ):
                return _error(request, 422, "VALIDATION_FAILED", "The request is invalid.")
            # Scalar query parameters have exactly one value. Reject duplicate
            # parameters rather than letting transport order choose the command.
            keys = list(request.query_params.keys())
            if (keys and not self.dependant.query_params) or any(
                len(request.query_params.getlist(key)) != 1 for key in keys
            ):
                return _error(request, 422, "VALIDATION_FAILED", "The request is invalid.")

            async def receive() -> dict[str, object]:
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            bounded_request = Request(request.scope, receive=receive)
            return await handler(bounded_request)

        return bounded


def target_response[T: BaseModel](
    request: Request,
    value: object,
    schema: type[T],
    *,
    etag: str | None = None,
    status_code: int = 200,
    conditional: bool = False,
) -> Response:
    """Validate the same DTO consumed by MCP before applying the HTTP byte bound."""
    headers = {"Cache-Control": "private, no-store"}
    if etag is not None:
        headers["ETag"] = etag
        supplied = request.headers.get("if-none-match", "")
        tags = {item.strip().removeprefix("W/") for item in supplied.split(",")}
        if conditional and (etag in tags or "*" in tags):
            return Response(status_code=304, headers=headers)
    try:
        payload = schema.model_validate(to_primitive(value)).model_dump_json().encode("utf-8")
    except ValidationError:
        return _error(request, 500, "INTERNAL_ERROR", "The requested operation failed.")
    if len(payload) > RESPONSE_BYTE_LIMIT:
        return _error(request, 422, "RESULT_TOO_LARGE", "The requested result is too large.")
    return Response(
        payload, status_code=status_code, media_type="application/json", headers=headers
    )


def register_target_routes(
    application: FastAPI,
    principal_dependency: Callable[..., Awaitable[Principal]],
    context_provider: Callable[[Request], TargetApiContext],
) -> None:
    principal_dep = Depends(principal_dependency)
    router = APIRouter(prefix="/api/v1", tags=["targets"], route_class=BoundedTargetRoute)

    def read(request: Request, principal: Principal) -> TargetService:
        context = context_provider(request)
        Authorizer().require_scope(principal, Scope.TARGETS_READ, now=context.clock())
        return available(context)

    def available(context: TargetApiContext) -> TargetService:
        if context.target_service is None:
            raise application_targets.TargetServiceError(
                application_targets.TargetServiceErrorCode.TARGETS_UNAVAILABLE,
                "Target persistence is unavailable.",
            )
        return context.target_service

    async def command(request: Request, principal: Principal) -> tuple[TargetService, str, str]:
        context = context_provider(request)
        Authorizer().require_scope(principal, Scope.TARGETS_WRITE, now=context.clock())
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
        return available(context), key, request.state.correlation_id

    @router.get(
        "/virtual-portfolios",
        response_model=TargetPageResponse[VirtualPortfolioResponse],
        operation_id="list_virtual_portfolios",
    )
    async def list_virtual_portfolios(
        request: Request,
        query: Annotated[VirtualPortfolioQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        service = read(request, principal)
        value = await service.list_virtual_portfolios(
            principal,
            query=application_targets.VirtualPortfolioQuery(
                cursor=query.cursor,
                limit=query.limit,
                account_id=query.account_id,
                state=application_targets.VirtualPortfolioStateFilter(query.state),
                sort=application_targets.VirtualPortfolioSort(query.sort),
                search=query.search,
            ),
        )
        return target_response(request, value, TargetPageResponse[VirtualPortfolioResponse])

    @router.post(
        "/virtual-portfolios",
        status_code=201,
        response_model=VirtualPortfolioResponse,
        operation_id="create_virtual_portfolio",
    )
    async def create_virtual_portfolio(
        request: Request,
        body: CreateVirtualPortfolioRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        service, key, correlation = await command(request, principal)
        value = await service.create_virtual_portfolio(
            principal,
            application_targets.CreateVirtualPortfolioCommand(
                name=body.name,
                reporting_currency=CurrencyCode(body.reporting_currency),
                account_id=body.account_id,
                description=body.description,
            ),
            idempotency_key=key,
            correlation_id=correlation,
        )
        return target_response(
            request, value, VirtualPortfolioResponse, etag=value.etag, status_code=201
        )

    @router.get(
        "/virtual-portfolios/{portfolio_id}",
        response_model=VirtualPortfolioResponse,
        operation_id="get_virtual_portfolio",
    )
    async def get_virtual_portfolio(
        request: Request,
        portfolio_id: UUIDString,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await read(request, principal).get_virtual_portfolio(principal, portfolio_id)
        return target_response(
            request, value, VirtualPortfolioResponse, etag=value.etag, conditional=True
        )

    @router.patch(
        "/virtual-portfolios/{portfolio_id}",
        response_model=VirtualPortfolioResponse,
        operation_id="update_virtual_portfolio",
    )
    async def update_virtual_portfolio(
        request: Request,
        portfolio_id: UUIDString,
        body: UpdateVirtualPortfolioRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        service, key, correlation = await command(request, principal)
        value = await service.update_virtual_portfolio(
            principal,
            portfolio_id,
            application_targets.UpdateVirtualPortfolioCommand(
                name=body.name, description=body.description
            ),
            if_match=request.headers.get("if-match"),
            idempotency_key=key,
            correlation_id=correlation,
        )
        return target_response(request, value, VirtualPortfolioResponse, etag=value.etag)

    @router.post(
        "/virtual-portfolios/{portfolio_id}/archive",
        response_model=VirtualPortfolioResponse,
        operation_id="archive_virtual_portfolio",
    )
    async def archive_virtual_portfolio(
        request: Request,
        portfolio_id: UUIDString,
        body: EmptyTargetRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        service, key, correlation = await command(request, principal)
        value = await service.archive_virtual_portfolio(
            principal,
            portfolio_id,
            if_match=request.headers.get("if-match"),
            idempotency_key=key,
            correlation_id=correlation,
        )
        return target_response(request, value, VirtualPortfolioResponse, etag=value.etag)

    @router.get(
        "/virtual-portfolios/{portfolio_id}/target-versions",
        response_model=TargetPageResponse[TargetVersionResponse],
        operation_id="list_target_versions",
    )
    async def list_target_versions(
        request: Request,
        portfolio_id: UUIDString,
        query: Annotated[TargetVersionQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await read(request, principal).list_target_versions(
            principal,
            portfolio_id,
            query=application_targets.TargetVersionQuery(
                cursor=query.cursor,
                limit=query.limit,
                state=application_targets.TargetVersionStateFilter(query.state),
            ),
        )
        return target_response(request, value, TargetPageResponse[TargetVersionResponse])

    @router.post(
        "/virtual-portfolios/{portfolio_id}/target-versions",
        status_code=201,
        response_model=TargetVersionResponse,
        operation_id="create_target_version",
    )
    async def create_target_version(
        request: Request,
        portfolio_id: UUIDString,
        body: CreateTargetVersionRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        service, key, correlation = await command(request, principal)
        value = await service.create_target_version(
            principal,
            portfolio_id,
            application_targets.CreateTargetVersionCommand(
                effective_at=body.effective_at,
                source_version_id=body.source_version_id,
                content=target_content(body.content) if body.content is not None else None,
            ),
            if_match=request.headers.get("if-match"),
            idempotency_key=key,
            correlation_id=correlation,
        )
        return target_response(
            request, value, TargetVersionResponse, etag=value.etag, status_code=201
        )

    @router.get(
        "/target-versions/{version_id}",
        response_model=TargetVersionResponse,
        operation_id="get_target_version",
    )
    async def get_target_version(
        request: Request,
        version_id: UUIDString,
        principal: Principal = principal_dep,
    ) -> Response:
        value = await read(request, principal).get_target_version(principal, version_id)
        return target_response(
            request, value, TargetVersionResponse, etag=value.etag, conditional=True
        )

    @router.patch(
        "/target-versions/{version_id}",
        response_model=TargetVersionResponse,
        operation_id="replace_target_draft",
    )
    async def replace_target_draft(
        request: Request,
        version_id: UUIDString,
        body: ReplaceTargetDraftRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        service, key, correlation = await command(request, principal)
        value = await service.replace_target_draft(
            principal,
            version_id,
            application_targets.ReplaceTargetDraftCommand(
                effective_at=body.effective_at, content=target_content(body.content)
            ),
            if_match=request.headers.get("if-match"),
            idempotency_key=key,
            correlation_id=correlation,
        )
        return target_response(request, value, TargetVersionResponse, etag=value.etag)

    @router.post(
        "/target-versions/{version_id}/validate",
        response_model=TargetValidationResponse,
        operation_id="validate_target_version",
    )
    async def validate_target_version(
        request: Request,
        version_id: UUIDString,
        body: ValidateTargetRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        service, key, correlation = await command(request, principal)
        value = await service.validate_target_version(
            principal,
            version_id,
            application_targets.ValidateTargetCommand(normalize=body.normalize),
            if_match=request.headers.get("if-match"),
            idempotency_key=key,
            correlation_id=correlation,
        )
        return target_response(request, value, TargetValidationResponse, etag=value.etag)

    @router.post(
        "/target-versions/{version_id}/publish",
        response_model=TargetVersionResponse,
        operation_id="publish_target_version",
    )
    async def publish_target_version(
        request: Request,
        version_id: UUIDString,
        body: PublishTargetRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        service, key, correlation = await command(request, principal)
        value = await service.publish_target_version(
            principal,
            version_id,
            application_targets.PublishTargetCommand(validation_id=body.validation_id),
            if_match=request.headers.get("if-match"),
            idempotency_key=key,
            correlation_id=correlation,
        )
        return target_response(request, value, TargetVersionResponse, etag=value.etag)

    @router.post(
        "/target-versions/{version_id}/archive",
        response_model=TargetVersionResponse,
        operation_id="archive_target_version",
    )
    async def archive_target_version(
        request: Request,
        version_id: UUIDString,
        body: EmptyTargetRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        service, key, correlation = await command(request, principal)
        value = await service.archive_target_version(
            principal,
            version_id,
            if_match=request.headers.get("if-match"),
            idempotency_key=key,
            correlation_id=correlation,
        )
        return target_response(request, value, TargetVersionResponse, etag=value.etag)

    @router.get(
        "/target-versions/{version_id}/events",
        response_model=TargetPageResponse[TargetVersionEventResponse],
        operation_id="list_target_version_events",
    )
    async def list_target_version_events(
        request: Request,
        version_id: UUIDString,
        query: Annotated[TargetPageQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await read(request, principal).list_target_version_events(
            principal,
            version_id,
            query=application_targets.TargetPageQuery(cursor=query.cursor, limit=query.limit),
        )
        return target_response(request, value, TargetPageResponse[TargetVersionEventResponse])

    @router.get(
        "/virtual-portfolios/{portfolio_id}/target-comparison",
        response_model=TargetVersionComparisonResponse,
        operation_id="compare_target_versions",
    )
    async def compare_target_versions(
        request: Request,
        portfolio_id: UUIDString,
        query: Annotated[TargetComparisonQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await read(request, principal).compare_target_versions(
            principal, portfolio_id, query.left_version_id, query.right_version_id
        )
        return target_response(request, value, TargetVersionComparisonResponse)

    @router.get(
        "/target-versions/{version_id}/nodes",
        response_model=TargetPageResponse[TargetHierarchyNodeResponse],
        operation_id="list_target_nodes",
    )
    async def list_target_nodes(
        request: Request,
        version_id: UUIDString,
        query: Annotated[TargetHierarchyQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await read(request, principal).list_target_nodes(
            principal,
            version_id,
            parent_node_id=query.parent_node_id,
            query=application_targets.TargetPageQuery(cursor=query.cursor, limit=query.limit),
        )
        return target_response(request, value, TargetPageResponse[TargetHierarchyNodeResponse])

    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        parameters: list[dict[str, object]] = []
        if (route.methods or set()) & {"POST", "PATCH"}:
            parameters.append(
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
                }
            )
            parameters.append(
                {
                    "name": "X-CSRF-Token",
                    "in": "header",
                    "required": False,
                    "description": (
                        "Required with a session cookie and a configured trusted Origin."
                    ),
                    "schema": {"type": "string", "maxLength": 2048},
                }
            )
            if route.operation_id != "create_virtual_portfolio":
                parameters.append(
                    {
                        "name": "If-Match",
                        "in": "header",
                        "required": False,
                        "description": (
                            "Strong aggregate ETag required for a new command; "
                            "an authorized identical replay is resolved first."
                        ),
                        "schema": {"type": "string", "maxLength": 2048},
                    }
                )
        elif route.operation_id in {"get_virtual_portfolio", "get_target_version"}:
            parameters.append(
                {
                    "name": "If-None-Match",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string", "maxLength": 2048},
                }
            )
        route.openapi_extra = {"parameters": parameters}
    application.include_router(router)
