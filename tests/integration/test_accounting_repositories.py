from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session
from trading212_domain import (
    BrokerAccountId,
    CalculationMetadata,
    CalculationRunId,
    Coverage,
    CurrencyCode,
    DataQuality,
    DiscrepancyId,
    DiscrepancySeverity,
    DiscrepancyType,
    Instant,
    ListingId,
    Money,
    PortfolioSnapshot,
    ProvenanceReference,
    QualityState,
    Quantity,
    ReconciliationDiscrepancy,
    ReconciliationRun,
    ReconciliationRunId,
    ReconciliationStatus,
    ResolutionState,
    SnapshotCash,
    SnapshotId,
    SnapshotPosition,
    SourceRecordId,
    ValueOrigin,
)
from trading212_persistence import (
    ReconciliationDiscrepancyWrite,
    ReconciliationRepository,
    SnapshotRepository,
    SnapshotWriteContext,
    UnitOfWork,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence.models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    CalculationRunModel,
    InstrumentModel,
    ListingModel,
    OwnerModel,
    PrincipalModel,
    ReconciliationDiscrepancyModel,
    ReconciliationRunModel,
    SnapshotCashModel,
    SnapshotPositionModel,
)

pytestmark = [pytest.mark.integration, pytest.mark.migrations]
EUR = CurrencyCode("EUR")
START = Instant.parse("2026-01-01T00:00:00Z")
END = Instant.parse("2026-08-31T12:00:00Z")


def _database_url() -> str:
    url = os.environ.get(
        "TEST_DATABASE_URL",
        os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio",
        ),
    )
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


@pytest.fixture(scope="module")
def database_engine() -> Iterator[Engine]:
    url = _database_url()
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_database_engine(url)
    yield engine
    engine.dispose()


