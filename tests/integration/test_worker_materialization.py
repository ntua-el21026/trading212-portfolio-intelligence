from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Iterator, Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from redis.asyncio import Redis
from sqlalchemy import Engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from trading212_analytics import project_ledger
from trading212_application.ingestion import (
    FULL_REFRESH_ORDER,
    BrokerAccountDataProvider,
    Checkpoint,
    FailureCategory,
    IngestionCapability,
    IngestionCoordinator,
    IngestionFailure,
    RateObservation,
    RunMode,
    RunStatus,
    SourcePage,
    SourceRecord,
)
from trading212_domain import (
    BrokerAccountId,
    CurrencyCode,
    Instant,
    Money,
    ProvenanceReference,
    SourceRecordId,
    Transaction,
    TransactionId,
    TransactionStatus,
    TransactionType,
    ValueOrigin,
    build_synthetic_identity,
)
from trading212_persistence import create_database_engine, create_session_factory
from trading212_persistence.models import (
    CalculationRunModel,
    CashBalanceObservationModel,
    CashFlowModel,
    DividendModel,
    IngestionRunModel,
    LedgerEntryModel,
    ListingModel,
    OrderObservationModel,
    PortfolioSnapshotModel,
    PositionObservationModel,
    ReconciliationDiscrepancyModel,
    ReconciliationRunModel,
    SnapshotPositionModel,
    SourceRecordModel,
    SourceRecordOccurrenceModel,
    TransactionModel,
)
from trading212_provider.client import Trading212Client
from trading212_provider.configuration import BrokerEnvironment, Trading212Settings
from trading212_provider.credentials import StaticCredentialProvider, Trading212Credentials
from trading212_provider.ingestion_adapter import Trading212IngestionAdapter
from trading212_worker.materializer import PostgresCanonicalMaterializer
from trading212_worker.postgres_store import PostgresIngestionStore
from trading212_worker.rate_coordinator import RedisRateCoordinator
from trading212_worker.seed import SEED_TIME, seed_materialized_synthetic
from trading212_worker.synthetic import SyntheticIngestionProvider

pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)


class WalletCurrencyProvider(SyntheticIngestionProvider):
    """Foreign-traded instrument with a selectable provider wallet-value currency."""

    def __init__(
        self,
        *,
        observed_at: datetime,
        wallet_currency: str,
        fx_rate: Decimal | None = None,
    ) -> None:
        super().__init__(clock=lambda: observed_at)
        self._wallet_currency = wallet_currency
        self._fx_rate = fx_rate

    def _payloads(
        self,
        *,
        account_id: str,
        capability: IngestionCapability,
        observed_at: datetime,
    ) -> tuple[tuple[str, datetime, dict[str, object]], ...]:
        rows = super()._payloads(
            account_id=account_id,
            capability=capability,
            observed_at=observed_at,
        )
        rewritten: list[tuple[str, datetime, dict[str, object]]] = []
        for provider_id, source_at, original in rows:
            payload = dict(original)
            if capability is IngestionCapability.INSTRUMENTS:
                payload["currencyCode"] = "USD"
            if capability is IngestionCapability.POSITIONS:
                instrument = dict(_mapping(payload["instrument"]))
                instrument["currency"] = "USD"
                wallet = dict(_mapping(payload["walletImpact"]))
                wallet["currency"] = self._wallet_currency
                if self._fx_rate is not None:
                    wallet["fxRate"] = {
                        "baseCurrency": self._wallet_currency,
                        "quoteCurrency": "EUR",
                        "rate": self._fx_rate,
                        "observedAt": observed_at,
                        "source": "synthetic-explicit-fx-fixture",
                    }
                payload["instrument"] = instrument
                payload["walletImpact"] = wallet
            if capability is IngestionCapability.ACCOUNT and self._fx_rate is not None:
                payload["totalValue"] = Decimal("12431.27") + (Decimal("236000") * self._fx_rate)
            rewritten.append((provider_id, source_at, payload))
        return tuple(rewritten)


