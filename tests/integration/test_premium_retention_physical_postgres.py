"""Real saved scenario rows: exact counter, parent guard and charged cleanup."""

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import Engine, event, select, text
from sqlalchemy.exc import IntegrityError
from trading212_persistence.premium_models import PremiumRunModel
from trading212_persistence.premium_retention_models import (
    PremiumRetainedParentModel,
    PremiumRetentionStateModel,
)
from trading212_persistence.scenario_retention import expire_scenario_payloads
from trading212_persistence.source_retention import SourcePurgeBudget

from tests.integration.test_scenario_retention_postgres import published
from tests.integration.test_scenario_runs_postgres import ScenarioCase
from tests.integration.test_scenario_runs_postgres import scenario_case as scenario_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def counter_parity(case: ScenarioCase) -> tuple[int, int]:
    with case.sessions() as session:
        state = session.get_one(PremiumRetentionStateModel, case.run.id)
        actual = session.scalar(text("SELECT scenario_storage_bytes(:run)"), {"run": case.run.id})
        assert state.stored_bytes == actual
        return state.financial_rows, state.stored_bytes


async def test_counter_exact_parity_partial_cleanup_and_direct_forgery_rejected(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    before_rows, before_bytes = counter_parity(case)
    assert before_rows > 0 and before_bytes > 0
    await published(case)
    after_rows, after_bytes = counter_parity(case)
    assert after_rows > before_rows and after_bytes > before_bytes
    with case.sessions() as session, session.begin():
        with pytest.raises(IntegrityError, match="trigger-owned"), session.begin_nested():
            session.execute(
                text(
                    "UPDATE premium_retention_state SET "
                    "stored_bytes=0,financial_rows=0 WHERE run_id=:run"
                ),
                {"run": case.run.id},
            )
        with pytest.raises(IntegrityError, match="still owns copies"), session.begin_nested():
            session.execute(
                text("DELETE FROM premium_retained_parents WHERE run_id=:run"), {"run": case.run.id}
            )
    at = case.now + timedelta(days=31)
    previous = after_bytes
    passes = 0
    for _ in range(200):
        budget = SourcePurgeBudget(rows_inspected=180)
        with case.sessions() as session, session.begin():
            complete = expire_scenario_payloads(
                session, at=at, owner=UUID(case.principal.owner_id), budget=budget
            )
        rows, measured = counter_parity(case)
        assert measured <= previous and 0 <= budget.rows_inspected <= 180
        previous = measured
        passes += 1
        if complete:
            break
    else:
        pytest.fail("Scenario physical retention did not converge")
    assert passes > 1 and rows == 0 and measured == 0
    with case.sessions() as session:
        state = session.get_one(PremiumRetentionStateModel, case.run.id)
        assert state.closed
        assert (
            session.scalar(
                select(PremiumRetainedParentModel.id).where(
                    PremiumRetainedParentModel.run_id == case.run.id
                )
            )
            is None
        )
        root = session.get_one(PremiumRunModel, case.run.id)
        assert root.reserved_bytes == root.retained_bytes == 0


async def test_retiring_run_never_calls_old_full_payload_aggregate(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    await published(case)
    statements: list[str] = []

    def observe(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _many: bool,
    ) -> None:
        statements.append(statement.lower())

    with case.sessions() as session, session.begin():
        # Transaction-local failure canary, restored by rollback; all production
        # guards stay installed and must now use the protected O(1) counter.
        session.execute(
            text(
                "CREATE OR REPLACE FUNCTION scenario_storage_bytes(p_run "
                "uuid) RETURNS bigint LANGUAGE plpgsql STABLE AS $$ BEGIN "
                "RAISE EXCEPTION 'unbounded aggregate reached'; END $$"
            )
        )
        connection = session.connection()
        event.listen(connection, "before_cursor_execute", observe)
        try:
            assert expire_scenario_payloads(
                session,
                at=case.now + timedelta(days=31),
                owner=UUID(case.principal.owner_id),
                budget=SourcePurgeBudget(),
            )
        finally:
            event.remove(connection, "before_cursor_execute", observe)
        assert not any(
            "scenario_run_has_payload" in statement or "scenario_storage_bytes(" in statement
            for statement in statements
        )
        session.rollback()


async def test_populated_real_capture_backfills_exact_counter_after_0025(
    scenario_case: ScenarioCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import MetaData

    from tests.integration.test_risk_migration_upgrade import fingerprints

    case = scenario_case
    await published(case)
    with case.sessions() as session:
        engine = session.get_bind()
        assert isinstance(engine, Engine)
        url = engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.downgrade(config, "20260915_0025")
    try:
        old = MetaData()
        old.reflect(bind=engine)
        before = fingerprints(engine, old)
        command.upgrade(config, "20260915_0026")
        assert fingerprints(engine, old) == before
        rows, size = counter_parity(case)
        assert rows > 0 and size > 0
        with case.sessions() as session:
            assert (
                session.scalar(
                    select(PremiumRetainedParentModel.id).where(
                        PremiumRetainedParentModel.run_id == case.run.id
                    )
                )
                is not None
            )
        command.upgrade(config, "20260915_0026")
        assert counter_parity(case) == (rows, size)
    finally:
        command.upgrade(config, "head")
