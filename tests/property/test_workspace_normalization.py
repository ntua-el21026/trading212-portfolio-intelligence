"""Properties for deterministic package-name normalization."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scripts.check_workspace import canonical_name


@pytest.mark.property
@given(st.from_regex(r"[A-Za-z][A-Za-z0-9_.-]{0,40}", fullmatch=True))
def test_package_name_normalization_is_idempotent(name: str) -> None:
    normalized = canonical_name(name)

    assert canonical_name(normalized) == normalized
    assert normalized == normalized.lower()
