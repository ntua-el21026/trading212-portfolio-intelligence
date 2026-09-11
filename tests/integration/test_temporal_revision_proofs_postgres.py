"""Actual ingestion, temporal proof capture and durable late-bridge alert replay."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics._historical_core import HistoricalEngine
from trading212_analytics.alerts import evaluate_alert
from trading212_application import alerts as alerts_app
from trading212_application import ingestion
from trading212_domain import alerts as a
from trading212_domain import historical as h
from trading212_domain.alert_serialization import decode_alert_input, decode_alert_result
from trading212_domain.historical_serialization import historical_value_from_json
from trading212_domain.reports import ReportSourceKind
from trading212_domain.serialization import canonical_json
from trading212_persistence.activity_revision_store import PostgresActivityRevisionStore
from trading212_persistence.alert_authorization import authorize_alert_request
from trading212_persistence.alert_capture import CanonicalAlertCapture
from trading212_persistence.alert_job_store import PostgresAlertJobStore
from trading212_persistence.alert_models import (
    AlertEvaluationJobModel,
    AlertEvaluationModel,
    AlertEventModel,
    AlertInputSnapshotModel,
    InAppNotificationModel,
)
from trading212_persistence.alert_service import PostgresAlertService
from trading212_persistence.historical_normalization import normalize_record
from trading212_persistence.historical_store import PostgresHistoricalStore
from trading212_persistence.models import SourceRecordModel, SourceRecordOccurrenceModel
from trading212_persistence.planning_inputs import digest
from trading212_worker.alert_tasks import AlertExecutionState, execute_alert_message
from trading212_worker.historical_seed import CURSOR_KEY

from tests.integration.report_history_cases import HistoryReportCase, history_report_case
from tests.integration.test_activity_revision_capture_postgres import DAY, ingest, request
from tests.integration.test_activity_revisions_postgres import registration
from tests.integration.test_alert_capture_matrix_postgres import Matrix
from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_historical_seed import seeded_history as seeded_history
from tests.unit.analytics.alert_factories import predicate

pytestmark = pytest.mark.integration


async def observe(
    case: HistoryReportCase, amount: str, key: str, *, paid_at: datetime | None = None
) -> UUID:
    paid_at = paid_at or datetime.combine(DAY, datetime.min.time(), UTC)
    return await ingest(
        case,
        ingestion.IngestionCapability.DIVIDENDS,
        ingestion.SourceRecord(
            provider_record_id=key,
            source_timestamp=paid_at,
            observed_at=datetime.now(UTC),
            payload={
                "reference": key,
                "paidOn": paid_at,
                "amount": Decimal(amount),
                "currency": "EUR",
            },
            schema_version="temporal-revision-regression-v1",
        ),
    )


def raw_facts(case: HistoryReportCase, identifiers: tuple[UUID, ...]) -> tuple[object, ...]:
    with case.sessions() as session:
        return tuple(
            (
                row.id,
                row.observed_at,
                row.created_at,
                row.source_updated_at,
                row.payload_fingerprint,
                canonical_json(row.sanitized_payload),
            )
            for identifier in identifiers
            for row in (session.get_one(SourceRecordModel, identifier),)
        )


@pytest.mark.parametrize("correction_to_past", (True, False))
def test_actual_future_economic_proof_parent_and_winner_are_scoped_correctly(
    seeded_history: tuple[sessionmaker[Session], dict[str, str]],
    correction_to_past: bool,
) -> None:
    async def run() -> None:
        case = history_report_case(*seeded_history)
        matrix = Matrix(case.sessions, case.principal, case.account_id, CURSOR_KEY)
        version = await matrix.activate(predicate(a.AlertMetric.POSITIVE_DIVIDEND))
        schedule = version.definition.schedule
        assert isinstance(schedule, a.AlertIntervalSchedule)
        future = schedule.anchor_at + timedelta(seconds=600)
        past = datetime.combine(DAY, datetime.min.time(), UTC)
        key = f"future-date-proof-{correction_to_past}"
        old = await observe(case, "2", key, paid_at=future if correction_to_past else past)
        new = await observe(case, "3", key, paid_at=past if correction_to_past else future)
        unrelated = await observe(case, "5", f"unrelated-{key}", paid_at=future)
        originals = raw_facts(case, (old, new, unrelated))
        evidence = await PostgresActivityRevisionStore(case.sessions).register_activity_revision(
            case.principal,
            case.account_id,
            registration(new, old),
            idempotency_key=uuid4().hex,
            correlation_id="future-economic-proof",
        )
        captured, result = matrix.capture(version)
        assert isinstance(captured.payload, a.AlertEventBatchInput)
        winners = [item for item in captured.payload.events if item.revision_id in {old, new}]
        if correction_to_past:
            assert result.outcome is a.AlertEvaluationOutcome.MATCHED and result.decision is True
            assert len(winners) == 1 and winners[0].revision_id == new
            assert winners[0].correction_of == old
            assert winners[0].first_eligible_at == evidence.first_observed_at
        else:
            # This genuine ingestion has no complete current-window coverage.
            # An empty batch must retain that truth instead of asserting a clear.
            assert result.outcome is a.AlertEvaluationOutcome.UNAVAILABLE
            assert result.reason is a.AlertReason.INCOMPLETE_COVERAGE
            assert winners == [], (
                "A correction to a future payment must suppress the superseded past value"
            )
        assert all(
            item.economic_at <= captured.source_cutoff_at for item in captured.payload.events
        )
        assert all(
            max(ref.effective_at, ref.first_observed_at) <= captured.source_cutoff_at
            for ref in captured.source_references
        )
        future_id = old if correction_to_past else new
        with case.sessions() as session:
            future_raw = session.get_one(SourceRecordModel, future_id)
            future_observed_at = future_raw.observed_at
            fingerprint = future_raw.payload_fingerprint
            occurrence = session.scalars(
                select(SourceRecordOccurrenceModel)
                .where(
                    SourceRecordOccurrenceModel.source_record_id == future_id,
                )
                .order_by(SourceRecordOccurrenceModel.observed_at, SourceRecordOccurrenceModel.id)
            ).first()
            normalized = normalize_record(future_raw, occurrence, ())
            assert normalized is not None
            normalized = replace(
                normalized,
                identity=replace(
                    normalized.identity,
                    first_observed_at=max(future_raw.observed_at, future_raw.created_at),
                ),
            )
            assert normalized.identity.economic_at == future
        assert any(
            ref.kind is ReportSourceKind.BROKER_SOURCE_RECORD
            and ref.subject_id == future_id
            and ref.effective_at == future_observed_at
            and ref.content_digest == fingerprint
            for ref in captured.source_references
        )
        assert any(
            binding.subject_id == future_id and binding.content_digest == digest(normalized)
            for binding in captured.canonical_bindings
        )
        assert any(
            ref.kind is ReportSourceKind.ACTIVITY_REVISION_EVIDENCE
            and ref.subject_id == evidence.registration.id
            and ref.content_digest == evidence.content_digest
            for ref in captured.source_references
        )
        assert all(ref.subject_id != unrelated for ref in captured.source_references)
        historical = await PostgresHistoricalStore(
            case.sessions,
            cursor_signing_key=CURSOR_KEY,
        ).capture(case.principal, str(case.account_id), request=request(case, datetime.now(UTC)))
        historical_winners, ambiguous = HistoricalEngine(historical.input).events(
            evidence.first_observed_at
        )
        assert not ambiguous
        actual_ids = {item.identity.source_record_id for item in historical_winners}
        if correction_to_past:
            assert str(new) in actual_ids and str(old) not in actual_ids
        else:
            assert not actual_ids & {str(old), str(new)}
        clock = [datetime.now(UTC)]
        if not correction_to_past:
            # Advance only the actual service clock through aligned durable slots.
            # No further ingestion or proof is registered when payment becomes due.
            def restarted() -> PostgresAlertJobStore:
                return PostgresAlertJobStore(
                    case.sessions,
                    cursor_signing_key=CURSOR_KEY,
                    clock=lambda: clock[0],
                )

            for scheduled in (
                future - timedelta(seconds=300),
                future,
                future + timedelta(seconds=300),
            ):
                clock[0] = scheduled
                assert (await restarted().admit_due_evaluations(limit=1)).admitted == 1
                (dispatch,) = await restarted().claim_evaluation_dispatches(
                    dispatcher_id="future-payment-slot",
                    limit=1,
                )
                message = dispatch.message
                assert message.rule_version_id == version.id and message.scheduled_for == scheduled
                assert await restarted().acknowledge_evaluation_dispatch(dispatch)
                with case.sessions() as session:
                    retained = session.get_one(AlertInputSnapshotModel, message.capture_id)
                    assert retained.payload is not None
                    slot = decode_alert_input(retained.payload)
                assert isinstance(slot.payload, a.AlertEventBatchInput)
                due = [item for item in slot.payload.events if item.revision_id in {old, new}]
                if scheduled == future:
                    assert len(due) == 1 and due[0].revision_id == new
                    assert due[0].first_eligible_at == due[0].economic_at == future
                    assert due[0].correction_of == old
                else:
                    assert due == []
                assert (
                    await execute_alert_message(
                        restarted(),
                        message,
                        consumer_id="future-payment-slot",
                    )
                    is AlertExecutionState.COMPLETED
                )
                assert (
                    await execute_alert_message(
                        restarted(),
                        message,
                        consumer_id="future-payment-duplicate",
                    )
                    is AlertExecutionState.NOT_CLAIMED
                )
                with case.sessions() as session:
                    assert session.scalar(
                        select(func.count())
                        .select_from(AlertEventModel)
                        .where(
                            AlertEventModel.rule_id == version.rule_id,
                        )
                    ) == (0 if scheduled < future else 1)
        assert raw_facts(case, (old, new, unrelated)) == originals
        service = PostgresAlertService(
            case.sessions,
            cursor_signing_key=CURSOR_KEY,
            clock=lambda: clock[0],
        )
        detail = await service.get_rule(
            case.principal, version.rule_id, query=alerts_app.AlertRuleDetailQuery()
        )
        await service.pause_rule(
            case.principal,
            version.rule_id,
            expected_revision=detail.revision,
            idempotency_key=uuid4().hex,
            correlation_id="future-proof-test-complete",
        )

    asyncio.run(run())


def test_one_actual_postproof_capture_preserves_earlier_pit_ambiguity(
    seeded_history: tuple[sessionmaker[Session], dict[str, str]],
) -> None:
    async def run() -> None:
        case = history_report_case(*seeded_history)
        store = PostgresHistoricalStore(case.sessions, cursor_signing_key=CURSOR_KEY)
        old = await observe(case, "2", "single-capture-pit")
        new = await observe(case, "3", "single-capture-pit")
        original_facts = raw_facts(case, (old, new))
        earlier_at = datetime.now(UTC)
        selection = request(case, earlier_at)
        selection = replace(
            selection,
            window=replace(
                selection.window,
                knowledge_policy=h.KnowledgePolicy.POINT_IN_TIME,
            ),
        )
        original = await store.capture(case.principal, str(case.account_id), request=selection)
        original_bytes = canonical_json(original.input)
        assert HistoricalEngine(original.input).events(earlier_at)[1]
        evidence = await PostgresActivityRevisionStore(case.sessions).register_activity_revision(
            case.principal,
            case.account_id,
            registration(new, old),
            idempotency_key=uuid4().hex,
            correlation_id="single-capture-pit-proof",
        )
        later = await store.capture(
            case.principal,
            str(case.account_id),
            request=replace(
                selection,
                window=replace(selection.window, source_cutoff_at=datetime.now(UTC)),
            ),
        )
        later_bytes = canonical_json(later.input)
        actual = historical_value_from_json(later_bytes, h.HistoricalInput)
        engine = HistoricalEngine(actual)
        # Intended red: the old overlay hides raw B at this earlier valuation.
        assert engine.events(earlier_at)[1], (
            "A/B must remain ambiguous inside one later PIT capture"
        )
        winners, ambiguous = engine.events(evidence.first_observed_at)
        assert not ambiguous
        winner = next(item for item in winners if item.identity.source_record_id == str(new))
        assert isinstance(winner, h.HistoricalDividend) and winner.net.amount == Decimal("3")
        assert winner.correction_of == str(old)
        earlier_raw = {
            item.identity.source_record_id: item for item in original.input.event_candidates
        }
        later_raw = {item.identity.source_record_id: item for item in actual.event_candidates}
        assert later_raw[str(new)] == earlier_raw[str(new)]
        assert later_raw[str(old)] == earlier_raw[str(old)]
        assert any(
            ref.kind == "activity_revision_evidence"
            and ref.id == str(evidence.registration.id)
            and ref.parent_ids == (str(new), str(old))
            and ref.semantic_digest == evidence.content_digest
            for ref in actual.sources
        )
        replay = await store.capture(case.principal, str(case.account_id), request=selection)
        assert replay.id == original.id and canonical_json(replay.input) == original_bytes
        assert canonical_json(actual) == later_bytes
        assert raw_facts(case, (old, new)) == original_facts

    asyncio.run(run())


def test_actual_late_bridge_winner_survives_durable_same_evaluation_retry(
    seeded_history: tuple[sessionmaker[Session], dict[str, str]],
) -> None:
    async def run() -> None:
        case = history_report_case(*seeded_history)
        old = await observe(case, "2", "late-bridge-payment")
        middle = await observe(case, "3", "late-bridge-payment")
        new = await observe(case, "4", "late-bridge-payment")
        original_facts = raw_facts(case, (old, middle, new))
        activated_at = datetime.now(UTC)
        first_proof_at = activated_at + timedelta(seconds=1)
        bridge_at = first_proof_at + timedelta(seconds=301)
        now = [activated_at]
        # Only the injectable server clock advances. Broker facts, ingestion and
        # database source timestamps remain their genuine persisted values.
        service = PostgresAlertService(
            case.sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: now[0]
        )
        rule = await service.create_rule(
            case.principal,
            alerts_app.CreateAlertRuleCommand(
                account_id=case.account_id,
                definition=a.AlertRuleDefinition(
                    name="Late bridge dividend durable replay",
                    predicate=predicate(a.AlertMetric.POSITIVE_DIVIDEND),
                    schedule=a.AlertIntervalSchedule(anchor_at=bridge_at),
                    quality_policy=a.AlertQualityPolicy.ALLOW_DEGRADED,
                ),
            ),
            idempotency_key=uuid4().hex,
            correlation_id="late-bridge-create",
        )
        active = await service.activate_rule(
            case.principal,
            rule.id,
            rule.latest_version.id,
            expected_revision=rule.revision,
            idempotency_key=uuid4().hex,
            correlation_id="late-bridge-activate",
        )
        version = active.active_version
        assert version is not None
        revisions = PostgresActivityRevisionStore(case.sessions, clock=lambda: now[0])
        now[0] = first_proof_at
        tail = await revisions.register_activity_revision(
            case.principal,
            case.account_id,
            registration(new, middle),
            idempotency_key=uuid4().hex,
            correlation_id="late-bridge-tail",
        )
        with case.sessions() as session, session.begin():
            authorization = authorize_alert_request(
                session,
                case.principal,
                account_id=case.account_id,
                now=now[0],
                write=True,
                definition=version.definition,
            )
            before = CanonicalAlertCapture(
                session,
                authorization,
                now=now[0],
                cursor_signing_key=CURSOR_KEY,
                sessions=case.sessions,
            ).capture_evaluation(version, now[0], a.AlertExecutionIntent.LIVE)
        assert evaluate_alert(before).reason is a.AlertReason.AMBIGUOUS_SOURCE
        assert any(
            ref.kind is ReportSourceKind.ACTIVITY_REVISION_EVIDENCE
            and ref.subject_id == tail.registration.id
            and ref.content_digest == tail.content_digest
            for ref in before.source_references
        )
        # Consume the genuine first aligned slot (T1+1s), which is still ambiguous.
        # The following aligned slot is exactly the late bridge at T1+301s.
        now[0] = first_proof_at + timedelta(seconds=1)
        pre_jobs = PostgresAlertJobStore(
            case.sessions,
            cursor_signing_key=CURSOR_KEY,
            clock=lambda: now[0],
        )
        assert (await pre_jobs.admit_due_evaluations(limit=1)).admitted == 1
        (pre_dispatch,) = await pre_jobs.claim_evaluation_dispatches(
            dispatcher_id="bridge-preproof-slot",
            limit=1,
        )
        assert pre_dispatch.message.scheduled_for == now[0]
        assert await pre_jobs.acknowledge_evaluation_dispatch(pre_dispatch)
        assert (
            await execute_alert_message(
                pre_jobs,
                pre_dispatch.message,
                consumer_id="bridge-preproof-slot",
            )
            is AlertExecutionState.COMPLETED
        )
        with case.sessions() as session:
            pre_result = session.scalars(
                select(AlertEvaluationModel).where(
                    AlertEvaluationModel.job_id == pre_dispatch.message.job_id,
                )
            ).one()
            assert pre_result.payload is not None
            assert decode_alert_result(pre_result.payload).reason is a.AlertReason.AMBIGUOUS_SOURCE
        now[0] = bridge_at
        bridge = await revisions.register_activity_revision(
            case.principal,
            case.account_id,
            registration(middle, old),
            idempotency_key=uuid4().hex,
            correlation_id="late-bridge-connect",
        )

        def restarted() -> PostgresAlertJobStore:
            return PostgresAlertJobStore(
                case.sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: now[0]
            )

        jobs = restarted()
        assert (await jobs.admit_due_evaluations(limit=1)).admitted == 1
        (dispatch,) = await jobs.claim_evaluation_dispatches(
            dispatcher_id="bridge-dispatch", limit=1
        )
        message = dispatch.message
        assert message.rule_version_id == version.id and message.scheduled_for == bridge_at
        assert await jobs.acknowledge_evaluation_dispatch(dispatch)
        with case.sessions() as session:
            retained = session.get_one(AlertInputSnapshotModel, message.capture_id)
            original_payload = retained.payload
            assert original_payload is not None and retained.sealed_at is not None
            captured = decode_alert_input(original_payload)
        assert isinstance(captured.payload, a.AlertEventBatchInput)
        assert tail.first_observed_at < captured.observation_window.start_at
        assert bridge.first_observed_at == captured.source_cutoff_at == bridge_at
        # Intended red: C's direct proof is outside 300s, although B->A now establishes C.
        winners = [item for item in captured.payload.events if item.revision_id == new]
        assert len(winners) == 1, (
            "Late bridge must emit newly established C outside its direct-proof window"
        )
        winner = winners[0]
        assert winner.first_eligible_at == bridge_at and winner.correction_of == middle
        assert winner.net_amount is not None and winner.net_amount.amount == Decimal("4")
        for evidence in (tail, bridge):
            assert any(
                ref.kind is ReportSourceKind.ACTIVITY_REVISION_EVIDENCE
                and ref.subject_id == evidence.registration.id
                and ref.content_digest == evidence.content_digest
                for ref in captured.source_references
            )
        claim = await jobs.claim_evaluation_job(message, consumer_id="bridge-first-attempt")
        assert claim is not None
        assert await jobs.fail_evaluation_job(
            claim, failure=a.AlertReason.PUBLICATION_UNAVAILABLE, retryable=True
        )
        now[0] += timedelta(seconds=2)
        assert (
            await execute_alert_message(restarted(), message, consumer_id="bridge-retry")
            is AlertExecutionState.COMPLETED
        )
        assert (
            await execute_alert_message(restarted(), message, consumer_id="bridge-duplicate")
            is AlertExecutionState.NOT_CLAIMED
        )
        assert (await restarted().admit_due_evaluations(limit=1)).admitted == 0
        with case.sessions() as session:
            job = session.get_one(AlertEvaluationJobModel, message.job_id)
            assert job.state == "succeeded" and job.consumer_attempts == 2
            retained = session.get_one(AlertInputSnapshotModel, message.capture_id)
            assert (
                retained.payload == original_payload
                and retained.input_digest == message.input_digest
            )
            evaluation = session.scalars(
                select(AlertEvaluationModel).where(AlertEvaluationModel.job_id == job.id)
            ).one()
            assert evaluation.payload is not None and evaluation.input_id == message.capture_id
            result = decode_alert_result(evaluation.payload)
            assert result.outcome is a.AlertEvaluationOutcome.MATCHED and result.decision is True
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AlertEventModel)
                    .where(
                        AlertEventModel.rule_id == rule.id, AlertEventModel.event_revision_id == new
                    )
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(InAppNotificationModel)
                    .join(
                        AlertEventModel,
                        AlertEventModel.id == InAppNotificationModel.event_id,
                    )
                    .where(
                        AlertEventModel.rule_id == rule.id, AlertEventModel.event_revision_id == new
                    )
                )
                == 1
            )
        # A subsequent real slot cannot emit C a second time.
        now[0] = bridge_at + timedelta(seconds=300)
        assert (await restarted().admit_due_evaluations(limit=1)).admitted == 1
        (later_dispatch,) = await restarted().claim_evaluation_dispatches(
            dispatcher_id="bridge-next-slot", limit=1
        )
        assert await restarted().acknowledge_evaluation_dispatch(later_dispatch)
        with case.sessions() as session:
            later_input = session.get_one(
                AlertInputSnapshotModel, later_dispatch.message.capture_id
            )
            assert later_input.payload is not None
            later_capture = decode_alert_input(later_input.payload)
            assert isinstance(later_capture.payload, a.AlertEventBatchInput)
            assert all(
                item.revision_id not in {old, middle, new} for item in later_capture.payload.events
            )
        assert (
            await execute_alert_message(
                restarted(), later_dispatch.message, consumer_id="bridge-next-slot"
            )
            is AlertExecutionState.COMPLETED
        )
        with case.sessions() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AlertEventModel)
                    .where(
                        AlertEventModel.rule_id == rule.id, AlertEventModel.event_revision_id == new
                    )
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(InAppNotificationModel)
                    .join(
                        AlertEventModel,
                        AlertEventModel.id == InAppNotificationModel.event_id,
                    )
                    .where(
                        AlertEventModel.rule_id == rule.id, AlertEventModel.event_revision_id == new
                    )
                )
                == 1
            )
            assert (
                session.get_one(AlertInputSnapshotModel, message.capture_id).payload
                == original_payload
            )
        assert raw_facts(case, (old, middle, new)) == original_facts

    asyncio.run(run())
