"""Five fixed GET transfers with bounded framing, pinned public DNS and verified TLS."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import ssl
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

from .alert_webhook import _public_addresses
from .premium_acquisition_types import (
    AcquireCompanyOverview,
    AcquireDailyAdjusted,
    AcquireEcbReferenceFx,
    AcquireEtfProfile,
    AcquireNewsSentiment,
    AcquisitionCommand,
    AcquisitionPermit,
    AcquisitionRejected,
    AlphaVantageCredential,
    capability,
)
from .premium_acquisition_types import (
    AcquisitionFailureCode as Code,
)

_HEADER_BYTES = 8192
_ECB_PATH = "/stats/eurofxref/eurofxref-hist-90d.xml"


@dataclass(frozen=True, slots=True, repr=False)
class _HttpBody:
    status: int
    body: bytes = field(repr=False)
    retry_after_seconds: int | None = None


def _selectors(
    command: AcquisitionCommand, permit: AcquisitionPermit
) -> tuple[str, str, tuple[tuple[str, str], ...], int]:
    if (permit.owner_id, permit.account_id, permit.mapping_version_id, permit.capability) != (
        command.owner_id,
        command.account_id,
        command.mapping_version_id,
        capability(command),
    ):
        raise AcquisitionRejected(Code.ACCESS_DENIED)
    if type(command) is AcquireEcbReferenceFx:
        return "www.ecb.europa.eu", _ECB_PATH, (), 1024 * 1024
    symbol = permit.symbol
    if symbol is None or re.fullmatch(r"[A-Z0-9][A-Z0-9.:-]{0,39}", symbol) is None:
        raise AcquisitionRejected()
    params: tuple[tuple[str, str], ...]
    if type(command) is AcquireDailyAdjusted:
        params = (
            ("function", "TIME_SERIES_DAILY_ADJUSTED"),
            ("symbol", symbol),
            ("outputsize", "full"),
            ("datatype", "json"),
        )
    elif type(command) is AcquireEtfProfile:
        params = (("function", "ETF_PROFILE"), ("symbol", symbol))
    elif type(command) is AcquireCompanyOverview:
        params = (("function", "OVERVIEW"), ("symbol", symbol))
    elif type(command) is AcquireNewsSentiment:
        params = (
            ("function", "NEWS_SENTIMENT"),
            ("tickers", symbol),
            ("time_from", command.time_from.strftime("%Y%m%dT%H%M")),
            ("time_to", command.time_to.strftime("%Y%m%dT%H%M")),
            ("sort", "LATEST"),
            ("limit", str(command.limit)),
        )
    else:
        raise AcquisitionRejected()
    return "www.alphavantage.co", "/query", params, 8 * 1024 * 1024


def _headers(raw: bytes, *, now: datetime) -> tuple[int, dict[str, str], int | None]:
    if len(raw) > _HEADER_BYTES or not raw.endswith(b"\r\n\r\n"):
        raise AcquisitionRejected(Code.PAYLOAD_TOO_LARGE)
    try:
        lines = raw.decode("ascii").split("\r\n")
    except UnicodeError:
        raise AcquisitionRejected() from None
    match = re.fullmatch(r"HTTP/1\.[01] ([1-5][0-9]{2})(?: [\x20-\x7e]*)?", lines[0])
    if match is None:
        raise AcquisitionRejected()
    headers: dict[str, str] = {}
    for line in lines[1:-2]:
        if ":" not in line or line[:1].isspace():
            raise AcquisitionRejected()
        key, value = line.split(":", 1)
        if not re.fullmatch(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+", key) or any(
            ord(char) < 32 and char != "\t" for char in value
        ):
            raise AcquisitionRejected()
        key, value = key.lower(), value.strip()
        # Reject duplicates, including conflicting framing and Retry-After values.
        if key in headers:
            raise AcquisitionRejected()
        headers[key] = value
    status, retry = int(match.group(1)), None
    if "retry-after" in headers:
        value = headers["retry-after"]
        if re.fullmatch(r"[0-9]{1,2}", value):
            retry = int(value)
        else:
            date = None
            with suppress(ValueError, TypeError, OverflowError):
                date = parsedate_to_datetime(value)
            if date is None or date.tzinfo is None:
                raise AcquisitionRejected()
            seconds = (date - now).total_seconds()
            retry = max(0, int(seconds) + (seconds > int(seconds)))
        if not 0 <= retry <= 60:
            raise AcquisitionRejected()
    return status, headers, retry


async def _read(reader: asyncio.StreamReader, size: int) -> bytes:
    async with asyncio.timeout(10):
        return await reader.readexactly(size)


async def _line(reader: asyncio.StreamReader, bound: int) -> bytes:
    async with asyncio.timeout(10):
        value = await reader.readuntil(b"\r\n")
    if len(value) > bound:
        raise AcquisitionRejected(Code.PAYLOAD_TOO_LARGE)
    return value


async def _body(reader: asyncio.StreamReader, headers: dict[str, str], maximum: int) -> bytes:
    if headers.get("content-encoding", "identity").lower() != "identity":
        raise AcquisitionRejected(Code.UNSUPPORTED)
    length, transfer = headers.get("content-length"), headers.get("transfer-encoding")
    if length is not None and transfer is not None:
        raise AcquisitionRejected()
    if transfer is not None:
        if transfer.lower() != "chunked":
            raise AcquisitionRejected(Code.UNSUPPORTED)
        result = bytearray()
        while True:
            line = await _line(reader, 18)
            if re.fullmatch(rb"[0-9a-fA-F]{1,12}\r\n", line) is None:
                raise AcquisitionRejected()
            size = int(line[:-2], 16)
            if size > maximum - len(result):
                raise AcquisitionRejected(Code.PAYLOAD_TOO_LARGE)
            if size == 0:
                if await _line(reader, 2) != b"\r\n":
                    raise AcquisitionRejected()
                return bytes(result)
            result.extend(await _read(reader, size))
            if await _read(reader, 2) != b"\r\n":
                raise AcquisitionRejected()
    if length is not None:
        if re.fullmatch(r"[0-9]{1,10}", length) is None:
            raise AcquisitionRejected()
        size = int(length)
        if size > maximum:
            raise AcquisitionRejected(Code.PAYLOAD_TOO_LARGE)
        return await _read(reader, size)
    result = bytearray()
    while True:
        async with asyncio.timeout(10):
            chunk = await reader.read(min(8192, maximum + 1 - len(result)))
        if not chunk:
            return bytes(result)
        result.extend(chunk)
        if len(result) > maximum:
            raise AcquisitionRejected(Code.PAYLOAD_TOO_LARGE)


class FixedPremiumTransport:
    """No URL, method, arbitrary query or caller header parameter is exposed."""

    async def daily_adjusted(
        self,
        command: AcquireDailyAdjusted,
        permit: AcquisitionPermit,
        credential: AlphaVantageCredential,
        *,
        now: datetime,
    ) -> _HttpBody:
        if type(command) is not AcquireDailyAdjusted:
            raise AcquisitionRejected()
        return await self._get(command, permit, credential, now=now)

    async def etf_profile(
        self,
        command: AcquireEtfProfile,
        permit: AcquisitionPermit,
        credential: AlphaVantageCredential,
        *,
        now: datetime,
    ) -> _HttpBody:
        if type(command) is not AcquireEtfProfile:
            raise AcquisitionRejected()
        return await self._get(command, permit, credential, now=now)

    async def company_overview(
        self,
        command: AcquireCompanyOverview,
        permit: AcquisitionPermit,
        credential: AlphaVantageCredential,
        *,
        now: datetime,
    ) -> _HttpBody:
        if type(command) is not AcquireCompanyOverview:
            raise AcquisitionRejected()
        return await self._get(command, permit, credential, now=now)

    async def news_sentiment(
        self,
        command: AcquireNewsSentiment,
        permit: AcquisitionPermit,
        credential: AlphaVantageCredential,
        *,
        now: datetime,
    ) -> _HttpBody:
        if type(command) is not AcquireNewsSentiment:
            raise AcquisitionRejected()
        return await self._get(command, permit, credential, now=now)

    async def ecb_reference_fx(
        self, command: AcquireEcbReferenceFx, permit: AcquisitionPermit, *, now: datetime
    ) -> _HttpBody:
        if type(command) is not AcquireEcbReferenceFx:
            raise AcquisitionRejected()
        return await self._get(command, permit, None, now=now)

    async def _get(
        self,
        command: AcquisitionCommand,
        permit: AcquisitionPermit,
        credential: AlphaVantageCredential | None,
        *,
        now: datetime,
    ) -> _HttpBody:
        failure = Code.TRANSIENT_FAILURE
        try:
            async with asyncio.timeout(20):
                return await self._request(command, permit, credential, now=now)
        except AcquisitionRejected as rejected:
            failure = rejected.code
        except ssl.SSLError:
            failure = Code.ACCESS_DENIED
        except TimeoutError:
            failure = Code.TIMEOUT
        except Exception:
            failure = Code.TRANSIENT_FAILURE
        # Raise only after leaving the exception scope, so neither raw body nor
        # credential-bearing transport cause/context crosses this boundary.
        raise AcquisitionRejected(failure)

    async def _request(
        self,
        command: AcquisitionCommand,
        permit: AcquisitionPermit,
        credential: AlphaVantageCredential | None,
        *,
        now: datetime,
    ) -> _HttpBody:
        host, path, params, maximum = _selectors(command, permit)
        if (host, path) not in {
            ("www.alphavantage.co", "/query"),
            ("www.ecb.europa.eu", _ECB_PATH),
        }:
            raise AcquisitionRejected(Code.ACCESS_DENIED)
        if host == "www.alphavantage.co":
            if type(credential) is not AlphaVantageCredential:
                raise AcquisitionRejected(Code.AUTHENTICATION_FAILED)
            params += (("apikey", credential.reveal()),)
        elif credential is not None:
            raise AcquisitionRejected()
        target = path + ("?" + urlencode(params) if params else "")
        if len(target) > 2048:
            raise AcquisitionRejected()
        loop = asyncio.get_running_loop()
        async with asyncio.timeout(5):
            answers = await loop.getaddrinfo(
                host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
            )
            try:
                addresses = _public_addresses(answers)
            except Exception:
                raise AcquisitionRejected(Code.ACCESS_DENIED) from None
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.set_alpn_protocols(["http/1.1"])
            reader, writer = await asyncio.open_connection(
                addresses[0],
                443,
                ssl=context,
                server_hostname=host,
                limit=_HEADER_BYTES + 1,
                ssl_handshake_timeout=5,
                ssl_shutdown_timeout=1,
            )
        try:
            peer = writer.get_extra_info("peername")
            tls = writer.get_extra_info("ssl_object")
            if (
                not isinstance(peer, tuple)
                or len(peer) not in (2, 4)
                or ipaddress.ip_address(peer[0]) != ipaddress.ip_address(addresses[0])
                or peer[1] != 443
                or tls is None
                or tls.selected_alpn_protocol() not in (None, "http/1.1")
            ):
                raise AcquisitionRejected(Code.ACCESS_DENIED)
            # The only place the API key is materialized is the terminal encrypted
            # request. No URL/query/response is returned or attached to an error.
            writer.write(
                (
                    f"GET {target} HTTP/1.1\r\nHost: {host}\r\n"
                    "Accept: application/json, application/xml, text/xml\r\n"
                    "Accept-Encoding: identity\r\nConnection: close\r\n"
                    "User-Agent: t212pi-reference-v1\r\n\r\n"
                ).encode("ascii")
            )
            await writer.drain()
            async with asyncio.timeout(10):
                raw_header = await reader.readuntil(b"\r\n\r\n")
            status, headers, retry = _headers(raw_header, now=now)
            if not 200 <= status < 300:
                # This includes all redirects. Their bodies and Location targets
                # are never acquired or followed.
                return _HttpBody(status, b"", retry)
            content_parts = tuple(
                part.strip().lower() for part in headers.get("content-type", "").split(";")
            )
            content_type = content_parts[0]
            if any(part not in {"charset=utf-8", 'charset="utf-8"'} for part in content_parts[1:]):
                raise AcquisitionRejected(Code.UNSUPPORTED)
            allowed = (
                {"application/xml", "text/xml"}
                if type(command) is AcquireEcbReferenceFx
                else {"application/json", "text/json"}
            )
            if content_type not in allowed or status != 200:
                raise AcquisitionRejected()
            body = await _body(reader, headers, maximum)
            async with asyncio.timeout(10):
                if await reader.read(1):
                    raise AcquisitionRejected()
            return _HttpBody(status, body, retry)
        finally:
            writer.close()
            with suppress(Exception):
                async with asyncio.timeout(1):
                    await writer.wait_closed()
