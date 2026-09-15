"""Closed research vocabulary and inert bounded values; no acquisition or model port."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from types import UnionType
from typing import Any, Literal, TypeAliasType, Union, get_args, get_origin, get_type_hints

from .errors import DomainError, ErrorCode, fail_validation
from .values import exact_decimal, require_utc

RESEARCH_METHOD = "research_summary_v1"
RESEARCH_VERSION = "1.0.0"
MAX_RESEARCH_SOURCE_BYTES = 16 * 1024
MAX_RESEARCH_TEXT_CHARS = 4096
MAX_RESEARCH_CITATIONS = 64
MAX_RESEARCH_PAGE = 100
MAX_RESEARCH_PRIVATE_BYTES = 32 * 1024 * 1024
MAX_RESEARCH_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_RESEARCH_COMMAND_BYTES = 64 * 1024
MAX_RESEARCH_VERSIONS = 512
MAX_RESEARCH_EXPOSURE_PATHS = 10000


class ResearchEventKind(StrEnum):
    NEWS = "news"
    COMPANY_OVERVIEW = "company_overview"


class ResearchReviewState(StrEnum):
    ALL = "all"
    REVIEWED = "reviewed"
    UNREVIEWED = "unreviewed"


class ResearchExposureReason(StrEnum):
    CAPTURED_VALUE_UNAVAILABLE = "captured_value_unavailable"
    ENTITY_ABSENT_FROM_CAPTURE = "entity_absent_from_capture"


def research_bound(condition: bool, field: str) -> None:
    if not condition:
        raise DomainError(ErrorCode.INPUT_BOUND_EXCEEDED, "Research capacity exceeded.", field)


def inert_research_text(value: str, *, allow_empty: bool = False) -> str:
    """Normalize prose only. Markup, quoted commands and links are never interpreted.

    Consumers must render this plain-text value through escaped text nodes. No
    destination, HTML, tool, instruction or numeric parser consumes this string.
    """
    if type(value) is not str:
        fail_validation("Research text is invalid.", field="text")
    research_bound(len(value) <= MAX_RESEARCH_TEXT_CHARS, "text")
    # Permit ordinary multiline prose; strip no words or possible numeric claims.
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    # ZWNJ/ZWJ are ordinary orthography in several scripts; bidi overrides,
    # isolates, zero-width spaces and other formatting controls remain forbidden.
    if any(
        unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        and char not in "\n\t\u200c\u200d"
        for char in value
    ):
        fail_validation("Research text contains unsupported controls.", field="text")
    normalized = unicodedata.normalize("NFC", value)
    research_bound(len(normalized) <= MAX_RESEARCH_TEXT_CHARS, "text")
    if not allow_empty and not normalized.strip():
        fail_validation("Research text is empty.", field="text")
    return normalized


def opaque_research_key(value: str) -> None:
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) is None:
        fail_validation("An opaque research source identity is required.", field="source_key")


def research_digest(value: str) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        fail_validation("A research digest is required.", field="digest")


def research_unique(values: tuple[object, ...], field: str) -> None:
    if len(set(values)) != len(values):
        fail_validation("Research identities are duplicated.", field=field)


@lru_cache(maxsize=64)
def research_hints(kind: type[object]) -> dict[str, Any]:
    return get_type_hints(kind)


def _typed(value: object, annotation: Any) -> bool:
    if isinstance(annotation, TypeAliasType):
        return _typed(value, annotation.__value__)
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, UnionType):
        return any(_typed(value, item) for item in args)
    if origin is Literal:
        return any(type(value) is type(item) and value == item for item in args)
    if origin is tuple:
        return (
            type(value) is tuple
            and len(value) <= MAX_RESEARCH_EXPOSURE_PATHS
            and all(_typed(item, args[0]) for item in value)
        )
    return isinstance(annotation, type) and type(value) is annotation


class ResearchRecord:
    __slots__ = ()

    def __post_init__(self) -> None:
        if not is_dataclass(self):
            fail_validation("A closed research record is required.")
        hints = research_hints(type(self))
        for field in fields(self):
            value = getattr(self, field.name)
            if not _typed(value, hints[field.name]):
                fail_validation("Research field type differs.", field=field.name)
            if type(value) is datetime:
                object.__setattr__(self, field.name, require_utc(value))
            elif type(value) is str:
                object.__setattr__(self, field.name, inert_research_text(value, allow_empty=True))
                if field.name.endswith("digest"):
                    research_digest(value)
            elif type(value) is Decimal:
                exact_decimal(value, field=field.name)
            elif type(value) is int:
                research_bound(0 <= value <= 2_147_483_647, field.name)
