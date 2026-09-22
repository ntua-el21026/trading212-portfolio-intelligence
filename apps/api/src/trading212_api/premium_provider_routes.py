"""One fixed metadata-only provider status endpoint, authorized before parsing."""

from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from pydantic import ValidationError
from trading212_api_contracts.premium_providers import PremiumProviderStatusResponse
from trading212_api_contracts.targets import UUIDString
from trading212_application import premium_provider_status as app
from trading212_domain.serialization import to_primitive
from trading212_security.principals import AuthenticationError, Authorizer, Principal

from .target_routes import BoundedTargetRoute, _error


class PremiumProviderApiContext(Protocol):
    @property
    def premium_provider_service(self) -> app.PremiumProviderStatusService | None: ...
    @property
    def clock(self) -> Callable[[], datetime]: ...


def register_premium_provider_routes(
    application: FastAPI,
    principal_dependency: Callable[[Request], Awaitable[Principal]],
    context_provider: Callable[[Request], PremiumProviderApiContext],
) -> None:
    class AuthorizedProviderRoute(BoundedTargetRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def authenticated(request: Request) -> Response:
                principal = await principal_dependency(request)
                for scope in app.PROVIDER_STATUS_SCOPES:
                    Authorizer().require_scope(
                        principal, scope, now=context_provider(request).clock()
                    )
                if request.query_params:
                    return _error(
                        request,
                        422,
                        "VALIDATION_FAILED",
                        "The provider status request has no query parameters.",
                    )
                request.state.premium_provider_principal = principal
                return await handler(request)

            return authenticated

    async def principal_from_request(request: Request) -> Principal:
        principal = request.state.premium_provider_principal
        if not isinstance(principal, Principal):
            raise AuthenticationError("Authentication is required.")
        return principal

    principal_dep = Depends(principal_from_request)
    router = APIRouter(
        prefix="/api/v1", tags=["premium-providers"], route_class=AuthorizedProviderRoute
    )

    @router.get(
        "/accounts/{account_id}/premium-providers",
        response_model=PremiumProviderStatusResponse,
        operation_id="get_premium_provider_status",
    )
    async def status(
        account_id: UUIDString,
        request: Request,
        response: Response,
        principal: Principal = principal_dep,
    ) -> PremiumProviderStatusResponse | Response:
        response.headers["Cache-Control"] = "private, no-store"
        service = context_provider(request).premium_provider_service
        if service is None:
            return _error(request, 503, "SOURCE_UNAVAILABLE", "Provider status is unavailable.")
        try:
            value = await service.get_premium_provider_status(principal, UUID(account_id))
            if value.account_id != UUID(account_id):
                raise app.PremiumStatusError(app.PremiumStatusErrorCode.SOURCE_UNAVAILABLE)
            return PremiumProviderStatusResponse.model_validate(to_primitive(value))
        except app.PremiumStatusError as failure:
            code = failure.code.value
            status_code, message = {
                "ACCESS_DENIED": (403, "Access to provider status is denied."),
                "VALIDATION_FAILED": (422, "The provider status request is invalid."),
                "SOURCE_UNAVAILABLE": (503, "Provider status is unavailable."),
            }[code]
            return _error(request, status_code, code, message)
        except ValidationError:
            return _error(request, 503, "SOURCE_UNAVAILABLE", "Provider status is unavailable.")

    application.include_router(router)
