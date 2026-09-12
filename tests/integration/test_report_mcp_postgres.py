"""Real retained report commands through MCP, including retry across the HTTP API.

These fixtures use the canonical ingestion seed and durable PostgreSQL stores.
The transport trap is armed before command execution and blocks all HTTP egress.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult
from sqlalchemy import func, select
from starlette.testclient import TestClient
from trading212_api.main import create_app as create_api_app
from trading212_mcp.auth import PrincipalResolver
from trading212_mcp.schemas import RESULT_MODELS
from trading212_mcp.server import create_runtime
from trading212_persistence import PostgresPortfolioService
from trading212_persistence.models import AuditEventModel
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_persistence.report_models import (
    ApplicationCommandIdentityModel,
    ArtifactDownloadGrantModel,
    ReportArtifactModel,
    ReportDispatchOutboxModel,
    ReportInputSnapshotModel,
    ReportJobModel,
    ReportManifestModel,
)
from trading212_persistence.report_service import PostgresReportService
from trading212_security.principals import AuthenticationError, Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_worker.report_tasks import ReportExecutionState, execute_report_message
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.test_report_postgres import ReportCase
from tests.integration.test_report_postgres import report_case as report_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def _settings() -> SecuritySettings:
    return SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=True,
        allowed_hosts=("localhost", "testserver"),
    )


def _arguments(case: ReportCase) -> dict[str, Any]:
    selection = case.selection()
    return {
        "account_id": str(case.account_id),
        "snapshot_id": str(selection.snapshot_id),
        "start_date": selection.start_date.isoformat(),
        "end_date": selection.end_date.isoformat(),
        "source_cutoff_at": selection.source_cutoff_at.isoformat(),
        "reporting_currency": "EUR",
        "report_type": "portfolio_summary",
        "format": "json",
        "sections": ["overview", "allocation", "quality"],
        "idempotency_key": "p209:durable:report",
    }


async def _call(
    server: MCPServer[Any],
    name: str,
    arguments: dict[str, Any],
) -> CallToolResult:
    result = await server.call_tool(name, arguments)
    assert isinstance(result, CallToolResult) and result.structured_content is not None
    RESULT_MODELS[name].model_validate(result.structured_content)
    assert result.is_error == (result.structured_content["error"] is not None)
    return result


def _data(result: CallToolResult) -> dict[str, Any]:
    assert not result.is_error and result.structured_content is not None
    value = result.structured_content["data"]
    assert isinstance(value, dict)
    return value


class _Bearer:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    async def authenticate(self, token: str) -> Principal:
        if token != "synthetic-p209-report":
            raise AuthenticationError("Invalid test credential.")
        return self.principal


def test_report_mcp_concurrent_retry_restart_api_parity_and_current_authorization(
    report_case: ReportCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = report_case
    selected = case.principal
    phase = "probe"
    attempts = {"probe": 0, "command": 0}

    async def forbid_network(
        _transport: httpx.AsyncHTTPTransport,
        _request: httpx.Request,
    ) -> httpx.Response:
        attempts[phase] += 1
        raise AssertionError("Outbound HTTP is forbidden by the registry test.")

    async def resolve(_resolver: PrincipalResolver) -> Principal:
        return selected

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbid_network)
    monkeypatch.setattr(PrincipalResolver, "resolve", resolve)

    async def run() -> None:
        nonlocal phase, selected
        # Positive control proves the spy intercepts HTTP before any socket is opened.
        async with httpx.AsyncClient(trust_env=False) as probe:
            with pytest.raises(AssertionError, match="Outbound HTTP is forbidden"):
                await probe.get("https://registry-network-probe.invalid/")
        assert attempts["probe"] == 1
        phase = "command"
        server = create_runtime(
            security_settings=_settings(),
            report_service=case.service,
        ).server
        args = _arguments(case)
        left, right = await asyncio.gather(
            _call(server, "generate_portfolio_report", args),
            _call(server, "generate_portfolio_report", dict(args)),
        )
        queued = _data(left)
        assert _data(right) == queued
        assert queued["state"] == "queued" and queued["artifacts"] == []
        assert queued["manifest_digest"] is None and queued["report_id"] is None
        job_id = UUID(queued["job_id"])
        with case.base.sessions() as session:
            row = session.get(ReportJobModel, job_id)
            assert row is not None
            input_id, input_digest = row.input_id, row.input_digest
            assert queued["context"]["input_digest"] == input_digest
            assert queued["context"]["snapshot_id"] == args["snapshot_id"]
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ApplicationCommandIdentityModel)
                    .where(ApplicationCommandIdentityModel.report_job_id == job_id)
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ReportDispatchOutboxModel)
                    .where(ReportDispatchOutboxModel.job_id == job_id)
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ReportInputSnapshotModel)
                    .where(ReportInputSnapshotModel.id == input_id)
                )
                == 1
            )

        fresh = PostgresReportService(case.base.sessions, cursor_signing_key=XRAY_CURSOR_KEY)
        restarted = create_runtime(security_settings=_settings(), report_service=fresh).server
        assert _data(await _call(restarted, "generate_portfolio_report", args)) == queued
        conflict = await _call(
            restarted,
            "generate_portfolio_report",
            {**args, "format": "csv"},
        )
        assert conflict.is_error and conflict.structured_content is not None
        assert conflict.structured_content["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"

        claims = await case.jobs.claim_report_dispatches(dispatcher_id="p209-report", limit=1)
        assert len(claims) == 1 and claims[0].message.job_id == job_id
        assert await case.jobs.acknowledge_report_dispatch(claims[0])
        assert (
            await execute_report_message(
                case.jobs,
                claims[0].message,
                consumer_id="p209-report",
            )
            is ReportExecutionState.COMPLETED
        )
        assert (
            await execute_report_message(
                case.jobs,
                claims[0].message,
                consumer_id="p209-report-duplicate",
            )
            is ReportExecutionState.NOT_CLAIMED
        )
        status_args = {"account_id": str(case.account_id), "report_job_id": str(job_id)}
        completed = _data(await _call(restarted, "get_report_status", status_args))
        assert completed["state"] == "succeeded"
        assert completed["report_id"] == str(job_id) and len(completed["artifacts"]) == 1
        assert completed["context"] == queued["context"]
        assert _data(await _call(restarted, "generate_portfolio_report", args)) == completed
        manifest = await fresh.get_report_manifest(case.principal, case.account_id, job_id)
        assert str(manifest.document.selection.snapshot_id) == args["snapshot_id"]

        api = create_api_app(
            settings=_settings(),
            service=PostgresPortfolioService(
                sessions=case.base.sessions,
                cursor_signing_key=XRAY_CURSOR_KEY,
            ),
            report_service=fresh,
            bearer_authenticator=_Bearer(case.principal),
        )
        headers = {"Authorization": "Bearer synthetic-p209-report"}
        with TestClient(api, base_url="https://testserver", headers=headers) as client:
            response = client.get(
                f"/api/v1/report-jobs/{job_id}",
                params={
                    "account_id": str(case.account_id),
                },
            )
            assert response.status_code == 200 and response.json() == completed
            body = {
                key: value
                for key, value in args.items()
                if key not in {"format", "idempotency_key"}
            }
            replay = client.post(
                "/api/v1/report-jobs",
                json={**body, "formats": ["json"]},
                headers={"X-Idempotency-Key": args["idempotency_key"]},
            )
            assert replay.status_code == 202 and replay.json() == completed
            listing = _data(
                await _call(
                    restarted,
                    "list_reports",
                    {"account_id": str(case.account_id), "limit": 1},
                )
            )
            listed = client.get(
                "/api/v1/reports",
                params={
                    "account_id": str(case.account_id),
                    "limit": 1,
                },
            )
            assert listed.status_code == 200 and listed.json() == listing
            assert [item["job_id"] for item in listing["items"]] == [str(job_id)]

            selected = replace(
                case.principal,
                owner_id="63891f9c-ee24-446f-8509-6f71c2b9d87b",
            )
            foreign = await _call(restarted, "get_report_status", status_args)
            assert foreign.is_error and foreign.structured_content is not None
            assert foreign.structured_content["data"] is None
            assert foreign.structured_content["error"]["code"] == "ACCESS_DENIED"
            selected = case.principal
            # The still-valid token cannot override a revoked physical current grant.
            with case.base.sessions() as session, session.begin():
                provision_principal_scopes(
                    session,
                    principal_id=UUID(case.principal.principal_id),
                    scopes=frozenset(Scope) - {Scope.REPORTS_READ},
                    now=datetime.now(UTC),
                )
            denied = await _call(restarted, "get_report_status", status_args)
            assert denied.is_error and denied.structured_content is not None
            assert denied.structured_content["data"] is None
            assert denied.structured_content["error"]["code"] == "ACCESS_DENIED"
            api_denied = client.get(
                f"/api/v1/report-jobs/{job_id}",
                params={
                    "account_id": str(case.account_id),
                },
            )
            assert api_denied.status_code == 403
            assert api_denied.json()["error"]["code"] == "ACCESS_DENIED"

        with case.base.sessions() as session:
            row = session.get(ReportJobModel, job_id)
            assert row is not None and row.input_id == input_id and row.input_digest == input_digest
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ReportManifestModel)
                    .where(ReportManifestModel.job_id == job_id)
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ReportArtifactModel)
                    .where(ReportArtifactModel.job_id == job_id)
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ArtifactDownloadGrantModel)
                    .where(
                        ArtifactDownloadGrantModel.report_artifact_id
                        == UUID(completed["artifacts"][0]["artifact_id"])
                    )
                )
                == 0
            )
            actions = session.scalars(
                select(AuditEventModel.action)
                .where(
                    AuditEventModel.resource_id == str(job_id),
                )
                .order_by(AuditEventModel.occurred_at)
            ).all()
            assert actions == ["report.job.created", "report.job.completed"]
        assert attempts == {"probe": 1, "command": 0}

    asyncio.run(run())
