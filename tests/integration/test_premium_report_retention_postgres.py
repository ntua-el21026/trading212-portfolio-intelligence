"""Normalized premium copy guards and bounded purge ordering without report decoding."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from inspect import unwrap
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from trading212_application import risk as app
from trading212_persistence.premium_models import (
    PremiumRetentionModel,
    PremiumRunLicenseModel,
    PremiumRunModel,
)
from trading212_persistence.report_models import (
    ReportInputChunkModel,
    ReportInputPinModel,
    ReportInputPremiumDependencyModel,
    ReportInputSnapshotModel,
    ReportRetentionWorkModel,
)
from trading212_persistence.report_retention import expire_report_payloads
from trading212_persistence.risk_models import RiskResultModel, RiskSeriesModel
from trading212_persistence.source_models import ProviderLicenseVersionModel
from trading212_persistence.source_retention import SourcePurgeBudget

from tests.integration.test_historical_postgres import historical_database as _historical_database
from tests.integration.test_historical_seed import NOW
from tests.integration.test_historical_seed import seeded_history as _seeded_history
from tests.integration.test_risk_retention_postgres import drain_cleanup, pass_cleanup, published
from tests.integration.test_risk_runs_postgres import RunCase
from tests.integration.test_risk_runs_postgres import run_case as run_case
from tests.integration.test_risk_source_authorization import restrict

pytestmark = pytest.mark.integration
historical_database = pytest.fixture(scope="function")(unwrap(_historical_database))
seeded_history = pytest.fixture(scope="function")(unwrap(_seeded_history))


def capture(
    session: Session,
    case: RunCase,
    run: app.RiskRunView,
    *,
    version: int = 2,
    dependency: bool = True,
    at: datetime = NOW,
) -> UUID:
    """Build a minimal opaque copy to isolate SQL lineage from report rendering.

    Its payload is intentionally never decoded. Canonical report generation and
    renderer tests independently exercise the complete typed document contract.
    """
    owner = UUID(case.principal.owner_id)
    root = session.get_one(PremiumRunModel, run.id)
    result = session.scalar(select(RiskResultModel).where(RiskResultModel.run_id == run.id))
    assert result is not None
    payload = b"synthetic retained risk copy"
    digest = sha256(payload).hexdigest()
    identifier = uuid4()
    deadline = root.expires_at - timedelta(seconds=1)
    assert root.created_at <= at < deadline <= root.expires_at
    row = ReportInputSnapshotModel(
        id=identifier,
        owner_id=owner,
        account_id=case.command.account_id,
        kind="report",
        contract_version=version,
        snapshot_id=case.command.portfolio_snapshot_id,
        start_date=NOW.date(),
        end_date=NOW.date(),
        valuation_at=NOW,
        source_cutoff_at=NOW,
        reporting_currency="EUR",
        input_digest=digest,
        document_digest=digest,
        canonical_byte_length=2 * len(payload),
        chunk_count=1,
        pin_count=1,
        source_count=0,
        canonical_manifest=payload,
        canonical_context=payload,
        sealed_at=None,
        expires_at=deadline,
        purged_at=None,
        created_at=at,
    )
    session.add(row)
    session.flush()
    session.add(
        ReportInputPinModel(
            id=uuid4(),
            owner_id=owner,
            input_id=identifier,
            ordinal=0,
            kind="risk",
            subject_id=run.id,
            parent_id=None,
            content_digest=result.content_digest,
            created_at=at,
        )
    )
    session.add(
        ReportInputChunkModel(
            id=uuid4(),
            owner_id=owner,
            input_id=identifier,
            table_key="risk_metrics_v1",
            ordinal=0,
            row_count=1,
            byte_length=len(payload),
            content_digest=digest,
            payload=payload,
            purged_at=None,
            created_at=at,
        )
    )
    if dependency:
        session.add(
            ReportInputPremiumDependencyModel(
                id=uuid4(),
                owner_id=owner,
                account_id=case.command.account_id,
                input_id=identifier,
                run_id=run.id,
                kind="risk",
                input_digest=root.input_digest,
                result_digest=result.content_digest,
                expires_at=deadline,
                created_at=at,
            )
        )
    session.flush()
    row.sealed_at = at
    session.flush()
    return identifier


def report_policy(
    case: RunCase, run: app.RiskRunView, permission: str, *, at: datetime = NOW
) -> None:
    with case.sessions() as session, session.begin():
        lineage = session.scalar(
            select(PremiumRunLicenseModel).where(PremiumRunLicenseModel.run_id == run.id).limit(1)
        )
        assert lineage is not None
        pinned = session.get_one(ProviderLicenseVersionModel, lineage.license_version_id)
        version = session.scalar(
            select(func.max(ProviderLicenseVersionModel.version_number)).where(
                ProviderLicenseVersionModel.provider_id == lineage.provider_id
            )
        )
        assert version is not None
        session.add(
            ProviderLicenseVersionModel(
                id=uuid4(),
                owner_id=pinned.owner_id,
                provider_id=pinned.provider_id,
                version_number=version + 1,
                version=f"report-only-{version + 1}",
                effective_at=at,
                store_permission="allowed",
                display_permission="allowed",
                report_permission=permission,
                export_permission="allowed",
                retention_days=30,
                attribution="Synthetic report policy",
                evidence_key="report-policy-fixture",
                created_at=at,
            )
        )


async def test_versioned_lineage_is_complete_and_immutable(run_case: RunCase) -> None:
    case = run_case
    run = await published(case, clock=lambda: datetime.now(UTC))
    for version, dependency in ((1, True), (2, False)):
        with case.sessions() as session, pytest.raises(DBAPIError), session.begin():
            capture(
                session, case, run, version=version, dependency=dependency, at=datetime.now(UTC)
            )
            session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    with case.sessions() as session, session.begin():
        legacy = capture(session, case, run, version=1, dependency=False, at=datetime.now(UTC))
        premium = capture(session, case, run, at=datetime.now(UTC))
    at = datetime.now(UTC)
    with case.sessions() as session, session.begin():
        assert (
            session.scalar(
                func.report_premium_restricted(UUID(case.principal.owner_id), legacy, at)
            )
            is False
        )
        assert (
            session.scalar(
                func.report_premium_restricted(UUID(case.principal.owner_id), premium, at)
            )
            is False
        )
        for statement in (
            update(ReportInputSnapshotModel)
            .where(ReportInputSnapshotModel.id == premium)
            .values(contract_version=1),
            update(ReportInputPremiumDependencyModel)
            .where(ReportInputPremiumDependencyModel.input_id == premium)
            .values(result_digest="0" * 64),
            delete(ReportInputPremiumDependencyModel).where(
                ReportInputPremiumDependencyModel.input_id == premium
            ),
        ):
            with pytest.raises(DBAPIError), session.begin_nested():
                session.execute(statement)


async def test_report_only_revocation_drains_copy_and_keeps_risk_result(run_case: RunCase) -> None:
    case = run_case
    run = await published(case, clock=lambda: datetime.now(UTC))
    with case.sessions() as session, session.begin():
        identifier = capture(session, case, run, at=datetime.now(UTC))
        original = session.scalar(
            select(RiskResultModel.canonical_result).where(RiskResultModel.run_id == run.id)
        )
        assert original
        assert (
            session.scalar(
                func.report_premium_restricted(
                    UUID(case.principal.owner_id), identifier, datetime.now(UTC)
                )
            )
            is False
        )
    report_policy(case, run, "denied", at=datetime.now(UTC))
    at = datetime.now(UTC)
    assert at < run.expires_at - timedelta(seconds=1)
    with case.sessions() as session, session.begin():
        assert (
            session.scalar(
                func.report_premium_restricted(UUID(case.principal.owner_id), identifier, at)
            )
            is True
        )
        assert (
            expire_report_payloads(session, at=at, budget=SourcePurgeBudget(bytes_removed=0)) == 0
        )
        work = session.scalar(
            select(ReportRetentionWorkModel).where(ReportRetentionWorkModel.input_id == identifier)
        )
        assert work is not None and work.reason == "source" and work.completed_at is None
        assert work.legacy_source_kind == "premium_license"
        result = session.scalar(select(RiskResultModel).where(RiskResultModel.run_id == run.id))
        assert result is not None and result.canonical_result == original
        assert (
            session.scalar(
                select(PremiumRetentionModel.id).where(PremiumRetentionModel.run_id == run.id)
            )
            is None
        )
    # A pending purge is permanent and resumes even if REPORT rights are restored.
    report_policy(case, run, "allowed", at=datetime.now(UTC))
    at = datetime.now(UTC)
    with case.sessions() as session, session.begin():
        assert expire_report_payloads(session, at=at) == 1
        assert session.get_one(ReportInputSnapshotModel, identifier).purged_at == at
        assert (
            session.scalar(func.report_capture_pending(UUID(case.principal.owner_id), identifier))
            is False
        )
        result = session.scalar(select(RiskResultModel).where(RiskResultModel.run_id == run.id))
        assert result is not None and result.canonical_result == original
    assert pass_cleanup(case, at=at)
    assert (await case.service.get_run(case.principal, run.id)).result is not None


async def test_risk_purge_waits_for_report_budget_and_sql_rejects_bypass(run_case: RunCase) -> None:
    case = run_case
    run = await published(case, clock=lambda: datetime.now(UTC))
    with case.sessions() as session, session.begin():
        identifier = capture(session, case, run, at=datetime.now(UTC))
    restrict(case, store="denied", days=30)
    at = datetime.now(UTC)
    assert not pass_cleanup(case, at=at, budget=SourcePurgeBudget(bytes_removed=0))
    with case.sessions() as session, session.begin():
        marker = session.scalar(
            select(PremiumRetentionModel).where(PremiumRetentionModel.run_id == run.id)
        )
        result = session.scalar(select(RiskResultModel).where(RiskResultModel.run_id == run.id))
        assert marker is not None and marker.completed_at is None
        assert result is not None and result.canonical_result
        assert (
            session.scalar(
                select(RiskSeriesModel.id).where(RiskSeriesModel.result_id == result.id).limit(1)
            )
            is not None
        )
        for statement in (
            update(PremiumRetentionModel)
            .where(PremiumRetentionModel.id == marker.id)
            .values(completed_at=at),
            update(RiskResultModel)
            .where(RiskResultModel.id == result.id)
            .values(canonical_result=b""),
            delete(RiskSeriesModel).where(RiskSeriesModel.result_id == result.id),
        ):
            with pytest.raises(DBAPIError), session.begin_nested():
                session.execute(statement)
        assert (
            session.scalar(func.report_capture_pending(UUID(case.principal.owner_id), identifier))
            is True
        )
    drain_cleanup(case, at=at)
    with case.sessions() as session:
        assert (
            session.scalar(func.report_capture_pending(UUID(case.principal.owner_id), identifier))
            is False
        )
        marker = session.scalar(
            select(PremiumRetentionModel).where(PremiumRetentionModel.run_id == run.id)
        )
        result = session.scalar(select(RiskResultModel).where(RiskResultModel.run_id == run.id))
        assert marker is not None and marker.completed_at is not None
        assert result is not None and result.canonical_result == b""
