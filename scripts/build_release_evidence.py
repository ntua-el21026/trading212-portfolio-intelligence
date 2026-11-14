"""Local, ephemeral release evidence; never a production or distribution attestation.

Build requires a clean committed source and a terminal build binding containing
run.py source bookends plus the actual nine-service ``image_ids`` mapping. Preserve
the original receipt and reference its SHA256 as ``original_receipt_sha256``.
Only the configured local Docker images and offline Trivy cache are consulted.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

_CONTEXT = b"t212pi.local-release-evidence.v1\0"
_PAYLOAD_SCHEMA = "t212pi.local-release-evidence.v1"
_ENVELOPE_SCHEMA = "t212pi.ed25519-envelope.v1"
_SCOPE = "local_ephemeral_demonstration"
_CANONICAL = ("postgres", "redis", "api", "worker", "mcp", "web")
_ALIASES = ("migrate", "seed", "dispatcher")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT = re.compile(r"^[0-9a-f]{40}$")
_IMAGE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_FILE = 512 * 1024 * 1024
_MAX_TOTAL = 2 * 1024 * 1024 * 1024
_MAX_JSON = 2 * 1024 * 1024
_MAX_FILES = 100_000
_MAX_ARTIFACTS = 32


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("An object with fixed string keys is required.")
    return cast(dict[str, object], value)


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("A bounded array is required.")
    return value


def _text(value: object, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or (pattern is not None and pattern.fullmatch(value) is None):
        raise ValueError("The declared identity is invalid.")
    return value


def _relative(value: object) -> str:
    name = _text(value)
    path = PurePosixPath(name)
    if (
        not name
        or len(name) > 4096
        or "\\" in name
        or "\0" in name
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in name.split("/"))
        or str(path) != name
    ):
        raise ValueError("Only normalized relative artifact paths are allowed.")
    return name


def _regular(path: Path, *, maximum: int = _MAX_FILE) -> int:
    try:
        status = path.lstat()
    except OSError:
        raise ValueError("The declared regular file is unavailable.") from None
    if not stat.S_ISREG(status.st_mode) or status.st_size > maximum:
        raise ValueError("The declared artifact is not a bounded regular file.")
    return status.st_size


def _file(root: Path, name: str) -> Path:
    name = _relative(name)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("A real artifact directory is required.")
    current = root
    for part in PurePosixPath(name).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("Artifact symlinks are forbidden.")
    _regular(current)
    return current


def _hash(path: Path, *, maximum: int = _MAX_FILE) -> str:
    _regular(path, maximum=maximum)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while data := source.read(1024 * 1024):
            digest.update(data)
    return digest.hexdigest()


def _canonical(value: object) -> bytes:
    def check(item: object, depth: int = 0) -> None:
        if depth > 20:
            raise ValueError("Release metadata nesting exceeds its bound.")
        if item is None or type(item) in {str, int, bool}:
            return
        if isinstance(item, (tuple, list)):
            for child in item:
                check(child, depth + 1)
        elif isinstance(item, dict) and all(isinstance(key, str) for key in item):
            for child in item.values():
                check(child, depth + 1)
        else:
            raise ValueError("Only closed JSON scalars and collections are supported.")

    check(value)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    if len(encoded) > _MAX_JSON:
        raise ValueError("Release metadata exceeds its byte bound.")
    return encoded


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys are forbidden.")
        result[key] = value
    return result


def _json(path: Path, *, maximum: int = _MAX_JSON) -> object:
    _regular(path, maximum=maximum)
    return cast(object, json.loads(path.read_bytes(), object_pairs_hook=_pairs))


def _write(path: Path, value: object) -> None:
    with path.open("xb") as target:
        target.write(_canonical(value) + b"\n")
    path.chmod(0o600)


def artifact_manifest(root: Path, paths: Sequence[str]) -> list[dict[str, object]]:
    if not 0 < len(paths) <= _MAX_ARTIFACTS or len(set(paths)) != len(paths):
        raise ValueError("Artifact membership is empty, duplicated or unbounded.")
    result = []
    total = 0
    for name in sorted(paths):
        path = _file(root, name)
        size = _regular(path)
        total += size
        if total > _MAX_TOTAL:
            raise ValueError("The evidence bundle exceeds its byte bound.")
        result.append({"path": name, "size": size, "sha256": _hash(path)})
    return result


def verify_source_archive(archive: Path, manifest: object) -> None:
    source = _object(manifest)
    if set(source) != {"schema_version", "commit", "tree", "files"}:
        raise ValueError("The source manifest schema differs.")
    if source["schema_version"] != "t212pi.release-source.v1":
        raise ValueError("The source manifest version differs.")
    _text(source["commit"], _GIT)
    _text(source["tree"], _GIT)
    files = _array(source["files"])
    if not 0 < len(files) <= _MAX_FILES:
        raise ValueError("The committed source inventory exceeds its bound.")
    expected: dict[str, dict[str, object]] = {}
    directories: set[str] = set()
    for value in files:
        row = _object(value)
        if set(row) != {"path", "type", "mode", "git_blob", "size", "sha256"}:
            raise ValueError("The source entry schema differs.")
        name = _relative(row["path"])
        if name in expected or row["type"] != "blob" or row["mode"] not in {"100644", "100755"}:
            raise ValueError("Source paths/types/modes must be exact and unique.")
        _text(row["git_blob"], _GIT)
        _text(row["sha256"], _SHA256)
        if type(row["size"]) is not int or not 0 <= row["size"] <= _MAX_FILE:
            raise ValueError("The source entry size exceeds its bound.")
        expected[name] = row
        directories.update(
            str(parent) for parent in PurePosixPath(name).parents if str(parent) != "."
        )
    _regular(archive)
    seen, seen_directories = set(), set()
    total = 0
    try:
        with tarfile.open(archive, "r:") as retained:
            for index, member in enumerate(retained):
                if index >= _MAX_FILES * 2:
                    raise ValueError("The archive entry count exceeds its bound.")
                name = _relative(member.name.rstrip("/") if member.isdir() else member.name)
                if member.isdir():
                    if name not in directories or name in seen_directories:
                        raise ValueError("An undeclared or duplicate source directory is present.")
                    seen_directories.add(name)
                    continue
                if not member.isfile() or name not in expected or name in seen:
                    raise ValueError("An unsafe, extra or duplicate archive member is present.")
                row = expected[name]
                if member.size != row["size"] or member.mode & 0o7777 != int(
                    _text(row["mode"])[-3:], 8
                ):
                    raise ValueError("The archive member size or mode differs from Git.")
                total += member.size
                if total > _MAX_FILE:
                    raise ValueError("The source archive exceeds its byte bound.")
                stream = retained.extractfile(member)
                if stream is None:
                    raise ValueError("The regular archive member is unavailable.")
                sha = hashlib.sha256()
                blob = hashlib.sha1(  # Git SHA1 identity is additional to SHA256 integrity.
                    b"blob " + str(member.size).encode() + b"\0", usedforsecurity=False
                )
                with stream:
                    while data := stream.read(1024 * 1024):
                        sha.update(data)
                        blob.update(data)
                if sha.hexdigest() != row["sha256"] or blob.hexdigest() != row["git_blob"]:
                    raise ValueError("The archive bytes differ from the exact committed Git blob.")
                seen.add(name)
    except (tarfile.TarError, OSError):
        raise ValueError("The source archive could not be verified.") from None
    if seen != set(expected):
        raise ValueError("The archive omits committed source paths.")


def validate_image_inventory(
    value: object, expected_commit: str, expected_tree: str
) -> tuple[str, ...]:
    inventory = _object(value)
    if set(inventory) != {"source_commit", "source_tree", "images", "alias_images"}:
        raise ValueError("Only the closed candidate source and image inventory fields are allowed.")
    if (inventory.get("source_commit"), inventory.get("source_tree")) != (
        expected_commit,
        expected_tree,
    ):
        raise ValueError("The images belong to another source, not this candidate.")
    identifiers = set()
    for field, services in (("images", _CANONICAL), ("alias_images", _ALIASES)):
        rows = _array(inventory.get(field))
        names = []
        for value in rows:
            row = _object(value)
            if set(row) != {"service", "image_id"}:
                raise ValueError("Only fixed service/actual-image identities are supported.")
            names.append(_text(row["service"]))
            identifiers.add(_text(row["image_id"], _IMAGE))
        if len(names) != len(services) or set(names) != set(services):
            raise ValueError("The canonical six and three startup aliases must remain exact.")
    return tuple(sorted(identifiers))


def _payload(value: object) -> dict[str, object]:
    payload = _object(value)
    required = {"schema_version", "scope", "source", "artifacts"}
    if not required <= set(payload) or set(payload) - required - {
        "image_inventory",
        "build",
        "trivy",
    }:
        raise ValueError("The local provenance schema differs.")
    if payload["schema_version"] != _PAYLOAD_SCHEMA or payload["scope"] != _SCOPE:
        raise ValueError("Only local ephemeral demonstration evidence is supported.")
    source = _object(payload["source"])
    if set(source) != {"commit", "tree"}:
        raise ValueError("An exact committed source identity is required.")
    _text(source["commit"], _GIT)
    _text(source["tree"], _GIT)
    records = _array(payload["artifacts"])
    if not 0 < len(records) <= _MAX_ARTIFACTS:
        raise ValueError("The artifact inventory exceeds its bound.")
    for value in records:
        row = _object(value)
        if set(row) != {"path", "size", "sha256"}:
            raise ValueError("The artifact descriptor schema differs.")
        _relative(row["path"])
        _text(row["sha256"], _SHA256)
        if type(row["size"]) is not int or not 0 <= row["size"] <= _MAX_FILE:
            raise ValueError("The artifact descriptor size exceeds its bound.")
    _canonical(payload)
    return payload


def sign_provenance(payload: dict[str, object]) -> dict[str, object]:
    payload = _payload(payload)
    key = Ed25519PrivateKey.generate()
    signature = key.sign(_CONTEXT + _canonical(payload))
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return {
        "schema_version": _ENVELOPE_SCHEMA,
        "payload": payload,
        "public_key": base64.b64encode(public).decode("ascii"),
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def verify_provenance(
    envelope: object,
    artifact_root: Path,
    expected_commit: str,
    expected_tree: str,
    expected_public_key_sha256: str,
) -> None:
    signed = _object(envelope)
    if set(signed) != {"schema_version", "payload", "public_key", "signature"}:
        raise ValueError("The signature envelope schema differs.")
    if signed["schema_version"] != _ENVELOPE_SCHEMA:
        raise ValueError("The signature envelope version differs.")
    payload = _payload(signed["payload"])
    if _object(payload["source"]) != {"commit": expected_commit, "tree": expected_tree}:
        raise ValueError("The signed evidence belongs to another source.")
    try:
        public = base64.b64decode(_text(signed["public_key"]), validate=True)
        signature = base64.b64decode(_text(signed["signature"]), validate=True)
        if (
            len(public) != 32
            or len(signature) != 64
            or hashlib.sha256(public).hexdigest() != expected_public_key_sha256
        ):
            raise ValueError("The expected ephemeral public-key identity differs.")
        Ed25519PublicKey.from_public_bytes(public).verify(signature, _CONTEXT + _canonical(payload))
    except InvalidSignature:
        raise ValueError("The local release-evidence signature is invalid.") from None
    records = _array(payload["artifacts"])
    actual = artifact_manifest(artifact_root, tuple(_text(_object(row)["path"]) for row in records))
    if actual != records:
        raise ValueError("A signed artifact's exact bytes or membership changed.")


def _run(
    program: Literal["git", "docker", "trivy"],
    arguments: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: int = 30,
    binary: Path | None = None,
    maximum: int = _MAX_JSON,
) -> bytes:
    if program in {"git", "docker"}:
        found = shutil.which(program)
        if found is None:
            raise ValueError("The required fixed local executable is unavailable.")
        executable = Path(found).resolve()
    elif program == "trivy":
        if binary is None or binary.name != "trivy" or not binary.is_absolute():
            raise ValueError("The operator-selected pinned Trivy executable is required.")
        executable = binary
    else:
        raise ValueError("Only the closed local Git/Docker/Trivy operations are supported.")
    _regular(executable)
    if not executable.is_absolute() or not os.access(executable, os.X_OK):
        raise ValueError("A real absolute local executable is required.")
    # Operator-only boundary: fixed executable names or hash-qualified Trivy;
    # internal callers supply closed operations and validated identities/paths.
    result = subprocess.run(  # noqa: S603 -- fixed local executable and validated argv.
        [str(executable), *arguments],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        shell=False,
        capture_output=True,
        check=True,
        timeout=timeout,
    )
    if len(result.stdout) > maximum or len(result.stderr) > _MAX_JSON:
        raise ValueError("The local tool's diagnostic output exceeds its bound.")
    return result.stdout


def _git(repository: Path, *arguments: str, maximum: int = _MAX_JSON) -> bytes:
    return _run("git", arguments, cwd=repository, maximum=maximum)


def _bookend(repository: Path, commit: str, tree: str) -> None:
    if (
        _git(repository, "rev-parse", "HEAD").decode().strip() != commit
        or _git(repository, "rev-parse", "HEAD^{tree}").decode().strip() != tree
        or _git(repository, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    ):
        raise ValueError("The expected committed source must be exact and clean.")


def _source_manifest(repository: Path, commit: str, tree: str) -> dict[str, object]:
    entries = _git(repository, "ls-tree", "-rz", "--full-tree", commit).split(b"\0")
    files = []
    total = 0
    for entry in entries:
        if not entry:
            continue
        header, raw_path = entry.split(b"\t", 1)
        mode, kind, blob = header.decode("ascii").split()
        _text(blob, _GIT)
        name = _relative(raw_path.decode("utf-8"))
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError("This finite source exporter supports regular Git blobs only.")
        size = int(_git(repository, "cat-file", "-s", blob))
        total += size
        if size > _MAX_FILE or total > _MAX_FILE:
            raise ValueError("The exact committed source exceeds its byte bound.")
        data = _git(repository, "cat-file", "blob", blob, maximum=_MAX_FILE)
        if len(data) != size:
            raise ValueError("The committed source object's size changed.")
        files.append(
            {
                "path": name,
                "type": kind,
                "mode": mode,
                "git_blob": blob,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
        if len(files) > _MAX_FILES:
            raise ValueError("The source inventory exceeds its bound.")
    return {
        "schema_version": "t212pi.release-source.v1",
        "commit": commit,
        "tree": tree,
        "files": sorted(files, key=lambda row: _text(row["path"])),
    }


def _build_binding(receipt: object, inventory: object, commit: str, tree: str) -> dict[str, object]:
    value = _object(receipt)
    before = _text(value.get("source_manifest_sha256"), _SHA256)
    if (
        value.get("exit_code") != 0
        or value.get("source_unchanged") is not True
        or (value.get("head_before"), value.get("head"), value.get("tree"))
        != (commit, commit, tree)
        or value.get("source_after_manifest_sha256") != before
    ):
        raise ValueError("A successful exact-source terminal image build is required.")
    ids = _object(value.get("image_ids"))
    current = _object(inventory)
    rows = (*_array(current["images"]), *_array(current["alias_images"]))
    expected = {_text(_object(row)["service"]): _object(row)["image_id"] for row in rows}
    if ids != expected:
        raise ValueError("The inventory differs from the actual terminal build image IDs.")
    return {
        "original_receipt_sha256": _text(value.get("original_receipt_sha256"), _SHA256),
        "head_before": commit,
        "head": commit,
        "tree": tree,
        "source_unchanged": True,
        "source_manifest_sha256": before,
        "source_after_manifest_sha256": before,
        "image_ids": ids,
        "exit_code": 0,
    }


def _trivy_metadata(binary: Path, cache: Path) -> dict[str, object]:
    metadata = cache / "db" / "metadata.json"
    database = cache / "db" / "trivy.db"
    return {
        "binary_sha256": _hash(binary),
        "version": _run("trivy", ("--version",), binary=binary).decode().strip(),
        "db_metadata": _json(metadata),
        "db_metadata_sha256": _hash(metadata),
        "db_sha256": _hash(database, maximum=_MAX_TOTAL),
        "db_bytes": _regular(database, maximum=_MAX_TOTAL),
        "scope": "offline SBOM generation; database freshness is not asserted",
    }


def _image_id(identifier: str) -> None:
    if (
        _run("docker", ("image", "inspect", "--format", "{{.Id}}", identifier)).decode().strip()
        != identifier
    ):
        raise ValueError("The actual local immutable image identity differs.")


def _verify_bundle(root: Path, commit: str, tree: str, fingerprint: str) -> None:
    envelope = _json(_file(root, "signature.json"))
    verify_provenance(envelope, root, commit, tree, fingerprint)
    payload = _payload(_object(envelope)["payload"])
    if not {"image_inventory", "build", "trivy"} <= set(payload):
        raise ValueError("The complete candidate machinery records are missing.")
    inventory = _json(_file(root, "images.json"))
    identifiers = validate_image_inventory(inventory, commit, tree)
    if payload["image_inventory"] != inventory:
        raise ValueError("The signed image inventory differs from the packaged inventory.")
    source = _object(_json(_file(root, "source-files.json")))
    if (source.get("commit"), source.get("tree")) != (commit, tree):
        raise ValueError("The archived source manifest belongs to another source.")
    verify_source_archive(_file(root, "source.tar"), source)
    binding = _build_binding(_json(_file(root, "build-binding.json")), inventory, commit, tree)
    signed_build = _object(payload["build"])
    selected_hash = _text(signed_build.get("selected_binding_sha256"), _SHA256)
    if signed_build != {**binding, "selected_binding_sha256": selected_hash}:
        raise ValueError("The packaged terminal build binding differs from signed provenance.")
    metadata = _object(_json(_file(root, "trivy-metadata.json")))
    if metadata.get("before") != metadata.get("after"):
        raise ValueError("The offline tool/database bookends differ.")
    tool_before = _object(metadata.get("before"))
    if payload["trivy"] != {"binary_sha256": tool_before.get("binary_sha256"), "offline": True}:
        raise ValueError("The signed tool identity differs from its retained metadata.")
    for identifier in identifiers:
        sbom = _object(
            _json(_file(root, f"sbom/{identifier[7:]}.spdx.json"), maximum=64 * 1024 * 1024)
        )
        if sbom.get("spdxVersion") not in {"SPDX-2.2", "SPDX-2.3"} or not isinstance(
            sbom.get("packages"), list
        ):
            raise ValueError("The actual image SBOM is not the declared SPDX inventory.")
    declared = {_text(_object(row)["path"]) for row in _array(payload["artifacts"])}
    fixed = {
        "source.tar",
        "source-files.json",
        "images.json",
        "build-binding.json",
        "trivy-metadata.json",
    }
    fixed.update(f"sbom/{identifier[7:]}.spdx.json" for identifier in identifiers)
    if declared != fixed:
        raise ValueError("The finite source/build/tool/SBOM artifact membership differs.")
    allowed = declared | {"provenance.json", "signature.json", "verification.json"}
    observed = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("Evidence-pack symlinks are forbidden.")
        if path.is_file():
            observed.add(path.relative_to(root).as_posix())
    if observed - allowed or not declared <= observed:
        raise ValueError("The evidence pack contains undeclared or missing files.")
    if _json(_file(root, "provenance.json")) != payload:
        raise ValueError("The standalone provenance differs from the signed payload.")
    if (root / "verification.json").exists():
        result = _object(_json(_file(root, "verification.json")))
        expected = {
            "source_commit": commit,
            "source_tree": tree,
            "public_key_sha256": fingerprint,
            "distinct_actual_image_ids": len(identifiers),
            "scope": _SCOPE,
        }
        if set(result) != set(expected) | {"verified_at_utc"} or any(
            result[key] != value for key, value in expected.items()
        ):
            raise ValueError("The local verification summary differs from the verified bundle.")


def _build(arguments: argparse.Namespace) -> None:
    repository, output = arguments.repository.resolve(), arguments.output.absolute()
    commit, tree = _text(arguments.expected_commit, _GIT), _text(arguments.expected_tree, _GIT)
    if output.resolve().is_relative_to(repository) or output.exists() or output.is_symlink():
        raise ValueError("A new evidence directory outside the checkout is required.")
    _bookend(repository, commit, tree)
    inventory = _json(arguments.inventory)
    identifiers = validate_image_inventory(inventory, commit, tree)
    binding = _build_binding(_json(arguments.build_receipt), inventory, commit, tree)
    binary, cache = arguments.trivy.resolve(), arguments.cache_dir.resolve()
    if _hash(binary) != _text(arguments.expected_trivy_sha256, _SHA256):
        raise ValueError("The selected Trivy bytes differ from the qualified tool hash.")
    before = _trivy_metadata(binary, cache)
    output.mkdir(mode=0o700)
    (output / "sbom").mkdir(mode=0o700)
    source = _source_manifest(repository, commit, tree)
    _write(output / "source-files.json", source)
    _git(
        repository,
        "-c",
        "tar.umask=0022",
        "archive",
        "--format=tar",
        "--output=" + str(output / "source.tar"),
        commit,
    )
    verify_source_archive(output / "source.tar", source)
    _write(output / "images.json", inventory)
    _write(output / "build-binding.json", binding)
    names = [
        "source.tar",
        "source-files.json",
        "images.json",
        "build-binding.json",
        "trivy-metadata.json",
    ]
    for identifier in identifiers:
        _image_id(identifier)
        name = f"sbom/{identifier[7:]}.spdx.json"
        _run(
            "trivy",
            (
                "image",
                "--image-src",
                "docker",
                "--format",
                "spdx-json",
                "--offline-scan",
                "--skip-db-update",
                "--skip-java-db-update",
                "--disable-telemetry",
                "--skip-version-check",
                "--cache-dir",
                str(cache),
                "--output",
                str(output / name),
                identifier,
            ),
            timeout=600,
            binary=binary,
        )
        _image_id(identifier)
        names.append(name)
    after = _trivy_metadata(binary, cache)
    if after != before:
        raise ValueError(
            "The pinned Trivy tool/database changed during offline artifact generation."
        )
    _write(output / "trivy-metadata.json", {"before": before, "after": after})
    _bookend(repository, commit, tree)
    payload = {
        "schema_version": _PAYLOAD_SCHEMA,
        "scope": _SCOPE,
        "source": {"commit": commit, "tree": tree},
        "artifacts": artifact_manifest(output, names),
        "image_inventory": inventory,
        "build": {**binding, "selected_binding_sha256": _hash(arguments.build_receipt)},
        "trivy": {"binary_sha256": before["binary_sha256"], "offline": True},
    }
    envelope = sign_provenance(payload)
    _write(output / "provenance.json", payload)
    _write(output / "signature.json", envelope)
    fingerprint = hashlib.sha256(base64.b64decode(_text(envelope["public_key"]))).hexdigest()
    _verify_bundle(output, commit, tree, fingerprint)
    _write(
        output / "verification.json",
        {
            "verified_at_utc": datetime.now(UTC).isoformat(),
            "source_commit": commit,
            "source_tree": tree,
            "public_key_sha256": fingerprint,
            "distinct_actual_image_ids": len(identifiers),
            "scope": _SCOPE,
        },
    )
    print(
        json.dumps(
            {
                "source_commit": commit,
                "source_tree": tree,
                "public_key_sha256": fingerprint,
                "scope": _SCOPE,
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    build = commands.add_parser("build")
    build.add_argument("--repository", type=Path, default=Path.cwd())
    for option in ("inventory", "build-receipt", "trivy", "cache-dir", "output"):
        build.add_argument("--" + option, type=Path, required=True)
    build.add_argument("--expected-trivy-sha256", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--expected-public-key-sha256", required=True)
    for command in (build, verify):
        command.add_argument("--expected-commit", required=True)
        command.add_argument("--expected-tree", required=True)
    arguments = parser.parse_args()
    if arguments.operation == "build":
        _build(arguments)
    else:
        _verify_bundle(
            arguments.bundle,
            arguments.expected_commit,
            arguments.expected_tree,
            _text(arguments.expected_public_key_sha256, _SHA256),
        )
        print(json.dumps({"verified": True, "scope": _SCOPE}, sort_keys=True))


if __name__ == "__main__":
    main()
