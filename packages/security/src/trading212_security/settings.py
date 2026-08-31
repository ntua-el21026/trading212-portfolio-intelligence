"""Fail-closed authentication, session, and secret configuration."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeEnvironment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class CredentialBackend(StrEnum):
    ENVIRONMENT = "environment"
    EXTERNAL = "external"


class SecuritySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="T212PI_",
        extra="forbid",
        frozen=True,
    )

    environment: RuntimeEnvironment = RuntimeEnvironment.LOCAL
    local_synthetic_auth_enabled: bool = False
    issuer: str | None = None
    audience: str | None = None
    jwt_public_key_reference: str | None = None
    session_signing_key_reference: str | None = None
    credential_backend: CredentialBackend = CredentialBackend.ENVIRONMENT
    cookie_secure: bool = True
    cookie_http_only: bool = True
    cookie_same_site: str = "strict"
    allowed_origins: tuple[str, ...] = ()
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1")
    session_ttl_seconds: int = Field(default=3_600, ge=300, le=86_400)
    access_token_clock_skew_seconds: int = Field(default=30, ge=0, le=300)

    @model_validator(mode="after")
    def validate_security_posture(self) -> SecuritySettings:
        deployed = self.environment in {
            RuntimeEnvironment.STAGING,
            RuntimeEnvironment.PRODUCTION,
        }
        if deployed and self.local_synthetic_auth_enabled:
            raise ValueError("local synthetic authentication is forbidden outside local/test")
        if deployed:
            required = {
                "issuer": self.issuer,
                "audience": self.audience,
                "jwt_public_key_reference": self.jwt_public_key_reference,
                "session_signing_key_reference": self.session_signing_key_reference,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(
                    f"deployed authentication configuration is incomplete: {missing!r}"
                )
            if not self.cookie_secure or not self.cookie_http_only:
                raise ValueError("deployed session cookies must be Secure and HttpOnly")
            if self.cookie_same_site not in {"strict", "lax"}:
                raise ValueError("deployed SameSite policy must be strict or lax")
            if not self.allowed_origins or not self.allowed_hosts:
                raise ValueError("deployed origin and host allowlists must be explicit")
            if any(origin == "*" for origin in self.allowed_origins):
                raise ValueError("wildcard origins are forbidden")
        if (
            self.credential_backend is CredentialBackend.ENVIRONMENT
            and self.environment is RuntimeEnvironment.PRODUCTION
        ):
            raise ValueError("production must use an external secret-provider adapter")
        return self
