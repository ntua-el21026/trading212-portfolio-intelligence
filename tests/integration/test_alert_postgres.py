"""Real transactional alert slots, lifecycle fencing, authorization and retained evidence."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import Engine, func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.alerts import evaluate_alert
from trading212_application import alert_jobs as jobs
from trading212_application import alerts as app
from trading212_domain import alerts as d
from trading212_domain import build_synthetic_identity
from trading212_domain.alert_serialization import encode_alert_result
from trading212_domain.enums import QualityState
from trading212_domain.sources import SourceLicense
from trading212_persistence import create_database_engine, create_session_factory
from trading212_persistence.alert_job_store import PostgresAlertJobStore
from trading212_persistence.alert_models import (
    AlertConditionModel,
    AlertEvaluationAttemptModel,
    AlertEvaluationJobModel,
    AlertEvaluationModel,
    AlertEvaluationOutboxModel,
    AlertEventModel,
    AlertInputSnapshotModel,
    InAppNotificationModel,
)
from trading212_persistence.alert_service import PostgresAlertService
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_security.principals import Principal, Scope
from trading212_worker.alert_tasks import (
    AlertExecutionState,
    execute_alert_message,
)
from trading212_worker.seed import seed_materialized_synthetic

from tests.unit.analytics.alert_factories import capture, predicate

pytestmark = pytest.mark.integration
KEY = b"alert-postgres-synthetic-cursor-signing-key"


@pytest.fixture(scope="module")
def alert_database() -> Iterator[tuple[Engine, sessionmaker[Session]]]:
    parsed = make_url(os.environ["TEST_DATABASE_URL"])
    name = "t212pi_alerts_" + uuid4().hex[:12]
    admin = parsed.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    engine = None
    try:
        url = parsed.set(drivername="postgresql+psycopg", database=name).render_as_string(
            hide_password=False
        )
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        command.check(config)
        asyncio.run(seed_materialized_synthetic(url, app_environment="test"))
        engine = create_database_engine(url)
        yield engine, create_session_factory(engine)
    finally:
        if engine is not None:
            engine.dispose()
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


@dataclass
class CaptureControl:
    scalar: Decimal = Decimal("0.5")
    quality: QualityState = QualityState.FRESH
    calls: int = 0
    references: tuple[d.AlertSourceReference, ...] = ()
    licenses: tuple[SourceLicense, ...] = ()

    def capture_evaluation(
        self,
        version: d.AlertRuleVersion,
        scheduled_for: datetime,
        execution_intent: d.AlertExecutionIntent,
    ) -> d.AlertEvaluationInput:
        self.calls += 1
        original = capture(scalar=self.scalar)
        assert isinstance(original.payload, d.AlertThresholdInput)
        observation = replace(
            original.payload.observation,
            observed=replace(original.payload.observation.observed, quality=self.quality),
        )
        return replace(
            original,
            version=version,
            scheduled_for=scheduled_for,
            source_cutoff_at=scheduled_for,
            execution_intent=execution_intent,
            observation_window=d.AlertObservationWindow(
                start_at=scheduled_for - timedelta(seconds=300),
                end_at=scheduled_for,
                newly_known_revisions=False,
            ),
            contexts=tuple(
                replace(
                    context,
                    account_id=version.account_id,
                    source_cutoff_at=scheduled_for,
                    valuation_at=scheduled_for,
                    quality=self.quality,
                    source_reference_keys=tuple(item.key for item in self.references),
                )
                for context in original.contexts
            ),
            payload=d.AlertThresholdInput(observation=observation),
            source_references=self.references,
            licenses=self.licenses,
        )


@dataclass
class AlertCase:
    engine: Engine
    sessions: sessionmaker[Session]
    clock: list[datetime]
    control: CaptureControl
    principal: Principal
    service: PostgresAlertService
    store: PostgresAlertJobStore
    account_override: UUID | None = None

    @property
    def account_id(self) -> UUID:
        return self.account_override or build_synthetic_identity().account.id

    def definition(self, *, destinations: tuple[UUID, ...] = ()) -> d.AlertRuleDefinition:
        return d.AlertRuleDefinition(
            name="Rule " + uuid4().hex[:8],
            predicate=predicate(),
            schedule=d.AlertIntervalSchedule(anchor_at=self.clock[0]),
            destination_ids=destinations,
        )

    async def active(self, *, destinations: tuple[UUID, ...] = ()) -> app.AlertRuleDetail:
        value = await self.service.create_rule(
            self.principal,
            app.CreateAlertRuleCommand(
                account_id=self.account_id, definition=self.definition(destinations=destinations)
            ),
            idempotency_key=uuid4().hex,
            correlation_id="alert-test",
        )
        return await self.service.activate_rule(
            self.principal,
            value.id,
            value.latest_version.id,
            idempotency_key=uuid4().hex,
            expected_revision=value.revision,
            correlation_id="alert-test",
        )

    async def admit(self, rule_id: UUID) -> jobs.AlertEvaluationTaskMessage:
        await self.store.admit_due_evaluations()
        with self.sessions() as session:
            row = session.scalar(
                select(AlertEvaluationJobModel)
                .where(AlertEvaluationJobModel.rule_id == rule_id)
                .order_by(AlertEvaluationJobModel.scheduled_for.desc())
                .limit(1)
            )
            assert row is not None
            return self.store._evaluation_message(row)


@pytest.fixture
def alert_case(alert_database: tuple[Engine, sessionmaker[Session]]) -> AlertCase:
    engine, sessions = alert_database
    identity = build_synthetic_identity()
    clock = [datetime.now(UTC)]
    principal = Principal(
        str(identity.principal.id),
        str(identity.owner.id),
        "local.synthetic",
        "synthetic-owner",
        frozenset(Scope),
        clock[0] - timedelta(days=1),
        clock[0] + timedelta(days=200),
    )
    with sessions() as session, session.begin():
        provision_principal_scopes(
            session,
            principal_id=identity.principal.id,
            scopes=frozenset(Scope),
            now=clock[0] - timedelta(seconds=1),
        )
    control = CaptureControl()
    return AlertCase(
        engine,
        sessions,
        clock,
        control,
        principal,
        PostgresAlertService(
            sessions,
            cursor_signing_key=KEY,
            clock=lambda: clock[0],
            capture_factory=lambda _session, _authorization: control,
        ),
        PostgresAlertJobStore(
            sessions,
            cursor_signing_key=KEY,
            clock=lambda: clock[0],
            capture_factory=lambda _session, _authorization: control,
        ),
    )


def test_atomic_slot_idempotency_immutable_input_and_real_worker_restart(
    alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = alert_case
        rule = await case.active()
        message = await case.admit(rule.id)
        count = case.control.calls
        await case.store.admit_due_evaluations()
        assert case.control.calls == count
        recreated = PostgresAlertJobStore(
            case.sessions, cursor_signing_key=KEY, clock=lambda: case.clock[0]
        )
        assert (
            await execute_alert_message(recreated, message, consumer_id="real-restart")
            is AlertExecutionState.COMPLETED
        )
        assert (
            await execute_alert_message(recreated, message, consumer_id="duplicate")
            is AlertExecutionState.NOT_CLAIMED
        )
        detail = await case.service.get_rule(
            case.principal, rule.id, query=app.AlertRuleDetailQuery()
        )
        assert detail.latest_evaluation is not None and detail.latest_evaluation.result is not None
        assert detail.latest_evaluation.outcome is d.AlertEvaluationOutcome.MATCHED
        with case.sessions() as session:
            stored = session.get(AlertInputSnapshotModel, message.capture_id)
            assert stored is not None and stored.sealed_at is not None
            result = session.scalar(
                select(AlertEvaluationModel).where(AlertEvaluationModel.job_id == message.job_id)
            )
            assert result is not None
            assert result.payload == encode_alert_result(detail.latest_evaluation.result)
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AlertEventModel)
                    .where(AlertEventModel.rule_id == rule.id)
                )
                == 1
            )
            event = session.scalar(
                select(AlertEventModel).where(AlertEventModel.rule_id == rule.id)
            )
            assert event is not None
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(InAppNotificationModel)
                    .where(InAppNotificationModel.event_id == event.id)
                )
                == 1
            )
        with pytest.raises(DBAPIError), case.sessions() as session, session.begin():
            session.execute(
                update(AlertInputSnapshotModel)
                .where(AlertInputSnapshotModel.id == message.capture_id)
                .values(payload=b"{}")
                .execution_options(synchronize_session=False)
            )

    asyncio.run(run())


def test_reversed_delivery_does_not_consume_later_attempt_or_apply_episode_out_of_order(
    alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = alert_case
        rule = await case.active()
        first = await case.admit(rule.id)
        case.clock[0] += timedelta(seconds=300)
        second = await case.admit(rule.id)
        assert second.scheduled_for > first.scheduled_for
        assert await case.store.claim_evaluation_job(second, consumer_id="reversed") is None
        with case.sessions() as session:
            later = session.get(AlertEvaluationJobModel, second.job_id)
            assert later is not None and later.consumer_attempts == 0 and later.fence == 0
        assert (
            await execute_alert_message(case.store, first, consumer_id="first")
            is AlertExecutionState.COMPLETED
        )
        assert (
            await execute_alert_message(case.store, second, consumer_id="second")
            is AlertExecutionState.COMPLETED
        )
        with case.sessions() as session:
            condition = session.scalar(
                select(AlertConditionModel).where(
                    AlertConditionModel.rule_version_id == first.rule_version_id
                )
            )
            assert (
                condition is not None
                and condition.last_applied_scheduled_for == second.scheduled_for
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AlertEventModel)
                    .where(AlertEventModel.rule_id == rule.id)
                )
                == 1
            )

    asyncio.run(run())


def test_pause_excludes_slots_preserves_backlog_and_fences_old_worker(
    alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = alert_case
        rule = await case.active()
        first = await case.admit(rule.id)
        claim = await case.store.claim_evaluation_job(first, consumer_id="before-pause")
        assert claim is not None
        original = await case.store.load_evaluation_input(claim)
        case.clock[0] += timedelta(seconds=1)
        paused = await case.service.pause_rule(
            case.principal,
            rule.id,
            idempotency_key=uuid4().hex,
            expected_revision=rule.revision,
            correlation_id="pause",
        )
        assert not await case.store.complete_evaluation_job(claim, result=evaluate_alert(original))
        case.clock[0] += timedelta(seconds=600)
        resumed = await case.service.activate_rule(
            case.principal,
            rule.id,
            first.rule_version_id,
            idempotency_key=uuid4().hex,
            expected_revision=paused.revision,
            correlation_id="resume",
        )
        replacement = await case.store.claim_evaluation_job(first, consumer_id="after-resume")
        assert replacement is not None and replacement.fence == claim.fence + 1
        assert replacement.consumer_attempt == claim.consumer_attempt + 1
        assert await case.store.complete_evaluation_job(
            replacement, result=evaluate_alert(original)
        )
        assert not await case.store.complete_evaluation_job(claim, result=evaluate_alert(original))
        assert resumed.next_scheduled_for == first.scheduled_for + timedelta(seconds=300)
        await case.store.admit_due_evaluations()
        with case.sessions() as session:
            slots = tuple(
                session.scalars(
                    select(AlertEvaluationJobModel.scheduled_for).where(
                        AlertEvaluationJobModel.rule_id == rule.id
                    )
                )
            )
            assert slots == (first.scheduled_for,)
        case.clock[0] = first.scheduled_for + timedelta(seconds=900)
        fresh = await case.admit(rule.id)
        assert fresh.scheduled_for == first.scheduled_for + timedelta(seconds=900)

    asyncio.run(run())


def test_version_creation_does_not_activate_and_idempotency_body_conflict_is_explicit(
    alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = alert_case
        rule = await case.active()
        key = uuid4().hex
        command = app.AlertRuleVersionCommand(
            definition=replace(case.definition(), severity=d.AlertSeverity.CRITICAL)
        )
        version = await case.service.create_rule_version(
            case.principal,
            rule.id,
            command,
            idempotency_key=key,
            expected_revision=rule.revision,
            correlation_id="version",
        )
        replay = await case.service.create_rule_version(
            case.principal,
            rule.id,
            command,
            idempotency_key=key,
            expected_revision=rule.revision,
            correlation_id="replay",
        )
        assert replay == version
        detail = await case.service.get_rule(
            case.principal, rule.id, query=app.AlertRuleDetailQuery()
        )
        assert (
            detail.active_version is not None
            and rule.active_version is not None
            and detail.active_version.id == rule.active_version.id
        )
        assert detail.latest_version.id == version.version.id
        with pytest.raises(app.AlertServiceError) as error:
            await case.service.create_rule_version(
                case.principal,
                rule.id,
                replace(command, definition=replace(command.definition, name="Different")),
                idempotency_key=key,
                expected_revision=rule.revision,
                correlation_id="conflict",
            )
        assert error.value.code is app.AlertServiceErrorCode.IDEMPOTENCY_KEY_REUSED

    asyncio.run(run())


def test_scope_revocation_denies_retained_read_and_prevents_worker_publication(
    alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = alert_case
        rule = await case.active()
        message = await case.admit(rule.id)
        claim = await case.store.claim_evaluation_job(message, consumer_id="revoked")
        assert claim is not None
        value = await case.store.load_evaluation_input(claim)
        case.clock[0] += timedelta(seconds=1)
        with case.sessions() as session, session.begin():
            provision_principal_scopes(
                session,
                principal_id=UUID(case.principal.principal_id),
                scopes=frozenset({Scope.PORTFOLIO_READ}),
                now=case.clock[0],
            )
        with pytest.raises(app.AlertServiceError) as denied:
            await case.service.get_rule(case.principal, rule.id, query=app.AlertRuleDetailQuery())
        assert denied.value.code is app.AlertServiceErrorCode.ACCESS_DENIED
        with pytest.raises(jobs.AlertJobInputError) as failed:
            await case.store.complete_evaluation_job(claim, result=evaluate_alert(value))
        assert failed.value.code is d.AlertReason.ACCESS_DENIED
        with case.sessions() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AlertEvaluationModel)
                    .where(AlertEvaluationModel.job_id == message.job_id)
                )
                == 0
            )

    asyncio.run(run())


def test_late_final_publication_failure_and_ack_preserve_completed_result(
    alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = alert_case
        rule = await case.active()
        message = await case.admit(rule.id)
        claims = await case.store.claim_evaluation_dispatches(dispatcher_id="final-dispatch")
        dispatch = next(c for c in claims if c.message.job_id == message.job_id)
        assert (
            await execute_alert_message(case.store, message, consumer_id="fast")
            is AlertExecutionState.COMPLETED
        )
        with case.sessions() as session:
            result = session.scalar(
                select(AlertEvaluationModel.content_digest).where(
                    AlertEvaluationModel.job_id == message.job_id
                )
            )
            before = tuple(
                session.execute(
                    select(
                        AlertEvaluationOutboxModel.state,
                        AlertEvaluationOutboxModel.publication_attempts,
                    ).where(AlertEvaluationOutboxModel.job_id == message.job_id)
                ).one()
            )
            count = session.scalar(
                select(func.count())
                .select_from(AlertEvaluationAttemptModel)
                .where(AlertEvaluationAttemptModel.job_id == message.job_id)
            )
        assert not await case.store.defer_evaluation_dispatch(
            dispatch, failure=d.AlertReason.PUBLICATION_UNAVAILABLE
        )
        assert not await case.store.acknowledge_evaluation_dispatch(dispatch)
        with case.sessions() as session:
            assert (
                session.scalar(
                    select(AlertEvaluationModel.content_digest).where(
                        AlertEvaluationModel.job_id == message.job_id
                    )
                )
                == result
            )
            assert (
                tuple(
                    session.execute(
                        select(
                            AlertEvaluationOutboxModel.state,
                            AlertEvaluationOutboxModel.publication_attempts,
                        ).where(AlertEvaluationOutboxModel.job_id == message.job_id)
                    ).one()
                )
                == before
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AlertEvaluationAttemptModel)
                    .where(AlertEvaluationAttemptModel.job_id == message.job_id)
                )
                == count
            )

    asyncio.run(run())


def test_acknowledgment_window_asof_counts_and_manual_resolution_do_not_rearm(
    alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = alert_case
        rule = await case.active()
        message = await case.admit(rule.id)
        assert (
            await execute_alert_message(case.store, message, consumer_id="episode")
            is AlertExecutionState.COMPLETED
        )
        page = await case.service.list_events(
            case.principal,
            query=app.AlertEventListQuery(account_id=case.account_id, rule_id=rule.id),
        )
        event = page.items[0]
        cutoff = case.clock[0]
        case.clock[0] += timedelta(seconds=1)
        ack = await case.service.acknowledge_event(
            case.principal,
            event.id,
            note="reviewed",
            idempotency_key=uuid4().hex,
            expected_revision=event.revision,
            correlation_id="ack",
        )
        await case.service.resolve_event(
            case.principal,
            event.id,
            note=None,
            idempotency_key=uuid4().hex,
            expected_revision=ack.event_revision,
            correlation_id="resolve",
        )
        before = await case.service.get_summary(
            case.principal,
            case.account_id,
            query=app.AlertSummaryWindowQuery(
                start_date=cutoff.date(), end_date=cutoff.date(), source_cutoff_at=cutoff
            ),
        )
        assert isinstance(before, app.AlertSummaryPage)
        actual = next(item for item in before.page.items if item.id == event.id)
        assert actual.episode_state is app.AlertEventState.OPEN and actual.acknowledgment is None
        case.clock[0] = message.scheduled_for + timedelta(seconds=300)
        again = await case.admit(rule.id)
        assert (
            await execute_alert_message(case.store, again, consumer_id="still-true")
            is AlertExecutionState.COMPLETED
        )
        with case.sessions() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AlertEventModel)
                    .where(AlertEventModel.rule_id == rule.id)
                )
                == 1
            )

    asyncio.run(run())


def test_every_saved_version_remains_paged_without_activating_drafts(alert_case: AlertCase) -> None:
    async def run() -> None:
        case = alert_case
        rule = await case.active()
        initial = rule.active_version
        assert initial is not None
        expected = {initial.id}
        revision = rule.revision
        for number in range(3):
            saved = await case.service.create_rule_version(
                case.principal,
                rule.id,
                app.AlertRuleVersionCommand(
                    definition=replace(initial.definition, name=f"Draft {number}")
                ),
                idempotency_key=uuid4().hex,
                expected_revision=revision,
                correlation_id="versions",
            )
            expected.add(saved.version.id)
            revision = saved.rule_revision
        seen: set[UUID] = set()
        cursor = None
        while True:
            detail = await case.service.get_rule(
                case.principal,
                rule.id,
                query=app.AlertRuleDetailQuery(version_limit=1, version_cursor=cursor),
            )
            assert detail.active_version is not None and detail.active_version.id == initial.id
            assert detail.version_page.total == 4 and len(detail.version_page.items) == 1
            assert detail.version_page.items[0].id not in seen
            seen.add(detail.version_page.items[0].id)
            cursor = detail.version_page.next_cursor
            if cursor is None:
                break
        assert seen == expected

    asyncio.run(run())


def test_real_notification_job_retries_same_payload_and_late_callbacks_preserve_success(
    alert_case: AlertCase,
) -> None:
    from trading212_domain.alert_serialization import decode_alert_record
    from trading212_persistence.alert_models import (
        NotificationDeliveryJobModel,
        NotificationDeliveryOutboxModel,
    )
    from trading212_persistence.models import AuditEventModel
    from trading212_persistence.notification_store import (
        PostgresAlertNotificationStore,
        provision_notification_destination,
    )

    async def run() -> None:
        case = alert_case
        with case.sessions() as session, session.begin():
            destination = provision_notification_destination(
                session,
                owner_id=UUID(case.principal.owner_id),
                account_id=case.account_id,
                configuration_key="test-webhook-" + uuid4().hex,
                channel=app.NotificationChannel.WEBHOOK,
                label="Configured test endpoint",
                secret_reference="synthetic-config-reference",
                state=app.NotificationDestinationState.CONFIGURED,
                now=case.clock[0],
            )
        rule = await case.active(destinations=(destination,))
        message = await case.admit(rule.id)
        assert (
            await execute_alert_message(case.store, message, consumer_id="notify-evaluate")
            is AlertExecutionState.COMPLETED
        )
        store = PostgresAlertNotificationStore(
            case.sessions, cursor_signing_key=KEY, clock=lambda: case.clock[0]
        )
        with case.sessions() as session:
            event = session.scalar(
                select(AlertEventModel).where(AlertEventModel.rule_id == rule.id)
            )
            assert event is not None
            row = session.scalar(
                select(NotificationDeliveryJobModel).where(
                    NotificationDeliveryJobModel.event_id == event.id
                )
            )
            assert row is not None and row.state == "queued"
            wire = store._message(row)
            assert isinstance(wire, jobs.AlertNotificationTaskMessage)
            content = bytes(row.payload)
            payload = decode_alert_record(content, jobs.AlertNotificationPayload)
            assert set(json.loads(content)) == {
                "delivery_id",
                "event_id",
                "rule_id",
                "rule_version_id",
            }
            assert b"synthetic-config-reference" not in content
        first = await store.claim_notification_job(wire, consumer_id="delivery-first")
        assert first is not None
        assert await store.load_notification_payload(first) == payload
        assert await store.fail_notification_job(
            first, failure=d.AlertReason.PUBLICATION_UNAVAILABLE, retryable=True
        )
        case.clock[0] += timedelta(seconds=2)
        dispatch = next(
            item
            for item in await store.claim_notification_dispatches(dispatcher_id="delivery-dispatch")
            if item.message == wire
        )
        second = await store.claim_notification_job(wire, consumer_id="delivery-second")
        assert second is not None and second.fence == first.fence + 1
        assert await store.load_notification_payload(second) == payload
        receipt = jobs.AlertDeliveryReceipt(
            delivery_id=wire.delivery_id,
            outcome=jobs.AlertDeliveryOutcome.ACCEPTED,
            observed_at=case.clock[0],
        )
        assert not await store.complete_notification_job(first, receipt=receipt)
        assert await store.complete_notification_job(second, receipt=receipt)
        assert not await store.defer_notification_dispatch(
            dispatch, failure=d.AlertReason.PUBLICATION_UNAVAILABLE
        )
        assert not await store.acknowledge_notification_dispatch(dispatch)
        with case.sessions() as session:
            stored = session.get(NotificationDeliveryJobModel, wire.delivery_id)
            outbox = session.scalar(
                select(NotificationDeliveryOutboxModel).where(
                    NotificationDeliveryOutboxModel.job_id == wire.delivery_id
                )
            )
            assert stored is not None and stored.state == "succeeded" and stored.payload == content
            assert outbox is not None and outbox.state == "claimed"
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEventModel)
                    .where(
                        AuditEventModel.resource_id == str(wire.delivery_id),
                        AuditEventModel.action == "alert.notification.completed",
                    )
                )
                == 1
            )

    asyncio.run(run())


def test_unavailable_destination_is_explicit_and_never_dispatches(alert_case: AlertCase) -> None:
    from trading212_persistence.alert_models import NotificationDeliveryJobModel
    from trading212_persistence.notification_store import (
        PostgresAlertNotificationStore,
        provision_notification_destination,
    )

    async def run() -> None:
        case = alert_case
        with case.sessions() as session, session.begin():
            identifier = provision_notification_destination(
                session,
                owner_id=UUID(case.principal.owner_id),
                account_id=case.account_id,
                configuration_key="unavailable-" + uuid4().hex,
                channel=app.NotificationChannel.EMAIL,
                label="Not configured",
                secret_reference=None,
                state=app.NotificationDestinationState.UNAVAILABLE,
                now=case.clock[0],
            )
        rule = await case.active(destinations=(identifier,))
        message = await case.admit(rule.id)
        assert (
            await execute_alert_message(case.store, message, consumer_id="unavailable")
            is AlertExecutionState.COMPLETED
        )
        with case.sessions() as session:
            event = session.scalar(
                select(AlertEventModel).where(AlertEventModel.rule_id == rule.id)
            )
            assert event is not None and event.notification_state == "external_delivery_unavailable"
            delivery = session.scalar(
                select(NotificationDeliveryJobModel).where(
                    NotificationDeliveryJobModel.event_id == event.id
                )
            )
            assert (
                delivery is not None
                and delivery.state == "failed"
                and delivery.failure_code == "not_configured"
            )
            store = PostgresAlertNotificationStore(
                case.sessions, cursor_signing_key=KEY, clock=lambda: case.clock[0]
            )
            wire = store._message(delivery)
            assert isinstance(wire, jobs.AlertNotificationTaskMessage)
        assert await store.claim_notification_job(wire, consumer_id="unavailable") is None

    asyncio.run(run())