class TwoPageRateLimitedProvider(BrokerAccountDataProvider):
    def __init__(self, *, observed_at: datetime, reference: str) -> None:
        self._observed_at = observed_at
        self._reference = reference
        self.calls = 0

    async def read_page(
        self,
        *,
        owner_id: str,
        account_id: str,
        capability: IngestionCapability,
        checkpoint: Checkpoint | None,
        correlation_id: str,
    ) -> SourcePage:
        del owner_id, account_id, correlation_id
        assert capability is IngestionCapability.TRANSACTIONS
        self.calls += 1
        record = SourceRecord(
            provider_record_id=self._reference,
            source_timestamp=self._observed_at,
            observed_at=self._observed_at,
            payload={
                "amount": Decimal("1"),
                "currency": "EUR",
                "dateTime": self._observed_at,
                "reference": self._reference,
                "type": "DEPOSIT",
            },
            schema_version="synthetic-rate-limit:historical_transactions",
        )
        if checkpoint is None or checkpoint.cursor is None:
            return SourcePage(
                records=(record,),
                next_checkpoint=Checkpoint(
                    cursor="rate-page-2",
                    overlap_started_at=(
                        checkpoint.overlap_started_at if checkpoint is not None else None
                    ),
                ),
                complete=False,
                rate=RateObservation(
                    limit=1,
                    period_seconds=2,
                    remaining=0,
                    reset_at=self._observed_at + timedelta(seconds=2),
                    used=1,
                ),
            )
        assert checkpoint.cursor == "rate-page-2"
        return SourcePage(records=(record,), next_checkpoint=None, complete=True)


class ResumableTransactionProvider(BrokerAccountDataProvider):
    def __init__(
        self,
        *,
        observed_at: datetime,
        first_reference: str,
        second_reference: str,
        interrupt_after_first_page: bool,
    ) -> None:
        self._observed_at = observed_at
        self._first_reference = first_reference
        self._second_reference = second_reference
        self._interrupt = interrupt_after_first_page
        self.checkpoints: list[Checkpoint | None] = []

    async def read_page(
        self,
        *,
        owner_id: str,
        account_id: str,
        capability: IngestionCapability,
        checkpoint: Checkpoint | None,
        correlation_id: str,
    ) -> SourcePage:
        del owner_id, account_id, correlation_id
        assert capability is IngestionCapability.TRANSACTIONS
        self.checkpoints.append(checkpoint)
        if checkpoint is None:
            return SourcePage(
                records=(self._record(self._first_reference, self._observed_at),),
                next_checkpoint=Checkpoint(cursor="resumable-page-2"),
                complete=False,
            )
        assert checkpoint.cursor == "resumable-page-2"
        if self._interrupt:
            raise IngestionFailure(FailureCategory.INTERRUPTED, "injected worker interruption")
        return SourcePage(
            records=(
                self._record(
                    self._second_reference,
                    self._observed_at + timedelta(minutes=1),
                ),
            ),
            next_checkpoint=None,
            complete=True,
        )

    @staticmethod
    def _record(reference: str, source_timestamp: datetime) -> SourceRecord:
        return SourceRecord(
            provider_record_id=reference,
            source_timestamp=source_timestamp,
            observed_at=source_timestamp,
            payload={
                "amount": Decimal("1"),
                "currency": "EUR",
                "dateTime": source_timestamp,
                "reference": reference,
                "type": "DEPOSIT",
            },
            schema_version="synthetic-resume:historical_transactions",
        )


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return value


def _base_url() -> str:
    value = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio",
    )
    return value.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture(scope="module")
def materialized_database() -> Iterator[tuple[str, Engine]]:
    parsed = make_url(_base_url())
    database_name = f"t212pi_materializer_{uuid4().hex[:12]}"
    admin = parsed.set(database="postgres")
    admin_dsn = admin.render_as_string(hide_password=False).replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    test_url = parsed.set(database=database_name).render_as_string(hide_password=False)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_url)
    engine: Engine | None = None
    try:
        command.upgrade(config, "head")
        asyncio.run(seed_materialized_synthetic(test_url, app_environment="test"))
        engine = create_database_engine(test_url)
        yield test_url, engine
    finally:
        if engine is not None:
            engine.dispose()
        if not database_name.startswith("t212pi_materializer_"):
            raise RuntimeError("refusing to drop an unexpected test database")
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
            )


