"""One fixed GET, explicit injection, bounded private response, no conditional auth cache."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from pydantic import TypeAdapter, ValidationError
from trading212_api_contracts import intelligence_quality as wire
from trading212_api_contracts.targets import UUIDString
from trading212_application import intelligence_quality as app
from trading212_application.queries import CollectionSnapshotCapacityError, CursorValidationError
from trading212_domain.serialization import to_primitive
from trading212_security.principals import AuthenticationError, Authorizer, Principal, Scope

from .target_routes import BoundedTargetRoute, _error

_RESPONSE: TypeAdapter[
    wire.IntelligenceDataQuality | wire.IntelligenceQualityPermissionRequired
] = TypeAdapter(wire.IntelligenceQualityResponse)


class IntelligenceQualityApiContext(Protocol):
    @property
    def intelligence_quality_service(self) -> app.IntelligenceDataQualityService | None: ...
    @property
    def clock(self) -> Callable[[], datetime]: ...


def register_intelligence_quality_routes(
    application: FastAPI,
    principal_dependency: Callable[[Request], Awaitable[Principal]],
    context_provider: Callable[[Request], IntelligenceQualityApiContext],
) -> None:
    class AuthorizedQualityRoute(BoundedTargetRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def authenticated(request: Request) -> Response:
                principal = await principal_dependency(request)
                for scope in (Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ):
                    Authorizer().require_scope(
                        principal, scope, now=context_provider(request).clock()
                    )
                request.state.intelligence_quality_principal = principal
                return await handler(request)

            return authenticated

    async def authenticated_principal(request: Request) -> Principal:
        value = request.state.intelligence_quality_principal
        if not isinstance(value, Principal):
            raise AuthenticationError("Authentication is required.")
        return value

    router = APIRouter(
        prefix="/api/v1/accounts/{account_id}",
        tags=["sources", "intelligence-quality"],
        route_class=AuthorizedQualityRoute,
    )

    principal_dep = Depends(authenticated_principal)

    @router.get(
        "/intelligence-data-quality",
        response_model=wire.IntelligenceQualityResponse,
        operation_id="get_intelligence_data_quality",
    )
    async def get_intelligence_data_quality(
        request: Request,
        account_id: UUIDString,
        query: Annotated[wire.IntelligenceDataQualityQuery, Query()],
        principal: Principal = principal_dep,
    ) -> Response:
        service = context_provider(request).intelligence_quality_service
        if service is None:
            return _error(
                request, 503, "QUALITY_UNAVAILABLE", "Intelligence quality is unavailable."
            )
        try:
            value = await service.get_intelligence_data_quality(
                principal,
                account_id,
                query=app.IntelligenceDataQualityQuery(
                    analytics_kind=app.IntelligenceKind(query.analytics_kind),
                    cursor=query.cursor,
                    limit=query.limit,
                ),
            )
        except CursorValidationError:
            return _error(request, 422, "INVALID_CURSOR", "The cursor is invalid.")
        except CollectionSnapshotCapacityError:
            return _error(request, 422, "RESULT_TOO_LARGE", "The requested result is too large.")
        except app.IntelligenceQualityError as exc:
            return _error(
                request,
                422 if exc.code == "RESULT_TOO_LARGE" else 503,
                exc.code,
                "Intelligence quality is unavailable.",
            )
        try:
            payload = _RESPONSE.validate_python(to_primitive(value)).model_dump_json().encode()
        except (ValidationError, ValueError, TypeError):
            return _error(request, 500, "INTERNAL_ERROR", "Intelligence quality is unavailable.")
        if len(payload) > app.MAX_QUALITY_BYTES:
            return _error(request, 422, "RESULT_TOO_LARGE", "The requested result is too large.")
        return Response(
            payload, media_type="application/json", headers={"Cache-Control": "private, no-store"}
        )

    application.include_router(router)
