"""Actual pending-copy authority, completed-prefix traversal and capacity refunds."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from trading212_persistence.research_models import (
    ResearchCapacityModel,
    ResearchEventCitationModel,
    ResearchEventPayloadModel,
    ResearchRetentionCursorModel,
    ResearchSourcePayloadModel,
)
from trading212_persistence.research_retention import expire_research_payloads
from trading212_persistence.source_retention import SourcePurgeBudget

from tests.integration.research_case import ResearchCase
from tests.integration.research_case import research_case as research_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


def test_pending_copy_is_exact_source_bound_and_cannot_be_forged(
    research_case: ResearchCase,
) -> None:
    case = research_case
    event = case.publish(case.incoming("copy-guard"))
    source = event.citations[0].source.version_id
    with case.xray.sessions() as session, session.begin():
        member = session.scalar(
            select(ResearchEventCitationModel).where(
                ResearchEventCitationModel.revision_id == event.revision_id,
            )
        )
        assert member is not None and member.source_version_id == source and member.copy_pending
        for change in ({"copy_pending": False}, {"source_version_id": uuid4()}):
            with pytest.raises(IntegrityError), session.begin_nested():
                session.execute(
                    update(ResearchEventCitationModel)
                    .where(ResearchEventCitationModel.id == member.id)
                    .values(**change),
                )
        assert (
            session.scalar(
                select(ResearchEventPayloadModel.id).where(
                    ResearchEventPayloadModel.revision_id == event.revision_id,
                )
            )
            is not None
        )
        session.execute(text("SET LOCAL enable_seqscan=off"))
        plan = str(
            session.execute(
                text(
                    "EXPLAIN (FORMAT JSON) SELECT revision_id FROM research_event"
                    "_citations WHERE owner_id=:owner AND source_version_id=:sour"
                    "ce AND copy_pending=true ORDER BY revision_id,id LIMIT 1"
                ),
                {"owner": member.owner_id, "source": source},
            ).scalar_one()
        )
        assert "ix_research_pending_event_source" in plan


def test_completed_source_prefix_is_budgeted_and_event_flags_follow_actual_delete(
    research_case: ResearchCase,
) -> None:
    case = research_case
    owner = UUID(case.xray.principal.owner_id)
    for ordinal in range(6):
        case.publish(
            case.incoming(f"completed-{ordinal}", summary=f"Distinct retained facts {ordinal}.")
        )
    # One full invocation can conservatively retire six one-citation event copies.
    with case.xray.sessions() as session, session.begin():
        assert expire_research_payloads(
            session,
            at=case.xray.now[0],
            owner=owner,
            capability_authority=None,
            budget=SourcePurgeBudget(),
        )
        assert session.scalar(select(func.count()).select_from(ResearchEventPayloadModel)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(ResearchEventCitationModel)
                .where(
                    ResearchEventCitationModel.copy_pending.is_(True),
                )
            )
            == 0
        )
        capacity = session.get(ResearchCapacityModel, owner)
        assert capacity is not None and capacity.retained_bytes == 0
    with case.xray.sessions() as session, session.begin():
        budget = SourcePurgeBudget(rows_inspected=24)
        assert not expire_research_payloads(
            session, at=case.xray.now[0], owner=owner, capability_authority=None, budget=budget
        )
        cursor = session.get(ResearchRetentionCursorModel, f"research:{owner}")
        assert cursor is not None and cursor.last_version_id is not None
        first = cursor.last_version_id
        assert budget.rows_inspected == 5
    with case.xray.sessions() as session, session.begin():
        budget = SourcePurgeBudget(rows_inspected=24)
        assert not expire_research_payloads(
            session, at=case.xray.now[0], owner=owner, capability_authority=None, budget=budget
        )
        cursor = session.get(ResearchRetentionCursorModel, f"research:{owner}")
        assert (
            cursor is not None
            and cursor.last_version_id is not None
            and cursor.last_version_id > first
        )
        assert budget.rows_inspected == 5
        assert session.scalar(select(func.count()).select_from(ResearchSourcePayloadModel)) == 0
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