def _identity() -> tuple[str, str]:
    fixture = build_synthetic_identity()
    return str(fixture.owner.id), str(fixture.account.id)


async def _synthetic_refresh(
    engine: Engine,
    *,
    observed_at: datetime,
    idempotency_key: str,
    current_price: Decimal,
    include_position: bool,
    reported_total_offset: Decimal = Decimal("0"),
) -> str:
    owner_id, account_id = _identity()
    run = await IngestionCoordinator(
        provider=SyntheticIngestionProvider(
            clock=lambda: observed_at,
            current_price=current_price,
            include_position=include_position,
            reported_total_offset=reported_total_offset,
        ),
        store=PostgresIngestionStore(
            create_session_factory(engine),
            provider="synthetic",
            materializer=PostgresCanonicalMaterializer(),
        ),
        clock=lambda: observed_at,
    ).refresh(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        idempotency_key=idempotency_key,
        correlation_id=idempotency_key,
    )
    assert run.status is RunStatus.SUCCEEDED
    return run.id


@pytest.mark.asyncio
async def test_seed_and_refreshes_materialize_changed_and_empty_current_state(
    materialized_database: tuple[str, Engine],
) -> None:
    _, engine = materialized_database
    changed_run_id = await _synthetic_refresh(
        engine,
        observed_at=NOW,
        idempotency_key="materialized-price-change",
        current_price=Decimal("600"),
        include_position=True,
    )
    empty_run_id = await _synthetic_refresh(
        engine,
        observed_at=NOW + timedelta(hours=1),
        idempotency_key="materialized-empty-position",
        current_price=Decimal("600"),
        include_position=False,
    )

    with Session(engine) as session:
        snapshots = tuple(
            session.scalars(
                select(PortfolioSnapshotModel).order_by(PortfolioSnapshotModel.valuation_at)
            )
        )
        assert [snapshot.valuation_at for snapshot in snapshots] == [
            SEED_TIME,
            NOW,
            NOW + timedelta(hours=1),
        ]
        assert [snapshot.portfolio_total for snapshot in snapshots] == [
            Decimal("248431.27"),
            Decimal("252431.27"),
            Decimal("12431.27"),
        ]
        assert [
            session.scalar(
                select(func.count())
                .select_from(SnapshotPositionModel)
                .where(SnapshotPositionModel.snapshot_id == snapshot.id)
            )
            for snapshot in snapshots
        ] == [1, 1, 0]

        assert session.scalar(select(func.count()).select_from(PositionObservationModel)) == 2
        assert session.scalar(select(func.count()).select_from(CashBalanceObservationModel)) == 3
        assert session.scalar(select(func.count()).select_from(TransactionModel)) == 2
        assert session.scalar(select(func.count()).select_from(DividendModel)) == 1
        assert session.scalar(select(func.count()).select_from(OrderObservationModel)) == 2
        assert session.scalar(select(func.count()).select_from(LedgerEntryModel)) == 3

        reconciliations = tuple(
            session.scalars(select(ReconciliationRunModel).order_by(ReconciliationRunModel.as_of))
        )
        assert len(reconciliations) == 3
        assert all(item.status == "partial" for item in reconciliations)
        assert all(item.quality_state == "partial" for item in reconciliations)
        assert all(item.coverage_complete is False for item in reconciliations)

        position_record_count = session.scalar(
            select(func.count())
            .select_from(SourceRecordModel)
            .where(SourceRecordModel.capability == IngestionCapability.POSITIONS.value)
        )
        assert position_record_count == 2
        empty_occurrences = session.scalar(
            select(func.count())
            .select_from(SourceRecordOccurrenceModel)
            .join(
                SourceRecordModel,
                SourceRecordModel.id == SourceRecordOccurrenceModel.source_record_id,
            )
            .where(
                SourceRecordOccurrenceModel.ingestion_run_id == UUID(empty_run_id),
                SourceRecordModel.capability == IngestionCapability.POSITIONS.value,
            )
        )
        assert empty_occurrences == 0
        changed_occurrences = session.scalar(
            select(func.count())
            .select_from(SourceRecordOccurrenceModel)
            .join(
                SourceRecordModel,
                SourceRecordModel.id == SourceRecordOccurrenceModel.source_record_id,
            )
            .where(
                SourceRecordOccurrenceModel.ingestion_run_id == UUID(changed_run_id),
                SourceRecordModel.capability == IngestionCapability.POSITIONS.value,
            )
        )
        assert changed_occurrences == 1

        empty_run = session.get(IngestionRunModel, UUID(empty_run_id))
        assert empty_run is not None
        assert empty_run.records_normalized > 0


