"""Every closed X-ray field keeps frozen admission, roles, errors and canonical bytes."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from types import UnionType
from typing import Annotated, Literal, Protocol, Union, get_args, get_origin, get_type_hints
from uuid import UUID

import pytest
from trading212_analytics.xray import calculate_xray
from trading212_domain import xray as d
from trading212_domain import xray_codec as codec
from trading212_domain import xray_result as result
from trading212_domain import xray_validation as validation
from trading212_domain.errors import DomainError
from trading212_domain.values import CurrencyCode, Instant, Money

from tests.unit.analytics.xray_factories import Builder, uid
from tests.unit.domain.xray_validation_reference import legacy_checked

pytestmark = pytest.mark.unit


class _Checker(Protocol):
    def __call__(self, value: object, annotation: object, field: str) -> object: ...


class IntChild(int):
    pass


class StrChild(str):
    pass


class UUIDChild(UUID):
    pass


class DecimalChild(Decimal):
    pass


class TupleChild(tuple[object, ...]):
    pass


class ForeignEnum(StrEnum):
    VALUE = "available"


KINDS = tuple(
    sorted(
        {
            kind
            for module in (d, result)
            for kind in vars(module).values()
            if isinstance(kind, type)
            and issubclass(kind, d.XrayRecord)
            and is_dataclass(kind)
            and kind.__module__ == module.__name__
        },
        key=lambda kind: (kind.__module__, kind.__name__),
    )
)

VALUES: tuple[object, ...] = (
    None,
    False,
    True,
    0,
    1,
    -1,
    2_147_483_647,
    2_147_483_648,
    0.5,
    "ordinary",
    "",
    "\x00",
    "prefix\x1fsuffix",
    "x" * 1024,
    "x" * 1025,
    "\u0395\u03bb\u03bb\u03b7\u03bd\u03b9\u03ba\u03ac \U0001f600",
    b"bytes",
    [],
    {},
    object(),
    (),
    (0,),
    (False,),
    Decimal("0"),
    Decimal("-0.000"),
    Decimal("1.25"),
    Decimal("NaN"),
    Decimal("Infinity"),
    UUID(int=3),
    CurrencyCode("EUR"),
    Instant(datetime(2026, 11, 15, tzinfo=UTC)),
    Money(Decimal("1.25"), CurrencyCode("EUR")),
    ForeignEnum.VALUE,
    IntChild(1),
    StrChild("ordinary"),
    UUIDChild(int=3),
    DecimalChild("1"),
    TupleChild((0,)),
)


def _ordinary(annotation: object) -> object:
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin is Annotated:
        return Decimal("0")
    if origin in (UnionType, Union):
        return _ordinary(arguments[0])
    if origin is Literal:
        return arguments[0]
    if origin is tuple:
        return ()
    if annotation is type(None):
        return None
    if annotation is str:
        return "ordinary"
    if annotation is int:
        return 1
    if annotation is bool:
        return False
    if annotation is UUID:
        return UUID(int=3)
    if annotation is Money:
        return Money(Decimal("1.25"), CurrencyCode("EUR"))
    if annotation is CurrencyCode:
        return CurrencyCode("EUR")
    if annotation is Instant:
        return Instant(datetime(2026, 11, 15, tzinfo=UTC))
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return next(iter(annotation))
    if isinstance(annotation, type):
        # checked() checks this exact nested type, not its record invariants.
        return object.__new__(annotation)
    raise AssertionError("Every closed X-ray annotation must have an independent corpus.")


def _extras(annotation: object) -> tuple[object, ...]:
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin in (UnionType, Union):
        return tuple(_ordinary(option) for option in arguments)
    if origin is Literal:
        return tuple(arguments)
    if origin is tuple:
        item = _ordinary(arguments[0])
        return ((item,), (item, item), TupleChild((item,)), (None,) * 100_001)
    return ()


def _outcome(check: _Checker, value: object, annotation: object, field: str) -> object:
    try:
        actual = check(value, annotation, field)
    except DomainError as error:
        return ("domain_error", error.code.value, error.field, error.message)
    except Exception as error:
        return ("other_error", type(error).__name__)
    if isinstance(actual, Decimal):
        return ("decimal", type(actual), actual.as_tuple())
    return ("accepted", type(actual), actual is value)


def test_bare_primitives_skip_runtime_annotation_reflection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"origin": 0, "args": 0}
    original_origin, original_args = get_origin, get_args

    def origin(annotation: object) -> object:
        calls["origin"] += 1
        return original_origin(annotation)

    def arguments(annotation: object) -> tuple[object, ...]:
        calls["args"] += 1
        return original_args(annotation)

    monkeypatch.setattr(validation, "get_origin", origin)
    monkeypatch.setattr(validation, "get_args", arguments)
    for annotation in (str, int, bool, UUID):
        for value in (*VALUES, _ordinary(annotation)):
            assert _outcome(validation.checked, value, annotation, "scalar") == _outcome(
                legacy_checked, value, annotation, "scalar"
            )
    assert calls == {"origin": 0, "args": 0}, "Bare scalar admission must precede reflection."


@pytest.mark.parametrize("kind", KINDS, ids=lambda kind: kind.__name__)
def test_every_closed_field_annotation_matches_the_frozen_validator(
    kind: type[d.XrayRecord],
) -> None:
    assert is_dataclass(kind)
    hints = get_type_hints(kind, include_extras=True)
    for field in fields(kind):
        annotation = hints[field.name]
        for value in (*VALUES, _ordinary(annotation), *_extras(annotation)):
            assert _outcome(validation.checked, value, annotation, field.name) == _outcome(
                legacy_checked, value, annotation, field.name
            ), (kind.__name__, field.name, type(value).__name__)


@pytest.mark.parametrize(
    "role",
    [
        "amount",
        "weight",
        "root_coefficient",
        "relative_coefficient",
        "path_coefficient",
        "aggregate_coefficient",
        "square_coefficient",
        "hhi_coefficient",
        "residual_coefficient",
    ],
)
def test_all_annotated_decimal_roles_keep_exact_boundaries_and_zero_normalization(
    role: str,
) -> None:
    annotation = Annotated[Decimal, role]
    for text in [
        "0",
        "-0.000",
        "1",
        "-1",
        "1e-18",
        "1e-19",
        "1e20",
        "1e38",
        "1e72",
        "1e110",
        "1e114",
        "1e228",
        "1e232",
        "1e43",
        "1e249",
        "1e250",
        "NaN",
        "Infinity",
        "9" * 250,
        "9" * 251,
    ]:
        value = Decimal(text)
        assert _outcome(validation.checked, value, annotation, "coefficient") == _outcome(
            legacy_checked, value, annotation, "coefficient"
        )


def test_original_tuple_bound_and_identity_remain_exact() -> None:
    legal = (0,) * 100_000
    for check in (validation.checked, legacy_checked):
        assert check(legal, tuple[int, ...], "points") is legal
    illegal = (*legal, 0)
    assert _outcome(validation.checked, illegal, tuple[int, ...], "points") == _outcome(
        legacy_checked, illegal, tuple[int, ...], "points"
    )


@pytest.mark.parametrize("amount", ["0", "12.3400"])
def test_frozen_validation_keeps_complete_input_result_bytes_and_digests(
    amount: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = Builder()
    builder.position(uid(10), amount)
    builder.identity(uid(10), uid(110))
    builder.classifications_for(uid(110), key=str(uid(110)))
    captured = builder.finish()
    value = calculate_xray(captured)
    with monkeypatch.context() as frozen:
        frozen.setattr(validation, "checked", legacy_checked)
        frozen.setattr(codec, "checked", legacy_checked)
        expected_input = codec.encode_xray_input(captured)
        expected_result = codec.encode_xray_result(value)
        expected_digest = value.content_digest
    assert codec.encode_xray_input(captured) == expected_input
    assert codec.encode_xray_result(value) == expected_result
    assert value.content_digest == expected_digest
    assert codec.encode_xray_input(codec.decode_xray_input(expected_input)) == expected_input
    assert codec.encode_xray_result(codec.decode_xray_result(expected_result)) == expected_result
