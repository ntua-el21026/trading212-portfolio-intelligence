"""Explicit profile routing precedes service calls, private payloads and conditionals."""

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from trading212_api import premium_report_schemas
from trading212_application import reports as app
from trading212_domain import report_v3 as v3
from trading212_domain.report_manifest import build_report_manifest, encode_report_manifest
from trading212_security.principals import Scope

from tests.unit.api.report_factories import ACCOUNT, ARTIFACT, BODY, JOB, artifact
from tests.unit.api.test_premium_report_routes import application as application_v2
from tests.unit.api.test_premium_report_schemas import RISK, selection, status
from tests.unit.api.test_report_routes import ORIGIN, SCOPES, _headers
from tests.unit.domain.report_v3_factories import capture_v3

pytestmark = pytest.mark.unit
PROFILE = "report_sections_v3"


def body_v3(*, risk: bool = False) -> dict[str, Any]:
    return {
        **BODY,
        "profile_version": PROFILE,
        "premium_run": {"run_id": RISK, "family": "risk" if risk else "scenario"},
        "sections": [*BODY["sections"], "risk" if risk else "scenario"],
    }


def status_v3() -> dict[str, Any]:
    value = status()
    value["context"].update(profile_version=PROFILE, schema_version="3.0.0")
    return value


def application(
    scopes: frozenset[Scope] = SCOPES,
) -> tuple[FastAPI, AsyncMock, AsyncMock, AsyncMock]:
    api, legacy, premium = application_v2(scopes)
    newest = AsyncMock(spec=app.ReportService)
    newest.generate_report.return_value = status_v3()
    newest.get_report_status.return_value = status_v3()
    newest.list_reports.return_value = {
        "items": [status_v3()],
        "next_cursor": None,
        "limit": 25,
        "total": 1,
    }
    newest.get_report_manifest.return_value = build_report_manifest(capture_v3())
    newest.create_report_download_grant.return_value = {
        "artifact_id": ARTIFACT,
        "token": "a" * 43,
        "expires_at": "2026-09-07T12:05:00Z",
    }
    newest.download_report_artifact.return_value = artifact()
    api.state.context.premium_report_v3_service = newest
    return api, legacy, premium, newest


@pytest.mark.parametrize("risk", [False, True])
async def test_explicit_v3_creates_the_actual_typed_run_pin_only(risk: bool) -> None:
    api, legacy, premium, newest = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            "/api/v2/report-jobs",
            params={"profile": PROFILE},
            json=body_v3(risk=risk),
            headers=_headers(),
        )
    assert response.status_code == 202
    assert response.json()["profile_version"] == PROFILE
    newest.generate_report.assert_awaited_once()
    command = newest.generate_report.await_args.args[1]
    assert isinstance(command.selection, v3.ReportSelectionV3)
    assert isinstance(
        command.selection.premium_run,
        v3.ReportRiskRunSelection if risk else v3.ReportScenarioRunSelection,
    )
    assert command.selection.premium_run.run_id == UUID(RISK)
    assert not hasattr(command.selection, "risk_run_id")
    assert command.idempotency_key == "report:one" and command.ttl_days == 7
    assert not legacy.mock_calls and not premium.mock_calls


async def test_omitted_and_explicit_profile2_preserve_response_bytes_and_command_identity() -> None:
    api, legacy, premium, newest = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        omitted = await client.post("/api/v2/report-jobs", json=selection(), headers=_headers())
        explicit = await client.post(
            "/api/v2/report-jobs",
            params={"profile": "report_sections_v2"},
            json=selection(),
            headers=_headers(),
        )
    assert omitted.status_code == explicit.status_code == 202
    assert omitted.content == explicit.content
    assert "profile_version" not in omitted.json()
    assert premium.generate_report.await_args_list[0] == premium.generate_report.await_args_list[1]
    assert not legacy.mock_calls and not newest.mock_calls


@pytest.mark.parametrize(
    "params,body",
    [
        ({}, body_v3()),
        ({"profile": "report_sections_v2"}, body_v3()),
        ({"profile": PROFILE}, selection()),
        ({"profile": PROFILE}, {**body_v3(), "private-field-canary": "private-value-canary"}),
    ],
)
async def test_body_profile_mismatch_never_reaches_any_service(
    params: dict[str, str],
    body: dict[str, Any],
) -> None:
    api, legacy, premium, newest = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            "/api/v2/report-jobs",
            params=httpx.QueryParams(params),
            json=body,
            headers=_headers(),
        )
    assert response.status_code == 422
    assert (
        "private-field-canary" not in response.text and "private-value-canary" not in response.text
    )
    assert not legacy.mock_calls and not premium.mock_calls and not newest.mock_calls


