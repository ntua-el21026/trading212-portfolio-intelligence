"""Frozen premium inventories cannot masquerade as executed acceptance."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from scripts.validate_repository import (
    PHASE3_DESIGN,
    PHASE3_LEDGER,
    PHASE3_MANIFEST,
    PHASE3_MATRIX,
    PHASE3_PACKAGES,
    PHASE3_REGISTRY,
    PHASE3_REQUIRED_FILES,
    validate_phase3_design,
)

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.contract


def _read(root: Path) -> dict[str, Any]:
    value: dict[str, Any] = json.loads((root / "PROJECT_PROGRESS.json").read_text())
    return value


def _write(root: Path, value: dict[str, Any]) -> None:
    (root / "PROJECT_PROGRESS.json").write_text(json.dumps(value))


@pytest.fixture
def design_root(tmp_path: Path) -> Path:
    for relative in (*PHASE3_REQUIRED_FILES, "PROJECT_STATUS.json", "PROJECT_PROGRESS.json"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    progress = _read(tmp_path)
    phase = progress["phases"]["phase_3"]
    phase["design"] = PHASE3_DESIGN
    phase["work_packages"] = dict.fromkeys(PHASE3_PACKAGES, "not_started")
    phase["acceptance"]["evidence"] = {}
    phase["acceptance_inventory"] = {
        "locally_executable_rows_total": 30,
        "locally_executable_rows_complete": 0,
        "mandatory_scenarios_total": 48,
        "mandatory_scenarios_complete": 0,
    }
    _write(tmp_path, progress)
    for relative in (PHASE3_MATRIX, PHASE3_LEDGER):
        path = tmp_path / relative
        path.write_text(
            re.sub(
                r"\| (complete|in_progress|implemented_unverified) \|",
                "| pending |",
                path.read_text(),
            )
        )
    return tmp_path


def _change(root: Path, relative: str, before: str, after: str) -> None:
    path = root / relative
    text = path.read_text()
    assert before in text
    path.write_text(text.replace(before, after, 1))


def _details(root: Path) -> str:
    return "\n".join(f.detail for f in validate_phase3_design(root))


def test_actual_phase3_authorities_are_consistent() -> None:
    assert validate_phase3_design() == []


def test_pending_design_needs_no_fabricated_runtime_tests(design_root: Path) -> None:
    assert validate_phase3_design(design_root) == []


@pytest.mark.parametrize("relative", PHASE3_REQUIRED_FILES)
def test_missing_authority_fails(design_root: Path, relative: str) -> None:
    (design_root / relative).unlink()
    assert "missing or unreadable" in _details(design_root)


@pytest.mark.parametrize(
    ("relative", "before", "after", "message"),
    [
        (PHASE3_MATRIX, "P3-RISK-001", "P3-RISK-099", "30-row acceptance"),
        (PHASE3_LEDGER, "| P3-S48 |", "| P3-S49 |", "48-scenario"),
        (PHASE3_MANIFEST, "| P3-10 |", "| P3-11 |", "ten-package"),
        (PHASE3_REGISTRY, "get_risk_summary", "execute_order", "thirteen frozen"),
        (PHASE3_REGISTRY, "| COMMAND |", "| READ |", "three internal commands"),
        (PHASE3_REGISTRY, "| READ | true |", "| READ | false |", "annotations"),
        (PHASE3_MATRIX, "P3-S01,P3-S02,P3-S03", "P3-S99", "known mandatory"),
        (PHASE3_LEDGER, "| P3-S01 | P3-01 |", "| P3-S01 | P3-11 |", "frozen package"),
        (PHASE3_LEDGER, "| pending |", "| blocked_external |", "valid local state"),
    ],
)
def test_registry_and_traceability_mutations_fail(
    design_root: Path, relative: str, before: str, after: str, message: str
) -> None:
    _change(design_root, relative, before, after)
    assert message in _details(design_root)


@pytest.mark.parametrize("value", [31, 30.0, True, None])
def test_inventory_is_exact_and_strict(design_root: Path, value: object) -> None:
    progress = _read(design_root)
    progress["phases"]["phase_3"]["acceptance_inventory"]["locally_executable_rows_total"] = value
    _write(design_root, progress)
    assert "inventory must match" in _details(design_root)


def test_package_cannot_skip_its_acceptance_predicates(design_root: Path) -> None:
    progress = _read(design_root)
    progress["phases"]["phase_3"]["work_packages"]["P3-01"] = "complete"
    _write(design_root, progress)
    assert "cannot complete while assigned" in _details(design_root)


def _complete_s04(root: Path) -> dict[str, Any]:
    """Build synthetic evidence syntax solely to test the validator, not an actual run."""
    ledger = root / PHASE3_LEDGER
    lines = ledger.read_text().splitlines()
    for index, line in enumerate(lines):
        if line.startswith("| P3-S04 |"):
            lines[index] = line.replace("| pending |", "| complete |")
    ledger.write_text("\n".join(lines))
    relative = "tests/unit/analytics/test_phase3_risk.py"
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_risk_zero():\n    assert True\n")
    artifact = "docs/implementation/evidence/phase3-validator-fixture.json"
    target = root / artifact
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"source_sha": "a" * 40, "result": "passed", "requirements": ["P3-S04"]})
    )
    progress = _read(root)
    phase = progress["phases"]["phase_3"]
    phase["acceptance_inventory"]["mandatory_scenarios_complete"] = 1
    phase["acceptance"]["evidence"]["P3-S04"] = {
        "sha": "a" * 40,
        "test_nodes": [relative + "::test_risk_zero"],
        "commands": [{"command": "pytest " + relative, "exit_code": 0}],
        "artifacts": [artifact],
    }
    _write(root, progress)
    return progress


def test_source_bound_scenario_can_complete_without_completing_package(design_root: Path) -> None:
    _complete_s04(design_root)
    assert validate_phase3_design(design_root) == []


@pytest.mark.parametrize("mutation", ["source", "selector", "failed", "missing", "malformed_nodes"])
def test_completion_requires_actual_selector_and_matching_source(
    design_root: Path, mutation: str
) -> None:
    progress = _complete_s04(design_root)
    evidence = progress["phases"]["phase_3"]["acceptance"]["evidence"]["P3-S04"]
    if mutation == "source":
        evidence["sha"] = "b" * 40
    elif mutation == "selector":
        evidence["test_nodes"] = ["tests/unit/analytics/test_phase3_risk.py::missing"]
    elif mutation == "failed":
        evidence["commands"][0]["exit_code"] = 1
    elif mutation == "missing":
        (design_root / evidence["artifacts"][0]).unlink()
    else:
        evidence["test_nodes"] = None
    _write(design_root, progress)
    assert validate_phase3_design(design_root)


def test_design_cannot_claim_runtime_acceptance(design_root: Path) -> None:
    progress = _read(design_root)
    progress["phases"]["phase_3"]["design"]["runtime_acceptance"] = "accepted"
    _write(design_root, progress)
    assert "without runtime acceptance" in _details(design_root)
