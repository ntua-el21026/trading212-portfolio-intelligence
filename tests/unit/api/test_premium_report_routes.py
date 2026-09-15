"""Separate V2 composition, authorization before parsing and bounded private responses."""

from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from trading212_api import premium_report_schemas
from trading212_api.main import create_app
from trading212_application import reports as app
from trading212_application.services import SyntheticPortfolioService
from trading212_security.principals import Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

from tests.unit.api.report_factories import ACCOUNT, ARTIFACT, BODY, JOB, NOW, artifact, job
from tests.unit.api.test_premium_report_schemas import RISK, selection, status
from tests.unit.api.test_report_routes import ORIGIN, SCOPES, _Bearer, _headers

pytestmark = pytest.mark.unit


def application(scopes: frozenset[Scope] = SCOPES) -> tuple[FastAPI, AsyncMock, AsyncMock]:
    legacy = AsyncMock(spec=app.ReportService)
    legacy.generate_report.return_value = job()
    legacy.get_report_status.return_value = job()
    premium = AsyncMock(spec=app.ReportService)
    premium.generate_report.return_value = status()
    premium.get_report_status.return_value = status()
    premium.list_reports.return_value = {
        "items": [status()],
        "next_cursor": None,
        "limit": 25,
        "total": 1,
    }
    premium.download_report_artifact.return_value = artifact()
    api = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
            allowed_hosts=("testserver",),
            allowed_origins=(ORIGIN,),
        ),
        service=SyntheticPortfolioService(clock=lambda: NOW),
        report_service=cast(app.ReportService, legacy),
        premium_report_service=cast(app.ReportService, premium),
        bearer_authenticator=_Bearer(scopes),
        clock=lambda: NOW,
    )
    return api, legacy, premium


def test_exact_six_routes_have_unique_models_and_both_auth_mechanisms() -> None:
    api, _, _ = application()
    schema = api.openapi()
    expected = {
        ("post", "/api/v2/report-jobs", "generate_premium_portfolio_report"),
        ("get", "/api/v2/report-jobs/{job_id}", "get_premium_report_status"),
        ("get", "/api/v2/reports", "list_premium_reports"),
        ("get", "/api/v2/reports/{report_id}", "get_premium_report_manifest"),
        (
            "post",
            "/api/v2/reports/{report_id}/artifacts/{artifact_id}/grants",
            "create_premium_report_download_grant",
        ),
        (
            "get",
            "/api/v2/reports/{report_id}/artifacts/{artifact_id}/content",
            "download_premium_report_artifact",
        ),
    }
    actual = {
        (method, path, value["operationId"])
        for path, methods in schema["paths"].items()
        for method, value in methods.items()
        if "premium-reports" in value.get("tags", [])
    }
    assert actual == expected
    for method, path, _ in actual:
        assert schema["paths"][path][method]["security"] == [
            {"bearerAuth": []},
            {"sessionCookie": []},
        ]
    definitions = schema["components"]["schemas"]
    assert {"ReportJobStatus", "ReportManifest", "GenerateReportRequest"}.issubset(definitions)
    assert {
        "PremiumReportJobStatus",
        "PremiumReportManifest",
        "GeneratePremiumReportRequest",
    }.issubset(definitions)
    assert "risk_run_id" not in definitions["GenerateReportRequest"]["properties"]


async def test_each_version_dispatches_only_to_its_injected_service() -> None:
    api, legacy, premium = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        old = await client.post("/api/v1/report-jobs", json=BODY, headers=_headers())
        new = await client.post("/api/v2/report-jobs", json=selection(), headers=_headers())
        replay = await client.post("/api/v2/report-jobs", json=selection(), headers=_headers())
        page = await client.get(
            "/api/v2/reports", params={"account_id": ACCOUNT}, headers=_headers()
        )
    assert old.status_code == new.status_code == replay.status_code == 202
    assert old.json()["context"]["profile_version"] == "report_sections_v1"
    assert new.json() == replay.json()
    assert new.json()["context"]["profile_version"] == "report_sections_v2"
    assert legacy.generate_report.await_count == 1 and premium.generate_report.await_count == 2
    command = premium.generate_report.await_args_list[0].args[1]
    assert command.selection.risk_run_id == UUID(RISK)
    assert command.idempotency_key == "report:one" and command.ttl_days == 7
    assert premium.generate_report.await_args_list[0] == premium.generate_report.await_args_list[1]
    assert page.status_code == 200 and page.json()["total"] == 1
    legacy.list_reports.assert_not_called()


