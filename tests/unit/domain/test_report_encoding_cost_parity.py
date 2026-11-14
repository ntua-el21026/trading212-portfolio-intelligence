"""Independent JSON byte/cap oracles and fixed-public-schema cache boundaries."""

import json
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from typing import cast
from uuid import UUID

import pytest
from trading212_domain import report_manifest as codec
from trading212_domain import report_v4 as v4
from trading212_domain import reports as r
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.report_profile import renderer_profile
from trading212_domain.report_schema import table_schema
from trading212_domain.report_v3 import ReportCaptureContract, ReportManifestContract
from trading212_domain.values import CurrencyCode
from trading212_persistence.report_capture_projection import project_projection

from tests.unit.domain.report_factories import document
from tests.unit.domain.report_v3_factories import capture_v3
from tests.unit.domain.test_premium_report_versions import _capture as capture_v2
from tests.unit.persistence.projection_report_factories import case as projection_case

pytestmark = pytest.mark.unit

_SCALARS = (
    (None, None),
    (True, True),
    (False, False),
    (0, 0),
    (-1, -1),
    (10**40, 10**40),
    ("", ""),
    ("ASCII", "ASCII"),
    ('quote" slash/ backslash\\', 'quote" slash/ backslash\\'),
    ("".join(chr(value) for value in range(32)), "".join(chr(value) for value in range(32))),
    ("Ελληνικά\u0000\n", "Ελληνικά\u0000\n"),
    ("中\U0001f600e\u0301\u2028\u2029", "中\U0001f600e\u0301\u2028\u2029"),
    (Decimal("-0.000"), "0"),
    (Decimal("12.3400"), "12.34"),
    (Decimal("0.000000000000000001"), "0.000000000000000001"),
    (date(2026, 11, 14), "2026-11-14"),
    (datetime(2026, 11, 14, 12, 0, 0, 123000, tzinfo=UTC), "2026-11-14T12:00:00.123Z"),
    (datetime(2026, 11, 14, 14, 0, tzinfo=timezone(timedelta(hours=2))), "2026-11-14T12:00:00Z"),
    (UUID(int=123), "00000000-0000-0000-0000-00000000007b"),
    (CurrencyCode("EUR"), "EUR"),
    (r.ReportFormat.JSON, "json"),
)


