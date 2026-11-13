"""Actual two-account aggregation, SQL fencing, current authority and physical erasure."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import monotonic
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from trading212_application import aggregation as app
from trading212_application import aggregation_views as views
from trading212_application.ingestion import IngestionCoordinator, RunMode, RunStatus
from trading212_domain.aggregation import (
    AggregateActivityWindow,
    AggregateMember,
    AggregateReason,
    AggregateSelectionContent,
    AggregateView,
)
from trading212_domain.values import CurrencyCode
from trading212_persistence import aggregation_models as m
from trading212_persistence.aggregation_retention import expire_aggregate_payloads
from trading212_persistence.aggregation_service import AggregateDeadline, PostgresAggregateService
from trading212_persistence.models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    PortfolioSnapshotModel,
    SourceRecordModel,
)
from trading212_persistence.premium_models import PremiumCapacityModel
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_worker.materializer import PostgresCanonicalMaterializer
from trading212_worker.postgres_store import PostgresIngestionStore
from trading212_worker.synthetic import SyntheticIngestionProvider
from trading212_worker.synthetic_custody import SyntheticCustodyIngestionProvider
from trading212_worker.synthetic_custody_types import CustodyActivity, CustodyTransferEvidence
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.aggregate_retention_clock import controlled_aggregate_retention_clock
from tests.integration.test_scenario_runs_postgres import grant_scenario_identity
from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case
from tests.unit.worker.test_synthetic_custody import custody_fixture

pytestmark = pytest.mark.integration


async def prepared(
    case: XrayReadCase, *, transfer_mode: str | None = None
) -> tuple[PostgresAggregateService, app.AggregateSelectionView]:
    # These new runs must be live under the unmodified PostgreSQL clock. The
    # shared X-ray fixture's historical August anchor is retained for its own facts.
    case.now[0] = datetime.now(UTC)
    grant_scenario_identity(case.sessions, case.principal, case.now[0])
    owner = UUID(case.principal.owner_id)
    accounts = (uuid4(), uuid4())
    connection = uuid4()
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
                    provider_account_id="aggregate-" + str(account),
                    account_type="invest",
                    base_currency="EUR",
                    display_name="Native aggregate fixture",
                    status="active",
                    first_seen_at=case.now[0],
                    last_seen_at=case.now[0],
                )
            )
    providers: tuple[
        tuple[UUID, SyntheticIngestionProvider | SyntheticCustodyIngestionProvider], ...
    ] = (
        (accounts[0], SyntheticIngestionProvider(clock=lambda: case.now[0])),
        (
            accounts[1],
            SyntheticCustodyIngestionProvider(
                custody_fixture(accounts[1], case.now[0]), clock=lambda: case.now[0]
            ),
        ),
    )
    if transfer_mode is not None:
        values = []
        for index, account in enumerate(accounts):
            currency = CurrencyCode("USD" if transfer_mode == "cross" and index == 1 else "EUR")
            amount = Decimal("-100" if index == 0 else "200" if transfer_mode == "cross" else "100")
            fee = Decimal("-1" if index == 0 else "-2")
            at = case.now[0] - timedelta(hours=1)
            proof = (
                None
                if transfer_mode == "unproven"
                else CustodyTransferEvidence(
                    counterparty_account_id=accounts[1 - index],
                    transfer_reference="retained-native-pair",
                    principal=amount,
                    currency=currency,
                    fx_rate=Decimal("2") if transfer_mode == "cross" else None,
                    fx_base_currency=CurrencyCode("EUR") if transfer_mode == "cross" else None,
                    fx_quote_currency=CurrencyCode("USD") if transfer_mode == "cross" else None,
                    fee_native_record_key="fee" if transfer_mode == "cross" else None,
                    fee_amount=fee if transfer_mode == "cross" else None,
                    fee_currency=currency if transfer_mode == "cross" else None,
                )
            )
            activities: tuple[CustodyActivity, ...] = (
                CustodyActivity(
                    native_record_key="transfer",
                    kind="custody_transfer",
                    booked_at=at,
                    published_at=at,
                    signed_cash=amount,
                    currency=currency,
                    transfer=proof,
                ),
            )
            if transfer_mode == "cross":
                activities += (
                    CustodyActivity(
                        native_record_key="fee",
                        kind="custody_fee",
                        booked_at=at,
                        published_at=at,
                        signed_cash=fee,
                        currency=currency,
                    ),
                )
            native = replace(custody_fixture(account, case.now[0]), activity=activities)
            values.append(
                (account, SyntheticCustodyIngestionProvider(native, clock=lambda: case.now[0]))
            )
        providers = tuple(values)
    for account, provider in providers:
        result = await IngestionCoordinator(
            provider=provider,
            store=PostgresIngestionStore(
                case.sessions, provider="synthetic", materializer=PostgresCanonicalMaterializer()
            ),
            clock=lambda: case.now[0],
        ).refresh(
            owner_id=str(owner),
            account_id=str(account),
            mode=RunMode.FULL,
            idempotency_key=str(uuid4()),
            correlation_id="aggregate-native",
        )
        assert result.status is RunStatus.SUCCEEDED
    with case.sessions() as session:
        snapshots = {
            row.broker_account_id: row.id
            for row in session.scalars(
                select(PortfolioSnapshotModel).where(
                    PortfolioSnapshotModel.broker_account_id.in_(accounts)
                )
            )
        }
    store = PostgresAggregateService(
        case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now[0]
    )
    selected = await store.create_selection(
        case.principal,
        app.CreateAggregateSelection(
            content=AggregateSelectionContent(
                name="Two distinct custody adapters",
                members=tuple(
                    AggregateMember(account_id=account, portfolio_snapshot_id=snapshots[account])
                    for account in accounts
                ),
                reporting_currency=CurrencyCode("EUR"),
                source_cutoff_at=case.now[0],
            ),
            idempotency_key=str(uuid4()),
            correlation_id="aggregate-native",
        ),
    )
    return store, selected


def command(selected: app.AggregateSelectionView) -> app.CreateAggregateRun:
    return app.CreateAggregateRun(
        selection_id=selected.selection_id,
        expected_revision=selected.revision,
        idempotency_key=str(uuid4()),
        correlation_id="aggregate-run",
    )


@contextmanager
def statements(case: XrayReadCase) -> Iterator[list[str]]:
    values: list[str] = []

    def capture(
        _connection: object,
        _cursor: object,
        sql: str,
        _parameters: object,
        _context: object,
        _many: bool,
    ) -> None:
        values.append(sql)

    event.listen(case.engine, "before_cursor_execute", capture)
    try:
        yield values
    finally:
        event.remove(case.engine, "before_cursor_execute", capture)


async def test_native_economic_identity_replay_exact_pages_and_all_member_denial(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    store, selected = await prepared(case)
    request = command(selected)
    with case.engine.connect() as occupied, occupied.begin():
        occupied.execute(
            text(
                "SELECT pg_advisory_xact_lock(hashtextextended('premium:single-execution-slot',0))"
            )
        )
        with pytest.raises(app.AggregateServiceError) as busy:
            await store.create_run(case.principal, request)
        assert busy.value.code is app.AggregateErrorCode.RATE_LIMITED
    run = await store.create_run(case.principal, request)
    assert await store.create_run(case.principal, request) == run
    for view in (AggregateView.HOLDINGS, AggregateView.COMPONENTS, AggregateView.ACCOUNTS):
        with statements(case) as observed:
            first = await store.get_run(
                case.principal, run.run_id, app.AggregateRunQuery(view=view, limit=1)
            )
        assert len(observed) <= 12
        assert isinstance(
            first.page,
            (views.AggregateHoldingPage, views.AggregateComponentPage, views.AggregateAccountPage),
        )
        assert first.page.context.total.value == Decimal("496862.54")
        assert first.page.context.securities.value == Decimal("472000")
        assert first.page.context.cash.value == Decimal("24862.54")
        assert not any("input_payload" in sql or "result_payload" in sql for sql in observed)
    holding = await store.get_run(case.principal, run.run_id, app.AggregateRunQuery())
    assert isinstance(holding.page, views.AggregateHoldingPage) and holding.page.total == 1
    assert holding.page.items[0].quantity == Decimal("800")
    assert len(holding.page.items[0].account_totals) == 2
    narrower = replace(case.principal, scopes=app.AGGREGATE_READ_SCOPES)
    assert (
        await store.get_run(narrower, run.run_id, app.AggregateRunQuery())
    ).run.run_id == run.run_id
    with pytest.raises(app.AggregateServiceError) as activity:
        await store.get_run(
            narrower, run.run_id, app.AggregateRunQuery(view=AggregateView.TRANSFERS)
        )
    assert activity.value.code is app.AggregateErrorCode.ACCESS_DENIED
    second = selected.content.members[1].account_id
    with case.sessions.begin() as session:
        session.execute(
            update(BrokerAccountModel)
            .where(BrokerAccountModel.id == second)
            .values(status="inactive")
        )
    with statements(case) as rejected, pytest.raises(app.AggregateServiceError) as denied:
        await store.get_run(case.principal, run.run_id, app.AggregateRunQuery())
    assert denied.value.code is app.AggregateErrorCode.ACCESS_DENIED
    assert not any(
        "summary_payload" in sql or "aggregate_components.payload" in sql for sql in rejected
    )
    with pytest.raises(app.AggregateServiceError):
        await store.create_run(case.principal, request)


async def test_full_physical_counter_parity_parent_barrier_and_bounded_drain(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    store, selected = await prepared(case)
    run = await store.create_run(case.principal, command(selected))
    owner = UUID(case.principal.owner_id)
    with case.sessions() as session:
        root = session.get(m.AggregateRunModel, run.run_id)
        assert root is not None and root.financial_rows > 0
        actual = session.scalar(text("SELECT aggregate_storage_bytes(:run)"), {"run": run.run_id})
        assert root.retained_bytes == actual > 0
        capacity = session.get(PremiumCapacityModel, owner)
        assert (
            capacity is not None
            and capacity.retained_bytes >= root.retained_bytes
            and capacity.reserved_bytes == 0
        )
        source = session.scalar(
            select(m.AggregateSourceModel.source_record_id)
            .where(
                m.AggregateSourceModel.run_id == run.run_id,
                m.AggregateSourceModel.source_record_id.is_not(None),
            )
            .limit(1)
        )
        assert source is not None
    with case.sessions.begin() as session:
        with pytest.raises(IntegrityError), session.begin_nested():
            session.execute(
                update(SourceRecordModel)
                .where(SourceRecordModel.id == source)
                .values(sanitized_payload=None)
            )
        with pytest.raises(IntegrityError), session.begin_nested():
            session.execute(
                text("UPDATE aggregate_runs SET retained_bytes=0,financial_rows=0 WHERE id=:run"),
                {"run": run.run_id},
            )
        with pytest.raises(IntegrityError), session.begin_nested():
            session.execute(
                text(
                    "INSERT INTO "
                    "aggregate_retention_work(id,owner_id,run_id,reason,created_at) "
                    "VALUES(:id,:owner,:run,'expired',:at)"
                ),
                {"id": uuid4(), "owner": owner, "run": run.run_id, "at": case.now[0]},
            )
    with controlled_aggregate_retention_clock(case, case.now) as advance:
        advance(run.expires_at + timedelta(seconds=1))
        passes = 0
        for _ in range(128):
            budget = SourcePurgeBudget(rows_inspected=256, rows_removed=256)
            with case.sessions.begin() as session:
                expire_aggregate_payloads(session, at=case.now[0], budget=budget, owner=owner)
                root = session.get(m.AggregateRunModel, run.run_id)
                assert root is not None
                assert root.retained_bytes == session.scalar(
                    text("SELECT aggregate_storage_bytes(:run)"), {"run": run.run_id}
                )
                remaining = root.retained_bytes
            assert 0 <= budget.rows_inspected <= 256 and 0 <= budget.rows_removed <= 256
            passes += 1
            if remaining == 0:
                break
        assert passes > 1 and remaining == 0
    with case.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(m.AggregateSourceModel)
                .where(m.AggregateSourceModel.run_id == run.run_id)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(m.AggregateHoldingsPayloadModel)
                .where(m.AggregateHoldingsPayloadModel.run_id == run.run_id)
            )
            == 0
        )
        assert (
            session.scalar(
                select(SourceRecordModel.sanitized_payload).where(SourceRecordModel.id == source)
            )
            is not None
        )
        marker = session.scalar(
            select(m.AggregateRetentionModel).where(m.AggregateRetentionModel.run_id == run.run_id)
        )
        assert marker is not None and marker.completed_at is not None
    expired = await store.get_run(case.principal, run.run_id, app.AggregateRunQuery())
    assert expired.run.state == "expired" and expired.page is None


async def test_original_transaction_deadline_rolls_back_and_pool_gets_fresh_connection(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    store, selected = await prepared(case)

    class ShortDeadline(AggregateDeadline):
        def __init__(self) -> None:
            super().__init__()
            self.expires = monotonic() + 0.08

    def delayed(session: Session, deadline: AggregateDeadline, owner: UUID) -> int:
        # Each individual statement is below80ms; only the original transaction
        # ceiling stops the sequence. A per-query refreshed deadline would not.
        for _ in range(5):
            session.execute(text("SELECT pg_sleep(0.04)"))
        return 1

    with (
        patch("trading212_persistence.aggregation_service.AggregateDeadline", ShortDeadline),
        pytest.raises(app.AggregateServiceError) as stopped,
    ):
        await store._execute(case.principal, delayed)
    assert stopped.value.code is app.AggregateErrorCode.DEADLINE_EXCEEDED
    assert (
        await store.get_selection(case.principal, selected.selection_id)
    ).selection_id == selected.selection_id
    with case.sessions() as session:
        assert session.scalar(text("SELECT 1")) == 1
        assert session.scalar(select(func.count()).select_from(m.AggregateRunModel)) == 0


@pytest.mark.parametrize("mode", ("mutual", "unproven", "cross"))
async def test_original_native_transfer_evidence_and_fees_never_invent_coverage(
    xray_read_case: XrayReadCase, mode: str
) -> None:
    case = xray_read_case
    store, selected = await prepared(case, transfer_mode=mode)
    request = replace(
        command(selected),
        activity_window=AggregateActivityWindow(
            start_at=case.now[0] - timedelta(days=1), end_at=case.now[0]
        ),
    )
    run = await store.create_run(case.principal, request)
    with statements(case) as observed:
        result = await store.get_run(
            case.principal, run.run_id, app.AggregateRunQuery(view=AggregateView.TRANSFERS)
        )
    assert len(observed) <= 12
    assert isinstance(result.page, views.AggregateTransferPage)
    page = result.page
    assert not page.complete and AggregateReason.COVERAGE_INCOMPLETE in page.reasons
    assert all(row.leg.classification != "external" for row in page.items)
    pairs = {row.match.outgoing_record_id: row.match for row in page.items if row.match is not None}
    if mode == "unproven":
        assert not pairs
        assert all(row.leg.classification == "unmatched_transfer" for row in page.items)
    else:
        assert len(pairs) == 1
        pair = next(iter(pairs.values()))
        assert pair.outgoing_principal == Decimal("-100")
        assert pair.incoming_principal == Decimal("200" if mode == "cross" else "100")
        if mode == "cross":
            assert pair.fx_rate == Decimal("2") and len(pair.fee_record_ids) == 2
            assert {
                (str(total.currency), total.external_net, total.fees)
                for total in page.currency_totals
            } == {("EUR", Decimal("0"), Decimal("-1")), ("USD", Decimal("0"), Decimal("-2"))}
        else:
            assert pair.fx_rate is None and pair.fee_record_ids == ()
    assert await store.create_run(case.principal, request) == run
