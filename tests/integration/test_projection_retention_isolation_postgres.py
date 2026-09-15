"""Real unrelated-owner markers must never expire another retained projection."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import projection as app
from trading212_application import sources as source_app
from trading212_application.projection_capture import (
    ProjectionDatedSchedule,
    ProjectionInitialSelection,
    ProjectionRunSelection,
)
from trading212_application.projection_views import (
    ProjectionOperationalRunView,
    ProjectionVersionMetadata,
)
from trading212_application.source_ingestion import SourceProviderRegistration
from trading212_application.source_providers import SourceCapability
from trading212_domain.projection import (
    ProjectionAllocation,
    ProjectionAsset,
    ProjectionAssumptions,
    ProjectionSourcePin,
)
from trading212_domain.sources import PriceBasis, source_snapshot_digest
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence.historical_models import HistoricalRetentionEventModel
from trading212_persistence.historical_store import PostgresHistoricalStore
from trading212_persistence.models import BrokerAccountModel, BrokerConnectionModel
from trading212_persistence.premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumRetentionModel,
    PremiumRunModel,
)
from trading212_persistence.projection_definition_store import READ_SCOPES
from trading212_persistence.projection_models import ProjectionRunSourceModel
from trading212_persistence.projection_retention_policy import projection_run_restricted
from trading212_persistence.projection_service import PostgresProjectionService
from trading212_persistence.report_authorization import authorize_report_request
from trading212_persistence.source_models import SourceExpiryEventModel, SourceRetentionWorkModel

from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_historical_postgres import policy, selection
from tests.integration.test_scenario_runs_postgres import grant_scenario_identity
from tests.integration.test_sources_postgres import KEY, Case, ingest, source_case

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class OwnedRun:
    source: Case
    account_id: UUID
    price_id: UUID
    history_id: UUID
    service: PostgresProjectionService
    run: ProjectionOperationalRunView


async def admitted_owner(sessions: sessionmaker[Session], *, retention_days: int) -> OwnedRun:
    # Existing typed source fixture supplies real owner/provider/license/mapping/calendar.
    # Each owner gets a different provider and physical source with its own lifetime.
    case = await source_case(sessions, retention_days=retention_days)
    with sessions() as session:
        at = session.scalar(select(func.clock_timestamp()))
        assert isinstance(at, datetime)
        case.now[0] = at
    case.principal = replace(
        case.principal, subject=case.principal.owner_id, principal_id=str(uuid4())
    )
    account, connection = uuid4(), uuid4()
    with sessions() as session, session.begin():
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
                display_name="Projection marker isolation",
                status="active",
                first_seen_at=at,
                last_seen_at=at,
            )
        )
    grant_scenario_identity(sessions, case.principal, at)
    await case.service.configure_source_provider(
        case.principal,
        SourceProviderRegistration(
            id=case.series.provider_id,
            key="synthetic-source",
            name="Synthetic source",
            adapter_version="synthetic-v1",
            configuration_state=source_app.ProviderConfigurationState.CONFIGURED,
            synthetic=True,
            capabilities=(SourceCapability.PRICE_HISTORY,),
            supported_price_bases=(PriceBasis.RAW_CLOSE, PriceBasis.TOTAL_RETURN),
        ),
        idempotency_key="isolation-total-return-provider",
        correlation_id="projection-isolation",
    )
    series = replace(case.series, id=str(uuid4()), basis=PriceBasis.TOTAL_RETURN)
    await case.service.register_source_series(
        case.principal,
        series,
        idempotency_key="isolation-total-return-series",
        correlation_id="projection-isolation",
    )
    case = replace(
        case,
        series=series,
        request=replace(case.request, series=series, source_cutoff_at=at),
        pages=tuple(replace(page, series=series) for page in case.pages),
    )
    price = await ingest(case, key="isolation-price")
    history = PostgresHistoricalStore(sessions, cursor_signing_key=KEY, clock=lambda: case.now[0])
    registration = policy(case)
    await history.register_historical_policy(
        case.principal,
        str(account),
        registration,
        idempotency_key="isolation-policy",
        correlation_id="projection-isolation",
    )
    request = selection(registration)
    captured = await history.capture(
        case.principal,
        str(account),
        request=replace(request, window=replace(request.window, source_cutoff_at=at)),
    )
    service = PostgresProjectionService(sessions, cursor_signing_key=KEY, clock=lambda: case.now[0])
    currency = CurrencyCode("EUR")
    definition = await service.create_assumption_set(
        case.principal,
        app.CreateAssumptionSet(
            account_id=account,
            metadata=ProjectionVersionMetadata(name="Actual marker-isolation sources"),
            content=ProjectionAssumptions(
                assets=(
                    ProjectionAsset(
                        key="equity",
                        annual_mean_log_return=Decimal(".03"),
                        annual_volatility=Decimal(".1"),
                        weight=Decimal(1),
                    ),
                ),
                correlation=((Decimal(1),),),
                reporting_currency=currency,
                annual_inflation=Decimal(0),
                annual_fee=Decimal(0),
                annual_tax_drag=Decimal(0),
                calibration_pins=(
                    ProjectionSourcePin(
                        subject_id=price.id, content_digest=source_snapshot_digest(price)
                    ),
                    ProjectionSourcePin(
                        subject_id=captured.id, content_digest=captured.input_digest
                    ),
                ),
            ),
            idempotency_key=str(uuid4()),
            correlation_id="projection-isolation",
        ),
    )
    run = await service.create_run(
        case.principal,
        app.CreateProjectionRun(
            selection=ProjectionRunSelection(
                account_id=account,
                assumption_version_id=definition.current_version_id,
                initial=ProjectionInitialSelection(
                    kind="modeled_value",
                    modeled_value=Money(Decimal(100), currency),
                    modeled_anchor_date=at.date(),
                ),
                schedule=ProjectionDatedSchedule(base_monthly=Money(Decimal(0), currency)),
                seed=29,
                months=1,
                paths=1,
                retained_months=(0, 1),
                allocation=(ProjectionAllocation(key="equity", weight=Decimal(1)),),
            ),
            idempotency_key=str(uuid4()),
            correlation_id="projection-isolation",
        ),
    )
    return OwnedRun(case, account, UUID(price.id), UUID(captured.id), service, run)


def owned_metadata(session: Session, value: OwnedRun) -> tuple[int, int, int, int, str, int]:
    root = session.get_one(PremiumRunModel, value.run.id)
    capacity = session.get_one(PremiumCapacityModel, UUID(value.source.principal.owner_id))
    job = session.get_one(PremiumJobModel, value.run.job_id)
    physical = session.scalar(select(func.projection_storage_bytes(root.id)))
    assert type(physical) is int and physical > 0
    return (
        root.reserved_bytes,
        root.retained_bytes,
        capacity.active_jobs,
        capacity.reserved_bytes,
        job.state,
        physical,
    )


async def test_foreign_price_history_and_run_markers_leave_actual_live_projection_unchanged(
    historical_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = historical_database
    live = await admitted_owner(sessions, retention_days=365)
    removed = await admitted_owner(sessions, retention_days=1)
    assert live.source.principal.owner_id != removed.source.principal.owner_id
    assert (
        live.run.id != removed.run.id
        and live.price_id != removed.price_id
        and live.history_id != removed.history_id
    )
    at = removed.run.expires_at + timedelta(seconds=1)
    live.source.now[0] = removed.source.now[0] = at
    assert live.run.expires_at > at
    with sessions() as session:
        before = owned_metadata(session, live)
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProjectionRunSourceModel)
                .where(ProjectionRunSourceModel.run_id == live.run.id)
            )
            == 2
        )
        assert (
            session.scalar(
                select(PremiumRunModel.id).where(
                    PremiumRunModel.id == live.run.id, projection_run_restricted(at)
                )
            )
            is None
        )

    # Use the real shared expiry dispatcher. Its one budget creates and completes
    # the foreign premium/source/history markers through ordinary fixed participants.
    for _ in range(8):
        await removed.source.service.expire_source_snapshots(limit=100)
        with sessions() as session:
            markers = (
                session.scalar(
                    select(PremiumRetentionModel.id).where(
                        PremiumRetentionModel.owner_id == UUID(removed.source.principal.owner_id),
                        PremiumRetentionModel.run_id == removed.run.id,
                        PremiumRetentionModel.completed_at.is_not(None),
                    )
                ),
                session.scalar(
                    select(SourceRetentionWorkModel.id).where(
                        SourceRetentionWorkModel.owner_id
                        == UUID(removed.source.principal.owner_id),
                        SourceRetentionWorkModel.price_snapshot_id == removed.price_id,
                        SourceRetentionWorkModel.phase == "complete",
                    )
                ),
                session.scalar(
                    select(SourceExpiryEventModel.id).where(
                        SourceExpiryEventModel.owner_id == UUID(removed.source.principal.owner_id),
                        SourceExpiryEventModel.price_snapshot_id == removed.price_id,
                    )
                ),
                session.scalar(
                    select(HistoricalRetentionEventModel.id).where(
                        HistoricalRetentionEventModel.owner_id
                        == UUID(removed.source.principal.owner_id),
                        HistoricalRetentionEventModel.input_id == removed.history_id,
                    )
                ),
            )
            assert owned_metadata(session, live) == before
            assert (
                session.scalar(
                    select(PremiumRetentionModel.id).where(
                        PremiumRetentionModel.owner_id == UUID(live.source.principal.owner_id),
                        PremiumRetentionModel.run_id == live.run.id,
                    )
                )
                is None
            )
            if all(marker is not None for marker in markers):
                break
    else:
        pytest.fail("bounded dispatcher did not establish the actual foreign marker fixture")

    with sessions() as session:
        # The historical/price headers and foreign source membership remain after
        # purge, so this catches the formerly uncorrelated inner EXISTS clauses.
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProjectionRunSourceModel)
                .where(ProjectionRunSourceModel.run_id == removed.run.id)
            )
            == 2
        )
        assert (
            session.scalar(
                select(PremiumRunModel.id).where(
                    PremiumRunModel.id == live.run.id, projection_run_restricted(at)
                )
            )
            is None
        )
        assert (
            session.scalar(select(func.projection_original_sources_restricted(live.run.id, at)))
            is False
        )
        auth = authorize_report_request(
            session,
            live.source.principal,
            account_id=live.account_id,
            required_scopes=READ_SCOPES,
            now=at,
        )
        retained = live.service.read_retained_input(session, auth, live.run.id)
        assert retained.input_digest == live.run.capture_digest
        assert {source.header.subject_id for source in retained.sources.sources} == {
            live.price_id,
            live.history_id,
        }
    # A fresh cleanup pass after all foreign markers exist must also preserve it.
    await removed.source.service.expire_source_snapshots(limit=100)
    with sessions() as session:
        assert owned_metadata(session, live) == before
    public = await live.service.get_run(
        live.source.principal, live.run.id, app.ProjectionPointPageQuery()
    )
    assert public.state.value == "queued" and public.result_availability == "pending"
