"""The new adapter package grants no new broker or arbitrary HTTP authority."""

from pathlib import Path

import pytest

from scripts import check_architecture as architecture
from scripts import check_trading212_boundary as broker_boundary

pytestmark = pytest.mark.security


@pytest.mark.parametrize(
    "consumer", ["domain", "analytics", "application", "persistence", "api-contracts"]
)
def test_canonical_layers_cannot_import_reference_adapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, consumer: str
) -> None:
    path = tmp_path / "packages" / consumer / "source.py"
    path.parent.mkdir(parents=True)
    path.write_text("import trading212_reference_data\n")
    monkeypatch.setattr(architecture, "ROOT", tmp_path)
    assert architecture.validate_architecture() == [
        f"packages/{consumer}/source.py imports forbidden dependency trading212_reference_data"
    ]


def test_reference_namespace_is_not_a_broad_transport_exception(tmp_path: Path) -> None:
    path = broker_boundary.ROOT / "packages/reference-data/src/trading212_reference_data/remote.py"
    import ast

    findings = broker_boundary._transport_import_findings(path, ast.parse("import httpx\n"))
    assert len(findings) == 1 and "narrowly named broker or alert adapter" in findings[0]


def test_alert_adapter_exception_is_exact_and_keeps_httpx_denied() -> None:
    import ast

    owner = broker_boundary.ALERT_WEBHOOK_OWNER
    assert (
        broker_boundary._transport_import_findings(
            owner, ast.parse("import http.client\nimport socket\n")
        )
        == []
    )
    assert broker_boundary._transport_import_findings(owner, ast.parse("import httpx\n"))
    sibling = owner.with_name("other_webhook.py")
    assert (
        len(
            broker_boundary._transport_import_findings(
                sibling, ast.parse("import http.client\nimport socket\n")
            )
        )
        == 2
    )
    assert broker_boundary._transport_import_findings(
        sibling, ast.parse("import asyncio\nasyncio.open_connection('example.org',443)\n")
    )


@pytest.mark.parametrize(
    "source",
    [
        "from asyncio import open_connection as connect\nconnect('example.org',443)",
        "from asyncio.streams import open_connection\nopen_connection('example.org',443)",
        "from asyncio import *",
        "from http import client as transport\ntransport.HTTPSConnection('example.org')",
        "from urllib import request as transport\ntransport.urlopen('https://example.org')",
    ],
)
def test_aliased_stream_imports_do_not_bypass_transport_ownership(source: str) -> None:
    import ast

    sibling = broker_boundary.ALERT_WEBHOOK_OWNER.with_name("other_webhook.py")
    assert broker_boundary._transport_import_findings(sibling, ast.parse(source))
