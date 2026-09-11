"""The optional transport has fixed authority, connection pinning and no secret outputs."""

import asyncio
import json
import socket
import ssl
from dataclasses import replace
from importlib.resources import files
from typing import cast
from uuid import UUID

import pytest
from trading212_application.alert_jobs import AlertDeliveryOutcome, AlertNotificationPayload
from trading212_domain.serialization import canonical_json
from trading212_reference_data import alert_webhook as w

pytestmark = pytest.mark.security
VERSION = UUID(int=1)
PAYLOAD = AlertNotificationPayload(
    delivery_id=UUID(int=2), event_id=UUID(int=3), rule_id=UUID(int=4), rule_version_id=UUID(int=5)
)
CANARY = "alert-webhook-secret-canary-9d422d"


def _contract() -> dict[str, object]:
    value: dict[str, object] = json.loads(
        files("trading212_reference_data").joinpath("contracts/alert-webhook.json").read_bytes()
    )
    return value


class Credentials:
    async def resolve_webhook_credential(
        self, destination_version_id: UUID, reference: str
    ) -> w.WebhookCredential:
        assert destination_version_id == VERSION
        assert reference == f"notifications/webhook/{VERSION}"
        return w.WebhookCredential(CANARY)


class Writer:
    def __init__(self) -> None:
        self.sent = bytearray()
        self.closed = False

    def write(self, value: bytes) -> None:
        self.sent.extend(value)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        assert self.closed


def configured(monkeypatch: pytest.MonkeyPatch) -> w.ConfiguredAlertWebhook:
    contract = _contract()
    contract["origins"] = [{"key": "fixture", "origin": "https://alerts.example.org"}]
    origins = w.validate_webhook_contract(contract)
    monkeypatch.setattr(w, "load_webhook_contract", lambda: origins)
    return w.ConfiguredAlertWebhook(
        destinations=(
            w.WebhookDestination(VERSION, "fixture", f"notifications/webhook/{VERSION}"),
        ),
        credentials=Credentials(),
    )


@pytest.mark.parametrize(
    "origin",
    [
        "http://alerts.example.org",
        "https://alerts.example.org:444",
        "https://user:secret@alerts.example.org",
        "https://alerts.example.org/path",
        "https://alerts.example.org?secret=1",
        "https://alerts.example.org#fragment",
        "https://127.0.0.1",
        "https://[::1]",
        "https://demo.trading212.com",
        "https://[alert-webhook-secret-canary-9d422d",
        "https://alerts.example.org\n",
    ],
)
def test_only_fixed_https_origin_authority(origin: str) -> None:
    contract = _contract()
    contract["origins"] = [{"key": "fixture", "origin": origin}]
    with pytest.raises(w.WebhookConfigurationError) as error:
        w.validate_webhook_contract(contract)
    assert CANARY not in str(error.value)
    assert error.value.__context__ is None


@pytest.mark.parametrize(
    "key,value",
    [
        ("method", "GET"),
        ("path", "/orders"),
        ("redirects", True),
        ("environment_proxies", True),
        ("consumer_attempts", 5),
        ("max_response_bytes", 65537),
        ("max_request_bytes", True),
        ("unknown_parameter", "value"),
    ],
)
def test_transport_manifest_is_closed(key: str, value: object) -> None:
    contract = _contract()
    contract[key] = value
    with pytest.raises(w.WebhookConfigurationError):
        w.validate_webhook_contract(contract)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104 - forbidden destination fixture, never a listener
        "224.0.0.1",
        "240.0.0.1",
        "::1",
        "::",
        "fe80::1",
        "fd00::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "::ffff:8.8.8.8",
        "64:ff9b::7f00:1",
        "2002:7f00:1::",
    ],
)
def test_every_dns_answer_is_checked_even_with_a_public_answer(address: str) -> None:
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443)),
        (
            socket.AF_INET6 if ":" in address else socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (address, 443, 0, 0) if ":" in address else (address, 443),
        ),
    ]
    with pytest.raises(w._Rejected):
        w._public_addresses(answers)


def test_native_public_ipv6_is_supported_without_scope_or_transition_routing() -> None:
    answer = (
        socket.AF_INET6,
        socket.SOCK_STREAM,
        socket.IPPROTO_TCP,
        "",
        ("2001:4860:4860::8888", 443, 0, 0),
    )
    assert w._public_addresses([answer]) == ("2001:4860:4860::8888",)


@pytest.mark.parametrize(
    "sockaddr",
    [("8.8.8.8", 80), (), ("2001:4860:4860::8888", 443)],
)
def test_dns_address_shape_family_and_port_are_closed(sockaddr: tuple[object, ...]) -> None:
    with pytest.raises(w._Rejected):
        w._public_addresses(
            [
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr),
            ]
        )


