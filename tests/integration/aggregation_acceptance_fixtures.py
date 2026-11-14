"""Small native inputs for actual PostgreSQL aggregation acceptance predicates."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from trading212_application import aggregation as app
from trading212_application.ingestion import IngestionCoordinator, RunMode, RunStatus
from trading212_domain import CurrencyCode
from trading212_domain.aggregation import AggregateMember, AggregateSelectionContent
from trading212_domain.serialization import canonical_json
from trading212_persistence import aggregation_models as m
from trading212_persistence.aggregation_service import PostgresAggregateService
from trading212_persistence.models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    PortfolioSnapshotModel,
    SourceRecordModel,
)
from trading212_persistence.premium_models import PremiumCapacityModel
from trading212_persistence.report_models import ApplicationCommandIdentityModel
from trading212_worker.materializer import PostgresCanonicalMaterializer
from trading212_worker.postgres_store import PostgresIngestionStore
from trading212_worker.synthetic_custody import SyntheticCustodyIngestionProvider
from trading212_worker.synthetic_custody_types import CustodyActivity
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.test_scenario_runs_postgres import grant_scenario_identity
from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.unit.worker.test_synthetic_custody import custody_fixture

type ActivityFactory = Callable[[tuple[UUID, ...], int, datetime], tuple[CustodyActivity, ...]]


async def native_selection(
    case: XrayReadCase,
    *,
    member_count: int = 2,
    activities: ActivityFactory | None = None,
) -> tuple[PostgresAggregateService, app.AggregateSelectionView]:
    """Ingest each member through the distinct native adapter, never seed results."""
    case.now[0] = datetime.now(UTC)
    grant_scenario_identity(case.sessions, case.principal, case.now[0])
    owner, connection = UUID(case.principal.owner_id), uuid4()
    accounts = tuple(uuid4() for _ in range(member_count))
    with case.sessions.begin() as session:
        session.add(
            BrokerConnectionModel(
                id=connection,
                owner_id=owner,
                provider="synthetic",
                environment="synthetic",
                credential_reference=None,
                status="active",
            )
        )
        session.flush()
        for account in accounts:
            session.add(
                BrokerAccountModel(
                    id=account,
                    connection_id=connection,
                    provider_account_id="acceptance-custody-" + str(account),
                    account_type="invest",
                    base_currency="EUR",
                    display_name="Synthetic aggregation acceptance member",
                    status="active",
                    first_seen_at=case.now[0],
                    last_seen_at=case.now[0],
                )
            )
    for index, account in enumerate(accounts):
        native = custody_fixture(account, case.now[0])
        if activities is not None:
            native = replace(native, activity=activities(accounts, index, case.now[0]))
        ingested = await IngestionCoordinator(
            provider=SyntheticCustodyIngestionProvider(native, clock=lambda: case.now[0]),
            store=PostgresIngestionStore(
                case.sessions, provider="synthetic", materializer=PostgresCanonicalMaterializer()
            ),
            clock=lambda: case.now[0],
        ).refresh(
            owner_id=str(owner),
            account_id=str(account),
            mode=RunMode.FULL,
            idempotency_key=str(uuid4()),
            correlation_id="aggregation-acceptance-native",
        )
        assert ingested.status is RunStatus.SUCCEEDED
    with case.sessions() as session:
        snapshots = {
            row.broker_account_id: row.id
            for row in session.scalars(
                select(PortfolioSnapshotModel).where(
                    PortfolioSnapshotModel.broker_account_id.in_(accounts)
                )
            )
        }
    assert len(snapshots) == member_count
    service = PostgresAggregateService(
        case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now[0]
    )
    selected = await service.create_selection(
        case.principal,
        app.CreateAggregateSelection(
            content=AggregateSelectionContent(
                name="Explicit native acceptance members",
                members=tuple(
                    AggregateMember(account_id=account, portfolio_snapshot_id=snapshots[account])
                    for account in accounts
                ),
                reporting_currency=CurrencyCode("EUR"),
                source_cutoff_at=case.now[0],
            ),
            idempotency_key=str(uuid4()),
            correlation_id="aggregation-acceptance-selection",
        ),
    )
    return service, selected


def publication_state(case: XrayReadCase) -> tuple[object, ...]:
    """Observe every aggregate copy plus real owner capacity and command identities."""
    with case.sessions() as session:
        counts = tuple(
            (model.__tablename__, session.scalar(select(func.count()).select_from(model)))
            for model in m.AGGREGATION_MODELS
        )
        capacity = session.get(PremiumCapacityModel, UUID(case.principal.owner_id))
        assert capacity is not None
        charges = (
            capacity.reserved_bytes,
            capacity.retained_bytes,
            capacity.active_jobs,
            capacity.definition_versions,
        )
        selections = tuple(
            session.execute(
                select(
                    m.AggregateSelectionModel.id,
                    m.AggregateSelectionModel.revision,
                    m.AggregateSelectionModel.content_digest,
                    m.AggregateSelectionModel.sealed,
                ).order_by(m.AggregateSelectionModel.id)
            ).all()
        )
        commands = tuple(
            session.execute(
                select(
                    ApplicationCommandIdentityModel.id,
                    ApplicationCommandIdentityModel.command,
                    ApplicationCommandIdentityModel.premium_resource_id,
                )
                .where(ApplicationCommandIdentityModel.owner_id == UUID(case.principal.owner_id))
                .order_by(ApplicationCommandIdentityModel.id)
            ).all()
        )
    return counts, charges, selections, commands


def original_sources(case: XrayReadCase, accounts: tuple[UUID, ...]) -> tuple[object, ...]:
    """Retain exact original minimized facts and clocks for before/after comparison."""
    with case.sessions() as session:
        return tuple(
            (
                row.id,
                row.broker_account_id,
                row.provider_record_id,
                row.schema_version,
                row.observed_at,
                row.source_updated_at,
                row.payload_fingerprint,
                canonical_json(row.sanitized_payload),
            )
            for row in session.scalars(
                select(SourceRecordModel)
                .where(SourceRecordModel.broker_account_id.in_(accounts))
                .order_by(SourceRecordModel.id)
            )
        )
