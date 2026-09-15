"""Trusted parent profile selects a closed decoder without inspecting private JSON."""

import sys
from unittest.mock import Mock

import pytest
from trading212_application.reports import ReportRenderError
from trading212_domain.errors import DomainError
from trading212_domain.report_manifest import build_report_manifest, encode_report_manifest
from trading212_domain.report_v3 import ReportManifestContract
from trading212_domain.reports import ReportFailureCode
from trading212_worker import report_render_process as process

from tests.unit.domain.report_factories import document
from tests.unit.domain.report_v3_factories import capture_v3
from tests.unit.domain.test_premium_report_versions import _capture

pytestmark = pytest.mark.unit


def manifests() -> tuple[ReportManifestContract, ...]:
    return (
        document().manifest,
        build_report_manifest(_capture()),
        build_report_manifest(capture_v3()),
    )


@pytest.mark.parametrize("profile", ["1", "2", "3"])
def test_explicit_profile_decodes_exact_canonical_manifest_without_rewriting(profile: str) -> None:
    manifest = manifests()[int(profile) - 1]
    payload = encode_report_manifest(manifest)
    parsed = process._decode_manifest(payload, profile)
    assert parsed == manifest
    assert encode_report_manifest(parsed) == payload


@pytest.mark.parametrize("profile", ["", "0", "4", "03", "report_sections_v3", "private-canary"])
def test_unknown_profile_fails_before_either_private_decoder(
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
) -> None:
    old, new = Mock(), Mock()
    monkeypatch.setattr(process, "decode_report_manifest", old)
    monkeypatch.setattr(process, "decode_report_manifest_v3", new)
    with pytest.raises(ReportRenderError) as caught:
        process._decode_manifest(b"private-payload-canary", profile)
    assert caught.value.code is ReportFailureCode.INPUT_CHANGED
    assert "untrusted-payload-canary-v3" not in str(caught.value)
    old.assert_not_called()
    new.assert_not_called()


@pytest.mark.parametrize(
    "selected,actual", [(a, b) for a in (1, 2, 3) for b in (1, 2, 3) if a != b]
)
def test_valid_but_mismatched_profile_cannot_decode_another_document_family(
    selected: int,
    actual: int,
) -> None:
    payload = encode_report_manifest(manifests()[actual - 1])
    with pytest.raises((ReportRenderError, DomainError)):
        process._decode_manifest(payload, str(selected))


def test_v3_decoder_selection_does_not_fall_back_to_legacy_on_corruption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = Mock()
    monkeypatch.setattr(process, "decode_report_manifest", old)
    with pytest.raises(DomainError):
        process._decode_manifest(b'{"document":{"document_schema_version":"3.0.0"}}', "3")
    old.assert_not_called()


def test_entrypoint_rejects_unknown_parent_profile_before_pipe_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = Mock()
    monkeypatch.setattr(process, "Connection", connection)
    monkeypatch.setattr(sys, "argv", ["report", "19", "json", "/unused", "1", "4"])
    with pytest.raises(SystemExit) as caught:
        process._main()
    assert caught.value.code == 2
    connection.assert_not_called()
