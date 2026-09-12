"""Authenticated MCP transport assertions over real persisted owner identities."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import cast

from mcp.types import CallToolResult
from starlette.testclient import TestClient
from trading212_mcp.schemas import RESULT_MODELS
from trading212_mcp.server import create_runtime
from trading212_mcp.settings import McpSettings
from trading212_security.principals import Principal, Scope

from tests.integration.phase2_authorization_cases import SETTINGS, Actor, GridBearer, OwnerGrid


class ScopedGridBearer(GridBearer):
    """Preserve persisted identities while varying authenticated token scopes."""

    def __init__(self, actors: tuple[Actor, Actor]) -> None:
        super().__init__(actors)
        self.omitted: Scope | None = None

    async def authenticate(self, token: str) -> Principal:
        principal = await super().authenticate(token)
        if self.omitted is None:
            return principal
        return replace(principal, scopes=principal.scopes - {self.omitted})


def mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict) and all(isinstance(key, str) for key in value)
    return cast("dict[str, object]", value)


def items(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    return [mapping(item) for item in value]


def call(
    client: TestClient,
    actor: Actor,
    name: str,
    arguments: dict[str, object],
) -> CallToolResult:
    response = client.post(
        "/mcp",
        headers={
            "Authorization": "Bearer " + actor.token,
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200
    result = CallToolResult.model_validate(response.json()["result"])
    assert result.structured_content is not None
    RESULT_MODELS[name].model_validate(result.structured_content)
    return result


def payload(result: CallToolResult) -> dict[str, object]:
    assert result.structured_content is not None
    error = result.structured_content["error"]
    assert not result.is_error, None if error is None else mapping(error)["code"]
    assert result.structured_content["error"] is None
    return mapping(result.structured_content["data"])


def denied(result: CallToolResult, code: str, private: tuple[str, ...]) -> None:
    assert result.is_error and result.structured_content is not None
    assert result.structured_content["data"] is None
    assert mapping(result.structured_content["error"])["code"] == code
    rendered = result.model_dump_json()
    assert all(value not in rendered for value in private)
    assert "p210-owner-" not in rendered


@contextmanager
def legacy_client(grid: OwnerGrid) -> Iterator[tuple[TestClient, ScopedGridBearer]]:
    bearer = ScopedGridBearer(grid.actors)
    runtime = create_runtime(
        security_settings=SETTINGS.model_copy(update={"issuer": "https://issuer.example"}),
        mcp_settings=McpSettings.model_validate({"public_base_url": "https://portfolio.example"}),
        service=grid.portfolio,
        bearer_authenticator=bearer,
        clock=lambda: grid.at,
    )
    with TestClient(runtime.asgi_app(), base_url="http://localhost") as client:
        yield client, bearer
