"""Replay through the calculator keeps source proof, exclusions and money distinct."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Literal

import pytest
from trading212_analytics.scenario import calculate_scenario
from trading212_domain import historical as h
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError
from trading212_domain.scenario import (
    ScenarioAssumption,
    ScenarioExclusion,
    ScenarioInstrumentSelector,
    ScenarioReason,
    ScenarioSectorSelector,
    ScenarioVersionContent,
    scenario_exclusion_key,
)
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.scenario_serialization import (
    canonical_scenario_bytes,
    scenario_definition_digest,
    scenario_input_digest,
    scenario_result_digest,
    scenario_result_from_json,
)
from trading212_domain.sources import (
    FxSnapshot,
    PriceSnapshot,
    SourceCoverage,
    SourcePeriod,
    source_snapshot_digest,
)
from trading212_domain.values import Instant
from trading212_domain.xray import XrayDimension, XrayInput

from tests.unit.analytics.historical_factories import point_in_time, with_fx
from tests.unit.analytics.source_factories import USD
from tests.unit.analytics.source_factories import uid as sid
from tests.unit.analytics.test_scenario import available_money
from tests.unit.analytics.test_scenario_replay import _execution, _history, _xray
from tests.unit.analytics.xray_factories import uid

pytestmark = pytest.mark.unit
D = Decimal


def _with_definition(
    value: ScenarioExecutionInput, definition: ScenarioVersionContent
) -> ScenarioExecutionInput:
    value = replace(
        value,
        definition=definition,
        pins=replace(value.pins, scenario_version_digest=scenario_definition_digest(definition)),
    )
    return replace(value, input_digest=scenario_input_digest(value))


def _unknown_sector() -> tuple[XrayInput, ScenarioExclusion]:
    source = _xray()
    taxonomy = next(
        row for row in source.policy.taxonomy_versions if row.dimension is XrayDimension.SECTOR
    )
    source = replace(
        source,
        classification_batches=tuple(
            replace(
                batch,
                assignments=tuple(
                    row for row in batch.assignments if row.dimension is not XrayDimension.SECTOR
                ),
            )
            for batch in source.classification_batches
        ),
    )
    return source, ScenarioExclusion(
        selector=ScenarioSectorSelector(
            taxonomy_id=taxonomy.taxonomy_id,
            taxonomy_version=taxonomy.version,
            bucket_key="known",
        )
    )


def _then_known_history() -> h.HistoricalInput:
    value = _history()
    # Reuse the existing daily historical fixture on the explicitly registered total-return series.
    value = point_in_time(replace(value, price_snapshots=(value.price_snapshots[1],)))
    (original,) = value.fx_snapshots
    snapshots = tuple(
        replace(
            original,
            id=sid(7000 + index),
            provenance=replace(
                original.provenance,
                effective_at=row.effective_at,
                first_observed_at=row.effective_at,
            ),
            period=SourcePeriod(start=row.session_date, end=row.session_date),
            observations=(row,),
            coverage=SourceCoverage(
                expected_count=1, available_count=1, gaps=(), quality=QualityState.FRESH
            ),
        )
        for index, row in enumerate(original.observations)
    )
    return replace(
        value,
        fx_snapshots=snapshots,
        sources=(
            *(row for row in value.sources if row.kind != "fx_snapshot"),
            *(
                h.HistoricalSourceReference(
                    kind="fx_snapshot",
                    id=row.id,
                    effective_at=row.provenance.effective_at,
                    first_observed_at=row.provenance.first_observed_at,
                    semantic_digest=source_snapshot_digest(row),
                )
                for row in snapshots
            ),
        ),
    )


def _historical_xray(history: h.HistoricalInput) -> XrayInput:
    source = _xray()
    start = history.selection.window.start_at
    observed = Instant(start - timedelta(days=1))
    return replace(
        source,
        valuation_at=observed,
        source_cutoff_at=Instant(start),
        entity_evidence=tuple(
            replace(
                row,
                evidence=replace(row.evidence, effective_at=observed, first_known_at=observed),
            )
            for row in source.entity_evidence
        ),
        classification_batches=tuple(
            replace(
                row,
                evidence=replace(row.evidence, effective_at=observed, first_known_at=observed),
            )
            for row in source.classification_batches
        ),
    )


@pytest.mark.parametrize(
    "mode,post,interaction", [("compounded", "108", "-2"), ("first_order", "110", "0")]
)
def test_calculator_applies_local_and_fx_once_and_retains_exact_market_proof(
    mode: Literal["compounded", "first_order"],
    post: str,
    interaction: str,
) -> None:
    selected = _execution()
    selected = _with_definition(selected, replace(selected.definition, mode=mode))
    result = calculate_scenario(selected)
    (component,) = result.components
    assert component.partition == "covered"
    assert available_money(component.exposure.pre_value).amount == D("100")
    assert available_money(component.post_value).amount == D(post)
    assert available_money(component.effects.price).amount == D("20")
    assert available_money(component.effects.factor).amount == 0
    assert available_money(component.effects.fx).amount == D("-10")
    assert available_money(component.effects.interaction).amount == D(interaction)
    assert available_money(result.summary.post_value).amount == D(post)
    assert available_money(result.summary.rounding_residual).amount == 0
    assert result.replay is not None and selected.replay is not None
    (change,) = result.replay.changes
    assert change.path_key == component.exposure.path_key
    assert change.local_return.value == D(".2")
    assert change.fx_return.value == D("-.1")
    # This describes the observed reporting-currency change, even in the first-order approximation.
    assert change.reporting_return.value == D(".08")
    assert result.replay.context.input_digest == selected.replay.historical_input_digest
    uses = {row.use_key: row for row in result.replay.source_uses}
    conversions = {row.conversion_key: row for row in result.replay.conversions}
    assert set(change.source_use_keys) == set(uses)
    assert set(change.conversion_keys) == set(conversions)
    assert len(conversions) == 2
    for conversion in conversions.values():
        assert conversion.leg_use_keys
        for key in conversion.leg_use_keys:
            use = uses[key]
            assert use.kind == "observation" and use.source_kind == "fx"
            assert use.conversion_leg is not None
            assert use.conversion_leg.conversion_key == conversion.conversion_key
    assert (
        scenario_result_from_json(
            canonical_scenario_bytes(result), expected_digest=scenario_result_digest(result)
        )
        == result
    )


@pytest.mark.parametrize("market_available", [True, False])
def test_definite_exclusion_overrides_unknown_exclusion_and_keeps_market_proof(
    market_available: bool,
) -> None:
    source, uncertain = _unknown_sector()
    definite = ScenarioExclusion(selector=ScenarioInstrumentSelector(instrument_id=uid(6)))
    selected = _execution(_history(fx=market_available), source)
    selected = _with_definition(
        selected, replace(selected.definition, exclusions=(uncertain, definite))
    )
    result = calculate_scenario(selected)
    (component,) = result.components
    assert component.partition == "excluded"
    assert component.matching_exclusion_keys == (scenario_exclusion_key(definite),)
    assert component.uncertain_rule_keys == component.diagnostic_keys == ()
    assert available_money(component.post_value).amount == D("100")
    assert available_money(result.summary.excluded_post_value).amount == D("100")
    assert available_money(result.summary.impact).amount == 0
    assert result.replay is not None
    change = result.replay.changes[0]
    assert change.local_return.value == D(".2")
    assert change.reporting_return.value == (D(".08") if market_available else None)
    assert change.source_use_keys


@pytest.mark.parametrize("unchanged", [False, True])
def test_uncertain_exclusion_allows_complete_money_only_for_proved_zero_market_channels(
    unchanged: bool,
) -> None:
    source, uncertain = _unknown_sector()
    history = (
        with_fx(_history(fx=False, prices=("100",) * 4), ("1",) * 4, base=USD)
        if unchanged
        else _history()
    )
    selected = _execution(history, source)
    selected = _with_definition(selected, replace(selected.definition, exclusions=(uncertain,)))
    result = calculate_scenario(selected)
    (component,) = result.components
    assert component.partition == "uncovered"
    assert component.uncertain_rule_keys == (scenario_exclusion_key(uncertain),)
    assert any(row.reason is ScenarioReason.UNCERTAIN_EXCLUSION for row in result.diagnostics)
    assert result.replay is not None
    if unchanged:
        assert component.money_basis == "provably_zero_effect"
        assert available_money(result.summary.post_value).amount == D("100")
        assert available_money(result.summary.provably_unchanged_uncovered_value).amount == D("100")
        assert result.replay.changes[0].reporting_return.value == 0
    else:
        assert component.money_basis == "unavailable"
        assert result.summary.post_value.value is None
        assert component.effects.price.value is component.effects.fx.value is None
        assert result.replay.changes[0].reporting_return.value == D(".08")


def test_missing_fx_retains_local_evidence_without_complete_reporting_money() -> None:
    result = calculate_scenario(_execution(_history(fx=False)))
    (component,) = result.components
    assert component.partition == "uncovered"
    assert available_money(component.effects.price).amount == D("20")
    assert component.effects.fx.value is component.post_value.value is None
    assert result.summary.post_value.value is None
    assert result.replay is not None and result.replay.diagnostics
    issues = {row.key: row for row in result.diagnostics}
    assert all(row.key in issues for row in result.replay.diagnostics)
    assert set(component.diagnostic_keys) <= set(issues)
    assert all(row.path_key == component.exposure.path_key for row in result.replay.diagnostics)


def test_cash_replay_uses_retained_reporting_principal_and_historical_fx() -> None:
    result = calculate_scenario(_execution(source=_xray(cash=True)))
    (component,) = result.components
    # The saved USD25 cash was valued at EUR20. Historical USD/EUR fell 10%.
    assert available_money(component.exposure.pre_value).amount == D("20")
    assert available_money(component.post_value).amount == D("18")
    assert available_money(component.effects.price).amount == 0
    assert available_money(component.effects.fx).amount == D("-2")
    assert ScenarioAssumption.FIXED_CASH_BALANCE_REPLAY in result.assumptions
    assert result.replay is not None
    assert all(
        row.kind != "observation" or row.source_kind == "fx" for row in result.replay.source_uses
    )


def test_point_in_time_market_never_uses_later_known_batch_to_fill_opening_return() -> None:
    then_known = calculate_scenario(_execution(point_in_time=True))
    retrospective = calculate_scenario(_execution())
    assert then_known.summary.post_value.value is None
    assert then_known.replay is not None
    assert any(row.kind == "missing" for row in then_known.replay.source_uses)
    assert available_money(retrospective.summary.post_value).amount == D("108")


def test_actual_then_known_holdings_and_market_produce_exact_replay_with_no_lookahead() -> None:
    history = _then_known_history()
    source = _historical_xray(history)
    selected = _execution(history, source, point_in_time=True, historical_holdings=True)
    result = calculate_scenario(selected)
    assert available_money(result.summary.post_value).amount == D("108")
    assert result.replay is not None
    assert result.replay.holdings_evidence_at == source.valuation_at.value
    assert result.replay.holdings_knowledge_cutoff_at == source.source_cutoff_at.value
    assert result.replay.holdings_knowledge_cutoff_at <= history.selection.window.start_at
    source_snapshots: tuple[PriceSnapshot | FxSnapshot, ...] = (
        *history.price_snapshots,
        *history.fx_snapshots,
    )
    snapshots = {row.id: row for row in source_snapshots}
    for use in result.replay.source_uses:
        if use.kind == "observation":
            snapshot = snapshots[use.snapshot_id]
            assert snapshot.provenance.first_observed_at <= use.knowledge_cutoff_at <= use.use_at
            assert snapshot.observations[use.observation_index].effective_at <= use.use_at
    later = replace(
        source, source_cutoff_at=Instant(history.selection.window.start_at + timedelta(days=1))
    )
    with pytest.raises(DomainError, match="later knowledge cutoff"):
        calculate_scenario(_execution(history, later, point_in_time=True, historical_holdings=True))


def test_replay_rejects_saved_series_that_is_not_a_member_of_its_historical_instrument() -> None:
    history = _history()
    valid = _execution(history)
    assert valid.replay is not None
    history = replace(
        history,
        instruments=(
            replace(
                history.instruments[0], source_series_ids=(history.price_snapshots[0].series.id,)
            ),
        ),
    )
    selected = _execution(history)
    assert selected.replay is not None
    assert selected.replay.market_bindings[0].reason is ScenarioReason.MISSING_REPLAY_MAPPING
    # A forged private saved binding cannot bypass the actual retained membership.
    forged = replace(
        selected, replay=replace(selected.replay, market_bindings=valid.replay.market_bindings)
    )
    forged = replace(forged, input_digest=scenario_input_digest(forged))
    with pytest.raises(DomainError, match="membership"):
        calculate_scenario(forged)
