"""Independent source/archive and ephemeral local release-evidence contracts."""

from __future__ import annotations

import base64
import builtins
import copy
import hashlib
import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

pytestmark = pytest.mark.unit

_COMMIT = "1" * 40
_TREE = "2" * 40
_CONTEXT = b"t212pi.local-release-evidence.v1\0"
_FILES = {"README.txt": (b"hello\n", "100644"), "scripts/check.sh": (b"exit 0\n", "100755")}


def _tool() -> ModuleType:
    path = Path("scripts/build_release_evidence.py")
    assert path.is_file(), "The reproducible local release-evidence tool is not implemented."
    spec = importlib.util.spec_from_file_location("release_evidence_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _source() -> dict[str, Any]:
    # Git blob identity and SHA256 are independently constructed from literal bytes.
    return {
        "schema_version": "t212pi.release-source.v1",
        "commit": _COMMIT,
        "tree": _TREE,
        "files": [
            {
                "path": path,
                "type": "blob",
                "mode": mode,
                "git_blob": hashlib.sha1(
                    b"blob " + str(len(data)).encode() + b"\0" + data, usedforsecurity=False
                ).hexdigest(),
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for path, (data, mode) in sorted(_FILES.items())
        ],
    }


def _archive(path: Path, mutation: str = "valid") -> None:
    with tarfile.open(path, "w") as archive:
        directory = tarfile.TarInfo("scripts/")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        for name, (original, mode) in _FILES.items():
            if mutation == "missing" and name == "README.txt":
                continue
            data = b"wrong\n" if mutation == "bytes" and name == "README.txt" else original
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(data), int(mode[-3:], 8)
            if mutation == "mode" and name == "README.txt":
                member.mode = 0o755
            archive.addfile(member, io.BytesIO(data))
            if mutation == "duplicate" and name == "README.txt":
                archive.addfile(member, io.BytesIO(data))
        if mutation in {"extra", "traversal", "absolute", "symlink", "hardlink", "fifo"}:
            name = {"traversal": "../outside", "absolute": "/outside"}.get(mutation, "extra")
            member = tarfile.TarInfo(name)
            if mutation in {"symlink", "hardlink", "fifo"}:
                member.type = {
                    "symlink": tarfile.SYMTYPE,
                    "hardlink": tarfile.LNKTYPE,
                    "fifo": tarfile.FIFOTYPE,
                }[mutation]
                member.linkname = "README.txt"
                archive.addfile(member)
            else:
                member.size = 1
                archive.addfile(member, io.BytesIO(b"x"))


def test_source_archive_matches_exact_git_blobs_types_modes_and_membership(tmp_path: Path) -> None:
    archive = tmp_path / "source.tar"
    _archive(archive)
    assert _tool().verify_source_archive(archive, _source()) is None


@pytest.mark.parametrize(
    "mutation",
    [
        "bytes",
        "mode",
        "missing",
        "extra",
        "duplicate",
        "traversal",
        "absolute",
        "symlink",
        "hardlink",
        "fifo",
    ],
)
def test_source_archive_rejects_changed_or_unsafe_members(tmp_path: Path, mutation: str) -> None:
    archive = tmp_path / "source.tar"
    _archive(archive, mutation)
    with pytest.raises(ValueError):
        _tool().verify_source_archive(archive, _source())


def test_source_archive_rejects_wrong_git_blob_even_when_sha256_and_bytes_match(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "source.tar"
    _archive(archive)
    source = _source()
    source["files"][0]["git_blob"] = "f" * 40
    with pytest.raises(ValueError):
        _tool().verify_source_archive(archive, source)


def _artifacts(root: Path) -> list[dict[str, object]]:
    root.mkdir()
    (root / "sbom").mkdir()
    contents = {"source.tar": b"archive-A", "sbom/image.spdx.json": b'{"spdxVersion":"SPDX-2.3"}'}
    result = []
    for path, data in sorted(contents.items()):
        (root / path).write_bytes(data)
        result.append({"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return result


def test_artifact_manifest_hashes_only_exact_regular_files(tmp_path: Path) -> None:
    root = tmp_path / "pack"
    expected = _artifacts(root)
    assert _tool().artifact_manifest(root, tuple(item["path"] for item in expected)) == expected


@pytest.mark.parametrize("mutation", ["traversal", "absolute", "symlink", "directory", "missing"])
def test_artifact_manifest_refuses_outside_or_nonregular_files(
    tmp_path: Path, mutation: str
) -> None:
    root = tmp_path / "pack"
    _artifacts(root)
    outside = tmp_path / "outside"
    outside.write_bytes(b"not a release artifact")
    names = {"traversal": "../outside", "absolute": str(outside), "directory": "sbom"}
    if mutation == "symlink":
        (root / "link").symlink_to(outside)
    name = names.get(mutation, "link" if mutation == "symlink" else "absent")
    with pytest.raises(ValueError):
        _tool().artifact_manifest(root, (name,))


def _inventory() -> dict[str, Any]:
    return {
        "source_commit": _COMMIT,
        "source_tree": _TREE,
        "images": [
            {"service": service, "image_id": "sha256:" + str(index) * 64}
            for index, service in enumerate(("postgres", "redis", "api", "worker", "mcp", "web"), 1)
        ],
        "alias_images": [
            {"service": service, "image_id": "sha256:" + "4" * 64}
            for service in ("migrate", "seed", "dispatcher")
        ],
    }


def test_image_inventory_preserves_six_canonical_services_and_all_distinct_alias_ids() -> None:
    inventory = _inventory()
    inventory["alias_images"][1]["image_id"] = "sha256:" + "a" * 64
    expected = tuple(
        sorted({row["image_id"] for row in (*inventory["images"], *inventory["alias_images"])})
    )
    assert _tool().validate_image_inventory(inventory, _COMMIT, _TREE) == expected
    assert len(inventory["images"]) == 6 and len(expected) == 7


@pytest.mark.parametrize("mutation", ["source", "missing", "duplicate", "mutable_tag", "extra"])
def test_image_inventory_rejects_unbound_or_expanded_scope(mutation: str) -> None:
    inventory = _inventory()
    if mutation == "source":
        inventory["source_commit"] = "9" * 40
    elif mutation == "missing":
        inventory["alias_images"].pop()
    elif mutation == "duplicate":
        inventory["images"][1]["service"] = "postgres"
    elif mutation == "mutable_tag":
        inventory["images"][0]["image_id"] = "postgres:latest"
    else:
        inventory["images"].append({"service": "unknown", "image_id": "sha256:" + "f" * 64})
    with pytest.raises(ValueError):
        _tool().validate_image_inventory(inventory, _COMMIT, _TREE)


def test_image_inventory_refuses_unknown_metadata_before_copying_it_into_provenance() -> None:
    inventory = _inventory()
    inventory["unexpected_metadata"] = {"operator_configuration": "synthetic private fixture"}
    with pytest.raises(ValueError):
        _tool().validate_image_inventory(inventory, _COMMIT, _TREE)


def _payload(artifacts: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "t212pi.local-release-evidence.v1",
        "scope": "local_ephemeral_demonstration",
        "source": {"commit": _COMMIT, "tree": _TREE},
        "artifacts": artifacts,
    }


def _key_hash(envelope: dict[str, Any]) -> str:
    return hashlib.sha256(base64.b64decode(envelope["public_key"], validate=True)).hexdigest()


def test_ephemeral_signing_performs_no_file_io_and_independent_public_key_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "pack"
    payload, tool = _payload(_artifacts(root)), _tool()

    def no_file_io(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "An ephemeral signing key or payload must never be written by signing."
        )

    with monkeypatch.context() as closed:
        closed.setattr(builtins, "open", no_file_io)
        closed.setattr(Path, "open", no_file_io)
        envelope = tool.sign_provenance(payload)
    assert set(envelope) == {"schema_version", "payload", "public_key", "signature"}
    assert envelope["payload"] == payload
    assert envelope["schema_version"] == "t212pi.ed25519-envelope.v1"
    public = base64.b64decode(envelope["public_key"], validate=True)
    signature = base64.b64decode(envelope["signature"], validate=True)
    assert len(public) == 32 and len(signature) == 64
    Ed25519PublicKey.from_public_bytes(public).verify(signature, _CONTEXT + _canonical(payload))
    assert tool.verify_provenance(envelope, root, _COMMIT, _TREE, _key_hash(envelope)) is None


@pytest.mark.parametrize(
    "mutation", ["source", "tree", "key", "payload", "signature", "artifact", "missing", "symlink"]
)
def test_verification_rejects_wrong_source_key_or_tampered_payload_and_artifacts(
    tmp_path: Path, mutation: str
) -> None:
    root = tmp_path / "pack"
    tool = _tool()
    envelope = tool.sign_provenance(_payload(_artifacts(root)))
    fingerprint = _key_hash(envelope)
    expected_commit, expected_tree = _COMMIT, _TREE
    if mutation == "source":
        expected_commit = "9" * 40
    elif mutation == "tree":
        expected_tree = "9" * 40
    elif mutation == "key":
        envelope = tool.sign_provenance(copy.deepcopy(envelope["payload"]))
    elif mutation == "payload":
        envelope["payload"]["scope"] = "production_attestation"
    elif mutation == "signature":
        changed = bytearray(base64.b64decode(envelope["signature"]))
        changed[0] ^= 1
        envelope["signature"] = base64.b64encode(changed).decode()
    elif mutation == "artifact":
        (root / "source.tar").write_bytes(b"archive-B")  # Same length, different bytes.
    elif mutation == "missing":
        (root / "source.tar").unlink()
    else:
        original = root / "source.tar"
        outside = tmp_path / "outside"
        original.replace(outside)
        original.symlink_to(outside)
    with pytest.raises(ValueError):
        tool.verify_provenance(envelope, root, expected_commit, expected_tree, fingerprint)
