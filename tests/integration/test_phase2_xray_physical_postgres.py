"""Real source/X-ray capture, row-counter parity and bounded physical erasure."""

import asyncio
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from trading212_persistence.phase2_retention_models import (
    XrayPhysicalStateModel,
    XrayRetainedSourceModel,
)
from trading212_persistence.source_models import SourceRetentionWorkModel
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.source_retention_service import expire_source_payloads
from trading212_persistence.xray_catalog_models import ConstituentSnapshotModel
from trading212_persistence.xray_run_models import (
    XrayExposurePathModel,
    XrayInputSnapshotModel,
    XrayPathEdgeModel,
    XrayRetentionEventModel,
)

from tests.integration.test_xray_reads_postgres import XrayReadCase, company
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def test_actual_counter_matches_independent_oracle_and_rejects_forged_absence(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    view = asyncio.run(company(case))
    input_id = UUID(view.context.input_snapshot_id)
    with case.sessions() as session:
        state = session.get_one(XrayPhysicalStateModel, input_id)
        assert state.input_pending and state.payload_rows > 0
        assert state.payload_rows == session.scalar(select(func.phase2_xray_rows_oracle(input_id)))
        membership = session.scalar(
            select(XrayRetainedSourceModel)
            .where(
                XrayRetainedSourceModel.input_id == input_id,
                XrayRetainedSourceModel.source_kind == "constituent",
            )
            .limit(1)
        )
        assert membership is not None
        dependency_id, owner, source_id = (
            membership.dependency_id,
            membership.owner_id,
            membership.source_id,
        )
        source = session.get_one(ConstituentSnapshotModel, source_id)
        at = source.expires_at + timedelta(seconds=1)
        premature_at, source_digest = source.created_at, source.content_digest
        edge = session.scalar(
            select(XrayPathEdgeModel).where(XrayPathEdgeModel.owner_id == owner).limit(1)
        )
        assert edge is not None
        path_id = edge.path_id
    with (
        pytest.raises(IntegrityError, match="pending retention authorization"),
        case.sessions.begin() as session,
    ):
        session.add(
            SourceRetentionWorkModel(
                owner_id=owner,
                constituent_snapshot_id=source_id,
                started_at=premature_at,
                content_digest=source_digest,
                phase="copies",
                removed_observation_count=0,
                created_at=premature_at,
            )
        )
        session.flush()
    for statement in (
        update(XrayPhysicalStateModel)
        .where(XrayPhysicalStateModel.input_id == input_id)
        .values(payload_rows=0),
        delete(XrayRetainedSourceModel).where(
            XrayRetainedSourceModel.dependency_id == dependency_id
        ),
    ):
        with pytest.raises(IntegrityError), case.sessions.begin() as session:
            session.execute(statement)
    with (
        pytest.raises(IntegrityError, match="path edges remain pending"),
        case.sessions.begin() as session,
    ):
        session.add(
            XrayRetentionEventModel(
                owner_id=owner,
                input_id=input_id,
                dependency_id=dependency_id,
                expired_at=at,
                created_at=at,
            )
        )
        session.flush()
        session.execute(
            update(XrayExposurePathModel)
            .where(XrayExposurePathModel.id == path_id)
            .values(canonical_payload=b"")
        )
    with case.sessions.begin() as session:
        indexes = {
            str(name): str(definition)
            for name, definition in session.execute(
                text(
                    "SELECT indexname,indexdef FROM pg_indexes WHERE indexna"
                    "me IN ('ix_p2_edge_holding','ix_p2_assignment_reference"
                    "')"
                )
            ).all()
        }
        assert "(owner_id, holding_id)" in indexes["ix_p2_edge_holding"]
        assert "(owner_id, assignment_id)" in indexes["ix_p2_assignment_reference"]
        session.execute(text("SET LOCAL enable_seqscan=off"))
        plan = session.scalar(
            text(
                "EXPLAIN (FORMAT JSON,COSTS OFF) SELECT input_id FROM xr"
                "ay_retained_sources WHERE owner_id=:owner AND source_ki"
                "nd='constituent' AND source_id=:source ORDER BY input_i"
                "d,dependency_id LIMIT 1"
            ),
            {"owner": owner, "source": source_id},
        )
        assert isinstance(plan, list)
        indexed = plan[0]["Plan"]["Plans"][0]
        assert indexed["Index Name"] == "ix_xray_retained_source" and "Filter" not in indexed


def test_actual_partial_erasure_keeps_membership_and_never_calls_full_oracle(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    view = asyncio.run(company(case))
    input_id = UUID(view.context.input_snapshot_id)
    with case.sessions() as session:
        source = session.scalar(
            select(ConstituentSnapshotModel)
            .where(ConstituentSnapshotModel.owner_id == UUID(case.principal.owner_id))
            .order_by(ConstituentSnapshotModel.expires_at)
            .limit(1)
        )
        assert source is not None
        at = source.expires_at + timedelta(seconds=1)
        digest = session.get_one(XrayInputSnapshotModel, input_id).input_digest
    # Changes to helper SQL and the purge itself are rolled back together; this is
    # an actual trigger execution canary, not a replacement for source authority.
    with case.sessions() as session, session.begin():
        session.execute(
            text(
                "CREATE OR REPLACE FUNCTION phase2_xray_rows_oracle(p_in"
                "put uuid) RETURNS bigint LANGUAGE plpgsql AS $$ BEGIN R"
                "AISE EXCEPTION 'aggregate-cleanup-canary'; END $$"
            )
        )
        budget = SourcePurgeBudget(rows_inspected=512, rows_removed=1)
        assert expire_source_payloads(session, at=at, limit=1, budget=budget) == 0
        state = session.get_one(XrayPhysicalStateModel, input_id)
        assert state.payload_rows > 0
        assert (
            session.scalar(
                select(XrayRetainedSourceModel.dependency_id)
                .where(XrayRetainedSourceModel.input_id == input_id)
                .limit(1)
            )
            is not None
        )
        assert (
            session.scalar(
                select(SourceRetentionWorkModel.id)
                .where(SourceRetentionWorkModel.completed_at.is_(None))
                .limit(1)
            )
            is not None
        )
        for _ in range(256):
            allowance = SourcePurgeBudget(rows_inspected=256, rows_removed=256)
            expire_source_payloads(session, at=at, limit=1, budget=allowance)
            assert 0 <= allowance.rows_inspected <= 256 and 0 <= allowance.rows_removed <= 256
            assert 0 <= allowance.bytes_inspected <= 64 * 1024 * 1024
            session.refresh(state)
            if not state.input_pending and state.payload_rows == 0:
                break
        else:
            pytest.fail("Phase2 source/X-ray cleanup did not converge within bounded retries")
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        capture = session.get_one(XrayInputSnapshotModel, input_id)
        session.refresh(capture)
        assert capture.canonical_input == b"" and capture.input_digest == digest
        # Membership may consume its own final bounded turn after the final blob.
        for _ in range(8):
            expire_source_payloads(session, at=at, limit=1, budget=SourcePurgeBudget())
            if (
                session.scalar(
                    select(XrayRetainedSourceModel.dependency_id)
                    .where(XrayRetainedSourceModel.input_id == input_id)
                    .limit(1)
                )
                is None
            ):
                break
        else:
            pytest.fail("empty X-ray membership did not drain")
        session.rollback()