OPERATIONS = (
    ("POST", "/api/v2/report-jobs", "generate_report"),
    ("GET", f"/api/v2/report-jobs/{JOB}", "get_report_status"),
    ("GET", "/api/v2/reports", "list_reports"),
    ("GET", f"/api/v2/reports/{JOB}", "get_report_manifest"),
    ("POST", f"/api/v2/reports/{JOB}/artifacts/{ARTIFACT}/grants", "create_report_download_grant"),
    ("GET", f"/api/v2/reports/{JOB}/artifacts/{ARTIFACT}/content", "download_report_artifact"),
)


@pytest.mark.parametrize("method,path,operation", OPERATIONS)
@pytest.mark.parametrize(
    "selectors",
    [
        [("profile", "private-profile-canary")],
        [("profile", PROFILE), ("profile", PROFILE)],
        [("profile", "report_sections_v2"), ("profile", PROFILE)],
    ],
)
async def test_unknown_or_duplicate_profile_rejects_every_operation_before_service(
    method: str,
    path: str,
    operation: str,
    selectors: list[tuple[str, str]],
) -> None:
    api, legacy, premium, newest = application()
    params = selectors if operation == "generate_report" else [("account_id", ACCOUNT), *selectors]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.request(
            method,
            path,
            params=httpx.QueryParams(tuple(params)),
            json=body_v3() if operation == "generate_report" else {},
            headers=_headers(**{"X-Artifact-Grant": "a" * 43, "If-None-Match": "*"}),
        )
    assert response.status_code == 422 and "private-profile-canary" not in response.text
    assert not legacy.mock_calls and not premium.mock_calls and not newest.mock_calls


@pytest.mark.parametrize("method,path,operation", OPERATIONS)
async def test_wrong_profile_id_denial_from_authorized_service_precedes_all_private_results(
    method: str,
    path: str,
    operation: str,
) -> None:
    api, legacy, premium, newest = application()
    getattr(newest, operation).side_effect = app.ReportServiceError(
        app.ReportServiceErrorCode.NOT_FOUND,
        "private-failure-canary",
    )
    params = {"profile": PROFILE}
    if operation != "generate_report":
        params["account_id"] = ACCOUNT
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.request(
            method,
            path,
            params=httpx.QueryParams(params),
            json=body_v3() if operation == "generate_report" else {},
            headers=_headers(**{"X-Artifact-Grant": "a" * 43, "If-None-Match": "*"}),
        )
    assert response.status_code == 404 and "private-failure-canary" not in response.text
    assert "etag" not in response.headers and "x-artifact-sha256" not in response.headers
    getattr(newest, operation).assert_awaited_once()
    assert not legacy.mock_calls and not premium.mock_calls


async def test_v3_list_status_manifest_grant_and_content_use_one_selected_service() -> None:
    api, legacy, premium, newest = application()
    params = {"account_id": ACCOUNT, "profile": PROFILE}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        page = await client.get("/api/v2/reports", params=params, headers=_headers())
        state = await client.get(f"/api/v2/report-jobs/{JOB}", params=params, headers=_headers())
        manifest = await client.get(f"/api/v2/reports/{JOB}", params=params, headers=_headers())
        grant = await client.post(
            f"/api/v2/reports/{JOB}/artifacts/{ARTIFACT}/grants",
            params=httpx.QueryParams(params),
            json={},
            headers=_headers(),
        )
        content = await client.get(
            f"/api/v2/reports/{JOB}/artifacts/{ARTIFACT}/content",
            params=httpx.QueryParams(params),
            headers=_headers(**{"X-Artifact-Grant": grant.json()["token"]}),
        )
    assert (
        page.status_code == state.status_code == manifest.status_code == content.status_code == 200
    )
    assert page.json()["profile_version"] == page.json()["items"][0]["profile_version"] == PROFILE
    assert state.json()["profile_version"] == PROFILE
    assert manifest.content == encode_report_manifest(newest.get_report_manifest.return_value)
    assert "profile_version" not in manifest.json()  # Canonical semantic envelope is unchanged.
    assert grant.status_code == 201 and content.content == artifact().content
    assert content.headers["x-artifact-sha256"] == artifact().metadata.content_digest
    assert not legacy.mock_calls and not premium.mock_calls


