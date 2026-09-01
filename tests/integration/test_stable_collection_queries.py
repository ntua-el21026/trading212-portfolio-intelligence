from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from mcp.types import CallToolResult
from psycopg import sql
from sqlalchemy import Engine, insert, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from trading212_application.queries import (
    ActivityQuery,
    ActivityTypeFilter,
    CursorValidationError,
    DividendQuery,
    DividendSummaryQuery,
    InstrumentQuery,
    PositionQuery,
    PositionSort,
    cursor_binding,
)
from trading212_domain import build_synthetic_identity
from trading212_mcp.server import create_runtime
from trading212_persistence import (
    PostgresPortfolioService,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence.models import (
    BrokerAccountModel,
    CalculationRunModel,
    DividendModel,
    IngestionRunModel,
    InstrumentModel,
    ListingModel,
    PortfolioSnapshotModel,
    SnapshotPositionModel,
    SourceRecordModel,
    TransactionModel,
)
from trading212_persistence.seed import seed_synthetic
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)
CURSOR_KEY = b"stable-collection-query-test-key-v1"
TRANSACTION_COUNT = 10_050
POSITION_COUNT = 60
INSTRUMENT_COUNT = 160
DIVIDEND_CURRENCIES = tuple(f"AA{chr(ord('A') + index)}" for index in range(21))
DIVIDENDS_PER_CURRENCY = 6


def _base_url() -> str:
    value = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio",
    )
    return value.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture(scope="module")
def stable_collection_database() -> Iterator[tuple[str, Engine]]:
    parsed = make_url(_base_url())
    database_name = f"t212pi_collections_{uuid4().hex[:12]}"
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
        seed_synthetic(database_url, app_environment="test")
        engine = create_database_engine(database_url)
        _seed_scale_fixture(engine)
        yield database_url, engine
    finally:
        if engine is not None:
            engine.dispose()
        if not database_name.startswith("t212pi_collections_"):
            raise RuntimeError("refusing to drop an unexpected test database")
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
            )


