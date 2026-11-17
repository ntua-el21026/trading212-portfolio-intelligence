"""Complete acquired-FX research copies, current authority and physical closure."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Table, event, func, select, text, update
from sqlalchemy.engine import Connection, ExecutionContext
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from trading212_application import reports as app
from trading212_domain import reports as r
from trading212_domain.report_research import ReportResearchBinding, ReportResearchSelection
from trading212_domain.research_facts import copy_research_portfolio_facts
from trading212_domain.research_serialization import research_record_digest
from trading212_domain.sources import source_snapshot_digest
from trading212_domain.values import CurrencyCode
from trading212_persistence.acquisition_authority import grant_digest
from trading212_persistence.acquisition_models import (
    ProviderAcquisitionAttemptModel,
    ProviderAcquisitionPublicationModel,
    ProviderAcquisitionRequestModel,
    ProviderCapabilityGrantModel,
)
from trading212_persistence.models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    OwnerModel,
    PrincipalModel,
)
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_persistence.report_models import (
    ApplicationCommandIdentityModel,
    ArtifactDownloadGrantModel,
    ReportArtifactModel,
    ReportDispatchOutboxModel,
    ReportInputChunkModel,
    ReportInputDependencyModel,
    ReportInputSnapshotModel,
    ReportJobModel,
    ReportManifestModel,
    ReportRetentionWorkModel,
)
from trading212_persistence.report_research_models import (
    ReportInputResearchDependencyModel,
    ReportInputResearchNoteModel,
    ReportInputResearchSourceModel,
)
from trading212_persistence.report_research_retention import expire_research_report_payloads
from trading212_persistence.source_models import (
    FxObservationModel,
    FxSnapshotModel,
    ProviderLicenseVersionModel,
)
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.xray_run_models import XrayInputDependencyModel
from trading212_security.principals import Scope

from tests.integration.acquired_research_report_case import (
    AcquiredResearchReportCase,
    research_item_for_run,
    select_fx_policy,
)
from tests.integration.acquired_research_report_case import (
    acquired_research_report_case as acquired_research_report_case,
)
from tests.integration.premium_report_v3_artifacts import download_v3
from tests.integration.research_case import research_case as research_case
from tests.integration.research_report_case import complete, generate, selection
from tests.integration.research_report_case import research_report_case as research_report_case
from tests.integration.test_research_report_retention_postgres import _assert_closed
from tests.integration.test_research_reports_postgres import originals
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def _report_state(case: AcquiredResearchReportCase) -> tuple[tuple[tuple[object, ...], ...], ...]:
    models = (
        ApplicationCommandIdentityModel,
        ReportInputSnapshotModel,
        ReportInputChunkModel,
        ReportInputDependencyModel,
        ReportInputResearchDependencyModel,
        ReportInputResearchSourceModel,
        ReportInputResearchNoteModel,
        ReportJobModel,
        ReportDispatchOutboxModel,
        ReportManifestModel,
        ReportArtifactModel,
        ArtifactDownloadGrantModel,
        ReportRetentionWorkModel,
    )
    with case.report.research.xray.sessions() as session:
        return tuple(
            tuple(tuple(row) for row in session.execute(select(table).order_by(*table.primary_key)))
            for table in (cast(Table, model.__table__) for model in models)
        )


def _fx_state(case: AcquiredResearchReportCase) -> tuple[object, ...]:
    with case.report.research.xray.sessions() as session:
        source = session.get_one(FxSnapshotModel, UUID(case.fx.id))
        return (
            source.content_digest,
            source.first_observed_at,
            source.created_at,
            source.expires_at,
            tuple(
                tuple(row)
                for row in session.execute(
                    select(
                        FxObservationModel.id,
                        FxObservationModel.base,
                        FxObservationModel.quote,
                        FxObservationModel.rate,
                        FxObservationModel.effective_at,
                        FxObservationModel.created_at,
                    )
                    .where(FxObservationModel.snapshot_id == source.id)
                    .order_by(FxObservationModel.id)
                )
            ),
        )


@contextmanager
def _no_private_reads(case: AcquiredResearchReportCase) -> Iterator[None]:
    """Observe the actual SELECT boundary; authority functions are not replaced."""
    columns = (
        "xray_input_snapshots.canonical_input",
        "xray_runs.canonical_summary",
        "xray_runs.canonical_exact_state",
        "analytics_runs.canonical_input",
        "analytics_runs.canonical_result",
        "research_source_payloads.canonical_source",
        "research_source_payloads.canonical_facts",
        "research_event_payloads.canonical_event",
        "research_note_payloads.canonical_note",
        "report_input_snapshots.canonical_manifest",
        "report_input_snapshots.canonical_context",
        "report_input_chunks.payload",
        "report_manifests.payload",
        "report_artifacts.contents",
    )

    def before_read(
        _connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: ExecutionContext,
        _executemany: bool,
    ) -> None:
        sql = statement.replace('"', "").lower().lstrip()
        if sql.startswith("select"):
            assert not any(column in sql for column in columns), (
                "Private payload SELECT preceded current acquired-FX REPORT authority"
            )

    engine = case.report.research.xray.engine
    event.listen(engine, "before_cursor_execute", before_read)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", before_read)


def _authority_revision(
    case: AcquiredResearchReportCase,
    restriction: str,
    *,
    session: Session | None = None,
) -> ProviderCapabilityGrantModel:
    """Append real immutable approvals, preserving original source/license/grant pins."""
    at = datetime.now(UTC)
    case.report.research.xray.now[0] = at

    def append(target: Session) -> ProviderCapabilityGrantModel:
        current = target.scalar(
            select(ProviderCapabilityGrantModel)
            .where(ProviderCapabilityGrantModel.scope_id == case.acquisition.grant.scope_id)
            .order_by(ProviderCapabilityGrantModel.version_number.desc())
            .limit(1)
        )
        assert current is not None
        license_id = current.license_version_id
        if restriction.startswith("license_") or restriction == "allowed":
            old = target.get_one(ProviderLicenseVersionModel, license_id)
            version = target.scalar(
                select(func.max(ProviderLicenseVersionModel.version_number)).where(
                    ProviderLicenseVersionModel.provider_id == old.provider_id
                )
            )
            assert version is not None
            license = ProviderLicenseVersionModel(
                id=uuid4(),
                owner_id=old.owner_id,
                provider_id=old.provider_id,
                version_number=version + 1,
                version=f"a1-authority-{uuid4().hex}",
                effective_at=at,
                store_permission="denied" if restriction == "license_store" else "allowed",
                display_permission="denied" if restriction == "license_display" else "allowed",
                report_permission="denied" if restriction == "license_report" else "allowed",
                export_permission="denied",
                retention_days=old.retention_days,
                attribution=old.attribution,
                evidence_key="synthetic-a1-current-authority",
                created_at=at,
            )
            target.add(license)
            target.flush()
            license_id = license.id
        grant = ProviderCapabilityGrantModel(
            id=uuid4(),
            owner_id=current.owner_id,
            provider_id=current.provider_id,
            scope_id=current.scope_id,
            version_number=current.version_number + 1,
            license_version_id=license_id,
            effective_at=at,
            expires_at=current.expires_at,
            store_allowed=restriction != "grant_store",
            display_allowed=restriction != "grant_display",
            report_allowed=restriction != "grant_report",
            export_allowed=False,
            daily_allowance=current.daily_allowance,
            evidence_key="synthetic-a1-current-authority",
            content_digest="0" * 64,
            created_at=at,
        )
        grant.content_digest = grant_digest(grant)
        target.add(grant)
        target.flush()
        target.expunge(grant)
        return grant

    if session is not None:
        return append(session)
    with case.report.research.xray.sessions() as own, own.begin():
        return append(own)


async def test_acquired_fx_complete_chain_preserves_authority_and_four_format_proof(
    acquired_research_report_case: AcquiredResearchReportCase,
) -> None:
    case = acquired_research_report_case
    report = case.report
    before, fx_before = originals(report), _fx_state(case)
    with report.research.xray.sessions() as session, session.begin():
        publication = session.scalar(
            select(ProviderAcquisitionPublicationModel).where(
                ProviderAcquisitionPublicationModel.source_kind == "fx",
                ProviderAcquisitionPublicationModel.source_id == UUID(case.fx.id),
            )
        )
        assert publication is not None
        attempt = session.get_one(ProviderAcquisitionAttemptModel, publication.attempt_id)
        request = session.get_one(ProviderAcquisitionRequestModel, attempt.request_id)
        pinned = session.get_one(ProviderCapabilityGrantModel, request.grant_id)
        license = session.get_one(ProviderLicenseVersionModel, pinned.license_version_id)
        source = session.get_one(FxSnapshotModel, UUID(case.fx.id))
        assert (request.owner_id, request.account_id, pinned.id, request.grant_digest) == (
            UUID(report.research.xray.principal.owner_id),
            report.research.account_id,
            case.acquisition.grant.id,
            case.acquisition.grant.content_digest,
        )
        assert pinned.store_allowed and pinned.display_allowed and pinned.report_allowed
        assert not pinned.export_allowed and license.export_permission == "denied"
        assert (
            license.store_permission
            == license.display_permission
            == license.report_permission
            == "allowed"
        )
        assert (
            source.content_digest == publication.content_digest == source_snapshot_digest(case.fx)
        )
        assert (
            source.first_observed_at
            == publication.first_known_at
            == case.fx.provenance.first_observed_at
        )
        assert source.created_at >= publication.acquired_at
        assert source.expires_at <= min(publication.expires_at, pinned.expires_at)
        pin, xray, input_id, deadline = report.research.service.retained_xray(
            session, report.research.auth(session), report.research.run_id
        )
        expected = copy_research_portfolio_facts(pin, xray, report.research.entity_id)
        assert xray.portfolio_summary.total.value is not None
        assert case.fx.observations[0].rate is not None
        assert xray.portfolio_summary.total.value.amount == case.fx.observations[0].rate * 1000
        assert deadline is not None and deadline <= source.expires_at
    key = uuid4().hex
    pending = await generate(report, key=key)
    # The actual worker lease shares PostgreSQL's UTC clock. Keep the financial
    # observation/cutoff fixture clock unchanged while real rendering takes time.
    finished = await complete(report, pending, worker_clock=lambda: datetime.now(UTC))
    copied = await download_v3(
        report.reports, report.research.xray.principal, report.research.account_id, finished
    )
    binding = copied.manifest.document.premium_binding
    assert isinstance(binding, ReportResearchBinding)
    assert (
        binding.item_id,
        binding.event_revision_id,
        binding.event_revision_digest,
        binding.xray.input_id,
        binding.xray.run_id,
        binding.xray.input_digest,
        binding.xray.result_digest,
    ) == (
        report.item.item_id,
        report.event.revision_id,
        report.event.content_digest,
        input_id,
        pin.run_id,
        pin.input_digest,
        pin.result_digest,
    )
    assert (
        binding.source_cutoff_at == report.item.source_cutoff_at > binding.xray_pin.source_cutoff_at
    )
    assert binding.xray_pin == pin and binding.reporting_currency == CurrencyCode("USD")
    assert finished.expires_at <= binding.expires_at <= deadline
    fx_refs = [
        s for s in copied.manifest.source_references if s.kind is r.ReportSourceKind.FX_SNAPSHOT
    ]
    assert len(fx_refs) == 1 and fx_refs[0].subject_id == UUID(case.fx.id)
    assert fx_refs[0].provider_id == case.acquisition.grant.provider_id
    assert fx_refs[0].license_version_id == case.acquisition.grant.license_version_id
    assert fx_refs[0].content_digest == source_snapshot_digest(case.fx)
    row = copied.rows(r.ReportTableKey.RESEARCH_PORTFOLIO_V1)[0]
    assert row["canonical_facts_digest"].value == research_record_digest(expected)
    assert row["effective_exposure"].value == (
        None if expected.effective_exposure is None else expected.effective_exposure.amount
    )
    assert row["quality"].value == expected.quality.value
    assert {a.format for a in finished.artifacts} == set(r.ReportFormat)
    state = _report_state(case)
    repeated = await generate(report, key=key)
    assert repeated.job_id == finished.job_id and repeated.context == finished.context
    assert (
        _report_state(case) == state
        and originals(report) == before
        and _fx_state(case) == fx_before
    )


@pytest.mark.parametrize(
    "restriction",
    [
        "grant_report",
        "license_report",
        "grant_store",
        "license_store",
        "grant_display",
        "license_display",
    ],
)
async def test_acquired_fx_current_restriction_precedes_every_private_report_boundary(
    acquired_research_report_case: AcquiredResearchReportCase,
    restriction: str,
) -> None:
    case = acquired_research_report_case
    report = case.report
    selected = selection(report, formats=(r.ReportFormat.JSON,))
    key = uuid4().hex
    finished = await complete(report, await generate(report, selected=selected, key=key))
    artifact = finished.artifacts[0]
    token = await report.reports.create_report_download_grant(
        report.research.xray.principal,
        report.research.account_id,
        finished.job_id,
        artifact.artifact_id,
    )
    _authority_revision(case, restriction)
    state, fx_before, originals_before = _report_state(case), _fx_state(case), originals(report)
    operations = (
        lambda: generate(report, selected=selected),
        lambda: generate(report, selected=selected, key=key),
        lambda: report.reports.get_report_manifest(
            report.research.xray.principal, report.research.account_id, finished.job_id
        ),
        lambda: report.reports.create_report_download_grant(
            report.research.xray.principal,
            report.research.account_id,
            finished.job_id,
            artifact.artifact_id,
        ),
        lambda: report.reports.download_report_artifact(
            report.research.xray.principal,
            report.research.account_id,
            finished.job_id,
            artifact.artifact_id,
            grant_token=token.token,
        ),
    )
    for operation in operations:
        with _no_private_reads(case), pytest.raises(app.ReportServiceError):
            await operation()
    assert (
        _report_state(case) == state
        and _fx_state(case) == fx_before
        and originals(report) == originals_before
    )


@pytest.mark.parametrize(
    "acquired_research_report_case", ["pinned_grant", "pinned_license"], indirect=True
)
async def test_acquired_fx_current_approval_cannot_expand_original_report_rights(
    acquired_research_report_case: AcquiredResearchReportCase,
) -> None:
    case = acquired_research_report_case
    original = case.acquisition.grant
    current = _authority_revision(case, "allowed")
    assert current.report_allowed and current.id != original.id
    state = _report_state(case)
    with _no_private_reads(case), pytest.raises(app.ReportServiceError):
        await generate(case.report, selected=selection(case.report, formats=(r.ReportFormat.JSON,)))
    assert _report_state(case) == state


@pytest.mark.parametrize("restriction", ["grant_report", "license_report"])
async def test_acquired_fx_report_only_cleanup_drains_artifacts_and_preserves_display_sources(
    acquired_research_report_case: AcquiredResearchReportCase,
    restriction: str,
) -> None:
    case = acquired_research_report_case
    report = case.report
    finished = await complete(report, await generate(report))
    with report.research.xray.sessions() as session:
        input_id = session.get_one(ReportJobModel, finished.job_id).input_id
        members = set(
            session.scalars(
                select(ReportInputDependencyModel.id).where(
                    ReportInputDependencyModel.input_id == input_id,
                    ReportInputDependencyModel.fx_snapshot_id == UUID(case.fx.id),
                )
            )
        )
    assert members
    before, fx_before = originals(report), _fx_state(case)
    _authority_revision(case, restriction)
    with report.research.xray.sessions() as session, session.begin():
        pin, value, _, _ = report.research.service.retained_xray(
            session, report.research.auth(session), report.research.run_id
        )
        assert pin == report.item.portfolio.pin and value.content_digest == pin.result_digest
    for _ in range(16):
        with report.research.xray.sessions() as session, session.begin():
            budget = SourcePurgeBudget()
            expire_research_report_payloads(session, at=report.research.xray.now[0], budget=budget)
            assert 0 <= budget.rows_inspected <= 4096 and 0 <= budget.rows_removed <= 4096
            assert (
                0 <= budget.bytes_inspected <= 67_108_864
                and 0 <= budget.bytes_removed <= 67_108_864
            )
            work = session.scalar(
                select(ReportRetentionWorkModel).where(
                    ReportRetentionWorkModel.input_id == input_id
                )
            )
            done = work is not None and work.completed_at is not None
            if work is not None:
                assert work.legacy_source_kind == "physical" and work.legacy_source_id in members
        if done:
            break
    else:
        pytest.fail("Bounded acquired-FX report cleanup did not finish.")
    _assert_closed(report, input_id)
    assert originals(report) == before and _fx_state(case) == fx_before


@pytest.mark.parametrize(
    "mismatch",
    ["foreign_owner", "foreign_account", "missing_item", "snapshot", "cutoff", "currency"],
)
async def test_acquired_fx_exact_selection_mismatches_never_admit_a_report(
    acquired_research_report_case: AcquiredResearchReportCase,
    mismatch: str,
) -> None:
    case, report = acquired_research_report_case, acquired_research_report_case.report
    chosen = selection(report, formats=(r.ReportFormat.JSON,))
    principal = report.research.xray.principal
    if mismatch == "foreign_owner":
        at, owner, actor = report.research.xray.now[0], uuid4(), uuid4()
        subject = f"a1-foreign-{actor}"
        with report.research.xray.sessions() as session, session.begin():
            session.add(OwnerModel(id=owner, display_name="Synthetic foreign A1 owner"))
            session.flush()
            session.add(
                PrincipalModel(
                    id=actor,
                    owner_id=owner,
                    issuer=principal.issuer,
                    subject=subject,
                    status="active",
                    created_at=at,
                    last_authenticated_at=at,
                )
            )
            session.flush()
            provision_principal_scopes(session, principal_id=actor, scopes=frozenset(Scope), now=at)
        principal = replace(
            principal, principal_id=str(actor), owner_id=str(owner), subject=subject
        )
    elif mismatch == "foreign_account":
        with report.research.xray.sessions() as session:
            other = session.scalar(
                select(BrokerAccountModel.id)
                .join(
                    BrokerConnectionModel,
                    BrokerConnectionModel.id == BrokerAccountModel.connection_id,
                )
                .where(
                    BrokerConnectionModel.owner_id == UUID(principal.owner_id),
                    BrokerAccountModel.id != report.research.account_id,
                )
                .limit(1)
            )
            assert other is not None
        chosen = replace(chosen, account_id=other)
    elif mismatch == "missing_item":
        pin = chosen.premium_run
        assert isinstance(pin, ReportResearchSelection)
        chosen = replace(chosen, premium_run=replace(pin, item_id=uuid4()))
    elif mismatch == "snapshot":
        chosen = replace(chosen, snapshot_id=uuid4())
    elif mismatch == "cutoff":
        chosen = replace(
            chosen, source_cutoff_at=chosen.source_cutoff_at - timedelta(microseconds=1)
        )
    else:
        chosen = replace(chosen, reporting_currency=CurrencyCode("EUR"))
    state = _report_state(case)
    command = app.GenerateReportCommand(selection=chosen, ttl_days=30, idempotency_key=uuid4().hex)
    if mismatch in {"foreign_owner", "foreign_account", "missing_item"}:
        with _no_private_reads(case), pytest.raises(app.ReportServiceError):
            await report.reports.generate_report(principal, command)
    else:
        with pytest.raises(app.ReportServiceError):
            await report.reports.generate_report(principal, command)
    assert _report_state(case) == state


@pytest.mark.parametrize(
    "changed",
    [
        "source",
        "source_digest",
        "source_clock",
        "source_owner",
        "grant_digest",
        "grant_license",
        "dependency",
    ],
)
async def test_acquired_fx_lineage_substitution_is_rejected_by_actual_storage_guards(
    acquired_research_report_case: AcquiredResearchReportCase,
    changed: str,
) -> None:
    case, report = acquired_research_report_case, acquired_research_report_case.report
    pending = await generate(report, selected=selection(report, formats=(r.ReportFormat.JSON,)))
    state, fx_before = _report_state(case), _fx_state(case)
    with report.research.xray.sessions() as session, session.begin():
        if changed in {"source", "source_digest", "source_clock", "source_owner"}:
            source_changes: dict[str, dict[str, object]] = {
                "source": {"provider_id": uuid4()},
                "source_digest": {"content_digest": "f" * 64},
                "source_clock": {"first_observed_at": report.research.xray.now[0]},
                "source_owner": {"owner_id": uuid4()},
            }
            values = source_changes[changed]
            statement = (
                update(FxSnapshotModel)
                .where(FxSnapshotModel.id == UUID(case.fx.id))
                .values(**values)
            )
        elif changed in {"grant_digest", "grant_license"}:
            values = (
                {"content_digest": "f" * 64}
                if changed == "grant_digest"
                else {"license_version_id": report.research.license.id}
            )
            statement = (
                update(ProviderCapabilityGrantModel)
                .where(ProviderCapabilityGrantModel.id == case.acquisition.grant.id)
                .values(**values)
            )
        else:
            input_id = session.get_one(ReportJobModel, pending.job_id).input_id
            statement = (
                update(ReportInputDependencyModel)
                .where(
                    ReportInputDependencyModel.input_id == input_id,
                    ReportInputDependencyModel.fx_snapshot_id == UUID(case.fx.id),
                )
                .values(source_id=uuid4())
            )
        with pytest.raises(IntegrityError), session.begin_nested():
            session.execute(statement)
    assert _report_state(case) == state and _fx_state(case) == fx_before


async def test_missing_fx_stays_explicitly_unavailable_in_the_complete_research_copy(
    acquired_research_report_case: AcquiredResearchReportCase,
) -> None:
    case = acquired_research_report_case
    degraded = await select_fx_policy(
        case.report.research.xray, case.xray, case.catalogue_provider_ids
    )
    assert degraded.summary.total.value is None
    report = await research_item_for_run(case.report, case.report.research.xray, degraded)
    with report.research.xray.sessions() as session, session.begin():
        pin, value, _, _ = report.research.service.retained_xray(
            session, report.research.auth(session), report.research.run_id
        )
        expected = copy_research_portfolio_facts(pin, value, report.research.entity_id)
        assert expected.effective_exposure is None and expected.reason is not None
        assert (
            session.scalar(
                select(XrayInputDependencyModel.id)
                .where(
                    XrayInputDependencyModel.input_id == UUID(degraded.context.input_snapshot_id),
                    XrayInputDependencyModel.fx_snapshot_id.is_not(None),
                )
                .limit(1)
            )
            is None
        )
    copied = await download_v3(
        report.reports,
        report.research.xray.principal,
        report.research.account_id,
        await complete(report, await generate(report)),
    )
    row = copied.rows(r.ReportTableKey.RESEARCH_PORTFOLIO_V1)[0]
    assert (
        row["effective_exposure"].value is None
        and row["effective_exposure"].state is r.CellState.UNAVAILABLE
    )
    assert row["canonical_facts_digest"].value == research_record_digest(expected)
    assert row["reason"].value == expected.reason.value
    assert row["quality"].value == expected.quality.value


async def test_original_acquired_fx_expiry_denies_private_reads_and_does_not_renew_retry(
    acquired_research_report_case: AcquiredResearchReportCase,
) -> None:
    case, report = acquired_research_report_case, acquired_research_report_case.report
    selected, key = selection(report, formats=(r.ReportFormat.JSON,)), uuid4().hex
    finished = await complete(report, await generate(report, selected=selected, key=key))
    with report.research.xray.sessions() as session:
        source = session.get_one(FxSnapshotModel, UUID(case.fx.id))
        expiry = source.expires_at
    assert finished.expires_at <= expiry
    before, fx_before = _report_state(case), _fx_state(case)
    report.research.xray.now[0] = expiry
    with _no_private_reads(case), pytest.raises(app.ReportServiceError):
        await report.reports.get_report_manifest(
            report.research.xray.principal, report.research.account_id, finished.job_id
        )
    with _no_private_reads(case), pytest.raises(app.ReportServiceError):
        await generate(report, selected=selected)
    with _no_private_reads(case):
        repeated = await generate(report, selected=selected, key=key)
    assert repeated.job_id == finished.job_id and repeated.state is r.ReportJobState.EXPIRED
    assert repeated.context is None and repeated.expires_at == finished.expires_at
    assert _report_state(case) == before and _fx_state(case) == fx_before


async def test_concurrent_fx_revocation_commits_before_waiting_capture_and_semantic_retry(
    acquired_research_report_case: AcquiredResearchReportCase,
) -> None:
    case, report = acquired_research_report_case, acquired_research_report_case.report
    writer_ready, reporter_waiting, release_writer = Event(), Event(), Event()
    key = uuid4().hex
    before = _report_state(case)

    def revoke() -> None:
        with report.research.xray.sessions() as session, session.begin():
            connection = session.connection()
            connection.info["a1_grant_writer"] = True
            try:
                session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                    {"key": f"sources:{report.research.xray.principal.owner_id}"},
                )
                _authority_revision(case, "grant_report", session=session)
                writer_ready.set()
                assert release_writer.wait(10), (
                    "Waiting report never reached its source-owner lock."
                )
            finally:
                connection.info.pop("a1_grant_writer", None)

    def observe(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: ExecutionContext,
        _executemany: bool,
    ) -> None:
        if "pg_advisory_xact_lock(hashtextextended" in statement and not connection.info.get(
            "a1_grant_writer"
        ):
            reporter_waiting.set()

    writer = asyncio.create_task(asyncio.to_thread(revoke))
    reporter: asyncio.Task[app.ReportJobStatus] | None = None
    event.listen(report.research.xray.engine, "before_cursor_execute", observe)
    try:
        assert await asyncio.to_thread(writer_ready.wait, 10)
        with _no_private_reads(case):
            reporter = asyncio.create_task(
                generate(
                    report, selected=selection(report, formats=(r.ReportFormat.JSON,)), key=key
                )
            )
            assert await asyncio.to_thread(reporter_waiting.wait, 10)
            assert not reporter.done()
            release_writer.set()
            await asyncio.wait_for(writer, 10)
            with pytest.raises(app.ReportServiceError):
                await asyncio.wait_for(reporter, 10)
            with pytest.raises(app.ReportServiceError):
                await generate(
                    report, selected=selection(report, formats=(r.ReportFormat.JSON,)), key=key
                )
    finally:
        release_writer.set()
        event.remove(report.research.xray.engine, "before_cursor_execute", observe)
        await asyncio.wait_for(writer, 10)
        if reporter is not None:
            if not reporter.done():
                reporter.cancel()
            await asyncio.gather(reporter, return_exceptions=True)
    assert _report_state(case) == before
