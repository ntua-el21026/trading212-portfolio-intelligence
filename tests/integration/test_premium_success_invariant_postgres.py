"""A succeeded job cannot outrun its sealed canonical result in the same transaction."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_historical_seed import NOW
from tests.integration.test_historical_seed import seeded_history as seeded_history
from tests.integration.test_risk_runs_postgres import RunCase
from tests.integration.test_risk_runs_postgres import run_case as run_case

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("result_state", ("absent", "unsealed"))
async def test_direct_risk_success_requires_sealed_complete_result(
    run_case: RunCase,
    result_state: str,
) -> None:
    run = await run_case.service.create_run(run_case.principal, run_case.command)
    with (
        pytest.raises(IntegrityError, match="Premium result publication incomplete"),
        run_case.sessions() as session,
        session.begin(),
    ):
        if result_state == "unsealed":
            session.execute(
                text("""
                INSERT INTO risk_results
                (id,owner_id,account_id,run_id,content_digest,canonical_result,series_count,
                 interval_count,matrix_cell_count,component_count,metric_count,sealed,created_at)
                SELECT :result,owner_id,account_id,id,:digest,:payload,1,0,0,0,1,false,:now
                FROM premium_runs WHERE id=:run
            """),
                dict(
                    result=uuid4(),
                    digest="a" * 64,
                    payload=b"schema boundary fixture",
                    now=NOW,
                    run=run.id,
                ),
            )
        session.execute(
            text("""
            UPDATE premium_jobs SET state='succeeded',completed_at=:now,lease_token=NULL,
              lease_expires_at=NULL,heartbeat_at=NULL,deadline_at=NULL,consumer_id=NULL,
              failure_code=NULL WHERE id=:job
        """),
            dict(now=NOW, job=run.job_id),
        )
        # Isolate the new converse invariant from the result INSERT trigger.
        session.execute(text("SET CONSTRAINTS premium_job_success_complete IMMEDIATE"))
