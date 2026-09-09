"""Closed X-ray transport selectors, authorization ordering and conditional reads."""

from dataclasses import replace
from datetime import timedelta
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from trading212_api.main import create_app
from trading212_application import xray as app
from trading212_application.services import SyntheticPortfolioService
from trading212_application.xray_projection import xray_public_primitive
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID

from tests.unit.api.xray_factories import ACCOUNT, NOW, QUERY, SNAPSHOT, exposures, pairs

HEADERS = {"Authorization": "Bearer xray-test-token"}
SCOPES = frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ})


class _Bearer:
    def __init__(self, scopes: frozenset[Scope]) -> None:
        self.scopes = scopes

    async def authenticate(self, token: str) -> Principal:
        assert token == "xray-test-token"
        return Principal(
            "xray-test",
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
    service = AsyncMock(spec=app.XrayService)
    service.get_effective_exposure.return_value = exposures()
    service.get_etf_overlap.return_value = pairs()
    service.list_constituent_holdings.return_value = app.ConstituentHoldingPage(
        snapshot_id=SNAPSHOT, items=(), next_cursor=None, limit=25, total=0
    )
    return create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
            allowed_hosts=("testserver",),
        ),
        service=SyntheticPortfolioService(),
        xray_service=cast(app.XrayService, service) if available else None,
        bearer_authenticator=_Bearer(scopes),
        clock=lambda: NOW,
    ), service


async def test_exposure_defaults_delegate_to_typed_request_without_recomputing_payload() -> None:
    api, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/effective-exposure", params=QUERY, headers=HEADERS
        )
    assert response.status_code == 200, response.text
    assert response.json() == xray_public_primitive(exposures())
    assert response.headers["cache-control"] == "private, no-store"
    principal, account = service.get_effective_exposure.call_args.args
    query = service.get_effective_exposure.call_args.kwargs["query"]
    assert principal.owner_id == LOCAL_SYNTHETIC_OWNER_ID and account == ACCOUNT
    assert isinstance(query.options, app.Exposures) and query.options.dimension.value == "company"
    assert query.options.normalized_known_only is False


async def test_only_repeated_fund_ids_are_accepted_and_scalar_duplicates_fail() -> None:
    api, service = application()
    params = [*QUERY.items(), ("fund_ids", str(UUID(int=6))), ("fund_ids", str(UUID(int=5)))]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        good = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/etf-overlap", params=tuple(params), headers=HEADERS
        )
        bad = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/etf-overlap",
            params=[*params, ("reporting_currency", "USD")],
            headers=HEADERS,
        )
        wrong_view = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/effective-exposure", params=tuple(params), headers=HEADERS
        )
    assert good.status_code == 200, good.text
    assert bad.status_code == wrong_view.status_code == 422
    assert service.get_etf_overlap.await_count == 1 and not service.get_effective_exposure.called
    assert service.get_etf_overlap.call_args.kwargs["query"].options.fund_ids == (
        str(UUID(int=5)),
        str(UUID(int=6)),
    )


@pytest.mark.parametrize(
    "suffix",
    [
        f"accounts/{ACCOUNT}/effective-exposure",
        f"accounts/{ACCOUNT}/etf-overlap",
        f"constituent-snapshots/{SNAPSHOT}",
        f"constituent-snapshots/{SNAPSHOT}/holdings",
    ],
)
async def test_authentication_and_scopes_precede_invalid_inputs(suffix: str) -> None:
    for scopes, headers, expected in [
        (SCOPES, {}, 401),
        (frozenset({Scope.PORTFOLIO_READ}), HEADERS, 403),
    ]:
        api, service = application(scopes)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(api), base_url="https://testserver"
        ) as client:
            result = await client.get(
                f"/api/v1/{suffix}",
                params={"private-field-canary": "value-canary"},
                headers=headers,
            )
        assert result.status_code == expected and not service.mock_calls
        assert "canary" not in result.text


async def test_source_diagnostics_require_only_their_exact_scopes() -> None:
    api, service = application(frozenset({Scope.ANALYTICS_READ}))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        direct = await client.get(
            f"/api/v1/constituent-snapshots/{SNAPSHOT}/holdings", headers=HEADERS
        )
        dependent = await client.get(
            f"/api/v1/constituent-snapshots/{SNAPSHOT}/holdings",
            params={"account_id": ACCOUNT, "run_id": str(UUID(int=3))},
            headers=HEADERS,
        )
    assert direct.status_code == 200 and dependent.status_code == 403
    assert service.list_constituent_holdings.await_count == 1
    assert service.list_constituent_holdings.call_args.kwargs["query"].account_id is None


async def test_reauthorization_and_complete_representation_etag_precede_304() -> None:
    api, service = application()
    endpoint = f"/api/v1/accounts/{ACCOUNT}/effective-exposure"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        initial = await client.get(endpoint, params=QUERY, headers=HEADERS)
        conditional = {**HEADERS, "If-None-Match": initial.headers["etag"]}
        replay = await client.get(endpoint, params=QUERY, headers=conditional)
        updated = exposures()
        service.get_effective_exposure.return_value = replace(
            updated, context=replace(updated.context, calculated_at=NOW + timedelta(seconds=1))
        )
        changed = await client.get(endpoint, params=QUERY, headers=conditional)
        service.get_effective_exposure.side_effect = app.XrayServiceError(
            app.XrayServiceErrorCode.ACCESS_DENIED, "license-private-canary"
        )
        denied = await client.get(endpoint, params=QUERY, headers=conditional)
    assert initial.status_code == changed.status_code == 200 and replay.status_code == 304
    assert initial.headers["etag"] != changed.headers["etag"]
    assert denied.status_code == 403 and "canary" not in denied.text
    assert service.get_effective_exposure.await_count == 4


@pytest.mark.parametrize(
    "extra",
    [
        {"provider_url": "private-canary"},
        {"view": "mcp_top_pair"},
        {"normalized_known_only": "yes"},
        {"view": "paths"},
        {"view": "held_funds", "dimension": "company"},
        {"limit": "101"},
    ],
)
async def test_unknown_or_wrong_branch_inputs_never_reach_service(extra: dict[str, str]) -> None:
    api, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/effective-exposure",
            params={**QUERY, **extra},
            headers=HEADERS,
        )
    assert response.status_code == 422 and not service.mock_calls
    assert "canary" not in response.text


async def test_missing_service_fails_closed() -> None:
    api, service = application(available=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/effective-exposure", params=QUERY, headers=HEADERS
        )
    assert response.status_code == 503 and response.json()["error"]["code"] == "XRAY_UNAVAILABLE"
    assert not service.mock_calls
