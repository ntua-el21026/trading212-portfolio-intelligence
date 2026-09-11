"""S28: actual target drift keeps one durable result and event under duplicate delivery."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.planning import calculate_drift
from trading212_application import alerts as app
from trading212_domain import alerts as d
from trading212_domain import build_synthetic_identity
from trading212_domain import planning as p
from trading212_domain.alert_serialization import decode_alert_input, decode_alert_result
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence.alert_job_store import PostgresAlertJobStore
from trading212_persistence.alert_models import (
    AlertEvaluationJobModel,
    AlertEvaluationModel,
    AlertEventModel,
    AlertInputSnapshotModel,
    InAppNotificationModel,
)
from trading212_persistence.alert_service import PostgresAlertService
from trading212_persistence.models import CalculationRunModel, PortfolioSnapshotModel
from trading212_persistence.planning_inputs import capture_input, digest
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_persistence.target_models import TargetVersionModel, VirtualPortfolioModel
from trading212_persistence.target_service import PostgresTargetService
from trading212_security.principals import Principal, Scope
from trading212_worker.alert_tasks import AlertExecutionState, execute_alert_message

from tests.integration.test_alert_postgres import KEY
from tests.integration.test_alert_postgres import alert_database as alert_database

pytestmark = pytest.mark.integration


def test_actual_target_drift_slot_deduplicates_concurrent_and_restarted_consumers(
    alert_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    async def run() -> None:
        _, sessions = alert_database
        identity = build_synthetic_identity()
        # The genuine seeded sources already exist. Only the application clock is
        # held at this actual instant so activation and admission share one slot;
        # no source, target, calculation, or PostgreSQL timestamp is rewritten.
        at = datetime.now(UTC)
        scopes = frozenset(
            {
                Scope.PORTFOLIO_READ,
                Scope.ANALYTICS_READ,
                Scope.TARGETS_READ,
                Scope.ALERTS_READ,
                Scope.ALERTS_WRITE,
            }
        )
        principal = Principal(
            str(identity.principal.id),
            str(identity.owner.id),
            "local.synthetic",
            "synthetic-owner",
            scopes,
            at - timedelta(seconds=1),
            at + timedelta(hours=1),
        )
        with sessions() as session, session.begin():
            provision_principal_scopes(
                session, principal_id=identity.principal.id, scopes=scopes, now=at
            )
            target = session.scalar(
                select(TargetVersionModel)
                .join(VirtualPortfolioModel)
                .where(
                    TargetVersionModel.owner_id == identity.owner.id,
                    VirtualPortfolioModel.broker_account_id == identity.account.id,
                    TargetVersionModel.published_at.is_not(None),
                )
                .order_by(TargetVersionModel.published_at.desc(), TargetVersionModel.id)
                .limit(1)
            )
            snapshot = session.scalar(
                select(PortfolioSnapshotModel)
                .where(PortfolioSnapshotModel.broker_account_id == identity.account.id)
                .order_by(PortfolioSnapshotModel.valuation_at.desc(), PortfolioSnapshotModel.id)
                .limit(1)
            )
            assert target is not None and snapshot is not None
            assert target.published_at is not None and target.content_digest is not None
            calculation = session.get_one(CalculationRunModel, snapshot.calculation_run_id)
            assert (
                max(
                    target.created_at,
                    target.published_at,
                    target.effective_at,
                    snapshot.created_at,
                    snapshot.valuation_at,
                    snapshot.source_cutoff_at,
                    calculation.created_at,
                    calculation.calculated_at,
                )
                <= at
            )
            original = capture_input(
                session,
                owner=identity.owner.id,
                account=identity.account.id,
                portfolio_id=target.virtual_portfolio_id,
                target_id=target.id,
                snapshot_id=snapshot.id,
                options=p.PlanningOptions(
                    Money(Decimal(0), CurrencyCode(snapshot.reporting_currency)),
                    p.PlanningMode.GLOBAL,
                    p.CoveragePolicy.ALLOW_DEGRADED,
                ),
                targets=PostgresTargetService(sessions=sessions, cursor_signing_key=KEY),
            )
            canonical = calculate_drift(original)
            frontier = tuple(
                row
                for row in canonical.rows
                if row.depth == 1 or row.kind in {"cash", "unclassified"}
            )
            assert frontier and all(row.signed_drift is not None for row in frontier)
            with localcontext() as context:
                context.prec = 80
                expected_drift = (
                    sum(
                        (
                            row.signed_drift.copy_abs()
                            for row in frontier
                            if row.signed_drift is not None
                        ),
                        Decimal(0),
                    )
                    / 2
                )
            assert expected_drift >= 0
            target_id, target_digest = target.id, target.content_digest
            snapshot_id, snapshot_digest = snapshot.id, calculation.output_fingerprint
            planning_digest = digest(original)

        service = PostgresAlertService(sessions, cursor_signing_key=KEY, clock=lambda: at)

        def restarted() -> PostgresAlertJobStore:
            # Default CanonicalAlertCapture, including on initial admission; no
            # controlled scalar, capture_factory, or persisted result injection.
            return PostgresAlertJobStore(sessions, cursor_signing_key=KEY, clock=lambda: at)

        definition = d.AlertRuleDefinition(
            name="Canonical target drift duplicate delivery",
            predicate=d.AlertPredicate(
                family=d.AlertFamily.TARGET_DRIFT,
                metric=d.AlertMetric.PORTFOLIO_L1_DRIFT,
                comparison=d.AlertComparison.GTE,
                threshold=Decimal(0),
                target_version_id=target_id,
                frontier_depth=1,
            ),
            schedule=d.AlertIntervalSchedule(anchor_at=at),
            quality_policy=d.AlertQualityPolicy.ALLOW_DEGRADED,
        )
        rule = await service.create_rule(
            principal,
            app.CreateAlertRuleCommand(account_id=identity.account.id, definition=definition),
            idempotency_key="s28-real-drift-create",
            correlation_id="s28-real-drift",
        )
        active = await service.activate_rule(
            principal,
            rule.id,
            rule.latest_version.id,
            idempotency_key="s28-real-drift-activate",
            expected_revision=rule.revision,
            correlation_id="s28-real-drift",
        )
        store = restarted()
        assert (await store.admit_due_evaluations(limit=1)).admitted == 1
        assert (await restarted().admit_due_evaluations(limit=1)).admitted == 0
        (dispatch,) = await store.claim_evaluation_dispatches(dispatcher_id="s28-publish", limit=1)
        message = dispatch.message
        assert message.rule_version_id == active.latest_version.id
        assert message.scheduled_for == at
        assert await store.acknowledge_evaluation_dispatch(dispatch)
        with sessions() as session:
            retained = session.get_one(AlertInputSnapshotModel, message.capture_id)
            original_payload = retained.payload
            assert original_payload is not None and retained.sealed_at is not None
            assert hashlib.sha256(original_payload).hexdigest() == message.input_digest
            captured = decode_alert_input(original_payload)
            assert captured.version.definition == definition
            assert captured.scheduled_for == captured.source_cutoff_at == at
            assert isinstance(captured.payload, d.AlertThresholdInput)
            assert captured.payload.observation.observed.value == expected_drift
            assert captured.source_references
            assert all(
                max(reference.effective_at, reference.first_observed_at) <= at
                for reference in captured.source_references
            )
            for family, role, subject_id, content_digest in (
                (
                    d.AlertCanonicalFamily.TARGET,
                    d.AlertInputRole.TARGET_VERSION,
                    target_id,
                    target_digest,
                ),
                (
                    d.AlertCanonicalFamily.VALUATION,
                    d.AlertInputRole.SNAPSHOT,
                    snapshot_id,
                    snapshot_digest,
                ),
                (
                    d.AlertCanonicalFamily.PLANNING,
                    d.AlertInputRole.INPUT,
                    snapshot_id,
                    planning_digest,
                ),
            ):
                assert any(
                    pin.family is family
                    and pin.role is role
                    and pin.subject_id == subject_id
                    and pin.content_digest == content_digest
                    for pin in captured.canonical_bindings
                )

        outcomes = await asyncio.gather(
            execute_alert_message(restarted(), message, consumer_id="s28-consumer-one"),
            execute_alert_message(restarted(), message, consumer_id="s28-consumer-two"),
        )
        assert outcomes.count(AlertExecutionState.COMPLETED) == 1
        assert outcomes.count(AlertExecutionState.NOT_CLAIMED) == 1
        assert (
            await execute_alert_message(restarted(), message, consumer_id="s28-after-restart")
            is AlertExecutionState.NOT_CLAIMED
        )
        assert (await restarted().admit_due_evaluations(limit=1)).admitted == 0
        with sessions() as session:
            for model in (
                AlertInputSnapshotModel,
                AlertEvaluationJobModel,
                AlertEvaluationModel,
                AlertEventModel,
                InAppNotificationModel,
            ):
                assert session.scalar(select(func.count()).select_from(model)) == 1
            job = session.get_one(AlertEvaluationJobModel, message.job_id)
            assert job.state == "succeeded" and job.consumer_attempts == 1 and job.fence == 1
            retained = session.get_one(AlertInputSnapshotModel, message.capture_id)
            assert (
                retained.payload == original_payload
                and retained.input_digest == message.input_digest
            )
            evaluation = session.scalar(
                select(AlertEvaluationModel).where(AlertEvaluationModel.job_id == job.id)
            )
            assert evaluation is not None and evaluation.payload is not None
            assert evaluation.input_id == message.capture_id
            assert evaluation.input_digest == message.input_digest
            assert hashlib.sha256(evaluation.payload).hexdigest() == evaluation.content_digest
            result = decode_alert_result(evaluation.payload)
            assert result.outcome is d.AlertEvaluationOutcome.MATCHED and result.decision is True
            assert result.observation is not None and result.observation.value == expected_drift
            assert result.contexts == captured.contexts
            event = session.scalar(select(AlertEventModel))
            assert event is not None and event.evaluation_id == evaluation.id
            assert event.rule_version_id == active.latest_version.id
            assert event.family == d.AlertFamily.TARGET_DRIFT.value and event.episode_ordinal == 1
            intent = session.scalar(select(InAppNotificationModel))
            assert intent is not None and intent.event_id == event.id

    asyncio.run(run())