def test_posted_external_flow_revision_is_retained_but_deactivated(
    materialized_database: tuple[str, Engine],
) -> None:
    _, engine = materialized_database
    identity = build_synthetic_identity()
    with Session(engine) as session:
        persisted = session.scalar(
            select(TransactionModel).where(
                TransactionModel.broker_account_id == identity.account.id,
                TransactionModel.provider_transaction_id == "synthetic-deposit-1",
            )
        )
        assert persisted is not None
        source = session.get(SourceRecordModel, persisted.source_record_id)
        assert source is not None
        flow = session.scalar(
            select(CashFlowModel).where(
                CashFlowModel.broker_account_id == identity.account.id,
                CashFlowModel.source_transaction_id == persisted.id,
            )
        )
        assert flow is not None
        assert flow.active is True

        reversed_transaction = Transaction(
            id=TransactionId(persisted.id),
            broker_account_id=BrokerAccountId(identity.account.id),
            provider_transaction_id=persisted.provider_transaction_id,
            transaction_type=TransactionType.DEPOSIT,
            status=TransactionStatus.REVERSED,
            net_cash_amount=Money(persisted.net_cash_amount, CurrencyCode(persisted.currency)),
            occurred_at=Instant(persisted.occurred_at),
            provenance=ProvenanceReference(
                (SourceRecordId(source.id),),
                persisted.mapping_version,
                ValueOrigin.NORMALIZED_PROVIDER,
            ),
        )
        projection = project_ledger(
            (reversed_transaction,),
            account_id=BrokerAccountId(identity.account.id),
            history_complete=True,
        )
        assert projection.entries[0].active is False
        PostgresCanonicalMaterializer()._materialize_transaction_ledger(
            session,
            account_id=identity.account.id,
            projection=projection,
            source_ids={persisted.provider_transaction_id: source},
        )
        session.flush()
        session.expire_all()

        retained = session.scalar(
            select(CashFlowModel).where(
                CashFlowModel.broker_account_id == identity.account.id,
                CashFlowModel.source_transaction_id == persisted.id,
            )
        )
        assert retained is not None
        assert retained.id == flow.id
        assert retained.active is False
        session.rollback()


def test_external_flow_reclassified_as_internal_is_retained_but_deactivated(
    materialized_database: tuple[str, Engine],
) -> None:
    _, engine = materialized_database
    identity = build_synthetic_identity()
    with Session(engine) as session:
        persisted = session.scalar(
            select(TransactionModel).where(
                TransactionModel.broker_account_id == identity.account.id,
                TransactionModel.provider_transaction_id == "synthetic-deposit-1",
            )
        )
        assert persisted is not None
        source = session.get(SourceRecordModel, persisted.source_record_id)
        assert source is not None
        flow = session.scalar(
            select(CashFlowModel).where(
                CashFlowModel.broker_account_id == identity.account.id,
                CashFlowModel.source_transaction_id == persisted.id,
            )
        )
        assert flow is not None
        assert flow.active is True

        reclassified_transaction = Transaction(
            id=TransactionId(persisted.id),
            broker_account_id=BrokerAccountId(identity.account.id),
            provider_transaction_id=persisted.provider_transaction_id,
            transaction_type=TransactionType.BUY,
            status=TransactionStatus.POSTED,
            net_cash_amount=Money(
                -abs(persisted.net_cash_amount),
                CurrencyCode(persisted.currency),
            ),
            occurred_at=Instant(persisted.occurred_at),
            provenance=ProvenanceReference(
                (SourceRecordId(source.id),),
                persisted.mapping_version,
                ValueOrigin.NORMALIZED_PROVIDER,
            ),
        )
        projection = project_ledger(
            (reclassified_transaction,),
            account_id=BrokerAccountId(identity.account.id),
            history_complete=True,
        )
        PostgresCanonicalMaterializer()._materialize_transaction_ledger(
            session,
            account_id=identity.account.id,
            projection=projection,
            source_ids={persisted.provider_transaction_id: source},
        )
        session.flush()
        session.expire_all()

        retained = session.scalar(
            select(CashFlowModel).where(
                CashFlowModel.broker_account_id == identity.account.id,
                CashFlowModel.source_transaction_id == persisted.id,
            )
        )
        assert retained is not None
        assert retained.id == flow.id
        assert retained.active is False
        active_external_flow_ids = tuple(
            session.scalars(
                select(CashFlowModel.id).where(
                    CashFlowModel.broker_account_id == identity.account.id,
                    CashFlowModel.active.is_(True),
                )
            )
        )
        assert retained.id not in active_external_flow_ids
        session.rollback()


