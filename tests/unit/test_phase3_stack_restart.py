"""Independent refusal cases for the destructive boundary of the local restart exercise."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from ipaddress import IPv4Address
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

pytestmark = pytest.mark.unit
_REPOSITORY = Path("/synthetic/checkout")
_PROJECT = "t212pi_batch2_20261114"
_SERVICES = ("postgres", "redis", "migrate", "seed", "api", "worker", "dispatcher", "mcp", "web")
_IMAGES = {service: "sha256:" + f"{index:x}" * 64 for index, service in enumerate(_SERVICES, 1)}


@pytest.fixture(autouse=True)
def _legacy_task_project_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Historical metadata fixtures explicitly retain their original task scope."""
    monkeypatch.setenv("T212PI_PHASE3_TASK_PROJECT", _PROJECT)


def _tool() -> ModuleType:
    path = Path("tests/integration/phase3_stack_restart.py")
    assert path.is_file(), "The guarded full-stack restart driver is not implemented."
    spec = importlib.util.spec_from_file_location("stack_restart_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _plan() -> dict[str, Any]:
    return {
        "schema_version": "t212pi.phase3.stack-restart-plan.v1",
        "qualification": "focused_local_preacceptance",
        "project": _PROJECT,
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
        "postgres_container_id": "1" * 64,
        "redis_container_id": "2" * 64,
        "postgres_volume": _PROJECT + "_postgres-data",
        "ports": {"postgres": 55432, "redis": 56379, "api": 58000, "mcp": 58001, "web": 53000},
        "compose_files": [
            str(_REPOSITORY / "compose.yaml"),
            "/private/task/compose.dependencies.yaml",
            "/private/task/compose.stack-images.yaml",
        ],
        "env_file": "/private/task/stack.env",
        "image_inventory": "/private/task/images.json",
        "build_receipt": "/private/task/build-binding.json",
        "original_build_receipt": "/private/task/build-receipt.json",
    }


def _containers() -> list[dict[str, Any]]:
    result = []
    bindings = {
        "postgres": ("5432/tcp", "55432"),
        "redis": ("6379/tcp", "56379"),
        "api": ("8000/tcp", "58000"),
        "mcp": ("8001/tcp", "58001"),
        "web": ("3000/tcp", "53000"),
    }
    for index, service in enumerate(_SERVICES, 1):
        one_shot = service in {"migrate", "seed"}
        result.append(
            {
                "Id": f"{index:x}" * 64,
                "Image": _IMAGES[service],
                "Config": {
                    "Env": [
                        "T212PI_ENVIRONMENT=local",
                        "T212PI_WORKER_PROVIDER=synthetic",
                        "PRIVATE_TEST_CANARY=never-copy-this-to-evidence",
                    ],
                    "Labels": {
                        "com.docker.compose.project": _PROJECT,
                        "com.docker.compose.service": service,
                        "com.docker.compose.oneoff": "False",
                        "com.docker.compose.project.working_dir": str(_REPOSITORY),
                        "com.docker.compose.project.config_files": ",".join(
                            _plan()["compose_files"]
                        ),
                    },
                },
                "State": {
                    "Running": not one_shot,
                    "Paused": False,
                    "Status": "exited" if one_shot else "running",
                    "ExitCode": 0,
                    "Health": {"Status": "healthy"},
                },
                "HostConfig": {"Privileged": False, "NetworkMode": _PROJECT + "_default"},
                "NetworkSettings": {
                    "Ports": {
                        bindings[service][0]: [
                            {"HostIp": "127.0.0.1", "HostPort": bindings[service][1]}
                        ]
                    }
                    if service in bindings
                    else {},
                    "Networks": {_PROJECT + "_default": {"NetworkID": "a" * 64}},
                },
                "Mounts": [
                    {
                        "Type": "volume",
                        "Name": _PROJECT + "_postgres-data",
                        "Destination": "/var/lib/postgresql",
                        "RW": True,
                    }
                ]
                if service == "postgres"
                else [],
            }
        )
    return result


def _validate(tool: ModuleType, rows: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        tool.validate_containers(rows, tool.validate_plan(_plan()), _IMAGES, _REPOSITORY, **kwargs),
    )


def test_exact_nine_service_ownership_accepts_two_completed_startup_services_without_secrets() -> (
    None
):
    actual = _validate(_tool(), _containers(), phase="ready")
    assert set(actual) == set(_SERVICES)
    assert actual["postgres"]["id"] == "1" * 64
    assert actual["seed"]["state"] == "exited"
    assert "never-copy-this-to-evidence" not in json.dumps(actual)


def test_closed_fallback_port_profile_accepts_matching_host_and_network_bindings() -> None:
    tool, plan, rows = _tool(), _plan(), _containers()
    plan["ports"] = {
        "postgres": 55432,
        "redis": 56379,
        "api": 58000,
        "mcp": 58001,
        "web": 53500,
    }
    web = rows[-1]
    web["HostConfig"]["PortBindings"] = {"3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "53500"}]}
    web["NetworkSettings"]["Ports"] = {"3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "53500"}]}
    actual = tool.validate_containers(
        rows, tool.validate_plan(plan), _IMAGES, _REPOSITORY, phase="ready"
    )
    assert set(actual) == set(_SERVICES)
    assert actual["web"]["id"] == "9" * 64
    assert actual["web"]["state"] == "running"


def test_closed_port_profiles_refuse_an_unapproved_web_port() -> None:
    plan = _plan()
    plan["ports"] = {
        "postgres": 55432,
        "redis": 56379,
        "api": 58000,
        "mcp": 58001,
        "web": 53501,
    }
    with pytest.raises(ValueError):
        _tool().validate_plan(plan)


@pytest.mark.parametrize(
    ("inspect_field", "ports_field"),
    [("HostConfig", "PortBindings"), ("NetworkSettings", "Ports")],
)
def test_original_plan_refuses_fallback_runtime_port(inspect_field: str, ports_field: str) -> None:
    tool, rows = _tool(), _containers()
    plan = tool.validate_plan(_plan())
    web = rows[-1]
    web["HostConfig"]["PortBindings"] = {"3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "53000"}]}
    web[inspect_field][ports_field]["3000/tcp"][0]["HostPort"] = "53500"
    with pytest.raises(ValueError):
        tool.validate_containers(rows, plan, _IMAGES, _REPOSITORY, phase="ready")


@pytest.mark.parametrize(
    ("inspect_field", "ports_field"),
    [("HostConfig", "PortBindings"), ("NetworkSettings", "Ports")],
)
def test_fallback_plan_refuses_original_runtime_port(inspect_field: str, ports_field: str) -> None:
    tool, plan, rows = _tool(), _plan(), _containers()
    plan["ports"] = {
        "postgres": 55432,
        "redis": 56379,
        "api": 58000,
        "mcp": 58001,
        "web": 53500,
    }
    plan = tool.validate_plan(plan)
    web = rows[-1]
    web["HostConfig"]["PortBindings"] = {"3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "53500"}]}
    web["NetworkSettings"]["Ports"] = {"3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "53500"}]}
    web[inspect_field][ports_field]["3000/tcp"][0]["HostPort"] = "53000"
    with pytest.raises(ValueError):
        tool.validate_containers(rows, plan, _IMAGES, _REPOSITORY, phase="ready")


@pytest.mark.parametrize(
    "mutation",
    [
        "foreign_project",
        "missing",
        "duplicate",
        "oneoff",
        "workdir",
        "config_files",
        "image",
        "postgres_id",
        "redis_id",
        "volume",
        "bind_mount",
        "public_port",
        "wrong_port",
        "extra_port",
        "foreign_network",
        "privileged",
        "unhealthy",
        "failed_seed",
        "live",
        "real_provider",
    ],
)
def test_restart_refuses_unowned_or_unqualified_resources_before_any_stop(mutation: str) -> None:
    rows = _containers()
    pg, redis, api, worker = rows[0], rows[1], rows[4], rows[5]
    if mutation == "foreign_project":
        pg["Config"]["Labels"]["com.docker.compose.project"] = "another-owner"
    elif mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows[-1] = copy.deepcopy(api)
    elif mutation == "oneoff":
        api["Config"]["Labels"]["com.docker.compose.oneoff"] = "True"
    elif mutation == "workdir":
        api["Config"]["Labels"]["com.docker.compose.project.working_dir"] = "/another/checkout"
    elif mutation == "config_files":
        api["Config"]["Labels"]["com.docker.compose.project.config_files"] = "/another/compose.yaml"
    elif mutation == "image":
        api["Image"] = "sha256:" + "f" * 64
    elif mutation == "postgres_id":
        pg["Id"] = "f" * 64
    elif mutation == "redis_id":
        redis["Id"] = "f" * 64
    elif mutation == "volume":
        pg["Mounts"][0]["Name"] = "another-owner-volume"
    elif mutation == "bind_mount":
        worker["Mounts"].append({"Type": "bind", "Source": "/", "Destination": "/host", "RW": True})
    elif mutation == "public_port":
        api["NetworkSettings"]["Ports"]["8000/tcp"][0]["HostIp"] = str(IPv4Address(0))
    elif mutation == "wrong_port":
        api["NetworkSettings"]["Ports"]["8000/tcp"][0]["HostPort"] = "8000"
    elif mutation == "extra_port":
        worker["NetworkSettings"]["Ports"]["9000/tcp"] = [
            {"HostIp": "127.0.0.1", "HostPort": "59000"}
        ]
    elif mutation == "foreign_network":
        worker["NetworkSettings"]["Networks"] = {"another_default": {"NetworkID": "b" * 64}}
    elif mutation == "privileged":
        worker["HostConfig"]["Privileged"] = True
    elif mutation == "unhealthy":
        api["State"]["Health"]["Status"] = "unhealthy"
    elif mutation == "failed_seed":
        rows[3]["State"]["ExitCode"] = 1
    elif mutation == "live":
        worker["Config"]["Env"].append("T212PI_TRADING212_LIVE_ENABLED=true")
    elif mutation == "real_provider":
        worker["Config"]["Env"][1] = "T212PI_WORKER_PROVIDER=trading212"
    with pytest.raises(ValueError):
        _validate(_tool(), rows, phase="ready")


def test_stop_boundary_requires_all_nine_stopped_and_restart_preserves_original_resources() -> None:
    tool, rows = _tool(), _containers()
    original = _validate(tool, rows, phase="ready")
    with pytest.raises(ValueError):
        _validate(tool, rows, phase="stopped", expected=original)
    for row in rows:
        row["State"].update(Running=False, Status="exited")
    stopped = _validate(tool, rows, phase="stopped", expected=original)
    assert set(stopped) == set(_SERVICES)
    replaced = _containers()
    replaced[4]["Id"] = "f" * 64
    with pytest.raises(ValueError):
        _validate(tool, replaced, phase="ready", expected=original)


def test_source_bound_scratch_policy_accepts_generic_declared_tmpfs_in_both_inspect_fields() -> (
    None
):
    rows = _containers()
    worker = rows[5]
    worker["Mounts"].append({"Type": "tmpfs", "Name": "", "Destination": "/scratch", "RW": True})
    worker["HostConfig"]["Tmpfs"] = {"/scratch": "rw,size=67108864,mode=1777"}
    tool = _tool()
    source: dict[str, Any] = {"services": {service: {} for service in _SERVICES}}
    source["services"]["worker"] = {"tmpfs": ["/scratch:size=67108864,mode=1777"]}
    policy = tool.compose_tmpfs_destinations(source)
    assert policy["worker"] == frozenset({"/scratch"})
    result = _validate(tool, rows, phase="ready", allowed_tmpfs=policy)
    assert result["worker"]["tmpfs_destinations"] == ["/scratch"]


@pytest.mark.parametrize("mutation", ["undeclared_destination", "foreign_service"])
def test_source_bound_scratch_policy_refuses_undeclared_or_other_service_tmpfs(
    mutation: str,
) -> None:
    rows = _containers()
    container = rows[5] if mutation == "undeclared_destination" else rows[4]
    destination = "/unapproved" if mutation == "undeclared_destination" else "/scratch"
    # Docker can omit tmpfs from Mounts, so HostConfig alone must still be checked.
    container["HostConfig"]["Tmpfs"] = {destination: "rw,size=67108864,mode=1777"}
    with pytest.raises(ValueError):
        _validate(_tool(), rows, phase="ready", allowed_tmpfs={"worker": frozenset({"/scratch"})})


@pytest.mark.parametrize(
    "mutation", ["project", "port", "qualification", "extra", "path", "source"]
)
def test_closed_plan_cannot_expand_operator_scope(mutation: str) -> None:
    plan = _plan()
    if mutation == "project":
        plan["project"] = "unrelated"
    elif mutation == "port":
        plan["ports"]["postgres"] = 5432
    elif mutation == "qualification":
        plan["qualification"] = "phase3_acceptance_passed"
    elif mutation == "extra":
        plan["command"] = "arbitrary-shell"
    elif mutation == "path":
        plan["env_file"] = "../outside"
    elif mutation == "source":
        plan["source_commit"] = "main"
    with pytest.raises(ValueError):
        _tool().validate_plan(plan)
