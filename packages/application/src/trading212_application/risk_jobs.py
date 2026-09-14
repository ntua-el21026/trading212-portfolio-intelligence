"""Fixed-purpose risk delivery and fenced worker contracts.

Messages contain authorized opaque identities only. Financial inputs and results
remain in canonical application storage; no broker request can be dispatched.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, Self
from uuid import UUID

from trading212_domain.historical_serialization import historical_canonical_bytes
from trading212_domain.risk_execution import RiskExecutionInput as RiskExecutionInput
from trading212_domain.values import require_utc
from trading212_domain.xray_codec import encode_xray_result

if TYPE_CHECKING:
    from trading212_domain.risk_result import RiskCalculation

RISK_TASK_NAME = "risk.calculate.v1"
RISK_PUBLICATION_ATTEMPTS = 8
RISK_CONSUMER_ATTEMPTS = 4
RISK_WORKER_LEASE_SECONDS = 60
RISK_HEARTBEAT_SECONDS = 15
RISK_DISPATCH_CLAIM_SECONDS = 30
RISK_DISPATCH_BATCH_SIZE = 1
RISK_DISPATCH_MAX_BATCH_SIZE = 20
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MESSAGE_KEYS = frozenset({"job_id", "run_id", "owner_id", "account_id", "input_digest"})


class RiskJobFailureCode(StrEnum):
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
class RiskJobInputError(Exception):
    code: RiskJobFailureCode
    retryable: bool = False

    def __str__(self) -> str:
        return "The pinned risk input is unavailable."


def _uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("risk identity must be a canonical UUID")
    try:
        canonical = str(UUID(value))
    except (ValueError, AttributeError):
        canonical = ""
    if canonical != value:
        raise ValueError("risk identity must be a canonical UUID")
    return value


@dataclass(frozen=True, slots=True)
class RiskTaskMessage:
    job_id: str
    run_id: str
    owner_id: str
    account_id: str
    input_digest: str

    def __post_init__(self) -> None:
        for value in (self.job_id, self.run_id, self.owner_id, self.account_id):
            _uuid(value)
        if not isinstance(self.input_digest, str) or _DIGEST.fullmatch(self.input_digest) is None:
            raise ValueError("risk input digest is invalid")

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
            raise ValueError("risk message fields are invalid")
        return cls(
            job_id=_uuid(value["job_id"]),
            run_id=_uuid(value["run_id"]),
            owner_id=_uuid(value["owner_id"]),
            account_id=_uuid(value["account_id"]),
            input_digest=str(value["input_digest"]),
        )


@dataclass(frozen=True, slots=True)
class RiskDispatchClaim:
    message: RiskTaskMessage
    claim_token: str
    expires_at: datetime
    publication_attempt: int

    def __post_init__(self) -> None:
        if not isinstance(self.message, RiskTaskMessage):
            raise ValueError("risk claim message is invalid")
        _uuid(self.claim_token)
        require_utc(self.expires_at)
        if type(self.publication_attempt) is not int or not 1 <= self.publication_attempt <= 8:
            raise ValueError("risk publication attempt is invalid")


@dataclass(frozen=True, slots=True)
class RiskJobClaim:
    message: RiskTaskMessage
    claim_token: str
    expires_at: datetime
    consumer_attempt: int
    deadline_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.message, RiskTaskMessage):
            raise ValueError("risk claim message is invalid")
        _uuid(self.claim_token)
        require_utc(self.expires_at)
        if type(self.consumer_attempt) is not int or not 1 <= self.consumer_attempt <= 4:
            raise ValueError("risk consumer attempt is invalid")
        require_utc(self.deadline_at)
        if self.expires_at > self.deadline_at:
            raise ValueError("risk lease exceeds absolute execution deadline")


class RiskJobStore(Protocol):
    async def claim_risk_dispatches(
        self, *, dispatcher_id: str, limit: int = RISK_DISPATCH_BATCH_SIZE
    ) -> tuple[RiskDispatchClaim, ...]: ...

    async def acknowledge_risk_dispatch(self, claim: RiskDispatchClaim) -> bool: ...

    async def defer_risk_dispatch(
        self, claim: RiskDispatchClaim, *, failure_code: RiskJobFailureCode
    ) -> bool: ...

    async def claim_risk_job(
        self, message: RiskTaskMessage, *, consumer_id: str
    ) -> RiskJobClaim | None: ...

    async def heartbeat_risk_job(self, claim: RiskJobClaim) -> bool: ...

    async def load_risk_job_input(self, claim: RiskJobClaim) -> RiskExecutionInput: ...

    async def complete_risk_job(self, claim: RiskJobClaim, result: RiskCalculation) -> bool: ...

    async def fail_risk_job(
        self,
        claim: RiskJobClaim,
        *,
        failure_code: RiskJobFailureCode,
        retryable: bool,
    ) -> bool: ...


def risk_execution_bytes(value: RiskExecutionInput) -> tuple[bytes, bytes]:
    main = historical_canonical_bytes(replace(value, xray=None))
    xray = b"" if value.xray is None else encode_xray_result(value.xray)
    if len(main) + len(xray) > 33554432:
        raise RiskJobInputError(RiskJobFailureCode.LIMIT_EXCEEDED)
    return main, xray
