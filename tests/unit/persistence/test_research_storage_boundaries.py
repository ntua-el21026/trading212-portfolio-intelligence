"""Authorization-before-decode and final original-lifetime boundary regressions."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import research as app
from trading212_domain.research_serialization import (
    research_record_bytes,
    research_source_version_from_json,
)
from trading212_domain.research_sources import ResearchSourceVersion
from trading212_domain.sources import SourceUse
from trading212_persistence import research_source_store as module
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_persistence.research_models import (
    ResearchSourceOriginModel,
    ResearchSourcePayloadModel,
    ResearchSourceVersionModel,
)
from trading212_persistence.research_permissions import (
    ResearchCapabilityGrant,
    require_research_capability,
)
from trading212_persistence.research_source_store import ResearchSourceStore
from trading212_persistence.source_models import MarketDataProviderModel

from tests.unit.domain.research_factories import AT, event, uid
from tests.unit.persistence.research_authority import SyntheticResearchAuthority


def authority() -> ReportAuthorization:
    return ReportAuthorization(
        principal_id=uid(51),
        owner_id=uid(1),
        account_id=uid(2),
        required_scopes=app.RESEARCH_WRITE_SCOPES,
        expires_at=AT + timedelta(days=60),
        issuer="local.synthetic",
        subject="research-fixture",
    )


def test_missing_capability_authority_denies_without_source_or_provider_query() -> None:
    session = Mock(spec=Session)
    source = event().citations[0].source
    with pytest.raises(app.ResearchServiceError) as error:
        require_research_capability(
            None,
            session,
            owner_id=source.owner_id,
            provider_id=source.provider_id,
            entity_id=source.entity_id,
            capability=source.capability,
            license_version_id=source.license_version_id,
            now=AT,
        )
    assert error.value.code is app.ResearchErrorCode.SOURCE_UNAVAILABLE
    assert session.mock_calls == []


@pytest.mark.parametrize("change", ("clock", "license"))
def test_final_read_uses_original_source_clock_after_decode(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    event_value = event()
    source = event_value.citations[0].source
    facts = event_value.facts
    clock = [AT]
    current = [source.license]
    auth = authority()
    store = ResearchSourceStore(
        sessions=sessionmaker(),
        cursor_signing_key=b"synthetic-research-cursor-key-32!",
        clock=lambda: clock[0],
    )
    grant = ResearchCapabilityGrant(
        grant_id=uid(910),
        grant_digest="b" * 64,
        owner_id=source.owner_id,
        provider_id=source.provider_id,
        entity_id=source.entity_id,
        capability=source.capability,
        license_version_id=source.license_version_id,
        effective_at=AT - timedelta(days=60),
        expires_at=AT + timedelta(days=365),
        uses=(SourceUse.STORE, SourceUse.DISPLAY),
    )
    store._research_capabilities = SyntheticResearchAuthority(grant)
    monkeypatch.setattr(store, "research_authority", lambda *args, **kwargs: None)
    monkeypatch.setattr(store, "_permit", lambda *args, **kwargs: source.license)
    monkeypatch.setattr(store, "_current_license", lambda *args, **kwargs: current[0])
    monkeypatch.setattr(store, "_license", lambda *args, **kwargs: source.license)
    row = ResearchSourceVersionModel(
        id=source.version_id,
        owner_id=source.owner_id,
        source_id=source.source_id,
        origin_id=uid(911),
        provider_id=source.provider_id,
        entity_id=source.entity_id,
        license_version_id=source.license_version_id,
        capability=source.capability.value,
        adapter_version=source.adapter_version,
        request_digest=source.request_digest,
        facts_digest=source.facts_digest,
        content_digest=source.content_digest,
        capability_grant_id=grant.grant_id,
        capability_grant_digest=grant.grant_digest,
        observed_at=source.observed_at,
        first_known_at=source.first_known_at,
        source_cutoff_at=source.source_cutoff_at,
        retained_at=source.retained_at,
        expires_at=source.expires_at,
        effective_expires_at=AT + timedelta(days=1),
        synthetic=True,
        sealed=True,
        created_at=source.retained_at,
    )
    origin = ResearchSourceOriginModel(
        id=row.origin_id,
        owner_id=source.owner_id,
        entity_id=source.entity_id,
        capability=source.capability.value,
        facts_digest=source.facts_digest,
        original_retained_at=AT - timedelta(days=29),
        expires_at=AT + timedelta(days=1),
    )
    provider = MarketDataProviderModel(
        id=source.provider_id, owner_id=source.owner_id, configuration_state="configured"
    )
    payload = ResearchSourcePayloadModel(
        id=uid(912),
        owner_id=source.owner_id,
        version_id=row.id,
        canonical_source=research_record_bytes(source),
        canonical_facts=research_record_bytes(facts),
        kind="news",
        publisher=facts.publisher,
        title="Dated issuer update",
        summary="The issuer published a dated update.",
        published_at=facts.published_at,
        company_name=None,
        description=None,
        publication_reason=None,
    )
    session = Mock(spec=Session)
    session.scalar.side_effect = [row, origin, provider, None, payload, row, origin, provider, None]
    decode = research_source_version_from_json

    def boundary(value: bytes, *, expected_digest: str) -> ResearchSourceVersion:
        result = decode(value, expected_digest=expected_digest)
        if change == "clock":
            clock[0] = AT + timedelta(days=2)
        else:
            current[0] = replace(source.license, retention_days=29)
        return result

    monkeypatch.setattr(module, "research_source_version_from_json", boundary)
    with pytest.raises(app.ResearchServiceError) as error:
        store.read_source(session, auth, row.id)
    assert error.value.code is app.ResearchErrorCode.SOURCE_UNAVAILABLE


def test_denied_source_authority_precedes_canonical_payload_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ResearchSourceStore(
        sessions=sessionmaker(), cursor_signing_key=b"synthetic-research-cursor-key-32!"
    )

    def deny(*args: object, **kwargs: object) -> object:
        raise app.ResearchServiceError(app.ResearchErrorCode.SOURCE_UNAVAILABLE)

    monkeypatch.setattr(store, "authorize_source", deny)
    session = Mock(spec=Session)
    with pytest.raises(app.ResearchServiceError):
        store.read_source(session, authority(), uid(1))
    assert session.mock_calls == []


def test_note_pages_pack_whole_revisions_without_advancing_past_byte_limit() -> None:
    from trading212_application.queries import CursorCodec
    from trading212_domain.research_notes import ResearchNoteContent, ResearchNoteRevision
    from trading212_domain.research_serialization import (
        research_record_bytes,
        research_record_digest,
    )
    from trading212_domain.serialization import canonical_json
    from trading212_persistence.research_models import (
        ResearchNotePayloadModel,
        ResearchNoteRevisionModel,
    )
    from trading212_persistence.research_note_page import research_note_page
    from trading212_persistence.research_page_authorization import ResearchPageAuthority

    values = tuple(
        ResearchNoteRevision(
            note_id=uid(1000 + i),
            revision_id=uid(2000 + i),
            revision=1,
            previous_revision_id=None,
            owner_id=uid(1),
            account_id=uid(2),
            entity_id=uid(3),
            actor_id=uid(51),
            created_at=AT,
            content=ResearchNoteContent(
                title="α" * 2048,  # noqa: RUF001 - intentional multilingual UTF-8 byte-bound fixture.
                note="β" * 4096,
                thesis="γ" * 4096,  # noqa: RUF001 - intentional multilingual UTF-8 byte-bound fixture.
                risks="δ" * 4096,
                catalysts="ε" * 4096,
                break_conditions="ζ" * 4096,
            ),
        )
        for i in reversed(range(48))
    )
    records = tuple(
        (
            ResearchNoteRevisionModel(
                id=value.revision_id,
                note_id=value.note_id,
                revision=value.revision,
                previous_revision_id=None,
                owner_id=value.owner_id,
                account_id=value.account_id,
                entity_id=value.entity_id,
                actor_id=value.actor_id,
                created_at=AT,
                content_digest=research_record_digest(value),
                citation_count=0,
                sealed=True,
            ),
            ResearchNotePayloadModel(
                owner_id=value.owner_id,
                account_id=value.account_id,
                revision_id=value.revision_id,
                canonical_note=research_record_bytes(value),
                title=value.content.title,
                note=value.content.note,
                thesis=value.content.thesis,
                risks=value.content.risks,
                catalysts=value.content.catalysts,
                break_conditions=value.content.break_conditions,
            ),
            AT,
            len(values),
        )
        for value in values
    )
    cursors = CursorCodec(b"synthetic-research-cursor-key-32!", clock=lambda: AT)
    context = ResearchPageAuthority(authority(), 1)
    session = Mock(spec=Session)
    session.execute.return_value.all.return_value = records
    session.scalars.return_value = ()
    first = research_note_page(
        session, context, app.ResearchPageQuery(limit=100), now=AT, cursors=cursors
    )
    assert 0 < len(first.items) < len(values) and first.next_cursor is not None
    assert (
        first.items == values[: len(first.items)] and len(canonical_json(first).encode()) <= 2097152
    )
    session.execute.return_value.all.return_value = records[len(first.items) :]
    second = research_note_page(
        session,
        context,
        app.ResearchPageQuery(limit=100, cursor=first.next_cursor),
        now=AT,
        cursors=cursors,
    )
    assert first.items + second.items == values and second.next_cursor is None
    assert len(canonical_json(second).encode()) <= 2097152
