from __future__ import annotations

import secrets
import traceback
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from trading212_mcp.auth import SharedTokenVerifier, _principal_from_access_token
from trading212_security.identity import is_string_or_uri
from trading212_security.principals import AuthenticationError
from trading212_security.sessions import InMemorySessionStore, SessionManager
from trading212_security.tokens import JwtAuthenticator

from tests.jwt_support import JwtTestSigner

ISSUER = "https://Identity.example.test/Tenant%2Fteam"
AUDIENCE = "portfolio-api"


@pytest.fixture(scope="module", params=["RS256", "ES256", "EdDSA"])
def signer(request: pytest.FixtureRequest) -> JwtTestSigner:
    return JwtTestSigner.generate(str(request.param))


def _claims() -> dict[str, Any]:
    now = datetime.now(UTC).timestamp()
    return {
        "iss": ISSUER,
        "sub": "provider|synthetic-subject",
        "aud": AUDIENCE,
        "iat": now - 60,
        "exp": now + 3600,
        "nbf": now - 60,
        "principal_id": "principal-1",
        "owner_id": "owner-1",
        "scope": "portfolio:read",
        "private_canary": "synthetic-private-claim-canary",
    }


def _auth(signer: JwtTestSigner, **kwargs: Any) -> JwtAuthenticator:
    return JwtAuthenticator(
        issuer=ISSUER, audience=AUDIENCE, public_key=signer.public_key, **kwargs
    )


def _safe_failure(error: AuthenticationError, credential: str) -> None:
    rendered = "".join(traceback.format_exception(error))
    if any(
        value in rendered
        for value in (
            credential,
            "synthetic-private-claim-canary",
            "provider|synthetic-subject",
            "BEGIN PRIVATE KEY",
        )
    ):
        pytest.fail("authentication failure exposed sensitive material", pytrace=False)
    assert str(error) == "invalid bearer credential"
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.mark.parametrize("claim", ["exp", "iat", "nbf"])
@pytest.mark.parametrize(
    "bad",
    [
        None,
        True,
        "synthetic-private-claim-canary",
        "17",
        [],
        {},
        10**100,
        float("inf"),
        float("nan"),
    ],
    ids=["null", "bool", "text", "numeric-string", "list", "object", "overflow", "infinity", "nan"],
)
async def test_malformed_numeric_dates_are_safe_authentication_errors(
    signer: JwtTestSigner, claim: str, bad: Any
) -> None:
    claims = _claims()
    claims[claim] = bad
    token = signer.sign_raw_claims(claims)
    with pytest.raises(AuthenticationError) as caught:
        await _auth(signer).authenticate(token)
    _safe_failure(caught.value, token)


@pytest.mark.parametrize("claim", ["iss", "aud", "sub", "exp", "iat", "owner_id", "scope"])
async def test_required_claims_fail_closed(signer: JwtTestSigner, claim: str) -> None:
    claims = _claims()
    del claims[claim]
    with pytest.raises(AuthenticationError, match=r"^invalid bearer credential$"):
        await _auth(signer).authenticate(signer.sign_raw_claims(claims))


@pytest.mark.parametrize(
    "fault",
    [
        "issuer-slash",
        "issuer-case",
        "issuer-escape",
        "audience",
        "expired",
        "future-issued",
        "future-not-before",
        "empty-scopes",
        "unknown-scope",
        "scope-object",
        "null-principal",
        "empty-principal",
        "uri-principal",
        "external-owner",
        "external-fallback",
        "nonstring-subject",
        "oversize-subject",
        "control-subject",
        "invalid-uri-subject",
        "nonstring-issuer",
    ],
)
async def test_invalid_identity_mapping_and_claims_fail_closed(
    signer: JwtTestSigner, fault: str
) -> None:
    claims = _claims()
    changes: dict[str, tuple[str, Any]] = {
        "issuer-slash": ("iss", ISSUER + "/"),
        "issuer-case": ("iss", ISSUER.lower()),
        "issuer-escape": ("iss", ISSUER.replace("%2F", "%2f")),
        "audience": ("aud", "different-api"),
        "expired": ("exp", datetime.now(UTC).timestamp() - 120),
        "future-issued": ("iat", datetime.now(UTC).timestamp() + 3600),
        "future-not-before": ("nbf", datetime.now(UTC).timestamp() + 3600),
        "empty-scopes": ("scope", ""),
        "unknown-scope": ("scope", "broker:write"),
        "scope-object": ("scope", {}),
        "null-principal": ("principal_id", None),
        "empty-principal": ("principal_id", ""),
        "uri-principal": ("principal_id", "https://identity.example/principal"),
        "external-owner": ("owner_id", "provider|owner"),
        "nonstring-subject": ("sub", []),
        "oversize-subject": ("sub", "x" * 256),
        "control-subject": ("sub", "subject\n"),
        "invalid-uri-subject": ("sub", "provider:subject|invalid"),
        "nonstring-issuer": ("iss", {}),
    }
    if fault == "external-fallback":
        del claims["principal_id"]
    else:
        field, value = changes[fault]
        claims[field] = value
    token = signer.sign_raw_claims(claims)
    with pytest.raises(AuthenticationError) as caught:
        await _auth(signer).authenticate(token)
    _safe_failure(caught.value, token)


