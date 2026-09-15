"""Frozen research command identities, bounded page envelopes and separate scopes."""

from dataclasses import replace
from datetime import timedelta

import pytest
from trading212_application import research as app
from trading212_domain.errors import DomainError
from trading212_domain.research import ResearchEventKind, ResearchReviewState
from trading212_domain.research_notes import ResearchNoteContent
from trading212_security.principals import Scope

from tests.unit.domain.research_factories import AT, event, note, pin, portfolio, uid

pytestmark = pytest.mark.unit


def test_create_replay_digest_binds_account_content_and_exact_note_version() -> None:
    content = ResearchNoteContent(title="Owner title", thesis="Owner premise")
    command = app.CreateResearchNote(
        account_id=uid(2),
        entity_id=uid(3),
        content=content,
        idempotency_key="research-create",
        correlation_id="request-one",
    )
    digest = app.research_command_digest(command, uid(2))
    assert (
        app.research_command_digest(
            replace(command, idempotency_key="retry", correlation_id="request-two"), uid(2)
        )
        == digest
    )
    assert (
        app.research_command_digest(
            replace(command, content=replace(content, thesis="Changed premise")), uid(2)
        )
        != digest
    )
    with pytest.raises(DomainError):
        app.research_command_digest(command, uid(4))
    version = app.CreateResearchNoteVersion(
        note_id=uid(70),
        expected_revision=1,
        content=content,
        idempotency_key="version-create",
        correlation_id="request",
    )
    assert app.research_command_digest(version, uid(2)) != app.research_command_digest(
        replace(version, expected_revision=2), uid(2)
    )
    assert app.research_command_digest(version, uid(2)) != app.research_command_digest(
        version, uid(4)
    )
    review = app.ReviewResearchEvent(
        event_id=uid(30001),
        revision_id=uid(40001),
        revision_digest="c" * 64,
        idempotency_key="review",
        correlation_id="request",
    )
    assert app.research_command_digest(review, uid(2)) != app.research_command_digest(
        replace(review, revision_id=uid(40002)), uid(2)
    )


def test_page_filter_and_source_boundaries_are_closed() -> None:
    query = app.ResearchSummaryQuery(
        account_id=uid(2),
        xray_run_id=uid(10),
        source_cutoff_at=AT,
        event_kind=ResearchEventKind.NEWS,
        review_state=ResearchReviewState.UNREVIEWED,
    )
    assert query.limit == 25 and query.cursor is None
    for limit in (0, 101):
        with pytest.raises(DomainError):
            replace(query, limit=limit)
    with pytest.raises(DomainError):
        replace(query, cursor="x" * 2049)
    value = event()
    view = app.ResearchItemView(
        item_id=uid(85000),
        source_cutoff_at=AT,
        source=value,
        portfolio=app.preview_research_portfolio(portfolio(value)),
        owner_revisions=(note(value),),
    )
    summary = app.ResearchSummary(
        pin=pin(),
        source_cutoff_at=AT,
        items=(view,),
        next_cursor=None,
        limit=25,
        total=1,
        unknown_exposure_total=0,
    )
    assert summary.items[0].item_id == uid(85000)
    assert summary.items[0].synthesis.availability == "unavailable"
    with pytest.raises(DomainError):
        replace(view, item_id=None)  # type: ignore[arg-type]
    assert summary.items[0].owner_revisions[0].content.thesis
    with pytest.raises(DomainError):
        replace(summary, source_cutoff_at=AT - timedelta(hours=2))
    with pytest.raises(DomainError):
        replace(view, owner_revisions=(replace(note(value), account_id=uid(99)),))
    with pytest.raises(DomainError):
        replace(
            summary,
            items=(
                replace(view, portfolio=app.preview_research_portfolio(portfolio(value, None))),
            ),
        )


def test_research_scopes_do_not_turn_write_into_read() -> None:
    assert (
        frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.RESEARCH_READ})
        == app.RESEARCH_READ_SCOPES
    )
    assert app.RESEARCH_READ_SCOPES | {Scope.RESEARCH_WRITE} == app.RESEARCH_WRITE_SCOPES
    assert Scope.RESEARCH_READ in app.RESEARCH_WRITE_SCOPES
    assert Scope.ACTIVITY_READ not in app.RESEARCH_READ_SCOPES


def test_complete_response_byte_bound_rejects_instead_of_truncating_rows() -> None:
    items = []
    for index in range(1, 101):
        source = event(index)
        owner_note = note(source)
        content = replace(
            owner_note.content,
            note="a" * 4096,
            thesis="b" * 4096,
            risks="c" * 4096,
            catalysts="d" * 4096,
            break_conditions="e" * 4096,
        )
        view = app.ResearchItemView(
            item_id=uid(85000 + index),
            source_cutoff_at=AT,
            source=source,
            portfolio=app.preview_research_portfolio(portfolio(source)),
            owner_revisions=(replace(owner_note, content=content),),
        )
        items.append(view)
    with pytest.raises(DomainError) as denied:
        app.ResearchSummary(
            pin=pin(),
            source_cutoff_at=AT,
            items=tuple(items),
            next_cursor=None,
            limit=100,
            total=100,
            unknown_exposure_total=0,
        )
    assert denied.value.field == "response.bytes"


def test_portfolio_preview_keeps_money_and_all_omitted_counts_without_becoming_canonical() -> None:
    from trading212_domain.research_facts import ResearchPortfolioWarning
    from trading212_domain.research_serialization import (
        research_record_bytes,
        research_record_digest,
    )
    from trading212_domain.values import Money
    from trading212_domain.xray import XrayWarningCode

    value = event()
    canonical = replace(
        portfolio(value),
        path_keys=tuple(f"position:proof-{index}" for index in range(70)),
        source_reference_ids=tuple(uid(1000 + index) for index in range(72)),
        metric_source_reference_ids=tuple(uid(2000 + index) for index in range(73)),
    )
    warning = ResearchPortfolioWarning(
        code=XrayWarningCode.PARTIAL_SOURCE,
        reason=None,
        source_reference_ids=canonical.source_reference_ids,
        path_keys=canonical.path_keys,
    )
    canonical = replace(canonical, warnings=(warning,) * 65)
    projected = app.preview_research_portfolio(canonical)
    assert projected.effective_exposure is canonical.effective_exposure
    assert isinstance(projected.effective_exposure, Money)
    assert (len(projected.path_keys), projected.paths_omitted) == (64, 6)
    assert (len(projected.source_reference_ids), projected.source_references_omitted) == (64, 8)
    assert (len(projected.metric_source_reference_ids), projected.metric_sources_omitted) == (64, 9)
    assert len(projected.warnings) == 64 and projected.warnings_omitted == 1
    assert projected.warnings[0].source_references_omitted == 8
    assert projected.warnings[0].paths_omitted == 6
    assert projected.company_coverage_complete == canonical.company_coverage_complete
    assert projected.canonical_facts_digest == research_record_digest(canonical)
    with pytest.raises(DomainError):
        research_record_bytes(projected)
