"""Production JWT validation and explicitly local synthetic authentication."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

import jwt

from .identity import is_string_or_uri
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
        if not is_string_or_uri(issuer) or not is_string_or_uri(audience) or not public_key:
            raise ValueError("valid JWT issuer, audience, and public key are required")
        if type(clock_skew_seconds) is not int or not 0 <= clock_skew_seconds <= 300:
            raise ValueError("JWT clock skew must be between zero and 300 seconds")
        self._issuer = issuer
        self._audience = audience
        self._public_key = public_key
        self._clock = clock or (lambda: datetime.now(UTC))
        self._clock_skew = clock_skew_seconds

    async def authenticate(self, token: str) -> Principal:
        if not isinstance(token, str) or not token or len(token) > 16_384:
            raise AuthenticationError("invalid bearer credential")
        try:
            claims = jwt.decode(
                token,
                self._public_key,
                algorithms=["RS256", "ES256", "EdDSA"],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._clock_skew,
                options={
                    "require": ["exp", "iat", "iss", "aud", "sub"],
                    # PyJWT coerces NumericDate to int. Validate all times below
                    # against one clock, preserving fractions and rejecting bad types.
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
            return self._principal(claims)
        except (jwt.PyJWTError, AuthenticationError, TypeError, ValueError, OverflowError, OSError):
            # Decoder/conversion exceptions can contain claim values. Discard the context.
            pass
        raise AuthenticationError("invalid bearer credential")

    def _principal(self, claims: dict[str, object]) -> Principal:
        owner_id = claims.get("owner_id")
        # Only an absent claim selects the legacy internal-subject fallback.
        principal_id = claims.get("principal_id", claims.get("sub"))
        scope_claim = claims.get("scope", "")
        if not isinstance(owner_id, str) or not isinstance(principal_id, str):
            raise AuthenticationError("invalid ownership claims")
        if not isinstance(scope_claim, str):
            raise AuthenticationError("invalid scopes")
        scopes = frozenset(Scope(value) for value in scope_claim.split())
        issued_at = _numeric_date(claims["iat"])
        expires_at = _numeric_date(claims["exp"])
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise AuthenticationError("invalid authentication clock")
        now = now.astimezone(UTC)
        skew = timedelta(seconds=self._clock_skew)
        if issued_at > now + skew or expires_at <= now - skew:
            raise AuthenticationError("invalid credential time")
        if "nbf" in claims and _numeric_date(claims["nbf"]) > now + skew:
            raise AuthenticationError("invalid credential time")
        session_id = claims.get("sid")
        return Principal(
            principal_id=principal_id,
            owner_id=owner_id,
            issuer=cast(str, claims["iss"]),
            subject=cast(str, claims["sub"]),
            scopes=scopes,
            authenticated_at=issued_at,
            expires_at=expires_at,
            session_id=session_id if isinstance(session_id, str) else None,
        )


def _numeric_date(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise AuthenticationError("invalid credential time")
    return datetime.fromtimestamp(value, tz=UTC)


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
                    Scope.TARGETS_READ,
                    Scope.TARGETS_WRITE,
                    Scope.ANALYTICS_READ,
                    Scope.PLANS_WRITE,
                    Scope.REPORTS_READ,
                    Scope.REPORTS_WRITE,
                    Scope.ALERTS_READ,
                    Scope.ALERTS_WRITE,
                    Scope.RISK_WRITE,
                    Scope.SCENARIOS_WRITE,
                    Scope.PROJECTIONS_WRITE,
                    Scope.GOALS_WRITE,
                    Scope.RESEARCH_READ,
                    Scope.RESEARCH_WRITE,
                }
            ),
            authenticated_at=now,
            expires_at=now + timedelta(hours=1),
        )
