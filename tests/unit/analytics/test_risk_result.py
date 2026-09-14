"""Integrated risk estimates with independent concentration and weight references."""

import json
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
from uuid import UUID

import pytest
from trading212_analytics._premium_numeric import arithmetic, modeled_risk_from_values
from trading212_analytics.risk import _concentration, _model, calculate_risk
from trading212_analytics.xray import calculate_xray
from trading212_domain import historical as d
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError
from trading212_domain.historical_serialization import (
    historical_canonical_bytes,
    historical_value_from_json,
)
from trading212_domain.risk import RiskMetric, RiskReason
from trading212_domain.risk_history import RiskAssetSource
from trading212_domain.risk_result import RiskCalculation
from trading212_domain.risk_serialization import risk_result_digest, risk_result_from_json
from trading212_domain.sources import PriceBasis, source_snapshot_digest

from .historical_factories import fixture
from .source_factories import uid
from .test_risk_history import definition
from .xray_factories import CUTOFF, Builder
from .xray_factories import fixture as xray_fixture
from .xray_factories import uid as xid

D = Decimal
pytestmark = pytest.mark.unit


def source_fixture() -> tuple[d.HistoricalInput, RiskAssetSource]:
    value = fixture(("100", "110") * 61)
    original = value.price_snapshots[0]
    source = replace(
        original,
        id=uid(2000),
        series=replace(original.series, id=uid(2001), basis=PriceBasis.TOTAL_RETURN),
    )
    value = replace(
        value,
        selection=replace(
            value.selection, window=replace(value.selection.window, source_cutoff_at=CUTOFF.value)
        ),
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
    return value, RiskAssetSource(
        instrument_id=value.instruments[0].instrument_id, series_id=source.series.id
    )


def test_integrated_zero_observed_risk_keeps_unavailable_models_and_tail() -> None:
    value = fixture(("100",) * 22)
    result = calculate_risk(value, definition(value))
    assert result.observed.used_observations == 20
    assert result.observed.volatility_annualized.value == 0
    assert result.parametric_tail.value_at_risk.value == 0
    assert result.historical_tail.value_at_risk.reason is RiskReason.INSUFFICIENT_TAIL
    assert result.modeled.volatility_annualized.reason is RiskReason.INCOMPLETE_UNIVERSE
    assert result.concentration.effective_holdings.reason is RiskReason.INCOMPLETE_UNIVERSE
    assert result.matrix.keys == ()
    encoded = historical_canonical_bytes(result)
    assert historical_value_from_json(encoded, RiskCalculation) == result
    assert risk_result_digest(result) == risk_result_digest(
        calculate_risk(value, definition(value))
    )


def test_canonical_total_return_matrix_and_complete_current_weight_model() -> None:
    value, mapping = source_fixture()
    builder = Builder()
    instrument = UUID(mapping.instrument_id)
    builder.position(instrument, "100", position_id=xid(8000))
    builder.position(instrument, "200", position_id=xid(8001))
    builder.identity(instrument, xid(9000))
    original = builder.finish()
    xray_input = replace(
        original,
        owner_id=UUID(value.owner_id),
        account_id=UUID(value.account_id),
        source_dependencies=tuple(
            replace(item, owner_id=UUID(value.owner_id), account_id=UUID(value.account_id))
            for item in original.source_dependencies
        ),
    )
    xray = calculate_xray(xray_input)
    result = calculate_risk(value, definition(value), assets=(mapping,), xray=xray)
    assert result.matrix.used_intervals == 120
    assert result.matrix.correlation[0][0].value == 1
    assert result.modeled.complete_universe and result.modeled.coverage.value == 1
    assert result.modeled.components[0].weight.value == 1
    assert result.modeled.components[0].component_annualized == result.modeled.volatility_annualized
    assert result.modeled.diversification_ratio.value == 1
    assert result.modeled.component_display_residual.value == 0
    assert result.modeled.weight_display_residual.value == 0
    assert (
        result.concentration.hhi.value == 1 and result.concentration.effective_holdings.value == 1
    )
    assert result.portfolio_snapshot_id == str(xray.snapshot_id)
    assert result.modeled_valuation_at == xray.valuation_at.value
    assert result.xray_result_digest == xray.content_digest
    returns = [
        Fraction(item.simple_return)
        for item in result.history.assets[0].intervals
        if item.simple_return is not None
    ]
    mean = sum(returns, Fraction(0)) / len(returns)
    variance = sum(((item - mean) ** 2 for item in returns), Fraction(0)) / (len(returns) - 1)
    with localcontext() as ctx:
        ctx.prec = 160
        sigma = (D(variance.numerator) / D(variance.denominator) * 252).sqrt().quantize(D("1e-18"))
    assert result.modeled.volatility_annualized.value == sigma
    assert result.historical_tail.value_at_risk.value == D(".090909090909090909")
    assert result.historical_tail.expected_shortfall == result.historical_tail.value_at_risk
    assert historical_value_from_json(historical_canonical_bytes(result), RiskCalculation) == result


def test_cash_or_unselected_material_position_never_renormalizes() -> None:
    builder = Builder()
    builder.position(xid(10), "50")
    builder.identity(xid(10), xid(110))
    builder.cash_row("50")
    xray = calculate_xray(builder.finish())
    with arithmetic():
        result = _model((str(xid(10)),), ((D(".01"),),), xray, 252)
    assert result.coverage.value == D(".5")
    assert result.components[0].weight.value == D(".5")
    assert not result.complete_universe
    assert result.volatility_annualized.reason is RiskReason.INCOMPLETE_UNIVERSE
    assert result.component_sum.value is None
    assert result.weight_display_residual.value is None


def test_thirds_preserve_weight_and_euler_publication_residuals() -> None:
    builder = Builder()
    keys = tuple(str(xid(i)) for i in (10, 20, 30))
    for i in (10, 20, 30):
        builder.position(xid(i), "1")
        builder.identity(xid(i), xid(i + 100))
    covariance = tuple(tuple(D(".01") if i == j else D(0) for j in range(3)) for i in range(3))
    with arithmetic():
        result = _model(keys, covariance, calculate_xray(builder.finish()), 252)
    assert result.complete_universe
    assert all(row.weight.value == D(".333333333333333333") for row in result.components)
    assert result.weight_display_residual.value == D(".000000000000000001")
    with localcontext() as ctx:
        ctx.prec = 160
        sigma = (D(".01") * 252 / 3).sqrt()
        expected = sigma.quantize(D("1e-18"))
        component = (sigma / 3).quantize(D("1e-18"))
    assert result.volatility_annualized.value == expected
    assert result.component_sum.value == 3 * component
    assert result.component_display_residual.value == expected - 3 * component


def test_concentration_reuses_direct_plus_indirect_partition_and_lower_bound() -> None:
    result = _concentration(calculate_xray(xray_fixture()))
    # 200 direct + 300 + 60 indirect = 560; second issuer = 150 + 240 = 390.
    assert result.hhi.value == D(".56") ** 2 + D(".39") ** 2
    assert result.company_known_weight.value == D(".95")
    assert result.unresolved_weight.value == D(".05")
    assert result.lower_bound and result.effective_holdings.value is None
    assert result.effective_holdings.reason is RiskReason.INCOMPLETE_UNIVERSE


def test_concentration_effective_holdings_is_not_inverse_of_rounded_hhi() -> None:
    builder = Builder()
    for i in (10, 20, 30):
        builder.position(xid(i), "1")
        builder.identity(xid(i), xid(100 + i))
    result = _concentration(calculate_xray(builder.finish()))
    assert result.hhi.value == D(".333333333333333333")
    assert result.effective_holdings.value == 3
    assert not result.lower_bound


def test_zero_covariance_has_zero_volatility_but_undefined_risk_contributions() -> None:
    estimate = modeled_risk_from_values(((D(0),),), (D(7),), 12)
    assert (
        estimate.volatility == 0
        and estimate.components is None
        and estimate.diversification is None
    )


@pytest.mark.parametrize(
    "field", ("owner_id", "account_id", "reporting_currency", "source_cutoff_at")
)
def test_foreign_or_incompatible_xray_fails_before_history_calculation(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import trading212_analytics.risk as module
    from trading212_domain.values import CurrencyCode, Instant

    value = fixture(("100",) * 22)
    source = calculate_xray(xray_fixture())
    source = replace(
        source,
        owner_id=UUID(value.owner_id),
        account_id=UUID(value.account_id),
        source_cutoff_at=Instant(value.selection.window.source_cutoff_at),
    )
    replacement = {
        "owner_id": xid(9999),
        "account_id": xid(9999),
        "reporting_currency": CurrencyCode("USD"),
        "source_cutoff_at": CUTOFF,
    }[field]
    source = replace(source, **{field: replacement})  # type: ignore[arg-type]

    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("Invalid source scope reached calculation")

    monkeypatch.setattr(module, "build_risk_history", unexpected)
    with pytest.raises(DomainError):
        calculate_risk(value, definition(value), xray=source)


def test_unavailable_history_keeps_original_missing_reason_and_context() -> None:
    value = fixture(("100",) * 22)
    result = calculate_risk(value, definition(value))
    with pytest.raises(DomainError):
        replace(result.history, account_id=uid(7777))
    with pytest.raises(DomainError):
        replace(result.matrix, omitted_intervals=True)
    with pytest.raises(DomainError):
        replace(result.modeled, volatility_annualized=RiskMetric(value=D(1)))
    assert result.history.canonical_performance_context.reconstruction == "restated"
    assert result.history.portfolio.intervals[0].quality is QualityState.FRESH


@pytest.mark.parametrize(
    "mutation", ("unknown", "float", "boolean", "source", "value", "duplicate", "method")
)
def test_private_codec_rejects_shape_and_source_tampering(mutation: str) -> None:
    value = fixture(("100",) * 22)
    result = calculate_risk(value, definition(value))
    encoded = historical_canonical_bytes(result)
    digest = risk_result_digest(result)
    assert risk_result_from_json(encoded, expected_digest=digest) == result
    raw = json.loads(encoded)
    if mutation == "unknown":
        raw["execute"] = "forbidden"
    elif mutation == "float":
        raw["observed"]["volatility_periodic"]["value"] = 0.125
    elif mutation == "boolean":
        raw["matrix"]["requested_intervals"] = False
    elif mutation == "source":
        raw["history"]["historical_input_digest"] = "b" * 64
    elif mutation == "value":
        raw["observed"]["volatility_periodic"]["value"] = "0.125"
    elif mutation == "method":
        raw["numerical_profile"] = "future_profile"
    if mutation == "duplicate":
        altered = encoded.decode().replace('"family":"risk"', '"family":"risk","family":"risk"')
    else:
        altered = json.dumps(raw)
    with pytest.raises(DomainError):
        risk_result_from_json(altered, expected_digest=digest)
