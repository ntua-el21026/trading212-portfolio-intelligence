from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_UP, Decimal, Inexact, Rounded, localcontext
from typing import Any

import pytest
from trading212_application.source_providers import (
    CorporateActionPage,
    FxPair,
    FxRatesRequest,
    PriceHistoryPage,
    PriceHistoryRequest,
    SourceCapability,
    SourceFailure,
    SourceProviderError,
)
from trading212_domain import DomainError, QualityState, canonical_json
from trading212_domain.source_details import (
    CorporateActionKind,
    CorporateActionObservation,
    CorporateActionSnapshot,
    SourceIdentifier,
    SourceIdentifierKind,
)
from trading212_domain.sources import (
    BenchmarkComponent,
    BenchmarkContent,
    BenchmarkRebalanceRule,
    BenchmarkSnapshot,
    BenchmarkSnapshotKind,
    LicensePermission,
    ObservationState,
    SourceCoverage,
    SourceLicense,
    SourcePeriod,
    SourceUse,
    normalize_benchmark_content,
    source_snapshot_digest,
)

from tests.unit.analytics.source_factories import AT, EUR, USD, price, provenance, series, uid

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "amount",
    [
        0,
        -1,
        True,
        0.1,
        "1e1",
        "01",
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("0.0000000000000000001"),
        Decimal("100000000000000000000"),
    ],
)
def test_source_observations_reject_invalid_financial_values(amount: Any) -> None:
    with pytest.raises(DomainError):
        replace(price().observations[0], value=amount)


def test_sources_reject_naive_time_and_excess_period_without_mutating_offset() -> None:
    original = price()
    with pytest.raises(DomainError):
        replace(original.provenance, first_observed_at=datetime(2026, 9, 4, 16))
    with pytest.raises(DomainError):
        SourcePeriod(start=date(2000, 1, 1), end=date(2011, 1, 1))
    with pytest.raises(DomainError):
        SourcePeriod(start=datetime(2026, 9, 4, tzinfo=UTC), end=date(2026, 9, 4))
    with pytest.raises(DomainError):
        SourcePeriod(start=date(2026, 9, 5), end=date(2026, 9, 4))


def test_snapshot_owner_mapping_kind_license_and_complete_coverage_cannot_disagree() -> None:
    original = price()
    for change in (
        {"owner_id": uid(8)},
        {"provenance": replace(original.provenance, license_version_id=uid(8))},
        {"series": series(benchmark=True)},
        {"observations": ()},
        {"observations": original.observations * 2},
    ):
        with pytest.raises(DomainError):
            replace(original, **change)
    with pytest.raises(DomainError):
        replace(original.series, mapping_id=None)
    with pytest.raises(DomainError):
        replace(series(benchmark=True), instrument_id=uid(8))
    with pytest.raises(DomainError):
        replace(original.observations[0], state=ObservationState.MISSING)


def test_semantic_digest_changes_with_economic_inputs_not_retrieval_or_order() -> None:
    original = price()
    assert source_snapshot_digest(original) == source_snapshot_digest(
        replace(
            original,
            id=uid(99),
            provenance=replace(original.provenance, first_observed_at=AT + timedelta(days=5)),
        )
    )
    assert source_snapshot_digest(original) != source_snapshot_digest(
        replace(
            original,
            provenance=replace(
                original.provenance, source_revision="corrected-2", revision_order=2
            ),
        )
    )
    assert source_snapshot_digest(original) != source_snapshot_digest(
        replace(original, series=replace(original.series, mapping_version="v2"))
    )
    assert "first_observed_at" in canonical_json(original)


def test_licenses_deny_unknown_use_and_require_explicit_retention() -> None:
    license = SourceLicense(
        id=uid(102),
        provider_id=uid(2),
        version="v1",
        effective_at=AT,
        store=LicensePermission.ALLOWED,
        display=LicensePermission.ALLOWED,
        report=LicensePermission.DENIED,
        export=LicensePermission.UNKNOWN,
        retention_days=30,
        attribution="Synthetic reference data",
        evidence_key="synthetic-fixture-license-v1",
    )
    assert license.permits(SourceUse.STORE) and license.permits(SourceUse.DISPLAY)
    assert not license.permits(SourceUse.REPORT) and not license.permits(SourceUse.EXPORT)
    with pytest.raises(DomainError):
        replace(license, retention_days=None)


def benchmark_content() -> BenchmarkContent:
    return BenchmarkContent(
        reporting_currency=EUR,
        effective_at=AT,
        return_basis=series().basis,
        calendar_id="synthetic-utc",
        calendar_version="v1",
        rebalance_rule=BenchmarkRebalanceRule.BUY_AND_HOLD,
        components=(
            BenchmarkComponent(source_id=uid(9), weight=Decimal("0.5")),
            BenchmarkComponent(source_id=uid(10), weight=Decimal("0.500000000000000001")),
        ),
    )