@pytest.mark.asyncio
async def test_comparable_provider_total_mismatch_remains_unreconciled(
    materialized_database: tuple[str, Engine],
) -> None:
    _, engine = materialized_database
    mismatch_at = NOW + timedelta(hours=2)
    await _synthetic_refresh(
        engine,
        observed_at=mismatch_at,
        idempotency_key="materialized-provider-total-mismatch",
        current_price=Decimal("600"),
        include_position=True,
        reported_total_offset=Decimal("100"),
    )

    with Session(engine) as session:
        reconciliation = session.scalar(
            select(ReconciliationRunModel).where(ReconciliationRunModel.as_of == mismatch_at)
        )
        assert reconciliation is not None
        assert reconciliation.status == "unreconciled"
        assert reconciliation.quality_state == "unreconciled"
        assert reconciliation.coverage_complete is False
        assert reconciliation.discrepancy_count == 2
        assert {warning["code"] for warning in reconciliation.warnings} == {
            "quantity_cash_history_coverage_gap"
        }


@pytest.mark.asyncio
async def test_redis_rate_limit_waits_and_duplicate_page_is_idempotently_persisted(
    materialized_database: tuple[str, Engine],
) -> None:
    _, engine = materialized_database
    observed_at = NOW + timedelta(days=2)
    owner_id, account_id = _identity()
    reference = f"rate-limited-{uuid4()}"
    provider = TwoPageRateLimitedProvider(observed_at=observed_at, reference=reference)
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    redis_client = Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    digest = hashlib.sha256(
        f"{account_id}\0{IngestionCapability.TRANSACTIONS.value}".encode()
    ).hexdigest()
    coordination_key = f"t212pi:rate:v1:{digest}"
    await redis_client.delete(coordination_key)
    coordinator = RedisRateCoordinator(
        redis_client,
        clock=lambda: observed_at,
        sleep=record_sleep,
        max_cooldown_seconds=10,
    )
    try:
        run = await IngestionCoordinator(
            provider=provider,
            store=PostgresIngestionStore(
                create_session_factory(engine),
                provider="synthetic",
                materializer=PostgresCanonicalMaterializer(),
            ),
            rate_coordinator=coordinator,
            clock=lambda: observed_at,
        ).refresh(
            owner_id=owner_id,
            account_id=account_id,
            mode=RunMode.INCREMENTAL,
            idempotency_key=reference,
            correlation_id=reference,
            capabilities=(IngestionCapability.TRANSACTIONS,),
        )
    finally:
        await redis_client.delete(coordination_key)
        await coordinator.aclose()

    assert run.status is RunStatus.SUCCEEDED
    assert provider.calls == 2
    assert delays == [2.0]
    assert run.steps[0].inserted == 1
    assert run.steps[0].unchanged == 1
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(SourceRecordModel)
                .where(SourceRecordModel.provider_record_id == reference)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(TransactionModel)
                .where(TransactionModel.provider_transaction_id == reference)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(SourceRecordOccurrenceModel)
                .join(
                    SourceRecordModel,
                    SourceRecordModel.id == SourceRecordOccurrenceModel.source_record_id,
                )
                .where(SourceRecordModel.provider_record_id == reference)
            )
            == 1
        )


