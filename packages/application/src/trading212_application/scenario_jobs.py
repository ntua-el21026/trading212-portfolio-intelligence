"""Fixed-purpose scenario delivery and fenced worker contracts.

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

from trading212_domain.scenario_execution import ScenarioExecutionInput as ScenarioExecutionInput
from trading212_domain.scenario_serialization import (
    ScenarioExecutionParts,
    encode_scenario_execution,
)
from trading212_domain.values import require_utc

if TYPE_CHECKING:
    from trading212_domain.scenario_result import ScenarioCalculation

SCENARIO_TASK_NAME = "scenarios.calculate.v1"
SCENARIO_PUBLICATION_ATTEMPTS = 8
SCENARIO_CONSUMER_ATTEMPTS = 4
SCENARIO_WORKER_LEASE_SECONDS = 60
SCENARIO_HEARTBEAT_SECONDS = 15
SCENARIO_DISPATCH_CLAIM_SECONDS = 30
SCENARIO_DISPATCH_BATCH_SIZE = 1
SCENARIO_DISPATCH_MAX_BATCH_SIZE = 20
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MESSAGE_KEYS = frozenset({"job_id", "run_id", "owner_id", "account_id", "input_digest"})


class ScenarioJobFailureCode(StrEnum):
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
class ScenarioJobInputError(Exception):
    code: ScenarioJobFailureCode
    retryable: bool = False

    def __str__(self) -> str:
        return "The pinned scenario input is unavailable."


def _uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("scenario identity must be a canonical UUID")
    try:
        canonical = str(UUID(value))
    except (ValueError, AttributeError):
        canonical = ""
    if canonical != value:
        raise ValueError("scenario identity must be a canonical UUID")
    return value


@dataclass(frozen=True, slots=True)
class ScenarioTaskMessage:
    job_id: str
    run_id: str
    owner_id: str
    account_id: str
    input_digest: str

    def __post_init__(self) -> None:
        for value in (self.job_id, self.run_id, self.owner_id, self.account_id):
            _uuid(value)
        if not isinstance(self.input_digest, str) or _DIGEST.fullmatch(self.input_digest) is None:
            raise ValueError("scenario input digest is invalid")

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
            raise ValueError("scenario message fields are invalid")
        return cls(
            job_id=_uuid(value["job_id"]),
            run_id=_uuid(value["run_id"]),
            owner_id=_uuid(value["owner_id"]),
            account_id=_uuid(value["account_id"]),
            input_digest=str(value["input_digest"]),
        )


@dataclass(frozen=True, slots=True)
class ScenarioDispatchClaim:
    message: ScenarioTaskMessage
    claim_token: str
    expires_at: datetime
    publication_attempt: int

    def __post_init__(self) -> None:
        if not isinstance(self.message, ScenarioTaskMessage):
            raise ValueError("scenario claim message is invalid")
        _uuid(self.claim_token)
        require_utc(self.expires_at)
        if type(self.publication_attempt) is not int or not 1 <= self.publication_attempt <= 8:
            raise ValueError("scenario publication attempt is invalid")


@dataclass(frozen=True, slots=True)
class ScenarioJobClaim:
    message: ScenarioTaskMessage
    claim_token: str
    expires_at: datetime
    consumer_attempt: int
    deadline_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.message, ScenarioTaskMessage):
            raise ValueError("scenario claim message is invalid")
        _uuid(self.claim_token)
        require_utc(self.expires_at)
        if type(self.consumer_attempt) is not int or not 1 <= self.consumer_attempt <= 4:
            raise ValueError("scenario consumer attempt is invalid")
        require_utc(self.deadline_at)
        if self.expires_at > self.deadline_at:
            raise ValueError("scenario lease exceeds absolute execution deadline")


class ScenarioJobStore(Protocol):
    async def claim_scenario_dispatches(
        self, *, dispatcher_id: str, limit: int = SCENARIO_DISPATCH_BATCH_SIZE
    ) -> tuple[ScenarioDispatchClaim, ...]: ...

    async def acknowledge_scenario_dispatch(self, claim: ScenarioDispatchClaim) -> bool: ...

    async def defer_scenario_dispatch(
        self, claim: ScenarioDispatchClaim, *, failure_code: ScenarioJobFailureCode
    ) -> bool: ...

    async def claim_scenario_job(
        self, message: ScenarioTaskMessage, *, consumer_id: str
    ) -> ScenarioJobClaim | None: ...

    async def heartbeat_scenario_job(self, claim: ScenarioJobClaim) -> bool: ...

    async def load_scenario_job_input(self, claim: ScenarioJobClaim) -> ScenarioExecutionInput: ...

    async def complete_scenario_job(
        self, claim: ScenarioJobClaim, result: ScenarioCalculation
    ) -> bool: ...

    async def fail_scenario_job(
        self,
        claim: ScenarioJobClaim,
        *,
        failure_code: ScenarioJobFailureCode,
        retryable: bool,
    ) -> bool: ...


def scenario_execution_bytes(value: ScenarioExecutionInput) -> ScenarioExecutionParts:
    """Keep each original parent on its frozen codec without an untyped wrapper."""
    return encode_scenario_execution(value)
