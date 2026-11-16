"""Final task admission retains exact resource identity and historical refusals."""

from __future__ import annotations

import json
from ipaddress import IPv4Address
from types import SimpleNamespace
from typing import Any, Literal, cast

import pytest
from sqlalchemy import Engine
from sqlalchemy.engine import make_url

from tests.integration import test_phase3_process_recovery as process
from tests.integration import test_phase3_remaining_family_recovery as remaining
from tests.unit.test_phase3_stack_restart import _IMAGES, _REPOSITORY, _containers, _plan, _tool

pytestmark = pytest.mark.unit
_FINAL = "t212pi_batch2_final_checkpoint_b_20261116"
_PRIOR = "t212pi_batch2_consolidated_b_20261115"
_LEGACY = "t212pi_batch2_20261114"
_IDS = {"postgres": "a" * 64, "redis": "b" * 64}


@pytest.fixture(autouse=True)
def _final_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("T212PI_PHASE3_TASK_PROJECT", _FINAL)
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:56379/0")


def _final_plan() -> dict[str, Any]:
    plan = _plan()
    plan["project"] = _FINAL
    plan["postgres_volume"] = _FINAL + "_postgres-data"
    return plan


def _final_containers() -> list[dict[str, Any]]:
    rows = _containers()
    for row in rows:
        row["Config"]["Labels"]["com.docker.compose.project"] = _FINAL
        row["HostConfig"]["NetworkMode"] = _FINAL + "_default"
        row["NetworkSettings"]["Networks"] = {_FINAL + "_default": {"NetworkID": "a" * 64}}
        if row["Mounts"]:
            row["Mounts"][0]["Name"] = _FINAL + "_postgres-data"
    return rows


def _engine() -> Engine:
    return cast(
        Engine,
        SimpleNamespace(
            url=make_url("postgresql+psycopg://127.0.0.1:55432/t212pi_xray_reads_synthetic")
        ),
    )


def _metadata(arguments: tuple[str, ...]) -> str:
    if arguments[0] == "ps":
        assert "label=com.docker.compose.project=" + _FINAL in arguments
        services = [
            service
            for service in _IDS
            if "label=com.docker.compose.service=" + service in arguments
        ]
        assert len(services) == 1
        return _IDS[services[0]]
    assert arguments[0] == "inspect" and arguments[1] == "--format"
    service = next(service for service, identifier in _IDS.items() if identifier == arguments[-1])
    if arguments[2] == "{{json .Config.Labels}}":
        return json.dumps(
            {"com.docker.compose.project": _FINAL, "com.docker.compose.service": service}
        )
    assert arguments[2] == "{{json .NetworkSettings.Ports}}"
    target, port = ("5432/tcp", "55432") if service == "postgres" else ("6379/tcp", "56379")
    return json.dumps({target: [{"HostIp": "127.0.0.1", "HostPort": port}]})


def test_final_task_accepts_exact_nine_service_identity_without_secrets() -> None:
    tool = _tool()
    actual = tool.validate_containers(
        _final_containers(), tool.validate_plan(_final_plan()), _IMAGES, _REPOSITORY, phase="ready"
    )
    assert len(actual) == 9 and actual["postgres"]["id"] == "1" * 64
    assert "never-copy-this-to-evidence" not in json.dumps(actual)


@pytest.mark.parametrize("service", ("postgres", "redis"))
def test_final_process_lookup_preserves_exact_project_and_service(
    monkeypatch: pytest.MonkeyPatch, service: Literal["postgres", "redis"]
) -> None:
    calls: list[tuple[str, ...]] = []

    def docker(*arguments: str) -> str:
        calls.append(arguments)
        return _metadata(arguments)

    monkeypatch.setattr(process, "_docker", docker)
    monkeypatch.setattr(process, "task_postgres", lambda: _IDS["postgres"])
    assert process._container(service) == _IDS[service]
    assert len(calls) == 2


def test_final_remaining_family_lookup_preserves_both_exact_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def docker(*arguments: str) -> str:
        calls.append(arguments)
        return _metadata(arguments)

    monkeypatch.setattr(remaining, "_docker", docker)
    monkeypatch.setattr(process, "_docker", docker)
    monkeypatch.setattr(remaining, "task_postgres", lambda: _IDS["postgres"])
    assert remaining._owned_dependencies(_engine()) == _IDS
    assert len(calls) == 6


@pytest.mark.parametrize(
    "project",
    (_FINAL + "0", _FINAL + " ", _FINAL + ";x", "t212pi_batch2_foreign", "", "../foreign"),
)
def test_final_near_miss_or_foreign_project_fails_before_resource_lookup(
    monkeypatch: pytest.MonkeyPatch, project: str
) -> None:
    monkeypatch.setenv("T212PI_PHASE3_TASK_PROJECT", project)

    def forbidden(*_arguments: str) -> str:
        pytest.fail("Unapproved project reached resource lookup.")

    monkeypatch.setattr(process, "_docker", forbidden)
    monkeypatch.setattr(remaining, "_docker", forbidden)
    with pytest.raises((AssertionError, ValueError)):
        process._container("postgres")
    with pytest.raises((AssertionError, ValueError)):
        remaining._owned_dependencies(_engine())
    with pytest.raises(ValueError):
        _tool().validate_plan(_final_plan())


def test_remaining_family_legacy_project_refusal_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("T212PI_PHASE3_TASK_PROJECT", _LEGACY)

    def forbidden(*_arguments: str) -> str:
        pytest.fail("Historically unapproved family project reached resource lookup.")

    monkeypatch.setattr(remaining, "_docker", forbidden)
    with pytest.raises(AssertionError):
        remaining._owned_dependencies(_engine())


@pytest.mark.parametrize(
    ("selected", "plan_project"),
    ((_FINAL, _PRIOR), (_PRIOR, _FINAL), (_FINAL, _LEGACY), (_LEGACY, _FINAL)),
)
def test_final_stack_plan_cannot_cross_another_authorized_task(
    monkeypatch: pytest.MonkeyPatch, selected: str, plan_project: str
) -> None:
    monkeypatch.setenv("T212PI_PHASE3_TASK_PROJECT", selected)
    plan = _final_plan()
    plan["project"], plan["postgres_volume"] = plan_project, plan_project + "_postgres-data"
    with pytest.raises(ValueError):
        _tool().validate_plan(plan)


@pytest.mark.parametrize("mutation", ("project", "image", "network", "volume", "public_port"))
def test_final_project_refuses_foreign_resource_metadata(mutation: str) -> None:
    tool, rows = _tool(), _final_containers()
    postgres = rows[0]
    if mutation == "project":
        postgres["Config"]["Labels"]["com.docker.compose.project"] = _PRIOR
    elif mutation == "image":
        postgres["Image"] = "sha256:" + "f" * 64
    elif mutation == "network":
        postgres["NetworkSettings"]["Networks"] = {_PRIOR + "_default": {"NetworkID": "a" * 64}}
    elif mutation == "volume":
        postgres["Mounts"][0]["Name"] = _PRIOR + "_postgres-data"
    else:
        postgres["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostIp"] = str(IPv4Address(0))
    with pytest.raises(ValueError):
        tool.validate_containers(
            rows, tool.validate_plan(_final_plan()), _IMAGES, _REPOSITORY, phase="ready"
        )
