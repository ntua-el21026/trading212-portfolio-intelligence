"""Signed MCP audience validation remains owned by the shared authenticator."""

import logging
import warnings
from datetime import UTC, datetime, timedelta

import pytest
from mcp.shared.exceptions import MCPDeprecationWarning
from starlette.testclient import TestClient
from trading212_application.services import SyntheticPortfolioService
from trading212_mcp.server import create_runtime
from trading212_mcp.settings import McpSettings
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import JwtAuthenticator

from tests.jwt_support import JwtTestSigner

pytestmark = pytest.mark.security
ISSUER = "https://Identity.example.test/Tenant%2Fteam"
AUDIENCE = "urn:portfolio:read-model"
RESOURCE = "https://portfolio.example/mcp"


@pytest.mark.parametrize("algorithm", ("RS256", "ES256", "EdDSA"))
@pytest.mark.parametrize(
    ("token_audience", "status"),
    ((AUDIENCE, 200), (RESOURCE, 401), ("urn:portfolio:another-service", 401)),
    ids=("configured-opaque-audience", "resource-url-is-not-audience", "wrong-audience"),
)
def test_signed_mcp_transport_keeps_exact_configured_audience_without_sdk_warning(
    algorithm: str,
    token_audience: str,
    status: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    signer = JwtTestSigner.generate(algorithm)
    now = datetime.now(UTC).replace(microsecond=0)
    with warnings.catch_warnings():
        warnings.simplefilter("error", MCPDeprecationWarning)
        runtime = create_runtime(
            security_settings=SecuritySettings(
                environment=RuntimeEnvironment.TEST,
                issuer=ISSUER,
                local_synthetic_auth_enabled=False,
                allowed_hosts=("localhost",),
            ),
            mcp_settings=McpSettings.model_validate(
                {"public_base_url": "https://portfolio.example"}
            ),
            bearer_authenticator=JwtAuthenticator(
                issuer=ISSUER,
                audience=AUDIENCE,
                public_key=signer.public_key,
                clock=lambda: now,
            ),
        )
    token = signer.sign(
        {
            "iss": ISSUER,
            "sub": "provider|synthetic-subject",
            "aud": token_audience,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
            "principal_id": "synthetic-principal",
            "owner_id": SyntheticPortfolioService.OWNER_ID,
            "scope": "portfolio:read",
        }
    )
    caplog.set_level(logging.INFO)
    with TestClient(runtime.asgi_app(), base_url="http://localhost") as client:
        response = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "get_account_summary",
                    "arguments": {"account_id": SyntheticPortfolioService.ACCOUNT_ID},
                },
            },
        )
    assert response.status_code == status
    if status == 200:
        assert response.json()["result"]["isError"] is False
    else:
        assert response.json()["error"] == "invalid_token"
    if token in response.text or token in caplog.text:
        pytest.fail("MCP transport exposed a bearer credential", pytrace=False)