def _add_identity_graph(session: Session) -> tuple[UUID, UUID, UUID]:
    owner_id = uuid4()
    principal_id = uuid4()
    connection_id = uuid4()
    account_id = uuid4()
    instrument_id = uuid4()
    listing_id = uuid4()
    now = END.value
    session.add_all(
        (
            OwnerModel(id=owner_id, display_name="Accounting repository fixture"),
            InstrumentModel(
                id=instrument_id,
                canonical_name="Accounting fixture instrument",
                instrument_type="equity",
                isin=None,
            ),
        )
    )
    session.flush()
    session.add_all(
        (
            PrincipalModel(
                id=principal_id,
                owner_id=owner_id,
                issuer="synthetic",
                subject=f"principal-{principal_id}",
                status="active",
            ),
            BrokerConnectionModel(
                id=connection_id,
                owner_id=owner_id,
                provider="synthetic",
                environment="synthetic",
                credential_reference=f"synthetic://{connection_id}",
                status="active",
            ),
            ListingModel(
                id=listing_id,
                instrument_id=instrument_id,
                provider="synthetic",
                environment="synthetic",
                provider_instrument_id=f"instrument-{listing_id}",
                ticker=f"SYN{str(listing_id)[:6]}",
                trading_currency="EUR",
                status="active",
                valid_from=now,
            ),
        )
    )
    session.flush()
    session.add(
        BrokerAccountModel(
            id=account_id,
            connection_id=connection_id,
            provider_account_id=f"account-{account_id}",
            account_type="invest",
            base_currency="EUR",
            display_name="Synthetic accounting",
            status="active",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    session.flush()
    return account_id, listing_id, principal_id


def _provenance(seed: int) -> ProvenanceReference:
    return ProvenanceReference(
        (SourceRecordId(UUID(int=100_000 + seed)),),
        "accounting-repository-v1",
        ValueOrigin.DERIVED_DETERMINISTIC,
    )


def _snapshot(
    account_id: UUID,
    listing_id: UUID,
    *,
    identity_seed: int,
    portfolio_total: str = "120",
) -> PortfolioSnapshot:
    quality = DataQuality(QualityState.FRESH, END, 3600, Coverage(START, END, True))
    metadata = CalculationMetadata(
        calculation_name="portfolio_snapshot",
        version="1.0.0",
        run_id=CalculationRunId(UUID(int=200_000 + identity_seed)),
        calculated_at=END,
        valuation_at=END,
        source_cutoff_at=END,
        reporting_currency=EUR,
        input_ids=(UUID(int=300_001), UUID(int=300_002)),
        method="Exact cash plus position aggregation",
        assumptions=("explicit reporting currency",),
        data_quality=quality,
        options={"fx_policy": "on_or_before_cutoff"},
    )
    return PortfolioSnapshot(
        id=SnapshotId(UUID(int=400_000 + identity_seed)),
        broker_account_id=BrokerAccountId(account_id),
        valuation_at=END,
        source_cutoff_at=END,
        reporting_currency=EUR,
        cash_total=Money.parse("20", "EUR"),
        invested_total=Money.parse("100", "EUR"),
        portfolio_total=Money.parse(portfolio_total, "EUR"),
        net_contributions=Money.parse("50", "EUR"),
        positions=(
            SnapshotPosition(
                listing_id=ListingId(listing_id),
                quantity=Quantity.parse("2.5"),
                market_value=Money.parse("100", "EUR"),
                quality=QualityState.FRESH,
                origin=ValueOrigin.DERIVED_DETERMINISTIC,
                current_price=None,
                cost_basis=Money.parse("80", "EUR"),
                unrealized_pnl=Money.parse("20", "EUR"),
            ),
        ),
        cash_components=(
            SnapshotCash(
                Money.parse("20", "EUR"),
                QualityState.FRESH,
                ValueOrigin.OBSERVED_PROVIDER,
            ),
        ),
        calculation=metadata,
        quality=quality,
    )


def _snapshot_context(listing_id: UUID) -> SnapshotWriteContext:
    return SnapshotWriteContext(
        input_schema_version="1.0.0",
        output_schema_version="1.0.0",
        input_fingerprint="a" * 64,
        output_fingerprint="b" * 64,
        position_currencies={ListingId(listing_id): EUR},
        position_provenance={ListingId(listing_id): _provenance(1)},
        cash_provenance={EUR: _provenance(2)},
    )


def test_snapshot_repository_persists_full_graph_and_exact_retry(database_engine: Engine) -> None:
    session = Session(database_engine)
    transaction = session.begin()
    try:
        account_id, listing_id, _ = _add_identity_graph(session)
        repository = SnapshotRepository(session)
        context = _snapshot_context(listing_id)
        first = repository.persist_immutable(
            _snapshot(account_id, listing_id, identity_seed=1),
            context=context,
        )
        retry = repository.persist_immutable(
            _snapshot(account_id, listing_id, identity_seed=2),
            context=context,
        )

        assert first.calculation_run_created and first.snapshot_created
        assert not retry.calculation_run_created and not retry.snapshot_created
        assert retry.calculation_run_id == first.calculation_run_id
        assert retry.snapshot_id == first.snapshot_id
        assert (
            session.scalar(
                select(func.count())
                .select_from(CalculationRunModel)
                .where(CalculationRunModel.broker_account_id == account_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(SnapshotPositionModel)
                .where(SnapshotPositionModel.snapshot_id == first.snapshot_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(SnapshotCashModel)
                .where(SnapshotCashModel.snapshot_id == first.snapshot_id)
            )
            == 1
        )

        calculation = session.get(CalculationRunModel, first.calculation_run_id)
        position = session.scalar(
            select(SnapshotPositionModel).where(
                SnapshotPositionModel.snapshot_id == first.snapshot_id
            )
        )
        assert calculation is not None
        assert calculation.input_ids == [str(UUID(int=300_001)), str(UUID(int=300_002))]
        assert calculation.quality_state == "fresh"
        assert calculation.coverage["complete"] is True
        assert position is not None
        assert position.quantity == Decimal("2.500000000000000000")
        assert position.provenance["mapping_version"] == "accounting-repository-v1"

        with pytest.raises(ValueError, match="immutable portfolio snapshot conflict"):
            repository.persist_immutable(
                _snapshot(
                    account_id,
                    listing_id,
                    identity_seed=3,
                    portfolio_total="121",
                ),
                context=context,
            )
    finally:
        transaction.rollback()
        session.close()


def _reconciliation(
    account_id: UUID,
    listing_id: UUID,
    *,
    identity_seed: int,
    resolution_state: ResolutionState = ResolutionState.OPEN,
    resolution_reason: str | None = None,
) -> tuple[ReconciliationRun, ReconciliationDiscrepancy]:
    run_id = ReconciliationRunId(UUID(int=500_000 + identity_seed))
    run = ReconciliationRun(
        id=run_id,
        broker_account_id=BrokerAccountId(account_id),
        as_of=END,
        algorithm_version="1.0.0",
        tolerance_version="v1",
        status=ReconciliationStatus.UNRECONCILED,
        coverage=Coverage(START, END, False, ("transactions_before_start",)),
        discrepancy_count=1,
    )
    discrepancy = ReconciliationDiscrepancy(
        id=DiscrepancyId(UUID(int=600_000 + identity_seed)),
        reconciliation_run_id=run_id,
        broker_account_id=BrokerAccountId(account_id),
        listing_id=ListingId(listing_id),
        discrepancy_type=DiscrepancyType.QUANTITY_MISMATCH,
        severity=DiscrepancySeverity.ERROR,
        resolution_state=resolution_state,
        first_seen_at=START,
        last_seen_at=END,
        expected_value=Decimal("2.500000000000000000"),
        observed_value=Decimal("2.520000000000000000"),
        residual=Decimal("0.020000000000000000"),
        tolerance=Decimal("0.010000000000000000"),
        downstream_effect="Position and portfolio accounting are unreconciled.",
        currency=EUR,
        likely_cause="missing source activity",
        resolution_reason=resolution_reason,
    )
    return run, discrepancy


def test_reconciliation_repository_persists_metadata_resolution_and_retry(
    database_engine: Engine,
) -> None:
    session = Session(database_engine)
    transaction = session.begin()
    try:
        account_id, listing_id, principal_id = _add_identity_graph(session)
        repository = ReconciliationRepository(session)
        run, discrepancy = _reconciliation(account_id, listing_id, identity_seed=1)
        first = repository.persist_immutable(
            run,
            input_fingerprint="c" * 64,
            quality_state=QualityState.UNRECONCILED,
            provenance=_provenance(3),
            discrepancies=(ReconciliationDiscrepancyWrite(discrepancy, _provenance(4)),),
        )
        retry_run, retry_discrepancy = _reconciliation(account_id, listing_id, identity_seed=2)
        retry = repository.persist_immutable(
            retry_run,
            input_fingerprint="c" * 64,
            quality_state=QualityState.UNRECONCILED,
            provenance=_provenance(3),
            discrepancies=(ReconciliationDiscrepancyWrite(retry_discrepancy, _provenance(4)),),
        )

        assert first.created
        assert not retry.created
        assert retry.reconciliation_run_id == first.reconciliation_run_id
        assert (
            session.scalar(
                select(func.count())
                .select_from(ReconciliationRunModel)
                .where(ReconciliationRunModel.broker_account_id == account_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ReconciliationDiscrepancyModel)
                .where(
                    ReconciliationDiscrepancyModel.reconciliation_run_id
                    == first.reconciliation_run_id
                )
            )
            == 1
        )
        stored_run = session.get(ReconciliationRunModel, first.reconciliation_run_id)
        assert stored_run is not None
        assert stored_run.quality_state == "unreconciled"
        assert stored_run.coverage_complete is False
        assert stored_run.coverage_gaps == ["transactions_before_start"]
        assert stored_run.provenance["mapping_version"] == "accounting-repository-v1"

        resolved_run, resolved_discrepancy = _reconciliation(
            account_id,
            listing_id,
            identity_seed=3,
            resolution_state=ResolutionState.RESOLVED,
            resolution_reason="Verified provider correction.",
        )
        resolved = repository.persist_immutable(
            resolved_run,
            input_fingerprint="d" * 64,
            quality_state=QualityState.UNRECONCILED,
            provenance=_provenance(5),
            discrepancies=(
                ReconciliationDiscrepancyWrite(
                    resolved_discrepancy,
                    _provenance(6),
                    resolved_at=Instant(END.value + timedelta(seconds=1)),
                    resolved_by_principal_id=principal_id,
                ),
            ),
        )
        stored_resolution = session.scalar(
            select(ReconciliationDiscrepancyModel).where(
                ReconciliationDiscrepancyModel.reconciliation_run_id
                == resolved.reconciliation_run_id
            )
        )
        assert stored_resolution is not None
        assert stored_resolution.resolution_state == "resolved"
        assert stored_resolution.resolved_by_principal_id == principal_id
        assert stored_resolution.resolved_at == END.value + timedelta(seconds=1)
    finally:
        transaction.rollback()
        session.close()


def test_unit_of_work_exposes_accounting_repositories(database_engine: Engine) -> None:
    factory = create_session_factory(database_engine)
    with UnitOfWork(factory) as unit_of_work:
        assert isinstance(unit_of_work.snapshots(), SnapshotRepository)
        assert isinstance(unit_of_work.reconciliations(), ReconciliationRepository)
