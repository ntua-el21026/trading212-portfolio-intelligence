"""Independent endpoint returns and saved-source replay boundary regressions."""

from dataclasses import replace
from datetime import timedelta
from decimal import ROUND_DOWN, Context, Decimal, Inexact, Rounded, localcontext
from uuid import UUID

import pytest
from trading212_analytics.scenario_replay import (
    ScenarioReplayMaterial,
    build_scenario_replay,
    resolve_scenario_replay,
)
from trading212_analytics.xray import convert_xray_money
from trading212_domain import historical as h
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.scenario import ScenarioReason
from trading212_domain.scenario_execution import ScenarioExecutionInput, ScenarioReplaySelection
from trading212_domain.scenario_exposure import extract_scenario_exposures
from trading212_domain.scenario_serialization import scenario_input_digest
from trading212_domain.sources import PriceBasis, source_snapshot_digest
from trading212_domain.values import Instant, Money
from trading212_domain.xray import XrayDimension, XrayInput, XrayLicensedFx

from tests.unit.analytics.historical_factories import fixture as historical_fixture
from tests.unit.analytics.historical_factories import with_fx
from tests.unit.analytics.source_factories import EUR, USD
from tests.unit.analytics.source_factories import uid as sid
from tests.unit.analytics.xray_factories import Builder, uid
from tests.unit.domain.scenario_factories import execution

D = Decimal
pytestmark = pytest.mark.unit


def _history(
    *, fx: bool = True, indices: int = 1, prices: tuple[str, ...] = ("100", "100", "110", "120")
) -> h.HistoricalInput:
    value = replace(historical_fixture(prices, currency=USD), account_id=sid(2))
    if fx:
        value = with_fx(value, ("1", "1", ".95", ".9"), base=USD)
    base = value.price_snapshots[0]
    additions = tuple(
        replace(
            base,
            id=sid(2000 + i),
            series=replace(base.series, id=sid(3000 + i), basis=PriceBasis.TOTAL_RETURN),
        )
        for i in range(indices)
    )
    return replace(
        value,
        price_snapshots=(*value.price_snapshots, *additions),
        instruments=(
            replace(
                value.instruments[0],
                source_series_ids=(
                    *value.instruments[0].source_series_ids,
                    *(item.series.id for item in additions),
                ),
            ),
        ),
        sources=(
            *value.sources,
            *(
                h.HistoricalSourceReference(
                    kind="price_snapshot",
                    id=item.id,
                    effective_at=item.provenance.effective_at,
                    first_observed_at=item.provenance.first_observed_at,
                    semantic_digest=source_snapshot_digest(item),
                )
                for item in additions
            ),
        ),
    )


def _xray(*, cash: bool = False) -> XrayInput:
    builder = Builder()
    if cash:
        builder.cash_row("25")
        row = builder.cash[0]
        original = replace(row.original_value, value=Money.parse("25", USD))
        leg = builder.fx_leg(USD, EUR, ".8")
        builder.cash[0] = replace(
            row,
            root=replace(row.root, original_currency=USD),
            original_value=original,
            reporting_value=convert_xray_money(original, EUR, legs=(leg,)),
            fx_refs=(leg.source_reference_id,),
        )
        builder.licensed_fx.append(XrayLicensedFx(row.root.key, original, EUR, (leg,)))
    else:
        builder.position(uid(6), "100")
        builder.identity(uid(6), uid(106))
        builder.classifications_for(uid(106))
        builder.classifications[0] = replace(
            builder.classifications[0],
            assignments=tuple(
                replace(item, bucket_key="USD")
                if item.dimension is XrayDimension.CURRENCY
                else item
                for item in builder.classifications[0].assignments
            ),
        )
    return builder.finish()


def _execution(
    history: h.HistoricalInput | None = None,
    source: XrayInput | None = None,
    *,
    point_in_time: bool = False,
    historical_holdings: bool = False,
) -> ScenarioExecutionInput:
    value = execution(_xray() if source is None else source)
    history = _history() if history is None else history
    if point_in_time:
        history = replace(
            history,
            selection=replace(
                history.selection,
                window=replace(
                    history.selection.window, knowledge_policy=h.KnowledgePolicy.POINT_IN_TIME
                ),
            ),
        )
    window = history.selection.window
    selection = ScenarioReplaySelection(
        historical_input_snapshot_id=uid(8000),
        start_date=window.start_date,
        end_date=window.end_date,
        market_knowledge_cutoff_at=window.source_cutoff_at,
        knowledge_basis="point_in_time" if point_in_time else "retrospective",
        holdings_basis="historical_holdings" if historical_holdings else "current_holdings",
    )
    replay = resolve_scenario_replay(selection, history, value.xray_input, value.xray_result)
    value = replace(value, replay=replay)
    return replace(value, input_digest=scenario_input_digest(value))


def _material(value: ScenarioExecutionInput) -> ScenarioReplayMaterial:
    return build_scenario_replay(
        value, extract_scenario_exposures(value.xray_input, value.xray_result)
    )


