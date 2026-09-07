from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import Engine, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.planning import calculate_contribution_plan
from trading212_application import planning as a
from trading212_application.planning_jobs import PlanJobFailureCode, PlanJobInputError
from trading212_application.queries import CollectionSnapshotCapacityError, CursorValidationError
from trading212_domain import build_synthetic_identity
from trading212_domain import planning as d
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence import (
    PostgresPlanningService,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence.models import (
    BrokerConnectionModel,
    ListingModel,
    PortfolioSnapshotModel,
    SnapshotPositionModel,
)
from trading212_persistence.planning_models import (
    ContributionPlanJobModel,
    ContributionPlanLineModel,
    ContributionPlanModel,
    ContributionPlanOutboxModel,
    ContributionPlanRequestModel,
    ContributionPlanResultModel,
    PlanningAuditModel,
)
from trading212_persistence.target_models import TargetVersionModel, VirtualPortfolioModel
from trading212_security.principals import Principal, Scope
from trading212_worker.seed import seed_materialized_synthetic

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
KEY = b"planning-postgres-synthetic-cursor-signing-key"


@pytest.fixture(scope="module")
def planning_database() -> Iterator[tuple[Engine, sessionmaker[Session]]]:
    name = "t212pi_planning_" + uuid4().hex[:12]
    admin = "postgresql://portfolio:portfolio@127.0.0.1:5432/postgres"
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/" + name
    engine = None
    try:
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")
        command.check(cfg)
        asyncio.run(seed_materialized_synthetic(url, app_environment="test"))
        engine = create_database_engine(url)
        yield engine, create_session_factory(engine)
    finally:
        if engine is not None:
            engine.dispose()
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


def user(owner: UUID | None = None) -> Principal:
    return Principal(
        "planning-tests",
        str(owner or build_synthetic_identity().owner.id),
        "test",
        "test",
        frozenset(Scope),
        NOW - timedelta(days=1),
        NOW + timedelta(days=10),
    )


def command_input(sessions: sessionmaker[Session]) -> a.CreateContributionPlanCommand:
    account = build_synthetic_identity().account.id
    with sessions() as session:
        version = session.scalar(
            select(TargetVersionModel)
            .join(VirtualPortfolioModel)
            .where(VirtualPortfolioModel.broker_account_id == account)
        )
        snapshot = session.scalar(
            select(PortfolioSnapshotModel).where(
                PortfolioSnapshotModel.broker_account_id == account
            )
        )
        assert version is not None and snapshot is not None
        return a.CreateContributionPlanCommand(
            account_id=str(account),
            virtual_portfolio_id=str(version.virtual_portfolio_id),
            target_version_id=str(version.id),
            snapshot_id=str(snapshot.id),
            options=d.PlanningOptions(
                Money(Decimal("20"), CurrencyCode("EUR")),
                d.PlanningMode.GLOBAL,
                d.CoveragePolicy.ALLOW_DEGRADED,
            ),
        )


def service(
    database: tuple[Engine, sessionmaker[Session]],
    clock: list[datetime] | None = None,
    *,
    quota: int = 64,
) -> PostgresPlanningService:
    return PostgresPlanningService(
        sessions=database[1],
        cursor_signing_key=KEY,
        clock=lambda: NOW if clock is None else clock[0],
        max_active_collection_snapshots_per_owner=quota,
    )


async def create(
    svc: PostgresPlanningService, cmd: a.CreateContributionPlanCommand
) -> a.ContributionPlanJobView:
    return await svc.create_contribution_plan(
        user(), cmd, idempotency_key=uuid4().hex, correlation_id="planning-test"
    )


async def complete(
    svc: PostgresPlanningService, job: a.ContributionPlanJobView
) -> d.ContributionPlanResult:
    from trading212_application.planning_jobs import PlanTaskMessage

    message = PlanTaskMessage(
        job.job_id, job.request_id, user().owner_id, job.account_id, job.input_digest
    )
    claim = await svc.claim_plan_job(message, consumer_id="integration")
    assert claim is not None
    value = await svc.load_plan_job_input(claim)
    result = calculate_contribution_plan(value)
    assert await svc.complete_plan_job(claim, result)
    assert not await svc.complete_plan_job(claim, result)
    return result


@pytest.mark.asyncio
async def test_real_snapshot_plan_is_immutable_idempotent_and_replayable(
    planning_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc = service(planning_database)
    cmd = command_input(planning_database[1])
    key = uuid4().hex
    one = await svc.create_contribution_plan(
        user(),
        cmd,
        idempotency_key=key,
        correlation_id="test",
    )
    replay = await svc.create_contribution_plan(
        user(),
        cmd,
        idempotency_key=key,
        correlation_id="other",
    )
    assert replay == one
    with pytest.raises(a.PlanningServiceError) as mismatch:
        await svc.create_contribution_plan(
            user(),
            replace(
                cmd,
                options=replace(
                    cmd.options, contribution=Money(Decimal("21"), CurrencyCode("EUR"))
                ),
            ),
            idempotency_key=key,
            correlation_id="test",
        )
    assert mismatch.value.code is a.PlanningServiceErrorCode.IDEMPOTENCY_KEY_REUSED
    result = await complete(svc, one)
    assert result.summary.execution_allowed is False
    assert result.summary.residual_cash is not None
    assert sum(
        (x.recommended_amount.amount for x in result.lines), Decimal(0)
    ) + result.summary.residual_cash.amount == Decimal("20")
    fresh = service(planning_database)
    detail = await fresh.get_contribution_plan(
        user(), one.plan_id, query=a.ContributionPlanDetailQuery()
    )
    assert detail.job.state is a.PlanJobState.SUCCEEDED
    assert detail.result == result.summary and detail.lines.items == result.lines
    two = await create(svc, cmd)
    await complete(svc, two)
    second = await svc.get_contribution_plan(
        user(), two.plan_id, query=a.ContributionPlanDetailQuery()
    )
    assert second.content_digest == detail.content_digest and two.input_digest == one.input_digest
    with planning_database[1]() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ContributionPlanResultModel)
                .where(ContributionPlanResultModel.request_id == UUID(one.request_id))
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(PlanningAuditModel)
                .where(PlanningAuditModel.request_id == UUID(one.request_id))
            )
            == 2
        )
    for model, identifier in (
        (ContributionPlanRequestModel, one.request_id),
        (ContributionPlanResultModel, detail.job.plan_revision_id),
    ):
        assert identifier is not None
        with pytest.raises(IntegrityError), planning_database[1].begin() as session:
            session.execute(delete(model).where(model.id == UUID(identifier)))
    with pytest.raises(IntegrityError), planning_database[1].begin() as session:
        session.execute(
            update(ContributionPlanLineModel)
            .where(ContributionPlanLineModel.result_id == UUID(str(detail.job.plan_revision_id)))
            .values(recommended_amount=Decimal("0"))
        )


