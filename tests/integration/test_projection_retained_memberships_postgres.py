"""Actual retained source closure, seal integrity and fixed cleanup SQL backstops."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import projection as app
from trading212_persistence import projection_input_store as inputs
from trading212_persistence import projection_retention as retention
from trading212_persistence.premium_models import PremiumRetentionModel, PremiumRunModel
from trading212_persistence.projection_models import (
    ProjectionRetainedSourceModel,
    ProjectionRunModel,
)
from trading212_persistence.projection_source_memberships import retained_source_keys
from trading212_persistence.projection_source_store import ProjectionSourceHeader
from trading212_persistence.source_models import PriceSnapshotModel
from trading212_persistence.source_retention import SourcePurgeBudget

from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_projection_retention_isolation_postgres import admitted_owner

pytestmark = pytest.mark.integration


async def test_actual_direct_and_historical_lineage_deduplicates_and_charges_exact_storage(
    historical_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = historical_database
    case = await admitted_owner(sessions, retention_days=365)
    owner = UUID(case.source.principal.owner_id)
    with sessions() as session:
        rows = tuple(
            session.scalars(
                select(ProjectionRetainedSourceModel).where(
                    ProjectionRetainedSourceModel.run_id == case.run.id
                )
            )
        )
        prices = [
            row for row in rows if row.source_kind == "price" and row.source_id == case.price_id
        ]
        assert len(prices) == 1  # selected directly and by the retained historical input
        assert (
            prices[0].original_created_at
            == session.get_one(PriceSnapshotModel, case.price_id).created_at
        )
        assert any(
            row.source_kind == "historical" and row.source_id == case.history_id for row in rows
        )
        assert all(row.owner_id == owner and row.account_id == case.account_id for row in rows)
        run = session.get_one(ProjectionRunModel, case.run.id)
        measured = session.scalar(
            text(
                "SELECT sum(pg_column_size(t)) FROM projection_retained_sourc"
                "e_memberships t WHERE t.run_id=:run"
            ),
            {"run": run.id},
        )
        assert run.retained_source_rows == len(rows) and run.retained_source_bytes == measured
        assert run.stored_bytes == session.scalar(select(func.projection_storage_bytes(run.id)))
        assert session.scalar(select(func.projection_source_membership_complete(run.id))) is True
        assert (
            session.scalar(select(func.projection_parent_has_copies(owner, "price", case.price_id)))
            is True
        )
        assert (
            session.scalar(
                select(func.projection_parent_has_copies(uuid4(), "price", case.price_id))
            )
            is False
        )
        identifier = prices[0].id
    for statement in (
        delete(ProjectionRetainedSourceModel).where(ProjectionRetainedSourceModel.id == identifier),
        update(ProjectionRetainedSourceModel)
        .where(ProjectionRetainedSourceModel.id == identifier)
        .values(original_created_at=datetime(2000, 1, 1, tzinfo=case.source.now[0].tzinfo)),
    ):
        with pytest.raises(IntegrityError), sessions() as session, session.begin():
            session.execute(statement)
    with sessions() as session, session.begin():
        session.execute(text("SET LOCAL enable_seqscan=off"))
        plan = session.scalar(
            text(
                "EXPLAIN (FORMAT JSON,COSTS OFF) SELECT 1 FROM projection_ret"
                "ained_source_memberships WHERE owner_id=:owner AND source_ki"
                "nd='price' AND source_id=:source LIMIT 1"
            ),
            {"owner": owner, "source": case.price_id},
        )
        assert isinstance(plan, list)
        indexed = plan[0]["Plan"]["Plans"][0]
        assert indexed["Node Type"] in ("Index Scan", "Index Only Scan")
        assert indexed["Index Name"] == "ix_projection_retained_parent"
        assert "Filter" not in indexed


@pytest.mark.parametrize("mutation", ["missing", "clock", "extra"])
async def test_sql_seal_rejects_omitted_forged_or_extra_source_membership(
    historical_database: tuple[Engine, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    _, sessions = historical_database
    original = retained_source_keys
    extra = uuid4()

    def corrupt(
        headers: Sequence[ProjectionSourceHeader],
    ) -> tuple[tuple[str, UUID, datetime], ...]:
        actual = original(headers)
        if mutation == "missing":
            return ()
        assert actual
        kind, identifier, stamp = actual[0]
        if mutation == "clock":
            return ((kind, identifier, stamp - timedelta(seconds=1)), *actual[1:])
        return (*actual, ("price", extra, stamp))

    monkeypatch.setattr(inputs, "retained_source_keys", corrupt)
    with sessions() as session:
        before = session.scalar(select(func.count()).select_from(PremiumRunModel))
    with pytest.raises(app.ProjectionServiceError) as rejected:
        await admitted_owner(sessions, retention_days=365)
    assert rejected.value.code is app.ProjectionErrorCode.CONFLICT
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(PremiumRunModel)) == before


async def test_partial_cleanup_keeps_membership_and_uses_no_recursive_or_aggregate_sql(
    historical_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = historical_database
    case = await admitted_owner(sessions, retention_days=365)
    owner = UUID(case.source.principal.owner_id)
    with sessions() as session, session.begin():
        assert retention._lock_owner(session, owner)
        # Roll back only these temporary helper replacements after exercising real
        # trigger execution; no production function is changed outside this test DB.
        session.execute(
            text(
                "CREATE OR REPLACE FUNCTION projection_history_links(p_owner "
                "uuid,p_input uuid) RETURNS SETOF historical_dependencies LAN"
                "GUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'recursive-cleanup"
                "-canary'; END $$"
            )
        )
        session.execute(
            text(
                "CREATE OR REPLACE FUNCTION projection_storage_bytes(p_run uu"
                "id) RETURNS bigint LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPT"
                "ION 'aggregate-cleanup-canary'; END $$"
            )
        )
        try:
            budget = SourcePurgeBudget(rows_inspected=512, rows_removed=1)
            assert not retention.purge_owner_projection_payloads(
                session, owner, at=case.source.now[0], budget=budget
            )
            run = session.get_one(ProjectionRunModel, case.run.id)
            session.refresh(run)
            assert run.retained_source_rows > 0 and run.payload_rows > 0
            assert (
                session.scalar(
                    select(func.projection_parent_has_copies(owner, "price", case.price_id))
                )
                is True
            )
            # Force every deferred integrity function now, while canaries are active.
            session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            for _ in range(20):
                budget = SourcePurgeBudget()
                if retention.purge_owner_projection_payloads(
                    session, owner, at=case.source.now[0], budget=budget
                ):
                    break
                assert 0 <= budget.rows_inspected <= 4096
            else:
                pytest.fail("bounded cleanup failed to resume")
            session.refresh(run)
            assert (
                run.payload_rows,
                run.retained_source_rows,
                run.retained_source_bytes,
                run.stored_bytes,
            ) == (0, 0, 0, 0)
            assert (
                session.scalar(
                    select(func.projection_parent_has_copies(owner, "price", case.price_id))
                )
                is False
            )
            marker = session.scalar(
                select(PremiumRetentionModel).where(PremiumRetentionModel.run_id == run.id)
            )
            assert marker is not None and marker.completed_at is not None
        finally:
            # Restore function definitions and all physical test mutations together.
            session.rollback()
