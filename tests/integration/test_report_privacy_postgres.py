"""Actual canonical four-format reports exclude runtime-only private source fields."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from datetime import timedelta
from io import BytesIO
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest
from pypdf import PdfReader
from sqlalchemy import select
from trading212_application.ingestion import (
    Checkpoint,
    IngestionCapability,
    IngestionCoordinator,
    RunMode,
    RunStatus,
    SourcePage,
)
from trading212_domain.report_manifest import encode_report_manifest
from trading212_domain.reports import ReportFormat, ReportSourceKind
from trading212_persistence.models import (
    AuditEventModel,
    PortfolioSnapshotModel,
    SourceRecordModel,
)
from trading212_persistence.report_models import (
    ArtifactDownloadGrantModel,
    ReportInputChunkModel,
    ReportJobModel,
)
from trading212_worker.materializer import PostgresCanonicalMaterializer
from trading212_worker.postgres_store import PostgresIngestionStore
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID, XRAY_AT
from trading212_worker.xray_provider import SyntheticXrayBrokerProvider

from tests.integration.test_report_postgres import ReportCase, finish, generate
from tests.integration.test_report_postgres import report_case as report_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


class PrivateSourceProvider(SyntheticXrayBrokerProvider):
    def __init__(self, canaries: tuple[str, ...]) -> None:
        super().__init__()
        self.canaries = canaries

    async def read_page(
        self,
        *,
        owner_id: str,
        account_id: str,
        capability: IngestionCapability,
        checkpoint: Checkpoint | None,
        correlation_id: str,
    ) -> SourcePage:
        page = await super().read_page(
            owner_id=owner_id,
            account_id=account_id,
            capability=capability,
            checkpoint=checkpoint,
            correlation_id=correlation_id,
        )
        if capability is not IngestionCapability.POSITIONS:
            return page
        # Innocuous provider annotation keys exercise the raw-payload boundary;
        # credential-shaped keys are correctly rejected by SourceRecord itself.
        return replace(
            page,
            records=tuple(
                replace(
                    record,
                    observed_at=XRAY_AT + timedelta(seconds=1),
                    payload={**record.payload, "diagnosticAnnotation": list(self.canaries)},
                )
                for record in page.records
            ),
        )


async def _ingest_private_annotation(case: ReportCase, canaries: tuple[str, ...]) -> None:
    case.base.now[0] = XRAY_AT + timedelta(seconds=1)
    receipt = await IngestionCoordinator(
        provider=PrivateSourceProvider(canaries),
        store=PostgresIngestionStore(
            case.base.sessions,
            provider="synthetic",
            materializer=PostgresCanonicalMaterializer(),
        ),
        clock=lambda: case.base.now[0],
    ).refresh(
        owner_id=case.principal.owner_id,
        account_id=XRAY_ACCOUNT_ID,
        mode=RunMode.FULL,
        idempotency_key="report-private-annotation",
        correlation_id="report-private-annotation",
    )
    assert receipt.status is RunStatus.SUCCEEDED
    with case.base.sessions() as session:
        snapshot = session.scalar(
            select(PortfolioSnapshotModel)
            .where(PortfolioSnapshotModel.broker_account_id == case.account_id)
            .order_by(PortfolioSnapshotModel.valuation_at.desc())
            .limit(1)
        )
        assert snapshot is not None and str(snapshot.id) != case.base.seed["snapshot_id"]
        case.base.seed["snapshot_id"] = str(snapshot.id)
        case.base.seed["source_cutoff_at"] = snapshot.source_cutoff_at.isoformat()


def test_four_actual_formats_and_audits_exclude_private_source_and_grant_canaries(
    report_case: ReportCase, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    # These random synthetic strings are generated only at runtime, never credentials.
    canaries = tuple(
        f"synthetic-private-{kind}-{uuid4().hex}"
        for kind in ("broker", "provider", "host", "path", "signature")
    )
    monkeypatch.setenv("T212PI_REPORT_TEST_BROKER_CREDENTIAL", canaries[0])
    monkeypatch.setenv("T212PI_REPORT_TEST_PROVIDER_KEY", canaries[1])
    monkeypatch.setenv(
        "T212PI_REPORT_TEST_SIGNED_EXPORT_URL",
        f"https://{canaries[2]}.invalid/{canaries[3]}?signature={canaries[4]}",
    )

    async def run() -> None:
        case = report_case
        await _ingest_private_annotation(case, canaries)
        status = await finish(case, await generate(case, formats=tuple(ReportFormat)))
        manifest = await case.service.get_report_manifest(
            case.principal, case.account_id, status.job_id
        )
        source_ids = {
            reference.subject_id
            for reference in manifest.source_references
            if reference.kind is ReportSourceKind.BROKER_SOURCE_RECORD
        }
        assert source_ids
        with case.base.sessions() as session:
            # A retained source actually consumed by this capture contains each
            # private annotation; absence is not proved by an unrelated seed row.
            payloads = session.scalars(
                select(SourceRecordModel.sanitized_payload).where(
                    SourceRecordModel.id.in_(source_ids)
                )
            ).all()
            assert any(
                all(value in json.dumps(payload) for value in canaries) for payload in payloads
            )
            job = session.get(ReportJobModel, status.job_id)
            assert job is not None
            copied = list(
                session.scalars(
                    select(ReportInputChunkModel.payload).where(
                        ReportInputChunkModel.input_id == job.input_id
                    )
                )
            )
        assert all(payload is not None for payload in copied)
        outputs = [
            encode_report_manifest(manifest),
            *(payload for payload in copied if payload is not None),
        ]
        grant_tokens = []
        observed_formats = set()
        for artifact in status.artifacts:
            grant = await case.service.create_report_download_grant(
                case.principal, case.account_id, status.job_id, artifact.artifact_id
            )
            grant_tokens.append(grant.token)
            downloaded = await case.service.download_report_artifact(
                case.principal,
                case.account_id,
                status.job_id,
                artifact.artifact_id,
                grant_token=grant.token,
            )
            content = downloaded.content
            outputs.append(content)
            observed_formats.add(artifact.format)
            if artifact.format is ReportFormat.PDF:
                pdf = PdfReader(BytesIO(content))
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                assert "1000" in text and pdf.metadata is not None
                outputs.extend((text.encode(), repr(pdf.metadata).encode()))
                assert set(pdf.attachments) == {"report-manifest.json"}
                attachments = [payload for values in pdf.attachments.values() for payload in values]
                assert attachments == [encode_report_manifest(manifest)]
                outputs.extend(attachments)
                if pdf.xmp_metadata is not None:
                    outputs.append(pdf.xmp_metadata.stream.get_data())
            elif artifact.format is ReportFormat.XLSX:
                with ZipFile(BytesIO(content)) as archive:
                    assert "xl/workbook.xml" in archive.namelist()
                    outputs.extend(archive.read(name) for name in archive.namelist())
            elif artifact.format is ReportFormat.JSON:
                assert json.loads(content)
            else:
                assert artifact.format is ReportFormat.CSV and b"1000" in content
        assert observed_formats == set(ReportFormat)
        with case.base.sessions() as session:
            outputs.extend(
                json.dumps(row, sort_keys=True).encode()
                for row in session.scalars(
                    select(AuditEventModel.safe_metadata).where(
                        AuditEventModel.owner_id == UUID(case.principal.owner_id)
                    )
                )
            )
            outputs.extend(
                value.encode()
                for value in session.scalars(select(ArtifactDownloadGrantModel.token_digest))
            )
        outputs.append(caplog.text.encode())
        for private in (*canaries, *grant_tokens):
            assert all(private.encode() not in output for output in outputs)

    asyncio.run(run())
