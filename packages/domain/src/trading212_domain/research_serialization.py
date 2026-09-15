"""Closed bounded research codecs; safe errors never repeat untrusted source or owner prose."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import fields
from datetime import datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from types import UnionType
from typing import Any, Literal, TypeAliasType, Union, cast, get_args, get_origin
from uuid import UUID

from . import research_facts as facts
from . import research_notes as notes
from . import research_ranking as ranking
from . import research_sources as sources
from .errors import DomainError, ErrorCode, fail_validation
from .research import (
    MAX_RESEARCH_COMMAND_BYTES,
    MAX_RESEARCH_EXPOSURE_PATHS,
    MAX_RESEARCH_PRIVATE_BYTES,
    MAX_RESEARCH_SOURCE_BYTES,
    ResearchRecord,
    research_bound,
    research_digest,
    research_hints,
)
from .serialization import canonical_json
from .sources import SourceLicense
from .values import CurrencyCode, Money, exact_decimal, require_utc

_RECORDS = frozenset(
    (
        sources.ResearchSourceVersion,
        sources.ResearchNewsFacts,
        sources.ResearchCompanyOverviewFacts,
        sources.ResearchCitation,
        sources.ResearchCitationPin,
        sources.ResearchEventRevision,
        notes.ResearchNoteContent,
        notes.ResearchNoteRevision,
        notes.ResearchReviewAcknowledgment,
        facts.ResearchXrayPin,
        facts.ResearchPortfolioFacts,
        facts.ResearchPortfolioWarning,
        facts.ResearchSynthesisUnavailable,
        ranking.ResearchDedupDecision,
        ranking.ResearchRankedItem,
        Money,
        SourceLicense,
    )
)
_LIMITS = {
    sources.ResearchSourceVersion: MAX_RESEARCH_SOURCE_BYTES,
    sources.ResearchEventRevision: MAX_RESEARCH_SOURCE_BYTES,
    notes.ResearchNoteContent: MAX_RESEARCH_COMMAND_BYTES,
    notes.ResearchNoteRevision: MAX_RESEARCH_COMMAND_BYTES + 4096,
    notes.ResearchReviewAcknowledgment: 4096,
    facts.ResearchPortfolioFacts: MAX_RESEARCH_PRIVATE_BYTES,
    facts.ResearchSynthesisUnavailable: 4096,
}


def _primitive(value: object, budget: list[int]) -> object:
    budget[0] += 1
    research_bound(budget[0] <= 8 * MAX_RESEARCH_EXPOSURE_PATHS, "research.nodes")
    if value is None or type(value) in (str, bool, int, Decimal, UUID, datetime, CurrencyCode):
        return value
    if isinstance(value, Enum):
        return value
    if type(value) is tuple:
        research_bound(len(value) <= MAX_RESEARCH_EXPOSURE_PATHS, "codec.rows")
        return tuple(_primitive(item, budget) for item in value)
    if type(value) in _RECORDS:
        return {
            field.name: _primitive(getattr(value, field.name), budget)
            for field in fields(cast(Any, value))
        }
    fail_validation("Unknown closed research record.", field="research.codec")


def research_record_bytes(value: ResearchRecord) -> bytes:
    if type(value) not in _RECORDS or not isinstance(value, ResearchRecord):
        fail_validation("A closed research record is required.", field="research.codec")
    payload = canonical_json(_primitive(value, [0])).encode("utf-8")
    research_bound(len(payload) <= MAX_RESEARCH_PRIVATE_BYTES, "research.bytes")
    _preflight(payload)
    return payload


def research_record_digest(value: ResearchRecord) -> str:
    return sha256(b"t212pi.research.record.v1\0" + research_record_bytes(value)).hexdigest()


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            fail_validation("Repeated research field.", field="research.codec")
        result[key] = value
    return result


def _decode(value: object, target: Any) -> object:
    if isinstance(target, TypeAliasType):
        return _decode(value, target.__value__)
    origin, args = get_origin(target), get_args(target)
    if origin in (Union, UnionType):
        for option in args:
            try:
                return _decode(value, option)
            except (DomainError, ValueError, TypeError):
                pass
        fail_validation("Research variant is invalid.", field="research.codec")
    if origin is Literal:
        if any(type(value) is type(item) and value == item for item in args):
            return value
    elif origin is tuple:
        if type(value) is list:
            research_bound(len(value) <= MAX_RESEARCH_EXPOSURE_PATHS, "codec.rows")
            return tuple(_decode(item, args[0]) for item in value)
    elif target is type(None):
        if value is None:
            return None
    elif target in (str, bool, int):
        if type(value) is target:
            return value
    elif target is Decimal and type(value) is str:
        return exact_decimal(value)
    elif target is CurrencyCode and type(value) is str:
        return CurrencyCode(value)
    elif target is UUID and type(value) is str:
        return UUID(value)
    elif target is datetime and type(value) is str:
        return require_utc(datetime.fromisoformat(value))
    elif isinstance(target, type) and issubclass(target, Enum) and type(value) is str:
        return target(value)
    elif target in _RECORDS and type(value) is dict:
        hints = research_hints(target)
        if set(value) == set(hints):
            constructor = cast(Callable[..., object], target)
            return constructor(**{key: _decode(item, hints[key]) for key, item in value.items()})
    fail_validation("Invalid closed research field.", field="research.codec")


def _preflight(payload: bytes) -> None:
    """Bound nesting, graph edges and string bytes before allocating decoded JSON arrays."""
    quoted = escaped = False
    depth = edges = string_bytes = 0
    for byte in payload:
        if quoted:
            string_bytes += 1
            research_bound(string_bytes <= 16384 + 1, "research.string")
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted, string_bytes = True, 0
        elif byte in (91, 123):
            depth += 1
            research_bound(depth <= 32, "research.depth")
        elif byte in (93, 125):
            depth -= 1
            if depth < 0:
                fail_validation("Research JSON nesting is invalid.", field="research.codec")
        elif byte in (44, 58):
            edges += 1
            research_bound(edges <= 8 * MAX_RESEARCH_EXPOSURE_PATHS, "research.nodes")


def _load(
    payload: bytes, target: type[ResearchRecord], expected_digest: str | None = None
) -> ResearchRecord:
    if type(payload) is not bytes or not 0 < len(payload) <= _LIMITS[target]:
        fail_validation("Research payload exceeds its bound.", field="research.bytes")
    try:
        _preflight(payload)
        raw = json.loads(payload, object_pairs_hook=_object)
        result = _decode(raw, target)
        if not isinstance(result, ResearchRecord) or research_record_bytes(result) != payload:
            fail_validation("Research payload is not canonical.", field="research.codec")
        if expected_digest is not None:
            research_digest(expected_digest)
            if research_record_digest(result) != expected_digest:
                fail_validation("Research retained digest differs.", field="research.codec")
        return result
    except (DomainError, ValueError, TypeError, KeyError, RecursionError, UnicodeError):
        raise DomainError(
            ErrorCode.VALIDATION_FAILED, "Invalid canonical research payload.", "research.codec"
        ) from None


def research_event_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> sources.ResearchEventRevision:
    return cast(
        sources.ResearchEventRevision,
        _load(payload, sources.ResearchEventRevision, expected_digest),
    )


def research_source_version_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> sources.ResearchSourceVersion:
    return cast(
        sources.ResearchSourceVersion,
        _load(payload, sources.ResearchSourceVersion, expected_digest),
    )


def research_note_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> notes.ResearchNoteRevision:
    return cast(
        notes.ResearchNoteRevision, _load(payload, notes.ResearchNoteRevision, expected_digest)
    )


def research_note_content_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> notes.ResearchNoteContent:
    return cast(
        notes.ResearchNoteContent, _load(payload, notes.ResearchNoteContent, expected_digest)
    )


def research_portfolio_facts_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> facts.ResearchPortfolioFacts:
    return cast(
        facts.ResearchPortfolioFacts, _load(payload, facts.ResearchPortfolioFacts, expected_digest)
    )


def research_review_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> notes.ResearchReviewAcknowledgment:
    return cast(
        notes.ResearchReviewAcknowledgment,
        _load(payload, notes.ResearchReviewAcknowledgment, expected_digest),
    )


def research_synthesis_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> facts.ResearchSynthesisUnavailable:
    return cast(
        facts.ResearchSynthesisUnavailable,
        _load(payload, facts.ResearchSynthesisUnavailable, expected_digest),
    )
