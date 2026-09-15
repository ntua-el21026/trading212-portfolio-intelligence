"""Independent retained-pin, coefficient, canonical and normalized corruption regressions."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from unittest.mock import Mock
from uuid import uuid5

import pytest
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.scenario import calculate_scenario
from trading212_domain.historical_results import HistoricalObservationUse
from trading212_domain.scenario import (
    ScenarioExclusion,
    ScenarioInstrumentSelector,
    ScenarioSectorSelector,
)
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.scenario_result import ScenarioCalculation
from trading212_domain.scenario_serialization import (
    canonical_scenario_bytes,
    scenario_definition_digest,
    scenario_result_digest,
)
from trading212_domain.serialization import canonical_json
from trading212_domain.sources import FxSnapshot, PriceSnapshot
from trading212_persistence.premium_models import PremiumRunModel
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_persistence.scenario_models import (
    ScenarioAppliedSensitivityModel,
    ScenarioComponentModel,
    ScenarioResultModel,
)
from trading212_persistence.scenario_result_projection import normalized_scenario_result
from trading212_persistence.scenario_result_replay_proof import _observation_binding
from trading212_persistence.scenario_result_store import ScenarioResultStore
from trading212_persistence.scenario_result_verification import verify_scenario_result_inputs
from trading212_persistence.scenario_store_types import (
    ScenarioStorageError,
    ScenarioStorageErrorCode,
)
from trading212_security.principals import AuthorizationError

from tests.unit.analytics.scenario_factories import (
    content,
    input_for,
    portfolio,
    rate,
    with_observation,
)
from tests.unit.analytics.test_scenario_replay import _execution as replay_execution
from tests.unit.analytics.xray_factories import CUTOFF, uid
from tests.unit.domain.scenario_factories import execution, sensitivity_capture
from tests.unit.persistence.test_scenario_private_stores import authority


def sensitivity_input() -> ScenarioExecutionInput:
    source = sensitivity_capture()
    return input_for(portfolio(("100",), economic="EUR"), content(rate(source, ".01")), source)


def excluded_input() -> ScenarioExecutionInput:
    source = sensitivity_capture()
    definition = replace(
        content(rate(source, ".01")),
        exclusions=(
            ScenarioExclusion(selector=ScenarioInstrumentSelector(instrument_id=uid(10))),
            ScenarioExclusion(
                selector=ScenarioSectorSelector(
                    taxonomy_id=uid(999999), taxonomy_version="unrelated", bucket_key="technology"
                )
            ),
        ),
    )
    return input_for(portfolio(("100",), economic="EUR"), definition, source)


@pytest.mark.parametrize("kind", ("baseline", "sensitivity", "replay", "excluded"))
def test_retained_result_matches_complete_saved_input_without_recalculation(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    inputs = (
        sensitivity_input()
        if kind == "sensitivity"
        else replay_execution()
        if kind == "replay"
        else excluded_input()
        if kind == "excluded"
        else execution()
    )
    result = calculate_scenario(inputs)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Retained result verification reran a financial calculator")

    monkeypatch.setattr("trading212_analytics.scenario.calculate_scenario", forbidden)
    monkeypatch.setattr("trading212_analytics.scenario_replay.build_scenario_replay", forbidden)
    verify_scenario_result_inputs(inputs, result)


@pytest.mark.parametrize(
    "field", ("pins", "definition", "valuation", "original_evidence", "assumptions")
)
def test_semantically_valid_result_cannot_change_its_saved_input_identity(field: str) -> None:
    inputs = execution()
    result = calculate_scenario(inputs)
    if field == "pins":
        result = replace(result, pins=replace(result.pins, xray_run_id=uid(9901)))
    elif field == "definition":
        changed_definition = replace(result.definition, name="Changed assumption")
        result = replace(
            result,
            definition=changed_definition,
            pins=replace(
                result.pins, scenario_version_digest=scenario_definition_digest(changed_definition)
            ),
        )
    elif field == "valuation":
        result = replace(result, valuation_at=result.valuation_at + timedelta(seconds=1))
    elif field == "assumptions":
        result = replace(result, assumptions=())
    else:
        component = result.components[0]
        changed = replace(component, exposure=replace(component.exposure, source_reference_ids=()))
        assert changed.exposure != component.exposure
        result = replace(result, components=(changed, *result.components[1:]))
    with pytest.raises(ScenarioStorageError):
        verify_scenario_result_inputs(inputs, result)


@pytest.mark.parametrize("kind", ("price", "fx"))
def test_replay_observation_cannot_move_to_another_date_inside_same_snapshot(kind: str) -> None:
    inputs = replay_execution()
    result = calculate_scenario(inputs)
    assert result.replay is not None and inputs.replay is not None
    proof = result.replay
    use = next(
        item
        for item in proof.source_uses
        if isinstance(item, HistoricalObservationUse) and item.source_kind == kind
    )
    snapshots: tuple[PriceSnapshot | FxSnapshot, ...] = (
        *inputs.replay.historical_input.price_snapshots,
        *inputs.replay.historical_input.fx_snapshots,
    )
    snapshot = next(item for item in snapshots if item.id == use.snapshot_id)
    changed = replace(
        use, observation_index=(use.observation_index + 1) % len(snapshot.observations)
    )
    tampered = replace(
        result,
        replay=replace(
            proof, source_uses=tuple(changed if item == use else item for item in proof.source_uses)
        ),
    )
    with pytest.raises(ScenarioStorageError):
        verify_scenario_result_inputs(inputs, tampered)
    # A self-consistent identifier cannot make a different observation date valid.
    forged = replace(
        changed,
        use_key=sha256(
            canonical_json(
                (
                    changed.source_kind,
                    changed.snapshot_id,
                    changed.observation_index,
                    changed.use_at,
                    changed.consumer,
                    changed.role,
                    changed.conversion_leg,
                )
            ).encode("utf-8")
        ).hexdigest(),
    )
    with pytest.raises(ScenarioStorageError):
        _observation_binding(inputs, forged, snapshot)


@pytest.mark.parametrize("field", ("coefficient", "candidate", "version", "driver", "missing_use"))
def test_sensitivity_use_must_match_actual_complete_captured_observation(field: str) -> None:
    inputs = sensitivity_input()
    result = calculate_scenario(inputs)
    component = next(item for item in result.components if item.sensitivity_uses)
    use = component.sensitivity_uses[0]
    if field == "coefficient":
        source = with_observation(
            inputs.sensitivities,
            replace(inputs.sensitivities.observations[0], coefficient=Decimal("-3")),
        )
        changed_inputs = input_for(inputs.xray_input, inputs.definition, source)
        # A self-consistent result still cannot substitute another captured coefficient.
        result = replace(calculate_scenario(changed_inputs), input_digest=inputs.input_digest)
        with pytest.raises(ScenarioStorageError):
            verify_scenario_result_inputs(inputs, result)
        return
    elif field == "candidate":
        use = replace(use, candidate_observation_ids=(uid(9901),), observation_id=uid(9901))
    elif field == "version":
        use = replace(use, version_id=uid(9901))
    elif field == "driver":
        use = replace(use, driver=replace(use.driver, evidence_reference_ids=()))
    changed = replace(component, sensitivity_uses=() if field == "missing_use" else (use,))
    result = replace(
        result,
        components=tuple(changed if item is component else item for item in result.components),
    )
    with pytest.raises(ScenarioStorageError):
        verify_scenario_result_inputs(inputs, result)


def result_reader(
    monkeypatch: pytest.MonkeyPatch, result: ScenarioCalculation
) -> tuple[
    ScenarioResultStore,
    Mock,
    ReportAuthorization,
    PremiumRunModel,
    list[ScenarioComponentModel],
    list[ScenarioAppliedSensitivityModel],
]:
    auth = authority()
    root = PremiumRunModel(
        id=uid(9910),
        owner_id=auth.owner_id,
        account_id=auth.account_id,
        kind="scenario",
        input_digest=result.input_digest,
        expires_at=CUTOFF.value + timedelta(days=1),
        created_at=CUTOFF.value,
        reserved_bytes=0,
        retained_bytes=33554432,
    )
    store = ScenarioResultStore(
        sessionmaker(),
        cursor_signing_key=b"synthetic-key-32-bytes-for-tests!",
        clock=lambda: CUTOFF.value,
    )
    monkeypatch.setattr(store, "_result_authority", lambda *args, **kwargs: (auth, root))
    monkeypatch.setattr(store, "_finish_result_authority", lambda *args, **kwargs: None)
    monkeypatch.setattr(store, "_result_bytes", lambda *args, **kwargs: 1000)
    identifier = uuid5(root.id, "scenario_results")
    projection = normalized_scenario_result(result, identifier)
    header = ScenarioResultModel(
        id=identifier,
        owner_id=auth.owner_id,
        account_id=auth.account_id,
        run_id=root.id,
        content_digest=scenario_result_digest(result),
        component_count=len(projection.components),
        sensitivity_source_row_count=result.sensitivity_source_row_count,
        applied_use_count=len(projection.applied_uses),
        sealed=True,
    )
    components = [ScenarioComponentModel(**row) for row in projection.components]
    uses = [ScenarioAppliedSensitivityModel(**row) for row in projection.applied_uses]
    session = Mock(spec=Session)
    session.scalar.side_effect = ("succeeded", header, canonical_scenario_bytes(result))
    session.scalars.side_effect = (components, uses)
    return store, session, auth, root, components, uses


@pytest.mark.parametrize(
    "field",
    (
        None,
        "coefficient",
        "candidate_observation_ids",
        "effect_quality",
        "canonical_component",
        "post_value",
        "missing_component",
        "extra_use",
    ),
)
def test_read_verifies_every_normalized_child_against_the_canonical_result(
    monkeypatch: pytest.MonkeyPatch, field: str | None
) -> None:
    inputs = sensitivity_input()
    result = calculate_scenario(inputs)
    store, session, auth, root, components, uses = result_reader(monkeypatch, result)
    if field == "coefficient":
        uses[0].coefficient = Decimal("-3")
    elif field == "candidate_observation_ids":
        uses[0].candidate_observation_ids = []
    elif field == "effect_quality":
        uses[0].effect_quality = "fresh" if uses[0].effect_quality != "fresh" else "partial"
    elif field == "canonical_component":
        components[0].canonical_component += b" "
    elif field == "post_value":
        components[0].post_value = Decimal("987654")
    elif field == "missing_component":
        components.pop()
    elif field == "extra_use":
        uses.append(uses[0])
    if field is None:
        assert store.read_result(session, auth, root, inputs) == result
    else:
        with pytest.raises(ScenarioStorageError) as error:
            store.read_result(session, auth, root, inputs)
        assert error.value.code is ScenarioStorageErrorCode.SCENARIO_UNAVAILABLE


def test_result_read_denies_authority_before_any_private_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ScenarioResultStore(
        sessionmaker(),
        cursor_signing_key=b"synthetic-key-32-bytes-for-tests!",
        clock=lambda: CUTOFF.value,
    )
    monkeypatch.setattr(
        store, "_result_authority", Mock(side_effect=AuthorizationError("access denied"))
    )
    session = Mock(spec=Session)
    with pytest.raises(AuthorizationError):
        store.read_result(session, authority(), PremiumRunModel(id=uid(9910)), execution())
    session.scalar.assert_not_called()
    session.scalars.assert_not_called()
