"""Closed calendar/source-intent bytes reject malformed or contradictory evidence."""

import json
from dataclasses import replace
from decimal import ROUND_DOWN, Context, Inexact, Rounded, localcontext
from typing import Any
from uuid import UUID

import pytest
from trading212_application.projection_capture import projection_capture_bytes
from trading212_persistence.projection_capture_codec import (
    ProjectionCodecError,
    ProjectionCodecErrorCode,
    decode_projection_capture,
    encode_projection_capture,
)
from trading212_persistence.projection_retained_codec import (
    ProjectionInputBytes,
    pack_projection_input,
    unpack_projection_input,
)

from tests.unit.persistence.projection_codec_factories import binding, capture

pytestmark = pytest.mark.unit


def wire(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


@pytest.mark.parametrize("observed", (True, False))
@pytest.mark.parametrize("goal", (True, False))
def test_full_capture_round_trip_preserves_dates_source_pins_and_exact_money(
    observed: bool, goal: bool
) -> None:
    value = capture(observed=observed, goal=goal)
    encoded = encode_projection_capture(value)
    assert encoded == projection_capture_bytes(value)
    restored = decode_projection_capture(encoded, expected=binding(value))
    assert restored == value
    assert restored.calendar.boundaries == value.calendar.boundaries
    assert restored.selection.schedule.entries == value.selection.schedule.entries
    assert (
        restored.inputs.initial.value.amount.as_tuple()
        == value.inputs.initial.value.amount.as_tuple()
    )
    if observed:
        assert restored.snapshot is not None and value.snapshot is not None
        assert restored.snapshot.valuation_at == value.snapshot.valuation_at
        assert restored.snapshot.valuation_at.microsecond == 123456


def test_separate_input_bytes_retain_both_digests_and_declared_lengths() -> None:
    value = capture()
    packed = pack_projection_input(value)
    assert packed.capture_bytes == len(packed.canonical_capture)
    assert packed.input_bytes == len(packed.canonical_input)
    expected = binding(value)
    assert expected.capture_digest != expected.numerical_input_digest
    assert unpack_projection_input(packed, expected=expected) == value
    with pytest.raises(ProjectionCodecError):
        unpack_projection_input(
            packed,
            expected=replace(
                expected,
                capture_digest=expected.numerical_input_digest,
                numerical_input_digest=expected.capture_digest,
            ),
        )


@pytest.mark.parametrize(
    "identity", ("account_id", "assumption_version_id", "goal_version_id", "numerical_input_digest")
)
def test_expected_immutable_metadata_is_required(identity: str) -> None:
    value = capture()
    expected = binding(value)
    invalid: Any = "c" * 64 if identity == "numerical_input_digest" else UUID(int=999)
    with pytest.raises(ProjectionCodecError):
        decode_projection_capture(
            encode_projection_capture(value), expected=replace(expected, **{identity: invalid})
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "extra_field",
        "missing_field",
        "duplicate_field",
        "duplicate_nested",
        "trailing_data",
        "invalid_utf8",
        "whitespace",
        "boolean_seed",
        "float_money",
        "unknown_method",
        "bad_date",
        "offset_timestamp",
        "bad_uuid",
    ),
)
def test_malformed_even_rehashed_capture_never_falls_back(mutation: str) -> None:
    value = capture()
    original = encode_projection_capture(value)
    raw = json.loads(original)
    if mutation == "extra_field":
        raw["provider_url"] = "https://untrusted.invalid"
    elif mutation == "missing_field":
        raw.pop("snapshot")
    elif mutation == "boolean_seed":
        raw["selection"]["seed"] = True
    elif mutation == "float_money":
        raw["snapshot"]["value"]["amount"] = 1500.5
    elif mutation == "unknown_method":
        raw["schema_version"] = "next"
    elif mutation == "bad_date":
        raw["calendar"]["anchor_date"] = "2025-W05-5"
    elif mutation == "offset_timestamp":
        raw["snapshot"]["valuation_at"] = "2025-02-01T01:17:21.123456+02:00"
    elif mutation == "bad_uuid":
        raw["selection"]["account_id"] = raw["selection"]["account_id"].replace("-", "")
    malformed = wire(raw)
    if mutation == "duplicate_field":
        malformed = original[:-1] + b',"schema_version":"1.0.0"}'
    elif mutation == "duplicate_nested":
        malformed = original.replace(b'"seed":1945', b'"seed":1945,"seed":1945', 1)
    elif mutation == "trailing_data":
        malformed = original + b"{}"
    elif mutation == "invalid_utf8":
        malformed = original + b"\xff"
    elif mutation == "whitespace":
        malformed = b" " + original
    with pytest.raises(ProjectionCodecError) as rejected:
        decode_projection_capture(malformed, expected=binding(value, payload=malformed))
    assert str(rejected.value) == "The saved projection cannot be decoded."


