"""Exact batch entitlement scope, omissions, duplicate identities and final expiry."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import literal
from sqlalchemy.orm import Session
from trading212_application import research as app
from trading212_domain.sources import SourceUse
from trading212_persistence.research_permissions import (
    ResearchCapabilityGrant,
    ResearchCapabilityRequest,
    ResearchCapabilityScope,
    require_research_capabilities,
    research_capability_eligibility,
)

from tests.unit.domain.research_factories import AT, event, uid
from tests.unit.persistence.research_authority import SyntheticResearchAuthority


def request() -> ResearchCapabilityRequest:
    source = event().citations[0].source
    return ResearchCapabilityRequest(
        source_version_id=source.version_id,
        owner_id=source.owner_id,
        provider_id=source.provider_id,
        entity_id=source.entity_id,
        capability=source.capability,
        license_version_id=source.license_version_id,
        grant_id=uid(800),
        grant_digest="a" * 64,
        retained_at=AT,
        original_retained_at=AT - timedelta(days=1),
        effective_expires_at=AT + timedelta(days=29),
    )


def grant(value: ResearchCapabilityRequest) -> ResearchCapabilityGrant:
    return ResearchCapabilityGrant(
        owner_id=value.owner_id,
        provider_id=value.provider_id,
        entity_id=value.entity_id,
        capability=value.capability,
        license_version_id=value.license_version_id,
        grant_id=value.grant_id,
        grant_digest=value.grant_digest,
        effective_at=AT - timedelta(days=30),
        expires_at=AT + timedelta(days=60),
        uses=(SourceUse.STORE, SourceUse.DISPLAY),
    )


@pytest.mark.parametrize(
    "change",
    (
        "missing",
        "extra",
        "owner",
        "provider",
        "entity",
        "license",
        "id",
        "digest",
        "expired",
        "late",
        "short",
    ),
)
def test_batch_rejects_incomplete_or_cross_scope_current_grants(change: str) -> None:
    item = request()
    value = grant(item)
    value = replace(
        value,
        owner_id=uid(999) if change == "owner" else value.owner_id,
        provider_id=uid(999) if change == "provider" else value.provider_id,
        entity_id=uid(999) if change == "entity" else value.entity_id,
        license_version_id=uid(999) if change == "license" else value.license_version_id,
        grant_id=uid(999) if change == "id" else value.grant_id,
    )
    if change == "digest":
        value = replace(value, grant_digest="b" * 64)
    if change == "expired":
        value = replace(value, expires_at=AT)
    if change == "late":
        value = replace(value, effective_at=AT + timedelta(seconds=1))
    if change == "short":
        value = replace(value, expires_at=AT + timedelta(days=1))
    authority = Mock()
    authority.authorize_research_capabilities.return_value = (
        () if change == "missing" else (value, value) if change == "extra" else (value,)
    )
    with pytest.raises(app.ResearchServiceError) as error:
        require_research_capabilities(authority, Mock(spec=Session), requests=(item,), now=AT)
    assert error.value.code is app.ResearchErrorCode.SOURCE_UNAVAILABLE


def test_missing_authority_and_duplicate_source_ids_fail_without_any_query() -> None:
    item = request()
    session = Mock(spec=Session)
    with pytest.raises(app.ResearchServiceError):
        require_research_capabilities(None, session, requests=(item,), now=AT)
    with pytest.raises(app.ResearchServiceError):
        require_research_capabilities(
            SyntheticResearchAuthority(grant(item)), session, requests=(item, item), now=AT
        )
    assert session.mock_calls == []


def test_exact_ordered_batch_accepts_two_distinct_source_versions_with_same_grant() -> None:
    item = request()
    value = grant(item)
    result = require_research_capabilities(
        SyntheticResearchAuthority(value),
        Mock(spec=Session),
        requests=(item, replace(item, source_version_id=uid(998))),
        now=AT,
    )
    assert result == (value, value)


def test_missing_predicate_authority_is_false_and_accepts_no_payload_query() -> None:
    item = request()
    scope = ResearchCapabilityScope(
        **{
            name: literal(getattr(item, name))
            for name in (
                "source_version_id",
                "owner_id",
                "provider_id",
                "entity_id",
                "capability",
                "license_version_id",
                "grant_id",
                "grant_digest",
                "retained_at",
                "original_retained_at",
                "effective_expires_at",
            )
        }
    )
    assert str(research_capability_eligibility(None, scope, now=AT)) == "false"
