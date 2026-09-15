"""Whole public request query count and actual authorized page/row parity."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import and_, func, literal, select
from sqlalchemy import event as sql_event
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement
from trading212_application import research as app
from trading212_domain.research_notes import ResearchNoteContent
from trading212_domain.research_serialization import research_event_from_json
from trading212_domain.research_sources import ResearchEventRevision
from trading212_domain.serialization import canonical_json
from trading212_persistence import research_summary_payloads as payload_module
from trading212_persistence.research_models import ResearchItemModel
from trading212_persistence.research_permissions import (
    ResearchCapabilityGrant,
    ResearchCapabilityRequest,
    ResearchCapabilityScope,
)

from tests.integration.research_case import ResearchCase
from tests.integration.research_case import research_case as research_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case
from tests.unit.persistence.research_authority import SyntheticResearchAuthority

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


@dataclass
class CountedSyntheticAuthority(SyntheticResearchAuthority):
    denied: set[UUID] = field(default_factory=set)
    batch_calls: int = 0

    def research_source_eligibility(
        self, scope: ResearchCapabilityScope, *, now: datetime
    ) -> ColumnElement[bool]:
        return and_(
            super().research_source_eligibility(scope, now=now),
            scope.source_version_id.not_in(tuple(self.denied)),
        )

    def authorize_research_capabilities(
        self, session: Session, *, requests: tuple[ResearchCapabilityRequest, ...], now: datetime
    ) -> tuple[ResearchCapabilityGrant, ...]:
        # Explicit fixture query occupies the real authority's entire one-statement
        # allowance; it is not production grant evidence or a live provider claim.
        session.execute(select(literal(1)))
        self.batch_calls += 1
        if any(item.source_version_id in self.denied for item in requests):
            raise app.ResearchServiceError(app.ResearchErrorCode.SOURCE_UNAVAILABLE)
        return super().authorize_research_capabilities(session, requests=requests, now=now)


@pytest.mark.asyncio
async def test_denied_long_prefix_filtered_count_rank_and_whole_request_twelve_queries(
    research_case: ResearchCase,
) -> None:
    case = research_case
    values = [
        case.publish(case.incoming(f"bounded-{i}", summary=f"Distinct issuer event {i}."))
        for i in range(120)
    ]
    ordered = sorted(values, key=lambda item: str(item.event_id))
    authority = CountedSyntheticAuthority(
        case.authority.grant, denied={item.citations[0].source.version_id for item in ordered[:108]}
    )
    case.service._research_capabilities = authority
    statements: list[str] = []
    metadata_rows: list[int] = []

    def before(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    def after(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        if "research_chosen_page" in statement:
            metadata_rows.append(cursor.rowcount)

    sql_event.listen(case.xray.engine, "before_cursor_execute", before)
    sql_event.listen(case.xray.engine, "after_cursor_execute", after)
    try:
        first = await case.service.get_research_summary(case.xray.principal, case.query(limit=5))
        assert len(statements) <= 12 and authority.batch_calls == 2
        assert first.total == 12 and len(first.items) == 5 and first.next_cursor is not None
        assert [item.source.event_id for item in first.items] == [
            item.event_id for item in ordered[108:113]
        ]
        assert metadata_rows and max(metadata_rows) <= 5 * 64
        statements.clear()
        metadata_rows.clear()
        second = await case.service.get_research_summary(
            case.xray.principal, case.query(limit=5, cursor=first.next_cursor)
        )
        assert len(statements) <= 12 and second.total == 12
        assert [item.source.event_id for item in second.items] == [
            item.event_id for item in ordered[113:118]
        ]
        authority.denied.add(ordered[-1].citations[0].source.version_id)
        with pytest.raises(app.ResearchServiceError) as changed:
            await case.service.get_research_summary(
                case.xray.principal, case.query(limit=5, cursor=first.next_cursor)
            )
        assert changed.value.code is app.ResearchErrorCode.CURSOR_INVALID
    finally:
        sql_event.remove(case.xray.engine, "before_cursor_execute", before)
        sql_event.remove(case.xray.engine, "after_cursor_execute", after)
    with case.xray.sessions() as session, session.begin():
        assert session.scalar(select(func.count()).select_from(ResearchItemModel)) == 10


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ("grant", "clock"))
async def test_final_authority_change_rolls_back_new_item_before_return(
    research_case: ResearchCase,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    case = research_case
    case.publish(case.incoming("final-boundary"))
    decode = research_event_from_json

    def changed(payload: bytes, *, expected_digest: str) -> ResearchEventRevision:
        value = decode(payload, expected_digest=expected_digest)
        if boundary == "grant":
            case.authority.revoked = True
        else:
            case.xray.now[0] += timedelta(days=31)
        return value

    monkeypatch.setattr(payload_module, "research_event_from_json", changed)
    with pytest.raises(app.ResearchServiceError) as error:
        await case.service.get_research_summary(case.xray.principal, case.query())
    assert error.value.code is app.ResearchErrorCode.SOURCE_UNAVAILABLE
    with case.xray.sessions() as session, session.begin():
        assert session.scalar(select(func.count()).select_from(ResearchItemModel)) == 0


@pytest.mark.asyncio
async def test_whole_note_page_resumes_without_skipping_byte_limited_revision(
    research_case: ResearchCase,
) -> None:
    case = research_case
    body = "漢" * 4096
    expected: list[UUID] = []
    for ordinal in range(36):
        value = await case.service.create_research_note(
            case.xray.principal,
            app.CreateResearchNote(
                account_id=case.account_id,
                entity_id=case.entity_id,
                content=ResearchNoteContent(
                    title=f"Owner note {ordinal}",
                    note=body,
                    thesis=body,
                    risks=body,
                    catalysts=body,
                    break_conditions=body,
                ),
                idempotency_key=uuid4().hex,
                correlation_id="bounded-notes",
            ),
        )
        expected.append(value.revision_id)
    statements: list[str] = []

    def observe(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    sql_event.listen(case.xray.engine, "before_cursor_execute", observe)
    try:
        first = await case.service.list_research_notes(
            case.xray.principal, case.account_id, app.ResearchPageQuery(limit=100)
        )
        assert len(statements) <= 12 and len(canonical_json(first).encode()) <= 2 * 1024 * 1024
        assert 0 < len(first.items) < 36 and first.next_cursor is not None and first.total == 36
        statements.clear()
        second = await case.service.list_research_notes(
            case.xray.principal,
            case.account_id,
            app.ResearchPageQuery(limit=100, cursor=first.next_cursor),
        )
        assert len(statements) <= 12 and second.next_cursor is None
        assert {item.revision_id for item in (*first.items, *second.items)} == set(expected)
        assert len(first.items) + len(second.items) == 36
    finally:
        sql_event.remove(case.xray.engine, "before_cursor_execute", observe)
