"""Fixed canonical report renderer metadata shared without importing runtime libraries."""

from __future__ import annotations

from .reports import (
    ReportFontReference,
    ReportFormat,
    ReportRendererProfile,
    ReportRendererVersion,
)

FONT_LICENSE_DIGEST = "7a083b136e64d064794c3419751e5c7dd10d2f64c108fe5ba161eae5e5958a93"
FONT_HASHES = (
    ("DejaVuSans.ttf", "7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954"),
    ("DejaVuSans-Bold.ttf", "e6476c1b80502924294eed40894c5b18e06c181444ca953e5334262df9c27724"),
)
_VERSIONS = {
    ReportFormat.PDF: ("reportlab", "5.0.1"),
    ReportFormat.CSV: ("python.csv", "3.13.15"),
    ReportFormat.JSON: ("report_document_json", "1.0.0"),
    ReportFormat.XLSX: ("xlsxwriter", "3.2.9"),
}


def renderer_profile(formats: tuple[ReportFormat, ...]) -> ReportRendererProfile:
    return ReportRendererProfile(
        renderer_versions=tuple(
            ReportRendererVersion(
                format=format, name=_VERSIONS[format][0], version=_VERSIONS[format][1]
            )
            for format in formats
        ),
        fonts=tuple(
            ReportFontReference(
                name=name,
                version="2.37",
                content_digest=digest,
                license_digest=FONT_LICENSE_DIGEST,
            )
            for name, digest in FONT_HASHES
        )
        if ReportFormat.PDF in formats
        else (),
    )
