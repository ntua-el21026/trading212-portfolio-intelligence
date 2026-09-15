"""Strict, complete scenario proof codecs with length-framed financial identity."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from types import UnionType
from typing import Any, Literal, TypeAliasType, Union, cast, get_args, get_origin
from uuid import UUID

from .errors import DomainError, fail_validation
from .historical import HistoricalInput
from .historical_serialization import (
    canonical_historical_input,
    historical_canonical_bytes,
    historical_value_from_json,
)
from .scenario import (
    MAX_SCENARIO_BYTES,
    MAX_SCENARIO_COMPONENTS,
    MAX_SCENARIO_SENSITIVITY_ROWS,
    ScenarioRecord,
    ScenarioVersionContent,
)
from .scenario_execution import (
    ScenarioExecutionInput,
    ScenarioInputPins,
    ScenarioReplayInput,
    ScenarioReplayMarketBinding,
    ScenarioReplaySelection,
)
from .scenario_result import ScenarioCalculation
from .scenario_sources import (
    ScenarioSensitivityCapture,
    ScenarioSensitivityEvidence,
    ScenarioSensitivityObservation,
    ScenarioSensitivitySourceVersion,
)
from .scenario_validation import scenario_bound, scenario_hints
from .serialization import canonical_json
from .values import CurrencyCode, Instant, decimal_string, exact_decimal, require_utc, utc_string
from .xray_codec import decode_xray_input, decode_xray_result, encode_xray_input, encode_xray_result


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioExecutionParts:
    main: bytes
    xray_input: bytes
    xray_result: bytes
    historical_input: bytes

    def __post_init__(self) -> None:
        parts = (self.main, self.xray_input, self.xray_result, self.historical_input)
        if any(type(item) is not bytes for item in parts):
            fail_validation("Scenario proof parts require bytes.")
        scenario_bound(sum(map(len, parts)) <= MAX_SCENARIO_BYTES, "document.bytes")
        if not self.main or not self.xray_input or not self.xray_result:
            fail_validation("Complete scenario and X-ray proof parts are required.")


@dataclass(frozen=True, slots=True, kw_only=True)
class _ReplayMetadata(ScenarioRecord):
    selection: ScenarioReplaySelection
    historical_input_digest: str
    market_bindings: tuple[ScenarioReplayMarketBinding, ...]
    holdings_evidence_at: datetime
    holdings_knowledge_cutoff_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class _FinancialMetadata(ScenarioRecord):
    pins: ScenarioInputPins
    definition: ScenarioVersionContent
    sensitivities: ScenarioSensitivityCapture
    replay: _ReplayMetadata | None


@dataclass(frozen=True, slots=True, kw_only=True)
class _ExecutionMetadata(ScenarioRecord):
    financial: _FinancialMetadata
    input_digest: str
    expires_at: datetime


def _json_bytes(value: object) -> bytes:
    result = canonical_json(value).encode("utf-8")
    scenario_bound(len(result) <= MAX_SCENARIO_BYTES, "document.bytes")
    return result


def scenario_record_bytes(value: ScenarioRecord) -> bytes:
    if (
        not isinstance(value, ScenarioRecord)
        or not is_dataclass(value)
        or type(value).__module__
        not in {
            "trading212_domain.scenario",
            "trading212_domain.scenario_sources",
            "trading212_domain.scenario_execution",
            "trading212_domain.scenario_result",
        }
        or type(value) is ScenarioExecutionInput
    ):
        fail_validation("A closed scenario record is required.")
    return _json_bytes(value)


def canonical_scenario_definition(value: ScenarioVersionContent) -> ScenarioVersionContent:
    if type(value) is not ScenarioVersionContent:
        fail_validation("A canonical scenario definition is required.")
    # The constructor sorts set-like rules and rejects semantic duplicates.
    return value


def scenario_definition_bytes(value: ScenarioVersionContent) -> bytes:
    return scenario_record_bytes(canonical_scenario_definition(value))


def scenario_definition_digest(value: ScenarioVersionContent) -> str:
    return hashlib.sha256(
        b"t212pi.scenario.definition.v1\0" + scenario_definition_bytes(value)
    ).hexdigest()


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            fail_validation("Duplicate scenario document field.")
        result[key] = value
    return result


def _reject(_: str) -> Any:
    fail_validation("Scenario decimals require canonical strings.")


def _integer(value: str) -> int:
    if len(value) > 10 or not value.isascii() or not value.isdigit():
        fail_validation("Scenario integer is invalid.")
    return int(value)


def _raw_budget(raw: object, *, result: bool = False) -> None:
    """Count raw rows before constructing any expanded domain graph or index."""
    if type(raw) is not dict:
        fail_validation("Scenario document root must be an object.")
    if result:
        components = raw.get("components")
        count = raw.get("sensitivity_source_row_count")
        if type(components) is not list or type(count) is not int or count < 0:
            fail_validation("Scenario result source count is invalid.")
        scenario_bound(len(components) <= MAX_SCENARIO_COMPONENTS, "components")
        for component in components:
            if type(component) is not dict or type(component.get("sensitivity_uses")) is not list:
                fail_validation("Scenario result sensitivity uses are invalid.")
            count += len(component["sensitivity_uses"])
            scenario_bound(count <= MAX_SCENARIO_SENSITIVITY_ROWS, "sensitivity_rows")
        scenario_bound(count <= MAX_SCENARIO_SENSITIVITY_ROWS, "sensitivity_rows")
    elif "financial" in raw or "observations" in raw:
        financial = raw.get("financial", {"sensitivities": raw})
        if type(financial) is not dict or type(financial.get("sensitivities")) is not dict:
            fail_validation("Scenario sensitivity capture is invalid.")
        source = financial["sensitivities"]
        count = 0
        for name in ("observations", "memberships", "evidence"):
            if type(source.get(name)) is not list:
                fail_validation("Scenario sensitivity rows require arrays.")
            count += len(source[name])
            scenario_bound(count <= MAX_SCENARIO_SENSITIVITY_ROWS, "sensitivity_rows")
        for name, maximum in (("versions", 128), ("licenses", 8192)):
            scenario_bound(type(source.get(name)) is list and len(source[name]) <= maximum, name)


def _decode(value: Any, kind: Any, depth: int = 0) -> Any:
    scenario_bound(depth <= 32, "document.depth")
    if isinstance(kind, TypeAliasType):
        return _decode(value, kind.__value__, depth + 1)
    origin, args = get_origin(kind), get_args(kind)
    if origin in (UnionType, Union):
        if value is None and type(None) in args:
            return None
        for choice in args:
            if choice is type(None):
                continue
            try:
                return _decode(value, choice, depth + 1)
            except (DomainError, ValueError, TypeError, KeyError):
                pass
        fail_validation("Scenario document union is invalid.")
    if origin is Literal:
        if not any(type(value) is type(item) and value == item for item in args):
            fail_validation("Scenario document discriminator is invalid.")
        return value
    if origin is tuple:
        scenario_bound(
            type(value) is list and len(value) <= MAX_SCENARIO_SENSITIVITY_ROWS,
            "document.collection",
        )
        return tuple(_decode(item, args[0], depth + 1) for item in value)
    if kind is Decimal:
        if type(value) is not str:
            fail_validation("Scenario decimal requires a string.")
        parsed = exact_decimal(value)
        if decimal_string(parsed) != value:
            fail_validation("Scenario decimal is not canonical.")
        return parsed
    if kind is CurrencyCode:
        return CurrencyCode(value)
    if kind is UUID:
        if type(value) is not str:
            fail_validation("Scenario UUID requires a string.")
        parsed_uuid = UUID(value)
        if str(parsed_uuid) != value:
            fail_validation("Scenario UUID is not canonical.")
        return parsed_uuid
    if kind in (datetime, Instant):
        if type(value) is not str:
            fail_validation("Scenario instant requires a string.")
        instant = require_utc(datetime.fromisoformat(value))
        if utc_string(instant) != value:
            fail_validation("Scenario instant is not canonical.")
        return Instant(instant) if kind is Instant else instant
    if kind is date:
        if type(value) is not str:
            fail_validation("Scenario date requires a string.")
        day = date.fromisoformat(value)
        if day.isoformat() != value:
            fail_validation("Scenario date is not canonical.")
        return day
    if isinstance(kind, type) and issubclass(kind, Enum):
        return kind(value)
    if kind in (str, bool, int, type(None)):
        if type(value) is not kind:
            fail_validation("Scenario scalar type differs.")
        return value
    if (
        isinstance(kind, type)
        and is_dataclass(kind)
        and kind.__module__.startswith("trading212_domain.")
    ):
        if type(value) is not dict or set(value) != {item.name for item in fields(kind)}:
            fail_validation("Scenario document fields differ from the closed schema.")
        hints = scenario_hints(kind)
        return kind(**{name: _decode(item, hints[name], depth + 1) for name, item in value.items()})
    fail_validation("Scenario record type is unsupported.")


def _document[T](payload: bytes, kind: type[T]) -> T:
    if type(payload) is not bytes:
        fail_validation("Scenario document requires bytes.")
    scenario_bound(len(payload) <= MAX_SCENARIO_BYTES, "document.bytes")
    try:
        raw = json.loads(
            payload,
            object_pairs_hook=_object,
            parse_float=_reject,
            parse_constant=_reject,
            parse_int=_integer,
        )
        _raw_budget(raw, result=kind is ScenarioCalculation)
        value = cast(T, _decode(raw, kind))
        if _json_bytes(value) != payload:
            fail_validation("Scenario document is not canonical.")
        return value
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
        pass
    fail_validation("Canonical scenario document is invalid.")


def scenario_definition_from_json(value: bytes) -> ScenarioVersionContent:
    return _document(value, ScenarioVersionContent)


def _financial(value: ScenarioExecutionInput) -> _FinancialMetadata:
    replay = value.replay
    metadata = (
        None
        if replay is None
        else _ReplayMetadata(
            selection=replay.selection,
            historical_input_digest=replay.historical_input_digest,
            market_bindings=replay.market_bindings,
            holdings_evidence_at=replay.holdings_evidence_at,
            holdings_knowledge_cutoff_at=replay.holdings_knowledge_cutoff_at,
        )
    )
    return _FinancialMetadata(
        pins=value.pins,
        definition=value.definition,
        sensitivities=value.sensitivities,
        replay=metadata,
    )


def _parts(value: ScenarioExecutionInput) -> ScenarioExecutionParts:
    if type(value) is not ScenarioExecutionInput:
        fail_validation("Canonical scenario execution is required.")
    return ScenarioExecutionParts(
        main=_json_bytes(
            _ExecutionMetadata(
                financial=_financial(value),
                input_digest=value.input_digest,
                expires_at=value.expires_at,
            )
        ),
        xray_input=encode_xray_input(value.xray_input),
        xray_result=encode_xray_result(value.xray_result),
        historical_input=b""
        if value.replay is None
        else historical_canonical_bytes(canonical_historical_input(value.replay.historical_input)),
    )


def _digest(financial: _FinancialMetadata, parts: ScenarioExecutionParts) -> str:
    result = hashlib.sha256(b"t212pi.scenario.input.v1\0")
    for part in (
        _json_bytes(financial),
        parts.xray_input,
        parts.xray_result,
        parts.historical_input,
    ):
        result.update(len(part).to_bytes(8, "big"))
        result.update(part)
    return result.hexdigest()


def scenario_input_digest(value: ScenarioExecutionInput) -> str:
    return _digest(_financial(value), _parts(value))


def encode_scenario_execution(value: ScenarioExecutionInput) -> ScenarioExecutionParts:
    parts = _parts(value)
    if _digest(_financial(value), parts) != value.input_digest:
        fail_validation("Scenario execution digest differs.")
    return parts


def decode_scenario_execution(
    parts: ScenarioExecutionParts, *, expected_digest: str
) -> ScenarioExecutionInput:
    if type(parts) is not ScenarioExecutionParts:
        fail_validation("Complete scenario proof parts are required.")
    metadata = _document(parts.main, _ExecutionMetadata)
    if (
        metadata.input_digest != expected_digest
        or _digest(metadata.financial, parts) != expected_digest
    ):
        fail_validation("Scenario execution digest differs.")
    replay = metadata.financial.replay
    if (replay is None) != (parts.historical_input == b""):
        fail_validation("Scenario historical proof presence differs.")
    historical = None
    if replay is not None:
        historical = historical_value_from_json(parts.historical_input, HistoricalInput)
        if (
            historical_canonical_bytes(canonical_historical_input(historical))
            != parts.historical_input
        ):
            fail_validation("Scenario historical proof is not canonical.")
    replay_input = None
    if replay is not None and historical is not None:
        replay_input = ScenarioReplayInput(
            selection=replay.selection,
            historical_input=historical,
            historical_input_digest=replay.historical_input_digest,
            market_bindings=replay.market_bindings,
            holdings_evidence_at=replay.holdings_evidence_at,
            holdings_knowledge_cutoff_at=replay.holdings_knowledge_cutoff_at,
        )
    value = ScenarioExecutionInput(
        pins=metadata.financial.pins,
        definition=metadata.financial.definition,
        sensitivities=metadata.financial.sensitivities,
        replay=replay_input,
        xray_input=decode_xray_input(parts.xray_input),
        xray_result=decode_xray_result(parts.xray_result),
        input_digest=metadata.input_digest,
        expires_at=metadata.expires_at,
    )
    return value


def canonical_scenario_bytes(value: ScenarioCalculation) -> bytes:
    if type(value) is not ScenarioCalculation:
        fail_validation("Canonical scenario result is required.")
    return scenario_record_bytes(value)


def scenario_result_digest(value: ScenarioCalculation) -> str:
    return hashlib.sha256(
        b"t212pi.scenario.result.v1\0" + canonical_scenario_bytes(value)
    ).hexdigest()


def scenario_result_from_json(value: bytes, *, expected_digest: str) -> ScenarioCalculation:
    result = _document(value, ScenarioCalculation)
    if scenario_result_digest(result) != expected_digest:
        fail_validation("Scenario result digest differs.")
    return result


def scenario_sensitivity_version_from_json(value: bytes) -> ScenarioSensitivitySourceVersion:
    result = _document(value, ScenarioSensitivitySourceVersion)
    if result.content_digest != scenario_sensitivity_version_digest(result):
        fail_validation("Sensitivity version content digest differs.")
    return result


def scenario_sensitivity_observation_from_json(value: bytes) -> ScenarioSensitivityObservation:
    result = _document(value, ScenarioSensitivityObservation)
    if result.content_digest != scenario_sensitivity_observation_digest(result):
        fail_validation("Sensitivity observation content digest differs.")
    return result


def scenario_sensitivity_evidence_from_json(value: bytes) -> ScenarioSensitivityEvidence:
    result = _document(value, ScenarioSensitivityEvidence)
    if result.content_digest != scenario_sensitivity_evidence_digest(result):
        fail_validation("Sensitivity evidence content digest differs.")
    return result


def scenario_sensitivity_capture_from_json(value: bytes) -> ScenarioSensitivityCapture:
    return _document(value, ScenarioSensitivityCapture)


def _source_digest(
    value: ScenarioSensitivitySourceVersion
    | ScenarioSensitivityObservation
    | ScenarioSensitivityEvidence,
    domain: bytes,
) -> str:
    # Nested digests remain part of the source record identity. Only self-reference is omitted.
    financial = {
        field.name: getattr(value, field.name)
        for field in fields(value)
        if field.name != "content_digest"
    }
    return hashlib.sha256(domain + _json_bytes(financial)).hexdigest()


def scenario_sensitivity_version_digest(value: ScenarioSensitivitySourceVersion) -> str:
    if type(value) is not ScenarioSensitivitySourceVersion:
        fail_validation("A canonical sensitivity version is required.")
    return _source_digest(value, b"t212pi.scenario.sensitivity.version.v1\0")


def scenario_sensitivity_observation_digest(value: ScenarioSensitivityObservation) -> str:
    if type(value) is not ScenarioSensitivityObservation:
        fail_validation("A canonical sensitivity observation is required.")
    return _source_digest(value, b"t212pi.scenario.sensitivity.observation.v1\0")


def scenario_sensitivity_evidence_digest(value: ScenarioSensitivityEvidence) -> str:
    if type(value) is not ScenarioSensitivityEvidence:
        fail_validation("A canonical sensitivity evidence record is required.")
    return _source_digest(value, b"t212pi.scenario.sensitivity.evidence.v1\0")
