"""Risk uses the exact shared historical/X-ray parent drain without new byte valuation."""

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from trading212_persistence.premium_retention_models import (
    PremiumRetainedParentModel as Parent,
)
from trading212_persistence.premium_retention_models import (
    PremiumRetentionStateModel as State,
)
from trading212_persistence.scenario_retention import purge_scenario_historical_copies
from trading212_persistence.source_retention import SourcePurgeBudget

from tests.integration.test_historical_seed import NOW
from tests.integration.test_risk_retention_postgres import assert_empty, published
from tests.integration.test_risk_retention_postgres import (
    historical_database as historical_database,
)
from tests.integration.test_risk_retention_postgres import seeded_history as seeded_history
from tests.integration.test_risk_runs_postgres import RunCase
from tests.integration.test_risk_runs_postgres import run_case as run_case

pytestmark = pytest.mark.integration


async def test_existing_historical_parent_participant_drains_real_risk_copies(
    run_case: RunCase,
) -> None:
    case = run_case
    run = await published(case)
    owner = UUID(case.principal.owner_id)
    with case.sessions() as session:
        state = session.get_one(State, run.id)
        assert state.kind == "risk" and state.financial_rows > 0
        assert state.stored_bytes == state.metadata_bytes == 0
        history = session.scalar(
            select(Parent.parent_id).where(
                Parent.owner_id == owner,
                Parent.run_id == run.id,
                Parent.parent_kind == "historical",
            )
        )
        assert history is not None
    for _ in range(200):
        budget = SourcePurgeBudget(rows_inspected=180)
        with case.sessions() as session, session.begin():
            done = purge_scenario_historical_copies(
                session, owner, history, at=NOW + timedelta(days=31), budget=budget
            )
        assert 0 <= budget.rows_inspected <= 180
        if done:
            break
    else:
        pytest.fail("Risk rows did not leave the exact historical parent queue")
    assert_empty(case, run)
    with case.sessions() as session:
        state = session.get_one(State, run.id)
        assert (
            state.closed and state.financial_rows == state.stored_bytes == state.metadata_bytes == 0
        )
        assert session.scalar(select(Parent.id).where(Parent.run_id == run.id)) is None
