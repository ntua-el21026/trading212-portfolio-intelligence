"""Phase 2 design/status contracts reject premature or unsupported acceptance."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from scripts.validate_repository import (
    PHASE2_LEDGER,
    PHASE2_MANIFEST,
    PHASE2_MATRIX,
    PHASE2_PACKAGES,
    PHASE2_REGISTRY,
    PHASE2_REQUIRED_FILES,
    REQUIRED_FILES,
    validate_phase2_design,
    validate_required_files,
)
from tests.status_fixtures import restore_phase2_selectors

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_FILES = (
    "PROJECT_STATUS.json",
    "PROJECT_PROGRESS.json",
    "docs/implementation/PHASE_1_AUDIT_CORRECTIONS.md",
    PHASE2_MATRIX,
    PHASE2_LEDGER,
    PHASE2_MANIFEST,
    PHASE2_REGISTRY,
)
pytestmark = pytest.mark.contract


@pytest.fixture
def contract_root(tmp_path: Path) -> Path:
    for relative in CONTRACT_FILES:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")
    restore_phase2_selectors(tmp_path)
    _normalize_design_baseline(tmp_path)
    return tmp_path


def _read(root: Path, filename: str = "PROJECT_PROGRESS.json") -> dict[str, Any]:
    value: dict[str, Any] = json.loads((root / filename).read_text(encoding="utf-8"))
    return value


def _write(root: Path, value: dict[str, Any], filename: str = "PROJECT_PROGRESS.json") -> None:
    (root / filename).write_text(json.dumps(value), encoding="utf-8")


def _normalize_design_baseline(root: Path) -> None:
    """Keep mutation fixtures stable as real packages acquire release evidence."""
    progress = _read(root)
    phase = progress["phases"]["phase_2"]
    phase.update(
        status="in_progress",
        progress_percent=0,
        work_packages=dict.fromkeys(PHASE2_PACKAGES, "not_started"),
        acceptance={
            "status": "pending",
            "locally_executable_rows_total": 29,
            "locally_executable_rows_complete": 0,
            "mandatory_scenarios_total": 40,
            "mandatory_scenarios_complete": 0,
            "release_evidence_sha": None,
        },
    )
    _write(root, progress)
    status = _read(root, "PROJECT_STATUS.json")
    status.update(
        current_phase="phase_2", current_release_target="0.2.0", implementation_status="in_progress"
    )
    status["phase_2_design"]["runtime_acceptance"] = "pending"
    _write(root, status, "PROJECT_STATUS.json")
    for relative in (PHASE2_MATRIX, PHASE2_LEDGER):
        path = root / relative
        lines = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("**Implementation acceptance:**"):
                line = "**Implementation acceptance:** Pending"
            elif line.startswith("**Validated Phase 2 SHA:**"):
                line = "**Validated Phase 2 SHA:** None"
            elif re.match(r"^\| P2-(?!EXT-)(?:[A-Z]+-\d{3}|S\d{2}) \|", line):
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                cells[-1] = "`pending`"
                if relative == PHASE2_LEDGER:
                    cells[-2] = "Not recorded / none"
                line = "| " + " | ".join(cells) + " |"
            lines.append(line)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _details(root: Path) -> str:
    return "\n".join(failure.detail for failure in validate_phase2_design(root))


def _replace(root: Path, relative: str, old: str, new: str) -> None:
    path = root / relative
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _complete_first_scenario(root: Path) -> dict[str, Any]:
    path = root / PHASE2_LEDGER
    text = path.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| P2-S01 |"))
    _replace(root, PHASE2_LEDGER, row, row.replace("`pending`", "`complete`"))
    progress = _read(root)
    progress["phases"]["phase_2"]["acceptance"]["mandatory_scenarios_complete"] = 1
    return progress


def _valid_evidence(root: Path) -> dict[str, Any]:
    test = root / "tests/unit/test_target_reference.py"
    test.parent.mkdir(parents=True, exist_ok=True)
    test.write_text("def test_target_reference():\n    assert 2 + 3 == 5\n", encoding="utf-8")
    artifact = root / "docs/implementation/evidence/phase2-reference.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    sha = "1234567890abcdef1234567890abcdef12345678"
    artifact.write_text(
        json.dumps({"source_sha": sha, "requirements": ["P2-S01"], "result": "passed"}),
        encoding="utf-8",
    )
    return {
        "sha": sha,
        "test_nodes": ["tests/unit/test_target_reference.py::test_target_reference"],
        "commands": [
            {"command": "uv run pytest tests/unit/test_target_reference.py", "exit_code": 0}
        ],
        "artifacts": ["docs/implementation/evidence/phase2-reference.json"],
    }


def test_current_phase2_design_is_truthful() -> None:
    assert validate_phase2_design() == []


def test_all_22_design_authorities_are_required(tmp_path: Path) -> None:
    assert len(PHASE2_REQUIRED_FILES) == len(set(PHASE2_REQUIRED_FILES)) == 22
    assert set(PHASE2_REQUIRED_FILES) <= set(REQUIRED_FILES)
    failures = {failure.detail for failure in validate_required_files(tmp_path)}
    assert all(f"missing {relative}" in failures for relative in PHASE2_REQUIRED_FILES)


def test_explicit_root_is_independent_of_checkout(contract_root: Path) -> None:
    assert validate_phase2_design(contract_root) == []
    (contract_root / PHASE2_LEDGER).unlink()
    assert "missing or unreadable" in _details(contract_root)


@pytest.mark.parametrize("field,value", [("status", "in_progress"), ("stage_b_allowed", False)])
def test_phase2_cannot_bypass_stage_a(contract_root: Path, field: str, value: object) -> None:
    progress = _read(contract_root)
    progress["audit_remediation"][field] = value
    _write(contract_root, progress)
    assert "complete Stage A" in _details(contract_root)


def test_stage_a_sha_cannot_drift_between_status_and_evidence(contract_root: Path) -> None:
    progress = _read(contract_root)
    progress["audit_remediation"]["corrected_evidence_sha"] = "a" * 40
    _write(contract_root, progress)
    details = _details(contract_root)
    assert "must agree across status documents" in details
    assert "document must identify the corrected SHA" in details


@pytest.mark.parametrize(
    "mutation", ["phase1_state", "phase1_percentage", "phase1_sha", "status_sha"]
)
def test_stage_a_unlock_is_bound_to_accepted_phase1(contract_root: Path, mutation: str) -> None:
    progress = _read(contract_root)
    phase1 = progress["phases"]["phase_1"]
    if mutation == "phase1_state":
        phase1["status"] = "in_progress"
    elif mutation == "phase1_percentage":
        phase1["progress_percent"] = 90
    elif mutation == "phase1_sha":
        phase1["acceptance"]["release_evidence_sha"] = "d" * 40
    else:
        status = _read(contract_root, "PROJECT_STATUS.json")
        status["validated_evidence"]["sha"] = "e" * 40
        _write(contract_root, status, "PROJECT_STATUS.json")
    _write(contract_root, progress)
    assert "completed Phase 1 acceptance" in _details(contract_root)


@pytest.mark.parametrize(
    "mutation", ["failed_ci", "missing_ci", "boolean_run_id", "missing_record"]
)
def test_stage_a_requires_real_recorded_gate_identity(contract_root: Path, mutation: str) -> None:
    progress = _read(contract_root)
    audit = progress["audit_remediation"]
    if mutation == "failed_ci":
        audit["github_actions"]["quality"]["conclusion"] = "failure"
    elif mutation == "missing_ci":
        del audit["github_actions"]["security"]
    elif mutation == "boolean_run_id":
        audit["github_actions"]["quality"]["run_id"] = True
    else:
        audit["evidence"] = "docs/implementation/evidence/missing-stage-a.md"
    _write(contract_root, progress)
    assert "Stage A" in _details(contract_root)


@pytest.mark.parametrize("field,value", [("status", "in_progress"), ("progress_percent", 1)])
def test_phase3_is_not_started(contract_root: Path, field: str, value: object) -> None:
    progress = _read(contract_root)
    progress["phases"]["phase_3"][field] = value
    _write(contract_root, progress)
    assert "Phase 3 must remain" in _details(contract_root)


@pytest.mark.parametrize("mutation", ["percentage", "skip_predecessor", "reorder", "invalid_state"])
def test_work_package_progress_is_ordered_and_evidence_based(
    contract_root: Path, mutation: str
) -> None:
    progress = _read(contract_root)
    phase = progress["phases"]["phase_2"]
    if mutation == "percentage":
        phase["progress_percent"] = 10
    elif mutation == "skip_predecessor":
        phase["work_packages"]["P2-02"] = "in_progress"
    elif mutation == "reorder":
        phase["work_packages"] = dict(reversed(tuple(phase["work_packages"].items())))
    else:
        phase["work_packages"]["P2-01"] = {"complete": True}
    _write(contract_root, progress)
    assert validate_phase2_design(contract_root)


@pytest.mark.parametrize(
    "relative,old,new,expected",
    [
        (PHASE2_MANIFEST, "| P2-02 |", "| P2-01 |", "execution manifest"),
        (PHASE2_MATRIX, "| P2-OPT-003 |", "| P2-TGT-001 |", "exact 29"),
        (PHASE2_LEDGER, "| P2-S40 |", "| P2-S39 |", "P2-S01 through P2-S40"),
        (PHASE2_REGISTRY, "`get_etf_overlap` |", "`request_anything` |", "25 frozen names"),
        (PHASE2_REGISTRY, "| COMMAND |", "| READ |", "two internal commands"),
    ],
)
def test_inventory_and_command_semantics_cannot_drift(
    contract_root: Path, relative: str, old: str, new: str, expected: str
) -> None:
    _replace(contract_root, relative, old, new)
    assert expected in _details(contract_root)


def test_completed_scenario_needs_real_nodes_commands_and_artifacts(contract_root: Path) -> None:
    _write(contract_root, _complete_first_scenario(contract_root))
    details = _details(contract_root)
    assert "P2-S01 requires an immutable evidence SHA" in details
    assert "existing exact test nodes" in details
    assert "successful commands" in details
    assert "existing repository evidence artifacts" in details


def test_package_completion_requires_its_assigned_predicates(contract_root: Path) -> None:
    progress = _read(contract_root)
    progress["phases"]["phase_2"]["work_packages"]["P2-01"] = "complete"
    progress["phases"]["phase_2"]["progress_percent"] = 10
    _write(contract_root, progress)
    assert "P2-01 cannot complete while its assigned acceptance predicates are pending" in _details(
        contract_root
    )


def test_internal_commands_cannot_be_mislabelled_observational(contract_root: Path) -> None:
    _replace(
        contract_root,
        PHASE2_REGISTRY,
        "| `COMMAND` | `false` | `false` | `true` | `false` |",
        "| `COMMAND` | `true` | `false` | `true` | `false` |",
    )
    assert "annotation profiles" in _details(contract_root)


def test_document_header_cannot_claim_unearned_acceptance(contract_root: Path) -> None:
    _replace(
        contract_root,
        PHASE2_MATRIX,
        "**Implementation acceptance:** Pending",
        "**Implementation acceptance:** Complete",
    )
    assert "document cannot claim runtime completion" in _details(contract_root)


def test_recorded_incremental_evidence_is_allowed_without_claiming_release(
    contract_root: Path,
) -> None:
    progress = _complete_first_scenario(contract_root)
    progress["phases"]["phase_2"]["acceptance"]["evidence"] = {
        "P2-S01": _valid_evidence(contract_root)
    }
    _write(contract_root, progress)
    assert validate_phase2_design(contract_root) == []


@pytest.mark.parametrize(
    "mutation", ["missing_node", "missing_artifact", "failed_command", "wrong_sha", "wrong_id"]
)
def test_evidence_cannot_substitute_unrelated_or_failed_artifacts(
    contract_root: Path, mutation: str
) -> None:
    progress = _complete_first_scenario(contract_root)
    record = _valid_evidence(contract_root)
    if mutation == "missing_node":
        record["test_nodes"] = ["tests/unit/test_target_reference.py::test_does_not_exist"]
    elif mutation == "missing_artifact":
        record["artifacts"] = ["docs/implementation/evidence/missing.json"]
    elif mutation == "failed_command":
        record["commands"][0]["exit_code"] = 1
    elif mutation == "wrong_sha":
        record["sha"] = "b" * 40
    else:
        manifest_path = contract_root / record["artifacts"][0]
        manifest = json.loads(manifest_path.read_text())
        manifest["requirements"] = ["P2-S02"]
        manifest_path.write_text(json.dumps(manifest))
    progress["phases"]["phase_2"]["acceptance"]["evidence"] = {"P2-S01": record}
    _write(contract_root, progress)
    assert "P2-S01 requires" in _details(contract_root)


def test_pending_scenario_cannot_reference_a_nonexistent_test(contract_root: Path) -> None:
    _replace(
        contract_root,
        PHASE2_LEDGER,
        "Not recorded / none",
        "`tests/unit/test_fabricated.py::test_not_implemented`",
    )
    assert "nonexistent or out-of-repository evidence" in _details(contract_root)


def test_evidence_symlink_cannot_escape_repository(contract_root: Path, tmp_path: Path) -> None:
    progress = _complete_first_scenario(contract_root)
    record = _valid_evidence(contract_root)
    outside = tmp_path.parent / f"{tmp_path.name}-outside-evidence.json"
    outside.write_text("{}", encoding="utf-8")
    artifact = contract_root / record["artifacts"][0]
    artifact.unlink()
    artifact.symlink_to(outside)
    progress["phases"]["phase_2"]["acceptance"]["evidence"] = {"P2-S01": record}
    _write(contract_root, progress)
    assert "existing repository evidence artifacts" in _details(contract_root)


@pytest.mark.parametrize("claim", ["phase", "acceptance", "runtime", "release_sha"])
def test_design_acceptance_cannot_claim_implementation_completion(
    contract_root: Path, claim: str
) -> None:
    progress = _read(contract_root)
    phase = progress["phases"]["phase_2"]
    if claim == "phase":
        phase["status"] = "complete"
    elif claim == "acceptance":
        phase["acceptance"]["status"] = "complete"
    elif claim == "runtime":
        status = _read(contract_root, "PROJECT_STATUS.json")
        status["phase_2_design"]["runtime_acceptance"] = "complete"
        _write(contract_root, status, "PROJECT_STATUS.json")
    else:
        phase["acceptance"]["release_evidence_sha"] = "c" * 40
    _write(contract_root, progress)
    assert "cannot claim" in _details(contract_root)


def test_mutation_fixture_resets_later_implementation_evidence(contract_root: Path) -> None:
    progress = _complete_first_scenario(contract_root)
    progress["phases"]["phase_2"]["work_packages"]["P2-01"] = "complete"
    progress["phases"]["phase_2"]["progress_percent"] = 10
    progress["phases"]["phase_2"]["acceptance"]["evidence"] = {
        "P2-S01": _valid_evidence(contract_root)
    }
    _write(contract_root, progress)
    _replace(
        contract_root,
        PHASE2_LEDGER,
        "**Implementation acceptance:** Pending",
        "**Implementation acceptance:** Complete",
    )

    _normalize_design_baseline(contract_root)

    assert validate_phase2_design(contract_root) == []
    assert _read(contract_root)["phases"]["phase_2"]["progress_percent"] == 0
    assert "evidence" not in _read(contract_root)["phases"]["phase_2"]["acceptance"]


def test_report_package_can_complete_before_shared_alert_restart_scenario(
    contract_root: Path,
) -> None:
    progress = _read(contract_root)
    phase = progress["phases"]["phase_2"]
    completed_packages = set(PHASE2_PACKAGES[:6])
    for package in completed_packages:
        phase["work_packages"][package] = "complete"
    phase["progress_percent"] = 60
    completed_ids = list(completed_packages)
    for relative, owner_column, count_field in (
        (PHASE2_MATRIX, 1, "locally_executable_rows_complete"),
        (PHASE2_LEDGER, 2, "mandatory_scenarios_complete"),
    ):
        path = contract_root / relative
        lines = []
        completed_count = 0
        for line in path.read_text().splitlines():
            if line.startswith("| P2-"):
                cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
                if len(cells) > owner_column and cells[owner_column] in completed_packages:
                    completed_ids.append(cells[0])
                    completed_count += 1
                    line = line.replace("`pending`", "`complete`")
            lines.append(line)
        path.write_text("\n".join(lines) + "\n")
        phase["acceptance"][count_field] = completed_count
    record = _valid_evidence(contract_root)
    artifact = contract_root / record["artifacts"][0]
    manifest = json.loads(artifact.read_text())
    manifest["requirements"] = completed_ids
    artifact.write_text(json.dumps(manifest))
    phase["acceptance"]["evidence"] = dict.fromkeys(completed_ids, record)
    _write(contract_root, progress)

    assert validate_phase2_design(contract_root) == []
    row = next(
        line
        for line in (contract_root / PHASE2_LEDGER).read_text().splitlines()
        if line.startswith("| P2-S31 |")
    )
    assert row.endswith("`pending` |")
