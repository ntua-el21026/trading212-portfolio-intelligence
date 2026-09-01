"""Executable repository-governance contract."""

import json
from pathlib import Path

import pytest

from scripts.validate_repository import (
    validate_acceptance_traceability,
    validate_direct_main_governance,
    validate_governance_text,
)

ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE_CONTRACT_FILES = (
    "PROJECT_PROGRESS.json",
    "PROJECT_STATUS.json",
    "docs/REQUIREMENTS_TRACEABILITY.md",
    "docs/implementation/PHASE_1_ACCEPTANCE_MATRIX.md",
)


def _copy_acceptance_contract(tmp_path: Path) -> Path:
    for relative in ACCEPTANCE_CONTRACT_FILES:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text((ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


@pytest.mark.contract
def test_active_repository_governance_is_main_only() -> None:
    assert validate_direct_main_governance() == []


@pytest.mark.contract
def test_phase1_acceptance_states_are_structured_and_fail_closed() -> None:
    assert validate_acceptance_traceability() == []


@pytest.mark.contract
def test_external_gate_cannot_be_relabelled_complete(tmp_path: Path) -> None:
    root = _copy_acceptance_contract(tmp_path)
    matrix_path = root / "docs/implementation/PHASE_1_ACCEPTANCE_MATRIX.md"
    matrix = matrix_path.read_text(encoding="utf-8")
    original = next(line for line in matrix.splitlines() if line.startswith("| P1-EXT-004 |"))
    altered = original.replace("`unavailable_explicit`", "Complete")
    assert altered != original
    matrix_path.write_text(matrix.replace(original, altered), encoding="utf-8")

    failures = validate_acceptance_traceability(root)

    assert any(
        failure.check == "acceptance-state"
        and "P1-EXT-004 must be unavailable_explicit" in failure.detail
        for failure in failures
    )


@pytest.mark.contract
def test_machine_status_cannot_promote_an_external_gate(tmp_path: Path) -> None:
    root = _copy_acceptance_contract(tmp_path)
    status_path = root / "PROJECT_STATUS.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["external_gate_status"]["public_https_oauth_mcp_and_chatgpt_registration"] = "complete"
    status_path.write_text(json.dumps(status), encoding="utf-8")

    failures = validate_acceptance_traceability(root)

    assert any(
        failure.check == "acceptance-state" and "external_gate_status must match" in failure.detail
        for failure in failures
    )


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
