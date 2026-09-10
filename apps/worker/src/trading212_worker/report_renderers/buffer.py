"""Private worker-owned byte buffers that reject overflow before every write."""

from __future__ import annotations

import hashlib
from io import BytesIO

from trading212_application.reports import (
    RenderedArtifact,
    ReportRenderError,
    ReportRenderGuard,
    ReportRenderReceipt,
)
from trading212_domain.reports import (
    MAX_REPORT_ARTIFACT_BYTES,
    ReportFailureCode,
    report_mime_type,
)


class BoundedArtifactBuffer:
    def __init__(self, *, guard: ReportRenderGuard, limit: int = MAX_REPORT_ARTIFACT_BYTES) -> None:
        if type(limit) is not int or not 1 <= limit <= MAX_REPORT_ARTIFACT_BYTES:
            raise ValueError("Artifact buffer bound is invalid.")
        self._content = BytesIO()
        self._guard = guard
        self._limit = limit
        self._length = 0
        self._finished = False

    @property
    def byte_length(self) -> int:
        return self._length

    def write(self, chunk: bytes) -> int:
        self._guard.check()
        if self._finished or self._content.closed:
            raise ReportRenderError(ReportFailureCode.RENDER_FAILED)
        if self._content.tell() + len(chunk) > self._limit:
            raise ReportRenderError(ReportFailureCode.LIMIT_EXCEEDED)
        written = self._content.write(chunk)
        self._length = max(self._length, self._content.tell())
        return written

    def tell(self) -> int:
        return self._content.tell()

    def seek(self, offset: int, whence: int = 0) -> int:
        if self._finished or self._content.closed:
            raise ReportRenderError(ReportFailureCode.RENDER_FAILED)
        old = self._content.tell()
        result = self._content.seek(offset, whence)
        if result > self._limit:
            self._content.seek(old)
            raise ReportRenderError(ReportFailureCode.LIMIT_EXCEEDED)
        return result

    def flush(self) -> None:
        self._guard.check()

    def finish(self, receipt: ReportRenderReceipt) -> RenderedArtifact:
        self._guard.check()
        if self._finished or self._content.closed or not self._length:
            raise ReportRenderError(ReportFailureCode.RENDER_FAILED)
        if receipt.mime_type is not report_mime_type(receipt.format):
            raise ReportRenderError(ReportFailureCode.RENDER_FAILED)
        content = self._content.getvalue()
        result = RenderedArtifact(
            format=receipt.format,
            mime_type=receipt.mime_type,
            content=content,
            byte_length=len(content),
            content_digest=hashlib.sha256(content).hexdigest(),
        )
        self._finished = True
        self._content.close()
        return result

    def close(self) -> None:
        self._content.close()

    def __enter__(self) -> BoundedArtifactBuffer:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
