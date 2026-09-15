"""Closed canonical calendar/source-intent decoding after metadata authorization.

This codec confers no source or account authority. Its caller must authorize current
identity, grants, original source lifetime and pinned/current licenses before passing
private bytes. Restoring declared calendar/input fields does not simulate any path.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import Decimal, DecimalException
from enum import StrEnum
from hashlib import sha256
from types import UnionType
from typing import (
    Any,
    Literal,
    NoReturn,
    TypeAliasType,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)
from uuid import UUID

from trading212_application.projection_calendar import ProjectionCalendar, ProjectionCalendarError
from trading212_application.projection_capture import (
    ProjectionAssumptionVersion,
    ProjectionCapturePlan,
    ProjectionDatedEntry,
    ProjectionDatedSchedule,
    ProjectionGoalVersion,
    ProjectionGoalVersionContent,
    ProjectionInitialSelection,
    ProjectionRunSelection,
    ProjectionSnapshotValue,
    projection_capture_bytes,
)
from trading212_domain import projection as d
from trading212_domain.errors import DomainError
from trading212_domain.historical import historical_digest
from trading212_domain.values import CurrencyCode, Money, exact_decimal, require_utc, utc_string

_CAPTURE_PREFIX = b"t212pi.projection.capture.v1\0"
_RECORDS = frozenset(
    (
        ProjectionCalendar,
        ProjectionCapturePlan,
        ProjectionAssumptionVersion,
        ProjectionGoalVersion,
        ProjectionGoalVersionContent,
        ProjectionDatedEntry,
        ProjectionDatedSchedule,
        ProjectionInitialSelection,
        ProjectionRunSelection,
        ProjectionSnapshotValue,
        d.ProjectionSourcePin,
        d.ProjectionAsset,
        d.ProjectionAllocation,
        d.ProjectionAssumptions,
        d.ProjectionInitialBasis,
        d.ProjectionScheduleEntry,
        d.ProjectionSchedule,
        d.ProjectionSensitivity,
        d.ProjectionGoal,
        d.ProjectionInput,
        Money,
    )
)


class ProjectionCodecErrorCode(StrEnum):
    INPUT_BOUND_EXCEEDED = "INPUT_BOUND_EXCEEDED"
    PROJECTION_UNAVAILABLE = "PROJECTION_UNAVAILABLE"


@dataclass(slots=True)
class ProjectionCodecError(Exception):
    code: ProjectionCodecErrorCode

    def __str__(self) -> str:
        return "The saved projection cannot be decoded."


def invalid_projection_storage() -> NoReturn:
    raise ProjectionCodecError(ProjectionCodecErrorCode.PROJECTION_UNAVAILABLE)


def bounded_projection_bytes(payload: bytes) -> None:
    if type(payload) is not bytes or not 0 < len(payload) <= d.PROJECTION_MAX_BYTES:
        raise ProjectionCodecError(ProjectionCodecErrorCode.INPUT_BOUND_EXCEEDED)


def projection_storage_digest(value: str) -> None:
    try:
        historical_digest(value, "projection.storage.digest")
    except DomainError:
        invalid_projection_storage()


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionCaptureBinding:
    """Expected immutable metadata supplied by the already-authorized run owner."""

    account_id: UUID
    assumption_version_id: UUID
    goal_version_id: UUID | None
    capture_digest: str
    numerical_input_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.account_id) is not UUID
            or type(self.assumption_version_id) is not UUID
            or (self.goal_version_id is not None and type(self.goal_version_id) is not UUID)
        ):
            invalid_projection_storage()
        projection_storage_digest(self.capture_digest)
        projection_storage_digest(self.numerical_input_digest)


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            invalid_projection_storage()
        result[key] = value
    return result


def _non_integer_number(value: str) -> NoReturn:
    del value
    invalid_projection_storage()


def _decoded(value: object, target: object) -> object:
    if isinstance(target, TypeAliasType):
        return _decoded(value, target.__value__)
    origin, args = get_origin(target), get_args(target)
    if origin in (Union, UnionType):
        # Closed declared unions only; there is no alternate schema/legacy decoder.
        for member in args:
            try:
                return _decoded(value, member)
            except (ProjectionCodecError, DomainError, ValueError, TypeError):
                continue
        invalid_projection_storage()
    if origin is Literal:
        if any(type(value) is type(member) and value == member for member in args):
            return value
    elif origin is tuple:
        # A capture's largest tuple is its fixed 601 monthly date boundaries.
        if type(value) is list and len(value) <= 601 and len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decoded(item, args[0]) for item in value)
    elif target is type(None):
        if value is None:
            return None
    elif target is Decimal:
        if type(value) is str:
            return exact_decimal(value)
    elif target is UUID:
        if type(value) is str:
            parsed = UUID(value)
            if str(parsed) == value:
                return parsed
    elif target is CurrencyCode:
        if type(value) is str:
            return CurrencyCode(value)
    elif target is datetime:
        if type(value) is str and value.endswith("Z"):
            parsed_at = require_utc(datetime.fromisoformat(value))
            if utc_string(parsed_at) == value:
                return parsed_at
    elif target is date:
        if type(value) is str:
            parsed_date = date.fromisoformat(value)
            if parsed_date.isoformat() == value:
                return parsed_date
    elif target in (str, bool, int):
        if type(value) is target:
            return value
    elif target in _RECORDS and type(value) is dict:
        constructor = cast(Callable[..., object], target)
        hints = get_type_hints(constructor)
        record_fields = fields(cast(Any, target))
        if set(value) == {field.name for field in record_fields}:
            decoded = {name: _decoded(item, hints[name]) for name, item in value.items()}
            result = constructor(
                **{field.name: decoded[field.name] for field in record_fields if field.init}
            )
            # Rebuild init=False calendar/basis fields, then compare every one;
            # serialized redundant evidence cannot be silently ignored or replaced.
            if all(getattr(result, field.name) == decoded[field.name] for field in record_fields):
                return result
    invalid_projection_storage()


def decode_projection_capture(
    payload: bytes, *, expected: ProjectionCaptureBinding
) -> ProjectionCapturePlan:
    bounded_projection_bytes(payload)
    if type(expected) is not ProjectionCaptureBinding:
        invalid_projection_storage()
    if sha256(_CAPTURE_PREFIX + payload).hexdigest() != expected.capture_digest:
        invalid_projection_storage()
    try:
        raw = json.loads(
            payload,
            object_pairs_hook=_object,
            parse_float=_non_integer_number,
            parse_constant=_non_integer_number,
        )
        value = _decoded(raw, ProjectionCapturePlan)
        if type(value) is not ProjectionCapturePlan:
            invalid_projection_storage()
        if (
            value.selection.account_id != expected.account_id
            or value.selection.assumption_version_id != expected.assumption_version_id
            or value.selection.goal_version_id != expected.goal_version_id
            or value.numerical_input_digest != expected.numerical_input_digest
            or projection_capture_bytes(value) != payload
        ):
            invalid_projection_storage()
        return value
    except (
        DomainError,
        ProjectionCalendarError,
        ValueError,
        TypeError,
        OverflowError,
        RecursionError,
        UnicodeError,
        DecimalException,
    ):
        raise ProjectionCodecError(ProjectionCodecErrorCode.PROJECTION_UNAVAILABLE) from None


def encode_projection_capture(value: ProjectionCapturePlan) -> bytes:
    if (
        type(value) is not ProjectionCapturePlan
        or type(value.selection) is not ProjectionRunSelection
    ):
        invalid_projection_storage()
    try:
        payload = projection_capture_bytes(value)
    except (DomainError, ValueError, TypeError, OverflowError, RecursionError, DecimalException):
        raise ProjectionCodecError(ProjectionCodecErrorCode.PROJECTION_UNAVAILABLE) from None
    bounded_projection_bytes(payload)
    expected = ProjectionCaptureBinding(
        account_id=value.selection.account_id,
        assumption_version_id=value.selection.assumption_version_id,
        goal_version_id=value.selection.goal_version_id,
        capture_digest=sha256(_CAPTURE_PREFIX + payload).hexdigest(),
        numerical_input_digest=value.numerical_input_digest,
    )
    decode_projection_capture(payload, expected=expected)
    return payload
