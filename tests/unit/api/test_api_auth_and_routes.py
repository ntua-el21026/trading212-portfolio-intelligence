from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from trading212_api.main import ApiContext, create_app
from trading212_application.ingestion import CURRENT_REFRESH_ORDER
from trading212_application.queries import (
    CollectionSnapshotCapacityError,
    PageQuery,
    PositionQuery,
)
from trading212_application.services import PortfolioService, SyntheticPortfolioService
from trading212_application.views import Page, PositionView, SnapshotView
from trading212_persistence import PostgresPortfolioService
from trading212_security.principals import Principal, Scope
from trading212_security.settings import CredentialBackend, RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID, BearerAuthenticator

NOW = datetime(2026, 8, 31, 10, 0, tzinfo=UTC)


class _ScopeBearerAuthenticator:
    def __init__(self, scopes: frozenset[Scope]) -> None:
        self._scopes = scopes

    async def authenticate(self, token: str) -> Principal:
        assert token == "scope-test-token"
        return Principal(
            principal_id="api-scope-test-principal",
            owner_id=LOCAL_SYNTHETIC_OWNER_ID,
            issuer="api-scope-test",
            subject="api-scope-test-subject",
            scopes=self._scopes,
            authenticated_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(hours=1),
        )


class _CapacityExhaustedService(SyntheticPortfolioService):
    async def list_positions(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: PositionQuery,
    ) -> Page[PositionView]:
        del principal, account_id, query
        raise CollectionSnapshotCapacityError()


def _app(
    service: PortfolioService | None = None,
    *,
    bearer_authenticator: BearerAuthenticator | None = None,
) -> FastAPI:
    return create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
            cookie_secure=True,
            allowed_hosts=("localhost",),
        ),
        service=service or SyntheticPortfolioService(clock=lambda: NOW),
        bearer_authenticator=bearer_authenticator,
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
async def test_broker_connections_require_configuration_scope_at_runtime() -> None:
    denied_authenticator = _ScopeBearerAuthenticator(
        frozenset({Scope.PORTFOLIO_READ, Scope.ACTIVITY_READ})
    )
    allowed_authenticator = _ScopeBearerAuthenticator(frozenset({Scope.CONFIGURATION_READ}))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(bearer_authenticator=denied_authenticator)),
        base_url="https://localhost",
    ) as client:
        denied = await client.get(
            "/api/v1/broker-connections",
            headers={"Authorization": "Bearer scope-test-token"},
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(bearer_authenticator=allowed_authenticator)),
        base_url="https://localhost",
    ) as client:
        allowed = await client.get(
            "/api/v1/broker-connections",
            headers={"Authorization": "Bearer scope-test-token"},
        )

    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ACCESS_DENIED"
    assert allowed.status_code == 200
    assert allowed.json()[0]["provider"] == "synthetic"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scopes",
    [
        frozenset({Scope.PORTFOLIO_READ}),
        frozenset({Scope.ACTIVITY_READ}),
    ],
)
async def test_data_quality_api_requires_portfolio_and_activity_scopes(
    scopes: frozenset[Scope],
) -> None:
    authenticator = _ScopeBearerAuthenticator(scopes)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(bearer_authenticator=authenticator)),
        base_url="https://localhost",
    ) as client:
        response = await client.get(
            f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/data-quality",
            headers={"Authorization": "Bearer scope-test-token"},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCESS_DENIED"


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
async def test_refresh_idempotency_key_reuse_with_different_semantics_is_sanitized() -> None:
    service = SyntheticPortfolioService(clock=lambda: NOW)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(service)),
        base_url="https://localhost",
    ) as client:
        login = await client.post("/api/v1/auth/local-session")
        headers = {
            "X-Idempotency-Key": "conflicting-refresh-key",
            "X-CSRF-Token": login.json()["csrf_token"],
        }
        url = f"/api/v1/accounts/{service.ACCOUNT_ID}/refresh"
        first = await client.post(url, headers=headers, json={"mode": "incremental"})
        conflict = await client.post(url, headers=headers, json={"mode": "full"})

    assert first.status_code == 202
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert conflict.json()["error"]["message"] == (
        "The idempotency key is already bound to a different refresh request."
    )
    assert len(cast(Any, service)._refresh_runs) == 1


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
        oversized_cursor = await client.get(
            f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/positions",
            params={"cursor": "A" * 2049},
        )
    assert cross_account.status_code == 403
    assert cross_account.json()["error"]["message"] == "Access denied."
    assert invalid_cursor.status_code == 400
    assert invalid_cursor.json()["error"]["code"] == "CURSOR_INVALID"
    assert invalid_cursor.json()["error"]["message"] == "The pagination cursor is invalid."
    assert oversized_cursor.status_code == 400
    assert oversized_cursor.json()["error"] == {
        **invalid_cursor.json()["error"],
        "correlation_id": oversized_cursor.headers["x-correlation-id"],
    }


@pytest.mark.asyncio
async def test_collection_snapshot_capacity_is_stable_retryable_and_sanitized() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(_CapacityExhaustedService(clock=lambda: NOW))),
        base_url="https://localhost",
    ) as client:
        await client.post("/api/v1/auth/local-session")
        response = await client.get(
            f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/positions"
        )

    assert response.status_code == 429
    assert response.json()["error"] == {
        "code": "COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED",
        "message": "Active pagination capacity is temporarily exhausted.",
        "correlation_id": response.headers["x-correlation-id"],
        "retryable": True,
        "details": {},
    }
    assert "snapshot capacity exhausted" not in response.text


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


@pytest.mark.asyncio
async def test_instrument_routes_search_canonical_unheld_listings() -> None:
    service = SyntheticPortfolioService(clock=lambda: NOW)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(service)),
        base_url="https://localhost",
    ) as client:
        await client.post("/api/v1/auth/local-session")
        listing = await client.get("/api/v1/instruments", params={"query": "SXR8"})
        detail = await client.get("/api/v1/instruments/instrument-sxr8-unheld")

    assert listing.status_code == 200
    assert detail.status_code == 200
    assert listing.json()["items"][0]["ticker"] == "SXR8"
    assert detail.json()["ticker"] == "SXR8"


class LatestFirstSnapshotService(SyntheticPortfolioService):
    def __init__(self) -> None:
        super().__init__(clock=lambda: NOW)
        self.requested_limits: list[int] = []

    async def list_snapshots(
        self,
        principal: Any,
        account_id: str,
        *,
        query: PageQuery,
    ) -> Page[SnapshotView]:
        await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        self.requested_limits.append(query.limit)
        latest = max(self._snapshots, key=lambda item: item.valuation_at)
        return Page(items=(latest,), next_cursor=None, limit=query.limit, total=2)


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
        cursor_signing_key_reference="vault://cursor-key",
        credential_backend=CredentialBackend.EXTERNAL,
        outbox_dispatcher_configured=True,
        allowed_origins=("https://portfolio.example.test",),
        allowed_hosts=("portfolio.example.test",),
    )
    with pytest.raises(ValueError, match="explicit service"):
        create_app(settings=settings)
