"""Dedicated fixed alert delivery with public-address pinning and bounded HTTPS."""

from __future__ import annotations

import asyncio
import http.client
import io
import ipaddress
import json
import re
import socket
import ssl
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.resources import files
from typing import Protocol, cast
from urllib.parse import urlsplit
from uuid import UUID

from trading212_application.alert_jobs import (
    AlertDeliveryOutcome,
    AlertDeliveryReceipt,
    AlertNotificationPayload,
)
from trading212_domain.alert_serialization import encode_alert_record
from trading212_domain.alerts import AlertReason

_BODY_BOUND = 65536
_HEADER_BOUND = 8192
_PATH = "/v1/alerts"
_CONNECT_SECONDS = 5
_READ_SECONDS = 5
_TOTAL_SECONDS = 15
_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,79}$")
_HOST = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


class WebhookConfigurationError(ValueError):
    def __init__(self) -> None:
        super().__init__("The fixed webhook configuration is invalid.")


class _Rejected(Exception):
    pass


@dataclass(frozen=True, slots=True)
class WebhookOrigin:
    key: str
    hostname: str


@dataclass(frozen=True, slots=True)
class WebhookDestination:
    """Trusted server configuration; public alert commands carry only the version UUID."""

    version_id: UUID
    origin_key: str
    credential_reference: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.version_id, UUID)
            or not _KEY.fullmatch(self.origin_key)
            or self.credential_reference != f"notifications/webhook/{self.version_id}"
        ):
            raise WebhookConfigurationError()


@dataclass(frozen=True, slots=True, repr=False)
class WebhookCredential:
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.value, str)
            or not 1 <= len(self.value) <= 4096
            or any(ord(char) < 33 or ord(char) > 126 for char in self.value)
        ):
            raise WebhookConfigurationError()


class WebhookCredentialPort(Protocol):
    async def resolve_webhook_credential(
        self, destination_version_id: UUID, reference: str
    ) -> WebhookCredential | None: ...


def validate_webhook_contract(value: object) -> tuple[WebhookOrigin, ...]:
    fixed = {
        "schema_version": "1.0.0",
        "capability": "deliver_alert",
        "method": "POST",
        "path": _PATH,
        "credential_namespace": "notifications/webhook/",
        "connect_timeout_seconds": _CONNECT_SECONDS,
        "read_timeout_seconds": _READ_SECONDS,
        "total_timeout_seconds": _TOTAL_SECONDS,
        "max_request_bytes": _BODY_BOUND,
        "max_response_bytes": _BODY_BOUND,
        "max_header_bytes": _HEADER_BOUND,
        "consumer_attempts": 4,
        "redirects": False,
        "environment_proxies": False,
        "payload_fields": ["delivery_id", "event_id", "rule_id", "rule_version_id"],
        "source_license_policy": "no_financial_or_provider_content",
    }
    if (
        not isinstance(value, dict)
        or set(value) != {*fixed, "origins"}
        or any(
            type(value[key]) is not type(expected) or value[key] != expected
            for key, expected in fixed.items()
        )
    ):
        raise WebhookConfigurationError()
    raw = value["origins"]
    if not isinstance(raw, list) or len(raw) > 16:
        raise WebhookConfigurationError()
    origins = []
    for item in raw:
        if (
            not isinstance(item, dict)
            or set(item) != {"key", "origin"}
            or any(type(item[key]) is not str for key in item)
        ):
            raise WebhookConfigurationError()
        if not _KEY.fullmatch(item["key"]):
            raise WebhookConfigurationError()
        parsed = None
        with suppress(ValueError):
            parsed = urlsplit(item["origin"])
        if parsed is None:
            raise WebhookConfigurationError()
        hostname = parsed.hostname or ""
        if (
            item["origin"] not in (f"https://{hostname}", f"https://{hostname}:443")
            or parsed.scheme != "https"
            or not _HOST.fullmatch(hostname)
            or parsed.netloc not in (hostname, f"{hostname}:443")
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
            or hostname == "trading212.com"
            or hostname.endswith(".trading212.com")
        ):
            raise WebhookConfigurationError()
        origins.append(WebhookOrigin(item["key"], hostname))
    if len({item.key for item in origins}) != len(origins) or len(
        {item.hostname for item in origins}
    ) != len(origins):
        raise WebhookConfigurationError()
    return tuple(origins)


