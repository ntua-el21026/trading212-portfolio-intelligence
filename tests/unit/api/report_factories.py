"""Synthetic metadata fixtures for report transport tests, without financial claims."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from trading212_application import reports as app
from trading212_domain import reports as domain
from trading212_domain.enums import QualityState
from trading212_domain.sources import SourceAvailability
from trading212_domain.values import CurrencyCode

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
ACCOUNT = str(UUID(int=1001))
SNAPSHOT = str(UUID(int=1002))
JOB = str(UUID(int=1003))
ARTIFACT = str(UUID(int=1004))
BODY: dict[str, Any] = {
    "account_id": ACCOUNT,
    "snapshot_id": SNAPSHOT,
    "start_date": "2026-09-01",
    "end_date": "2026-09-07",
    "source_cutoff_at": "2026-09-07T12:00:00Z",
    "reporting_currency": "EUR",
    "report_type": "portfolio_summary",
    "sections": ["overview", "allocation", "quality"],
    "formats": ["json"],
}


def context() -> app.ReportPinnedContext:
    return app.ReportPinnedContext(
        snapshot_id=UUID(SNAPSHOT),
        valuation_at=NOW,
        source_cutoff_at=NOW,
        reporting_currency=CurrencyCode("EUR"),
        input_digest="a" * 64,
        document_digest="b" * 64,
        pins=(
            domain.ReportBinding(
                family=domain.ReportFamily.SNAPSHOT,
                role=domain.ReportInputRole.SNAPSHOT,
                subject_id=UUID(SNAPSHOT),
                content_digest="c" * 64,
            ),
        ),
        quality=app.ReportQualitySummary(
            state=QualityState.FRESH,
            availability=SourceAvailability.AVAILABLE,
            evaluated_at=NOW,
        ),
    )


def job() -> app.ReportJobStatus:
    return app.ReportJobStatus(
        account_id=UUID(ACCOUNT),
        context=context(),
        job_id=UUID(JOB),
        state=domain.ReportJobState.QUEUED,
        requested_at=NOW,
        expires_at=NOW + timedelta(days=7),
        report_type=domain.ReportType.PORTFOLIO_SUMMARY,
        formats=(domain.ReportFormat.JSON,),
    )


def artifact(content: bytes = b'{"source":"synthetic"}') -> app.ReportArtifactDownload:
    return app.ReportArtifactDownload(
        metadata=app.ReportArtifactMetadata(
            artifact_id=UUID(ARTIFACT),
            format=domain.ReportFormat.JSON,
            mime_type=domain.ReportMimeType.JSON,
            byte_length=len(content),
            content_digest=hashlib.sha256(content).hexdigest(),
            expires_at=NOW + timedelta(days=7),
        ),
        filename="synthetic-report.json",
        content=content,
    )