@pytest.mark.asyncio
async def test_default_disabled_and_unknown_version_never_resolve_or_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert w.load_webhook_contract() == ()
    adapter = w.ConfiguredAlertWebhook()
    result = await adapter.deliver(VERSION, PAYLOAD)
    assert result.outcome is AlertDeliveryOutcome.UNAVAILABLE
    enabled = configured(monkeypatch)
    assert (
        await enabled.deliver(UUID(int=90), PAYLOAD)
    ).outcome is AlertDeliveryOutcome.UNAVAILABLE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response,outcome",
    [
        (b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n", AlertDeliveryOutcome.ACCEPTED),
        (
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\nok\r\n0\r\n\r\n",
            AlertDeliveryOutcome.ACCEPTED,
        ),
        (
            b"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1/private\r\n"
            b"Content-Length: 0\r\n\r\n",
            AlertDeliveryOutcome.PERMANENT_FAILURE,
        ),
        (
            b"HTTP/1.1 503 Unavailable\r\nContent-Length: 0\r\n\r\n",
            AlertDeliveryOutcome.RETRYABLE_FAILURE,
        ),
        (
            b"HTTP/1.1 200 OK\r\nContent-Length: 65537\r\n\r\n",
            AlertDeliveryOutcome.PERMANENT_FAILURE,
        ),
        (b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nx", AlertDeliveryOutcome.RETRYABLE_FAILURE),
    ],
)
async def test_checked_numeric_connection_preserves_tls_and_delivery_identity(
    monkeypatch: pytest.MonkeyPatch, response: bytes, outcome: AlertDeliveryOutcome
) -> None:
    adapter = configured(monkeypatch)
    calls: list[tuple[object, ...]] = []
    writers: list[Writer] = []

    async def resolve(host: str, port: int, **kwargs: object) -> list[w._DnsAnswer]:
        calls.append(("dns", host, port))
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443))]

    async def connect(
        host: str, port: int, **kwargs: object
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        calls.append(("connect", host, port))
        assert host == "8.8.8.8" and kwargs["server_hostname"] == "alerts.example.org"
        context = kwargs["ssl"]
        assert (
            isinstance(context, ssl.SSLContext)
            and context.check_hostname
            and context.verify_mode == ssl.CERT_REQUIRED
        )
        reader = asyncio.StreamReader()
        reader.feed_data(response)
        reader.feed_eof()
        writer = Writer()
        writers.append(writer)
        return reader, cast(asyncio.StreamWriter, writer)

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(asyncio, "open_connection", connect)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    first = await adapter.deliver(VERSION, PAYLOAD)
    second = await adapter.deliver(VERSION, PAYLOAD)
    assert first.outcome is second.outcome is outcome
    assert len(calls) == 4 and calls[0] == calls[2] and calls[1] == calls[3]
    assert all(writer.closed for writer in writers)
    assert writers[0].sent == writers[1].sent
    header, body = bytes(writers[0].sent).split(b"\r\n\r\n", 1)
    assert header.startswith(b"POST /v1/alerts HTTP/1.1\r\n")
    assert f"Idempotency-Key: {PAYLOAD.delivery_id}".encode() in header
    assert set(json.loads(body)) == {"delivery_id", "event_id", "rule_id", "rule_version_id"}
    assert CANARY not in canonical_json((first, second))


@pytest.mark.asyncio
async def test_rebinding_private_retry_is_rejected_before_second_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = configured(monkeypatch)
    lookups = 0
    connects = 0

    async def resolve(host: str, port: int, **kwargs: object) -> list[w._DnsAnswer]:
        nonlocal lookups
        lookups += 1
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("8.8.8.8" if lookups == 1 else "127.0.0.1", 443),
            )
        ]

    async def connect(*args: object, **kwargs: object) -> object:
        nonlocal connects
        connects += 1
        raise OSError(CANARY)

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(asyncio, "open_connection", connect)
    first, second = await adapter.deliver(VERSION, PAYLOAD), await adapter.deliver(VERSION, PAYLOAD)
    assert first.outcome is AlertDeliveryOutcome.RETRYABLE_FAILURE
    assert second.outcome is AlertDeliveryOutcome.PERMANENT_FAILURE and connects == 1
    assert CANARY not in canonical_json((first, second))


@pytest.mark.asyncio
async def test_total_deadline_cancels_before_any_late_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = configured(monkeypatch)
    monkeypatch.setattr(w, "_TOTAL_SECONDS", 0.02)

    async def resolve(*args: object, **kwargs: object) -> list[w._DnsAnswer]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def connect(*args: object, **kwargs: object) -> object:
        raise AssertionError("DNS did not complete")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(asyncio, "open_connection", connect)
    assert (
        await adapter.deliver(VERSION, PAYLOAD)
    ).outcome is AlertDeliveryOutcome.RETRYABLE_FAILURE


def test_response_bound_and_secret_repr() -> None:
    with pytest.raises(w._Rejected):
        w._response_status(b"HTTP/1.1 204 No Content\r\nX-Test: " + b"x" * 8192 + b"\r\n\r\n")
    assert CANARY not in repr(w.WebhookCredential(CANARY))
    with pytest.raises(w.WebhookConfigurationError):
        w.WebhookCredential(CANARY + "\r\nInjected: header")
    with pytest.raises(w.WebhookConfigurationError):
        replace(
            w.WebhookDestination(VERSION, "fixture", f"notifications/webhook/{VERSION}"),
            credential_reference="broker/credentials",
        )
