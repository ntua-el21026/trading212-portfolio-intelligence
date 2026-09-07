#!/usr/bin/env python3
"""Reject runtime export-URL canaries in retained source and generated artifacts."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator, Sequence
from io import BytesIO
from pathlib import Path
from typing import IO
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, is_zipfile
from zlib import error as ZlibError

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 4096
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
_READ_BYTES = 64 * 1024
# A ZIP end record is 22 bytes plus an optional comment of at most 65,535 bytes.
_ZIP_TAIL_BYTES = 22 + 65_535
_ARCHIVE_SUFFIXES = (
    ".zip",
    ".gz",
    ".gzip",
    ".tgz",
    ".bz2",
    ".tbz2",
    ".xz",
    ".zst",
    ".7z",
    ".rar",
    ".tar",
)
_ARCHIVE_MAGIC = (
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
    b"\x1f\x8b",
    b"BZh",
    b"\xfd7zXZ\x00",
    b"\x28\xb5\x2f\xfd",
    b"7z\xbc\xaf\x27\x1c",
    b"Rar!\x1a\x07",
)


class ArtifactScanError(ValueError):
    """An artifact cannot be safely inspected; never include its contents or member names."""


def _artifact_files(paths: Sequence[Path]) -> Iterator[Path]:
    for path in paths:
        if path.is_file():
            yield path
            continue
        for directory, directory_names, file_names in os.walk(
            path, followlinks=False, onerror=_walk_error
        ):
            directory_names[:] = sorted(
                name for name in directory_names if not (Path(directory) / name).is_symlink()
            )
            for name in sorted(file_names):
                candidate = Path(directory) / name
                if candidate.is_file() and not candidate.is_symlink():
                    yield candidate


def _walk_error(_: OSError) -> None:
    raise ArtifactScanError("Artifact directory could not be inspected.")


def _is_archive(prefix: bytes, name: str) -> bool:
    return (
        name.casefold().endswith(_ARCHIVE_SUFFIXES)
        or prefix.startswith(_ARCHIVE_MAGIC)
        or prefix[257:262] == b"ustar"
    )


def _scan_stream(
    stream: IO[bytes],
    components: Sequence[bytes],
    *,
    limit: int | None = None,
    initial: bytes = b"",
) -> tuple[bool, int, bytes]:
    consumed = len(initial)
    if limit is not None and consumed > limit:
        raise ArtifactScanError("Artifact expansion exceeds its inspection bound.")
    found = any(component in initial for component in components)
    overlap = max(map(len, components)) - 1
    previous = initial[-overlap:]
    tail = initial[-_ZIP_TAIL_BYTES:]
    while chunk := stream.read(_READ_BYTES):
        consumed += len(chunk)
        if limit is not None and consumed > limit:
            raise ArtifactScanError("Artifact expansion exceeds its inspection bound.")
        combined = previous + chunk
        found = found or any(component in combined for component in components)
        previous = combined[-overlap:]
        tail = (tail + chunk)[-_ZIP_TAIL_BYTES:]
    return found, consumed, tail


def _scan_zip(path: Path, components: Sequence[bytes]) -> bool:
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ArtifactScanError("Artifact archive exceeds its inspection bound.")
    found = False
    expanded = 0
    with ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise ArtifactScanError("Artifact archive contains too many members.")
        for member in members:
            if member.flag_bits & 1 or member.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
                raise ArtifactScanError("Artifact archive uses unsupported encoding.")
            if (
                member.file_size > MAX_MEMBER_BYTES
                or expanded + member.file_size > MAX_EXPANDED_BYTES
            ):
                raise ArtifactScanError("Artifact expansion exceeds its inspection bound.")
            with archive.open(member) as stream:
                prefix = stream.read(512)
                if _is_archive(prefix, member.filename):
                    raise ArtifactScanError("Nested artifact archives are unsupported.")
                member_found, consumed, tail = _scan_stream(
                    stream,
                    components,
                    limit=min(MAX_MEMBER_BYTES, MAX_EXPANDED_BYTES - expanded),
                    initial=prefix,
                )
                if consumed != member.file_size:
                    raise ArtifactScanError("Artifact member size does not match its metadata.")
                # ZIP permits arbitrary leading bytes. Its bounded end-record tail
                # detects prefixed nested archives without rereading or extracting.
                if is_zipfile(BytesIO(tail)):
                    raise ArtifactScanError("Nested artifact archives are unsupported.")
                found = found or member_found
                expanded += consumed
    return found


def _scan_file(path: Path, components: Sequence[bytes]) -> bool:
    with path.open("rb") as stream:
        prefix = stream.read(512)
        zip_artifact = path.suffix.casefold() == ".zip" or is_zipfile(path)
        if zip_artifact:
            # Enforce archive size before reading its compressed bytes or member data.
            archive_found = _scan_zip(path, components)
        elif _is_archive(prefix, path.name):
            raise ArtifactScanError("Artifact archive format is unsupported or malformed.")
        else:
            archive_found = False
        stream.seek(0)
        found, _, _ = _scan_stream(stream, components)
    return archive_found or found


def export_url_canary_components() -> tuple[bytes, ...]:
    """Construct synthetic markers without embedding a signed URL in source."""
    return (
        "_".join(("EXPORT", "URL", "CANARY")).encode(),
        ".".join(("signed", "example", "invalid")).encode(),
        ("/" + "report" + ".csv" + "?token=").encode(),
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if not arguments:
        print("usage: python -m scripts.check_export_url_canary PATH [PATH ...]", file=sys.stderr)
        return 2
    paths = tuple(Path(value) for value in arguments)
    if any(not path.exists() or path.is_symlink() for path in paths):
        print("Export URL canary scan requires existing non-symlink paths.", file=sys.stderr)
        return 2
    try:
        findings = {
            path
            for path in _artifact_files(paths)
            if _scan_file(path, export_url_canary_components())
        }
    except (
        ValueError,
        BadZipFile,
        OSError,
        RuntimeError,
        NotImplementedError,
        EOFError,
        ZlibError,
    ):
        print("Export URL canary scan could not safely inspect an artifact.", file=sys.stderr)
        return 2
    if findings:
        print("Export URL canary found in retained/output artifacts:", file=sys.stderr)
        for path in sorted(findings):
            print(f"- {path}", file=sys.stderr)
        return 1
    print(f"Export URL canary absence scan passed for {len(paths)} path(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
