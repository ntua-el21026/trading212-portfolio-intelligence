"""Privacy-preserving, append-oriented security audit event boundary."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from .logging import logger

_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
_OPERATION = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
_OPAQUE_REFERENCE = re.compile(r"^sha256:[0-9a-f]{32}$")


class SecurityAuditAction(StrEnum):
    """Closed Phase 1 authentication and authorization audit vocabulary."""

    LOCAL_SESSION_CREATED = "authentication.local_session.created"
    SESSION_REVOKED = "authentication.session.revoked"
    AUTHENTICATION_DENIED = "authentication.denied"
    AUTHORIZATION_DENIED = "authorization.denied"


class SecurityAuditOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    DENIED = "denied"


class AuthenticationMethod(StrEnum):
    """Authentication mechanisms safe to expose as bounded audit metadata."""

    BEARER = "bearer"
    LOCAL_SYNTHETIC = "local_synthetic"
    SESSION = "session"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class SecurityAuditEvent:
    """A deliberately small event that cannot carry request or credential payloads."""

    event_id: str
    action: SecurityAuditAction
    outcome: SecurityAuditOutcome
    occurred_at: datetime
    correlation_id: str
    operation: str
    authentication_method: AuthenticationMethod
    actor_ref: str | None = None
    owner_ref: str | None = None
    application_version: str = "0.2.0"

    def __post_init__(self) -> None:
        try:
            UUID(self.event_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("audit event ID must be a UUID") from exc
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("audit timestamp must be timezone-aware")
        object.__setattr__(self, "occurred_at", self.occurred_at.astimezone(UTC))
        if not _CORRELATION_ID.fullmatch(self.correlation_id):
            raise ValueError("audit correlation ID must be bounded and opaque")
        if not _OPERATION.fullmatch(self.operation):
            raise ValueError("audit operation must be bounded and allowlisted")
        for reference in (self.actor_ref, self.owner_ref):
            if reference is not None and not _OPAQUE_REFERENCE.fullmatch(reference):
                raise ValueError("audit actor references must be one-way opaque references")
        if not self.application_version or len(self.application_version) > 32:
            raise ValueError("audit application version must be non-empty and bounded")


class SecurityAuditSink(Protocol):
    """Adapter point for structured logs now and durable audit storage later."""

    async def record(self, event: SecurityAuditEvent) -> None: ...


class StructuredLogSecurityAuditSink:
    """Default sink emitting only the closed, privacy-preserving event schema."""

    def __init__(self) -> None:
        self._logger = logger("trading212_api.security_audit")

    async def record(self, event: SecurityAuditEvent) -> None:
        self._logger.info(
            "security_audit_event",
            audit_event_id=event.event_id,
            audit_action=event.action.value,
            audit_outcome=event.outcome.value,
            occurred_at=event.occurred_at.isoformat(),
            correlation_id=event.correlation_id,
            operation=event.operation,
            authentication_method=event.authentication_method.value,
            actor_ref=event.actor_ref,
            owner_ref=event.owner_ref,
            application_version=event.application_version,
        )


def opaque_audit_reference(value: str) -> str:
    """Return a bounded stable reference without retaining the underlying identifier."""

    if not value or len(value) > 255:
        raise ValueError("audit source identifier must be non-empty and bounded")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
    return f"sha256:{digest}"
