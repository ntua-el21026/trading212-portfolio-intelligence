"""Frozen-validator differential coverage over every closed report field annotation."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum, StrEnum
from types import UnionType
from typing import Any, get_args, get_origin, get_type_hints
from uuid import UUID

import pytest
from trading212_domain import report_research, report_v3, report_v4
from trading212_domain import reports as r
from trading212_domain.errors import DomainError
from trading212_domain.values import CurrencyCode

from tests.unit.domain.report_validation_reference import legacy_post_init

pytestmark = pytest.mark.unit
MODULES = (r, report_v3, report_v4, report_research)
KINDS = tuple(
    sorted(
        {
            value
            for module in MODULES
            for value in vars(module).values()
            if isinstance(value, type)
            and issubclass(value, r.ReportRecord)
            and value.__module__ == module.__name__
        },
        key=lambda kind: (kind.__module__, kind.__name__),
    )
)


class IntChild(int):
    pass


class StrChild(str):
    pass


class TupleChild(tuple[object, ...]):
    pass


class DecimalChild(Decimal):
    pass


class DateChild(date):
    pass


class DatetimeChild(datetime):
    pass


class UUIDChild(UUID):
    pass


class ForeignEnum(StrEnum):
    VALUE = "available"


class IdentitySpoof(type):
    """An equality-based set of classes would incorrectly accept this as int."""

    comparisons = 0
    hashes = 0

    def __eq__(cls, other: object) -> bool:
        IdentitySpoof.comparisons += 1
        return other is int

    def __hash__(cls) -> int:
        IdentitySpoof.hashes += 1
        return hash(int)


class SpoofedScalar(metaclass=IdentitySpoof):
    pass


VALUES: tuple[object, ...] = (
    None,
    False,
    True,
    0,
    1,
    -1,
    0.0,
    "",
    "ordinary",
    "a" * 64,
    "x" * (r.MAX_REPORT_TEXT_CHARS + 1),
    b"",
    bytearray(),
    [],
    {},
    object(),
    (),
    (0,),
    (True,),
    ("ordinary",),
    ((0,),),
    Decimal("1.2500"),
    Decimal("NaN"),
    Decimal("Infinity"),
    UUID(int=3),
    CurrencyCode("EUR"),
    date(2026, 11, 15),
    datetime(2026, 11, 15),
    datetime(2026, 11, 15, tzinfo=UTC),
    datetime(2026, 11, 15, tzinfo=timezone(timedelta(hours=2))),
    r.ReportFormat.JSON,
    ForeignEnum.VALUE,
    IntChild(1),
    StrChild("ordinary"),
    TupleChild((0,)),
    DecimalChild("1"),
    DateChild(2026, 11, 15),
    DatetimeChild(2026, 11, 15, tzinfo=UTC),
    UUIDChild(int=3),
    SpoofedScalar(),
)


def _ordinary(annotation: object, name: str) -> object:
    origin = get_origin(annotation)
    if origin is UnionType:
        return _ordinary(get_args(annotation)[0], name)
    if origin is tuple:
        return ()
    if annotation is type(None):
        return None
    if annotation is str:
        return "a" * 64 if name.endswith("digest") else "ordinary"
    if annotation is int:
        return 0
    if annotation is bool:
        return False
    if annotation is Decimal:
        return Decimal("0")
    if annotation is date:
        return date(2026, 11, 15)
    if annotation is datetime:
        return datetime(2026, 11, 15, tzinfo=UTC)
    if annotation is bytes:
        return b""
    if annotation is UUID:
        return UUID(int=3)
    if annotation is CurrencyCode:
        return CurrencyCode("EUR")
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return next(iter(annotation))
    if isinstance(annotation, type):
        # The base validator checks exact nested type, never nested record values.
        return object.__new__(annotation)
    raise AssertionError("A closed report field has an unaccounted annotation.")


def _values(kind: type[r.ReportRecord]) -> dict[str, object]:
    hints = get_type_hints(kind)
    return {field.name: _ordinary(hints[field.name], field.name) for field in fields(kind)}


def _record(kind: type[r.ReportRecord], values: dict[str, object]) -> r.ReportRecord:
    value = object.__new__(kind)
    for name, field in values.items():
        object.__setattr__(value, name, field)
    return value


def _outcome(validator: Any, kind: type[r.ReportRecord], values: dict[str, object]) -> object:
    value = _record(kind, values)
    try:
        validator(value)
    except DomainError as error:
        return ("domain_error", error.code.value, error.field, error.message)
    except Exception as error:
        return ("other_error", type(error).__name__)
    return (
        "accepted",
        tuple(
            (name, field.isoformat())
            for name in values
            if type(field := getattr(value, name)) is datetime
        ),
    )


@pytest.mark.parametrize("kind", KINDS, ids=lambda kind: kind.__name__)
def test_every_closed_report_annotation_matches_frozen_validator(
    kind: type[r.ReportRecord],
) -> None:
    ordinary = _values(kind)
    assert _outcome(r.ReportRecord.__post_init__, kind, ordinary) == _outcome(
        legacy_post_init, kind, ordinary
    )
    for field in fields(kind):
        annotation = get_type_hints(kind)[field.name]
        extra: tuple[object, ...] = ()
        if get_origin(annotation) is tuple:
            member = _ordinary(get_args(annotation)[0], field.name)
            extra = ((member,), (member, member), TupleChild((member,)))
        for value in (*VALUES, *extra):
            changed = {**ordinary, field.name: value}
            assert _outcome(r.ReportRecord.__post_init__, kind, changed) == _outcome(
                legacy_post_init, kind, changed
            ), (kind.__name__, field.name, type(value).__name__)


def test_scalar_union_record_avoids_per_value_recursive_type_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = r._typed
    calls = 0

    def typed(value: object, annotation: object) -> bool:
        nonlocal calls
        calls += 1
        return original(value, annotation)

    monkeypatch.setattr(r, "_typed", typed)
    value = _record(r.ReportCell, _values(r.ReportCell))
    r.ReportRecord.__post_init__(value)
    assert calls == 0, "Closed scalar/union schema metadata must be compiled once."


def test_identity_type_lookup_never_invokes_spoofing_metaclass_hash_or_equality() -> None:
    IdentitySpoof.hashes = IdentitySpoof.comparisons = 0
    values = _values(r.ReportTableDescriptor)
    values["row_count"] = SpoofedScalar()
    assert _outcome(r.ReportRecord.__post_init__, r.ReportTableDescriptor, values) == _outcome(
        legacy_post_init, r.ReportTableDescriptor, values
    )
    assert IdentitySpoof.hashes == IdentitySpoof.comparisons == 0


@dataclass(frozen=True, slots=True, kw_only=True)
class DynamicRecord(r.ReportRecord):
    first: int | bool
    second: tuple[int, ...]
    third: bytes


def test_dynamic_records_stay_outside_bounded_public_schema_cache() -> None:
    cache = getattr(r, "_record_validation_fields", None)
    assert callable(cache), "A bounded public-schema metadata cache is required."
    cache.cache_clear()
    assert cache.cache_info().maxsize == 128
    r.ReportRecord.__post_init__(_record(r.ReportCell, _values(r.ReportCell)))
    before = cache.cache_info()
    ordinary = {"first": 1, "second": (1, 2), "third": b"ordinary"}
    assert _outcome(r.ReportRecord.__post_init__, DynamicRecord, ordinary) == _outcome(
        legacy_post_init, DynamicRecord, ordinary
    )
    assert cache.cache_info().currsize == before.currsize
    # A forged module spelling is not a declaration in the canonical module.
    saved = DynamicRecord.__module__
    DynamicRecord.__module__ = r.__name__
    try:
        assert _outcome(r.ReportRecord.__post_init__, DynamicRecord, ordinary) == _outcome(
            legacy_post_init, DynamicRecord, ordinary
        )
        assert cache.cache_info().currsize == before.currsize
    finally:
        DynamicRecord.__module__ = saved


@pytest.mark.parametrize(
    "values",
    [
        {"first": "wrong", "second": (False,), "third": b""},
        {"first": 1, "second": (False,), "third": b""},
        {"first": 1, "second": (1,) * (r.MAX_REPORT_DATASET_ROWS + 1), "third": b""},
        {"first": 1, "second": (), "third": b"x" * (r.MAX_REPORT_DOCUMENT_BYTES + 1)},
    ],
)
def test_original_tuple_bytes_bounds_and_error_order_remain_exact(
    values: dict[str, object],
) -> None:
    assert _outcome(r.ReportRecord.__post_init__, DynamicRecord, values) == _outcome(
        legacy_post_init, DynamicRecord, values
    )
