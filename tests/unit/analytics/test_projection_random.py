"""Independent references for the ADR-0019 stateless projection sampler."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from decimal import ROUND_DOWN, Context, Decimal, Inexact, Rounded, getcontext, localcontext
from typing import Any

import pytest
from trading212_analytics import _projection_random as sampler
from trading212_domain.errors import DomainError, ErrorCode

D = Decimal
pytestmark = pytest.mark.unit

type Identity = tuple[int, int, int, int]


@dataclass(frozen=True)
class _Digest:
    value: bytes

    def digest(self) -> bytes:
        return self.value


def _oracle(identity: Identity) -> Decimal:
    """Use independent encoding, centered integers and a 180-digit polar factor.

    The centered numerator is odd, so neither coordinate can equal zero. The
    radius and unit-vector factors are evaluated separately from production's
    u * sqrt(-2 * ln(q) / q) expression.
    """
    with localcontext(Context(prec=180)):
        denominator = 1 << 128
        for attempt in range(32):
            payload = b"t212pi.projection.v1\x00" + struct.pack(">IIHBB", *identity, attempt)
            digest = hashlib.sha256(payload).digest()
            first = struct.unpack(">QQ", digest[:16])
            second = struct.unpack(">QQ", digest[16:])
            first_integer = (first[0] << 64) | first[1]
            second_integer = (second[0] << 64) | second[1]
            x = D(2 * first_integer + 1 - denominator) / D(denominator)
            y = D(2 * second_integer + 1 - denominator) / D(denominator)
            radius_squared = x * x + y * y
            if 0 < radius_squared < 1:
                radius = (-2 * radius_squared.ln()).sqrt()
                unit_x = x / radius_squared.sqrt()
                return radius * unit_x
    raise AssertionError("The independent projection reference exhausted all 32 attempts.")


def _assert_reference(actual: Decimal, expected: Decimal) -> None:
    assert isinstance(actual, Decimal)
    assert actual.is_finite()
    with localcontext(Context(prec=180)):
        assert abs(actual - expected) <= D("1e-60") * max(D(1), abs(expected))


def _assert_context_unchanged(active: Context, before: Context) -> None:
    assert getcontext() is active
    assert active.prec == before.prec
    assert active.rounding == before.rounding
    assert active.Emin == before.Emin
    assert active.Emax == before.Emax
    assert active.capitals == before.capitals
    assert active.clamp == before.clamp
    assert active.traps == before.traps
    assert active.flags == before.flags


@pytest.mark.parametrize(
    "identity",
    [
        (0, 0, 1, 0),
        (1, 1, 2, 1),
        (42, 17, 12, 3),
        (20260914, 31, 13, 11),
        (16909060, 255, 256, 8),
        (4294967295, 4095, 600, 11),
    ],
)
def test_sampler_matches_independent_high_precision_reference(identity: Identity) -> None:
    _assert_reference(sampler.normal_at(*identity), _oracle(identity))


def test_sampler_preimage_is_literal_fixed_width_big_endian(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[bytes] = []

    def fake_sha256(payload: bytes) -> _Digest:
        seen.append(payload)
        return _Digest(bytes.fromhex("80" + "00" * 15) * 2)

    monkeypatch.setattr(sampler, "sha256", fake_sha256)
    result = sampler.normal_at(16909060, 4095, 600, 11)

    assert seen == [b"t212pi.projection.v1\x00\x01\x02\x03\x04\x00\x00\x0f\xff\x02\x58\x0b\x00"]
    assert len(seen[0]) == 33
    with localcontext(Context(prec=180)):
        expected = (255 * D(2).ln()).sqrt()
    _assert_reference(result, expected)


@pytest.mark.parametrize(
    ("first_half", "sign"),
    [("80" + "00" * 15, 1), ("7f" + "ff" * 15, -1)],
)
def test_signed_midpoint_vector_has_analytic_polar_value(
    monkeypatch: pytest.MonkeyPatch, first_half: str, sign: int
) -> None:
    # k = 2**127 or 2**127-1 gives u = +/-2**-128. The second
    # midpoint gives v = 2**-128, hence q = 2**-255 and z = +/-sqrt(255 ln 2).
    digest = bytes.fromhex(first_half + "80" + "00" * 15)
    monkeypatch.setattr(sampler, "sha256", lambda _payload: _Digest(digest))
    with localcontext(Context(prec=180)):
        expected = sign * (255 * D(2).ln()).sqrt()
    _assert_reference(sampler.normal_at(0, 0, 1, 0), expected)


@pytest.mark.parametrize("rejected", [b"\x00" * 32, b"\xff" * 32])
def test_sampler_rejects_outside_unit_disk_before_accepting_next_attempt(
    monkeypatch: pytest.MonkeyPatch, rejected: bytes
) -> None:
    seen: list[bytes] = []
    accepted = bytes.fromhex("80" + "00" * 15) * 2

    def fake_sha256(payload: bytes) -> _Digest:
        seen.append(payload)
        return _Digest(rejected if len(seen) == 1 else accepted)

    monkeypatch.setattr(sampler, "sha256", fake_sha256)
    result = sampler.normal_at(0, 0, 1, 0)
    prefix = b"t212pi.projection.v1\x00" + b"\x00" * 8 + b"\x00\x01\x00"
    assert seen == [prefix + b"\x00", prefix + b"\x01"]
    with localcontext(Context(prec=180)):
        expected = (255 * D(2).ln()).sqrt()
    _assert_reference(result, expected)


def test_attempt_31_can_succeed_after_31_rejections(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bytes] = []
    accepted = bytes.fromhex("80" + "00" * 15) * 2

    def fake_sha256(payload: bytes) -> _Digest:
        seen.append(payload)
        return _Digest(accepted if len(seen) == 32 else b"\x00" * 32)

    monkeypatch.setattr(sampler, "sha256", fake_sha256)
    result = sampler.normal_at(0, 0, 1, 0)
    assert len(seen) == 32
    assert [payload[-1] for payload in seen] == list(range(32))
    assert all(payload[:-1] == seen[0][:-1] for payload in seen)
    with localcontext(Context(prec=180)):
        expected = (255 * D(2).ln()).sqrt()
    _assert_reference(result, expected)


def test_exhaustion_is_typed_and_restores_hostile_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[bytes] = []

    def fake_sha256(payload: bytes) -> _Digest:
        seen.append(payload)
        return _Digest(b"\x00" * 32)

    monkeypatch.setattr(sampler, "sha256", fake_sha256)
    with localcontext(
        Context(prec=3, rounding=ROUND_DOWN, Emin=-9, Emax=9, capitals=0, clamp=1)
    ) as hostile:
        for signal in hostile.traps:
            hostile.traps[signal] = True
        hostile.flags[Inexact] = hostile.flags[Rounded] = True
        before = hostile.copy()
        with pytest.raises(DomainError) as failure:
            sampler.normal_at(0, 0, 1, 0)
        assert failure.value.code == ErrorCode.DATA_UNAVAILABLE
        _assert_context_unchanged(hostile, before)
    assert len(seen) == 32
    assert [payload[-1] for payload in seen] == list(range(32))


def test_success_ignores_and_restores_hostile_context() -> None:
    identity = (42, 17, 12, 3)
    expected = _oracle(identity)
    with localcontext(
        Context(prec=3, rounding=ROUND_DOWN, Emin=-9, Emax=9, capitals=0, clamp=1)
    ) as hostile:
        for signal in hostile.traps:
            hostile.traps[signal] = True
        hostile.flags[Inexact] = hostile.flags[Rounded] = True
        before = hostile.copy()
        result = sampler.normal_at(*identity)
        _assert_context_unchanged(hostile, before)
    _assert_reference(result, expected)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("seed", -1),
        ("seed", 4294967296),
        ("path_index", -1),
        ("path_index", 4096),
        ("month", 0),
        ("month", 601),
        ("asset_ordinal", -1),
        ("asset_ordinal", 12),
        *[
            (field, value)
            for field in ("seed", "path_index", "month", "asset_ordinal")
            for value in (True, False, "1", 1.0, D(1), None)
        ],
    ],
)
def test_invalid_identity_fails_before_hashing_and_restores_context(
    monkeypatch: pytest.MonkeyPatch, field: str, value: Any
) -> None:
    def unexpected_hash(_payload: bytes) -> _Digest:
        raise AssertionError("An invalid sampler identity reached hashing.")

    monkeypatch.setattr(sampler, "sha256", unexpected_hash)
    arguments: dict[str, Any] = {"seed": 0, "path_index": 0, "month": 1, "asset_ordinal": 0}
    arguments[field] = value
    with localcontext(Context(prec=3, rounding=ROUND_DOWN, Emin=-9, Emax=9)) as hostile:
        hostile.traps[Inexact] = hostile.traps[Rounded] = True
        before = hostile.copy()
        with pytest.raises(DomainError) as failure:
            sampler.normal_at(**arguments)
        assert failure.value.code == ErrorCode.VALIDATION_FAILED
        _assert_context_unchanged(hostile, before)


def test_absolute_identity_survives_chunk_order_and_checkpoint_retry() -> None:
    seed = 20260914
    months = (1, 12, 600)
    assets = (0, 11)
    identities = [
        (seed, path, month, asset) for path in range(9) for month in months for asset in assets
    ]
    expected = {identity: _oracle(identity) for identity in identities}
    serial = {identity: sampler.normal_at(*identity) for identity in identities}
    for identity, value in serial.items():
        _assert_reference(value, expected[identity])

    # Chunks arrive out of order; paths 6..8 are redelivered after a restart.
    chunks = ((6, 7, 8), (0, 1), (5,), (2, 3, 4), (6, 7, 8))
    resumed: dict[Identity, Decimal] = {}
    for chunk in chunks:
        for path in chunk:
            for month in reversed(months):
                for asset in reversed(assets):
                    identity = (seed, path, month, asset)
                    result = sampler.normal_at(*identity)
                    _assert_reference(result, expected[identity])
                    resumed[identity] = result
    # Exact equality supplements the independent reference comparisons above.
    assert resumed == serial
