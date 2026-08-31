from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from trading212_provider.client import Trading212Client
from trading212_provider.configuration import BrokerEnvironment, Trading212Settings
from trading212_provider.credentials import StaticCredentialProvider, Trading212Credentials
from trading212_provider.errors import ProviderError, ProviderErrorKind

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures/trading212"


def _client(handler: httpx.AsyncBaseTransport, *, max_pages: int = 10) -> Trading212Client:
    return Trading212Client(
        settings=Trading212Settings(max_pages=max_pages),
        credential_provider=StaticCredentialProvider(
            Trading212Credentials("synthetic-key", "synthetic-secret", BrokerEnvironment.DEMO)
        ),
        credential_reference="secret://synthetic/demo",
        transport=handler,
    )


@pytest.mark.asyncio
async def test_next_page_is_reconstructed_through_the_sealed_capability() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        fixture = "transactions_page_1.json" if len(requests) == 1 else "transactions_page_2.json"
        return httpx.Response(200, content=(FIXTURES / fixture).read_bytes())

    client = _client(httpx.MockTransport(handler))
    try:
        pages = [page async for page in client.iter_transactions(limit=50)]
    finally:
        await client.aclose()
    assert len(pages) == 2
    assert requests[1].url.path == "/api/v0/equity/history/transactions"
    assert requests[1].url.params["cursor"] == "opaque-2"
    assert requests[1].method == "GET"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe_next",
    [
        "https://attacker.invalid/api/v0/equity/history/transactions?cursor=x&limit=50",
        "/api/v0/equity/orders?cursor=x&limit=50",
        "/api/v0/equity/history/transactions?cursor=x&cursor=y&limit=50",
        "/api/v0/equity/history/transactions?cursor=x&limit=500",
        "/api/v0/equity/history/transactions?cursor=x&limit=50&url=https://attacker.invalid",
    ],
)
async def test_unsafe_next_page_never_reaches_transport(unsafe_next: str) -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"items": [], "nextPagePath": unsafe_next})

    client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as captured:
            _ = [page async for page in client.iter_transactions(limit=50)]
    finally:
        await client.aclose()
    assert captured.value.kind is ProviderErrorKind.PAGINATION
    assert calls == 1


@pytest.mark.asyncio
async def test_pagination_loop_fails_visibly() -> None:
    next_path = "/api/v0/equity/history/transactions?cursor=same&limit=50"

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [], "nextPagePath": next_path})

    client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError, match="loop"):
            _ = [page async for page in client.iter_transactions(limit=50)]
    finally:
        await client.aclose()
