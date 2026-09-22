"""Dispatcher maintenance removes expired bytes while retaining source authority."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import trading212_worker.outbox_dispatcher as dispatcher
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.source_policy import assess_fx_coverage
from trading212_application import sources as app
from trading212_application.source_ingestion import SourceProviderRegistration
from trading212_application.source_providers import (
    FxPair,
    FxRatePage,
    FxRatesRequest,
    SourceCapability,
)
from trading212_domain import CurrencyCode
from trading212_domain.sources import (
    FxObservation,
    LicensePermission,
    PriceBasis,
    source_snapshot_digest,
)
from trading212_persistence.query_telemetry import DatabaseQueryTiming, QueryObserver
from trading212_persistence.research_permissions import ResearchCapabilityAuthority
from trading212_persistence.source_models import (
    FxObservationModel,
    FxSnapshotModel,
    PriceObservationModel,
    PriceSnapshotModel,
    SourceExpiryEventModel,
    SourceRetentionWorkModel,
)
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.source_retention_service import expire_source_payloads
from trading212_persistence.source_service import PostgresSourceService

from tests.integration.test_sources_postgres import (
    Case,
    count,
    ingest,
    source_case,
)
from tests.integration.test_sources_postgres import (
    sources_database as sources_database,
)
from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def run_dispatcher_once(monkeypatch: pytest.MonkeyPatch, engine: Engine, *, at: datetime) -> None:
    """Run the real dispatcher composition with a bounded synthetic maintenance clock."""
    monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv("CELERY_BROKER_URL", "memory://")
    monkeypatch.setenv("T212PI_ENVIRONMENT", "test")

    def database(url: str, *, query_observer: QueryObserver | None = None) -> Engine:
        # A blocking-lock regression must fail rather than hang the test runner.
        selected = create_engine(url, connect_args={"options": "-c lock_timeout=200ms"})
        if query_observer is not None:
            DatabaseQueryTiming(selected, query_observer)
        return selected

    def source_service(
        *,
        sessions: sessionmaker[Session],
        cursor_signing_key: bytes,
        research_capability_authority: ResearchCapabilityAuthority | None = None,
    ) -> PostgresSourceService:
        return PostgresSourceService(
            sessions=sessions,
            cursor_signing_key=cursor_signing_key,
            clock=lambda: at,
            research_capability_authority=research_capability_authority,
        )

    monkeypatch.setattr(dispatcher, "create_database_engine", database)
    monkeypatch.setattr(dispatcher, "PostgresSourceService", source_service)
    assert dispatcher.main(["--once"]) == 0


def test_dispatcher_preserves_current_license_denial_and_only_purges_expired_sources(
    sources_database: tuple[Engine, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, sessions = sources_database

    async def arrange() -> tuple[Case, str, Case, str]:
        expired = await source_case(sessions, retention_days=1)
        retained = await source_case(sessions, retention_days=365)
        first, second = await ingest(expired), await ingest(retained)
        for case, snapshot in ((expired, first), (retained, second)):
            header = await case.service.get_price_snapshot(case.principal, snapshot.id)
            assert header.id == snapshot.id
            assert header.content_digest == source_snapshot_digest(snapshot)
        with pytest.raises(app.SourceServiceError) as wrong_owner:
            await retained.service.get_price_snapshot(retained.principal, first.id)
        assert wrong_owner.value.code is app.SourceServiceErrorCode.NOT_FOUND
        denied = replace(
            retained.license,
            id=str(uuid4()),
            version="deny-v2",
            effective_at=retained.now[0],
            display=LicensePermission.DENIED,
            store=LicensePermission.DENIED,
        )
        await retained.service.register_source_license(
            retained.principal, denied, idempotency_key="revoke", correlation_id="source-test"
        )
        expired.now[0] += timedelta(days=2)
        retained.now[0] = expired.now[0]
        for case, snapshot in ((expired, first), (retained, second)):
            with pytest.raises(app.SourceServiceError) as denied_read:
                await case.service.get_price_snapshot(case.principal, snapshot.id)
            assert denied_read.value.code is app.SourceServiceErrorCode.ACCESS_DENIED
        return expired, first.id, retained, second.id

    expired, first_id, retained, second_id = asyncio.run(arrange())
    before = count(sessions, PriceObservationModel, retained.principal.owner_id)
    with sessions() as session:
        first = session.get(PriceSnapshotModel, UUID(first_id))
        second = session.get(PriceSnapshotModel, UUID(second_id))
        assert first is not None and second is not None
        immutable = (first.content_digest, first.first_observed_at, first.expires_at)
        second_digest = second.content_digest
    run_dispatcher_once(monkeypatch, engine, at=expired.now[0])
    assert count(sessions, PriceObservationModel, expired.principal.owner_id) == 0
    assert count(sessions, PriceObservationModel, retained.principal.owner_id) == before > 0
    with sessions() as session:
        first = session.get(PriceSnapshotModel, UUID(first_id))
        second = session.get(PriceSnapshotModel, UUID(second_id))
        assert first is not None and second is not None
        assert (first.content_digest, first.first_observed_at, first.expires_at) == immutable
        assert second.content_digest == second_digest
        event = session.scalar(
            select(SourceExpiryEventModel).where(
                SourceExpiryEventModel.price_snapshot_id == UUID(first_id)
            )
        )
        assert event is not None and event.content_digest == immutable[0]
        assert (
            session.scalar(
                select(SourceExpiryEventModel.id).where(
                    SourceExpiryEventModel.price_snapshot_id == UUID(second_id)
                )
            )
            is None
        )
    with pytest.raises(app.SourceServiceError) as still_denied:
        asyncio.run(retained.service.get_price_snapshot(retained.principal, second_id))
    assert still_denied.value.code is app.SourceServiceErrorCode.ACCESS_DENIED


@pytest.mark.parametrize("held_lock", ["sources", "xray", "row"])
def test_busy_owner_does_not_stall_other_owners_and_resumes_next_dispatch_cycle(
    sources_database: tuple[Engine, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    held_lock: str,
) -> None:
    engine, sessions = sources_database

    async def arrange() -> tuple[Case, str, Case, str]:
        busy = await source_case(sessions, retention_days=1)
        free = await source_case(sessions, retention_days=1)
        first, second = await ingest(busy), await ingest(free)
        busy.now[0] += timedelta(days=2)
        return busy, first.id, free, second.id

    busy, first_id, free, second_id = asyncio.run(arrange())
    before = count(sessions, PriceObservationModel, busy.principal.owner_id)
    with sessions.begin() as blocker:
        if held_lock == "row":
            assert (
                blocker.scalar(
                    select(PriceSnapshotModel)
                    .where(PriceSnapshotModel.id == UUID(first_id))
                    .with_for_update()
                )
                is not None
            )
        else:
            blocker.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"{held_lock}:{busy.principal.owner_id}"},
            )
        run_dispatcher_once(monkeypatch, engine, at=busy.now[0])
        assert count(sessions, PriceObservationModel, busy.principal.owner_id) == before > 0
        assert count(sessions, PriceObservationModel, free.principal.owner_id) == 0
        with sessions() as session:
            assert (
                session.scalar(
                    select(SourceExpiryEventModel.id).where(
                        SourceExpiryEventModel.price_snapshot_id == UUID(first_id)
                    )
                )
                is None
            )
            assert (
                session.scalar(
                    select(SourceExpiryEventModel.id).where(
                        SourceExpiryEventModel.price_snapshot_id == UUID(second_id)
                    )
                )
                is not None
            )
    run_dispatcher_once(monkeypatch, engine, at=busy.now[0])
    assert count(sessions, PriceObservationModel, busy.principal.owner_id) == 0


def test_dispatcher_resumes_partial_physical_purge_without_replacing_parent(
    sources_database: tuple[Engine, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, sessions = sources_database

    async def arrange() -> tuple[Case, str, str]:
        case = await source_case(sessions, retention_days=1)
        snapshot = await ingest(case)
        case.now[0] += timedelta(days=2)
        return case, snapshot.id, source_snapshot_digest(snapshot)

    case, snapshot_id, digest = asyncio.run(arrange())
    before = count(sessions, PriceObservationModel, case.principal.owner_id)
    assert before > 1
    with sessions.begin() as session:
        assert (
            expire_source_payloads(
                session, at=case.now[0], limit=1, budget=SourcePurgeBudget(rows_removed=1)
            )
            == 0
        )
    assert count(sessions, PriceObservationModel, case.principal.owner_id) == before - 1
    run_dispatcher_once(monkeypatch, engine, at=case.now[0])
    with sessions() as session:
        parent = session.get(PriceSnapshotModel, UUID(snapshot_id))
        work = session.scalar(
            select(SourceRetentionWorkModel).where(
                SourceRetentionWorkModel.price_snapshot_id == UUID(snapshot_id)
            )
        )
        event = session.scalar(
            select(SourceExpiryEventModel).where(
                SourceExpiryEventModel.price_snapshot_id == UUID(snapshot_id)
            )
        )
        assert parent is not None and parent.content_digest == digest
        assert work is not None and work.phase == "complete"
        assert event is not None and event.content_digest == digest
        assert event.removed_observation_count == before
        original_event_id = event.id
    run_dispatcher_once(monkeypatch, engine, at=case.now[0])
    with sessions() as session:
        assert (
            session.scalar(
                select(SourceExpiryEventModel.id).where(
                    SourceExpiryEventModel.price_snapshot_id == UUID(snapshot_id)
                )
            )
            == original_event_id
        )


async def _register_market_prefix(case: Case, *, count: int) -> None:
    """Create distinct canonical revisions in two families through actual ingestion."""
    await case.service.configure_source_provider(
        case.principal,
        SourceProviderRegistration(
            id=case.series.provider_id,
            key="synthetic-source",
            name="Synthetic source",
            adapter_version="synthetic-v1",
            configuration_state=app.ProviderConfigurationState.CONFIGURED,
            synthetic=True,
            capabilities=(SourceCapability.PRICE_HISTORY, SourceCapability.FX_RATES),
            supported_price_bases=(PriceBasis.RAW_CLOSE,),
        ),
        idempotency_key="prefix-provider",
        correlation_id="source-prefix-test",
    )
    pair = (CurrencyCode("EUR"), CurrencyCode("USD"))
    request = FxRatesRequest(
        provider_id=case.series.provider_id,
        license_version_id=case.license.id,
        pairs=(FxPair(base=pair[0], quote=pair[1]),),
        period=case.calendar.period,
        source_cutoff_at=case.request.source_cutoff_at,
        calendar_id=case.calendar.id,
        calendar_version=case.calendar.version,
    )
    observations = tuple(
        FxObservation(
            base=pair[0],
            quote=pair[1],
            session_date=market_session.session_date,
            effective_at=market_session.close_at,
            rate=Decimal("1.1"),
            batch_key="synthetic-prefix-fixing",
        )
        for market_session in case.calendar.sessions
    )
    coverage = assess_fx_coverage(case.calendar, request.period, observations, pairs=(pair,))
    for revision in range(1, count + 1):
        pages = tuple(
            replace(
                page,
                provenance=replace(
                    page.provenance, source_revision=f"prefix-{revision}", revision_order=revision
                ),
            )
            for page in case.pages
        )
        await case.service.ingest_price_history(
            case.principal,
            case.request,
            pages,
            idempotency_key=f"prefix-price-{revision}",
            correlation_id="source-prefix-test",
        )
        await case.service.ingest_fx_rates(
            case.principal,
            request,
            (
                FxRatePage(
                    provenance=pages[0].provenance,
                    period=request.period,
                    coverage=coverage,
                    observations=observations,
                ),
            ),
            idempotency_key=f"prefix-fx-{revision}",
            correlation_id="source-prefix-test",
        )


@pytest.mark.parametrize("held_lock", ["sources", "xray"])
def test_busy_owner_prefix_preserves_budget_for_other_owners_across_source_families(
    xray_read_case: XrayReadCase, held_lock: str
) -> None:
    # Reuse a function-scoped, migrated database so earlier retention cases cannot
    # supply another expired prefix. Its existing X-ray sources expire much later.
    sessions = xray_read_case.sessions
    allowance, prefix_size = 32, 33

    async def arrange() -> tuple[Case, Case, datetime]:
        busy = await source_case(sessions, retention_days=1)
        free = await source_case(sessions, retention_days=1)
        await _register_market_prefix(busy, count=prefix_size)
        free.now[0] += timedelta(seconds=1)
        await _register_market_prefix(free, count=1)
        return busy, free, free.now[0] + timedelta(days=2)

    busy, free, at = asyncio.run(arrange())
    busy_owner, free_owner = UUID(busy.principal.owner_id), UUID(free.principal.owner_id)
    owners = (busy_owner, free_owner)
    families = (
        (PriceSnapshotModel, PriceObservationModel, "price_snapshot_id"),
        (FxSnapshotModel, FxObservationModel, "fx_snapshot_id"),
    )
    before: dict[UUID, tuple[str, datetime, datetime]] = {}
    with sessions() as session:
        for model, _, _ in families:
            rows = list(session.scalars(select(model).where(model.owner_id.in_(owners))))
            assert len(rows) == prefix_size + 1
            busy_expiries = [row.expires_at for row in rows if row.owner_id == busy_owner]
            free_expiries = [row.expires_at for row in rows if row.owner_id == free_owner]
            assert len(busy_expiries) == prefix_size and len(free_expiries) == 1
            assert max(busy_expiries) < free_expiries[0] <= at
            before.update(
                (row.id, (row.content_digest, row.first_observed_at, row.expires_at))
                for row in rows
            )

    with sessions.begin() as blocker:
        blocker.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"{held_lock}:{busy_owner}"},
        )
        with sessions.begin() as session:
            session.execute(text("SET LOCAL lock_timeout = '200ms'"))
            budget = SourcePurgeBudget(rows_inspected=allowance)
            assert expire_source_payloads(session, at=at, limit=100, budget=budget) == 2
            assert 0 < budget.rows_inspected < allowance
        with sessions() as session:
            assert (
                session.scalar(
                    select(SourceRetentionWorkModel.id).where(
                        SourceRetentionWorkModel.owner_id == busy_owner
                    )
                )
                is None
            )
            for _model, child, reference in families:
                assert count(sessions, child, busy.principal.owner_id) == prefix_size * 3
                assert count(sessions, child, free.principal.owner_id) == 0
                events = list(
                    session.scalars(
                        select(SourceExpiryEventModel).where(
                            SourceExpiryEventModel.owner_id.in_(owners),
                            getattr(SourceExpiryEventModel, reference).is_not(None),
                        )
                    )
                )
                assert len(events) == 1 and events[0].owner_id == free_owner
                identifier = getattr(events[0], reference)
                assert events[0].content_digest == before[identifier][0]
                assert events[0].removed_at == at
                assert events[0].removed_observation_count == 3
        # A second locked pass retains eligibility without exhausting another prefix.
        with sessions.begin() as session:
            budget = SourcePurgeBudget(rows_inspected=allowance)
            assert expire_source_payloads(session, at=at, limit=100, budget=budget) == 0
            # Only one busy owner remains across both families: charge it once per pass.
            assert budget.rows_inspected == allowance - 1

    remaining = prefix_size * len(families)
    for _ in range(remaining):
        with sessions.begin() as session:
            budget = SourcePurgeBudget(rows_inspected=allowance)
            completed = expire_source_payloads(session, at=at, limit=100, budget=budget)
            assert 0 <= budget.rows_inspected < allowance
            assert 0 < completed <= remaining
        remaining -= completed
        if remaining == 0:
            break
    assert remaining == 0
    with sessions() as session:
        for model, child, reference in families:
            assert count(sessions, child, busy.principal.owner_id) == 0
            rows = list(session.scalars(select(model).where(model.owner_id.in_(owners))))
            assert len(rows) == prefix_size + 1
            assert all(
                (row.content_digest, row.first_observed_at, row.expires_at) == before[row.id]
                for row in rows
            )
            events = list(
                session.scalars(
                    select(SourceExpiryEventModel).where(
                        SourceExpiryEventModel.owner_id.in_(owners),
                        getattr(SourceExpiryEventModel, reference).is_not(None),
                    )
                )
            )
            assert {getattr(event, reference) for event in events} == {row.id for row in rows}
            assert all(
                event.content_digest == before[getattr(event, reference)][0]
                and event.removed_at == at
                and event.removed_observation_count == 3
                for event in events
            )
