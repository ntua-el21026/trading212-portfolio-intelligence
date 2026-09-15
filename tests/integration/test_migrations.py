from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import DateTime, Engine, Numeric, delete, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from trading212_application.ingestion import IngestionCapability, RunMode
from trading212_application.refresh_semantics import RefreshRequestSemantics
from trading212_persistence import (
    AccountRepository,
    Base,
    CheckpointRepository,
    SourceRecordRepository,
    UnitOfWork,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence.models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    CashFlowModel,
    IngestionCheckpointModel,
    IngestionRunModel,
    InstrumentModel,
    ListingModel,
    OwnerModel,
    PositionObservationModel,
    RefreshDispatcherHeartbeatModel,
    RefreshDispatchOutboxModel,
    SourceRecordModel,
    TransactionModel,
)

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


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
    base_url = make_url(_database_url())
    database_name = f"t212pi_migrations_{uuid4().hex[:12]}"
    admin_url = base_url.set(database="postgres")
    admin_dsn = admin_url.render_as_string(hide_password=False).replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    url = base_url.set(database=database_name).render_as_string(hide_password=False)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    original_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        command.check(config)
        engine = create_database_engine(url)
        yield engine
        engine.dispose()
    finally:
        if original_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_url
        if not database_name.startswith("t212pi_migrations_"):
            raise RuntimeError("refusing to drop an unexpected test database")
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
            )


