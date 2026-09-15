"""Synthetic canonical inputs and complete compact scenario API fixtures."""

from dataclasses import replace
from datetime import timedelta
from functools import lru_cache

from trading212_analytics.scenario import calculate_scenario, compare_scenario_results
from trading212_application.queries import CursorCodec
from trading212_application.risk import PremiumJobState
from trading212_application.scenario import ScenarioComparisonQuery, ScenarioComponentPageQuery
from trading212_application.scenario_projection import (
    RetainedScenarioResult,
    project_scenario_comparison_page,
    project_scenario_page,
)
from trading212_application.scenario_views import (
    ScenarioComparisonPage,
    ScenarioDefinitionView,
    ScenarioRunView,
    ScenarioVersionView,
)
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.scenario_serialization import (
    scenario_definition_digest,
    scenario_result_digest,
)
from trading212_security.principals import Principal, Scope

from tests.unit.analytics.scenario_factories import content, input_for, portfolio, price
from tests.unit.analytics.xray_factories import CUTOFF, uid

NOW = CUTOFF.value
ACCOUNT, DEFINITION, VERSION, SNAPSHOT, XRAY = uid(2), uid(8001), uid(8002), uid(3), uid(8003)
RUN, SECOND_RUN, JOB = uid(24001), uid(25001), uid(24002)
KEY = b"synthetic-scenario-api-cursor-key!"


def actor() -> Principal:
    return Principal(
        "scenario-test",
        str(uid(1)),
        "test",
        "test",
        frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.SCENARIOS_WRITE}),
        NOW,
        NOW + timedelta(hours=1),
    )


@lru_cache(maxsize=2)
def inputs(*, second: bool = False) -> ScenarioExecutionInput:
    return input_for(
        portfolio(("60", "40"), economic="EUR"), content(price(10, "-.2" if second else "-.1"))
    )


def definition() -> ScenarioDefinitionView:
    return ScenarioDefinitionView(
        id=DEFINITION,
        account_id=ACCOUNT,
        name=inputs().definition.name,
        revision=1,
        archived=False,
        current_version_id=VERSION,
        created_at=NOW,
        updated_at=NOW,
    )


def version() -> ScenarioVersionView:
    value = inputs().definition
    return ScenarioVersionView(
        id=VERSION,
        account_id=ACCOUNT,
        definition_id=DEFINITION,
        version_number=1,
        predecessor_id=None,
        content=value,
        content_digest=scenario_definition_digest(value),
        created_at=NOW,
    )


@lru_cache(maxsize=2)
def retained(*, second: bool = False) -> RetainedScenarioResult:
    value = calculate_scenario(inputs(second=second))
    return RetainedScenarioResult(
        run_id=SECOND_RUN if second else RUN,
        result_id=uid(25003 if second else 24003),
        account_id=ACCOUNT,
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
        result_digest=scenario_result_digest(value),
        calculation=value,
    )


@lru_cache(maxsize=1)
def run() -> ScenarioRunView:
    saved = retained()
    page = project_scenario_page(
        actor(),
        ACCOUNT,
        saved,
        ScenarioComponentPageQuery(),
        cursors=CursorCodec(KEY, clock=lambda: NOW),
        now=NOW,
    )
    return ScenarioRunView(
        id=RUN,
        account_id=ACCOUNT,
        scenario_version_id=VERSION,
        portfolio_snapshot_id=SNAPSHOT,
        xray_run_id=XRAY,
        job_id=JOB,
        state=PremiumJobState.SUCCEEDED,
        failure_code=None,
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
        completed_at=NOW,
        input_digest=saved.calculation.input_digest,
        result=page,
        result_availability="available",
    )


def queued() -> ScenarioRunView:
    return replace(
        run(),
        state=PremiumJobState.QUEUED,
        completed_at=None,
        result=None,
        result_availability="pending",
    )


@lru_cache(maxsize=1)
def comparison() -> ScenarioComparisonPage:
    left, right = retained(), retained(second=True)
    value = compare_scenario_results(left.calculation, right.calculation)
    return project_scenario_comparison_page(
        actor(),
        ACCOUNT,
        left,
        right,
        value,
        ScenarioComparisonQuery(run_ids=(RUN, SECOND_RUN)),
        cursors=CursorCodec(KEY, clock=lambda: NOW),
        now=NOW,
    )
