"""Complete proof round trips, canonical negative cases, and financial digest boundaries."""

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.scenario import (
    MAX_SCENARIO_BYTES,
    ScenarioInstrumentSelector,
    ScenarioPriceShock,
)
from trading212_domain.scenario_serialization import (
    ScenarioExecutionParts,
    canonical_scenario_bytes,
    decode_scenario_execution,
    encode_scenario_execution,
    scenario_definition_bytes,
    scenario_definition_from_json,
    scenario_input_digest,
    scenario_result_digest,
    scenario_result_from_json,
)
from trading212_domain.serialization import canonical_json
from trading212_domain.xray_codec import encode_xray_input, encode_xray_result

from tests.unit.analytics.xray_factories import reversed_input, uid
from tests.unit.domain.scenario_factories import baseline_calculation, definition, execution


def test_complete_xray_proof_round_trip_preserves_long_exact_coefficients() -> None:
    value = execution()
    assert any(
        path.money_coefficient is not None and len(path.money_coefficient.as_tuple().digits) > 38
        for path in value.xray_result.terminal_paths
    )
    parts = encode_scenario_execution(value)
    restored = decode_scenario_execution(parts, expected_digest=value.input_digest)
    assert encode_scenario_execution(restored) == parts
    assert encode_xray_input(restored.xray_input) == encode_xray_input(value.xray_input)
    assert encode_xray_result(restored.xray_result) == encode_xray_result(value.xray_result)
    assert [path.reporting_value for path in restored.xray_result.terminal_paths] == [
        path.reporting_value for path in value.xray_result.terminal_paths
    ]
    permuted = replace(value, xray_input=reversed_input(value.xray_input))
    assert scenario_input_digest(permuted) == value.input_digest


def test_expiry_is_operational_but_saved_identity_and_all_parts_are_financial() -> None:
    value = execution()
    extended = replace(value, expires_at=value.expires_at + timedelta(hours=1))
    assert scenario_input_digest(extended) == value.input_digest
    assert encode_scenario_execution(extended).main != encode_scenario_execution(value).main
    changed = replace(value, pins=replace(value.pins, xray_run_id=uid(777)))
    assert scenario_input_digest(changed) != value.input_digest
    parts = encode_scenario_execution(value)
    with pytest.raises(DomainError):
        decode_scenario_execution(
            replace(parts, xray_result=parts.xray_input), expected_digest=value.input_digest
        )
    with pytest.raises(DomainError):
        decode_scenario_execution(
            replace(parts, historical_input=b"{}"), expected_digest=value.input_digest
        )
    with pytest.raises(DomainError):
        replace(value, pins=replace(value.pins, account_id=uid(778)))


def test_definition_decode_rejects_unknown_duplicate_noncanonical_and_wrong_union_fields() -> None:
    value = replace(
        definition(),
        shocks=(
            ScenarioPriceShock(
                selector=ScenarioInstrumentSelector(instrument_id=uid(10)), size=Decimal("-0.2")
            ),
        ),
    )
    data = scenario_definition_bytes(value)
    assert scenario_definition_from_json(data) == value
    mutations = [
        data.replace(b'"size":"-0.2"', b'"size":-0.2'),
        data.replace(b'"size":"-0.2"', b'"size":"-0.20"'),
        data.replace(b'"kind":"instrument"', b'"kind":"listing"'),
        data.replace(b'"name":', b'"unexpected":true,"name":'),
        data.replace(b'"name":', b'"mode":"compounded","name":'),
        b" " + data,
    ]
    for document in mutations:
        with pytest.raises(DomainError):
            scenario_definition_from_json(document)


def test_result_round_trip_and_raw_aggregate_budget_precedes_record_decoding() -> None:
    value = baseline_calculation()
    encoded = canonical_scenario_bytes(value)
    assert (
        scenario_result_from_json(encoded, expected_digest=scenario_result_digest(value)) == value
    )
    raw = json.loads(encoded)
    raw["sensitivity_source_row_count"] = 100_000
    # This malformed use would normally cause a validation failure. Admission must count it first.
    raw["components"][0]["sensitivity_uses"] = [{}]
    with pytest.raises(DomainError) as caught:
        scenario_result_from_json(canonical_json(raw).encode(), expected_digest="0" * 64)
    assert caught.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    with pytest.raises(DomainError):
        scenario_result_from_json(encoded, expected_digest="0" * 64)