def _add_identity_graph(session: Session) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID]:
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    owner_id = uuid4()
    connection_id = uuid4()
    account_id = uuid4()
    instrument_id = uuid4()
    listing_id = uuid4()
    run_id = uuid4()
    session.add_all(
        (
            OwnerModel(id=owner_id, display_name="Migration fixture"),
            InstrumentModel(
                id=instrument_id,
                canonical_name="Synthetic instrument",
                instrument_type="equity",
                isin=None,
            ),
        )
    )
    session.flush()
    session.add_all(
        (
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
            display_name="Synthetic",
            status="active",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    session.flush()
    semantics = RefreshRequestSemantics.create(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=(IngestionCapability.POSITIONS,),
    )
    session.add(
        IngestionRunModel(
            id=run_id,
            broker_account_id=account_id,
            capability="portfolio_positions",
            mode="full",
            status="running",
            idempotency_key=f"run-{run_id}",
            request_schema_version=semantics.schema_version,
            requested_mode=semantics.mode.value,
            requested_create_snapshot=semantics.create_snapshot,
            requested_capabilities=semantics.capability_values,
            effective_capabilities=semantics.capability_values,
            request_fingerprint=semantics.fingerprint,
            correlation_id=f"correlation-{run_id}",
            started_at=now,
        )
    )
    session.flush()
    return owner_id, connection_id, account_id, instrument_id, listing_id, run_id


def test_empty_to_head_is_idempotent_and_matches_metadata(database_engine: Engine) -> None:
    inspector = inspect(database_engine)
    actual = set(inspector.get_table_names()) - {"alembic_version"}
    expected = set(Base.metadata.tables)
    assert actual == expected
    with database_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260915_0019"


def test_export_url_cleanup_is_scoped_null_safe_and_repeatable(database_engine: Engine) -> None:
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url", database_engine.url.render_as_string(hide_password=False)
    )
    command.downgrade(config, "20260901_0007")
    now = datetime(2026, 9, 7, tzinfo=UTC)
    token = "_".join(("EXPORT", "URL", "CANARY"))
    host = ".".join(("signed", "example", "invalid"))
    url = f"https://{host}/" + "report" + ".csv?token=" + token
    preserved = {
        "reportId": 19,
        "status": "Finished",
        "dataIncluded": {"includeTransactions": True},
        "nested": {"downloadLink": "non-url unrelated nested value"},
    }
    values: tuple[tuple[str, object, object], ...] = (
        ("historical_exports", {**preserved, "downloadLink": url, "download_link": url}, preserved),
        ("historical_exports", {**preserved, "downloadLink": None}, preserved),
        ("historical_exports", preserved, preserved),
        ("historical_exports", None, None),
        ("historical_exports", None, None),
        ("historical_exports", {}, {}),
        ("historical_exports", [], []),
        ("historical_exports", "legacy scalar", "legacy scalar"),
        (
            "historical_transactions",
            {"downloadLink": "unrelated literal", "download_link": "unrelated literal"},
            {"downloadLink": "unrelated literal", "download_link": "unrelated literal"},
        ),
    )
    rows = []
    with Session(database_engine) as session, session.begin():
        owner_id, _, account_id, instrument_id, listing_id, run_id = _add_identity_graph(session)
        for index, (capability, payload, expected) in enumerate(values):
            record_id = uuid4()
            session.add(
                SourceRecordModel(
                    id=record_id,
                    ingestion_run_id=run_id,
                    broker_account_id=account_id,
                    provider="synthetic",
                    capability=capability,
                    provider_record_type=capability,
                    provider_record_id=f"export-migration-{index}",
                    payload_fingerprint=f"{index:064x}",
                    observed_at=now,
                    schema_version="migration-test-v1",
                    sanitized_payload=payload,
                )
            )
            rows.append((record_id, expected))
        session.flush()
        # Exercise SQL NULL separately from the JSON null produced by the ORM.
        session.execute(
            text("UPDATE source_records SET sanitized_payload = NULL WHERE id = :id"),
            {"id": rows[3][0]},
        )
    try:
        for _ in range(2):
            command.upgrade(config, "head")
            command.upgrade(config, "head")
            command.check(config)
            with Session(database_engine) as session:
                for record_id, expected in rows:
                    record = session.get(SourceRecordModel, record_id)
                    assert record is not None
                    assert record.sanitized_payload == expected
                    assert token not in repr(record.sanitized_payload)
                    assert host not in repr(record.sanitized_payload)
            command.downgrade(config, "20260901_0007")
    finally:
        command.upgrade(config, "head")
        with Session(database_engine) as cleanup, cleanup.begin():
            cleanup.execute(delete(OwnerModel).where(OwnerModel.id == owner_id))
            cleanup.execute(delete(ListingModel).where(ListingModel.id == listing_id))
            cleanup.execute(delete(InstrumentModel).where(InstrumentModel.id == instrument_id))


def test_external_cash_flow_active_state_is_durable(database_engine: Engine) -> None:
    active_column = next(
        column
        for column in inspect(database_engine).get_columns(CashFlowModel.__tablename__)
        if column["name"] == "active"
    )
    assert active_column["nullable"] is False
    assert "true" in str(active_column["default"]).casefold()


def test_external_cash_flow_upgrade_backfills_reversed_source_transactions(
    database_engine: Engine,
) -> None:
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    with Session(database_engine) as session, session.begin():
        owner_id, _, account_id, instrument_id, listing_id, run_id = _add_identity_graph(session)
        source_id = uuid4()
        transaction_id = uuid4()
        cash_flow_id = uuid4()
        session.add(
            SourceRecordModel(
                id=source_id,
                ingestion_run_id=run_id,
                broker_account_id=account_id,
                provider="synthetic",
                capability="historical_transactions",
                provider_record_type="transaction",
                provider_record_id="reversed-before-active-migration",
                payload_fingerprint="f" * 64,
                observed_at=now,
                schema_version="1.0.0",
            )
        )
        session.flush()
        session.add(
            TransactionModel(
                id=transaction_id,
                broker_account_id=account_id,
                provider_transaction_id="reversed-before-active-migration",
                transaction_type="deposit",
                status="reversed",
                instrument_listing_id=None,
                quantity=None,
                unit_price=None,
                gross_amount=None,
                fees=None,
                taxes=None,
                net_cash_amount=Decimal("100"),
                currency="EUR",
                occurred_at=now,
                settlement_date=None,
                source_record_id=source_id,
                mapping_version="migration-fixture/1",
            )
        )
        session.flush()
        session.add(
            CashFlowModel(
                id=cash_flow_id,
                broker_account_id=account_id,
                source_transaction_id=transaction_id,
                classification="external",
                flow_type="deposit",
                amount=Decimal("100"),
                currency="EUR",
                occurred_at=now,
                quality="fresh",
                active=True,
                idempotency_key="reversed-before-active-migration",
                source_record_id=source_id,
            )
        )

    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        database_engine.url.render_as_string(hide_password=False),
    )
    try:
        command.downgrade(config, "20260901_0006")
        command.upgrade(config, "head")
        with Session(database_engine) as session:
            migrated = session.get(CashFlowModel, cash_flow_id)
            assert migrated is not None
            assert migrated.active is False
    finally:
        command.upgrade(config, "head")
        with Session(database_engine) as cleanup, cleanup.begin():
            cleanup.execute(delete(OwnerModel).where(OwnerModel.id == owner_id))
            cleanup.execute(delete(ListingModel).where(ListingModel.id == listing_id))
            cleanup.execute(delete(InstrumentModel).where(InstrumentModel.id == instrument_id))


