"""Risk history consumes real canonical fixture accounting and retained source selections."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from trading212_analytics.historical import calculate_performance
from trading212_analytics.risk_history import build_risk_history
from trading212_domain import Money
from trading212_domain import historical as d
from trading212_domain import historical_results as h
from trading212_domain.errors import DomainError
from trading212_domain.historical_serialization import historical_input_digest
from trading212_domain.risk import RiskDefinitionContent, RiskReason
from trading212_domain.risk_history import RiskAssetSource
from trading212_domain.sources import PriceBasis, source_snapshot_digest

from .historical_factories import START, fixture, identity, metric, with_events, with_fx
from .source_factories import EUR, USD, uid

D = Decimal
pytestmark = pytest.mark.unit


def definition(value: d.HistoricalInput, *, monthly: bool = False) -> RiskDefinitionContent:
    calendar = value.calendars[0]
    return RiskDefinitionContent(
        name="Risk history",
        description="Synthetic canonical source",
        calendar_id=calendar.id,
        calendar_version=calendar.version,
        frequency="monthly" if monthly else "daily",
    )


def test_session_returns_reuse_canonical_accounting_and_drawdown() -> None:
    value = fixture(("100", "110", "121", "133.1"))
    result = build_risk_history(value, definition(value))
    assert [item.simple_return for item in result.portfolio.intervals] == [D(".1"), D(".1")]
    assert all(item.end_at.hour == 16 for item in result.portfolio.intervals)
    assert (
        result.maximum_drawdown
        == calculate_performance(value, options=h.PerformanceOptions()).summary.maximum_drawdown
    )
    assert result.historical_input_digest == historical_input_digest(value)
    assert result.owner_id == value.owner_id and result.account_id == value.account_id
    assert result.source_uses and result.conversions


def test_monthly_boundaries_exclude_incomplete_last_month() -> None:
    value = fixture(("100",) * 100)
    result = build_risk_history(value, definition(value, monthly=True))
    assert [
        (item.start_at.date().isoformat(), item.end_at.date().isoformat())
        for item in result.portfolio.intervals
    ] == [("2025-01-31", "2025-02-28"), ("2025-02-28", "2025-03-31")]
    assert all(item.simple_return == 0 for item in result.portfolio.intervals)


def test_exact_flow_anchor_excludes_deposit_from_return() -> None:
    value = fixture(("100",) * 5)
    at = START + timedelta(days=1, hours=12)
    flow = d.HistoricalExternalFlow(
        identity=identity(100, at),
        kind="deposit",
        signed_amount=Money(D(100), EUR),
        scope_proof="account_boundary",
    )
    value = with_events(value, flow)
    assert isinstance(value.opening, d.ObservedHistoricalOpening)
    anchor = replace(
        value.opening.anchor,
        id=uid(52),
        at=at,
        positions=(replace(value.opening.anchor.positions[0], market_value=metric("100")),),
        cash=(Money(D(100), EUR),),
        source_refs=(uid(100),),
        reconciliation=replace(value.opening.anchor.reconciliation, anchor_refs=(uid(100),)),
    )
    anchored = replace(value, valuation_anchors=(anchor,))
    result = build_risk_history(anchored, definition(anchored))
    assert result.portfolio.intervals[0].simple_return == 0
    missing = build_risk_history(value, definition(value))
    assert missing.portfolio.intervals[0].simple_return is None
    assert d.HistoricalReason.TWR_FLOW_ANCHOR in missing.historical_warnings


def test_fx_changes_are_returns_and_missing_fx_is_unavailable() -> None:
    value = fixture(("100",) * 4, currency=USD)
    captured = with_fx(value, (".90", ".90", ".99", ".99"), base=USD)
    result = build_risk_history(captured, definition(captured))
    assert result.portfolio.intervals[0].simple_return == D(".10")
    missing = build_risk_history(value, definition(value))
    assert all(item.simple_return is None for item in missing.portfolio.intervals)


def test_raw_asset_price_is_not_silently_relabelled_total_return() -> None:
    value = fixture()
    mapping = RiskAssetSource(
        instrument_id=value.instruments[0].instrument_id,
        series_id=value.price_snapshots[0].series.id,
    )
    result = build_risk_history(value, definition(value), assets=(mapping,))
    assert all(item.simple_return is not None for item in result.portfolio.intervals)
    assert all(
        item.simple_return is None and item.reason is RiskReason.INCOMPATIBLE_BASIS
        for item in result.assets[0].intervals
    )


def test_total_return_asset_series_is_quantity_independent() -> None:
    value = fixture(("100", "110", "121", "133.1"), quantity="7")
    original = value.price_snapshots[0]
    source = replace(
        original,
        id=uid(2000),
        series=replace(original.series, id=uid(2001), basis=PriceBasis.TOTAL_RETURN),
    )
    value = replace(
        value,
        price_snapshots=(*value.price_snapshots, source),
        instruments=(
            replace(
                value.instruments[0],
                source_series_ids=(*value.instruments[0].source_series_ids, source.series.id),
            ),
        ),
        sources=(
            *value.sources,
            d.HistoricalSourceReference(
                kind="price_snapshot",
                id=source.id,
                effective_at=source.provenance.effective_at,
                first_observed_at=source.provenance.first_observed_at,
                semantic_digest=source_snapshot_digest(source),
            ),
        ),
    )
    mapping = RiskAssetSource(
        instrument_id=value.instruments[0].instrument_id, series_id=source.series.id
    )
    result = build_risk_history(value, definition(value), assets=(mapping,))
    assert [item.simple_return for item in result.assets[0].intervals] == [D(".1"), D(".1")]
    assert any(
        isinstance(use, h.HistoricalObservationUse) and use.snapshot_id == source.id
        for use in result.source_uses
    )


def test_wrong_calendar_or_asset_mapping_is_rejected() -> None:
    value = fixture()
    with pytest.raises(DomainError):
        build_risk_history(value, replace(definition(value), calendar_version="unknown"))
    mapping = RiskAssetSource(instrument_id=uid(9999), series_id=value.price_snapshots[0].series.id)
    with pytest.raises(DomainError):
        build_risk_history(value, definition(value), assets=(mapping,))


def test_future_fx_retrieval_cannot_cross_captured_cutoff() -> None:
    value = with_fx(fixture(("100",) * 4, currency=USD), (".9",) * 4, base=USD)
    original = value.fx_snapshots[0]
    future = replace(
        original,
        provenance=replace(
            original.provenance,
            first_observed_at=value.selection.window.source_cutoff_at + timedelta(days=1),
        ),
    )
    value = replace(
        value,
        fx_snapshots=(future,),
        sources=tuple(
            replace(
                item,
                first_observed_at=future.provenance.first_observed_at,
                semantic_digest=source_snapshot_digest(future),
            )
            if item.id == future.id
            else item
            for item in value.sources
        ),
    )
    result = build_risk_history(value, definition(value))
    assert all(item.simple_return is None for item in result.portfolio.intervals)
    assert not any(
        isinstance(item, h.HistoricalObservationUse) and item.snapshot_id == future.id
        for item in result.source_uses
    )


def test_missing_daily_observation_breaks_month_without_forward_fill() -> None:
    from trading212_domain.enums import QualityState
    from trading212_domain.sources import ObservationState, SourceCoverage, SourceGap, SourceReason

    value = fixture(("100",) * 100)
    original = value.price_snapshots[0]
    missing = original.observations[42]
    snapshot = replace(
        original,
        observations=tuple(
            replace(item, value=None, state=ObservationState.MISSING) if item == missing else item
            for item in original.observations
        ),
        coverage=SourceCoverage(
            expected_count=100,
            available_count=99,
            quality=QualityState.PARTIAL,
            gaps=(
                SourceGap(
                    session_date=missing.session_date,
                    source_key=original.series.provider_key,
                    reason=SourceReason.MISSING_SESSION,
                ),
            ),
        ),
    )
    value = replace(
        value,
        price_snapshots=(snapshot,),
        sources=tuple(
            replace(item, semantic_digest=source_snapshot_digest(snapshot))
            if item.id == snapshot.id
            else item
            for item in value.sources
        ),
    )
    result = build_risk_history(value, definition(value, monthly=True))
    assert result.portfolio.intervals[0].simple_return is None
    assert result.portfolio.intervals[1].simple_return == 0


def test_invalid_asset_reference_fails_before_canonical_calculation() -> None:
    from unittest.mock import patch

    value = fixture()
    mapping = RiskAssetSource(instrument_id=uid(9999), series_id=value.price_snapshots[0].series.id)
    with (
        patch("trading212_analytics.risk_history.performance") as calculate,
        pytest.raises(DomainError),
    ):
        build_risk_history(value, definition(value), assets=(mapping,))
    calculate.assert_not_called()


def test_combined_admission_includes_additional_asset_cells_before_valuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import trading212_analytics.risk_history as module

    value = fixture(("100",) * 22)
    asset = RiskAssetSource(
        instrument_id=value.instruments[0].instrument_id,
        series_id=value.price_snapshots[0].series.id,
    )
    from trading212_analytics._historical_core import HistoricalEngine

    monkeypatch.setattr(HistoricalEngine, "_preflight", lambda _: 99990)

    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("Combined oversized input reached valuation")

    monkeypatch.setattr(module, "performance", unexpected)
    with pytest.raises(DomainError):
        build_risk_history(value, definition(value), assets=(asset,))


def test_benchmark_intervals_use_retained_total_return_components() -> None:
    from .historical_factories import with_benchmark

    levels = ("100", "110", "121", "133.1")
    value = with_benchmark(fixture(levels), levels, levels)
    result = build_risk_history(value, definition(value))
    assert result.benchmark is not None
    assert [item.simple_return for item in result.benchmark.intervals] == [D(".1"), D(".1")]
    assert result.benchmark.source_cutoff_at == result.portfolio.source_cutoff_at
    assert any(
        isinstance(item, h.HistoricalObservationUse) and item.source_kind == "provider_benchmark"
        for item in result.source_uses
    )
