"""Replay evidence is bound to one typed fixture, scope and logical read."""

import base64
import hashlib
import hmac
import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from importlib.resources import files
from typing import Any, cast

import pytest
from trading212_analytics.source_policy import assess_fx_coverage
from trading212_application import source_providers as ports
from trading212_domain import build_synthetic_identity
from trading212_domain.serialization import canonical_json, to_primitive
from trading212_domain.source_details import (
    ClassificationDimension,
    CorporateActionKind,
    SourceIdentifier,
    SourceIdentifierKind,
    SourceMappingState,
)
from trading212_domain.sources import ObservationState, SourceReason, source_snapshot_digest
from trading212_domain.values import CurrencyCode
from trading212_reference_data.replay import (
    ReplayContext,
    ReplayFxReferenceProvider,
    ReplayMarketPriceHistoryProvider,
    ReplayVariant,
)
from trading212_reference_data.replay_enrichment import (
    ReplayETFConstituentProvider,
    ReplayInstrumentEnrichmentProvider,
)
from trading212_reference_data.replay_runtime import ReplayFault, ReplayRuntime
from trading212_reference_data.synthetic import (
    CALENDAR_ID,
    CALENDAR_VERSION,
    FIXTURE_KNOWN_AT,
    FIXTURE_PERIOD,
    FUND_SERIES_ID,
    LICENSE_ID,
    PROVIDER_ID,
    SyntheticData,
    SyntheticFundMapping,
)

from tests.unit.analytics.source_factories import EUR, USD, fx, uid
from tests.unit.test_reference_replay import context, price_request

pytestmark = pytest.mark.unit


def fixture() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(
            files("trading212_reference_data").joinpath("fixtures/synthetic-v1.json").read_bytes()
        ),
    )


def fx_request() -> ports.FxRatesRequest:
    return ports.FxRatesRequest(
        provider_id=PROVIDER_ID,
        license_version_id=LICENSE_ID,
        calendar_id=CALENDAR_ID,
        calendar_version=CALENDAR_VERSION,
        pairs=(ports.FxPair(base=EUR, quote=USD),),
        period=FIXTURE_PERIOD,
        source_cutoff_at=FIXTURE_KNOWN_AT,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("currency", CurrencyCode("GBP")),
        ("provider_key", "ANOTHER_SECURITY"),
        ("calendar_id", "another-calendar"),
        ("calendar_version", "next-version"),
        ("mapping_version", "another-mapping"),
        ("mapping_id", uid(900)),
        ("id", uid(901)),
    ],
)
def test_context_rejects_fixed_fixture_relabeling(field: str, value: Any) -> None:
    ctx = context()
    changed = replace(ctx.series[0], **{field: value})
    with pytest.raises(ValueError, match="replay source configuration is incompatible"):
        ReplayContext(license=ctx.license, series=(changed, *ctx.series[1:]), clock=ctx.clock)


async def test_gap_fx_coverage_exactly_matches_registered_calendar_assessment() -> None:
    ctx = context(variant=ReplayVariant.GAP)
    request = fx_request()
    page = await ReplayFxReferenceProvider(ctx).get_rates(request)
    assert isinstance(page, ports.FxRatePage) and isinstance(ctx.data, SyntheticData)
    assert page.coverage == assess_fx_coverage(
        ctx.data.calendar,
        request.period,
        page.observations,
        pairs=tuple((pair.base, pair.quote) for pair in request.pairs),
    )
    assert page.coverage.gaps[0].source_key == "EUR:USD"
    assert page.coverage.reason is SourceReason.MISSING_SESSION
    denied = await ReplayFxReferenceProvider(ctx).get_rates(
        replace(request, calendar_version="other")
    )
    assert (
        isinstance(denied, ports.SourceFailure)
        and denied.code is ports.SourceProviderError.UNSUPPORTED
    )


def test_fx_snapshot_semantic_digest_pins_calendar_version() -> None:
    before = fx((EUR, USD, "1.2"))
    assert source_snapshot_digest(before) != source_snapshot_digest(
        replace(before, calendar_version="2")
    )


async def test_continuation_cannot_join_different_selected_fixture_bytes() -> None:
    first = context(page_size=1)
    page = await ReplayMarketPriceHistoryProvider(first).get_price_history(price_request(first))
    assert isinstance(page, ports.PriceHistoryPage) and page.continuation is not None
    payload = fixture()
    payload["prices"]["raw_close"][1]["value"] = "999"
    changed = context(payload=json.dumps(payload).encode(), page_size=1)
    denied = await ReplayMarketPriceHistoryProvider(changed).get_price_history(
        replace(price_request(changed), continuation=page.continuation)
    )
    assert (
        isinstance(denied, ports.SourceFailure)
        and denied.code is ports.SourceProviderError.PAGINATION_INVALID
    )
    # An ignored private field does not change any canonical source or cursor scope.
    unchanged = fixture()
    unchanged["private_location"] = "_".join(("REFERENCE", "PRIVATE", "CANARY"))
    extra = context(payload=json.dumps(unchanged).encode(), page_size=1)
    allowed = await ReplayMarketPriceHistoryProvider(extra).get_price_history(
        replace(price_request(extra), continuation=page.continuation)
    )
    assert isinstance(allowed, ports.PriceHistoryPage) and allowed.observations[0].value == Decimal(
        "101"
    )