async def test_empty_page_and_expired_status_keep_explicit_v3_marker_without_context() -> None:
    api, _, _, newest = application()
    newest.list_reports.return_value = {"items": [], "next_cursor": None, "limit": 25, "total": 0}
    newest.get_report_status.return_value = {**status_v3(), "state": "expired", "context": None}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        page = await client.get(
            "/api/v2/reports",
            params={"account_id": ACCOUNT, "profile": PROFILE},
            headers=_headers(),
        )
        state = await client.get(
            f"/api/v2/report-jobs/{JOB}",
            params={"account_id": ACCOUNT, "profile": PROFILE},
            headers=_headers(),
        )
    assert page.status_code == state.status_code == 200
    assert page.json()["profile_version"] == state.json()["profile_version"] == PROFILE
    assert page.json()["items"] == [] and state.json()["context"] is None


async def test_v3_validation_and_full_envelope_bound_precede_conditional_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, _, _, newest = application()
    path = f"/api/v2/report-jobs/{JOB}"
    params = {"account_id": ACCOUNT, "profile": PROFILE}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        valid = await client.get(path, params=params, headers=_headers())
        assert valid.status_code == 200
        repeated = await client.get(
            path,
            params=httpx.QueryParams(params),
            headers=_headers(**{"If-None-Match": valid.headers["etag"]}),
        )
        assert repeated.status_code == 304
        newest.get_report_status.return_value = status()
        mismatch = await client.get(path, params=params, headers=_headers(**{"If-None-Match": "*"}))
        assert mismatch.status_code == 500
        newest.get_report_status.return_value = status_v3()
        monkeypatch.setattr(premium_report_schemas, "MAX_REPORT_JSON_BYTES", len(valid.content) - 1)
        oversized = await client.get(
            path, params=params, headers=_headers(**{"If-None-Match": "*"})
        )
        assert (
            oversized.status_code == 422 and oversized.json()["error"]["code"] == "RESULT_TOO_LARGE"
        )


async def test_hypothetical_v3_scope_is_conditional_while_risk_keeps_activity_scope() -> None:
    api, legacy, premium, newest = application(SCOPES - {Scope.ACTIVITY_READ})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        hypothetical = await client.post(
            "/api/v2/report-jobs",
            params={"profile": PROFILE},
            json=body_v3(),
            headers=_headers(),
        )
        risk = await client.post(
            "/api/v2/report-jobs",
            params={"profile": PROFILE},
            json=body_v3(risk=True),
            headers=_headers(),
        )
    assert hypothetical.status_code == 202 and risk.status_code == 403
    newest.generate_report.assert_awaited_once()
    assert not legacy.mock_calls and not premium.mock_calls


@pytest.mark.parametrize(
    "missing", [Scope.PORTFOLIO_READ, Scope.REPORTS_WRITE, Scope.ANALYTICS_READ]
)
async def test_v3_base_scopes_precede_malformed_body(missing: Scope) -> None:
    api, legacy, premium, newest = application(SCOPES - {missing})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            "/api/v2/report-jobs",
            params={"profile": PROFILE},
            content=b"{",
            headers=_headers(),
        )
    assert response.status_code == 403
    assert not legacy.mock_calls and not premium.mock_calls and not newest.mock_calls


async def test_unavailable_profile3_never_falls_back_to_prior_profiles() -> None:
    api, legacy, premium, newest = application()
    api.state.context.premium_report_v3_service = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            "/api/v2/report-jobs",
            params={"profile": PROFILE},
            json=body_v3(),
            headers=_headers(),
        )
    assert response.status_code == 503
    assert not legacy.mock_calls and not premium.mock_calls and not newest.mock_calls


async def test_v3_csrf_precedes_body_parsing_and_request_limits_remain_unchanged() -> None:
    api, legacy, premium, newest = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        anonymous = await client.post(
            "/api/v2/report-jobs", params={"profile": PROFILE}, content=b"{"
        )
        assert anonymous.status_code == 401
        await client.post("/api/v1/auth/local-session")
        for path, params in (
            ("/api/v2/report-jobs", {"profile": PROFILE}),
            (
                f"/api/v2/reports/{JOB}/artifacts/{ARTIFACT}/grants",
                {"account_id": ACCOUNT, "profile": PROFILE},
            ),
        ):
            csrf = await client.post(
                path, params=params, content=b"{", headers={"Content-Type": "application/json"}
            )
            assert csrf.status_code == 401
        oversized = await client.post(
            "/api/v2/report-jobs",
            params={"profile": PROFILE},
            content=b" " * (65536 + 1),
            headers=_headers(),
        )
        assert oversized.status_code == 413
        unknown_query = await client.post(
            "/api/v2/report-jobs",
            params={"profile": PROFILE, "private-query-canary": "unused"},
            json=body_v3(),
            headers=_headers(),
        )
        assert unknown_query.status_code == 422 and "private-query-canary" not in unknown_query.text
    assert not legacy.mock_calls and not premium.mock_calls and not newest.mock_calls
