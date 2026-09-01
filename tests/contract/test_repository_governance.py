"""Executable repository-governance contract."""

from pathlib import Path

import pytest

from scripts.validate_repository import (
    validate_direct_main_governance,
    validate_governance_text,
)


@pytest.mark.contract
def test_active_repository_governance_is_main_only() -> None:
    assert validate_direct_main_governance() == []


@pytest.mark.contract
def test_main_only_policy_and_push_command_are_allowed() -> None:
    text = """\
Commit directly to `main`.
Do not create branches or pull requests.
git push origin main
git checkout -- README.md
git pull --ff-only origin main
git merge --ff-only origin/main
"""
    assert validate_governance_text(Path("MAIN_ONLY_EXAMPLE.md"), text) == []


@pytest.mark.contract
@pytest.mark.parametrize(
    "instruction",
    (
        "git switch -c demo/governance",
        "- `git switch -c demo/governance`",
        "git switch feature/governance",
        "git checkout -b feature/governance",
        "git checkout --detach 0123456789abcdef",
        "git checkout demo/governance",
        "git branch topic/governance",
        "git merge demo/governance",
        "git pull origin feature/governance",
        "git rebase topic/governance",
        "git push --set-upstream origin demo/governance",
        "git push origin feature/governance",
        "gh pr create --base main --head demo/governance",
        "Create a feature branch for this release.",
        "Work on the feature branch for this release.",
        "Open a pull request before delivery.",
        "Submit a PR before delivery.",
        "ADR-0009 defines the active workflow.",
        "**Execution branch:** `feature/governance`",
    ),
)
def test_non_main_workflow_instructions_are_rejected(instruction: str) -> None:
    failures = validate_governance_text(Path("DEMO_WORKFLOW.md"), instruction)
    assert failures
    assert {failure.check for failure in failures} == {"direct-main-governance"}
