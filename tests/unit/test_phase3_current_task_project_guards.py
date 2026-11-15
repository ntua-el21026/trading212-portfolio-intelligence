"""Current-task recovery selection preserves exact legacy resource guards."""

from __future__ import annotations

import json
from ipaddress import IPv4Address
from typing import Any, Literal

import pytest

from tests.integration import test_phase3_process_recovery as process
from tests.unit.test_phase3_stack_restart import _IMAGES, _REPOSITORY, _containers, _plan, _tool

pytestmark = pytest.mark.unit

_CURRENT = "t212pi_batch2_consolidated_b_20261115"
_LEGACY = "t212pi_batch2_20261114"
_CID = "a" * 64


def _current_plan() -> dict[str, Any]:
    plan = _plan()
    plan["project"] = _CURRENT
    plan["postgres_volume"] = _CURRENT + "_postgres-data"
    return plan


def _current_containers() -> list[dict[str, Any]]:
    rows = _containers()
    for row in rows:
        row["Config"]["Labels"]["com.docker.compose.project"] = _CURRENT
        row["HostConfig"]["NetworkMode"] = _CURRENT + "_default"
        row["NetworkSettings"]["Networks"] = {_CURRENT + "_default": {"NetworkID": "a" * 64}}
        if row["Mounts"]:
            row["Mounts"][0]["Name"] = _CURRENT + "_postgres-data"
    return rows


def test_current_explicit_project_accepts_exact_nine_service_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("T212PI_PHASE3_TASK_PROJECT", _CURRENT)
    tool = _tool()
    plan = tool.validate_plan(_current_plan())
    actual = tool.validate_containers(
        _current_containers(), plan, _IMAGES, _REPOSITORY, phase="ready"
    )
    assert len(actual) == 9 and actual["postgres"]["id"] == "1" * 64
    assert "never-copy-this-to-evidence" not in json.dumps(actual)


@pytest.mark.parametrize("service", ("postgres", "redis"))
def test_process_recovery_looks_up_only_the_current_explicit_project(
    monkeypatch: pytest.MonkeyPatch, service: Literal["postgres", "redis"]
) -> None:
    monkeypatch.setenv("T212PI_PHASE3_TASK_PROJECT", _CURRENT)
    calls: list[tuple[str, ...]] = []

    def docker(*arguments: str) -> str:
        calls.append(arguments)
        if arguments[0] == "ps":
            assert "label=com.docker.compose.project=" + _CURRENT in arguments
            return _CID
        assert arguments == ("inspect", "--format", "{{json .Config.Labels}}", _CID)
        return json.dumps(
            {"com.docker.compose.project": _CURRENT, "com.docker.compose.service": service}
        )

    monkeypatch.setattr(process, "_docker", docker)
    monkeypatch.setattr(process, "task_postgres", lambda: _CID)
    assert process._container(service) == _CID
    assert len(calls) == 2


@pytest.mark.parametrize(
    "project",
    (
        "t212pi_batch2_foreign",
        "",
        "../foreign",
        _CURRENT + " ",
        _CURRENT + ";x",
        "t212pi_batch2_δοκιμή",
    ),
)
def test_foreign_or_malformed_project_fails_before_resource_lookup(
    monkeypatch: pytest.MonkeyPatch, project: str
) -> None:
    monkeypatch.setenv("T212PI_PHASE3_TASK_PROJECT", project)

    def forbidden(*_arguments: str) -> str:
        pytest.fail("Invalid task selection reached Docker.")

    monkeypatch.setattr(process, "_docker", forbidden)
    with pytest.raises((AssertionError, ValueError)):
        process._container("redis")
    with pytest.raises(ValueError):
        _tool().validate_plan(_current_plan())


@pytest.mark.parametrize(("selected", "plan_project"), ((_CURRENT, _LEGACY), (_LEGACY, _CURRENT)))
def test_stack_plan_must_match_the_explicit_environment_project(
    monkeypatch: pytest.MonkeyPatch, selected: str, plan_project: str
) -> None:
    monkeypatch.setenv("T212PI_PHASE3_TASK_PROJECT", selected)
    plan = _current_plan()
    plan["project"], plan["postgres_volume"] = plan_project, plan_project + "_postgres-data"
    with pytest.raises(ValueError):
        _tool().validate_plan(plan)


@pytest.mark.parametrize("mutation", ("project", "image", "network", "volume", "public_port"))
def test_current_project_still_rejects_foreign_resource_metadata(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    monkeypatch.setenv("T212PI_PHASE3_TASK_PROJECT", _CURRENT)
    tool, rows = _tool(), _current_containers()
    postgres = rows[0]
    if mutation == "project":
        postgres["Config"]["Labels"]["com.docker.compose.project"] = _LEGACY
    elif mutation == "image":
        postgres["Image"] = "sha256:" + "f" * 64
    elif mutation == "network":
        postgres["NetworkSettings"]["Networks"] = {_LEGACY + "_default": {"NetworkID": "a" * 64}}
    elif mutation == "volume":
        postgres["Mounts"][0]["Name"] = _LEGACY + "_postgres-data"
    else:
        postgres["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostIp"] = str(IPv4Address(0))
    with pytest.raises(ValueError):
        tool.validate_containers(
            rows, tool.validate_plan(_current_plan()), _IMAGES, _REPOSITORY, phase="ready"
        )


def test_legacy_stack_default_remains_a_metadata_only_compatible_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("T212PI_PHASE3_TASK_PROJECT", raising=False)
    assert _tool().validate_plan(_plan())["project"] == _LEGACY