@pytest.mark.asyncio
async def test_resumed_history_materializes_pages_committed_by_the_failed_predecessor(
    materialized_database: tuple[str, Engine],
) -> None:
    _, engine = materialized_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    observed_at = NOW + timedelta(days=2, hours=1)
    first_reference = f"resume-first-{uuid4()}"
    second_reference = f"resume-second-{uuid4()}"

    interrupted_provider = ResumableTransactionProvider(
        observed_at=observed_at,
        first_reference=first_reference,
        second_reference=second_reference,
        interrupt_after_first_page=True,
    )
    interrupted = await IngestionCoordinator(
        provider=interrupted_provider,
        store=PostgresIngestionStore(
            sessions,
            provider="synthetic",
            materializer=PostgresCanonicalMaterializer(),
        ),
        clock=lambda: observed_at,
    ).refresh(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        idempotency_key=first_reference,
        correlation_id=first_reference,
        capabilities=(IngestionCapability.TRANSACTIONS,),
    )
    assert interrupted.status is RunStatus.FAILED

    resumed_provider = ResumableTransactionProvider(
        observed_at=observed_at,
        first_reference=first_reference,
        second_reference=second_reference,
        interrupt_after_first_page=False,
    )
    resumed = await IngestionCoordinator(
        provider=resumed_provider,
        store=PostgresIngestionStore(
            sessions,
            provider="synthetic",
            materializer=PostgresCanonicalMaterializer(),
        ),
        clock=lambda: observed_at + timedelta(minutes=2),
    ).refresh(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.INCREMENTAL,
        idempotency_key=second_reference,
        correlation_id=second_reference,
        capabilities=(IngestionCapability.TRANSACTIONS,),
    )

    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed_provider.checkpoints == [
        Checkpoint(
            cursor="resumable-page-2",
            source_timestamp=observed_at,
        )
    ]
    with Session(engine) as session:
        persisted_references = set(
            session.scalars(
                select(TransactionModel.provider_transaction_id).where(
                    TransactionModel.provider_transaction_id.in_(
                        (first_reference, second_reference)
                    )
                )
            )
        )
        assert persisted_references == {first_reference, second_reference}


