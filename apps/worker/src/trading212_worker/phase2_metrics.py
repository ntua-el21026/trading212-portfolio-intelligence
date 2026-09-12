"""Bounded metadata-only queue observations in the existing dispatcher process."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import Table, func, literal, select
from sqlalchemy.orm import Session, sessionmaker
from trading212_observability import OperationalMetrics
from trading212_persistence.alert_models import (
    AlertEvaluationJobModel,
    AlertEvaluationOutboxModel,
    NotificationDeliveryJobModel,
    NotificationDeliveryOutboxModel,
)
from trading212_persistence.planning_models import (
    ContributionPlanJobModel,
    ContributionPlanOutboxModel,
)
from trading212_persistence.report_models import (
    ExportDispatchOutboxModel,
    ExportJobModel,
    ReportDispatchOutboxModel,
    ReportJobModel,
)

QUEUE_SAMPLE_LIMIT = 1000
QUEUE_SAMPLE_INTERVAL_SECONDS = 30.0

_QUEUES = (
    ("plan", ContributionPlanJobModel, ContributionPlanOutboxModel, "dead_letter"),
    ("report", ReportJobModel, ReportDispatchOutboxModel, "dead_letter"),
    ("export", ExportJobModel, ExportDispatchOutboxModel, "dead_letter"),
    ("alert", AlertEvaluationJobModel, AlertEvaluationOutboxModel, "failed"),
    ("notification", NotificationDeliveryJobModel, NotificationDeliveryOutboxModel, "failed"),
)


@dataclass(frozen=True, slots=True)
class QueueObservation:
    queue: str
    state: str
    count: int
    saturated: bool


def _count(
    session: Session, table: Table, state: str, *, retry_column: str | None = None
) -> tuple[int, bool]:
    bounded = select(literal(1)).select_from(table).where(table.c.state == state)
    if retry_column is not None:
        bounded = bounded.where(table.c[retry_column] > 0)
    # Count at most cap+1 indexed state matches without fetching identities or payloads.
    observed = int(
        session.scalar(
            select(func.count()).select_from(bounded.limit(QUEUE_SAMPLE_LIMIT + 1).subquery())
        )
        or 0
    )
    return min(observed, QUEUE_SAMPLE_LIMIT), observed > QUEUE_SAMPLE_LIMIT


def observe_phase2_queues(
    sessions: sessionmaker[Session], metrics: OperationalMetrics, *, at: datetime
) -> None:
    observations: list[QueueObservation] = []
    with sessions() as session:
        for queue, job_model, outbox_model, dead_state in _QUEUES:
            jobs, outbox = cast(Table, job_model.__table__), cast(Table, outbox_model.__table__)
            for label, table, state, retry_column in (
                ("queued", jobs, "queued", None),
                ("running", jobs, "running", None),
                ("consumer_retry_waiting", jobs, "queued", "consumer_attempts"),
                ("publication_retry_waiting", outbox, "pending", "publication_attempts"),
                ("publication_dead", outbox, dead_state, None),
                ("job_failed", jobs, "failed", None),
            ):
                count, saturated = _count(session, table, state, retry_column=retry_column)
                observations.append(QueueObservation(queue, label, count, saturated))
    # A failed sample leaves the previous values and timestamp intact. These
    # advisory observations use read-committed queries, not one atomic queue census.
    for observation in observations:
        labels = {"queue": observation.queue, "state": observation.state}
        metrics.phase2_queue_items.labels(**labels).set(observation.count)
        metrics.phase2_queue_saturated.labels(**labels).set(int(observation.saturated))
    metrics.phase2_queue_observed_at.set(at.timestamp())
