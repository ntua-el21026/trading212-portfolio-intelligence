"""Authenticated fixed planning routes, command preconditions and safe wire bounds."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from trading212_api.main import create_app
from trading212_api.planning_schemas import planning_command
from trading212_api_contracts.planning import CreateContributionPlanRequest
from trading212_application import planning as app
from trading212_application.services import SyntheticPortfolioService
from trading212_application.views import Page
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
ORIGIN = "https://testserver"
ACCOUNT = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee"
PORTFOLIO = "aef0bdf3-3613-4cfe-b15f-bc1f8b9c4119"
TARGET = "19a8b590-9c18-4c43-8dce-d622cb6ae033"
SNAPSHOT = "5dd1049e-7433-43f4-bf5b-3a73c24c0568"
PLAN = "b7e267ab-9f80-4cda-8f5e-e5c28a7f72b9"
REQUEST = "fedaa769-cba7-4b7e-8f4a-30ab5795ea8e"
JOB = "6fdba70f-39ec-4df5-8e96-1d965c892c04"
BODY: dict[str, Any] = {
    "account_id": ACCOUNT,
    "virtual_portfolio_id": PORTFOLIO,
    "target_version_id": TARGET,
    "snapshot_id": SNAPSHOT,
    "contribution": {"amount": "10", "currency": "EUR"},
    "mode": "global",
}
ALL_SCOPES = frozenset(
    {Scope.PORTFOLIO_READ, Scope.TARGETS_READ, Scope.ANALYTICS_READ, Scope.PLANS_WRITE}
)


class _Bearer:
    def __init__(self, scopes: frozenset[Scope]) -> None:
        self.scopes = scopes

    async def authenticate(self, token: str) -> Principal:
        assert token == "planning-test-token"
        return Principal(
            "planning-test",
            LOCAL_SYNTHETIC_OWNER_ID,
            "planning-test",
            "planning-test",
            self.scopes,
            NOW,
            NOW + timedelta(hours=1),
        )


def _job() -> app.ContributionPlanJobView:
    return app.ContributionPlanJobView(
        plan_id=PLAN,
        account_id=ACCOUNT,
        virtual_portfolio_id=PORTFOLIO,
        target_version_id=TARGET,
        snapshot_id=SNAPSHOT,
        request_id=REQUEST,
        request_revision=1,
        job_id=JOB,
        state=app.PlanJobState.QUEUED,
        outcome=None,
        requested_at=NOW,
        input_digest="a" * 64,
    )


def _app(
    scopes: frozenset[Scope] = ALL_SCOPES, *, available: bool = True
) -> tuple[FastAPI, AsyncMock]:
    service = AsyncMock(spec=app.PlanningService)
    service.create_contribution_plan.return_value = _job()
    service.create_contribution_plan_revision.return_value = replace(_job(), request_revision=2)
    service.get_contribution_plan.return_value = app.ContributionPlanDetailView(
        _job(),
        planning_command(CreateContributionPlanRequest.model_validate(BODY)),
        None,
        Page((), None, 25, 0),
        None,
        None,
    )
    application = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
            allowed_hosts=("testserver",),
            allowed_origins=(ORIGIN,),
        ),
        service=SyntheticPortfolioService(clock=lambda: NOW),
        planning_service=cast(app.PlanningService, service) if available else None,
        bearer_authenticator=_Bearer(scopes),
        clock=lambda: NOW,
    )
    return application, service


def _headers(**extra: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer planning-test-token",
        "X-Idempotency-Key": "planning:one",
        **extra,
    }


@pytest.mark.parametrize("missing", list(ALL_SCOPES))
async def test_every_plan_command_scope_is_required_before_service(missing: Scope) -> None:
    application, service = _app(ALL_SCOPES - {missing})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        denied = await client.post("/api/v1/contribution-plans", json=BODY, headers=_headers())
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "ACCESS_DENIED"
    service.create_contribution_plan.assert_not_awaited()


async def test_plan_read_requires_read_scopes_without_granting_target_or_plan_write() -> None:
    application, service = _app(frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ}))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        response = await client.get(f"/api/v1/contribution-plans/{PLAN}", headers=_headers())
        assert response.status_code == 200
        denied = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/actual-vs-target",
            params={
                "snapshot_id": SNAPSHOT,
                "virtual_portfolio_id": PORTFOLIO,
                "target_version_id": TARGET,
                "reporting_currency": "EUR",
            },
            headers=_headers(),
        )
        assert denied.status_code == 403
    service.get_actual_vs_target.assert_not_awaited()
    service.create_contribution_plan.assert_not_awaited()


async def test_cookie_commands_require_session_csrf_and_trusted_origin() -> None:
    application, service = _app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        session = await client.post("/api/v1/auth/local-session")
        assert session.status_code == 201
        csrf = session.json()["csrf_token"]
        for headers in (
            {},
            {"Origin": ORIGIN},
            {"X-CSRF-Token": csrf},
            {"Origin": "https://foreign.invalid", "X-CSRF-Token": csrf},
            {"Origin": ORIGIN, "X-CSRF-Token": "invalid"},
        ):
            denied = await client.post(
                "/api/v1/contribution-plans",
                json=BODY,
                headers={"X-Idempotency-Key": "cookie-plan", **headers},
            )
            assert denied.status_code == 401
        service.create_contribution_plan.assert_not_awaited()
        response = await client.post(
            "/api/v1/contribution-plans",
            json=BODY,
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf, "X-Idempotency-Key": "cookie-plan"},
        )
        assert response.status_code == 202 and response.json()["state"] == "queued"
        assert response.json()["outcome"] is None and response.json()["execution_allowed"] is False
        bearer = await client.post("/api/v1/contribution-plans", json=BODY, headers=_headers())
        assert bearer.status_code == 202


@pytest.mark.parametrize("key", [None, "", "white space", "x" * 181])
async def test_command_idempotency_key_is_required_and_bounded(key: str | None) -> None:
    application, service = _app()
    headers = {"Authorization": "Bearer planning-test-token"}
    if key is not None:
        headers["X-Idempotency-Key"] = key
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        response = await client.post("/api/v1/contribution-plans", json=BODY, headers=headers)
        assert response.status_code == 422
    service.create_contribution_plan.assert_not_awaited()


async def test_recalculation_passes_absent_or_stale_precondition_for_service_replay() -> None:
    application, service = _app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        for etag in (None, f'"{PLAN}:1"'):
            headers = _headers(**({"If-Match": etag} if etag else {}))
            result = await client.post(
                f"/api/v1/contribution-plans/{PLAN}/revisions", json=BODY, headers=headers
            )
            assert result.status_code == 202
            assert service.create_contribution_plan_revision.call_args.kwargs["if_match"] == etag
            assert result.json()["revision_etag"] == f'"{PLAN}:2"'


async def test_conditional_read_authenticates_and_hashes_complete_current_representation() -> None:
    application, service = _app()
    path = f"/api/v1/contribution-plans/{PLAN}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        denied = await client.get(path, headers={"If-None-Match": "*"})
        assert denied.status_code == 401
        service.get_contribution_plan.assert_not_awaited()
        first = await client.get(path, headers=_headers())
        assert first.status_code == 200
        etag = first.headers["etag"]
        assert etag != first.json()["revision_etag"]
        same = await client.get(path, headers=_headers(**{"If-None-Match": etag}))
        assert same.status_code == 304 and not same.content
        previous = service.get_contribution_plan.return_value
        service.get_contribution_plan.return_value = replace(
            previous, job=replace(previous.job, state=app.PlanJobState.RUNNING)
        )
        changed = await client.get(path, headers=_headers(**{"If-None-Match": etag}))
        assert changed.status_code == 200 and changed.headers["etag"] != etag
        assert changed.json()["revision_etag"] == first.json()["revision_etag"]


@pytest.mark.parametrize(
    "path",
    [
        f"/api/v1/contribution-plans?account_id={ACCOUNT}&limit=1&limit=2",
        f"/api/v1/contribution-plans?account_id={ACCOUNT}&limit=101",
        f"/api/v1/contribution-plans/{PLAN}?provider_secret=private-value",
        f"/api/v1/contribution-plans/{PLAN}?plan_revision_id=not-a-uuid",
    ],
)
async def test_unbounded_unknown_or_ambiguous_queries_fail_without_echo(path: str) -> None:
    application, service = _app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        response = await client.get(path, headers=_headers())
        assert response.status_code == 422 and "private-value" not in response.text
    service.get_contribution_plan.assert_not_awaited()
    service.list_contribution_plans.assert_not_awaited()


async def test_planning_request_bound_counts_stream_bytes_before_json_or_service() -> None:
    application, service = _app()

    async def body() -> Any:
        for _ in range(65):
            yield b" " * 1024

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        response = await client.post(
            "/api/v1/contribution-plans",
            content=body(),
            headers={**_headers(), "Content-Type": "application/json"},
        )
        assert (
            response.status_code == 413 and response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
        )
    service.create_contribution_plan.assert_not_awaited()


@pytest.mark.parametrize(
    "code,expected",
    [
        (app.PlanningServiceErrorCode.REVISION_REQUIRED, 428),
        (app.PlanningServiceErrorCode.REVISION_MISMATCH, 412),
        (app.PlanningServiceErrorCode.IDEMPOTENCY_KEY_REUSED, 409),
        (app.PlanningServiceErrorCode.NOT_FOUND, 404),
        (app.PlanningServiceErrorCode.PLANNING_UNAVAILABLE, 503),
    ],
)
async def test_service_failures_are_fixed_safe_error_envelopes(
    code: app.PlanningServiceErrorCode, expected: int
) -> None:
    application, service = _app()
    service.create_contribution_plan.side_effect = app.PlanningServiceError(
        code, "private-service-detail"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        response = await client.post("/api/v1/contribution-plans", json=BODY, headers=_headers())
        assert response.status_code == expected and response.json()["error"]["code"] == code.value
        assert (
            "private-service-detail" not in response.text
            and response.json()["error"]["details"] == {}
        )


async def test_optional_legacy_runtime_is_authenticated_unavailable_not_successful_noop() -> None:
    application, _ = _app(available=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        denied = await client.post("/api/v1/contribution-plans", json=BODY)
        assert denied.status_code == 401
        response = await client.post("/api/v1/contribution-plans", json=BODY, headers=_headers())
        assert (
            response.status_code == 503
            and response.json()["error"]["code"] == "PLANNING_UNAVAILABLE"
        )
