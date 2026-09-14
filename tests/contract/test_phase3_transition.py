"""An owner-authorized transition never self-certifies a new release."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.validate_repository import (
    PHASE3_AUTHORIZATION_PATH,
    validate_current_release_status,
)

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = ("PROJECT_STATUS.json", "PROJECT_PROGRESS.json")
pytestmark = pytest.mark.contract


@pytest.fixture
def transition_root(tmp_path: Path) -> Path:
    paths = [*DOCUMENTS, PHASE3_AUTHORIZATION_PATH]
    status = json.loads((ROOT / DOCUMENTS[0]).read_bytes())
    paths.append(status["historical_evidence"]["phase_2"]["artifact"]["path"])
    owner = json.loads((ROOT / PHASE3_AUTHORIZATION_PATH).read_bytes())
    paths.append(owner["local_validation_evidence"]["path"])
    for relative in paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    return tmp_path


def _mutate(root: Path, pointer: str, value: object, names: tuple[str, ...] = DOCUMENTS) -> None:
    for name in names:
        path = root / name
        document: dict[str, Any] = json.loads(path.read_bytes())
        parent = document
        keys = pointer.strip("/").split("/")
        for key in keys[:-1]:
            parent = parent[key]
        parent[keys[-1]] = value
        path.write_text(json.dumps(document), encoding="utf-8")


def _details(root: Path) -> str:
    return "\n".join(f.detail for f in validate_current_release_status(root))


def test_authorized_owner_progression_preserves_pending_phase3(transition_root: Path) -> None:
    assert validate_current_release_status(transition_root) == []
    status = json.loads((transition_root / DOCUMENTS[0]).read_bytes())
    assert status["current_candidate"]["phase"] == "phase_3"
    assert status["current_candidate"]["local_validation_evidence"] is None
    owner = json.loads((transition_root / PHASE3_AUTHORIZATION_PATH).read_bytes())
    assert owner["independent_verification"]["full_local_archives_inspected"] is False
    assert owner["independent_verification"]["full_gates_independently_rerun"] is False


@pytest.mark.parametrize(
    ("pointer", "value", "message"),
    [
        ("/phase_transition/authority", "implementing_agent", "owner authority"),
        ("/phase_transition/scope", "production_release", "owner authority"),
        ("/phase_transition/source_sha", "a" * 40, "owner authority"),
        ("/phase_transition/tree_sha", "b" * 40, "owner authority"),
        ("/phase_transition/delivery_sha", "c" * 40, "owner authority"),
        ("/phase_transition/to_phase", "phase_4", "owner authority"),
        ("/phase_transition/decision", "independently_accepted", "owner authority"),
        ("/phase_transition/evidence/sha256", "a" * 64, "owner authority"),
        ("/phase_transition/evidence/bytes", True, "owner authority"),
        ("/phase_transition/evidence/bytes", 1193.0, "owner authority"),
        ("/schema_version", 3, "unsupported status schema"),
        ("/schema_version", 2.0, "schema_version 2"),
        ("/production_readiness", "accepted", "not_authorized"),
        ("/current_candidate/independent_review_status", "accepted", "await independent review"),
        ("/current_candidate/ci_status", "passed", "deferred, unverified CI"),
        ("/current_evidence/ci_verified", True, "deferred, unverified CI"),
        (
            "/current_candidate/implementation_source_sha",
            "f88b0199b2d8691ff89101b7991e9bb0fea1d1ca",
            "new implementation source/tree",
        ),
        (
            "/current_candidate/implementation_source_sha",
            "d2ebdaf96d1b61aacea5c6492824946540f88803",
            "new implementation source/tree",
        ),
    ],
)
def test_transition_rejects_unsupported_claims(
    transition_root: Path, pointer: str, value: object, message: str
) -> None:
    _mutate(transition_root, pointer, value)
    assert message in _details(transition_root)


def test_rehashed_agent_approval_cannot_replace_owner_source(transition_root: Path) -> None:
    path = transition_root / PHASE3_AUTHORIZATION_PATH
    owner = json.loads(path.read_bytes())
    owner["authority"] = "implementing_agent"
    raw = json.dumps(owner).encode()
    path.write_bytes(raw)
    _mutate(transition_root, "/phase_transition/evidence/sha256", hashlib.sha256(raw).hexdigest())
    _mutate(transition_root, "/phase_transition/evidence/bytes", len(raw))
    assert "retained reviewed owner authorization artifact" in _details(transition_root)


def test_owner_record_does_not_replace_missing_local_evidence(transition_root: Path) -> None:
    owner = json.loads((transition_root / PHASE3_AUTHORIZATION_PATH).read_bytes())
    (transition_root / owner["local_validation_evidence"]["path"]).unlink()
    assert "corrected Phase 2 source-bound local result" in _details(transition_root)


@pytest.mark.parametrize(
    "field", ["owner_acceptance_status", "independent_review_status", "status"]
)
def test_phase3_cannot_inherit_phase2_acceptance(transition_root: Path, field: str) -> None:
    _mutate(transition_root, f"/phases/phase_3/acceptance/{field}", "accepted", (DOCUMENTS[1],))
    assert "cannot inherit" in _details(transition_root)


def test_package_completion_requires_its_own_evidence(transition_root: Path) -> None:
    _mutate(transition_root, "/phases/phase_3/work_packages/P3-01", "complete", (DOCUMENTS[1],))
    _mutate(transition_root, "/phases/phase_3/progress_percent", 10, (DOCUMENTS[1],))
    assert "P3-01 requires" in _details(transition_root)


def test_one_sided_transition_is_rejected(transition_root: Path) -> None:
    _mutate(transition_root, "/phase_transition/decision", "pending", (DOCUMENTS[1],))
    assert "owner authority" in _details(transition_root)