def test_refresh_outbox_and_request_fingerprint_constraints_are_present(
    database_engine: Engine,
) -> None:
    inspector = inspect(database_engine)
    assert RefreshDispatchOutboxModel.__tablename__ in inspector.get_table_names()
    assert RefreshDispatcherHeartbeatModel.__tablename__ in inspector.get_table_names()
    inspected_run_columns = inspector.get_columns("ingestion_runs")
    run_columns = {column["name"] for column in inspected_run_columns}
    assert {
        "request_schema_version",
        "requested_mode",
        "requested_create_snapshot",
        "requested_capabilities",
        "effective_capabilities",
        "request_fingerprint",
    }.issubset(run_columns)
    create_snapshot_column = next(
        column for column in inspected_run_columns if column["name"] == "requested_create_snapshot"
    )
    assert create_snapshot_column["nullable"] is False
    assert "true" in str(create_snapshot_column["default"]).casefold()
    outbox_columns = {
        column["name"]: column for column in inspector.get_columns("refresh_dispatch_outbox")
    }
    assert outbox_columns["attempt_count"]["nullable"] is False
    assert outbox_columns["consumer_attempt_count"]["nullable"] is False
    assert "0" in str(outbox_columns["consumer_attempt_count"]["default"])
    assert outbox_columns["consecutive_failure_count"]["nullable"] is False
    assert "0" in str(outbox_columns["consecutive_failure_count"]["default"])
    outbox_uniques = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("refresh_dispatch_outbox")
    }
    assert "uq_refresh_dispatch_outbox_run" in outbox_uniques
    outbox_checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("refresh_dispatch_outbox")
    }
    assert {
        "ck_refresh_dispatch_outbox_task_name_fixed",
        "ck_refresh_dispatch_outbox_task_version_supported",
        "ck_refresh_dispatch_outbox_status_allowed",
        "ck_refresh_dispatch_outbox_payload_contract",
        "ck_refresh_dispatch_outbox_claim_owner_format",
        "ck_refresh_dispatch_outbox_publishing_claim_present",
        "ck_refresh_dispatch_outbox_attempt_count_nonnegative",
        "ck_refresh_dispatch_outbox_consumer_attempt_count_bounded",
        "ck_refresh_dispatch_outbox_consecutive_failures_nonnegative",
        "ck_refresh_dispatch_outbox_consecutive_failures_within_attempts",
        "ck_refresh_dispatch_outbox_publication_state_match",
    }.issubset(outbox_checks)
    heartbeat_uniques = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("refresh_dispatcher_heartbeats")
    }
    assert "uq_refresh_dispatcher_heartbeats_identity" in heartbeat_uniques
    lease_columns = {column["name"]: column for column in inspector.get_columns("ingestion_leases")}
    assert lease_columns["fencing_token"]["nullable"] is False
    lease_uniques = {
        constraint["name"] for constraint in inspector.get_unique_constraints("ingestion_leases")
    }
    assert "uq_ingestion_leases_fencing_token" in lease_uniques


