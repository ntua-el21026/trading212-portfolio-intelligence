"""Projection route authorization order, exact commands and bounded saved-value responses."""

from dataclasses import fields, replace
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from trading212_api.main import create_app
from trading212_application import projection as app
from trading212_application import projection_presentation as presentation
from trading212_application import projection_views as views
from trading212_application.services import SyntheticPortfolioService
from trading212_application.views import Page
from trading212_domain.projection import ProjectionSourcePin
from trading212_domain.serialization import to_primitive
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

from tests.unit.api.projection_factories import (
    ACCOUNT,
    GOAL,
    GOAL_ID,
    METADATA,
    NOW,
    RUN,
    SET,
    VERSION,
    assumption_set,
    assumption_version,
    cancelled,
    goal,
    goal_version,
    queued,
    run,
    saved,
)

pytestmark = pytest.mark.unit
ORIGIN = "https://testserver"
READ_SCOPES = frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ})
SCOPES = READ_SCOPES | {Scope.PROJECTIONS_WRITE, Scope.GOALS_WRITE}
HEADERS = {
    "Authorization": "Bearer synthetic-projection-test",
    "X-Idempotency-Key": "synthetic-one",
}


class Bearer:
    def __init__(self, scopes: frozenset[Scope]) -> None:
        self.scopes = scopes

    async def authenticate(self, token: str) -> Principal:
        assert token == "synthetic-projection-test"
        return Principal(
            "projection-test",
            str(UUID(int=1)),
            "test",
            "test",
            self.scopes,
            NOW,
            NOW + timedelta(hours=1),
        )


def application(
    scopes: frozenset[Scope] = SCOPES, *, available: bool = True
) -> tuple[FastAPI, AsyncMock]:
    service = AsyncMock(spec=app.ProjectionService)
    service.create_assumption_set.return_value = service.get_assumption_set.return_value = (
        assumption_set()
    )
    service.create_assumption_version.return_value = replace(
        assumption_version(), id=UUID(int=8804), predecessor_id=VERSION, version_number=2
    )
    service.get_assumption_version.return_value = assumption_version()
    service.list_assumption_sets.return_value = Page((assumption_set(),), None, 25, 1)
    service.list_assumption_versions.return_value = Page((assumption_version(),), None, 25, 1)
    service.create_goal.return_value = service.get_goal.return_value = goal()
    service.create_goal_version.return_value = replace(
        goal_version(), id=UUID(int=8805), predecessor_id=GOAL, version_number=2
    )
    service.get_goal_version.return_value = goal_version()
    service.list_goals.return_value = Page((goal(),), None, 25, 1)
    service.list_goal_versions.return_value = Page((goal_version(),), None, 25, 1)
    service.create_run.return_value = queued()
    service.get_run.return_value = run()
    service.list_runs.return_value = Page((queued(),), None, 25, 1)
    service.cancel_run.return_value = cancelled()
    service.get_goal_analysis.return_value = presentation.project_goal_analysis(saved())
    api = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            allowed_hosts=("testserver",),
            allowed_origins=(ORIGIN,),
            local_synthetic_auth_enabled=True,
        ),
        service=SyntheticPortfolioService(clock=lambda: NOW),
        projection_service=cast(app.ProjectionService, service) if available else None,
        bearer_authenticator=Bearer(scopes),
        clock=lambda: NOW,
    )
    return api, service


def run_body() -> dict[str, Any]:
    value = cast(dict[str, Any], to_primitive(saved().capture.selection))
    value.pop("account_id")
    value["initial_basis"] = value.pop("initial")
    return value


def body_for(name: str) -> dict[str, Any] | None:
    if name in {
        "create_assumption_set",
        "create_assumption_version",
        "create_goal",
        "create_goal_version",
    }:
        content = (
            goal_version().content
            if name in {"create_goal", "create_goal_version"}
            else assumption_version().content
        )
        return {"metadata": to_primitive(METADATA), "content": to_primitive(content)}
    return run_body() if name == "create_run" else {} if name == "cancel_run" else None


