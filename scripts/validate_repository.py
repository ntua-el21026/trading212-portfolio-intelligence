#!/usr/bin/env python3
"""Validate the documentation-first Phase 1 implementation baseline.

The validator intentionally uses only the Python standard library so it can run
before application dependency manifests exist.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "README.md",
    "AGENTS.md",
    "LICENSE.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "PROJECT_STATUS.md",
    "PROJECT_STATUS.json",
    "PROJECT_PROGRESS.json",
    "VALIDATION_REPORT.md",
    ".env.example",
    ".gitignore",
    ".gitattributes",
    ".dockerignore",
    ".github/CODEOWNERS",
    ".github/workflows/documentation-validation.yml",
    "docs/DESIGN_INDEX.md",
    "docs/DESIGN_FREEZE_V0_1.md",
    "docs/DOCUMENT_GOVERNANCE.md",
    "docs/PRODUCT_REQUIREMENTS.md",
    "docs/SCOPE_AND_NON_GOALS.md",
    "docs/SYSTEM_ARCHITECTURE.md",
    "docs/REQUIREMENTS_TRACEABILITY.md",
    "docs/REFERENCES.md",
    "docs/integrations/TRADING212_API_CONTRACT.md",
    "docs/integrations/CHATGPT_MCP_APP.md",
    "docs/integrations/PROVIDER_ADAPTERS.md",
    "docs/analytics/FINANCIAL_CALCULATION_POLICY.md",
    "docs/analytics/PERFORMANCE_ACCOUNTING.md",
    "docs/analytics/DATA_QUALITY_AND_RECONCILIATION.md",
    "docs/security/SECURITY_ARCHITECTURE.md",
    "docs/security/PRIVACY_RETENTION_AUDIT.md",
    "docs/engineering/ENGINEERING_STANDARDS.md",
    "docs/engineering/TEST_STRATEGY.md",
    "docs/engineering/DEPLOYMENT_OPERATIONS.md",
    "docs/implementation/MASTER_IMPLEMENTATION_PLAN.md",
    "docs/implementation/PHASE_1_TECHNICAL_BASELINE.md",
    "docs/implementation/PHASE_1_TRUSTED_FOUNDATION.md",
    "docs/implementation/PHASE_1_EXECUTION_MANIFEST.md",
    "docs/implementation/PHASE_1_ACCEPTANCE_MATRIX.md",
    "docs/implementation/PHASE_1_READINESS_REVIEW.md",
    "docs/implementation/PHASE_2_PORTFOLIO_INTELLIGENCE.md",
    "docs/implementation/PHASE_3_PREMIUM_PRODUCTIZATION.md",
    "docs/implementation/prompts/PHASE_1_CODEX_PROMPT.md",
    "config/contracts/trading212-read-allowlist.yaml",
    "scripts/validate_repository.py",
)

EXPECTED_CAPABILITIES = {
    "account_summary": ("GET", "/equity/account/summary"),
    "metadata_instruments": ("GET", "/equity/metadata/instruments"),
    "metadata_exchanges": ("GET", "/equity/metadata/exchanges"),
    "portfolio_positions": ("GET", "/equity/positions"),
    "pending_orders": ("GET", "/equity/orders"),
    "order_detail": ("GET", "/equity/orders/{order_id}"),
    "historical_orders": ("GET", "/equity/history/orders"),
    "historical_transactions": ("GET", "/equity/history/transactions"),
    "historical_dividends": ("GET", "/equity/history/dividends"),
    "historical_exports": ("GET", "/equity/history/exports"),
}

STALE_ENDPOINTS = (
    "/equity/account/info",
    "/equity/account/cash",
    "/equity/portfolio",
)

AUTHORITATIVE_ENDPOINT_FILES = (
    "README.md",
    "docs/DESIGN_FREEZE_V0_1.md",
    "docs/integrations/TRADING212_API_CONTRACT.md",
    "docs/implementation/PHASE_1_TECHNICAL_BASELINE.md",
    "docs/implementation/prompts/PHASE_1_CODEX_PROMPT.md",
    "config/contracts/trading212-read-allowlist.yaml",
)

TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".py",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".env",
    ".example",
    ".gitignore",
    ".gitattributes",
    ".dockerignore",
}

MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
CAPABILITY_RE = re.compile(r"^\s*-\s+capability:\s*([A-Za-z0-9_-]+)\s*$")
METHOD_RE = re.compile(r"^\s+method:\s*([A-Z]+)\s*$")
PATH_RE = re.compile(r"^\s+path:\s*(\S+)\s*$")


@dataclass(frozen=True)
class Failure:
    check: str
    detail: str


def text_files() -> Iterable[Path]:
    excluded = {".git", ".venv", "node_modules", ".next", "dist", "build"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in excluded for part in path.parts):
            continue
        if path.name in {"CODEOWNERS", "Makefile"} or path.suffix.lower() in TEXT_SUFFIXES:
            yield path


def read_text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def validate_required_files() -> list[Failure]:
    return [
        Failure("required-files", f"missing {relative}")
        for relative in REQUIRED_FILES
        if not (ROOT / relative).is_file()
    ]


def validate_utf8() -> list[Failure]:
    failures: list[Failure] = []
    for path in text_files():
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            failures.append(Failure("utf8", f"{path.relative_to(ROOT)}: {exc}"))
    return failures


def validate_json() -> list[Failure]:
    failures: list[Failure] = []
    for path in ROOT.rglob("*.json"):
        if any(part in {"node_modules", ".next", "dist", "build"} for part in path.parts):
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            failures.append(Failure("json", f"{path.relative_to(ROOT)}: {exc}"))
    return failures


def parse_allowlist(text: str) -> dict[str, tuple[str, str]]:
    parsed: dict[str, tuple[str, str]] = {}
    current: str | None = None
    method: str | None = None
    path: str | None = None

    def flush() -> None:
        nonlocal current, method, path
        if current is not None:
            if method is None or path is None:
                raise ValueError(f"capability {current!r} is missing method or path")
            if current in parsed:
                raise ValueError(f"duplicate capability {current!r}")
            parsed[current] = (method, path)
        current = method = path = None

    for line in text.splitlines():
        capability_match = CAPABILITY_RE.match(line)
        if capability_match:
            flush()
            current = capability_match.group(1)
            continue
        if current is None:
            continue
        method_match = METHOD_RE.match(line)
        if method_match and method is None:
            method = method_match.group(1)
            continue
        path_match = PATH_RE.match(line)
        if path_match and path is None:
            path = path_match.group(1)
    flush()
    return parsed


def validate_allowlist() -> list[Failure]:
    relative = "config/contracts/trading212-read-allowlist.yaml"
    try:
        text = read_text(relative)
        parsed = parse_allowlist(text)
    except (OSError, ValueError) as exc:
        return [Failure("allowlist", f"{relative}: {exc}")]

    failures: list[Failure] = []
    if parsed != EXPECTED_CAPABILITIES:
        failures.append(
            Failure(
                "allowlist",
                f"exact capability registry mismatch; expected {EXPECTED_CAPABILITIES!r}, got {parsed!r}",
            )
        )
    if "default_deny: true" not in text:
        failures.append(Failure("allowlist", "default_deny must be true"))
    if any(method != "GET" for method, _ in parsed.values()):
        failures.append(Failure("allowlist", "every broker capability must use GET"))
    return failures


def validate_endpoint_contract() -> list[Failure]:
    failures: list[Failure] = []
    contract = read_text("docs/integrations/TRADING212_API_CONTRACT.md")
    prompt = read_text("docs/implementation/prompts/PHASE_1_CODEX_PROMPT.md")
    for capability, (method, path) in EXPECTED_CAPABILITIES.items():
        if capability not in contract or f"`{path}`" not in contract:
            failures.append(Failure("endpoint-contract", f"contract missing {capability} {path}"))
        if path not in prompt:
            failures.append(Failure("endpoint-contract", f"Codex prompt missing {path}"))
        if method != "GET":
            failures.append(Failure("endpoint-contract", f"non-GET expected capability {capability}"))

    for relative in AUTHORITATIVE_ENDPOINT_FILES:
        text = read_text(relative)
        for stale in STALE_ENDPOINTS:
            if stale in text:
                failures.append(Failure("endpoint-contract", f"stale endpoint {stale} in {relative}"))
    return failures


def clean_link_target(raw_target: str) -> str | None:
    target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
    if not target or target.startswith(("#", "http://", "https://", "mailto:")):
        return None
    target = target.split("#", 1)[0].split("?", 1)[0]
    return target or None


def validate_markdown_links() -> list[Failure]:
    failures: list[Failure] = []
    for path in ROOT.rglob("*.md"):
        if any(part in {"node_modules", ".next", "dist", "build"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK_RE.findall(text):
            target = clean_link_target(raw_target)
            if target is None:
                continue
            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(ROOT.resolve())
            except ValueError:
                failures.append(Failure("markdown-links", f"{path.relative_to(ROOT)} -> {target} escapes repository"))
                continue
            if not resolved.exists():
                failures.append(Failure("markdown-links", f"{path.relative_to(ROOT)} -> missing {target}"))
    return failures


def validate_env_example() -> list[Failure]:
    failures: list[Failure] = []
    for line_number, line in enumerate(read_text(".env.example").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        sensitive = any(token in key.upper() for token in ("SECRET", "TOKEN", "PASSWORD", "API_KEY", "CREDENTIAL"))
        if sensitive and value.strip():
            failures.append(Failure("env-example", f"line {line_number}: sensitive example {key} must be blank"))
    return failures


def validate_governance_and_prompt() -> list[Failure]:
    failures: list[Failure] = []
    agents = read_text("AGENTS.md")
    freeze = read_text("docs/DESIGN_FREEZE_V0_1.md")
    prompt = read_text("docs/implementation/prompts/PHASE_1_CODEX_PROMPT.md")
    progress = json.loads(read_text("PROJECT_PROGRESS.json"))

    required_agent_phrases = ("directly to `main`", "Never force-push", "strictly read-only")
    for phrase in required_agent_phrases:
        if phrase not in agents:
            failures.append(Failure("governance", f"AGENTS.md missing phrase: {phrase}"))

    for phrase in ("Status:** Accepted", "Phase 1", "strictly read-only"):
        if phrase not in freeze:
            failures.append(Failure("governance", f"design freeze missing phrase: {phrase}"))

    for token in ("P1-01", "P1-12", "work directly on `main`", "Do not implement any broker `POST`", "Stop after Phase 1"):
        if token not in prompt:
            failures.append(Failure("codex-prompt", f"Phase 1 prompt missing token: {token}"))

    packages = progress.get("phases", {}).get("phase_1", {}).get("work_packages", {})
    expected_package_ids = {f"P1-{number:02d}" for number in range(1, 13)}
    if set(packages) != expected_package_ids:
        failures.append(Failure("progress", "PROJECT_PROGRESS.json must contain exactly P1-01 through P1-12"))
    return failures


def validate_case_collisions() -> list[Failure]:
    seen: dict[str, Path] = {}
    failures: list[Failure] = []
    for path in ROOT.rglob("*"):
        if ".git" in path.parts:
            continue
        relative = path.relative_to(ROOT)
        key = str(relative).casefold()
        prior = seen.get(key)
        if prior is not None and prior != relative:
            failures.append(Failure("case-collision", f"{prior} conflicts with {relative}"))
        else:
            seen[key] = relative
    return failures


def main() -> int:
    checks = (
        validate_required_files,
        validate_utf8,
        validate_json,
        validate_allowlist,
        validate_endpoint_contract,
        validate_markdown_links,
        validate_env_example,
        validate_governance_and_prompt,
        validate_case_collisions,
    )
    failures: list[Failure] = []
    for check in checks:
        failures.extend(check())

    if failures:
        print(f"Repository validation failed with {len(failures)} issue(s):", file=sys.stderr)
        for failure in failures:
            print(f"- [{failure.check}] {failure.detail}", file=sys.stderr)
        return 1

    print("Repository documentation and Phase 1 handoff validation passed.")
    print(f"Validated {len(REQUIRED_FILES)} required files and {len(EXPECTED_CAPABILITIES)} exact GET capabilities.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