def test_refresh_outbox_enforces_consumer_budget_and_publication_marker_state(
    database_engine: Engine,
) -> None:
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    with Session(database_engine) as session, session.begin():
        owner_id, connection_id, account_id, instrument_id, listing_id, run_id = (
            _add_identity_graph(session)
        )
        run = session.get(IngestionRunModel, run_id)
        assert run is not None
        dispatch_id = uuid4()
        session.add(
            RefreshDispatchOutboxModel(
                id=dispatch_id,
                ingestion_run_id=run_id,
                task_name="portfolio.refresh",
                task_version=1,
                payload={
                    "run_id": str(run_id),
                    "account_id": str(account_id),
                    "request_fingerprint": run.request_fingerprint,
                    "request_schema_version": 1,
                },
                status="pending",
                available_at=now,
            )
        )

    with pytest.raises(IntegrityError), database_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE refresh_dispatch_outbox SET consumer_attempt_count = 5 "
                "WHERE id = :dispatch_id"
            ),
            {"dispatch_id": dispatch_id},
        )
    with pytest.raises(IntegrityError), database_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE refresh_dispatch_outbox SET status = 'publishing', "
                "attempt_count = 1, claim_token = :claim_token, "
                "claim_owner = 'migration-invariant-test', claimed_at = :claimed_at, "
                "claim_expires_at = :claim_expires_at, published_at = :published_at "
                "WHERE id = :dispatch_id"
            ),
            {
                "dispatch_id": dispatch_id,
                "claim_token": uuid4(),
                "claimed_at": now,
                "claim_expires_at": now.replace(minute=1),
                "published_at": now,
            },
        )

    with Session(database_engine) as cleanup, cleanup.begin():
        cleanup.execute(delete(IngestionRunModel).where(IngestionRunModel.id == run_id))
        cleanup.execute(delete(BrokerAccountModel).where(BrokerAccountModel.id == account_id))
        cleanup.execute(
            delete(BrokerConnectionModel).where(BrokerConnectionModel.id == connection_id)
        )
        cleanup.execute(delete(OwnerModel).where(OwnerModel.id == owner_id))
        cleanup.execute(delete(ListingModel).where(ListingModel.id == listing_id))
        cleanup.execute(delete(InstrumentModel).where(InstrumentModel.id == instrument_id))


def test_schema_uses_exact_numeric_and_timezone_aware_columns(database_engine: Engine) -> None:
    inspector = inspect(database_engine)
    position_columns = {
        column["name"]: column["type"] for column in inspector.get_columns("position_observations")
    }
    numeric = cast(Numeric[Decimal], position_columns["quantity"])
    assert numeric.precision == 38
    assert numeric.scale == 18
    observed_at_type = cast(DateTime, position_columns["observed_at"])
    assert observed_at_type.timezone is True


def test_decimal_and_utc_round_trip_preserve_values(database_engine: Engine) -> None:
    session = Session(database_engine)
    transaction = session.begin()
    try:
        _, _, account_id, _, listing_id, run_id = _add_identity_graph(session)
        now = datetime(2026, 8, 31, 12, 34, 56, 123456, tzinfo=UTC)
        source_id = uuid4()
        session.add(
            SourceRecordModel(
                id=source_id,
                ingestion_run_id=run_id,
                broker_account_id=account_id,
                provider="synthetic",
                capability="portfolio_positions",
                provider_record_type="position",
                provider_record_id="position-1",
                payload_fingerprint="a" * 64,
                observed_at=now,
                schema_version="1.0.0",
            )
        )
        session.flush()
        expected = Decimal("12345678901234567890.123456789012345678")
        observation = PositionObservationModel(
            broker_account_id=account_id,
            listing_id=listing_id,
            quantity=expected,
            valuation_currency="EUR",
            observed_at=now,
            source_record_id=source_id,
        )
        session.add(observation)
        session.flush()
        session.expire_all()
        loaded = session.get(PositionObservationModel, observation.id)
        assert loaded is not None
        assert loaded.quantity == expected
        assert loaded.observed_at == now
        assert loaded.observed_at.tzinfo is not None
    finally:
        transaction.rollback()
        session.close()


def test_source_record_deduplication_is_idempotent(database_engine: Engine) -> None:
    session = Session(database_engine)
    transaction = session.begin()
    try:
        _, _, account_id, _, _, run_id = _add_identity_graph(session)
        values = {
            "ingestion_run_id": run_id,
            "broker_account_id": account_id,
            "provider": "synthetic",
            "capability": "portfolio_positions",
            "provider_record_type": "position",
            "provider_record_id": "position-dedup",
            "payload_fingerprint": "b" * 64,
            "observed_at": datetime(2026, 8, 31, tzinfo=UTC),
            "schema_version": "1.0.0",
        }
        repository = SourceRecordRepository(session)
        first_id, first_created = repository.insert_idempotent(values.copy())
        second_id, second_created = repository.insert_idempotent(values.copy())
        assert first_id == second_id
        assert first_created is True
        assert second_created is False
        count = session.scalar(
            select(text("count(*)"))
            .select_from(SourceRecordModel)
            .where(SourceRecordModel.payload_fingerprint == "b" * 64)
        )
        assert count == 1
    finally:
        transaction.rollback()
        session.close()


