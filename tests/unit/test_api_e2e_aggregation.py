"""The additional native fixture stays explicitly restricted to disposable tests."""

from datetime import UTC, datetime
from typing import cast
from unittest.mock import Mock, patch

import pytest
from alembic import command
from sqlalchemy.orm import Session, sessionmaker

from scripts import run_api_backed_e2e as runner
from scripts.api_e2e_aggregation import aggregation_enabled, seed_aggregation_browser_scenario


@pytest.mark.parametrize(("value", "expected"), [("0", False), ("1", True)])
def test_selector_requires_exact_explicit_value(value: str, expected: bool) -> None:
    assert aggregation_enabled(value) is expected


@pytest.mark.parametrize("value", ["", "true", "01", " 1", "CANARY"])
def test_invalid_selector_precedes_migration(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("T212PI_E2E_AGGREGATION", value)
    with patch.object(command, "upgrade") as migrate:
        with pytest.raises(RuntimeError, match="must be 0 or 1") as raised:
            runner._serve_fixture("postgresql://unused")
        migrate.assert_not_called()
    assert "CANARY" not in str(raised.value)


@pytest.mark.parametrize(
    ("environment", "selector"),
    [("production", "1"), ("local", "1"), ("test", "0"), ("test", "CANARY")],
)
async def test_guard_rejects_before_any_session_or_grant(
    environment: str, selector: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("T212PI_E2E_AGGREGATION", selector)
    sessions = Mock()
    with pytest.raises(RuntimeError):
        await seed_aggregation_browser_scenario(
            cast(sessionmaker[Session], sessions),
            app_environment=environment,
            at=datetime(2026, 9, 22, tzinfo=UTC),
        )
    assert sessions.mock_calls == []
