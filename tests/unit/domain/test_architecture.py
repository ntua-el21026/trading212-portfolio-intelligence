import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

FORBIDDEN_ROOT_IMPORTS = {
    "alembic",
    "celery",
    "fastapi",
    "httpx",
    "mcp",
    "psycopg",
    "sqlalchemy",
    "trading212_persistence",
    "trading212_provider",
}


def test_domain_has_no_framework_transport_or_persistence_dependency() -> None:
    root = Path("packages/domain/src/trading212_domain")
    violations: list[str] = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                imported = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = (node.module,)
            violations.extend(
                f"{path}:{getattr(node, 'lineno', 0)}: {module}"
                for module in imported
                if module.split(".", maxsplit=1)[0] in FORBIDDEN_ROOT_IMPORTS
            )
    assert violations == []
