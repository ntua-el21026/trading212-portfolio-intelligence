"""Authorization, bounded commands and private artifact transport regression cases."""

from dataclasses import replace
from datetime import timedelta
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from trading212_api.main import create_app
from trading212_application import reports as app
from trading212_application.services import SyntheticPortfolioService
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID

from tests.unit.api.report_factories import ACCOUNT, ARTIFACT, BODY, JOB, NOW, artifact, job

ORIGIN = "https://testserver"
SCOPES = frozenset(
    {
        Scope.PORTFOLIO_READ,
        Scope.REPORTS_READ,
        Scope.REPORTS_WRITE,
        Scope.ANALYTICS_READ,
        Scope.ACTIVITY_READ,
        Scope.TARGETS_READ,
    }
)


class _Bearer:
    def __init__(self, scopes: frozenset[Scope]) -> None:
        self.scopes = scopes

    async def authenticate(self, token: str) -> Principal:
        assert token == "synthetic-report-test"
        return Principal(
            "report-test",
            LOCAL_SYNTHETIC_OWNER_ID,
            "report-test",
            "report-test",
            self.scopes,
            NOW,
            NOW + timedelta(hours=1),
        )


def _app(scopes: frozenset[Scope] = SCOPES) -> tuple[FastAPI, AsyncMock]:
    service = AsyncMock(spec=app.ReportService)
    service.generate_report.return_value = job()
    service.get_report_status.return_value = job()
    service.download_report_artifact.return_value = artifact()
    service.create_report_download_grant.return_value = app.ArtifactGrant(
        artifact_id=UUID(ARTIFACT),
        token="a" * 43,
        expires_at=NOW + timedelta(minutes=5),
    )
    application = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
            allowed_hosts=("testserver",),
            allowed_origins=(ORIGIN,),
        ),
        service=SyntheticPortfolioService(clock=lambda: NOW),
        report_service=cast(app.ReportService, service),
        bearer_authenticator=_Bearer(scopes),
        clock=lambda: NOW,
    )
    return application, service


def _headers(**extra: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer synthetic-report-test",
        "X-Idempotency-Key": "report:one",
        **extra,
    }


@pytest.mark.parametrize(
    "missing", [Scope.PORTFOLIO_READ, Scope.REPORTS_WRITE, Scope.ANALYTICS_READ]
)
async def test_creation_scopes_fail_before_service(missing: Scope) -> None:
    application, service = _app(SCOPES - {missing})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        response = await client.post("/api/v1/report-jobs", json=BODY, headers=_headers())
    assert response.status_code == 403
    service.generate_report.assert_not_awaited()


async def test_safe_status_requires_read_scope_even_with_write_and_conditional_validator() -> None:
    application, service = _app(SCOPES - {Scope.REPORTS_READ})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        response = await client.get(
            f"/api/v1/report-jobs/{JOB}",
            params={"account_id": ACCOUNT},
            headers=_headers(**{"If-None-Match": "*"}),
        )
    assert response.status_code == 403
    service.get_report_status.assert_not_awaited()


async def test_exact_retry_command_identity_and_queued_input_pins_are_preserved() -> None:
    application, service = _app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        responses = [
            await client.post("/api/v1/report-jobs", json=BODY, headers=_headers())
            for _ in range(2)
        ]
    assert responses[0].status_code == responses[1].status_code == 202
    assert responses[0].json() == responses[1].json()
    assert responses[0].json()["context"]["input_digest"] == "a" * 64
    assert service.generate_report.await_args_list[0] == service.generate_report.await_args_list[1]


