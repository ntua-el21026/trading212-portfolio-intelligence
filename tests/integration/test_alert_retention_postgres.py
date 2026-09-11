"""Natural payload TTL and owner termination use actual guarded PostgreSQL transitions."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from trading212_application import alerts as app
from trading212_persistence.alert_models import (
    AlertEvaluationJobModel,
    AlertEvaluationModel,
    AlertEventModel,
    AlertInputSnapshotModel,
    AlertRetentionWorkModel,
)
from trading212_persistence.alert_retention import expire_alert_payloads, purge_alert_input
from trading212_persistence.models import AuditEventModel, BrokerAccountModel, PrincipalModel
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_security.principals import Scope
from trading212_worker.alert_tasks import AlertExecutionState, execute_alert_message

from tests.integration.test_alert_postgres import AlertCase
from tests.integration.test_alert_postgres import alert_case as alert_case
from tests.integration.test_alert_postgres import alert_database as alert_database

pytestmark = pytest.mark.integration


def _database_now(case: AlertCase) -> datetime:
    with case.sessions() as session:
        value = session.scalar(select(func.clock_timestamp()))
        assert isinstance(value, datetime)
        return value.astimezone(UTC)


def test_natural_alert_ttl_denies_before_bounded_resumable_payload_cleanup(
    alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = alert_case
        expiry = _database_now(case) + timedelta(seconds=45)
        created = expiry - timedelta(days=90)
        identifier = uuid4()
        case.principal = replace(
            case.principal,
            principal_id=str(identifier),
            subject=f"alert-ttl-{identifier}",
            authenticated_at=created - timedelta(seconds=1),
            expires_at=expiry + timedelta(hours=1),
            scopes=frozenset(Scope),
        )
        with case.sessions() as session, session.begin():
            session.add(
                PrincipalModel(
                    id=identifier,
                    owner_id=UUID(case.principal.owner_id),
                    issuer=case.principal.issuer,
                    subject=case.principal.subject,
                    status="active",
                    created_at=created - timedelta(seconds=1),
                    last_authenticated_at=created - timedelta(seconds=1),
                )
            )
            session.flush()
            provision_principal_scopes(
                session,
                principal_id=identifier,
                scopes=case.principal.scopes,
                now=created - timedelta(seconds=1),
            )
        case.clock[0] = created
        rule = await case.active()
        first = await case.admit(rule.id)
        # A second ordinary job proves limit=1 resumption without generating101 payloads.
        second_rule = await case.active()
        second = await case.admit(second_rule.id)
        case.clock[0] = _database_now(case)
        for message in (first, second):
            assert (
                await execute_alert_message(case.store, message, consumer_id="ttl")
                is AlertExecutionState.COMPLETED
            )
        with case.sessions() as session:
            for message in (first, second):
                saved = session.get(AlertInputSnapshotModel, message.capture_id)
                assert (
                    saved is not None and saved.created_at == created and saved.expires_at == expiry
                )
        # Application access expires at the captured deadline even before physical cleanup.
        case.clock[0] = expiry + timedelta(seconds=1)
        detail = await case.service.get_rule(
            case.principal, rule.id, query=app.AlertRuleDetailQuery()
        )
        assert detail.evaluation_page.items[0].reproducibility is app.AlertReproducibility.EXPIRED
        assert detail.evaluation_page.items[0].result is None
        assert detail.evaluation_page.items[0].definition is None
        assert detail.evaluation_page.items[0].source_references == ()
        if _database_now(case) < expiry:
            with pytest.raises(DBAPIError), case.sessions() as session, session.begin():
                expire_alert_payloads(session, at=case.clock[0], limit=1)
        for _ in range(60):
            if _database_now(case) > expiry:
                break
            await asyncio.sleep(1)
        else:
            pytest.fail("PostgreSQL clock did not cross the real TTL deadline.")
        case.clock[0] = _database_now(case)
        for expected in (1, 2):
            with case.sessions() as session, session.begin():
                budget = SourcePurgeBudget(captures=1)
                assert expire_alert_payloads(session, at=case.clock[0], limit=1, budget=budget) == 1
                assert budget.captures == 0 and budget.rows_removed < 4096
            with case.sessions() as session:
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(AlertInputSnapshotModel)
                        .where(
                            AlertInputSnapshotModel.id.in_((first.capture_id, second.capture_id)),
                            AlertInputSnapshotModel.purged_at.is_not(None),
                        )
                    )
                    == expected
                )
        with case.sessions() as session, session.begin():
            assert expire_alert_payloads(session, at=case.clock[0], limit=1) == 0
            with pytest.raises(ValueError):
                expire_alert_payloads(session, at=case.clock[0], limit=101)
        with case.sessions() as session:
            for message in (first, second):
                saved = session.get(AlertInputSnapshotModel, message.capture_id)
                result = session.scalar(
                    select(AlertEvaluationModel).where(
                        AlertEvaluationModel.job_id == message.job_id
                    )
                )
                assert (
                    saved is not None
                    and saved.payload is None
                    and saved.input_digest == message.input_digest
                )
                assert (
                    result is not None and result.payload is None and result.purged_at is not None
                )
                events = session.scalars(
                    select(AlertEventModel).where(AlertEventModel.evaluation_id == result.id)
                ).all()
                assert events and all(
                    item.payload is None and item.purged_at is not None for item in events
                )
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(AlertRetentionWorkModel)
                        .where(
                            AlertRetentionWorkModel.input_id == message.capture_id,
                            AlertRetentionWorkModel.reason == "ttl",
                            AlertRetentionWorkModel.completed_at.is_not(None),
                        )
                    )
                    == 1
                )
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(AuditEventModel)
                        .where(
                            AuditEventModel.action == "alert.input.purged",
                            AuditEventModel.resource_id == str(message.capture_id),
                        )
                    )
                    == 1
                )
                job = session.get(AlertEvaluationJobModel, message.job_id)
                assert job is not None and job.state == "succeeded"

    asyncio.run(run())


def test_active_owner_purge_is_rejected_and_termination_is_distinct_from_archive(
    alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = alert_case
        rule = await case.active()
        message = await case.admit(rule.id)
        assert (
            await execute_alert_message(case.store, message, consumer_id="owner-retention")
            is AlertExecutionState.COMPLETED
        )
        await case.service.archive_rule(
            case.principal,
            rule.id,
            idempotency_key=uuid4().hex,
            expected_revision=rule.revision,
            correlation_id="archive",
        )
        with pytest.raises(DBAPIError), case.sessions() as session, session.begin():
            purge_alert_input(
                session,
                owner=UUID(case.principal.owner_id),
                input_id=message.capture_id,
                reason="owner",
                at=case.clock[0],
                budget=SourcePurgeBudget(),
            )
        with case.sessions() as session:
            before = session.get(AlertInputSnapshotModel, message.capture_id)
            assert before is not None and before.payload is not None
        try:
            with case.sessions() as session, session.begin():
                session.execute(
                    update(BrokerAccountModel)
                    .where(BrokerAccountModel.id == case.account_id)
                    .values(status="inactive")
                )
                assert purge_alert_input(
                    session,
                    owner=UUID(case.principal.owner_id),
                    input_id=message.capture_id,
                    reason="owner",
                    at=case.clock[0],
                    budget=SourcePurgeBudget(),
                )
            with case.sessions() as session:
                row = session.get(AlertInputSnapshotModel, message.capture_id)
                assert row is not None and row.payload is None
                work = session.scalar(
                    select(AlertRetentionWorkModel).where(
                        AlertRetentionWorkModel.input_id == message.capture_id
                    )
                )
                assert work is not None and work.reason == "owner" and work.completed_at is not None
        finally:
            with case.sessions() as session, session.begin():
                session.execute(
                    update(BrokerAccountModel)
                    .where(BrokerAccountModel.id == case.account_id)
                    .values(status="active")
                )

    asyncio.run(run())
