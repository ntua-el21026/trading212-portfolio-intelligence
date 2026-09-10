from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from trading212_security.principals import (
    AuthorizationError,
    Authorizer,
    Principal,
    Scope,
)
from trading212_security.settings import CredentialBackend, RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID, LocalSyntheticAuthenticator

NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _principal(*, owner_id: str = "owner-1", scopes: frozenset[Scope] | None = None) -> Principal:
    return Principal(
        principal_id="principal-1",
        owner_id=owner_id,
        issuer="test.issuer",
        subject="subject-1",
        scopes=scopes or frozenset({Scope.PORTFOLIO_READ}),
        authenticated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )


def test_deployed_configuration_fails_closed() -> None:
    with pytest.raises(ValidationError, match="incomplete"):
        SecuritySettings(environment=RuntimeEnvironment.PRODUCTION)
    with pytest.raises(ValidationError, match="forbidden"):
        SecuritySettings(
            environment=RuntimeEnvironment.STAGING,
            local_synthetic_auth_enabled=True,
        )


def test_valid_production_configuration_requires_external_secret_provider() -> None:
    settings = SecuritySettings(
        environment=RuntimeEnvironment.PRODUCTION,
        issuer="https://identity.example",
        audience="portfolio-api",
        jwt_public_key_reference="vault://auth/jwt-public-key",
        session_signing_key_reference="vault://auth/session-signing-key",
        cursor_signing_key_reference="vault://auth/cursor-signing-key",
        credential_backend=CredentialBackend.EXTERNAL,
        outbox_dispatcher_configured=True,
        allowed_origins=("https://portfolio.example",),
        allowed_hosts=("portfolio.example",),
    )
    assert settings.environment is RuntimeEnvironment.PRODUCTION
    assert settings.cookie_secure is True


def test_deployed_configuration_requires_refresh_dispatcher() -> None:
    with pytest.raises(ValidationError, match="dispatcher"):
        SecuritySettings(
            environment=RuntimeEnvironment.STAGING,
            issuer="https://identity.example",
            audience="portfolio-api",
            jwt_public_key_reference="vault://auth/jwt-public-key",
            session_signing_key_reference="vault://auth/session-signing-key",
            cursor_signing_key_reference="vault://auth/cursor-signing-key",
            allowed_origins=("https://portfolio.example",),
            allowed_hosts=("portfolio.example",),
        )


def test_scope_registry_contains_no_execution_capability() -> None:
    assert {scope.value for scope in Scope} == {
        "portfolio:read",
        "activity:read",
        "portfolio:refresh",
        "configuration:read",
        "targets:read",
        "targets:write",
        "analytics:read",
        "plans:write",
        "reports:read",
        "reports:write",
    }
    assert all("trade" not in scope.value for scope in Scope)


def test_scope_expiry_and_owner_checks_are_server_side() -> None:
    authorizer = Authorizer()
    principal = _principal()
    authorizer.require_scope(principal, Scope.PORTFOLIO_READ, now=NOW)
    authorizer.require_owner(principal, "owner-1")
    with pytest.raises(AuthorizationError, match="access denied"):
        authorizer.require_scope(principal, Scope.PORTFOLIO_REFRESH, now=NOW)
    with pytest.raises(AuthorizationError, match="access denied"):
        authorizer.require_owner(principal, "owner-2")
    with pytest.raises(AuthorizationError, match="access denied"):
        authorizer.require_scope(
            principal,
            Scope.PORTFOLIO_READ,
            now=NOW + timedelta(hours=2),
        )


@pytest.mark.asyncio
async def test_cross_owner_account_is_denied_without_revealing_existence() -> None:
    class Ownership:
        async def owner_for_account(self, account_id: str) -> str | None:
            return {"account-1": "owner-1", "account-2": "owner-2"}.get(account_id)

    authorizer = Authorizer()
    await authorizer.require_account(_principal(), "account-1", Ownership())
    for account_id in ("account-2", "missing"):
        with pytest.raises(AuthorizationError, match=r"^access denied$"):
            await authorizer.require_account(_principal(), account_id, Ownership())


@pytest.mark.asyncio
async def test_synthetic_auth_is_local_only_and_explicit() -> None:
    settings = SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=True,
    )
    principal = await LocalSyntheticAuthenticator(settings, clock=lambda: NOW).authenticate("")
    assert principal.owner_id == LOCAL_SYNTHETIC_OWNER_ID
    assert Scope.PORTFOLIO_REFRESH in principal.scopes
    assert {
        Scope.TARGETS_READ,
        Scope.TARGETS_WRITE,
        Scope.ANALYTICS_READ,
        Scope.PLANS_WRITE,
        Scope.REPORTS_READ,
        Scope.REPORTS_WRITE,
    } <= principal.scopes


@pytest.mark.parametrize(
    "granted,denied",
    [(Scope.TARGETS_WRITE, Scope.TARGETS_READ), (Scope.TARGETS_READ, Scope.TARGETS_WRITE)],
)
def test_target_read_and_write_scopes_are_independent(granted: Scope, denied: Scope) -> None:
    principal = _principal(scopes=frozenset({granted}))
    authorizer = Authorizer()
    authorizer.require_scope(principal, granted, now=NOW)
    with pytest.raises(AuthorizationError, match="access denied"):
        authorizer.require_scope(principal, denied, now=NOW)
    with pytest.raises(AuthorizationError, match="access denied"):
        authorizer.require_scope(principal, Scope.PORTFOLIO_READ, now=NOW)


@pytest.mark.parametrize(
    "granted,denied",
    [
        (Scope.PLANS_WRITE, Scope.ANALYTICS_READ),
        (Scope.ANALYTICS_READ, Scope.PLANS_WRITE),
        (Scope.TARGETS_WRITE, Scope.PLANS_WRITE),
    ],
)
def test_planning_scopes_never_imply_other_capabilities(granted: Scope, denied: Scope) -> None:
    principal = _principal(scopes=frozenset({granted}))
    Authorizer().require_scope(principal, granted, now=NOW)
    with pytest.raises(AuthorizationError):
        Authorizer().require_scope(principal, denied, now=NOW)


@pytest.mark.parametrize(
    ("granted", "denied"),
    [
        (Scope.REPORTS_WRITE, Scope.REPORTS_READ),
        (Scope.REPORTS_READ, Scope.REPORTS_WRITE),
        (Scope.REPORTS_WRITE, Scope.ANALYTICS_READ),
        (Scope.REPORTS_WRITE, Scope.ACTIVITY_READ),
        (Scope.REPORTS_WRITE, Scope.TARGETS_READ),
        (Scope.REPORTS_WRITE, Scope.PORTFOLIO_READ),
        (Scope.PLANS_WRITE, Scope.REPORTS_WRITE),
    ],
)
def test_report_scopes_never_imply_other_capabilities(granted: Scope, denied: Scope) -> None:
    authorizer = Authorizer()
    principal = _principal(scopes=frozenset({granted}))
    authorizer.require_scope(principal, granted, now=NOW)
    with pytest.raises(AuthorizationError):
        authorizer.require_scope(principal, denied, now=NOW)
