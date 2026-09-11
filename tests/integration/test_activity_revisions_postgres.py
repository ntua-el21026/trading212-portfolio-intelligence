"""Actual immutable broker revisions require explicit, authorized correction evidence."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from trading212_analytics._historical_core import selected_event_revisions
from trading212_application import activity_revisions as app
from trading212_domain import historical as d
from trading212_persistence.activity_revision_models import ActivityRevisionEvidenceModel
from trading212_persistence.activity_revision_store import (
    PostgresActivityRevisionStore,
    activity_revision_sources,
    capture_activity_revisions,
    revision_digest,
)
from trading212_persistence.historical_normalization import normalize_record
from trading212_persistence.models import AuditEventModel, IngestionRunModel, SourceRecordModel
from trading212_persistence.planning_inputs import digest
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_security.principals import Scope

from tests.integration.test_report_postgres import ReportCase
from tests.integration.test_report_postgres import report_case as report_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def records(case: ReportCase) -> tuple[UUID, UUID, UUID]:
    """Insert synthetic broker facts under a real account/ingestion run, without revision hints."""
    identifiers = (uuid4(), uuid4(), uuid4())
    with case.base.sessions() as session, session.begin():
        run = session.scalar(
            select(IngestionRunModel)
            .where(IngestionRunModel.broker_account_id == case.account_id)
            .order_by(IngestionRunModel.id)
        )
        assert run is not None
        for identifier, amount, reference in zip(
            identifiers, ("2", "3", "4"), ("payment-1", "payment-1", "payment-2"), strict=True
        ):
            now = datetime.now(UTC)
            body = {
                "amount": amount,
                "currency": "EUR",
                "reference": reference,
                "paidOn": (now - timedelta(days=1)).date().isoformat(),
            }
            session.add(
                SourceRecordModel(
                    id=identifier,
                    ingestion_run_id=run.id,
                    broker_account_id=case.account_id,
                    provider="synthetic",
                    capability="historical_dividends",
                    provider_record_type="dividend",
                    provider_record_id=reference,
                    payload_fingerprint=digest(body),
                    observed_at=now,
                    created_at=now,
                    source_updated_at=now - timedelta(days=1),
                    schema_version="synthetic-revision-evidence-v1",
                    sanitized_payload=body,
                )
            )
    return identifiers


def registration(new: UUID, old: UUID) -> app.ActivityRevisionRegistration:
    return app.ActivityRevisionRegistration(
        id=uuid4(),
        new_source_record_id=new,
        superseded_source_record_id=old,
        authority=app.ActivityRevisionAuthority.OWNER_ATTESTATION,
        evidence_key="synthetic-explicit-correction-review",
    )


def test_real_revision_registration_replays_once_and_binds_cutoff_visible_correction(
    report_case: ReportCase,
) -> None:
    case = report_case
    previous, new, _ = records(case)
    command = registration(new, previous)
    store = PostgresActivityRevisionStore(case.base.sessions)

    async def register() -> app.ActivityRevisionEvidence:
        first = await store.register_activity_revision(
            case.principal,
            case.account_id,
            command,
            idempotency_key="same-correction",
            correlation_id="revision-regression",
        )
        again = await store.register_activity_revision(
            case.principal,
            case.account_id,
            command,
            idempotency_key="same-correction",
            correlation_id="revision-regression-replay",
        )
        assert first == again
        return first

    proof = asyncio.run(register())
    assert proof.content_digest == revision_digest(proof)
    with case.base.sessions() as session:
        raw = tuple(
            normalize_record(session.get_one(SourceRecordModel, identifier), None, ())
            for identifier in (previous, new)
        )
        assert all(isinstance(value, d.HistoricalDividend) for value in raw)
        events = tuple(value for value in raw if value is not None)
        assert selected_event_revisions(events, proof.first_observed_at) == ((), True)
        earlier, absent = capture_activity_revisions(
            session,
            owner_id=proof.owner_id,
            account_id=case.account_id,
            events=events,
            cutoff=proof.first_observed_at - timedelta(microseconds=1),
        )
        assert earlier == events and absent == ()
        corrected, actual = capture_activity_revisions(
            session,
            owner_id=proof.owner_id,
            account_id=case.account_id,
            events=events,
            cutoff=proof.first_observed_at,
        )
        assert actual == (proof,)
        assert corrected == events
        selected, ambiguous = selected_event_revisions(
            corrected, proof.first_observed_at, revision_sources=activity_revision_sources(actual)
        )
        assert not ambiguous and len(selected) == 1
        result = selected[0]
        assert isinstance(result, d.HistoricalDividend)
        assert result.identity.source_record_id == str(new)
        assert result.identity.supersedes_revision_id == result.correction_of == str(previous)
        assert result.identity.first_observed_at == events[1].identity.first_observed_at
        assert result.identity.revision_sequence is None
        assert isinstance(events[1], d.HistoricalDividend)
        assert result.net == events[1].net
        assert session.scalar(select(func.count()).select_from(ActivityRevisionEvidenceModel)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEventModel)
                .where(AuditEventModel.action == "activity.revision.registered")
            )
            == 1
        )
    with pytest.raises(IntegrityError), case.base.sessions() as session, session.begin():
        session.execute(
            update(ActivityRevisionEvidenceModel)
            .where(ActivityRevisionEvidenceModel.id == proof.registration.id)
            .values(evidence_key="changed")
        )


def test_real_revision_registration_rejects_identity_cycles_key_reuse_and_missing_authority(
    report_case: ReportCase,
) -> None:
    case = report_case
    previous, new, different = records(case)
    store = PostgresActivityRevisionStore(case.base.sessions)

    async def rejected(
        command: app.ActivityRevisionRegistration, key: str, expected: app.ActivityRevisionErrorCode
    ) -> None:
        with pytest.raises(app.ActivityRevisionError) as error:
            await store.register_activity_revision(
                case.principal,
                case.account_id,
                command,
                idempotency_key=key,
                correlation_id="revision-negative",
            )
        assert error.value.code is expected

    async def run() -> None:
        await rejected(
            registration(different, previous),
            "wrong-economic",
            app.ActivityRevisionErrorCode.SOURCE_REVISION_CONFLICT,
        )
        await rejected(
            registration(uuid4(), previous),
            "missing-source",
            app.ActivityRevisionErrorCode.NOT_FOUND,
        )
        command = registration(new, previous)
        denied = replace(case.principal, scopes=case.principal.scopes - {Scope.TARGETS_WRITE})
        with pytest.raises(app.ActivityRevisionError) as error:
            await store.register_activity_revision(
                denied,
                case.account_id,
                command,
                idempotency_key="without-authority",
                correlation_id="revision-negative",
            )
        assert error.value.code is app.ActivityRevisionErrorCode.ACCESS_DENIED
        await store.register_activity_revision(
            case.principal,
            case.account_id,
            command,
            idempotency_key="explicit-edge",
            correlation_id="revision-positive",
        )
        await rejected(
            registration(previous, new),
            "cycle",
            app.ActivityRevisionErrorCode.SOURCE_REVISION_CONFLICT,
        )
        await rejected(
            registration(different, previous),
            "explicit-edge",
            app.ActivityRevisionErrorCode.IDEMPOTENCY_KEY_REUSED,
        )
        await rejected(
            registration(new, previous),
            "conflicting-edge",
            app.ActivityRevisionErrorCode.SOURCE_REVISION_CONFLICT,
        )
        with case.base.sessions() as session, session.begin():
            provision_principal_scopes(
                session,
                principal_id=UUID(case.principal.principal_id),
                scopes=frozenset(Scope) - {Scope.TARGETS_WRITE},
                now=datetime.now(UTC),
            )
        # Even an exact replay rechecks persisted grants, despite the still-broad token claim.
        await rejected(command, "explicit-edge", app.ActivityRevisionErrorCode.ACCESS_DENIED)

    asyncio.run(run())
    with case.base.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ActivityRevisionEvidenceModel)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEventModel)
                .where(AuditEventModel.action == "activity.revision.registered")
            )
            == 1
        )
