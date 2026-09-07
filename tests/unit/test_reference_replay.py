"""Actual typed replay families preserve exact source semantics and safe failures."""

import json
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from importlib.resources import files

import pytest
from trading212_application import source_providers as ports
from trading212_domain import build_synthetic_identity
from trading212_domain.serialization import canonical_json, to_primitive
from trading212_domain.source_details import (
    SourceIdentifier,
    SourceIdentifierKind,
    SourceMappingState,
)
from trading212_domain.sources import (
    LicensePermission,
    ObservationState,
    PriceBasis,
    PriceObservation,
    PriceSnapshot,
    SourceSeriesKind,
    source_snapshot_digest,
)
from trading212_domain.values import CurrencyCode
from trading212_reference_data.replay import (
    ReplayBenchmarkProvider,
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
    SyntheticFundMapping,
    synthetic_license,
    synthetic_series,
)
from trading212_reference_data.unconfigured import UnconfiguredReferenceProviders

pytestmark = pytest.mark.unit


@dataclass
class SchedulingClock:
    now: float = 0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.now += delay


def context(
    *,
    variant: ReplayVariant = ReplayVariant.STANDARD,
    payload: bytes | None = None,
    faults: tuple[ReplayFault, ...] = (),
    page_size: int = 1000,
) -> ReplayContext:
    identity = build_synthetic_identity()
    clock = SchedulingClock()
    return ReplayContext(
        license=synthetic_license(),
        series=synthetic_series(
            owner_id=str(identity.owner.id),
            instrument_id=str(identity.instrument.id),
            listing_id=str(identity.listing.id),
        ),
        clock=lambda: FIXTURE_KNOWN_AT,
        fund_mapping=SyntheticFundMapping(
            owner_id=str(identity.owner.id),
            fund_series_id=FUND_SERIES_ID,
            constituent_instrument_id=str(identity.instrument.id),
        ),
        variant=variant,
        fixture_payload=payload,
        runtime=ReplayRuntime(
            cursor_key=b"r" * 32,
            page_size=page_size,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            faults=faults,
        ),
    )


def price_request(
    ctx: ReplayContext, basis: PriceBasis = PriceBasis.RAW_CLOSE
) -> ports.PriceHistoryRequest:
    return ports.PriceHistoryRequest(
        series=next(
            s for s in ctx.series if s.kind is SourceSeriesKind.SECURITY_PRICE and s.basis is basis
        ),
        period=FIXTURE_PERIOD,
        source_cutoff_at=FIXTURE_KNOWN_AT,
    )


@pytest.mark.parametrize("basis", list(PriceBasis))
async def test_price_replay_traverses_whole_series_without_relabeling_basis(
    basis: PriceBasis,
) -> None:
    ctx = context(page_size=3)
    provider = ReplayMarketPriceHistoryProvider(ctx)
    request = price_request(ctx, basis)
    observations: list[PriceObservation] = []
    while True:
        page = await provider.get_price_history(request)
        assert isinstance(page, ports.PriceHistoryPage)
        assert page.series.basis is basis
        assert page.provenance.synthetic
        assert page.coverage.expected_count == 20 and page.coverage.available_count == 20
        assert len(page.observations) <= 3
        observations.extend(page.observations)
        if not page.continuation:
            break
        request = replace(request, continuation=page.continuation)
    assert len(observations) == 20 and len({r.session_date for r in observations}) == 20
    assert (
        observations[-1].value
        == {
            PriceBasis.RAW_CLOSE: Decimal("59"),
            PriceBasis.SPLIT_ADJUSTED: Decimal("119"),
            PriceBasis.TOTAL_RETURN: Decimal("138"),
        }[basis]
    )


@pytest.mark.parametrize("variant,count", [(ReplayVariant.GAP, 19), (ReplayVariant.EMPTY, 0)])
async def test_missing_replay_observations_remain_explicit(
    variant: ReplayVariant, count: int
) -> None:
    ctx = context(variant=variant)
    page = await ReplayMarketPriceHistoryProvider(ctx).get_price_history(price_request(ctx))
    assert isinstance(page, ports.PriceHistoryPage)
    assert page.coverage.available_count == count and page.coverage.expected_count == 20
    assert len(page.coverage.gaps) == 20 - count
    assert all(
        row.value is None for row in page.observations if row.state is ObservationState.MISSING
    )


