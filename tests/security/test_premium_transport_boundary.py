"""Only the reviewed fixed acquisition module gains its required stream transport."""

import ast
import hashlib

import pytest
from trading212_provider.allowlist import load_capability_registry

from scripts import check_trading212_boundary as boundary

pytestmark = pytest.mark.security


def transport_source() -> str:
    return boundary.PREMIUM_ACQUISITION_OWNER.read_text(encoding="utf-8")


def test_named_premium_owner_permits_only_its_required_socket_and_stream() -> None:
    owner = boundary.PREMIUM_ACQUISITION_OWNER
    source = "import socket\nimport asyncio\nasyncio.open_connection('1.1.1.1', 443)\n"
    assert boundary._transport_import_findings(owner, ast.parse(source)) == []
    assert (
        boundary._transport_import_findings(
            owner, ast.parse("from asyncio import open_connection as connect\n")
        )
        == []
    )
    assert boundary._transport_import_findings(owner, ast.parse(transport_source())) == []
    assert boundary._premium_surface_findings(owner, ast.parse(transport_source())) == []
    for sibling in ("premium_acquisition.py", "premium_parsing.py", "other_transport.py"):
        assert boundary._transport_import_findings(owner.with_name(sibling), ast.parse(source))


@pytest.mark.parametrize(
    "source",
    [
        "import httpx",
        "import http.client",
        "from urllib import request",
        "import requests",
        "from asyncio import *",
        "from asyncio import create_connection",
        "from asyncio.streams import open_connection",
        "asyncio.create_connection('1.1.1.1', 443)",
        "asyncio.create_datagram_endpoint(None)",
        "loop.create_connection(None, '1.1.1.1', 443)",
    ],
)
def test_exact_exception_does_not_allow_generic_clients_or_other_factories(source: str) -> None:
    assert boundary._transport_import_findings(
        boundary.PREMIUM_ACQUISITION_OWNER, ast.parse(source)
    )


@pytest.mark.parametrize(
    "before,after",
    [
        ('"/query"', '"/arbitrary"'),
        ('"www.alphavantage.co"', '"unreviewed.example.org"'),
        ("async def daily_adjusted(", "async def request("),
        ("command: AcquireDailyAdjusted,", "url: str, command: AcquireDailyAdjusted,"),
        (
            "return await self._get(command, permit, credential, now=now)",
            "return await self.request(command)",
        ),
    ],
)
def test_fixed_surface_rejects_unknown_routes_and_generic_dispatch(before: str, after: str) -> None:
    original = transport_source()
    assert before in original
    altered = original.replace(before, after, 1)
    assert boundary._premium_surface_findings(
        boundary.PREMIUM_ACQUISITION_OWNER, ast.parse(altered)
    )


def test_generic_module_entrypoint_cannot_bypass_named_class_surface() -> None:
    altered = (
        transport_source()
        + "\nasync def fetch(url, headers):\n    return await send(url, headers)\n"
    )
    assert boundary._premium_surface_findings(
        boundary.PREMIUM_ACQUISITION_OWNER, ast.parse(altered)
    )


def test_original_broker_contract_is_byte_exact_and_still_only_ten_gets() -> None:
    # Frozen contract bytes and exact paths are independent of the new provider adapters.
    assert (
        hashlib.sha256(boundary.ORIGIN_CONTRACT.read_bytes()).hexdigest()
        == "36aa7afbbeb416bfeaca4efda31bc52983bcbeaab93aea906fa43204cf12a284"
    )
    registry = load_capability_registry(boundary.ORIGIN_CONTRACT)
    assert tuple((entry.name, entry.path_template) for entry in registry.values()) == (
        ("account_summary", "/equity/account/summary"),
        ("metadata_instruments", "/equity/metadata/instruments"),
        ("metadata_exchanges", "/equity/metadata/exchanges"),
        ("portfolio_positions", "/equity/positions"),
        ("pending_orders", "/equity/orders"),
        ("order_detail", "/equity/orders/{order_id}"),
        ("historical_orders", "/equity/history/orders"),
        ("historical_transactions", "/equity/history/transactions"),
        ("historical_dividends", "/equity/history/dividends"),
        ("historical_exports", "/equity/history/exports"),
    )
    assert boundary._client_surface_findings() == []
    assert boundary._provider_call_findings(
        boundary.TRANSPORT_OWNER, ast.parse("client.request('GET', '/equity/account/summary')")
    )
