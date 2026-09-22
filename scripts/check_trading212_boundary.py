#!/usr/bin/env python3
"""Statically enforce the sealed, GET-only Trading 212 production boundary."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVIDER_ROOT = ROOT / "packages/trading212/src/trading212_provider"
TRANSPORT_OWNER = PROVIDER_ROOT / "client.py"
ALERT_WEBHOOK_OWNER = (
    ROOT / "packages/reference-data/src/trading212_reference_data/alert_webhook.py"
)
PREMIUM_ACQUISITION_OWNER = (
    ROOT / "packages/reference-data/src/trading212_reference_data/premium_transport.py"
)
_PREMIUM_METHODS = frozenset(
    {"daily_adjusted", "etf_profile", "company_overview", "news_sentiment", "ecb_reference_fx"}
)
_PREMIUM_PATHS = frozenset({"/query", "/stats/eurofxref/eurofxref-hist-90d.xml"})
_PREMIUM_HOSTS = frozenset({"www.alphavantage.co", "www.ecb.europa.eu"})
ORIGIN_OWNER = PROVIDER_ROOT / "configuration.py"
ORIGIN_CONTRACT = PROVIDER_ROOT / "contracts/trading212-read-allowlist.yaml"
ORIGIN_OWNERS = frozenset({ORIGIN_OWNER, ORIGIN_CONTRACT})

_PRODUCTION_ROOTS = (ROOT / "apps", ROOT / "packages", ROOT / "scripts")
_PRODUCTION_TEXT_SUFFIXES = {
    ".cjs",
    ".dockerfile",
    ".js",
    ".json",
    ".mjs",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}
_EXCLUDED_PARTS = {
    ".next",
    ".venv",
    "__pycache__",
    "coverage",
    "dist",
    "docs",
    "node_modules",
    "test-results",
    "tests",
}
_TRANSPORT_IMPORTS = {"aiohttp", "http.client", "httpx", "requests", "urllib.request", "socket"}
_STREAM_FACTORIES = {"open_connection", "create_connection", "create_datagram_endpoint"}
_MUTATING_METHODS = {"delete", "patch", "post", "put"}
_MUTATING_LITERALS = {method.upper() for method in _MUTATING_METHODS}
_FORBIDDEN_PATH_FRAGMENTS = (
    "/cfd/",
    "/equity/orders/limit",
    "/equity/orders/market",
    "/equity/orders/stop",
    "/equity/pies",
    "/equity/transfers",
    "/equity/payments",
    "/equity/withdrawals",
)
_PROVIDER_ORIGINS = (
    "demo.trading212.com",
    "live.trading212.com",
)


def _production_python_files() -> list[Path]:
    files: list[Path] = []
    for root in _PRODUCTION_ROOTS:
        for path in root.rglob("*.py"):
            if not set(path.parts) & _EXCLUDED_PARTS:
                files.append(path)
    return sorted(files)


def _production_text_files() -> list[Path]:
    files: list[Path] = []
    for root in _PRODUCTION_ROOTS:
        for path in root.rglob("*"):
            if (
                path.is_file()
                and path.suffix.casefold() in _PRODUCTION_TEXT_SUFFIXES
                and not set(path.parts) & _EXCLUDED_PARTS
            ):
                files.append(path)
    return sorted(files)


def _import_name(node: ast.Import | ast.ImportFrom) -> set[str]:
    if isinstance(node, ast.Import):
        return {alias.name for alias in node.names}
    if node.module is None:
        return set()
    return {node.module, *(f"{node.module}.{alias.name}" for alias in node.names)}


def _transport_import_findings(path: Path, tree: ast.AST) -> list[str]:
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for imported in _import_name(node):
            if (
                any(
                    imported == transport or imported.startswith(f"{transport}.")
                    for transport in _TRANSPORT_IMPORTS
                )
                and path != TRANSPORT_OWNER
                and not (
                    path == ALERT_WEBHOOK_OWNER
                    and any(
                        imported == allowed or imported.startswith(f"{allowed}.")
                        for allowed in {"http.client", "socket"}
                    )
                )
                and not (
                    path == PREMIUM_ACQUISITION_OWNER
                    and (imported == "socket" or imported.startswith("socket."))
                )
            ):
                findings.append(
                    f"{path.relative_to(ROOT)} imports outbound transport {imported}; "
                    "transport belongs only to its narrowly named broker or alert adapter, "
                    "or the fixed premium acquisition transport"
                )
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (node.module == "asyncio" or node.module.startswith("asyncio."))
            and any(alias.name in _STREAM_FACTORIES or alias.name == "*" for alias in node.names)
            and path != ALERT_WEBHOOK_OWNER
            and not (
                path == PREMIUM_ACQUISITION_OWNER
                and node.module == "asyncio"
                and all(alias.name == "open_connection" for alias in node.names)
            )
        ):
            findings.append(
                f"{path.relative_to(ROOT)}:{node.lineno} imports an unapproved "
                "outbound stream connection factory"
            )
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _STREAM_FACTORIES
            and path != ALERT_WEBHOOK_OWNER
            and not (
                path == PREMIUM_ACQUISITION_OWNER
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "asyncio"
                and node.func.attr == "open_connection"
            )
        ):
            findings.append(
                f"{path.relative_to(ROOT)}:{node.lineno} contains an unapproved "
                "outbound stream connection"
            )
    return findings


def _premium_surface_findings(path: Path, tree: ast.AST) -> list[str]:
    """The one new socket owner has five named operations and two reviewed routes."""
    if path != PREMIUM_ACQUISITION_OWNER:
        return []
    findings: list[str] = []
    if isinstance(tree, ast.Module) and any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
        for node in tree.body
    ):
        findings.append("Fixed premium transport cannot expose module-level generic functions")
    classes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "FixedPremiumTransport"
    ]
    if len(classes) != 1:
        return ["FixedPremiumTransport must exist exactly once in its named transport owner"]
    methods = [
        node
        for node in classes[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    ]
    if {node.name for node in methods} != _PREMIUM_METHODS or len(methods) != 5:
        findings.append("FixedPremiumTransport must expose exactly its five fixed operations")
    for node in methods:
        parameters = {
            arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        }
        expected = {"self", "command", "permit", "now"}
        if node.name != "ecb_reference_fx":
            expected.add("credential")
        if parameters != expected or node.args.vararg is not None or node.args.kwarg is not None:
            findings.append(f"FixedPremiumTransport.{node.name} exposes an unapproved parameter")
    paths: set[str] = set()
    hosts: set[str] = set()
    for walk_node in ast.walk(tree):
        if (
            isinstance(walk_node, ast.Call)
            and isinstance(walk_node.func, ast.Attribute)
            and walk_node.func.attr.casefold() in _MUTATING_METHODS | {"request"}
        ):
            findings.append("FixedPremiumTransport contains generic or mutating HTTP dispatch")
        if not isinstance(walk_node, ast.Constant) or not isinstance(walk_node.value, str):
            continue
        value = walk_node.value
        if value.startswith("/"):
            paths.add(value)
        if re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,}", value):
            hosts.add(value)
        if value.startswith(("http://", "https://")) or value in _MUTATING_LITERALS:
            findings.append("FixedPremiumTransport contains an unapproved URL or HTTP method")
    if paths != _PREMIUM_PATHS or hosts != _PREMIUM_HOSTS:
        findings.append("FixedPremiumTransport contains an unknown or missing fixed route")
    return findings


def _provider_call_findings(path: Path, tree: ast.AST) -> list[str]:
    if PROVIDER_ROOT not in path.parents:
        return []
    findings: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr.casefold() in _MUTATING_METHODS | {"request"}
        ):
            findings.append(
                f"{path.relative_to(ROOT)}:{node.lineno} contains a generic or mutating "
                f"HTTP call ({node.func.attr})"
            )
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in _MUTATING_LITERALS
        ):
            findings.append(
                f"{path.relative_to(ROOT)}:{node.lineno} contains mutating method literal "
                f"{node.value}"
            )
    return findings


def _text_findings(path: Path, text: str) -> list[str]:
    if path == Path(__file__).resolve():
        return []
    findings: list[str] = []
    relative = path.relative_to(ROOT)
    for origin in _PROVIDER_ORIGINS:
        if origin in text and path not in ORIGIN_OWNERS:
            findings.append(
                f"{relative} contains Trading 212 origin {origin}; origins belong only to "
                "the closed provider configuration"
            )
    for fragment in _FORBIDDEN_PATH_FRAGMENTS:
        if fragment in text.casefold():
            findings.append(f"{relative} contains forbidden provider path fragment {fragment}")
    return findings


def _non_python_provider_call_findings(path: Path, text: str) -> list[str]:
    if PROVIDER_ROOT not in path.parents or path.suffix == ".py":
        return []
    relative = path.relative_to(ROOT)
    patterns = (
        r"\bmethod\s*:\s*['\"](?:DELETE|PATCH|POST|PUT)['\"]",
        r"\.(?:delete|patch|post|put|request)\s*\(",
    )
    return [
        f"{relative} contains a generic or mutating provider request pattern"
        for pattern in patterns
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]


def validate_trading212_text(path: Path, text: str) -> list[str]:
    """Validate one production text file for forbidden provider boundary material."""

    return sorted(
        set((*_text_findings(path, text), *_non_python_provider_call_findings(path, text)))
    )


def _client_surface_findings() -> list[str]:
    tree = ast.parse(TRANSPORT_OWNER.read_text(encoding="utf-8"), filename=str(TRANSPORT_OWNER))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "Trading212Client":
            continue
        public = {
            child.name
            for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not child.name.startswith("_")
        }
        generic = public & {"delete", "fetch", "get", "patch", "post", "put", "request"}
        return [f"Trading212Client exposes forbidden generic method {name}" for name in generic]
    return ["Trading212Client class was not found in the sealed transport owner"]


def validate_trading212_boundary() -> list[str]:
    """Return deterministic findings; an empty list proves the static boundary."""
    findings: list[str] = []
    for path in _production_python_files():
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            findings.append(f"{path.relative_to(ROOT)} could not be parsed: {exc}")
            continue
        findings.extend(_transport_import_findings(path, tree))
        findings.extend(_provider_call_findings(path, tree))
        findings.extend(_premium_surface_findings(path, tree))
        findings.extend(_text_findings(path, text))
    for path in _production_text_files():
        if path.suffix == ".py":
            continue
        findings.extend(validate_trading212_text(path, path.read_text(encoding="utf-8")))
    findings.extend(_client_surface_findings())
    return sorted(set(findings))


def main() -> int:
    findings = validate_trading212_boundary()
    if findings:
        print("Trading 212 GET-only boundary validation failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("Trading 212 GET-only production boundary validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
