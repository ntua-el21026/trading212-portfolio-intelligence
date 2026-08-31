from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from trading212_api.main import ApiContext, create_app
from trading212_application.ingestion import CURRENT_REFRESH_ORDER
from trading212_application.services import PortfolioService, SyntheticPortfolioService
from trading212_application.views import Page, SnapshotView
from trading212_persistence import PostgresPortfolioService
from trading212_security.principals import Scope
from trading212_security.settings import CredentialBackend, RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID

NOW = datetime(2026, 8, 31, 10, 0, tzinfo=UTC)


def _app(service: PortfolioService | None = None) -> FastAPI:
    return create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
            cookie_secure=True,
            allowed_hosts=("localhost",),
        ),
        service=service or SyntheticPortfolioService(clock=lambda: NOW),
        clock=lambda: NOW,
    )


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="https://localhost",
    )


@pytest.mark.asyncio
async def test_private_routes_require_authentication_and_use_error_envelope() -> None:
    async with _client() as client:
        response = await client.get(
            f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/summary"
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert response.headers["x-correlation-id"]
    assert "detail" not in response.json()


@pytest.mark.asyncio
async def test_local_session_summary_and_pagination_contract() -> None:
    async with _client() as client:
        login = await client.post("/api/v1/auth/local-session")
        assert login.status_code == 201
        assert login.json()["principal"]["owner_id"] == LOCAL_SYNTHETIC_OWNER_ID
        assert "HttpOnly" in login.headers["set-cookie"]
        assert "Secure" in login.headers["set-cookie"]

        summary = await client.get(
            f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/summary"
        )
        positions = await client.get(
            f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/positions",
            params={"limit": 2},
        )
        next_page = await client.get(
            f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/positions",
            params={"limit": 100, "cursor": positions.json()["next_cursor"]},
        )
        orders = await client.get(f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/orders")
    assert summary.status_code == 200
    assert summary.json()["total_value"]["value"] == "248431.27"
    assert isinstance(summary.json()["total_value"]["value"], str)
    assert summary.json()["realized_profit_loss"]["availability"] == "unavailable"
    assert len(positions.json()["items"]) == 2
    assert len(next_page.json()["items"]) == 3
    assert orders.json()["items"][0]["observed_value"]["value"] == "7500"


@pytest.mark.asyncio
async def test_refresh_requires_csrf_and_is_idempotent() -> None:
    async with _client() as client:
        login = await client.post("/api/v1/auth/local-session")
        csrf = login.json()["csrf_token"]
        url = f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/refresh"
        denied = await client.post(
            url,
            headers={"X-Idempotency-Key": "refresh-1"},
            json={"scope": "all", "mode": "incremental", "create_snapshot": True},
        )
        headers = {
            "X-Idempotency-Key": "refresh-1",
            "X-CSRF-Token": csrf,
        }
        first = await client.post(url, headers=headers, json={})
        second = await client.post(url, headers=headers, json={})
        current = await client.post(
            url,
            headers={**headers, "X-Idempotency-Key": "refresh-current"},
            json={"scope": "current", "mode": "full", "create_snapshot": True},
        )
    assert denied.status_code == 401
    assert first.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert all("/" not in name for name in first.json()["capabilities"])
    assert current.json()["capabilities"] == [
        capability.value for capability in CURRENT_REFRESH_ORDER
    ]


@pytest.mark.asyncio
async def test_refresh_rejects_disabling_required_snapshot_materialization() -> None:
    async with _client() as client:
        login = await client.post("/api/v1/auth/local-session")
        response = await client.post(
            f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/refresh",
            headers={
                "X-Idempotency-Key": "no-snapshot",
                "X-CSRF-Token": login.json()["csrf_token"],
            },
            json={"create_snapshot": False},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


@pytest.mark.asyncio
async def test_body_cannot_select_provider_path_or_unknown_fields() -> None:
    async with _client() as client:
        login = await client.post("/api/v1/auth/local-session")
        response = await client.post(
            f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/refresh",
            headers={
                "X-Idempotency-Key": "invalid-refresh",
                "X-CSRF-Token": login.json()["csrf_token"],
            },
            json={"scope": "all", "provider_path": "/equity/orders"},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert "/equity/orders" not in response.text


@pytest.mark.asyncio
async def test_cross_account_and_invalid_cursor_fail_without_private_detail() -> None:
    async with _client() as client:
        await client.post("/api/v1/auth/local-session")
        cross_account = await client.get("/api/v1/accounts/someone-elses-account/summary")
        invalid_cursor = await client.get(
            f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/positions",
            params={"cursor": "../../../private"},
        )
    assert cross_account.status_code == 403
    assert cross_account.json()["error"]["message"] == "Access denied."
    assert invalid_cursor.status_code == 422
    assert invalid_cursor.json()["error"]["message"] == "The request is invalid."


@pytest.mark.asyncio
async def test_logout_revokes_the_server_session() -> None:
    async with _client() as client:
        login = await client.post("/api/v1/auth/local-session")
        logout = await client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": login.json()["csrf_token"]},
        )
        me = await client.get("/api/v1/me")
    assert logout.status_code == 204
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_metrics_are_scope_protected_and_have_bounded_labels() -> None:
    async with _client() as client:
        denied = await client.get("/internal/metrics")
        await client.post("/api/v1/auth/local-session")
        response = await client.get("/internal/metrics")
    assert denied.status_code == 401
    assert response.status_code == 200
    assert "t212pi_api_requests_total" in response.text
    assert "account_id=" not in response.text
    assert "ticker=" not in response.text


def test_local_default_composes_postgres_service_and_durable_refresh_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    application = create_app(
        settings=SecuritySettings(environment=RuntimeEnvironment.TEST),
        clock=lambda: NOW,
    )
    context = cast(ApiContext, application.state.context)

    assert isinstance(context.service, PostgresPortfolioService)
    assert type(cast(Any, context.service)._refresh_queue).__name__ == ("PostgresRefreshQueue")


class AliasAccountService(SyntheticPortfolioService):
    ACCOUNT_ALIAS = "authorized-account-alias"

    def __init__(self) -> None:
        super().__init__(clock=lambda: NOW)
        self.requested_account_ids: list[str] = []

    async def list_accounts(self, principal: Any) -> tuple[Any, ...]:
        accounts = await super().list_accounts(principal)
        return (replace(accounts[0], id=self.ACCOUNT_ALIAS),)

    async def list_positions(
        self,
        principal: Any,
        account_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> Any:
        self.requested_account_ids.append(account_id)
        if account_id != self.ACCOUNT_ALIAS:
            raise AssertionError("instrument route did not resolve the authorized account")
        return await super().list_positions(
            principal,
            self.ACCOUNT_ID,
            cursor=cursor,
            limit=limit,
        )

    async def get_position(
        self,
        principal: Any,
        account_id: str,
        position_id: str,
    ) -> Any:
        self.requested_account_ids.append(account_id)
        if account_id != self.ACCOUNT_ALIAS:
            raise AssertionError("instrument route did not resolve the authorized account")
        return await super().get_position(principal, self.ACCOUNT_ID, position_id)


@pytest.mark.asyncio
async def test_instrument_routes_resolve_the_principals_authorized_account() -> None:
    service = AliasAccountService()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(service)),
        base_url="https://localhost",
    ) as client:
        await client.post("/api/v1/auth/local-session")
        listing = await client.get("/api/v1/instruments", params={"limit": 1})
        detail = await client.get("/api/v1/instruments/vwce")

    assert listing.status_code == 200
    assert detail.status_code == 200
    assert service.requested_account_ids == [service.ACCOUNT_ALIAS, service.ACCOUNT_ALIAS]


class LatestFirstSnapshotService(SyntheticPortfolioService):
    def __init__(self) -> None:
        super().__init__(clock=lambda: NOW)
        self.requested_limits: list[int] = []

    async def list_snapshots(
        self,
        principal: Any,
        account_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> Page[SnapshotView]:
        await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        self.requested_limits.append(limit)
        latest = max(self._snapshots, key=lambda item: item.valuation_at)
        return Page(items=(latest,), next_cursor=None, limit=limit, total=2)


@pytest.mark.asyncio
async def test_latest_snapshot_uses_first_item_from_a_one_row_descending_page() -> None:
    service = LatestFirstSnapshotService()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(service)),
        base_url="https://localhost",
    ) as client:
        await client.post("/api/v1/auth/local-session")
        response = await client.get(
            f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/snapshots/latest"
        )

    assert response.status_code == 200
    assert response.json()["id"] == "snapshot-2026-08-31"
    assert service.requested_limits == [1]


def test_deployed_composition_requires_explicit_runtime_adapters() -> None:
    settings = SecuritySettings(
        environment=RuntimeEnvironment.PRODUCTION,
        issuer="https://identity.example.test",
        audience="portfolio-api",
        jwt_public_key_reference="vault://jwt-public-key",
        session_signing_key_reference="vault://session-key",
        credential_backend=CredentialBackend.EXTERNAL,
        allowed_origins=("https://portfolio.example.test",),
        allowed_hosts=("portfolio.example.test",),
    )
    with pytest.raises(ValueError, match="explicit service"):
        create_app(settings=settings)
