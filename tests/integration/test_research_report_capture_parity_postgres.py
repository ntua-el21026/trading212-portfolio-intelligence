"""Frozen capture-byte parity and real REPORT authority around retained reads."""

from collections.abc import Callable
from contextlib import ExitStack
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import reports as app
from trading212_application import research as research_app
from trading212_domain import reports as r
from trading212_domain.research_facts import ResearchXrayPin
from trading212_domain.sources import SourceUse
from trading212_domain.xray_result import XrayCalculation
from trading212_persistence import report_capture_research_store as capture_module
from trading212_persistence.acquisition_models import ProviderCapabilityGrantModel
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_persistence.report_capture_research import ResearchReportWriter
from trading212_persistence.report_capture_research_store import ResearchReportStore
from trading212_persistence.report_capture_xray import _SOURCE_KINDS, _source_key, _source_parents
from trading212_persistence.report_models import (
    ReportInputChunkModel,
    ReportInputSnapshotModel,
    ReportJobModel,
)
from trading212_persistence.research_item_store import ResearchItemStore
from trading212_persistence.research_xray_read import (
    ResearchXrayRead,
    finish_research_xray,
    read_research_xray,
)
from trading212_persistence.source_store import digest
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.acquired_research_report_case import AcquiredResearchReportCase
from tests.integration.acquired_research_report_case import (
    acquired_research_report_case as acquired_research_report_case,
)
from tests.integration.research_case import research_case as research_case
from tests.integration.research_report_case import generate, selection
from tests.integration.research_report_case import research_report_case as research_report_case
from tests.integration.test_acquired_research_reports_postgres import (
    _authority_revision,
    _fx_state,
    _no_private_reads,
    _report_state,
)
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


class LegacyResearchReportStore(ResearchReportStore):
    """Retain the pre-optimization reader, including both original metadata gates."""

    def xray_metadata(
        self, session: Session, auth: ReportAuthorization, run_id: UUID
    ) -> tuple[UUID, str, str, UUID, datetime | None]:
        return ResearchItemStore.xray_metadata(self, session, auth, run_id)

    def retained_xray(
        self, session: Session, auth: ReportAuthorization, run_id: UUID
    ) -> tuple[ResearchXrayPin, XrayCalculation, UUID, datetime | None]:
        return ResearchItemStore.retained_xray(self, session, auth, run_id)


def _legacy_xray_sources(
    writer: ResearchReportWriter,
    store: ResearchReportStore,
    session: Session,
    result: XrayCalculation,
) -> None:
    """Frozen source projection: independently retain its original keys/order/bytes."""
    builder, context, service = writer.builder, writer.context, store._research_xray
    for dependency in result.source_dependencies:
        if dependency.license_version_id is not None:
            license = service._permit(
                session, builder.owner_id, dependency.license_version_id, SourceUse.REPORT
            )
            builder.add_license(
                r.ReportLicenseReference(
                    version_id=dependency.license_version_id,
                    provider_id=UUID(license.provider_id),
                    license_digest=digest(license),
                    attribution=license.attribution,
                    pinned_store=license.store,
                    pinned_display=license.display,
                    pinned_report=license.report,
                    pinned_export=license.export,
                    valid_from=license.effective_at,
                )
            )
        view = service._source_view(session, builder.owner_id, dependency)
        builder.add_reference(
            r.ReportSourceReference(
                key=_source_key(dependency.id),
                kind=_SOURCE_KINDS[dependency.reference.kind],
                subject_id=dependency.reference.record_id,
                parent_id=dependency.reference.parent_record_id,
                content_digest=dependency.content_digest,
                source_at=view.source_at,
                first_observed_at=view.first_observed_at,
                provider_id=None
                if dependency.provider_id is None
                else UUID(dependency.provider_id),
                license_version_id=dependency.license_version_id,
            ),
            provenance_set_key=context.provenance_set_key,
        )
    _source_parents(builder, context, session, service, result, SourceUse.REPORT)


