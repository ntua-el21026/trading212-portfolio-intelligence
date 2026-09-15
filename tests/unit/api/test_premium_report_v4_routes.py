"""Exact six-route V4 dispatch retains authentication and final conditional checks."""

from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from trading212_application import reports as app
from trading212_domain.report_v4 import ReportSelectionV4
from trading212_security.principals import Scope

from tests.unit.api.projection_report_profile_factories import (
    PROFILE,
    body_v4,
    manifest_v4,
    status_v4,
)
from tests.unit.api.report_factories import ACCOUNT, ARTIFACT, JOB, artifact
from tests.unit.api.test_premium_report_profile_routes import (
    OPERATIONS,
)
from tests.unit.api.test_premium_report_profile_routes import (
    application as application_v3,
)
from tests.unit.api.test_report_routes import ORIGIN, SCOPES, _headers

pytestmark = pytest.mark.unit


def application(
    scopes: frozenset[Scope] = SCOPES,
) -> tuple[FastAPI, tuple[AsyncMock, ...], AsyncMock]:
    api, legacy, second, third = application_v3(scopes)
    fourth = AsyncMock(spec=app.ReportService)
    fourth.generate_report.return_value = status_v4()
    fourth.get_report_status.return_value = status_v4()
    fourth.list_reports.return_value = {
        "items": [status_v4()],
        "next_cursor": None,
        "limit": 25,
        "total": 1,
    }
    fourth.create_report_download_grant.return_value = {
        "artifact_id": ARTIFACT,
        "token": "a" * 43,
        "expires_at": "2026-09-07T12:05:00Z",
    }
    fourth.download_report_artifact.return_value = artifact()
    api.state.context.premium_report_v4_service = fourth
    return api, (legacy, second, third), fourth


async def test_exact_saved_projection_command_and_idempotency_use_only_four() -> None:
    api, old, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        responses = [
            await client.post(
                "/api/v2/report-jobs",
                params={"profile": PROFILE},
                json=body_v4(),
                headers=_headers(),
            )
            for _ in range(2)
        ]
    assert all(item.status_code == 202 for item in responses)
    assert responses[0].content == responses[1].content
    command = service.generate_report.await_args.args[1]
    assert isinstance(command.selection, ReportSelectionV4)
    assert command.selection.premium_run.run_id == UUID(JOB) and not hasattr(
        command.selection, "risk_run_id"
    )
    assert command.idempotency_key == "report:one" and command.ttl_days == 7
    assert service.generate_report.await_args_list[0] == service.generate_report.await_args_list[1]
    assert not any(item.mock_calls for item in old)


@pytest.mark.parametrize("profile", [None, "report_sections_v2", "report_sections_v3"])
async def test_four_body_cannot_enter_another_profile(profile: str | None) -> None:
    api, old, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            "/api/v2/report-jobs",
            params={} if profile is None else {"profile": profile},
            json=body_v4(),
            headers=_headers(),
        )
    assert response.status_code == 422
    assert not service.mock_calls and not any(item.mock_calls for item in old)


@pytest.mark.parametrize(
    "missing", [Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.REPORTS_WRITE]
)
async def test_create_scope_check_precedes_even_malformed_body(missing: Scope) -> None:
    api, old, service = application(SCOPES - {missing})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            "/api/v2/report-jobs",
            params={"profile": PROFILE},
            content=b"private-invalid-json",
            headers=_headers(**{"Content-Type": "application/json"}),
        )
    assert response.status_code == 403 and "private-invalid-json" not in response.text
    assert not service.mock_calls and not any(item.mock_calls for item in old)


async def test_modeled_projection_admission_does_not_invent_a_history_scope() -> None:
    api, _, service = application(SCOPES - {Scope.ACTIVITY_READ})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            "/api/v2/report-jobs", params={"profile": PROFILE}, json=body_v4(), headers=_headers()
        )
    assert response.status_code == 202
    service.generate_report.assert_awaited_once()


@pytest.mark.parametrize("method,path,operation", OPERATIONS)
async def test_current_source_denial_wins_over_conditional_and_artifact_headers(
    method: str, path: str, operation: str
) -> None:
    api, old, service = application()
    getattr(service, operation).side_effect = app.ReportServiceError(
        app.ReportServiceErrorCode.NOT_FOUND, "private-source-canary"
    )
    params = {"profile": PROFILE}
    if operation != "generate_report":
        params["account_id"] = ACCOUNT
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.request(
            method,
            path,
            params=params,
            json=body_v4() if operation == "generate_report" else {},
            headers=_headers(**{"If-None-Match": "*", "X-Artifact-Grant": "a" * 43}),
        )
    assert response.status_code == 404 and "private-source-canary" not in response.text
    assert "etag" not in response.headers and "x-artifact-sha256" not in response.headers
    getattr(service, operation).assert_awaited_once()
    assert not any(item.mock_calls for item in old)


@pytest.mark.parametrize("method,path,operation", OPERATIONS)
async def test_duplicate_four_selector_fails_before_every_service(
    method: str, path: str, operation: str
) -> None:
    api, old, service = application()
    params = [("profile", PROFILE), ("profile", PROFILE)]
    if operation != "generate_report":
        params.append(("account_id", ACCOUNT))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.request(
            method,
            path,
            params=httpx.QueryParams(tuple(params)),
            json=body_v4() if operation == "generate_report" else {},
            headers=_headers(**{"X-Artifact-Grant": "a" * 43}),
        )
    assert response.status_code == 422
    assert not service.mock_calls and not any(item.mock_calls for item in old)


async def test_manifest_serializes_original_null_clocks_and_authorizes_before_304() -> None:
    api, old, service = application()
    service.get_report_manifest.return_value = manifest_v4()
    params = {"account_id": ACCOUNT, "profile": PROFILE}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        first = await client.get(f"/api/v2/reports/{JOB}", params=params, headers=_headers())
        assert first.status_code == 200
        second = await client.get(
            f"/api/v2/reports/{JOB}",
            params=params,
            headers=_headers(**{"If-None-Match": first.headers["etag"]}),
        )
    assert second.status_code == 304 and not second.content
    assert service.get_report_manifest.await_count == 2
    assert first.json()["document"]["document_schema_version"] == "4.0.0"
    assert any(
        item["family"] == "projection" and item["source_cutoff_at"] is None
        for item in first.json()["contexts"]
    )
    assert not any(item.mock_calls for item in old)
