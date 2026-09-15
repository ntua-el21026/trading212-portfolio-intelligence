"""Private fixed-part storage framing; existing proof codecs own financial schemas."""

from trading212_domain.errors import DomainError
from trading212_domain.scenario import MAX_SCENARIO_BYTES
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.scenario_serialization import (
    ScenarioExecutionParts,
    decode_scenario_execution,
    encode_scenario_execution,
)

from .scenario_store_types import ScenarioStorageError
from .scenario_store_types import ScenarioStorageErrorCode as Code

_MAGIC = b"t212pi.scenario.storage.v1\0"
_LENGTH_BYTES = 8
_PART_COUNT = 4


def pack_scenario_input(value: ScenarioExecutionInput) -> bytes:
    parts = encode_scenario_execution(value)
    values = (parts.main, parts.xray_input, parts.xray_result, parts.historical_input)
    size = len(_MAGIC) + _LENGTH_BYTES * _PART_COUNT + sum(map(len, values))
    if size > MAX_SCENARIO_BYTES:
        raise ScenarioStorageError(Code.INPUT_BOUND_EXCEEDED)
    return _MAGIC + b"".join(len(part).to_bytes(_LENGTH_BYTES, "big") + part for part in values)


def unpack_scenario_input(payload: bytes, *, expected_digest: str) -> ScenarioExecutionInput:
    if type(payload) is not bytes or len(payload) > MAX_SCENARIO_BYTES:
        raise ScenarioStorageError(Code.INPUT_BOUND_EXCEEDED)
    if not payload.startswith(_MAGIC):
        raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
    offset = len(_MAGIC)
    parts: list[bytes] = []
    for _ in range(_PART_COUNT):
        if offset + _LENGTH_BYTES > len(payload):
            raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
        size = int.from_bytes(payload[offset : offset + _LENGTH_BYTES], "big")
        offset += _LENGTH_BYTES
        if size > len(payload) - offset:
            raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
        parts.append(payload[offset : offset + size])
        offset += size
    if offset != len(payload):
        raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
    try:
        return decode_scenario_execution(
            ScenarioExecutionParts(
                main=parts[0], xray_input=parts[1], xray_result=parts[2], historical_input=parts[3]
            ),
            expected_digest=expected_digest,
        )
    except DomainError:
        raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE) from None
