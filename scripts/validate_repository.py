#!/usr/bin/env python3
"""Validate repository authorities and evidence for the Phase 1/2 contracts.

The validator intentionally uses only the Python standard library so it can run
before application dependency manifests exist.
"""

from __future__ import annotations

import ast
import json
import re
import shlex
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PHASE2_REQUIRED_FILES = (
    "docs/DESIGN_FREEZE_V0_2.md",
    "docs/implementation/PHASE_2_TECHNICAL_BASELINE.md",
    "docs/implementation/PHASE_2_EXECUTION_MANIFEST.md",
    "docs/implementation/PHASE_2_ACCEPTANCE_MATRIX.md",
    "docs/implementation/PHASE_2_SCENARIO_EVIDENCE.md",
    "docs/architecture/PHASE_2_DATA_MODEL.md",
    "docs/architecture/PHASE_2_API_SERVICE_CONTRACTS.md",
    "docs/architecture/PHASE_2_WEB_INFORMATION_ARCHITECTURE.md",
    "docs/integrations/PHASE_2_PROVIDER_CONTRACTS.md",
    "docs/integrations/PHASE_2_MCP_TOOL_REGISTRY.md",
    "docs/security/PHASE_2_SECURITY_PRIVACY.md",
    "docs/engineering/PHASE_2_TEST_STRATEGY.md",
    "docs/operations/PHASE_2_OPERATIONS.md",
    "docs/analytics/PHASE_2_METHODS.md",
    "docs/adr/ADR-0009-PROVIDER-TRANSPORT-ISOLATION.md",
    "docs/adr/ADR-0010-IMMUTABLE-VIRTUAL-TARGETS.md",
    "docs/adr/ADR-0011-DETERMINISTIC-CONTRIBUTION-OPTIMIZER.md",
    "docs/adr/ADR-0012-MARKET-SOURCE-SNAPSHOTS.md",
    "docs/adr/ADR-0013-ECONOMIC-ENTITY-NORMALIZATION.md",
    "docs/adr/ADR-0014-PRIVATE-REPRODUCIBLE-REPORTS.md",
    "docs/adr/ADR-0015-VERSIONED-ALERT-EVALUATION.md",
    "docs/adr/ADR-0016-INTERNAL-MCP-COMMANDS.md",
)

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
    *PHASE2_REQUIRED_FILES,
)

PHASE2_PACKAGES = tuple(f"P2-{number:02d}" for number in range(1, 11))
PHASE2_ACCEPTANCE_IDS = (
    "P2-TGT-001",
    "P2-TGT-002",
    "P2-TGT-003",
    "P2-OPT-001",
    "P2-OPT-002",
    "P2-OPT-003",
    "P2-SRC-001",
    "P2-SRC-002",
    "P2-PERF-001",
    "P2-PERF-002",
    "P2-INC-001",
    "P2-XRAY-001",
    "P2-XRAY-002",
    "P2-RPT-001",
    "P2-RPT-002",
    "P2-RPT-003",
    "P2-ALT-001",
    "P2-ALT-002",
    "P2-ALT-003",
    "P2-WEB-001",
    "P2-WEB-002",
    "P2-MCP-001",
    "P2-MCP-002",
    "P2-API-001",
    "P2-DATA-001",
    "P2-SEC-001",
    "P2-REG-001",
    "P2-OPS-001",
    "P2-REL-001",
)
PHASE2_SCENARIOS = tuple(f"P2-S{number:02d}" for number in range(1, 41))
PHASE2_MCP_TOOLS = (
    "get_account_summary",
    "get_portfolio_snapshot",
    "list_positions",
    "list_recent_transactions",
    "get_dividend_summary",
    "get_direct_allocation",
    "compare_portfolio_snapshots",
    "get_reconciliation_status",
    "get_data_quality_summary",
    "list_virtual_pies",
    "get_virtual_pie",
    "get_actual_vs_target",
    "get_drift_analysis",
    "get_contribution_plan",
    "get_performance_summary",
    "get_benchmark_comparison",
    "get_dividend_intelligence",
    "get_attribution_summary",
    "get_effective_exposure",
    "get_etf_overlap",
    "get_report_status",
    "list_reports",
    "get_alert_summary",
    "create_contribution_plan",
    "generate_portfolio_report",
)
PHASE2_MATRIX = "docs/implementation/PHASE_2_ACCEPTANCE_MATRIX.md"
PHASE2_LEDGER = "docs/implementation/PHASE_2_SCENARIO_EVIDENCE.md"
PHASE2_MANIFEST = "docs/implementation/PHASE_2_EXECUTION_MANIFEST.md"
PHASE2_REGISTRY = "docs/integrations/PHASE_2_MCP_TOOL_REGISTRY.md"
PHASE2_ROW_STATES = {"pending", "in_progress", "implemented_unverified", "complete"}
SHA_RE = re.compile(r"[0-9a-f]{40}")


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
    "P1-EXT-003",
    "P1-EXT-004",
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

