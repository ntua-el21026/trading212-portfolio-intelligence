"""Strict bounded private codec. Exact coefficients never cross ordinary NUMERIC parsing."""

from __future__ import annotations

import json
import re
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum
from types import UnionType
from typing import Annotated, Any, Literal, Union, get_args, get_origin
from uuid import UUID

from trading212_domain import xray as d
from trading212_domain import xray_result as r
from trading212_domain.errors import DomainError
from trading212_domain.values import CurrencyCode, Instant, Money
from trading212_domain.xray import XrayInput, XrayRecord
from trading212_domain.xray_result import XrayCalculation
from trading212_domain.xray_validation import (
    bound,
    checked,
    decimal_role,
    hints,
    invalid,
    validate_record,
)

MAX_BYTES = 33_554_432
_COEFFICIENT = re.compile(r"-?(?:0|[1-9][0-9]{0,249})\Z")
_AMOUNT = re.compile(r"-?(?:0|[1-9][0-9]{0,19})(?:\.[0-9]{1,18})?\Z")
# Only these input arrays express sequence, rather than immutable sets.
_ORDERED = frozenset({"provider_order", "legs"})


def _decimal_text(value: Decimal) -> str:
    if value.is_zero():
        return "0"
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def _encode(value: object, *, input_sets: bool, field: str = "", depth: int = 0) -> Any:
    bound(depth <= 32, "document.depth")
    if value is None or type(value) in (bool, int, str):
        return value
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Instant):
        return value.value.isoformat().replace("+00:00", "Z")
    if isinstance(value, CurrencyCode):
        return value.value
    if isinstance(value, tuple):
        result = [_encode(item, input_sets=input_sets, depth=depth + 1) for item in value]
        if input_sets and field not in _ORDERED:
            result.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
        return result
    if isinstance(value, (XrayRecord, Money)) and is_dataclass(value):
        if isinstance(value, XrayRecord):
            validate_record(value)
        else:
            decimal_role(value.amount, "amount")
        return {
            item.name: _encode(
                getattr(value, item.name), input_sets=input_sets, field=item.name, depth=depth + 1
            )
            for item in fields(value)
        }
    invalid("document.type")


def _bytes(value: XrayInput | XrayCalculation) -> bytes:
    data = _encode(value, input_sets=isinstance(value, XrayInput))
    result = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    bound(len(result) <= MAX_BYTES, "document.bytes")
    return result


def encode_xray_input(value: XrayInput) -> bytes:
    if type(value) is not XrayInput:
        invalid("input.type")
    return _bytes(value)


def encode_xray_result(value: XrayCalculation) -> bytes:
    if type(value) is not XrayCalculation:
        invalid("result.type")
    return _bytes(value)


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            invalid("document.duplicate_field")
        result[key] = value
    return result


def _count(text: str) -> int:
    if not re.fullmatch(r"(?:0|[1-9][0-9]{0,9})", text):
        invalid("document.integer")
    return int(text)


def _reject(text: str) -> Any:
    invalid("document.number")


def _decode(value: object, annotation: Any, depth: int = 0) -> Any:
    bound(depth <= 32, "document.depth")
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin is Annotated:
        role = arguments[1]
        pattern = _AMOUNT if role in ("amount", "weight") else _COEFFICIENT
        if type(value) is not str or pattern.fullmatch(value) is None or value == "-0":
            invalid("document.decimal")
        return decimal_role(Decimal(value), role)
    if origin in (UnionType, Union):
        # Enum(None) raises ValueError before a later nullable branch is reached.
        # Select the closed null alternative without constructing another type.
        if value is None:
            if type(None) in arguments:
                return None
            invalid("document.union")
        for option in arguments:
            try:
                return _decode(value, option, depth + 1)
            except DomainError:
                continue
        invalid("document.union")
    if origin is Literal:
        return checked(value, annotation, "document.literal")
    if origin is tuple:
        if type(value) is not list:
            invalid("document.collection")
        bound(len(value) <= 100_000, "document.collection")
        return tuple(_decode(item, arguments[0], depth + 1) for item in value)
    if annotation is UUID:
        if type(value) is not str:
            invalid("document.uuid")
        result = UUID(value)
        if str(result) != value:
            invalid("document.uuid")
        return result
    if annotation is Instant:
        if type(value) is not str:
            invalid("document.instant")
        return Instant.parse(value)
    if annotation is CurrencyCode:
        if not isinstance(value, str):
            invalid("document.currency")
        return CurrencyCode(value)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return annotation(value)
    if annotation is Money:
        if type(value) is not dict or set(value) != {"amount", "currency"}:
            invalid("document.money")
        return Money(
            _decode(value["amount"], Annotated[Decimal, "amount"], depth + 1),
            _decode(value["currency"], CurrencyCode, depth + 1),
        )
    if isinstance(annotation, type) and issubclass(annotation, XrayRecord):
        if type(value) is not dict or set(value) != set(hints(annotation)):
            invalid("document.fields")
        return annotation(
            **{
                name: _decode(value[name], kind, depth + 1)
                for name, kind in hints(annotation).items()
            }
        )
    return checked(value, annotation, "document.value")


