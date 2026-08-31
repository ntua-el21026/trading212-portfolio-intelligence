#!/usr/bin/env python3
"""Enforce the initial Python dependency direction using import syntax."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_IMPORTS = {
    "packages/domain": {
        "fastapi",
        "mcp",
        "sqlalchemy",
        "trading212_api",
        "trading212_application",
        "trading212_mcp",
        "trading212_persistence",
        "trading212_provider",
        "trading212_worker",
    },
    "packages/analytics": {"fastapi", "mcp", "sqlalchemy", "trading212_provider"},
    "packages/api-contracts": {"sqlalchemy", "trading212_provider"},
}


def imported_roots(path: Path) -> set[str]:
    """Return top-level import names from one Python source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.partition(".")[0])
    return imports


def validate_architecture() -> list[str]:
    """Return forbidden dependency findings."""
    failures: list[str] = []
    for relative, forbidden in FORBIDDEN_IMPORTS.items():
        for path in sorted((ROOT / relative).rglob("*.py")):
            for imported in sorted(imported_roots(path) & forbidden):
                failures.append(f"{path.relative_to(ROOT)} imports forbidden dependency {imported}")
    return failures


def main() -> int:
    """Run architecture validation."""
    failures = validate_architecture()
    if failures:
        print("Architecture dependency validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Architecture dependency validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