async def test_fx_replay_has_direct_rates_and_never_manufactures_missing_pairs() -> None:
    ctx = context()
    provider = ReplayFxReferenceProvider(ctx)
    request = ports.FxRatesRequest(
        provider_id=PROVIDER_ID,
        license_version_id=LICENSE_ID,
        calendar_id=CALENDAR_ID,
        calendar_version=CALENDAR_VERSION,
        pairs=(
            ports.FxPair(base=CurrencyCode("EUR"), quote=CurrencyCode("USD")),
            ports.FxPair(base=CurrencyCode("GBP"), quote=CurrencyCode("EUR")),
        ),
        period=FIXTURE_PERIOD,
        source_cutoff_at=FIXTURE_KNOWN_AT,
    )
    page = await provider.get_rates(request)
    assert isinstance(page, ports.FxRatePage) and len(page.observations) == 40
    assert {row.rate for row in page.observations} == {Decimal("1.2"), Decimal("1.1")}
    assert all(row.base != row.quote for row in page.observations)
    missing = await provider.get_rates(
        replace(request, pairs=(ports.FxPair(base=CurrencyCode("GBP"), quote=CurrencyCode("USD")),))
    )
    assert (
        isinstance(missing, ports.SourceFailure)
        and missing.code is ports.SourceProviderError.UNSUPPORTED
    )


@pytest.mark.parametrize("basis", list(PriceBasis))
async def test_benchmark_replay_keeps_raw_provider_levels_and_explicit_basis(
    basis: PriceBasis,
) -> None:
    ctx = context()
    request = ports.BenchmarkSeriesRequest(
        series=next(
            s for s in ctx.series if s.kind is SourceSeriesKind.BENCHMARK_LEVEL and s.basis is basis
        ),
        period=FIXTURE_PERIOD,
        source_cutoff_at=FIXTURE_KNOWN_AT,
    )
    page = await ReplayBenchmarkProvider(ctx).get_series(request)
    assert isinstance(page, ports.BenchmarkSeriesPage)
    assert page.observations[0].level == Decimal("1000")
    assert page.observations[-1].level == Decimal(
        "1057" if basis is PriceBasis.TOTAL_RETURN else "1038"
    )


async def test_corporate_actions_and_enrichment_are_working_typed_operations() -> None:
    ctx = context()
    request = price_request(ctx)
    actions = await ReplayMarketPriceHistoryProvider(ctx).get_corporate_actions(
        ports.CorporateActionsRequest(
            series=request.series, period=request.period, source_cutoff_at=request.source_cutoff_at
        )
    )
    assert isinstance(actions, ports.CorporateActionPage) and len(actions.observations) == 2
    assert actions.observations[0].ratio == Decimal("2")
    assert actions.observations[1].amount == Decimal("0.5")
    provider = ReplayInstrumentEnrichmentProvider(ctx)
    for identifier in [
        SourceIdentifier(kind=SourceIdentifierKind.ISIN, value="XS0000000001"),
        SourceIdentifier(kind=SourceIdentifierKind.PROVIDER_KEY, value="SYNTHETIC_EQ_1"),
        SourceIdentifier(kind=SourceIdentifierKind.MIC_TICKER, value="SYNEQ", mic="XOFF"),
    ]:
        result = await provider.resolve_instrument(
            ports.InstrumentResolutionRequest(
                identifier=identifier, source_cutoff_at=FIXTURE_KNOWN_AT
            )
        )
        assert (
            isinstance(result, ports.InstrumentResolutionResult)
            and result.state is SourceMappingState.RESOLVED
        )
    unresolved = await provider.resolve_instrument(
        ports.InstrumentResolutionRequest(
            identifier=SourceIdentifier(kind=SourceIdentifierKind.PROVIDER_KEY, value="UNKNOWN"),
            source_cutoff_at=FIXTURE_KNOWN_AT,
        )
    )
    assert isinstance(unresolved, ports.InstrumentResolutionResult) and not unresolved.candidates
    classifications = await provider.get_classifications(
        ports.ClassificationRequest(
            instrument_ids=(str(build_synthetic_identity().instrument.id),),
            taxonomy="synthetic-taxonomy",
            taxonomy_version="1",
            source_cutoff_at=FIXTURE_KNOWN_AT,
        )
    )
    assert (
        isinstance(classifications, ports.ClassificationPage)
        and len(classifications.observations) == 4
    )
    fund = await ReplayETFConstituentProvider(ctx).get_constituents(
        ports.ConstituentRequest(
            fund_series_id=FUND_SERIES_ID,
            effective_at=FIXTURE_KNOWN_AT,
            source_cutoff_at=FIXTURE_KNOWN_AT,
        )
    )
    assert isinstance(fund, ports.ConstituentPage) and len(fund.holdings) == 3
    assert fund.stated_coverage + fund.unresolved_weight + fund.cash_weight == 1