async def test_one_captured_receipt_instant_is_used_for_cutoff_and_provenance() -> None:
    ctx = context()
    calls = 0

    def advancing_clock() -> datetime:
        nonlocal calls
        now = FIXTURE_KNOWN_AT + timedelta(seconds=calls)
        calls += 1
        return now

    ctx.clock = advancing_clock
    page = await ReplayMarketPriceHistoryProvider(ctx).get_price_history(price_request(ctx))
    assert isinstance(page, ports.PriceHistoryPage)
    assert calls == 1 and page.provenance.first_observed_at == FIXTURE_KNOWN_AT
    later = await ReplayMarketPriceHistoryProvider(ctx).get_price_history(price_request(ctx))
    assert (
        isinstance(later, ports.SourceFailure) and later.code is ports.SourceProviderError.NOT_FOUND
    )


async def test_enrichment_returns_selected_fixture_values_and_exact_weight_totals() -> None:
    payload = fixture()
    payload["instrument"]["isin"] = "XS0000000002"
    payload["classifications"][0]["category"] = "Financials"
    for row, weight in zip(payload["constituents"], ("0.6", "0.2", "0.2"), strict=True):
        row["weight"] = weight
    ctx = context(payload=json.dumps(payload).encode())
    enrichment = ReplayInstrumentEnrichmentProvider(ctx)
    mapped = await enrichment.resolve_instrument(
        ports.InstrumentResolutionRequest(
            identifier=SourceIdentifier(kind=SourceIdentifierKind.ISIN, value="XS0000000002"),
            source_cutoff_at=FIXTURE_KNOWN_AT,
        )
    )
    assert (
        isinstance(mapped, ports.InstrumentResolutionResult)
        and mapped.state is SourceMappingState.RESOLVED
    )
    old = await enrichment.resolve_instrument(
        ports.InstrumentResolutionRequest(
            identifier=SourceIdentifier(kind=SourceIdentifierKind.ISIN, value="XS0000000001"),
            source_cutoff_at=FIXTURE_KNOWN_AT,
        )
    )
    assert (
        isinstance(old, ports.InstrumentResolutionResult)
        and old.state is SourceMappingState.UNRESOLVED
    )
    classifications = await enrichment.get_classifications(
        ports.ClassificationRequest(
            instrument_ids=(str(build_synthetic_identity().instrument.id),),
            taxonomy="synthetic-taxonomy",
            taxonomy_version="1",
            source_cutoff_at=FIXTURE_KNOWN_AT,
        )
    )
    assert isinstance(classifications, ports.ClassificationPage)
    assert (
        next(
            row.category
            for row in classifications.observations
            if row.dimension is ClassificationDimension.SECTOR
        )
        == "Financials"
    )
    fund = await ReplayETFConstituentProvider(ctx).get_constituents(
        ports.ConstituentRequest(
            fund_series_id=FUND_SERIES_ID,
            effective_at=FIXTURE_KNOWN_AT,
            source_cutoff_at=FIXTURE_KNOWN_AT,
        )
    )
    assert isinstance(fund, ports.ConstituentPage)
    assert (fund.stated_coverage, fund.unresolved_weight, fund.cash_weight) == (
        Decimal("0.6"),
        Decimal("0.2"),
        Decimal("0.2"),
    )
    assert [row.weight for row in fund.holdings] == [Decimal("0.6"), Decimal("0.2"), Decimal("0.2")]


async def test_fund_requires_explicit_owner_bound_mapping() -> None:
    ctx = context()
    ctx.fund_mapping = None
    unavailable = await ReplayETFConstituentProvider(ctx).get_constituents(
        ports.ConstituentRequest(
            fund_series_id=FUND_SERIES_ID,
            effective_at=FIXTURE_KNOWN_AT,
            source_cutoff_at=FIXTURE_KNOWN_AT,
        )
    )
    assert (
        isinstance(unavailable, ports.SourceFailure)
        and unavailable.code is ports.SourceProviderError.NOT_FOUND
    )
    with pytest.raises(ValueError, match="replay fund mapping is incompatible"):
        ReplayContext(
            license=ctx.license,
            series=ctx.series,
            clock=ctx.clock,
            fund_mapping=SyntheticFundMapping(
                owner_id=uid(900),
                fund_series_id=FUND_SERIES_ID,
                constituent_instrument_id=str(build_synthetic_identity().instrument.id),
            ),
        )