@pytest.mark.parametrize(
    "missing",
    [Scope.PORTFOLIO_READ, Scope.REPORTS_WRITE, Scope.ANALYTICS_READ, Scope.ACTIVITY_READ],
)
async def test_premium_creation_scopes_precede_even_malformed_json(missing: Scope) -> None:
    api, _, premium = application(SCOPES - {missing})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            "/api/v2/report-jobs",
            content=b"{",
            headers=_headers(**{"Content-Type": "application/json"}),
        )
    assert response.status_code == 403
    assert not premium.mock_calls


async def test_authentication_and_csrf_precede_parsing_on_creation_and_grants() -> None:
    api, _, premium = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post("/api/v2/report-jobs", content=b"{")
        assert response.status_code == 401
        await client.post("/api/v1/auth/local-session")
        for path in (
            "/api/v2/report-jobs",
            f"/api/v2/reports/{JOB}/artifacts/{ARTIFACT}/grants",
        ):
            response = await client.post(
                path, content=b"{", headers={"Content-Type": "application/json"}
            )
            assert response.status_code == 401
    assert not premium.mock_calls


async def test_read_scope_precedes_conditional_status_and_query_validation() -> None:
    api, _, premium = application(SCOPES - {Scope.REPORTS_READ})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.get(
            "/api/v2/report-jobs/invalid",
            params={"account_id": "invalid"},
            headers=_headers(**{"If-None-Match": "*"}),
        )
    assert response.status_code == 403 and not premium.mock_calls


async def test_request_bytes_duplicate_headers_and_private_unknown_fields_fail_closed() -> None:
    api, _, premium = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        oversized = await client.post(
            "/api/v2/report-jobs", content=b" " * (65536 + 1), headers=_headers()
        )
        assert oversized.status_code == 413
        repeated = await client.post(
            "/api/v2/report-jobs",
            json=selection(),
            headers=[*_headers().items(), ("X-Idempotency-Key", "other")],
        )
        assert repeated.status_code == 422
        for body in (BODY, {**selection(), "private-field-canary": "private-value-canary"}):
            denied = await client.post("/api/v2/report-jobs", json=body, headers=_headers())
            assert denied.status_code == 422
            assert (
                "private-field-canary" not in denied.text
                and "private-value-canary" not in denied.text
            )
    assert not premium.mock_calls


async def test_full_v2_dto_and_byte_validation_precede_not_modified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, _, premium = application()
    path = f"/api/v2/report-jobs/{JOB}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        success = await client.get(path, params={"account_id": ACCOUNT}, headers=_headers())
        assert success.status_code == 200
        unchanged = await client.get(
            path,
            params={"account_id": ACCOUNT},
            headers=_headers(**{"If-None-Match": success.headers["etag"]}),
        )
        assert unchanged.status_code == 304 and not unchanged.content
        premium.get_report_status.return_value = job()
        wrong_version = await client.get(
            path, params={"account_id": ACCOUNT}, headers=_headers(**{"If-None-Match": "*"})
        )
        assert wrong_version.status_code == 500
        premium.get_report_status.return_value = status()
        monkeypatch.setattr(premium_report_schemas, "MAX_REPORT_JSON_BYTES", 100)
        oversized = await client.get(
            path, params={"account_id": ACCOUNT}, headers=_headers(**{"If-None-Match": "*"})
        )
        assert (
            oversized.status_code == 422 and oversized.json()["error"]["code"] == "RESULT_TOO_LARGE"
        )


async def test_ephemeral_grant_and_verified_binary_use_v2_service_only() -> None:
    api, legacy, premium = application()
    premium.create_report_download_grant.return_value = {
        "artifact_id": ARTIFACT,
        "token": "a" * 43,
        "expires_at": "2026-09-07T12:05:00Z",
    }
    path = f"/api/v2/reports/{JOB}/artifacts/{ARTIFACT}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        granted = await client.post(
            path + "/grants",
            params={"account_id": ACCOUNT},
            json={},
            headers={"Authorization": _headers()["Authorization"]},
        )
        assert granted.status_code == 201
        response = await client.get(
            path + "/content",
            params={"account_id": ACCOUNT},
            headers=_headers(**{"X-Artifact-Grant": "a" * 43}),
        )
    assert response.status_code == 200 and response.content == artifact().content
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-artifact-sha256"] == artifact().metadata.content_digest
    assert "a" * 43 not in str(response.headers)
    legacy.download_report_artifact.assert_not_called()


async def test_unavailable_v2_service_never_falls_back_to_v1() -> None:
    api, legacy, premium = application()
    api.state.context.premium_report_service = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post("/api/v2/report-jobs", json=selection(), headers=_headers())
    assert response.status_code == 503
    assert not legacy.mock_calls and not premium.mock_calls
