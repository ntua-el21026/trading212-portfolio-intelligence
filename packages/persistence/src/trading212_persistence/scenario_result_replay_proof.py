"""Check saved replay provenance membership without recomputing historical returns."""

from datetime import timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo

from trading212_domain.historical_results import (
    HistoricalEvidenceUse,
    HistoricalObservationUse,
    HistoricalUseConsumer,
)
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.scenario_result import ScenarioCalculation
from trading212_domain.serialization import canonical_json
from trading212_domain.sources import FxSnapshot, ObservationState, PriceBasis, PriceSnapshot

from .scenario_store_types import ScenarioStorageError
from .scenario_store_types import ScenarioStorageErrorCode as Code


def _require(condition: bool) -> None:
    if not condition:
        raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)


def _observation_binding(
    inputs: ScenarioExecutionInput,
    use: HistoricalObservationUse,
    snapshot: PriceSnapshot | FxSnapshot,
) -> None:
    """Validate retained source coordinates without rebuilding prices or returns."""
    replay = inputs.replay
    assert replay is not None
    history = replay.historical_input
    policy = history.selection.source_policy
    _require(policy is not None)
    assert policy is not None
    window = history.selection.window
    cutoff = (
        min(window.source_cutoff_at, use.use_at)
        if replay.selection.knowledge_basis == "point_in_time"
        else window.source_cutoff_at
    )
    _require(
        use.role == "benchmark_component"
        and use.use_at in (window.start_at, window.end_at)
        and use.knowledge_cutoff_at == cutoff
        and snapshot.provenance.first_observed_at <= cutoff
        and snapshot.provenance.effective_at <= cutoff
        and use.use_key
        == sha256(
            canonical_json(
                (
                    use.source_kind,
                    use.snapshot_id,
                    use.observation_index,
                    use.use_at,
                    use.consumer,
                    use.role,
                    use.conversion_leg,
                )
            ).encode("utf-8")
        ).hexdigest()
    )
    consumer = use.consumer
    if consumer.kind == "cash":
        _require(
            consumer == HistoricalUseConsumer(kind="cash") and isinstance(snapshot, FxSnapshot)
        )
    else:
        _require(
            consumer.kind == "benchmark"
            and consumer
            == HistoricalUseConsumer(
                kind="benchmark",
                component_source_id=consumer.component_source_id,
                instrument_id=consumer.instrument_id,
            )
            and any(
                str(item.local_series_id) == consumer.component_source_id
                and str(item.instrument_id) == consumer.instrument_id
                for item in replay.market_bindings
            )
        )
    if isinstance(snapshot, PriceSnapshot):
        _require(
            snapshot.series.id == consumer.component_source_id
            and snapshot.series.instrument_id == consumer.instrument_id
            and snapshot.series.basis is PriceBasis.TOTAL_RETURN
            and use.conversion_leg is None
        )
        calendar_key = (snapshot.series.calendar_id, snapshot.series.calendar_version)
    else:
        leg = use.conversion_leg
        _require(leg is not None)
        assert leg is not None
        observed = snapshot.observations[use.observation_index]
        _require(
            (observed.base, observed.quote)
            == ((leg.base, leg.quote) if leg.direction == "direct" else (leg.quote, leg.base))
        )
        calendar_key = (snapshot.calendar_id, snapshot.calendar_version)
    calendar = next(
        (item for item in history.calendars if (item.id, item.version) == calendar_key), None
    )
    _require(calendar is not None)
    assert calendar is not None
    completed = [item for item in calendar.sessions if item.close_at <= use.use_at]
    _require(bool(completed))
    latest = completed[-1]
    observation = snapshot.observations[use.observation_index]
    _require(
        observation.session_date == latest.session_date
        and observation.effective_at == latest.close_at
        and observation.effective_at <= cutoff
        and observation.state is ObservationState.AVAILABLE
        and use.use_at - observation.effective_at <= timedelta(seconds=policy.max_age_seconds)
        and (
            policy.allow_closed_session_carry
            or latest.session_date == use.use_at.astimezone(ZoneInfo(calendar.timezone)).date()
        )
    )


def verify_scenario_replay_proof(
    inputs: ScenarioExecutionInput, result: ScenarioCalculation
) -> None:
    replay, proof = inputs.replay, result.replay
    _require(replay is not None and proof is not None)
    assert replay is not None and proof is not None
    history = replay.historical_input
    context = proof.context
    _require(
        proof.selection == replay.selection
        and proof.holdings_evidence_at == replay.holdings_evidence_at
        and proof.holdings_knowledge_cutoff_at == replay.holdings_knowledge_cutoff_at
        and context.account_id == history.account_id
        and context.window == history.selection.window
        and context.input_digest == replay.historical_input_digest
        and context.method.name == "scenario_replay_v1"
        and context.method.version == "1.0.0"
        and context.accounting_policy_version == history.selection.accounting_policy.version
        and context.source_policy_version
        == (
            None
            if history.selection.source_policy is None
            else history.selection.source_policy.version
        )
        and context.sources == tuple(sorted(history.sources, key=lambda item: (item.kind, item.id)))
        and set(history.warnings) <= set(context.warnings)
    )
    paths = {item.exposure.path_key for item in result.components}
    _require({item.path_key for item in proof.changes} == paths)
    _require(set(proof.diagnostics) <= set(result.diagnostics))
    snapshots: dict[str, PriceSnapshot | FxSnapshot] = {
        item.id: item for item in history.price_snapshots
    }
    snapshots.update({item.id: item for item in history.fx_snapshots})
    references = {item.id for item in history.sources}
    uses = {item.use_key: item for item in proof.source_uses}
    conversions = {item.conversion_key: item for item in proof.conversions}
    for use in proof.source_uses:
        _require(use.knowledge_cutoff_at <= replay.selection.market_knowledge_cutoff_at)
        if isinstance(use, HistoricalObservationUse):
            snapshot = snapshots.get(use.snapshot_id)
            _require(snapshot is not None and use.snapshot_id in references)
            assert snapshot is not None
            _require(0 <= use.observation_index < len(snapshot.observations))
            _require(
                (use.source_kind == "price" and isinstance(snapshot, PriceSnapshot))
                or (use.source_kind == "fx" and isinstance(snapshot, FxSnapshot))
            )
            _observation_binding(inputs, use, snapshot)
            if use.conversion_leg is not None:
                leg = use.conversion_leg
                conversion = conversions.get(leg.conversion_key)
                _require(
                    conversion is not None
                    and use.use_key in conversion.leg_use_keys
                    and conversion.use_at == use.use_at
                )
        elif isinstance(use, HistoricalEvidenceUse):
            _require(use.reference_id in references)
        else:
            _require(all(identifier in snapshots for identifier in use.candidate_snapshot_ids))
    for conversion in proof.conversions:
        for ordinal, key in enumerate(conversion.leg_use_keys):
            retained_use = uses.get(key)
            _require(isinstance(retained_use, HistoricalObservationUse))
            assert isinstance(retained_use, HistoricalObservationUse)
            retained_leg = retained_use.conversion_leg
            _require(
                retained_leg is not None
                and retained_leg.conversion_key == conversion.conversion_key
                and retained_leg.ordinal == ordinal
                and retained_use.source_kind == "fx"
            )
    for issue in (*result.diagnostics, *proof.diagnostics):
        _require(set(issue.source_use_keys) <= set(uses))
