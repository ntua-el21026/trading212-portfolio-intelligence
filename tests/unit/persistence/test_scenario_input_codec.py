"""Complete proof framing, digest, canonicality and allocation-bound regressions."""

from dataclasses import replace

import pytest
from trading212_domain.scenario_serialization import encode_scenario_execution
from trading212_persistence import scenario_input_codec as codec
from trading212_persistence.scenario_store_types import (
    ScenarioStorageError,
    ScenarioStorageErrorCode,
)

from tests.unit.domain.scenario_factories import execution


def test_saved_envelope_round_trips_complete_existing_proof_parts() -> None:
    value = execution()
    payload = codec.pack_scenario_input(value)
    decoded = codec.unpack_scenario_input(payload, expected_digest=value.input_digest)
    parts = encode_scenario_execution(value)
    # The existing X-ray codec canonicalizes unordered source inventories.
    assert encode_scenario_execution(decoded) == parts
    assert parts.xray_input in payload and parts.xray_result in payload
    assert codec.pack_scenario_input(decoded) == payload


@pytest.mark.parametrize("mutation", ("trailing", "truncated", "version", "length", "missing"))
def test_malformed_framing_fails_closed_without_financial_decode(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    value = execution()
    payload = codec.pack_scenario_input(value)
    if mutation == "trailing":
        payload += b"\0"
    elif mutation == "truncated":
        payload = payload[:-1]
    elif mutation == "version":
        payload = payload.replace(b"storage.v1", b"storage.v2", 1)
    elif mutation == "missing":
        payload = b"t212pi.scenario.storage.v1\0"
    else:
        boundary = len(b"t212pi.scenario.storage.v1\0")
        payload = payload[:boundary] + (2**64 - 1).to_bytes(8, "big") + payload[boundary + 8 :]

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Malformed framing reached the financial decoder")

    monkeypatch.setattr(codec, "decode_scenario_execution", forbidden)
    with pytest.raises(ScenarioStorageError) as error:
        codec.unpack_scenario_input(payload, expected_digest=value.input_digest)
    assert error.value.code is ScenarioStorageErrorCode.SCENARIO_UNAVAILABLE


def test_framing_header_bytes_count_toward_the_total_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    value = execution()
    payload = codec.pack_scenario_input(value)
    parts = encode_scenario_execution(value)
    raw_size = sum(
        map(len, (parts.main, parts.xray_input, parts.xray_result, parts.historical_input))
    )
    assert raw_size < len(payload)
    monkeypatch.setattr(codec, "MAX_SCENARIO_BYTES", len(payload) - 1)
    with pytest.raises(ScenarioStorageError) as error:
        codec.pack_scenario_input(value)
    assert error.value.code is ScenarioStorageErrorCode.INPUT_BOUND_EXCEEDED


def test_retained_financial_digest_and_canonical_encoding_are_verified() -> None:
    value = execution()
    payload = codec.pack_scenario_input(value)
    with pytest.raises(ScenarioStorageError):
        codec.unpack_scenario_input(payload, expected_digest="f" * 64)
    changed = replace(value, input_digest="f" * 64)
    from trading212_domain.errors import DomainError

    with pytest.raises(DomainError):
        codec.pack_scenario_input(changed)