@pytest.mark.asyncio
async def test_provider_wallet_currency_is_retained_and_missing_fx_fails_closed(
    materialized_database: tuple[str, Engine],
) -> None:
    _, engine = materialized_database
    owner_id, account_id = _identity()
    sessions = create_session_factory(engine)

    reporting_wallet_at = NOW + timedelta(days=3)
    reporting_run = await IngestionCoordinator(
        provider=WalletCurrencyProvider(
            observed_at=reporting_wallet_at,
            wallet_currency="EUR",
        ),
        store=PostgresIngestionStore(
            sessions,
            provider="synthetic",
            materializer=PostgresCanonicalMaterializer(),
        ),
        clock=lambda: reporting_wallet_at,
    ).refresh(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        idempotency_key="wallet-reporting-currency",
        correlation_id="wallet-reporting-currency",
        capabilities=FULL_REFRESH_ORDER,
    )
    assert reporting_run.status is RunStatus.SUCCEEDED

    source_wallet_at = reporting_wallet_at + timedelta(hours=1)
    source_run = await IngestionCoordinator(
        provider=WalletCurrencyProvider(
            observed_at=source_wallet_at,
            wallet_currency="USD",
        ),
        store=PostgresIngestionStore(
            sessions,
            provider="synthetic",
            materializer=PostgresCanonicalMaterializer(),
        ),
        clock=lambda: source_wallet_at,
    ).refresh(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        idempotency_key="wallet-source-currency-without-fx",
        correlation_id="wallet-source-currency-without-fx",
        capabilities=FULL_REFRESH_ORDER,
    )
    assert source_run.status is RunStatus.SUCCEEDED

    explicit_fx_at = source_wallet_at + timedelta(hours=1)
    explicit_fx_run = await IngestionCoordinator(
        provider=WalletCurrencyProvider(
            observed_at=explicit_fx_at,
            wallet_currency="USD",
            fx_rate=Decimal("0.9"),
        ),
        store=PostgresIngestionStore(
            sessions,
            provider="synthetic",
            materializer=PostgresCanonicalMaterializer(),
        ),
        clock=lambda: explicit_fx_at,
    ).refresh(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        idempotency_key="wallet-source-currency-with-explicit-fx",
        correlation_id="wallet-source-currency-with-explicit-fx",
        capabilities=FULL_REFRESH_ORDER,
    )
    assert explicit_fx_run.status is RunStatus.SUCCEEDED

    with Session(engine) as session:
        reporting_snapshot = session.scalar(
            select(PortfolioSnapshotModel).where(
                PortfolioSnapshotModel.valuation_at == reporting_wallet_at
            )
        )
        assert reporting_snapshot is not None
        assert reporting_snapshot.reporting_currency == "EUR"
        assert reporting_snapshot.invested_total == Decimal("236000")
        assert reporting_snapshot.portfolio_total == Decimal("248431.27")
        reporting_position = session.scalar(
            select(SnapshotPositionModel).where(
                SnapshotPositionModel.snapshot_id == reporting_snapshot.id
            )
        )
        assert reporting_position is not None
        assert reporting_position.currency == "EUR"
        assert reporting_position.current_price is None
        listing = session.get(ListingModel, reporting_position.listing_id)
        assert listing is not None
        assert listing.trading_currency == "USD"

        source_snapshot = session.scalar(
            select(PortfolioSnapshotModel).where(
                PortfolioSnapshotModel.valuation_at == source_wallet_at
            )
        )
        assert source_snapshot is not None
        assert source_snapshot.reporting_currency == "EUR"
        assert source_snapshot.cash_total == Decimal("12431.27")
        assert source_snapshot.invested_total is None
        assert source_snapshot.portfolio_total is None
        assert source_snapshot.quality_state == "partial"
        source_position = session.scalar(
            select(SnapshotPositionModel).where(
                SnapshotPositionModel.snapshot_id == source_snapshot.id
            )
        )
        assert source_position is not None
        assert source_position.currency == "USD"
        assert source_position.market_value == Decimal("236000")

        calculation = session.get(CalculationRunModel, source_snapshot.calculation_run_id)
        assert calculation is not None
        assert any(item.endswith(":fx") for item in calculation.missing_inputs)
        assert calculation.options == {"fx_policy": "explicit_only", "fx_quotes": []}
        assert "No implicit FX rate is applied" in " ".join(calculation.assumptions)

        reconciliation = session.scalar(
            select(ReconciliationRunModel).where(ReconciliationRunModel.as_of == source_wallet_at)
        )
        assert reconciliation is not None
        assert reconciliation.status == "partial"
        discrepancy_types = set(
            session.scalars(
                select(ReconciliationDiscrepancyModel.discrepancy_type).where(
                    ReconciliationDiscrepancyModel.reconciliation_run_id == reconciliation.id
                )
            )
        )
        assert "currency_fx_gap" in discrepancy_types

        explicit_snapshot = session.scalar(
            select(PortfolioSnapshotModel).where(
                PortfolioSnapshotModel.valuation_at == explicit_fx_at
            )
        )
        assert explicit_snapshot is not None
        assert explicit_snapshot.reporting_currency == "EUR"
        assert explicit_snapshot.invested_total == Decimal("212400")
        assert explicit_snapshot.portfolio_total == Decimal("224831.27")
        assert explicit_snapshot.quality_state == "fresh"
        explicit_position = session.scalar(
            select(SnapshotPositionModel).where(
                SnapshotPositionModel.snapshot_id == explicit_snapshot.id
            )
        )
        assert explicit_position is not None
        assert explicit_position.currency == "EUR"
        assert explicit_position.market_value == Decimal("212400")

        raw_position = session.scalar(
            select(PositionObservationModel).where(
                PositionObservationModel.source_record_id
                == UUID(str(explicit_position.provenance["source_record_ids"][0]))
            )
        )
        assert raw_position is not None
        assert raw_position.valuation_currency == "USD"
        assert raw_position.provider_market_value == Decimal("236000")

        explicit_calculation = session.get(
            CalculationRunModel,
            explicit_snapshot.calculation_run_id,
        )
        assert explicit_calculation is not None
        assert explicit_calculation.missing_inputs == []
        assert explicit_calculation.options == {
            "fx_policy": "explicit_only",
            "fx_quotes": [
                {
                    "listing_id": str(explicit_position.listing_id),
                    "source_record_id": str(raw_position.source_record_id),
                    "base_currency": "USD",
                    "quote_currency": "EUR",
                    "rate": "0.9",
                    "observed_at": explicit_fx_at.isoformat().replace("+00:00", "Z"),
                    "source": "synthetic-explicit-fx-fixture",
                }
            ],
        }
        assert str(raw_position.source_record_id) in explicit_calculation.input_ids
        assert "explicit sourced FX" in " ".join(explicit_calculation.assumptions)

        explicit_reconciliation = session.scalar(
            select(ReconciliationRunModel).where(ReconciliationRunModel.as_of == explicit_fx_at)
        )
        assert explicit_reconciliation is not None
        assert explicit_reconciliation.status == "partial"
        explicit_discrepancy_types = set(
            session.scalars(
                select(ReconciliationDiscrepancyModel.discrepancy_type).where(
                    ReconciliationDiscrepancyModel.reconciliation_run_id
                    == explicit_reconciliation.id
                )
            )
        )
        assert "currency_fx_gap" not in explicit_discrepancy_types
        assert "provider_history_coverage_gap" in explicit_discrepancy_types