OPERATIONS = (
    ("get", f"/accounts/{ACCOUNT}/assumption-sets", "list_assumption_sets", 200),
    ("post", f"/accounts/{ACCOUNT}/assumption-sets", "create_assumption_set", 201),
    ("get", f"/assumption-sets/{SET}", "get_assumption_set", 200),
    ("get", f"/assumption-sets/{SET}/versions", "list_assumption_versions", 200),
    ("post", f"/assumption-sets/{SET}/versions", "create_assumption_version", 201),
    ("get", f"/assumption-versions/{VERSION}", "get_assumption_version", 200),
    ("get", f"/accounts/{ACCOUNT}/goals", "list_goals", 200),
    ("post", f"/accounts/{ACCOUNT}/goals", "create_goal", 201),
    ("get", f"/goals/{GOAL_ID}", "get_goal", 200),
    ("get", f"/goals/{GOAL_ID}/versions", "list_goal_versions", 200),
    ("post", f"/goals/{GOAL_ID}/versions", "create_goal_version", 201),
    ("get", f"/goal-versions/{GOAL}", "get_goal_version", 200),
    ("get", f"/accounts/{ACCOUNT}/projection-runs", "list_runs", 200),
    ("post", f"/accounts/{ACCOUNT}/projection-runs", "create_run", 202),
    ("get", f"/projection-runs/{RUN}", "get_run", 200),
    ("get", f"/projection-runs/{RUN}/goal-analysis", "get_goal_analysis", 200),
    ("post", f"/projection-runs/{RUN}/cancel", "cancel_run", 200),
)


@pytest.mark.parametrize("method,path,name,status", OPERATIONS)
async def test_all_seventeen_routes_delegate_exact_typed_commands_and_saved_views(
    method: str, path: str, name: str, status: int
) -> None:
    api, service = application()
    aggregate = GOAL_ID if name == "create_goal_version" else SET
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.request(
            method,
            "/api/v1" + path,
            json=body_for(name),
            headers={**HEADERS, "If-Match": f'"{aggregate}:1"'},
        )
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == to_primitive(getattr(service, name).return_value)
    assert len(service.mock_calls) == 1
    if method == "post":
        command = getattr(service, name).call_args.args[1]
        assert command.idempotency_key == "synthetic-one"
        if name == "create_run":
            assert command.selection == saved().capture.selection
        elif name != "cancel_run":
            assert command.metadata == METADATA
            assert command.content == (
                goal_version().content
                if name in {"create_goal", "create_goal_version"}
                else assumption_version().content
            )
        if name.endswith("_version"):
            assert command.expected_revision == 1
            assert response.headers["etag"] == f'"{aggregate}:2"'


@pytest.mark.parametrize("method,path,name,status", OPERATIONS)
async def test_authentication_and_read_scopes_precede_malformed_body_and_query(
    method: str, path: str, name: str, status: int
) -> None:
    for scopes, headers, expected in (
        (SCOPES, {}, 401),
        (SCOPES - {Scope.PORTFOLIO_READ}, HEADERS, 403),
        (SCOPES - {Scope.ANALYTICS_READ}, HEADERS, 403),
    ):
        api, service = application(scopes)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
            response = await client.request(
                method,
                "/api/v1" + path + "?private-canary=hidden",
                content=b"malformed",
                headers=headers,
            )
        assert response.status_code == expected and not service.mock_calls
        assert "canary" not in response.text


@pytest.mark.parametrize(
    "kind,scope",
    [
        ("assumption-sets", Scope.PROJECTIONS_WRITE),
        ("goals", Scope.GOALS_WRITE),
        ("projection-runs", Scope.PROJECTIONS_WRITE),
    ],
)
async def test_write_scopes_are_independent_and_precede_parsing(kind: str, scope: Scope) -> None:
    api, service = application(SCOPES - {scope})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        denied = await client.post(
            f"/api/v1/accounts/{ACCOUNT}/{kind}", content=b"invalid", headers=HEADERS
        )
    assert denied.status_code == 403 and not service.mock_calls
    api, service = application(READ_SCOPES | {scope})
    name = {
        "assumption-sets": "create_assumption_set",
        "goals": "create_goal",
        "projection-runs": "create_run",
    }[kind]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        allowed = await client.post(
            f"/api/v1/accounts/{ACCOUNT}/{kind}", json=body_for(name), headers=HEADERS
        )
    assert allowed.status_code in (201, 202) and len(service.mock_calls) == 1


@pytest.mark.parametrize(
    "path,name,identifier",
    [
        (f"/assumption-sets/{SET}/versions", "create_assumption_version", SET),
        (f"/goals/{GOAL_ID}/versions", "create_goal_version", GOAL_ID),
    ],
)
@pytest.mark.parametrize(
    "revision,status",
    [
        (None, 428),
        ('W/"old"', 422),
        ('"invalid"', 422),
        ('"{id}:513"', 422),
        ('"{id}:01"', 422),
        (f'"{RUN}:1"', 412),
    ],
)
async def test_versions_require_strict_matching_aggregate_revision(
    path: str, name: str, identifier: UUID, revision: str | None, status: int
) -> None:
    api, service = application()
    header = None if revision is None else revision.replace("{id}", str(identifier))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            "/api/v1" + path,
            json=body_for(name),
            headers={**HEADERS, **({"If-Match": header} if header is not None else {})},
        )
    assert response.status_code == status and not service.mock_calls


