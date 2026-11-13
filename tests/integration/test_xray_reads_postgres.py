"""Real ingestion, immutable X-ray reads, licensed paging and independent fixture values."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import func, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import xray as app
from trading212_domain import CurrencyCode, build_synthetic_identity
from trading212_domain.sources import LicensePermission
from trading212_domain.xray import XrayBound, XrayDimension
from trading212_persistence import collection_snapshots as collection_store
from trading212_persistence import create_database_engine, create_session_factory
from trading212_persistence import xray_read_store as read_store
from trading212_persistence.models import (
    CollectionQuerySnapshotMemberModel,
    CollectionQuerySnapshotModel,
)
from trading212_persistence.phase2_retention_models import Phase2RetentionSweepModel
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.source_service import PostgresSourceService
from trading212_persistence.xray_run_models import (
    EtfOverlapEntityModel,
    EtfOverlapPairModel,
    XrayCollectionBindingModel,
)
from trading212_persistence.xray_service import PostgresXrayService
from trading212_security.principals import Principal, Scope
from trading212_worker.seed import seed_materialized_synthetic
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID, XRAY_AT, xray_id
from trading212_worker.xray_seed import XRAY_CURSOR_KEY, seed_xray_scenario
from trading212_worker.xray_source_fixture import xray_license

pytestmark = pytest.mark.integration


@dataclass
class XrayReadCase:
    engine: Engine
    sessions: sessionmaker[Session]
    service: PostgresXrayService
    principal: Principal
    now: list[datetime]
    seed: dict[str, str]

    def request(self, run_id: str | None = None) -> app.XrayRunRequest:
        return app.XrayRunRequest(
            snapshot_id=self.seed["snapshot_id"],
            source_cutoff_at=datetime.fromisoformat(self.seed["source_cutoff_at"]),
            currency=app.ExplicitCurrency(reporting_currency=CurrencyCode("EUR")),
            run_id=run_id,
        )

    @property
    def funds(self) -> tuple[str, str]:
        return self.seed["fund-a_instrument_id"], self.seed["fund-b_instrument_id"]


@pytest.fixture
def xray_read_case(monkeypatch: pytest.MonkeyPatch) -> Iterator[XrayReadCase]:
    """Each test owns one disposable database in the single shared PostgreSQL service."""
    parsed = make_url(os.environ["TEST_DATABASE_URL"])
    name = "t212pi_xray_reads_" + uuid4().hex[:12]
    admin = parsed.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = parsed.set(drivername="postgresql+psycopg", database=name).render_as_string(
        hide_password=False
    )
    engine = None
    try:
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", url)
        # Alembic intentionally prefers DATABASE_URL; a coexisting migration
        # fixture may own that variable, so pin this database for migration only.
        with monkeypatch.context() as migration_environment:
            migration_environment.setenv("DATABASE_URL", url)
            command.upgrade(cfg, "head")
        asyncio.run(seed_materialized_synthetic(url, app_environment="test"))
        engine = create_database_engine(url)
        sessions = create_session_factory(engine)
        seed = asyncio.run(seed_xray_scenario(sessions, app_environment="test"))
        identity = build_synthetic_identity()
        now = [XRAY_AT]
        principal = Principal(
            str(identity.principal.id),
            str(identity.owner.id),
            "local.synthetic",
            "synthetic-owner",
            frozenset(Scope),
            XRAY_AT - timedelta(minutes=1),
            XRAY_AT + timedelta(days=800),
        )
        yield XrayReadCase(
            engine,
            sessions,
            PostgresXrayService(
                sessions=sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: now[0]
            ),
            principal,
            now,
            seed,
        )
    finally:
        if engine is not None:
            engine.dispose()
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


async def company(case: XrayReadCase, *, limit: int = 25) -> app.ExposuresView:
    value = await case.service.get_effective_exposure(
        case.principal,
        XRAY_ACCOUNT_ID,
        query=app.EffectiveExposureQuery(request=case.request(), limit=limit),
    )
    assert isinstance(value, app.ExposuresView)
    return value


def test_real_snapshot_values_and_full_path_provenance_survive_new_service(
    xray_read_case: XrayReadCase,
) -> None:
    async def run() -> None:
        case = xray_read_case
        first = await company(case)
        assert first.summary.total.value is not None
        assert first.summary.total.value.amount == Decimal("1000")
        assert first.summary.company_known_weight.value == Decimal("0.95")
        assert first.summary.unresolved_weight.value == Decimal("0.05")
        assert first.summary.duplicated_exposure.value == Decimal("0.41")
        assert first.summary.hhi.value == Decimal("0.4657")
        actual = {row.bucket_key: row for row in first.exposures.items}
        alpha, beta = actual[xray_id("entity/alpha")], actual[xray_id("entity/beta")]
        assert alpha.effective.value is not None and beta.effective.value is not None
        assert alpha.effective.value.amount == Decimal("560")
        assert beta.effective.value.amount == Decimal("390")
        assert alpha.path_count == 6
        paths = await case.service.get_effective_exposure(
            case.principal,
            XRAY_ACCOUNT_ID,
            query=app.EffectiveExposureQuery(
                request=case.request(first.context.run_id),
                options=app.Paths(exposure_id=alpha.id),
            ),
        )
        assert isinstance(paths, app.PathsView) and paths.paths.total == 6
        assert sum(
            (
                row.reporting_value.value.amount
                for row in paths.paths.items
                if row.reporting_value.value is not None
            ),
            Decimal("0"),
        ) == Decimal("560")
        assert all(
            tuple(source.id for source in row.sources) == row.source_reference_ids
            for row in paths.paths.items
        )
        assert any(
            source.kind.value == "broker_fx" for row in paths.paths.items for source in row.sources
        )
        assert all(
            len(row.identity_decision_ids) <= 256 and len(row.sources) <= 256
            for row in paths.paths.items
        )
        case.engine.dispose()
        restored = PostgresXrayService(
            sessions=case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now[0]
        )
        replay = await restored.get_effective_exposure(
            case.principal,
            XRAY_ACCOUNT_ID,
            query=app.EffectiveExposureQuery(request=case.request(first.context.run_id)),
        )
        assert replay == first

    asyncio.run(run())


def test_page_size_normalization_and_mcp_top_preserve_run_and_exact_pair(
    xray_read_case: XrayReadCase,
) -> None:
    async def run() -> None:
        case = xray_read_case
        first = await company(case, limit=1)
        assert first.exposures.total == 2 and first.exposures.next_cursor is not None
        second = await case.service.get_effective_exposure(
            case.principal,
            XRAY_ACCOUNT_ID,
            query=app.EffectiveExposureQuery(
                request=case.request(first.context.run_id),
                cursor=first.exposures.next_cursor,
                limit=25,
            ),
        )
        assert isinstance(second, app.ExposuresView)
        assert len(second.exposures.items) == 1 and second.exposures.next_cursor is None
        assert first.exposures.items[0].id != second.exposures.items[0].id
        assert second.summary == first.summary and second.context == first.context
        normalized = await case.service.get_effective_exposure(
            case.principal,
            XRAY_ACCOUNT_ID,
            query=app.EffectiveExposureQuery(
                request=case.request(first.context.run_id),
                options=app.Exposures(normalized_known_only=True),
            ),
        )
        assert isinstance(normalized, app.ExposuresView)
        assert normalized.summary == first.summary and normalized.context == first.context
        assert normalized.exposures.items[0].normalized_known_weight is not None
        pair = await case.service.get_etf_overlap(
            case.principal,
            XRAY_ACCOUNT_ID,
            query=app.EtfOverlapQuery(
                request=case.request(first.context.run_id), options=app.Pairs(fund_ids=case.funds)
            ),
        )
        assert isinstance(pair, app.OverlapPairsView)
        assert pair.pairs.items[0].overlap.value == Decimal("0.5")
        assert pair.pairs.items[0].overlap.bound is XrayBound.LOWER_BOUND
        assert pair.pairs.items[0].common_entity_count == 2
        with case.sessions() as session:
            before = tuple(
                session.scalar(select(func.count()).select_from(model))
                for model in (
                    CollectionQuerySnapshotModel,
                    EtfOverlapPairModel,
                    EtfOverlapEntityModel,
                )
            )
        top = await case.service.get_etf_overlap(
            case.principal,
            XRAY_ACCOUNT_ID,
            query=app.EtfOverlapQuery(
                request=case.request(first.context.run_id),
                options=app.McpTopPair(
                    left_fund_id=case.funds[0], right_fund_id=case.funds[1], top_n=1
                ),
            ),
        )
        assert isinstance(top, app.McpTopPairView)
        assert top.pair.overlap == pair.pairs.items[0].overlap
        assert (top.total_count, top.returned_count, top.omitted_count) == (2, 1, 1)
        assert top.common_entities[0].common_weight.value == Decimal("0.3")
        assert top.omitted_common_weight.value == Decimal("0.2")
        with case.sessions() as session:
            after = tuple(
                session.scalar(select(func.count()).select_from(model))
                for model in (
                    CollectionQuerySnapshotModel,
                    EtfOverlapPairModel,
                    EtfOverlapEntityModel,
                )
            )
        assert after == before

    asyncio.run(run())


def test_source_page_pins_and_current_revocation_fail_before_replay_or_cursor(
    xray_read_case: XrayReadCase,
) -> None:
    async def run() -> None:
        case = xray_read_case
        first = await company(case, limit=1)
        source_id = case.seed["fund-a_snapshot_id"]
        query = app.ConstituentHoldingsQuery(
            account_id=XRAY_ACCOUNT_ID, run_id=first.context.run_id, limit=1
        )
        holdings = await case.service.list_constituent_holdings(
            case.principal, source_id, query=query
        )
        assert holdings.total == 3 and holdings.next_cursor is not None
        header = await case.service.get_constituent_snapshot(
            case.principal,
            source_id,
            query=app.ConstituentSnapshotQuery(
                account_id=XRAY_ACCOUNT_ID, run_id=first.context.run_id
            ),
        )
        assert header.known_weight == Decimal("0.9")
        assert header.unresolved_weight == Decimal("0.1")
        assert header.holding_count == holdings.total
        assert header.freshness.state.value == "stale"
        assert header.freshness_evaluated_at == first.context.quality_evaluated_at
        case.now[0] += timedelta(seconds=1)
        source = PostgresSourceService(
            sessions=case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now[0]
        )
        await source.register_source_license(
            case.principal,
            replace(
                xray_license(),
                id=str(uuid4()),
                version="synthetic-revoked",
                effective_at=case.now[0],
                display=LicensePermission.DENIED,
            ),
            idempotency_key="xray-revoke-display",
            correlation_id="xray-revoke-display",
        )
        operations = (
            case.service.get_constituent_snapshot(
                case.principal, source_id, query=app.ConstituentSnapshotQuery()
            ),
            case.service.list_constituent_holdings(
                case.principal, source_id, query=replace(query, cursor=holdings.next_cursor)
            ),
            case.service.get_effective_exposure(
                case.principal,
                XRAY_ACCOUNT_ID,
                query=app.EffectiveExposureQuery(
                    request=case.request(first.context.run_id),
                    cursor=first.exposures.next_cursor,
                    limit=1,
                ),
            ),
        )
        for operation in operations:
            with pytest.raises(app.XrayServiceError) as denied:
                await operation
            assert denied.value.code is app.XrayServiceErrorCode.ACCESS_DENIED

    asyncio.run(run())


def test_tampered_dimension_cursor_and_nonheld_pair_are_closed(
    xray_read_case: XrayReadCase,
) -> None:
    async def run() -> None:
        case = xray_read_case
        first = await company(case, limit=1)
        assert first.exposures.next_cursor is not None
        for options, cursor in (
            (app.Exposures(dimension=XrayDimension.SECTOR), first.exposures.next_cursor),
            (app.Exposures(), first.exposures.next_cursor + "tampered"),
        ):
            with pytest.raises(app.XrayServiceError) as denied:
                await case.service.get_effective_exposure(
                    case.principal,
                    XRAY_ACCOUNT_ID,
                    query=app.EffectiveExposureQuery(
                        request=case.request(first.context.run_id), options=options, cursor=cursor
                    ),
                )
            assert denied.value.code is app.XrayServiceErrorCode.VALIDATION_FAILED
        with pytest.raises(app.XrayServiceError) as nonheld:
            await case.service.get_etf_overlap(
                case.principal,
                XRAY_ACCOUNT_ID,
                query=app.EtfOverlapQuery(
                    request=case.request(first.context.run_id),
                    options=app.Pairs(fund_ids=(case.funds[0], xray_id("instrument/alpha-a"))),
                ),
            )
        assert nonheld.value.code is app.XrayServiceErrorCode.VALIDATION_FAILED
        with pytest.raises(app.XrayServiceError) as account:
            await case.service.get_effective_exposure(
                case.principal,
                str(uuid4()),
                query=app.EffectiveExposureQuery(request=case.request(first.context.run_id)),
            )
        assert account.value.code is app.XrayServiceErrorCode.NOT_FOUND

    asyncio.run(run())


def test_first_page_reuses_original_collection_before_rejecting_new_capacity(
    xray_read_case: XrayReadCase,
) -> None:
    async def run() -> None:
        case = xray_read_case
        with case.sessions() as session:
            count = session.scalar(select(func.count()).select_from(CollectionQuerySnapshotModel))
        assert count is not None
        case.service = PostgresXrayService(
            sessions=case.sessions,
            cursor_signing_key=XRAY_CURSOR_KEY,
            clock=lambda: case.now[0],
            max_active_collection_snapshots_per_owner=count + 1,
        )
        first = await company(case, limit=1)
        with case.sessions() as session:
            original = tuple(
                session.execute(
                    select(
                        CollectionQuerySnapshotModel.id, CollectionQuerySnapshotModel.expires_at
                    ).order_by(CollectionQuerySnapshotModel.id)
                )
            )
        # Changing the response limit must neither charge another snapshot nor
        # refresh the existing collection's retained lifetime.
        case.now[0] += timedelta(minutes=1)
        again = await company(case, limit=100)
        assert again.context == first.context and again.exposures.total == 2
        assert len(again.exposures.items) == 2
        with pytest.raises(app.XrayServiceError) as capacity:
            await case.service.get_etf_overlap(
                case.principal,
                XRAY_ACCOUNT_ID,
                query=app.EtfOverlapQuery(
                    request=case.request(first.context.run_id),
                    options=app.Pairs(fund_ids=case.funds),
                ),
            )
        assert capacity.value.code is app.XrayServiceErrorCode.RESULT_TOO_LARGE
        with case.sessions() as session:
            after = tuple(
                session.execute(
                    select(
                        CollectionQuerySnapshotModel.id, CollectionQuerySnapshotModel.expires_at
                    ).order_by(CollectionQuerySnapshotModel.id)
                )
            )
            assert session.scalar(select(func.count()).select_from(EtfOverlapPairModel)) == 0
            assert session.scalar(select(func.count()).select_from(EtfOverlapEntityModel)) == 0
        assert after == original

    asyncio.run(run())


def test_expired_collection_cannot_resume_and_new_collection_keeps_retained_run(
    xray_read_case: XrayReadCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        case = xray_read_case
        # Create a historical collection through the real store; PostgreSQL's
        # immutable-delete guard must also see its TTL elapsed. Advancing only
        # the application clock would correctly fail that database guard.
        with monkeypatch.context() as historical_clock:
            historical_clock.setattr(collection_store, "_database_now", lambda _: case.now[0])
            first = await company(case, limit=1)
        assert first.exposures.next_cursor is not None
        with case.sessions() as session:
            owned_collection = CollectionQuerySnapshotModel.resource == "xray_exposures"
            expiry = session.scalar(
                select(func.max(CollectionQuerySnapshotModel.expires_at)).where(owned_collection)
            )
            original_ids = set(
                session.scalars(select(CollectionQuerySnapshotModel.id).where(owned_collection))
            )
            unrelated_ids = (
                set(session.scalars(select(CollectionQuerySnapshotModel.id))) - original_ids
            )
        assert expiry is not None
        case.now[0] = expiry + timedelta(seconds=1)
        with pytest.raises(app.XrayServiceError) as expired:
            await case.service.get_effective_exposure(
                case.principal,
                XRAY_ACCOUNT_ID,
                query=app.EffectiveExposureQuery(
                    request=case.request(first.context.run_id),
                    cursor=first.exposures.next_cursor,
                    limit=1,
                ),
            )
        assert expired.value.code is app.XrayServiceErrorCode.VALIDATION_FAILED
        fresh = await case.service.get_effective_exposure(
            case.principal,
            XRAY_ACCOUNT_ID,
            query=app.EffectiveExposureQuery(request=case.request(first.context.run_id), limit=1),
        )
        assert isinstance(fresh, app.ExposuresView)
        assert fresh.context == first.context and fresh.summary == first.summary
        assert fresh.exposures.items == first.exposures.items
        with case.sessions() as session:
            current_ids = set(session.scalars(select(CollectionQuerySnapshotModel.id)))
        assert not current_ids & original_ids
        assert unrelated_ids <= current_ids

    asyncio.run(run())


def test_capacity_rejection_commits_partial_expired_collection_cleanup(
    xray_read_case: XrayReadCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        case = xray_read_case
        with monkeypatch.context() as historical_clock:
            historical_clock.setattr(collection_store, "_database_now", lambda _: case.now[0])
            pair = await case.service.get_etf_overlap(
                case.principal,
                XRAY_ACCOUNT_ID,
                query=app.EtfOverlapQuery(
                    request=case.request(), options=app.Pairs(fund_ids=case.funds)
                ),
            )
        assert isinstance(pair, app.OverlapPairsView)
        with case.sessions() as session:
            expired_collection = session.scalar(
                select(CollectionQuerySnapshotModel).where(
                    CollectionQuerySnapshotModel.resource == "xray_pairs"
                )
            )
            assert expired_collection is not None
            identifier, expiry = expired_collection.id, expired_collection.expires_at
            active = session.scalar(select(func.count()).select_from(CollectionQuerySnapshotModel))
            assert session.scalar(select(func.count()).select_from(EtfOverlapPairModel)) == 1
        assert active is not None
        case.now[0] = expiry + timedelta(seconds=1)
        case.service = PostgresXrayService(
            sessions=case.sessions,
            cursor_signing_key=XRAY_CURSOR_KEY,
            clock=lambda: case.now[0],
            max_active_collection_snapshots_per_owner=active,
        )

        def collection_rows() -> tuple[object, ...]:
            # Read all physical columns, including licensed payload bytes, in a
            # fresh transaction after each service call has committed cleanup.
            with case.sessions() as session:
                return (
                    tuple(
                        session.execute(
                            select(*CollectionQuerySnapshotModel.__table__.c).where(
                                CollectionQuerySnapshotModel.id == identifier
                            )
                        )
                    ),
                    tuple(
                        session.execute(
                            select(*XrayCollectionBindingModel.__table__.c).where(
                                XrayCollectionBindingModel.collection_id == identifier
                            )
                        )
                    ),
                    tuple(
                        session.execute(
                            select(*CollectionQuerySnapshotMemberModel.__table__.c)
                            .where(CollectionQuerySnapshotMemberModel.snapshot_id == identifier)
                            .order_by(CollectionQuerySnapshotMemberModel.ordinal)
                        )
                    ),
                    tuple(
                        session.execute(
                            select(*EtfOverlapEntityModel.__table__.c)
                            .where(EtfOverlapEntityModel.collection_id == identifier)
                            .order_by(EtfOverlapEntityModel.id)
                        )
                    ),
                    tuple(
                        session.execute(
                            select(*EtfOverlapPairModel.__table__.c)
                            .where(EtfOverlapPairModel.collection_id == identifier)
                            .order_by(EtfOverlapPairModel.id)
                        )
                    ),
                )

        def progress() -> tuple[object, ...]:
            with case.sessions() as session:
                return (
                    collection_rows(),
                    tuple(
                        session.execute(
                            select(*Phase2RetentionSweepModel.__table__.c).order_by(
                                Phase2RetentionSweepModel.family,
                                Phase2RetentionSweepModel.scope_id,
                            )
                        )
                    ),
                )

        allowance = 8
        budgets: list[SourcePurgeBudget] = []

        def cleanup_budget() -> SourcePurgeBudget:
            budget = SourcePurgeBudget(rows_inspected=allowance, rows_removed=8)
            budgets.append(budget)
            return budget

        def assert_budget() -> None:
            budget = budgets[-1]
            assert 0 <= budget.rows_inspected <= allowance
            assert 0 <= budget.rows_removed <= 8
            assert 0 <= budget.bytes_inspected <= 64 * 1024 * 1024
            assert 0 <= budget.bytes_removed <= 64 * 1024 * 1024

        monkeypatch.setattr(read_store, "SourcePurgeBudget", cleanup_budget)
        original = collection_rows()
        assert original[0] and original[1] and original[2] and not original[3] and original[4]
        # Eight inspections cannot reserve one 48-inspection collection mutation.
        # Capacity rejection commits metadata progress but preserves every copy.
        with pytest.raises(app.XrayServiceError) as full:
            await company(case)
        assert full.value.code is app.XrayServiceErrorCode.RESULT_TOO_LARGE
        assert len(budgets) == 1
        assert_budget()
        assert budgets[-1].rows_removed == 8
        assert budgets[-1].bytes_inspected == budgets[-1].bytes_removed == 64 * 1024 * 1024
        assert collection_rows() == original

        # A legal small allowance clears the pair and commits that partial purge
        # even though the retained root still occupies capacity and denies a read.
        allowance = 64
        with pytest.raises(app.XrayServiceError) as partial:
            await company(case)
        assert partial.value.code is app.XrayServiceErrorCode.RESULT_TOO_LARGE
        assert len(budgets) == 2
        assert_budget()
        assert budgets[-1].rows_removed == 7
        assert collection_rows() == (*original[:4], ())
        with case.sessions() as session:
            assert session.get(CollectionQuerySnapshotModel, identifier) is not None
            assert session.scalar(select(func.count()).select_from(EtfOverlapPairModel)) == 0

        # Keep a bounded physical allowance and resume committed cleanup. A
        # zero-completion pass must still advance durable work before retrying.
        allowance = 256
        previous = progress()
        for _ in range(8):
            calls = len(budgets)
            try:
                resumed = await company(case)
            except app.XrayServiceError as pending:
                assert pending.code is app.XrayServiceErrorCode.RESULT_TOO_LARGE
                current = progress()
                assert current != previous
                previous = current
            else:
                assert len(budgets) == calls + 1
                assert_budget()
                break
            assert len(budgets) == calls + 1
            assert_budget()
        else:
            pytest.fail("Bounded cleanup did not release the expired collection capacity")
        assert resumed.context == pair.context and resumed.summary == pair.summary
        with case.sessions() as session:
            assert session.get(CollectionQuerySnapshotModel, identifier) is None
        assert collection_rows() == ((), (), (), (), ())

    asyncio.run(run())