def test_account_repository_enforces_owner_scope(database_engine: Engine) -> None:
    session = Session(database_engine)
    transaction = session.begin()
    try:
        owner_id, _, account_id, _, _, _ = _add_identity_graph(session)
        different_owner_id = uuid4()
        session.add(OwnerModel(id=different_owner_id, display_name="Other owner"))
        session.flush()
        repository = AccountRepository(session)
        assert repository.get_owned(owner_id, account_id) is not None
        assert repository.get_owned(different_owner_id, account_id) is None
        assert tuple(item.id for item in repository.list_owned(owner_id)) == (account_id,)
    finally:
        transaction.rollback()
        session.close()


def test_atomic_rollback_does_not_advance_checkpoint(database_engine: Engine) -> None:
    setup = Session(database_engine)
    try:
        owner_id, _, account_id, instrument_id, listing_id, run_id = _add_identity_graph(setup)
        setup.commit()
        factory = create_session_factory(database_engine)
        with (
            pytest.raises(RuntimeError, match="simulated page failure"),
            UnitOfWork(factory) as unit_of_work,
        ):
            CheckpointRepository(unit_of_work.require_session()).advance(
                account_id=account_id,
                capability="portfolio_positions",
                state={"cursor": "unsafe-to-commit"},
                run_id=run_id,
                coverage_start_at=datetime(2026, 8, 1, tzinfo=UTC),
                coverage_end_at=datetime(2026, 8, 31, tzinfo=UTC),
                coverage_complete=False,
            )
            raise RuntimeError("simulated page failure")
        with Session(database_engine) as verification:
            checkpoint = verification.scalar(
                select(IngestionCheckpointModel).where(
                    IngestionCheckpointModel.broker_account_id == account_id,
                    IngestionCheckpointModel.capability == "portfolio_positions",
                )
            )
            assert checkpoint is None
    finally:
        setup.rollback()
        setup.close()
        with Session(database_engine) as cleanup, cleanup.begin():
            cleanup.execute(delete(OwnerModel).where(OwnerModel.id == owner_id))
            cleanup.execute(delete(ListingModel).where(ListingModel.id == listing_id))
            cleanup.execute(delete(InstrumentModel).where(InstrumentModel.id == instrument_id))


