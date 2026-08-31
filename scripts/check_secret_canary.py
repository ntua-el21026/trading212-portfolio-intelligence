#!/usr/bin/env python3
"""Assert that a runtime-only secret canary is absent from selected artifacts."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

CANARY_ENVIRONMENT_VARIABLE = "PHASE1_SECRET_CANARY"
MINIMUM_CANARY_BYTES = 16
REPOSITORY_SCAN_EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".hypothesis",
        ".mypy_cache",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "htmlcov",
        "node_modules",
        "playwright-report",
        "test-results",
        "venv",
    }
)


def find_canary_occurrences(
    paths: Iterable[Path],
    canary: bytes,
    *,
    excluded_directory_names: frozenset[str] = frozenset(),
) -> tuple[Path, ...]:
    """Return regular files containing ``canary`` without following symlinks."""

    if len(canary) < MINIMUM_CANARY_BYTES:
        raise ValueError(f"secret canary must be at least {MINIMUM_CANARY_BYTES} bytes")
    findings: list[Path] = []
    for path in paths:
        if path.is_symlink() or not path.exists():
            continue
        if path.is_file():
            if canary in path.read_bytes():
                findings.append(path)
            continue
        for directory, directory_names, file_names in os.walk(path, followlinks=False):
            directory_names[:] = sorted(
                name
                for name in directory_names
                if name not in excluded_directory_names
                and not (Path(directory) / name).is_symlink()
            )
            for file_name in sorted(file_names):
                candidate = Path(directory) / file_name
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                if canary in candidate.read_bytes():
                    findings.append(candidate)
    return tuple(findings)


def _canary_from_environment() -> bytes:
    value = os.environ.get(CANARY_ENVIRONMENT_VARIABLE)
    if value is None:
        raise ValueError(f"{CANARY_ENVIRONMENT_VARIABLE} must be set")
    return value.encode("utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if not arguments:
        print("usage: check_secret_canary.py PATH [PATH ...]", file=sys.stderr)
        return 2
    try:
        canary = _canary_from_environment()
        paths = tuple(Path(value) for value in arguments)
        missing = tuple(path for path in paths if not path.exists())
        if missing:
            rendered = ", ".join(str(path) for path in missing)
            raise ValueError(f"scan path does not exist: {rendered}")
        findings = find_canary_occurrences(paths, canary)
    except (OSError, ValueError) as exc:
        print(f"Secret-canary scan could not complete: {exc}", file=sys.stderr)
        return 2
    if findings:
        print("Secret canary found in forbidden artifact paths:", file=sys.stderr)
        for path in findings:
            print(f"- {path}", file=sys.stderr)
        return 1
    print(f"Secret-canary absence scan passed for {len(arguments)} path(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
