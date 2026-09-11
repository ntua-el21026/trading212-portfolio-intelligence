"""Trusted internal revision attestations; never inferred from arrival order."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from trading212_domain.alerts import AlertRecord, alert_require
from trading212_security.principals import Principal


class ActivityRevisionAuthority(StrEnum):
    OWNER_ATTESTATION = "owner_attestation"
    PROVIDER_EVIDENCE = "provider_evidence"


@dataclass(frozen=True, slots=True, kw_only=True)
class ActivityRevisionRegistration(AlertRecord):
    id: UUID
    new_source_record_id: UUID
    superseded_source_record_id: UUID
    authority: ActivityRevisionAuthority
    evidence_key: str

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(
            self.new_source_record_id != self.superseded_source_record_id, "revision.identity"
        )
        alert_require(
            1 <= len(self.evidence_key) <= 120 and bool(self.evidence_key.strip()), "evidence_key"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ActivityRevisionEvidence(AlertRecord):
    registration: ActivityRevisionRegistration
    owner_id: UUID
    account_id: UUID
    principal_id: UUID
    economic_key: str
    first_observed_at: datetime
    content_digest: str


class ActivityRevisionErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    SOURCE_REVISION_CONFLICT = "SOURCE_REVISION_CONFLICT"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    INPUT_BOUND_EXCEEDED = "INPUT_BOUND_EXCEEDED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    REVISION_UNAVAILABLE = "REVISION_UNAVAILABLE"


@dataclass(slots=True)
class ActivityRevisionError(Exception):
    code: ActivityRevisionErrorCode

    def __str__(self) -> str:
        return "The trusted activity revision operation is unavailable."


class ActivityRevisionStore(Protocol):
    async def register_activity_revision(
        self,
        principal: Principal,
        account_id: UUID,
        registration: ActivityRevisionRegistration,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> ActivityRevisionEvidence: ...
