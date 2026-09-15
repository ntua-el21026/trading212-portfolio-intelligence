"""Real modeled projection admission in the existing single disposable PostgreSQL DB."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import projection as app
from trading212_application.projection_capture import (
    ProjectionDatedSchedule,
    ProjectionInitialSelection,
    ProjectionRunSelection,
)
from trading212_application.projection_views import ProjectionRunView, ProjectionVersionMetadata
from trading212_domain.projection import (
    ProjectionAllocation,
    ProjectionAsset,
    ProjectionAssumptions,
)
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence.projection_service import PostgresProjectionService
from trading212_security.principals import Principal
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.test_scenario_runs_postgres import grant_scenario_identity
from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case


@dataclass
class ProjectionJobCase:
    sessions: sessionmaker[Session]
    service: PostgresProjectionService
    principal: Principal
    command: app.CreateProjectionRun
    run: ProjectionRunView
    xray: XrayReadCase

    @property
    def now(self) -> datetime:
        return self.xray.now[0]

    @now.setter
    def now(self, value: datetime) -> None:
        self.xray.now[0] = value

    @property
    def engine(self) -> Engine:
        return self.xray.engine


@pytest.fixture
async def projection_job_case(xray_read_case: XrayReadCase) -> ProjectionJobCase:
    """Publish immutable assumptions and queue through production service contracts.

    Empty calibration pins are deliberately modeled inputs; no evidence, grant or
    provider authority is invented. All scopes are explicitly provisioned through
    the same local synthetic identity helper used by existing premium PG tests.
    """
    case = xray_read_case
    # 0022 validates leases against PostgreSQL clock_timestamp(), so modeled
    # runs use its current clock rather than the older X-ray financial fixture date.
    with case.sessions() as session:
        at = session.scalar(select(func.clock_timestamp()))
        assert isinstance(at, datetime)
        case.now[0] = at
    grant_scenario_identity(case.sessions, case.principal, case.now[0])
    service = PostgresProjectionService(
        case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now[0]
    )
    currency = CurrencyCode("EUR")
    assumptions = ProjectionAssumptions(
        assets=(
            ProjectionAsset(
                key="modeled-equity",
                annual_mean_log_return=Decimal(".04"),
                annual_volatility=Decimal(".2"),
                weight=Decimal(1),
            ),
        ),
        correlation=((Decimal(1),),),
        reporting_currency=currency,
        annual_inflation=Decimal(".02"),
        annual_fee=Decimal(".001"),
        annual_tax_drag=Decimal(".002"),
    )
    definition = await service.create_assumption_set(
        case.principal,
        app.CreateAssumptionSet(
            account_id=UUID(XRAY_ACCOUNT_ID),
            metadata=ProjectionVersionMetadata(
                name="Synthetic modeled assumptions", description="No observed calibration sources"
            ),
            content=assumptions,
            idempotency_key=str(uuid4()),
            correlation_id="projection-job-fixture",
        ),
    )
    command = app.CreateProjectionRun(
        selection=ProjectionRunSelection(
            account_id=UUID(XRAY_ACCOUNT_ID),
            assumption_version_id=definition.current_version_id,
            initial=ProjectionInitialSelection(
                kind="modeled_value",
                modeled_value=Money(Decimal("100.123456789012345678"), currency),
                modeled_anchor_date=case.now[0].date(),
            ),
            schedule=ProjectionDatedSchedule(base_monthly=Money(Decimal(10), currency)),
            seed=23,
            months=3,
            paths=7,
            retained_months=(0, 1, 2, 3),
            allocation=(ProjectionAllocation(key="modeled-equity", weight=Decimal(1)),),
        ),
        idempotency_key=str(uuid4()),
        correlation_id="projection-job-fixture",
    )
    queued = await service.create_run(case.principal, command)
    return ProjectionJobCase(case.sessions, service, case.principal, command, queued, case)
