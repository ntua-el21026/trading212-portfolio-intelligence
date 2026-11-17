"""Actual normalized research grant, immutable revisions and existing four-format jobs."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from trading212_application import report_jobs
from trading212_application import reports as app
from trading212_application import research as research_app
from trading212_domain import reports as r
from trading212_domain.report_research import ReportResearchSelection
from trading212_domain.report_v3 import ReportSelectionV3
from trading212_domain.research_notes import (
    ResearchNoteContent,
    ResearchNoteRevision,
    ResearchReviewAcknowledgment,
)
from trading212_domain.research_sources import ResearchCitationPin, ResearchEventRevision
from trading212_persistence.acquisition_authority import grant_digest
from trading212_persistence.acquisition_models import (
    ProviderCapabilityGrantModel,
    ProviderCapabilityScopeModel,
)
from trading212_persistence.acquisition_research_authority import (
    PostgresResearchCapabilityAuthority,
)
from trading212_persistence.report_job_store import PostgresReportJobStore
from trading212_persistence.report_models import ReportJobModel
from trading212_persistence.report_service import PostgresReportService
from trading212_persistence.research_service import PostgresResearchService
from trading212_persistence.source_models import (
    MarketDataProviderModel,
    ProviderLicenseVersionModel,
)
from trading212_worker.report_tasks import ReportExecutionState, execute_report_message
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.report_runtime_sources import fresh_report_xray
from tests.integration.research_case import ResearchCase
from tests.integration.research_case import research_case as research_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case


@dataclass
class ResearchReportCase:
    research: ResearchCase
    reports: PostgresReportService
    item: research_app.ResearchItemView
    event: ResearchEventRevision
    note: ResearchNoteRevision
    newer_note: ResearchNoteRevision
    review: ResearchReviewAcknowledgment
    grant: ProviderCapabilityGrantModel


@pytest.fixture
async def research_report_case(research_case: ResearchCase) -> ResearchReportCase:
    case = research_case
    fresh = await fresh_report_xray(case.xray)
    case.run_id = UUID(fresh.context.run_id)
    # Event visibility is a separate later observation, not the financial cutoff.
    case.xray.now[0] += timedelta(microseconds=1)
    at, owner = case.xray.now[0], UUID(case.xray.principal.owner_id)
    with case.xray.sessions() as session, session.begin():
        provider = MarketDataProviderModel(
            id=uuid4(),
            owner_id=owner,
            key="alpha_vantage",
            name="Synthetic report entitlement fixture",
            adapter_version="research-fixture-1",
            configuration_state="configured",
            synthetic=True,
            revision=1,
            capabilities=[],
            supported_price_bases=[],
            freshness_policy_version=None,
            max_age_seconds=None,
            created_at=at,
            updated_at=at,
        )
        session.add(provider)
        session.flush()
        report_license = ProviderLicenseVersionModel(
            id=uuid4(),
            owner_id=owner,
            provider_id=provider.id,
            version_number=1,
            version="report-only-1",
            effective_at=at - timedelta(hours=12),
            store_permission="allowed",
            display_permission="allowed",
            report_permission="allowed",
            export_permission="denied",
            retention_days=30,
            attribution="Synthetic research report fixture",
            evidence_key="synthetic-report-only-license",
            created_at=at,
        )
        session.add(report_license)
        session.flush()
        session.expunge(report_license)
        case.license = report_license
        scope = ProviderCapabilityScopeModel(
            id=uuid4(),
            owner_id=owner,
            provider_id=provider.id,
            capability="news_sentiment",
            subject_kind="entity",
            subject_id=case.entity_id,
            created_at=at,
        )
        session.add(scope)
        session.flush()
        grant = ProviderCapabilityGrantModel(
            id=uuid4(),
            owner_id=owner,
            provider_id=provider.id,
            scope_id=scope.id,
            version_number=1,
            license_version_id=case.license.id,
            effective_at=at - timedelta(hours=6),
            expires_at=at + timedelta(days=30),
            store_allowed=True,
            display_allowed=True,
            report_allowed=True,
            export_allowed=False,
            daily_allowance=25,
            evidence_key="synthetic-report-approval",
            content_digest="0" * 64,
            created_at=at,
        )
        grant.content_digest = grant_digest(grant)
        session.add(grant)
        session.flush()
        session.expunge(grant)
    case.service = PostgresResearchService(
        case.xray.sessions,
        cursor_signing_key=XRAY_CURSOR_KEY,
        clock=lambda: case.xray.now[0],
        capability_authority=PostgresResearchCapabilityAuthority(),
    )
    event = case.publish(
        case.incoming(
            "explicit-report", summary="Synthetic facts remain distinct from the owner's thesis."
        )
    )
    item = (await case.service.get_research_summary(case.xray.principal, case.query())).items[0]
    note = await case.service.create_research_note(
        case.xray.principal,
        research_app.CreateResearchNote(
            account_id=case.account_id,
            entity_id=case.entity_id,
            content=ResearchNoteContent(
                title="Selected owner thesis",
                note="=1+1\n<script>synthetic inert text</script>",
                thesis="Exact historical owner revision.",
                risks="Independent owner risk assessment.",
                citations=(ResearchCitationPin.from_citation(event.citations[0]),),
            ),
            idempotency_key=uuid4().hex,
            correlation_id="research-report-note",
        ),
    )
    newer = await case.service.create_research_note_version(
        case.xray.principal,
        research_app.CreateResearchNoteVersion(
            note_id=note.note_id,
            expected_revision=note.revision,
            content=replace(
                note.content, thesis="Later current head must never replace the exact selection."
            ),
            idempotency_key=uuid4().hex,
            correlation_id="research-report-note-newer",
        ),
    )
    review = await case.service.review_research_event(
        case.xray.principal,
        research_app.ReviewResearchEvent(
            event_id=event.event_id,
            revision_id=event.revision_id,
            revision_digest=event.content_digest,
            idempotency_key=uuid4().hex,
            correlation_id="research-report-review",
        ),
    )
    reports = PostgresReportService(
        case.xray.sessions,
        cursor_signing_key=XRAY_CURSOR_KEY,
        clock=lambda: case.xray.now[0],
        contract_version=3,
    )
    return ResearchReportCase(case, reports, item, event, note, newer, review, grant)


def selection(
    case: ResearchReportCase,
    *,
    notes: tuple[UUID, ...] | None = None,
    review: bool = True,
    formats: tuple[r.ReportFormat, ...] = tuple(r.ReportFormat),
) -> ReportSelectionV3:
    pin = case.item.portfolio.pin
    return ReportSelectionV3(
        account_id=case.research.account_id,
        snapshot_id=pin.snapshot_id,
        reporting_currency=pin.reporting_currency,
        source_cutoff_at=case.item.source_cutoff_at,
        start_date=pin.valuation_at.date(),
        end_date=pin.valuation_at.date(),
        report_type=r.ReportType.PORTFOLIO_SUMMARY,
        sections=(
            r.ReportSection.OVERVIEW,
            r.ReportSection.ALLOCATION,
            r.ReportSection.QUALITY,
            r.ReportSection.RESEARCH,
        ),
        formats=formats,
        premium_run=ReportResearchSelection(
            item_id=case.item.item_id,
            note_revision_ids=(case.note.revision_id,) if notes is None else notes,
            review_acknowledgment_id=case.review.acknowledgment_id if review else None,
        ),
    )


async def generate(
    case: ResearchReportCase, *, selected: ReportSelectionV3 | None = None, key: str | None = None
) -> app.ReportJobStatus:
    return await case.reports.generate_report(
        case.research.xray.principal,
        app.GenerateReportCommand(
            selection=selection(case) if selected is None else selected,
            ttl_days=30,
            idempotency_key=uuid4().hex if key is None else key,
        ),
    )


def message(case: ResearchReportCase, status: app.ReportJobStatus) -> report_jobs.ReportTaskMessage:
    with case.research.xray.sessions() as session:
        row = session.get_one(ReportJobModel, status.job_id)
        return report_jobs.ReportTaskMessage(
            job_id=row.id,
            owner_id=row.owner_id,
            account_id=row.account_id,
            capture_id=row.input_id,
            input_digest=row.input_digest,
        )


async def complete(
    case: ResearchReportCase,
    pending: app.ReportJobStatus,
    *,
    worker_clock: Callable[[], datetime] | None = None,
) -> app.ReportJobStatus:
    """Preserve logical fixture time unless a real-time worker is explicitly selected."""
    state = await execute_report_message(
        PostgresReportJobStore(
            case.research.xray.sessions,
            clock=(lambda: case.research.xray.now[0]) if worker_clock is None else worker_clock,
        ),
        message(case, pending),
        consumer_id="research-report-test",
    )
    result = await case.reports.get_report_status(
        case.research.xray.principal, case.research.account_id, pending.job_id
    )
    assert state is ReportExecutionState.COMPLETED, result.failure_code
    assert result.state is r.ReportJobState.SUCCEEDED
    return result
