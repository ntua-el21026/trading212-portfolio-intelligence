"""Real research publication, exact X-ray copying, ownership and bounded retention."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from trading212_application import research as app
from trading212_domain.research_facts import copy_research_portfolio_facts
from trading212_domain.research_notes import ResearchNoteContent
from trading212_domain.research_serialization import research_record_digest
from trading212_domain.research_sources import ResearchCitationPin
from trading212_persistence import research_source_store as source_module
from trading212_persistence.premium_models import PremiumCapacityModel
from trading212_persistence.research_models import (
    ResearchAliasModel,
    ResearchAliasPromotionModel,
    ResearchCapacityModel,
    ResearchEventCitationModel,
    ResearchEventPayloadModel,
    ResearchEventRevisionModel,
    ResearchItemModel,
    ResearchNotePayloadModel,
    ResearchNoteRevisionModel,
    ResearchRetentionModel,
    ResearchSourcePayloadModel,
    ResearchSourceVersionModel,
    ResearchWitnessModel,
)
from trading212_persistence.research_retention import (
    expire_research_payloads,
    purge_owner_research_payloads,
)
from trading212_persistence.source_retention import SourcePurgeBudget

from tests.integration.research_case import ResearchCase
from tests.integration.research_case import research_case as research_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


@pytest.mark.asyncio
async def test_real_item_exact_xray_pin_notes_revision_and_current_grant(
    research_case: ResearchCase,
) -> None:
    case = research_case
    event = case.publish(case.incoming("issuer-a"))
    summary = await case.service.get_research_summary(case.xray.principal, case.query())
    assert summary.total == 1 and len(summary.items) == 1
    item = summary.items[0]
    with case.xray.sessions() as session, session.begin():
        pin, value, _, _ = case.service.retained_xray(session, case.auth(session), case.run_id)
        expected = copy_research_portfolio_facts(pin, value, case.entity_id)
        assert item.portfolio.effective_exposure == expected.effective_exposure
        assert item.portfolio.bound == expected.bound
        assert item.portfolio.canonical_facts_digest == research_record_digest(expected)
        assert session.scalar(select(func.count()).select_from(ResearchItemModel)) == 1
    assert (
        await case.service.get_research_item(
            case.xray.principal, item.item_id, expected_account_id=case.account_id
        )
        == item
    )
    with pytest.raises(app.ResearchServiceError) as error:
        await case.service.get_research_item(
            case.xray.principal, item.item_id, expected_account_id=uuid4()
        )
    assert error.value.code is app.ResearchErrorCode.NOT_FOUND
    command = app.CreateResearchNote(
        account_id=case.account_id,
        entity_id=case.entity_id,
        content=ResearchNoteContent(
            title="Owner thesis",
            thesis="Own conclusion, distinct from issuer prose.",
            citations=(ResearchCitationPin.from_citation(event.citations[0]),),
        ),
        idempotency_key=uuid4().hex,
        correlation_id="research-pg",
    )
    note = await case.service.create_research_note(case.xray.principal, command)
    assert (
        await case.service.create_research_note(
            case.xray.principal, replace(command, correlation_id="retry")
        )
        == note
    )
    changed = app.CreateResearchNoteVersion(
        note_id=note.note_id,
        expected_revision=1,
        content=replace(note.content, risks="New owner-authored risk."),
        idempotency_key=uuid4().hex,
        correlation_id="research-pg",
    )
    newer = await case.service.create_research_note_version(case.xray.principal, changed)
    assert newer.previous_revision_id == note.revision_id and newer.revision == 2
    assert (await case.service.get_research_note(case.xray.principal, note.note_id)) == newer
    assert (
        await case.service.list_research_note_versions(
            case.xray.principal, note.note_id, app.ResearchPageQuery()
        )
    ).items == (newer, note)
    assert (
        await case.service.list_research_notes(
            case.xray.principal, case.account_id, app.ResearchPageQuery()
        )
    ).items == (newer,)
    with pytest.raises(app.ResearchServiceError) as error:
        await case.service.create_research_note_version(
            case.xray.principal, replace(changed, idempotency_key=uuid4().hex)
        )
    assert error.value.code is app.ResearchErrorCode.REVISION_MISMATCH


@pytest.mark.asyncio
async def test_alias_correction_promotes_exact_provider_stream_without_erasing_review(
    research_case: ResearchCase,
) -> None:
    case = research_case
    a = case.publish(case.incoming("a"))
    incoming_b = case.incoming("b")
    grouped = case.publish(incoming_b)
    assert grouped.event_id == a.event_id and grouped.revision == 2 and len(grouped.citations) == 2
    ack = await case.service.review_research_event(
        case.xray.principal,
        app.ReviewResearchEvent(
            event_id=grouped.event_id,
            revision_id=grouped.revision_id,
            revision_digest=grouped.content_digest,
            idempotency_key=uuid4().hex,
            correlation_id="review-a",
        ),
    )
    correction = case.incoming(
        "b",
        summary="B corrected its original statement.",
        revision=2,
        previous_revision_id=incoming_b.revision_id,
    )
    promoted = case.publish(correction)
    assert (
        promoted.event_id != a.event_id
        and promoted.revision == 1
        and promoted.previous_revision_id is None
    )
    assert len(promoted.citations) == 1 and promoted.citations[0].provider_event_key == "b"
    summary = await case.service.get_research_summary(case.xray.principal, case.query())
    assert summary.total == 2
    by_event = {item.source.event_id: item for item in summary.items}
    assert by_event[grouped.event_id].review == ack
    assert by_event[promoted.event_id].review is None
    with case.xray.sessions() as session, session.begin():
        promotion = session.scalar(
            select(ResearchAliasPromotionModel).where(
                ResearchAliasPromotionModel.event_id == promoted.event_id
            )
        )
        assert promotion is not None
        alias = session.get(ResearchAliasModel, promotion.alias_id)
        assert alias is not None and alias.event_id == a.event_id
        assert (
            case.service.read_witness(session, case.auth(session), promotion.witness_id)
            == correction
        )
        witnesses = tuple(
            session.scalars(
                select(ResearchWitnessModel).order_by(
                    ResearchWitnessModel.created_at, ResearchWitnessModel.id
                )
            )
        )
        assert len(witnesses) == 3
        assert any(
            case.service.read_witness(session, case.auth(session), w.id) == incoming_b
            for w in witnesses
        )
    # Same facts retrieved again preserve a receipt without adding a material revision.
    again = case.publish(case.incoming("b", summary="B corrected its original statement."))
    assert again == promoted


@pytest.mark.asyncio
async def test_source_revocation_denies_before_decode_and_missing_authority_cleanup_drains_copies(
    research_case: ResearchCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = research_case
    source = case.publish(case.incoming("restricted"))
    item = (await case.service.get_research_summary(case.xray.principal, case.query())).items[0]
    note = await case.service.create_research_note(
        case.xray.principal,
        app.CreateResearchNote(
            account_id=case.account_id,
            entity_id=case.entity_id,
            content=ResearchNoteContent(
                title="Owner writing", note="This text belongs to the owner."
            ),
            idempotency_key=uuid4().hex,
            correlation_id="note",
        ),
    )

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("Private provider bytes were decoded after authority denial.")

    case.authority.revoked = True
    monkeypatch.setattr(source_module, "research_source_version_from_json", forbidden)
    with pytest.raises(app.ResearchServiceError) as error:
        await case.service.get_research_item(case.xray.principal, item.item_id)
    assert error.value.code is app.ResearchErrorCode.SOURCE_UNAVAILABLE
    owner = UUID(case.xray.principal.owner_id)
    with case.xray.sessions() as session, session.begin():
        before = session.get(ResearchCapacityModel, owner)
        assert before is not None
        charged = before.retained_bytes
        budget = SourcePurgeBudget(bytes_removed=0)
        assert not expire_research_payloads(
            session, at=case.xray.now[0], owner=owner, budget=budget, capability_authority=None
        )
        marker = session.scalar(
            select(ResearchRetentionModel).where(
                ResearchRetentionModel.source_version_id == source.citations[0].source.version_id
            )
        )
        assert marker is not None and marker.completed_at is None
        session.expire_all()
        current = session.get(ResearchCapacityModel, owner)
        assert current is not None and current.retained_bytes == charged
        assert expire_research_payloads(
            session,
            at=case.xray.now[0],
            owner=owner,
            budget=SourcePurgeBudget(),
            capability_authority=None,
        )
        assert session.scalar(select(func.count()).select_from(ResearchSourcePayloadModel)) == 0
        assert session.scalar(select(func.count()).select_from(ResearchEventPayloadModel)) == 0
        assert session.scalar(select(func.count()).select_from(ResearchSourceVersionModel)) == 1
        assert session.scalar(select(func.count()).select_from(ResearchItemModel)) == 1
        assert session.scalar(select(func.count()).select_from(ResearchNotePayloadModel)) == 1
        session.expire_all()
        after = session.get(ResearchCapacityModel, owner)
        assert after is not None and 0 < after.retained_bytes < charged
    assert (
        await case.service.get_research_note(case.xray.principal, note.note_id)
    ).content.note == note.content.note
    with case.xray.sessions() as session, session.begin():
        assert purge_owner_research_payloads(
            session, owner, at=case.xray.now[0], budget=SourcePurgeBudget()
        )
        session.expire_all()
        capacity = session.get(ResearchCapacityModel, owner)
        assert capacity is not None and capacity.retained_bytes == 0
        assert session.scalar(select(func.count()).select_from(ResearchNoteRevisionModel)) == 1
        assert session.scalar(select(func.count()).select_from(ResearchNotePayloadModel)) == 0


@pytest.mark.asyncio
async def test_asof_cursor_is_bound_to_account_basis_and_review_epoch(
    research_case: ResearchCase,
) -> None:
    case = research_case
    first = case.publish(case.incoming("one", summary="First issuer fact."))
    case.publish(case.incoming("two", summary="Second issuer fact."))
    query = case.query(limit=1)
    page = await case.service.get_research_summary(case.xray.principal, query)
    assert page.total == 2 and page.next_cursor is not None
    second = await case.service.get_research_summary(
        case.xray.principal, replace(query, cursor=page.next_cursor)
    )
    assert second.next_cursor is None and second.items[0].item_id != page.items[0].item_id
    await case.service.review_research_event(
        case.xray.principal,
        app.ReviewResearchEvent(
            event_id=first.event_id,
            revision_id=first.revision_id,
            revision_digest=first.content_digest,
            idempotency_key=uuid4().hex,
            correlation_id="review",
        ),
    )
    with pytest.raises(app.ResearchServiceError) as error:
        await case.service.get_research_summary(
            case.xray.principal, replace(query, cursor=page.next_cursor)
        )
    assert error.value.code is app.ResearchErrorCode.CURSOR_INVALID


def test_sql_completed_marker_cannot_hide_retained_provider_copies(
    research_case: ResearchCase,
) -> None:
    case = research_case
    source = case.publish(case.incoming("sql-marker"))
    with case.xray.sessions() as session, session.begin():
        with pytest.raises(IntegrityError), session.begin_nested():
            session.add(
                ResearchRetentionModel(
                    id=uuid4(),
                    owner_id=UUID(case.xray.principal.owner_id),
                    source_version_id=source.citations[0].source.version_id,
                    reason="source_restricted",
                    created_at=case.xray.now[0],
                    completed_at=case.xray.now[0],
                )
            )
            session.flush()
        revision = session.get(ResearchEventRevisionModel, source.revision_id)
        assert revision is not None
        with pytest.raises(IntegrityError), session.begin_nested():
            session.execute(
                text("DELETE FROM research_event_payloads WHERE revision_id=:identifier"),
                {"identifier": revision.id},
            )
        with pytest.raises(IntegrityError), session.begin_nested():
            session.add(
                ResearchEventCitationModel(
                    id=uuid4(),
                    owner_id=revision.owner_id,
                    account_id=revision.account_id,
                    revision_id=revision.id,
                    citation_id=source.citations[0].citation_id,
                    ordinal=63,
                    created_at=case.xray.now[0],
                )
            )
            session.flush()


@pytest.mark.asyncio
async def test_retrieval_receipt_does_not_renew_original_fact_lifetime(
    research_case: ResearchCase,
) -> None:
    case = research_case
    first_incoming = case.incoming("retention-origin")
    first = case.publish(first_incoming)
    original_expiry = first.citations[0].source.expires_at
    # A later transport receipt retains exactly the same published facts and key.
    case.xray.now[0] += timedelta(days=1)
    at = case.xray.now[0]
    original = first_incoming.citations[0]
    fresh_source = replace(
        original.source,
        source_id=uuid4(),
        version_id=uuid4(),
        observed_at=at,
        first_known_at=at,
        source_cutoff_at=at,
        retained_at=at,
        expires_at=at + timedelta(days=30),
    )
    fresh_citation = replace(original, citation_id=uuid4(), source=fresh_source)
    receipt = replace(
        first_incoming,
        event_id=uuid4(),
        revision_id=uuid4(),
        citations=(fresh_citation,),
        created_at=at,
    )
    assert case.publish(receipt) == first
    with case.xray.sessions() as session, session.begin():
        row = session.get(ResearchSourceVersionModel, fresh_source.version_id)
        assert row is not None and row.expires_at == at + timedelta(days=30)
        assert row.effective_expires_at == original_expiry
        assert case.service.read_source(session, case.auth(session), row.id)[0] == fresh_source
    case.xray.now[0] = original_expiry + timedelta(seconds=1)
    with case.xray.sessions() as session, session.begin():
        with pytest.raises(app.ResearchServiceError):
            case.service.read_source(session, case.auth(session), fresh_source.version_id)
        assert expire_research_payloads(
            session,
            at=case.xray.now[0],
            owner=UUID(case.xray.principal.owner_id),
            budget=SourcePurgeBudget(),
            capability_authority=case.authority,
        )
        assert session.scalar(select(func.count()).select_from(ResearchSourcePayloadModel)) == 0


def test_source_receipt_is_reusable_but_event_identity_is_account_scoped(
    research_case: ResearchCase,
) -> None:
    from trading212_persistence.models import BrokerAccountModel
    from trading212_persistence.report_authorization import authorize_report_request

    case = research_case
    incoming = case.incoming("same-provider-event")
    first = case.publish(incoming)
    with case.xray.sessions() as session, session.begin():
        base = session.get(BrokerAccountModel, case.account_id)
        assert base is not None
        account = BrokerAccountModel(
            id=uuid4(),
            connection_id=base.connection_id,
            provider_account_id=uuid4().hex,
            account_type=base.account_type,
            base_currency=base.base_currency,
            display_name="Second research fixture account",
            status="active",
            first_seen_at=case.xray.now[0],
            last_seen_at=case.xray.now[0],
            created_at=case.xray.now[0],
            updated_at=case.xray.now[0],
        )
        session.add(account)
        session.flush()
        auth = authorize_report_request(
            session,
            case.xray.principal,
            account_id=account.id,
            required_scopes=app.RESEARCH_WRITE_SCOPES,
            now=case.xray.now[0],
        )
        second = case.service.publish_event(session, auth, incoming)
        assert second.event_id != first.event_id and second.revision_id != first.revision_id
        assert second.citations == first.citations
        assert session.scalar(select(func.count()).select_from(ResearchSourceVersionModel)) == 1
        assert case.service.read_event(session, auth, second.revision_id) == second
        with pytest.raises(app.ResearchServiceError):
            case.service.read_event(session, auth, first.revision_id)


@pytest.mark.asyncio
async def test_note_admission_uses_shared_reserved_bytes_and_definition_count(
    research_case: ResearchCase,
) -> None:
    case = research_case
    owner = UUID(case.xray.principal.owner_id)
    case.publish(case.incoming("capacity"))
    command = app.CreateResearchNote(
        account_id=case.account_id,
        entity_id=case.entity_id,
        content=ResearchNoteContent(title="Bounded owner note", note="Retained owner text."),
        idempotency_key=uuid4().hex,
        correlation_id="capacity",
    )
    with case.xray.sessions() as session, session.begin():
        capacity = session.get(PremiumCapacityModel, owner)
        assert capacity is not None
        baseline = (capacity.reserved_bytes, capacity.definition_versions)
        capacity.reserved_bytes = 268435456 - capacity.retained_bytes
    with pytest.raises(app.ResearchServiceError) as error:
        await case.service.create_research_note(case.xray.principal, command)
    assert error.value.code is app.ResearchErrorCode.RATE_LIMITED
    with case.xray.sessions() as session, session.begin():
        capacity = session.get(PremiumCapacityModel, owner)
        assert capacity is not None
        capacity.reserved_bytes = baseline[0]
        capacity.definition_versions = 512
    with pytest.raises(app.ResearchServiceError) as error:
        await case.service.create_research_note(case.xray.principal, command)
    assert error.value.code is app.ResearchErrorCode.RATE_LIMITED
    with case.xray.sessions() as session, session.begin():
        capacity = session.get(PremiumCapacityModel, owner)
        assert capacity is not None
        capacity.definition_versions = baseline[1]
        assert session.scalar(select(func.count()).select_from(ResearchNoteRevisionModel)) == 0
    assert (await case.service.create_research_note(case.xray.principal, command)).revision == 1
