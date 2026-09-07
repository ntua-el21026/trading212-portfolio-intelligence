"""Real target ingestion, API/MCP parity, durable pages, and scoped hierarchy reads."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from mcp.types import CallToolResult
from psycopg import sql
from sqlalchemy import Engine
from sqlalchemy.engine import make_url
from starlette.testclient import TestClient
from trading212_api.main import create_app
from trading212_application import targets as app
from trading212_domain import build_synthetic_identity
from trading212_domain import targets as domain
from trading212_domain.values import CurrencyCode
from trading212_mcp.server import create_runtime
from trading212_mcp.settings import McpSettings
from trading212_persistence import (
    PostgresPortfolioService,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence.seed import seed_synthetic
from trading212_persistence.target_service import PostgresTargetService
from trading212_security.principals import AuthenticationError, Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
KEY = b"target-mcp-parity-cursor-signing-key"


@pytest.fixture(scope="module")
def target_mcp_database() -> Iterator[Engine]:
    parsed = make_url(
        os.environ.get(
            "TEST_DATABASE_URL", "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio"
        ).replace("postgresql://", "postgresql+psycopg://", 1)
    )
    name = "t212pi_targetmcp_" + uuid4().hex[:12]
    admin = (
        parsed.set(database="postgres")
        .render_as_string(hide_password=False)
        .replace("postgresql+psycopg://", "postgresql://", 1)
    )
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = parsed.set(database=name).render_as_string(hide_password=False)
    engine = None
    try:
        configuration = Config("alembic.ini")
        configuration.set_main_option("sqlalchemy.url", url)
        command.upgrade(configuration, "head")
        seed_synthetic(url, app_environment="test")
        engine = create_database_engine(url)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if not name.startswith("t212pi_targetmcp_"):
            raise RuntimeError("Unexpected target test database name.")
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


def _service(engine: Engine) -> PostgresTargetService:
    return PostgresTargetService(
        sessions=create_session_factory(engine),
        clock=lambda: NOW,
        cursor_signing_key=KEY,
    )


class ForeignTargetBearer:
    def __init__(self, principal: Principal) -> None:
        self.principal = replace(
            principal, owner_id=str(uuid4()), expires_at=datetime(2099, 1, 1, tzinfo=UTC)
        )
        self.token = "_".join(("FOREIGN", "TARGET", "CANARY"))

    async def authenticate(self, token: str) -> Principal:
        if token != self.token:
            raise AuthenticationError("Invalid synthetic credential.")
        return self.principal


async def test_canonical_targets_match_api_and_resume_mcp_hierarchy_after_restart(
    target_mcp_database: Engine,
) -> None:
    identity = build_synthetic_identity()
    principal = Principal(
        "mcp-target-parity",
        str(identity.owner.id),
        "test",
        "test",
        frozenset({Scope.TARGETS_READ, Scope.TARGETS_WRITE, Scope.PORTFOLIO_READ}),
        NOW - timedelta(days=1),
        NOW + timedelta(days=1),
    )
    service = _service(target_mcp_database)
    portfolio = await service.create_virtual_portfolio(
        principal,
        app.CreateVirtualPortfolioCommand(
            "Canonical MCP target", CurrencyCode("EUR"), str(identity.account.id)
        ),
        idempotency_key=uuid4().hex,
        correlation_id="target-mcp-parity",
    )
    content = domain.TargetContent(
        (
            domain.TargetNode(
                "group", None, domain.TargetNodeKind.GROUP, "Equities", 0, Decimal("0.8")
            ),
            domain.TargetNode(
                "holding",
                "group",
                domain.TargetNodeKind.HOLDING,
                "Synthetic fund",
                0,
                Decimal("1"),
                domain.TargetHoldingMapping(
                    domain.TargetMappingState.RESOLVED,
                    identity.instrument.id,
                    identity.listing.id,
                ),
            ),
            domain.TargetNode("cash", None, domain.TargetNodeKind.CASH, "Cash", 1, Decimal("0.2")),
        )
    )
    version = await service.create_target_version(
        principal,
        portfolio.id,
        app.CreateTargetVersionCommand(NOW, content=content),
        if_match=portfolio.etag,
        idempotency_key=uuid4().hex,
        correlation_id="target-mcp-parity",
    )
    validation = await service.validate_target_version(
        principal,
        version.id,
        app.ValidateTargetCommand(),
        if_match=version.etag,
        idempotency_key=uuid4().hex,
        correlation_id="target-mcp-parity",
    )
    assert validation.valid
    published = await service.publish_target_version(
        principal,
        version.id,
        app.PublishTargetCommand(validation.id),
        if_match=validation.etag,
        idempotency_key=uuid4().hex,
        correlation_id="target-mcp-parity",
    )
    settings = SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=True,
        allowed_hosts=("localhost", "testserver"),
    )
    observations = PostgresPortfolioService(
        sessions=create_session_factory(target_mcp_database),
        clock=lambda: NOW,
        cursor_signing_key=KEY,
    )
    api = create_app(
        settings=settings, service=observations, target_service=service, clock=lambda: NOW
    )
    with TestClient(api, base_url="https://testserver") as client:
        assert client.post("/api/v1/auth/local-session").status_code == 201
        response = client.get(f"/api/v1/target-versions/{published.id}")
        assert response.status_code == 200, response.text
        canonical = response.json()
    collected: list[dict[str, Any]] = []
    cursor = None
    first_group_id = None
    while True:
        # A fresh application/service instance must accept the previous durable cursor.
        runtime = create_runtime(
            security_settings=settings,
            service=observations,
            target_service=_service(target_mcp_database),
            clock=lambda: NOW,
        )
        result = await runtime.server.call_tool(
            "get_virtual_pie",
            {
                "account_id": str(identity.account.id),
                "virtual_portfolio_id": portfolio.id,
                "limit": 1,
                "cursor": cursor,
            },
        )
        assert isinstance(result, CallToolResult)
        assert not result.is_error, result
        data = result.structured_content
        assert data["data_quality"]["state"] == "valid"
        assert data["data"]["validation"] == canonical["latest_validation"]
        metadata = data["data"]["target_version"]
        for field in ("id", "revision", "state", "content_digest", "effective_at"):
            assert metadata[field] == canonical[field]
        assert metadata["constraints"] == canonical["content"]["constraints"]
        assert data["pagination"]["total"] == 3
        collected.extend(data["data"]["nodes"])
        first_group_id = first_group_id or collected[0]["hierarchy"]["id"]
        cursor = data["pagination"]["next_cursor"]
        if cursor is None:
            break
    assert [item["hierarchy"]["node"]["key"] for item in collected] == ["group", "holding", "cash"]
    by_key = {item["key"]: item for item in canonical["content"]["nodes"]}
    calculated = {item["node"]["key"]: item for item in canonical["flattened_nodes"]}
    for item in collected:
        key = item["hierarchy"]["node"]["key"]
        assert item["hierarchy"]["node"] == by_key[key]
        assert item["calculated"] == calculated[key]
    selected = {
        "account_id": str(identity.account.id),
        "virtual_portfolio_id": portfolio.id,
        "target_version_id": published.id,
    }
    subtree = await runtime.server.call_tool(
        "get_virtual_pie",
        {
            **selected,
            "parent_node_id": first_group_id,
        },
    )
    assert isinstance(subtree, CallToolResult)
    assert not subtree.is_error
    assert subtree.structured_content["pagination"]["total"] == 1
    assert subtree.structured_content["data"]["nodes"][0]["hierarchy"]["node"]["key"] == "holding"
    for invalid in (
        {**selected, "parent_node_id": str(uuid4())},
        {**selected, "account_id": None},
        {**selected, "virtual_portfolio_id": str(uuid4())},
        {**selected, "target_version_id": str(uuid4())},
    ):
        rejected = await runtime.server.call_tool("get_virtual_pie", invalid)
        assert isinstance(rejected, CallToolResult)
        assert rejected.is_error
        assert rejected.structured_content["error"]["code"] == "NOT_FOUND"
    tampered = await runtime.server.call_tool("get_virtual_pie", {**selected, "cursor": "tampered"})
    assert isinstance(tampered, CallToolResult)
    assert tampered.structured_content["error"]["code"] == "CURSOR_INVALID"
    foreign = ForeignTargetBearer(principal)
    remote = create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            issuer="https://issuer.example",
            allowed_hosts=("localhost",),
        ),
        mcp_settings=McpSettings.model_validate({"public_base_url": "https://portfolio.example"}),
        service=observations,
        target_service=_service(target_mcp_database),
        bearer_authenticator=foreign,
        clock=lambda: NOW,
    )
    with TestClient(remote.asgi_app(), base_url="http://localhost") as client:
        response = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {foreign.token}",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_virtual_pie", "arguments": selected},
            },
        )
    assert response.status_code == 200
    assert response.json()["result"]["structuredContent"]["error"]["code"] == "NOT_FOUND"
    assert foreign.token not in response.text