@pytest.mark.parametrize("value,expected", _SCALARS)
def test_independent_scalar_bytes_measure_exact_cap_and_one_short(
    value: object, expected: object
) -> None:
    reference = json.dumps(
        expected, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    assert codec._measure(value, len(reference)) == len(reference)
    assert codec._json(codec._primitive(value), len(reference)) == reference
    with pytest.raises(DomainError) as rejected:
        codec._measure(value, len(reference) - 1)
    assert rejected.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    assert rejected.value.field == "encoded_bytes"


@pytest.mark.parametrize("value", ["\ud800", "\udfff", "prefix\ud800suffix", "\ud83d\ude00"])
@pytest.mark.parametrize("maximum", [0, 1, 100])
def test_invalid_unicode_precedes_scalar_capacity_with_the_same_error(
    value: str, maximum: int
) -> None:
    with pytest.raises(DomainError) as measured:
        codec._measure(value, maximum)
    with pytest.raises(DomainError) as written:
        codec._json(value, maximum)
    assert (measured.value.code, measured.value.field) == (written.value.code, written.value.field)
    assert measured.value.field == "text"


@pytest.mark.parametrize("value", [[], {}, b"bytes", 0.5])
def test_scalar_measurement_keeps_the_closed_type_boundary(value: object) -> None:
    with pytest.raises(DomainError) as rejected:
        codec._measure(value, 1000)
    assert rejected.value.field == "record"


def test_oversized_record_is_refused_before_constructing_its_primitive_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    note = document().capture.proof.notes[0]
    proof = r.ReportProof(notes=(replace(note, text="\U0001f600" * 4096),))
    original = codec._primitive

    def observe(value: object) -> codec.JsonValue:
        assert value is not proof, "The complete oversized primitive graph was constructed."
        return original(value)

    monkeypatch.setattr(codec, "_primitive", observe)
    with pytest.raises(DomainError) as rejected:
        codec._encode(proof, 128)
    assert rejected.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    assert rejected.value.field == "encoded_bytes"


def test_only_fixed_public_schemas_are_reused_and_custom_schema_bytes_stay_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The independent stdlib oracle preserves dataclass declaration order. Schema
    # records contain only public strings/enums/booleans/nulls, never private facts.
    for key in r.ReportTableKey:
        schema = table_schema(key)
        reference = json.dumps(
            asdict(schema), ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
        assert codec.encode_report_schema(schema) == reference
    schema = table_schema(r.ReportTableKey.ALERT_EVENTS)
    custom = replace(
        schema,
        columns=(replace(schema.columns[0], key="private_schema_canary"), *schema.columns[1:]),
    )
    expected = codec.encode_report_schema(schema)
    custom_expected = json.dumps(
        asdict(custom), ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()
    encoded: list[object] = []
    original = codec._encode

    def observe(value: r.ReportRecord, maximum: int) -> bytes:
        encoded.append(value)
        return original(value, maximum)

    monkeypatch.setattr(codec, "_encode", observe)
    for _ in range(3):
        assert codec.encode_report_schema(schema) == expected
    assert sum(value is schema for value in encoded) <= 1
    for _ in range(2):
        assert codec.encode_report_schema(custom) == custom_expected != expected
    assert sum(value is custom for value in encoded) == 2
    assert codec.encode_report_schema(schema) == expected


def _capture_v4() -> v4.ReportCaptureSummaryV4:
    fixture = projection_case(goal=False, sensitive=False)
    binding = project_projection(fixture.builder, fixture.captured, fixture.saved, fixture.metadata)
    proof = v4.ReportProofV4(
        contexts=tuple(fixture.builder.contexts.values()),
        notes=tuple(fixture.builder.notes.values()),
        note_memberships=tuple(fixture.builder.note_memberships),
    )
    proof_digest = sha256(codec.encode_report_proof(proof)).hexdigest()
    header = v4.ReportDocumentHeaderV4(
        selection=fixture.builder.selection,
        owner_id=fixture.builder.owner_id,
        valuation_at=fixture.builder.valuation_at,
        context_digest=proof_digest,
        tables=fixture.builder.descriptors(),
        document_digest="0" * 64,
        premium_binding=binding,
    )
    header = replace(header, document_digest=codec.report_document_digest(header))
    return v4.ReportCaptureSummaryV4(
        header=header,
        canonical_byte_length=0,
        chunk_count=0,
        immutable_bindings=tuple(fixture.builder.bindings),
        proof=proof,
        proof_digest=proof_digest,
        renderer_profile=renderer_profile(fixture.builder.selection.formats),
        copy_expires_at=fixture.metadata.expires_at,
    )


_CAPTURES: tuple[Callable[[], ReportCaptureContract], ...] = (
    lambda: document().capture,
    capture_v2,
    capture_v3,
    lambda: capture_v3(risk=True),
    _capture_v4,
)


@pytest.mark.parametrize("capture", _CAPTURES, ids=["v1", "v2", "v3-scenario", "v3-risk", "v4"])
def test_build_and_encode_preserves_public_manifest_type_bytes_and_validation(
    capture: Callable[[], ReportCaptureContract],
) -> None:
    summary = capture()
    expected = codec.build_report_manifest(summary)
    payload = codec.encode_report_manifest(expected)
    candidate = getattr(codec, "build_and_encode_report_manifest", None)
    assert callable(candidate), "The validated build-and-encode helper is required."
    build = cast(Callable[[ReportCaptureContract], tuple[ReportManifestContract, bytes]], candidate)
    actual, encoded = build(summary)
    assert type(actual) is type(expected) and actual == expected
    assert encoded == payload
    broken = replace(summary, proof_digest="f" * 64)
    with pytest.raises(DomainError):
        codec.build_report_manifest(broken)
    with pytest.raises(DomainError):
        build(broken)


def test_v4_build_and_encode_keeps_independent_profile_and_schema_checks() -> None:
    summary = _capture_v4()
    candidate = getattr(codec, "build_and_encode_report_manifest", None)
    assert callable(candidate), "The validated build-and-encode helper is required."
    build = cast(Callable[[ReportCaptureContract], tuple[ReportManifestContract, bytes]], candidate)
    table = replace(summary.header.tables[0], schema_digest="f" * 64)
    header = replace(summary.header, tables=(table, *summary.header.tables[1:]))
    header = replace(header, document_digest=codec.report_document_digest(header))
    corrupted = replace(summary, header=header)
    with pytest.raises(DomainError) as old:
        codec.build_report_manifest(corrupted)
    with pytest.raises(DomainError) as new:
        build(corrupted)
    assert old.value.field == new.value.field == "schema_digest"
