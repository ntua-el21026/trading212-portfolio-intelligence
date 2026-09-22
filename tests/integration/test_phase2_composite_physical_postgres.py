"""Shared benchmark points drain once under an exact original-input witness."""

from dataclasses import replace
from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import historical as app
from trading212_domain import historical as d
from trading212_domain.historical_results import ComparisonOptions
from trading212_domain.values import CurrencyCode
from trading212_persistence import historical_models as hm
from trading212_persistence.historical_retention import purge_source_copies
from trading212_persistence.historical_service import PostgresHistoricalService
from trading212_persistence.phase2_retention_models import (
    HistoricalCompositeErasureModel,
    HistoricalCompositePhysicalModel,
    HistoricalPhysicalRunModel,
    HistoricalRetainedSourceModel,
)
from trading212_persistence.source_models import PriceSnapshotModel
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_worker.historical_seed import history_principal

from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_historical_postgres import historical_seed as historical_seed
from tests.integration.test_sources_postgres import KEY, NOW

pytestmark = pytest.mark.integration


async def test_two_saved_runs_share_bounded_composite_erasure_without_fanout(
    historical_database: tuple[Engine, sessionmaker[Session]], historical_seed: dict[str, str]
) -> None:
    _, sessions = historical_database
    principal = history_principal(NOW)
    owner = UUID(principal.owner_id)
    account = historical_seed["annual_account_id"]
    service = PostgresHistoricalService(sessions, cursor_signing_key=KEY, clock=lambda: NOW)
    query = app.BenchmarkComparisonQuery(
        window=d.HistoricalWindow(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            source_cutoff_at=NOW,
            reporting_currency=CurrencyCode("EUR"),
        ),
        benchmark_version_id=historical_seed["annual_benchmark_version_id"],
    )
    first = await service.get_benchmark_comparison(principal, account, query=query)
    assert first.composite_snapshot is not None
    second = await service.get_benchmark_comparison(
        principal,
        account,
        query=replace(
            query,
            input_snapshot_id=first.context.input_snapshot_id,
            options=ComparisonOptions(frequency=d.HistoricalFrequency.DAILY),
        ),
    )
    assert (
        first.context.run_id != second.context.run_id
        and second.composite_snapshot == first.composite_snapshot
    )
    snapshot, input_id = UUID(first.composite_snapshot.id), UUID(first.context.input_snapshot_id)
    with sessions() as session:
        run_ids = list(
            session.scalars(
                select(hm.HistoricalCompositeModel.run_id).where(
                    hm.HistoricalCompositeModel.snapshot_id == snapshot,
                    hm.HistoricalCompositeModel.owner_id == owner,
                )
            )
        )
        assert len(run_ids) >= 2
        state = session.get_one(HistoricalCompositePhysicalModel, snapshot)
        points = session.scalar(
            select(func.count())
            .select_from(hm.BenchmarkCompositePointModel)
            .where(
                hm.BenchmarkCompositePointModel.snapshot_id == snapshot,
                hm.BenchmarkCompositePointModel.canonical_point != b"",
            )
        )
        assert state.point_rows == points and points is not None and points > 1
        member = session.scalar(
            select(HistoricalRetainedSourceModel)
            .where(
                HistoricalRetainedSourceModel.owner_id == owner,
                HistoricalRetainedSourceModel.input_id == input_id,
                HistoricalRetainedSourceModel.source_kind == "price",
            )
            .order_by(HistoricalRetainedSourceModel.dependency_id)
            .limit(1)
        )
        assert member is not None
        source_id = member.source_id
        at = session.get_one(PriceSnapshotModel, source_id).expires_at + timedelta(seconds=1)
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.add(
            HistoricalCompositeErasureModel(
                snapshot_id=snapshot, owner_id=owner, run_id=run_ids[0], event_id=uuid4()
            )
        )
        session.flush()
    with sessions() as session, session.begin():
        source = session.get_one(PriceSnapshotModel, source_id)
        initial = SourcePurgeBudget(rows_inspected=256, rows_removed=1)
        assert not purge_source_copies(session, source, at=at, budget=initial)
        assert session.get_one(HistoricalCompositePhysicalModel, snapshot).point_rows == points
        # This canary proves the actual SQL mutation path does not consult the
        # independent aggregate, including when the shared points reach zero.
        session.execute(
            text(
                "CREATE OR REPLACE FUNCTION phase2_historical_rows_oracl"
                "e(p_run uuid) RETURNS bigint LANGUAGE plpgsql AS $$ BEG"
                "IN RAISE EXCEPTION 'shared-composite-aggregate-canary';"
                " END $$"
            )
        )
        for _ in range(128):
            allowance = SourcePurgeBudget()
            complete = purge_source_copies(session, source, at=at, budget=allowance)
            assert 0 <= allowance.rows_inspected <= 4096 and 0 <= allowance.rows_removed <= 4096
            assert 0 <= allowance.bytes_inspected <= 64 * 1024 * 1024
            if complete:
                break
        else:
            pytest.fail(
                "Shared composite erasure did not converge under one bou"
                "nded allowance per invocation"
            )
        session.expire_all()
        assert session.get_one(HistoricalCompositePhysicalModel, snapshot).point_rows == 0
        assert session.get_one(HistoricalCompositeErasureModel, snapshot).run_id in run_ids
        for identifier in run_ids:
            retained = session.get_one(HistoricalPhysicalRunModel, identifier)
            assert retained.child_rows == 0 and not retained.analytics_pending
        assert (
            session.scalar(
                select(HistoricalRetainedSourceModel.dependency_id)
                .where(HistoricalRetainedSourceModel.input_id == input_id)
                .limit(1)
            )
            is None
        )
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        session.rollback()
