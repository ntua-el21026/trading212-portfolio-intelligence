"""The sole frozen metadata GET preserves authorization and safe fixed failures."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from trading212_api.main import create_app
from trading212_application import premium_provider_status as app
from trading212_application.services import SyntheticPortfolioService
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

AT = datetime(2026, 9, 15, 12, tzinfo=UTC)
ACCOUNT = UUID(int=2)
PATH = f"/api/v1/accounts/{ACCOUNT}/premium-providers"
HEADERS = {"Authorization": "Bearer synthetic-provider-status"}


def view() -> app.PremiumProviderStatusView:
    return app.PremiumProviderStatusView(
        account_id=ACCOUNT,
        observed_at=AT,
        providers=tuple(
            app.PremiumProviderStatus(
                provider=provider,
                capabilities=tuple(
                    app.PremiumCapabilityStatus(
                        capability=cap,
                        state=app.PremiumReadiness.NOT_CONFIGURED,
                        reason=app.PremiumStatusReason.OUTBOUND_DISABLED,
                        canonical_publication_supported=cap
                        is not app.PremiumCapability.ETF_PROFILE,
                    )
                    for cap in caps
                ),
            )
            for provider, caps in app.PROVIDER_CAPABILITIES
        ),
    )


class Bearer:
    def __init__(self, scopes: frozenset[Scope]) -> None:
        self.scopes = scopes

    async def authenticate(self, token: str) -> Principal:
        assert token == "synthetic-provider-status"
        return Principal(
            "test",
            str(UUID(int=1)),
            "test",
            "opaque-test",
            self.scopes,
            AT,
            AT + timedelta(hours=1),
        )


def application(scopes: frozenset[Scope] = app.PROVIDER_STATUS_SCOPES) -> tuple[FastAPI, AsyncMock]:
    service = AsyncMock(spec=app.PremiumProviderStatusService)
    service.get_premium_provider_status.return_value = view()
    api = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            allowed_hosts=("testserver",),
            allowed_origins=("https://testserver",),
            local_synthetic_auth_enabled=True,
        ),
        service=SyntheticPortfolioService(clock=lambda: AT),
        premium_provider_service=cast(app.PremiumProviderStatusService, service),
        bearer_authenticator=Bearer(scopes),
        clock=lambda: AT,
    )
    return api, service


@pytest.mark.asyncio
async def test_conditional_metadata_get_stays_current_and_omits_credentials() -> None:
    api, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.get(PATH, headers={**HEADERS, "If-None-Match": '"old"'})
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    assert response.json()["live_verification"] == "unavailable"
    assert len(response.json()["providers"]) == 2 and "credential_reference" not in response.text
    assert service.get_premium_provider_status.call_args.args[1] == ACCOUNT
    operations = [
        (method, path, op["operationId"])
        for path, methods in api.openapi()["paths"].items()
        for method, op in methods.items()
        if "premium-providers" in op.get("tags", [])
    ]
    assert operations == [
        ("get", "/api/v1/accounts/{account_id}/premium-providers", "get_premium_provider_status")
    ]


@pytest.mark.asyncio
async def test_missing_scope_precedes_bad_path_and_optional_query() -> None:
    api, service = application(frozenset({Scope.PORTFOLIO_READ}))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.get(
            "/api/v1/accounts/invalid/premium-providers?credential=canary", headers=HEADERS
        )
    assert response.status_code == 403 and "canary" not in response.text
    service.get_premium_provider_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_extra_query_and_account_mismatch_fail_closed() -> None:
    api, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.get(PATH + "?provider=unknown", headers=HEADERS)
        assert response.status_code == 422
        service.get_premium_provider_status.assert_not_awaited()
        service.get_premium_provider_status.return_value = replace(view(), account_id=UUID(int=3))
        response = await client.get(PATH, headers=HEADERS)
    assert response.status_code == 503 and str(UUID(int=3)) not in response.text


@pytest.mark.asyncio
async def test_current_service_denial_has_fixed_error() -> None:
    api, service = application()
    service.get_premium_provider_status.side_effect = app.PremiumStatusError(
        app.PremiumStatusErrorCode.ACCESS_DENIED
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.get(PATH, headers=HEADERS)
    assert response.status_code == 403 and response.json()["error"]["code"] == "ACCESS_DENIED"
