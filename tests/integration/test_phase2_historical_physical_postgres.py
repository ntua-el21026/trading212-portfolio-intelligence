"""Original direct/transitive historical sources authorize exact bounded cleanup."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import historical as app
from trading212_application.historical_evidence import HistoricalEvidenceRegistration
from trading212_domain import historical as d
from trading212_persistence import historical_models as hm
from trading212_persistence.historical_retention import purge_source_copies
from trading212_persistence.historical_service import PostgresHistoricalService
from trading212_persistence.phase2_retention_models import (
    HistoricalPhysicalRunModel,
    HistoricalRetainedSourceModel,
)
from trading212_persistence.source_models import PriceSnapshotModel
from trading212_persistence.source_retention import SourcePurgeBudget

from tests.integration.test_historical_postgres import historical_case, policy, selection
from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_sources_postgres import KEY, ingest

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("transitive", [False, True])
async def test_real_historical_original_dependency_witness_and_counter_parity(
    historical_database: tuple[Engine, sessionmaker[Session]], transitive: bool
) -> None:
    _, sessions = historical_database
    case, account, store = await historical_case(sessions)
    source = await ingest(case, key="physical")
    registration = policy(case)
    evidence_id = None
    if transitive:
        evidence_id = uuid4()
        case.now[0] += timedelta(microseconds=1)
        opening = d.InceptionHistoricalOpening(
            inception_at=selection(None).window.start_at,
            source_refs=(source.id,),
            bridge_coverage=d.HistoricalCoverage(measures=()),
        )
        evidence = HistoricalEvidenceRegistration(
            id=str(evidence_id), key="phase2-physical-origin", opening=opening
        )
        await store.register_historical_evidence(
            case.principal,
            account,
            evidence,
            idempotency_key="phase2-origin",
            correlation_id="physical-retention",
        )
        registration = replace(registration, price_series_ids=())
        with pytest.raises(app.HistoricalServiceError):
            await store.register_historical_evidence(
                case.principal,
                account,
                replace(
                    evidence,
                    id=str(uuid4()),
                    key="illegal-nested",
                    opening=replace(opening, source_refs=(str(evidence_id),)),
                ),
                idempotency_key="phase2-illegal-nested",
                correlation_id="physical-retention",
            )
    await store.register_historical_policy(
        case.principal,
        account,
        registration,
        idempotency_key="policy",
        correlation_id="physical-retention",
    )
    request = selection(registration)
    request = replace(request, window=replace(request.window, source_cutoff_at=case.now[0]))
    captured = await store.capture(case.principal, account, request=request)
    service = PostgresHistoricalService(sessions, cursor_signing_key=KEY, clock=lambda: case.now[0])
    await service.get_performance_series(
        case.principal,
        account,
        query=app.PerformanceSeriesQuery(window=request.window, input_snapshot_id=captured.id),
    )
    owner, input_id = UUID(case.principal.owner_id), UUID(captured.id)
    with sessions() as session:
        membership = session.scalar(
            select(HistoricalRetainedSourceModel)
            .where(
                HistoricalRetainedSourceModel.owner_id == owner,
                HistoricalRetainedSourceModel.input_id == input_id,
                HistoricalRetainedSourceModel.source_id == UUID(source.id),
                (
                    HistoricalRetainedSourceModel.dependency_id
                    != HistoricalRetainedSourceModel.leaf_id
                )
                if transitive
                else (
                    HistoricalRetainedSourceModel.dependency_id
                    == HistoricalRetainedSourceModel.leaf_id
                ),
            )
            .limit(1)
        )
        assert (
            membership is not None
            and (membership.dependency_id != membership.leaf_id) == transitive
        )
        root_id, leaf_id = membership.dependency_id, membership.leaf_id
        state = session.scalar(
            select(HistoricalPhysicalRunModel).where(
                HistoricalPhysicalRunModel.input_id == input_id
            )
        )
        assert state is not None and state.analytics_pending
        assert state.child_rows == session.scalar(
            select(func.phase2_historical_rows_oracle(state.run_id))
        )
        run_id = state.run_id
        original_evidence = (
            None
            if evidence_id is None
            else session.get_one(hm.HistoricalEvidenceModel, evidence_id).canonical_evidence
        )
        at = session.get_one(PriceSnapshotModel, UUID(source.id)).expires_at + timedelta(seconds=1)
    for statement in (
        update(HistoricalPhysicalRunModel)
        .where(HistoricalPhysicalRunModel.run_id == run_id)
        .values(child_rows=0, analytics_pending=False),
        delete(HistoricalRetainedSourceModel).where(
            HistoricalRetainedSourceModel.input_id == input_id
        ),
    ):
        with pytest.raises(IntegrityError), sessions.begin() as session:
            session.execute(statement)
    # A real leaf of a different owner cannot borrow the original root's authority.
    foreign, foreign_account, foreign_store = await historical_case(sessions)
    foreign_source = await ingest(foreign, key="foreign-physical-source")
    foreign_policy = policy(foreign)
    await foreign_store.register_historical_policy(
        foreign.principal,
        foreign_account,
        foreign_policy,
        idempotency_key="foreign-physical-policy",
        correlation_id="physical-retention",
    )
    foreign_capture = await foreign_store.capture(
        foreign.principal, foreign_account, request=selection(foreign_policy)
    )
    with sessions() as session:
        foreign_leaf = session.scalar(
            select(hm.HistoricalDependencyModel.id).where(
                hm.HistoricalDependencyModel.input_id == UUID(foreign_capture.id),
                hm.HistoricalDependencyModel.price_snapshot_id == UUID(foreign_source.id),
            )
        )
        assert foreign_leaf is not None
    for forged_leaf in (foreign_leaf, root_id if transitive else uuid4()):
        with pytest.raises(IntegrityError), sessions.begin() as session:
            session.add(
                hm.HistoricalRetentionEventModel(
                    owner_id=owner,
                    input_id=input_id,
                    dependency_id=root_id,
                    source_dependency_id=forged_leaf,
                    removed_at=at,
                    reason="retention_removed",
                    created_at=at,
                )
            )
            session.flush()
    with sessions() as session, session.begin():
        if transitive:
            # A captured inception source has both direct and registered-evidence
            # witnesses. Exercise the exact transitive marker independently of
            # randomly generated dependency UUID ordering.
            session.add(
                hm.HistoricalRetentionEventModel(
                    owner_id=owner,
                    input_id=input_id,
                    dependency_id=root_id,
                    source_dependency_id=leaf_id,
                    removed_at=at,
                    reason="retention_removed",
                    created_at=at,
                )
            )
            session.flush()
        session.execute(
            text(
                "CREATE OR REPLACE FUNCTION phase2_historical_rows_oracl"
                "e(p_run uuid) RETURNS bigint LANGUAGE plpgsql AS $$ BEG"
                "IN RAISE EXCEPTION 'aggregate-cleanup-canary'; END $$"
            )
        )
        physical = session.get_one(PriceSnapshotModel, UUID(source.id))
        for _ in range(128):
            budget = SourcePurgeBudget(rows_inspected=256, rows_removed=256)
            if purge_source_copies(session, physical, at=at, budget=budget):
                break
            assert 0 <= budget.rows_inspected <= 256
        else:
            pytest.fail("bounded historical copy cleanup failed to resume")
        marker = session.scalar(
            select(hm.HistoricalRetentionEventModel).where(
                hm.HistoricalRetentionEventModel.input_id == input_id
            )
        )
        assert marker is not None and marker.dependency_id == root_id
        assert marker.source_dependency_id == (leaf_id if transitive else None)
        assert session.get_one(hm.HistoricalInputModel, input_id).canonical_input == b""
        state = session.get_one(HistoricalPhysicalRunModel, run_id)
        assert state.child_rows == 0 and not state.analytics_pending
        assert (
            session.scalar(
                select(HistoricalRetainedSourceModel.input_id)
                .where(HistoricalRetainedSourceModel.input_id == input_id)
                .limit(1)
            )
            is None
        )
        if evidence_id is not None:
            assert (
                session.get_one(hm.HistoricalEvidenceModel, evidence_id).canonical_evidence
                == original_evidence
            )
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        session.rollback()
