"""Opaque credential boundary and safe Basic authentication construction."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Protocol

from .configuration import BrokerEnvironment
from .errors import ProviderError, ProviderErrorKind


@dataclass(frozen=True, repr=False)
class Trading212Credentials:
    api_key: str
    api_secret: str
    environment: BrokerEnvironment

    def __post_init__(self) -> None:
        if not self.api_key or not self.api_secret:
            raise ProviderError(
                ProviderErrorKind.CONFIGURATION,
                "Trading 212 credential reference resolved to an incomplete value",
            )
        if "\n" in self.api_key or "\r" in self.api_key or ":" in self.api_key:
            raise ProviderError(ProviderErrorKind.CONFIGURATION, "invalid API key format")
        if "\n" in self.api_secret or "\r" in self.api_secret:
            raise ProviderError(ProviderErrorKind.CONFIGURATION, "invalid API secret format")

    def __repr__(self) -> str:
        return f"Trading212Credentials(environment={self.environment.value!r}, redacted=True)"

    def authorization_header(self) -> str:
        value = base64.b64encode(f"{self.api_key}:{self.api_secret}".encode()).decode("ascii")
        return f"Basic {value}"


class CredentialProvider(Protocol):
    async def resolve_trading212(
        self,
        *,
        credential_reference: str,
        environment: BrokerEnvironment,
    ) -> Trading212Credentials: ...


class StaticCredentialProvider:
    """Test-only provider; production composition must use an external secret store."""

    def __init__(self, credentials: Trading212Credentials) -> None:
        self._credentials = credentials

    async def resolve_trading212(
        self,
        *,
        credential_reference: str,
        environment: BrokerEnvironment,
    ) -> Trading212Credentials:
        del credential_reference
        if self._credentials.environment is not environment:
            raise ProviderError(
                ProviderErrorKind.AUTHENTICATION,
                "credential environment does not match the selected broker environment",
            )
        return self._credentials