@pytest.mark.asyncio
async def test_revision_preconditions_history_and_cursor_pin_prior_request(
    planning_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc = service(planning_database)
    cmd = command_input(planning_database[1])
    first = await create(svc, cmd)
    await complete(svc, first)
    key = uuid4().hex
    with pytest.raises(a.PlanningServiceError) as missing:
        await svc.create_contribution_plan_revision(
            user(),
            first.plan_id,
            cmd,
            if_match=None,
            idempotency_key=key,
            correlation_id="test",
        )
    assert missing.value.code is a.PlanningServiceErrorCode.REVISION_REQUIRED
    revised = await svc.create_contribution_plan_revision(
        user(),
        first.plan_id,
        cmd,
        if_match=first.etag,
        idempotency_key=key,
        correlation_id="test",
    )
    assert revised.request_revision == 2
    assert (
        await svc.create_contribution_plan_revision(
            user(),
            first.plan_id,
            cmd,
            if_match=first.etag,
            idempotency_key=key,
            correlation_id="test",
        )
    ) == revised
    await complete(svc, revised)
    query = a.ContributionPlanQuery(
        account_id=first.account_id, plan_id=first.plan_id, include_revisions=True, limit=1
    )
    page = await svc.list_contribution_plans(user(), query=query)
    assert page.total == 2 and page.items[0].job.request_revision == 2 and page.next_cursor
    third = await svc.create_contribution_plan_revision(
        user(),
        first.plan_id,
        cmd,
        if_match=revised.etag,
        idempotency_key=uuid4().hex,
        correlation_id="test",
    )
    assert third.request_revision == 3
    following = await service(planning_database).list_contribution_plans(
        user(), query=replace(query, cursor=page.next_cursor)
    )
    assert following.total == 2 and following.items[0].job.request_revision == 1
    with pytest.raises(a.PlanningServiceError):
        await svc.list_contribution_plans(
            user(), query=replace(query, plan_id=str(uuid4()), cursor=page.next_cursor)
        )


@pytest.mark.asyncio
async def test_pinned_sources_and_listing_mapping_survive_current_projection_changes(
    planning_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc = service(planning_database)
    cmd = command_input(planning_database[1])
    job = await create(svc, cmd)
    from trading212_application.planning_jobs import PlanTaskMessage

    claim = await svc.claim_plan_job(
        PlanTaskMessage(
            job.job_id, job.request_id, user().owner_id, job.account_id, job.input_digest
        ),
        consumer_id="frozen",
    )
    assert claim
    before = await svc.load_plan_job_input(claim)
    assert all(
        p.value is None or p.value.currency.value == "EUR" for p in before.valuation.positions
    )
    assert all(p.fx is None for p in before.valuation.positions), (
        "already converted materialized values must not receive FX twice"
    )
    listing_id = build_synthetic_identity().listing.id
    with planning_database[1].begin() as session:
        session.execute(
            update(ListingModel).where(ListingModel.id == listing_id).values(status="inactive")
        )
    try:
        after = await service(planning_database).load_plan_job_input(claim)
        assert after == before
        result = calculate_contribution_plan(after)
        assert await svc.complete_plan_job(claim, result)
    finally:
        with planning_database[1].begin() as session:
            session.execute(
                update(ListingModel).where(ListingModel.id == listing_id).values(status="active")
            )
    with pytest.raises(IntegrityError), planning_database[1].begin() as session:
        session.execute(
            update(SnapshotPositionModel)
            .where(SnapshotPositionModel.snapshot_id == UUID(cmd.snapshot_id))
            .values(market_value=Decimal("123"))
        )


@pytest.mark.asyncio
async def test_actual_drift_bounds_identity_and_repeat_calculated_time(
    planning_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc = service(planning_database)
    cmd = command_input(planning_database[1])
    query = a.ActualVsTargetQuery(
        snapshot_id=cmd.snapshot_id,
        virtual_portfolio_id=cmd.virtual_portfolio_id,
        target_version_id=cmd.target_version_id,
        reporting_currency=CurrencyCode("EUR"),
        limit=1,
    )
    first = await svc.get_actual_vs_target(user(), cmd.account_id, query=query)
    assert first.rows.total == 3 and len(first.rows.items) == 1 and first.rows.next_cursor
    assert len(first.target_identities) == 3
    holding = next(x for x in first.target_identities if x.holding_id)
    assert holding.id != holding.holding_id
    changed_clock = [NOW + timedelta(minutes=2)]
    next_page = await service(planning_database, changed_clock).get_actual_vs_target(
        user(), cmd.account_id, query=replace(query, cursor=first.rows.next_cursor)
    )
    assert (
        first.content_digest == next_page.content_digest
        and first.calculated_at == next_page.calculated_at
    )
    selected = await svc.get_actual_vs_target(
        user(), cmd.account_id, query=replace(query, node_id=holding.id, cursor=None)
    )
    assert selected.rows.total == 1 and selected.rows.items[0].holding_id == holding.holding_id
    drift = await svc.get_drift_analysis(
        user(),
        cmd.account_id,
        query=a.DriftAnalysisQuery(
            snapshot_id=cmd.snapshot_id,
            virtual_portfolio_id=cmd.virtual_portfolio_id,
            target_version_id=cmd.target_version_id,
            reporting_currency=CurrencyCode("EUR"),
            top_n=1,
        ),
    )
    assert len(drift.groups) + len(drift.leaves) + len(drift.cash_and_unclassified) == 1
    assert drift.eligible_rows == 3 and drift.omitted_rows == 2
    with pytest.raises(CollectionSnapshotCapacityError):
        await service(planning_database, quota=1).get_actual_vs_target(
            user(),
            cmd.account_id,
            query=replace(
                query, node_id=next(x.id for x in first.target_identities if x.key == "growth")
            ),
        )


@pytest.mark.asyncio
async def test_dispatch_consumer_fences_restart_and_attempt_bounds(
    planning_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    clock = [NOW + timedelta(hours=1)]
    svc = service(planning_database, clock)
    job = await create(svc, command_input(planning_database[1]))

    claims = await svc.claim_plan_dispatches(dispatcher_id="restart", limit=100)
    dispatch = next(x for x in claims if x.message.job_id == job.job_id)
    assert await svc.acknowledge_plan_dispatch(dispatch)
    claim = await svc.claim_plan_job(dispatch.message, consumer_id="first")
    assert claim
    assert await svc.claim_plan_job(dispatch.message, consumer_id="duplicate") is None
    clock[0] += timedelta(seconds=61)
    claims = await svc.claim_plan_dispatches(dispatcher_id="restart", limit=100)
    again = next(x for x in claims if x.message.job_id == job.job_id)
    assert again.message == dispatch.message and again.publication_attempt == 2
    assert not await svc.heartbeat_plan_job(claim)
    assert not await svc.fail_plan_job(
        claim, failure_code=PlanJobFailureCode.CALCULATION_FAILED, retryable=False
    )
    for attempt in (2, 3, 4):
        current = await svc.claim_plan_job(again.message, consumer_id="replacement")
        assert current and current.consumer_attempt == attempt
        assert await svc.fail_plan_job(
            current, failure_code=PlanJobFailureCode.STORAGE_UNAVAILABLE, retryable=True
        )
        clock[0] += timedelta(seconds=60)
    with planning_database[1]() as session:
        stored = session.get(ContributionPlanJobModel, UUID(job.job_id))
        assert stored
        assert stored.state == "failed" and stored.consumer_attempts == 4


@pytest.mark.asyncio
async def test_eighth_ambiguous_publication_preserves_delivered_live_consumer(
    planning_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    clock = [NOW + timedelta(hours=3)]
    svc = service(planning_database, clock)
    job = await create(svc, command_input(planning_database[1]))
    dispatch = None
    for number in range(1, 9):
        claims = await svc.claim_plan_dispatches(dispatcher_id="ambiguous", limit=100)
        dispatch = next(x for x in claims if x.message.job_id == job.job_id)
        assert dispatch.publication_attempt == number
        if number < 8:
            assert await svc.defer_plan_dispatch(
                dispatch, failure_code=PlanJobFailureCode.PUBLICATION_UNAVAILABLE
            )
            clock[0] += timedelta(seconds=60)
    assert dispatch
    claim = await svc.claim_plan_job(dispatch.message, consumer_id="delivered")
    assert claim
    assert await svc.defer_plan_dispatch(
        dispatch, failure_code=PlanJobFailureCode.PUBLICATION_UNAVAILABLE
    )
    assert await svc.heartbeat_plan_job(claim)
    result = calculate_contribution_plan(await svc.load_plan_job_input(claim))
    assert await svc.complete_plan_job(claim, result)


@pytest.mark.asyncio
async def test_foreign_owner_and_account_fail_before_durable_mutation(
    planning_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc = service(planning_database)
    cmd = command_input(planning_database[1])
    with planning_database[1]() as session:
        before = session.scalar(select(func.count()).select_from(ContributionPlanRequestModel))
    for principal, request in (
        (user(uuid4()), cmd),
        (user(), replace(cmd, account_id=str(uuid4()))),
    ):
        with pytest.raises(a.PlanningServiceError) as rejected:
            await svc.create_contribution_plan(
                principal, request, idempotency_key=uuid4().hex, correlation_id="foreign"
            )
        assert rejected.value.code is a.PlanningServiceErrorCode.NOT_FOUND
    with planning_database[1]() as session:
        assert (
            session.scalar(select(func.count()).select_from(ContributionPlanRequestModel)) == before
        )


@pytest.mark.asyncio
async def test_owner_graph_is_immutable_and_denied_job_does_not_poison_dispatch(
    planning_database: tuple[Engine, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from trading212_application.planning_jobs import PlanTaskMessage
    from trading212_persistence.planning_job_store import PlanningJobPersistence

    clock = [NOW + timedelta(hours=5)]
    svc = service(planning_database, clock)
    cmd = command_input(planning_database[1])
    queued = await create(svc, cmd)
    running = await create(svc, cmd)
    healthy = await create(svc, cmd)
    claim = await svc.claim_plan_job(
        PlanTaskMessage(
            running.job_id,
            running.request_id,
            user().owner_id,
            running.account_id,
            running.input_digest,
        ),
        consumer_id="revoked",
    )
    assert claim
    identity = build_synthetic_identity()
    with pytest.raises(IntegrityError), planning_database[1].begin() as session:
        session.execute(
            update(BrokerConnectionModel)
            .where(BrokerConnectionModel.id == identity.connection.id)
            .values(owner_id=uuid4())
        )
    original = PlanningJobPersistence._message
    denied = {queued.job_id, running.job_id}

    def authorization_failure(
        self: PlanningJobPersistence,
        session: Session,
        job: ContributionPlanJobModel,
        *,
        authorize: bool = True,
    ) -> PlanTaskMessage:
        if authorize and str(job.id) in denied:
            raise PlanJobInputError(PlanJobFailureCode.ACCESS_DENIED)
        return original(self, session, job, authorize=authorize)

    monkeypatch.setattr(PlanningJobPersistence, "_message", authorization_failure)
    with pytest.raises(PlanJobInputError) as failure:
        await svc.load_plan_job_input(claim)
    assert failure.value.code is PlanJobFailureCode.ACCESS_DENIED
    assert await svc.fail_plan_job(claim, failure_code=failure.value.code, retryable=False)
    dispatched = await svc.claim_plan_dispatches(dispatcher_id="revoked", limit=100)
    assert any(x.message.job_id == healthy.job_id for x in dispatched)
    assert all(x.message.job_id not in denied for x in dispatched)
    with planning_database[1]() as session:
        failed = session.get(ContributionPlanJobModel, UUID(queued.job_id))
        assert failed is not None and failed.state == "failed"


@pytest.mark.asyncio
async def test_concurrent_same_command_has_one_job_request_and_outbox(
    planning_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    cmd = command_input(planning_database[1])
    key = uuid4().hex
    one, two = await asyncio.gather(
        *(
            service(planning_database).create_contribution_plan(
                user(),
                cmd,
                idempotency_key=key,
                correlation_id="concurrent",
            )
            for _ in range(2)
        )
    )
    assert one == two
    with planning_database[1]() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ContributionPlanOutboxModel)
                .where(ContributionPlanOutboxModel.job_id == UUID(one.job_id))
            )
            == 1
        )
    await complete(service(planning_database), one)


@pytest.mark.asyncio
async def test_completion_rechecks_lease_after_validation_and_rolls_back_result(
    planning_database: tuple[Engine, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from trading212_application.planning_jobs import PlanTaskMessage

    clock = [NOW + timedelta(hours=6)]
    svc = service(planning_database, clock)
    job = await create(svc, command_input(planning_database[1]))
    claim = await svc.claim_plan_job(
        PlanTaskMessage(
            job.job_id, job.request_id, user().owner_id, job.account_id, job.input_digest
        ),
        consumer_id="expires-during-validation",
    )
    assert claim
    result = calculate_contribution_plan(await svc.load_plan_job_input(claim))
    original = PostgresPlanningService._persist_plan_result

    def slow_publication(
        self: PostgresPlanningService,
        session: Session,
        request: ContributionPlanRequestModel,
        output: d.ContributionPlanResult,
    ) -> None:
        original(self, session, request, output)
        clock[0] += timedelta(seconds=61)

    monkeypatch.setattr(PostgresPlanningService, "_persist_plan_result", slow_publication)
    assert not await svc.complete_plan_job(claim, result)
    with planning_database[1]() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ContributionPlanResultModel)
                .where(ContributionPlanResultModel.request_id == UUID(job.request_id))
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(PlanningAuditModel)
                .where(
                    PlanningAuditModel.request_id == UUID(job.request_id),
                    PlanningAuditModel.kind == "completed",
                )
            )
            == 0
        )


@pytest.mark.asyncio
async def test_invalid_result_cannot_publish_and_sql_error_context_is_sanitized(
    planning_database: tuple[Engine, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import traceback

    import trading212_persistence.planning_service as module
    from sqlalchemy.exc import OperationalError
    from trading212_application.planning_jobs import PlanTaskMessage
    from trading212_domain.errors import DomainError

    svc = service(planning_database)
    cmd = command_input(planning_database[1])
    job = await create(svc, cmd)
    claim = await svc.claim_plan_job(
        PlanTaskMessage(
            job.job_id, job.request_id, user().owner_id, job.account_id, job.input_digest
        ),
        consumer_id="corrupt-result",
    )
    assert claim
    result = calculate_contribution_plan(await svc.load_plan_job_input(claim))
    with pytest.raises(DomainError):
        await svc.complete_plan_job(
            claim, replace(result, summary=replace(result.summary, execution_allowed=True))
        )
    with planning_database[1]() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ContributionPlanResultModel)
                .where(ContributionPlanResultModel.request_id == UUID(job.request_id))
            )
            == 0
        )
    canary = "SYNTHETIC_PLAN_DB_PRIVATE_CANARY_9c2"

    def fail_capture(*args: object, **kwargs: object) -> d.PlanningInput:
        raise OperationalError("private statement", {"private": canary}, RuntimeError(canary))

    monkeypatch.setattr(module, "capture_input", fail_capture)
    with pytest.raises(a.PlanningServiceError) as failure:
        await create(svc, cmd)
    assert failure.value.code is a.PlanningServiceErrorCode.PLANNING_UNAVAILABLE
    assert failure.value.__cause__ is None and failure.value.__context__ is None
    assert canary not in "".join(traceback.format_exception(failure.value))


@pytest.mark.asyncio
async def test_request_source_and_result_rows_enforce_database_scope(
    planning_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    from trading212_persistence.planning_models import ContributionPlanSelectionModel

    svc = service(planning_database)
    job = await create(svc, command_input(planning_database[1]))
    with planning_database[1]() as session:
        request = session.get(ContributionPlanRequestModel, UUID(job.request_id))
        assert request
        input_value = svc._load_request_input(session, request)
    holding = next(x for x in input_value.node_identities if x.holding_id)
    # Even same-owner valid references cannot append financial input after sealing.
    with pytest.raises(IntegrityError), planning_database[1].begin() as session:
        session.add(
            ContributionPlanSelectionModel(
                owner_id=UUID(user().owner_id),
                request_id=UUID(job.request_id),
                kind="excluded",
                target_node_id=UUID(holding.id),
                holding_id=UUID(str(holding.holding_id)),
                created_at=NOW,
            )
        )
    # Account association is checked against both the owner graph and target portfolio.
    with pytest.raises(IntegrityError), planning_database[1].begin() as session:
        session.add(
            ContributionPlanModel(
                owner_id=UUID(user().owner_id),
                broker_account_id=uuid4(),
                virtual_portfolio_id=UUID(input_value.virtual_portfolio_id),
                revision=1,
                actor_principal_id="scope-test",
                updated_at=NOW,
                created_at=NOW,
            )
        )


@pytest.mark.asyncio
async def test_native_currency_requires_pinned_fx_and_missing_value_remains_unavailable(
    planning_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    import hashlib

    from trading212_persistence.models import (
        CalculationRunModel,
        SnapshotCashModel,
        SourceRecordModel,
    )

    cmd = command_input(planning_database[1])
    svc = service(planning_database)
    snapshots = []
    with planning_database[1].begin() as session:
        original = session.get(PortfolioSnapshotModel, UUID(cmd.snapshot_id))
        assert original
        calculation = session.get(CalculationRunModel, original.calculation_run_id)
        assert calculation
        original_position = session.scalar(
            select(SnapshotPositionModel).where(SnapshotPositionModel.snapshot_id == original.id)
        )
        original_source = session.get(SourceRecordModel, UUID(calculation.input_ids[0]))
        cash_rows = list(
            session.scalars(
                select(SnapshotCashModel).where(SnapshotCashModel.snapshot_id == original.id)
            )
        )
        assert original_position and original_source
        fx_id = uuid4()
        fx_digest = hashlib.sha256(b"synthetic-usd-eur-0.85").hexdigest()
        session.add(
            SourceRecordModel(
                id=fx_id,
                ingestion_run_id=original_source.ingestion_run_id,
                broker_account_id=original.broker_account_id,
                provider="synthetic",
                capability="equity.positions.read",
                provider_record_type="synthetic_fx_fixture",
                provider_record_id=str(fx_id),
                payload_fingerprint=fx_digest,
                source_updated_at=original.source_cutoff_at,
                observed_at=original.source_cutoff_at,
                schema_version="synthetic-fx-v1",
                sanitized_payload={"base": "USD", "quote": "EUR", "rate": "0.85"},
            )
        )
        session.flush()
        for variant in ("fx", "future_fx", "missing_fx", "missing_value"):
            tag = uuid4().hex
            calculation_values = {
                c.name: getattr(calculation, c.name) for c in CalculationRunModel.__table__.columns
            }
            calculation_values.update(
                id=uuid4(),
                version=tag[:20],
                input_fingerprint=hashlib.sha256(tag.encode()).hexdigest(),
                output_fingerprint=hashlib.sha256((tag + "output").encode()).hexdigest(),
                options={
                    "fx_quotes": [
                        {
                            "listing_id": str(original_position.listing_id),
                            "source_record_id": str(fx_id),
                            "base_currency": "USD",
                            "quote_currency": "EUR",
                            "rate": "0.85",
                            "observed_at": (
                                original.source_cutoff_at
                                + (timedelta(hours=1) if variant == "future_fx" else timedelta())
                            ).isoformat(),
                        }
                    ]
                    if variant in {"fx", "future_fx"}
                    else []
                },
                input_ids=[*calculation.input_ids, str(fx_id)],
                missing_inputs=["market_value"] if variant == "missing_value" else [],
            )
            new_calculation = CalculationRunModel(**calculation_values)
            session.add(new_calculation)
            session.flush()
            snapshot_values = {
                c.name: getattr(original, c.name) for c in PortfolioSnapshotModel.__table__.columns
            }
            snapshot_values.update(
                id=uuid4(),
                calculation_run_id=new_calculation.id,
                calculation_version=tag[:20],
                portfolio_total=Decimal("12516.27") if variant == "fx" else None,
                invested_total=Decimal("85") if variant == "fx" else None,
                quality_state="fresh" if variant == "fx" else "partial",
            )
            snapshot = PortfolioSnapshotModel(**snapshot_values)
            session.add(snapshot)
            session.flush()
            position_values = {
                c.name: getattr(original_position, c.name)
                for c in SnapshotPositionModel.__table__.columns
            }
            position_values.update(
                id=uuid4(),
                snapshot_id=snapshot.id,
                market_value=None if variant == "missing_value" else Decimal("100"),
                currency="USD",
            )
            session.add(SnapshotPositionModel(**position_values))
            for cash in cash_rows:
                values = {
                    c.name: getattr(cash, c.name) for c in SnapshotCashModel.__table__.columns
                }
                values.update(id=uuid4(), snapshot_id=snapshot.id)
                session.add(SnapshotCashModel(**values))
            snapshots.append((variant, str(snapshot.id)))
    for variant, snapshot_id in snapshots:
        job = await create(svc, replace(cmd, snapshot_id=snapshot_id))
        result = await complete(svc, job)
        if variant == "fx":
            assert result.summary.outcome in {
                d.PlanOutcome.OPTIMAL,
                d.PlanOutcome.FEASIBLE_NONOPTIMAL,
            }
            assert result.summary.current_cash == Money(Decimal("12431.27"), CurrencyCode("EUR"))
            assert result.summary.post_total == Money(Decimal("12536.27"), CurrencyCode("EUR"))
            assert result.lines[0].current_value == Money(Decimal("85"), CurrencyCode("EUR"))
        else:
            assert result.summary.outcome is d.PlanOutcome.UNAVAILABLE
            assert result.lines == () and result.summary.post_total is None


@pytest.mark.asyncio
async def test_immutable_cache_preserves_source_scope_expiry_quota_and_membership(
    planning_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    from sqlalchemy import text
    from trading212_persistence.models import (
        CollectionQuerySnapshotMemberModel,
        CollectionQuerySnapshotModel,
    )
    from trading212_persistence.planning_models import PlanningCollectionBindingModel

    svc = service(planning_database)
    job = await create(svc, command_input(planning_database[1]))
    query = a.ContributionPlanDetailQuery()
    await svc.get_contribution_plan(user(), job.plan_id, query=query)
    with planning_database[1]() as session:
        pending = session.scalar(
            select(PlanningCollectionBindingModel).where(
                PlanningCollectionBindingModel.request_id == UUID(job.request_id)
            )
        )
        assert pending
        pending_snapshot = pending.collection_snapshot_id
    with pytest.raises(a.PlanningServiceError) as denied:
        await svc.get_contribution_plan(user(uuid4()), job.plan_id, query=query)
    assert denied.value.code is a.PlanningServiceErrorCode.NOT_FOUND
    with planning_database[1].begin() as session:
        session.execute(
            update(CollectionQuerySnapshotModel)
            .where(CollectionQuerySnapshotModel.id == pending_snapshot)
            .values(
                created_at=text("now() - interval '2 hours'"),
                expires_at=text("now() - interval '1 hour'"),
            )
        )
    # An expired reservation is not silently revived, even for an empty immutable page.
    with pytest.raises(CollectionSnapshotCapacityError):
        await service(planning_database, quota=1).get_contribution_plan(
            user(), job.plan_id, query=query
        )
    await svc.get_contribution_plan(user(), job.plan_id, query=query)
    with planning_database[1]() as session:
        renewed = session.scalar(
            select(PlanningCollectionBindingModel).where(
                PlanningCollectionBindingModel.request_id == UUID(job.request_id)
            )
        )
        assert renewed and renewed.collection_snapshot_id != pending_snapshot
    await complete(svc, job)
    ready = await svc.get_contribution_plan(user(), job.plan_id, query=query)
    assert ready.job.plan_revision_id and ready.lines.items
    with planning_database[1]() as session:
        binding = session.scalar(
            select(PlanningCollectionBindingModel).where(
                PlanningCollectionBindingModel.result_id == UUID(ready.job.plan_revision_id)
            )
        )
        assert binding
        ready_snapshot = binding.collection_snapshot_id
        assert ready_snapshot != renewed.collection_snapshot_id
        member = session.scalar(
            select(CollectionQuerySnapshotMemberModel).where(
                CollectionQuerySnapshotMemberModel.snapshot_id == ready_snapshot
            )
        )
        assert member
        original_id = member.record_id
    with planning_database[1].begin() as session:
        session.execute(
            update(CollectionQuerySnapshotMemberModel)
            .where(CollectionQuerySnapshotMemberModel.snapshot_id == ready_snapshot)
            .values(record_id=uuid4())
        )
    try:
        with pytest.raises(CursorValidationError):
            await svc.get_contribution_plan(user(), job.plan_id, query=query)
    finally:
        with planning_database[1].begin() as session:
            session.execute(
                update(CollectionQuerySnapshotMemberModel)
                .where(CollectionQuerySnapshotMemberModel.snapshot_id == ready_snapshot)
                .values(record_id=original_id)
            )
    assert (await svc.get_contribution_plan(user(), job.plan_id, query=query)).lines == ready.lines
