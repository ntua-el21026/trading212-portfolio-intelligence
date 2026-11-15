"""Real normalized grants, report copies, physical barriers and bounded erasure."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID, uuid4

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import Table, delete, func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from trading212_application import reports as app
from trading212_application import research as research_app
from trading212_domain import reports as r
from trading212_domain.research_notes import ResearchNoteContent
from trading212_domain.research_sources import ResearchCitationPin
from trading212_domain.sources import FxSnapshot, source_snapshot_digest
from trading212_persistence.acquisition_authority import grant_digest
from trading212_persistence.acquisition_models import ProviderCapabilityGrantModel
from trading212_persistence.acquisition_records import AcquisitionCapability
from trading212_persistence.acquisition_research_authority import (
    PostgresResearchCapabilityAuthority,
)
from trading212_persistence.report_models import (
    ArtifactDownloadGrantModel,
    ReportArtifactModel,
    ReportDispatchOutboxModel,
    ReportInputChunkModel,
    ReportInputDependencyModel,
    ReportInputLicenseModel,
    ReportInputPinModel,
    ReportInputSnapshotModel,
    ReportJobModel,
    ReportManifestModel,
    ReportRetentionWorkModel,
)
from trading212_persistence.report_research_models import (
    ReportInputResearchDependencyModel,
    ReportInputResearchNoteModel,
    ReportInputResearchSourceModel,
    ReportResearchRetentionSweepModel,
)
from trading212_persistence.report_research_retention import expire_research_report_payloads
from trading212_persistence.report_retention import expire_report_payloads, purge_report_input
from trading212_persistence.report_sources import _physical_permit
from trading212_persistence.research_models import (
    ResearchEventPayloadModel,
    ResearchItemModel,
    ResearchNotePayloadModel,
    ResearchOwnerErasureModel,
    ResearchRetentionModel,
    ResearchSourcePayloadModel,
)
from trading212_persistence.research_retention import (
    expire_research_payloads,
    purge_owner_research_payloads,
)
from trading212_persistence.source_models import (
    FxObservationModel,
    FxSnapshotModel,
    ProviderLicenseVersionModel,
)
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.xray_run_models import XrayInputSnapshotModel, XrayRunModel
from trading212_security.principals import AuthorizationError
from trading212_worker.premium_acquisition_runtime import PostgresPremiumAcquisitionRuntime
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.provider_acquisition_case import acquisition_case
from tests.integration.research_case import research_case as research_case
from tests.integration.research_report_case import ResearchReportCase, complete, generate, selection
from tests.integration.research_report_case import research_report_case as research_report_case
from tests.integration.test_provider_publication_postgres import batch
from tests.integration.test_research_reports_postgres import originals
from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


async def test_populated_research_report_downgrade_refuses_without_mutating_state(
    research_report_case: ResearchReportCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = research_report_case
    status = await generate(case, selected=selection(case, formats=(r.ReportFormat.JSON,)))
    input_id = _input(case, status.job_id)
    models = (
        ReportInputResearchDependencyModel,
        ReportInputResearchSourceModel,
        ReportInputResearchNoteModel,
        ReportResearchRetentionSweepModel,
        ReportInputSnapshotModel,
        ReportInputChunkModel,
        ReportInputPinModel,
        ReportInputLicenseModel,
        ReportInputDependencyModel,
        ReportJobModel,
        ReportDispatchOutboxModel,
        ReportManifestModel,
        ReportArtifactModel,
        ArtifactDownloadGrantModel,
        ReportRetentionWorkModel,
    )
    tables = tuple(cast(Table, model.__table__) for model in models)

    def retained_state() -> tuple[tuple[tuple[object, ...], ...], ...]:
        with case.research.xray.sessions() as session:
            return tuple(
                tuple(
                    tuple(row)
                    for row in session.execute(select(table).order_by(*table.primary_key))
                )
                for table in tables
            )

    def schema_state() -> tuple[str, tuple[str, ...], tuple[tuple[object, ...], ...]]:
        with case.research.xray.sessions() as session:
            head = session.scalar(text("SELECT version_num FROM alembic_version"))
            assert isinstance(head, str)
            functions = tuple(
                tuple(row)
                for row in session.execute(
                    text(
                        "SELECT p.oid::bigint,p.oid::regprocedure::text,pg_get_functiondef(p.oid) "
                        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                        "WHERE n.nspname='public' AND (p.proname LIKE 'report_research_%' "
                        "OR p.proname LIKE 'research_report_%' OR p.proname IN "
                        "('report_premium_restricted','report_premium_capture_complete',"
                        "'legacy_report_witness_restricted')) ORDER BY p.oid"
                    )
                )
            )
        return head, tuple(sorted(inspect(case.research.xray.engine).get_table_names())), functions

    before, schema_before, originals_before = retained_state(), schema_state(), originals(case)
    assert before[0] and before[1] and before[2]
    assert schema_before[0] == "20261115_0036"
    with case.research.xray.sessions() as session:
        assert (
            session.scalar(
                select(ReportInputResearchDependencyModel.copy_pending).where(
                    ReportInputResearchDependencyModel.input_id == input_id
                )
            )
            is True
        )
    url = case.research.xray.engine.url.render_as_string(hide_password=False)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    with monkeypatch.context() as environment:
        environment.setenv("DATABASE_URL", url)
        with pytest.raises(IntegrityError, match="requires empty research report provenance"):
            alembic_command.downgrade(config, "20261113_0034")
    assert retained_state() == before
    assert schema_state() == schema_before
    assert originals(case) == originals_before


def _revoke(case: ResearchReportCase, *, store: bool = True, license_only: bool = False) -> None:
    """Append a valid current approval; the original immutable grant is untouched."""
    original = case.grant
    with case.research.xray.sessions() as session, session.begin():
        license_id = original.license_version_id
        if license_only:
            pinned = session.get_one(ProviderLicenseVersionModel, license_id)
            successor = ProviderLicenseVersionModel(
                id=uuid4(),
                owner_id=pinned.owner_id,
                provider_id=pinned.provider_id,
                version_number=pinned.version_number + 1,
                version="synthetic-report-denied-v2",
                effective_at=case.research.xray.now[0],
                store_permission="allowed",
                display_permission="allowed",
                report_permission="denied",
                export_permission="allowed",
                retention_days=pinned.retention_days,
                attribution=pinned.attribution,
                evidence_key="synthetic-report-license-revocation",
                created_at=case.research.xray.now[0],
            )
            session.add(successor)
            session.flush()
            license_id = successor.id
        current = ProviderCapabilityGrantModel(
            id=uuid4(),
            owner_id=original.owner_id,
            provider_id=original.provider_id,
            scope_id=original.scope_id,
            version_number=original.version_number + 1,
            license_version_id=license_id,
            effective_at=case.research.xray.now[0],
            expires_at=original.expires_at,
            store_allowed=store,
            display_allowed=True,
            report_allowed=license_only,
            export_allowed=True,
            daily_allowance=original.daily_allowance,
            evidence_key="synthetic-report-revocation",
            content_digest="0" * 64,
            created_at=case.research.xray.now[0],
        )
        current.content_digest = grant_digest(current)
        session.add(current)


def _input(case: ResearchReportCase, job_id: UUID) -> UUID:
    with case.research.xray.sessions() as session:
        return session.get_one(ReportJobModel, job_id).input_id


def _assert_physical_absence(case: ResearchReportCase, input_id: UUID) -> None:
    with case.research.xray.sessions() as session:
        capture = session.get_one(ReportInputSnapshotModel, input_id)
        assert capture.canonical_manifest is None and capture.canonical_context is None
        assert capture.purged_at is not None
        assert (
            session.scalar(
                select(ReportInputChunkModel.id)
                .where(
                    ReportInputChunkModel.input_id == input_id,
                    ReportInputChunkModel.payload.is_not(None),
                )
                .limit(1)
            )
            is None
        )
        jobs = tuple(
            session.scalars(select(ReportJobModel.id).where(ReportJobModel.input_id == input_id))
        )
        assert jobs
        assert (
            session.scalar(
                select(ReportArtifactModel.id)
                .where(
                    ReportArtifactModel.job_id.in_(jobs), ReportArtifactModel.contents.is_not(None)
                )
                .limit(1)
            )
            is None
        )
        assert (
            session.scalar(
                select(ReportManifestModel.id)
                .where(
                    ReportManifestModel.job_id.in_(jobs), ReportManifestModel.payload.is_not(None)
                )
                .limit(1)
            )
            is None
        )
        artifact_ids = select(ReportArtifactModel.id).where(ReportArtifactModel.job_id.in_(jobs))
        assert (
            session.scalar(
                select(ArtifactDownloadGrantModel.id)
                .where(ArtifactDownloadGrantModel.report_artifact_id.in_(artifact_ids))
                .limit(1)
            )
            is None
        )
        assert set(
            session.scalars(
                select(ReportDispatchOutboxModel.state).where(
                    ReportDispatchOutboxModel.job_id.in_(jobs)
                )
            )
        ) == {"dead_letter"}


def _assert_closed(case: ResearchReportCase, input_id: UUID) -> None:
    _assert_physical_absence(case, input_id)
    with case.research.xray.sessions() as session:
        root = session.scalar(
            select(ReportInputResearchDependencyModel).where(
                ReportInputResearchDependencyModel.input_id == input_id
            )
        )
        assert root is not None and not root.copy_pending and not root.payload_pending
        for model in (ReportInputResearchSourceModel, ReportInputResearchNoteModel):
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.input_id == input_id, model.copy_pending.is_(True))
                )
                == 0
            )
        work = session.scalar(
            select(ReportRetentionWorkModel).where(ReportRetentionWorkModel.input_id == input_id)
        )
        assert work is not None and work.completed_at is not None


@pytest.mark.parametrize("restriction", ["grant", "license"])
async def test_report_only_revocation_drains_all_copies_and_preserves_originals(
    research_report_case: ResearchReportCase,
    restriction: Literal["grant", "license"],
) -> None:
    case = research_report_case
    completed = await complete(case, await generate(case))
    input_id = _input(case, completed.job_id)
    artifact = next(a for a in completed.artifacts if a.format is r.ReportFormat.JSON)
    grant = await case.reports.create_report_download_grant(
        case.research.xray.principal,
        case.research.account_id,
        completed.job_id,
        artifact.artifact_id,
    )
    before = originals(case)
    _revoke(case, license_only=restriction == "license")
    for operation in (
        lambda: case.reports.get_report_manifest(
            case.research.xray.principal, case.research.account_id, completed.job_id
        ),
        lambda: case.reports.download_report_artifact(
            case.research.xray.principal,
            case.research.account_id,
            completed.job_id,
            artifact.artifact_id,
            grant_token=grant.token,
        ),
        lambda: generate(case),
    ):
        with pytest.raises(app.ReportServiceError):
            await operation()
    # DISPLAY remains independently authorized by the actual normalized authority.
    assert (
        await case.research.service.get_research_item(
            case.research.xray.principal, case.item.item_id
        )
    ).source.revision_id == case.event.revision_id
    owner, at = UUID(case.research.xray.principal.owner_id), case.research.xray.now[0]
    with case.research.xray.sessions() as session, session.begin():
        witness = session.scalar(
            select(ReportInputResearchSourceModel.id).where(
                ReportInputResearchSourceModel.input_id == input_id
            )
        )
        assert witness is not None
        budget = SourcePurgeBudget(rows_inspected=160)
        assert not purge_report_input(
            session,
            owner=owner,
            input_id=input_id,
            reason="source",
            at=at,
            budget=budget,
            legacy_witness=("research_source", witness),
        )
        marker = session.scalar(
            select(ReportRetentionWorkModel).where(ReportRetentionWorkModel.input_id == input_id)
        )
        assert marker is not None and marker.completed_at is None
        assert (
            session.scalar(
                select(ReportInputResearchDependencyModel.copy_pending).where(
                    ReportInputResearchDependencyModel.input_id == input_id
                )
            )
            is True
        )
        assert 0 <= budget.rows_inspected <= 160
    for _ in range(16):
        with case.research.xray.sessions() as session, session.begin():
            budget = SourcePurgeBudget()
            expire_report_payloads(session, at=at, budget=budget)
            assert 0 <= budget.rows_inspected <= 4096 and 0 <= budget.rows_removed <= 4096
            done = session.scalar(
                select(ReportRetentionWorkModel.completed_at).where(
                    ReportRetentionWorkModel.input_id == input_id
                )
            )
        if done is not None:
            break
    else:
        pytest.fail("Bounded research report cleanup did not finish.")
    _assert_closed(case, input_id)
    assert originals(case) == before


async def test_source_completion_cannot_overtake_retained_research_report_copies(
    research_report_case: ResearchReportCase,
) -> None:
    case = research_report_case
    completed = await complete(
        case,
        await generate(
            case,
            selected=selection(
                case,
                notes=(case.note.revision_id, case.newer_note.revision_id),
                formats=(r.ReportFormat.JSON,),
            ),
        ),
    )
    input_id = _input(case, completed.job_id)
    source = case.event.citations[0].source.version_id
    _revoke(case, store=False)
    owner, at = UUID(case.research.xray.principal.owner_id), case.research.xray.now[0]
    with case.research.xray.sessions() as session, session.begin():
        budget = SourcePurgeBudget(rows_inspected=128)
        assert not expire_research_payloads(
            session,
            at=at,
            owner=owner,
            budget=budget,
            capability_authority=PostgresResearchCapabilityAuthority(),
        )
        marker = session.scalar(
            select(ResearchRetentionModel).where(ResearchRetentionModel.source_version_id == source)
        )
        assert marker is not None and marker.completed_at is None
        for statement in (
            delete(ResearchSourcePayloadModel).where(
                ResearchSourcePayloadModel.version_id == source
            ),
            delete(ResearchEventPayloadModel).where(
                ResearchEventPayloadModel.revision_id == case.event.revision_id
            ),
            update(ResearchRetentionModel)
            .where(ResearchRetentionModel.id == marker.id)
            .values(completed_at=at),
        ):
            with (
                pytest.raises(IntegrityError, match="Research report physical copies remain"),
                session.begin_nested(),
            ):
                session.execute(statement)
    # A160-row invocation cannot combine physical completion and all four
    # source/note/header flag transitions. Observe the real committed boundary.
    for _ in range(16):
        with case.research.xray.sessions() as session, session.begin():
            expire_research_payloads(
                session,
                at=at,
                owner=owner,
                budget=SourcePurgeBudget(rows_inspected=160),
                capability_authority=PostgresResearchCapabilityAuthority(),
            )
            root = session.scalar(
                select(ReportInputResearchDependencyModel).where(
                    ReportInputResearchDependencyModel.input_id == input_id
                )
            )
            source_pending = session.scalar(
                select(ReportInputResearchSourceModel.copy_pending).where(
                    ReportInputResearchSourceModel.input_id == input_id
                )
            )
            assert root is not None
            intermediate = (
                not root.payload_pending and root.copy_pending and source_pending is False
            )
        if intermediate:
            break
    else:
        pytest.fail("The bounded physical-before-audit continuation was not observed.")
    _assert_physical_absence(case, input_id)
    for _ in range(16):
        with case.research.xray.sessions() as session, session.begin():
            complete_pass = expire_research_payloads(
                session,
                at=at,
                owner=owner,
                budget=SourcePurgeBudget(),
                capability_authority=PostgresResearchCapabilityAuthority(),
            )
        if complete_pass:
            break
    else:
        pytest.fail("Research source report closure did not finish.")
    # Original source completion is permitted after physical copies are gone;
    # the independent permanent report work queue finishes any audit flags.
    for _ in range(16):
        with case.research.xray.sessions() as session, session.begin():
            expire_report_payloads(session, at=at, budget=SourcePurgeBudget())
            completed_at = session.scalar(
                select(ReportRetentionWorkModel.completed_at).where(
                    ReportRetentionWorkModel.input_id == input_id
                )
            )
        if completed_at is not None:
            break
    else:
        pytest.fail("Report audit continuation did not finish.")
    _assert_closed(case, input_id)
    with case.research.xray.sessions() as session:
        assert (
            session.scalar(
                select(ResearchSourcePayloadModel.id).where(
                    ResearchSourcePayloadModel.version_id == source
                )
            )
            is None
        )
        assert (
            session.scalar(
                select(ResearchEventPayloadModel.id).where(
                    ResearchEventPayloadModel.revision_id == case.event.revision_id
                )
            )
            is None
        )
        # Provider cleanup preserves the owner's original revision and opaque pins.
        assert (
            session.scalar(
                select(ResearchNotePayloadModel.canonical_note).where(
                    ResearchNotePayloadModel.revision_id == case.note.revision_id
                )
            )
            is not None
        )


async def test_active_owner_research_erasure_drains_reports_before_owner_note_copies(
    research_report_case: ResearchReportCase,
) -> None:
    case = research_report_case
    status = await complete(
        case, await generate(case, selected=selection(case, formats=(r.ReportFormat.JSON,)))
    )
    input_id = _input(case, status.job_id)
    owner, at = UUID(case.research.xray.principal.owner_id), case.research.xray.now[0]
    with case.research.xray.sessions() as session, session.begin():
        assert not purge_owner_research_payloads(
            session, owner, at=at, budget=SourcePurgeBudget(rows_inspected=128)
        )
        marker = session.get_one(ResearchOwnerErasureModel, owner)
        assert marker.completed_at is None
        with (
            pytest.raises(IntegrityError, match="Research report physical copies remain"),
            session.begin_nested(),
        ):
            session.execute(
                delete(ResearchNotePayloadModel).where(
                    ResearchNotePayloadModel.revision_id == case.note.revision_id
                )
            )
        with (
            pytest.raises(IntegrityError, match="Research report physical copies remain"),
            session.begin_nested(),
        ):
            session.execute(
                update(ResearchOwnerErasureModel)
                .where(ResearchOwnerErasureModel.owner_id == owner)
                .values(completed_at=at)
            )
    for _ in range(16):
        with case.research.xray.sessions() as session, session.begin():
            done = purge_owner_research_payloads(session, owner, at=at, budget=SourcePurgeBudget())
        if done:
            break
    else:
        pytest.fail("Owner research report closure did not finish.")
    _assert_closed(case, input_id)
    with case.research.xray.sessions() as session:
        assert session.get_one(ResearchOwnerErasureModel, owner).completed_at is not None
        for model in (
            ResearchNotePayloadModel,
            ResearchEventPayloadModel,
            ResearchSourcePayloadModel,
        ):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.owner_id == owner)
                )
                == 0
            )


async def test_exact_lineage_and_xray_copy_flags_cannot_be_rewritten_before_erasure(
    research_report_case: ResearchReportCase,
) -> None:
    case = research_report_case
    status = await generate(case, selected=selection(case, formats=(r.ReportFormat.JSON,)))
    input_id = _input(case, status.job_id)
    with case.research.xray.sessions() as session, session.begin():
        root = session.scalar(
            select(ReportInputResearchDependencyModel).where(
                ReportInputResearchDependencyModel.input_id == input_id
            )
        )
        assert root is not None
        for model, change in (
            (ReportInputResearchDependencyModel, {"copy_pending": False}),
            (ReportInputResearchDependencyModel, {"payload_pending": False}),
            (ReportInputResearchSourceModel, {"source_version_id": uuid4()}),
            (ReportInputResearchSourceModel, {"copy_pending": False}),
            (ReportInputResearchNoteModel, {"revision_id": case.newer_note.revision_id}),
            (ReportInputResearchNoteModel, {"copy_pending": False}),
        ):
            with pytest.raises(IntegrityError), session.begin_nested():
                session.execute(update(model).where(model.input_id == input_id).values(**change))
        for statement in (
            update(XrayInputSnapshotModel)
            .where(XrayInputSnapshotModel.id == root.xray_input_id)
            .values(canonical_input=b""),
            update(XrayRunModel)
            .where(XrayRunModel.id == case.item.portfolio.pin.run_id)
            .values(canonical_summary=b"", canonical_reconciliation=b"", canonical_exact_state=b""),
        ):
            with pytest.raises(IntegrityError), session.begin_nested():
                session.execute(statement)


async def test_note_only_source_membership_clamps_the_copy_to_the_original_expiry(
    research_report_case: ResearchReportCase,
) -> None:
    case = research_report_case
    incoming = case.research.incoming(
        "selected-note-only", summary="Independent note citation facts."
    )
    citation = incoming.citations[0]
    shorter = replace(citation.source, expires_at=case.research.xray.now[0] + timedelta(days=1))
    note_event = case.research.publish(
        replace(incoming, citations=(replace(citation, source=shorter),))
    )
    note = await case.research.service.create_research_note(
        case.research.xray.principal,
        research_app.CreateResearchNote(
            account_id=case.research.account_id,
            entity_id=case.research.entity_id,
            content=ResearchNoteContent(
                title="Explicit separate source",
                thesis="Owner hypothesis.",
                citations=(ResearchCitationPin.from_citation(note_event.citations[0]),),
            ),
            idempotency_key=uuid4().hex,
            correlation_id="note-only-report-source",
        ),
    )
    status = await generate(
        case, selected=selection(case, notes=(note.revision_id,), formats=(r.ReportFormat.JSON,))
    )
    input_id = _input(case, status.job_id)
    with case.research.xray.sessions() as session:
        root = session.scalar(
            select(ReportInputResearchDependencyModel).where(
                ReportInputResearchDependencyModel.input_id == input_id
            )
        )
        assert root is not None and root.source_count == 2 and root.note_count == 1
        item = session.get_one(ResearchItemModel, case.item.item_id)
        assert root.expires_at <= shorter.expires_at < item.expires_at
        assert set(
            session.scalars(
                select(ReportInputResearchSourceModel.source_version_id).where(
                    ReportInputResearchSourceModel.input_id == input_id
                )
            )
        ) == {case.event.citations[0].source.version_id, shorter.version_id}
        assert (
            session.scalar(
                select(ReportInputResearchNoteModel.revision_id).where(
                    ReportInputResearchNoteModel.input_id == input_id
                )
            )
            == note.revision_id
        )


async def test_xray_report_only_license_revocation_uses_the_bounded_physical_phase(
    research_report_case: ResearchReportCase,
) -> None:
    case = research_report_case
    completed = await complete(
        case, await generate(case, selected=selection(case, formats=(r.ReportFormat.JSON,)))
    )
    input_id = _input(case, completed.job_id)
    before = originals(case)
    artifact = completed.artifacts[0]
    grant = await case.reports.create_report_download_grant(
        case.research.xray.principal,
        case.research.account_id,
        completed.job_id,
        artifact.artifact_id,
    )
    with case.research.xray.sessions() as session, session.begin():
        members = tuple(
            session.scalars(
                select(ReportInputDependencyModel)
                .where(
                    ReportInputDependencyModel.input_id == input_id,
                    ReportInputDependencyModel.provider_id != case.research.license.provider_id,
                )
                .order_by(ReportInputDependencyModel.id)
            )
        )
        assert members, "The complete research report must retain its original X-ray proof."
        pinned = session.get_one(ProviderLicenseVersionModel, members[0].license_version_id)
        affected_ids = {m.id for m in members if m.provider_id == pinned.provider_id}
        number = session.scalar(
            select(func.max(ProviderLicenseVersionModel.version_number)).where(
                ProviderLicenseVersionModel.provider_id == pinned.provider_id
            )
        )
        assert number is not None
        session.add(
            ProviderLicenseVersionModel(
                id=uuid4(),
                owner_id=pinned.owner_id,
                provider_id=pinned.provider_id,
                version_number=number + 1,
                version=f"synthetic-xray-report-denied-{number + 1}",
                effective_at=case.research.xray.now[0],
                store_permission="allowed",
                display_permission="allowed",
                report_permission="denied",
                export_permission="allowed",
                retention_days=pinned.retention_days,
                attribution=pinned.attribution,
                evidence_key="synthetic-xray-report-only",
                created_at=case.research.xray.now[0],
            )
        )
    for operation in (
        lambda: case.reports.get_report_manifest(
            case.research.xray.principal, case.research.account_id, completed.job_id
        ),
        lambda: case.reports.download_report_artifact(
            case.research.xray.principal,
            case.research.account_id,
            completed.job_id,
            artifact.artifact_id,
            grant_token=grant.token,
        ),
        lambda: generate(case),
    ):
        with pytest.raises(app.ReportServiceError):
            await operation()
    # The ordinary retained reader still authorizes STORE/DISPLAY and decodes
    # the actual pinned result; REPORT refusal is confined to the derived copy.
    with case.research.xray.sessions() as session, session.begin():
        pin, xray, xray_input, _ = case.research.service.retained_xray(
            session, case.research.auth(session), case.research.run_id
        )
        assert pin == case.item.portfolio.pin
        assert xray is not None and xray_input is not None
    for _ in range(16):
        with case.research.xray.sessions() as session, session.begin():
            budget = SourcePurgeBudget()
            expire_research_report_payloads(session, at=case.research.xray.now[0], budget=budget)
            assert 0 <= budget.rows_inspected <= 4096
            marker = session.scalar(
                select(ReportRetentionWorkModel).where(
                    ReportRetentionWorkModel.input_id == input_id
                )
            )
            done = marker is not None and marker.completed_at is not None
            if marker is not None:
                assert marker.legacy_source_kind == "physical"
                assert marker.legacy_source_id in affected_ids
        if done:
            break
    else:
        pytest.fail("Research X-ray REPORT-only physical cleanup did not finish.")
    _assert_closed(case, input_id)
    assert originals(case) == before


async def test_real_acquired_fx_report_only_grant_loss_reaches_the_closed_research_helper(
    xray_read_case: XrayReadCase,
) -> None:
    """Component qualification; no claim this current fixing belongs to the old X-ray.

    The preceding full-report case covers exact physical-witness cleanup. This
    case independently uses real publication/approval storage for the acquired
    financial authority arm, without substituting permission functions or pins.
    """
    case = acquisition_case(xray_read_case, capability=AcquisitionCapability.REFERENCE_FX)
    runtime = PostgresPremiumAcquisitionRuntime(
        sessions=case.xray.sessions,
        principal=case.xray.principal,
        cursor_signing_key=XRAY_CURSOR_KEY,
        enabled=True,
    )
    published = await runtime.publish(await batch(case, runtime))
    assert isinstance(published, FxSnapshot)
    source_id, owner = UUID(published.id), case.selection.owner_id
    with case.xray.sessions() as session, session.begin():
        source = session.get_one(FxSnapshotModel, source_id)
        assert source.adapter_version == "premium_fixed_get_v1"
        at = datetime.now(UTC)
        assert (
            session.scalar(
                text("SELECT report_research_acquired_report_restricted(:owner,'fx',:source,:at)"),
                {"owner": owner, "source": source_id, "at": at},
            )
            is False
        )
        _physical_permit(session, source, "fx", source_use=r.ReportSourceUse.REPORT, now=at)
        before = tuple(
            tuple(row)
            for row in session.execute(
                select(
                    FxObservationModel.id,
                    FxObservationModel.rate,
                    FxObservationModel.effective_at,
                    FxObservationModel.created_at,
                )
                .where(FxObservationModel.snapshot_id == source_id)
                .order_by(FxObservationModel.id)
            )
        )
        assert before
        original = case.grant
        successor = ProviderCapabilityGrantModel(
            id=uuid4(),
            owner_id=owner,
            provider_id=original.provider_id,
            scope_id=original.scope_id,
            version_number=original.version_number + 1,
            license_version_id=original.license_version_id,
            effective_at=at,
            expires_at=original.expires_at,
            store_allowed=True,
            display_allowed=True,
            report_allowed=False,
            export_allowed=True,
            daily_allowance=original.daily_allowance,
            evidence_key="synthetic-fx-report-only",
            content_digest="0" * 64,
            created_at=at,
        )
        successor.content_digest = grant_digest(successor)
        session.add(successor)
    with case.xray.sessions() as session, session.begin():
        at = datetime.now(UTC)
        for use in ("store", "display"):
            assert (
                session.scalar(
                    text("SELECT acquisition_source_restricted(:owner,'fx',:source,:at,:use)"),
                    {"owner": owner, "source": source_id, "at": at, "use": use},
                )
                is False
            )
        assert (
            session.scalar(
                text("SELECT report_research_acquired_report_restricted(:owner,'fx',:source,:at)"),
                {"owner": owner, "source": source_id, "at": at},
            )
            is True
        )
        source = session.get_one(FxSnapshotModel, source_id)
        with pytest.raises(AuthorizationError):
            _physical_permit(session, source, "fx", source_use=r.ReportSourceUse.REPORT, now=at)
        assert source.content_digest == source_snapshot_digest(published)
        assert (
            tuple(
                tuple(row)
                for row in session.execute(
                    select(
                        FxObservationModel.id,
                        FxObservationModel.rate,
                        FxObservationModel.effective_at,
                        FxObservationModel.created_at,
                    )
                    .where(FxObservationModel.snapshot_id == source_id)
                    .order_by(FxObservationModel.id)
                )
            )
            == before
        )
