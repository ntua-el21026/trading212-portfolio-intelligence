from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from trading212_api.main import create_app
from trading212_application.services import SyntheticPortfolioService
from trading212_application.views import AccountSummaryView
from trading212_security.principals import Principal
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID, JwtAuthenticator

from tests.jwt_support import JwtTestSigner


class ObservedPortfolioService(SyntheticPortfolioService):
    summary_calls = 0

    async def get_summary(self, principal: Principal, account_id: str) -> AccountSummaryView:
        self.summary_calls += 1
        return await super().get_summary(principal, account_id)


@pytest.mark.parametrize("algorithm", ["RS256", "ES256", "EdDSA"])
async def test_real_signed_api_bearer_uses_authentication_dependency(
    algorithm: str, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    signer = JwtTestSigner.generate(algorithm)
    issuer = "https://identity.example.test/Tenant"
    claims: dict[str, Any] = {
        "iss": issuer,
        "sub": "provider|synthetic-api-subject",
        "aud": "portfolio-api",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "principal_id": "synthetic-api-principal",
        "owner_id": LOCAL_SYNTHETIC_OWNER_ID,
        "scope": "portfolio:read",
    }
    service = ObservedPortfolioService(clock=lambda: now)
    app = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=False,
            issuer=issuer,
            allowed_hosts=("localhost",),
        ),
        service=service,
        bearer_authenticator=JwtAuthenticator(
            issuer=issuer,
            audience="portfolio-api",
            public_key=signer.public_key,
            clock=lambda: now,
        ),
        clock=lambda: now,
    )
    path = f"/api/v1/accounts/{service.ACCOUNT_ID}/summary"
    responses: list[httpx.Response] = []
    credentials: list[str] = []

    def bearer(token: str) -> dict[str, str]:
        credentials.extend((token, token.split(".")[1]))
        return {"Authorization": "Bearer " + token}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://localhost"
    ) as client:
        response = await client.get(path, headers=bearer(signer.sign(claims)))
        responses.append(response)
        for fault in ("anonymous", "malformed-time", "expired", "wrong-key", "wrong-issuer"):
            altered = dict(claims)
            signing = signer
            if fault == "malformed-time":
                altered["exp"] = {"value": "private-claim-canary"}
            elif fault == "expired":
                altered["exp"] = int(now.timestamp()) - 120
            elif fault == "wrong-issuer":
                altered["iss"] = issuer + "/"
            elif fault == "wrong-key":
                signing = JwtTestSigner.generate(algorithm)
            headers = {} if fault == "anonymous" else bearer(signing.sign_raw_claims(altered))
            denied = await client.get(path, headers=headers)
            responses.append(denied)
            assert service.summary_calls == 1
            assert denied.status_code == 401
            assert denied.headers["www-authenticate"] == "Bearer"
            assert denied.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
            assert denied.json()["error"]["message"] == "Authentication is required."
        for field, value in (("scope", "activity:read"), ("owner_id", "other-owner")):
            denied = await client.get(path, headers=bearer(signer.sign({**claims, field: value})))
            responses.append(denied)
            assert denied.status_code == 403
            assert denied.json()["error"]["code"] == "ACCESS_DENIED"
        unknown_account = await client.get(
            "/api/v1/accounts/unknown-account/summary",
            headers=bearer(signer.sign(claims)),
        )
        responses.append(unknown_account)
        assert unknown_account.status_code == 403
    captured = capsys.readouterr()
    rendered = captured.out + captured.err + caplog.text + "".join(item.text for item in responses)
    if any(
        marker in rendered
        for marker in (
            *credentials,
            "private-claim-canary",
            "provider|synthetic-api-subject",
            "BEGIN PRIVATE KEY",
        )
    ):
        caplog.clear()
        pytest.fail("authentication material leaked in API output", pytrace=False)
    if response.status_code != 200:
        pytest.fail(
            "real signed API authentication did not admit a valid mapped identity", pytrace=False
        )
    assert response.json()["total_value"]["value"] == "248431.27"
    assert response.json()["total_value"]["reporting_currency"] == "EUR"
