"""Current status never promotes historical reports into remediation acceptance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.validate_repository import validate_current_release_status
from tests.status_fixtures import restore_phase2_selectors

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = ("PROJECT_STATUS.json", "PROJECT_PROGRESS.json")
pytestmark = pytest.mark.contract


def _read(root: Path, name: str) -> dict[str, Any]:
    value: dict[str, Any] = json.loads((root / name).read_text(encoding="utf-8"))
    return value


def _write(root: Path, name: str, value: dict[str, Any]) -> None:
    (root / name).write_text(json.dumps(value), encoding="utf-8")


def _candidate(root: Path, **updates: object) -> None:
    for name in DOCUMENTS:
        document = _read(root, name)
        candidate = document["current_candidate"]
        candidate.update(updates)
        current = document["current_evidence"]
        for key in (
            "implementation_source_sha",
            "implementation_tree_sha",
            "documentation_delivery_sha",
            "local_validation_status",
            "independent_review_status",
            "ci_status",
            "ci_verified",
        ):
            current[key] = candidate[key]
        current["artifact"] = candidate["local_validation_evidence"]
        if name == "PROJECT_STATUS.json":
            active = document["current_work_package"]
        else:
            phase = document["phases"]["phase_2"]
            active = phase["current_implementation"]
            phase["candidate_validation"]["source_sha"] = candidate["implementation_source_sha"]
        active["source_sha"] = candidate["implementation_source_sha"]
        active["status"] = candidate["implementation_status"]
        _write(root, name, document)


def _details(root: Path) -> str:
    return "\n".join(failure.detail for failure in validate_current_release_status(root))


@pytest.fixture
def status_root(tmp_path: Path) -> Path:
    for name in DOCUMENTS:
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    restore_phase2_selectors(tmp_path)
    relative = _read(tmp_path, DOCUMENTS[0])["historical_evidence"]["phase_2"]["artifact"]["path"]
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((ROOT / relative).read_bytes())
    # Keep tests independent of ROOT later recording actual candidate evidence.
    _candidate(
        tmp_path,
        implementation_source_sha=None,
        implementation_tree_sha=None,
        documentation_delivery_sha=None,
        implementation_status="in_progress",
        local_validation_status="pending",
        local_validation_evidence=None,
        independent_review_status="pending",
        independent_review_evidence=None,
    )
    return tmp_path


def _local_result(root: Path, result: str = "passed") -> dict[str, object]:
    """Synthetic contract fixture, never an application execution record."""
    path = root / "candidate-fixture.json"
    raw = json.dumps({"source_sha": "a" * 40, "tree_sha": "b" * 40, "result": result}).encode(
        "utf-8"
    )
    path.write_bytes(raw)
    ref: dict[str, object] = {
        "path": path.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }
    _candidate(
        root,
        implementation_source_sha="a" * 40,
        implementation_tree_sha="b" * 40,
        implementation_status=(
            "implemented_pending_independent_review"
            if result == "passed"
            else "implemented_unverified"
        ),
        local_validation_status=result,
        local_validation_evidence=ref,
    )
    return ref


def test_repository_has_explicit_current_and_historical_selectors() -> None:
    assert validate_current_release_status(ROOT) == []


def test_pending_source_preserves_historical_stage_a_and_phase2(status_root: Path) -> None:
    assert validate_current_release_status(status_root) == []
    status = _read(status_root, DOCUMENTS[0])
    assert status["release_candidate_sha"] == status["validated_evidence"]["sha"]
    assert status["current_candidate"]["implementation_source_sha"] is None
    assert (
        status["historical_evidence"]["phase_2"]["implementation_source_sha"]
        != status["validated_evidence"]["sha"]
    )


@pytest.mark.parametrize("result", ["passed", "failed"])
def test_own_source_result_does_not_close_independent_review(
    status_root: Path, result: str
) -> None:
    _local_result(status_root, result)
    assert validate_current_release_status(status_root) == []
    candidate = _read(status_root, DOCUMENTS[0])["current_candidate"]
    assert candidate["independent_review_status"] == "pending"
    assert candidate["documentation_delivery_sha"] is None
    assert candidate["ci_verified"] is False
    current = _read(status_root, DOCUMENTS[0])["current_evidence"]
    assert current["scope"] == "current_candidate"
    assert current["implementation_source_sha"] == candidate["implementation_source_sha"]
    assert current["local_validation_status"] == result
    assert current["artifact"] == candidate["local_validation_evidence"]


@pytest.mark.parametrize("selector", ["current_candidate", "current_evidence"])
@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong_type"])
def test_new_selectors_are_closed_objects(status_root: Path, selector: str, mutation: str) -> None:
    for name in DOCUMENTS:
        document = _read(status_root, name)
        if mutation == "missing":
            document[selector].pop("phase")
        elif mutation == "extra":
            document[selector]["accepted"] = True
        else:
            document[selector] = []
        _write(status_root, name, document)
    assert "must contain exactly" in _details(status_root)


def test_divergent_status_documents_are_rejected(status_root: Path) -> None:
    document = _read(status_root, DOCUMENTS[0])
    document["current_candidate"]["implementation_status"] = "implemented_unverified"
    _write(status_root, DOCUMENTS[0], document)
    assert "current_candidate must agree" in _details(status_root)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("implementation_tree_sha", "b" * 40, "uncommitted candidate"),
        ("documentation_delivery_sha", "c" * 40, "uncommitted candidate"),
        ("local_validation_status", "passed", "uncommitted candidate"),
        ("independent_review_status", "accepted", "must await independent review"),
        ("independent_review_evidence", {"result": "approved"}, "must await independent review"),
        ("ci_status", "passed", "deferred, unverified CI"),
        ("ci_verified", 1, "deferred, unverified CI"),
        ("local_validation_evidence", {"result": "passed"}, "cannot carry a copied"),
    ],
)
def test_pending_candidate_rejects_premature_claims(
    status_root: Path, key: str, value: object, message: str
) -> None:
    _candidate(status_root, **{key: value})
    assert message in _details(status_root)


@pytest.mark.parametrize("identity", ["stage_a", "prior_source", "prior_delivery"])
def test_historical_identity_cannot_be_the_remediation_source(
    status_root: Path, identity: str
) -> None:
    status = _read(status_root, DOCUMENTS[0])
    old = status["historical_evidence"]["phase_2"]
    source = {
        "stage_a": status["release_candidate_sha"],
        "prior_source": old["implementation_source_sha"],
        "prior_delivery": old["documentation_delivery_sha"],
    }[identity]
    _candidate(status_root, implementation_source_sha=source, implementation_tree_sha="b" * 40)
    assert "requires a new implementation source/tree" in _details(status_root)


def test_old_evidence_cannot_validate_a_new_source(status_root: Path) -> None:
    _local_result(status_root)
    prior = _read(status_root, DOCUMENTS[0])["historical_evidence"]["phase_2"]["artifact"]
    _candidate(status_root, local_validation_evidence=prior)
    details = _details(status_root)
    assert "must bind its own source/tree and actual result" in details
    assert "historical evidence cannot validate" in details


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("path", "missing.json"),
        ("sha256", "0" * 64),
        ("bytes", True),
        ("bytes", 1),
        ("unreviewed", True),
    ],
)
def test_candidate_artifact_reference_is_strictly_bound(
    status_root: Path, key: str, value: object
) -> None:
    ref = _local_result(status_root)
    ref[key] = value
    _candidate(status_root, local_validation_evidence=ref)
    assert "candidate validation evidence" in _details(status_root)


@pytest.mark.parametrize("field", ["source_sha", "tree_sha", "result"])
def test_even_correct_hash_does_not_hide_wrong_evidence_identity(
    status_root: Path, field: str
) -> None:
    ref = _local_result(status_root)
    path = status_root / str(ref["path"])
    document = json.loads(path.read_bytes())
    document[field] = "failed" if field == "result" else "c" * 40
    raw = json.dumps(document).encode("utf-8")
    path.write_bytes(raw)
    ref.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    _candidate(status_root, local_validation_evidence=ref)
    assert "must bind its own source/tree and actual result" in _details(status_root)


def test_evidence_symlink_cannot_escape_repository(status_root: Path, tmp_path: Path) -> None:
    ref = _local_result(status_root)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside.write_bytes((status_root / str(ref["path"])).read_bytes())
    link = status_root / "outside-link.json"
    link.symlink_to(outside)
    ref["path"] = link.name
    _candidate(status_root, local_validation_evidence=ref)
    assert "existing repository file" in _details(status_root)


@pytest.mark.parametrize("name", DOCUMENTS)
def test_legacy_selectors_must_be_explicitly_historical(status_root: Path, name: str) -> None:
    document = _read(status_root, name)
    document["legacy_evidence_scopes"].pop("/release_readiness")
    _write(status_root, name, document)
    assert "historical compatibility scopes" in _details(status_root)


def test_historical_artifact_must_keep_its_actual_hash(status_root: Path) -> None:
    for name in DOCUMENTS:
        document = _read(status_root, name)
        document["historical_evidence"]["phase_2"]["artifact"]["sha256"] = "0" * 64
        _write(status_root, name, document)
    assert "hash or byte length differs" in _details(status_root)


def test_active_compatibility_fields_cannot_keep_a_historical_pass(status_root: Path) -> None:
    document = _read(status_root, DOCUMENTS[1])
    phase = document["phases"]["phase_2"]
    phase["current_implementation"]["status"] = "complete"
    phase["candidate_validation"]["acceptance_claim"] = True
    _write(status_root, DOCUMENTS[1], document)
    details = _details(status_root)
    assert "active compatibility selectors" in details
    assert "candidate_validation must not retain a historical pass" in details


def test_historical_ledger_cannot_be_promoted_to_current_completion(status_root: Path) -> None:
    document = _read(status_root, DOCUMENTS[1])
    document["phases"]["phase_2"]["acceptance"]["status"] = "complete"
    _write(status_root, DOCUMENTS[1], document)
    assert "pending beside the historical Phase 2 ledger" in _details(status_root)


def test_current_evidence_cannot_select_historical_report(status_root: Path) -> None:
    for name in DOCUMENTS:
        document = _read(status_root, name)
        document["current_evidence"] = document["historical_evidence"]["phase_2"]
        _write(status_root, name, document)
    assert "must describe this candidate" in _details(status_root)


def test_local_pass_has_precise_pending_independent_review_state(status_root: Path) -> None:
    _local_result(status_root)
    _candidate(status_root, implementation_status="implemented_unverified")
    assert "a local pass must be implemented_pending_independent_review" in _details(status_root)


def test_pending_validation_cannot_claim_locally_passed_implementation(status_root: Path) -> None:
    _candidate(status_root, implementation_status="implemented_pending_independent_review")
    assert "a local pass must be implemented_pending_independent_review" in _details(status_root)