def _document(payload: bytes, kind: type[XrayInput] | type[XrayCalculation]) -> Any:
    if type(payload) is not bytes:
        invalid("document.bytes")
    bound(len(payload) <= MAX_BYTES, "document.bytes")
    try:
        data = json.loads(
            payload,
            object_pairs_hook=_object,
            parse_int=_count,
            parse_float=_reject,
            parse_constant=_reject,
        )
        result = _decode(data, kind)
        if _bytes(result) != payload:
            invalid("document.canonical")
        return result
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
        pass
    invalid("document")


def decode_xray_input(payload: bytes) -> XrayInput:
    result = _document(payload, XrayInput)
    assert isinstance(result, XrayInput)
    return result


def decode_xray_result(payload: bytes) -> XrayCalculation:
    result = _document(payload, XrayCalculation)
    assert isinstance(result, XrayCalculation)
    return result


type XrayComponent = (
    d.PositionRoot
    | d.CashRoot
    | d.XrayMoneyMetric
    | d.XrayRatioMetric
    | d.XrayPosition
    | d.XrayCash
    | d.XraySourceDependency
    | d.XrayPhysicalReference
    | d.XrayBrokerFx
    | d.XrayFxLeg
    | d.XrayLicensedFx
    | d.XrayEvidence
    | d.XrayPolicyVersion
    | d.XrayProviderSelectionPolicy
    | d.XrayIdentityPolicy
    | d.XrayClassificationPolicy
    | d.XrayTaxonomyVersion
    | d.XrayFreshnessPolicy
    | d.XrayQualityPolicy
    | d.XrayTraversalPolicy
    | d.XrayLimits
    | d.XrayUnconfiguredThresholds
    | d.ConcentrationThresholdPolicy
    | d.XrayFundDefinition
    | d.XrayFundMapping
    | d.XrayConstituentHolding
    | d.XrayConstituentCandidate
    | d.XrayEntityEvidence
    | d.XrayRelationshipVersion
    | d.XrayClassificationAssignment
    | d.XrayClassificationSubject
    | d.XrayClassificationBatch
    | d.XrayValuationCoverage
    | d.XrayReconciliation
    | r.XraySelection
    | r.XraySourceUse
    | r.XrayFundEdge
    | r.XrayPathClassification
    | r.XrayClassificationDecision
    | r.XrayPathDimensionMetric
    | r.XrayTerminalPath
    | r.XrayRootExact
    | r.XrayBucketExact
    | r.XrayDimensionExact
    | r.XrayExactState
    | r.XrayExposureBucket
    | r.XrayDimensionSummary
    | r.XrayTopConcentration
    | r.XrayThresholdConclusion
    | r.XrayPortfolioSummary
    | r.XrayQualityCoverage
    | r.XrayDisplayResidual
    | r.XrayHeldFund
    | r.XrayFundEntity
    | r.FundComposition
    | r.XrayDirectPosition
    | r.XrayWarning
    | r.CanonicalFundPair
    | r.CanonicalOverlapPair
    | r.CanonicalCommonEntity
    | r.CanonicalCommonEntities
    | r.CompanyExposureBasis
    | r.XrayCommonEntitiesTop
)

