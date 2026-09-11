"""Authorized fixed alert management, immutable history and bounded capture ports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from trading212_domain.alerts import (
    AlertCanonicalBinding,
    AlertEvaluationInput,
    AlertEvaluationOutcome,
    AlertEvaluationResult,
    AlertExecutionIntent,
    AlertFamily,
    AlertLifecycle,
    AlertNotificationState,
    AlertRecord,
    AlertResolutionReason,
    AlertRuleDefinition,
    AlertRuleVersion,
    AlertSeverity,
    AlertSourceReference,
    alert_require,
)
from trading212_domain.sources import SourceLicense
from trading212_security.principals import Principal, Scope


class AlertServiceErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INPUT_BOUND_EXCEEDED = "INPUT_BOUND_EXCEEDED"
    RESULT_TOO_LARGE = "RESULT_TOO_LARGE"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    IMMUTABLE_VERSION = "IMMUTABLE_VERSION"
    SOURCE_REVISION_CONFLICT = "SOURCE_REVISION_CONFLICT"
    CURSOR_INVALID = "CURSOR_INVALID"
    RATE_LIMITED = "RATE_LIMITED"
    ALERTS_UNAVAILABLE = "ALERTS_UNAVAILABLE"
    JOB_DISPATCH_UNAVAILABLE = "JOB_DISPATCH_UNAVAILABLE"


@dataclass(slots=True)
class AlertServiceError(Exception):
    code: AlertServiceErrorCode
    message: str = "The alert operation is unavailable."
    retryable: bool = False

    def __str__(self) -> str:
        return self.message


class AlertEventState(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class AlertStateFilter(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    ALL = "all"


class AlertSeverityFilter(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    ALL = "all"


class AlertReproducibility(StrEnum):
    RETAINED = "retained"
    EXPIRED = "expired"
    SOURCE_RESTRICTED = "source_restricted"


class NotificationChannel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    WEBHOOK = "webhook"


class NotificationDestinationState(StrEnum):
    CONFIGURED = "configured"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class AlertDeliveryState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateAlertRuleCommand(AlertRecord):
    account_id: UUID
    definition: AlertRuleDefinition


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertRuleVersionCommand(AlertRecord):
    definition: AlertRuleDefinition


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertPageQuery(AlertRecord):
    cursor: str | None = None
    limit: int = 25

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(
            1 <= self.limit <= 100 and (self.cursor is None or 1 <= len(self.cursor) <= 2048),
            "page",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertRuleListQuery(AlertPageQuery):
    account_id: UUID
    state: AlertLifecycle | None = None
    family: AlertFamily | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertRuleDetailQuery(AlertRecord):
    evaluation_cursor: str | None = None
    evaluation_limit: int = 25
    version_cursor: str | None = None
    version_limit: int = 25

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(
            1 <= self.evaluation_limit <= 100
            and (self.evaluation_cursor is None or 1 <= len(self.evaluation_cursor) <= 2048),
            "evaluation_page",
        )
        alert_require(
            1 <= self.version_limit <= 100
            and (self.version_cursor is None or 1 <= len(self.version_cursor) <= 2048),
            "version_page",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertEventListQuery(AlertPageQuery):
    account_id: UUID
    rule_id: UUID | None = None
    state: AlertStateFilter = AlertStateFilter.OPEN
    severity: AlertSeverityFilter = AlertSeverityFilter.ALL
    start_date: date | None = None
    end_date: date | None = None

    def __post_init__(self) -> None:
        AlertPageQuery.__post_init__(self)
        alert_require((self.start_date is None) == (self.end_date is None), "period")
        if self.start_date is not None and self.end_date is not None:
            alert_require(0 <= (self.end_date - self.start_date).days <= 3660, "period")


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertSummaryTopQuery(AlertRecord):
    state: AlertStateFilter = AlertStateFilter.OPEN
    severity: AlertSeverityFilter = AlertSeverityFilter.ALL
    top_n: int = 25

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(1 <= self.top_n <= 50, "top_n")


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertSummaryWindowQuery(AlertPageQuery):
    start_date: date
    end_date: date
    source_cutoff_at: datetime
    state: AlertStateFilter = AlertStateFilter.OPEN
    severity: AlertSeverityFilter = AlertSeverityFilter.ALL

    def __post_init__(self) -> None:
        AlertPageQuery.__post_init__(self)
        alert_require(0 <= (self.end_date - self.start_date).days <= 3660, "period")


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertEvaluationView(AlertRecord):
    id: UUID
    job_id: UUID
    rule_id: UUID
    rule_version_id: UUID
    account_id: UUID
    input_digest: str
    result_digest: str
    rule_content_digest: str
    definition: AlertRuleDefinition | None
    source_references: tuple[AlertSourceReference, ...]
    canonical_bindings: tuple[AlertCanonicalBinding, ...]
    licenses: tuple[SourceLicense, ...]
    scheduled_for: datetime
    evaluated_at: datetime
    outcome: AlertEvaluationOutcome
    execution_intent: AlertExecutionIntent
    result: AlertEvaluationResult | None
    reproducibility: AlertReproducibility
    expires_at: datetime

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(
            (self.result is not None) == (self.reproducibility is AlertReproducibility.RETAINED),
            "result.retention",
        )
        alert_require(
            (self.definition is not None) == (self.result is not None), "definition.retention"
        )
        alert_require(
            self.result is not None
            or not (self.source_references or self.canonical_bindings or self.licenses),
            "proof.retention",
        )
        if self.result is not None:
            alert_require(
                self.result.rule_version_id == self.rule_version_id
                and self.result.input_digest == self.input_digest
                and self.result.scheduled_for == self.scheduled_for
                and self.result.outcome is self.outcome
                and self.result.execution_intent is self.execution_intent,
                "result.binding",
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertEvaluationPage(AlertRecord):
    items: tuple[AlertEvaluationView, ...]
    total: int
    limit: int
    next_cursor: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertRuleVersionDetail(AlertRecord):
    version: AlertRuleVersion
    rule_revision: int


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertRuleVersionPage(AlertRecord):
    items: tuple[AlertRuleVersion, ...]
    total: int
    limit: int
    next_cursor: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertRuleDetail(AlertRecord):
    id: UUID
    account_id: UUID
    revision: int
    lifecycle: AlertLifecycle
    created_at: datetime
    updated_at: datetime
    latest_version: AlertRuleVersion
    active_version: AlertRuleVersion | None
    next_scheduled_for: datetime | None
    latest_evaluation: AlertEvaluationView | None
    evaluation_page: AlertEvaluationPage
    version_page: AlertRuleVersionPage

    @property
    def etag(self) -> str:
        return f'"{self.id}:{self.revision}"'


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertRulePage(AlertRecord):
    items: tuple[AlertRuleDetail, ...]
    total: int
    limit: int
    next_cursor: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationDestination(AlertRecord):
    id: UUID
    channel: NotificationChannel
    label: str
    state: NotificationDestinationState


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationDestinationPage(AlertRecord):
    items: tuple[NotificationDestination, ...]
    total: int
    limit: int
    next_cursor: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertAcknowledgment(AlertRecord):
    id: UUID
    event_id: UUID
    principal_id: UUID
    acknowledged_at: datetime
    event_revision: int
    note: str | None = None

    def __post_init__(self) -> None:
        AlertRecord.__post_init__(self)
        alert_require(self.note is None or len(self.note) <= 1000, "note")


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertDeliveryView(AlertRecord):
    id: UUID
    destination_id: UUID
    destination_version_id: UUID
    channel: NotificationChannel
    state: AlertDeliveryState
    attempts: int
    reason: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertDeliverySummary(AlertRecord):
    in_app_notification_id: UUID
    created_at: datetime
    notification_state: AlertNotificationState
    external: tuple[AlertDeliveryView, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertEventDetail(AlertRecord):
    id: UUID
    account_id: UUID
    rule_id: UUID
    rule_version_id: UUID
    evaluation_id: UUID
    revision: int
    deduplication_digest: str
    severity: AlertSeverity
    episode_state: AlertEventState
    occurred_at: datetime
    recorded_at: datetime
    updated_at: datetime
    evaluation: AlertEvaluationView
    delivery: AlertDeliverySummary
    acknowledgment: AlertAcknowledgment | None = None
    resolved_at: datetime | None = None
    resolution_reason: AlertResolutionReason | None = None
    correction_of: UUID | None = None
    episode_ordinal: int | None = None
    remediation: str = ""

    @property
    def etag(self) -> str:
        return f'"{self.id}:{self.revision}"'


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertEventPage(AlertRecord):
    items: tuple[AlertEventDetail, ...]
    total: int
    limit: int
    next_cursor: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertSummaryCounts(AlertRecord):
    total_count: int
    open_count: int
    resolved_count: int
    acknowledged_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertSummary(AlertRecord):
    account_id: UUID
    source_cutoff_at: datetime
    counts: AlertSummaryCounts
    items: tuple[AlertEventDetail, ...]
    top_n: int
    returned_count: int
    omitted_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertSummaryPage(AlertRecord):
    account_id: UUID
    source_cutoff_at: datetime
    counts: AlertSummaryCounts
    page: AlertEventPage


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertBackfillRequest(AlertRecord):
    rule_version_id: UUID
    scheduled_for: datetime


class AlertCapturePort(Protocol):
    def capture_evaluation(
        self,
        version: AlertRuleVersion,
        scheduled_for: datetime,
        execution_intent: AlertExecutionIntent,
    ) -> AlertEvaluationInput: ...


class AlertService(Protocol):
    async def create_rule(
        self,
        principal: Principal,
        command: CreateAlertRuleCommand,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> AlertRuleDetail: ...
    async def create_rule_version(
        self,
        principal: Principal,
        rule_id: UUID,
        command: AlertRuleVersionCommand,
        *,
        idempotency_key: str,
        expected_revision: int,
        correlation_id: str,
    ) -> AlertRuleVersionDetail: ...
    async def get_rule(
        self, principal: Principal, rule_id: UUID, *, query: AlertRuleDetailQuery
    ) -> AlertRuleDetail: ...
    async def list_rules(
        self, principal: Principal, *, query: AlertRuleListQuery
    ) -> AlertRulePage: ...
    async def activate_rule(
        self,
        principal: Principal,
        rule_id: UUID,
        version_id: UUID,
        *,
        idempotency_key: str,
        expected_revision: int,
        correlation_id: str,
    ) -> AlertRuleDetail: ...
    async def pause_rule(
        self,
        principal: Principal,
        rule_id: UUID,
        *,
        idempotency_key: str,
        expected_revision: int,
        correlation_id: str,
    ) -> AlertRuleDetail: ...
    async def archive_rule(
        self,
        principal: Principal,
        rule_id: UUID,
        *,
        idempotency_key: str,
        expected_revision: int,
        correlation_id: str,
    ) -> AlertRuleDetail: ...
    async def list_events(
        self, principal: Principal, *, query: AlertEventListQuery
    ) -> AlertEventPage: ...
    async def get_event(self, principal: Principal, event_id: UUID) -> AlertEventDetail: ...
    async def acknowledge_event(
        self,
        principal: Principal,
        event_id: UUID,
        *,
        note: str | None,
        idempotency_key: str,
        expected_revision: int,
        correlation_id: str,
    ) -> AlertAcknowledgment: ...
    async def resolve_event(
        self,
        principal: Principal,
        event_id: UUID,
        *,
        note: str | None,
        idempotency_key: str,
        expected_revision: int,
        correlation_id: str,
    ) -> AlertEventDetail: ...
    async def get_summary(
        self,
        principal: Principal,
        account_id: UUID,
        *,
        query: AlertSummaryTopQuery | AlertSummaryWindowQuery,
    ) -> AlertSummary | AlertSummaryPage: ...
    async def list_notification_destinations(
        self, principal: Principal, account_id: UUID, *, query: AlertPageQuery
    ) -> NotificationDestinationPage: ...


def alert_required_scopes(
    definition: AlertRuleDefinition | None, *, write: bool
) -> frozenset[Scope]:
    """Read and write grants are independent; material write scopes are additive."""
    required = {Scope.PORTFOLIO_READ, Scope.ALERTS_WRITE if write else Scope.ALERTS_READ}
    if write:
        required.add(Scope.ANALYTICS_READ)
        if definition is not None and definition.predicate.family in {
            AlertFamily.TARGET_DRIFT,
            AlertFamily.GROUP_DRIFT,
            AlertFamily.HOLDING_DRIFT,
        }:
            required.add(Scope.TARGETS_READ)
        if definition is not None and definition.predicate.family in {
            AlertFamily.DIVIDEND_RECEIVED,
            AlertFamily.UNUSUAL_ACTIVITY,
        }:
            required.add(Scope.ACTIVITY_READ)
    return frozenset(required)
