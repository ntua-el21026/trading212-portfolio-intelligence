"""Remaining-family recovery selects only its explicit task and owned endpoints."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy import Engine

from tests.integration import test_phase3_remaining_family_recovery as recovery

pytestmark = pytest.mark.unit
_CURRENT = "t212pi_batch2_consolidated_b_20261115"
_LEGACY = "t212pi_batch2_checkpoint_b_20261115"
_IDS = {"postgres": "a" * 64, "redis": "b" * 64}


def _engine(
    *, host: str = "127.0.0.1", port: int = 55432, database: str = "t212pi_xray_reads_synthetic"
) -> Engine:
    return cast(
        Engine, SimpleNamespace(url=SimpleNamespace(host=host, port=port, database=database))
    )


@pytest.mark.parametrize("project", (_LEGACY, _CURRENT))
def test_remaining_family_recovery_accepts_only_its_explicit_owned_task(
    monkeypatch: pytest.MonkeyPatch, project: str
) -> None:
    monkeypatch.setenv("T212PI_PHASE3_TASK_PROJECT", project)
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:56379/0")
    observed: list[tuple[str, str, int]] = []

    def docker(*arguments: str) -> str:
        if arguments[0] == "ps":
            assert "label=com.docker.compose.project=" + project in arguments
            service = arguments[-1].removeprefix("label=com.docker.compose.service=")
            return _IDS[service]
        assert arguments[:3] == ("inspect", "--format", "{{json .Config.Labels}}")
        service = next(name for name, identifier in _IDS.items() if identifier == arguments[3])
        return json.dumps(
            {"com.docker.compose.project": project, "com.docker.compose.service": service}
        )

    monkeypatch.setattr(recovery, "_docker", docker)
    monkeypatch.setattr(recovery, "task_postgres", lambda: _IDS["postgres"])
    monkeypatch.setattr(
        recovery,
        "_mapped_port",
        lambda identifier, target, port: observed.append((identifier, target, port)),
    )
    assert recovery._owned_dependencies(_engine()) == _IDS
    assert observed == [(_IDS["postgres"], "5432/tcp", 55432), (_IDS["redis"], "6379/tcp", 56379)]


@pytest.mark.parametrize(
    "project", ("", "t212pi_batch2_foreign", "t212pi_batch2_20261114", _CURRENT + " ", "../foreign")
)
def test_remaining_family_foreign_task_fails_before_resource_discovery(
    monkeypatch: pytest.MonkeyPatch, project: str
) -> None:
    monkeypatch.setenv("T212PI_PHASE3_TASK_PROJECT", project)

    def forbidden(*_arguments: object) -> str:
        pytest.fail("Foreign task selection reached resource discovery.")

    monkeypatch.setattr(recovery, "task_postgres", forbidden)
    monkeypatch.setattr(recovery, "_docker", forbidden)
    with pytest.raises(AssertionError):
        recovery._owned_dependencies(_engine())


@pytest.mark.parametrize(
    ("host", "port", "database"),
    (
        ("192.0.2.1", 55432, "t212pi_xray_reads_synthetic"),
        ("127.0.0.1", 5432, "t212pi_xray_reads_synthetic"),
        ("127.0.0.1", 55432, "original_database"),
    ),
)
def test_remaining_family_wrong_postgres_endpoint_fails_before_discovery(
    monkeypatch: pytest.MonkeyPatch, host: str, port: int, database: str
) -> None:
    monkeypatch.setenv("T212PI_PHASE3_TASK_PROJECT", _CURRENT)

    def forbidden(*_arguments: object) -> str:
        pytest.fail("Foreign endpoint reached resource discovery.")

    monkeypatch.setattr(recovery, "task_postgres", forbidden)
    monkeypatch.setattr(recovery, "_docker", forbidden)
    with pytest.raises(AssertionError):
        recovery._owned_dependencies(_engine(host=host, port=port, database=database))