def test_migration_is_current_and_downgrade_policy_is_explicit(database_engine: Engine) -> None:
    del database_engine
    revision = Path("migrations/versions/20260831_0001_baseline_phase_1_schema.py").read_text(
        encoding="utf-8"
    )
    metadata_revision = Path(
        "migrations/versions/20260831_0002_accounting_persistence_metadata.py"
    ).read_text(encoding="utf-8")
    occurrence_revision = Path(
        "migrations/versions/20260831_0003_source_record_occurrences.py"
    ).read_text(encoding="utf-8")
    outbox_revision = Path(
        "migrations/versions/20260901_0004_refresh_dispatch_outbox.py"
    ).read_text(encoding="utf-8")
    collection_snapshot_revision = Path(
        "migrations/versions/20260901_0006_immutable_collection_snapshots.py"
    ).read_text(encoding="utf-8")
    active_cash_flow_revision = Path(
        "migrations/versions/20260901_0007_active_external_cash_flows.py"
    ).read_text(encoding="utf-8")
    target_revision = Path("migrations/versions/20260907_0009_virtual_targets.py").read_text(
        encoding="utf-8"
    )
    planning_revision = Path(
        "migrations/versions/20260907_0010_contribution_planning.py"
    ).read_text(encoding="utf-8")
    policy = Path("migrations/README.md").read_text(encoding="utf-8")
    assert "down_revision" in revision
    assert "def downgrade()" in revision
    source_revision = Path("migrations/versions/20260907_0011_market_sources.py").read_text()
    historical_revision = Path(
        "migrations/versions/20260907_0012_historical_intelligence.py"
    ).read_text()
    xray_revision = Path("migrations/versions/20260909_0013_xray_intelligence.py").read_text()
    report_revision = Path("migrations/versions/20260909_0014_private_reports.py").read_text()
    alert_revision = Path("migrations/versions/20260910_0015_alerts.py").read_text()
    quality_revision = Path("migrations/versions/20260911_0016_intelligence_quality.py").read_text()
    premium_revision = Path("migrations/versions/20260914_0017_premium_risk.py").read_text()
    retention_revision = Path("migrations/versions/20260914_0018_premium_retention.py").read_text()
    premium_report_revision = Path(
        "migrations/versions/20260915_0019_premium_reports.py"
    ).read_text()
    assert revision.count("op.drop_table(") + metadata_revision.count(
        "op.drop_table("
    ) + occurrence_revision.count("op.drop_table(") + outbox_revision.count(
        "op.drop_table("
    ) + collection_snapshot_revision.count("op.drop_table(") + target_revision.count(
        "op.drop_table("
    ) + planning_revision.count("op.drop_table(") + source_revision.count(
        "op.drop_table("
    ) + historical_revision.count("op.drop_table(") + xray_revision.count(
        "op.drop_table("
    ) + report_revision.count("op.drop_table(") + alert_revision.count(
        "op.drop_table("
    ) + quality_revision.count("op.drop_table(") + premium_revision.count(
        "op.drop_table("
    ) + retention_revision.count("op.drop_table(") + premium_report_revision.count(
        "op.drop_table("
    ) == len(Base.metadata.tables)
    assert 'revision = "20260915_0019"' in premium_report_revision
    assert 'down_revision = "20260914_0018"' in premium_report_revision
    assert "trading212_persistence" not in premium_report_revision
    assert 'revision = "20260914_0018"' in retention_revision
    assert 'down_revision = "20260914_0017"' in retention_revision
    assert "trading212_persistence" not in retention_revision
    assert 'revision = "20260914_0017"' in premium_revision
    assert 'down_revision = "20260911_0016"' in premium_revision
    assert "trading212_persistence" not in premium_revision
    assert 'revision = "20260911_0016"' in quality_revision
    assert 'down_revision = "20260910_0015"' in quality_revision
    assert 'revision = "20260910_0015"' in alert_revision
    assert 'down_revision = "20260909_0014"' in alert_revision
    assert 'revision = "20260909_0013"' in xray_revision
    assert 'down_revision = "20260907_0012"' in xray_revision
    assert 'revision = "20260909_0014"' in report_revision
    assert 'down_revision = "20260909_0013"' in report_revision
    assert 'revision: str = "20260831_0002"' in metadata_revision
    assert 'down_revision: str | None = "20260831_0001"' in metadata_revision
    assert 'revision: str = "20260831_0003"' in occurrence_revision
    assert 'down_revision: str | None = "20260831_0002"' in occurrence_revision
    assert 'op.drop_table("source_record_occurrences")' in occurrence_revision
    assert 'revision: str = "20260901_0004"' in outbox_revision
    assert 'down_revision: str | None = "20260831_0003"' in outbox_revision
    assert 'op.drop_table("refresh_dispatch_outbox")' in outbox_revision
    assert 'op.drop_table("refresh_dispatcher_heartbeats")' in outbox_revision
    assert "requested_create_snapshot = TRUE" in outbox_revision
    assert 'op.drop_column("ingestion_runs", "requested_create_snapshot")' in outbox_revision
    assert '"ingestion_leases",\n        sa.Column("fencing_token"' in outbox_revision
    assert 'op.drop_column("ingestion_leases", "fencing_token")' in outbox_revision
    assert 'revision: str = "20260901_0006"' in collection_snapshot_revision
    assert 'down_revision: str | None = "20260901_0005"' in collection_snapshot_revision
    assert 'op.drop_table("collection_query_snapshot_members")' in collection_snapshot_revision
    assert 'op.drop_table("collection_query_snapshots")' in collection_snapshot_revision
    assert 'revision: str = "20260901_0007"' in active_cash_flow_revision
    assert 'down_revision: str | None = "20260901_0006"' in active_cash_flow_revision
    assert "UPDATE cash_flows AS cash_flow" in active_cash_flow_revision
    assert "lower(source_transaction.status) = 'reversed'" in active_cash_flow_revision
    assert 'op.drop_column("cash_flows", "active")' in active_cash_flow_revision
    expected_metadata_drops = {
        'op.drop_column("calculation_runs", "input_ids")',
        'op.drop_column("reconciliation_runs", "quality_state")',
        'op.drop_column("reconciliation_runs", "coverage_complete")',
        'op.drop_column("reconciliation_runs", "coverage_gaps")',
        'op.drop_column("reconciliation_runs", "provenance")',
    }
    assert all(statement in metadata_revision for statement in expected_metadata_drops)
    assert "Production rollbacks are" in policy
    assert "destructive Alembic downgrades are not an operational rollback mechanism" in policy