_COMPONENT_TYPES = (
    d.PositionRoot,
    d.CashRoot,
    d.XrayMoneyMetric,
    d.XrayRatioMetric,
    d.XrayPosition,
    d.XrayCash,
    d.XraySourceDependency,
    d.XrayPhysicalReference,
    d.XrayBrokerFx,
    d.XrayFxLeg,
    d.XrayLicensedFx,
    d.XrayEvidence,
    d.XrayPolicyVersion,
    d.XrayProviderSelectionPolicy,
    d.XrayIdentityPolicy,
    d.XrayClassificationPolicy,
    d.XrayTaxonomyVersion,
    d.XrayFreshnessPolicy,
    d.XrayQualityPolicy,
    d.XrayTraversalPolicy,
    d.XrayLimits,
    d.XrayUnconfiguredThresholds,
    d.ConcentrationThresholdPolicy,
    d.XrayFundDefinition,
    d.XrayFundMapping,
    d.XrayConstituentHolding,
    d.XrayConstituentCandidate,
    d.XrayEntityEvidence,
    d.XrayRelationshipVersion,
    d.XrayClassificationAssignment,
    d.XrayClassificationSubject,
    d.XrayClassificationBatch,
    d.XrayValuationCoverage,
    d.XrayReconciliation,
    r.XraySelection,
    r.XraySourceUse,
    r.XrayFundEdge,
    r.XrayPathClassification,
    r.XrayClassificationDecision,
    r.XrayPathDimensionMetric,
    r.XrayTerminalPath,
    r.XrayRootExact,
    r.XrayBucketExact,
    r.XrayDimensionExact,
    r.XrayExactState,
    r.XrayExposureBucket,
    r.XrayDimensionSummary,
    r.XrayTopConcentration,
    r.XrayThresholdConclusion,
    r.XrayPortfolioSummary,
    r.XrayQualityCoverage,
    r.XrayDisplayResidual,
    r.XrayHeldFund,
    r.XrayFundEntity,
    r.FundComposition,
    r.XrayDirectPosition,
    r.XrayWarning,
    r.CanonicalFundPair,
    r.CanonicalOverlapPair,
    r.CanonicalCommonEntity,
    r.CanonicalCommonEntities,
    r.CompanyExposureBasis,
    r.XrayCommonEntitiesTop,
)


def encode_xray_component(value: XrayComponent) -> bytes:
    """Encode one closed typed policy/source/normalized result component."""
    if type(value) not in _COMPONENT_TYPES:
        invalid("component.type")
    source_component = type(value).__module__ == d.__name__
    document = {
        "component": type(value).__name__,
        "schema_version": "1",
        "value": _encode(value, input_sets=source_component),
    }
    payload = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    bound(len(payload) <= MAX_BYTES, "component.bytes")
    return payload


def decode_xray_component[T: XrayComponent](payload: bytes, component_type: type[T]) -> T:
    """Require the caller's closed expected row type, never infer a foreign model."""
    if component_type not in _COMPONENT_TYPES or type(payload) is not bytes:
        invalid("component.type")
    bound(len(payload) <= MAX_BYTES, "component.bytes")
    try:
        document = json.loads(
            payload,
            object_pairs_hook=_object,
            parse_int=_count,
            parse_float=_reject,
            parse_constant=_reject,
        )
        if type(document) is not dict or set(document) != {"component", "schema_version", "value"}:
            invalid("component.fields")
        if document["component"] != component_type.__name__ or document["schema_version"] != "1":
            invalid("component.identity")
        result = _decode(document["value"], component_type)
        if not isinstance(result, component_type) or encode_xray_component(result) != payload:
            invalid("component.canonical")
        return result
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
        pass
    invalid("component")


def encode_xray_policy(value: d.XrayPolicyVersion) -> bytes:
    if type(value) is not d.XrayPolicyVersion:
        invalid("policy.type")
    return encode_xray_component(value)


def decode_xray_policy(payload: bytes) -> d.XrayPolicyVersion:
    return decode_xray_component(payload, d.XrayPolicyVersion)
