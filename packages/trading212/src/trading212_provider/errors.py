"""Sanitized, provider-independent error surface."""

from __future__ import annotations

from enum import StrEnum


class ProviderErrorKind(StrEnum):
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    RATE_LIMITED = "rate_limited"
    TRANSIENT = "transient"
    TIMEOUT = "timeout"
    CONTRACT = "contract"
    CONFIGURATION = "configuration"
    NOT_FOUND = "not_found"
    PERMANENT = "permanent"
    PAGINATION = "pagination"


class ProviderError(RuntimeError):
    """Never includes provider response bodies, credentials, or request URLs."""

    def __init__(
        self,
        kind: ProviderErrorKind,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.status_code = status_code


class MethodNotAllowedError(ProviderError):
    def __init__(self) -> None:
        super().__init__(
            ProviderErrorKind.CONFIGURATION,
            "provider transport permits allowlisted reads only",
        )


class CapabilityError(ProviderError):
    def __init__(self, message: str) -> None:
        super().__init__(ProviderErrorKind.CONFIGURATION, message)