def test_local_total_return_and_fx_are_separate_and_not_double_applied() -> None:
    result = _material(_execution())
    (change,) = result.proof.changes
    assert (change.local_return.value, change.fx_return.value, change.reporting_return.value) == (
        D(".2"),
        D("-.1"),
        D(".08"),
    )
    assert result.channels[0].price == D(".2") and result.channels[0].fx == D("-.1")
    assert change.source_use_keys and len(change.conversion_keys) == 2
    assert all(
        use.snapshot_id in (sid(2000), sid(30))
        for use in result.proof.source_uses
        if use.kind == "observation"
    )
    execution = _execution()
    assert execution.replay is not None
    assert result.proof.context.input_digest == execution.replay.historical_input_digest


def test_missing_fx_keeps_local_change_but_never_assumes_one() -> None:
    result = _material(_execution(_history(fx=False)))
    change = result.proof.changes[0]
    assert change.local_return.value == D(".2")
    assert change.fx_return.value is change.reporting_return.value is None
    assert change.basis == "unavailable" and result.proof.diagnostics


@pytest.mark.parametrize(
    "indices,reason",
    [(0, ScenarioReason.MISSING_REPLAY_MAPPING), (2, ScenarioReason.AMBIGUOUS_REPLAY_MAPPING)],
)
def test_resolver_never_guesses_missing_or_ambiguous_total_return_mapping(
    indices: int, reason: ScenarioReason
) -> None:
    value = _execution(_history(indices=indices))
    assert value.replay is not None
    assert value.replay.market_bindings[0].reason is reason
    result = _material(value)
    assert result.proof.changes[0].local_return.reason is reason
    assert result.proof.changes[0].reporting_return.value is None


def test_reporting_return_without_local_fx_decomposition_is_unavailable() -> None:
    value = _execution()
    assert value.replay is not None
    binding = replace(value.replay.market_bindings[0], response_basis="reporting_total_return")
    value = replace(value, replay=replace(value.replay, market_bindings=(binding,)))
    value = replace(value, input_digest=scenario_input_digest(value))
    change = _material(value).proof.changes[0]
    assert change.reporting_return.value is None
    assert change.local_return.reason is ScenarioReason.FX_DECOMPOSITION_UNAVAILABLE


def test_replay_cash_preserves_principal_and_uses_its_original_currency() -> None:
    result = _material(_execution(source=_xray(cash=True)))
    change = result.proof.changes[0]
    assert change.local_return.value == D(0) and change.fx_return.value == D("-.1")
    assert change.reporting_return.value == D("-.1")
    assert all(
        item.kind != "observation" or item.source_kind == "fx" for item in result.proof.source_uses
    )


def test_market_point_in_time_rejects_later_known_snapshot_revision() -> None:
    result = _material(_execution(point_in_time=True))
    assert result.proof.changes[0].reporting_return.value is None
    assert any(use.kind == "missing" for use in result.proof.source_uses)
    assert _material(_execution()).proof.changes[0].reporting_return.value == D(".08")


def test_current_holdings_cannot_be_relabelled_as_historical() -> None:
    value = _execution(historical_holdings=True)
    with pytest.raises(DomainError, match="then-dated"):
        _material(value)
    assert value.replay is not None
    forged = replace(
        value,
        replay=replace(
            value.replay,
            holdings_evidence_at=value.replay.historical_input.selection.window.start_at,
        ),
    )
    forged = replace(forged, input_digest=scenario_input_digest(forged))
    with pytest.raises(DomainError, match="actual saved"):
        _material(forged)


def test_actual_historical_cash_basis_has_explicit_currency_identity_proof() -> None:
    history = _history()
    start = history.selection.window.start_at
    builder = Builder()
    builder.cash_row("25")
    source = replace(
        builder.finish(),
        valuation_at=Instant(start - timedelta(days=1)),
        source_cutoff_at=Instant(start),
    )
    result = _material(_execution(history, source, historical_holdings=True, point_in_time=True))
    change = result.proof.changes[0]
    assert change.reporting_return.value == D(0)
    assert len(change.conversion_keys) == 2
    assert not result.proof.source_uses
    later = replace(source, source_cutoff_at=Instant(start + timedelta(days=1)))
    with pytest.raises(DomainError, match="later knowledge cutoff"):
        _material(_execution(history, later, historical_holdings=True, point_in_time=True))


def test_foreign_series_membership_is_rejected_before_selection() -> None:
    value = _execution()
    assert value.replay is not None
    binding = replace(value.replay.market_bindings[0], instrument_id=UUID(int=7))
    value = replace(value, replay=replace(value.replay, market_bindings=(binding,)))
    value = replace(value, input_digest=scenario_input_digest(value))
    with pytest.raises(DomainError, match="membership differs"):
        _material(value)


def test_out_of_range_replay_is_typed_failure_without_clipping() -> None:
    with pytest.raises(DomainError) as caught:
        _material(_execution(_history(prices=("1", "1", "2", "7"))))
    assert caught.value.code is ErrorCode.DATA_UNAVAILABLE


def test_replay_restores_hostile_decimal_context() -> None:
    value = _execution()
    expected = _material(value)
    with localcontext(Context(prec=4, rounding=ROUND_DOWN, Emin=-9, Emax=9)) as active:
        active.traps[Inexact] = active.traps[Rounded] = True
        before = active.copy()
        actual = _material(value)
        assert active.flags == before.flags and active.traps == before.traps
    assert actual == expected