def _seed_scale_fixture(engine: Engine) -> None:
    identity = build_synthetic_identity()
    account_id = identity.account.id
    run_id = uuid5(NAMESPACE_URL, "t212pi-scale/run")
    source_id = uuid5(NAMESPACE_URL, "t212pi-scale/source")
    calculation_id = uuid5(NAMESPACE_URL, "t212pi-scale/calculation")
    snapshot_id = uuid5(NAMESPACE_URL, "t212pi-scale/snapshot")
    second_account_id = uuid5(NAMESPACE_URL, "t212pi-scale/second-account")
    baseline_created_at = NOW - timedelta(days=1)

    instrument_ids = [
        uuid5(NAMESPACE_URL, f"t212pi-scale/instrument/{index}")
        for index in range(INSTRUMENT_COUNT)
    ]
    listing_ids = [
        uuid5(NAMESPACE_URL, f"t212pi-scale/listing/{index}") for index in range(INSTRUMENT_COUNT)
    ]
    transaction_ids = [
        uuid5(NAMESPACE_URL, f"t212pi-scale/transaction/{index}")
        for index in range(TRANSACTION_COUNT)
    ]

    with Session(engine) as session, session.begin():
        session.add(
            BrokerAccountModel(
                id=second_account_id,
                connection_id=identity.connection.id,
                provider_account_id="synthetic-scale-second-account",
                account_type="invest",
                base_currency="EUR",
                display_name="Synthetic scale second account",
                status="active",
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
        )
        session.add(
            IngestionRunModel(
                id=run_id,
                broker_account_id=account_id,
                capability="historical_transactions",
                mode="full",
                status="succeeded",
                idempotency_key="stable-collection-scale-seed",
                request_schema_version=1,
                requested_mode="full",
                requested_capabilities=["historical_transactions"],
                effective_capabilities=["historical_transactions"],
                request_fingerprint="a" * 64,
                correlation_id="stable-collection-scale-seed",
                started_at=NOW,
                heartbeat_at=NOW,
                completed_at=NOW,
                request_count=1,
                records_received=TRANSACTION_COUNT,
                records_normalized=TRANSACTION_COUNT,
                records_rejected=0,
                warnings=[],
            )
        )
        session.add(
            SourceRecordModel(
                id=source_id,
                ingestion_run_id=run_id,
                broker_account_id=account_id,
                provider="synthetic",
                capability="historical_transactions",
                provider_record_type="scale_fixture",
                provider_record_id="stable-collection-scale-source",
                payload_fingerprint="b" * 64,
                source_updated_at=NOW,
                observed_at=NOW,
                schema_version="stable-collection-scale/1",
                sanitized_payload={"fixture": "stable-collection-scale"},
                created_at=baseline_created_at,
            )
        )
        session.add(
            CalculationRunModel(
                id=calculation_id,
                broker_account_id=account_id,
                calculation_name="portfolio_snapshot",
                version="1.0.0",
                input_schema_version="1",
                output_schema_version="1",
                input_fingerprint="scale-snapshot-input",
                output_fingerprint="scale-snapshot-output",
                calculated_at=NOW,
                valuation_at=NOW,
                source_cutoff_at=NOW,
                reporting_currency="EUR",
                method="stable collection integration fixture",
                assumptions=[],
                options={},
                input_ids=[],
                quality_state="fresh",
                coverage={"complete": True, "gaps": []},
                warnings=[],
                missing_inputs=[],
            )
        )
        session.add(
            PortfolioSnapshotModel(
                id=snapshot_id,
                broker_account_id=account_id,
                calculation_run_id=calculation_id,
                valuation_at=NOW,
                source_cutoff_at=NOW,
                reporting_currency="EUR",
                cash_total=Decimal("0"),
                invested_total=Decimal("60000.000000000000001770"),
                portfolio_total=Decimal("60000.000000000000001770"),
                net_contributions=Decimal("60000"),
                calculation_version="1.0.0",
                quality_state="fresh",
                coverage={"complete": True, "gaps": []},
                warnings=[],
                created_at=baseline_created_at,
            )
        )
        session.flush()

        session.execute(
            insert(InstrumentModel),
            [
                {
                    "id": instrument_id,
                    "canonical_name": f"Unheld scale instrument {index:03d}",
                    "instrument_type": "equity",
                    "isin": None,
                }
                for index, instrument_id in enumerate(instrument_ids)
            ],
        )
        session.execute(
            insert(ListingModel),
            [
                {
                    "id": listing_id,
                    "instrument_id": instrument_ids[index],
                    "provider": "synthetic",
                    "environment": "synthetic",
                    "provider_instrument_id": f"scale-instrument-{index:03d}",
                    "ticker": f"UNH{index:03d}",
                    "exchange_mic": "XTEST",
                    "exchange_id": "synthetic-scale",
                    "trading_currency": "EUR",
                    "status": "active",
                    "valid_from": NOW,
                    "valid_to": None,
                }
                for index, listing_id in enumerate(listing_ids)
            ],
        )
        session.execute(
            insert(SnapshotPositionModel),
            [
                {
                    "id": uuid5(NAMESPACE_URL, f"t212pi-scale/snapshot-position/{index}"),
                    "snapshot_id": snapshot_id,
                    "listing_id": listing_ids[index],
                    "quantity": Decimal("1"),
                    "current_price": Decimal("1000")
                    + Decimal(index) * Decimal("0.000000000000000001"),
                    "market_value": Decimal("1000")
                    + Decimal(index) * Decimal("0.000000000000000001"),
                    "cost_basis": Decimal("900"),
                    "unrealized_pnl": Decimal("100")
                    + Decimal(index) * Decimal("0.000000000000000001"),
                    "currency": "EUR",
                    "quality_state": "fresh",
                    "value_origin": "synthetic_scale_fixture",
                    "provenance": {"origin": "synthetic_scale_fixture"},
                }
                for index in range(POSITION_COUNT)
            ],
        )
        session.execute(
            insert(TransactionModel),
            [
                {
                    "id": transaction_ids[index],
                    "broker_account_id": account_id,
                    "provider_transaction_id": f"scale-transaction-{index:05d}",
                    "transaction_type": "deposit" if index % 2 == 0 else "fee",
                    "status": "completed",
                    "instrument_listing_id": None,
                    "quantity": None,
                    "unit_price": None,
                    "gross_amount": None,
                    "fees": None,
                    "taxes": None,
                    "net_cash_amount": Decimal("1") if index % 2 == 0 else Decimal("-1"),
                    "currency": "EUR",
                    "occurred_at": NOW - timedelta(microseconds=index),
                    "settlement_date": None,
                    "source_record_id": source_id,
                    "mapping_version": "stable-collection-scale/1",
                    "created_at": baseline_created_at,
                }
                for index in range(TRANSACTION_COUNT)
            ],
        )
        dividend_rows: list[dict[str, Any]] = []
        for currency_index, currency in enumerate(DIVIDEND_CURRENCIES):
            for row_index in range(DIVIDENDS_PER_CURRENCY):
                missing_component = currency == "AAA" and row_index == 0
                dividend_rows.append(
                    {
                        "id": uuid5(
                            NAMESPACE_URL,
                            f"t212pi-scale/dividend/{currency}/{row_index}",
                        ),
                        "broker_account_id": account_id,
                        "provider_dividend_id": f"scale-dividend-{currency}-{row_index}",
                        "instrument_listing_id": listing_ids[currency_index],
                        "gross_amount": (None if missing_component else Decimal("1.20")),
                        "withholding_tax": (None if missing_component else Decimal("0.20")),
                        "net_amount": Decimal("1.00"),
                        "currency": currency,
                        "quantity": Decimal("1"),
                        "paid_on": date(2026, 8, 1) + timedelta(days=row_index),
                        "source_record_id": source_id,
                        "created_at": baseline_created_at,
                    }
                )
        session.execute(insert(DividendModel), dividend_rows)


def _principal() -> Principal:
    identity = build_synthetic_identity()
    return Principal(
        principal_id="stable-collection-query-principal",
        owner_id=str(identity.owner.id),
        issuer="local.synthetic",
        subject="synthetic-owner",
        scopes=frozenset(
            {
                Scope.PORTFOLIO_READ,
                Scope.ACTIVITY_READ,
                Scope.PORTFOLIO_REFRESH,
            }
        ),
        authenticated_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=2),
    )


