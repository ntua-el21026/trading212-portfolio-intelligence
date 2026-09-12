"""HTTP retained selector relationships across real owner and account resources."""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx2
import pytest
from starlette.testclient import TestClient
from trading212_persistence.source_models import BenchmarkVersionModel
from trading212_security.principals import Scope

from tests.integration.phase2_authorization_cases import Actor, OwnerGrid, retained_state
from tests.integration.phase2_authorization_cases import owner_grid as owner_grid
from tests.integration.phase2_mcp_owner_resources import IntelligenceOwners
from tests.integration.phase2_mcp_owner_resources import intelligence_owners as intelligence_owners
from tests.integration.phase2_mcp_owner_transport import ScopedGridBearer, mapping
from tests.integration.test_alert_postgres import alert_database as alert_database
from tests.integration.test_phase2_remaining_command_authorization_postgres import (
    STATE,
    assert_denied,
    setup_post,
)
from tests.integration.test_phase2_remaining_command_authorization_postgres import (
    command_api as command_api,
)

pytestmark = pytest.mark.integration


def read(
    client: TestClient,
    actor: Actor,
    path: str,
    params: dict[str, str],
) -> httpx2.Response:
    response = client.get(path, params=params, headers={"Authorization": "Bearer " + actor.token})
    assert response.status_code == 200, response.text
    return response


def rejected(
    client: TestClient,
    grid: OwnerGrid,
    actor: Actor,
    path: str,
    params: dict[str, str],
    private: tuple[str, ...],
) -> None:
    before = retained_state(grid, STATE)
    response = client.get(
        path,
        params=params,
        headers={
            "Authorization": "Bearer " + actor.token,
            "If-None-Match": "*",
        },
    )
    assert_denied(response, "NOT_FOUND", private)
    assert retained_state(grid, STATE) == before


@pytest.mark.parametrize("field", ("left_version_id", "right_version_id"))
def test_http_comparison_versions_cannot_cross_the_selected_portfolio(
    intelligence_owners: IntelligenceOwners,
    command_api: tuple[TestClient, ScopedGridBearer],
    field: str,
) -> None:
    case = intelligence_owners
    client, _ = command_api
    for actor, other in (case.grid.actors, tuple(reversed(case.grid.actors))):
        own = case.plans[actor.accounts[0].account_id]
        path = "/api/v1/virtual-portfolios/" + own.target.portfolio.id + "/target-comparison"
        params = {
            "left_version_id": own.target.version.id,
            "right_version_id": own.target.version.id,
        }
        original = read(client, actor, path, params)
        assert mapping(original.json())[field] == own.target.version.id
        for donor_actor, pin in ((actor, actor.accounts[1]), (other, other.accounts[0])):
            donor = case.plans[pin.account_id]
            donor_path = (
                "/api/v1/virtual-portfolios/" + donor.target.portfolio.id + "/target-comparison"
            )
            donor_params = {
                "left_version_id": donor.target.version.id,
                "right_version_id": donor.target.version.id,
            }
            assert (
                mapping(read(client, donor_actor, donor_path, donor_params).json())[field]
                == donor.target.version.id
            )
            rejected(
                client,
                case.grid,
                actor,
                path,
                {**params, field: donor.target.version.id},
                (
                    donor.target.version.id,
                    donor.target.portfolio.id,
                ),
            )
        assert read(client, actor, path, params).json() == original.json()


