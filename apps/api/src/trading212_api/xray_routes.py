"""Four authenticated X-ray GET operations over the injected application service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.routing import APIRoute
from trading212_api_contracts import xray as wire
from trading212_api_contracts.targets import UUIDString
from trading212_application import xray as app
from trading212_security.principals import AuthenticationError, Authorizer, Principal, Scope

from .target_routes import REQUEST_BYTE_LIMIT, BoundedTargetRoute, _error
from .xray_schemas import (
    constituent_holdings_query,
    constituent_snapshot_query,
    effective_exposure_query,
    etf_overlap_query,
    xray_response,
)


class XrayApiContext(Protocol):
    @property
    def xray_service(self) -> app.XrayService | None: ...
    @property
    def clock(self) -> Callable[[], datetime]: ...


def register_xray_routes(
    application: FastAPI,
    principal_dependency: Callable[[Request], Awaitable[Principal]],
    context_provider: Callable[[Request], XrayApiContext],
) -> None:
    class AuthorizedXrayRoute(BoundedTargetRoute):
        def permits_repeated_query(self, key: str) -> bool:
            return self.path.endswith("/etf-overlap") and key == "fund_ids"

        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def authenticated(request: Request) -> Response:
                principal = await principal_dependency(request)
                context = context_provider(request)
                required = [Scope.ANALYTICS_READ]
                if "/accounts/" in self.path or "account_id" in request.query_params:
                    required.append(Scope.PORTFOLIO_READ)
                for scope in required:
                    Authorizer().require_scope(principal, scope, now=context.clock())
                if len(request.scope.get("query_string", b"")) > REQUEST_BYTE_LIMIT:
                    return _error(
                        request, 422, "VALIDATION_FAILED", "The X-ray request is invalid."
                    )
                if len(request.query_params.getlist("fund_ids")) > 32:
                    return _error(
                        request, 422, "VALIDATION_FAILED", "The X-ray request is invalid."
                    )
                request.state.xray_principal = principal
                return await handler(request)

            return authenticated

    async def principal_from_request(request: Request) -> Principal:
        principal = request.state.xray_principal
        if not isinstance(principal, Principal):
            raise AuthenticationError("Authentication is required.")
        return principal

    principal_dep = Depends(principal_from_request)
    router = APIRouter(prefix="/api/v1", tags=["xray"], route_class=AuthorizedXrayRoute)

    def service(request: Request) -> app.XrayService:
        value = context_provider(request).xray_service
        if value is None:
            raise app.XrayServiceError(
                app.XrayServiceErrorCode.XRAY_UNAVAILABLE, "X-ray is unavailable."
            )
        return value

    @router.get(
        "/accounts/{account_id}/effective-exposure",
        response_model=wire.XrayEffectiveExposureResponse,
        operation_id="get_effective_exposure",
    )
    async def get_effective_exposure(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.XrayEffectiveExposureQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_effective_exposure(
            principal, account_id, query=effective_exposure_query(query)
        )
        if isinstance(value, app.ExposuresView):
            return xray_response(request, value, wire.XrayExposuresResponse)
        if isinstance(value, app.PathsView):
            return xray_response(request, value, wire.XrayPathsResponse)
        return xray_response(request, value, wire.XrayHeldFundsResponse)

    @router.get(
        "/accounts/{account_id}/etf-overlap",
        response_model=wire.XrayEtfOverlapResponse,
        operation_id="get_etf_overlap",
    )
    async def get_etf_overlap(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.XrayEtfOverlapQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_etf_overlap(
            principal, account_id, query=etf_overlap_query(query)
        )
        if isinstance(value, app.OverlapPairsView):
            return xray_response(request, value, wire.XrayOverlapPairsResponse)
        if isinstance(value, app.CommonEntitiesView):
            return xray_response(request, value, wire.XrayCommonEntitiesResponse)
        return _error(request, 500, "INTERNAL_ERROR", "The X-ray operation could not complete.")

    @router.get(
        "/constituent-snapshots/{id}",
        response_model=wire.XrayConstituentSnapshotHeader,
        operation_id="get_constituent_snapshot",
    )
    async def get_constituent_snapshot(
        request: Request,
        id: UUIDString,
        query: Annotated[wire.XrayConstituentSnapshotQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).get_constituent_snapshot(
            principal, id, query=constituent_snapshot_query(query)
        )
        return xray_response(request, value, wire.XrayConstituentSnapshotHeader)

    @router.get(
        "/constituent-snapshots/{id}/holdings",
        response_model=wire.XrayConstituentHoldingPage,
        operation_id="list_constituent_holdings",
    )
    async def list_constituent_holdings(
        request: Request,
        id: UUIDString,
        query: Annotated[wire.XrayConstituentHoldingsQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        value = await service(request).list_constituent_holdings(
            principal, id, query=constituent_holdings_query(query)
        )
        return xray_response(request, value, wire.XrayConstituentHoldingPage)

    application.include_router(router)
    for route in application.routes:
        if isinstance(route, APIRoute) and route.operation_id in {
            "get_effective_exposure",
            "get_etf_overlap",
            "get_constituent_snapshot",
            "list_constituent_holdings",
        }:
            route.responses.setdefault(
                304, {"description": "Authorized representation is unchanged."}
            )

    @application.exception_handler(app.XrayServiceError)
    async def xray_service_error(request: Request, exc: app.XrayServiceError) -> Response:
        responses = {
            "NOT_FOUND": (404, "The requested X-ray resource was not found."),
            "ACCESS_DENIED": (403, "Access to this X-ray resource is denied."),
            "VALIDATION_FAILED": (422, "The X-ray request is invalid."),
            "INPUT_SNAPSHOT_MISMATCH": (
                409,
                "The retained input does not match the requested X-ray scope.",
            ),
            "IDEMPOTENCY_KEY_REUSED": (409, "The request conflicts with an existing operation."),
            "XRAY_UNAVAILABLE": (503, "The X-ray service is unavailable."),
            "RESULT_TOO_LARGE": (422, "The X-ray result exceeds its permitted size."),
            "SOURCE_REVISION_CONFLICT": (
                409,
                "The retained source revision conflicts with an existing observation.",
            ),
        }
        status, message = responses.get(
            str(exc.code), (500, "The X-ray operation could not complete.")
        )
        return _error(request, status, str(exc.code), message)
