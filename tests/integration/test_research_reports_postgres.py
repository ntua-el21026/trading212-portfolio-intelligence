"""Complete actual report copies preserve exact selections and original evidence."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import select
from trading212_api_contracts.premium_reports_v3 import PremiumReportManifestV3
from trading212_application import reports as app
from trading212_domain import reports as r
from trading212_domain.report_manifest import encode_report_manifest
from trading212_domain.report_research import ReportResearchBinding, ReportResearchSelection
from trading212_domain.report_research_schema import RESEARCH_PROOF_TABLES, RESEARCH_REPORT_TABLES
from trading212_domain.research_facts import copy_research_portfolio_facts
from trading212_domain.research_serialization import research_record_digest
from trading212_domain.research_sources import ResearchNewsFacts
from trading212_persistence.research_models import (
    ResearchEventPayloadModel,
    ResearchNotePayloadModel,
    ResearchSourcePayloadModel,
)
from trading212_persistence.xray_run_models import XrayInputSnapshotModel, XrayRunModel

from tests.integration.premium_report_v3_artifacts import download_v3
from tests.integration.research_case import research_case as research_case
from tests.integration.research_report_case import ResearchReportCase, complete, generate, selection
from tests.integration.research_report_case import research_report_case as research_report_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def originals(case: ResearchReportCase) -> tuple[object, ...]:
    """Bounded actual canonical source/event/owner-note/X-ray originals, before copying."""
    with case.research.xray.sessions() as session:
        return tuple(
            tuple(tuple(row) for row in session.execute(query))
            for query in (
                select(
                    ResearchSourcePayloadModel.canonical_source,
                    ResearchSourcePayloadModel.canonical_facts,
                ).order_by(ResearchSourcePayloadModel.id),
                select(ResearchEventPayloadModel.canonical_event).order_by(
                    ResearchEventPayloadModel.id
                ),
                select(ResearchNotePayloadModel.canonical_note).order_by(
                    ResearchNotePayloadModel.id
                ),
                select(XrayInputSnapshotModel.canonical_input).order_by(XrayInputSnapshotModel.id),
                select(
                    XrayRunModel.canonical_summary,
                    XrayRunModel.canonical_reconciliation,
                    XrayRunModel.canonical_exact_state,
                ).order_by(XrayRunModel.id),
            )
        )


async def test_exact_research_four_formats_preserve_original_sources_and_historical_revisions(
    research_report_case: ResearchReportCase,
) -> None:
    case = research_report_case
    assert case.research.license.report_permission == "allowed"
    assert case.research.license.export_permission == "denied"
    assert case.grant.report_allowed is True and case.grant.export_allowed is False
    before = originals(case)
    with case.research.xray.sessions() as session, session.begin():
        pin, xray, _, _ = case.research.service.retained_xray(
            session, case.research.auth(session), case.research.run_id
        )
        expected = copy_research_portfolio_facts(pin, xray, case.research.entity_id)
    pending = await generate(case)
    completed = await complete(case, pending)
    copied = await download_v3(
        case.reports, case.research.xray.principal, case.research.account_id, completed
    )
    binding = copied.manifest.document.premium_binding
    transport = PremiumReportManifestV3.model_validate_json(encode_report_manifest(copied.manifest))
    assert transport.document.premium_binding.family == "research"
    assert transport.document.premium_binding.item_id == str(case.item.item_id)
    assert transport.document.premium_binding.source_cutoff_at == case.item.source_cutoff_at
    assert isinstance(binding, ReportResearchBinding)
    assert binding.item_id == case.item.item_id
    assert binding.event_revision_id == case.event.revision_id
    assert binding.event_revision_digest == case.event.content_digest
    assert binding.xray_pin == expected.pin
    assert binding.source_cutoff_at == case.item.source_cutoff_at
    assert binding.xray_pin.source_cutoff_at != binding.source_cutoff_at
    assert len(binding.note_revisions) == 1
    assert binding.note_revisions[0].revision_id == case.note.revision_id
    assert binding.note_revisions[0].content_digest == case.note.content_digest
    assert binding.review_acknowledgment == case.review
    assert not hasattr(binding, "run_id")
    assert set((*RESEARCH_REPORT_TABLES, *RESEARCH_PROOF_TABLES)) <= set(copied.tables)
    event = copied.rows(r.ReportTableKey.RESEARCH_EVENT_V1)[0]
    assert event["content_type"].value == "source_facts"
    assert event["content_digest"].value == case.event.content_digest
    assert event["published_at"].value == case.event.facts.published_at
    assert isinstance(case.event.facts, ResearchNewsFacts)
    assert event["summary"].value == case.event.facts.summary
    notes = copied.rows(r.ReportTableKey.RESEARCH_NOTES_V1)
    assert len(notes) == 1 and notes[0]["content_type"].value == "owner_revision"
    assert notes[0]["thesis"].value == case.note.content.thesis
    assert notes[0]["note"].value == case.note.content.note
    assert notes[0]["thesis"].value != case.newer_note.content.thesis
    assert notes[0]["created_at"].value == case.note.created_at
    portfolio = copied.rows(r.ReportTableKey.RESEARCH_PORTFOLIO_V1)[0]
    assert portfolio["canonical_facts_digest"].value == research_record_digest(expected)
    metric = portfolio["effective_exposure"]
    assert metric.value == (
        None if expected.effective_exposure is None else expected.effective_exposure.amount
    )
    assert metric.currency == expected.pin.reporting_currency
    context = next(item for item in copied.manifest.contexts if item.key == metric.context_key)
    assert (metric.quality or context.quality) == expected.quality
    assert metric.confidence == expected.confidence
    assert metric.origin is not None and metric.origin.value == expected.origin.value
    assert portfolio["availability"].value == expected.availability.value
    assert portfolio["bound"].value == expected.bound.value
    assert len(copied.rows(r.ReportTableKey.RESEARCH_WARNINGS_V1)) == len(expected.warnings)
    members = copied.rows(r.ReportTableKey.RESEARCH_PORTFOLIO_MEMBERS_V1)
    for field in ("source_reference_ids", "metric_source_reference_ids", "path_keys"):
        actual = tuple(
            row["member_id"].value
            for row in members
            if row["owner_kind"].value == "portfolio" and row["field"].value == field
        )
        assert actual == tuple(str(value) for value in getattr(expected, field))
    assert any(note.code == "optional_synthesis_disabled" for note in copied.manifest.notes)
    assert originals(case) == before
    assert (
        completed.expires_at
        <= binding.expires_at
        <= case.item.source.citations[0].source.expires_at
    )


async def test_empty_explicit_selection_and_semantic_retries_never_resolve_current_heads(
    research_report_case: ResearchReportCase,
) -> None:
    case = research_report_case
    chosen = selection(case, notes=(), review=False)
    key = uuid4().hex
    first = await generate(case, selected=chosen, key=key)
    repeated = await generate(case, selected=chosen, key=key)
    assert repeated.job_id == first.job_id and repeated.context == first.context
    with pytest.raises(app.ReportServiceError) as conflict:
        await generate(case, selected=selection(case), key=key)
    assert conflict.value.code is app.ReportServiceErrorCode.CONFLICT
    copied = await download_v3(
        case.reports,
        case.research.xray.principal,
        case.research.account_id,
        await complete(case, first),
    )
    binding = copied.manifest.document.premium_binding
    assert isinstance(binding, ReportResearchBinding)
    assert binding.note_revisions == () and binding.review_acknowledgment is None
    assert copied.tables[r.ReportTableKey.RESEARCH_NOTES_V1] == ()
    assert copied.tables[r.ReportTableKey.RESEARCH_REVIEW_V1] == ()
    basis = copied.rows(r.ReportTableKey.RESEARCH_BASIS_V1)[0]
    assert basis["selected_note_count"].value == 0 and basis["review_selected"].value is False


@pytest.mark.parametrize("changed", ["item", "note", "review", "snapshot", "currency"])
async def test_invalid_exact_research_pins_never_admit_a_report(
    research_report_case: ResearchReportCase,
    changed: str,
) -> None:
    case = research_report_case
    chosen = selection(case)
    pin = chosen.premium_run
    assert isinstance(pin, ReportResearchSelection)
    if changed == "item":
        chosen = replace(chosen, premium_run=replace(pin, item_id=uuid4()))
    elif changed == "note":
        chosen = replace(chosen, premium_run=replace(pin, note_revision_ids=(uuid4(),)))
    elif changed == "review":
        chosen = replace(chosen, premium_run=replace(pin, review_acknowledgment_id=uuid4()))
    elif changed == "snapshot":
        chosen = replace(chosen, snapshot_id=uuid4())
    else:
        from trading212_domain.values import CurrencyCode

        chosen = replace(chosen, reporting_currency=CurrencyCode("USD"))
    before = originals(case)
    with pytest.raises(app.ReportServiceError):
        await generate(case, selected=chosen)
    assert originals(case) == before
