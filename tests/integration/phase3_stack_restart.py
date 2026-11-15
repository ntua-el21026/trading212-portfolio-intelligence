"""Guarded nine-service local restart with one real modeled-projection witness.

Root builds/starts the stack first. This driver never builds, pulls, removes a
container/volume, changes a clock, or performs a provider operation. It requires
a clean source/build binding and the existing task PostgreSQL/Redis identities.
This is focused local evidence, not a Phase 3 acceptance or all-family claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import time
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any, cast
from uuid import UUID, uuid4

SERVICES = ("postgres", "redis", "migrate", "seed", "api", "worker", "dispatcher", "mcp", "web")
_STARTUP = frozenset({"migrate", "seed"})
_PORTS = {"postgres": 55432, "redis": 56379, "api": 58000, "mcp": 58001, "web": 53000}
_FALLBACK_PORTS = {**_PORTS, "web": 53500}
_TARGETS = {
    "postgres": "5432/tcp",
    "redis": "6379/tcp",
    "api": "8000/tcp",
    "mcp": "8001/tcp",
    "web": "3000/tcp",
}
_PROJECT = "t212pi_batch2_20261114"
_CURRENT_PROJECT = "t212pi_batch2_consolidated_b_20261115"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_JSON = 2 * 1024 * 1024


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("A string-keyed object is required.")
    return cast(dict[str, Any], value)


def _require(condition: object, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _project() -> str:
    project = os.environ.get("T212PI_PHASE3_TASK_PROJECT", _PROJECT)
    _require(
        project in {_PROJECT, _CURRENT_PROJECT},
        "Only an authorized exact task project is supported.",
    )
    return project


def _path(value: object) -> Path:
    _require(isinstance(value, str) and len(value) <= 4096, "Invalid operator path.")
    path = Path(cast(str, value))
    _require(
        path.is_absolute() and ".." not in path.parts, "An absolute normalized path is required."
    )
    return path


def validate_plan(value: object) -> dict[str, Any]:
    plan = _object(value)
    project = _project()
    _require(
        set(plan)
        == {
            "schema_version",
            "qualification",
            "project",
            "source_commit",
            "source_tree",
            "postgres_container_id",
            "redis_container_id",
            "postgres_volume",
            "ports",
            "compose_files",
            "env_file",
            "image_inventory",
            "build_receipt",
            "original_build_receipt",
        },
        "The restart plan is closed.",
    )
    _require(
        plan["schema_version"] == "t212pi.phase3.stack-restart-plan.v1", "Unknown restart plan."
    )
    _require(
        plan["qualification"] == "focused_local_preacceptance",
        "Only focused local evidence is supported.",
    )
    _require(
        plan["project"] == project, "The plan differs from the selected authorized task project."
    )
    for name in ("source_commit", "source_tree"):
        _require(
            isinstance(plan[name], str) and _HEX40.fullmatch(plan[name]),
            "Invalid exact source identity.",
        )
    for name in ("postgres_container_id", "redis_container_id"):
        _require(
            isinstance(plan[name], str) and _HEX64.fullmatch(plan[name]),
            "An exact existing container ID is required.",
        )
    _require(
        plan["postgres_container_id"] != plan["redis_container_id"], "Storage container IDs differ."
    )
    _require(
        plan["postgres_volume"] == project + "_postgres-data",
        "Only the existing task volume is supported.",
    )
    _require(
        plan["ports"] in (_PORTS, _FALLBACK_PORTS),
        "The approved loopback ports must remain exact.",
    )
    files = plan["compose_files"]
    _require(
        isinstance(files, list) and len(files) == 3 and len(set(files)) == 3,
        "Exactly three Compose files are required.",
    )
    for name in files:
        _path(name)
    for name in ("env_file", "image_inventory", "build_receipt", "original_build_receipt"):
        _path(plan[name])
    return plan


def _bindings(
    value: object, service: str, ports: Mapping[str, int], *, missing_allowed: bool = False
) -> None:
    bindings = _object(value or {})
    published = {key: rows for key, rows in bindings.items() if rows}
    if service not in _TARGETS:
        _require(not published, "An internal service publishes an undeclared port.")
        return
    if missing_allowed and not published:
        return
    _require(set(published) == {_TARGETS[service]}, "Published port membership differs.")
    rows = published[_TARGETS[service]]
    _require(isinstance(rows, list) and 1 <= len(rows) <= 2, "Invalid loopback port mapping.")
    for row in rows:
        binding = _object(row)
        _require(
            binding.get("HostIp") in {"127.0.0.1", "::1"}, "A public host binding is forbidden."
        )
        _require(
            str(binding.get("HostPort")) == str(ports[service]),
            "The existing approved host port differs.",
        )


def _scratch_destination(value: object) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= 4096 or "\0" in value:
        raise ValueError("A bounded scratch destination is required.")
    path = PurePosixPath(value)
    _require(
        path.anchor == "/" and ".." not in path.parts and str(path) == value,
        "Scratch destinations must be canonical absolute container paths.",
    )
    return value


def compose_tmpfs_destinations(value: object) -> dict[str, frozenset[str]]:
    """Read fixed per-service scratch policy from a Compose document, never host defaults."""
    services = _object(_object(value).get("services"))
    _require(set(services) == set(SERVICES), "Scratch policy requires the exact nine services.")
    result: dict[str, frozenset[str]] = {}
    for service, raw in services.items():
        configuration = _object(raw)
        entries = configuration.get("tmpfs", [])
        if isinstance(entries, str):
            entries = [entries]
        _require(
            isinstance(entries, list) and len(entries) <= 16,
            "Scratch declarations exceed their bound.",
        )
        destinations = []
        for entry in entries:
            if not isinstance(entry, str):
                raise ValueError("A Compose scratch declaration must be a string.")
            # Parse the declared mount destination separately from its size/mode options.
            destinations.append(_scratch_destination(entry.partition(":")[0]))
        volumes = configuration.get("volumes", [])
        _require(
            isinstance(volumes, list) and len(volumes) <= 16,
            "Mount declarations exceed their bound.",
        )
        destinations.extend(
            _scratch_destination(volume.get("target"))
            for volume in volumes
            if isinstance(volume, dict) and volume.get("type") == "tmpfs"
        )
        _require(
            len(destinations) == len(set(destinations)),
            "Duplicate scratch destinations are forbidden.",
        )
        result[service] = frozenset(destinations)
    return result


def validate_containers(
    value: object,
    plan: dict[str, Any],
    images: dict[str, str],
    repository: Path,
    *,
    phase: str,
    expected: dict[str, Any] | None = None,
    allowed_tmpfs: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, Any]:
    """Validate raw inspect data; return only nonsecret identity/state metadata."""
    project = _project()
    _require(
        plan.get("project") == project, "The resource plan differs from the selected task project."
    )
    _require(phase in {"ready", "stopped", "owned"}, "Unknown stack boundary.")
    _require(
        isinstance(value, list) and len(value) == len(SERVICES),
        "Exactly nine task containers are required.",
    )
    _require(set(images) == set(SERVICES), "The build must bind all nine service images.")
    scratch_policy = allowed_tmpfs or {}
    _require(set(scratch_policy) <= set(SERVICES), "Scratch policy contains an unknown service.")
    actual: dict[str, Any] = {}
    for raw in cast(list[object], value):
        row = _object(raw)
        config, state = _object(row.get("Config")), _object(row.get("State"))
        labels = _object(config.get("Labels"))
        service = labels.get("com.docker.compose.service")
        if not isinstance(service, str) or service not in SERVICES or service in actual:
            raise ValueError("Duplicate or foreign service membership.")
        _require(
            labels.get("com.docker.compose.project") == project,
            "A container belongs to another project.",
        )
        _require(
            str(labels.get("com.docker.compose.oneoff")).lower() == "false",
            "One-off containers are outside this exercise.",
        )
        _require(
            labels.get("com.docker.compose.project.working_dir") == str(repository),
            "The container belongs to another checkout.",
        )
        configured = str(labels.get("com.docker.compose.project.config_files", "")).split(",")
        allowed_files = [plan["compose_files"]]
        if service in {"postgres", "redis"}:
            # --no-recreate preserves the original two-file labels on these existing resources.
            allowed_files.append(plan["compose_files"][:2])
        _require(
            configured in allowed_files, "The container belongs to another Compose configuration."
        )
        identifier, image = row.get("Id"), row.get("Image")
        _require(
            isinstance(identifier, str) and _HEX64.fullmatch(identifier),
            "An exact container ID is required.",
        )
        _require(
            isinstance(image, str) and _IMAGE.fullmatch(image) and image == images[service],
            "The running image differs from the source-bound build.",
        )
        if service in {"postgres", "redis"}:
            _require(
                identifier == plan[service + "_container_id"],
                "The original storage container was replaced.",
            )
        environment = {}
        for entry in config.get("Env", []):
            key, _, content = str(entry).partition("=")
            environment[key] = content
        _require(
            environment.get("T212PI_TRADING212_ENVIRONMENT", "demo") == "demo",
            "Live is outside this exercise.",
        )
        _require(
            environment.get("T212PI_TRADING212_LIVE_ENABLED", "false").lower() == "false",
            "Live enablement is forbidden.",
        )
        _require(
            not environment.get("T212PI_TRADING212_CREDENTIAL_BUNDLE"),
            "Broker credentials are forbidden.",
        )
        if service == "worker":
            _require(
                environment.get("T212PI_WORKER_PROVIDER") == "synthetic",
                "Only the synthetic worker is authorized.",
            )
        host, network = _object(row.get("HostConfig")), _object(row.get("NetworkSettings"))
        _require(host.get("Privileged") is False, "Privileged containers are forbidden.")
        _require(
            host.get("NetworkMode") == project + "_default", "The private task network differs."
        )
        if "PortBindings" in host:
            _bindings(host["PortBindings"], service, plan["ports"])
        _bindings(
            network.get("Ports"),
            service,
            plan["ports"],
            missing_allowed=phase != "ready" and "PortBindings" in host,
        )
        networks = _object(network.get("Networks"))
        _require(
            set(networks) == {project + "_default"}, "Foreign network membership is forbidden."
        )
        network_id = _object(networks[project + "_default"]).get("NetworkID")
        if phase == "ready":
            _require(
                isinstance(network_id, str) and _HEX64.fullmatch(network_id),
                "The task network identity is unavailable.",
            )
        mounts = []
        scratch = {
            _scratch_destination(destination) for destination in _object(host.get("Tmpfs") or {})
        }
        for raw_mount in row.get("Mounts", []):
            mount = _object(raw_mount)
            _require(
                mount.get("Type") in {"volume", "tmpfs"},
                "Host bind mounts are outside this exercise.",
            )
            if mount.get("Type") == "tmpfs":
                scratch.add(_scratch_destination(mount.get("Destination")))
            else:
                _require(
                    service in {"postgres", "redis"},
                    "Application data volumes are outside this exercise.",
                )
                mounts.append(
                    {name: mount.get(name) for name in ("Type", "Name", "Destination", "RW")}
                )
        _require(
            scratch == scratch_policy.get(service, frozenset()),
            "Actual scratch mounts differ from the frozen source service policy.",
        )
        if service == "postgres":
            _require(
                mounts
                == [
                    {
                        "Type": "volume",
                        "Name": plan["postgres_volume"],
                        "Destination": "/var/lib/postgresql",
                        "RW": True,
                    }
                ],
                "The original authoritative volume differs.",
            )
        _require(state.get("Paused") is False, "Paused containers cannot establish this boundary.")
        if phase == "ready":
            if service in _STARTUP:
                _require(
                    state.get("Running") is False
                    and state.get("Status") == "exited"
                    and state.get("ExitCode") == 0,
                    "A startup service did not complete successfully.",
                )
            else:
                _require(
                    state.get("Running") is True
                    and _object(state.get("Health")).get("Status") == "healthy",
                    "A long-running service is not healthy.",
                )
        if phase == "stopped":
            _require(
                state.get("Running") is False and state.get("Status") == "exited",
                "All nine service containers must be stopped.",
            )
        summary = {
            "id": identifier,
            "image_id": image,
            "mounts": mounts,
            "tmpfs_destinations": sorted(scratch),
            "network_id": network_id,
            "state": state.get("Status"),
            "running": state.get("Running"),
            "exit_code": state.get("ExitCode"),
            "health": _object(state.get("Health", {})).get("Status"),
        }
        if expected is not None:
            for key in ("id", "image_id", "mounts", "tmpfs_destinations"):
                _require(
                    summary[key] == expected[service][key],
                    "A previously inspected resource was replaced.",
                )
            if phase == "ready":
                _require(
                    summary["network_id"] == expected[service]["network_id"],
                    "The original task network was replaced.",
                )
        actual[service] = summary
    _require(set(actual) == set(SERVICES), "The nine-service membership differs.")
    return actual


def _json(path: Path) -> object:
    _require(path.stat().st_size <= _MAX_JSON, "Operator metadata exceeds its bound.")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            _require(key not in result, "Duplicate JSON metadata keys are forbidden.")
            result[key] = value
        return result

    return cast(object, json.loads(path.read_bytes(), object_pairs_hook=pairs))


def _regular(path: Path) -> None:
    _require(
        path.resolve(strict=True) == path and stat.S_ISREG(path.lstat().st_mode),
        "Only exact regular operator files are allowed.",
    )
    _require(path.stat().st_uid == os.getuid(), "Operator files must belong to this user.")
    _require(path.stat().st_size <= _MAX_JSON, "Operator files exceed their fixed byte bound.")


class _Exercise:
    def __init__(self, plan: dict[str, Any], repository: Path, output: Path) -> None:
        self.plan, self.repository, self.output = plan, repository, output
        self.started, self.sequence = time.monotonic(), 0
        self.stage = "preflight"
        self.deadline = self.started + 600
        self.mutated = False
        self.original: dict[str, Any] | None = None
        self.images: dict[str, str] = {}
        self.allowed_tmpfs: dict[str, frozenset[str]] = {}
        self.operator_hashes: dict[Path, str] = {}
        _require(
            plan["project"] == _project(), "The exercise differs from the selected task project."
        )
        self.compose = [
            "compose",
            "--project-name",
            plan["project"],
            "--env-file",
            plan["env_file"],
        ]
        for path in plan["compose_files"]:
            self.compose.extend(["--file", path])

    def event(self, name: str, **details: Any) -> None:
        self.sequence += 1
        path = self.output / f"{self.sequence:03d}-{name}.json"
        with path.open("x", encoding="utf8") as target:
            target.write(
                json.dumps(
                    {"elapsed_seconds": time.monotonic() - self.started, **details},
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            )
        path.chmod(0o600)

    def remaining(self, limit: float = 30) -> float:
        value = min(limit, self.deadline - time.monotonic())
        if value <= 0:
            raise TimeoutError("The fixed 600-second exercise budget expired.")
        return value

    def command(self, arguments: list[str], *, docker: bool = True, timeout: float = 30) -> str:
        binary = "/usr/bin/docker" if docker else "/usr/bin/git"
        result = subprocess.run(  # noqa: S603 -- fixed binaries and finite internal call sites.
            [binary, *arguments],
            cwd=self.repository,
            capture_output=True,
            text=True,
            timeout=self.remaining(timeout),
            check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
        _require(
            result.returncode == 0,
            "A fixed operator command failed; output is intentionally not echoed.",
        )
        _require(len(result.stdout) <= 8 * _MAX_JSON, "Operator output exceeds its bound.")
        return result.stdout

    def source(self) -> None:
        _require(
            self.command(["rev-parse", "HEAD"], docker=False).strip() == self.plan["source_commit"],
            "The committed source changed.",
        )
        _require(
            self.command(["rev-parse", "HEAD^{tree}"], docker=False).strip()
            == self.plan["source_tree"],
            "The source tree differs.",
        )
        _require(
            not self.command(["status", "--porcelain=v1", "--untracked-files=all"], docker=False),
            "A clean committed checkout is required.",
        )
        for path, digest in self.operator_hashes.items():
            _require(
                hashlib.sha256(path.read_bytes()).hexdigest() == digest,
                "An operator input changed during the exercise.",
            )

    def inspect(self, phase: str, *, expected: bool = True) -> dict[str, Any]:
        identifiers = self.command(
            [
                "ps",
                "--all",
                "--quiet",
                "--no-trunc",
                "--filter",
                "label=com.docker.compose.project=" + self.plan["project"],
            ]
        ).split()
        _require(
            len(identifiers) == 9 and all(_HEX64.fullmatch(value) for value in identifiers),
            "The task project does not contain exactly nine service containers.",
        )
        rows = json.loads(self.command(["inspect", *identifiers]))
        return validate_containers(
            rows,
            self.plan,
            self.images,
            self.repository,
            phase=phase,
            expected=self.original if expected else None,
            allowed_tmpfs=self.allowed_tmpfs,
        )

    def mutate(self, arguments: list[str]) -> None:
        self.source()
        self.inspect("owned")
        self.mutated = True
        self.command([*self.compose, *arguments], timeout=90)

    def preflight(self, task_root: Path) -> None:
        import yaml

        from scripts.build_release_evidence import _build_binding, validate_image_inventory

        files = [Path(name) for name in self.plan["compose_files"]]
        _require(files[0] == self.repository / "compose.yaml", "The source Compose file differs.")
        files += [
            Path(self.plan[name])
            for name in ("env_file", "image_inventory", "build_receipt", "original_build_receipt")
        ]
        for path in files:
            _regular(path)
            _require(
                path == self.repository / "compose.yaml" or path.is_relative_to(task_root),
                "Private operator inputs must remain under this task directory.",
            )
            self.operator_hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.source()
        source_compose = files[0].read_bytes()
        _require(
            hashlib.sha256(source_compose).hexdigest() == self.operator_hashes[files[0]],
            "The verified source Compose bytes changed before policy derivation.",
        )
        self.allowed_tmpfs = compose_tmpfs_destinations(yaml.safe_load(source_compose))
        inventory = _json(Path(self.plan["image_inventory"]))
        validate_image_inventory(inventory, self.plan["source_commit"], self.plan["source_tree"])
        binding = _build_binding(
            _json(Path(self.plan["build_receipt"])),
            inventory,
            self.plan["source_commit"],
            self.plan["source_tree"],
        )
        _require(
            binding["original_receipt_sha256"]
            == self.operator_hashes[Path(self.plan["original_build_receipt"])],
            "The original build receipt hash differs.",
        )
        self.images = cast(dict[str, str], binding["image_ids"])
        configured = _object(
            json.loads(self.command([*self.compose, "config", "--format", "json"]))
        )
        services = _object(configured.get("services"))
        _require(
            set(services) == set(SERVICES),
            "The Compose configuration must contain exactly nine services.",
        )
        _require(
            compose_tmpfs_destinations(configured) == self.allowed_tmpfs,
            "Private Compose overrides cannot change the committed source scratch policy.",
        )
        for configuration in services.values():
            config = _object(configuration)
            _require(not config.get("profiles"), "Profile-dependent services are forbidden.")
            _require(config.get("image"), "Every service must use an already built explicit image.")
        self.original = self.inspect("ready", expected=False)
        volume = _object(
            json.loads(self.command(["volume", "inspect", self.plan["postgres_volume"]]))[0]
        )
        labels = _object(volume.get("Labels"))
        _require(
            volume.get("Driver") == "local" and not volume.get("Options"),
            "Only the original local task volume is supported.",
        )
        _require(
            labels.get("com.docker.compose.project") == self.plan["project"]
            and labels.get("com.docker.compose.volume") == "postgres-data",
            "The authoritative volume is not owned by this project.",
        )
        self.volume = {
            key: volume.get(key) for key in ("Name", "Driver", "CreatedAt", "Mountpoint", "Scope")
        }
        self.event(
            "preflight",
            source_commit=self.plan["source_commit"],
            source_tree=self.plan["source_tree"],
            build_binding_sha256=self.operator_hashes[Path(self.plan["build_receipt"])],
            containers=self.original,
            volume=self.volume,
            source_tmpfs_destinations={
                service: sorted(destinations)
                for service, destinations in self.allowed_tmpfs.items()
            },
            operator_input_sha256={
                str(path): digest for path, digest in self.operator_hashes.items()
            },
        )

    def ready(self) -> None:
        import httpx

        while True:
            self.remaining()
            self.inspect("owned")
            try:
                state = self.inspect("ready")
                with httpx.Client(trust_env=False, timeout=self.remaining(3)) as client:
                    for service, path in (
                        ("api", "/health/ready"),
                        ("mcp", "/health/ready"),
                        ("web", "/sign-in"),
                    ):
                        response = client.get(
                            f"http://127.0.0.1:{self.plan['ports'][service]}{path}"
                        )
                        _require(
                            response.status_code == 200, "A restarted HTTP service is unavailable."
                        )
                self.event("ready", containers=state)
                return
            except (ValueError, httpx.HTTPError):
                time.sleep(min(0.5, self.remaining()))


def _wire(value: object) -> object:
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
    if isinstance(value, Decimal):
        return {"decimal": str(value)}
    if isinstance(value, datetime):
        return {"utc": value.astimezone(UTC).isoformat(timespec="microseconds")}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    if isinstance(value, UUID):
        return {"uuid": str(value)}
    if isinstance(value, Mapping):
        return {str(key): _wire(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_wire(item) for item in value]
    return value


def _finance(sessions: Any) -> dict[str, Any]:
    from sqlalchemy import select
    from trading212_persistence import models

    result = {}
    for name in (
        "TransactionModel",
        "CashFlowModel",
        "DividendModel",
        "OrderObservationModel",
        "PositionObservationModel",
        "CashBalanceObservationModel",
        "LedgerEntryModel",
        "CalculationRunModel",
        "PortfolioSnapshotModel",
        "SnapshotPositionModel",
        "SnapshotCashModel",
        "ReconciliationRunModel",
        "ReconciliationDiscrepancyModel",
    ):
        table = getattr(models, name).__table__
        digest, count = hashlib.sha256(), 0
        with sessions() as session:
            for row in session.execute(
                select(table).order_by(*table.primary_key).limit(100_001),
                execution_options={"yield_per": 64},
            ):
                encoded = json.dumps(
                    _wire(tuple(row)), sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()
                digest.update(len(encoded).to_bytes(8, "big") + encoded)
                count += 1
                _require(
                    count <= 100_000, "The synthetic witness table exceeds its harness row bound."
                )
        result[table.name] = {"rows": count, "sha256": digest.hexdigest()}
    return result


def _projection(sessions: Any, run_id: str) -> dict[str, Any]:
    from sqlalchemy import func, select
    from trading212_domain.projection_serialization import decode_projection_result
    from trading212_persistence.premium_models import (
        PremiumJobModel,
        PremiumOutboxModel,
        PremiumRunModel,
    )
    from trading212_persistence.projection_models import (
        ProjectionChunkModel,
        ProjectionInputModel,
        ProjectionPathModel,
        ProjectionPointAssetModel,
        ProjectionPointModel,
        ProjectionResultModel,
        ProjectionRunModel,
    )

    identifier = UUID(run_id)
    with sessions() as session:
        run = session.get_one(ProjectionRunModel, identifier)
        root = session.get_one(PremiumRunModel, identifier)
        job = session.scalars(
            select(PremiumJobModel).where(PremiumJobModel.run_id == identifier)
        ).one()
        outbox = session.scalars(
            select(PremiumOutboxModel).where(PremiumOutboxModel.job_id == job.id)
        ).one()
        inputs = session.scalars(
            select(ProjectionInputModel).where(ProjectionInputModel.run_id == identifier)
        ).one()
        result = session.scalars(
            select(ProjectionResultModel).where(ProjectionResultModel.run_id == identifier)
        ).one_or_none()
        counts = {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.run_id == identifier)
            )
            for model in (
                ProjectionInputModel,
                ProjectionResultModel,
                ProjectionChunkModel,
                ProjectionPathModel,
                ProjectionPointModel,
                ProjectionPointAssetModel,
            )
        }
        paths = [
            tuple(row)
            for row in session.execute(
                select(ProjectionPathModel.variant, ProjectionPathModel.path_index)
                .where(ProjectionPathModel.run_id == identifier)
                .order_by(ProjectionPathModel.variant, ProjectionPathModel.path_index)
            )
        ]
        terminal = None
        if result is not None:
            digest = hashlib.sha256(result.canonical_result).hexdigest()
            _require(
                digest == result.content_digest
                and len(result.canonical_result) == result.byte_length
                and result.sealed,
                "The retained canonical result differs from its sealed header.",
            )
            parsed = decode_projection_result(result.canonical_result)
            _require(
                parsed.input_digest == run.numerical_input_digest == result.input_digest,
                "The result differs from the originally selected numerical input.",
            )
            _require(
                paths == [("baseline", index) for index in range(7)],
                "The exact baseline path partition differs.",
            )
            terminal = {"id": str(result.id), "sha256": digest, "bytes": result.byte_length}
        return {
            "id": run_id,
            "job_id": str(job.id),
            "owner_id": str(root.owner_id),
            "account_id": str(root.account_id),
            "state": job.state,
            "consumer_attempts": job.consumer_attempts,
            "capture_digest": run.capture_digest,
            "numerical_input_digest": run.numerical_input_digest,
            "capture_bytes_sha256": hashlib.sha256(inputs.canonical_capture).hexdigest(),
            "input_bytes_sha256": hashlib.sha256(inputs.canonical_input).hexdigest(),
            "outbox_id": str(outbox.id),
            "outbox_state": outbox.state,
            "publication_attempts": outbox.publication_attempts,
            "counts": counts,
            "paths": paths,
            "result": terminal,
        }


def _request(
    exercise: _Exercise, client: Any, method: str, path: str, *, status: int = 200, **arguments: Any
) -> dict[str, Any]:
    response = client.request(method, path, timeout=exercise.remaining(5), **arguments)
    _require(
        response.status_code == status and len(response.content) <= _MAX_JSON,
        "A fixed local API operation returned an unexpected status or size.",
    )
    return _object(response.json())


def _run(exercise: _Exercise) -> None:
    import httpx
    from sqlalchemy import func, select
    from sqlalchemy.engine import make_url
    from trading212_api_contracts.projections import (
        AssumptionSetResponse,
        ProjectionOperationalRunResponse,
        ProjectionRunResponse,
    )
    from trading212_domain import build_synthetic_identity
    from trading212_persistence import create_database_engine, create_session_factory
    from trading212_persistence.models import OwnerModel
    from trading212_persistence.premium_models import PremiumJobModel
    from trading212_persistence.report_models import ReportJobModel

    database_url = os.environ.get("DATABASE_URL", "")
    url = make_url(database_url)
    _require(
        (url.drivername, url.host, url.port, url.database, url.username, url.password)
        == ("postgresql+psycopg", "127.0.0.1", 55432, "portfolio", "portfolio", "portfolio"),
        "Only the exact synthetic task database is authorized.",
    )
    _require(not url.query, "Database connection options must be fixed by this driver.")
    engine = create_database_engine(
        url.update_query_dict(
            {"connect_timeout": "3", "options": "-c statement_timeout=5000 -c lock_timeout=5000"}
        )
    )
    sessions = create_session_factory(engine)
    account = str(build_synthetic_identity().account.id)
    try:
        exercise.stage = "synthetic-database-boundary"
        with sessions() as stored:
            _require(
                set(stored.scalars(select(OwnerModel.id))) == {build_synthetic_identity().owner.id},
                "The witness requires the exact synthetic owner database.",
            )
            for model in (PremiumJobModel, ReportJobModel):
                _require(
                    stored.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.state.in_(("queued", "running")))
                    )
                    == 0,
                    "Existing queued/running work must finish before this exercise.",
                )
        with httpx.Client(base_url="http://127.0.0.1:58000", trust_env=False, timeout=5) as client:
            session = _request(exercise, client, "POST", "/api/v1/auth/local-session", status=201)
            csrf = session["csrf_token"]
            headers = {
                "Origin": f"http://localhost:{exercise.plan['ports']['web']}",
                "X-CSRF-Token": csrf,
                "X-Idempotency-Key": "stack-assumptions-" + uuid4().hex,
            }
            created = _request(
                exercise,
                client,
                "POST",
                f"/api/v1/accounts/{account}/assumption-sets",
                status=201,
                headers=headers,
                json={
                    "metadata": {
                        "name": "Synthetic restart witness",
                        "description": "One modeled projection family; no acquired provider input",
                    },
                    "content": {
                        "assets": [
                            {
                                "key": "modeled",
                                "annual_mean_log_return": "0.04",
                                "annual_volatility": "0.1",
                                "weight": "1",
                            }
                        ],
                        "correlation": [["1"]],
                        "reporting_currency": "EUR",
                        "annual_inflation": "0.02",
                        "annual_fee": "0.001",
                        "annual_tax_drag": "0.002",
                    },
                },
            )
            definition = AssumptionSetResponse.model_validate(created)
            body = {
                "assumption_version_id": definition.current_version_id,
                "initial_basis": {
                    "kind": "modeled_value",
                    "modeled_value": {"amount": "100.123456789012345678", "currency": "EUR"},
                    "modeled_anchor_date": datetime.now(UTC).date().isoformat(),
                },
                "schedule": {
                    "base_monthly": {"amount": "10", "currency": "EUR"},
                    "annual_growth": "0",
                    "paused_dates": [],
                    "entries": [],
                },
                "seed": 23,
                "months": 3,
                "paths": 7,
                "retained_months": [0, 1, 2, 3],
                "allocation": [{"key": "modeled", "weight": "1"}],
            }

            def admit() -> str:
                value = _request(
                    exercise,
                    client,
                    "POST",
                    f"/api/v1/accounts/{account}/projection-runs",
                    status=202,
                    headers={**headers, "X-Idempotency-Key": "stack-run-" + uuid4().hex},
                    json=body,
                )
                return ProjectionOperationalRunResponse.model_validate(value).id

            def completed(run_id: str) -> None:
                while True:
                    response = ProjectionRunResponse.model_validate(
                        _request(exercise, client, "GET", f"/api/v1/projection-runs/{run_id}")
                    )
                    _require(
                        response.state not in {"failed", "cancelled", "expired"},
                        "The real worker did not complete the retained projection.",
                    )
                    if response.state == "succeeded":
                        _require(
                            response.result_availability == "available",
                            "A succeeded projection lacks its canonical result.",
                        )
                        return
                    time.sleep(min(0.25, exercise.remaining()))

            exercise.stage = "baseline-worker-completion"
            baseline_id = admit()
            completed(baseline_id)
            baseline = _projection(sessions, baseline_id)
            _require(
                baseline["consumer_attempts"] == 1 and baseline["result"] is not None,
                "The baseline worker did not publish one result.",
            )
            exercise.event("baseline", projection=baseline)
            exercise.stage = "durable-pending-admission"
            exercise.mutate(["stop", "--timeout", "30", "worker", "dispatcher"])
            stopped_consumers = exercise.inspect("owned")
            _require(
                all(
                    stopped_consumers[name]["running"] is False for name in ("worker", "dispatcher")
                ),
                "Consumers must be stopped before queue admission.",
            )
            pending_id = admit()
            pending = _projection(sessions, pending_id)
            _require(
                pending_id != baseline_id
                and pending["state"] == "queued"
                and pending["outbox_state"] == "pending"
                and pending["consumer_attempts"] == pending["publication_attempts"] == 0
                and pending["counts"]["projection_results"] == 0,
                "The pending witness was not durably queued without consumption.",
            )
            finance = _finance(sessions)
            exercise.event(
                "durable-boundary", baseline=baseline, pending=pending, economic_tables=finance
            )
            engine.dispose()
            restart_started = time.monotonic()
            exercise.stage = "all-nine-stop"
            exercise.mutate(["stop", "--timeout", "30", *SERVICES])
            exercise.event("all-nine-stopped", containers=exercise.inspect("stopped"))
            exercise.stage = "same-resource-restart"
            exercise.mutate(
                ["up", "--detach", "--no-build", "--pull", "never", "--no-recreate", *SERVICES]
            )
            exercise.ready()
            # Reauthenticate normally after restart; never persist session secrets.
            session = _request(exercise, client, "POST", "/api/v1/auth/local-session", status=201)
            exercise.stage = "recovered-worker-completion"
            completed(pending_id)
            recovered = _projection(sessions, pending_id)
            _require(
                _projection(sessions, baseline_id) == baseline,
                "The retained pre-restart projection changed.",
            )
            _require(
                _finance(sessions) == finance, "Canonical economic rows changed during restart."
            )
            for key in (
                "id",
                "job_id",
                "owner_id",
                "account_id",
                "capture_digest",
                "numerical_input_digest",
                "capture_bytes_sha256",
                "input_bytes_sha256",
                "outbox_id",
            ):
                _require(
                    recovered[key] == pending[key],
                    "The recovered job differs from its original durable input.",
                )
            _require(
                recovered["result"] is not None
                and recovered["consumer_attempts"] == 1
                and recovered["counts"]["projection_results"] == 1,
                "Recovery did not publish exactly one result.",
            )
            _require(
                recovered["result"]["sha256"] == baseline["result"]["sha256"],
                "Identical retained inputs did not reproduce the pre-stop canonical result.",
            )
            recovery_seconds = time.monotonic() - restart_started
            _require(recovery_seconds <= 600, "The original local recovery target was exceeded.")
            exercise.event(
                "recovered",
                projection=recovered,
                recovery_seconds=recovery_seconds,
                economic_tables=finance,
            )
            exercise.stage = "duplicate-transport-verification"
            _redeliver(exercise, sessions, recovered)
            _require(
                _projection(sessions, baseline_id) == baseline
                and _projection(sessions, pending_id) == recovered
                and _finance(sessions) == finance,
                "Duplicate delivery changed a retained result or economic rows.",
            )
            volume = _object(
                json.loads(
                    exercise.command(["volume", "inspect", exercise.plan["postgres_volume"]])
                )[0]
            )
            _require(
                {key: volume.get(key) for key in exercise.volume} == exercise.volume,
                "The original volume identity changed.",
            )
            exercise.source()
            final_containers = exercise.inspect("ready")
            total_seconds = time.monotonic() - exercise.started
            _require(
                total_seconds <= 600,
                "The original total exercise budget was exceeded.",
            )
            exercise.event(
                "verified",
                containers=final_containers,
                recovery_seconds=recovery_seconds,
                total_seconds=total_seconds,
                volume=exercise.volume,
                scope=(
                    "all nine services; retained and pending modeled projections only; "
                    "no all-family or production claim"
                ),
            )
    finally:
        engine.dispose()


def _redeliver(exercise: _Exercise, sessions: Any, recovered: dict[str, Any]) -> None:
    from celery import Celery  # type: ignore[import-untyped]
    from redis import Redis
    from trading212_application.projection_jobs import PROJECTION_TASK_NAME, ProjectionTaskMessage

    application = Celery("phase3-stack-restart-witness", broker="redis://127.0.0.1:56379/0")
    application.conf.update(
        task_serializer="json",
        accept_content=["json"],
        broker_connection_retry_on_startup=False,
        broker_connection_max_retries=0,
        broker_connection_timeout=3,
        broker_transport_options={"socket_timeout": 2, "socket_connect_timeout": 2},
    )
    redis = Redis(host="127.0.0.1", port=56379, db=0, socket_timeout=2, socket_connect_timeout=2)
    try:
        registered = application.control.inspect(timeout=min(3, exercise.remaining())).registered()
        _require(
            isinstance(registered, dict)
            and len(registered) == 1
            and PROJECTION_TASK_NAME in next(iter(registered.values())),
            "Exactly one real registered task consumer is required.",
        )
        _require(
            redis.llen("celery") == redis.hlen("unacked") == 0,
            "Duplicate transport verification requires an idle task broker.",
        )
        payload = ProjectionTaskMessage(
            job_id=recovered["job_id"],
            run_id=recovered["id"],
            owner_id=recovered["owner_id"],
            account_id=recovered["account_id"],
            input_digest=recovered["capture_digest"],
        )
        published = application.send_task(
            PROJECTION_TASK_NAME,
            kwargs=payload.to_wire(),
            task_id=payload.job_id,
            retry=False,
            priority=0,
        )
        _require(
            published.id == payload.job_id,
            "Duplicate publication changed the original task identity.",
        )
        samples, idle = [], 0
        while idle < 3:
            sample = {
                "elapsed_seconds": time.monotonic() - exercise.started,
                "queued": redis.llen("celery"),
                "unacknowledged": redis.hlen("unacked"),
            }
            samples.append(sample)
            idle = idle + 1 if sample["queued"] == sample["unacknowledged"] == 0 else 0
            time.sleep(min(0.25, exercise.remaining()))
        _require(
            _projection(sessions, recovered["id"]) == recovered,
            "The duplicate transport delivery changed canonical state.",
        )
        exercise.event(
            "duplicate-transport",
            task_name=PROJECTION_TASK_NAME,
            job_id=payload.job_id,
            samples=samples,
            scope=(
                "fixed metadata published to the real broker; late-ack transport drained; "
                "canonical state unchanged"
            ),
        )
    finally:
        redis.close()
        application.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    arguments = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    plan_path, output = arguments.plan.absolute(), arguments.evidence_dir.absolute()
    _regular(plan_path)
    _require(
        not plan_path.is_relative_to(repository)
        and output.is_relative_to(plan_path.parent)
        and not output.is_relative_to(repository),
        "Evidence and operator metadata must remain private outside the checkout.",
    )
    _require(output.resolve() == output, "Evidence symlinks are forbidden.")
    output.mkdir(mode=0o700)
    exercise = None
    outcome, error_type = "failed", None
    try:
        plan = validate_plan(_json(plan_path))
        exercise = _Exercise(plan, repository, output)
        exercise.operator_hashes[plan_path] = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        exercise.event(
            "plan", plan=plan, plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest()
        )
        exercise.preflight(plan_path.parent)
        _run(exercise)
        outcome = "passed"
    except BaseException as error:
        error_type = type(error).__name__
        # Never persist exception text, raw HTTP data, cookies, CSRF or Docker Config.Env.
    finally:
        cleanup: dict[str, Any] = {"needed": bool(exercise and exercise.mutated)}
        if exercise is not None and exercise.mutated and outcome != "passed":
            try:
                # Recovery cleanup has its own bounded120s; it does not extend measured RTO.
                exercise.deadline = time.monotonic() + 120
                exercise.mutate(
                    ["up", "--detach", "--no-build", "--pull", "never", "--no-recreate", *SERVICES]
                )
                exercise.ready()
                cleanup["services_restored"] = True
            except BaseException as error:
                cleanup.update(services_restored=False, error_type=type(error).__name__)
        receipt = {
            "scope": "focused_local_preacceptance",
            "outcome": outcome,
            "error_type": error_type,
            "cleanup": cleanup,
            "formal_phase3_acceptance": "pending",
            "all_premium_family_recovery": "unverified",
            "last_stage": exercise.stage if exercise is not None else "plan-validation",
        }
        if exercise is not None:
            exercise.event("terminal", **receipt)
        else:
            with (output / "terminal.json").open("x", encoding="utf8") as target:
                target.write(json.dumps(receipt, sort_keys=True) + "\n")
            (output / "terminal.json").chmod(0o600)
    print(
        json.dumps(
            {"outcome": outcome, "error_type": error_type, "evidence_dir": str(output)},
            sort_keys=True,
        )
    )
    return 0 if outcome == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
