"""Fixed-purpose projection delivery and fenced worker contracts.

Messages contain authorized opaque identities only. Financial inputs and results
remain in canonical application storage; no broker request can be dispatched.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, Self
from uuid import UUID

from trading212_domain.projection import ProjectionVariant
from trading212_domain.values import require_utc

from .projection_capture import ProjectionCapturePlan

if TYPE_CHECKING:
    from trading212_domain.projection_result import ProjectionCalculation, ProjectionChunk

PROJECTION_TASK_NAME = "projections.calculate.v1"
PROJECTION_PUBLICATION_ATTEMPTS = 8
PROJECTION_CONSUMER_ATTEMPTS = 4
PROJECTION_WORKER_LEASE_SECONDS = 60
PROJECTION_HEARTBEAT_SECONDS = 15
PROJECTION_DISPATCH_CLAIM_SECONDS = 30
PROJECTION_DISPATCH_BATCH_SIZE = 1
PROJECTION_DISPATCH_MAX_BATCH_SIZE = 20
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MESSAGE_KEYS = frozenset({"job_id", "run_id", "owner_id", "account_id", "input_digest"})


class ProjectionJobFailureCode(StrEnum):
    PUBLICATION_UNAVAILABLE = "publication_unavailable"
    CONSUMER_UNAVAILABLE = "consumer_unavailable"
    LEASE_EXPIRED = "lease_expired"
    INVALID_MESSAGE = "invalid_message"
    INPUT_UNAVAILABLE = "input_unavailable"
    INPUT_CHANGED = "input_changed"
    ACCESS_DENIED = "access_denied"
    CALCULATION_FAILED = "calculation_failed"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    LIMIT_EXCEEDED = "limit_exceeded"
    SOURCE_RESTRICTED = "source_restricted"


@dataclass(slots=True)
class ProjectionJobInputError(Exception):
    code: ProjectionJobFailureCode
    retryable: bool = False

    def __str__(self) -> str:
        return "The pinned projection input is unavailable."


def _uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("projection identity must be a canonical UUID")
    try:
        canonical = str(UUID(value))
    except (ValueError, AttributeError):
        canonical = ""
    if canonical != value:
        raise ValueError("projection identity must be a canonical UUID")
    return value


@dataclass(frozen=True, slots=True)
class ProjectionTaskMessage:
    job_id: str
    run_id: str
    owner_id: str
    account_id: str
    input_digest: str

    def __post_init__(self) -> None:
        for value in (self.job_id, self.run_id, self.owner_id, self.account_id):
            _uuid(value)
        if not isinstance(self.input_digest, str) or _DIGEST.fullmatch(self.input_digest) is None:
            raise ValueError("projection input digest is invalid")

    def to_wire(self) -> dict[str, str]:
        return {
            "job_id": self.job_id,
            "run_id": self.run_id,
            "owner_id": self.owner_id,
            "account_id": self.account_id,
            "input_digest": self.input_digest,
        }

    @classmethod
    def from_wire(cls, value: Mapping[str, object]) -> Self:
        if (
            not isinstance(value, Mapping)
            or set(value) != _MESSAGE_KEYS
            or any(not isinstance(v, str) for v in value.values())
        ):
            raise ValueError("projection message fields are invalid")
        return cls(
            job_id=_uuid(value["job_id"]),
            run_id=_uuid(value["run_id"]),
            owner_id=_uuid(value["owner_id"]),
            account_id=_uuid(value["account_id"]),
            input_digest=str(value["input_digest"]),
        )


@dataclass(frozen=True, slots=True)
class ProjectionDispatchClaim:
    message: ProjectionTaskMessage
    claim_token: str
    expires_at: datetime
    publication_attempt: int

    def __post_init__(self) -> None:
        if not isinstance(self.message, ProjectionTaskMessage):
            raise ValueError("projection claim message is invalid")
        _uuid(self.claim_token)
        require_utc(self.expires_at)
        if type(self.publication_attempt) is not int or not 1 <= self.publication_attempt <= 8:
            raise ValueError("projection publication attempt is invalid")


@dataclass(frozen=True, slots=True)
class ProjectionJobClaim:
    message: ProjectionTaskMessage
    claim_token: str
    expires_at: datetime
    consumer_attempt: int
    deadline_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.message, ProjectionTaskMessage):
            raise ValueError("projection claim message is invalid")
        _uuid(self.claim_token)
        require_utc(self.expires_at)
        if type(self.consumer_attempt) is not int or not 1 <= self.consumer_attempt <= 4:
            raise ValueError("projection consumer attempt is invalid")
        require_utc(self.deadline_at)
        if self.expires_at > self.deadline_at:
            raise ValueError("projection lease exceeds absolute execution deadline")


class ProjectionJobStore(Protocol):
    async def claim_projection_dispatches(
        self, *, dispatcher_id: str, limit: int = PROJECTION_DISPATCH_BATCH_SIZE
    ) -> tuple[ProjectionDispatchClaim, ...]: ...

    async def acknowledge_projection_dispatch(self, claim: ProjectionDispatchClaim) -> bool: ...

    async def defer_projection_dispatch(
        self, claim: ProjectionDispatchClaim, *, failure_code: ProjectionJobFailureCode
    ) -> bool: ...

    async def claim_projection_job(
        self, message: ProjectionTaskMessage, *, consumer_id: str
    ) -> ProjectionJobClaim | None: ...

    async def heartbeat_projection_job(self, claim: ProjectionJobClaim) -> bool: ...

    async def load_projection_job_input(
        self, claim: ProjectionJobClaim
    ) -> ProjectionCapturePlan: ...

    async def load_projection_job_chunks(
        self,
        claim: ProjectionJobClaim,
        *,
        after: tuple[ProjectionVariant, int] | None = None,
        limit: int = 32,
    ) -> tuple[ProjectionChunk, ...]: ...

    async def save_projection_job_chunk(
        self, claim: ProjectionJobClaim, chunk: ProjectionChunk
    ) -> bool: ...

    async def complete_projection_job(
        self, claim: ProjectionJobClaim, result: ProjectionCalculation
    ) -> bool: ...

    async def fail_projection_job(
        self,
        claim: ProjectionJobClaim,
        *,
        failure_code: ProjectionJobFailureCode,
        retryable: bool,
    ) -> bool: ...
