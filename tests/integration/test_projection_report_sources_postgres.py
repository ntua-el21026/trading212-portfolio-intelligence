"""An actual licensed total-return calibration remains readable after REPORT-only purge."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from functools import partial
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from trading212_application import projection as projections
from trading212_application import reports as app
from trading212_application import source_providers as ports
from trading212_application import sources as sources_app
from trading212_application.projection_views import ProjectionVersionMetadata
from trading212_application.source_ingestion import (
    SourceInstrumentMapping,
    SourceProviderRegistration,
)
from trading212_domain.enums import QualityState
from trading212_domain.projection import ProjectionSourcePin
from trading212_domain.source_details import (
    SourceIdentifier,
    SourceIdentifierKind,
    SourceMappingState,
)
from trading212_domain.sources import (
    LicensePermission,
    MarketSession,
    PriceBasis,
    PriceObservation,
    PriceSnapshot,
    SourceCalendar,
    SourceCoverage,
    SourceLicense,
    SourcePeriod,
    SourceProvenance,
    SourceSeries,
    SourceSeriesKind,
    source_snapshot_digest,
)
from trading212_persistence.premium_models import PremiumRunModel
from trading212_persistence.projection_report_retention import expire_projection_report_payloads
from trading212_persistence.report_models import (
    ArtifactDownloadGrantModel,
    ReportArtifactModel,
    ReportInputChunkModel,
    ReportInputSnapshotModel,
    ReportJobModel,
    ReportManifestModel,
)
from trading212_persistence.source_models import PriceObservationModel, ProviderLicenseVersionModel
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.source_service import PostgresSourceService
from trading212_persistence.source_store import license_view
from trading212_worker.xray_fixture import build_xray_fixture
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.premium_report_v4_artifacts import download_v4, restored_projection_sources
from tests.integration.projection_job_fixture import ProjectionJobCase
from tests.integration.projection_job_fixture import projection_job_case as projection_job_case
from tests.integration.projection_report_runtime import (
    complete_report,
    execute_saved,
    no_private_reads,
    no_resampling,
    report_selection,
    report_service,
    saved_projection,
)
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Calibration:
    service: PostgresSourceService
    license: SourceLicense
    snapshot: PriceSnapshot


async def publish_calibration(case: ProjectionJobCase, *, report: LicensePermission) -> Calibration:
    source = PostgresSourceService(
        sessions=case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now
    )
    provider = str(uuid4())
    key = "projection-report-" + uuid4().hex
    await source.configure_source_provider(
        case.principal,
        SourceProviderRegistration(
            id=provider,
            key=key,
            name="Synthetic report calibration",
            adapter_version="projection-report-test-1",
            configuration_state=sources_app.ProviderConfigurationState.CONFIGURED,
            synthetic=True,
            capabilities=(ports.SourceCapability.PRICE_HISTORY,),
            supported_price_bases=(PriceBasis.TOTAL_RETURN,),
        ),
        idempotency_key=uuid4().hex,
        correlation_id=key,
    )
    license = SourceLicense(
        id=str(uuid4()),
        provider_id=provider,
        version="1",
        effective_at=case.now - timedelta(days=10),
        store=LicensePermission.ALLOWED,
        display=LicensePermission.ALLOWED,
        report=report,
        export=LicensePermission.ALLOWED,
        retention_days=365,
        attribution="Synthetic report calibration",
        evidence_key=key,
    )
    await source.register_source_license(
        case.principal, license, idempotency_key=uuid4().hex, correlation_id=key
    )
    days = tuple(case.now.date() - timedelta(days=offset) for offset in (3, 2, 1))
    closes = tuple(datetime.combine(day, time(17), UTC) for day in days)
    period = SourcePeriod(start=days[0], end=days[-1])
    calendar = SourceCalendar(
        id=key,
        version="1",
        timezone="UTC",
        period=period,
        sessions=tuple(
            MarketSession(session_date=day, close_at=at)
            for day, at in zip(days, closes, strict=True)
        ),
    )
    await source.register_source_calendar(
        case.principal, calendar, idempotency_key=uuid4().hex, correlation_id=key
    )
    listing = next(item for item in build_xray_fixture().listings if item.key == "fund-a")
    assert listing.instrument.isin is not None
    mapping_id = str(uuid4())
    await source.register_source_mapping(
        case.principal,
        SourceInstrumentMapping(
            id=mapping_id,
            provider_id=provider,
            provider_key=key,
            version="1",
            state=SourceMappingState.RESOLVED,
            identifier=SourceIdentifier(
                kind=SourceIdentifierKind.ISIN, value=listing.instrument.isin
            ),
            currency=listing.listing.trading_currency,
            asset_type="etf",
            evidence_key=key,
            valid_from=closes[0] - timedelta(days=1),
            instrument_id=str(listing.instrument.id),
            listing_id=str(listing.listing.id),
        ),
        idempotency_key=uuid4().hex,
        correlation_id=key,
    )
    series = SourceSeries(
        id=str(uuid4()),
        owner_id=case.principal.owner_id,
        provider_id=provider,
        license_version_id=license.id,
        kind=SourceSeriesKind.SECURITY_PRICE,
        provider_key=key,
        mapping_version="1",
        basis=PriceBasis.TOTAL_RETURN,
        currency=listing.listing.trading_currency,
        calendar_id=calendar.id,
        calendar_version=calendar.version,
        mapping_id=mapping_id,
        instrument_id=str(listing.instrument.id),
        listing_id=str(listing.listing.id),
    )
    await source.register_source_series(
        case.principal, series, idempotency_key=uuid4().hex, correlation_id=key
    )
    provenance = SourceProvenance(
        provider_id=provider,
        license_version_id=license.id,
        adapter_version="projection-report-test-1",
        schema_version="1",
        source_revision="1",
        revision_order=1,
        effective_at=closes[-1],
        first_observed_at=case.now,
        synthetic=True,
    )
    snapshot = await source.ingest_price_history(
        case.principal,
        ports.PriceHistoryRequest(series=series, period=period, source_cutoff_at=case.now),
        (
            ports.PriceHistoryPage(
                series=series,
                provenance=provenance,
                period=period,
                coverage=SourceCoverage(
                    expected_count=3, available_count=3, gaps=(), quality=QualityState.FRESH
                ),
                observations=tuple(
                    PriceObservation(session_date=day, effective_at=at, value=Decimal(value))
                    for day, at, value in zip(
                        days, closes, ("100", "101.123456789012345678", "102"), strict=True
                    )
                ),
            ),
        ),
        idempotency_key=uuid4().hex,
        correlation_id=key,
    )
    return Calibration(source, license, snapshot)


async def pin_calibration(case: ProjectionJobCase, calibration: Calibration) -> None:
    await case.service.cancel_run(
        case.principal,
        projections.CancelProjectionRun(
            run_id=case.run.id,
            idempotency_key=uuid4().hex,
            correlation_id="projection-report-source",
        ),
    )
    old = await case.service.get_assumption_version(
        case.principal, case.command.selection.assumption_version_id
    )
    definition = await case.service.create_assumption_set(
        case.principal,
        projections.CreateAssumptionSet(
            account_id=case.command.selection.account_id,
            metadata=ProjectionVersionMetadata(
                name="Explicit calibrated assumption evidence",
                description="Parameters stay owner-modeled; retained evidence is not an i"
                "nferred estimate",
            ),
            content=replace(
                old.content,
                calibration_pins=(
                    ProjectionSourcePin(
                        subject_id=calibration.snapshot.id,
                        content_digest=source_snapshot_digest(calibration.snapshot),
                    ),
                ),
            ),
            idempotency_key=uuid4().hex,
            correlation_id="projection-report-source",
        ),
    )
    case.command = replace(
        case.command,
        idempotency_key=uuid4().hex,
        selection=replace(
            case.command.selection,
            assumption_version_id=definition.current_version_id,
            paths=2,
            months=1,
            retained_months=(0, 1),
        ),
    )
    case.run = await case.service.create_run(case.principal, case.command)


@pytest.mark.parametrize("pinned_denied", [False, True])
async def test_original_and_current_report_license_precede_decode_and_report_only_purge(
    projection_job_case: ProjectionJobCase, pinned_denied: bool
) -> None:
    case = projection_job_case
    calibration = await publish_calibration(
        case, report=LicensePermission.DENIED if pinned_denied else LicensePermission.ALLOWED
    )
    if pinned_denied:
        await calibration.service.register_source_license(
            case.principal,
            replace(
                calibration.license,
                id=str(uuid4()),
                version="2-current-report-allowed",
                effective_at=case.now,
                report=LicensePermission.ALLOWED,
            ),
            idempotency_key=uuid4().hex,
            correlation_id="projection-report-pinned-rights",
        )
    await pin_calibration(case, calibration)
    saved = await execute_saved(case)
    assert len(saved.sources) == 1
    reports = report_service(case)
    account = case.command.selection.account_id
    request = app.GenerateReportCommand(
        selection=report_selection(case), idempotency_key=uuid4().hex, ttl_days=30
    )
    if pinned_denied:
        with no_private_reads(case), pytest.raises(app.ReportServiceError) as denied:
            await reports.generate_report(case.principal, request)
        assert denied.value.code is app.ReportServiceErrorCode.ACCESS_DENIED
        with case.sessions() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ReportJobModel)
                    .where(ReportJobModel.contract_version == 4)
                )
                == 0
            )
        still_readable = await case.service.get_run(
            case.principal, case.run.id, projections.ProjectionPointPageQuery()
        )
        assert still_readable.result_availability == "available"
        assert saved_projection(case) == saved
        return
    with no_resampling():
        queued = await reports.generate_report(case.principal, request)
        status = await complete_report(case, reports, queued)
        report = await download_v4(reports, case.principal, account, status)
    assert restored_projection_sources(report) == saved.sources
    assert report.manifest.document.premium_binding.source_cutoff_at is None
    assert report.manifest.document.premium_binding.source_count == 1
    with case.sessions() as session:
        input_id = session.get_one(ReportJobModel, status.job_id).input_id
        assert (
            license_view(session.get_one(ProviderLicenseVersionModel, UUID(calibration.license.id)))
            == calibration.license
        )
    metadata = status.artifacts[0]
    grant = await reports.create_report_download_grant(
        case.principal, account, status.job_id, metadata.artifact_id
    )
    await calibration.service.register_source_license(
        case.principal,
        replace(
            calibration.license,
            id=str(uuid4()),
            version="2-current-report-denied",
            effective_at=case.now,
            report=LicensePermission.DENIED,
        ),
        idempotency_key=uuid4().hex,
        correlation_id="projection-report-current-rights",
    )
    with no_private_reads(case):
        for operation in (
            partial(reports.get_report_status, case.principal, account, status.job_id),
            partial(reports.get_report_manifest, case.principal, account, status.job_id),
            partial(
                reports.create_report_download_grant,
                case.principal,
                account,
                status.job_id,
                metadata.artifact_id,
            ),
            partial(
                reports.download_report_artifact,
                case.principal,
                account,
                status.job_id,
                metadata.artifact_id,
                grant_token=grant.token,
            ),
            partial(reports.generate_report, case.principal, request),
            partial(
                reports.generate_report,
                case.principal,
                replace(request, idempotency_key=uuid4().hex),
            ),
        ):
            with pytest.raises(app.ReportServiceError) as denied:
                await operation()
            assert denied.value.code is app.ReportServiceErrorCode.ACCESS_DENIED
    with case.sessions() as session:
        assert (
            session.scalar(select(func.projection_report_sources_restricted(case.run.id, case.now)))
            is True
        )
        assert (
            session.scalar(
                select(func.projection_original_sources_restricted(case.run.id, case.now))
            )
            is False
        )
    # A small shared budget must leave explicit pending work and eventually finish.
    outcomes = []
    for _ in range(100):
        budget = SourcePurgeBudget(rows_inspected=80, rows_removed=10, artifacts=1)
        with case.sessions() as session, session.begin():
            outcome = expire_projection_report_payloads(
                session, at=case.now, owner=UUID(case.principal.owner_id), budget=budget
            )
        assert 0 <= budget.rows_inspected <= 80 and 0 <= budget.rows_removed <= 10
        outcomes.append(outcome)
        if outcome:
            break
    else:
        pytest.fail("bounded report-only purge did not complete")
    assert False in outcomes
    with case.sessions() as session, session.begin():
        assert expire_projection_report_payloads(
            session, at=case.now, owner=UUID(case.principal.owner_id), budget=SourcePurgeBudget()
        )
        root = session.get_one(PremiumRunModel, case.run.id)
        assert root.kind == "projection" and root.retained_bytes > 0 and root.expires_at > case.now
        captured = session.get_one(ReportInputSnapshotModel, input_id)
        assert (
            captured.purged_at is not None
            and captured.canonical_manifest is None
            and captured.canonical_context is None
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ReportInputChunkModel)
                .where(
                    ReportInputChunkModel.input_id == input_id,
                    ReportInputChunkModel.payload.is_not(None),
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ReportArtifactModel)
                .where(
                    ReportArtifactModel.job_id == status.job_id,
                    ReportArtifactModel.contents.is_not(None),
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ReportManifestModel)
                .where(
                    ReportManifestModel.job_id == status.job_id,
                    ReportManifestModel.payload.is_not(None),
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactDownloadGrantModel)
                .where(
                    ArtifactDownloadGrantModel.report_artifact_id.in_(
                        tuple(item.artifact_id for item in status.artifacts)
                    )
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(PriceObservationModel)
                .where(PriceObservationModel.snapshot_id == UUID(calibration.snapshot.id))
            )
            == 3
        )
    assert saved_projection(case) == saved
    readable = await case.service.get_run(
        case.principal, case.run.id, projections.ProjectionPointPageQuery()
    )
    assert readable.result_availability == "available" and readable.result is not None
