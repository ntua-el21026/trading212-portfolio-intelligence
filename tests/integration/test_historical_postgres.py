"""Real PostgreSQL historical capture, evidence and immutable source boundaries."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import historical as app
from trading212_application.historical_evidence import HistoricalPolicyRegistration
from trading212_domain import historical as d
from trading212_domain.sources import LicensePermission, SourceSelectionPolicy
from trading212_domain.values import CurrencyCode
from trading212_persistence import create_database_engine, create_session_factory
from trading212_persistence import historical_models as hm
from trading212_persistence.historical_store import PostgresHistoricalStore
from trading212_persistence.models import BrokerAccountModel, BrokerConnectionModel
from trading212_worker.seed import seed_materialized_synthetic

from tests.integration.test_sources_postgres import KEY, NOW, Case, source_case

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def historical_database() -> Iterator[tuple[Engine, sessionmaker[Session]]]:
    name = "t212pi_historical_" + uuid4().hex[:12]
    parsed = make_url(
        os.environ.get(
            "TEST_DATABASE_URL", "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio"
        )
    )
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
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")
        command.check(cfg)
        asyncio.run(seed_materialized_synthetic(url, app_environment="test"))
        engine = create_database_engine(url)
        yield engine, create_session_factory(engine)
    finally:
        if engine is not None:
            engine.dispose()
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


async def historical_case(
    sessions: sessionmaker[Session],
) -> tuple[Case, str, PostgresHistoricalStore]:
    case = await source_case(sessions)
    account, connection = uuid4(), uuid4()
    with sessions.begin() as session:
        session.add(
            BrokerConnectionModel(
                id=connection,
                owner_id=UUID(case.principal.owner_id),
                provider="synthetic",
                environment="synthetic",
                status="active",
            )
        )
        session.flush()
        session.add(
            BrokerAccountModel(
                id=account,
                connection_id=connection,
                provider_account_id=str(account),
                account_type="invest",
                base_currency="EUR",
                display_name="Synthetic historical test",
                status="active",
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
        )
    store = PostgresHistoricalStore(sessions, cursor_signing_key=KEY, clock=lambda: case.now[0])
    return case, str(account), store


def policy(case: Case) -> HistoricalPolicyRegistration:
    return HistoricalPolicyRegistration(
        id=str(uuid4()),
        key="history-v1",
        effective_at=NOW - timedelta(days=30),
        accounting_policy=d.HistoricalAccountingPolicy(),
        source_policy=SourceSelectionPolicy(
            version="historical-source-v1",
            provider_priority=(case.series.provider_id,),
            max_age_seconds=86400,
            allow_closed_session_carry=True,
        ),
        reporting_calendar_ref=d.CalendarRef(id=case.calendar.id, version=case.calendar.version),
        price_series_ids=(case.series.id,),
    )


def selection(registration: HistoricalPolicyRegistration | None) -> d.HistoricalSelectionRequest:
    return d.HistoricalSelectionRequest(
        window=d.HistoricalWindow(
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 3),
            source_cutoff_at=NOW,
            reporting_currency=CurrencyCode("EUR"),
        ),
        accounting_policy=d.HistoricalAccountingPolicy(),
        source_policy=None if registration is None else registration.source_policy,
        reporting_calendar_ref=None
        if registration is None
        else registration.reporting_calendar_ref,
    )


def test_missing_setup_captures_truthful_unavailable_and_replays_after_new_engine(
    historical_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    engine, sessions = historical_database

    async def run() -> None:
        case, account, store = await historical_case(sessions)
        first = await store.capture(case.principal, account, request=selection(None))
        assert isinstance(first.input.opening, d.UnavailableHistoricalOpening)
        assert first.input.selection.source_policy is None
        assert first.input.calendars == ()
        second = await store.capture(case.principal, account, request=selection(None))
        assert second == first
        fresh = create_database_engine(engine.url.render_as_string(hide_password=False))
        try:
            replay = await PostgresHistoricalStore(
                create_session_factory(fresh), cursor_signing_key=KEY, clock=lambda: NOW
            ).load(case.principal, first.id)
            assert replay == first
        finally:
            fresh.dispose()

    asyncio.run(run())


def test_policy_registration_retains_first_knowledge_and_concurrent_capture_identity(
    historical_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = historical_database

    async def run() -> None:
        case, account, store = await historical_case(sessions)
        registration = policy(case)
        first = await store.register_historical_policy(
            case.principal,
            account,
            registration,
            idempotency_key="historical-policy",
            correlation_id="historical-test",
        )
        case.now[0] += timedelta(hours=1)
        repeated = await store.register_historical_policy(
            case.principal,
            account,
            registration,
            idempotency_key="historical-policy",
            correlation_id="historical-test",
        )
        assert repeated == first and repeated.first_observed_at == NOW
        await case.service.ingest_price_history(
            case.principal,
            case.request,
            case.pages,
            idempotency_key="historical-price",
            correlation_id="historical-test",
        )
        # Prices were actually received after the first cutoff and must not be backdated.
        old = await store.capture(case.principal, account, request=selection(registration))
        assert old.input.price_snapshots == ()
        current = replace(
            selection(registration),
            window=replace(selection(registration).window, source_cutoff_at=case.now[0]),
        )
        a, b = await asyncio.gather(
            store.capture(case.principal, account, request=current),
            store.capture(case.principal, account, request=current),
        )
        assert a == b and a.id != old.id and len(a.input.price_snapshots) == 1
        with sessions() as session:
            count = session.scalar(
                select(func.count())
                .select_from(hm.HistoricalInputModel)
                .where(hm.HistoricalInputModel.owner_id == UUID(case.principal.owner_id))
            )
            assert count == 2

    asyncio.run(run())


def test_capture_dependencies_reauthorize_current_license_before_replay(
    historical_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = historical_database

    async def run() -> None:
        case, account, store = await historical_case(sessions)
        registration = policy(case)
        await store.register_historical_policy(
            case.principal,
            account,
            registration,
            idempotency_key="historical-policy",
            correlation_id="historical-test",
        )
        await case.service.ingest_price_history(
            case.principal,
            case.request,
            case.pages,
            idempotency_key="historical-price",
            correlation_id="historical-test",
        )
        captured = await store.capture(case.principal, account, request=selection(registration))
        case.now[0] += timedelta(hours=1)
        license = replace(
            case.license,
            id=str(uuid4()),
            version="display-denied",
            effective_at=case.now[0],
            display=LicensePermission.DENIED,
        )
        await case.service.register_source_license(
            case.principal,
            license,
            idempotency_key="license-denied",
            correlation_id="historical-test",
        )
        with pytest.raises(app.HistoricalServiceError) as denied:
            await store.load(case.principal, captured.id)
        assert denied.value.code is app.HistoricalServiceErrorCode.ACCESS_DENIED
        assert denied.value.__cause__ is None and denied.value.__context__ is None

    asyncio.run(run())


def test_capture_owner_concealment_and_database_immutability(
    historical_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = historical_database

    async def run() -> None:
        case, account, store = await historical_case(sessions)
        foreign, _, _ = await historical_case(sessions)
        captured = await store.capture(case.principal, account, request=selection(None))
        with pytest.raises(app.HistoricalServiceError) as denied:
            await store.load(foreign.principal, captured.id)
        assert denied.value.code is app.HistoricalServiceErrorCode.NOT_FOUND
        with sessions.begin() as session, pytest.raises(IntegrityError):
            session.execute(
                update(hm.HistoricalInputModel)
                .where(hm.HistoricalInputModel.id == UUID(captured.id))
                .values(reporting_currency="USD")
            )
        assert await store.load(case.principal, captured.id) == captured

    asyncio.run(run())


def test_retention_purges_copied_inputs_and_results_but_preserves_digests(
    historical_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    from trading212_persistence.historical_service import PostgresHistoricalService
    from trading212_persistence.planning_models import AnalyticsRunModel

    _, sessions = historical_database

    async def run() -> None:
        case, account, store = await historical_case(sessions)
        registration = policy(case)
        await store.register_historical_policy(
            case.principal,
            account,
            registration,
            idempotency_key="retention-policy",
            correlation_id="retention-test",
        )
        snapshot = await case.service.ingest_price_history(
            case.principal,
            case.request,
            case.pages,
            idempotency_key="retention-price",
            correlation_id="retention-test",
        )
        captured = await store.capture(case.principal, account, request=selection(registration))
        service = PostgresHistoricalService(
            sessions, cursor_signing_key=KEY, clock=lambda: case.now[0]
        )
        result = await service.get_performance_series(
            case.principal,
            account,
            query=app.PerformanceSeriesQuery(
                window=selection(registration).window,
                input_snapshot_id=captured.id,
            ),
        )
        with sessions() as session:
            retained_run = session.scalar(
                select(hm.HistoricalRunModel).where(
                    hm.HistoricalRunModel.input_id == UUID(captured.id)
                )
            )
            assert retained_run is not None
            analytics_id = retained_run.analytics_run_id
            raw = session.get(AnalyticsRunModel, analytics_id)
            assert raw is not None and snapshot.id.encode() in raw.canonical_input
            financial_digest = raw.content_digest
        # The public SQL boundary cannot empty a live capture or authorize fake retention.
        with sessions.begin() as session, pytest.raises(IntegrityError):
            session.execute(
                update(hm.HistoricalInputModel)
                .where(hm.HistoricalInputModel.id == UUID(captured.id))
                .values(canonical_input=b"")
            )
        with sessions.begin() as session, pytest.raises(IntegrityError):
            dep = session.scalar(
                select(hm.HistoricalDependencyModel).where(
                    hm.HistoricalDependencyModel.input_id == UUID(captured.id),
                    hm.HistoricalDependencyModel.price_snapshot_id == UUID(snapshot.id),
                )
            )
            assert dep is not None
            session.add(
                hm.HistoricalRetentionEventModel(
                    owner_id=UUID(case.principal.owner_id),
                    input_id=UUID(captured.id),
                    dependency_id=dep.id,
                    removed_at=NOW,
                    reason="retention_removed",
                )
            )
            session.flush()
        case.now[0] += timedelta(days=400)
        assert await case.service.expire_source_snapshots(limit=1000) >= 1
        with sessions() as session:
            retained = session.get(hm.HistoricalInputModel, UUID(captured.id))
            raw = session.get(AnalyticsRunModel, analytics_id)
            assert retained is not None and raw is not None
            assert retained.canonical_input == raw.canonical_input == raw.canonical_result == b""
            assert retained.input_digest == captured.input_digest
            assert raw.content_digest == financial_digest == result.context.content_digest
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(hm.HistoricalRetentionEventModel)
                    .where(hm.HistoricalRetentionEventModel.input_id == retained.id)
                )
                == 1
            )
        refreshed = replace(case.principal, expires_at=case.now[0] + timedelta(hours=1))
        with pytest.raises(app.HistoricalServiceError) as denied:
            await store.load(refreshed, captured.id)
        assert denied.value.code is app.HistoricalServiceErrorCode.ACCESS_DENIED
        assert await case.service.expire_source_snapshots(limit=1000) == 0

    asyncio.run(run())


@pytest.fixture(scope="module")
def historical_seed(
    historical_database: tuple[Engine, sessionmaker[Session]],
) -> dict[str, str]:
    from trading212_worker.historical_seed import seed_historical_scenarios

    return asyncio.run(seed_historical_scenarios(historical_database[1], app_environment="test"))


def test_full_history_composite_pages_and_restart_preserve_immutable_results(
    historical_database: tuple[Engine, sessionmaker[Session]],
    historical_seed: dict[str, str],
) -> None:
    from decimal import Decimal

    from trading212_application import sources as sources_app
    from trading212_domain.historical_results import ComparisonOptions
    from trading212_domain.serialization import canonical_json
    from trading212_persistence.historical_service import PostgresHistoricalService
    from trading212_persistence.source_service import PostgresSourceService
    from trading212_worker.historical_seed import history_principal

    engine, sessions = historical_database

    async def run() -> None:
        principal = history_principal(NOW)
        account = historical_seed["annual_account_id"]
        service = PostgresHistoricalService(sessions, cursor_signing_key=KEY, clock=lambda: NOW)
        window = d.HistoricalWindow(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            source_cutoff_at=NOW,
            reporting_currency=CurrencyCode("EUR"),
        )
        performance = await service.get_performance_series(
            principal, account, query=app.PerformanceSeriesQuery(window=window, limit=2)
        )
        assert performance.context.availability is d.HistoricalAvailability.AVAILABLE
        assert performance.summary.deposits.value is not None
        assert performance.summary.deposits.value.amount == Decimal("200")
        assert performance.summary.withdrawals.value is not None
        assert performance.summary.withdrawals.value.amount == Decimal("100")
        assert performance.points.total == 12 and performance.points.next_cursor is not None
        continuation = app.PerformanceSeriesQuery(
            window=window,
            limit=2,
            cursor=performance.points.next_cursor,
            input_snapshot_id=performance.context.input_snapshot_id,
        )
        page = await service.get_performance_series(principal, account, query=continuation)
        assert page.points.items[0].date > performance.points.items[-1].date
        query = app.BenchmarkComparisonQuery(
            window=window, benchmark_version_id=historical_seed["annual_benchmark_version_id"]
        )
        benchmark = await service.get_benchmark_comparison(principal, account, query=query)
        assert benchmark.context.availability is d.HistoricalAvailability.AVAILABLE
        assert benchmark.composite_snapshot is not None
        sources = PostgresSourceService(
            sessions=sessions, cursor_signing_key=KEY, clock=lambda: NOW
        )
        header = await sources.get_benchmark_snapshot(
            principal, benchmark.composite_snapshot.id, account_id=account
        )
        assert isinstance(header, sources_app.CompositeBenchmarkSnapshotHeaderView)
        assert canonical_json(header) == canonical_json(benchmark.composite_snapshot)
        later = PostgresHistoricalService(
            sessions, cursor_signing_key=KEY, clock=lambda: NOW + timedelta(hours=1)
        )
        daily = await later.get_benchmark_comparison(
            principal,
            account,
            query=replace(
                query,
                input_snapshot_id=benchmark.context.input_snapshot_id,
                options=ComparisonOptions(frequency=d.HistoricalFrequency.DAILY),
            ),
        )
        assert daily.context.run_id != benchmark.context.run_id
        assert daily.context.calculated_at > benchmark.context.calculated_at
        assert daily.composite_snapshot == benchmark.composite_snapshot
        first = await sources.list_benchmark_observations(
            principal,
            header.id,
            query=sources_app.SourceObservationQuery(account_id=account, limit=2),
        )
        assert isinstance(first, sources_app.CompositeBenchmarkObservationPageView)
        assert first.next_cursor is not None and first.total == header.observation_count
        next_query = sources_app.SourceObservationQuery(
            account_id=account, limit=2, cursor=first.next_cursor
        )
        second = await sources.list_benchmark_observations(principal, header.id, query=next_query)
        fresh_engine = create_database_engine(engine.url.render_as_string(hide_password=False))
        try:
            fresh_sessions = create_session_factory(fresh_engine)
            fresh_service = PostgresHistoricalService(
                fresh_sessions, cursor_signing_key=KEY, clock=lambda: NOW
            )
            assert (
                await fresh_service.get_performance_series(principal, account, query=continuation)
                == page
            )
            replay = await fresh_service.get_benchmark_comparison(
                principal,
                account,
                query=replace(query, input_snapshot_id=benchmark.context.input_snapshot_id),
            )
            assert replay == benchmark
            fresh_sources = PostgresSourceService(
                sessions=fresh_sessions, cursor_signing_key=KEY, clock=lambda: NOW
            )
            assert (
                await fresh_sources.list_benchmark_observations(
                    principal, header.id, query=next_query
                )
                == second
            )
        finally:
            fresh_engine.dispose()

    asyncio.run(run())


def test_historical_seed_repeat_keeps_all_published_knowledge_and_financial_content(
    historical_database: tuple[Engine, sessionmaker[Session]],
    historical_seed: dict[str, str],
) -> None:
    from trading212_worker.historical_seed import seed_historical_scenarios

    _, sessions = historical_database
    with sessions() as session:
        before = tuple(
            session.execute(
                select(
                    hm.HistoricalEvidenceModel.id,
                    hm.HistoricalEvidenceModel.first_observed_at,
                    hm.HistoricalEvidenceModel.content_digest,
                ).order_by(hm.HistoricalEvidenceModel.id)
            )
        )
    assert (
        asyncio.run(seed_historical_scenarios(sessions, app_environment="test")) == historical_seed
    )
    with sessions() as session:
        after = tuple(
            session.execute(
                select(
                    hm.HistoricalEvidenceModel.id,
                    hm.HistoricalEvidenceModel.first_observed_at,
                    hm.HistoricalEvidenceModel.content_digest,
                ).order_by(hm.HistoricalEvidenceModel.id)
            )
        )
    assert after == before


def test_explicit_configuration_cannot_cross_its_first_knowledge_cutoff(
    historical_database: tuple[Engine, sessionmaker[Session]],
    historical_seed: dict[str, str],
) -> None:
    from datetime import UTC, datetime

    from trading212_persistence.historical_service import PostgresHistoricalService
    from trading212_worker.historical_seed import history_principal

    _, sessions = historical_database

    async def run() -> None:
        service = PostgresHistoricalService(sessions, cursor_signing_key=KEY, clock=lambda: NOW)
        window = d.HistoricalWindow(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            source_cutoff_at=datetime(2026, 8, 30, tzinfo=UTC),
            reporting_currency=CurrencyCode("EUR"),
        )
        principal = history_principal(NOW)
        account = historical_seed["annual_account_id"]
        with sessions() as session:
            before = session.scalar(select(func.count()).select_from(hm.HistoricalInputModel))
        with pytest.raises(app.HistoricalServiceError) as benchmark:
            await service.get_benchmark_comparison(
                principal,
                account,
                query=app.BenchmarkComparisonQuery(
                    window=window,
                    benchmark_version_id=historical_seed["annual_benchmark_version_id"],
                ),
            )
        assert benchmark.value.code is app.HistoricalServiceErrorCode.VALIDATION_FAILED
        with pytest.raises(app.HistoricalServiceError) as target:
            await service.get_attribution_summary(
                principal,
                account,
                query=app.AttributionQuery(
                    window=window,
                    target_version_id=historical_seed["annual_target_version_id"],
                    grouping_policy="explicit_comparison",
                ),
            )
        assert target.value.code is app.HistoricalServiceErrorCode.VALIDATION_FAILED
        with sessions() as session:
            assert (
                session.scalar(select(func.count()).select_from(hm.HistoricalInputModel)) == before
            )

    asyncio.run(run())


def test_activity_proofs_reject_future_intervals_and_mutation_of_pinned_runs(
    historical_database: tuple[Engine, sessionmaker[Session]],
    historical_seed: dict[str, str],
) -> None:
    from trading212_persistence.models import IngestionRunModel, SourceRecordOccurrenceModel

    _, sessions = historical_database
    with sessions() as session:
        evidence = session.scalar(
            select(hm.HistoricalEvidenceModel)
            .join(
                hm.HistoricalActivityCoverageModel,
                hm.HistoricalActivityCoverageModel.evidence_id == hm.HistoricalEvidenceModel.id,
            )
            .where(
                hm.HistoricalEvidenceModel.broker_account_id
                == UUID(historical_seed["annual_account_id"])
            )
        )
        assert evidence is not None
        proof = session.scalar(
            select(hm.HistoricalActivityCoverageModel).where(
                hm.HistoricalActivityCoverageModel.evidence_id == evidence.id
            )
        )
        assert proof is not None
        run = session.get(IngestionRunModel, proof.ingestion_run_id)
        assert run is not None
        original = (run.status, tuple(run.effective_capabilities), run.completed_at)
        occurrence = session.scalar(
            select(SourceRecordOccurrenceModel).where(
                SourceRecordOccurrenceModel.ingestion_run_id == run.id
            )
        )
        assert occurrence is not None
        occurrence_id, observed_at = occurrence.id, occurrence.observed_at
    with (
        pytest.raises(IntegrityError, match="Pinned historical activity proof is immutable"),
        sessions.begin() as session,
    ):
        session.execute(
            update(IngestionRunModel)
            .where(IngestionRunModel.id == run.id)
            .values(effective_capabilities=[])
        )
    with (
        pytest.raises(IntegrityError, match="Pinned historical activity proof is immutable"),
        sessions.begin() as session,
    ):
        session.execute(
            update(SourceRecordOccurrenceModel)
            .where(SourceRecordOccurrenceModel.id == occurrence_id)
            .values(observed_at=observed_at + timedelta(seconds=1))
        )
    with (
        pytest.raises(IntegrityError, match="Historical activity interval is unsupported"),
        sessions.begin() as session,
    ):
        parent = hm.HistoricalEvidenceModel(
            id=uuid4(),
            owner_id=evidence.owner_id,
            broker_account_id=evidence.broker_account_id,
            key="unsupported-coverage-" + uuid4().hex,
            first_observed_at=evidence.first_observed_at,
            content_digest=evidence.content_digest,
            canonical_evidence=evidence.canonical_evidence,
            sealed=False,
        )
        session.add(parent)
        session.flush()
        session.add(
            hm.HistoricalActivityCoverageModel(
                owner_id=evidence.owner_id,
                evidence_id=parent.id,
                ingestion_run_id=run.id,
                capability=proof.capability,
                start_at=proof.start_at,
                end_at=evidence.first_observed_at,
                first_observed_at=evidence.first_observed_at,
                coverage_complete=True,
            )
        )
        session.flush()
    with sessions() as session:
        retained = session.get(IngestionRunModel, run.id)
        assert retained is not None
        assert (
            retained.status,
            tuple(retained.effective_capabilities),
            retained.completed_at,
        ) == original
        retained_occurrence = session.get(SourceRecordOccurrenceModel, occurrence_id)
        assert retained_occurrence is not None and retained_occurrence.observed_at == observed_at
