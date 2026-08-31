"""P1-01 process composition smoke tests."""

import httpx
import pytest
from trading212_api.main import app
from trading212_mcp.main import health as mcp_health
from trading212_worker.main import health as worker_health


@pytest.mark.unit
async def test_api_liveness_is_bounded() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.get("/health/live")
    assert response.json() == {"service": "api", "status": "ok"}
    assert app.docs_url is None
    assert app.redoc_url is None


@pytest.mark.unit
def test_worker_and_mcp_health_are_bounded() -> None:
    assert worker_health() == {"service": "worker", "status": "ok"}
    assert mcp_health() == {"service": "mcp", "status": "ok"}
