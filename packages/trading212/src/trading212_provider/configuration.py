"""Fail-closed Trading 212 adapter configuration."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BrokerEnvironment(StrEnum):
    DEMO = "demo"
    LIVE = "live"


class Trading212Settings(BaseModel):
    """Runtime settings; arbitrary provider origins are deliberately impossible."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    environment: BrokerEnvironment = BrokerEnvironment.DEMO
    live_mode_explicitly_enabled: bool = False
    connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    read_timeout_seconds: float = Field(default=20.0, gt=0, le=60)
    max_attempts: int = Field(default=3, ge=1, le=5)
    max_backoff_seconds: float = Field(default=8.0, gt=0, le=30)
    max_response_bytes: int = Field(default=2_000_000, ge=1_024, le=10_000_000)
    max_pages: int = Field(default=500, ge=1, le=5_000)
    max_records: int = Field(default=50_000, ge=1, le=500_000)

    @model_validator(mode="after")
    def require_explicit_live_gate(self) -> Trading212Settings:
        if self.environment is BrokerEnvironment.LIVE and not self.live_mode_explicitly_enabled:
            raise ValueError("live Trading 212 mode requires an explicit read-only enablement gate")
        if self.environment is BrokerEnvironment.DEMO and self.live_mode_explicitly_enabled:
            raise ValueError("live enablement must be false in Demo mode")
        return self

    @property
    def base_url(self) -> str:
        if self.environment is BrokerEnvironment.DEMO:
            return "https://demo.trading212.com/api/v0"
        return "https://live.trading212.com/api/v0"
