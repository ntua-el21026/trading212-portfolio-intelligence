"""Actual canonical alert admission and workers for the disposable browser database."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from queue import Queue

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import alert_jobs as jobs
from trading212_application import alerts as app
from trading212_domain import alerts as d
from trading212_domain import build_synthetic_identity
from trading212_domain.values import CurrencyCode
from trading212_persistence.alert_job_store import PostgresAlertJobStore
from trading212_persistence.alert_models import (
    AlertEvaluationJobModel,
    AlertEvaluationModel,
    AlertEventModel,
)
from trading212_persistence.alert_service import PostgresAlertService
from trading212_persistence.notification_store import PostgresAlertNotificationStore
from trading212_security.principals import Principal, Scope
from trading212_worker.alert_tasks import (
    AlertExecutionState,
    dispatch_alerts_once,
    dispatch_notifications_once,
    execute_alert_message,
    execute_notification_message,
)
from trading212_worker.synthetic_grants import seed_synthetic_grants

KEY = b"synthetic-browser-alert-cursor-signing-key"


class FixtureAlertPublisher:
    """Only the bounded transport is in memory; capture and workers are production code."""

    def __init__(self) -> None:
        self.evaluations: Queue[jobs.AlertEvaluationTaskMessage] = Queue(maxsize=100)
        self.notifications: Queue[jobs.AlertNotificationTaskMessage] = Queue(maxsize=100)

    async def publish_evaluation(self, message: jobs.AlertEvaluationTaskMessage) -> None:
        self.evaluations.put_nowait(message)

    async def publish_notification(self, message: jobs.AlertNotificationTaskMessage) -> None:
        self.notifications.put_nowait(message)


async def seed_alert_browser_scenario(sessions: sessionmaker[Session]) -> None:
    identity = build_synthetic_identity()
    # All prior fixture sources already exist at this clock. Creating/activating at
    # the exact anchor makes the first real slot due without waiting five minutes.
    at = datetime.now(UTC)
    scopes = frozenset(
        {
            Scope.PORTFOLIO_READ,
            Scope.ANALYTICS_READ,
            Scope.ALERTS_READ,
            Scope.ALERTS_WRITE,
        }
    )
    seed_synthetic_grants(sessions, app_environment="test", at=at, scopes=scopes)
    principal = Principal(
        principal_id=str(identity.principal.id),
        owner_id=str(identity.owner.id),
        issuer="local.synthetic",
        subject="synthetic-owner",
        scopes=scopes,
        authenticated_at=at - timedelta(seconds=1),
        expires_at=at + timedelta(hours=1),
    )
    service = PostgresAlertService(sessions, cursor_signing_key=KEY, clock=lambda: at)
    store = PostgresAlertJobStore(sessions, cursor_signing_key=KEY, clock=lambda: at)
    notification_store = PostgresAlertNotificationStore(
        sessions,
        cursor_signing_key=KEY,
        clock=lambda: at,
    )
    rule_ids = []
    for name, metric, policy in (
        ("Synthetic cash monitor", d.AlertMetric.CASH_AMOUNT, d.AlertQualityPolicy.ALLOW_DEGRADED),
        (
            "Synthetic quality monitor",
            d.AlertMetric.CASH_WEIGHT,
            d.AlertQualityPolicy.REQUIRE_COMPLETE,
        ),
    ):
        definition = d.AlertRuleDefinition(
            name=name,
            predicate=d.AlertPredicate(
                family=d.AlertFamily.CASH_THRESHOLD,
                metric=metric,
                comparison=d.AlertComparison.GT,
                threshold=Decimal(0),
                currency=CurrencyCode("EUR") if metric is d.AlertMetric.CASH_AMOUNT else None,
            ),
            schedule=d.AlertIntervalSchedule(anchor_at=at),
            quality_policy=policy,
        )
        key = f"browser-alert:{metric.value}"
        rule = await service.create_rule(
            principal,
            app.CreateAlertRuleCommand(account_id=identity.account.id, definition=definition),
            idempotency_key=key,
            correlation_id=key,
        )
        await service.activate_rule(
            principal,
            rule.id,
            rule.latest_version.id,
            idempotency_key=f"{key}:activate",
            expected_revision=rule.revision,
            correlation_id=key,
        )
        rule_ids.append(rule.id)
    admitted = await store.admit_due_evaluations(limit=2)
    if admitted.admitted != 2:
        raise RuntimeError("The browser alert fixture did not admit both canonical slots.")
    publisher = FixtureAlertPublisher()
    dispatched = await dispatch_alerts_once(store, publisher, dispatcher_id="browser-fixture")
    if dispatched.published != 2:
        raise RuntimeError("The browser alert fixture did not publish both durable jobs.")
    while not publisher.evaluations.empty():
        outcome = await execute_alert_message(
            store,
            publisher.evaluations.get_nowait(),
            consumer_id="browser-fixture",
        )
        if outcome is not AlertExecutionState.COMPLETED:
            raise RuntimeError("Canonical browser alert evaluation did not complete.")
    await dispatch_notifications_once(
        notification_store, publisher, dispatcher_id="browser-fixture"
    )
    while not publisher.notifications.empty():
        outcome = await execute_notification_message(
            notification_store,
            publisher.notifications.get_nowait(),
            consumer_id="browser-fixture",
        )
        if outcome is not AlertExecutionState.COMPLETED:
            raise RuntimeError("The in-app browser notification did not complete.")
    with sessions() as session:
        evaluations = {
            rule_id: result
            for rule_id, result in session.execute(
                select(AlertEvaluationJobModel.rule_id, AlertEvaluationModel.outcome)
                .join(
                    AlertEvaluationJobModel,
                    AlertEvaluationJobModel.id == AlertEvaluationModel.job_id,
                )
                .where(AlertEvaluationJobModel.rule_id.in_(rule_ids))
            )
        }
        if evaluations != {rule_ids[0]: "matched", rule_ids[1]: "suppressed"}:
            raise RuntimeError(
                "The canonical browser fixture did not retain its expected quality states."
            )
        event_rules = tuple(
            session.scalars(
                select(AlertEventModel.rule_id).where(AlertEventModel.rule_id.in_(rule_ids))
            )
        )
        if event_rules != (rule_ids[0],):
            raise RuntimeError(
                "The browser fixture must have one actual cash event and no quality-gap event."
            )
