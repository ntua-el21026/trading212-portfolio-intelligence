import asyncio
import socket
import ssl
from collections.abc import Sequence
from typing import cast

import pytest
from trading212_reference_data import premium_transport as transport_module
from trading212_reference_data.premium_acquisition_types import (
    AcquireDailyAdjusted,
    AcquireEcbReferenceFx,
    AcquisitionRejected,
    AlphaVantageCredential,
)
from trading212_reference_data.premium_acquisition_types import (
    AcquisitionCapability as Kind,
)
from trading212_reference_data.premium_acquisition_types import (
    AcquisitionFailureCode as Code,
)
from trading212_reference_data.premium_transport import (
    FixedPremiumTransport,
    _body,
    _headers,
    _HttpBody,
)

from tests.unit.reference_data.premium_fixtures import AT, SECRET, command, permit


class Tls:
    def selected_alpn_protocol(self) -> str:
        return "http/1.1"


class Writer:
    def __init__(self, *, peer: str = "1.1.1.1") -> None:
        self.peer = peer
        self.request = b""
        self.closed = False

    def get_extra_info(self, name: str) -> object:
        return (self.peer, 443) if name == "peername" else Tls()

    def write(self, body: bytes) -> None:
        self.request += body

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass


def stream(body: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader(limit=8193)
    reader.feed_data(body)
    reader.feed_eof()
    return reader


def network(
    monkeypatch: pytest.MonkeyPatch,
    raw: bytes,
    *,
    peer: str = "1.1.1.1",
    answers: Sequence[tuple[int, int, int, str, tuple[object, ...]]] | None = None,
) -> tuple[Writer, asyncio.StreamReader, list[tuple[str, dict[str, object]]]]:
    writer, reader = Writer(peer=peer), stream(raw)
    calls: list[tuple[str, dict[str, object]]] = []

    async def dns(
        *args: object, **kwargs: object
    ) -> list[tuple[int, int, int, str, tuple[object, ...]]]:
        return (
            list(answers)
            if answers is not None
            else [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("1.1.1.1", 443))]
        )

    async def connect(
        host: str, port: int, **kwargs: object
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        assert port == 443
        calls.append((host, kwargs))
        return reader, cast(asyncio.StreamWriter, writer)

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    monkeypatch.setattr(asyncio, "open_connection", connect)
    return writer, reader, calls


@pytest.mark.asyncio
async def test_fixed_get_pins_numeric_peer_tls_hostname_and_terminal_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, _, calls = network(
        monkeypatch,
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}",
    )
    request = command()
    assert isinstance(request, AcquireDailyAdjusted)
    response = await FixedPremiumTransport().daily_adjusted(
        request, permit(request), AlphaVantageCredential(SECRET), now=AT
    )
    assert response.body == b"{}" and response.status == 200
    assert writer.request.startswith(
        b"GET /query?function=TIME_SERIES_DAILY_ADJUSTED&symbol=I"
        b"BM&outputsize=full&datatype=json&apikey="
    )
    assert (
        b"Host: www.alphavantage.co\r\n" in writer.request
        and b"Accept-Encoding: identity" in writer.request
    )
    assert calls[0][0] == "1.1.1.1" and calls[0][1]["server_hostname"] == "www.alphavantage.co"
    context = calls[0][1]["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert (
        context.check_hostname
        and context.verify_mode == ssl.CERT_REQUIRED
        and context.minimum_version >= ssl.TLSVersion.TLSv1_2
    )
    assert (
        writer.closed
        and SECRET not in repr(response)
        and SECRET not in str(AlphaVantageCredential(SECRET))
    )


