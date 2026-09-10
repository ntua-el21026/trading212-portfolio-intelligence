"""Fixed installed renderer and bundled-font provenance, with no host font lookup."""

from __future__ import annotations

import hashlib
import importlib.metadata
import platform
from pathlib import Path

from trading212_application.reports import ReportRenderError
from trading212_domain.report_profile import FONT_HASHES, FONT_LICENSE_DIGEST, renderer_profile
from trading212_domain.reports import (
    ReportFailureCode,
    ReportFormat,
    ReportRendererProfile,
)

ASSETS = Path(__file__).resolve().parent.parent / "report_assets"


def verify_profile(profile: ReportRendererProfile, format: ReportFormat) -> None:
    formats = tuple(item.format for item in profile.renderer_versions)
    if format not in formats or profile != renderer_profile(formats):
        raise ReportRenderError(ReportFailureCode.INVALID_INPUT)
    if platform.python_version() != "3.13.15":
        raise ReportRenderError(ReportFailureCode.RENDER_FAILED)
    if format in {ReportFormat.PDF, ReportFormat.XLSX}:
        expected = next(item for item in profile.renderer_versions if item.format is format)
        if importlib.metadata.version(expected.name) != expected.version:
            raise ReportRenderError(ReportFailureCode.RENDER_FAILED)
    if format is ReportFormat.PDF:
        verify_fonts()


def verify_fonts() -> None:
    for name, digest in (*FONT_HASHES, ("LICENSE", FONT_LICENSE_DIGEST)):
        path = ASSETS / name
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise ReportRenderError(ReportFailureCode.RENDER_FAILED)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ReportRenderError(ReportFailureCode.RENDER_FAILED)
