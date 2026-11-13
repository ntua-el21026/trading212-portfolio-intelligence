"""Actual scenario parents, third-profile SQL lineage and bounded physical copy purge."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from runpy import run_path
from typing import cast
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from trading212_persistence.premium_models import PremiumRunLicenseModel, PremiumRunModel
from trading212_persistence.report_models import (
    ReportInputChunkModel,
    ReportInputDependencyModel,
    ReportInputLicenseModel,
    ReportInputPinModel,
    ReportInputPremiumDependencyModel,
    ReportInputSnapshotModel,
)
from trading212_persistence.report_retention import expire_report_payloads
from trading212_persistence.report_sources import _PHYSICAL, PhysicalSource
from trading212_persistence.scenario_input_store import ScenarioInputStore
from trading212_persistence.scenario_models import (
    ScenarioComponentModel,
    ScenarioResultModel,
    ScenarioRunModel,
    ScenarioVersionModel,
)
from trading212_persistence.source_models import ProviderLicenseVersionModel
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.source_store import digest, license_view
from trading212_persistence.xray_run_models import XrayInputDependencyModel, XrayInputSnapshotModel

from tests.integration.report_runtime_sources import fresh_report_xray
from tests.integration.test_scenario_retention_postgres import cleanup, published, restrict
from tests.integration.test_scenario_runs_postgres import ScenarioCase, cancel_scenario
from tests.integration.test_scenario_runs_postgres import scenario_case as _historical_scenario_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration
historical_scenario_case = _historical_scenario_case


@pytest.fixture
async def scenario_case(historical_scenario_case: ScenarioCase) -> ScenarioCase:
    """New report copies use a current admitted parent and newly available sources."""
    case = historical_scenario_case
    await cancel_scenario(case, case.run.id)
    fresh = await fresh_report_xray(case.xray)
    case.command = replace(
        case.command,
        xray_run_id=UUID(fresh.context.run_id),
        source_cutoff_at=fresh.context.source_cutoff_at,
        idempotency_key=str(uuid4()),
    )
    case.run = await case.service.create_run(case.principal, case.command)
    return case


def capture(
    session: Session,
    case: ScenarioCase,
    *,
    profile: int = 3,
    wrong: str | None = None,
    copy_deadline: datetime | None = None,
) -> UUID:
    """Minimal opaque report bytes isolate normalized guard behavior from renderers.

    Every saved parent and license is real; only the report body is a fixed synthetic
    byte string that these tests never decode. Full capture has separate tests.
    """
    owner = UUID(case.principal.owner_id)
    root = session.get_one(PremiumRunModel, case.run.id)
    run = session.get_one(ScenarioRunModel, root.id)
    result = session.scalar(
        select(ScenarioResultModel).where(ScenarioResultModel.run_id == root.id)
    )
    assert result is not None
    version = session.get_one(ScenarioVersionModel, run.definition_version_id)
    valuation = session.scalar(
        select(XrayInputSnapshotModel.valuation_at).where(
            XrayInputSnapshotModel.id == run.xray_input_id
        )
    )
    assert valuation is not None
    payload = b"synthetic complete scenario report copy"
    fingerprint = sha256(payload).hexdigest()
    identifier = uuid4()
    deadline = min(root.expires_at - timedelta(seconds=1), copy_deadline or root.expires_at)
    pins = (
        ("snapshot:snapshot", run.portfolio_snapshot_id, run.portfolio_snapshot_digest, None),
        ("scenario:input", root.id, root.input_digest, None),
        ("scenario:result", result.id, result.content_digest, root.id),
        ("scenario:policy", version.id, version.content_digest, version.definition_id),
        ("xray:input", run.xray_input_id, run.xray_input_digest, None),
        ("xray:result", run.xray_run_id, run.xray_result_digest, None),
    )
    row = ReportInputSnapshotModel(
        id=identifier,
        owner_id=owner,
        account_id=run.account_id,
        kind="report",
        contract_version=profile,
        snapshot_id=run.portfolio_snapshot_id,
        start_date=valuation.date(),
        end_date=valuation.date(),
        valuation_at=valuation,
        source_cutoff_at=run.source_cutoff_at,
        reporting_currency=run.reporting_currency,
        input_digest=fingerprint,
        document_digest=fingerprint,
        canonical_byte_length=2 * len(payload),
        chunk_count=1,
        pin_count=len(pins),
        source_count=0,
        canonical_manifest=payload,
        canonical_context=payload,
        sealed_at=None,
        expires_at=deadline,
        purged_at=None,
        created_at=case.now,
    )
    session.add(row)
    session.flush()
    for ordinal, (kind, subject, content, parent) in enumerate(pins):
        session.add(
            ReportInputPinModel(
                id=uuid4(),
                owner_id=owner,
                input_id=identifier,
                ordinal=ordinal,
                kind=kind,
                subject_id=subject,
                parent_id=parent,
                content_digest=content,
                created_at=case.now,
            )
        )
    session.add(
        ReportInputChunkModel(
            id=uuid4(),
            owner_id=owner,
            input_id=identifier,
            table_key="scenario_summary_v1",
            ordinal=0,
            row_count=1,
            byte_length=len(payload),
            content_digest=fingerprint,
            payload=payload,
            purged_at=None,
            created_at=case.now,
        )
    )
    for lineage in session.scalars(
        select(PremiumRunLicenseModel).where(
            PremiumRunLicenseModel.owner_id == owner, PremiumRunLicenseModel.run_id == root.id
        )
    ):
        pinned = session.get_one(ProviderLicenseVersionModel, lineage.license_version_id)
        session.add(
            ReportInputLicenseModel(
                id=uuid4(),
                owner_id=owner,
                input_id=identifier,
                license_version_id=pinned.id,
                provider_id=pinned.provider_id,
                content_digest=digest(license_view(pinned)),
                created_at=case.now,
            )
        )
    selected = tuple(
        session.scalars(
            select(XrayInputDependencyModel).where(
                XrayInputDependencyModel.owner_id == owner,
                XrayInputDependencyModel.input_id == run.xray_input_id,
            )
        )
    )
    copied: set[UUID] = set()
    for dependency in selected:
        for kind, (model, column) in _PHYSICAL.items():
            source_id = getattr(dependency, column, None)
            if source_id is None or source_id in copied:
                continue
            original = session.scalar(
                select(model).where(model.owner_id == owner, model.id == source_id)
            )
            assert original is not None
            source = cast(PhysicalSource, original)
            copied.add(source_id)
            session.add(
                ReportInputDependencyModel(
                    id=uuid4(),
                    owner_id=owner,
                    input_id=identifier,
                    source_key=f"fixture:{source_id}",
                    kind=kind,
                    source_id=source_id,
                    parent_id=None,
                    content_digest=source.content_digest,
                    provider_id=source.provider_id,
                    license_version_id=source.license_version_id,
                    expires_at=source.expires_at,
                    created_at=case.now,
                    **{column: source_id},
                )
            )
    binding = ReportInputPremiumDependencyModel(
        id=uuid4(),
        owner_id=owner,
        account_id=run.account_id,
        input_id=identifier,
        run_id=root.id,
        kind="scenario",
        input_digest=root.input_digest,
        result_digest=result.content_digest,
        result_id=result.id,
        definition_version_id=version.id,
        definition_digest=version.content_digest,
        snapshot_id=run.portfolio_snapshot_id,
        snapshot_digest=run.portfolio_snapshot_digest,
        reporting_currency=run.reporting_currency,
        source_cutoff_at=run.source_cutoff_at,
        valuation_at=valuation,
        expires_at=deadline,
        created_at=case.now,
    )
    if wrong == "definition":
        binding.definition_digest = "0" * 64
    if wrong == "result":
        binding.result_id = uuid4()
    if wrong == "snapshot":
        binding.snapshot_digest = "0" * 64
    if wrong == "currency":
        binding.reporting_currency = "USD"
    if wrong == "cutoff":
        binding.source_cutoff_at = run.source_cutoff_at - timedelta(seconds=1)
    if wrong == "family":
        binding.kind = "risk"
    session.add(binding)
    row.source_count = len(copied)
    session.flush()
    row.sealed_at = case.now
    session.flush()
    return identifier


@pytest.mark.parametrize(
    "wrong", ["definition", "result", "snapshot", "currency", "cutoff", "family"]
)
async def test_third_profile_rejects_altered_canonical_pin_before_sealing(
    scenario_case: ScenarioCase, wrong: str
) -> None:
    await published(scenario_case)
    with scenario_case.sessions() as session:
        identifier = capture(session, scenario_case)
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        assert (
            session.scalar(
                func.report_premium_restricted(
                    UUID(scenario_case.principal.owner_id), identifier, scenario_case.now
                )
            )
            is False
        )
    with pytest.raises(DBAPIError), scenario_case.sessions() as session, session.begin():
        capture(session, scenario_case, wrong=wrong)


async def test_scenario_cannot_be_attached_to_legacy_profile_two(
    scenario_case: ScenarioCase,
) -> None:
    await published(scenario_case)
    with scenario_case.sessions() as session:
        identifier = capture(session, scenario_case)
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        assert (
            session.scalar(
                func.report_premium_restricted(
                    UUID(scenario_case.principal.owner_id), identifier, scenario_case.now
                )
            )
            is False
        )
    with pytest.raises(DBAPIError), scenario_case.sessions() as session, session.begin():
        capture(session, scenario_case, profile=2)


async def test_current_report_rights_revoke_read_and_sweep_only_the_report(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    await published(case)
    with case.sessions() as session, session.begin():
        identifier = capture(session, case)
    with case.sessions() as session:
        assert (
            session.scalar(
                select(
                    func.report_premium_restricted(
                        UUID(case.principal.owner_id), identifier, case.now
                    )
                )
            )
            is False
        )
    with case.sessions() as session, session.begin():
        lineage = session.scalar(
            select(PremiumRunLicenseModel)
            .where(PremiumRunLicenseModel.run_id == case.run.id)
            .limit(1)
        )
        assert lineage is not None
        original = session.get_one(ProviderLicenseVersionModel, lineage.license_version_id)
        number = session.scalar(
            select(func.max(ProviderLicenseVersionModel.version_number)).where(
                ProviderLicenseVersionModel.provider_id == original.provider_id
            )
        )
        assert number is not None
        session.add(
            ProviderLicenseVersionModel(
                id=uuid4(),
                owner_id=original.owner_id,
                provider_id=original.provider_id,
                version_number=number + 1,
                version=f"report-denied-{number + 1}",
                effective_at=case.now,
                store_permission="allowed",
                display_permission="allowed",
                report_permission="denied",
                export_permission="allowed",
                retention_days=30,
                attribution="Synthetic report denial",
                evidence_key="synthetic",
                created_at=case.now,
            )
        )
    with case.sessions() as session:
        assert (
            session.scalar(
                select(
                    func.report_premium_restricted(
                        UUID(case.principal.owner_id), identifier, case.now
                    )
                )
            )
            is True
        )
    with patch.object(
        ScenarioInputStore, "read_retained_input", side_effect=AssertionError("private decoder")
    ):
        for _ in range(10):
            with case.sessions() as session, session.begin():
                expire_report_payloads(session, at=case.now, budget=SourcePurgeBudget())
            with case.sessions() as session:
                if session.get_one(ReportInputSnapshotModel, identifier).purged_at is not None:
                    break
    with case.sessions() as session:
        assert session.get_one(ReportInputSnapshotModel, identifier).purged_at is not None
        assert (
            session.scalar(
                select(ScenarioResultModel.id).where(
                    ScenarioResultModel.run_id == case.run.id,
                    ScenarioResultModel.canonical_result != b"",
                )
            )
            is not None
        )
    with case.sessions() as session, session.begin():
        assert expire_report_payloads(session, at=case.now) == 0


async def test_source_cleanup_must_drain_report_before_scenario_financial_rows(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    result_id = await published(case)
    with case.sessions() as session, session.begin():
        identifier = capture(session, case)
    for statement in (
        delete(ScenarioComponentModel).where(ScenarioComponentModel.result_id == result_id),
        update(ScenarioResultModel)
        .where(ScenarioResultModel.id == result_id)
        .values(canonical_result=b""),
        update(ReportInputPremiumDependencyModel)
        .where(ReportInputPremiumDependencyModel.input_id == identifier)
        .values(kind="risk"),
    ):
        with pytest.raises(DBAPIError), case.sessions() as session, session.begin():
            session.execute(statement)
    restrict(case)
    assert not cleanup(case, budget=SourcePurgeBudget(bytes_inspected=0, bytes_removed=0))
    with case.sessions() as session:
        assert session.get_one(ReportInputSnapshotModel, identifier).purged_at is None
        assert (
            session.scalar(
                select(ScenarioResultModel.id).where(
                    ScenarioResultModel.id == result_id, ScenarioResultModel.canonical_result != b""
                )
            )
            is not None
        )
    for _ in range(20):
        if cleanup(case):
            break
    with case.sessions() as session:
        assert session.get_one(ReportInputSnapshotModel, identifier).purged_at is not None
        assert (
            session.scalar(
                select(ScenarioResultModel.canonical_result).where(
                    ScenarioResultModel.id == result_id
                )
            )
            == b""
        )
    assert cleanup(case)


async def test_new_run_does_not_refresh_original_source_license_lifetime(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    case.now = max(case.now + timedelta(days=2), datetime.now(UTC))
    case.principal = replace(case.principal, expires_at=case.now + timedelta(days=1))
    case.command = replace(case.command, idempotency_key=str(uuid4()))
    case.run = await case.service.create_run(case.principal, case.command)
    await published(case)
    with case.sessions() as session, session.begin():
        identifier = capture(session, case, copy_deadline=case.now + timedelta(hours=1))
    restrict(case, permission="allowed", days=1)
    with case.sessions() as session:
        root = session.get_one(PremiumRunModel, case.run.id)
        assert root.created_at + timedelta(days=1) > case.now
        license_id = session.scalar(
            select(PremiumRunLicenseModel.license_version_id)
            .where(PremiumRunLicenseModel.run_id == case.run.id)
            .order_by(PremiumRunLicenseModel.id)
            .limit(1)
        )
        assert license_id is not None
        original_license = session.get_one(ProviderLicenseVersionModel, license_id)
        dependency = session.scalar(
            select(ReportInputDependencyModel)
            .where(
                ReportInputDependencyModel.input_id == identifier,
                ReportInputDependencyModel.provider_id == original_license.provider_id,
            )
            .limit(1)
        )
        assert dependency is not None
        model, _column = _PHYSICAL[dependency.kind]
        original_at = session.scalar(
            select(model.created_at).where(
                model.id == dependency.source_id, model.owner_id == dependency.owner_id
            )
        )
        assert original_at is not None
        short_copy_end = case.now + timedelta(hours=1)
        assert (
            session.scalar(
                select(
                    func.report_premium_license_restricted(
                        dependency.owner_id,
                        dependency.provider_id,
                        dependency.license_version_id,
                        root.created_at,
                        short_copy_end,
                        case.now,
                    )
                )
            )
            is False
        )
        assert (
            session.scalar(
                select(
                    func.report_premium_license_restricted(
                        dependency.owner_id,
                        dependency.provider_id,
                        dependency.license_version_id,
                        original_at,
                        short_copy_end,
                        case.now,
                    )
                )
            )
            is True
        )
        assert (
            session.scalar(
                select(
                    func.report_premium_restricted(
                        UUID(case.principal.owner_id), identifier, case.now
                    )
                )
            )
            is True
        )


async def test_busy_source_owner_fails_without_waiting_on_scenario_financial_row(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    result_id = await published(case)
    with case.sessions() as session, session.begin():
        capture(session, case)
    with case.sessions() as holder, holder.begin():
        holder.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"sources:{case.principal.owner_id}"},
        )
        with pytest.raises(DBAPIError) as error, case.sessions() as other, other.begin():
            other.execute(text("SET LOCAL statement_timeout='2s'"))
            other.execute(
                delete(ScenarioComponentModel).where(ScenarioComponentModel.result_id == result_id)
            )
        assert getattr(error.value.orig, "sqlstate", None) == "55P03"


async def test_populated_profile3_downgrade_rejects_before_any_schema_change(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    await published(case)
    with case.sessions() as session, session.begin():
        identifier = capture(session, case)
    migration = run_path("migrations/versions/20260915_0021_premium_report_profiles.py")
    downgrade = cast(Callable[[], None], migration["downgrade"])
    with case.engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with (
            Operations.context(context),
            pytest.raises(DBAPIError, match="Third-profile reports must be absent"),
            connection.begin(),
        ):
            downgrade()
    with case.sessions() as session:
        assert session.get_one(ReportInputSnapshotModel, identifier).contract_version == 3
        assert (
            session.scalar(
                select(
                    func.report_premium_restricted(
                        UUID(case.principal.owner_id), identifier, case.now
                    )
                )
            )
            is False
        )
