"""Durable admission progresses past denied or locked rules without losing their slots."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from trading212_persistence.alert_base import alert_owner_lock
from trading212_persistence.alert_job_store import PostgresAlertJobStore
from trading212_persistence.alert_models import (
    AlertEvaluationJobModel,
    AlertEvaluationModel,
    AlertInputSnapshotModel,
    AlertRuleModel,
)
from trading212_persistence.models import PrincipalModel
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_security.principals import Scope
from trading212_worker.alert_tasks import AlertExecutionState, execute_alert_message

from tests.integration.test_alert_postgres import KEY, AlertCase
from tests.integration.test_alert_postgres import alert_case as alert_case
from tests.integration.test_alert_postgres import alert_database as alert_database

pytestmark = pytest.mark.integration


def _restarted(case: AlertCase) -> PostgresAlertJobStore:
    return PostgresAlertJobStore(
        case.sessions,
        cursor_signing_key=KEY,
        clock=lambda: case.clock[0],
        capture_factory=lambda _session, _authorization: case.control,
    )


def _second_principal(case: AlertCase) -> AlertCase:
    identifier = uuid4()
    principal = replace(
        case.principal,
        principal_id=str(identifier),
        subject="admission-fairness-" + identifier.hex,
    )
    with case.sessions() as session, session.begin():
        session.add(
            PrincipalModel(
                id=identifier,
                owner_id=UUID(principal.owner_id),
                issuer=principal.issuer,
                subject=principal.subject,
                status="active",
                created_at=case.clock[0],
                last_authenticated_at=case.clock[0],
            )
        )
        session.flush()
        provision_principal_scopes(
            session, principal_id=identifier, scopes=principal.scopes, now=case.clock[0]
        )
    return replace(case, principal=principal)


def _order(case: AlertCase, rule_id: UUID) -> int | None:
    with case.sessions() as session:
        return session.scalar(
            select(AlertRuleModel.last_admission_sequence).where(AlertRuleModel.id == rule_id)
        )


def test_revoked_oldest_rule_rotates_at_limit_one_and_retains_original_slot_after_restart(
    alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = alert_case
        blocked_case = _second_principal(case)
        blocked = await blocked_case.active()
        original_slot = case.clock[0]
        case.clock[0] += timedelta(seconds=1)
        healthy = await case.active()
        tied_clock = case.clock[0]
        with case.sessions() as session, session.begin():
            provision_principal_scopes(
                session,
                principal_id=UUID(blocked_case.principal.principal_id),
                scopes=blocked_case.principal.scopes - {Scope.ALERTS_WRITE},
                now=tied_clock,
            )
            assert (
                session.scalar(
                    select(func.pg_get_serial_sequence("alert_rules", "last_admission_sequence"))
                )
                == "public.alert_admission_attempt_sequence"
            )

        denied = await _restarted(case).admit_due_evaluations(limit=1)
        assert denied.admitted == 0 and denied.deferred
        denied_order = _order(case, blocked.id)
        with case.sessions() as session:
            row = session.get(AlertRuleModel, blocked.id)
            assert row is not None
            assert row.next_scheduled_for == original_slot and row.revision == blocked.revision
            assert row.lifecycle_sequence == 2 and row.lifecycle == "active"
            assert session.scalar(select(func.count()).select_from(AlertEvaluationJobModel)) == 0
            assert session.scalar(select(func.count()).select_from(AlertInputSnapshotModel)) == 0
            assert session.scalar(select(func.count()).select_from(AlertEvaluationModel)) == 0
        assert case.control.calls == 0

        progressed = await _restarted(case).admit_due_evaluations(limit=1)
        assert progressed.admitted == 1 and progressed.deferred
        healthy_order = _order(case, healthy.id)
        assert denied_order is not None and healthy_order is not None
        assert healthy_order > denied_order
        assert case.control.calls == 1
        with case.sessions() as session:
            admitted = session.scalars(select(AlertEvaluationJobModel)).all()
            assert len(admitted) == 1 and admitted[0].rule_id == healthy.id
            assert admitted[0].scheduled_for == tied_clock

        with case.sessions() as session, session.begin():
            provision_principal_scopes(
                session,
                principal_id=UUID(blocked_case.principal.principal_id),
                scopes=blocked_case.principal.scopes,
                now=tied_clock,
            )
        restored = await _restarted(case).admit_due_evaluations(limit=1)
        assert restored.admitted == 1 and not restored.deferred
        final_order = _order(case, blocked.id)
        assert final_order is not None and final_order > healthy_order
        assert case.clock[0] == tied_clock and case.control.calls == 2
        with case.sessions() as session:
            rows = session.scalars(
                select(AlertEvaluationJobModel).order_by(AlertEvaluationJobModel.scheduled_for)
            ).all()
            assert len(rows) == 2
            assert rows[0].rule_id == blocked.id and rows[0].scheduled_for == original_slot
            assert rows[0].rule_version_id == blocked.latest_version.id
            messages = tuple(case.store._evaluation_message(row) for row in rows)
        for message in messages:
            assert (
                await execute_alert_message(
                    _restarted(case), message, consumer_id="admission-restored"
                )
                is AlertExecutionState.COMPLETED
            )
        assert (await _restarted(case).admit_due_evaluations(limit=1)).admitted == 0
        assert case.control.calls == 2

    asyncio.run(run())


def test_busy_owner_reservations_rotate_without_holding_rule_locks(
    alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = alert_case
        first = await case.active()
        case.clock[0] += timedelta(seconds=1)
        second = await case.active()
        with case.sessions() as locked, locked.begin():
            assert alert_owner_lock(locked, UUID(case.principal.owner_id))
            assert (await _restarted(case).admit_due_evaluations(limit=1)).admitted == 0
            first_order = _order(case, first.id)
            assert first_order is not None and _order(case, second.id) is None
            assert (await _restarted(case).admit_due_evaluations(limit=1)).admitted == 0
            second_order = _order(case, second.id)
            assert second_order is not None and second_order > first_order
            assert case.control.calls == 0
        assert (await _restarted(case).admit_due_evaluations(limit=1)).admitted == 1
        assert (await _restarted(case).admit_due_evaluations(limit=1)).admitted == 1
        assert case.control.calls == 2

    asyncio.run(run())


def test_locked_due_rule_is_skipped_before_the_admission_limit(
    alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = alert_case
        locked_rule = await case.active()
        original_slot = case.clock[0]
        case.clock[0] += timedelta(seconds=1)
        available = await case.active()
        with case.sessions() as locked, locked.begin():
            locked.execute(
                select(AlertRuleModel).where(AlertRuleModel.id == locked_rule.id).with_for_update()
            ).scalar_one()
            result = await _restarted(case).admit_due_evaluations(limit=1)
            assert result.admitted == 1 and result.deferred
            assert _order(case, locked_rule.id) is None
            assert _order(case, available.id) is not None
        assert (await _restarted(case).admit_due_evaluations(limit=1)).admitted == 1
        with case.sessions() as session:
            row = session.scalar(
                select(AlertEvaluationJobModel).where(
                    AlertEvaluationJobModel.rule_id == locked_rule.id
                )
            )
            assert row is not None and row.scheduled_for == original_slot
        assert case.control.calls == 2

    asyncio.run(run())


def test_concurrent_admission_reservations_do_not_duplicate_or_invent_future_slots(
    alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = alert_case
        first, second = await case.active(), await case.active()
        original_slot = case.clock[0]
        results = await asyncio.gather(
            _restarted(case).admit_due_evaluations(limit=1),
            _restarted(case).admit_due_evaluations(limit=1),
        )
        assert all(result.admitted <= 1 for result in results)
        # One owner can be busy in a concurrent caller; ordinary subsequent
        # bounded cycles recover that reservation without moving its due slot.
        follow_up = await _restarted(case).admit_due_evaluations(limit=1)
        final = await _restarted(case).admit_due_evaluations(limit=1)
        assert sum(result.admitted for result in results) + follow_up.admitted + final.admitted == 2
        with case.sessions() as session:
            rows = session.scalars(
                select(AlertEvaluationJobModel).where(
                    AlertEvaluationJobModel.rule_id.in_((first.id, second.id))
                )
            ).all()
            assert {row.rule_id for row in rows} == {first.id, second.id}
            assert len(rows) == 2 and {row.scheduled_for for row in rows} == {original_slot}
            assert len({row.input_id for row in rows}) == 2
        assert case.clock[0] == original_slot and case.control.calls == 2
        assert (await _restarted(case).admit_due_evaluations(limit=1)).admitted == 0

    asyncio.run(run())
