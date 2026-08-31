"""Production-path acceptance flows for stateful Phase 1 synthetic refreshes."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import Engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from trading212_application.ingestion import (
    FULL_REFRESH_ORDER,
    Checkpoint,
    FailureCategory,
    IngestionCapability,
    IngestionCoordinator,
    IngestionFailure,
    IngestionRun,
    RunMode,
    RunStatus,
    SourcePage,
    SourceRecord,
)
from trading212_domain import build_synthetic_identity
from trading212_persistence import create_database_engine, create_session_factory
from trading212_persistence.models import (
    CashBalanceObservationModel,
    CashFlowModel,
    DividendModel,
    LedgerEntryModel,
    OrderObservationModel,
    PortfolioSnapshotModel,
    PositionObservationModel,
    ReconciliationRunModel,
    TransactionModel,
)
from trading212_worker.materializer import PostgresCanonicalMaterializer
from trading212_worker.postgres_store import PostgresIngestionStore
from trading212_worker.seed import SEED_TIME, seed_materialized_synthetic
from trading212_worker.synthetic import SyntheticIngestionProvider

pytestmark = pytest.mark.integration

INCREMENTAL_TIME = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
IDENTICAL_REFRESH_TIME = SEED_TIME + timedelta(hours=1)


def _base_url() -> str:
    value = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio",
    )
    return value.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture
def acceptance_database() -> Iterator[Engine]:
    parsed = make_url(_base_url())
    database_name = f"t212pi_acceptance_{uuid4().hex[:12]}"
    admin = parsed.set(database="postgres")
    admin_dsn = admin.render_as_string(hide_password=False).replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))

    database_url = parsed.set(database=database_name).render_as_string(hide_password=False)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    engine: Engine | None = None
    try:
        command.upgrade(config, "head")
        asyncio.run(seed_materialized_synthetic(database_url, app_environment="test"))
        engine = create_database_engine(database_url)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if not database_name.startswith("t212pi_acceptance_"):
            raise RuntimeError("refusing to drop an unexpected test database")
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
            )


def _identity() -> tuple[str, str]:
    identity = build_synthetic_identity()
    return str(identity.owner.id), str(identity.account.id)


async def _refresh(
    engine: Engine,
    provider: SyntheticIngestionProvider,
    *,
    observed_at: datetime,
    idempotency_key: str,
    mode: RunMode,
) -> None:
    owner_id, account_id = _identity()
    run = await IngestionCoordinator(
        provider=provider,
        store=PostgresIngestionStore(
            create_session_factory(engine),
            provider="synthetic",
            materializer=PostgresCanonicalMaterializer(),
        ),
        clock=lambda: observed_at,
    ).refresh(
        owner_id=owner_id,
        account_id=account_id,
        mode=mode,
        idempotency_key=idempotency_key,
        correlation_id=idempotency_key,
        capabilities=FULL_REFRESH_ORDER,
    )
    assert run.status is RunStatus.SUCCEEDED


def _economic_counts(session: Session) -> dict[str, int]:
    models = {
        "cash_balances": CashBalanceObservationModel,
        "cash_flows": CashFlowModel,
        "dividends": DividendModel,
        "ledger_entries": LedgerEntryModel,
        "orders": OrderObservationModel,
        "positions": PositionObservationModel,
        "transactions": TransactionModel,
    }
    return {
        name: session.scalar(select(func.count()).select_from(model)) or 0
        for name, model in models.items()
    }


@pytest.mark.asyncio
async def test_identical_production_refresh_does_not_duplicate_economic_records(
    acceptance_database: Engine,
) -> None:
    with Session(acceptance_database) as session:
        before = _economic_counts(session)
        snapshots_before = tuple(session.scalars(select(PortfolioSnapshotModel)))
        assert len(snapshots_before) == 1

    await _refresh(
        acceptance_database,
        SyntheticIngestionProvider(clock=lambda: IDENTICAL_REFRESH_TIME),
        observed_at=IDENTICAL_REFRESH_TIME,
        idempotency_key="acceptance-identical-refresh",
        mode=RunMode.INCREMENTAL,
    )

    with Session(acceptance_database) as session:
        after = _economic_counts(session)
        snapshots_after = tuple(
            session.scalars(
                select(PortfolioSnapshotModel).order_by(PortfolioSnapshotModel.created_at)
            )
        )
        assert after == before
        assert len(snapshots_after) == 2
        assert snapshots_after[0].id != snapshots_after[1].id
        assert snapshots_after[0].portfolio_total == snapshots_after[1].portfolio_total


class IncrementalSyntheticProvider(SyntheticIngestionProvider):
    """One deterministic transaction, dividend, and position revision over the seed."""

    async def read_page(
        self,
        *,
        owner_id: str,
        account_id: str,
        capability: IngestionCapability,
        checkpoint: Checkpoint | None,
        correlation_id: str,
    ) -> SourcePage:
        page = await super().read_page(
            owner_id=owner_id,
            account_id=account_id,
            capability=capability,
            checkpoint=checkpoint,
            correlation_id=correlation_id,
        )
        records = list(page.records)
        if capability is IngestionCapability.ACCOUNT:
            records = [self._account_record(records[0])]
        elif capability is IngestionCapability.POSITIONS:
            records = [self._position_record(records[0])]
        elif capability is IngestionCapability.TRANSACTIONS:
            records.append(self._transaction_record())
        elif capability is IngestionCapability.DIVIDENDS:
            records.append(self._dividend_record(records[0]))
        return SourcePage(
            records=tuple(records),
            next_checkpoint=page.next_checkpoint,
            complete=page.complete,
            rate=page.rate,
            warnings=page.warnings,
        )

    @staticmethod
    def _account_record(record: SourceRecord) -> SourceRecord:
        payload = dict(record.payload)
        investments = dict(cast(Mapping[str, object], payload["investments"]))
        cash = dict(cast(Mapping[str, object], payload["cash"]))
        invested = Decimal("236590")
        provider_cost = Decimal("218112.651825")
        cash["availableToTrade"] = Decimal("12541.27")
        investments.update(
            {
                "currentValue": invested,
                "totalCost": provider_cost,
                "unrealizedProfitLoss": invested - provider_cost,
            }
        )
        payload["cash"] = cash
        payload["investments"] = investments
        payload["totalValue"] = invested + Decimal("12541.27")
        return _record_revision(record, payload)

    @staticmethod
    def _position_record(record: SourceRecord) -> SourceRecord:
        payload = dict(record.payload)
        wallet = dict(cast(Mapping[str, object], payload["walletImpact"]))
        provider_cost = Decimal("218112.651825")
        wallet.update(
            {
                "currentValue": Decimal("236590"),
                "totalCost": provider_cost,
                "unrealizedProfitLoss": Decimal("236590") - provider_cost,
            }
        )
        payload.update(
            {
                "quantity": Decimal("401"),
                "quantityAvailableForTrading": Decimal("401"),
                "walletImpact": wallet,
            }
        )
        return _record_revision(record, payload)

    @staticmethod
    def _transaction_record() -> SourceRecord:
        return SourceRecord(
            provider_record_id="synthetic-deposit-2",
            source_timestamp=INCREMENTAL_TIME,
            observed_at=INCREMENTAL_TIME,
            payload={
                "amount": Decimal("100"),
                "currency": "EUR",
                "dateTime": INCREMENTAL_TIME,
                "reference": "synthetic-deposit-2",
                "type": "DEPOSIT",
            },
            schema_version="synthetic-phase1:historical_transactions",
        )

    @staticmethod
    def _dividend_record(template: SourceRecord) -> SourceRecord:
        instrument = dict(cast(Mapping[str, object], template.payload["instrument"]))
        return SourceRecord(
            provider_record_id="synthetic-dividend-2",
            source_timestamp=INCREMENTAL_TIME,
            observed_at=INCREMENTAL_TIME,
            payload={
                "amount": Decimal("10"),
                "amountInEuro": Decimal("10"),
                "currency": "EUR",
                "grossAmountPerShare": Decimal("1"),
                "instrument": instrument,
                "paidOn": date(2026, 9, 1),
                "quantity": Decimal("10"),
                "reference": "synthetic-dividend-2",
                "ticker": "SYNEQ",
                "tickerCurrency": "EUR",
                "type": "ORDINARY",
            },
            schema_version="synthetic-phase1:historical_dividends",
        )


def _record_revision(record: SourceRecord, payload: Mapping[str, object]) -> SourceRecord:
    return SourceRecord(
        provider_record_id=record.provider_record_id,
        source_timestamp=INCREMENTAL_TIME,
        observed_at=INCREMENTAL_TIME,
        payload=payload,
        schema_version=record.schema_version,
    )


class TransientOnceSyntheticProvider(SyntheticIngestionProvider):
    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        super().__init__(clock=clock)
        self.failures = 0

    async def read_page(
        self,
        *,
        owner_id: str,
        account_id: str,
        capability: IngestionCapability,
        checkpoint: Checkpoint | None,
        correlation_id: str,
    ) -> SourcePage:
        if self.failures == 0:
            self.failures += 1
            raise IngestionFailure(
                FailureCategory.TRANSIENT,
                "synthetic transient outage",
                retryable=True,
            )
        return await super().read_page(
            owner_id=owner_id,
            account_id=account_id,
            capability=capability,
            checkpoint=checkpoint,
            correlation_id=correlation_id,
        )


@pytest.mark.asyncio
async def test_incremental_production_refresh_adds_transaction_dividend_and_position_change(
    acceptance_database: Engine,
) -> None:
    with Session(acceptance_database) as session:
        before = _economic_counts(session)
        snapshot_count = (
            session.scalar(select(func.count()).select_from(PortfolioSnapshotModel)) or 0
        )
        reconciliation_count = (
            session.scalar(select(func.count()).select_from(ReconciliationRunModel)) or 0
        )

    await _refresh(
        acceptance_database,
        IncrementalSyntheticProvider(clock=lambda: INCREMENTAL_TIME),
        observed_at=INCREMENTAL_TIME,
        idempotency_key="acceptance-incremental-refresh",
        mode=RunMode.INCREMENTAL,
    )

    with Session(acceptance_database) as session:
        after = _economic_counts(session)
        assert after["transactions"] == before["transactions"] + 1
        assert after["dividends"] == before["dividends"] + 1
        assert after["positions"] == before["positions"] + 1
        assert after["cash_balances"] == before["cash_balances"] + 1
        assert after["cash_flows"] == before["cash_flows"] + 1
        assert after["ledger_entries"] == before["ledger_entries"] + 2
        assert after["orders"] == before["orders"]

        latest = session.scalar(
            select(PortfolioSnapshotModel)
            .order_by(PortfolioSnapshotModel.valuation_at.desc())
            .limit(1)
        )
        assert latest is not None
        assert latest.valuation_at == INCREMENTAL_TIME
        assert latest.portfolio_total == Decimal("249131.27")
        assert (
            session.scalar(select(func.count()).select_from(PortfolioSnapshotModel))
            == snapshot_count + 1
        )
        assert (
            session.scalar(select(func.count()).select_from(ReconciliationRunModel))
            == reconciliation_count + 1
        )


@pytest.mark.asyncio
async def test_transient_failure_reuses_durable_run_and_recovers_within_retry_budget(
    acceptance_database: Engine,
) -> None:
    owner_id, account_id = _identity()
    provider = TransientOnceSyntheticProvider(clock=lambda: INCREMENTAL_TIME)
    coordinator = IngestionCoordinator(
        provider=provider,
        store=PostgresIngestionStore(
            create_session_factory(acceptance_database),
            provider="synthetic",
            materializer=PostgresCanonicalMaterializer(),
        ),
        clock=lambda: INCREMENTAL_TIME,
    )

    async def refresh_once() -> IngestionRun:
        return await coordinator.refresh(
            owner_id=owner_id,
            account_id=account_id,
            mode=RunMode.INCREMENTAL,
            idempotency_key="acceptance-transient-retry",
            correlation_id="acceptance-transient-retry",
            capabilities=FULL_REFRESH_ORDER,
        )

    first = await refresh_once()
    recovered = await refresh_once()

    assert first.status is RunStatus.PARTIAL
    assert first.steps[0].failure_category is FailureCategory.TRANSIENT
    assert recovered.status is RunStatus.SUCCEEDED
    assert recovered.id == first.id
    assert provider.failures == 1