async def test_replay_failure_mapping_and_cutoff_license_guards_precede_page_output() -> None:
    ctx = context(faults=(ReplayFault.TRANSIENT_FAILURE, ReplayFault.TRANSIENT_FAILURE))
    assert isinstance(
        await ReplayMarketPriceHistoryProvider(ctx).get_price_history(price_request(ctx)),
        ports.PriceHistoryPage,
    )
    assert len(ctx.runtime.attempts) == 3
    before = await ReplayMarketPriceHistoryProvider(ctx).get_price_history(
        replace(price_request(ctx), source_cutoff_at=FIXTURE_KNOWN_AT - timedelta(seconds=1))
    )
    assert (
        isinstance(before, ports.SourceFailure)
        and before.code is ports.SourceProviderError.NOT_FOUND
    )
    ctx.license = replace(ctx.license, store=LicensePermission.UNKNOWN)
    denied = await ReplayMarketPriceHistoryProvider(ctx).get_price_history(price_request(ctx))
    assert (
        isinstance(denied, ports.SourceFailure)
        and denied.code is ports.SourceProviderError.LICENSE_DENIED
    )
    assert len(ctx.runtime.attempts) == 3


async def test_unknown_signed_fields_are_minimized_before_semantic_hashing() -> None:
    payload = json.loads(
        files("trading212_reference_data").joinpath("fixtures/synthetic-v1.json").read_bytes()
    )
    payload["signed_location"] = "CANARY_REFERENCE_PRIVATE_VALUE"
    for row in payload["prices"]["raw_close"]:
        row["unknown_credential"] = "CANARY_REFERENCE_PRIVATE_VALUE"
    normal = context()
    extra = context(payload=json.dumps(payload).encode())
    first = await ReplayMarketPriceHistoryProvider(normal).get_price_history(price_request(normal))
    second = await ReplayMarketPriceHistoryProvider(extra).get_price_history(price_request(extra))
    assert isinstance(first, ports.PriceHistoryPage) and isinstance(second, ports.PriceHistoryPage)
    assert to_primitive(first) == to_primitive(second)
    assert "CANARY_REFERENCE_PRIVATE_VALUE" not in canonical_json(to_primitive(second))
    snapshots = [
        PriceSnapshot(
            id=page.series.id,
            owner_id=page.series.owner_id,
            series=page.series,
            provenance=page.provenance,
            period=page.period,
            coverage=page.coverage,
            observations=page.observations,
        )
        for page in (first, second)
    ]
    assert source_snapshot_digest(snapshots[0]) == source_snapshot_digest(snapshots[1])


async def test_unconfigured_external_provider_stays_unavailable_on_every_call() -> None:
    ctx = context()
    provider = UnconfiguredReferenceProviders()
    for _ in range(4):
        result = await provider.get_price_history(price_request(ctx))
        assert result.code is ports.SourceProviderError.NOT_CONFIGURED and not result.retryable