@pytest.mark.parametrize("fault", ["signature", "wrong-key", "none", "hs256"])
async def test_signature_and_algorithm_allowlist(signer: JwtTestSigner, fault: str) -> None:
    claims = _claims()
    if fault == "wrong-key":
        token = JwtTestSigner.generate(signer.algorithm).sign(claims)
    elif fault == "none":
        token = jwt.encode(claims, key="", algorithm="none")
    elif fault == "hs256":
        token = jwt.encode(claims, secrets.token_bytes(32), algorithm="HS256")
    else:
        head, payload, signature = signer.sign(claims).split(".")
        altered = ("A" if signature[0] != "A" else "B") + signature[1:]
        token = ".".join((head, payload, altered))
    with pytest.raises(AuthenticationError) as caught:
        await _auth(signer).authenticate(token)
    _safe_failure(caught.value, token)


async def test_explicit_and_legacy_mapping_roundtrip_session_and_mcp(signer: JwtTestSigner) -> None:
    claims = _claims()
    token = signer.sign(claims)
    principal = await _auth(signer).authenticate(token)
    session = SessionManager(
        store=InMemorySessionStore(),
        signing_key=secrets.token_bytes(32),
        clock=lambda: datetime.now(UTC),
    )
    grant = await session.create(principal)
    restored = await session.authenticate(grant.cookie_value)
    access = await SharedTokenVerifier(
        _auth(signer), resource="https://portfolio.example/mcp"
    ).verify_token(token)
    assert access is not None
    resolved = _principal_from_access_token(access)
    if restored != principal or resolved != principal or access.token == token:
        pytest.fail("validated identity was not preserved through session and MCP", pytrace=False)
    await session.revoke(grant.cookie_value)
    with pytest.raises(AuthenticationError, match=r"^invalid session$"):
        await session.authenticate(grant.cookie_value)
    del claims["principal_id"]
    claims["sub"] = "legacy-principal"
    legacy = await _auth(signer).authenticate(signer.sign(claims))
    assert legacy.principal_id == "legacy-principal"
    for field in ("owner_id", "principal_id"):
        with pytest.raises(AuthenticationError):
            if field == "owner_id":
                replace(principal, owner_id="provider|invalid-internal-id")
            else:
                replace(principal, principal_id="provider|invalid-internal-id")


@pytest.mark.parametrize(
    "value",
    [
        "x" * 255,
        "provider|subject",
        "\u00e9",
        "e\u0301",
        "https://Identity.example/Tenant%2fX",
        "urn:example:subject",
        "mailto:a@example.test",
        "https://[2001:db8::1]/subject",
        "scheme://[v1.a:b]/path",
        "scheme:",
        "scheme:/",
        "scheme:opaque/path?query#fragment",
    ],
    ids=[
        "max-bound",
        "provider",
        "unicode-composed",
        "unicode-decomposed",
        "exact-url",
        "urn",
        "mailto",
        "ipv6",
        "ipvfuture",
        "empty-path",
        "absolute-path",
        "rootless-path",
    ],
)
async def test_external_identity_grammar_preserves_values(
    signer: JwtTestSigner, value: str
) -> None:
    principal = await _auth(signer).authenticate(signer.sign({**_claims(), "sub": value}))
    if principal.subject != value:
        pytest.fail("subject identity was transformed", pytrace=False)


