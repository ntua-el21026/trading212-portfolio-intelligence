"""Closed REST surface, command guards, conditional authorization and sanitized errors."""

from dataclasses import replace
from datetime import timedelta
from typing import cast
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from trading212_api.main import create_app
from trading212_application import risk as app
from trading212_application.services import SyntheticPortfolioService
from trading212_application.views import Page
from trading212_domain.serialization import to_primitive
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID

from tests.unit.api.risk_factories import (
    ACCOUNT,
    DEFINITION,
    NOW,
    RUN,
    SNAPSHOT,
    VERSION,
    definition,
    matrix,
    queued,
    run,
    version,
)

ORIGIN = "https://testserver"
SCOPES = frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.RISK_WRITE})
HEADERS = {"Authorization": "Bearer synthetic-risk-test", "X-Idempotency-Key": "synthetic-one"}


class Bearer:
    def __init__(self, scopes: frozenset[Scope]) -> None:
        self.scopes = scopes

    async def authenticate(self, token: str) -> Principal:
        assert token == "synthetic-risk-test"
        return Principal(
            "risk-test",
            LOCAL_SYNTHETIC_OWNER_ID,
            "test",
            "test",
            self.scopes,
            NOW,
            NOW + timedelta(hours=1),
        )


def application(
    scopes: frozenset[Scope] = SCOPES, *, available: bool = True
) -> tuple[FastAPI, AsyncMock]:
    service = AsyncMock(spec=app.RiskService)
    service.create_definition.return_value = service.get_definition.return_value = definition()
    service.get_version.return_value = version()
    service.create_version.return_value = replace(
        version(), id=SNAPSHOT, predecessor_id=VERSION, version_number=2
    )
    service.create_run.return_value = queued()
    service.get_run.return_value = run()
    service.get_matrix.return_value = matrix()
    service.cancel_run.return_value = replace(
        queued(),
        state=app.PremiumJobState.CANCELLED,
        completed_at=NOW,
        result_availability="unavailable",
    )
    service.list_definitions.return_value = Page((definition(),), None, 25, 1)
    service.list_versions.return_value = Page((version(),), None, 25, 1)
    service.list_runs.return_value = Page((queued(),), None, 25, 1)
    api = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            allowed_hosts=("testserver",),
            allowed_origins=(ORIGIN,),
            local_synthetic_auth_enabled=True,
        ),
        service=SyntheticPortfolioService(clock=lambda: NOW),
        risk_service=cast(app.RiskService, service) if available else None,
        bearer_authenticator=Bearer(scopes),
        clock=lambda: NOW,
    )
    return api, service


def run_body() -> dict[str, object]:
    result = run().result
    assert result is not None
    return {
        "definition_version_id": str(VERSION),
        "portfolio_snapshot_id": str(SNAPSHOT),
        "historical_input_snapshot_id": str(SNAPSHOT),
        "window": to_primitive(result.historical_context.window),
    }


OPERATIONS = (
    ("get", f"/accounts/{ACCOUNT}/risk-definitions", "list_definitions", 200),
    ("post", f"/accounts/{ACCOUNT}/risk-definitions", "create_definition", 201),
    ("get", f"/risk-definitions/{DEFINITION}", "get_definition", 200),
    ("get", f"/risk-definitions/{DEFINITION}/versions", "list_versions", 200),
    ("post", f"/risk-definitions/{DEFINITION}/versions", "create_version", 201),
    ("get", f"/risk-definition-versions/{VERSION}", "get_version", 200),
    ("get", f"/accounts/{ACCOUNT}/risk-runs", "list_runs", 200),
    ("post", f"/accounts/{ACCOUNT}/risk-runs", "create_run", 202),
    ("get", f"/risk-runs/{RUN}", "get_run", 200),
    ("get", f"/risk-runs/{RUN}/matrix", "get_matrix", 200),
    ("post", f"/risk-runs/{RUN}/cancel", "cancel_run", 200),
)