def load_webhook_contract() -> tuple[WebhookOrigin, ...]:
    raw = files("trading212_reference_data").joinpath("contracts/alert-webhook.json").read_bytes()
    if len(raw) > 16384:
        raise WebhookConfigurationError()
    value = None
    with suppress(ValueError, UnicodeError):
        value = json.loads(raw)
    return validate_webhook_contract(value)


type _DnsAnswer = tuple[int, int, int, str, tuple[object, ...]]


def _public_addresses(answers: Sequence[_DnsAnswer]) -> tuple[str, ...]:
    if not answers or len(answers) > 64:
        raise _Rejected()
    addresses = set()
    for family, kind, protocol, _, sockaddr in answers:
        if (
            family not in {socket.AF_INET, socket.AF_INET6}
            or kind != socket.SOCK_STREAM
            or protocol != socket.IPPROTO_TCP
            or len(sockaddr) != (2 if family == socket.AF_INET else 4)
            or sockaddr[1] != 443
            or (family == socket.AF_INET6 and sockaddr[2:] != (0, 0))
        ):
            raise _Rejected()
        raw = sockaddr[0]
        if not isinstance(raw, str) or "%" in raw:
            raise _Rejected()
        address = ipaddress.ip_address(raw)
        if (
            address.version != (4 if family == socket.AF_INET else 6)
            or not address.is_global
            or address.is_multicast
            or address.is_reserved
            or address.is_loopback
            or address.is_link_local
            or address.is_unspecified
            or (
                isinstance(address, ipaddress.IPv6Address)
                and (
                    address.ipv4_mapped is not None
                    or address.sixtofour is not None
                    or address.teredo is not None
                    or address in ipaddress.IPv6Network("64:ff9b::/96")
                )
            )
        ):
            raise _Rejected()
        addresses.add(str(address))
    return tuple(sorted(addresses))


class _ResponseSocket:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    def makefile(self, mode: str) -> io.BytesIO:
        return io.BytesIO(self.raw)


def _response_status(raw: bytes) -> int:
    end = raw.find(b"\r\n\r\n")
    if end < 0 or end + 4 > _HEADER_BOUND or len(raw) - end - 4 > _BODY_BOUND:
        raise _Rejected()
    # Parse only already bounded memory. HTTPResponse cannot perform another request.
    response = http.client.HTTPResponse(cast(socket.socket, _ResponseSocket(raw)))
    try:
        response.begin()
        if response.status < 200 or response.status >= 300:
            return response.status
        if response.length is not None and response.length > _BODY_BOUND:
            raise _Rejected()
        expected = response.length
        content = response.read(_BODY_BOUND + 1)
        if len(content) > _BODY_BOUND:
            raise _Rejected()
        if expected is not None and len(content) != expected:
            raise http.client.IncompleteRead(b"", expected - len(content))
        return response.status
    finally:
        response.close()