def _captured(case: AcquiredResearchReportCase, job_id: UUID) -> tuple[object, ...]:
    with case.report.research.xray.sessions() as session:
        job = session.get_one(ReportJobModel, job_id)
        row = session.get_one(ReportInputSnapshotModel, job.input_id)
        chunks = tuple(
            tuple(value)
            for value in session.execute(
                select(
                    ReportInputChunkModel.table_key,
                    ReportInputChunkModel.ordinal,
                    ReportInputChunkModel.content_digest,
                    ReportInputChunkModel.row_count,
                    ReportInputChunkModel.byte_length,
                    ReportInputChunkModel.payload,
                )
                .where(ReportInputChunkModel.input_id == row.id)
                .order_by(ReportInputChunkModel.table_key, ReportInputChunkModel.ordinal)
            )
        )
        assert row.canonical_manifest and row.canonical_context and chunks
        return (
            row.canonical_manifest,
            row.canonical_context,
            row.input_digest,
            row.document_digest,
            row.canonical_byte_length,
            row.chunk_count,
            row.pin_count,
            row.source_count,
            row.expires_at,
            chunks,
        )


async def test_frozen_legacy_and_candidate_research_capture_have_identical_bytes(
    acquired_research_report_case: AcquiredResearchReportCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = acquired_research_report_case
    # Keep the actual current capture clock fixed across both admissions. These
    # jobs remain queued: no frozen worker lease is compared with SQL wall time.
    case.report.research.xray.now[0] = max(case.report.research.xray.now[0], datetime.now(UTC))
    assert case.xray.summary.total.value is not None
    assert case.xray.summary.total.value.amount == Decimal("1123.456789123456789")
    selected = selection(case.report, formats=(r.ReportFormat.JSON,))
    sources = _fx_state(case)
    with monkeypatch.context() as legacy:
        legacy.setattr(capture_module, "ResearchReportStore", LegacyResearchReportStore)
        legacy.setattr(capture_module, "_xray_sources", _legacy_xray_sources)
        original = await generate(case.report, selected=selected)
    candidate = await generate(case.report, selected=selected)
    assert original.job_id != candidate.job_id
    assert original.state is candidate.state is r.ReportJobState.QUEUED
    assert _captured(case, original.job_id) == _captured(case, candidate.job_id)
    assert _fx_state(case) == sources


async def test_candidate_capture_denies_current_acquired_report_rights_before_payload(
    acquired_research_report_case: AcquiredResearchReportCase,
) -> None:
    case = acquired_research_report_case
    before, sources = _report_state(case), _fx_state(case)
    _authority_revision(case, "grant_report")
    with case.report.research.xray.sessions() as session:
        auth = case.report.research.auth(session)
        with _no_private_reads(case), pytest.raises(research_app.ResearchServiceError):
            read_research_xray(
                session,
                auth,
                case.report.research.run_id,
                now=case.report.research.xray.now[0],
                required_copy_use=SourceUse.REPORT,
            )
        # REPORT-only revocation must retain the separately authorized DISPLAY
        # reader rather than disabling all access to the original X-ray.
        displayed = read_research_xray(
            session, auth, case.report.research.run_id, now=case.report.research.xray.now[0]
        )
        finish_research_xray(session, auth, displayed, now=case.report.research.xray.now[0])
        assert displayed.pin.result_digest == case.xray.context.content_digest
    with _no_private_reads(case), pytest.raises(app.ReportServiceError) as denied:
        await generate(case.report, selected=selection(case.report, formats=(r.ReportFormat.JSON,)))
    assert denied.value.code is app.ReportServiceErrorCode.ACCESS_DENIED
    assert _report_state(case) == before and _fx_state(case) == sources


async def test_candidate_capture_rechecks_report_revocation_after_initial_retained_read(
    acquired_research_report_case: AcquiredResearchReportCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = acquired_research_report_case
    before, sources = _report_state(case), _fx_state(case)
    with case.report.research.xray.sessions() as session:
        auth = case.report.research.auth(session)
        basis = read_research_xray(
            session,
            auth,
            case.report.research.run_id,
            now=case.report.research.xray.now[0],
            required_copy_use=SourceUse.REPORT,
        )
        _authority_revision(case, "grant_report", session=session)
        with _no_private_reads(case), pytest.raises(research_app.ResearchServiceError):
            finish_research_xray(
                session,
                auth,
                basis,
                now=case.report.research.xray.now[0],
                required_copy_use=SourceUse.REPORT,
            )
        session.rollback()
    assert _report_state(case) == before and _fx_state(case) == sources

    original: Callable[
        [ResearchReportStore, Session, ReportAuthorization, UUID],
        tuple[ResearchXrayPin, XrayCalculation, UUID, datetime | None],
    ] = ResearchReportStore.retained_xray
    observed: list[UUID] = []
    with ExitStack() as boundary:

        def revoke_after_read(
            store: ResearchReportStore, session: Session, auth: ReportAuthorization, run_id: UUID
        ) -> tuple[ResearchXrayPin, XrayCalculation, UUID, datetime | None]:
            result = original(store, session, auth, run_id)
            grant = _authority_revision(case, "grant_report", session=session)
            assert (
                session.scalar(
                    select(ProviderCapabilityGrantModel.report_allowed).where(
                        ProviderCapabilityGrantModel.id == grant.id
                    )
                )
                is False
            )
            observed.append(grant.id)
            boundary.enter_context(_no_private_reads(case))
            return result

        monkeypatch.setattr(ResearchReportStore, "retained_xray", revoke_after_read)
        with pytest.raises(app.ReportServiceError) as denied:
            await generate(
                case.report, selected=selection(case.report, formats=(r.ReportFormat.JSON,))
            )
        assert denied.value.code in {
            app.ReportServiceErrorCode.ACCESS_DENIED,
            app.ReportServiceErrorCode.REPORT_UNAVAILABLE,
        }
    assert len(observed) == 1
    # The genuine authority successor is transaction-local here. Rejection rolls
    # it back with every report write; the existing A1 test owns concurrent proof.
    with case.report.research.xray.sessions() as session:
        assert session.get(ProviderCapabilityGrantModel, observed[0]) is None
    assert _report_state(case) == before and _fx_state(case) == sources


def _force_fast_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> list[SourceUse]:
    """Simulate only the fast aggregate cap, without constructing a near-32MiB run."""
    observed: list[SourceUse] = []

    def reject(
        session: Session,
        auth: ReportAuthorization,
        run_id: UUID,
        *,
        now: datetime,
        required_copy_use: SourceUse = SourceUse.DISPLAY,
    ) -> ResearchXrayRead:
        observed.append(required_copy_use)
        raise research_app.ResearchServiceError(research_app.ResearchErrorCode.INPUT_BOUND_EXCEEDED)

    monkeypatch.setattr(capture_module, "read_research_xray", reject)
    return observed


async def test_simulated_fast_cap_falls_back_to_identical_legacy_report_bytes(
    acquired_research_report_case: AcquiredResearchReportCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = acquired_research_report_case
    case.report.research.xray.now[0] = max(case.report.research.xray.now[0], datetime.now(UTC))
    assert case.xray.summary.total.value is not None
    assert case.xray.summary.total.value.amount == Decimal("1123.456789123456789")
    selected = selection(case.report, formats=(r.ReportFormat.JSON,))
    sources = _fx_state(case)
    with monkeypatch.context() as legacy:
        legacy.setattr(capture_module, "ResearchReportStore", LegacyResearchReportStore)
        legacy.setattr(capture_module, "_xray_sources", _legacy_xray_sources)
        original = await generate(case.report, selected=selected)
    fast_calls = _force_fast_bound(monkeypatch)
    fallback = await generate(case.report, selected=selected)
    assert original.job_id != fallback.job_id
    assert original.state is fallback.state is r.ReportJobState.QUEUED
    # Full context/manifest and exact ordered chunk bytes/digests/deadlines are
    # compared, not only selected financial fields or an equivalence hash.
    assert _captured(case, original.job_id) == _captured(case, fallback.job_id)
    assert fast_calls == [SourceUse.REPORT]
    assert _fx_state(case) == sources


def test_non_bound_fast_reader_denials_never_fall_back(
    acquired_research_report_case: AcquiredResearchReportCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = acquired_research_report_case

    def forbidden_fallback(
        store: ResearchItemStore, session: Session, auth: ReportAuthorization, run_id: UUID
    ) -> tuple[ResearchXrayPin, XrayCalculation, UUID, datetime | None]:
        raise AssertionError("An unavailable, unauthorized or invalid fast read cannot fall back.")

    monkeypatch.setattr(ResearchItemStore, "retained_xray", forbidden_fallback)
    for code in (
        research_app.ResearchErrorCode.SOURCE_UNAVAILABLE,
        research_app.ResearchErrorCode.ACCESS_DENIED,
        research_app.ResearchErrorCode.NOT_FOUND,
        research_app.ResearchErrorCode.VALIDATION_FAILED,
    ):
        denial = research_app.ResearchServiceError(code)

        def reject(
            session: Session,
            auth: ReportAuthorization,
            run_id: UUID,
            *,
            now: datetime,
            required_copy_use: SourceUse = SourceUse.DISPLAY,
            _denial: research_app.ResearchServiceError = denial,
        ) -> ResearchXrayRead:
            assert required_copy_use is SourceUse.REPORT
            raise _denial

        monkeypatch.setattr(capture_module, "read_research_xray", reject)
        store = ResearchReportStore(
            case.report.research.xray.sessions,
            clock=lambda: case.report.research.xray.now[0],
            cursor_signing_key=XRAY_CURSOR_KEY,
        )
        with case.report.research.xray.sessions() as session:
            auth = case.report.research.auth(session)
            with (
                _no_private_reads(case),
                pytest.raises(research_app.ResearchServiceError) as failed,
            ):
                store.retained_xray(session, auth, case.report.research.run_id)
            assert failed.value is denial


async def test_simulated_fast_cap_fallback_rechecks_real_report_revocation(
    acquired_research_report_case: AcquiredResearchReportCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = acquired_research_report_case
    before, sources = _report_state(case), _fx_state(case)
    fast_calls = _force_fast_bound(monkeypatch)
    original = ResearchReportStore.retained_xray
    observed: list[UUID] = []
    with ExitStack() as boundary:

        def revoke_after_read(
            store: ResearchReportStore, session: Session, auth: ReportAuthorization, run_id: UUID
        ) -> tuple[ResearchXrayPin, XrayCalculation, UUID, datetime | None]:
            result = original(store, session, auth, run_id)
            grant = _authority_revision(case, "grant_report", session=session)
            assert (
                session.scalar(
                    select(ProviderCapabilityGrantModel.report_allowed).where(
                        ProviderCapabilityGrantModel.id == grant.id
                    )
                )
                is False
            )
            observed.append(grant.id)
            boundary.enter_context(_no_private_reads(case))
            return result

        monkeypatch.setattr(ResearchReportStore, "retained_xray", revoke_after_read)
        with pytest.raises(app.ReportServiceError) as denied:
            await generate(
                case.report, selected=selection(case.report, formats=(r.ReportFormat.JSON,))
            )
        assert denied.value.code in {
            app.ReportServiceErrorCode.ACCESS_DENIED,
            app.ReportServiceErrorCode.REPORT_UNAVAILABLE,
        }
    assert fast_calls == [SourceUse.REPORT]
    assert len(observed) == 1
    with case.report.research.xray.sessions() as session:
        assert session.get(ProviderCapabilityGrantModel, observed[0]) is None
    assert _report_state(case) == before and _fx_state(case) == sources
