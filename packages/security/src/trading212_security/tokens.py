"""Production JWT validation and explicitly local synthetic authentication."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

import jwt

from .principals import AuthenticationError, Principal, Scope
from .settings import RuntimeEnvironment, SecuritySettings

LOCAL_SYNTHETIC_OWNER_ID = "f9da1e93-85d5-5c1b-8221-ff997ffb035e"
LOCAL_SYNTHETIC_PRINCIPAL_ID = "86c2ebdb-8e90-5279-b0e8-5f747a091c31"


class BearerAuthenticator(Protocol):
    async def authenticate(self, token: str) -> Principal: ...


class JwtAuthenticator:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        public_key: str | bytes,
        clock: Callable[[], datetime] | None = None,
        clock_skew_seconds: int = 30,
    ) -> None:
        if not issuer or not audience or not public_key:
            raise ValueError("JWT issuer, audience, and public key are required")
        self._issuer = issuer
        self._audience = audience
        self._public_key = public_key
        self._clock = clock or (lambda: datetime.now(UTC))
        self._clock_skew = clock_skew_seconds

    async def authenticate(self, token: str) -> Principal:
        if not token or len(token) > 16_384:
            raise AuthenticationError("invalid bearer credential")
        try:
            claims = jwt.decode(
                token,
                self._public_key,
                algorithms=["RS256", "ES256", "EdDSA"],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._clock_skew,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("invalid bearer credential") from exc
        owner_id = claims.get("owner_id")
        principal_id = claims.get("principal_id") or claims.get("sub")
        scope_claim = claims.get("scope", "")
        if not isinstance(owner_id, str) or not isinstance(principal_id, str):
            raise AuthenticationError("bearer credential lacks ownership claims")
        if not isinstance(scope_claim, str):
            raise AuthenticationError("bearer credential has invalid scopes")
        try:
            scopes = frozenset(Scope(value) for value in scope_claim.split() if value)
        except ValueError as exc:
            raise AuthenticationError("bearer credential has an unknown scope") from exc
        issued_at = datetime.fromtimestamp(cast(int, claims["iat"]), tz=UTC)
        expires_at = datetime.fromtimestamp(cast(int, claims["exp"]), tz=UTC)
        now = self._clock().astimezone(UTC)
        if issued_at > now + timedelta(seconds=self._clock_skew):
            raise AuthenticationError("invalid bearer credential")
        return Principal(
            principal_id=principal_id,
            owner_id=owner_id,
            issuer=self._issuer,
            subject=cast(str, claims["sub"]),
            scopes=scopes,
            authenticated_at=issued_at,
            expires_at=expires_at,
            session_id=claims.get("sid") if isinstance(claims.get("sid"), str) else None,
        )


class LocalSyntheticAuthenticator:
    """No-token local mode; construction itself enforces the deployment boundary."""

    def __init__(self, settings: SecuritySettings, *, clock: Callable[[], datetime]) -> None:
        if not settings.local_synthetic_auth_enabled:
            raise AuthenticationError("local synthetic authentication is disabled")
        if settings.environment not in {RuntimeEnvironment.LOCAL, RuntimeEnvironment.TEST}:
            raise AuthenticationError("local synthetic authentication is forbidden")
        self._clock = clock

    async def authenticate(self, token: str) -> Principal:
        if token:
            raise AuthenticationError("local synthetic mode does not accept bearer credentials")
        now = self._clock().astimezone(UTC)
        return Principal(
            principal_id=LOCAL_SYNTHETIC_PRINCIPAL_ID,
            owner_id=LOCAL_SYNTHETIC_OWNER_ID,
            issuer="local.synthetic",
            subject="synthetic-owner",
            scopes=frozenset(
                {
                    Scope.PORTFOLIO_READ,
                    Scope.ACTIVITY_READ,
                    Scope.PORTFOLIO_REFRESH,
                    Scope.CONFIGURATION_READ,
                }
            ),
            authenticated_at=now,
            expires_at=now + timedelta(hours=1),
        )