def test_benchmark_normalization_is_opt_in_exact_recorded_and_context_independent() -> None:
    content = benchmark_content()
    with pytest.raises(DomainError):
        normalize_benchmark_content(content)
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        normalized = normalize_benchmark_content(content, normalize=True)
    assert [x.weight for x in normalized.content.components] == [Decimal("0.5"), Decimal("0.5")]
    assert len(normalized.adjustments) == 1
    assert normalized.adjustments[0].source_id == uid(10)
    assert normalized.adjustments[0].original_weight == Decimal("0.500000000000000001")
    assert normalized.adjustments[0].normalized_weight == Decimal("0.5")
    assert normalize_benchmark_content(normalized.content).adjustments == ()
    assert (
        normalize_benchmark_content(
            replace(content, components=tuple(reversed(content.components))), normalize=True
        )
        == normalized
    )
    with pytest.raises(DomainError):
        normalize_benchmark_content(
            replace(
                content,
                components=(
                    replace(content.components[0], weight=Decimal("0.6")),
                    content.components[1],
                ),
            ),
            normalize=True,
        )


def test_provider_benchmark_snapshot_cannot_impersonate_future_composite() -> None:
    p = price()
    with pytest.raises(DomainError):
        BenchmarkSnapshot(
            id=uid(45),
            owner_id=p.owner_id,
            series=None,
            provenance=p.provenance,
            period=p.period,
            coverage=SourceCoverage(
                expected_count=0, available_count=0, gaps=(), quality=QualityState.FRESH
            ),
            observations=(),
            kind=BenchmarkSnapshotKind.COMPOSITE,
            benchmark_version_id=uid(46),
        )


def test_provider_requests_and_pages_are_bounded_and_kind_scoped() -> None:
    p = price()
    with pytest.raises(DomainError):
        PriceHistoryRequest(series=series(benchmark=True), period=p.period, source_cutoff_at=AT)
    with pytest.raises(DomainError):
        FxRatesRequest(
            provider_id=uid(2),
            license_version_id=uid(102),
            calendar_id="test-sessions",
            calendar_version="1",
            pairs=(FxPair(base=EUR, quote=USD),) * 2,
            period=p.period,
            source_cutoff_at=AT,
        )
    with pytest.raises(DomainError):
        PriceHistoryPage(
            series=p.series,
            provenance=p.provenance,
            period=p.period,
            coverage=p.coverage,
            observations=p.observations * 1001,
        )
    with pytest.raises(DomainError):
        PriceHistoryPage(
            series=p.series,
            provenance=replace(p.provenance, provider_id=uid(88)),
            period=p.period,
            coverage=p.coverage,
            observations=p.observations,
        )
    failure = SourceFailure(
        code=SourceProviderError.RATE_LIMITED,
        capability=SourceCapability.PRICE_HISTORY,
        provider_key="synthetic",
        retryable=True,
        retry_after_seconds=60,
    )
    assert failure.retryable and failure.retry_after_seconds == 60
    with pytest.raises(DomainError):
        replace(failure, code=SourceProviderError.LICENSE_DENIED)


def test_corporate_actions_preserve_sparse_coverage_and_same_day_distinct_events() -> None:
    stock = series()
    split = CorporateActionObservation(
        source_key="split-1",
        session_date=AT.date(),
        effective_at=AT,
        kind=CorporateActionKind.SPLIT,
        state=ObservationState.AVAILABLE,
        ratio=Decimal(2),
    )
    distribution = CorporateActionObservation(
        source_key="distribution-1",
        session_date=AT.date(),
        effective_at=AT,
        kind=CorporateActionKind.CASH_DISTRIBUTION,
        state=ObservationState.AVAILABLE,
        amount=Decimal("1.25"),
        currency=EUR,
    )
    coverage = SourceCoverage(
        expected_count=2, available_count=2, gaps=(), quality=QualityState.FRESH
    )
    page = CorporateActionPage(
        series=stock,
        provenance=provenance(),
        period=SourcePeriod(start=AT.date(), end=AT.date()),
        coverage=coverage,
        observations=(split, distribution),
    )
    snapshot = CorporateActionSnapshot(
        id=uid(77),
        owner_id=stock.owner_id,
        series=stock,
        provenance=page.provenance,
        period=page.period,
        coverage=coverage,
        observations=page.observations,
    )
    assert len(snapshot.observations) == 2
    assert source_snapshot_digest(snapshot) == source_snapshot_digest(
        replace(snapshot, observations=tuple(reversed(snapshot.observations)))
    )
    with pytest.raises(DomainError):
        replace(split, currency=EUR)
    with pytest.raises(DomainError):
        replace(distribution, amount=None)
    unsupported = replace(
        split, kind=CorporateActionKind.MERGER, state=ObservationState.UNSUPPORTED, ratio=None
    )
    assert unsupported.ratio is None and unsupported.target_instrument_id is None


def test_enrichment_identifier_kinds_do_not_accept_generic_provider_requests() -> None:
    value = SourceIdentifier(kind=SourceIdentifierKind.MIC_TICKER, value="SYNTH", mic="XNAS")
    assert value.mic == "XNAS"
    with pytest.raises(DomainError):
        replace(value, mic=None)
    with pytest.raises(DomainError):
        SourceIdentifier(kind=SourceIdentifierKind.PROVIDER_KEY, value="synthetic", mic="XNAS")
