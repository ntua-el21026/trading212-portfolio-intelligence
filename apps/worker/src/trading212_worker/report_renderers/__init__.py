"""Fixed private artifact rendering over authorized canonical report documents."""

from __future__ import annotations

from trading212_application.reports import (
    BoundedArtifactSink,
    ReportDocumentReader,
    ReportRenderError,
    ReportRenderGuard,
    ReportRenderReceipt,
)
from trading212_domain.reports import (
    ReportFailureCode,
    ReportFormat,
    ReportRendererProfile,
    report_mime_type,
)

from .buffer import BoundedArtifactBuffer
from .profile import verify_profile
from .structured import render_csv, render_json

__all__ = ["BoundedArtifactBuffer", "PrivateReportRenderer"]


class PrivateReportRenderer:
    def render(
        self,
        document: ReportDocumentReader,
        *,
        format: ReportFormat,
        profile: ReportRendererProfile,
        sink: BoundedArtifactSink,
        guard: ReportRenderGuard,
    ) -> ReportRenderReceipt:
        guard.check()
        verify_profile(profile, format)
        if (
            document.manifest.document != document.header
            or document.manifest.renderer_profile != profile
        ):
            raise ReportRenderError(ReportFailureCode.INPUT_CHANGED)
        if sink.byte_length:
            raise ReportRenderError(ReportFailureCode.INVALID_INPUT)
        if format is ReportFormat.JSON:
            render_json(document, sink, guard)
        elif format is ReportFormat.CSV:
            render_csv(document, sink, guard)
        elif format is ReportFormat.XLSX:
            from .spreadsheet import render_xlsx

            render_xlsx(document, sink, guard)
        elif format is ReportFormat.PDF:
            from .pdf import render_pdf

            render_pdf(document, sink, guard)
        else:
            raise ReportRenderError(ReportFailureCode.INVALID_INPUT)
        guard.check()
        return ReportRenderReceipt(format=format, mime_type=report_mime_type(format))
