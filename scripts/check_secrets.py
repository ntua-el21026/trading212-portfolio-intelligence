#!/usr/bin/env python3
"""Scan repository files for high-confidence committed secret material."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "dist",
    "node_modules",
}
FORBIDDEN_NAMES = {".env", "id_rsa", "id_ed25519"}
PATTERNS = {
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "GitHub token": re.compile(r"gh(?:p|o|u|s|r)_[A-Za-z0-9]{36,}"),
    "OpenAI-style secret": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def candidate_files() -> list[Path]:
    """Return bounded text-like files outside generated dependency trees."""
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".lock", ".whl", ".gz"}:
            continue
        files.append(path)
    return files


def validate_secrets() -> list[str]:
    """Return high-confidence secret findings."""
    failures: list[str] = []
    for path in candidate_files():
        if path.name in FORBIDDEN_NAMES or path.suffix.lower() in {".key", ".pem", ".p12", ".pfx"}:
            failures.append(f"forbidden secret-bearing filename: {path.relative_to(ROOT)}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                failures.append(f"{label} pattern in {path.relative_to(ROOT)}")
    return failures


def main() -> int:
    """Run the repository secret scan."""
    failures = validate_secrets()
    if failures:
        print("Secret scan failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("High-confidence repository secret scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
