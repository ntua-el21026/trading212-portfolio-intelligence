"""Authorization, conditional reads, bounded results and closed historical query delegation."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from trading212_api.main import create_app
from trading212_application import historical as app
from trading212_application.services import SyntheticPortfolioService
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID

from tests.unit.api.historical_factories import ACCOUNT, QUERY, VERSION, payload

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
SCOPES = frozenset(
    {Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.ACTIVITY_READ, Scope.TARGETS_READ}
)
OPERATIONS = (
    ("get_performance_series", "performance/series"),
    ("get_performance_summary", "performance/intelligence"),
    ("get_benchmark_comparison", "benchmark-comparison"),
    ("get_attribution_summary", "attribution"),
    ("get_dividend_intelligence", "dividend-intelligence"),
    ("get_cash_flow_intelligence", "cash-flow-intelligence"),
)
HEADERS = {"Authorization": "Bearer historical-test-token"}


class _Bearer:
    def __init__(self, scopes: frozenset[Scope]) -> None:
        self.scopes = scopes

    async def authenticate(self, token: str) -> Principal:
        assert token == "historical-test-token"
        return Principal(
            "historical-test",
            LOCAL_SYNTHETIC_OWNER_ID,
            "test",
            "test",
            self.scopes,
            NOW - timedelta(hours=1),
            NOW + timedelta(hours=1),
        )


def application(
    scopes: frozenset[Scope] = SCOPES, *, available: bool = True
) -> tuple[FastAPI, AsyncMock]:
    service = AsyncMock(spec=app.PerformanceIntelligenceService)
    for name, _ in OPERATIONS:
        getattr(service, name).return_value = payload(name)
    return create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
            allowed_hosts=("testserver",),
        ),
        service=SyntheticPortfolioService(),
        historical_service=cast(app.PerformanceIntelligenceService, service) if available else None,
        bearer_authenticator=_Bearer(scopes),
        clock=lambda: NOW,
    ), service


def params(name: str) -> dict[str, str]:
    return {
        **QUERY,
        **({"benchmark_version_id": VERSION} if name == "get_benchmark_comparison" else {}),
    }


@pytest.mark.parametrize(("name", "suffix"), OPERATIONS)
async def test_six_historical_reads_delegate_typed_queries_and_return_closed_payloads(
    name: str, suffix: str
) -> None:
    api, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/{suffix}", params=params(name), headers=HEADERS
        )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store" and response.headers["etag"]
    assert response.json() == payload(name)
    assert len(service.mock_calls) == 1
    principal, account = getattr(service, name).call_args.args
    assert principal.owner_id == LOCAL_SYNTHETIC_OWNER_ID and account == ACCOUNT
    query = getattr(service, name).call_args.kwargs["query"]
    assert query.window.reporting_currency.value == "EUR"
    assert query.window.knowledge_policy.value == "as_of_cutoff" and query.input_snapshot_id is None


@pytest.mark.parametrize(("name", "suffix"), OPERATIONS)
async def test_authentication_and_scopes_precede_malformed_selectors(
    name: str, suffix: str
) -> None:
    for scopes, headers, status in (
        (SCOPES, {}, 401),
        (frozenset({Scope.PORTFOLIO_READ}), HEADERS, 403),
    ):
        api, service = application(scopes)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(api), base_url="https://testserver"
        ) as client:
            response = await client.get(
                f"/api/v1/accounts/invalid/{suffix}",
                params={"private-selector-canary": "secret-value-canary"},
                headers=headers,
            )
        assert response.status_code == status
        assert "canary" not in response.text and not service.mock_calls


@pytest.mark.parametrize(
    ("suffix", "missing", "extra"),
    [
        ("performance/intelligence", Scope.ANALYTICS_READ, {}),
        ("performance/intelligence", Scope.PORTFOLIO_READ, {}),
        ("dividend-intelligence", Scope.ACTIVITY_READ, {}),
        ("cash-flow-intelligence", Scope.ACTIVITY_READ, {}),
        ("attribution", Scope.TARGETS_READ, {"target_version_id": VERSION}),
        (
            "dividend-intelligence",
            Scope.TARGETS_READ,
            {"grouping": "group", "target_version_id": VERSION},
        ),
    ],
)
async def test_exact_scope_dependencies(suffix: str, missing: Scope, extra: dict[str, str]) -> None:
    api, service = application(SCOPES - {missing})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/{suffix}", params={**QUERY, **extra}, headers=HEADERS
        )
    assert response.status_code == 403 and not service.mock_calls


@pytest.mark.parametrize(
    "extra",
    [
        {"private-selector-canary": "secret-value-canary"},
        {"limit": "1.0"},
        {"input_snapshot_id": "bad-id"},
        {"frequency": "hourly"},
        {"end_date": "2040-01-01"},
    ],
)
async def test_unknown_and_out_of_bound_inputs_never_call_service(extra: dict[str, str]) -> None:
    api, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/performance/series",
            params={**QUERY, **extra},
            headers=HEADERS,
        )
    assert response.status_code == 422 and not service.mock_calls
    assert "canary" not in response.text


async def test_complete_response_etag_changes_with_access_and_authorization_precedes_304() -> None:
    api, service = application()
    endpoint = f"/api/v1/accounts/{ACCOUNT}/performance/intelligence"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        first = await client.get(endpoint, params=QUERY, headers=HEADERS)
        replay = await client.get(
            endpoint, params=QUERY, headers={**HEADERS, "If-None-Match": first.headers["etag"]}
        )
        assert replay.status_code == 304 and not replay.content
        changed = copy.deepcopy(payload("get_performance_summary"))
        changed["context"]["access"]["reproducibility"] = "inputs_expired"
        service.get_performance_summary.return_value = changed
        current = await client.get(
            endpoint, params=QUERY, headers={**HEADERS, "If-None-Match": first.headers["etag"]}
        )
        assert current.status_code == 200 and current.headers["etag"] != first.headers["etag"]
        assert (
            current.json()["context"]["content_digest"] == first.json()["context"]["content_digest"]
        )
        service.get_performance_summary.side_effect = app.HistoricalServiceError(
            app.HistoricalServiceErrorCode.ACCESS_DENIED, "private-provider-canary"
        )
        denied = await client.get(endpoint, params=QUERY, headers={**HEADERS, "If-None-Match": "*"})
    assert denied.status_code == 403 and "canary" not in denied.text
    assert service.get_performance_summary.await_count == 4


@pytest.mark.parametrize("mode", ["unknown", "float", "overflow", "byte_bound"])
async def test_invalid_or_oversized_result_cannot_pass_conditional_get(mode: str) -> None:
    api, service = application()
    data = payload("get_performance_summary")
    if mode == "unknown":
        data["context"]["secret-provider-canary"] = "hidden-canary"
    elif mode == "float":
        data["summary"]["ending_value"]["value"]["amount"] = 0.1
    elif mode == "overflow":
        data["series"] *= 3662
    else:
        data["series"] *= 3661
    service.get_performance_summary.return_value = data
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/performance/intelligence",
            params=QUERY,
            headers={**HEADERS, "If-None-Match": "*"},
        )
    assert response.status_code == (422 if mode == "byte_bound" else 500)
    assert response.json()["error"]["code"] == (
        "RESULT_TOO_LARGE" if mode == "byte_bound" else "INTERNAL_ERROR"
    )
    assert "canary" not in response.text


async def test_missing_historical_service_returns_typed_unavailable_after_authentication() -> None:
    api, _ = application(available=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/performance/intelligence", params=QUERY, headers=HEADERS
        )
    assert (
        response.status_code == 503 and response.json()["error"]["code"] == "HISTORICAL_UNAVAILABLE"
    )


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
async def test_historical_surface_has_no_business_commands(method: str) -> None:
    api, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.request(
            method,
            f"/api/v1/accounts/{ACCOUNT}/performance/intelligence",
            params=QUERY,
            headers=HEADERS,
            json={},
        )
    assert response.status_code == 405 and not service.mock_calls


async def test_historical_body_byte_bound_applies_even_to_read_requests() -> None:
    api, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.request(
            "GET",
            f"/api/v1/accounts/{ACCOUNT}/performance/intelligence",
            params=QUERY,
            headers=HEADERS,
            content=b"x" * (64 * 1024 + 1),
        )
    assert response.status_code == 413 and not service.mock_calls
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
