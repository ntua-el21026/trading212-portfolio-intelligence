"""Executable workspace and dependency baseline contract."""

import pytest

from scripts.check_workspace import validate_workspace


@pytest.mark.contract
def test_workspace_contract_is_satisfied() -> None:
    assert validate_workspace() == []
