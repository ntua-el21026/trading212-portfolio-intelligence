"""Cross-interface secret-canary acceptance checks for controlled failures."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from starlette.testclient import TestClient
from trading212_api.main import create_app
from trading212_application.services import SyntheticPortfolioService
from trading212_mcp.server import create_runtime
from trading212_observability import SecurityAuditEvent, SecurityAuditSink
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

from scripts.check_secret_canary import (
    REPOSITORY_SCAN_EXCLUDED_DIRECTORY_NAMES,
    find_canary_occurrences,
)

_CANARY = "-".join(("phase1", "runtime", "secret", "canary", "7d5f81b3049c"))
_MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
_REPOSITORY_ROOT = Path(__file__).parents[2]


@dataclass(slots=True)
class _RecordingAuditSink(SecurityAuditSink):
    events: list[SecurityAuditEvent] = field(default_factory=list)

    async def record(self, event: SecurityAuditEvent) -> None:
        self.events.append(event)


class _CanaryFailureService(SyntheticPortfolioService):
    async def get_summary(self, principal: Any, account_id: str) -> Any:
        del principal, account_id
        raise RuntimeError(f"Bearer {_CANARY}")


def _tool_call() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_account_summary",
            "arguments": {"account_id": SyntheticPortfolioService.ACCOUNT_ID},
        },
    }


@pytest.mark.asyncio
@pytest.mark.security
async def test_secret_canary_is_absent_from_api_mcp_errors_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=True,
        cookie_secure=True,
        allowed_hosts=("localhost",),
    )
    audit_sink = _RecordingAuditSink()
    api = create_app(
        settings=settings,
        service=_CanaryFailureService(),
        audit_sink=audit_sink,
    )
    caplog.set_level("INFO")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api, raise_app_exceptions=False),
        base_url="https://localhost",
    ) as client:
        invalid_bearer = await client.get(
            f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/summary",
            headers={"Authorization": f"Bearer {_CANARY}"},
        )
        login = await client.post("/api/v1/auth/local-session")
        internal_failure = await client.get(
            f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/summary"
        )

    assert invalid_bearer.status_code == 401
    assert invalid_bearer.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert login.status_code == 201
    assert internal_failure.status_code == 500

    mcp = create_runtime(security_settings=settings, service=_CanaryFailureService())
    with TestClient(mcp.asgi_app(), base_url="http://localhost") as client:
        mcp_failure = client.post(
            "/mcp",
            headers={
                **_MCP_HEADERS,
                "X-Correlation-ID": f"Bearer {_CANARY}",
            },
            json=_tool_call(),
        )

    assert mcp_failure.status_code == 200
    result = mcp_failure.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "INTERNAL_ERROR"

    observable_output = "\n".join(
        (
            invalid_bearer.text,
            login.text,
            internal_failure.text,
            mcp_failure.text,
            repr(audit_sink.events),
            caplog.text,
        )
    )
    assert _CANARY not in observable_output


@pytest.mark.security
def test_secret_canary_scanner_covers_repository_and_available_web_artifacts(
    tmp_path: Path,
) -> None:
    leak = tmp_path / "synthetic-leak.bin"
    leak.write_bytes(b"prefix:" + _CANARY.encode() + b":suffix")
    assert find_canary_occurrences((leak,), _CANARY.encode()) == (leak,)

    assert (
        find_canary_occurrences(
            (_REPOSITORY_ROOT,),
            _CANARY.encode(),
            excluded_directory_names=REPOSITORY_SCAN_EXCLUDED_DIRECTORY_NAMES,
        )
        == ()
    )

    next_build = _REPOSITORY_ROOT / "apps" / "web" / ".next"
    artifact_paths = tuple(
        path
        for path in (
            next_build / "standalone",
            next_build / "static",
            next_build / "server",
            next_build / "trace",
            next_build / "trace-build",
        )
        if path.exists()
    )
    assert find_canary_occurrences(artifact_paths, _CANARY.encode()) == ()
