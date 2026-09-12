"""Persisted MCP target, planning and historical selections respect both real owners."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from enum import StrEnum
from uuid import uuid4

import pytest
from starlette.testclient import TestClient
from trading212_mcp.server import create_runtime
from trading212_mcp.settings import McpSettings
from trading212_security.principals import Scope

from tests.integration.phase2_authorization_cases import SETTINGS, Actor, retained_state
from tests.integration.phase2_authorization_cases import owner_grid as owner_grid
from tests.integration.phase2_mcp_owner_resources import IntelligenceOwners, PlanningPin
from tests.integration.phase2_mcp_owner_resources import intelligence_owners as intelligence_owners
from tests.integration.phase2_mcp_owner_transport import (
    ScopedGridBearer,
    call,
    denied,
    items,
    mapping,
    payload,
)
from tests.integration.test_alert_postgres import alert_database as alert_database

pytestmark = pytest.mark.integration
STATE = (
    "virtual_portfolios",
    "target_versions",
    "target_nodes",
    "target_holdings",
    "target_command_identities",
    "target_collection_references",
    "contribution_plans",
    "contribution_plan_requests",
    "contribution_plan_inputs",
    "contribution_plan_jobs",
    "contribution_plan_dispatch_outbox",
    "contribution_plan_revisions",
    "contribution_plan_lines",
    "planning_command_identities",
    "planning_collection_bindings",
    "analytics_runs",
    "analytics_drift_rows",
    "historical_input_snapshots",
    "historical_dependencies",
    "historical_analytics_runs",
    "historical_event_revisions",
    "historical_collection_bindings",
)


class Tool(StrEnum):
    TARGET_LIST = "list_virtual_pies"
    TARGET = "get_virtual_pie"
    ACTUAL = "get_actual_vs_target"
    DRIFT = "get_drift_analysis"
    PLAN = "get_contribution_plan"
    CREATE = "create_contribution_plan"
    PERFORMANCE = "get_performance_summary"
    BENCHMARK = "get_benchmark_comparison"
    INCOME = "get_dividend_intelligence"
    ATTRIBUTION = "get_attribution_summary"


HISTORY = (Tool.PERFORMANCE, Tool.BENCHMARK, Tool.INCOME, Tool.ATTRIBUTION)


def scopes(tool: Tool) -> tuple[Scope, ...]:
    required = [Scope.PORTFOLIO_READ]
    if tool not in (Tool.TARGET_LIST, Tool.TARGET):
        required.append(Scope.ANALYTICS_READ)
    if tool in (
        Tool.TARGET_LIST,
        Tool.TARGET,
        Tool.ACTUAL,
        Tool.DRIFT,
        Tool.CREATE,
        Tool.ATTRIBUTION,
    ):
        required.append(Scope.TARGETS_READ)
    if tool is Tool.CREATE:
        required.append(Scope.PLANS_WRITE)
    if tool is Tool.INCOME:
        required.append(Scope.ACTIVITY_READ)
    return tuple(required)


@contextmanager
def client_for(case: IntelligenceOwners) -> Iterator[tuple[TestClient, ScopedGridBearer]]:
    grid = case.grid
    bearer = ScopedGridBearer(grid.actors)
    runtime = create_runtime(
        security_settings=SETTINGS.model_copy(update={"issuer": "https://issuer.example"}),
        mcp_settings=McpSettings.model_validate({"public_base_url": "https://portfolio.example"}),
        service=grid.portfolio,
        target_service=case.targets,
        planning_service=case.planning,
        historical_service=case.history,
        bearer_authenticator=bearer,
        clock=lambda: grid.at,
    )
    with TestClient(runtime.asgi_app(), base_url="http://localhost") as client:
        yield client, bearer


def arguments(
    case: IntelligenceOwners,
    actor: Actor,
    resource: PlanningPin,
    tool: Tool,
) -> dict[str, object]:
    result: dict[str, object] = {"account_id": str(resource.pin.account_id)}
    if tool is Tool.TARGET_LIST:
        return {**result, "state": "all", "limit": 100}
    if tool is Tool.PLAN:
        return {**result, "plan_id": resource.job.plan_id}
    if tool in HISTORY:
        # Inclusive historical dates must finish before the frozen service clock.
        closed_day = case.grid.at.date() - timedelta(days=1)
        result.update(
            start_date=closed_day.isoformat(),
            end_date=closed_day.isoformat(),
            source_cutoff_at=case.grid.at.isoformat(),
            reporting_currency="EUR",
        )
        if tool is Tool.BENCHMARK:
            result["benchmark_version_id"] = case.benchmarks[actor.principal.owner_id]
        if tool is Tool.ATTRIBUTION:
            result.update(grouping="group", target_version_id=resource.target.version.id)
        return result
    result.update(
        virtual_portfolio_id=resource.target.portfolio.id,
        target_version_id=resource.target.version.id,
    )
    if tool is Tool.TARGET:
        return result
    result.update(snapshot_id=str(resource.pin.snapshot_id), reporting_currency="EUR")
    if tool is Tool.CREATE:
        del result["reporting_currency"]
        result.update(
            idempotency_key=uuid4().hex,
            contribution={"amount": "20", "currency": "EUR"},
            mode="global",
            coverage_policy="allow_degraded",
        )
    return result


def assert_owned(value: dict[str, object], tool: Tool, resource: PlanningPin) -> None:
    account = str(resource.pin.account_id)
    if tool is Tool.TARGET_LIST:
        rows = items(value["portfolios"])
        assert resource.target.portfolio.id in {row["id"] for row in rows}
        assert all(row["account_id"] == account for row in rows)
    elif tool is Tool.TARGET:
        assert mapping(value["portfolio"])["id"] == resource.target.portfolio.id
        assert mapping(value["portfolio"])["account_id"] == account
        assert mapping(value["target_version"])["id"] == resource.target.version.id
    elif tool is Tool.PLAN:
        job = mapping(value["job"])
        assert job["account_id"] == account and job["plan_id"] == resource.job.plan_id
        assert job["state"] == "succeeded" and value["result"] is not None
    elif tool is Tool.CREATE:
        assert value["account_id"] == account and value["state"] == "queued"
    else:
        context = mapping(value["context"])
        assert context["account_id"] == account
        if tool in HISTORY:
            # These real captures truthfully lack historical opening coverage.
            assert isinstance(context["run_id"], str)
            assert isinstance(context["input_snapshot_id"], str)
        else:
            assert context["snapshot_id"] == str(resource.pin.snapshot_id)
            assert context["target_version_id"] == resource.target.version.id


@pytest.mark.parametrize("tool", tuple(Tool), ids=lambda tool: tool.value)
def test_intelligence_tools_real_owner_account_controls_and_authenticated_scopes(
    intelligence_owners: IntelligenceOwners,
    tool: Tool,
) -> None:
    case = intelligence_owners
    grid = case.grid
    with client_for(case) as (client, bearer):
        for actor, other in (grid.actors, tuple(reversed(grid.actors))):
            for pin in actor.accounts:
                resource = case.plans[pin.account_id]
                request = arguments(case, actor, resource, tool)
                value = payload(call(client, actor, tool.value, request))
                assert_owned(value, tool, resource)
                if tool is Tool.CREATE:
                    before_retry = retained_state(grid, STATE)
                    assert payload(call(client, actor, tool.value, request)) == value
                    assert retained_state(grid, STATE) == before_retry
                before = retained_state(grid, STATE)
                for scope in scopes(tool):
                    bearer.omitted = scope
                    try:
                        denied(
                            call(client, actor, tool.value, request),
                            "ACCESS_DENIED",
                            (
                                str(pin.account_id),
                                resource.job.plan_id,
                                resource.target.version.id,
                            ),
                        )
                    finally:
                        bearer.omitted = None
                    assert retained_state(grid, STATE) == before
            foreign = case.plans[other.accounts[0].account_id]
            request = arguments(case, other, foreign, tool)
            before = retained_state(grid, STATE)
            denied(
                call(client, actor, tool.value, request),
                "NOT_FOUND",
                (
                    other.principal.owner_id,
                    str(foreign.pin.account_id),
                    foreign.job.plan_id,
                    foreign.target.version.id,
                ),
            )
            denied(
                call(
                    client,
                    actor,
                    tool.value,
                    {
                        **request,
                        "account_id": str(uuid4()),
                    },
                ),
                "NOT_FOUND",
                (foreign.job.plan_id, foreign.target.version.id),
            )
            assert retained_state(grid, STATE) == before


BINDINGS = (
    (Tool.TARGET, "virtual_portfolio_id"),
    (Tool.TARGET, "target_version_id"),
    *(
        (tool, field)
        for tool in (Tool.ACTUAL, Tool.DRIFT, Tool.CREATE)
        for field in ("snapshot_id", "virtual_portfolio_id", "target_version_id")
    ),
    (Tool.PLAN, "plan_id"),
    (Tool.ATTRIBUTION, "target_version_id"),
)


@pytest.mark.parametrize(
    ("tool", "field"), BINDINGS, ids=[f"{tool.value}-{field}" for tool, field in BINDINGS]
)
def test_individual_intelligence_pin_cannot_be_substituted_from_another_account_or_owner(
    intelligence_owners: IntelligenceOwners,
    tool: Tool,
    field: str,
) -> None:
    case = intelligence_owners
    grid = case.grid
    with client_for(case) as (client, _):
        for actor, other in (grid.actors, tuple(reversed(grid.actors))):
            own = case.plans[actor.accounts[0].account_id]
            request = arguments(case, actor, own, tool)
            assert_owned(payload(call(client, actor, tool.value, request)), tool, own)
            donor_requests: list[dict[str, object]] = []
            for caller, pin in (
                (actor, actor.accounts[1]),
                (other, other.accounts[0]),
            ):
                donor = case.plans[pin.account_id]
                donor_request = arguments(case, caller, donor, tool)
                assert_owned(
                    payload(call(client, caller, tool.value, donor_request)),
                    tool,
                    donor,
                )
                donor_requests.append(donor_request)
            # Use fresh command keys so idempotency cannot mask invalid resource pins.
            before = retained_state(grid, STATE)
            for donor_request in donor_requests:
                bad = {**request, field: donor_request[field]}
                if tool is Tool.CREATE:
                    bad["idempotency_key"] = uuid4().hex
                denied(
                    call(client, actor, tool.value, bad), "NOT_FOUND", (str(donor_request[field]),)
                )
                assert retained_state(grid, STATE) == before
            missing = {**request, field: str(uuid4())}
            if tool is Tool.CREATE:
                missing["idempotency_key"] = uuid4().hex
            denied(call(client, actor, tool.value, missing), "NOT_FOUND", (str(missing[field]),))
            assert retained_state(grid, STATE) == before


def test_benchmark_versions_are_owner_private_and_usable_across_own_accounts(
    intelligence_owners: IntelligenceOwners,
) -> None:
    case = intelligence_owners
    grid = case.grid
    with client_for(case) as (client, _):
        for actor, other in (grid.actors, tuple(reversed(grid.actors))):
            for pin in actor.accounts:
                resource = case.plans[pin.account_id]
                request = arguments(case, actor, resource, Tool.BENCHMARK)
                assert_owned(
                    payload(call(client, actor, Tool.BENCHMARK.value, request)),
                    Tool.BENCHMARK,
                    resource,
                )
            before = retained_state(grid, STATE)
            for identifier in (case.benchmarks[other.principal.owner_id], str(uuid4())):
                denied(
                    call(
                        client,
                        actor,
                        Tool.BENCHMARK.value,
                        {
                            **request,
                            "benchmark_version_id": identifier,
                        },
                    ),
                    "ACCESS_DENIED",
                    (identifier, other.principal.owner_id),
                )
                assert retained_state(grid, STATE) == before


@pytest.mark.parametrize("tool", (Tool.TARGET_LIST, Tool.TARGET), ids=lambda tool: tool.value)
def test_private_templates_never_pivot_owner_or_account_and_cursors_keep_their_scope(
    intelligence_owners: IntelligenceOwners,
    tool: Tool,
) -> None:
    case = intelligence_owners
    grid = case.grid
    with client_for(case) as (client, _):
        for actor, other in (grid.actors, tuple(reversed(grid.actors))):
            target = case.templates[actor.principal.owner_id][0]
            foreign = case.templates[other.principal.owner_id][0]
            request: dict[str, object] = {"account_id": None, "limit": 1}
            if tool is Tool.TARGET:
                request.update(
                    virtual_portfolio_id=target.portfolio.id, target_version_id=target.version.id
                )
            else:
                request["state"] = "all"
            first = call(client, actor, tool.value, request)
            value = payload(first)
            if tool is Tool.TARGET_LIST:
                assert all(row["account_id"] is None for row in items(value["portfolios"]))
            else:
                assert mapping(value["portfolio"])["id"] == target.portfolio.id
            assert first.structured_content is not None
            cursor = mapping(first.structured_content["pagination"])["next_cursor"]
            assert isinstance(cursor, str)
            payload(call(client, actor, tool.value, {**request, "cursor": cursor}))
            before = retained_state(grid, STATE)
            other_request = {**request, "cursor": cursor}
            if tool is Tool.TARGET:
                other_request.update(
                    virtual_portfolio_id=foreign.portfolio.id,
                    target_version_id=foreign.version.id,
                )
            denied(call(client, other, tool.value, other_request), "CURSOR_INVALID", (cursor,))
            assert retained_state(grid, STATE) == before
            if tool is Tool.TARGET:
                for changed in (
                    {"account_id": str(actor.accounts[0].account_id)},
                    {
                        "virtual_portfolio_id": foreign.portfolio.id,
                        "target_version_id": foreign.version.id,
                    },
                ):
                    denied(
                        call(client, actor, tool.value, {**request, **changed}),
                        "NOT_FOUND",
                        (
                            foreign.portfolio.id,
                            foreign.version.id,
                        ),
                    )
                assert retained_state(grid, STATE) == before


def test_plan_command_key_is_owner_scoped_and_mismatched_retry_does_not_queue(
    intelligence_owners: IntelligenceOwners,
) -> None:
    case = intelligence_owners
    grid = case.grid
    shared_key = uuid4().hex
    jobs: list[object] = []
    with client_for(case) as (client, _):
        for actor in grid.actors:
            resource = case.plans[actor.accounts[0].account_id]
            request = {
                **arguments(case, actor, resource, Tool.CREATE),
                "idempotency_key": shared_key,
            }
            first = payload(call(client, actor, Tool.CREATE.value, request))
            jobs.append(first["job_id"])
            before = retained_state(grid, STATE)
            assert payload(call(client, actor, Tool.CREATE.value, request)) == first
            denied(
                call(
                    client,
                    actor,
                    Tool.CREATE.value,
                    {
                        **request,
                        "contribution": {"amount": "21", "currency": "EUR"},
                    },
                ),
                "IDEMPOTENCY_KEY_REUSED",
                (str(first["job_id"]),),
            )
            assert retained_state(grid, STATE) == before
    assert jobs[0] != jobs[1]


def test_saved_plan_revision_must_belong_to_the_selected_plan_and_account(
    intelligence_owners: IntelligenceOwners,
) -> None:
    case = intelligence_owners
    grid = case.grid
    with client_for(case) as (client, _):
        for actor, other in (grid.actors, tuple(reversed(grid.actors))):
            revisions: list[str] = []
            for caller, pin in (
                (actor, actor.accounts[0]),
                (actor, actor.accounts[1]),
                (other, other.accounts[0]),
            ):
                resource = case.plans[pin.account_id]
                request = arguments(case, caller, resource, Tool.PLAN)
                value = payload(call(client, caller, Tool.PLAN.value, request))
                assert_owned(value, Tool.PLAN, resource)
                revision = mapping(value["job"])["plan_revision_id"]
                assert isinstance(revision, str)
                selected = payload(
                    call(
                        client,
                        caller,
                        Tool.PLAN.value,
                        {
                            **request,
                            "plan_revision_id": revision,
                        },
                    )
                )
                assert mapping(selected["job"])["plan_revision_id"] == revision
                revisions.append(revision)
            own = case.plans[actor.accounts[0].account_id]
            request = arguments(case, actor, own, Tool.PLAN)
            before = retained_state(grid, STATE)
            for revision in (*revisions[1:], str(uuid4())):
                denied(
                    call(
                        client,
                        actor,
                        Tool.PLAN.value,
                        {
                            **request,
                            "plan_revision_id": revision,
                        },
                    ),
                    "NOT_FOUND",
                    (revision,),
                )
                assert retained_state(grid, STATE) == before


@pytest.mark.parametrize(
    ("tool", "field"),
    ((Tool.TARGET, "parent_node_id"), (Tool.ACTUAL, "node_id")),
    ids=("target-parent", "actual-node"),
)
def test_selected_subtree_cannot_borrow_another_target_node(
    intelligence_owners: IntelligenceOwners,
    tool: Tool,
    field: str,
) -> None:
    case = intelligence_owners
    grid = case.grid
    with client_for(case) as (client, _):
        for actor, other in (grid.actors, tuple(reversed(grid.actors))):
            nodes: list[str] = []
            for caller, pin in (
                (actor, actor.accounts[0]),
                (actor, actor.accounts[1]),
                (other, other.accounts[0]),
            ):
                resource = case.plans[pin.account_id]
                target = payload(
                    call(
                        client,
                        caller,
                        Tool.TARGET.value,
                        {
                            **arguments(case, caller, resource, Tool.TARGET),
                            "limit": 100,
                        },
                    )
                )
                group = next(
                    mapping(row["hierarchy"])
                    for row in items(target["nodes"])
                    if mapping(mapping(row["hierarchy"])["node"])["key"] == "group"
                )
                node = group["id"]
                assert isinstance(node, str)
                request = {**arguments(case, caller, resource, tool), field: node}
                assert_owned(payload(call(client, caller, tool.value, request)), tool, resource)
                nodes.append(node)
            own = case.plans[actor.accounts[0].account_id]
            request = arguments(case, actor, own, tool)
            before = retained_state(grid, STATE)
            for node in (*nodes[1:], str(uuid4())):
                denied(
                    call(
                        client,
                        actor,
                        tool.value,
                        {
                            **request,
                            field: node,
                        },
                    ),
                    "NOT_FOUND",
                    (node,),
                )
                assert retained_state(grid, STATE) == before


@pytest.mark.parametrize("tool", (Tool.ACTUAL, Tool.PLAN), ids=lambda tool: tool.value)
def test_planning_cursor_stays_with_its_real_owner_account_and_selected_resource(
    intelligence_owners: IntelligenceOwners,
    tool: Tool,
) -> None:
    case = intelligence_owners
    grid = case.grid
    with client_for(case) as (client, _):
        for actor, other in (grid.actors, tuple(reversed(grid.actors))):
            own = case.plans[actor.accounts[0].account_id]
            request = {**arguments(case, actor, own, tool), "limit": 1}
            first = call(client, actor, tool.value, request)
            assert_owned(payload(first), tool, own)
            assert first.structured_content is not None
            cursor = mapping(first.structured_content["pagination"])["next_cursor"]
            assert isinstance(cursor, str)
            assert_owned(
                payload(
                    call(
                        client,
                        actor,
                        tool.value,
                        {
                            **request,
                            "cursor": cursor,
                        },
                    )
                ),
                tool,
                own,
            )
            # Authorize each destination before testing the stolen source cursor.
            destinations: list[tuple[Actor, dict[str, object]]] = []
            for caller, pin in (
                (actor, actor.accounts[1]),
                (other, other.accounts[0]),
            ):
                resource = case.plans[pin.account_id]
                destination = {**arguments(case, caller, resource, tool), "limit": 1}
                assert_owned(payload(call(client, caller, tool.value, destination)), tool, resource)
                destinations.append((caller, destination))
            before = retained_state(grid, STATE)
            for caller, destination in destinations:
                denied(
                    call(
                        client,
                        caller,
                        tool.value,
                        {
                            **destination,
                            "cursor": cursor,
                        },
                    ),
                    "CURSOR_INVALID",
                    (cursor, own.job.plan_id),
                )
                assert retained_state(grid, STATE) == before
