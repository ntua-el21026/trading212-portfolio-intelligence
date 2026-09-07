"""Fixed-purpose planning delivery and fenced worker contracts.

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

from trading212_domain.values import require_utc

if TYPE_CHECKING:
    from trading212_domain.planning import ContributionPlanResult, PlanningInput

PLAN_TASK_NAME = "plans.calculate.v1"
PLAN_PUBLICATION_ATTEMPTS = 8
PLAN_CONSUMER_ATTEMPTS = 4
PLAN_WORKER_LEASE_SECONDS = 60
PLAN_HEARTBEAT_SECONDS = 15
PLAN_DISPATCH_CLAIM_SECONDS = 30
PLAN_DISPATCH_BATCH_SIZE = 20
PLAN_DISPATCH_MAX_BATCH_SIZE = 100
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MESSAGE_KEYS = frozenset({"job_id", "request_id", "owner_id", "account_id", "input_digest"})


class PlanJobFailureCode(StrEnum):
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


@dataclass(slots=True)
class PlanJobInputError(Exception):
    code: PlanJobFailureCode
    retryable: bool = False

    def __str__(self) -> str:
        return "The pinned planning input is unavailable."


def _uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("planning identity must be a canonical UUID")
    try:
        canonical = str(UUID(value))
    except (ValueError, AttributeError):
        canonical = ""
    if canonical != value:
        raise ValueError("planning identity must be a canonical UUID")
    return value


@dataclass(frozen=True, slots=True)
class PlanTaskMessage:
    job_id: str
    request_id: str
    owner_id: str
    account_id: str
    input_digest: str

    def __post_init__(self) -> None:
        for value in (self.job_id, self.request_id, self.owner_id, self.account_id):
            _uuid(value)
        if not isinstance(self.input_digest, str) or _DIGEST.fullmatch(self.input_digest) is None:
            raise ValueError("planning input digest is invalid")

    def to_wire(self) -> dict[str, str]:
        return {
            "job_id": self.job_id,
            "request_id": self.request_id,
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
            raise ValueError("planning message fields are invalid")
        return cls(
            job_id=_uuid(value["job_id"]),
            request_id=_uuid(value["request_id"]),
            owner_id=_uuid(value["owner_id"]),
            account_id=_uuid(value["account_id"]),
            input_digest=str(value["input_digest"]),
        )


@dataclass(frozen=True, slots=True)
class PlanDispatchClaim:
    message: PlanTaskMessage
    claim_token: str
    expires_at: datetime
    publication_attempt: int

    def __post_init__(self) -> None:
        if not isinstance(self.message, PlanTaskMessage):
            raise ValueError("planning claim message is invalid")
        _uuid(self.claim_token)
        require_utc(self.expires_at)
        if type(self.publication_attempt) is not int or not 1 <= self.publication_attempt <= 8:
            raise ValueError("planning publication attempt is invalid")


@dataclass(frozen=True, slots=True)
class PlanJobClaim:
    message: PlanTaskMessage
    claim_token: str
    expires_at: datetime
    consumer_attempt: int

    def __post_init__(self) -> None:
        if not isinstance(self.message, PlanTaskMessage):
            raise ValueError("planning claim message is invalid")
        _uuid(self.claim_token)
        require_utc(self.expires_at)
        if type(self.consumer_attempt) is not int or not 1 <= self.consumer_attempt <= 4:
            raise ValueError("planning consumer attempt is invalid")


class PlanJobStore(Protocol):
    async def claim_plan_dispatches(
        self, *, dispatcher_id: str, limit: int = PLAN_DISPATCH_BATCH_SIZE
    ) -> tuple[PlanDispatchClaim, ...]: ...

    async def acknowledge_plan_dispatch(self, claim: PlanDispatchClaim) -> bool: ...

    async def defer_plan_dispatch(
        self, claim: PlanDispatchClaim, *, failure_code: PlanJobFailureCode
    ) -> bool: ...

    async def claim_plan_job(
        self, message: PlanTaskMessage, *, consumer_id: str
    ) -> PlanJobClaim | None: ...

    async def heartbeat_plan_job(self, claim: PlanJobClaim) -> bool: ...

    async def load_plan_job_input(self, claim: PlanJobClaim) -> PlanningInput: ...

    async def complete_plan_job(
        self, claim: PlanJobClaim, result: ContributionPlanResult
    ) -> bool: ...

    async def fail_plan_job(
        self,
        claim: PlanJobClaim,
        *,
        failure_code: PlanJobFailureCode,
        retryable: bool,
    ) -> bool: ...
