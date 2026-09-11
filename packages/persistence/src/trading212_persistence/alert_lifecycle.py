"""Immutable rule versions, audited active intervals and idempotent owner commands."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import alerts as app
from trading212_domain.alert_serialization import (
    encode_alert_condition,
    encode_alert_rule_definition,
)
from trading212_domain.alerts import (
    AlertConditionState,
    AlertDailyUtcSchedule,
    AlertIntervalSchedule,
    AlertRuleDefinition,
)
from trading212_security.principals import Principal

from .alert_authorization import AlertAuthorization, authorize_alert_request
from .alert_base import alert_owner_lock, audit_alert, fail, rule_version
from .alert_models import (
    AlertConditionModel,
    AlertEvaluationAttemptModel,
    AlertEvaluationJobModel,
    AlertEventModel,
    AlertRuleEventModel,
    AlertRuleModel,
    AlertRuleVersionModel,
)
from .alert_reads import AlertReads


def command_digest(command: str, account_id: UUID, *parts: object) -> str:
    raw = json.dumps(
        [command, str(account_id), *parts],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def aligned_slot(version: AlertRuleVersionModel, at: datetime) -> datetime:
    if version.schedule_kind == "daily_utc":
        assert version.daily_minute is not None
        day = at.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        result = day + timedelta(minutes=version.daily_minute)
        return result if result >= at else result + timedelta(days=1)
    assert version.anchor_at is not None and version.interval_seconds is not None
    delta = at - version.anchor_at
    micros = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
    interval = version.interval_seconds * 1000000
    slots = -(-micros // interval)
    return version.anchor_at + timedelta(seconds=slots * version.interval_seconds)


def next_slot(version: AlertRuleVersionModel, slot: datetime) -> datetime:
    return slot + timedelta(seconds=version.interval_seconds or 86400)


def eligible_interval(
    session: Session, version: AlertRuleVersionModel, slot: datetime
) -> AlertRuleEventModel | None:
    event = session.scalar(
        select(AlertRuleEventModel)
        .where(
            AlertRuleEventModel.owner_id == version.owner_id,
            AlertRuleEventModel.rule_id == version.rule_id,
            AlertRuleEventModel.kind.not_in(("created", "version_created")),
            AlertRuleEventModel.occurred_at <= slot,
        )
        .order_by(AlertRuleEventModel.occurred_at.desc(), AlertRuleEventModel.sequence.desc())
        .limit(1)
    )
    return (
        event
        if event is not None and event.version_id == version.id and event.lifecycle == "active"
        else None
    )


def next_eligible_slot(
    session: Session, version: AlertRuleVersionModel, slot: datetime, *, through: datetime
) -> datetime | None:
    """Jump over audited inactive intervals without losing eligible downtime slots."""
    if slot > through:
        return None
    if eligible_interval(session, version, slot) is not None:
        return slot
    event = session.scalar(
        select(AlertRuleEventModel)
        .where(
            AlertRuleEventModel.rule_id == version.rule_id,
            AlertRuleEventModel.version_id == version.id,
            AlertRuleEventModel.kind.in_(("activated", "resumed")),
            AlertRuleEventModel.occurred_at > slot,
            AlertRuleEventModel.occurred_at <= through,
        )
        .order_by(AlertRuleEventModel.occurred_at, AlertRuleEventModel.sequence)
        .limit(1)
    )
    if event is None:
        return None
    candidate = aligned_slot(version, event.occurred_at)
    # Intervals can be shorter than a slot: query the next eligible interval iteratively.
    while candidate <= through:
        if eligible_interval(session, version, candidate) is not None:
            return candidate
        following = session.scalar(
            select(AlertRuleEventModel)
            .where(
                AlertRuleEventModel.rule_id == version.rule_id,
                AlertRuleEventModel.version_id == version.id,
                AlertRuleEventModel.kind.in_(("activated", "resumed")),
                AlertRuleEventModel.occurred_at > candidate,
                AlertRuleEventModel.occurred_at <= through,
            )
            .order_by(AlertRuleEventModel.occurred_at, AlertRuleEventModel.sequence)
            .limit(1)
        )
        if following is None:
            return None
        candidate = aligned_slot(version, following.occurred_at)
    return None


class AlertLifecycle(AlertReads):
    def _new_version(
        self, session: Session, rule: AlertRuleModel, definition: AlertRuleDefinition, number: int
    ) -> AlertRuleVersionModel:
        payload = encode_alert_rule_definition(definition)
        if len(payload) > 65536:
            fail(app.AlertServiceErrorCode.INPUT_BOUND_EXCEEDED)
        schedule = definition.schedule
        row = AlertRuleVersionModel(
            id=uuid4(),
            owner_id=rule.owner_id,
            account_id=rule.account_id,
            rule_id=rule.id,
            version_number=number,
            created_at=self._now(),
            family=definition.predicate.family.value,
            metric=definition.predicate.metric.value,
            severity=definition.severity.value,
            content_digest=hashlib.sha256(payload).hexdigest(),
            definition_payload=payload,
            schedule_kind=schedule.kind.value,
            anchor_at=schedule.anchor_at if isinstance(schedule, AlertIntervalSchedule) else None,
            interval_seconds=schedule.interval_seconds
            if isinstance(schedule, AlertIntervalSchedule)
            else None,
            daily_minute=schedule.minute_utc
            if isinstance(schedule, AlertDailyUtcSchedule)
            else None,
            cooldown_seconds=definition.cooldown_seconds,
        )
        session.add(row)
        session.flush()
        rule.latest_version_id = row.id
        rule.name = definition.name
        session.add(
            AlertConditionModel(
                id=uuid4(),
                owner_id=rule.owner_id,
                account_id=rule.account_id,
                rule_version_id=row.id,
                created_at=self._now(),
                last_applied_scheduled_for=None,
                state_payload=encode_alert_condition(AlertConditionState(rule_version_id=row.id)),
            )
        )
        return row

    def _lifecycle_event(
        self,
        session: Session,
        rule: AlertRuleModel,
        version_id: UUID,
        authorization: AlertAuthorization,
        kind: str,
    ) -> None:
        session.add(
            AlertRuleEventModel(
                id=uuid4(),
                owner_id=rule.owner_id,
                account_id=rule.account_id,
                rule_id=rule.id,
                version_id=version_id,
                principal_id=authorization.principal_id,
                created_at=self._now(),
                sequence=rule.revision,
                kind=kind,
                lifecycle=rule.lifecycle,
                occurred_at=rule.updated_at,
                due_frontier=rule.next_scheduled_for,
            )
        )
        audit_alert(
            session,
            authorization,
            action=f"alert.rule.{kind}",
            resource_id=rule.id,
            at=rule.updated_at,
        )

    async def create_rule(
        self,
        principal: Principal,
        command: app.CreateAlertRuleCommand,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> app.AlertRuleDetail:
        def execute() -> app.AlertRuleDetail:
            with self._sessions() as session, session.begin():
                authorization = authorize_alert_request(
                    session,
                    principal,
                    account_id=command.account_id,
                    definition=command.definition,
                    write=True,
                    now=self._now(),
                )
                alert_owner_lock(session, authorization.owner_id)
                digest = command_digest(
                    "create_rule",
                    command.account_id,
                    encode_alert_rule_definition(command.definition).decode(),
                )
                previous = self._command(
                    session,
                    authorization,
                    command="create_rule",
                    idempotency_key=idempotency_key,
                    digest=digest,
                )
                if previous is not None:
                    rule = session.get(AlertRuleModel, previous.rule_id)
                    assert rule is not None
                    return self._rule_detail(
                        session, authorization, rule, app.AlertRuleDetailQuery()
                    )
                self._references(session, authorization, command.definition)
                at = self._now()
                rule = AlertRuleModel(
                    id=uuid4(),
                    owner_id=authorization.owner_id,
                    account_id=authorization.account_id,
                    principal_id=authorization.principal_id,
                    name=command.definition.name,
                    lifecycle="draft",
                    revision=1,
                    lifecycle_sequence=1,
                    created_at=at,
                    updated_at=at,
                    latest_version_id=None,
                    active_version_id=None,
                    next_scheduled_for=None,
                )
                session.add(rule)
                session.flush()
                version = self._new_version(session, rule, command.definition, 1)
                self._lifecycle_event(session, rule, version.id, authorization, "created")
                self._record_command(
                    session,
                    authorization,
                    command="create_rule",
                    key=idempotency_key,
                    digest=digest,
                    result_id=rule.id,
                    revision=rule.revision,
                    rule_id=rule.id,
                )
                session.flush()
                authorization.check(session, now=self._now())
                return self._rule_detail(session, authorization, rule, app.AlertRuleDetailQuery())

        return await self._run(execute)

    async def create_rule_version(
        self,
        principal: Principal,
        rule_id: UUID,
        command: app.AlertRuleVersionCommand,
        *,
        idempotency_key: str,
        expected_revision: int,
        correlation_id: str,
    ) -> app.AlertRuleVersionDetail:
        def execute() -> app.AlertRuleVersionDetail:
            with self._sessions() as session, session.begin():
                rule, _ = self._rule(session, principal, rule_id, write=True)
                authorization = authorize_alert_request(
                    session,
                    principal,
                    account_id=rule.account_id,
                    definition=command.definition,
                    write=True,
                    now=self._now(),
                )
                digest = command_digest(
                    "create_rule_version",
                    rule.account_id,
                    str(rule_id),
                    expected_revision,
                    encode_alert_rule_definition(command.definition).decode(),
                )
                previous = self._command(
                    session,
                    authorization,
                    command="create_rule_version",
                    idempotency_key=idempotency_key,
                    digest=digest,
                )
                if previous is not None:
                    return app.AlertRuleVersionDetail(
                        version=rule_version(self._version(session, rule, previous.result_id)),
                        rule_revision=previous.resulting_revision,
                    )
                self._revision(rule.revision, expected_revision)
                if rule.lifecycle == "archived":
                    fail(app.AlertServiceErrorCode.INVALID_STATE_TRANSITION)
                self._references(session, authorization, command.definition)
                latest = self._version(session, rule)
                version = self._new_version(
                    session, rule, command.definition, latest.version_number + 1
                )
                rule.revision += 1
                rule.updated_at = self._now()
                self._lifecycle_event(session, rule, version.id, authorization, "version_created")
                self._record_command(
                    session,
                    authorization,
                    command="create_rule_version",
                    key=idempotency_key,
                    digest=digest,
                    result_id=version.id,
                    revision=rule.revision,
                    rule_id=rule.id,
                )
                authorization.check(session, now=self._now())
                return app.AlertRuleVersionDetail(
                    version=rule_version(version), rule_revision=rule.revision
                )

        return await self._run(execute)

    def _close_episodes(
        self, session: Session, authorization: AlertAuthorization, rule: AlertRuleModel, reason: str
    ) -> None:
        # At most one open threshold episode per version; event rules remain independent.
        from .alert_events import resolve_episode

        rows = session.scalars(
            select(AlertEventModel).where(
                AlertEventModel.rule_id == rule.id,
                AlertEventModel.state == "open",
                AlertEventModel.episode_ordinal.is_not(None),
            )
        )
        for event in rows:
            resolve_episode(
                session,
                event,
                reason=reason,
                at=self._now(),
                principal_id=authorization.principal_id,
            )

    def _pause_running_evaluation(self, session: Session, rule: AlertRuleModel) -> None:
        # Strict chronological claims permit one live evaluation for the active version.
        running = tuple(
            session.scalars(
                select(AlertEvaluationJobModel)
                .where(
                    AlertEvaluationJobModel.rule_id == rule.id,
                    AlertEvaluationJobModel.rule_version_id == rule.active_version_id,
                    AlertEvaluationJobModel.execution_intent == "live",
                    AlertEvaluationJobModel.state == "running",
                )
                .limit(2)
                .with_for_update()
            )
        )
        if len(running) > 1:
            fail(app.AlertServiceErrorCode.ALERTS_UNAVAILABLE)
        for job in running:
            job.state = "queued"
            job.failure_code = "rule_paused"
            job.available_at = self._now()
            job.lease_id = None
            job.lease_expires_at = None
            job.consumer_id = None
            session.add(
                AlertEvaluationAttemptModel(
                    id=uuid4(),
                    owner_id=job.owner_id,
                    job_id=job.id,
                    created_at=self._now(),
                    phase="consumer",
                    attempt=job.consumer_attempts,
                    fence=job.fence,
                    outcome="retry",
                    failure_code="rule_paused",
                )
            )

    async def _change_lifecycle(
        self,
        principal: Principal,
        rule_id: UUID,
        *,
        command: str,
        version_id: UUID | None,
        idempotency_key: str,
        expected_revision: int,
    ) -> app.AlertRuleDetail:
        def execute() -> app.AlertRuleDetail:
            with self._sessions() as session, session.begin():
                rule, authorization = self._rule(session, principal, rule_id, write=True)
                digest = command_digest(
                    command,
                    rule.account_id,
                    str(rule.id),
                    str(version_id) if version_id else None,
                    expected_revision,
                )
                previous = self._command(
                    session,
                    authorization,
                    command=command,
                    idempotency_key=idempotency_key,
                    digest=digest,
                )
                if previous is not None:
                    # Replay the original command's scope requirements even when a
                    # different version is active now. The immutable lifecycle event
                    # pins the version used by that command's resulting revision.
                    event = session.scalar(
                        select(AlertRuleEventModel).where(
                            AlertRuleEventModel.owner_id == rule.owner_id,
                            AlertRuleEventModel.rule_id == rule.id,
                            AlertRuleEventModel.sequence == previous.resulting_revision,
                        )
                    )
                    if event is None:
                        fail(app.AlertServiceErrorCode.ALERTS_UNAVAILABLE)
                    assert event is not None
                    definition = rule_version(
                        self._version(session, rule, event.version_id)
                    ).definition
                    authorization = authorize_alert_request(
                        session,
                        principal,
                        account_id=rule.account_id,
                        definition=definition,
                        write=True,
                        now=self._now(),
                    )
                    return self._rule_detail(
                        session, authorization, rule, app.AlertRuleDetailQuery()
                    )
                self._revision(rule.revision, expected_revision)
                if rule.lifecycle == "archived":
                    fail(app.AlertServiceErrorCode.INVALID_STATE_TRANSITION)
                if command == "activate_rule":
                    version = self._version(session, rule, version_id)
                    definition = rule_version(version).definition
                    authorization = authorize_alert_request(
                        session,
                        principal,
                        account_id=rule.account_id,
                        definition=definition,
                        write=True,
                        now=self._now(),
                    )
                    self._references(session, authorization, definition)
                    if rule.lifecycle == "active" and rule.active_version_id == version.id:
                        fail(app.AlertServiceErrorCode.INVALID_STATE_TRANSITION)
                    same = rule.active_version_id == version.id
                    kind = "resumed" if same else "activated"
                    if rule.active_version_id is not None and not same:
                        self._close_episodes(session, authorization, rule, "rule_superseded")
                    rule.active_version_id = version.id
                    rule.principal_id = authorization.principal_id
                    rule.lifecycle = "active"
                    if not same or rule.next_scheduled_for is None:
                        rule.next_scheduled_for = aligned_slot(version, self._now())
                elif command == "pause_rule":
                    if rule.lifecycle != "active":
                        fail(app.AlertServiceErrorCode.INVALID_STATE_TRANSITION)
                    definition = rule_version(
                        self._version(session, rule, rule.active_version_id)
                    ).definition
                    authorization = authorize_alert_request(
                        session,
                        principal,
                        account_id=rule.account_id,
                        definition=definition,
                        write=True,
                        now=self._now(),
                    )
                    self._pause_running_evaluation(session, rule)
                    rule.lifecycle = "paused"
                    kind = "paused"
                else:
                    definition = rule_version(
                        self._version(session, rule, rule.active_version_id)
                    ).definition
                    authorization = authorize_alert_request(
                        session,
                        principal,
                        account_id=rule.account_id,
                        definition=definition,
                        write=True,
                        now=self._now(),
                    )
                    rule.lifecycle = "archived"
                    kind = "archived"
                    self._close_episodes(session, authorization, rule, "rule_archived")
                rule.revision += 1
                rule.lifecycle_sequence += 1
                rule.updated_at = self._now()
                selected_version_id = rule.active_version_id or rule.latest_version_id
                assert selected_version_id is not None
                self._lifecycle_event(
                    session,
                    rule,
                    selected_version_id,
                    authorization,
                    kind,
                )
                self._record_command(
                    session,
                    authorization,
                    command=command,
                    key=idempotency_key,
                    digest=digest,
                    result_id=rule.id,
                    revision=rule.revision,
                    rule_id=rule.id,
                )
                session.flush()
                authorization.check(session, now=self._now())
                return self._rule_detail(session, authorization, rule, app.AlertRuleDetailQuery())

        return await self._run(execute)

    async def activate_rule(
        self,
        principal: Principal,
        rule_id: UUID,
        version_id: UUID,
        *,
        idempotency_key: str,
        expected_revision: int,
        correlation_id: str,
    ) -> app.AlertRuleDetail:
        return await self._change_lifecycle(
            principal,
            rule_id,
            command="activate_rule",
            version_id=version_id,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
        )

    async def pause_rule(
        self,
        principal: Principal,
        rule_id: UUID,
        *,
        idempotency_key: str,
        expected_revision: int,
        correlation_id: str,
    ) -> app.AlertRuleDetail:
        return await self._change_lifecycle(
            principal,
            rule_id,
            command="pause_rule",
            version_id=None,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
        )

    async def archive_rule(
        self,
        principal: Principal,
        rule_id: UUID,
        *,
        idempotency_key: str,
        expected_revision: int,
        correlation_id: str,
    ) -> app.AlertRuleDetail:
        return await self._change_lifecycle(
            principal,
            rule_id,
            command="archive_rule",
            version_id=None,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
        )