@pytest.mark.asyncio
async def test_ecb_path_has_no_query_or_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    writer, _, _ = network(
        monkeypatch, b"HTTP/1.1 200 OK\r\nContent-Type: text/xml\r\nContent-Length: 4\r\n\r\n<a/>"
    )
    request = command(Kind.REFERENCE_FX)
    assert isinstance(request, AcquireEcbReferenceFx)
    await FixedPremiumTransport().ecb_reference_fx(request, permit(request), now=AT)
    assert writer.request.startswith(b"GET /stats/eurofxref/eurofxref-hist-90d.xml HTTP/1.1\r\n")
    assert b"Host: www.ecb.europa.eu" in writer.request and b"apikey" not in writer.request


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "192.168.1.1"])
async def test_any_private_dns_answer_denies_before_connection(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (host, 443))
        for host in ("1.1.1.1", address)
    ]
    writer, _, calls = network(monkeypatch, b"", answers=answers)
    request = command()
    assert isinstance(request, AcquireDailyAdjusted)
    with pytest.raises(AcquisitionRejected) as failure:
        await FixedPremiumTransport().daily_adjusted(
            request, permit(request), AlphaVantageCredential(SECRET), now=AT
        )
    assert failure.value.code is Code.ACCESS_DENIED and not calls and not writer.request


@pytest.mark.asyncio
async def test_changed_tls_peer_rejects_before_sending_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, _, _ = network(monkeypatch, b"", peer="8.8.8.8")
    request = command()
    assert isinstance(request, AcquireDailyAdjusted)
    with pytest.raises(AcquisitionRejected):
        await FixedPremiumTransport().daily_adjusted(
            request, permit(request), AlphaVantageCredential(SECRET), now=AT
        )
    assert not writer.request and writer.closed


@pytest.mark.asyncio
async def test_redirect_body_and_destination_are_never_acquired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, reader, calls = network(
        monkeypatch,
        (
            b"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1/private\r"
            b"\nContent-Length: 7\r\n\r\nprivate"
        ),
    )
    request = command()
    assert isinstance(request, AcquireDailyAdjusted)
    result = await FixedPremiumTransport().daily_adjusted(
        request, permit(request), AlphaVantageCredential(SECRET), now=AT
    )
    assert result.status == 302 and result.body == b"" and len(calls) == 1
    assert await reader.read() == b"private" and writer.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers,body",
    [
        ({"content-length": "9"}, b"short"),
        ({"content-length": "1", "transfer-encoding": "chunked"}, b"0\r\n\r\n"),
        ({"content-encoding": "gzip"}, b"compressed"),
        ({"transfer-encoding": "chunked"}, b"f\r\n012345678901234\r\n0\r\n\r\n"),
        ({"transfer-encoding": "chunked"}, b"1;x=1\r\na\r\n0\r\n\r\n"),
        ({"transfer-encoding": "chunked"}, b"0\r\nX-Trailer: unsupported\r\n\r\n"),
    ],
)
async def test_ambiguous_truncated_or_oversized_framing_rejects(
    headers: dict[str, str], body: bytes
) -> None:
    with pytest.raises((AcquisitionRejected, asyncio.IncompleteReadError)):
        await _body(stream(body), headers, 8)


@pytest.mark.asyncio
async def test_exact_chunked_body_is_bounded_and_preserved() -> None:
    assert (
        await _body(stream(b"2\r\n{}\r\n0\r\n\r\n"), {"transfer-encoding": "chunked"}, 2) == b"{}"
    )


@pytest.mark.parametrize(
    "raw",
    [
        b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\nContent-Length: 2\r\n\r\n",
        b"HTTP/1.1 429 Slow\r\nRetry-After: 61\r\n\r\n",
        b"HTTP/1.1 200 OK\r\n Folded: value\r\n\r\n",
    ],
)
def test_header_conflicts_and_unhonorable_retry_delays_reject(raw: bytes) -> None:
    with pytest.raises(AcquisitionRejected):
        _headers(raw, now=AT)


