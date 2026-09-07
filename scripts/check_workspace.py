#!/usr/bin/env python3
"""Validate the reproducible P1-01 workspace and dependency contract."""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_DIRECT_PYTHON = {
    "alembic": "1.19.1",
    "celery": "5.6.3",
    "coverage": "7.16.0",
    "cryptography": "50.0.1",
    "fastapi": "0.141.1",
    "httpx": "0.28.1",
    "hypothesis": "6.167.1",
    "mcp": "2.1.1",
    "mypy": "2.3.1",
    "opentelemetry-api": "1.44.0",
    "opentelemetry-sdk": "1.44.0",
    "prometheus-client": "0.26.0",
    "psycopg": "3.3.4",
    "pydantic": "2.13.5",
    "pydantic-settings": "2.15.0",
    "pyjwt": "2.13.0",
    "pytest": "9.1.1",
    "pytest-asyncio": "1.4.0",
    "pyyaml": "6.0.3",
    "ruff": "0.16.5",
    "sqlalchemy": "2.0.52",
    "structlog": "26.1.0",
}

REQUIRED_DIRECT_NODE = {
    "@playwright/test": "1.62.1",
    "@testing-library/jest-dom": "7.0.1",
    "@testing-library/react": "16.3.3",
    "@testing-library/user-event": "14.6.6",
    "@typescript/typescript6": "6.0.2",
    "@vitejs/plugin-react": "6.1.1",
    "decimal.js": "10.6.0",
    "eslint": "10.9.1",
    "eslint-config-next": "16.3.3",
    "lucide-react": "1.38.0",
    "next": "16.3.3",
    "react": "19.2.8",
    "react-dom": "19.2.8",
    "recharts": "3.10.1",
    "typescript": "7.0.2",
    "vitest": "4.1.11",
    "zod": "4.5.4",
}

REQUIRED_DIRECTORIES = (
    "apps/api",
    "apps/mcp",
    "apps/web",
    "apps/worker",
    "packages/analytics",
    "packages/api-contracts",
    "packages/application",
    "packages/domain",
    "packages/observability",
    "packages/persistence",
    "packages/reference-data",
    "packages/security",
    "packages/trading212",
    "packages/ui",
)

REQUIRED_MAKE_TARGETS = {
    "bootstrap",
    "build",
    "dev",
    "docs-check",
    "format",
    "format-check",
    "lint",
    "migrate",
    "run-local",
    "security",
    "security-check",
    "seed-demo",
    "stop-local",
    "test",
    "test-contract",
    "test-e2e",
    "test-integration",
    "test-migrations",
    "test-property",
    "test-security",
    "test-unit",
    "typecheck",
    "validate",
}

DEPENDENCY_RE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^;\s]+)")
MAKE_TARGET_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:", re.MULTILINE)