@pytest.mark.parametrize(
    "value",
    [
        None,
        1,
        "",
        "x" * 256,
        "a\x00b",
        "a\x7fb",
        "a\u0085b",
        "a\u200bb",
        "a\u2028b",
        "a\ud800b",
        ":bad",
        "1:bad",
        "a:b|c",
        "https://a/%xx",
        "https://[bad]/",
        "https://[fe80::1%eth0]/",
        "https://a:bad/",
        "https://a/a b",
    ],
    ids=[
        "null",
        "number",
        "empty",
        "too-long",
        "nul",
        "del",
        "c1",
        "format",
        "line",
        "surrogate",
        "no-scheme",
        "bad-scheme",
        "pipe-uri",
        "bad-escape",
        "bad-ip",
        "zone-id",
        "bad-port",
        "space-uri",
    ],
)
def test_malformed_external_identity_profile(value: Any) -> None:
    assert not is_string_or_uri(value)


@pytest.mark.parametrize("value", [-1, 301, True, 1.5])
def test_clock_skew_configuration_is_bounded(value: Any, signer: JwtTestSigner) -> None:
    with pytest.raises(ValueError, match="JWT clock skew"):
        _auth(signer, clock_skew_seconds=value)


@pytest.mark.parametrize(
    "value", [None, b"bytes", "", "x" * 16385], ids=["null", "bytes", "empty", "oversized"]
)
async def test_bearer_input_is_bounded(value: Any, signer: JwtTestSigner) -> None:
    with pytest.raises(AuthenticationError, match=r"^invalid bearer credential$"):
        await _auth(signer).authenticate(value)


async def test_audience_list_and_explicit_clock_skew(signer: JwtTestSigner) -> None:
    claims = _claims()
    now = datetime.now(UTC)
    claims.update(
        aud=[AUDIENCE, "secondary-api"], iat=now.timestamp() + 60, nbf=now.timestamp() + 60
    )
    principal = await _auth(signer, clock=lambda: now, clock_skew_seconds=120).authenticate(
        signer.sign(claims)
    )
    assert principal.authenticated_at > now
    with pytest.raises(AuthenticationError, match=r"^invalid bearer credential$"):
        await _auth(signer, clock=lambda: now, clock_skew_seconds=0).authenticate(
            signer.sign(claims)
        )
    with pytest.raises(AuthenticationError, match=r"^invalid bearer credential$"):
        await _auth(
            signer, clock=lambda: now + timedelta(hours=2), clock_skew_seconds=120
        ).authenticate(signer.sign(claims))


@pytest.mark.parametrize("field", ["owner_id", "principal_id", "scope", "aud"])
@pytest.mark.parametrize("value", [False, None, {}, []], ids=["bool", "null", "object", "array"])
async def test_malformed_mapped_claim_types_are_rejected(
    signer: JwtTestSigner, field: str, value: Any
) -> None:
    token = signer.sign_raw_claims({**_claims(), field: value})
    with pytest.raises(AuthenticationError) as caught:
        await _auth(signer).authenticate(token)
    _safe_failure(caught.value, token)


async def test_fractional_expiry_uses_exact_verified_numeric_date(
    signer: JwtTestSigner, monkeypatch: pytest.MonkeyPatch
) -> None:
    at = datetime(2026, 9, 14, 4, 0, 0, 200000, tzinfo=UTC)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> FixedDatetime:
            return cls.fromtimestamp(at.timestamp(), tz=tz or UTC)

    monkeypatch.setattr(jwt.api_jwt, "datetime", FixedDatetime)
    claims = _claims()
    claims.update(iat=at.timestamp() - 1, nbf=at.timestamp() - 1, exp=at.timestamp() + 0.6)
    authenticator = _auth(signer, clock=lambda: at, clock_skew_seconds=0)
    token = signer.sign(claims)
    principal = await authenticator.authenticate(token)
    assert principal.expires_at == at + timedelta(microseconds=600000)
    at += timedelta(microseconds=600000)
    with pytest.raises(AuthenticationError, match=r"^invalid bearer credential$"):
        await authenticator.authenticate(token)
