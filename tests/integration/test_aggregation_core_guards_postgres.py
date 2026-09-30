"""Unmodified-clock marker forgery and physical FK/revision integrity regressions."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from trading212_application import aggregation as app
from trading212_domain import CurrencyCode
from trading212_domain.aggregation import (
    AggregateFxBinding,
    AggregateMember,
    AggregateSelectionContent,
)
from trading212_persistence import aggregation_models as m
from trading212_persistence.aggregation_service import PostgresAggregateService

from scripts.api_e2e_aggregation import (
    EUR_ACCOUNT_ID,
    USD_ACCOUNT_ID,
    seed_aggregation_browser_scenario,
)
from tests.integration.test_aggregation_postgres import command, prepared
from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


async def test_live_run_future_expiry_marker_rejected_by_unmodified_database_clock(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    case.now[0] = datetime.now(UTC)
    store, selected = await prepared(case)
    run = await store.create_run(case.principal, command(selected))
    owner = UUID(case.principal.owner_id)
    with case.sessions.begin() as session:
        with (
            pytest.raises(IntegrityError, match="metadata is in the future"),
            session.begin_nested(),
        ):
            session.execute(
                text(
                    "INSERT INTO aggregate_retention_work "
                    "(id,owner_id,run_id,reason,created_at) VALUES(:id,:owner,:run,'expired',:at)"
                ),
                {"id": uuid4(), "owner": owner, "run": run.run_id, "at": run.expires_at},
            )
        assert (
            session.scalar(
                select(m.AggregateRetentionModel.id).where(
                    m.AggregateRetentionModel.run_id == run.run_id
                )
            )
            is None
        )
    assert (
        await store.get_run(case.principal, run.run_id, app.AggregateRunQuery())
    ).page is not None


async def test_marker_completion_and_owner_creation_reject_future_clock_without_substitution(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    case.now[0] = datetime.now(UTC)
    store, selected = await prepared(case)
    run = await store.create_run(case.principal, command(selected))
    owner = UUID(case.principal.owner_id)
    future = datetime.now(UTC) + timedelta(days=1)
    with case.sessions.begin() as session:
        session.execute(
            text("UPDATE principals SET status='disabled' WHERE owner_id=:owner"), {"owner": owner}
        )
        session.execute(
            text("UPDATE broker_connections SET status='inactive' WHERE owner_id=:owner"),
            {"owner": owner},
        )
        with (
            pytest.raises(IntegrityError, match="metadata is in the future"),
            session.begin_nested(),
        ):
            session.execute(
                text("INSERT INTO aggregate_owner_erasure(owner_id,created_at) VALUES(:owner,:at)"),
                {"owner": owner, "at": future},
            )
        session.execute(
            text(
                "INSERT INTO aggregate_owner_erasure(owner_id,created_at) "
                "VALUES(:owner,clock_timestamp())"
            ),
            {"owner": owner},
        )
        session.execute(
            text(
                "INSERT INTO aggregate_retention_work(id,owner_id,run_id,reason,created_at) "
                "VALUES(:id,:owner,:run,'owner_erasure',clock_timestamp())"
            ),
            {"id": uuid4(), "owner": owner, "run": run.run_id},
        )
        with (
            pytest.raises(IntegrityError, match="metadata is in the future"),
            session.begin_nested(),
        ):
            session.execute(
                text("UPDATE aggregate_retention_work SET completed_at=:at WHERE run_id=:run"),
                {"at": future, "run": run.run_id},
            )
        with (
            pytest.raises(IntegrityError, match="metadata is in the future"),
            session.begin_nested(),
        ):
            session.execute(
                text("UPDATE aggregate_owner_erasure SET completed_at=:at WHERE owner_id=:owner"),
                {"at": future, "owner": owner},
            )
        marker = session.scalar(
            select(m.AggregateRetentionModel).where(m.AggregateRetentionModel.run_id == run.run_id)
        )
        assert marker is not None and marker.completed_at is None


async def test_healthy_fx_cannot_be_purged_by_backdating_source_witness(
    xray_read_case: XrayReadCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = xray_read_case
    at = datetime.now(UTC).replace(microsecond=0)
    monkeypatch.setenv("T212PI_E2E_AGGREGATION", "1")
    facts = await seed_aggregation_browser_scenario(case.sessions, app_environment="test", at=at)
    principal = replace(
        case.principal,
        authenticated_at=at - timedelta(seconds=1),
        expires_at=at + timedelta(hours=1),
    )
    store = PostgresAggregateService(
        case.sessions, cursor_signing_key=b"aggregate-core-guard-cursor-test", clock=lambda: at
    )
    selected = await store.create_selection(
        principal,
        app.CreateAggregateSelection(
            content=AggregateSelectionContent(
                name="Actual FX restriction witness",
                reporting_currency=CurrencyCode("EUR"),
                source_cutoff_at=at,
                members=(
                    AggregateMember(
                        account_id=EUR_ACCOUNT_ID,
                        portfolio_snapshot_id=UUID(facts["eur_snapshot_id"]),
                    ),
                    AggregateMember(
                        account_id=USD_ACCOUNT_ID,
                        portfolio_snapshot_id=UUID(facts["usd_snapshot_id"]),
                    ),
                ),
            ),
            idempotency_key="actual-fx-guard-selection",
            correlation_id="actual-fx-guard",
        ),
    )
    run = await store.create_run(
        principal,
        app.CreateAggregateRun(
            selection_id=selected.selection_id,
            expected_revision=selected.revision,
            fx_bindings=(
                AggregateFxBinding(
                    account_id=USD_ACCOUNT_ID,
                    currency=CurrencyCode("USD"),
                    fx_observation_id=UUID(facts["fx_observation_id"]),
                ),
            ),
            idempotency_key="actual-fx-guard-run",
            correlation_id="actual-fx-guard",
        ),
    )
    # A timestamp before the original license used to manufacture a restricted witness.
    with case.sessions.begin() as session:
        for supplied, message in (
            (at - timedelta(days=3), "predates its run"),
            (at, "no original restricted witness"),
        ):
            with pytest.raises(IntegrityError, match=message), session.begin_nested():
                session.execute(
                    text(
                        "INSERT INTO aggregate_retention_work "
                        "(id,owner_id,run_id,reason,source_fx_snapshot_id,created_at) "
                        "VALUES(:id,:owner,:run,'source',:source,:at)"
                    ),
                    {
                        "id": uuid4(),
                        "owner": UUID(principal.owner_id),
                        "run": run.run_id,
                        "source": UUID(facts["fx_snapshot_id"]),
                        "at": supplied,
                    },
                )
    assert (await store.get_run(principal, run.run_id, app.AggregateRunQuery())).page is not None


async def test_selection_revision_cannot_advance_without_sealed_run(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    case.now[0] = datetime.now(UTC)
    store, selected = await prepared(case)
    with (
        pytest.raises(IntegrityError, match="operational revision has no completed run"),
        case.sessions.begin() as session,
    ):
        session.execute(
            text("UPDATE aggregate_selections SET revision=revision+1 WHERE id=:id"),
            {"id": selected.selection_id},
        )
        session.execute(text("SET CONSTRAINTS aggregate_revision_complete IMMEDIATE"))
    assert (await store.get_selection(case.principal, selected.selection_id)).revision == 1
    run = await store.create_run(case.principal, command(selected))
    assert run.selection_revision == 2
    assert (await store.get_selection(case.principal, selected.selection_id)).revision == 2
    with pytest.raises(app.AggregateServiceError) as stale:
        await store.create_run(case.principal, command(selected))
    assert stale.value.code is app.AggregateErrorCode.REVISION_MISMATCH


def test_fx_observation_reverse_fk_probes_have_matching_index_prefixes(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    inspector = inspect(case.engine)
    expected = (
        (
            "aggregate_fx_uses",
            "ix_aggregate_fx_observation_reverse",
            ["owner_id", "fx_observation_id"],
        ),
        ("aggregate_components", "ix_aggregate_component_fx_reverse", ["fx_observation_id"]),
    )
    with case.sessions() as session:
        session.execute(text("SET LOCAL enable_seqscan=off"))
        for table, name, columns in expected:
            indexes = {row["name"]: row["column_names"] for row in inspector.get_indexes(table)}
            assert indexes[name] == columns
            # These are the exact predicates issued by PostgreSQL's RESTRICT FK probes.
            query = (
                "EXPLAIN (FORMAT JSON) SELECT 1 FROM aggregate_fx_uses "
                "WHERE owner_id=:owner AND fx_observation_id=:id LIMIT 1"
                if table == "aggregate_fx_uses"
                else "EXPLAIN (FORMAT JSON) SELECT 1 FROM aggregate_components "
                "WHERE fx_observation_id=:id LIMIT 1"
            )
            plan = session.execute(
                text(query),
                {"owner": UUID(case.principal.owner_id), "id": uuid4()},
            ).scalar_one()
            assert name in str(plan)