@pytest.mark.parametrize(
    "path,name",
    [
        (f"/assumption-sets/{SET}", "get_assumption_set"),
        (f"/assumption-versions/{VERSION}", "get_assumption_version"),
        (f"/goals/{GOAL_ID}", "get_goal"),
        (f"/goal-versions/{GOAL}", "get_goal_version"),
        (f"/projection-runs/{RUN}", "get_run"),
        (f"/projection-runs/{RUN}/goal-analysis", "get_goal_analysis"),
    ],
)
async def test_every_conditional_read_calls_current_service_and_denial_precedes_304(
    path: str, name: str
) -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        first = await client.get("/api/v1" + path, headers=HEADERS)
        same = await client.get(
            "/api/v1" + path, headers={**HEADERS, "If-None-Match": first.headers["etag"]}
        )
        assert first.status_code == 200 and same.status_code == 304
        assert getattr(service, name).await_count == 2
        getattr(service, name).side_effect = app.ProjectionServiceError(
            app.ProjectionErrorCode.SOURCE_UNAVAILABLE, "private-license-canary"
        )
        denied = await client.get("/api/v1" + path, headers={**HEADERS, "If-None-Match": "*"})
    assert denied.status_code == 503 and denied.headers["cache-control"] == "private, no-store"
    assert "canary" not in denied.text and denied.json()["error"]["retryable"]


@pytest.mark.parametrize(
    "code,status",
    [
        (app.ProjectionErrorCode.NOT_FOUND, 404),
        (app.ProjectionErrorCode.ACCESS_DENIED, 403),
        (app.ProjectionErrorCode.CONFLICT, 409),
        (app.ProjectionErrorCode.RUN_EXPIRED, 410),
        (app.ProjectionErrorCode.RATE_LIMITED, 429),
    ],
)
async def test_service_errors_are_sanitized_even_with_wildcard_etag(
    code: app.ProjectionErrorCode, status: int
) -> None:
    api, service = application()
    service.get_run.side_effect = app.ProjectionServiceError(code, "private-owner-canary")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.get(
            f"/api/v1/projection-runs/{RUN}", headers={**HEADERS, "If-None-Match": "*"}
        )
    assert response.status_code == status and "canary" not in response.text
    if status == 429:
        assert response.headers["retry-after"] == "60"


@pytest.mark.parametrize(
    "query",
    [
        "point_limit=0",
        "point_limit=101",
        "point_limit=true",
        "point_limit=1&point_limit=2",
        "point_cursor=" + "x" * 2049,
        "point_cursor=a&point_cursor=b",
        "private-canary=hidden",
    ],
)
async def test_point_queries_are_closed_and_bounded_before_service(query: str) -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.get(f"/api/v1/projection-runs/{RUN}?{query}", headers=HEADERS)
    assert response.status_code == 422 and not service.mock_calls and "canary" not in response.text


async def test_body_duplicate_headers_uuid_and_idempotency_guards() -> None:
    api, service = application()
    path = f"/api/v1/accounts/{ACCOUNT}/projection-runs"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        for changes in ({"owner_id": str(ACCOUNT)}, {"seed": True}, {"paths": 1.5}):
            response = await client.post(path, json={**run_body(), **changes}, headers=HEADERS)
            assert response.status_code == 422
        for key in (None, "", "x" * 181):
            response = await client.post(
                path,
                json=run_body(),
                headers={
                    "Authorization": HEADERS["Authorization"],
                    **({"X-Idempotency-Key": key} if key is not None else {}),
                },
            )
            assert response.status_code == 422
        for header in ("X-Idempotency-Key", "If-Match", "If-None-Match", "Origin", "X-CSRF-Token"):
            response = await client.post(
                path, json=run_body(), headers=[*HEADERS.items(), (header, "one"), (header, "two")]
            )
            assert response.status_code == 422
        for identifier in ("not-a-uuid", str(ACCOUNT).replace("-", ""), "{" + str(ACCOUNT) + "}"):
            response = await client.get(
                f"/api/v1/accounts/{identifier}/projection-runs", headers=HEADERS
            )
            assert response.status_code == 422
        response = await client.post(path, content=b"x" * 65537, headers=HEADERS)
        assert response.status_code == 413
    assert not service.mock_calls