async def test_csrf_is_required_for_ephemeral_grants_without_business_idempotency() -> None:
    application, service = _app()
    path = f"/api/v1/reports/{JOB}/artifacts/{ARTIFACT}/grants"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        session = await client.post("/api/v1/auth/local-session")
        csrf = session.json()["csrf_token"]
        for headers in (
            {},
            {"Origin": ORIGIN},
            {"X-CSRF-Token": csrf},
            {"Origin": "https://foreign.invalid", "X-CSRF-Token": csrf},
        ):
            response = await client.post(
                path, params={"account_id": ACCOUNT}, json={}, headers=headers
            )
            assert response.status_code == 401
        service.create_report_download_grant.assert_not_awaited()
        response = await client.post(
            path,
            params={"account_id": ACCOUNT},
            json={},
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
    assert response.status_code == 201
    assert set(response.json()) == {"artifact_id", "token", "expires_at"}
    assert response.headers["cache-control"] == "private, no-store"


async def test_binary_above_json_bound_is_verified_and_expired_grant_rechecked() -> None:
    application, service = _app()
    data = b" " * (2 * 1024 * 1024) + b"{}"
    service.download_report_artifact.return_value = artifact(data)
    path = f"/api/v1/reports/{JOB}/artifacts/{ARTIFACT}/content"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        response = await client.get(
            path, params={"account_id": ACCOUNT}, headers=_headers(**{"X-Artifact-Grant": "a" * 43})
        )
        assert response.status_code == 200 and response.content == data
        assert response.headers["content-length"] == str(len(data))
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "a" * 43 not in str(response.headers)
        service.download_report_artifact.side_effect = app.ReportServiceError(
            app.ReportServiceErrorCode.ARTIFACT_EXPIRED, "private-cause-canary"
        )
        denied = await client.get(
            path,
            params={"account_id": ACCOUNT},
            headers=_headers(**{"X-Artifact-Grant": "a" * 43, "If-None-Match": "*"}),
        )
    assert denied.status_code == 410 and denied.json()["error"]["code"] == "ARTIFACT_EXPIRED"
    assert "private-cause-canary" not in denied.text


async def test_query_grants_and_unknown_body_fields_cannot_dispatch() -> None:
    application, service = _app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        denied = await client.get(
            f"/api/v1/reports/{JOB}/artifacts/{ARTIFACT}/content",
            params={"account_id": ACCOUNT, "token": "secret-canary"},
            headers=_headers(),
        )
        assert denied.status_code == 422 and "secret-canary" not in denied.text
        denied = await client.post(
            "/api/v1/report-jobs",
            json={**BODY, "private-canary": "private-value"},
            headers=_headers(),
        )
        assert denied.status_code == 422 and "private-value" not in denied.text
    service.download_report_artifact.assert_not_awaited()
    service.generate_report.assert_not_awaited()


async def test_invalid_status_precedes_304_and_invalid_digest_precedes_bytes() -> None:
    application, service = _app()
    service.get_report_status.return_value = {"state": "succeeded"}
    download = artifact()
    service.download_report_artifact.return_value = replace(
        download, metadata=replace(download.metadata, content_digest="e" * 64)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        status = await client.get(
            f"/api/v1/report-jobs/{JOB}",
            params={"account_id": ACCOUNT},
            headers=_headers(**{"If-None-Match": "*"}),
        )
        content = await client.get(
            f"/api/v1/reports/{JOB}/artifacts/{ARTIFACT}/content",
            params={"account_id": ACCOUNT},
            headers=_headers(**{"X-Artifact-Grant": "a" * 43}),
        )
    assert status.status_code == content.status_code == 500
    assert download.content not in content.content


async def test_unsupported_alerts_export_fails_before_durable_service() -> None:
    application, service = _app()
    body = {
        key: value
        for key, value in BODY.items()
        if key not in {"report_type", "sections", "formats"}
    }
    body.update(dataset="alerts", field_set="standard", format="json")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        response = await client.post("/api/v1/exports", json=body, headers=_headers())
    assert response.status_code == 422
    service.create_export.assert_not_awaited()


@pytest.mark.parametrize(
    ("operation", "error_code", "wire_code", "status_code", "retryable"),
    [
        (
            "generate_report",
            app.ReportServiceErrorCode.CONFLICT,
            "IDEMPOTENCY_KEY_REUSED",
            409,
            False,
        ),
        (
            "get_report_manifest",
            app.ReportServiceErrorCode.INVALID_STATE_TRANSITION,
            "INVALID_STATE_TRANSITION",
            409,
            False,
        ),
        (
            "create_report_download_grant",
            app.ReportServiceErrorCode.INVALID_STATE_TRANSITION,
            "INVALID_STATE_TRANSITION",
            409,
            False,
        ),
        (
            "create_report_download_grant",
            app.ReportServiceErrorCode.RATE_LIMITED,
            "RATE_LIMITED",
            429,
            True,
        ),
    ],
)
async def test_lifecycle_rate_and_idempotency_failures_have_distinct_safe_responses(
    operation: str,
    error_code: app.ReportServiceErrorCode,
    wire_code: str,
    status_code: int,
    retryable: bool,
) -> None:
    application, service = _app()
    getattr(service, operation).side_effect = app.ReportServiceError(
        error_code, "private-report-state-canary", retryable=retryable
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        if operation == "generate_report":
            response = await client.post("/api/v1/report-jobs", json=BODY, headers=_headers())
        elif operation == "get_report_manifest":
            response = await client.get(
                f"/api/v1/reports/{JOB}",
                params={"account_id": ACCOUNT},
                headers=_headers(**{"If-None-Match": "*"}),
            )
        else:
            response = await client.post(
                f"/api/v1/reports/{JOB}/artifacts/{ARTIFACT}/grants",
                params={"account_id": ACCOUNT},
                json={},
                headers=_headers(),
            )
    assert response.status_code == status_code
    assert response.json()["error"]["code"] == wire_code
    assert response.json()["error"]["retryable"] is retryable
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers.get("retry-after") == ("300" if wire_code == "RATE_LIMITED" else None)
    assert "private-report-state-canary" not in response.text
    if wire_code != "IDEMPOTENCY_KEY_REUSED":
        assert "idempotency" not in response.json()["error"]["message"]
