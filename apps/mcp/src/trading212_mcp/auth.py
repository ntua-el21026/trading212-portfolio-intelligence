"""MCP OAuth transport adapter over the shared authentication principal boundary."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from trading212_security.principals import AuthenticationError, Principal, Scope
from trading212_security.settings import SecuritySettings
from trading212_security.tokens import BearerAuthenticator, LocalSyntheticAuthenticator


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]


class SharedTokenVerifier:
    """Validate OAuth bearer tokens with the shared server-side authenticator."""

    def __init__(self, authenticator: BearerAuthenticator, *, resource: str) -> None:
        self._authenticator = authenticator
        self._resource = resource

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            principal = await self._authenticator.authenticate(token)
        except AuthenticationError:
            return None
        return AccessToken(
            # Never retain the bearer secret in MCP request context after validation.
            token=f"sha256:{_fingerprint(token)}",
            client_id=principal.principal_id,
            scopes=sorted(scope.value for scope in principal.scopes),
            expires_at=int(principal.expires_at.timestamp()),
            resource=self._resource,
            subject=principal.subject,
            claims={
                "principal_id": principal.principal_id,
                "owner_id": principal.owner_id,
                "issuer": principal.issuer,
                "subject": principal.subject,
                "authenticated_at": principal.authenticated_at.isoformat(),
                "expires_at": principal.expires_at.isoformat(),
                "session_id": principal.session_id,
            },
        )


@dataclass(frozen=True, slots=True)
class PrincipalResolver:
    """Resolve only server-validated identities; never trust tool inputs or headers."""

    local_authenticator: LocalSyntheticAuthenticator | None

    @classmethod
    def from_settings(
        cls,
        settings: SecuritySettings,
        *,
        clock: Any,
    ) -> PrincipalResolver:
        local = (
            LocalSyntheticAuthenticator(settings, clock=clock)
            if settings.local_synthetic_auth_enabled
            else None
        )
        return cls(local_authenticator=local)

    async def resolve(self) -> Principal:
        if self.local_authenticator is not None:
            return await self.local_authenticator.authenticate("")

        access_token = get_access_token()
        if access_token is None:
            raise AuthenticationError("authentication required")
        return _principal_from_access_token(access_token)


def _principal_from_access_token(access_token: AccessToken) -> Principal:
    claims = access_token.claims or {}
    try:
        authenticated_at = datetime.fromisoformat(_claim(claims, "authenticated_at"))
        expires_at = datetime.fromisoformat(_claim(claims, "expires_at"))
        scopes = frozenset(Scope(value) for value in access_token.scopes)
        session_id = claims.get("session_id")
        if session_id is not None and not isinstance(session_id, str):
            raise AuthenticationError("invalid authenticated principal")
        return Principal(
            principal_id=_claim(claims, "principal_id"),
            owner_id=_claim(claims, "owner_id"),
            issuer=_claim(claims, "issuer"),
            subject=_claim(claims, "subject"),
            scopes=scopes,
            authenticated_at=authenticated_at,
            expires_at=expires_at,
            session_id=session_id,
        )
    except (TypeError, ValueError) as exc:
        raise AuthenticationError("invalid authenticated principal") from exc


def _claim(claims: dict[str, Any], name: str) -> str:
    value = claims.get(name)
    if not isinstance(value, str):
        raise AuthenticationError("invalid authenticated principal")
    return value
