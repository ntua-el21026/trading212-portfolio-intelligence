"""Stable, non-sensitive domain error contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, NoReturn


class ErrorCode(StrEnum):
    """Machine-stable errors shared by application interfaces."""

    VALIDATION_FAILED = "validation_failed"
    CURRENCY_MISMATCH = "currency_mismatch"
    FX_RATE_REQUIRED = "fx_rate_required"
    MISSING_INPUT = "missing_input"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    UNAUTHENTICATED = "unauthenticated"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN_CAPABILITY = "forbidden_capability"
    INPUT_BOUND_EXCEEDED = "input_bound_exceeded"
    PROVIDER_AUTHENTICATION_FAILED = "provider_authentication_failed"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_SCHEMA_INCOMPATIBLE = "provider_schema_incompatible"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    DATA_UNAVAILABLE = "data_unavailable"
    INTERNAL_ERROR = "internal_error"


@dataclass(slots=True)
class DomainError(Exception):
    """An interface-safe error without credentials or private payload data."""

    code: ErrorCode
    message: str
    field: str | None = None

    def __str__(self) -> str:
        return self.message


def fail_validation(message: str, *, field: str | None = None) -> NoReturn:
    raise DomainError(ErrorCode.VALIDATION_FAILED, message, field)


def reject_float(value: Any, *, field: str) -> None:
    """Reject binary floats before they can contaminate an exact value."""

    if isinstance(value, float):
        fail_validation(f"{field} must not be constructed from a binary float", field=field)
