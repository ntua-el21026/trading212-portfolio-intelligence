"""Additional real-owner HTTP command authorization boundaries."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

import httpx2
import pytest
from starlette.testclient import TestClient
from trading212_api.main import create_app
from trading212_persistence.source_models import BenchmarkVersionModel
from trading212_persistence.source_service import PostgresSourceService
from trading212_security.principals import Scope

from tests.integration.phase2_authorization_cases import (
    KEY,
    ORIGIN,
    SETTINGS,
    Actor,
    OwnerGrid,
    retained_state,
)
from tests.integration.phase2_authorization_cases import owner_grid as owner_grid
from tests.integration.phase2_mcp_owner_resources import IntelligenceOwners
from tests.integration.phase2_mcp_owner_resources import intelligence_owners as intelligence_owners
from tests.integration.phase2_mcp_owner_transport import ScopedGridBearer, mapping
from tests.integration.test_alert_postgres import alert_database as alert_database

pytestmark = pytest.mark.integration

STATE = (
    "virtual_portfolios",
    "target_versions",
    "target_nodes",
    "target_holdings",
    "target_mapping_decisions",
    "target_constraints",
    "target_exclusions",
    "target_validation_results",
    "target_validation_issues",
    "target_normalization_adjustments",
    "virtual_portfolio_events",
    "target_version_events",
    "target_command_identities",
    "benchmark_definitions",
    "benchmark_versions",
    "benchmark_components",
    "source_command_identities",
    "source_command_versions",
    "contribution_plans",
    "contribution_plan_requests",
    "contribution_plan_inputs",
    "contribution_plan_jobs",
    "contribution_plan_dispatch_outbox",
    "contribution_plan_attempts",
    "contribution_plan_revisions",
    "contribution_plan_lines",
    "planning_command_identities",
)


@dataclass(frozen=True)
class Command:
    method: Literal["POST", "PATCH"]
    path: str
    body: dict[str, object]
    etag: str
    success: int
    scopes: tuple[Scope, ...]
    private: tuple[str, ...]
    key: str


@pytest.fixture
def command_api(
    intelligence_owners: IntelligenceOwners,
) -> Iterator[tuple[TestClient, ScopedGridBearer]]:
    case = intelligence_owners
    bearer = ScopedGridBearer(case.grid.actors)
    sources = PostgresSourceService(
        sessions=case.grid.sessions,
        cursor_signing_key=KEY,
        clock=lambda: case.grid.at,
    )
    api = create_app(
        settings=SETTINGS,
        service=case.grid.portfolio,
        target_service=case.targets,
        planning_service=case.planning,
        source_service=sources,
        bearer_authenticator=bearer,
        clock=lambda: case.grid.at,
    )
    with TestClient(api, base_url=ORIGIN) as client:
        yield client, bearer


def send(client: TestClient, actor: Actor, command: Command) -> httpx2.Response:
    return client.request(
        command.method,
        command.path,
        json=command.body,
        headers={
            "Authorization": "Bearer " + actor.token,
            "X-Idempotency-Key": command.key,
            "If-Match": command.etag,
        },
    )


def assert_denied(
    response: httpx2.Response,
    code: str,
    private: tuple[str, ...],
) -> None:
    assert response.status_code == (404 if code == "NOT_FOUND" else 403), response.text
    assert mapping(mapping(response.json())["error"])["code"] == code
    assert "etag" not in response.headers
    assert all(value not in response.text for value in private)


def deny_then_execute_and_replay(
    client: TestClient,
    bearer: ScopedGridBearer,
    grid: OwnerGrid,
    actor: Actor,
    other: Actor,
    command: Command,
) -> dict[str, object]:
    # The actual victim ETag, key and valid body do not bypass owner/scope checks,
    # including after the owner has established an idempotent success.
    body: dict[str, object] | None = None
    for replay_available in (False, True):
        before = retained_state(grid, STATE)
        assert_denied(send(client, other, command), "NOT_FOUND", command.private)
        assert retained_state(grid, STATE) == before
        for scope in command.scopes:
            bearer.omitted = scope
            try:
                assert_denied(send(client, actor, command), "ACCESS_DENIED", command.private)
                assert retained_state(grid, STATE) == before
            finally:
                bearer.omitted = None
        if not replay_available:
            success = send(client, actor, command)
            assert success.status_code == command.success, success.text
            body = mapping(success.json())
            persisted = retained_state(grid, STATE, include_collections=False)
            replay = send(client, actor, command)
            assert replay.status_code == command.success, replay.text
            assert replay.json() == success.json()
            assert replay.headers["etag"] == success.headers["etag"]
            assert retained_state(grid, STATE, include_collections=False) == persisted
    assert body is not None
    return body


def setup_post(
    client: TestClient,
    actor: Actor,
    path: str,
    body: dict[str, object],
    expected: int,
    etag: str | None = None,
) -> httpx2.Response:
    headers = {"Authorization": "Bearer " + actor.token, "X-Idempotency-Key": uuid4().hex}
    if etag is not None:
        headers["If-Match"] = etag
    response = client.post(path, json=body, headers=headers)
    assert response.status_code == expected, response.text
    return response


TARGET_COMMANDS = (
    "archive_virtual_portfolio",
    "create_target_version",
    "replace_target_draft",
    "validate_target_version",
    "publish_target_version",
    "archive_target_version",
)


@pytest.mark.parametrize("operation", TARGET_COMMANDS)
def test_remaining_target_commands_check_real_owner_and_authenticated_scopes(
    intelligence_owners: IntelligenceOwners,
    command_api: tuple[TestClient, ScopedGridBearer],
    operation: str,
) -> None:
    grid = intelligence_owners.grid
    client, bearer = command_api
    content: dict[str, object] = {
        "nodes": [
            {
                "key": "cash",
                "parent_key": None,
                "kind": "cash",
                "name": "Cash",
                "order": 0,
                "weight": "1",
            }
        ],
        "constraints": [],
        "exclusions": [],
    }
    version_body: dict[str, object] = {"effective_at": grid.at.isoformat(), "content": content}
    for actor, other in (grid.actors, tuple(reversed(grid.actors))):
        created = setup_post(
            client,
            actor,
            "/api/v1/virtual-portfolios",
            {
                "name": "P210 private command " + uuid4().hex[:8],
                "reporting_currency": "EUR",
                "account_id": str(actor.accounts[0].account_id),
            },
            201,
        )
        portfolio = str(mapping(created.json())["id"])
        path = "/api/v1/virtual-portfolios/" + portfolio
        etag = created.headers["etag"]
        private: tuple[str, ...] = (portfolio, str(actor.accounts[0].account_id))
        body: dict[str, object] = {}
        method: Literal["POST", "PATCH"] = "POST"
        success = 200
        if operation == "archive_virtual_portfolio":
            path += "/archive"
        elif operation == "create_target_version":
            path += "/target-versions"
            body, success = version_body, 201
        else:
            draft = setup_post(client, actor, path + "/target-versions", version_body, 201, etag)
            version = str(mapping(draft.json())["id"])
            path, etag = "/api/v1/target-versions/" + version, draft.headers["etag"]
            private = (*private, version)
            if operation == "replace_target_draft":
                method, body = "PATCH", version_body
            elif operation == "validate_target_version":
                path, body = path + "/validate", {"normalize": False}
            else:
                validation = setup_post(
                    client,
                    actor,
                    path + "/validate",
                    {"normalize": False},
                    200,
                    etag,
                )
                validation_id = str(mapping(validation.json())["id"])
                assert mapping(validation.json())["valid"] is True
                etag, body = validation.headers["etag"], {"validation_id": validation_id}
                private = (*private, validation_id)
                if operation == "publish_target_version":
                    path += "/publish"
                else:
                    published = setup_post(client, actor, path + "/publish", body, 200, etag)
                    path, etag, body = path + "/archive", published.headers["etag"], {}
        result = deny_then_execute_and_replay(
            client,
            bearer,
            grid,
            actor,
            other,
            Command(
                method,
                path,
                body,
                etag,
                success,
                (Scope.TARGETS_WRITE, Scope.PORTFOLIO_READ),
                private,
                uuid4().hex,
            ),
        )
        if operation == "publish_target_version":
            assert result["state"] == "active" and isinstance(result["content_digest"], str)
        elif operation.startswith("archive_"):
            assert result["state"] == "archived"
        elif operation == "validate_target_version":
            assert result["valid"] is True


@pytest.mark.parametrize("operation", ("create_benchmark_version", "archive_benchmark_definition"))
def test_remaining_benchmark_commands_check_real_owner_and_authenticated_scopes(
    intelligence_owners: IntelligenceOwners,
    command_api: tuple[TestClient, ScopedGridBearer],
    operation: str,
) -> None:
    case = intelligence_owners
    client, bearer = command_api
    for actor, other in (case.grid.actors, tuple(reversed(case.grid.actors))):
        with case.grid.sessions() as session:
            source = session.get(
                BenchmarkVersionModel, UUID(case.benchmarks[actor.principal.owner_id])
            )
            assert source is not None
            definition_id = str(source.definition_id)
        detail = client.get(
            "/api/v1/benchmark-definitions/" + definition_id,
            headers={"Authorization": "Bearer " + actor.token},
        )
        assert detail.status_code == 200, detail.text
        content = mapping(mapping(mapping(detail.json())["selected_version"])["content"])
        # Clone through the actual API, preserving owned calendar/series provenance.
        created = setup_post(
            client,
            actor,
            "/api/v1/benchmark-definitions",
            {
                "name": "P210 private benchmark " + uuid4().hex[:8],
                "content": content,
            },
            201,
        )
        definition = mapping(mapping(created.json())["definition"])
        identifier = str(definition["id"])
        archive = operation == "archive_benchmark_definition"
        result = deny_then_execute_and_replay(
            client,
            bearer,
            case.grid,
            actor,
            other,
            Command(
                "POST",
                "/api/v1/benchmark-definitions/"
                + identifier
                + ("/archive" if archive else "/versions"),
                {} if archive else {"content": content},
                str(definition["revision_etag"]),
                200 if archive else 201,
                (Scope.TARGETS_WRITE, Scope.ANALYTICS_READ),
                (identifier, actor.principal.owner_id),
                uuid4().hex,
            ),
        )
        if archive:
            assert mapping(result["definition"])["state"] == "archived"
        else:
            assert mapping(result["selected_version"])["version_number"] == 2


def test_plan_revision_checks_real_owner_and_authenticated_scopes_before_retry(
    intelligence_owners: IntelligenceOwners,
    command_api: tuple[TestClient, ScopedGridBearer],
) -> None:
    case = intelligence_owners
    client, bearer = command_api
    for actor, other in (case.grid.actors, tuple(reversed(case.grid.actors))):
        resource = case.plans[actor.accounts[0].account_id]
        body: dict[str, object] = {
            "account_id": str(resource.pin.account_id),
            "snapshot_id": str(resource.pin.snapshot_id),
            "virtual_portfolio_id": resource.target.portfolio.id,
            "target_version_id": resource.target.version.id,
            "contribution": {"amount": "20", "currency": "EUR"},
            "mode": "global",
            "coverage_policy": "allow_degraded",
        }
        path = "/api/v1/contribution-plans/" + resource.job.plan_id
        detail = client.get(path, headers={"Authorization": "Bearer " + actor.token})
        assert detail.status_code == 200, detail.text
        original = mapping(detail.json())
        assert mapping(original["job"])["state"] == "succeeded"
        result = deny_then_execute_and_replay(
            client,
            bearer,
            case.grid,
            actor,
            other,
            Command(
                "POST",
                path + "/revisions",
                body,
                str(original["revision_etag"]),
                202,
                (Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.TARGETS_READ, Scope.PLANS_WRITE),
                (resource.job.plan_id, str(resource.pin.account_id), resource.job.input_digest),
                uuid4().hex,
            ),
        )
        assert result["plan_id"] == resource.job.plan_id and result["request_revision"] == 2
        retained = client.get(
            path,
            params={
                "plan_revision_id": str(mapping(original["job"])["plan_revision_id"]),
            },
            headers={"Authorization": "Bearer " + actor.token},
        )
        assert retained.status_code == 200, retained.text
        assert mapping(retained.json())["result"] == original["result"]
        assert mapping(retained.json())["content_digest"] == original["content_digest"]
