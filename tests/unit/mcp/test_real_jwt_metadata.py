from __future__ import annotations

import httpx
import pytest
from pydantic import AnyHttpUrl
from trading212_mcp.auth import ExactIssuerUrl
from trading212_mcp.server import create_runtime
from trading212_mcp.settings import McpSettings
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import JwtAuthenticator

from tests.jwt_support import JwtTestSigner


@pytest.mark.parametrize(
    "issuer",
    [
        "https://identity.example.test",
        "https://identity.example.test/",
        "https://Identity.example.test/Tenant%2fTeam",
        "https://identity.example.test/tenant",
    ],
)
async def test_discovery_serializes_exact_configured_issuer(issuer: str) -> None:
    signer = JwtTestSigner.generate("ES256")
    resource = "https://portfolio.example/mcp"
    runtime = create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            issuer=issuer,
            local_synthetic_auth_enabled=False,
            allowed_hosts=("portfolio.example",),
        ),
        mcp_settings=McpSettings(public_base_url=AnyHttpUrl("https://portfolio.example")),
        bearer_authenticator=JwtAuthenticator(
            issuer=issuer,
            audience=resource,
            public_key=signer.public_key,
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime.asgi_app()), base_url="https://portfolio.example"
    ) as client:
        response = await client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    assert response.json()["authorization_servers"] == [issuer]
    assert response.json()["resource"] == resource


@pytest.mark.parametrize(
    "issuer",
    [
        "opaque.issuer",
        "https:identity.example.test",
        "https:/identity.example.test",
        "https:///identity.example.test",
        "http://identity.example.test",
        "https://user@identity.example.test",
        "https://identity.example.test?query",
        "https://identity.example.test/#fragment",
        "https://identity.example.test/bad%xx",
    ],
)
def test_mcp_metadata_issuer_profile_fails_closed(issuer: str) -> None:
    with pytest.raises(ValueError):
        ExactIssuerUrl(issuer)


@pytest.mark.parametrize("issuer", ["http://localhost", "http://127.0.0.1", "http://[::1]"])
def test_mcp_local_loopback_profile_preserves_exact_identity(issuer: str) -> None:
    assert str(ExactIssuerUrl(issuer)) == issuer
