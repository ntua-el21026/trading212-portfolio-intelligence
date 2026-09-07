"""HTTP boundary regressions over an injected, observable target service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from trading212_api.main import create_app
from trading212_application.services import SyntheticPortfolioService
from trading212_application.targets import (
    TargetService,
    TargetValidationView,
    VirtualPortfolioState,
    VirtualPortfolioView,
)
from trading212_domain.targets import TargetIssueSeverity, TargetValidationIssue
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
PORTFOLIO_ID = "a4d0da15-6b68-4e6d-b6b2-f8c10aff828b"
ORIGIN = "https://testserver"
BODY = {"name": "Private template", "reporting_currency": "EUR", "account_id": None}


class _Bearer:
    def __init__(self, scopes: frozenset[Scope]) -> None:
        self.scopes = scopes

    async def authenticate(self, token: str) -> Principal:
        assert token == "target-test-token"
        return Principal(
            principal_id="target-test-principal",
            owner_id=LOCAL_SYNTHETIC_OWNER_ID,
            issuer="target-test",
            subject="target-test",
            scopes=self.scopes,
            authenticated_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )


def _view() -> VirtualPortfolioView:
    return VirtualPortfolioView(
        id=PORTFOLIO_ID,
        account_id=None,
        name="Private template",
        description="",
        reporting_currency="EUR",
        revision=1,
        state=VirtualPortfolioState.DRAFT,
        created_at=NOW,
        updated_at=NOW,
    )


def _app(
    scopes: frozenset[Scope] | None = None, *, available: bool = True
) -> tuple[FastAPI, AsyncMock]:
    target = AsyncMock(spec=TargetService)
    target.create_virtual_portfolio.return_value = _view()
    target.get_virtual_portfolio.return_value = _view()
    app = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
            allowed_hosts=("testserver",),
            allowed_origins=(ORIGIN,),
        ),
        service=SyntheticPortfolioService(clock=lambda: NOW),
        target_service=cast(TargetService, target) if available else None,
        bearer_authenticator=_Bearer(
            scopes or frozenset({Scope.TARGETS_READ, Scope.TARGETS_WRITE})
        ),
        clock=lambda: NOW,
    )
    return app, target


def _headers(**extra: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer target-test-token",
        "X-Idempotency-Key": "target-command",
        **extra,
    }


@pytest.mark.asyncio
async def test_target_authentication_and_scopes_precede_service_calls() -> None:
    app, target = _app(frozenset({Scope.TARGETS_READ}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
        assert (await client.get(f"/api/v1/virtual-portfolios/{PORTFOLIO_ID}")).status_code == 401
        denied = await client.post("/api/v1/virtual-portfolios", json=BODY, headers=_headers())
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "ACCESS_DENIED"
    target.create_virtual_portfolio.assert_not_awaited()
    target.get_virtual_portfolio.assert_not_awaited()


@pytest.mark.asyncio
async def test_bearer_target_write_does_not_require_cookie_csrf_or_read_scope() -> None:
    app, target = _app(frozenset({Scope.TARGETS_WRITE}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
        response = await client.post("/api/v1/virtual-portfolios", json=BODY, headers=_headers())
        assert response.status_code == 201
        assert response.headers["etag"] == f'"{PORTFOLIO_ID}:1"'
        assert response.headers["cache-control"] == "private, no-store"
        assert "etag" not in response.json()
        read = await client.get(f"/api/v1/virtual-portfolios/{PORTFOLIO_ID}", headers=_headers())
        assert read.status_code == 403
    command = target.create_virtual_portfolio.await_args
    assert command is not None
    assert command.args[1].account_id is None
    assert command.kwargs["idempotency_key"] == "target-command"


@pytest.mark.asyncio
async def test_cookie_commands_require_both_session_csrf_and_trusted_origin() -> None:
    app, target = _app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
        login = await client.post("/api/v1/auth/local-session")
        assert login.status_code == 201
        csrf = login.json()["csrf_token"]
        for headers in (
            {"Origin": ORIGIN},
            {"X-CSRF-Token": csrf},
            {"Origin": "https://foreign.invalid", "X-CSRF-Token": csrf},
            {"Origin": ORIGIN, "X-CSRF-Token": "incorrect"},
        ):
            response = await client.post(
                "/api/v1/virtual-portfolios",
                json=BODY,
                headers={"X-Idempotency-Key": "cookie-command", **headers},
            )
            assert response.status_code == 401
        target.create_virtual_portfolio.assert_not_awaited()
        result = await client.post(
            "/api/v1/virtual-portfolios",
            json=BODY,
            headers={"X-Idempotency-Key": "cookie-command", "X-CSRF-Token": csrf, "Origin": ORIGIN},
        )
        assert result.status_code == 201
        # An explicitly authenticated bearer takes precedence over an incidental cookie.
        result = await client.post("/api/v1/virtual-portfolios", json=BODY, headers=_headers())
        assert result.status_code == 201


@pytest.mark.asyncio
@pytest.mark.parametrize("key", [None, "", "white space", "unicode-%CE%B1", "x" * 181])
async def test_all_target_commands_require_a_bounded_idempotency_key(key: str | None) -> None:
    app, target = _app()
    headers = {"Authorization": "Bearer target-test-token"}
    if key is not None:
        headers["X-Idempotency-Key"] = key
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
        response = await client.post("/api/v1/virtual-portfolios", json=BODY, headers=headers)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    target.create_virtual_portfolio.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/virtual-portfolios?provider_path=secret-canary",
        f"/api/v1/virtual-portfolios/{PORTFOLIO_ID}?extra=secret-canary",
        "/api/v1/virtual-portfolios?limit=1&limit=2",
        "/api/v1/virtual-portfolios?limit=101",
        "/api/v1/virtual-portfolios?sort=provider_url",
    ],
)
async def test_unknown_ambiguous_or_unbounded_queries_fail_safely(path: str) -> None:
    app, target = _app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
        response = await client.get(path, headers=_headers())
        assert response.status_code == 422
        assert "secret-canary" not in response.text
    target.list_virtual_portfolios.assert_not_awaited()
    target.get_virtual_portfolio.assert_not_awaited()


@pytest.mark.asyncio
async def test_target_request_bound_counts_actual_stream_bytes_without_content_length() -> None:
    app, target = _app()

    async def body() -> Any:
        for _ in range(65):
            yield b" " * 1024

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
        response = await client.post(
            "/api/v1/virtual-portfolios",
            content=body(),
            headers={**_headers(), "Content-Type": "application/json"},
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    target.create_virtual_portfolio.assert_not_awaited()


@pytest.mark.asyncio
async def test_target_conditional_get_authorizes_before_returning_304() -> None:
    app, target = _app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
        headers = {"If-None-Match": f'W/"{PORTFOLIO_ID}:1"'}
        denied = await client.get(f"/api/v1/virtual-portfolios/{PORTFOLIO_ID}", headers=headers)
        assert denied.status_code == 401
        target.get_virtual_portfolio.assert_not_awaited()
        response = await client.get(
            f"/api/v1/virtual-portfolios/{PORTFOLIO_ID}", headers={**_headers(), **headers}
        )
        assert response.status_code == 304
        assert response.content == b""
    target.get_virtual_portfolio.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_target_runtime_reports_unavailable_only_after_authentication() -> None:
    app, _ = _app(available=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
        assert (await client.get("/api/v1/virtual-portfolios")).status_code == 401
        result = await client.get("/api/v1/virtual-portfolios", headers=_headers())
        assert result.status_code == 503
        assert result.json()["error"]["code"] == "TARGETS_UNAVAILABLE"


@pytest.mark.asyncio
async def test_target_response_limit_counts_utf8_bytes_and_never_returns_partial_results() -> None:
    app, target = _app()
    target.validate_target_version.return_value = TargetValidationView(
        id=PORTFOLIO_ID,
        version_id=PORTFOLIO_ID,
        input_revision=1,
        result_revision=1,
        input_digest="a" * 64,
        result_digest="a" * 64,
        valid=False,
        normalize_requested=False,
        normalization_applied=False,
        issues=tuple(
            TargetValidationIssue(
                code="bounded_issue", severity=TargetIssueSeverity.ERROR, message="界" * 1000
            )
            for _ in range(1024)
        ),
        adjustments=(),
        evaluated_at=NOW,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
        response = await client.post(
            f"/api/v1/target-versions/{PORTFOLIO_ID}/validate",
            json={},
            headers=_headers(**{"If-Match": f'"{PORTFOLIO_ID}:1"'}),
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "RESULT_TOO_LARGE"
        assert "bounded_issue" not in response.text
        assert len(response.content) < 1024


@pytest.mark.asyncio
async def test_invalid_backend_dto_never_echoes_values_or_claims_a_client_error() -> None:
    app, target = _app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
        # The service view must satisfy its typed output contract before serialization.
        # Exercise a structurally valid view with an invalid bounded field.
        target.get_virtual_portfolio.return_value = VirtualPortfolioView(
            id=PORTFOLIO_ID,
            account_id=None,
            name="private-backend-canary" * 20,
            description="",
            reporting_currency="EUR",
            revision=1,
            state=VirtualPortfolioState.DRAFT,
            created_at=NOW,
            updated_at=NOW,
        )
        response = await client.get(
            f"/api/v1/virtual-portfolios/{PORTFOLIO_ID}", headers=_headers()
        )
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "private-backend-canary" not in response.text