@pytest.mark.parametrize(
    "mutation",
    (
        "calendar_boundary",
        "numerical_seed",
        "numerical_digest",
        "source_digest",
        "schedule_date",
        "goal_schedule_key",
        "snapshot_value",
    ),
)
def test_derived_or_pinned_evidence_cannot_be_repaired_by_decoding(mutation: str) -> None:
    value = capture()
    raw = json.loads(encode_projection_capture(value))
    if mutation == "calendar_boundary":
        raw["calendar"]["boundaries"][2] = "2025-03-28"
    elif mutation == "numerical_seed":
        raw["inputs"]["seed"] += 1
    elif mutation == "numerical_digest":
        raw["numerical_input_digest"] = "0" * 64
    elif mutation == "source_digest":
        raw["assumption_version"]["content_digest"] = "0" * 64
    elif mutation == "schedule_date":
        raw["selection"]["schedule"]["entries"][0]["on"] = "2025-02-01"
    elif mutation == "goal_schedule_key":
        raw["goal_version"]["content"]["schedule"]["entries"][0]["key"] = "renamed"
    elif mutation == "snapshot_value":
        raw["snapshot"]["value"]["amount"] = "1600"
    malformed = wire(raw)
    with pytest.raises(ProjectionCodecError):
        decode_projection_capture(malformed, expected=binding(value, payload=malformed))


def test_foreign_numerical_part_cannot_be_attached_to_a_valid_capture() -> None:
    first = capture()
    second = replace(first, selection=replace(first.selection, seed=17))
    one, two = pack_projection_input(first), pack_projection_input(second)
    mixed = replace(one, canonical_input=two.canonical_input, input_bytes=two.input_bytes)
    with pytest.raises(ProjectionCodecError):
        unpack_projection_input(mixed, expected=binding(first))
    with pytest.raises(ProjectionCodecError):
        unpack_projection_input(
            mixed,
            expected=replace(binding(first), numerical_input_digest=second.numerical_input_digest),
        )


def test_input_byte_declarations_and_combined_bound_fail_closed() -> None:
    value = pack_projection_input(capture())
    with pytest.raises(ProjectionCodecError):
        replace(value, input_bytes=value.input_bytes + 1)
    with pytest.raises(ProjectionCodecError):
        replace(value, capture_bytes=True)
    with pytest.raises(ProjectionCodecError) as over:
        ProjectionInputBytes(
            canonical_capture=b"x" * (16 * 1024 * 1024),
            canonical_input=b"x" * (16 * 1024 * 1024 + 1),
            capture_bytes=16 * 1024 * 1024,
            input_bytes=16 * 1024 * 1024 + 1,
        )
    assert over.value.code is ProjectionCodecErrorCode.INPUT_BOUND_EXCEEDED


def test_hostile_decimal_context_does_not_change_capture_bytes() -> None:
    value = capture()
    packed = pack_projection_input(value)
    expected = binding(value)
    hostile = Context(prec=2, rounding=ROUND_DOWN, Emin=-2, Emax=2)
    hostile.traps[Inexact] = True
    hostile.traps[Rounded] = True
    with localcontext(hostile):
        restored = unpack_projection_input(packed, expected=expected)
        assert encode_projection_capture(restored) == packed.canonical_capture
