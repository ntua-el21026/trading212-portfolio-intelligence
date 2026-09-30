"""Two distinct synthetic adapters through actual ingestion and canonical persistence."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select
from trading212_application.ingestion import IngestionCoordinator, RunMode, RunStatus
from trading212_domain import build_synthetic_identity
from trading212_persistence import create_session_factory
from trading212_persistence.models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    ListingModel,
    PortfolioSnapshotModel,
    SnapshotPositionModel,
    SourceRecordModel,
)
from trading212_worker.materializer import PostgresCanonicalMaterializer
from trading212_worker.postgres_store import PostgresIngestionStore
from trading212_worker.synthetic import SyntheticIngestionProvider
from trading212_worker.synthetic_custody import SyntheticCustodyIngestionProvider

from tests.integration.test_worker_ingestion_store import isolated_database as isolated_database
from tests.unit.worker.test_synthetic_custody import custody_fixture

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_second_native_contract_has_canonical_parity_and_repeated_source_dedup(
    isolated_database: tuple[str, Engine],
) -> None:
    _, engine = isolated_database
    sessions = create_session_factory(engine)
    identity = build_synthetic_identity()
    owner = identity.owner.id
    first, second, connection = uuid4(), uuid4(), uuid4()
    at = datetime.now(UTC)
    with sessions.begin() as session:
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
        for account in (first, second):
            session.add(
                BrokerAccountModel(
                    id=account,
                    connection_id=connection,
                    provider_account_id="native-parity-" + str(account),
                    account_type="invest",
                    base_currency="EUR",
                    display_name="Synthetic custody parity",
                    status="active",
                    first_seen_at=at,
                    last_seen_at=at,
                )
            )
    for account, provider in (
        (first, SyntheticIngestionProvider(clock=lambda: at)),
        (second, SyntheticCustodyIngestionProvider(custody_fixture(second, at), clock=lambda: at)),
    ):
        result = await IngestionCoordinator(
            provider=provider,
            store=PostgresIngestionStore(
                sessions, provider="synthetic", materializer=PostgresCanonicalMaterializer()
            ),
            clock=lambda: at,
        ).refresh(
            owner_id=str(owner),
            account_id=str(account),
            mode=RunMode.FULL,
            idempotency_key="native-parity-" + str(account),
            correlation_id="native-parity",
        )
        assert result.status is RunStatus.SUCCEEDED
    with sessions() as session:
        snapshots = tuple(
            session.scalars(
                select(PortfolioSnapshotModel)
                .where(PortfolioSnapshotModel.broker_account_id.in_((first, second)))
                .order_by(PortfolioSnapshotModel.broker_account_id)
            )
        )
        assert len(snapshots) == 2
        assert all(
            x.cash_total == Decimal("12431.27")
            and x.invested_total == Decimal("236000")
            and x.portfolio_total == Decimal("248431.27")
            for x in snapshots
        )
        rows = session.execute(
            select(
                SnapshotPositionModel.quantity,
                SnapshotPositionModel.market_value,
                ListingModel.instrument_id,
                ListingModel.id,
            )
            .join(ListingModel, ListingModel.id == SnapshotPositionModel.listing_id)
            .where(SnapshotPositionModel.snapshot_id.in_(x.id for x in snapshots))
        ).all()
        assert len(rows) == 2
        assert rows[0][0:3] == rows[1][0:3]
        assert rows[0][3] != rows[1][3]
        records_before = session.scalar(
            select(func.count())
            .select_from(SourceRecordModel)
            .where(SourceRecordModel.broker_account_id == second)
        )
    later = at + timedelta(minutes=1)
    result = await IngestionCoordinator(
        provider=SyntheticCustodyIngestionProvider(
            custody_fixture(second, at), clock=lambda: later
        ),
        store=PostgresIngestionStore(
            sessions, provider="synthetic", materializer=PostgresCanonicalMaterializer()
        ),
        clock=lambda: later,
    ).refresh(
        owner_id=str(owner),
        account_id=str(second),
        mode=RunMode.FULL,
        idempotency_key="native-repeat-" + str(second),
        correlation_id="native-repeat",
    )
    assert result.status is RunStatus.SUCCEEDED
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(SourceRecordModel)
                .where(SourceRecordModel.broker_account_id == second)
            )
            == records_before
        )
        latest = session.scalar(
            select(PortfolioSnapshotModel)
            .where(PortfolioSnapshotModel.broker_account_id == second)
            .order_by(PortfolioSnapshotModel.valuation_at.desc())
            .limit(1)
        )
        assert latest is not None and latest.portfolio_total == Decimal("248431.27")
        assert (
            session.scalar(
                select(func.count())
                .select_from(SnapshotPositionModel)
                .where(SnapshotPositionModel.snapshot_id == latest.id)
            )
            == 1
        )
