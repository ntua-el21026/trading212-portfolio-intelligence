"""Ordinary price/FX source expiry removes genuine canonical report copies."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import reports as app
from trading212_domain import reports as r
from trading212_domain.report_manifest import decode_report_chunk
from trading212_domain.report_schema import table_schema
from trading212_persistence.report_models import (
    ArtifactDownloadGrantModel,
    ReportArtifactModel,
    ReportInputChunkModel,
    ReportInputDependencyModel,
    ReportInputSnapshotModel,
    ReportJobModel,
    ReportRetentionWorkModel,
)
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.source_retention_service import expire_source_payloads

from tests.integration.report_history_cases import history_report_case
from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_historical_seed import seeded_history as seeded_history

pytestmark = pytest.mark.integration


def test_historical_price_fx_expiry_removes_report_bytes_with_shared_budget(
    seeded_history: tuple[sessionmaker[Session], dict[str, str]],
) -> None:
    async def run() -> None:
        sessions, identifiers = seeded_history
        case = history_report_case(sessions, identifiers)
        status = await case.complete(
            case.selection(
                r.ReportType.PERFORMANCE_BENCHMARK,
                (
                    r.ReportSection.OVERVIEW,
                    r.ReportSection.PERFORMANCE,
                    r.ReportSection.BENCHMARK,
                    r.ReportSection.QUALITY,
                ),
            )
        )
        manifest = await case.service.get_report_manifest(
            case.principal, case.account_id, status.job_id
        )
        assert manifest.document.valuation_at.year == 2026
        assert manifest.document.selection.start_date == date(2025, 1, 1)
        assert manifest.document.selection.end_date == date(2025, 12, 31)
        assert any(note.code == "snapshot_outside_period" for note in manifest.notes)
        with sessions() as session:
            saved_job = session.get(ReportJobModel, status.job_id)
            assert saved_job is not None
            payloads = session.scalars(
                select(ReportInputChunkModel.payload).where(
                    ReportInputChunkModel.input_id == saved_job.input_id,
                    ReportInputChunkModel.table_key.in_(
                        (
                            r.ReportTableKey.PERFORMANCE_SUMMARY.value,
                            r.ReportTableKey.PERFORMANCE_POINTS.value,
                            r.ReportTableKey.HISTORICAL_OPTIONS.value,
                            r.ReportTableKey.HISTORICAL_OBSERVATION_USES.value,
                        )
                    ),
                )
            ).all()
        retained: dict[r.ReportTableKey, list[dict[str, r.ReportCell]]] = {
            r.ReportTableKey.PERFORMANCE_SUMMARY: [],
            r.ReportTableKey.PERFORMANCE_POINTS: [],
            r.ReportTableKey.HISTORICAL_OPTIONS: [],
            r.ReportTableKey.HISTORICAL_OBSERVATION_USES: [],
        }
        for payload in payloads:
            assert payload is not None
            chunk = decode_report_chunk(payload)
            retained[chunk.table].extend(
                dict(
                    zip(
                        (column.key for column in table_schema(chunk.table).columns),
                        row.cells,
                        strict=True,
                    )
                )
                for row in chunk.rows
            )
        performance = retained[r.ReportTableKey.PERFORMANCE_SUMMARY][0]
        for key, amount in (
            ("beginning_value", "1872.4697"),
            ("ending_value", "2191.280575"),
            ("investment_gain", "218.810875"),
        ):
            assert performance[key].value == Decimal(amount)
        points = retained[r.ReportTableKey.PERFORMANCE_POINTS]
        assert len(points) == 12
        assert all(
            row["frequency"].value == "monthly"
            for row in retained[r.ReportTableKey.HISTORICAL_OPTIONS]
        )
        observations = retained[r.ReportTableKey.HISTORICAL_OBSERVATION_USES]
        assert {"price", "fx"} <= {row["source_kind"].value for row in observations}
        assert {point["valuation_at"].value for point in points} <= {
            row["use_at"].value for row in observations
        }
        dates = []
        for point in points:
            value = point["date"].value
            assert isinstance(value, date)
            dates.append(value)
        assert min(dates) == date(2025, 1, 31)
        assert max(dates) == date(2025, 12, 31)
        grant = await case.service.create_report_download_grant(
            case.principal, case.account_id, status.job_id, status.artifacts[0].artifact_id
        )
        with sessions() as session:
            job = session.get(ReportJobModel, status.job_id)
            assert job is not None
            input_id = job.input_id
            dependencies = session.scalars(
                select(ReportInputDependencyModel).where(
                    ReportInputDependencyModel.input_id == input_id
                )
            ).all()
            assert {"price", "fx"} <= {row.kind for row in dependencies}
            physical_ids = {str(row.source_id) for row in dependencies}
            assert {str(row["snapshot_id"].value) for row in observations} <= physical_ids
            expiries = [row.expires_at for row in dependencies if row.expires_at is not None]
            assert len(expiries) == len(dependencies)
            at = max(expiries) + timedelta(seconds=1)
        for _ in range(256):
            with sessions() as session, session.begin():
                budget = SourcePurgeBudget(
                    rows_inspected=64, rows_removed=64, bytes_inspected=8192, bytes_removed=8192
                )
                expire_source_payloads(session, at=at, limit=1, budget=budget)
                pending = session.scalar(
                    select(ReportRetentionWorkModel.id).where(
                        ReportRetentionWorkModel.input_id == input_id,
                        ReportRetentionWorkModel.completed_at.is_(None),
                    )
                )
            if pending is not None:
                break
        assert pending is not None
        with pytest.raises(app.ReportServiceError):
            await case.service.download_report_artifact(
                case.principal,
                case.account_id,
                status.job_id,
                status.artifacts[0].artifact_id,
                grant_token=grant.token,
            )
        for _ in range(256):
            with sessions() as session, session.begin():
                budget = SourcePurgeBudget(rows_inspected=256, rows_removed=256)
                expire_source_payloads(session, at=at, limit=1, budget=budget)
                assert 0 <= budget.rows_inspected <= 256 and 0 <= budget.rows_removed <= 256
                assert 0 <= budget.artifacts <= 100
                purged = session.scalar(
                    select(ReportInputSnapshotModel.purged_at).where(
                        ReportInputSnapshotModel.id == input_id
                    )
                )
            if purged is not None:
                break
        assert purged is not None
        with sessions() as session:
            assert session.scalar(select(func.count()).select_from(ArtifactDownloadGrantModel)) == 0
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ReportArtifactModel)
                    .where(ReportArtifactModel.contents.is_not(None))
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ReportInputChunkModel)
                    .where(ReportInputChunkModel.payload.is_not(None))
                )
                == 0
            )
            assert (
                session.scalar(
                    select(ReportRetentionWorkModel.completed_at).where(
                        ReportRetentionWorkModel.input_id == input_id
                    )
                )
                is not None
            )

    asyncio.run(run())
