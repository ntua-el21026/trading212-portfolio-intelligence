"""Counterfactual replay channels from the complete retained historical source proof."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from trading212_domain import historical as h
from trading212_domain import historical_results as hr
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError, ErrorCode, fail_validation
from trading212_domain.historical_serialization import historical_input_digest
from trading212_domain.historical_validation import validate_historical_input
from trading212_domain.scenario import ScenarioReason
from trading212_domain.scenario_execution import (
    ScenarioExecutionInput,
    ScenarioReplayInput,
    ScenarioReplayMarketBinding,
    ScenarioReplaySelection,
)
from trading212_domain.scenario_exposure import extract_scenario_exposures
from trading212_domain.scenario_result import (
    ScenarioDiagnostic,
    ScenarioRatioMetric,
    ScenarioReplayChange,
    ScenarioReplayProof,
    ScenarioTerminalExposure,
)
from trading212_domain.scenario_serialization import encode_scenario_execution
from trading212_domain.sources import PriceBasis, SourceSeries
from trading212_domain.values import CurrencyCode
from trading212_domain.xray import XrayInput
from trading212_domain.xray_result import XrayCalculation

from ._historical_core import HistoricalEngine, financial
from ._premium_numeric import ONE, ZERO, arithmetic, q18


@dataclass(frozen=True, slots=True)
class ScenarioReplayChannels:
    path_key: str
    price: Decimal | None
    fx: Decimal | None
    reasons: tuple[ScenarioReason | None, ScenarioReason | None, ScenarioReason | None]


@dataclass(frozen=True, slots=True)
class ScenarioReplayMaterial:
    proof: ScenarioReplayProof
    channels: tuple[ScenarioReplayChannels, ...]


@dataclass(frozen=True, slots=True)
class _MarketChange:
    local: Decimal | None
    fx: Decimal | None
    local_reason: ScenarioReason | None
    fx_reason: ScenarioReason | None
    uses: tuple[str, ...] = ()
    conversions: tuple[str, ...] = ()


def resolve_scenario_replay(
    selection: ScenarioReplaySelection,
    historical_input: h.HistoricalInput,
    xray_input: XrayInput,
    xray_result: XrayCalculation,
) -> ScenarioReplayInput:
    """Resolve only unambiguous immutable membership, after caller source authorization."""
    validate_historical_input(historical_input)
    if (historical_input.owner_id, historical_input.account_id) != (
        str(xray_input.owner_id),
        str(xray_input.account_id),
    ):
        fail_validation("Scenario replay source ownership differs.")
    exposures = extract_scenario_exposures(xray_input, xray_result)
    instruments = sorted(
        {item.instrument.subject_id for item in exposures if item.instrument.subject_id is not None}
    )
    if len(instruments) > 256:
        raise DomainError(
            ErrorCode.INPUT_BOUND_EXCEEDED, "Scenario replay mapping capacity exceeded."
        )
    bindings = []
    for instrument in instruments:
        selected_ids = {
            series_id
            for item in historical_input.instruments
            if item.instrument_id == str(instrument)
            for series_id in item.source_series_ids
        }
        candidates: dict[str, SourceSeries] = {}
        references: dict[str, set[str]] = {}
        for snapshot in historical_input.price_snapshots:
            series = snapshot.series
            if series.id not in selected_ids or series.basis is not PriceBasis.TOTAL_RETURN:
                continue
            if (
                series.instrument_id != str(instrument)
                or candidates.setdefault(series.id, series) != series
            ):
                fail_validation("Replay instrument-series membership conflicts.")
            references.setdefault(series.id, set()).add(snapshot.id)
        if len(candidates) == 1:
            series = next(iter(candidates.values()))
            binding = ScenarioReplayMarketBinding(
                instrument_id=instrument,
                local_series_id=UUID(series.id),
                local_currency=series.currency,
                response_basis="local_total_return",
                reason=None,
                source_reference_ids=tuple(sorted(references[series.id])),
            )
        else:
            binding = ScenarioReplayMarketBinding(
                instrument_id=instrument,
                local_series_id=None,
                local_currency=None,
                response_basis="unavailable",
                reason=ScenarioReason.AMBIGUOUS_REPLAY_MAPPING
                if candidates
                else ScenarioReason.MISSING_REPLAY_MAPPING,
                source_reference_ids=tuple(
                    sorted({ref for refs in references.values() for ref in refs})
                ),
            )
        bindings.append(binding)
    return ScenarioReplayInput(
        selection=selection,
        historical_input=historical_input,
        historical_input_digest=historical_input_digest(historical_input),
        market_bindings=tuple(bindings),
        holdings_evidence_at=xray_input.valuation_at.value,
        holdings_knowledge_cutoff_at=xray_input.source_cutoff_at.value,
    )


def _ratio(value: Decimal | None, reason: ScenarioReason | None) -> ScenarioRatioMetric:
    return ScenarioRatioMetric(
        value=None if value is None else q18(value),
        quality=QualityState.PARTIAL if value is None else QualityState.ESTIMATED,
        reason=reason if value is None else None,
    )


def _change(opening: Decimal | None, closing: Decimal | None) -> Decimal | None:
    if opening is None or opening <= ZERO or closing is None:
        return None
    with arithmetic():
        result = closing / opening - ONE
        if not -ONE <= result <= Decimal(5):
            raise DomainError(
                ErrorCode.DATA_UNAVAILABLE,
                "Replay channel exceeds the supported scenario range.",
                "scenario.replay.channel",
            )
        return result


def _series(value: h.HistoricalInput, binding: ScenarioReplayMarketBinding) -> SourceSeries | None:
    if binding.response_basis != "local_total_return" or binding.local_series_id is None:
        return None
    sources = tuple(
        item for item in value.price_snapshots if item.series.id == str(binding.local_series_id)
    )
    if not sources:
        return None
    series = sources[0].series
    if any(item.series != series for item in sources) or (
        series.instrument_id != str(binding.instrument_id)
        or series.currency != binding.local_currency
        or not any(
            item.instrument_id == str(binding.instrument_id) and series.id in item.source_series_ids
            for item in value.instruments
        )
        or not {item.id for item in sources} <= set(binding.source_reference_ids)
        or not set(binding.source_reference_ids) <= {item.id for item in value.sources}
    ):
        fail_validation("Replay local-series membership differs from captured source proof.")
    return series if series.basis is PriceBasis.TOTAL_RETURN else None


def _market(
    engine: HistoricalEngine,
    binding: ScenarioReplayMarketBinding | None,
    currency: CurrencyCode | None,
    *,
    cash: bool,
) -> _MarketChange:
    unavailable = ScenarioReason.MISSING_REPLAY_MAPPING
    if cash:
        series = None
        consumer = hr.HistoricalUseConsumer(kind="cash")
    elif binding is None:
        return _MarketChange(None, None, unavailable, unavailable)
    elif binding.response_basis == "reporting_total_return":
        reason = ScenarioReason.FX_DECOMPOSITION_UNAVAILABLE
        return _MarketChange(None, None, reason, reason)
    else:
        series = _series(engine.value, binding)
        if series is None:
            reason = binding.reason or ScenarioReason.MISSING_REPLAY_SOURCE
            return _MarketChange(None, None, reason, reason)
        consumer = hr.HistoricalUseConsumer(
            kind="benchmark", component_source_id=series.id, instrument_id=series.instrument_id
        )
    if currency is None:
        return _MarketChange(
            ZERO if cash else None,
            None,
            None if cash else ScenarioReason.MISSING_ECONOMIC_CURRENCY,
            ScenarioReason.MISSING_ECONOMIC_CURRENCY,
        )
    if series is not None and series.currency != currency:
        reason = ScenarioReason.INCOMPATIBLE_BASIS
        return _MarketChange(None, None, reason, reason)
    uses_before, conversions_before = set(engine.uses), set(engine.conversions)
    endpoints = (engine.window.start_at, engine.window.end_at)
    local: Decimal | None = ZERO
    if series is not None:
        levels = []
        for instant in endpoints:
            engine._cell(series.id, instant)
            value = engine.price(
                series.id, instant, consumer, "benchmark_component", benchmark=True
            )
            if value is not None:
                engine.successful_cells.add((series.id, instant))
            levels.append(value)
        local = _change(levels[0], levels[1])
    fx = _change(
        *(engine.fx(currency, instant, consumer, "benchmark_component") for instant in endpoints)
    )
    return _MarketChange(
        local,
        fx,
        ScenarioReason.MISSING_REPLAY_SOURCE if local is None else None,
        ScenarioReason.MISSING_REPLAY_SOURCE if fx is None else None,
        tuple(sorted(set(engine.uses) - uses_before)),
        tuple(sorted(set(engine.conversions) - conversions_before)),
    )


def _holdings(value: ScenarioExecutionInput) -> None:
    replay = value.replay
    assert replay is not None
    if (
        replay.holdings_evidence_at != value.xray_input.valuation_at.value
        or replay.holdings_knowledge_cutoff_at != value.xray_input.source_cutoff_at.value
    ):
        fail_validation("Replay holdings dates must equal the actual saved X-ray basis.")
    if replay.selection.holdings_basis == "historical_holdings":
        start = replay.historical_input.selection.window.start_at
        if replay.holdings_evidence_at > start:
            fail_validation("Historical replay requires an actual then-dated holdings snapshot.")
        if (
            replay.selection.knowledge_basis == "point_in_time"
            and replay.holdings_knowledge_cutoff_at > start
        ):
            fail_validation("Then-known historical holdings cannot use a later knowledge cutoff.")


@financial
def build_scenario_replay(
    value: ScenarioExecutionInput, exposures: tuple[ScenarioTerminalExposure, ...]
) -> ScenarioReplayMaterial:
    """Reuse fixed historical selectors and their original UTC boundary/cutoff policy.

    This reprices a retained terminal partition. It never reconstructs owner holdings
    or treats portfolio cash flows as returns. Explicit cash keeps its principal;
    interest is outside this fixed-balance replay assumption.
    """
    encode_scenario_execution(value)
    replay = value.replay
    if replay is None or value.definition.shocks:
        fail_validation("Replay requires saved historical input and no hypothetical shocks.")
    if exposures != extract_scenario_exposures(value.xray_input, value.xray_result):
        fail_validation("Replay exposures differ from the saved canonical terminal partition.")
    _holdings(value)
    validate_historical_input(replay.historical_input)
    engine = HistoricalEngine(replay.historical_input)
    if (
        engine.preflight_cell_bound + 4 * (len(replay.market_bindings) + 32)
        > h.MAX_HISTORICAL_CELLS
    ):
        raise DomainError(ErrorCode.INPUT_BOUND_EXCEEDED, "Scenario replay work capacity exceeded.")
    bindings = {item.instrument_id: item for item in replay.market_bindings}
    for binding in bindings.values():
        _series(replay.historical_input, binding)
    cache: dict[tuple[UUID | None, CurrencyCode | None, bool], _MarketChange] = {}
    changes: list[ScenarioReplayChange] = []
    channels: list[ScenarioReplayChannels] = []
    diagnostics: list[ScenarioDiagnostic] = []
    for exposure in exposures:
        instrument = exposure.instrument.subject_id
        currency = exposure.economic_currency.currency
        cache_key = (instrument, currency, exposure.explicit_cash)
        if cache_key not in cache:
            cache[cache_key] = _market(
                engine,
                bindings.get(instrument) if instrument is not None else None,
                currency,
                cash=exposure.explicit_cash,
            )
        market = cache[cache_key]
        with arithmetic():
            reporting = (
                None
                if market.local is None or market.fx is None
                else (ONE + market.local) * (ONE + market.fx) - ONE
            )
        changes.append(
            ScenarioReplayChange(
                path_key=exposure.path_key,
                local_return=_ratio(market.local, market.local_reason),
                fx_return=_ratio(market.fx, market.fx_reason),
                reporting_return=_ratio(reporting, market.local_reason or market.fx_reason),
                basis="unavailable" if reporting is None else "local_with_fx",
                source_use_keys=market.uses,
                conversion_keys=market.conversions,
            )
        )
        channels.append(
            ScenarioReplayChannels(
                exposure.path_key,
                market.local,
                market.fx,
                (market.local_reason, None, market.fx_reason),
            )
        )
        for reason in sorted({r for r in (market.local_reason, market.fx_reason) if r is not None}):
            key = "replay:" + sha256((exposure.path_key + ":" + reason.value).encode()).hexdigest()
            diagnostics.append(
                ScenarioDiagnostic(
                    key=key,
                    reason=reason,
                    path_key=exposure.path_key,
                    rule_key=None,
                    upstream_xray_reason=exposure.upstream_reason,
                    upstream_historical_reason=None,
                    source_reference_ids=exposure.source_reference_ids,
                    source_use_keys=market.uses,
                )
            )
    available = sum(item.basis == "local_with_fx" for item in changes)
    proof = ScenarioReplayProof(
        selection=replay.selection,
        context=engine.context(
            "scenario_replay_v1", available=bool(available), partial=available < len(changes)
        ),
        changes=tuple(changes),
        source_uses=engine.ordered_uses(),
        conversions=engine.ordered_conversions(),
        holdings_evidence_at=replay.holdings_evidence_at,
        holdings_knowledge_cutoff_at=replay.holdings_knowledge_cutoff_at,
        diagnostics=tuple(sorted(diagnostics, key=lambda item: item.key)),
    )
    return ScenarioReplayMaterial(proof, tuple(channels))