async def test_snapshot_selection_rejects_client_money_and_model_keeps_exact_money_and_dates() -> (
    None
):
    api, service = application()
    body = run_body()
    body["initial_basis"]["modeled_value"] = {"amount": "999", "currency": "EUR"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        denied = await client.post(
            f"/api/v1/accounts/{ACCOUNT}/projection-runs", json=body, headers=HEADERS
        )
        assert denied.status_code == 422 and not service.mock_calls
        body["initial_basis"] = {
            "kind": "modeled_value",
            "modeled_value": {"amount": "123.123456789012345678", "currency": "EUR"},
            "modeled_anchor_date": "2025-01-31",
        }
        accepted = await client.post(
            f"/api/v1/accounts/{ACCOUNT}/projection-runs", json=body, headers=HEADERS
        )
    assert accepted.status_code == 202
    selected = service.create_run.call_args.args[1].selection
    assert selected.initial.modeled_value is not None
    assert selected.initial.modeled_anchor_date is not None
    assert selected.initial.modeled_value.amount == Decimal("123.123456789012345678")
    assert selected.initial.modeled_anchor_date.isoformat() == "2025-01-31"
    assert (
        selected.schedule == saved().capture.selection.schedule
        and selected.sensitivity == saved().capture.selection.sensitivity
    )


@pytest.mark.parametrize(
    "date,code", [("2025-02-27", "DATE_NOT_MONTH_BOUNDARY"), ("2026-02-28", "DATE_OUTSIDE_HORIZON")]
)
async def test_modeled_calendar_errors_have_closed_codes_before_admission(
    date: str, code: str
) -> None:
    api, service = application()
    body = run_body()
    body["initial_basis"] = {
        "kind": "modeled_value",
        "modeled_value": {"amount": "100", "currency": "EUR"},
        "modeled_anchor_date": "2025-01-31",
    }
    body["schedule"]["entries"][0]["on"] = date
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            f"/api/v1/accounts/{ACCOUNT}/projection-runs", json=body, headers=HEADERS
        )
    assert (
        response.status_code == 422
        and response.json()["error"]["code"] == code
        and not service.mock_calls
    )


async def test_symmetric_but_non_psd_assumptions_fail_before_service() -> None:
    api, service = application()
    body = cast(dict[str, Any], body_for("create_assumption_set"))
    body["content"]["assets"] = [
        {"key": key, "annual_mean_log_return": "0", "annual_volatility": "0.1", "weight": weight}
        for key, weight in (("a", "0.2"), ("b", "0.3"), ("c", "0.5"))
    ]
    body["content"]["correlation"] = [
        ["1", "0.9", "0.9"],
        ["0.9", "1", "-0.9"],
        ["0.9", "-0.9", "1"],
    ]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            f"/api/v1/accounts/{ACCOUNT}/assumption-sets", json=body, headers=HEADERS
        )
    assert response.status_code == 422 and not service.mock_calls