class ConfiguredAlertWebhook:
    def __init__(
        self,
        *,
        destinations: tuple[WebhookDestination, ...] = (),
        credentials: WebhookCredentialPort | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        origins = {item.key: item for item in load_webhook_contract()}
        if (
            not isinstance(destinations, tuple)
            or len(destinations) > 256
            or any(
                not isinstance(item, WebhookDestination) or item.origin_key not in origins
                for item in destinations
            )
        ):
            raise WebhookConfigurationError()
        self._destinations = {item.version_id: item for item in destinations}
        if len(self._destinations) != len(destinations):
            raise WebhookConfigurationError()
        self._origins, self._credentials = origins, credentials
        self._clock = clock or (lambda: datetime.now(UTC))

    async def deliver(
        self, destination_version_id: UUID, payload: AlertNotificationPayload
    ) -> AlertDeliveryReceipt:
        if (
            not isinstance(destination_version_id, UUID)
            or type(payload) is not AlertNotificationPayload
        ):
            raise WebhookConfigurationError()
        outcome = AlertDeliveryOutcome.UNAVAILABLE
        reason: AlertReason | None = AlertReason.NOT_CONFIGURED
        target = self._destinations.get(destination_version_id)
        if target is not None and self._credentials is not None:
            try:
                async with asyncio.timeout(_TOTAL_SECONDS):
                    credential = await self._credentials.resolve_webhook_credential(
                        target.version_id, target.credential_reference
                    )
                    if credential is not None:
                        status = await self._deliver(target, credential, payload)
                        if 200 <= status < 300:
                            outcome, reason = AlertDeliveryOutcome.ACCEPTED, None
                        elif status in {408, 425, 429} or status >= 500:
                            outcome, reason = (
                                AlertDeliveryOutcome.RETRYABLE_FAILURE,
                                AlertReason.PUBLICATION_UNAVAILABLE,
                            )
                        else:
                            outcome, reason = (
                                AlertDeliveryOutcome.PERMANENT_FAILURE,
                                AlertReason.PUBLICATION_UNAVAILABLE,
                            )
            except _Rejected:
                outcome, reason = AlertDeliveryOutcome.PERMANENT_FAILURE, AlertReason.ACCESS_DENIED
            except Exception:
                # Return after leaving the exception scope: no raw cause/context or receiver bytes.
                outcome, reason = (
                    AlertDeliveryOutcome.RETRYABLE_FAILURE,
                    AlertReason.PUBLICATION_UNAVAILABLE,
                )
        return AlertDeliveryReceipt(
            delivery_id=payload.delivery_id,
            outcome=outcome,
            reason=reason,
            observed_at=self._clock(),
        )

    async def _deliver(
        self,
        target: WebhookDestination,
        credential: WebhookCredential,
        payload: AlertNotificationPayload,
    ) -> int:
        origin = self._origins[target.origin_key]
        body = encode_alert_record(payload)
        if len(body) > _BODY_BOUND:
            raise _Rejected()
        loop = asyncio.get_running_loop()
        async with asyncio.timeout(_CONNECT_SECONDS):
            answers = await loop.getaddrinfo(
                origin.hostname, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
            )
            addresses = _public_addresses(answers)
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.set_alpn_protocols(["http/1.1"])
            # Connect to the checked numeric address. TLS still checks the configured hostname.
            reader, writer = await asyncio.open_connection(
                addresses[0],
                443,
                ssl=context,
                server_hostname=origin.hostname,
                limit=_HEADER_BOUND + _BODY_BOUND + 1,
                ssl_handshake_timeout=_CONNECT_SECONDS,
                ssl_shutdown_timeout=1,
            )
        try:
            request = (
                f"POST {_PATH} HTTP/1.1\r\nHost: {origin.hostname}\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\nIdempotency-Key: {payload.delivery_id}\r\n"
                f"Authorization: Bearer {credential.value}\r\nConnection: close\r\n\r\n"
            ).encode("ascii") + body
            writer.write(request)
            await writer.drain()
            raw = bytearray()
            while True:
                async with asyncio.timeout(_READ_SECONDS):
                    chunk = await reader.read(min(8192, _HEADER_BOUND + _BODY_BOUND + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > _HEADER_BOUND + _BODY_BOUND:
                    raise _Rejected()
            return _response_status(bytes(raw))
        finally:
            writer.close()
            # Closing is bounded independently, including cancellation at the total deadline.
            with suppress(Exception):
                async with asyncio.timeout(1):
                    await writer.wait_closed()
