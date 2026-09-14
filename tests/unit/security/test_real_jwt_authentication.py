from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from trading212_security.tokens import JwtAuthenticator

from tests.jwt_support import JwtTestSigner


@pytest.mark.parametrize("algorithm", ["RS256", "ES256", "EdDSA"])
@pytest.mark.parametrize(
    ("issuer", "subject"),
    [
        ("https://identity.example.test/tenant", "synthetic-subject"),
        ("identity.example.test", "synthetic-subject"),
        ("identity.example.test", "provider|synthetic-subject"),
    ],
    ids=["https-tenant", "opaque-diagnostic-control", "provider-subject"],
)
async def test_real_signed_jwt_preserves_external_identity(
    algorithm: str, issuer: str, subject: str
) -> None:
    signer = JwtTestSigner.generate(algorithm)
    now = datetime.now(UTC).replace(microsecond=0)
    token = signer.sign(
        {
            "iss": issuer,
            "sub": subject,
            "aud": "portfolio-api",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
            "principal_id": "principal-1",
            "owner_id": "owner-1",
            "scope": "portfolio:read",
        }
    )
    # Independent signature/claim validation distinguishes the application defect.
    verified = jwt.decode(
        token, signer.public_key, algorithms=[algorithm], issuer=issuer, audience="portfolio-api"
    )
    if verified["iss"] != issuer or verified["sub"] != subject:
        pytest.fail("cryptographic identity verification did not preserve identity", pytrace=False)
    principal = await JwtAuthenticator(
        issuer=issuer, audience="portfolio-api", public_key=signer.public_key, clock=lambda: now
    ).authenticate(token)
    if (principal.issuer, principal.subject, principal.principal_id, principal.owner_id) != (
        issuer,
        subject,
        "principal-1",
        "owner-1",
    ):
        pytest.fail("verified application identity was not preserved", pytrace=False)