@pytest.mark.asyncio
async def test_adapter_dividend_date_is_safely_persisted_to_postgres(
    materialized_database: tuple[str, Engine],
) -> None:
    _, engine = materialized_database

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "amount": 17.5,
                        "amountInEuro": 17.5,
                        "currency": "EUR",
                        "grossAmountPerShare": 1.75,
                        "instrument": {
                            "currency": "EUR",
                            "isin": "XS0000000001",
                            "name": "Synthetic Global Equity",
                            "ticker": "SYNEQ",
                        },
                        "paidOn": "2026-06-30",
                        "quantity": 10,
                        "reference": "adapter-dividend-date-1",
                        "ticker": "SYNEQ",
                        "tickerCurrency": "EUR",
                        "type": "ORDINARY",
                    }
                ],
                "nextPagePath": None,
            },
        )

    client = Trading212Client(
        settings=Trading212Settings(),
        credential_provider=StaticCredentialProvider(
            Trading212Credentials(
                "synthetic-key",
                "synthetic-secret",
                BrokerEnvironment.DEMO,
            )
        ),
        credential_reference="secret://synthetic/demo",
        transport=httpx.MockTransport(handler),
        now=lambda: NOW + timedelta(hours=2),
    )
    owner_id, account_id = _identity()
    try:
        run = await IngestionCoordinator(
            provider=Trading212IngestionAdapter(client),
            store=PostgresIngestionStore(
                create_session_factory(engine),
                provider="synthetic",
            ),
            clock=lambda: NOW + timedelta(hours=2),
        ).refresh(
            owner_id=owner_id,
            account_id=account_id,
            mode=RunMode.INCREMENTAL,
            idempotency_key="adapter-dividend-date-postgres",
            correlation_id="adapter-dividend-date-postgres",
            capabilities=(IngestionCapability.DIVIDENDS,),
        )
    finally:
        await client.aclose()

    assert run.status is RunStatus.SUCCEEDED
    with Session(engine) as session:
        record = session.scalar(
            select(SourceRecordModel).where(
                SourceRecordModel.provider_record_id == "adapter-dividend-date-1"
            )
        )
        assert record is not None
        assert record.sanitized_payload is not None
        assert record.sanitized_payload["paidOn"] == {"$date": date(2026, 6, 30).isoformat()}
