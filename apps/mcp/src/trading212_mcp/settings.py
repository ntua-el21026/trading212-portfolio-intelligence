"""Bounded MCP transport configuration kept separate from portfolio settings."""

from __future__ import annotations

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class McpSettings(BaseSettings):
    """Runtime-only MCP settings; authentication material is never stored here."""

    model_config = SettingsConfigDict(
        env_prefix="T212PI_MCP_",
        extra="forbid",
        frozen=True,
    )

    host: str = "127.0.0.1"
    port: int = Field(default=8001, ge=1, le=65_535)
    public_base_url: AnyHttpUrl | None = None
    widget_domain: AnyHttpUrl | None = None
    allow_non_loopback_local_synthetic_bind: bool = False
    max_request_body_bytes: int = Field(default=1_048_576, ge=16_384, le=4_194_304)

    @model_validator(mode="after")
    def require_https_public_origins(self) -> McpSettings:
        """Keep OAuth resource metadata and hosted widgets off plaintext origins."""
        for name in ("public_base_url", "widget_domain"):
            value = getattr(self, name)
            if value is not None and value.scheme != "https":
                raise ValueError(f"{name} must use HTTPS")
        return self

    @property
    def resource_server_url(self) -> str | None:
        """Return the canonical public MCP resource URL when configured."""
        if self.public_base_url is None:
            return None
        return f"{str(self.public_base_url).rstrip('/')}/mcp"
