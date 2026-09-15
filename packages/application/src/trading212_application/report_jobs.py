"""Fixed-purpose report/export outboxes and monotonically fenced worker ports."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Protocol, Self
from uuid import UUID

from trading212_domain.errors import fail_validation
from trading212_domain.report_v3 import ReportManifestContract
from trading212_domain.reports import ReportFailureCode, ReportManifest, ReportRecord

from .reports import RenderedArtifact, ReportDocumentReader

REPORT_TASK_NAME = "reports.generate.v1"
EXPORT_TASK_NAME = "exports.generate.v1"
REPORT_PUBLICATION_ATTEMPTS = 8
REPORT_CONSUMER_ATTEMPTS = 4
REPORT_WORKER_LEASE_SECONDS = 60
REPORT_HEARTBEAT_SECONDS = 15
REPORT_DISPATCH_CLAIM_SECONDS = 30
REPORT_DISPATCH_BATCH_SIZE = 20
REPORT_DISPATCH_MAX_BATCH_SIZE = 100
REPORT_RETRY_DELAYS = (1, 2, 4)
_MESSAGE_KEYS = frozenset({"job_id", "owner_id", "account_id", "capture_id", "input_digest"})


@dataclass(slots=True)
class ReportJobInputError(Exception):
    code: ReportFailureCode
    retryable: bool = False

    def __str__(self) -> str:
        return "The pinned private report input is unavailable."


@dataclass(frozen=True, slots=True, kw_only=True)
class _ReportMessage(ReportRecord):
    job_id: UUID
    owner_id: UUID
    account_id: UUID
    capture_id: UUID
    input_digest: str

    def to_wire(self) -> dict[str, str]:
        return {item.name: str(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_wire(cls, value: Mapping[str, object]) -> Self:
        if set(value) != _MESSAGE_KEYS or any(type(item) is not str for item in value.values()):
            fail_validation("Fixed report message fields are required.", field="message")
        identifiers: dict[str, UUID] = {}
        for key in _MESSAGE_KEYS - {"input_digest"}:
            raw = value[key]
            assert isinstance(raw, str)
            try:
                identifier = UUID(raw)
            except ValueError:
                fail_validation("Message identity must be a UUID.", field="message")
            if str(identifier) != raw:
                fail_validation("Message identity must be canonical.", field="message")
            identifiers[key] = identifier
        digest = value["input_digest"]
        assert isinstance(digest, str)
        return cls(
            job_id=identifiers["job_id"],
            owner_id=identifiers["owner_id"],
            account_id=identifiers["account_id"],
            capture_id=identifiers["capture_id"],
            input_digest=digest,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportTaskMessage(_ReportMessage):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportTaskMessage(_ReportMessage):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportJobClaim(ReportRecord):
    message: ReportTaskMessage
    lease_id: UUID
    fence: int
    lease_expires_at: datetime
    consumer_attempt: int

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        if self.fence < 1 or not 1 <= self.consumer_attempt <= REPORT_CONSUMER_ATTEMPTS:
            fail_validation("Report job claim is outside its bound.", field="claim")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportJobClaim(ReportRecord):
    message: ExportTaskMessage
    lease_id: UUID
    fence: int
    lease_expires_at: datetime
    consumer_attempt: int

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        if self.fence < 1 or not 1 <= self.consumer_attempt <= REPORT_CONSUMER_ATTEMPTS:
            fail_validation("Export job claim is outside its bound.", field="claim")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportDispatchClaim(ReportRecord):
    message: ReportTaskMessage
    claim_token: UUID
    claim_expires_at: datetime
    publication_attempt: int

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        if not 1 <= self.publication_attempt <= REPORT_PUBLICATION_ATTEMPTS:
            fail_validation("Report dispatch exceeds its attempt bound.", field="claim")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportDispatchClaim(ReportRecord):
    message: ExportTaskMessage
    claim_token: UUID
    claim_expires_at: datetime
    publication_attempt: int

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        if not 1 <= self.publication_attempt <= REPORT_PUBLICATION_ATTEMPTS:
            fail_validation("Export dispatch exceeds its attempt bound.", field="claim")


class ReportJobStore(Protocol):
    async def claim_report_dispatches(
        self, *, dispatcher_id: str, limit: int = REPORT_DISPATCH_BATCH_SIZE
    ) -> tuple[ReportDispatchClaim, ...]: ...
    async def acknowledge_report_dispatch(self, claim: ReportDispatchClaim) -> bool: ...
    async def defer_report_dispatch(
        self, claim: ReportDispatchClaim, *, failure: ReportFailureCode
    ) -> bool: ...
    async def claim_report_job(
        self, message: ReportTaskMessage, *, consumer_id: str
    ) -> ReportJobClaim | None: ...
    async def heartbeat_report_job(self, claim: ReportJobClaim) -> bool: ...
    def open_report_document(
        self, claim: ReportJobClaim
    ) -> AbstractContextManager[ReportDocumentReader]: ...
    async def complete_report_job(
        self,
        claim: ReportJobClaim,
        *,
        manifest: ReportManifestContract,
        artifacts: tuple[RenderedArtifact, ...],
    ) -> bool: ...
    async def fail_report_job(
        self, claim: ReportJobClaim, *, failure: ReportFailureCode, retryable: bool
    ) -> bool: ...


class ExportJobStore(Protocol):
    async def claim_export_dispatches(
        self, *, dispatcher_id: str, limit: int = REPORT_DISPATCH_BATCH_SIZE
    ) -> tuple[ExportDispatchClaim, ...]: ...
    async def acknowledge_export_dispatch(self, claim: ExportDispatchClaim) -> bool: ...
    async def defer_export_dispatch(
        self, claim: ExportDispatchClaim, *, failure: ReportFailureCode
    ) -> bool: ...
    async def claim_export_job(
        self, message: ExportTaskMessage, *, consumer_id: str
    ) -> ExportJobClaim | None: ...
    async def heartbeat_export_job(self, claim: ExportJobClaim) -> bool: ...
    def open_export_document(
        self, claim: ExportJobClaim
    ) -> AbstractContextManager[ReportDocumentReader]: ...
    async def complete_export_job(
        self,
        claim: ExportJobClaim,
        *,
        manifest: ReportManifest,
        artifacts: tuple[RenderedArtifact, ...],
    ) -> bool: ...
    async def fail_export_job(
        self, claim: ExportJobClaim, *, failure: ReportFailureCode, retryable: bool
    ) -> bool: ...


class ReportTaskPublisher(Protocol):
    async def publish_report(self, message: ReportTaskMessage) -> None: ...


class ExportTaskPublisher(Protocol):
    async def publish_export(self, message: ExportTaskMessage) -> None: ...
