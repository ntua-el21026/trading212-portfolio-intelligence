#!/usr/bin/env python3
"""Validate the documentation-first Phase 1 implementation baseline.

The validator intentionally uses only the Python standard library so it can run
before application dependency manifests exist.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

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
    ".github/workflows/phase-1-ci.yml",
    ".github/workflows/security.yml",
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
    "docs/operations/LOCAL_AND_DEPLOYMENT.md",
    "docs/operations/BACKUP_RESTORE.md",
    "docs/operations/CREDENTIALS_AND_DEMO_VALIDATION.md",
    "docs/operations/MCP_CHATGPT_VALIDATION.md",
    "docs/operations/TROUBLESHOOTING.md",
    "docs/implementation/MASTER_IMPLEMENTATION_PLAN.md",
    "docs/implementation/PHASE_1_TECHNICAL_BASELINE.md",
    "docs/implementation/P1_01_DEPENDENCY_BASELINE.md",
    "docs/implementation/PHASE_1_TRUSTED_FOUNDATION.md",
    "docs/implementation/PHASE_1_EXECUTION_MANIFEST.md",
    "docs/implementation/PHASE_1_ACCEPTANCE_MATRIX.md",
    "docs/implementation/PHASE_1_READINESS_REVIEW.md",
    "docs/implementation/PHASE_2_PORTFOLIO_INTELLIGENCE.md",
    "docs/implementation/PHASE_3_PREMIUM_PRODUCTIZATION.md",
    "docs/implementation/prompts/PHASE_1_CODEX_PROMPT.md",
    "config/contracts/trading212-read-allowlist.yaml",
    "scripts/validate_repository.py",
    "scripts/check_workspace.py",
    "compose.yaml",
    "Makefile",
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
)

EXPECTED_ACCEPTANCE_IDS = {
    "P1-API-001",
    "P1-API-002",
    "P1-AUTH-001",
    "P1-CALC-001",
    "P1-CALC-002",
    "P1-CALC-003",
    "P1-DATA-001",
    "P1-DATA-002",
    "P1-DATA-003",
    "P1-DOM-001",
    "P1-DOM-002",
    "P1-E2E-001",
    "P1-EXT-001",
    "P1-EXT-002",
    "P1-MCP-001",
    "P1-MCP-002",
    "P1-OPS-001",
    "P1-OPS-002",
    "P1-REC-001",
    "P1-SAFE-001",
    "P1-SAFE-002",
    "P1-SAFE-003",
    "P1-SEC-001",
    "P1-SNAP-001",
    "P1-WEB-001",
    "P1-WEB-002",
}

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
    ".css",
    ".py",
    ".sh",
    ".ts",
    ".tsx",
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
ACCEPTANCE_ID_RE = re.compile(r"\bP1-[A-Z0-9]+-\d{3}\b")
BRANCH_METADATA_RE = re.compile(
    r"^[ \t]*(?:[-*][ \t]*)?\*{0,2}(?P<label>(?:candidate|implementation|execution|working)\s+"
    r"branch|branch)(?:[ \t]*/[ \t]*SHA)?[ \t]*:\*{0,2}[ \t]*`?(?P<value>[^`\s]+)",
    re.IGNORECASE | re.MULTILINE,
)
NEGATED_WORKFLOW_INSTRUCTION_RE = re.compile(
    r"\b(?:do not|don't|never|no\s+(?:task|branch|pull request)|must not|cannot|"
    r"prohibit(?:ed|s)?|reject(?:ed|s)?|rather than|without creating)\b",
    re.IGNORECASE,
)
ACTIVE_WORKFLOW_INSTRUCTION_RES = (
    re.compile(
        r"\b(?:commit|create|develop|implement|merge|open|push|use|work)\b.{0,60}\b"
        r"(?:candidate|review|feature|topic|implementation|demo)[ -]branch\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:create|open|submit|raise)\b.{0,60}\b(?:pull request|PR)\b", re.IGNORECASE),
)

DIRECT_MAIN_REQUIREMENTS = {
    "AGENTS.md": ("Commit directly to `main`.", "Do not create branches or pull requests."),
    "README.md": ("commit directly to `main`", "no branches or pull requests"),
    "CONTRIBUTING.md": ("Commit directly to `main`", "Never force-push"),
    "docs/DOCUMENT_GOVERNANCE.md": ("direct commits to `main`",),
    "docs/adr/ADR-0007-DIRECT-COMMITS-TO-MAIN.md": ("fast-forward commits directly on `main`",),
    "docs/engineering/ENGINEERING_STANDARDS.md": ("commit directly to `main`",),
    "docs/engineering/TEST_STRATEGY.md": ("GitHub Actions validates pushes to `main`",),
    "docs/implementation/MASTER_IMPLEMENTATION_PLAN.md": (
        "Work directly on `main`; no branches or pull requests.",
    ),
    "docs/implementation/PHASE_1_TRUSTED_FOUNDATION.md": (
        "**Execution branch:** `main` only",
        "committed directly and incrementally to `main`",
    ),
    "docs/implementation/PHASE_1_EXECUTION_MANIFEST.md": ("Direct fast-forward commits to `main`",),
    "docs/implementation/PHASE_1_READINESS_REVIEW.md": (
        "commit coherent increments directly to `main`",
    ),
    "docs/implementation/prompts/PHASE_1_CODEX_PROMPT.md": (
        "work directly on `main`;",
        "do not create a branch or pull request;",
    ),
    "docs/operations/LOCAL_AND_DEPLOYMENT.md": ("synchronized `main` line",),
}

RETIRED_GOVERNANCE_PATHS = ("docs/adr/ADR-0009-PHASE-1-REVIEW-BRANCH-EXCEPTION.md",)
FORBIDDEN_GOVERNANCE_TOKENS = (
    "ADR-0009",
    "codex/phase-1-trusted-foundation",
    "candidate branch",
    "review-branch exception",
    "review branch exception",
    "review-only pull request",
)
GOVERNANCE_TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".sh"}
GOVERNANCE_EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "work",
}
BRANCH_JSON_KEYS = {"branch", "candidate_branch", "execution_branch", "implementation_branch"}
ALLOWED_MAIN_REFS = {"main", "refs/heads/main", "HEAD:main", "HEAD:refs/heads/main"}


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
                "exact capability registry mismatch; "
                f"expected {EXPECTED_CAPABILITIES!r}, got {parsed!r}",
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
            failures.append(
                Failure("endpoint-contract", f"non-GET expected capability {capability}")
            )

    for relative in AUTHORITATIVE_ENDPOINT_FILES:
        text = read_text(relative)
        for stale in STALE_ENDPOINTS:
            if stale in text:
                failures.append(
                    Failure("endpoint-contract", f"stale endpoint {stale} in {relative}")
                )
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
                failures.append(
                    Failure(
                        "markdown-links", f"{path.relative_to(ROOT)} -> {target} escapes repository"
                    )
                )
                continue
            if not resolved.exists():
                failures.append(
                    Failure("markdown-links", f"{path.relative_to(ROOT)} -> missing {target}")
                )
    return failures


def validate_env_example() -> list[Failure]:
    failures: list[Failure] = []
    for line_number, line in enumerate(read_text(".env.example").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        sensitive = any(
            token in key.upper()
            for token in ("SECRET", "TOKEN", "PASSWORD", "API_KEY", "CREDENTIAL")
        )
        if sensitive and value.strip():
            failures.append(
                Failure("env-example", f"line {line_number}: sensitive example {key} must be blank")
            )
    return failures


def governance_text_files(root: Path = ROOT) -> Iterable[Path]:
    """Yield deterministic, human-authored governance surfaces."""

    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in GOVERNANCE_EXCLUDED_PARTS for part in path.parts):
            continue
        if path.name == "Makefile" or path.suffix.lower() in GOVERNANCE_TEXT_SUFFIXES:
            yield path


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _command_tokens(line: str) -> list[str]:
    stripped = line.strip()
    stripped = re.sub(r"^(?:[-+*>]|\d+[.)])[ \t]+", "", stripped)
    stripped = stripped.strip("`").strip()
    if stripped.startswith("$ "):
        stripped = stripped[2:].lstrip()
    if not stripped.startswith(("git ", "gh ")):
        return []
    try:
        return shlex.split(stripped, comments=True)
    except ValueError:
        return []


def _git_command_violation(tokens: list[str]) -> str | None:
    if len(tokens) < 2 or tokens[0] != "git":
        return None
    command = tokens[1]
    arguments = tokens[2:]

    if command in {"switch", "checkout"}:
        if any(
            argument in {"-b", "-c", "--branch", "--create", "--detach", "--orphan"}
            for argument in arguments
        ):
            return "branch-creation or detached-checkout command is not allowed"
        if command == "switch" or "--" not in arguments:
            targets = [argument for argument in arguments if not argument.startswith("-")]
            if targets and targets[-1] not in {"main", "refs/heads/main"}:
                return f"{command} command targets non-main ref {targets[-1]!r}"

    if command == "branch":
        inspection_flags = {"-a", "--all", "--contains", "--list", "--show-current"}
        if arguments and not any(argument in inspection_flags for argument in arguments):
            return "branch command may create or mutate a non-main delivery line"

    if command == "merge":
        targets = [argument for argument in arguments if not argument.startswith("-")]
        allowed_targets = {"main", "refs/heads/main", "origin/main", "refs/remotes/origin/main"}
        if targets and targets[-1] not in allowed_targets:
            return f"merge command targets non-main ref {targets[-1]!r}"

    if command == "pull":
        targets = [argument for argument in arguments if not argument.startswith("-")]
        if len(targets) >= 2 and targets[-1] not in {"main", "refs/heads/main"}:
            return f"pull command targets non-main ref {targets[-1]!r}"

    if command == "rebase":
        targets = [argument for argument in arguments if not argument.startswith("-")]
        allowed_targets = {"main", "refs/heads/main", "origin/main", "refs/remotes/origin/main"}
        if targets and targets[-1] not in allowed_targets:
            return f"rebase command targets non-main ref {targets[-1]!r}"

    if (
        command == "worktree"
        and arguments
        and arguments[0] == "add"
        and any(argument in {"-b", "-B", "--detach"} for argument in arguments[1:])
    ):
        return "worktree command creates a branch or detached delivery line"

    if command == "push":
        if any(
            argument in {"-f", "--force", "--force-with-lease", "--all", "--mirror"}
            for argument in arguments
        ):
            return "force/all/mirror push is not allowed"
        positional = [argument for argument in arguments if not argument.startswith("-")]
        refspecs = positional[1:] if positional else []
        for refspec in refspecs:
            if refspec not in ALLOWED_MAIN_REFS:
                return f"push command targets non-main ref {refspec!r}"

    return None


def _command_violation(line: str) -> str | None:
    tokens = _command_tokens(line)
    if not tokens:
        return None
    git_violation = _git_command_violation(tokens)
    if git_violation is not None:
        return git_violation
    if (
        len(tokens) >= 3
        and tokens[:2] == ["gh", "pr"]
        and tokens[2]
        in {
            "close",
            "comment",
            "create",
            "checkout",
            "edit",
            "lock",
            "merge",
            "ready",
            "reopen",
            "review",
            "unlock",
        }
    ):
        return f"pull-request workflow command 'gh pr {tokens[2]}' is not allowed"
    return None


def validate_governance_text(relative: Path, text: str) -> list[Failure]:
    """Reject active instructions that route repository work away from main."""

    failures: list[Failure] = []
    seen: set[tuple[int, str]] = set()

    def add(line_number: int, detail: str) -> None:
        key = (line_number, detail)
        if key in seen:
            return
        seen.add(key)
        failures.append(Failure("direct-main-governance", f"{relative}:{line_number}: {detail}"))

    for token in FORBIDDEN_GOVERNANCE_TOKENS:
        for match in re.finditer(re.escape(token), text, re.IGNORECASE):
            add(_line_number(text, match.start()), f"retired workflow token {token!r}")

    for match in BRANCH_METADATA_RE.finditer(text):
        value = match.group("value").rstrip(".,;:")
        if value not in {"main", "refs/heads/main"}:
            add(
                _line_number(text, match.start()),
                f"{match.group('label')} metadata targets non-main ref {value!r}",
            )

    for line_number, line in enumerate(text.splitlines(), start=1):
        violation = _command_violation(line)
        if violation is not None:
            add(line_number, violation)
        if NEGATED_WORKFLOW_INSTRUCTION_RE.search(line):
            continue
        for pattern in ACTIVE_WORKFLOW_INSTRUCTION_RES:
            if pattern.search(line):
                add(line_number, "active branch or pull-request workflow instruction")
                break

    return failures


def _branch_json_failures(relative: Path, value: object, location: str = "$") -> list[Failure]:
    failures: list[Failure] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            nested_location = f"{location}.{key}"
            if (
                key.casefold() in BRANCH_JSON_KEYS
                and isinstance(nested, str)
                and nested not in {"main", "refs/heads/main"}
            ):
                failures.append(
                    Failure(
                        "direct-main-governance",
                        f"{relative}:{nested_location} targets non-main ref {nested!r}",
                    )
                )
            failures.extend(_branch_json_failures(relative, nested, nested_location))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            failures.extend(_branch_json_failures(relative, nested, f"{location}[{index}]"))
    return failures


def validate_direct_main_governance(root: Path = ROOT) -> list[Failure]:
    failures: list[Failure] = []

    for relative, required_tokens in DIRECT_MAIN_REQUIREMENTS.items():
        path = root / relative
        if not path.is_file():
            failures.append(Failure("direct-main-governance", f"missing authority {relative}"))
            continue
        text = path.read_text(encoding="utf-8")
        for token in required_tokens:
            if token not in text:
                failures.append(
                    Failure(
                        "direct-main-governance",
                        f"{relative} missing main-only token: {token}",
                    )
                )

    for relative in RETIRED_GOVERNANCE_PATHS:
        if (root / relative).exists():
            failures.append(
                Failure(
                    "direct-main-governance", f"retired governance file still exists: {relative}"
                )
            )

    for path in governance_text_files(root):
        relative_path = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        failures.extend(validate_governance_text(relative_path, text))
        if path.suffix.lower() == ".json":
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            failures.extend(_branch_json_failures(relative_path, parsed))

    return failures


def validate_governance_and_prompt() -> list[Failure]:
    failures = validate_direct_main_governance()
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

    for token in (
        "P1-01",
        "P1-12",
        "work directly on `main`",
        "Do not implement any broker `POST`",
        "Stop after Phase 1",
    ):
        if token not in prompt:
            failures.append(Failure("codex-prompt", f"Phase 1 prompt missing token: {token}"))

    packages = progress.get("phases", {}).get("phase_1", {}).get("work_packages", {})
    expected_package_ids = {f"P1-{number:02d}" for number in range(1, 13)}
    if set(packages) != expected_package_ids:
        failures.append(
            Failure("progress", "PROJECT_PROGRESS.json must contain exactly P1-01 through P1-12")
        )
    return failures


def validate_acceptance_traceability() -> list[Failure]:
    """Require the acceptance matrix and traceability index to expose identical IDs."""
    matrix_ids = set(
        ACCEPTANCE_ID_RE.findall(read_text("docs/implementation/PHASE_1_ACCEPTANCE_MATRIX.md"))
    )
    traceability_ids = set(ACCEPTANCE_ID_RE.findall(read_text("docs/REQUIREMENTS_TRACEABILITY.md")))
    failures: list[Failure] = []
    if matrix_ids != EXPECTED_ACCEPTANCE_IDS:
        failures.append(
            Failure(
                "acceptance-ids",
                "acceptance matrix mismatch: "
                f"expected {sorted(EXPECTED_ACCEPTANCE_IDS)}, got {sorted(matrix_ids)}",
            )
        )
    if traceability_ids != matrix_ids:
        failures.append(
            Failure(
                "acceptance-ids",
                "traceability mismatch: "
                f"matrix {sorted(matrix_ids)}, traceability {sorted(traceability_ids)}",
            )
        )
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
        validate_acceptance_traceability,
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
    print(
        f"Validated {len(REQUIRED_FILES)} required files and "
        f"{len(EXPECTED_CAPABILITIES)} exact GET capabilities."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
