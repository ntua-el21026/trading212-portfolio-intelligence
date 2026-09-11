"""Authorized alert management; mutations never execute broker operations."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from trading212_application import alerts as app
from trading212_security.principals import Principal

from .alert_authorization import authorize_alert_request
from .alert_base import audit_alert, fail, rule_version
from .alert_events import resolve_episode
from .alert_lifecycle import AlertLifecycle, command_digest
from .alert_models import AlertAcknowledgmentModel, AlertEventTransitionModel, AlertRuleVersionModel


class PostgresAlertService(AlertLifecycle):
    async def acknowledge_event(
        self,
        principal: Principal,
        event_id: UUID,
        *,
        note: str | None,
        idempotency_key: str,
        expected_revision: int,
        correlation_id: str,
    ) -> app.AlertAcknowledgment:
        def execute() -> app.AlertAcknowledgment:
            with self._sessions() as session, session.begin():
                event, authorization = self._event(session, principal, event_id, write=True)
                version = session.get(AlertRuleVersionModel, event.rule_version_id)
                assert version is not None
                authorization = authorize_alert_request(
                    session,
                    principal,
                    account_id=event.account_id,
                    definition=rule_version(version).definition,
                    write=True,
                    now=self._now(),
                )
                if note is not None and (not isinstance(note, str) or len(note) > 1000):
                    fail(app.AlertServiceErrorCode.VALIDATION_FAILED)
                digest = command_digest(
                    "acknowledge_event", event.account_id, str(event.id), expected_revision, note
                )
                previous = self._command(
                    session,
                    authorization,
                    command="acknowledge_event",
                    idempotency_key=idempotency_key,
                    digest=digest,
                )
                if previous is not None:
                    row = session.scalar(
                        select(AlertAcknowledgmentModel).where(
                            AlertAcknowledgmentModel.command_id == previous.id
                        )
                    )
                    assert row is not None
                    return self._ack_view(row, previous.resulting_revision)
                self._revision(event.revision, expected_revision)
                event.revision += 1
                event.updated_at = self._now()
                identifier = uuid4()
                command = self._record_command(
                    session,
                    authorization,
                    command="acknowledge_event",
                    key=idempotency_key,
                    digest=digest,
                    result_id=identifier,
                    revision=event.revision,
                    event_id=event.id,
                )
                session.flush()
                row = AlertAcknowledgmentModel(
                    id=identifier,
                    owner_id=event.owner_id,
                    account_id=event.account_id,
                    created_at=self._now(),
                    event_id=event.id,
                    command_id=command.id,
                    principal_id=authorization.principal_id,
                    acknowledged_at=self._now(),
                    note=note,
                )
                session.add(row)
                session.add(
                    AlertEventTransitionModel(
                        id=uuid4(),
                        owner_id=event.owner_id,
                        account_id=event.account_id,
                        created_at=self._now(),
                        event_id=event.id,
                        evaluation_id=None,
                        principal_id=authorization.principal_id,
                        sequence=event.revision,
                        kind="acknowledged",
                        reason=None,
                        occurred_at=event.updated_at,
                    )
                )
                audit_alert(
                    session,
                    authorization,
                    action="alert.event.acknowledged",
                    resource_id=event.id,
                    at=self._now(),
                )
                authorization.check(session, now=self._now())
                return self._ack_view(row, event.revision)

        return await self._run(execute)

    async def resolve_event(
        self,
        principal: Principal,
        event_id: UUID,
        *,
        note: str | None,
        idempotency_key: str,
        expected_revision: int,
        correlation_id: str,
    ) -> app.AlertEventDetail:
        def execute() -> app.AlertEventDetail:
            with self._sessions() as session, session.begin():
                event, authorization = self._event(session, principal, event_id, write=True)
                version = session.get(AlertRuleVersionModel, event.rule_version_id)
                assert version is not None
                authorization = authorize_alert_request(
                    session,
                    principal,
                    account_id=event.account_id,
                    definition=rule_version(version).definition,
                    write=True,
                    now=self._now(),
                )
                if note is not None and (not isinstance(note, str) or len(note) > 1000):
                    fail(app.AlertServiceErrorCode.VALIDATION_FAILED)
                digest = command_digest(
                    "resolve_event", event.account_id, str(event.id), expected_revision, note
                )
                previous = self._command(
                    session,
                    authorization,
                    command="resolve_event",
                    idempotency_key=idempotency_key,
                    digest=digest,
                )
                if previous is not None:
                    return self._event_detail(session, authorization, event)
                self._revision(event.revision, expected_revision)
                if event.state == "resolved":
                    fail(app.AlertServiceErrorCode.INVALID_STATE_TRANSITION)
                # Resolution deliberately leaves the independent condition latch untouched.
                resolve_episode(
                    session,
                    event,
                    reason="manual",
                    at=self._now(),
                    principal_id=authorization.principal_id,
                    note=note,
                )
                self._record_command(
                    session,
                    authorization,
                    command="resolve_event",
                    key=idempotency_key,
                    digest=digest,
                    result_id=event.id,
                    revision=event.revision,
                    event_id=event.id,
                )
                audit_alert(
                    session,
                    authorization,
                    action="alert.event.resolved",
                    resource_id=event.id,
                    at=self._now(),
                )
                session.flush()
                authorization.check(session, now=self._now())
                return self._event_detail(session, authorization, event)

        return await self._run(execute)
