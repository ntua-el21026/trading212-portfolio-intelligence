"""MCP alert WindowPage parity with the real canonical service and durable cursor.

The existing alert fixture authors synthetic threshold inputs through real durable
evaluation jobs. It is not broker data or evidence of live financial behavior.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from mcp.types import CallToolResult
from trading212_api_contracts import alerts as wire
from trading212_application import alerts as app
from trading212_application.alert_projection import alert_content
from trading212_mcp.auth import PrincipalResolver
from trading212_mcp.schemas import RESULT_MODELS
from trading212_mcp.server import create_runtime
from trading212_persistence.alert_service import PostgresAlertService
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_worker.alert_tasks import AlertExecutionState, execute_alert_message

from tests.integration.test_alert_postgres import KEY, AlertCase
from tests.integration.test_alert_postgres import alert_case as alert_case
from tests.integration.test_alert_postgres import alert_database as alert_database

pytestmark = pytest.mark.integration


def test_alert_mcp_window_page_survives_restart_and_checks_current_grants(
    alert_case: AlertCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = alert_case

    async def resolve(_resolver: PrincipalResolver) -> Principal:
        return case.principal

    monkeypatch.setattr(PrincipalResolver, "resolve", resolve)

    async def run() -> None:
        for _ in range(2):
            rule = await case.active()
            message = await case.admit(rule.id)
            assert (
                await execute_alert_message(
                    case.store,
                    message,
                    consumer_id="p209-alert",
                )
                is AlertExecutionState.COMPLETED
            )
        capture_calls = case.control.calls
        cutoff = case.clock[0]
        settings = SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
        )
        server = create_runtime(
            security_settings=settings,
            alert_service=case.service,
            clock=lambda: case.clock[0],
        ).server
        arguments: dict[str, Any] = {
            "account_id": str(case.account_id),
            "start_date": cutoff.date().isoformat(),
            "end_date": cutoff.date().isoformat(),
            "source_cutoff_at": cutoff.isoformat(),
            "state": "all",
            "limit": 1,
        }
        first = await server.call_tool("get_alert_summary", arguments)
        assert isinstance(first, CallToolResult) and not first.is_error
        assert first.structured_content is not None
        RESULT_MODELS["get_alert_summary"].model_validate(first.structured_content)
        data = first.structured_content["data"]
        assert data["page"]["total"] == 2 and len(data["page"]["items"]) == 1
        cursor = data["page"]["next_cursor"]
        assert isinstance(cursor, str) and 0 < len(cursor) <= 2048

        fresh_service = PostgresAlertService(
            case.sessions,
            cursor_signing_key=KEY,
            clock=lambda: case.clock[0],
        )
        restarted = create_runtime(
            security_settings=settings,
            alert_service=fresh_service,
            clock=lambda: case.clock[0],
        ).server
        resumed = await restarted.call_tool(
            "get_alert_summary",
            {**arguments, "cursor": cursor},
        )
        assert isinstance(resumed, CallToolResult) and not resumed.is_error
        assert resumed.structured_content is not None
        tail = resumed.structured_content["data"]
        assert len(tail["page"]["items"]) == 1 and tail["page"]["next_cursor"] is None
        canonical = await fresh_service.get_summary(
            case.principal,
            case.account_id,
            query=app.AlertSummaryWindowQuery(
                start_date=cutoff.date(),
                end_date=cutoff.date(),
                source_cutoff_at=cutoff,
                state=app.AlertStateFilter.ALL,
                limit=2,
            ),
        )
        assert isinstance(canonical, app.AlertSummaryPage)
        expected = wire.AlertSummaryPage.model_validate(alert_content(canonical)).model_dump(
            mode="json"
        )
        assert [*data["page"]["items"], *tail["page"]["items"]] == expected["page"]["items"]
        for field in ("account_id", "source_cutoff_at", "counts"):
            assert data[field] == tail[field] == expected[field]

        invalid = await restarted.call_tool(
            "get_alert_summary",
            {**arguments, "cursor": cursor, "severity": "critical"},
        )
        assert isinstance(invalid, CallToolResult) and invalid.is_error
        assert invalid.structured_content is not None
        assert invalid.structured_content["error"]["code"] == "CURSOR_INVALID"
        case.clock[0] += timedelta(seconds=1)
        with case.sessions() as session, session.begin():
            provision_principal_scopes(
                session,
                principal_id=UUID(case.principal.principal_id),
                scopes=frozenset(Scope) - {Scope.ALERTS_READ},
                now=case.clock[0],
            )
        revoked = await restarted.call_tool(
            "get_alert_summary",
            {**arguments, "cursor": cursor},
        )
        assert isinstance(revoked, CallToolResult) and revoked.is_error
        assert revoked.structured_content is not None
        assert revoked.structured_content["data"] is None
        assert revoked.structured_content["error"]["code"] == "ACCESS_DENIED"
        assert case.control.calls == capture_calls

    asyncio.run(run())
