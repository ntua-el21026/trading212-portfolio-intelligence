"""Fixed alert evaluation and notification outboxes with bounded fenced worker ports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, Self
from uuid import UUID

from trading212_domain.alert_serialization import decode_alert_record, encode_alert_record
from trading212_domain.alerts import (
    AlertEvaluationInput,
    AlertEvaluationResult,
    AlertExecutionIntent,
    AlertReason,
    AlertRecord,
    alert_require,
)

ALERT_EVALUATION_TASK_NAME = "alerts.evaluate.v1"
ALERT_NOTIFICATION_TASK_NAME = "notifications.deliver.v1"
ALERT_PUBLICATION_ATTEMPTS = 8
ALERT_CONSUMER_ATTEMPTS = 4
ALERT_WORKER_LEASE_SECONDS = 60
ALERT_HEARTBEAT_SECONDS = 15
ALERT_DISPATCH_CLAIM_SECONDS = 30
ALERT_DISPATCH_BATCH_SIZE = 20
ALERT_MAX_DUE_SLOTS = 100
ALERT_RETRY_DELAYS = (1, 2, 4)
ALERT_PERMANENT_FAILURES = frozenset(
    {
        AlertReason.COMPUTATION_FAILED,
        AlertReason.AMBIGUOUS_SOURCE,
        AlertReason.ACCESS_DENIED,
        AlertReason.SOURCE_RESTRICTED,
        AlertReason.INPUT_BOUND_EXCEEDED,
    }
)


class AlertJobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(slots=True)
class AlertJobInputError(Exception):
    code: AlertReason
    retryable: bool = False

    def __str__(self) -> str:
        return "The immutable alert input is unavailable."


@dataclass(frozen=True, slots=True, kw_only=True)
class _AlertMessage(AlertRecord):
    def to_wire(self) -> dict[str, object]:
        import json

        result: dict[str, object] = json.loads(encode_alert_record(self))
        return result

    @classmethod
    def from_wire(cls, value: Mapping[str, object]) -> Self:
        import json

        alert_require(all(type(key) is str for key in value), "message")
        payload = json.dumps(
            dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        return decode_alert_record(payload, cls)


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertEvaluationTaskMessage(_AlertMessage):
    job_id: UUID
    owner_id: UUID
    account_id: UUID
    rule_version_id: UUID
    capture_id: UUID
    input_digest: str
    scheduled_for: datetime
    execution_intent: AlertExecutionIntent = AlertExecutionIntent.LIVE


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertEvaluationJobClaim(AlertRecord):
    message: AlertEvaluationTaskMessage
    lease_id: UUID
    fence: int
    lease_expires_at: datetime
    consumer_attempt: int
    lifecycle_sequence: int

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(
            self.fence >= 1 and 1 <= self.consumer_attempt <= 4 and self.lifecycle_sequence >= 1,
            "claim",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertEvaluationDispatchClaim(AlertRecord):
    message: AlertEvaluationTaskMessage
    claim_token: UUID
    claim_expires_at: datetime
    publication_attempt: int

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(1 <= self.publication_attempt <= 8, "dispatch")


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertAdmissionSummary(AlertRecord):
    admitted: int
    deferred: bool
    observed_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertNotificationPayload(AlertRecord):
    delivery_id: UUID
    event_id: UUID
    rule_id: UUID
    rule_version_id: UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertNotificationTaskMessage(_AlertMessage):
    delivery_id: UUID
    owner_id: UUID
    account_id: UUID
    event_id: UUID
    destination_version_id: UUID
    payload_digest: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertNotificationJobClaim(AlertRecord):
    message: AlertNotificationTaskMessage
    lease_id: UUID
    fence: int
    lease_expires_at: datetime
    consumer_attempt: int

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(self.fence >= 1 and 1 <= self.consumer_attempt <= 4, "claim")


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertNotificationDispatchClaim(AlertRecord):
    message: AlertNotificationTaskMessage
    claim_token: UUID
    claim_expires_at: datetime
    publication_attempt: int

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(1 <= self.publication_attempt <= 8, "dispatch")


class AlertDeliveryOutcome(StrEnum):
    ACCEPTED = "accepted"
    UNAVAILABLE = "unavailable"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertDeliveryReceipt(AlertRecord):
    delivery_id: UUID
    outcome: AlertDeliveryOutcome
    observed_at: datetime
    reason: AlertReason | None = None


class AlertJobStore(Protocol):
    async def admit_due_evaluations(
        self, *, limit: int = ALERT_MAX_DUE_SLOTS
    ) -> AlertAdmissionSummary: ...
    async def claim_evaluation_dispatches(
        self, *, dispatcher_id: str, limit: int = ALERT_DISPATCH_BATCH_SIZE
    ) -> tuple[AlertEvaluationDispatchClaim, ...]: ...
    async def acknowledge_evaluation_dispatch(
        self, claim: AlertEvaluationDispatchClaim
    ) -> bool: ...
    async def defer_evaluation_dispatch(
        self, claim: AlertEvaluationDispatchClaim, *, failure: AlertReason
    ) -> bool: ...
    async def claim_evaluation_job(
        self, message: AlertEvaluationTaskMessage, *, consumer_id: str
    ) -> AlertEvaluationJobClaim | None: ...
    async def heartbeat_evaluation_job(self, claim: AlertEvaluationJobClaim) -> bool: ...
    async def load_evaluation_input(
        self, claim: AlertEvaluationJobClaim
    ) -> AlertEvaluationInput: ...
    async def complete_evaluation_job(
        self, claim: AlertEvaluationJobClaim, *, result: AlertEvaluationResult
    ) -> bool: ...
    async def fail_evaluation_job(
        self, claim: AlertEvaluationJobClaim, *, failure: AlertReason, retryable: bool
    ) -> bool: ...


class AlertNotificationStore(Protocol):
    async def claim_notification_dispatches(
        self, *, dispatcher_id: str, limit: int = ALERT_DISPATCH_BATCH_SIZE
    ) -> tuple[AlertNotificationDispatchClaim, ...]: ...
    async def acknowledge_notification_dispatch(
        self, claim: AlertNotificationDispatchClaim
    ) -> bool: ...
    async def defer_notification_dispatch(
        self, claim: AlertNotificationDispatchClaim, *, failure: AlertReason
    ) -> bool: ...
    async def claim_notification_job(
        self, message: AlertNotificationTaskMessage, *, consumer_id: str
    ) -> AlertNotificationJobClaim | None: ...
    async def heartbeat_notification_job(self, claim: AlertNotificationJobClaim) -> bool: ...
    async def load_notification_payload(
        self, claim: AlertNotificationJobClaim
    ) -> AlertNotificationPayload: ...
    async def complete_notification_job(
        self, claim: AlertNotificationJobClaim, *, receipt: AlertDeliveryReceipt
    ) -> bool: ...
    async def fail_notification_job(
        self, claim: AlertNotificationJobClaim, *, failure: AlertReason, retryable: bool
    ) -> bool: ...


class AlertTaskPublisher(Protocol):
    async def publish_evaluation(self, message: AlertEvaluationTaskMessage) -> None: ...
    async def publish_notification(self, message: AlertNotificationTaskMessage) -> None: ...


class AlertNotificationPort(Protocol):
    async def deliver(
        self, destination_version_id: UUID, payload: AlertNotificationPayload
    ) -> AlertDeliveryReceipt: ...
