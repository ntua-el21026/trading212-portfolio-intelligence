"""Provider page subjects and every continuation retain the exact typed request."""

from dataclasses import replace
from datetime import timedelta
from typing import Any, cast

import pytest
from trading212_application import source_providers as ports
from trading212_domain import DomainError, build_synthetic_identity
from trading212_reference_data.replay_enrichment import (
    ReplayETFConstituentProvider,
    ReplayInstrumentEnrichmentProvider,
)
from trading212_reference_data.synthetic import FIXTURE_KNOWN_AT, FUND_SERIES_ID

from tests.unit.analytics.source_factories import uid
from tests.unit.test_reference_replay import context

pytestmark = pytest.mark.unit


def classification_request() -> ports.ClassificationRequest:
    return ports.ClassificationRequest(
        instrument_ids=(str(build_synthetic_identity().instrument.id),),
        taxonomy="synthetic-taxonomy",
        taxonomy_version="1",
        source_cutoff_at=FIXTURE_KNOWN_AT,
    )


def constituent_request() -> ports.ConstituentRequest:
    return ports.ConstituentRequest(
        fund_series_id=FUND_SERIES_ID,
        effective_at=FIXTURE_KNOWN_AT + timedelta(days=2),
        source_cutoff_at=FIXTURE_KNOWN_AT + timedelta(days=3),
    )


async def test_constituent_chain_echo_preserves_requested_and_actual_dates_separately() -> None:
    provider = ReplayETFConstituentProvider(context(page_size=1))
    request = constituent_request()
    keys: list[str] = []
    continuations: list[str] = []
    while True:
        page = await provider.get_constituents(request)
        assert isinstance(page, ports.ConstituentPage)
        assert page.request == request
        assert page.effective_at == FIXTURE_KNOWN_AT < page.request.effective_at
        keys.extend(row.source_key for row in page.holdings)
        if page.continuation is None:
            break
        assert page.continuation not in continuations
        continuations.append(page.continuation)
        request = replace(request, continuation=page.continuation)
    assert len(keys) == len(set(keys)) == 3
    assert len(continuations) == 2


async def test_classification_chain_echo_preserves_full_subject_and_taxonomy_request() -> None:
    provider = ReplayInstrumentEnrichmentProvider(context(page_size=1))
    request = classification_request()
    dimensions: list[str] = []
    while True:
        page = await provider.get_classifications(request)
        assert isinstance(page, ports.ClassificationPage)
        assert page.request == request
        assert all(row.instrument_id in request.instrument_ids for row in page.observations)
        dimensions.extend(row.dimension.value for row in page.observations)
        if page.continuation is None:
            break
        request = replace(request, continuation=page.continuation)
    assert len(dimensions) == len(set(dimensions)) == 4


@pytest.mark.parametrize(
    "changes", [{"instrument_id": uid(991)}, {"taxonomy": "other"}, {"taxonomy_version": "2"}]
)
async def test_classification_page_rejects_relabelled_subject_or_taxonomy(
    changes: dict[str, Any],
) -> None:
    page = await ReplayInstrumentEnrichmentProvider(context()).get_classifications(
        classification_request()
    )
    assert isinstance(page, ports.ClassificationPage)
    with pytest.raises(DomainError, match="subjects and taxonomy"):
        replace(page, observations=(replace(page.observations[0], **changes),))


async def test_constituent_page_rejects_future_effective_date_and_untyped_echo() -> None:
    page = await ReplayETFConstituentProvider(context()).get_constituents(constituent_request())
    assert isinstance(page, ports.ConstituentPage)
    with pytest.raises(DomainError, match="requested effective date"):
        replace(page, effective_at=page.request.effective_at + timedelta(microseconds=1))
    with pytest.raises(DomainError, match="complete constituent request"):
        replace(page, request=cast(Any, {}))


async def test_classification_page_requires_typed_request() -> None:
    page = await ReplayInstrumentEnrichmentProvider(context()).get_classifications(
        classification_request()
    )
    assert isinstance(page, ports.ClassificationPage)
    with pytest.raises(DomainError, match="complete classification request"):
        replace(page, request=cast(Any, {}))
