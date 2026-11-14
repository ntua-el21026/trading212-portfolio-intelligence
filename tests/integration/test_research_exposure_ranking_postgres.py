"""Unknown research exposure counts/ranks and prior cursor rejection on real PG."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from trading212_application import research as app
from trading212_application.queries import cursor_binding
from trading212_domain.research import ResearchExposureReason
from trading212_persistence.research_models import ResearchItemModel
from trading212_persistence.research_page_authorization import authorize_research_page

from tests.integration.acquired_research_report_case import (
    AcquiredResearchReportCase,
    research_item_for_run,
    select_fx_policy,
)
from tests.integration.acquired_research_report_case import (
    acquired_research_report_case as acquired_research_report_case,
)
from tests.integration.research_case import research_case as research_case
from tests.integration.research_report_case import research_report_case as research_report_case
from tests.integration.test_acquired_research_reports_postgres import _no_private_reads
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def _items(case: AcquiredResearchReportCase) -> tuple[tuple[object, ...], ...]:
    with case.report.research.xray.sessions() as session:
        return tuple(
            tuple(row)
            for row in session.execute(
                select(ResearchItemModel.__table__).order_by(ResearchItemModel.id)
            )
        )


def _documented_unknown_rank(item: app.ResearchItemView) -> tuple[object, ...]:
    """All money ranks tie as unknown; remaining order follows the written contract."""
    published = item.source.facts.published_at
    return (
        item.review is not None,
        published is None,
        timedelta() if published is None else datetime.max.replace(tzinfo=UTC) - published,
        item.source.entity_id.int,
        item.source.event_id.int,
    )


async def test_unvalued_summary_counts_ranks_pages_and_rejects_old_cursor_before_private_read(
    acquired_research_report_case: AcquiredResearchReportCase,
) -> None:
    source = acquired_research_report_case
    degraded = await select_fx_policy(
        source.report.research.xray, source.xray, source.catalogue_provider_ids
    )
    assert degraded.summary.total.value is None
    report = await research_item_for_run(source.report, source.report.research.xray, degraded)
    case = replace(source, report=report)
    research = report.research
    research.publish(research.incoming("unvalued-rank-" + uuid4().hex))
    query = replace(research.query(limit=1), entity_id=research.entity_id)
    whole = await research.service.get_research_summary(
        research.xray.principal, replace(query, limit=25)
    )
    assert whole.next_cursor is None and whole.total == len(whole.items) >= 2
    assert whole.unknown_exposure_total == whole.total
    assert all(item.portfolio.effective_exposure is None for item in whole.items)
    assert all(
        item.portfolio.reason is ResearchExposureReason.CAPTURED_VALUE_UNAVAILABLE
        for item in whole.items
    )
    assert tuple(sorted(whole.items, key=_documented_unknown_rank)) == whole.items
    assert any(item.review is not None for item in whole.items)
    assert any(item.review is None for item in whole.items)

    first = await research.service.get_research_summary(research.xray.principal, query)
    assert first.next_cursor is not None and first.unknown_exposure_total == first.total
    assert first.items == whole.items[:1]
    second = await research.service.get_research_summary(
        research.xray.principal, replace(query, cursor=first.next_cursor)
    )
    assert second.items == whole.items[1:2]
    assert second.unknown_exposure_total == whole.total

    # Retain the real valid scope, epoch, cutoff, full rank and membership digest;
    # only the previous rank-resource version differs. This is a signed old
    # cursor, not a malformed token or a substituted authorization function.
    with research.xray.sessions() as session, session.begin():
        authority = authorize_research_page(
            session, research.xray.principal, research.account_id, now=research.xray.now[0]
        )
        auth = authority.auth
        binding = cursor_binding(
            auth.owner_id,
            auth.account_id,
            auth.issuer,
            auth.subject,
            authority.epoch,
            query.xray_run_id,
            query.source_cutoff_at,
            query.entity_id,
            query.event_kind,
            query.review_state,
            query.limit,
        )
    cutoff, key = research.service._cursors.decode(
        first.next_cursor, resource="research_items.bounded.v2", binding=binding, key_size=8
    )
    old = research.service._cursors.encode(
        resource="research_items.bounded.v1", binding=binding, read_cutoff=cutoff, key=key
    )
    before = _items(case)
    with _no_private_reads(case), pytest.raises(app.ResearchServiceError) as denied:
        await research.service.get_research_summary(
            research.xray.principal, replace(query, cursor=old)
        )
    assert denied.value.code is app.ResearchErrorCode.CURSOR_INVALID
    assert _items(case) == before