def canonical_name(name: str) -> str:
    """Return the normalized package index name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def iter_python_dependencies() -> Iterable[str]:
    """Yield every declared direct Python dependency across the uv workspace."""
    for path in sorted(ROOT.rglob("pyproject.toml")):
        if any(part in {".venv", "node_modules"} for part in path.parts):
            continue
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        yield from data.get("project", {}).get("dependencies", [])
        for group in data.get("dependency-groups", {}).values():
            yield from group


def direct_python_versions() -> dict[str, set[str]]:
    """Collect exact direct Python package pins."""
    versions: dict[str, set[str]] = {}
    for dependency in iter_python_dependencies():
        match = DEPENDENCY_RE.match(dependency)
        if match is None:
            continue
        name, version = match.groups()
        versions.setdefault(canonical_name(name), set()).add(version)
    return versions


def direct_node_versions() -> dict[str, set[str]]:
    """Collect direct npm dependency pins across every workspace manifest."""
    versions: dict[str, set[str]] = {}
    for path in sorted(ROOT.rglob("package.json")):
        if "node_modules" in path.parts:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for section in ("dependencies", "devDependencies"):
            for name, version in data.get(section, {}).items():
                if version.startswith("workspace:"):
                    continue
                dependency_name = name
                dependency_version = version
                if version.startswith("npm:"):
                    target = version.removeprefix("npm:")
                    dependency_name, _, dependency_version = target.rpartition("@")
                versions.setdefault(dependency_name, set()).add(dependency_version)
    return versions


def validate_workspace() -> list[str]:
    """Return deterministic contract failures; an empty list means success."""
    failures: list[str] = []

    if (ROOT / ".python-version").read_text(encoding="utf-8").strip() != "3.13.15":
        failures.append(".python-version must pin 3.13.15")
    if (ROOT / ".node-version").read_text(encoding="utf-8").strip() != "24.20.0":
        failures.append(".node-version must pin 24.20.0")
    if (ROOT / ".uv-version").read_text(encoding="utf-8").strip() != "0.12.7":
        failures.append(".uv-version must pin uv 0.12.7")

    root_package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    if root_package.get("packageManager") != "pnpm@10.34.5":
        failures.append("packageManager must pin pnpm@10.34.5")

    for relative in REQUIRED_DIRECTORIES:
        if not (ROOT / relative).is_dir():
            failures.append(f"missing architecture directory: {relative}")

    for relative in ("uv.lock", "pnpm-lock.yaml", "compose.yaml", "Makefile"):
        if not (ROOT / relative).is_file():
            failures.append(f"missing reproducibility artifact: {relative}")

    source_contract = ROOT / "config/contracts/trading212-read-allowlist.yaml"
    packaged_contract = (
        ROOT
        / "packages/trading212/src/trading212_provider/contracts/trading212-read-allowlist.yaml"
    )
    if source_contract.read_bytes() != packaged_contract.read_bytes():
        failures.append("packaged Trading 212 allowlist must exactly match the root contract")

    python_versions = direct_python_versions()
    for name, expected in REQUIRED_DIRECT_PYTHON.items():
        actual = python_versions.get(name, set())
        if actual != {expected}:
            failures.append(
                f"Python direct pin {name} must be exactly {expected}; got {sorted(actual)}"
            )

    node_versions = direct_node_versions()
    for name, expected in REQUIRED_DIRECT_NODE.items():
        actual = node_versions.get(name, set())
        if actual != {expected}:
            failures.append(
                f"npm direct pin {name} must be exactly {expected}; got {sorted(actual)}"
            )

    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    for required in (
        "image: t212pi-postgres:18.6-hardened",
        "image: t212pi-redis:8.10.1-hardened",
        "non-authoritative",
    ):
        if required not in compose:
            failures.append(f"compose contract missing: {required}")

    hardened_bases = {
        "infrastructure/docker/postgres.Dockerfile": "FROM postgres:18.6",
        "infrastructure/docker/redis.Dockerfile": "FROM redis:8.10.1",
    }
    for relative, required_base in hardened_bases.items():
        dockerfile = (ROOT / relative).read_text(encoding="utf-8")
        if required_base not in dockerfile:
            failures.append(f"hardened image base missing: {relative} -> {required_base}")

    makefile = (
        (ROOT / "Makefile").read_text(encoding="utf-8") if (ROOT / "Makefile").exists() else ""
    )
    actual_targets = set(MAKE_TARGET_RE.findall(makefile))
    for target in sorted(REQUIRED_MAKE_TARGETS - actual_targets):
        failures.append(f"Makefile target missing: {target}")

    return failures


def main() -> int:
    """Validate and print a concise machine-friendly result."""
    failures = validate_workspace()
    if failures:
        print(f"Workspace validation failed with {len(failures)} issue(s):")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("P1-01 workspace contract passed.")
    print(
        f"Validated {len(REQUIRED_DIRECT_PYTHON)} Python pins, "
        f"{len(REQUIRED_DIRECT_NODE)} npm pins, and {len(REQUIRED_MAKE_TARGETS)} Make targets."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
