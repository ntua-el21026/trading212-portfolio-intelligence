"""Fourteen authorized reference reads and private benchmark definition commands."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import TypeAdapter
from trading212_api_contracts import sources as wire
from trading212_api_contracts.targets import IdempotencyKey, UUIDString
from trading212_application import sources as app
from trading212_observability import AuthenticationMethod
from trading212_security.principals import AuthenticationError, Authorizer, Principal, Scope
from trading212_security.sessions import SessionManager
from trading212_security.settings import SecuritySettings

from .source_schemas import benchmark_content, fx_status_query, source_response, source_status_query
from .target_routes import BoundedTargetRoute

_IDEMPOTENCY = TypeAdapter(IdempotencyKey)


class SourceApiContext(Protocol):
    @property
    def source_service(self) -> app.SourceService | None: ...
    @property
    def settings(self) -> SecuritySettings: ...
    @property
    def sessions(self) -> SessionManager: ...
    @property
    def clock(self) -> Callable[[], datetime]: ...


def register_source_routes(
    application: FastAPI,
    principal_dependency: Callable[[Request], Awaitable[Principal]],
    context_provider: Callable[[Request], SourceApiContext],
) -> None:
    async def csrf(request: Request) -> None:
        if getattr(request.state, "authentication_method", None) != AuthenticationMethod.SESSION:
            return
        context = context_provider(request)
        cookie = request.cookies.get("t212pi_session")
        token = request.headers.get("x-csrf-token")
        if (
            not cookie
            or len(cookie) > 2048
            or not token
            or len(token) > 2048
            or request.headers.get("origin") not in context.settings.allowed_origins
        ):
            raise AuthenticationError("Session command authentication is required.")
        await context.sessions.validate_csrf(cookie, token)

    class AuthorizedSourceRoute(BoundedTargetRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def authenticated(request: Request) -> Response:
                # Authentication and fixed capability checks precede parsing any
                # caller-controlled path, query or body; resource ownership remains
                # the injected service's responsibility before disclosure/replay.
                principal = await principal_dependency(request)
                context = context_provider(request)
                required = [Scope.ANALYTICS_READ]
                if request.method == "POST":
                    required.append(Scope.TARGETS_WRITE)
                if "/accounts/" in self.path or "account_id" in request.query_params:
                    required.append(Scope.PORTFOLIO_READ)
                for scope in required:
                    Authorizer().require_scope(principal, scope, now=context.clock())
                if request.method == "POST":
                    await csrf(request)
                request.state.source_principal = principal
                return await handler(request)

            return authenticated

    async def principal_from_request(request: Request) -> Principal:
        principal = request.state.source_principal
        if not isinstance(principal, Principal):
            raise AuthenticationError("Authentication is required.")
        return principal

    principal_dep = Depends(principal_from_request)
    router = APIRouter(prefix="/api/v1", tags=["sources"], route_class=AuthorizedSourceRoute)

    def service(request: Request) -> app.SourceService:
        result = context_provider(request).source_service
        if result is None:
            raise app.SourceServiceError(
                app.SourceServiceErrorCode.PROVIDER_UNAVAILABLE,
                "Retained reference source persistence is unavailable.",
            )
        return result

    def command(request: Request) -> tuple[app.SourceService, str, str]:
        key = _IDEMPOTENCY.validate_python(request.headers.get("x-idempotency-key"))
        return service(request), key, request.state.correlation_id

    @router.get(
        "/accounts/{account_id}/market-sources",
        response_model=wire.MarketSourceStatus,
        operation_id="get_market_source_status",
    )
    async def get_market_source_status(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.SourceStatusQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_market_source_status(
            principal, account_id, query=source_status_query(query)
        )
        return source_response(request, value, wire.MarketSourceStatus)

    @router.get(
        "/accounts/{account_id}/fx-sources",
        response_model=wire.FxSourceStatus,
        operation_id="get_fx_source_status",
    )
    async def get_fx_source_status(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.FxSourceStatusQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_fx_source_status(
            principal, account_id, query=fx_status_query(query)
        )
        return source_response(request, value, wire.FxSourceStatus)

    @router.get(
        "/accounts/{account_id}/benchmark-sources",
        response_model=wire.BenchmarkSourceStatus,
        operation_id="get_benchmark_source_status",
    )
    async def get_benchmark_source_status(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.SourceStatusQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_benchmark_source_status(
            principal, account_id, query=source_status_query(query)
        )
        return source_response(request, value, wire.BenchmarkSourceStatus)

    @router.get(
        "/price-snapshots/{snapshot_id}",
        response_model=wire.PriceSnapshotHeader,
        operation_id="get_price_snapshot",
    )
    async def get_price_snapshot(
        request: Request,
        snapshot_id: UUIDString,
        query: Annotated[wire.SourceDetailQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_price_snapshot(
            principal, snapshot_id, account_id=query.account_id
        )
        return source_response(request, value, wire.PriceSnapshotHeader)

    @router.get(
        "/fx-snapshots/{snapshot_id}",
        response_model=wire.FxSnapshotHeader,
        operation_id="get_fx_snapshot",
    )
    async def get_fx_snapshot(
        request: Request,
        snapshot_id: UUIDString,
        query: Annotated[wire.SourceDetailQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_fx_snapshot(
            principal, snapshot_id, account_id=query.account_id
        )
        return source_response(request, value, wire.FxSnapshotHeader)

    @router.get(
        "/benchmark-snapshots/{snapshot_id}",
        response_model=wire.BenchmarkSnapshotHeader,
        operation_id="get_benchmark_snapshot",
    )
    async def get_benchmark_snapshot(
        request: Request,
        snapshot_id: UUIDString,
        query: Annotated[wire.SourceDetailQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_benchmark_snapshot(
            principal, snapshot_id, account_id=query.account_id
        )
        return source_response(request, value, wire.BenchmarkSnapshotHeader)

    @router.get(
        "/price-snapshots/{snapshot_id}/observations",
        response_model=wire.SourcePage[wire.PriceObservation],
        operation_id="list_price_observations",
    )
    async def list_price_observations(
        request: Request,
        snapshot_id: UUIDString,
        query: Annotated[wire.SourceObservationQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_price_observations(
            principal, snapshot_id, query=app.SourceObservationQuery(**query.model_dump())
        )
        return source_response(request, value, wire.SourcePage[wire.PriceObservation])

    @router.get(
        "/fx-snapshots/{snapshot_id}/observations",
        response_model=wire.SourcePage[wire.FxObservation],
        operation_id="list_fx_observations",
    )
    async def list_fx_observations(
        request: Request,
        snapshot_id: UUIDString,
        query: Annotated[wire.SourceObservationQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_fx_observations(
            principal, snapshot_id, query=app.SourceObservationQuery(**query.model_dump())
        )
        return source_response(request, value, wire.SourcePage[wire.FxObservation])

    @router.get(
        "/benchmark-snapshots/{snapshot_id}/observations",
        response_model=wire.SourcePage[wire.BenchmarkObservation],
        operation_id="list_benchmark_observations",
    )
    async def list_benchmark_observations(
        request: Request,
        snapshot_id: UUIDString,
        query: Annotated[wire.SourceObservationQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_benchmark_observations(
            principal, snapshot_id, query=app.SourceObservationQuery(**query.model_dump())
        )
        return source_response(request, value, wire.SourcePage[wire.BenchmarkObservation])

    @router.get(
        "/benchmark-definitions",
        response_model=wire.SourcePage[wire.BenchmarkDefinitionSummary],
        operation_id="list_benchmark_definitions",
    )
    async def list_benchmark_definitions(
        request: Request,
        query: Annotated[wire.BenchmarkDefinitionQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_benchmark_definitions(
            principal,
            query=app.BenchmarkDefinitionQuery(
                **query.model_dump(exclude={"state", "sort"}),
                state=app.BenchmarkStateFilter(query.state),
                sort=app.BenchmarkSort(query.sort),
            ),
        )
        return source_response(request, value, wire.SourcePage[wire.BenchmarkDefinitionSummary])

    @router.post(
        "/benchmark-definitions",
        status_code=201,
        response_model=wire.BenchmarkDefinitionDetail,
        operation_id="create_benchmark_definition",
    )
    async def create_benchmark_definition(
        request: Request,
        body: wire.CreateBenchmarkDefinitionRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        source_service, key, correlation = command(request)
        value = await source_service.create_benchmark_definition(
            principal,
            app.CreateBenchmarkDefinitionCommand(
                name=body.name, content=benchmark_content(body.content), normalize=body.normalize
            ),
            idempotency_key=key,
            correlation_id=correlation,
        )
        return source_response(
            request,
            value,
            wire.BenchmarkDefinitionDetail,
            status_code=201,
            etag=value.definition.etag,
        )

    @router.get(
        "/benchmark-definitions/{definition_id}",
        response_model=wire.BenchmarkDefinitionDetail,
        operation_id="get_benchmark_definition",
    )
    async def get_benchmark_definition(
        request: Request,
        definition_id: UUIDString,
        query: Annotated[wire.BenchmarkDetailQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_benchmark_definition(
            principal, definition_id, query=app.BenchmarkDetailQuery(**query.model_dump())
        )
        return source_response(request, value, wire.BenchmarkDefinitionDetail)

    @router.post(
        "/benchmark-definitions/{definition_id}/versions",
        status_code=201,
        response_model=wire.BenchmarkDefinitionDetail,
        operation_id="create_benchmark_version",
    )
    async def create_benchmark_version(
        request: Request,
        definition_id: UUIDString,
        body: wire.CreateBenchmarkVersionRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        source_service, key, correlation = command(request)
        value = await source_service.create_benchmark_version(
            principal,
            definition_id,
            app.CreateBenchmarkVersionCommand(
                content=benchmark_content(body.content), normalize=body.normalize
            ),
            if_match=request.headers.get("if-match"),
            idempotency_key=key,
            correlation_id=correlation,
        )
        return source_response(
            request,
            value,
            wire.BenchmarkDefinitionDetail,
            status_code=201,
            etag=value.definition.etag,
        )

    @router.post(
        "/benchmark-definitions/{definition_id}/archive",
        response_model=wire.BenchmarkDefinitionDetail,
        operation_id="archive_benchmark_definition",
    )
    async def archive_benchmark_definition(
        request: Request,
        definition_id: UUIDString,
        body: wire.EmptySourceRequest,
        principal: Principal = principal_dep,
    ) -> Response:
        del body
        source_service, key, correlation = command(request)
        value = await source_service.archive_benchmark_definition(
            principal,
            definition_id,
            if_match=request.headers.get("if-match"),
            idempotency_key=key,
            correlation_id=correlation,
        )
        return source_response(
            request, value, wire.BenchmarkDefinitionDetail, etag=value.definition.etag
        )

    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        parameters: list[dict[str, object]] = []
        if "POST" in (route.methods or set()):
            parameters.extend(
                [
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
                    },
                    {
                        "name": "X-CSRF-Token",
                        "in": "header",
                        "required": False,
                        "description": (
                            "Required with a session cookie and configured trusted Origin."
                        ),
                        "schema": {"type": "string", "maxLength": 2048},
                    },
                ]
            )
            if route.operation_id != "create_benchmark_definition":
                parameters.append(
                    {
                        "name": "If-Match",
                        "in": "header",
                        "required": False,
                        "description": (
                            "Current benchmark revision token for new commands; "
                            "authorized exact replay resolves first."
                        ),
                        "schema": {"type": "string", "maxLength": 2048},
                    }
                )
        else:
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