def _tamper(token: str) -> str:
    index = len(token) // 2
    replacement = "A" if token[index] != "A" else "B"
    return f"{token[:index]}{replacement}{token[index + 1 :]}"


def _new_transaction(
    *, account_id: UUID, source_id: UUID, suffix: str, occurred_at: datetime
) -> tuple[UUID, dict[str, Any]]:
    transaction_id = uuid5(NAMESPACE_URL, f"t212pi-scale/inserted/{suffix}")
    return transaction_id, {
        "id": transaction_id,
        "broker_account_id": account_id,
        "provider_transaction_id": f"scale-inserted-{suffix}",
        "transaction_type": "deposit",
        "status": "completed",
        "instrument_listing_id": None,
        "quantity": None,
        "unit_price": None,
        "gross_amount": None,
        "fees": None,
        "taxes": None,
        "net_cash_amount": Decimal("2"),
        "currency": "EUR",
        "occurred_at": occurred_at,
        "settlement_date": None,
        "source_record_id": source_id,
        "mapping_version": "stable-collection-scale/1",
    }


@pytest.mark.asyncio
async def test_postgres_keysets_are_stable_beyond_ui_sized_collections(
    stable_collection_database: tuple[str, Engine],
) -> None:
    database_url, engine = stable_collection_database
    identity = build_synthetic_identity()
    account_id = str(identity.account.id)
    second_account_id = str(uuid5(NAMESPACE_URL, "t212pi-scale/second-account"))
    source_id = uuid5(NAMESPACE_URL, "t212pi-scale/source")
    sessions = create_session_factory(engine)
    service = PostgresPortfolioService(
        sessions=sessions,
        cursor_signing_key=CURSOR_KEY,
        clock=lambda: NOW,
    )
    restarted_service = PostgresPortfolioService(
        sessions=sessions,
        cursor_signing_key=CURSOR_KEY,
        clock=lambda: NOW,
    )
    principal = _principal()

    activity_query = ActivityQuery(
        limit=100,
        start_date=date(2026, 8, 30),
        end_date=date(2026, 8, 31),
    )
    first_activity = await service.list_activity(principal, account_id, query=activity_query)
    assert first_activity.total == TRANSACTION_COUNT
    assert first_activity.next_cursor is not None
    assert len(first_activity.items) == 100

    deposit_page = await service.list_activity(
        principal,
        account_id,
        query=ActivityQuery(
            limit=1,
            start_date=activity_query.start_date,
            end_date=activity_query.end_date,
            activity_type=ActivityTypeFilter.DEPOSIT,
        ),
    )
    assert deposit_page.total == TRANSACTION_COUNT // 2

    with pytest.raises(CursorValidationError):
        await service.list_activity(
            principal,
            account_id,
            query=ActivityQuery(
                cursor=first_activity.next_cursor,
                limit=100,
                start_date=activity_query.start_date,
                end_date=activity_query.end_date,
                activity_type=ActivityTypeFilter.DEPOSIT,
            ),
        )
    with pytest.raises(CursorValidationError):
        await service.list_activity(
            principal,
            second_account_id,
            query=ActivityQuery(
                cursor=first_activity.next_cursor,
                limit=100,
                start_date=activity_query.start_date,
                end_date=activity_query.end_date,
            ),
        )
    with pytest.raises(CursorValidationError):
        await service.list_positions(
            principal,
            account_id,
            query=PositionQuery(cursor=first_activity.next_cursor, limit=10),
        )
    with pytest.raises(CursorValidationError):
        await service.list_activity(
            principal,
            account_id,
            query=ActivityQuery(
                cursor=_tamper(first_activity.next_cursor),
                limit=100,
                start_date=activity_query.start_date,
                end_date=activity_query.end_date,
            ),
        )
    with pytest.raises(CursorValidationError):
        await service.list_activity(
            principal,
            account_id,
            query=ActivityQuery(
                cursor="malformed+cursor",
                limit=100,
                start_date=activity_query.start_date,
                end_date=activity_query.end_date,
            ),
        )

    signed_invalid_cursor = cast(Any, service)._cursors.encode(
        resource="activity",
        binding=cursor_binding(
            account_id,
            activity_query.start_date,
            activity_query.end_date,
            ActivityTypeFilter.ALL,
        ),
        read_cutoff=NOW,
        key=("not-a-timestamp", "not-a-uuid"),
    )
    with pytest.raises(CursorValidationError):
        await service.list_activity(
            principal,
            account_id,
            query=ActivityQuery(
                cursor=signed_invalid_cursor,
                limit=100,
                start_date=activity_query.start_date,
                end_date=activity_query.end_date,
            ),
        )

    newer_id, newer = _new_transaction(
        account_id=identity.account.id,
        source_id=source_id,
        suffix="newer",
        occurred_at=NOW + timedelta(minutes=1),
    )
    backfill_id, backfill = _new_transaction(
        account_id=identity.account.id,
        source_id=source_id,
        suffix="backfill",
        occurred_at=NOW - timedelta(hours=12),
    )
    with Session(engine) as session, session.begin():
        session.execute(insert(TransactionModel), [newer, backfill])
        session.execute(
            update(TransactionModel)
            .where(TransactionModel.id == UUID(first_activity.items[0].id))
            .values(occurred_at=NOW - timedelta(hours=20))
        )
        session.execute(
            update(TransactionModel)
            .where(TransactionModel.id == uuid5(NAMESPACE_URL, "t212pi-scale/transaction/500"))
            .values(occurred_at=NOW + timedelta(minutes=2))
        )

    expected_baseline_ids = {
        str(uuid5(NAMESPACE_URL, f"t212pi-scale/transaction/{index}"))
        for index in range(TRANSACTION_COUNT)
    }
    seen_activity_ids = {item.id for item in first_activity.items}
    cursor: str | None = first_activity.next_cursor
    while cursor is not None:
        activity_page = await restarted_service.list_activity(
            principal,
            account_id,
            query=ActivityQuery(
                cursor=cursor,
                limit=100,
                start_date=activity_query.start_date,
                end_date=activity_query.end_date,
            ),
        )
        assert activity_page.total == TRANSACTION_COUNT
        assert seen_activity_ids.isdisjoint(item.id for item in activity_page.items)
        seen_activity_ids.update(item.id for item in activity_page.items)
        cursor = activity_page.next_cursor
    assert seen_activity_ids == expected_baseline_ids
    assert str(newer_id) not in seen_activity_ids
    assert str(backfill_id) not in seen_activity_ids

    fresh_activity = await service.list_activity(principal, account_id, query=activity_query)
    assert fresh_activity.total == TRANSACTION_COUNT + 2
    fresh_deposits = await service.list_activity(
        principal,
        account_id,
        query=ActivityQuery(
            limit=1,
            start_date=activity_query.start_date,
            end_date=activity_query.end_date,
            activity_type=ActivityTypeFilter.DEPOSIT,
        ),
    )
    assert fresh_deposits.total == TRANSACTION_COUNT // 2 + 2

    expiry_clock = [NOW]
    expiring_service = PostgresPortfolioService(
        sessions=sessions,
        cursor_signing_key=CURSOR_KEY,
        clock=lambda: expiry_clock[0],
        cursor_ttl_seconds=60,
    )
    expiring_page = await expiring_service.list_activity(
        principal, account_id, query=activity_query
    )
    assert expiring_page.next_cursor is not None
    expiry_clock[0] += timedelta(seconds=61)
    with pytest.raises(CursorValidationError):
        await expiring_service.list_activity(
            principal,
            account_id,
            query=ActivityQuery(
                cursor=expiring_page.next_cursor,
                limit=100,
                start_date=activity_query.start_date,
                end_date=activity_query.end_date,
            ),
        )

    first_positions = await service.list_positions(
        principal,
        account_id,
        query=PositionQuery(limit=17, sort=PositionSort.WEIGHT_DESC, search="UNH"),
    )
    assert first_positions.total == POSITION_COUNT
    assert first_positions.next_cursor is not None
    with pytest.raises(CursorValidationError):
        await service.list_positions(
            principal,
            account_id,
            query=PositionQuery(
                cursor=first_positions.next_cursor,
                limit=17,
                sort=PositionSort.MARKET_VALUE_DESC,
                search="UNH",
            ),
        )
    with pytest.raises(CursorValidationError):
        await service.list_positions(
            principal,
            account_id,
            query=PositionQuery(
                cursor=first_positions.next_cursor,
                limit=17,
                sort=PositionSort.WEIGHT_DESC,
                search="OTHER",
            ),
        )

    new_snapshot_id = uuid5(NAMESPACE_URL, "t212pi-scale/newer-snapshot")
    renamed_position_listing_id = uuid5(NAMESPACE_URL, "t212pi-scale/listing/30")
    renamed_position_instrument_id = uuid5(NAMESPACE_URL, "t212pi-scale/instrument/30")
    with Session(engine) as session, session.begin():
        session.execute(
            update(ListingModel)
            .where(ListingModel.id == renamed_position_listing_id)
            .values(ticker="ZZZ999")
        )
        session.execute(
            update(InstrumentModel)
            .where(InstrumentModel.id == renamed_position_instrument_id)
            .values(canonical_name="ZZZ renamed after position page one")
        )
        session.add(
            PortfolioSnapshotModel(
                id=new_snapshot_id,
                broker_account_id=identity.account.id,
                calculation_run_id=uuid5(NAMESPACE_URL, "t212pi-scale/calculation"),
                valuation_at=NOW + timedelta(minutes=5),
                source_cutoff_at=NOW + timedelta(minutes=5),
                reporting_currency="EUR",
                cash_total=Decimal("0"),
                invested_total=Decimal("2000"),
                portfolio_total=Decimal("2000"),
                net_contributions=Decimal("2000"),
                calculation_version="1.0.0",
                quality_state="fresh",
                coverage={"complete": True, "gaps": []},
                warnings=[],
            )
        )
        session.add(
            SnapshotPositionModel(
                id=uuid5(NAMESPACE_URL, "t212pi-scale/newer-snapshot-position"),
                snapshot_id=new_snapshot_id,
                listing_id=uuid5(NAMESPACE_URL, "t212pi-scale/listing/159"),
                quantity=Decimal("1"),
                current_price=Decimal("2000"),
                market_value=Decimal("2000"),
                cost_basis=Decimal("1900"),
                unrealized_pnl=Decimal("100"),
                currency="EUR",
                quality_state="fresh",
                value_origin="synthetic_scale_fixture",
                provenance={"origin": "synthetic_scale_fixture"},
            )
        )

    position_ids = {item.id for item in first_positions.items}
    position_values = [cast(Decimal, item.market_value.value) for item in first_positions.items]
    cursor = first_positions.next_cursor
    while cursor is not None:
        position_page = await restarted_service.list_positions(
            principal,
            account_id,
            query=PositionQuery(
                cursor=cursor,
                limit=17,
                sort=PositionSort.WEIGHT_DESC,
                search="UNH",
            ),
        )
        assert position_page.total == POSITION_COUNT
        assert position_ids.isdisjoint(item.id for item in position_page.items)
        position_ids.update(item.id for item in position_page.items)
        position_values.extend(
            cast(Decimal, item.market_value.value) for item in position_page.items
        )
        cursor = position_page.next_cursor
    assert len(position_ids) == POSITION_COUNT
    assert str(renamed_position_listing_id) in position_ids
    assert position_values == sorted(position_values, reverse=True)
    assert len(set(position_values)) == POSITION_COUNT
    current_positions = await service.list_positions(
        principal,
        account_id,
        query=PositionQuery(limit=10, sort=PositionSort.WEIGHT_DESC),
    )
    assert current_positions.total == 1
    assert current_positions.items[0].ticker == "UNH159"

    with Session(engine) as session, session.begin():
        session.execute(
            update(ListingModel)
            .where(ListingModel.id == renamed_position_listing_id)
            .values(ticker="UNH030")
        )
        session.execute(
            update(InstrumentModel)
            .where(InstrumentModel.id == renamed_position_instrument_id)
            .values(canonical_name="Unheld scale instrument 030")
        )

    first_instruments = await service.search_instruments(
        principal,
        query=InstrumentQuery(limit=50, search="UNH"),
    )
    assert first_instruments.next_cursor is not None
    instrument_ids = {item.instrument_id for item in first_instruments.items}
    instrument_listing_ids = {item.listing_id for item in first_instruments.items}
    instrument_tickers = [item.ticker for item in first_instruments.items]
    instrument_total = first_instruments.total
    changed_listing_id = UUID(first_instruments.items[0].listing_id)
    changed_instrument_id = UUID(first_instruments.items[0].instrument_id)
    with Session(engine) as session, session.begin():
        session.execute(
            update(ListingModel)
            .where(ListingModel.id == changed_listing_id)
            .values(ticker="ZZZ999")
        )
        session.execute(
            update(InstrumentModel)
            .where(InstrumentModel.id == changed_instrument_id)
            .values(canonical_name="ZZZ renamed after page one")
        )
    instrument_cursor: str | None = first_instruments.next_cursor
    while instrument_cursor is not None:
        instrument_page = await service.search_instruments(
            principal,
            query=InstrumentQuery(
                cursor=instrument_cursor,
                limit=50,
                search="UNH",
            ),
        )
        instrument_total = instrument_page.total
        assert instrument_listing_ids.isdisjoint(item.listing_id for item in instrument_page.items)
        instrument_ids.update(item.instrument_id for item in instrument_page.items)
        instrument_listing_ids.update(item.listing_id for item in instrument_page.items)
        instrument_tickers.extend(item.ticker for item in instrument_page.items)
        instrument_cursor = instrument_page.next_cursor
    assert instrument_total == INSTRUMENT_COUNT
    assert len(instrument_ids) == INSTRUMENT_COUNT
    assert len(instrument_listing_ids) == INSTRUMENT_COUNT
    assert instrument_tickers == [f"UNH{index:03d}" for index in range(INSTRUMENT_COUNT)]
    target_instrument_id = str(uuid5(NAMESPACE_URL, "t212pi-scale/instrument/149"))
    assert target_instrument_id in instrument_ids
    assert str(uuid5(NAMESPACE_URL, "t212pi-scale/listing/149")) not in position_ids

    expected_dividend_count = len(DIVIDEND_CURRENCIES) * DIVIDENDS_PER_CURRENCY
    first_dividends = await service.list_dividends(
        principal,
        account_id,
        query=DividendQuery(limit=31),
    )
    assert first_dividends.total == expected_dividend_count
    assert first_dividends.next_cursor is not None
    dividend_ids = {item.id for item in first_dividends.items}
    with Session(engine) as session, session.begin():
        session.execute(
            update(DividendModel)
            .where(DividendModel.id == UUID(first_dividends.items[0].id))
            .values(paid_on=date(2026, 1, 1))
        )
    dividend_cursor: str | None = first_dividends.next_cursor
    while dividend_cursor is not None:
        dividend_page = await service.list_dividends(
            principal,
            account_id,
            query=DividendQuery(cursor=dividend_cursor, limit=31),
        )
        assert dividend_page.total == expected_dividend_count
        assert dividend_ids.isdisjoint(item.id for item in dividend_page.items)
        dividend_ids.update(item.id for item in dividend_page.items)
        dividend_cursor = dividend_page.next_cursor
    assert len(dividend_ids) == expected_dividend_count

    dividend_summary = await service.get_dividend_summary(
        principal,
        account_id,
        query=DividendSummaryQuery(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 8, 31),
            recent_limit=7,
        ),
    )
    assert dividend_summary.covered_record_count == expected_dividend_count
    assert len(dividend_summary.recent) == 7
    assert len(dividend_summary.totals) == 20
    assert dividend_summary.totals_truncated is True
    assert dividend_summary.omitted_currency_count == 1
    assert dividend_summary.quality.state.value == "partial"
    assert "dividend_currency_groups" in dividend_summary.quality.missing_inputs
    assert "dividend_gross_amount" in dividend_summary.quality.missing_inputs
    assert "dividend_withholding_tax" in dividend_summary.quality.missing_inputs
    aaa_total = next(item for item in dividend_summary.totals if item.currency == "AAA")
    assert aaa_total.net_amount == Decimal(DIVIDENDS_PER_CURRENCY)
    assert aaa_total.gross_amount is None
    assert aaa_total.withholding_tax is None

    mcp_runtime = create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
        ),
        service=service,
    )
    mcp_result = await mcp_runtime.server.call_tool(
        "get_dividend_summary",
        {
            "account_id": account_id,
            "start_date": "2026-01-01",
            "end_date": "2026-08-31",
            "recent_limit": 7,
        },
    )
    assert isinstance(mcp_result, CallToolResult)
    assert mcp_result.is_error is False
    structured = cast(dict[str, Any], mcp_result.structured_content)
    assert structured["data"]["covered_record_count"] == expected_dividend_count
    assert len(structured["data"]["totals_by_currency"]) == 20
    assert structured["data"]["totals_truncated"] is True
    assert structured["data"]["omitted_currency_count"] == 1
    assert structured["data_quality"]["state"] == "partial"

    filter_rows: list[dict[str, Any]] = []
    for sequence, canonical_type in enumerate(
        ("tax_withholding", "unknown_provider_activity", "adjustment")
    ):
        _, row = _new_transaction(
            account_id=identity.account.id,
            source_id=source_id,
            suffix=f"activity-filter-{canonical_type}",
            occurred_at=NOW - timedelta(hours=2, microseconds=sequence),
        )
        row["transaction_type"] = canonical_type
        filter_rows.append(row)
    with Session(engine) as session, session.begin():
        session.execute(insert(TransactionModel), filter_rows)

    tax_activity = await service.list_activity(
        principal,
        account_id,
        query=ActivityQuery(
            limit=10,
            start_date=date(2026, 8, 30),
            end_date=date(2026, 8, 31),
            activity_type=ActivityTypeFilter.TAX,
        ),
    )
    unknown_activity = await service.list_activity(
        principal,
        account_id,
        query=ActivityQuery(
            limit=10,
            start_date=date(2026, 8, 30),
            end_date=date(2026, 8, 31),
            activity_type=ActivityTypeFilter.UNKNOWN,
        ),
    )
    fx_activity = await service.list_activity(
        principal,
        account_id,
        query=ActivityQuery(
            limit=10,
            start_date=date(2026, 8, 30),
            end_date=date(2026, 8, 31),
            activity_type=ActivityTypeFilter.FX_CONVERSION,
        ),
    )
    assert [item.activity_type for item in tax_activity.items] == ["tax_withholding"]
    assert tax_activity.total == 1
    assert [item.activity_type for item in unknown_activity.items] == ["unknown_provider_activity"]
    assert unknown_activity.total == 1
    assert fx_activity.items == ()
    assert fx_activity.total == 0

    # A first-page cursor is restart-stable because both adapters use the same key.
    restart_page = await restarted_service.search_instruments(
        principal,
        query=InstrumentQuery(limit=1, search="UNH"),
    )
    assert restart_page.next_cursor is not None
    resumed = await service.search_instruments(
        principal,
        query=InstrumentQuery(
            cursor=restart_page.next_cursor,
            limit=1,
            search="UNH",
        ),
    )
    assert resumed.items[0].ticker == "UNH002"

    # Keep the database URL live in the fixture contract for API/MCP reuse tests.
    assert database_url.startswith("postgresql+psycopg://")
