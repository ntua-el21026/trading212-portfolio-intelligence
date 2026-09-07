"""Six authenticated historical GET operations backed by one injected application service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.routing import APIRoute
from trading212_api_contracts import historical as wire
from trading212_api_contracts.targets import UUIDString
from trading212_application import historical as app
from trading212_security.principals import AuthenticationError, Authorizer, Principal, Scope

from .historical_schemas import (
    attribution_query,
    benchmark_comparison_query,
    cash_flow_intelligence_query,
    dividend_intelligence_query,
    historical_response,
    performance_series_query,
    performance_summary_query,
)
from .target_routes import BoundedTargetRoute


class HistoricalApiContext(Protocol):
    @property
    def historical_service(self) -> app.PerformanceIntelligenceService | None: ...
    @property
    def clock(self) -> Callable[[], datetime]: ...


def register_historical_routes(
    application: FastAPI,
    principal_dependency: Callable[[Request], Awaitable[Principal]],
    context_provider: Callable[[Request], HistoricalApiContext],
) -> None:
    class AuthorizedHistoricalRoute(BoundedTargetRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def authenticated(request: Request) -> Response:
                principal = await principal_dependency(request)
                required = [Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ]
                if self.path.endswith(("/dividend-intelligence", "/cash-flow-intelligence")):
                    required.append(Scope.ACTIVITY_READ)
                if (
                    "target_version_id" in request.query_params
                    or request.query_params.get("grouping") == "group"
                ):
                    required.append(Scope.TARGETS_READ)
                for scope in required:
                    Authorizer().require_scope(
                        principal, scope, now=context_provider(request).clock()
                    )
                request.state.historical_principal = principal
                return await handler(request)

            return authenticated

    async def principal_from_request(request: Request) -> Principal:
        principal = request.state.historical_principal
        if not isinstance(principal, Principal):
            raise AuthenticationError("Authentication is required.")
        return principal

    principal_dep = Depends(principal_from_request)
    router = APIRouter(
        prefix="/api/v1/accounts/{account_id}",
        tags=["historical"],
        route_class=AuthorizedHistoricalRoute,
    )

    def service(request: Request) -> app.PerformanceIntelligenceService:
        value = context_provider(request).historical_service
        if value is None:
            raise app.HistoricalServiceError(
                app.HistoricalServiceErrorCode.HISTORICAL_UNAVAILABLE,
                "Historical intelligence is unavailable.",
            )
        return value

    @router.get(
        "/performance/series",
        response_model=wire.PerformanceSeriesResponse,
        operation_id="get_performance_series",
    )
    async def get_performance_series(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.HistoricalPerformanceSeriesQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_performance_series(
            principal, account_id, query=performance_series_query(query)
        )
        return historical_response(request, value, wire.PerformanceSeriesResponse)

    @router.get(
        "/performance/intelligence",
        response_model=wire.PerformanceIntelligenceResponse,
        operation_id="get_performance_summary",
    )
    async def get_performance_summary(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.HistoricalPerformanceSummaryQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_performance_summary(
            principal, account_id, query=performance_summary_query(query)
        )
        return historical_response(request, value, wire.PerformanceIntelligenceResponse)

    @router.get(
        "/benchmark-comparison",
        response_model=wire.BenchmarkComparisonResponse,
        operation_id="get_benchmark_comparison",
    )
    async def get_benchmark_comparison(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.HistoricalBenchmarkComparisonQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_benchmark_comparison(
            principal, account_id, query=benchmark_comparison_query(query)
        )
        return historical_response(request, value, wire.BenchmarkComparisonResponse)

    @router.get(
        "/attribution",
        response_model=wire.AttributionSummaryResponse,
        operation_id="get_attribution_summary",
    )
    async def get_attribution_summary(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.HistoricalAttributionQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_attribution_summary(
            principal, account_id, query=attribution_query(query)
        )
        return historical_response(request, value, wire.AttributionSummaryResponse)

    @router.get(
        "/dividend-intelligence",
        response_model=wire.DividendIntelligenceResponse,
        operation_id="get_dividend_intelligence",
    )
    async def get_dividend_intelligence(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.HistoricalDividendIntelligenceQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_dividend_intelligence(
            principal, account_id, query=dividend_intelligence_query(query)
        )
        return historical_response(request, value, wire.DividendIntelligenceResponse)

    @router.get(
        "/cash-flow-intelligence",
        response_model=wire.CashFlowIntelligenceResponse,
        operation_id="get_cash_flow_intelligence",
    )
    async def get_cash_flow_intelligence(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.HistoricalCashFlowIntelligenceQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_cash_flow_intelligence(
            principal, account_id, query=cash_flow_intelligence_query(query)
        )
        return historical_response(request, value, wire.CashFlowIntelligenceResponse)

    for route in router.routes:
        if isinstance(route, APIRoute):
            route.responses.update({304: {"description": "Authorized representation unchanged"}})
    application.include_router(router)