async def test_session_origin_and_csrf_precede_projection_command() -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        session = await client.post("/api/v1/auth/local-session")
        csrf = session.json()["csrf_token"]
        for extra in (
            {},
            {"Origin": ORIGIN},
            {"Origin": "https://foreign.invalid", "X-CSRF-Token": csrf},
        ):
            response = await client.post(
                f"/api/v1/projection-runs/{RUN}/cancel",
                json={},
                headers={"X-Idempotency-Key": "cancel-one", **extra},
            )
            assert response.status_code == 401 and not service.mock_calls
        response = await client.post(
            f"/api/v1/projection-runs/{RUN}/cancel",
            json={},
            headers={"X-Idempotency-Key": "cancel-one", "Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
    assert response.status_code == 200 and service.cancel_run.await_count == 1


async def test_complete_dated_points_and_goal_variants_keep_saved_values() -> None:
    api, service = application()
    service.get_run.return_value = run(offset=27, limit=2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.get(
            f"/api/v1/projection-runs/{RUN}?point_limit=2&point_cursor=signed_27", headers=HEADERS
        )
        goals = await client.get(f"/api/v1/projection-runs/{RUN}/goal-analysis", headers=HEADERS)
    assert response.status_code == 200 and goals.status_code == 200
    assert service.get_run.call_args.args[2] == app.ProjectionPointPageQuery(
        point_limit=2, point_cursor="signed_27"
    )
    body = response.json()["result"]
    assert body["points"]["total"] == 84 and body["points"]["next_cursor"] == "signed_29"
    for row, (variant, path, point_index) in zip(
        body["points"]["items"], ((0, 6, 3), (1, 0, 0)), strict=True
    ):
        original = saved().calculation.variants[variant].paths[path].points[point_index]
        for field in fields(original):
            actual, expected = row["point"][field.name], getattr(original, field.name)
            if isinstance(expected, Decimal):
                assert Decimal(actual["amount"]) == expected and actual["currency"] == "EUR"
            elif field.name == "assets":
                assert [(item["key"], Decimal(item["value"]["amount"])) for item in actual] == [
                    (item.key, item.value) for item in expected
                ]
            else:
                assert actual == expected
    assert len(body["variants"]) == len(goals.json()["variants"]) == 3
    assert all(
        not variant["estimate"]["automatic_goal_acceptance"] for variant in goals.json()["variants"]
    )


@pytest.mark.parametrize("operation", ["create_run", "list_runs", "cancel_run"])
async def test_operational_routes_reject_financial_payloads(operation: str) -> None:
    api, service = application()
    getattr(service, operation).return_value = (
        Page((run(),), None, 25, 1) if operation == "list_runs" else run()
    )
    path = (
        f"/api/v1/projection-runs/{RUN}/cancel"
        if operation == "cancel_run"
        else f"/api/v1/accounts/{ACCOUNT}/projection-runs"
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.request(
            "get" if operation == "list_runs" else "post",
            path,
            json=body_for(operation),
            headers=HEADERS,
        )
    assert response.status_code == 500 and "assets" not in response.text


async def test_unavailable_no_goal_and_missing_composition_are_explicit() -> None:
    api, service = application()
    service.get_goal_analysis.return_value = presentation.unavailable_goal_analysis(
        replace(queued(), goal_version_id=None)
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        result = await client.get(f"/api/v1/projection-runs/{RUN}/goal-analysis", headers=HEADERS)
    assert result.status_code == 200 and result.json()["reason"] == "no_goal_pinned"
    assert result.json()["context"] is None and result.json()["variants"] == []
    api, service = application(available=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        result = await client.get(f"/api/v1/projection-runs/{RUN}", headers=HEADERS)
    assert result.status_code == 503 and not service.mock_calls


async def test_actual_full_utf8_collection_envelope_exceeds_two_mib_without_truncation() -> None:
    api, service = application()
    original = assumption_version()
    content = replace(
        original.content,
        calibration_pins=tuple(
            ProjectionSourcePin(subject_id=str(UUID(int=30000 + index)), content_digest="a" * 64)
            for index in range(256)
        ),
    )
    bulky = replace(original, metadata=replace(METADATA, description="界" * 1024), content=content)
    service.list_assumption_versions.return_value = Page(
        tuple(bulky for _ in range(100)), None, 100, 100
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        result = await client.get(
            f"/api/v1/assumption-sets/{SET}/versions?limit=100",
            headers={**HEADERS, "If-None-Match": "*"},
        )
    assert result.status_code == 422 and result.json()["error"]["code"] == "RESULT_TOO_LARGE"
    assert "界" not in result.text


async def test_final_utf8_byte_check_precedes_wildcard_conditional_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from trading212_api_contracts.projections import AssumptionSetResponse

    api, service = application()
    value = replace(assumption_set(), name="界" * 120)
    service.get_assumption_set.return_value = value
    encoded = AssumptionSetResponse.model_validate(to_primitive(value)).model_dump_json()
    assert len(encoded.encode("utf-8")) > len(encoded)
    monkeypatch.setattr(views, "PROJECTION_PUBLIC_RESPONSE_BYTES", len(encoded.encode("utf-8")) - 1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.get(
            f"/api/v1/assumption-sets/{SET}", headers={**HEADERS, "If-None-Match": "*"}
        )
    assert response.status_code == 422 and response.json()["error"]["code"] == "RESULT_TOO_LARGE"


async def test_streamed_body_limit_does_not_trust_content_length() -> None:
    from collections.abc import AsyncIterator

    async def chunks() -> AsyncIterator[bytes]:
        yield b"x" * 65536
        yield b"y"

    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            f"/api/v1/accounts/{ACCOUNT}/projection-runs",
            content=chunks(),
            headers={**HEADERS, "Content-Length": "1"},
        )
    assert response.status_code == 413 and not service.mock_calls


@pytest.mark.parametrize(
    "field,value", [("currency", "USD"), ("allocation_residual", "999"), ("funding_failed", True)]
)
async def test_invalid_saved_financial_page_never_crosses_response_boundary(
    field: str, value: str | bool
) -> None:
    api, service = application()
    raw = to_primitive(run())
    point = raw["result"]["points"]["items"][0]["point"]
    if field == "currency":
        point["nominal"]["currency"] = value
    elif field == "allocation_residual":
        point[field]["amount"] = value
    else:
        point[field] = value
    service.get_run.return_value = raw
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.get(f"/api/v1/projection-runs/{RUN}", headers=HEADERS)
    assert response.status_code == 500 and "999" not in response.text
