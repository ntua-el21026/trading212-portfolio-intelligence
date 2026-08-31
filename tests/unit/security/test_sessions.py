from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from trading212_security.principals import AuthenticationError, Principal, Scope
from trading212_security.sessions import InMemorySessionStore, SessionManager

NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _principal() -> Principal:
    return Principal(
        principal_id="principal-1",
        owner_id="owner-1",
        issuer="test.issuer",
        subject="subject-1",
        scopes=frozenset({Scope.PORTFOLIO_READ}),
        authenticated_at=NOW,
        expires_at=NOW + timedelta(hours=2),
    )


@pytest.mark.asyncio
async def test_session_cookie_is_signed_csrf_protected_and_revocable() -> None:
    current = NOW
    manager = SessionManager(
        store=InMemorySessionStore(),
        signing_key=b"s" * 32,
        clock=lambda: current,
    )
    grant = await manager.create(_principal())
    assert "principal-1" not in grant.cookie_value
    assert "owner-1" not in grant.cookie_value
    assert "redacted" in repr(grant).casefold()
    assert (await manager.authenticate(grant.cookie_value)).owner_id == "owner-1"
    await manager.validate_csrf(grant.cookie_value, grant.csrf_token)

    with pytest.raises(AuthenticationError, match="CSRF"):
        await manager.validate_csrf(grant.cookie_value, "wrong")
    with pytest.raises(AuthenticationError, match="session"):
        await manager.authenticate(grant.cookie_value + "tampered")

    await manager.revoke(grant.cookie_value)
    with pytest.raises(AuthenticationError, match="session"):
        await manager.authenticate(grant.cookie_value)


@pytest.mark.asyncio
async def test_expired_session_fails_closed() -> None:
    current = NOW
    manager = SessionManager(
        store=InMemorySessionStore(),
        signing_key=b"k" * 32,
        clock=lambda: current,
        ttl=timedelta(minutes=5),
    )
    grant = await manager.create(_principal())
    current += timedelta(minutes=6)
    with pytest.raises(AuthenticationError, match="session"):
        await manager.authenticate(grant.cookie_value)
