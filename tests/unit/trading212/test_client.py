from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from trading212_provider.allowlist import CAPABILITIES
from trading212_provider.client import Trading212Client
from trading212_provider.configuration import BrokerEnvironment, Trading212Settings
from trading212_provider.credentials import StaticCredentialProvider, Trading212Credentials
from trading212_provider.errors import MethodNotAllowedError, ProviderError, ProviderErrorKind

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures/trading212"
CANARY_KEY = "synthetic-key"
CANARY_SECRET = "CANARY_NEVER_LOG_THIS_SECRET"


async def _immediate_sleep(_: float) -> None:
    return None


def _credentials(
    environment: BrokerEnvironment = BrokerEnvironment.DEMO,
) -> StaticCredentialProvider:
    return StaticCredentialProvider(
        Trading212Credentials(
            api_key=CANARY_KEY,
            api_secret=CANARY_SECRET,
            environment=environment,
        )
    )


def _client(
    handler: httpx.AsyncBaseTransport,
    *,
    settings: Trading212Settings | None = None,
    sleep: Callable[[float], Awaitable[None]] = _immediate_sleep,
) -> Trading212Client:
    return Trading212Client(
        settings=settings or Trading212Settings(),
        credential_provider=_credentials((settings or Trading212Settings()).environment),
        credential_reference="secret://synthetic/demo",
        transport=handler,
        sleep=sleep,
        now=lambda: datetime(2026, 1, 10, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_successful_basic_auth_decimal_parse_and_redacted_logging(
    caplog: pytest.LogCaptureFixture,
) -> None:
    observed: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(
            200,
            content=(FIXTURES / "account_summary.json").read_bytes(),
            headers={
                "x-ratelimit-limit": "1",
                "x-ratelimit-period": "5",
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset": "1768003230",
                "x-ratelimit-used": "1",
            },
        )

    caplog.set_level(logging.INFO)
    client = _client(httpx.MockTransport(handler))
    try:
        result = await client.get_account_summary(correlation_id="test-correlation")
    finally:
        await client.aclose()
    assert len(observed) == 1
    assert observed[0].method == "GET"
    assert observed[0].url == "https://demo.trading212.com/api/v0/equity/account/summary"
    assert observed[0].headers["authorization"].startswith("Basic ")
    assert result.data.currency == "EUR"
    assert result.rate_limit is not None and result.rate_limit.period_seconds == 5
    assert CANARY_KEY not in caplog.text
    assert CANARY_SECRET not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_non_read_methods_fail_before_transport(method: str) -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(MethodNotAllowedError):
            client._request_builder.build(
                method=method,
                capability=CAPABILITIES["account_summary"],
                authorization="Basic REDACTED",
                correlation_id="negative-test",
                query={},
                order_id=None,
            )
    finally:
        await client.aclose()
    assert calls == 0


@pytest.mark.asyncio
async def test_rate_limit_retries_are_bounded() -> None:
    attempts = 0
    delays: list[float] = []

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, content=(FIXTURES / "account_summary.json").read_bytes())

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    client = _client(httpx.MockTransport(handler), sleep=record_sleep)
    try:
        result = await client.get_account_summary()
    finally:
        await client.aclose()
    assert result.status_code == 200
    assert attempts == 3
    assert delays == [0.0, 0.0]


@pytest.mark.asyncio
async def test_retry_exhaustion_sanitizes_provider_body() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text=f"upstream echoed {CANARY_SECRET}")

    client = _client(httpx.MockTransport(handler), settings=Trading212Settings(max_attempts=1))
    try:
        with pytest.raises(ProviderError) as captured:
            await client.get_account_summary()
    finally:
        await client.aclose()
    assert captured.value.kind is ProviderErrorKind.TRANSIENT
    assert CANARY_SECRET not in str(captured.value)


@pytest.mark.asyncio
async def test_malformed_or_missing_contract_data_fails_closed() -> None:
    responses = iter(
        [
            httpx.Response(200, content=b"not-json"),
            httpx.Response(200, json={"currency": "EUR"}),
        ]
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return next(responses)

    client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as malformed:
            await client.get_account_summary()
        with pytest.raises(ProviderError) as missing:
            await client.get_account_summary()
    finally:
        await client.aclose()
    assert malformed.value.kind is ProviderErrorKind.CONTRACT
    assert missing.value.kind is ProviderErrorKind.CONTRACT


@pytest.mark.asyncio
async def test_wrong_environment_credentials_fail_before_transport() -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    settings = Trading212Settings(
        environment=BrokerEnvironment.LIVE,
        live_mode_explicitly_enabled=True,
    )
    client = Trading212Client(
        settings=settings,
        credential_provider=_credentials(BrokerEnvironment.DEMO),
        credential_reference="secret://synthetic/demo",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ProviderError) as captured:
            await client.get_account_summary()
    finally:
        await client.aclose()
    assert captured.value.kind is ProviderErrorKind.AUTHENTICATION
    assert calls == 0


def test_no_public_generic_provider_request_surface() -> None:
    public_names = {name for name in dir(Trading212Client) if not name.startswith("_")}
    assert "request" not in public_names
    assert "get" not in public_names