def test_retry_after_is_bounded_schedule_metadata() -> None:
    assert _headers(b"HTTP/1.1 429 Slow\r\nRetry-After: 12\r\n\r\n", now=AT)[2] == 12
    assert (
        _headers(
            b"HTTP/1.1 429 Slow\r\nRetry-After: Tue, 15 Sep 2026 20:00:15 GMT\r\n\r\n", now=AT
        )[2]
        == 15
    )


@pytest.mark.asyncio
async def test_wrong_named_operation_rejects_before_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    writer, _, calls = network(monkeypatch, b"")
    request = command(Kind.ETF_PROFILE)
    with pytest.raises(AcquisitionRejected):
        await FixedPremiumTransport().daily_adjusted(
            cast(AcquireDailyAdjusted, request),
            permit(request),
            AlphaVantageCredential(SECRET),
            now=AT,
        )
    assert not calls and not writer.request


@pytest.mark.asyncio
async def test_raw_transport_exception_context_is_not_exposed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def rejected(*args: object, **kwargs: object) -> _HttpBody:
        raise RuntimeError(f"credential={SECRET}; private provider body")

    transport = FixedPremiumTransport()
    monkeypatch.setattr(transport, "_request", rejected)
    request = command()
    assert isinstance(request, AcquireDailyAdjusted)
    with pytest.raises(AcquisitionRejected) as failure:
        await transport.daily_adjusted(
            request, permit(request), AlphaVantageCredential(SECRET), now=AT
        )
    assert (
        SECRET not in str(failure.value)
        and failure.value.__context__ is None
        and failure.value.__cause__ is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "host,path",
    [
        ("unreviewed.example.org", "/query"),
        ("www.alphavantage.co", "/arbitrary"),
        ("www.ecb.europa.eu", "/query"),
    ],
)
async def test_unknown_terminal_route_denied_before_dns_or_credentials(
    monkeypatch: pytest.MonkeyPatch,
    host: str,
    path: str,
) -> None:
    writer, _, calls = network(monkeypatch, b"")
    request = command()
    assert isinstance(request, AcquireDailyAdjusted)
    monkeypatch.setattr(transport_module, "_selectors", lambda *args: (host, path, (), 1024))
    with pytest.raises(AcquisitionRejected) as denied:
        await FixedPremiumTransport().daily_adjusted(
            request,
            permit(request),
            AlphaVantageCredential(SECRET),
            now=AT,
        )
    assert denied.value.code is Code.ACCESS_DENIED
    assert not calls and not writer.request


@pytest.mark.parametrize(
    "kind,function,selector",
    [
        (Kind.DAILY_ADJUSTED, "TIME_SERIES_DAILY_ADJUSTED", "symbol"),
        (Kind.ETF_PROFILE, "ETF_PROFILE", "symbol"),
        (Kind.COMPANY_OVERVIEW, "OVERVIEW", "symbol"),
        (Kind.NEWS_SENTIMENT, "NEWS_SENTIMENT", "tickers"),
    ],
)
def test_all_four_alpha_vantage_contracts_have_exact_selectors(
    kind: Kind,
    function: str,
    selector: str,
) -> None:
    request = command(kind)
    host, path, pairs, maximum = transport_module._selectors(request, permit(request))
    params = dict(pairs)
    assert (host, path, maximum) == ("www.alphavantage.co", "/query", 8 * 1024 * 1024)
    assert params["function"] == function and params[selector] == "IBM"
    assert len(params) == len(pairs) and "apikey" not in params
    expected = {"function", selector}
    if kind is Kind.DAILY_ADJUSTED:
        expected |= {"outputsize", "datatype"}
        assert params["outputsize"] == "full" and params["datatype"] == "json"
    if kind is Kind.NEWS_SENTIMENT:
        expected |= {"time_from", "time_to", "limit", "sort"}
        assert (params["time_from"], params["time_to"], params["limit"], params["sort"]) == (
            "20260914T2000",
            "20260915T2000",
            "100",
            "LATEST",
        )
    assert set(params) == expected