@pytest.mark.parametrize(
    ("kind", "field"),
    (
        ("list", "virtual_portfolio_id"),
        ("list", "plan_id"),
        ("detail", "plan_revision_id"),
    ),
)
def test_http_plan_filters_and_revision_keep_the_selected_account_and_plan(
    intelligence_owners: IntelligenceOwners,
    command_api: tuple[TestClient, ScopedGridBearer],
    kind: str,
    field: str,
) -> None:
    case = intelligence_owners
    client, _ = command_api
    for actor, other in (case.grid.actors, tuple(reversed(case.grid.actors))):
        own = case.plans[actor.accounts[0].account_id]
        detail_path = "/api/v1/contribution-plans/" + own.job.plan_id
        detail = mapping(read(client, actor, detail_path, {}).json())
        job = mapping(detail["job"])
        assert job["state"] == "succeeded" and isinstance(job["plan_revision_id"], str)
        params: dict[str, str] = {}
        if kind == "detail":
            path = detail_path
            params[field] = job["plan_revision_id"]
        else:
            params["account_id"] = str(own.pin.account_id)
            path = "/api/v1/contribution-plans"
            params.update(include_revisions="true" if field == "plan_id" else "false", limit="100")
            params[field] = (
                own.target.portfolio.id if field == "virtual_portfolio_id" else own.job.plan_id
            )
        original = read(client, actor, path, params)
        if kind == "list":
            entries = mapping(original.json())["items"]
            assert isinstance(entries, list) and entries
            assert all(
                mapping(mapping(item)["job"])["account_id"] == str(own.pin.account_id)
                for item in entries
            )
            assert own.job.plan_id in {mapping(mapping(item)["job"])["plan_id"] for item in entries}
        else:
            assert mapping(original.json())["content_digest"] == detail["content_digest"]
            assert mapping(original.json())["result"] == detail["result"]
        for donor_actor, pin in ((actor, actor.accounts[1]), (other, other.accounts[0])):
            donor = case.plans[pin.account_id]
            donor_detail = mapping(
                read(
                    client,
                    donor_actor,
                    "/api/v1/contribution-plans/" + donor.job.plan_id,
                    {},
                ).json()
            )
            donor_job = mapping(donor_detail["job"])
            assert donor_job["state"] == "succeeded"
            if field == "plan_revision_id":
                identifier = donor_job["plan_revision_id"]
                assert isinstance(identifier, str)
            elif field == "virtual_portfolio_id":
                identifier = donor.target.portfolio.id
            else:
                identifier = donor.job.plan_id
            rejected(
                client,
                case.grid,
                actor,
                path,
                {**params, field: identifier},
                (
                    identifier,
                    donor.job.plan_id,
                    str(pin.account_id),
                ),
            )
        assert read(client, actor, path, params).json() == original.json()


def test_http_benchmark_selection_and_list_cannot_expose_another_definition_or_owner(
    intelligence_owners: IntelligenceOwners,
    command_api: tuple[TestClient, ScopedGridBearer],
) -> None:
    case = intelligence_owners
    client, bearer = command_api
    definitions: dict[str, tuple[str, str]] = {}
    for actor in case.grid.actors:
        version_id = case.benchmarks[actor.principal.owner_id]
        with case.grid.sessions() as session:
            version = session.get(BenchmarkVersionModel, UUID(version_id))
            assert version is not None
            definitions[actor.principal.owner_id] = (str(version.definition_id), version_id)
    for actor, other in (case.grid.actors, tuple(reversed(case.grid.actors))):
        definition_id, version_id = definitions[actor.principal.owner_id]
        path = "/api/v1/benchmark-definitions/" + definition_id
        params = {"selected_version_id": version_id}
        original = read(client, actor, path, params)
        content = mapping(mapping(mapping(original.json())["selected_version"])["content"])
        # A real second owned definition isolates definition binding from owner denial.
        clone = mapping(
            setup_post(
                client,
                actor,
                "/api/v1/benchmark-definitions",
                {
                    "name": "P210 GET selection " + uuid4().hex[:8],
                    "content": content,
                },
                201,
            ).json()
        )
        cloned_version = str(mapping(clone["selected_version"])["id"])
        foreign_definition, foreign_version = definitions[other.principal.owner_id]
        donor = read(
            client,
            other,
            "/api/v1/benchmark-definitions/" + foreign_definition,
            {
                "selected_version_id": foreign_version,
            },
        )
        assert mapping(mapping(donor.json())["selected_version"])["id"] == foreign_version
        for identifier in (cloned_version, foreign_version):
            rejected(
                client, case.grid, actor, path, {"selected_version_id": identifier}, (identifier,)
            )
        assert read(client, actor, path, params).json() == original.json()

        listing = read(
            client, actor, "/api/v1/benchmark-definitions", {"state": "all", "limit": "100"}
        )
        page = mapping(listing.json())
        assert page["next_cursor"] is None
        entries = page["items"]
        assert isinstance(entries, list)
        ids = {mapping(item)["id"] for item in entries}
        assert {definition_id, mapping(clone["definition"])["id"]} <= ids
        assert foreign_definition not in ids and foreign_definition not in listing.text
        before = retained_state(case.grid, STATE)
        bearer.omitted = Scope.ANALYTICS_READ
        try:
            denied = client.get(
                "/api/v1/benchmark-definitions",
                headers={
                    "Authorization": "Bearer " + actor.token,
                    "If-None-Match": listing.headers["etag"],
                },
            )
            assert_denied(denied, "ACCESS_DENIED", (definition_id, foreign_definition))
        finally:
            bearer.omitted = None
        assert retained_state(case.grid, STATE) == before