EXPECTED_ACCEPTANCE_STATES = {
    acceptance_id: "complete" for acceptance_id in EXPECTED_ACCEPTANCE_IDS
}
EXPECTED_ACCEPTANCE_STATES.update(
    {
        "P1-EXT-001": "blocked_external",
        "P1-EXT-002": "blocked_external",
        "P1-EXT-003": "blocked_external",
        "P1-EXT-004": "unavailable_explicit",
    }
)
EXPECTED_EXTERNAL_GATE_STATUS = {
    "trading212_demo_smoke": "blocked_external",
    "production_host_identity_secret_manager_selection": "blocked_external",
    "public_https_oauth_mcp_and_chatgpt_registration": "blocked_external",
    "real_provider_opening_history_coverage": "unavailable_explicit",
}
EXPECTED_EXTERNAL_REPORTING_STATUS = {"real_provider_opening_history_coverage": "complete"}

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
ACCEPTANCE_TABLE_ROW_RE = re.compile(
    r"^\|\s*(?P<id>P1-[A-Z0-9]+-\d{3})\s*\|[^|]*\|[^|]*\|"
    r"\s*(?P<state>[^|]+?)\s*\|\s*$",
    re.MULTILINE,
)
TRACEABILITY_DEFINITION_RE = re.compile(
    r"^-\s+`(?P<id>P1-[A-Z0-9]+-\d{3})`:\s*(?P<description>.*(?:\n  .*)*)$",
    re.MULTILINE,
)
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
    "ADR-0009-PHASE-1-REVIEW-BRANCH-EXCEPTION",
    "codex/phase-1-trusted-foundation",
    "candidate branch",
    "review-branch exception",
    "review branch exception",
    "review-only pull request",
)
RETIRED_ADR_WORKFLOW_RE = re.compile(
    r"\bADR-0009\b[^\n]{0,120}\b(?:active\s+workflow|branch\s+(?:exception|workflow)|"
    r"review\s+(?:branch|workflow)|delivery\s+workflow)\b",
    re.IGNORECASE,
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


def validate_required_files(root: Path = ROOT) -> list[Failure]:
    return [
        Failure("required-files", f"missing {relative}")
        for relative in REQUIRED_FILES
        if not (root / relative).is_file()
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

    for match in RETIRED_ADR_WORKFLOW_RE.finditer(text):
        add(_line_number(text, match.start()), "retired ADR-0009 branch-governance reference")

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


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def validate_acceptance_traceability(root: Path = ROOT) -> list[Failure]:
    """Bind structured acceptance rows, traceability definitions, and status state."""
    matrix_text = (root / "docs/implementation/PHASE_1_ACCEPTANCE_MATRIX.md").read_text(
        encoding="utf-8"
    )
    traceability_text = (root / "docs/REQUIREMENTS_TRACEABILITY.md").read_text(encoding="utf-8")
    matrix_rows = [
        (match.group("id"), match.group("state").strip().strip("`").casefold())
        for match in ACCEPTANCE_TABLE_ROW_RE.finditer(matrix_text)
    ]
    traceability_rows = [
        (match.group("id"), match.group("description"))
        for match in TRACEABILITY_DEFINITION_RE.finditer(traceability_text)
    ]
    matrix_ids = {acceptance_id for acceptance_id, _state in matrix_rows}
    traceability_ids = {acceptance_id for acceptance_id, _description in traceability_rows}
    failures: list[Failure] = []

    matrix_duplicates = _duplicates(acceptance_id for acceptance_id, _state in matrix_rows)
    if matrix_duplicates:
        failures.append(
            Failure(
                "acceptance-ids",
                f"acceptance matrix contains duplicate rows: {sorted(matrix_duplicates)}",
            )
        )
    traceability_duplicates = _duplicates(
        acceptance_id for acceptance_id, _description in traceability_rows
    )
    if traceability_duplicates:
        failures.append(
            Failure(
                "acceptance-ids",
                f"traceability contains duplicate definitions: {sorted(traceability_duplicates)}",
            )
        )
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

    matrix_states = dict(matrix_rows)
    for acceptance_id, expected_state in EXPECTED_ACCEPTANCE_STATES.items():
        actual_state = matrix_states.get(acceptance_id)
        if actual_state is not None and actual_state != expected_state:
            failures.append(
                Failure(
                    "acceptance-state",
                    f"{acceptance_id} must be {expected_state}, got {actual_state}",
                )
            )

    traceability_definitions = dict(traceability_rows)
    for acceptance_id, expected_state in EXPECTED_ACCEPTANCE_STATES.items():
        if not acceptance_id.startswith("P1-EXT-"):
            continue
        description = traceability_definitions.get(acceptance_id)
        if description is not None and f"`{expected_state}`" not in description:
            failures.append(
                Failure(
                    "acceptance-state",
                    f"traceability {acceptance_id} must retain state `{expected_state}`",
                )
            )

    status = json.loads((root / "PROJECT_STATUS.json").read_text(encoding="utf-8"))
    progress = json.loads((root / "PROJECT_PROGRESS.json").read_text(encoding="utf-8"))
    status_external = status.get("external_gate_status")
    progress_external = progress.get("external_gates")
    if status_external != EXPECTED_EXTERNAL_GATE_STATUS:
        failures.append(
            Failure(
                "acceptance-state",
                "PROJECT_STATUS.json external_gate_status must match the fail-closed "
                "external gate map",
            )
        )
    if progress_external != EXPECTED_EXTERNAL_GATE_STATUS:
        failures.append(
            Failure(
                "acceptance-state",
                "PROJECT_PROGRESS.json external_gates must match the fail-closed external gate map",
            )
        )
    if set(status.get("external_gates", ())) != set(EXPECTED_EXTERNAL_GATE_STATUS):
        failures.append(
            Failure(
                "acceptance-state",
                "PROJECT_STATUS.json external_gates must list exactly the external gate map keys",
            )
        )
    for document_name, document in (
        ("PROJECT_STATUS.json", status),
        ("PROJECT_PROGRESS.json", progress),
    ):
        if document.get("external_gate_reporting") != EXPECTED_EXTERNAL_REPORTING_STATUS:
            failures.append(
                Failure(
                    "acceptance-state",
                    f"{document_name} external_gate_reporting must preserve explicit "
                    "limitation reporting",
                )
            )
        if document.get("release_readiness") != "blocked_external":
            failures.append(
                Failure(
                    "acceptance-state",
                    f"{document_name} release_readiness must remain blocked_external",
                )
            )

    acceptance = progress.get("phases", {}).get("phase_1", {}).get("acceptance", {})
    expected_counts = {
        "external_conditions_total": len(EXPECTED_EXTERNAL_GATE_STATUS),
        "external_rows_blocked_external": 3,
        "external_rows_unavailable_explicit": 1,
        "external_rows_reporting_complete": 1,
    }
    for field, expected_value in expected_counts.items():
        if acceptance.get(field) != expected_value:
            failures.append(
                Failure(
                    "acceptance-state",
                    f"PROJECT_PROGRESS.json acceptance.{field} must be {expected_value}",
                )
            )
    if status.get("remaining_external_conditions") != len(EXPECTED_EXTERNAL_GATE_STATUS):
        failures.append(
            Failure(
                "acceptance-state",
                "PROJECT_STATUS.json remaining_external_conditions must match the "
                "external gate map",
            )
        )
    return failures


def _object(value: object) -> dict[str, object]:
    return {str(key): item for key, item in value.items()} if isinstance(value, dict) else {}


def _positive_integer(value: object) -> bool:
    return type(value) is int and value > 0


def _phase2_rows(text: str, id_pattern: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if cells and re.fullmatch(id_pattern, cells[0]):
            rows.append(cells)
    return rows


def _evidence_file(root: Path, value: object) -> Path | None:
    """Accept existing repository files only, including through symlinks."""
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        return None
    path = (root / value).resolve()
    return path if path.is_relative_to(root.resolve()) and path.is_file() else None


def _test_node_exists(root: Path, node: object) -> bool:
    if not isinstance(node, str) or "::" not in node:
        return False
    relative, *selectors = node.split("::")
    path = _evidence_file(root, relative)
    if path is None or not Path(relative).parts or Path(relative).parts[0] != "tests":
        return False
    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".py":
            body = ast.parse(text).body
            for selector in selectors:
                name = selector.split("[", 1)[0]
                found = next(
                    (
                        item
                        for item in body
                        if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name == name
                    ),
                    None,
                )
                if found is None:
                    return False
                body = found.body
            return isinstance(found, (ast.FunctionDef, ast.AsyncFunctionDef))
        if path.suffix in {".ts", ".tsx"} and len(selectors) == 1:
            return bool(
                re.search(
                    r"\b(?:test|it)(?:\.[a-zA-Z]+)?\(\s*([\"'])" + re.escape(selectors[0]) + r"\1",
                    text,
                )
            )
    except (OSError, UnicodeError, SyntaxError):
        return False
    return False


def _phase2_evidence_errors(root: Path, identifier: str, value: object) -> list[str]:
    record = _object(value)
    sha = record.get("sha")
    errors = []
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha) or sha == "0" * 40:
        errors.append(f"{identifier} requires an immutable evidence SHA")
    nodes = record.get("test_nodes")
    if (
        not isinstance(nodes, list)
        or not nodes
        or not all(_test_node_exists(root, node) for node in nodes)
    ):
        errors.append(f"{identifier} requires existing exact test nodes")
    commands = record.get("commands")
    if (
        not isinstance(commands, list)
        or not commands
        or not all(
            isinstance(_object(command).get("command"), str)
            and bool(str(_object(command).get("command")).strip())
            and type(_object(command).get("exit_code")) is int
            and _object(command).get("exit_code") == 0
            for command in commands
        )
    ):
        errors.append(f"{identifier} requires recorded successful commands")
    artifacts = record.get("artifacts")
    if (
        not isinstance(artifacts, list)
        or not artifacts
        or not all(
            isinstance(artifact, str)
            and artifact.startswith("docs/implementation/evidence/")
            and _evidence_file(root, artifact) is not None
            for artifact in artifacts
        )
    ):
        errors.append(f"{identifier} requires existing repository evidence artifacts")
    manifests = []
    for artifact in artifacts if isinstance(artifacts, list) else []:
        path = _evidence_file(root, artifact)
        if path is None or path.suffix != ".json":
            continue
        try:
            if path.stat().st_size <= 2 * 1024 * 1024:
                manifests.append(_object(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
    if not any(
        manifest.get("source_sha") == sha
        and manifest.get("result") == "passed"
        and isinstance(requirements := manifest.get("requirements"), list)
        and identifier in requirements
        for manifest in manifests
    ):
        errors.append(f"{identifier} requires a passing artifact manifest bound to its SHA and ID")
    return errors


def validate_phase2_design(root: Path = ROOT) -> list[Failure]:
    """Check declared evidence consistency, not independently attest execution.

    Completed package/row/scenario IDs require acceptance.evidence[ID] with sha,
    exact test_nodes, successful commands and retained artifact paths. A JSON
    artifact binds source_sha, requirements and result=passed to that record. This
    fail-closed contract supports incremental acceptance after design closure.
    """
    failures: list[Failure] = []

    def add(detail: str) -> None:
        failures.append(Failure("phase2-design", detail))

    def load(relative: str) -> str:
        try:
            return (root / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            add(f"missing or unreadable Phase 2 authority: {relative}")
            return ""

    documents = []
    for relative in ("PROJECT_STATUS.json", "PROJECT_PROGRESS.json"):
        try:
            value = json.loads(load(relative))
        except json.JSONDecodeError:
            value = None
        if not isinstance(value, dict):
            add(f"{relative} must be a JSON object")
        documents.append(_object(value))
    status, progress = documents
    phases = _object(progress.get("phases"))
    phase2 = _object(phases.get("phase_2"))
    phase3 = _object(phases.get("phase_3"))
    audit_shas = []
    for document in documents:
        audit = _object(document.get("audit_remediation"))
        sha = audit.get("corrected_evidence_sha")
        if (
            audit.get("stage") != "A"
            or audit.get("status") != "complete"
            or audit.get("stage_b_allowed") is not True
            or audit.get("all_phase_1_gates_at_corrected_sha") != "passed"
            or audit.get("findings") != {"F-01": "complete", "F-02": "complete"}
            or not isinstance(sha, str)
            or not SHA_RE.fullmatch(sha)
            or sha == "0" * 40
        ):
            add("Phase 2 requires complete Stage A findings and corrected-SHA gates")
        audit_shas.append(sha)
        runs = _object(audit.get("github_actions"))
        if set(runs) != {"quality", "security", "documentation"} or any(
            _object(run).get("conclusion") != "success"
            or not _positive_integer(_object(run).get("run_id"))
            or not _positive_integer(_object(run).get("attempt"))
            for run in runs.values()
        ):
            add("Stage A requires all three recorded successful exact-SHA workflows")
        audit_file = _evidence_file(root, audit.get("evidence"))
        if audit_file is None:
            add("Stage A evidence reference must exist within the repository")
        elif isinstance(sha, str) and sha not in load(
            audit_file.relative_to(root.resolve()).as_posix()
        ):
            add("Stage A evidence document must identify the corrected SHA")
    if audit_shas[0] != audit_shas[1]:
        add("Stage A corrected evidence SHA must agree across status documents")
    phase1 = _object(phases.get("phase_1"))
    phase1_acceptance = _object(phase1.get("acceptance"))
    if (
        phase1.get("status") != "complete"
        or type(phase1.get("progress_percent")) is not int
        or phase1.get("progress_percent") != 100
        or phase1_acceptance.get("status") != "complete"
        or phase1_acceptance.get("release_evidence_sha") != audit_shas[0]
        or _object(status.get("validated_evidence")).get("sha") != audit_shas[0]
    ):
        add("completed Phase 1 acceptance and current validated evidence must bind Stage A SHA")
    if (
        phase3.get("status") != "not_started"
        or type(phase3.get("progress_percent")) is not int
        or phase3.get("progress_percent") != 0
    ):
        add("Phase 3 must remain not_started with zero progress")
    if any(state != "not_started" for state in _object(phase3.get("work_packages")).values()):
        add("Phase 3 work packages must remain untouched")
    if status.get("current_phase") != "phase_2" or status.get("current_release_target") != "0.2.0":
        add("current status must identify Phase 2 release 0.2.0")

    packages = _object(phase2.get("work_packages"))
    if tuple(packages) != PHASE2_PACKAGES:
        add("work packages must be exactly ordered P2-01 through P2-10")
    unfinished = False
    for identifier, state in packages.items():
        if not isinstance(state, str) or state not in {
            "not_started",
            "in_progress",
            "implemented_unverified",
            "complete",
            "blocked",
        }:
            add(f"{identifier} has an invalid work-package state")
        if unfinished and state != "not_started":
            add(f"{identifier} cannot advance before its predecessor is complete")
        unfinished = unfinished or state != "complete"
    complete_packages = sum(state == "complete" for state in packages.values())
    if (
        type(phase2.get("progress_percent")) is not int
        or phase2.get("progress_percent") != complete_packages * 10
    ):
        add("Phase 2 progress must equal completed work packages out of ten")
    manifest_rows = _phase2_rows(load(PHASE2_MANIFEST), r"P2-\d{2}")
    if tuple(row[0] for row in manifest_rows) != PHASE2_PACKAGES:
        add("execution manifest must contain exactly ordered P2-01 through P2-10")

    matrix = load(PHASE2_MATRIX)
    ledger = load(PHASE2_LEDGER)
    matrix_rows = _phase2_rows(matrix, r"P2-(?!EXT-)[A-Z]+-\d{3}")
    scenario_rows = _phase2_rows(ledger, r"P2-S\d{2}")
    if any(len(row) != 5 for row in matrix_rows) or any(len(row) != 6 for row in scenario_rows):
        add("Phase 2 acceptance and scenario rows must preserve all required evidence columns")
    if tuple(row[0] for row in matrix_rows) != PHASE2_ACCEPTANCE_IDS:
        add("acceptance matrix must contain the exact 29 local acceptance IDs")
    if tuple(row[0] for row in scenario_rows) != PHASE2_SCENARIOS:
        add("scenario ledger must contain exactly ordered P2-S01 through P2-S40")
    completed = [identifier for identifier, state in packages.items() if state == "complete"]
    for row in matrix_rows + scenario_rows:
        if row[-1] not in PHASE2_ROW_STATES:
            add(f"{row[0]} has an invalid local acceptance state")
        if row[-1] == "complete":
            completed.append(row[0])
    for identifier, state in packages.items():
        # Shared scenarios close at release; each package still needs scoped evidence.
        if state == "complete" and (
            any(
                len(row) == 5 and row[1] == identifier and row[-1] != "complete"
                for row in matrix_rows
            )
            or any(
                len(row) == 6 and row[2] == identifier and row[-1] != "complete"
                for row in scenario_rows
            )
        ):
            add(
                f"{identifier} cannot complete while its assigned acceptance predicates are pending"
            )
    acceptance = _object(phase2.get("acceptance"))
    expected_counts = {
        "locally_executable_rows_total": 29,
        "locally_executable_rows_complete": sum(row[-1] == "complete" for row in matrix_rows),
        "mandatory_scenarios_total": 40,
        "mandatory_scenarios_complete": sum(row[-1] == "complete" for row in scenario_rows),
    }
    for field, count in expected_counts.items():
        if type(acceptance.get(field)) is not int or acceptance.get(field) != count:
            add(f"Phase 2 acceptance.{field} must match the structured inventory ({count})")
    evidence = _object(acceptance.get("evidence"))
    for identifier in completed:
        for error in _phase2_evidence_errors(root, identifier, evidence.get(identifier)):
            add(error)
    for identifier, record in evidence.items():
        if identifier not in (*PHASE2_PACKAGES, *PHASE2_ACCEPTANCE_IDS, *PHASE2_SCENARIOS):
            add(f"unknown evidence requirement {identifier}")
        for error in _phase2_evidence_errors(root, identifier, record):
            add(error)
    for reference in re.findall(
        r"`(tests/[^`]+|docs/implementation/evidence/[^`]+)`", matrix + ledger
    ):
        valid = (
            _test_node_exists(root, reference)
            if "::" in reference
            else _evidence_file(root, reference) is not None
        )
        if not valid:
            add("acceptance documents reference nonexistent or out-of-repository evidence")

    release_complete = complete_packages == 10 and len(completed) == 79
    for field, claim in (
        ("phase status", phase2.get("status")),
        ("acceptance status", acceptance.get("status")),
        ("implementation status", status.get("implementation_status")),
        ("runtime acceptance", _object(status.get("phase_2_design")).get("runtime_acceptance")),
    ):
        if claim == "complete" and not release_complete:
            add(f"{field} cannot claim completion before all packages, rows and scenarios")
    if phase2.get("status") not in ("not_started", "in_progress", "complete", "blocked"):
        add("Phase 2 status must use a supported implementation state")
    if acceptance.get("status") not in ("pending", "in_progress", "complete"):
        add("Phase 2 acceptance status must be pending, in_progress or complete")
    release_sha = acceptance.get("release_evidence_sha")
    if release_complete:
        if (
            not isinstance(release_sha, str)
            or not SHA_RE.fullmatch(release_sha)
            or any(
                _object(evidence.get(identifier)).get("sha") != release_sha
                for identifier in completed
            )
        ):
            add("complete Phase 2 acceptance requires one immutable release evidence SHA")
    elif release_sha is not None:
        add("pending Phase 2 release cannot claim an accepted release evidence SHA")

    for text in (matrix, ledger):
        for claim in re.findall(r"\*\*Implementation acceptance:\*\*\s*([^\n]+)", text):
            if (
                re.match(r"(?:complete|passed|accepted)\b", claim, re.IGNORECASE)
                and not release_complete
            ):
                add("acceptance document cannot claim runtime completion before release gates")

    registry = load(PHASE2_REGISTRY)
    registry_rows = _phase2_rows(registry, r"\d+")
    if (
        tuple(row[0] for row in registry_rows) != tuple(str(number) for number in range(1, 26))
        or tuple(row[1] for row in registry_rows if len(row) > 1) != PHASE2_MCP_TOOLS
    ):
        add("MCP registry must contain exactly the 25 frozen names in order")
    for index, row in enumerate(registry_rows):
        if len(row) != 6 or row[4] != ("READ" if index < 23 else "COMMAND"):
            add("MCP registry must preserve 23 reads and exactly two internal commands")
    annotations = _phase2_rows(registry, r"READ|COMMAND")
    if annotations != [
        ["READ", "true", "false", "true", "false"],
        ["COMMAND", "false", "false", "true", "false"],
    ]:
        add("MCP annotation profiles must preserve bounded read and internal-command semantics")
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
        validate_phase2_design,
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

    print("Repository documentation, Phase 1 handoff and Phase 2 design validation passed.")
    print(
        f"Validated {len(REQUIRED_FILES)} required files and "
        f"{len(EXPECTED_CAPABILITIES)} exact GET capabilities."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
