"""Explicit synthetic identities and complete scoped replay chains for X-ray ingestion."""

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from typing import cast

import pytest
from trading212_application import source_providers as ports
from trading212_application.ingestion import FULL_REFRESH_ORDER, IngestionCapability
from trading212_domain import build_synthetic_identity
from trading212_reference_data.replay_runtime import ReplayRuntime
from trading212_worker.source_seed import collect_source_pages
from trading212_worker.xray_fixture import (
    XRAY_ACCOUNT_ID,
    XRAY_AT,
    XRAY_EFFECTIVE,
    build_xray_fixture,
    synthetic_xray_policy,
    xray_id,
)
from trading212_worker.xray_provider import SyntheticXrayBrokerProvider
from trading212_worker.xray_source_fixture import xray_entities, xray_replay


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


class SchedulingClock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    async def sleep(self, delay: float) -> None:
        self.value += delay


async def test_broker_fixture_has_six_held_roots_and_preserves_observed_receipt_fx() -> None:
    provider = SyntheticXrayBrokerProvider()
    owner = str(build_synthetic_identity().owner.id)
    pages = {
        capability: await provider.read_page(
            owner_id=owner,
            account_id=XRAY_ACCOUNT_ID,
            capability=capability,
            checkpoint=None,
            correlation_id="fixture-test",
        )
        for capability in FULL_REFRESH_ORDER
    }
    positions = pages[IngestionCapability.POSITIONS].records
    assert len(positions) == 6 and all(page.complete for page in pages.values())
    receipt = next(
        row for row in positions if _mapping(row.payload["instrument"])["currency"] == "USD"
    )
    wallet = _mapping(receipt.payload["walletImpact"])
    value = wallet["currentValue"]
    rate = _mapping(wallet["fxRate"])["rate"]
    assert isinstance(value, Decimal) and value == Decimal("62.50")
    assert isinstance(rate, Decimal) and rate == Decimal("0.8")
    assert Fraction(value) * Fraction(rate) == 50
    fixture = build_xray_fixture()
    ordinary = [
        item for item in fixture.listings if item.key in ("alpha-primary", "alpha-secondary")
    ]
    assert ordinary[0].instrument.id == ordinary[1].instrument.id
    assert ordinary[0].listing.id != ordinary[1].listing.id
    assert any(row.units_per_receipt == Decimal("2") for row in xray_entities().relationships)
    beta = next(
        row for row in xray_entities().mappings if row.instrument_id == xray_id("instrument/beta")
    )
    assert beta.listing_id is None and beta.entity_id == xray_id("entity/beta")
    assert synthetic_xray_policy().method_version == "1.1.0"


async def test_broker_fixture_rejects_another_account() -> None:
    with pytest.raises(ValueError):
        await SyntheticXrayBrokerProvider().read_page(
            owner_id=str(build_synthetic_identity().owner.id),
            account_id=xray_id("another-account"),
            capability=IngestionCapability.POSITIONS,
            checkpoint=None,
            correlation_id="fixture-test",
        )


async def test_constituent_chains_keep_subject_headers_and_all_declared_mass() -> None:
    provider = xray_replay(str(build_synthetic_identity().owner.id))
    clock = SchedulingClock()
    provider.runtime = ReplayRuntime(
        cursor_key=b"x" * 32, page_size=1, monotonic=clock.now, sleep=clock.sleep
    )
    for key, expected_rows, expected_known in (
        ("fund-a", 3, Fraction(9, 10)),
        ("fund-b", 2, Fraction(1)),
    ):
        request = ports.ConstituentRequest(
            fund_series_id=xray_id(f"fund-mapping/{key}"),
            effective_at=XRAY_AT,
            source_cutoff_at=XRAY_AT,
        )

        async def fetch(
            cursor: str | None, request: ports.ConstituentRequest = request
        ) -> ports.ConstituentPage | ports.SourceFailure:
            return await provider.get_constituents(replace(request, continuation=cursor))

        pages = await collect_source_pages(
            fetch,
            page_type=ports.ConstituentPage,
            next_cursor=lambda page: page.continuation,
            row_count=lambda page: len(page.holdings),
        )
        assert len(pages) == expected_rows
        assert all(page.request.fund_series_id == request.fund_series_id for page in pages)
        assert (
            sum((Fraction(row.weight) for page in pages for row in page.holdings), Fraction()) == 1
        )
        assert Fraction(pages[0].stated_coverage) == expected_known
        if key == "fund-a":
            assert pages[0].effective_at == XRAY_EFFECTIVE


async def test_constituent_cursor_cannot_be_replayed_under_another_fund() -> None:
    provider = xray_replay(str(build_synthetic_identity().owner.id))
    provider.runtime = ReplayRuntime(cursor_key=b"x" * 32, page_size=1)
    request = ports.ConstituentRequest(
        fund_series_id=xray_id("fund-mapping/fund-a"),
        effective_at=XRAY_AT,
        source_cutoff_at=XRAY_AT,
    )
    first = await provider.get_constituents(request)
    assert isinstance(first, ports.ConstituentPage) and first.continuation is not None
    wrong = await provider.get_constituents(
        replace(
            request, fund_series_id=xray_id("fund-mapping/fund-b"), continuation=first.continuation
        )
    )
    assert (
        isinstance(wrong, ports.SourceFailure)
        and wrong.code is ports.SourceProviderError.PAGINATION_INVALID
    )


async def test_classifications_use_explicit_subject_taxonomy_and_economic_currency() -> None:
    provider = xray_replay(str(build_synthetic_identity().owner.id))
    request = ports.ClassificationRequest(
        instrument_ids=(xray_id("instrument/alpha-a"), xray_id("instrument/beta")),
        taxonomy="synthetic-xray-currency",
        taxonomy_version="1",
        source_cutoff_at=XRAY_AT,
    )
    result = await provider.get_classifications(request)
    assert isinstance(result, ports.ClassificationPage)
    assert {row.instrument_id: row.category for row in result.observations} == {
        xray_id("instrument/alpha-a"): "USD",
        xray_id("instrument/beta"): "EUR",
    }
    unknown = await provider.get_classifications(replace(request, taxonomy="unconfigured-taxonomy"))
    assert (
        isinstance(unknown, ports.SourceFailure)
        and unknown.code is ports.SourceProviderError.NOT_FOUND
    )
