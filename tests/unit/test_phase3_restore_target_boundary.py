"""Reject a foreign restore target before resolving containers or opening SQL."""

import json
import subprocess
from dataclasses import dataclass, field
from ipaddress import IPv4Address
from pathlib import Path
from typing import Literal, NoReturn, cast

import psycopg
import pytest
from sqlalchemy import Engine

from tests.integration import phase3_operational_fixture as operational

pytestmark = pytest.mark.unit
_PROJECT = "t212pi_batch2_20261114"
_PRIVATE = "TARGET_CREDENTIAL_CANARY"
type Operation = Literal["restore", "drop"]


class _OperatorCallReached(RuntimeError):
    """Pure sentinel: an external operation would have been attempted."""


@dataclass
class _TargetURL:
    drivername: str = "postgresql+psycopg"
    host: str = "127.0.0.1"
    port: int = 55432
    database: str = "t212pi_xray_reads_synthetic"
    query: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    @property
    def password(self) -> NoReturn:
        self.calls.append("password")
        raise _OperatorCallReached("Password fields must not be inspected by the target guard.")

    def set(self, **_changes: object) -> NoReturn:
        self.calls.append("url.set")
        raise _OperatorCallReached("Connection URL construction must follow the target guard.")

    def __str__(self) -> NoReturn:
        self.calls.append("url.str")
        raise _OperatorCallReached("Connection URLs must not be rendered in target errors.")


@dataclass
class _SourceEngine:
    url: _TargetURL


def _call(operation: Operation, target: _TargetURL, directory: Path) -> None:
    engine = cast(Engine, _SourceEngine(target))
    if operation == "restore":
        operational.restore_empty(engine, directory=directory)
    else:
        operational.drop_restored(engine, "t212pi_phase3_ops_synthetic")


def _external_sentinels(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    def task_container() -> NoReturn:
        calls.append("task_postgres")
        raise _OperatorCallReached("Container lookup must follow the target guard.")

    def docker(*_args: object, **_kwargs: object) -> NoReturn:
        calls.append("docker")
        raise _OperatorCallReached("Docker must not run before target validation.")

    def sql(*_args: object, **_kwargs: object) -> NoReturn:
        calls.append("sql")
        raise _OperatorCallReached("SQL must not run before target validation.")

    monkeypatch.setattr(operational, "task_postgres", task_container)
    monkeypatch.setattr(subprocess, "run", docker)
    monkeypatch.setattr(psycopg, "connect", sql)


@pytest.mark.parametrize("operation", ["restore", "drop"])
@pytest.mark.parametrize(
    "mutation", ["foreign_host", "wrong_port", "wrong_driver", "query_host_override"]
)
def test_restore_and_drop_refuse_foreign_targets_before_any_operator_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    operation: Operation,
    mutation: str,
) -> None:
    monkeypatch.setenv("T212PI_PHASE3_TASK_PROJECT", _PROJECT)
    target = _TargetURL()
    calls: list[str] = []
    if mutation == "foreign_host":
        target.host = _PRIVATE + ".invalid"
    elif mutation == "wrong_port":
        target.port = 55433
    elif mutation == "wrong_driver":
        target.drivername = "postgresql"
    else:
        target.query = {"host": _PRIVATE + ".invalid"}
    _external_sentinels(monkeypatch, calls)

    with pytest.raises(ValueError) as rejected:
        _call(operation, target, tmp_path)

    assert _PRIVATE not in str(rejected.value)
    assert target.calls == calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("operation", ["restore", "drop"])
@pytest.mark.parametrize("project", [None, "foreign_" + _PRIVATE])
def test_restore_and_drop_require_the_validated_task_project_before_any_operator_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    operation: Operation,
    project: str | None,
) -> None:
    if project is None:
        monkeypatch.delenv("T212PI_PHASE3_TASK_PROJECT", raising=False)
    else:
        monkeypatch.setenv("T212PI_PHASE3_TASK_PROJECT", project)
    target = _TargetURL()
    calls: list[str] = []
    _external_sentinels(monkeypatch, calls)

    with pytest.raises(ValueError) as rejected:
        _call(operation, target, tmp_path)

    assert _PRIVATE not in str(rejected.value)
    assert target.calls == calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("operation", ["restore", "drop"])
