"""Initial dependency-direction and secret-boundary tests."""

from pathlib import Path

import pytest

from scripts.check_architecture import validate_architecture
from scripts.check_secrets import validate_secrets
from scripts.check_trading212_boundary import (
    PROVIDER_ROOT,
    validate_trading212_boundary,
    validate_trading212_text,
)


@pytest.mark.security
def test_python_dependency_direction_is_preserved() -> None:
    assert validate_architecture() == []


@pytest.mark.security
def test_repository_contains_no_high_confidence_secret() -> None:
    assert validate_secrets() == []


@pytest.mark.security
def test_trading212_production_boundary_is_statically_get_only() -> None:
    assert validate_trading212_boundary() == []


@pytest.mark.security
def test_non_python_provider_mutation_is_rejected_by_repository_guard() -> None:
    path = PROVIDER_ROOT / "forbidden-client.ts"
    findings = validate_trading212_text(
        path,
        "fetch('/provider-endpoint', { method: 'POST' });",
    )
    assert findings == [
        f"{path.relative_to(Path(__file__).resolve().parents[2])} contains a generic or "
        "mutating provider request pattern"
    ]
