"""Signed immutable layout membership stays bounded at all permitted identities."""

import base64
from datetime import UTC, datetime
from uuid import UUID

import pytest
from trading212_application.queries import CursorCodec, CursorValidationError
from trading212_domain.serialization import canonical_json
from trading212_persistence.owner_layout_cursor import (
    LayoutPageMember,
    layout_page_capsule,
    layout_page_members,
)

pytestmark = pytest.mark.unit


def test_maximum32_members_identity_binding_and_signed_envelope_fit2048() -> None:
    members = tuple(
        LayoutPageMember(layout_id=UUID(int=index + 1), version=128, archived=index % 2 == 0)
        for index in range(32)
    )
    capsule = layout_page_capsule(members)
    assert len(capsule) == 768
    assert layout_page_members(capsule) == members
    at = datetime(2026, 9, 15, tzinfo=UTC)
    codec = CursorCodec(b"layout-cursor-test-signing-key-32bytes", clock=lambda: at)
    binding = canonical_json(
        (str(UUID(int=500)), "https://" + "i" * 247, "s" * 255, "owner-layouts-v1", 100, True)
    )
    token = codec.encode(
        resource="owner-layouts-v1",
        binding=binding,
        read_cutoff=at,
        key=(str(members[-1].layout_id), capsule),
    )
    assert len(token) <= 2048
    assert codec.decode(token, resource="owner-layouts-v1", binding=binding, key_size=2) == (
        at,
        (str(members[-1].layout_id), capsule),
    )
    with pytest.raises(CursorValidationError):
        codec.decode(
            token, resource="owner-layouts-v1", binding=binding + "other-principal", key_size=2
        )
    with pytest.raises(CursorValidationError):
        codec.decode(token, resource="different-resource", binding=binding, key_size=2)


@pytest.mark.parametrize(
    "case", ["zero", "129", "unknown_flag", "duplicate", "trailing", "padding", "33"]
)
def test_capsule_rejects_ambiguous_or_expanded_members_before_iteration(case: str) -> None:
    raw = UUID(int=1).bytes + bytes((1, 0))
    if case == "zero":
        raw = raw[:16] + bytes((0, 0))
    elif case == "129":
        raw = raw[:16] + bytes((129, 0))
    elif case == "unknown_flag":
        raw = raw[:17] + b"\x02"
    elif case == "duplicate":
        raw += raw
    elif case == "trailing":
        raw += b"\x00"
    elif case == "33":
        raw *= 33
    capsule = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    if case == "padding":
        capsule += "="
    with pytest.raises(CursorValidationError):
        layout_page_members(capsule)