def test_valid_synthetic_target_reaches_only_the_first_pure_operator_sentinel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, operation: Operation
) -> None:
    monkeypatch.setenv("T212PI_PHASE3_TASK_PROJECT", _PROJECT)
    target = _TargetURL()
    calls: list[str] = []
    _external_sentinels(monkeypatch, calls)

    with pytest.raises(_OperatorCallReached):
        _call(operation, target, tmp_path)

    assert calls == ["task_postgres"]
    assert target.calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("operation", ["restore", "drop"])
def test_selected_task_endpoint_denial_precedes_admin_connection_construction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, operation: Operation
) -> None:
    monkeypatch.setenv("T212PI_PHASE3_TASK_PROJECT", _PROJECT)
    target = _TargetURL()
    calls: list[str] = []
    _external_sentinels(monkeypatch, calls)

    def denied_endpoint() -> NoReturn:
        calls.append("endpoint")
        raise ValueError("The selected task PostgreSQL endpoint does not match.")

    monkeypatch.setattr(operational, "task_postgres", denied_endpoint)
    with pytest.raises(ValueError) as rejected:
        _call(operation, target, tmp_path)

    assert _PRIVATE not in str(rejected.value)
    assert calls == ["endpoint"] and target.calls == []
    assert list(tmp_path.iterdir()) == []


def _port_inspection(monkeypatch: pytest.MonkeyPatch, ports: object) -> list[list[str]]:
    monkeypatch.setenv("T212PI_PHASE3_TASK_PROJECT", _PROJECT)
    calls: list[list[str]] = []

    def docker(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        assert arguments[0] == "/usr/bin/docker"
        if arguments[1] == "ps":
            assert "label=com.docker.compose.project=" + _PROJECT in arguments
            assert "label=com.docker.compose.service=postgres" in arguments
            return subprocess.CompletedProcess(arguments, 0, "synthetic-task-postgres\n", "")
        assert arguments == [
            "/usr/bin/docker",
            "inspect",
            "--format",
            "{{json .NetworkSettings.Ports}}",
            "synthetic-task-postgres",
        ]
        return subprocess.CompletedProcess(arguments, 0, json.dumps(ports), "")

    monkeypatch.setattr(subprocess, "run", docker)
    return calls


@pytest.mark.parametrize(
    "mutation", ["missing", "public", "wrong_port", "foreign_host", "duplicate", "malformed"]
)
def test_task_postgres_refuses_a_selected_container_with_a_different_endpoint(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    ports: object = {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "55432"}]}
    if mutation == "missing":
        ports = {}
    elif mutation == "public":
        ports = {"5432/tcp": [{"HostIp": str(IPv4Address(0)), "HostPort": "55432"}]}
    elif mutation == "wrong_port":
        ports = {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "55433"}]}
    elif mutation == "foreign_host":
        ports = {"5432/tcp": [{"HostIp": _PRIVATE + ".invalid", "HostPort": "55432"}]}
    elif mutation == "duplicate":
        ports = {
            "5432/tcp": [
                {"HostIp": "127.0.0.1", "HostPort": "55432"},
                {"HostIp": "127.0.0.1", "HostPort": "55433"},
            ]
        }
    else:
        ports = {"5432/tcp": _PRIVATE}
    calls = _port_inspection(monkeypatch, ports)

    with pytest.raises(ValueError) as rejected:
        operational.task_postgres()

    assert _PRIVATE not in str(rejected.value)
    assert len(calls) == 2


def test_task_postgres_accepts_only_the_exact_loopback_port_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _port_inspection(
        monkeypatch, {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "55432"}]}
    )
    assert operational.task_postgres() == "synthetic-task-postgres"
    assert len(calls) == 2