async def test_corporate_action_correction_changes_values_and_keeps_relationship_provenance() -> (
    None
):
    original, corrected = context(), context(variant=ReplayVariant.CORRECTION)
    pages = []
    for ctx in (original, corrected):
        request = price_request(ctx)
        page = await ReplayMarketPriceHistoryProvider(ctx).get_corporate_actions(
            ports.CorporateActionsRequest(
                series=request.series,
                period=request.period,
                source_cutoff_at=request.source_cutoff_at,
            )
        )
        assert isinstance(page, ports.CorporateActionPage)
        pages.append(page)
    before, after = pages
    assert before.observations[0].ratio == Decimal("2") and after.observations[0].ratio == Decimal(
        "3"
    )
    assert before.observations[1].amount == Decimal("0.5") and after.observations[
        1
    ].amount == Decimal("0.75")
    assert all(
        new.correction_source_key == old.source_key
        for old, new in zip(before.observations, after.observations, strict=True)
    )
    assert before.observations[0].source_revision == "synthetic-split-1"
    assert after.observations[0].source_revision == "synthetic-split-2"
    prices = await ReplayMarketPriceHistoryProvider(corrected).get_price_history(
        price_request(corrected)
    )
    assert isinstance(prices, ports.PriceHistoryPage)
    assert {row.corporate_action_revision for row in prices.observations} == {
        after.observations[0].source_revision
    }
    assert before.provenance.revision_order == 1 and after.provenance.revision_order == 2


async def test_actions_preserve_typed_targets_and_unsupported_fields() -> None:
    payload = fixture()
    payload["actions"][0].update(
        kind="merger", target_instrument_id=uid(800), correction_source_key="earlier-action"
    )
    ctx = context(payload=json.dumps(payload).encode())
    request = price_request(ctx)
    page = await ReplayMarketPriceHistoryProvider(ctx).get_corporate_actions(
        ports.CorporateActionsRequest(
            series=request.series, period=request.period, source_cutoff_at=request.source_cutoff_at
        )
    )
    assert isinstance(page, ports.CorporateActionPage)
    row = page.observations[0]
    assert row.kind is CorporateActionKind.MERGER and row.target_instrument_id == uid(800)
    assert row.correction_source_key == "earlier-action"
    gap = context(variant=ReplayVariant.GAP)
    request = price_request(gap)
    partial = await ReplayMarketPriceHistoryProvider(gap).get_corporate_actions(
        ports.CorporateActionsRequest(
            series=request.series, period=request.period, source_cutoff_at=request.source_cutoff_at
        )
    )
    assert isinstance(partial, ports.CorporateActionPage) and partial.coverage.available_count == 1
    assert partial.observations[0].state is ObservationState.UNSUPPORTED
    assert (
        partial.observations[0].ratio is None
        and partial.coverage.gaps[0].source_key == "synthetic-split"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "period",
        "duplicate_price",
        "off_calendar_fx",
        "bad_revision_link",
        "bool_revision",
        "duplicate_classification",
    ],
)
async def test_invalid_selected_fixture_structure_returns_safe_failure(mutation: str) -> None:
    payload = fixture()
    if mutation == "period":
        payload["period"]["end"] = "2026-08-29"
    elif mutation == "duplicate_price":
        payload["prices"]["raw_close"].append(payload["prices"]["raw_close"][0])
    elif mutation == "off_calendar_fx":
        payload["fx"][0]["effective_at"] = "2026-08-03T15:00:00Z"
    elif mutation == "bad_revision_link":
        payload["actions"][0]["revision"] = "unrelated-revision"
    elif mutation == "bool_revision":
        payload["revision_order"] = True
    else:
        payload["classifications"].append(payload["classifications"][0])
    marker = "_".join(("REFERENCE", "PRIVATE", "CANARY"))
    payload["unrecognized_private_field"] = marker
    ctx = context(payload=json.dumps(payload).encode())
    result = await ReplayMarketPriceHistoryProvider(ctx).get_price_history(price_request(ctx))
    assert (
        isinstance(result, ports.SourceFailure)
        and result.code is ports.SourceProviderError.INVALID_SCHEMA
    )
    assert marker not in canonical_json(to_primitive(result)) and marker not in repr(ctx.data)


@pytest.mark.parametrize("deadline", ["nan", "inf", "-inf", "1000"])
def test_signed_cursor_rejects_nonfinite_or_extended_deadline(deadline: str) -> None:
    key = b"x" * 32
    runtime = ReplayRuntime(cursor_key=key, page_size=1, monotonic=lambda: 0)
    body = f"{hashlib.sha256(b'fixed').hexdigest()}:1:2:{deadline}".encode()
    cursor = base64.urlsafe_b64encode(body + hmac.digest(key, body, "sha256")).decode().rstrip("=")
    assert (
        runtime.window(scope="fixed", count=3, continuation=cursor)
        is ReplayFault.PAGINATION_INVALID
    )
