"""Canonical compact layout/version membership inside the existing signed cursor."""

import base64
from dataclasses import dataclass
from uuid import UUID

from trading212_application.queries import CursorValidationError


@dataclass(frozen=True, slots=True, kw_only=True)
class LayoutPageMember:
    layout_id: UUID
    version: int
    archived: bool


def layout_page_capsule(members: tuple[LayoutPageMember, ...]) -> str:
    if not 1 <= len(members) <= 32 or len({item.layout_id for item in members}) != len(members):
        raise CursorValidationError("invalid cursor")
    parts = []
    for item in members:
        if (
            type(item.layout_id) is not UUID
            or type(item.version) is not int
            or not 1 <= item.version <= 128
            or type(item.archived) is not bool
        ):
            raise CursorValidationError("invalid cursor")
        parts.append(item.layout_id.bytes + bytes((item.version, int(item.archived))))
    return base64.urlsafe_b64encode(b"".join(parts)).decode("ascii").rstrip("=")


def layout_page_members(capsule: str) -> tuple[LayoutPageMember, ...]:
    if type(capsule) is not str or not capsule or len(capsule) > 768:
        raise CursorValidationError("invalid cursor")
    try:
        raw = base64.b64decode(capsule, altchars=b"-_", validate=True)
        if not 18 <= len(raw) <= 576 or len(raw) % 18:
            raise ValueError("invalid capsule")
        if any(raw[index + 17] not in (0, 1) for index in range(0, len(raw), 18)):
            raise ValueError("invalid flags")
        members = tuple(
            LayoutPageMember(
                layout_id=UUID(bytes=raw[index : index + 16]),
                version=raw[index + 16],
                archived=bool(raw[index + 17]),
            )
            for index in range(0, len(raw), 18)
        )
        if layout_page_capsule(members) != capsule:
            raise ValueError("noncanonical capsule")
        return members
    except (ValueError, TypeError):
        raise CursorValidationError("invalid cursor") from None
