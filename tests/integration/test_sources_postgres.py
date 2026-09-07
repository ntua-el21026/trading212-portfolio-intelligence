"""Real PostgreSQL reference-source ownership, retention, replay and publication boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.source_policy import assess_source_coverage, select_price
from trading212_application import sources as app
from trading212_application.queries import CursorValidationError
from trading212_application.source_ingestion import (
    SourceInstrumentMapping,
    SourceProviderRegistration,
)
from trading212_application.source_providers import (
    PriceHistoryPage,
    PriceHistoryRequest,
    SourceCapability,
)
from trading212_domain import CurrencyCode, QualityState, build_synthetic_identity
from trading212_domain.errors import DomainError
from trading212_domain.source_details import (
    SourceIdentifier,
    SourceIdentifierKind,
    SourceMappingState,
)
from trading212_domain.sources import (
    BenchmarkComponent,
    BenchmarkContent,
    BenchmarkRebalanceRule,
    LicensePermission,
    MarketSession,
    PriceBasis,
    PriceObservation,
    PriceSnapshot,
    SourceCalendar,
    SourceLicense,
    SourcePeriod,
    SourceProvenance,
    SourceSelectionPolicy,
    SourceSeries,
    SourceSeriesKind,
    source_snapshot_digest,
)
from trading212_persistence import create_database_engine, create_session_factory
from trading212_persistence.models import CollectionQuerySnapshotModel, OwnerModel
from trading212_persistence.source_models import (
    SOURCE_MODELS,
    BenchmarkComponentModel,
    BenchmarkVersionModel,
    MarketDataInstrumentModel,
    PriceObservationModel,
    PriceSnapshotModel,
    SourceCommandIdentityModel,
    SourceMappingCandidateModel,
    SourceOwned,
    SourceRetrievalOccurrenceModel,
)
from trading212_persistence.source_service import PostgresSourceService
from trading212_security.principals import Principal, Scope
from trading212_worker.seed import SEED_TIME, seed_materialized_synthetic
from trading212_worker.source_seed import seed_source_scenarios

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
KEY = b"source-postgres-synthetic-cursor-key"


@pytest.fixture(scope="module")
def sources_database() -> Iterator[tuple[Engine, sessionmaker[Session]]]:
    name = "t212pi_sources_" + uuid4().hex[:12]
    admin = "postgresql://portfolio:portfolio@127.0.0.1:5432/postgres"
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/" + name
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


@dataclass
class Case:
    sessions: sessionmaker[Session]
    principal: Principal
    service: PostgresSourceService
    now: list[datetime]
    license: SourceLicense
    series: SourceSeries
    calendar: SourceCalendar
    request: PriceHistoryRequest
    pages: tuple[PriceHistoryPage, ...]


async def source_case(sessions: sessionmaker[Session], *, retention_days: int = 365) -> Case:
    owner = uuid4()
    provider = uuid4()
    license_id = uuid4()
    mapping_id = uuid4()
    series_id = uuid4()
    with sessions.begin() as session:
        session.add(OwnerModel(id=owner, display_name="Synthetic source test"))
    now = [NOW]
    principal = Principal(
        "source-tests",
        str(owner),
        "test",
        "test",
        frozenset(Scope),
        NOW - timedelta(days=100),
        NOW + timedelta(days=500),
    )
    service = PostgresSourceService(sessions=sessions, cursor_signing_key=KEY, clock=lambda: now[0])
    await service.configure_source_provider(
        principal,
        SourceProviderRegistration(
            id=str(provider),
            key="synthetic-source",
            name="Synthetic source",
            adapter_version="synthetic-v1",
            configuration_state=app.ProviderConfigurationState.CONFIGURED,
            synthetic=True,
            capabilities=(SourceCapability.PRICE_HISTORY,),
            supported_price_bases=(PriceBasis.RAW_CLOSE,),
        ),
        idempotency_key="provider",
        correlation_id="source-test",
    )
    license = SourceLicense(
        id=str(license_id),
        provider_id=str(provider),
        version="v1",
        effective_at=NOW - timedelta(days=30),
        store=LicensePermission.ALLOWED,
        display=LicensePermission.ALLOWED,
        report=LicensePermission.DENIED,
        export=LicensePermission.UNKNOWN,
        retention_days=retention_days,
        attribution="Synthetic source",
        evidence_key="synthetic-license",
    )
    await service.register_source_license(
        principal, license, idempotency_key="license", correlation_id="source-test"
    )
    period = SourcePeriod(start=date(2026, 9, 1), end=date(2026, 9, 3))
    calendar = SourceCalendar(
        id="synthetic-calendar",
        version="v1",
        timezone="UTC",
        period=period,
        sessions=tuple(
            MarketSession(
                session_date=date(2026, 9, i), close_at=datetime(2026, 9, i, 16, tzinfo=UTC)
            )
            for i in range(1, 4)
        ),
    )
    await service.register_source_calendar(
        principal, calendar, idempotency_key="calendar", correlation_id="source-test"
    )
    identity = build_synthetic_identity()
    mapping = SourceInstrumentMapping(
        id=str(mapping_id),
        provider_id=str(provider),
        provider_key="synthetic-security",
        version="v1",
        state=SourceMappingState.RESOLVED,
        identifier=SourceIdentifier(
            kind=SourceIdentifierKind.PROVIDER_KEY, value="synthetic-security"
        ),
        currency=CurrencyCode("EUR"),
        asset_type="equity",
        evidence_key="synthetic-mapping",
        valid_from=NOW - timedelta(days=30),
        instrument_id=str(identity.instrument.id),
        listing_id=str(identity.listing.id),
    )
    await service.register_source_mapping(
        principal, mapping, idempotency_key="mapping", correlation_id="source-test"
    )
    series = SourceSeries(
        id=str(series_id),
        owner_id=str(owner),
        provider_id=str(provider),
        license_version_id=license.id,
        kind=SourceSeriesKind.SECURITY_PRICE,
        provider_key="synthetic-security",
        mapping_version="v1",
        basis=PriceBasis.RAW_CLOSE,
        currency=CurrencyCode("EUR"),
        calendar_id=calendar.id,
        calendar_version=calendar.version,
        mapping_id=mapping.id,
        instrument_id=mapping.instrument_id,
        listing_id=mapping.listing_id,
    )
    await service.register_source_series(
        principal, series, idempotency_key="series", correlation_id="source-test"
    )
    observations = tuple(
        PriceObservation(
            session_date=x.session_date, effective_at=x.close_at, value=Decimal(100 + i)
        )
        for i, x in enumerate(calendar.sessions)
    )
    coverage = assess_source_coverage(calendar, period, observations)
    provenance = SourceProvenance(
        provider_id=str(provider),
        license_version_id=license.id,
        adapter_version="synthetic-v1",
        schema_version="1",
        source_revision="v1",
        revision_order=1,
        effective_at=calendar.sessions[-1].close_at,
        first_observed_at=NOW - timedelta(days=2),
        synthetic=True,
    )
    pages = (
        PriceHistoryPage(
            series=series,
            provenance=provenance,
            period=period,
            coverage=coverage,
            observations=observations[:1],
            continuation="page2",
        ),
        PriceHistoryPage(
            series=series,
            provenance=replace(provenance, first_observed_at=NOW - timedelta(days=1)),
            period=period,
            coverage=coverage,
            observations=observations[1:],
        ),
    )
    return Case(
        sessions,
        principal,
        service,
        now,
        license,
        series,
        calendar,
        PriceHistoryRequest(series=series, period=period, source_cutoff_at=NOW),
        pages,
    )


async def ingest(case: Case, *, key: str = "ingest") -> PriceSnapshot:
    return await case.service.ingest_price_history(
        case.principal,
        case.request,
        case.pages,
        idempotency_key=key,
        correlation_id="source-test",
    )


def count(
    sessions: sessionmaker[Session],
    model: type[SourceOwned] | type[CollectionQuerySnapshotModel],
    owner: str,
) -> int:
    with sessions() as session:
        return int(
            session.scalar(
                select(func.count()).select_from(model).where(model.owner_id == UUID(owner))
            )
            or 0
        )


def test_real_seed_idempotent_and_restarted_public_reads(
    sources_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = sources_database

    async def scenario() -> None:
        first = await seed_source_scenarios(sessions, app_environment="test", at=SEED_TIME)
        with sessions() as session:
            before = {
                m.__tablename__: session.scalar(select(func.count()).select_from(m))
                for m in SOURCE_MODELS
            }
        second = await seed_source_scenarios(sessions, app_environment="test", at=SEED_TIME)
        with sessions() as session:
            after = {
                m.__tablename__: session.scalar(select(func.count()).select_from(m))
                for m in SOURCE_MODELS
            }
        assert first == second and before == after
        with sessions() as session:
            mapping = session.scalar(
                select(MarketDataInstrumentModel).where(
                    MarketDataInstrumentModel.owner_id == build_synthetic_identity().owner.id
                )
            )
            assert mapping is not None
            candidate = session.scalar(
                select(SourceMappingCandidateModel).where(
                    SourceMappingCandidateModel.mapping_id == mapping.id
                )
            )
            assert candidate is not None
            assert (mapping.evidence_key, mapping.valid_from, mapping.valid_to) == (
                candidate.evidence_key,
                candidate.valid_from,
                candidate.valid_to,
            )
        identity = build_synthetic_identity()
        principal = Principal(
            "test",
            str(identity.owner.id),
            "test",
            "test",
            frozenset(Scope),
            NOW - timedelta(days=1),
            NOW + timedelta(days=1),
        )
        service = PostgresSourceService(
            sessions=sessions, cursor_signing_key=KEY, clock=lambda: NOW
        )
        market = await service.get_market_source_status(
            principal, str(identity.account.id), query=app.SourceStatusQuery(limit=1)
        )
        assert market.series.total == 3 and market.series.next_cursor
        continued = await service.get_market_source_status(
            principal,
            str(identity.account.id),
            query=app.SourceStatusQuery(limit=1, cursor=market.series.next_cursor),
        )
        assert continued.series.items[0].series.id != market.series.items[0].series.id
        definitions = await service.list_benchmark_definitions(
            principal, query=app.BenchmarkDefinitionQuery()
        )
        detail = await service.get_benchmark_definition(
            principal, definitions.items[0].id, query=app.BenchmarkDetailQuery()
        )
        assert detail.versions.total == 1
        with pytest.raises(RuntimeError, match="local/test"):
            await seed_source_scenarios(sessions, app_environment="production", at=NOW)

    asyncio.run(scenario())


def test_dedup_preserves_first_knowledge_and_corrections_are_cutoff_bound(
    sources_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = sources_database

    async def scenario() -> None:
        case = await source_case(sessions)
        original = await ingest(case)
        assert original.provenance.first_observed_at == NOW
        again = await ingest(case)
        assert (
            again == original
            and count(sessions, SourceRetrievalOccurrenceModel, case.principal.owner_id) == 1
        )
        case.now[0] += timedelta(hours=1)
        repeated = await ingest(case, key="new-retrieval")
        assert (
            repeated == original
            and count(sessions, SourceRetrievalOccurrenceModel, case.principal.owner_id) == 2
        )
        corrected_pages = tuple(
            replace(
                page,
                provenance=replace(page.provenance, source_revision="v2", revision_order=2),
                observations=tuple(
                    replace(x, value=Decimal(10) + (x.value if x.value is not None else Decimal(0)))
                    for x in page.observations
                ),
            )
            for page in case.pages
        )
        correction = await case.service.ingest_price_history(
            case.principal,
            case.request,
            corrected_pages,
            idempotency_key="correction",
            correlation_id="source-test",
        )
        assert correction.id != original.id and source_snapshot_digest(
            correction
        ) != source_snapshot_digest(original)
        policy = SourceSelectionPolicy(
            version="v1", provider_priority=(case.series.provider_id,), max_age_seconds=999999
        )
        selected = select_price(
            (original, correction),
            series_id=case.series.id,
            at=case.calendar.sessions[-1].close_at,
            source_cutoff_at=NOW,
            policy=policy,
            calendar=case.calendar,
        )
        assert selected.selected is not None
        assert selected.value == Decimal(102) and selected.selected.snapshot_id == original.id
        later = select_price(
            (original, correction),
            series_id=case.series.id,
            at=case.calendar.sessions[-1].close_at,
            source_cutoff_at=case.now[0],
            policy=policy,
            calendar=case.calendar,
        )
        assert later.selected is not None
        assert later.value == Decimal(112) and later.selected.snapshot_id == correction.id

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fault", ["incomplete", "duplicate", "wrong-revision", "wrong-coverage", "future"]
)
def test_invalid_page_chains_leave_no_snapshot_command_or_occurrence(
    sources_database: tuple[Engine, sessionmaker[Session]], fault: str
) -> None:
    _, sessions = sources_database

    async def scenario() -> None:
        case = await source_case(sessions)
        pages = case.pages
        if fault == "incomplete":
            pages = pages[:1]
        elif fault == "duplicate":
            pages = (pages[0], replace(pages[1], observations=pages[0].observations))
        elif fault == "wrong-revision":
            pages = (
                pages[0],
                replace(
                    pages[1], provenance=replace(pages[1].provenance, source_revision="changed")
                ),
            )
        elif fault == "wrong-coverage":
            pages = tuple(
                replace(
                    p, coverage=replace(p.coverage, expected_count=4, quality=QualityState.PARTIAL)
                )
                for p in pages
            )
        elif fault == "future":
            pages = (
                replace(
                    pages[0],
                    observations=(
                        replace(pages[0].observations[0], effective_at=NOW + timedelta(days=1)),
                    ),
                ),
                pages[1],
            )
        before = count(sessions, SourceCommandIdentityModel, case.principal.owner_id)
        with pytest.raises((app.SourceServiceError, DomainError)):
            await case.service.ingest_price_history(
                case.principal,
                case.request,
                pages,
                idempotency_key="invalid",
                correlation_id="source-test",
            )
        assert count(sessions, PriceSnapshotModel, case.principal.owner_id) == 0
        assert count(sessions, SourceRetrievalOccurrenceModel, case.principal.owner_id) == 0
        assert count(sessions, SourceCommandIdentityModel, case.principal.owner_id) == before

    asyncio.run(scenario())


def test_license_revocation_before_header_page_cursor_and_idempotent_replay(
    sources_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = sources_database

    async def scenario() -> None:
        case = await source_case(sessions)
        snapshot = await ingest(case)
        page = await case.service.list_price_observations(
            case.principal, snapshot.id, query=app.SourceObservationQuery(limit=1)
        )
        assert page.next_cursor
        denied = replace(
            case.license,
            id=str(uuid4()),
            version="deny-v2",
            effective_at=NOW,
            display=LicensePermission.DENIED,
            store=LicensePermission.DENIED,
        )
        await case.service.register_source_license(
            case.principal, denied, idempotency_key="revoke", correlation_id="source-test"
        )
        for operation in (
            case.service.get_price_snapshot(case.principal, snapshot.id),
            case.service.list_price_observations(
                case.principal,
                snapshot.id,
                query=app.SourceObservationQuery(limit=1, cursor=page.next_cursor),
            ),
            ingest(case),
        ):
            with pytest.raises(app.SourceServiceError) as caught:
                await operation
            assert caught.value.code is app.SourceServiceErrorCode.ACCESS_DENIED

    asyncio.run(scenario())


def test_immutable_database_guards_owner_links_and_fresh_service_persistence(
    sources_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = sources_database

    async def scenario() -> None:
        case = await source_case(sessions)
        snapshot = await ingest(case)
        with sessions() as session:
            observation = session.scalar(
                select(PriceObservationModel).where(
                    PriceObservationModel.snapshot_id == UUID(snapshot.id)
                )
            )
            assert observation is not None
            observation_id = observation.id
        for statement in (
            update(PriceSnapshotModel)
            .where(PriceSnapshotModel.id == UUID(snapshot.id))
            .values(first_observed_at=NOW - timedelta(days=1)),
            delete(PriceSnapshotModel).where(PriceSnapshotModel.id == UUID(snapshot.id)),
            update(PriceObservationModel)
            .where(PriceObservationModel.id == observation_id)
            .values(value=Decimal(999)),
            delete(PriceObservationModel).where(PriceObservationModel.id == observation_id),
        ):
            with pytest.raises(IntegrityError), sessions.begin() as session:
                session.execute(statement)
        foreign = await source_case(sessions)
        with pytest.raises(app.SourceServiceError) as caught:
            await foreign.service.get_price_snapshot(foreign.principal, snapshot.id)
        assert caught.value.code is app.SourceServiceErrorCode.NOT_FOUND
        with pytest.raises(IntegrityError), sessions.begin() as session:
            session.add(
                PriceObservationModel(
                    owner_id=UUID(foreign.principal.owner_id),
                    snapshot_id=UUID(snapshot.id),
                    ordinal=99,
                    session_date=date(2026, 9, 1),
                    effective_at=NOW,
                    value=Decimal(1),
                    state="available",
                )
            )
        restarted = PostgresSourceService(
            sessions=sessions, cursor_signing_key=KEY, clock=lambda: NOW
        )
        header = await restarted.get_price_snapshot(case.principal, snapshot.id)
        assert (
            header.content_digest == source_snapshot_digest(snapshot)
            and header.provenance.first_observed_at == NOW
        )

    asyncio.run(scenario())


def test_immutable_page_reuse_owner_binding_and_hard_cursor_expiry(
    sources_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = sources_database

    async def scenario() -> None:
        case = await source_case(sessions)
        snapshot = await ingest(case)
        first = await case.service.list_price_observations(
            case.principal, snapshot.id, query=app.SourceObservationQuery(limit=1)
        )
        assert first.next_cursor
        before = count(sessions, CollectionQuerySnapshotModel, case.principal.owner_id)
        for _ in range(100):
            assert (
                await case.service.list_price_observations(
                    case.principal, snapshot.id, query=app.SourceObservationQuery(limit=1)
                )
                == first
            )
        assert count(sessions, CollectionQuerySnapshotModel, case.principal.owner_id) == before
        with pytest.raises(CursorValidationError):
            await case.service.list_price_observations(
                case.principal,
                snapshot.id,
                query=app.SourceObservationQuery(
                    limit=2,
                    cursor=first.next_cursor[:-1] + ("a" if first.next_cursor[-1] != "a" else "b"),
                ),
            )
        case.now[0] += timedelta(hours=2)
        with pytest.raises(CursorValidationError):
            await case.service.list_price_observations(
                case.principal,
                snapshot.id,
                query=app.SourceObservationQuery(limit=1, cursor=first.next_cursor),
            )

    asyncio.run(scenario())


def test_benchmark_normalization_concurrent_revision_and_database_sealing(
    sources_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = sources_database

    async def scenario() -> None:
        case = await source_case(sessions)
        content = BenchmarkContent(
            reporting_currency=CurrencyCode("EUR"),
            effective_at=NOW,
            return_basis=PriceBasis.RAW_CLOSE,
            calendar_id=case.calendar.id,
            calendar_version=case.calendar.version,
            rebalance_rule=BenchmarkRebalanceRule.BUY_AND_HOLD,
            components=(
                BenchmarkComponent(source_id=case.series.id, weight=Decimal("0.9999999999999")),
            ),
        )
        created = await case.service.create_benchmark_definition(
            case.principal,
            app.CreateBenchmarkDefinitionCommand(
                name="Synthetic benchmark", content=content, normalize=True
            ),
            idempotency_key="create-benchmark",
            correlation_id="source-test",
        )
        version = created.selected_version
        assert version is not None
        assert (
            version.content.components[0].weight == Decimal(1)
            and len(version.normalization_adjustments) == 1
        )
        command = app.CreateBenchmarkVersionCommand(content=version.content)
        results = await asyncio.gather(
            *(
                case.service.create_benchmark_version(
                    case.principal,
                    created.definition.id,
                    command,
                    if_match=created.definition.etag,
                    idempotency_key=f"concurrent-{i}",
                    correlation_id="source-test",
                )
                for i in range(2)
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(x, app.BenchmarkDefinitionDetailView) for x in results) == 1
        assert (
            sum(
                isinstance(x, app.SourceServiceError)
                and x.code is app.SourceServiceErrorCode.REVISION_MISMATCH
                for x in results
            )
            == 1
        )
        for statement in (
            update(BenchmarkVersionModel)
            .where(BenchmarkVersionModel.id == UUID(version.id))
            .values(content_digest="0" * 64),
            delete(BenchmarkComponentModel).where(
                BenchmarkComponentModel.version_id == UUID(version.id)
            ),
        ):
            with pytest.raises(IntegrityError), sessions.begin() as session:
                session.execute(statement)

    asyncio.run(scenario())


def test_retention_expiry_denies_before_bounded_cleanup_and_keeps_permitted_digest(
    sources_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = sources_database

    async def scenario() -> None:
        case = await source_case(sessions, retention_days=1)
        snapshot = await ingest(case)
        case.now[0] += timedelta(days=2)
        with pytest.raises(app.SourceServiceError) as caught:
            await case.service.get_price_snapshot(case.principal, snapshot.id)
        assert caught.value.code is app.SourceServiceErrorCode.ACCESS_DENIED
        assert await case.service.expire_source_snapshots(limit=1) == 1
        assert count(sessions, PriceObservationModel, case.principal.owner_id) == 0
        with sessions() as session:
            row = session.get(PriceSnapshotModel, UUID(snapshot.id))
            assert row is not None
            assert row.content_digest == source_snapshot_digest(snapshot)
        assert await case.service.expire_source_snapshots(limit=1) == 0

    asyncio.run(scenario())


def attach_account(case: Case) -> str:
    from trading212_persistence.models import BrokerAccountModel, BrokerConnectionModel

    connection_id, account_id = uuid4(), uuid4()
    with case.sessions.begin() as session:
        session.add(
            BrokerConnectionModel(
                id=connection_id,
                owner_id=UUID(case.principal.owner_id),
                provider="synthetic",
                environment="synthetic",
                status="active",
            )
        )
        session.flush()
        session.add(
            BrokerAccountModel(
                id=account_id,
                connection_id=connection_id,
                provider_account_id="synthetic-source-account",
                account_type="invest",
                base_currency="EUR",
                display_name="Synthetic source account",
                status="active",
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
        )
    return str(account_id)


@pytest.mark.parametrize("orders", [(None, None), (1, 1), (1, None)])
def test_public_status_pins_ambiguous_revision_without_arbitrary_winner(
    sources_database: tuple[Engine, sessionmaker[Session]], orders: tuple[int | None, int | None]
) -> None:
    _, sessions = sources_database

    async def scenario() -> None:
        case = await source_case(sessions)
        account = attach_account(case)
        case.pages = tuple(
            replace(p, provenance=replace(p.provenance, revision_order=orders[0]))
            for p in case.pages
        )
        first = await ingest(case)
        known = await case.service.get_market_source_status(
            case.principal, account, query=app.SourceStatusQuery(source_cutoff_at=NOW)
        )
        assert known.series.items[0].latest_snapshot is not None
        assert known.series.items[0].latest_snapshot.id == first.id
        case.now[0] += timedelta(hours=1)
        corrected = tuple(
            replace(
                p,
                provenance=replace(p.provenance, source_revision="v2", revision_order=orders[1]),
                observations=tuple(replace(x, value=Decimal(999)) for x in p.observations),
            )
            for p in case.pages
        )
        await case.service.ingest_price_history(
            case.principal,
            case.request,
            corrected,
            idempotency_key="ambiguous-revision",
            correlation_id="source-test",
        )
        now = await case.service.get_market_source_status(
            case.principal, account, query=app.SourceStatusQuery()
        )
        from trading212_domain.sources import SourceAvailability, SourceReason

        assert now.series.items[0].availability is SourceAvailability.UNAVAILABLE
        assert now.series.items[0].reason is SourceReason.AMBIGUOUS_REVISION
        assert now.series.items[0].latest_snapshot is None
        old = await case.service.get_market_source_status(
            case.principal, account, query=app.SourceStatusQuery(source_cutoff_at=NOW)
        )
        assert old == known

    asyncio.run(scenario())


def test_newer_fx_gap_revision_cannot_resurrect_old_pair(
    sources_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    from trading212_analytics.source_policy import assess_fx_coverage
    from trading212_application.source_providers import FxPair, FxRatePage, FxRatesRequest
    from trading212_domain.sources import FxObservation, SourceAvailability, SourceReason

    _, sessions = sources_database

    async def scenario() -> None:
        case = await source_case(sessions)
        account = attach_account(case)
        await case.service.configure_source_provider(
            case.principal,
            SourceProviderRegistration(
                id=case.series.provider_id,
                key="synthetic-source",
                name="Synthetic source",
                adapter_version="synthetic-v1",
                configuration_state=app.ProviderConfigurationState.CONFIGURED,
                synthetic=True,
                capabilities=(SourceCapability.FX_RATES,),
                supported_price_bases=(),
            ),
            idempotency_key="fx-provider",
            correlation_id="source-test",
        )
        pair = (CurrencyCode("EUR"), CurrencyCode("USD"))
        request = FxRatesRequest(
            provider_id=case.series.provider_id,
            license_version_id=case.license.id,
            pairs=(FxPair(base=pair[0], quote=pair[1]),),
            period=case.calendar.period,
            source_cutoff_at=NOW,
            calendar_id=case.calendar.id,
            calendar_version=case.calendar.version,
        )
        observations = tuple(
            FxObservation(
                base=pair[0],
                quote=pair[1],
                session_date=x.session_date,
                effective_at=x.close_at,
                rate=Decimal("1.1"),
                batch_key="synthetic-fixing",
            )
            for x in case.calendar.sessions
        )
        provenance = case.pages[0].provenance
        first = await case.service.ingest_fx_rates(
            case.principal,
            request,
            (
                FxRatePage(
                    provenance=provenance,
                    period=request.period,
                    coverage=assess_fx_coverage(
                        case.calendar, request.period, observations, pairs=(pair,)
                    ),
                    observations=observations,
                ),
            ),
            idempotency_key="fx-first",
            correlation_id="source-test",
        )
        case.now[0] += timedelta(hours=1)
        missing = FxRatePage(
            provenance=replace(provenance, source_revision="v2", revision_order=2),
            period=request.period,
            coverage=assess_fx_coverage(case.calendar, request.period, (), pairs=(pair,)),
            observations=(),
        )
        correction = await case.service.ingest_fx_rates(
            case.principal,
            request,
            (missing,),
            idempotency_key="fx-removed",
            correlation_id="source-test",
        )
        assert correction.id != first.id
        view = await case.service.get_fx_source_status(
            case.principal, account, query=app.FxSourceStatusQuery()
        )
        assert view.pairs.total == 1
        item = view.pairs.items[0]
        assert item.latest_snapshot is not None and item.latest_snapshot.id == correction.id
        assert (
            item.availability is SourceAvailability.UNAVAILABLE
            and item.reason is SourceReason.MISSING_SESSION
        )
        assert item.latest_snapshot.available_count == 0

    asyncio.run(scenario())


def test_command_replays_original_response_after_new_version_and_archive(
    sources_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = sources_database

    async def scenario() -> None:
        case = await source_case(sessions)
        content = BenchmarkContent(
            reporting_currency=CurrencyCode("EUR"),
            effective_at=NOW,
            return_basis=PriceBasis.RAW_CLOSE,
            calendar_id=case.calendar.id,
            calendar_version=case.calendar.version,
            rebalance_rule=BenchmarkRebalanceRule.BUY_AND_HOLD,
            components=(BenchmarkComponent(source_id=case.series.id, weight=Decimal(1)),),
        )
        create = app.CreateBenchmarkDefinitionCommand(
            name="Synthetic immutable command", content=content
        )
        original = await case.service.create_benchmark_definition(
            case.principal, create, idempotency_key="immutable-create", correlation_id="source-test"
        )
        command = app.CreateBenchmarkVersionCommand(
            content=replace(content, rebalance_rule=BenchmarkRebalanceRule.DAILY_REBALANCED)
        )
        version = await case.service.create_benchmark_version(
            case.principal,
            original.definition.id,
            command,
            if_match=original.definition.etag,
            idempotency_key="immutable-version",
            correlation_id="source-test",
        )
        archived = await case.service.archive_benchmark_definition(
            case.principal,
            original.definition.id,
            if_match=version.definition.etag,
            idempotency_key="immutable-archive",
            correlation_id="source-test",
        )
        assert archived.definition.state is app.BenchmarkDefinitionState.ARCHIVED
        assert (
            await case.service.create_benchmark_definition(
                case.principal,
                create,
                idempotency_key="immutable-create",
                correlation_id="source-test",
            )
            == original
        )
        assert (
            await case.service.create_benchmark_version(
                case.principal,
                original.definition.id,
                command,
                if_match=None,
                idempotency_key="immutable-version",
                correlation_id="source-test",
            )
            == version
        )
        assert (
            await case.service.archive_benchmark_definition(
                case.principal,
                original.definition.id,
                if_match=None,
                idempotency_key="immutable-archive",
                correlation_id="source-test",
            )
            == archived
        )

    asyncio.run(scenario())


def test_concurrent_identical_ingestions_share_economic_identity(
    sources_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = sources_database

    async def scenario() -> None:
        case = await source_case(sessions)
        first, second = await asyncio.gather(
            ingest(case, key="concurrent-one"), ingest(case, key="concurrent-two")
        )
        assert first == second
        assert count(sessions, PriceSnapshotModel, case.principal.owner_id) == 1
        assert count(sessions, SourceRetrievalOccurrenceModel, case.principal.owner_id) == 2

    asyncio.run(scenario())


def test_shared_capacity_and_corrupt_membership_fail_atomically(
    sources_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    from trading212_application.queries import CollectionSnapshotCapacityError
    from trading212_persistence.models import CollectionQuerySnapshotMemberModel
    from trading212_persistence.source_models import SourceCollectionBindingModel

    _, sessions = sources_database

    async def scenario() -> None:
        case = await source_case(sessions)
        snapshot = await ingest(case)
        case.service = PostgresSourceService(
            sessions=sessions,
            cursor_signing_key=KEY,
            clock=lambda: NOW,
            max_active_collection_snapshots_per_owner=1,
            max_active_collection_members_per_owner=3,
        )
        first = await case.service.list_price_observations(
            case.principal, snapshot.id, query=app.SourceObservationQuery(limit=1)
        )
        assert first.total == 3
        before = count(sessions, SourceCommandIdentityModel, case.principal.owner_id)
        with pytest.raises(CollectionSnapshotCapacityError):
            await case.service.list_benchmark_definitions(
                case.principal, query=app.BenchmarkDefinitionQuery()
            )
        assert count(sessions, CollectionQuerySnapshotModel, case.principal.owner_id) == 1
        assert count(sessions, SourceCollectionBindingModel, case.principal.owner_id) == 1
        assert count(sessions, SourceCommandIdentityModel, case.principal.owner_id) == before
        with sessions.begin() as session:
            collection = session.scalar(
                select(CollectionQuerySnapshotModel).where(
                    CollectionQuerySnapshotModel.owner_id == UUID(case.principal.owner_id)
                )
            )
            assert collection is not None
            session.execute(
                update(CollectionQuerySnapshotMemberModel)
                .where(
                    CollectionQuerySnapshotMemberModel.snapshot_id == collection.id,
                    CollectionQuerySnapshotMemberModel.ordinal == 1,
                )
                .values(record_id=uuid4())
            )
        with pytest.raises(CursorValidationError):
            await case.service.list_price_observations(
                case.principal, snapshot.id, query=app.SourceObservationQuery(limit=1)
            )
        assert count(sessions, CollectionQuerySnapshotModel, case.principal.owner_id) == 1

    asyncio.run(scenario())


def test_database_runtime_failure_is_sanitized_without_exception_context(
    sources_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    import traceback

    from sqlalchemy.exc import SQLAlchemyError

    _, sessions = sources_database

    async def scenario() -> None:
        case = await source_case(sessions)
        canary = "synthetic-private-source-exception-canary"

        def fail(_session: Session, _owner: UUID) -> None:
            raise SQLAlchemyError(canary)

        with pytest.raises(app.SourceServiceError) as caught:
            await case.service._run(case.principal, fail)
        assert caught.value.code is app.SourceServiceErrorCode.PROVIDER_UNAVAILABLE
        assert caught.value.__context__ is None and caught.value.__cause__ is None
        assert canary not in "".join(traceback.format_exception(caught.value))

    asyncio.run(scenario())


def test_series_cannot_relabel_a_different_provider_instrument_key(
    sources_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    from trading212_persistence.source_models import MarketSourceSeriesModel

    _, sessions = sources_database

    async def scenario() -> None:
        case = await source_case(sessions)
        mismatched = replace(case.series, id=str(uuid4()), provider_key="different-security")
        before = count(sessions, SourceCommandIdentityModel, case.principal.owner_id)
        with pytest.raises(app.SourceServiceError) as caught:
            await case.service.register_source_series(
                case.principal,
                mismatched,
                idempotency_key="wrong-provider-key",
                correlation_id="source-test",
            )
        assert caught.value.code is app.SourceServiceErrorCode.VALIDATION_FAILED
        assert count(sessions, SourceCommandIdentityModel, case.principal.owner_id) == before
        with sessions() as session:
            original = session.get(MarketSourceSeriesModel, UUID(case.series.id))
            assert original is not None
            values = {
                column.name: getattr(original, column.name)
                for column in MarketSourceSeriesModel.__table__.columns
            }
        values.update(id=uuid4(), provider_key="different-security", content_digest="0" * 64)
        with pytest.raises(IntegrityError), sessions.begin() as session:
            session.add(MarketSourceSeriesModel(**values))
        assert count(sessions, MarketSourceSeriesModel, case.principal.owner_id) == 1

    asyncio.run(scenario())