@pytest.mark.parametrize("method,path,name,status", OPERATIONS)
async def test_eleven_routes_delegate_once_and_preserve_canonical_views(
    method: str, path: str, name: str, status: int
) -> None:
    api, service = application()
    body = (
        {"content": to_primitive(version().content)}
        if name in {"create_definition", "create_version"}
        else run_body()
        if name == "create_run"
        else {}
        if method == "post"
        else None
    )
    headers = {**HEADERS, "If-Match": f'"{DEFINITION}:1"'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.request(method, "/api/v1" + path, json=body, headers=headers)
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == to_primitive(getattr(service, name).return_value)
    assert len(service.mock_calls) == 1
    if method == "post":
        command = getattr(service, name).call_args.args[1]
        assert command.idempotency_key == "synthetic-one"
    if name == "create_version":
        assert service.create_version.call_args.args[1].expected_revision == 1
        assert response.headers["etag"] == f'"{DEFINITION}:2"'


@pytest.mark.parametrize("method,path,name,status", OPERATIONS)
async def test_authentication_and_required_read_scopes_precede_parsing(
    method: str, path: str, name: str, status: int
) -> None:
    for scopes, headers, expected in (
        (SCOPES, {}, 401),
        (SCOPES - {Scope.ANALYTICS_READ}, HEADERS, 403),
        (SCOPES - {Scope.PORTFOLIO_READ}, HEADERS, 403),
    ):
        api, service = application(scopes)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
            response = await client.request(
                method,
                "/api/v1" + path + "?private-canary=hidden",
                content=b"malformed",
                headers=headers,
            )
        assert response.status_code == expected
        assert not service.mock_calls and "canary" not in response.text


@pytest.mark.parametrize(
    "revision,status",
    [
        (None, 428),
        ('W/"old"', 422),
        ('"invalid"', 422),
        (f'"{DEFINITION}:513"', 422),
        (f'"{RUN}:1"', 412),
    ],
)
async def test_version_requires_owned_aggregate_revision(revision: str | None, status: int) -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            f"/api/v1/risk-definitions/{DEFINITION}/versions",
            json={"content": to_primitive(version().content)},
            headers={**HEADERS, **({"If-Match": revision} if revision is not None else {})},
        )
    assert response.status_code == status and not service.mock_calls


@pytest.mark.parametrize(
    "code,status",
    [
        (app.RiskErrorCode.CONFLICT, 409),
        (app.RiskErrorCode.RUN_EXPIRED, 410),
        (app.RiskErrorCode.SOURCE_UNAVAILABLE, 503),
        (app.RiskErrorCode.ACCESS_DENIED, 403),
        (app.RiskErrorCode.RATE_LIMITED, 429),
    ],
)
async def test_conditional_reads_reauthorize_and_errors_are_sanitized(
    code: app.RiskErrorCode, status: int
) -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        first = await client.get(f"/api/v1/risk-runs/{RUN}", headers=HEADERS)
        unchanged = await client.get(
            f"/api/v1/risk-runs/{RUN}", headers={**HEADERS, "If-None-Match": first.headers["etag"]}
        )
        assert unchanged.status_code == 304 and service.get_run.await_count == 2
        service.get_run.side_effect = app.RiskServiceError(code, "private-error-canary")
        denied = await client.get(
            f"/api/v1/risk-runs/{RUN}", headers={**HEADERS, "If-None-Match": "*"}
        )
    assert denied.status_code == status and "canary" not in denied.text
    assert denied.headers["cache-control"] == "private, no-store"
    assert denied.json()["error"]["retryable"] == (status == 503)


async def test_unknown_duplicate_oversized_and_float_inputs_never_enter_service() -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        path = f"/api/v1/accounts/{ACCOUNT}/risk-definitions"
        for query in ("limit=25&limit=26", "private-canary=hidden", "limit=101"):
            response = await client.get(path + "?" + query, headers=HEADERS)
            assert response.status_code == 422 and "canary" not in response.text
        for body in (
            {"content": {**to_primitive(version().content), "confidence": 0.95}},
            {"owner_id": str(ACCOUNT), "content": to_primitive(version().content)},
        ):
            response = await client.post(path, json=body, headers=HEADERS)
            assert response.status_code == 422
        for key in (None, "", "x" * 181):
            headers = {
                "Authorization": HEADERS["Authorization"],
                **({"X-Idempotency-Key": key} if key is not None else {}),
            }
            response = await client.post(
                path, json={"content": to_primitive(version().content)}, headers=headers
            )
            assert response.status_code == 422
        response = await client.post(path, content=b"x" * 65537, headers=HEADERS)
        assert response.status_code == 413
        response = await client.post(
            path, json={}, headers=[*HEADERS.items(), ("X-Idempotency-Key", "two")]
        )
        assert response.status_code == 422
    assert not service.mock_calls


async def test_session_origin_csrf_and_write_scope_are_required() -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        session = await client.post("/api/v1/auth/local-session")
        csrf = session.json()["csrf_token"]
        for extra in (
            {},
            {"Origin": ORIGIN},
            {"Origin": "https://foreign.invalid", "X-CSRF-Token": csrf},
        ):
            response = await client.post(
                f"/api/v1/risk-runs/{RUN}/cancel",
                json={},
                headers={"X-Idempotency-Key": "cancel-one", **extra},
            )
            assert response.status_code == 401
        assert not service.mock_calls
        response = await client.post(
            f"/api/v1/risk-runs/{RUN}/cancel",
            json={},
            headers={"X-Idempotency-Key": "cancel-one", "Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        assert response.status_code == 200
    api, service = application(SCOPES - {Scope.RISK_WRITE})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(f"/api/v1/risk-runs/{RUN}/cancel", json={}, headers=HEADERS)
    assert response.status_code == 403 and not service.mock_calls


async def test_missing_composition_is_explicitly_unavailable() -> None:
    api, service = application(available=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.get(f"/api/v1/risk-runs/{RUN}", headers=HEADERS)
    assert response.status_code == 503 and not service.mock_calls
