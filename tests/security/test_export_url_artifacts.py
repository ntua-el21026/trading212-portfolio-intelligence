"""Export URL minimization extends to source-controlled and generated artifacts."""

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_BZIP2, ZIP_DEFLATED, ZipFile, is_zipfile

import pytest

from scripts import check_export_url_canary as scanner
from scripts.check_export_url_canary import export_url_canary_components, main
from scripts.check_secret_canary import (
    REPOSITORY_SCAN_EXCLUDED_DIRECTORY_NAMES,
    find_canary_occurrences,
)

pytestmark = pytest.mark.security
ROOT = Path(__file__).parents[2]


def test_export_canary_scanner_detects_each_component_and_rejects_missing_paths(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "artifact.bin"
    for component in export_url_canary_components():
        artifact.write_bytes(b"prefix " + component + b" suffix")
        assert main((str(artifact),)) == 1
    artifact.write_bytes(b"safe selected export metadata")
    assert main((str(artifact),)) == 0
    assert main((str(tmp_path / "missing"),)) == 2
    assert main(()) == 2


@pytest.mark.parametrize("offset", (0, 505, 65_530))
def test_export_canary_scanner_inspects_compressed_playwright_trace(
    tmp_path: Path, offset: int
) -> None:
    artifact = tmp_path / "trace.zip"
    for component in export_url_canary_components():
        with ZipFile(artifact, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("trace.trace", b"x" * offset + component + b" response")
        assert component not in artifact.read_bytes()
        assert main((str(artifact),)) == 1
    with ZipFile(artifact, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("trace.trace", b'{"response":"selected metadata"}')
        archive.writestr("resources/image.png", b"synthetic image bytes")
    assert main((str(artifact),)) == 0


@pytest.mark.parametrize(
    ("bound", "limit", "members"),
    (
        ("MAX_ARCHIVE_BYTES", 10, (b"safe",)),
        ("MAX_ARCHIVE_MEMBERS", 1, (b"safe", b"safe")),
        ("MAX_MEMBER_BYTES", 3, (b"four",)),
        ("MAX_EXPANDED_BYTES", 7, (b"four", b"four")),
    ),
)
def test_export_canary_scanner_fails_closed_at_each_archive_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bound: str,
    limit: int,
    members: tuple[bytes, ...],
) -> None:
    artifact = tmp_path / "trace.zip"
    with ZipFile(artifact, "w", compression=ZIP_DEFLATED) as archive:
        for index, content in enumerate(members):
            archive.writestr(f"resource-{index}", content)
    monkeypatch.setattr(scanner, bound, limit)
    assert main((str(artifact),)) == 2


@pytest.mark.parametrize("prefix_size", (0, 600, 70_000))
def test_export_canary_scanner_rejects_nested_archives_without_extraction(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], prefix_size: int
) -> None:
    nested = BytesIO()
    component = export_url_canary_components()[0]
    with ZipFile(nested, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("trace.trace", component)
    prefixed_archive = b"x" * prefix_size + nested.getvalue()
    assert is_zipfile(BytesIO(prefixed_archive))
    artifact = tmp_path / "trace.zip"
    with ZipFile(artifact, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(component.decode() + "/resource.bin", prefixed_archive)
    assert main((str(artifact),)) == 2
    assert component.decode() not in capsys.readouterr().err
    assert tuple(tmp_path.iterdir()) == (artifact,)


@pytest.mark.parametrize("kind", ("malformed", "encrypted", "unsupported", "corrupt"))
def test_export_canary_scanner_rejects_uninspectable_archives(
    tmp_path: Path, kind: str, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = tmp_path / "trace.zip"
    component = export_url_canary_components()[0]
    if kind == "malformed":
        artifact.write_bytes(b"PK\x03\x04broken")
    else:
        with ZipFile(
            artifact, "w", compression=ZIP_BZIP2 if kind == "unsupported" else ZIP_DEFLATED
        ) as archive:
            archive.writestr(component.decode(), b"safe selected metadata")
        data = bytearray(artifact.read_bytes())
        if kind == "encrypted":
            # Mark the central-directory member encrypted without needing a password fixture.
            central = data.index(b"PK\x01\x02")
            data[central + 8] |= 1
        elif kind == "corrupt":
            # A false CRC must fail inspection even when decompression yields safe bytes.
            central = data.index(b"PK\x01\x02")
            data[central + 16] ^= 1
        artifact.write_bytes(data)
    assert main((str(artifact),)) == 2
    assert component.decode() not in capsys.readouterr().err


def test_export_canary_scanner_rejects_unreadable_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = tmp_path / "trace.zip"
    artifact.write_bytes(b"synthetic inaccessible archive")

    def unreadable(*args: object, **kwargs: object) -> None:
        raise OSError("private archive metadata must not be printed")

    monkeypatch.setattr(Path, "open", unreadable)
    assert main((str(artifact),)) == 2


def test_export_url_canary_absent_from_retained_source_and_available_artifacts() -> None:
    for component in export_url_canary_components():
        assert not find_canary_occurrences(
            (ROOT,),
            component,
            excluded_directory_names=REPOSITORY_SCAN_EXCLUDED_DIRECTORY_NAMES,
        )
    # CI additionally invokes the CLI after builds/browsers with mandatory paths.
    artifacts = tuple(
        path
        for path in (
            ROOT / "packages/api-contracts/openapi",
            ROOT / "packages/api-contracts/src/index.ts",
            ROOT / "tests/fixtures",
            ROOT / "apps/web/.next/standalone",
            ROOT / "apps/web/.next/static",
            ROOT / "apps/web/.next/server",
            ROOT / "apps/web/test-results",
        )
        if path.exists()
    )
    assert main(tuple(str(path) for path in artifacts)) == 0