def test_byte_budget_covers_all_proof_parts_together() -> None:
    half = b"x" * (MAX_SCENARIO_BYTES // 2)
    with pytest.raises(DomainError) as caught:
        ScenarioExecutionParts(main=b"{}", xray_input=half, xray_result=half, historical_input=b"")
    assert caught.value.code is ErrorCode.INPUT_BOUND_EXCEEDED


def test_authorized_source_payload_decoders_have_fixed_closed_types() -> None:
    from trading212_domain.scenario_serialization import (
        scenario_record_bytes,
        scenario_sensitivity_capture_from_json,
        scenario_sensitivity_evidence_from_json,
        scenario_sensitivity_observation_from_json,
        scenario_sensitivity_version_from_json,
    )

    from tests.unit.domain.scenario_factories import sensitivity_capture

    source = sensitivity_capture()
    assert scenario_sensitivity_capture_from_json(scenario_record_bytes(source)) == source
    assert (
        scenario_sensitivity_version_from_json(scenario_record_bytes(source.versions[0]))
        == source.versions[0]
    )
    assert (
        scenario_sensitivity_observation_from_json(scenario_record_bytes(source.observations[0]))
        == source.observations[0]
    )
    assert (
        scenario_sensitivity_evidence_from_json(scenario_record_bytes(source.evidence[0]))
        == source.evidence[0]
    )
    with pytest.raises(DomainError):
        scenario_sensitivity_observation_from_json(scenario_record_bytes(source.versions[0]))


def test_replay_retains_full_history_and_rejects_mixed_hypothetical_shocks() -> None:
    from trading212_domain.historical_serialization import historical_input_digest
    from trading212_domain.scenario_execution import ScenarioReplayInput, ScenarioReplaySelection
    from trading212_domain.scenario_serialization import scenario_definition_digest

    from tests.unit.analytics.historical_factories import fixture as historical_fixture

    value = execution()
    historical = replace(
        historical_fixture(),
        owner_id=str(value.pins.owner_id),
        account_id=str(value.pins.account_id),
    )
    window = historical.selection.window
    replay = ScenarioReplayInput(
        selection=ScenarioReplaySelection(
            historical_input_snapshot_id=uid(888),
            start_date=window.start_date,
            end_date=window.end_date,
            market_knowledge_cutoff_at=window.source_cutoff_at,
            holdings_basis="current_holdings",
            knowledge_basis="retrospective",
        ),
        historical_input=historical,
        historical_input_digest=historical_input_digest(historical),
        market_bindings=(),
        holdings_evidence_at=value.xray_input.valuation_at.value,
        holdings_knowledge_cutoff_at=value.pins.source_cutoff_at,
    )
    provisional = replace(value, replay=replay)
    selected = replace(provisional, input_digest=scenario_input_digest(provisional))
    parts = encode_scenario_execution(selected)
    assert parts.historical_input
    restored = decode_scenario_execution(parts, expected_digest=selected.input_digest)
    assert encode_scenario_execution(restored) == parts
    shock = ScenarioPriceShock(
        selector=ScenarioInstrumentSelector(instrument_id=uid(10)), size=Decimal("-0.2")
    )
    mixed = replace(value.definition, shocks=(shock,))
    with pytest.raises(DomainError):
        replace(
            selected,
            definition=mixed,
            pins=replace(selected.pins, scenario_version_digest=scenario_definition_digest(mixed)),
        )
    with pytest.raises(DomainError):
        replace(
            replay,
            selection=replace(
                replay.selection,
                market_knowledge_cutoff_at=window.source_cutoff_at + timedelta(seconds=1),
            ),
        )


def test_source_digest_excludes_self_reference_but_binds_coefficient_and_nested_driver_digest() -> (
    None
):
    from trading212_domain.scenario_serialization import (
        scenario_record_bytes,
        scenario_sensitivity_observation_digest,
        scenario_sensitivity_observation_from_json,
        scenario_sensitivity_version_digest,
    )

    from tests.unit.domain.scenario_factories import sensitivity_capture

    source = sensitivity_capture()
    observation = source.observations[0]
    assert (
        scenario_sensitivity_observation_digest(replace(observation, content_digest="0" * 64))
        == observation.content_digest
    )
    changed = replace(observation, coefficient=Decimal("-3"))
    assert scenario_sensitivity_observation_digest(changed) != observation.content_digest
    with pytest.raises(DomainError):
        scenario_sensitivity_observation_from_json(scenario_record_bytes(changed))
    version = source.versions[0]
    changed_version = replace(version, driver=replace(version.driver, definition_digest="f" * 64))
    assert scenario_sensitivity_version_digest(changed_version) != version.content_digest
