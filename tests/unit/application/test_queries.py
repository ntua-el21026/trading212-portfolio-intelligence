from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from trading212_application.queries import CursorCodec, CursorValidationError

NOW = datetime(2026, 8, 31, 10, 0, tzinfo=UTC)
KEY = b"application-cursor-codec-test-key-v1"


def _tamper(token: str) -> str:
    index = len(token) // 2
    replacement = "A" if token[index] != "A" else "B"
    return f"{token[:index]}{replacement}{token[index + 1 :]}"


def test_cursor_round_trip_survives_restart_and_separates_cutoff_from_issued_at() -> None:
    token = CursorCodec(KEY, clock=lambda: NOW, ttl_seconds=60).encode(
        resource="activity",
        binding="owner/account/filter",
        read_cutoff=NOW - timedelta(days=365),
        key=("2026-08-31T09:00:00+00:00", "row-id"),
    )

    cutoff, key = CursorCodec(
        KEY,
        clock=lambda: NOW + timedelta(seconds=59),
        ttl_seconds=60,
    ).decode(
        token,
        resource="activity",
        binding="owner/account/filter",
        key_size=2,
    )

    assert cutoff == NOW - timedelta(days=365)
    assert key == ("2026-08-31T09:00:00+00:00", "row-id")


def test_cursor_lifetime_and_future_skew_are_bounded() -> None:
    token = CursorCodec(KEY, clock=lambda: NOW, ttl_seconds=60).encode(
        resource="positions",
        binding="account/sort",
        read_cutoff=NOW,
        key=("snapshot", "metric", "ticker", "listing"),
    )

    with pytest.raises(CursorValidationError):
        CursorCodec(
            KEY,
            clock=lambda: NOW + timedelta(seconds=61),
            ttl_seconds=60,
        ).decode(
            token,
            resource="positions",
            binding="account/sort",
            key_size=4,
        )
    with pytest.raises(CursorValidationError):
        CursorCodec(
            KEY,
            clock=lambda: NOW - timedelta(seconds=31),
            ttl_seconds=60,
            future_skew_seconds=30,
        ).decode(
            token,
            resource="positions",
            binding="account/sort",
            key_size=4,
        )


def test_cursor_authenticity_binding_and_payload_shape_fail_closed() -> None:
    codec = CursorCodec(KEY, clock=lambda: NOW)
    token = codec.encode(
        resource="instruments",
        binding="owner/scope/search",
        read_cutoff=NOW,
        key=("synthetic", "synthetic", "ticker", "name", "listing"),
    )
    invalid_cases = (
        (_tamper(token), "instruments", "owner/scope/search", 5),
        (token, "activity", "owner/scope/search", 5),
        (token, "instruments", "other-owner/scope/search", 5),
        (token, "instruments", "owner/scope/search", 4),
    )
    for candidate, resource, binding, key_size in invalid_cases:
        with pytest.raises(CursorValidationError):
            codec.decode(
                candidate,
                resource=resource,
                binding=binding,
                key_size=key_size,
            )

    signed_invalid = codec.encode(
        resource="instruments",
        binding="owner/scope/search",
        read_cutoff=NOW,
        key=cast(tuple[str, ...], (123,)),
    )
    with pytest.raises(CursorValidationError):
        codec.decode(
            signed_invalid,
            resource="instruments",
            binding="owner/scope/search",
            key_size=1,
        )
    with pytest.raises(ValueError, match="256 bits"):
        CursorCodec(b"short")
