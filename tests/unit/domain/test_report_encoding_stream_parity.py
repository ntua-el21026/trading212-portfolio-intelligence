"""Frozen field/writer oracles for class-only caching and bounded C encoding."""

import json
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import Field, fields, replace
from typing import cast

import pytest
from trading212_domain import report_manifest as codec
from trading212_domain import report_v3 as v3
from trading212_domain import reports as r
from trading212_domain.errors import DomainError, ErrorCode, fail_validation
from trading212_domain.report_v3 import ReportCaptureContract

from tests.unit.domain.report_factories import document
from tests.unit.domain.report_research_factories import research_capture
from tests.unit.domain.test_report_encoding_cost_parity import _CAPTURES

pytestmark = pytest.mark.unit

# Frozen pre-cache omission policy. Do not use the production optional-field
# registries: their exact bytes, including absent optional keys, are the oracle.
_OPTIONAL_CELL = frozenset(
    {
        "decimal_role",
        "currency",
        "context_key",
        "reason_key",
        "bound_key",
        "quality",
        "origin",
        "coverage_key",
        "confidence",
        "method_key",
        "method_version",
        "provenance_set_key",
        "note_set_key",
    }
)
_OPTIONAL_V3 = {
    v3.ReportSelectionV3: frozenset({"xray_run_id"}),
    v3.ReportRiskRunBinding: frozenset({"xray", "benchmark_version_id"}),
    v3.ReportScenarioRunBinding: frozenset({"historical"}),
    v3.ReportResearchSelection: frozenset({"review_acknowledgment_id"}),
    v3.ReportResearchBinding: frozenset({"review_acknowledgment"}),
}
_PROFILES: tuple[Callable[[], ReportCaptureContract], ...] = (
    *_CAPTURES,
    research_capture,
    lambda: research_capture(notes=False, review=False),
)
_PROFILE_NAMES = ["v1", "v2", "v3-scenario", "v3-risk", "v4", "research", "research-no-review"]


def _original_field_names(value: r.ReportRecord) -> tuple[str, ...]:
    return tuple(
        item.name
        for item in fields(value)
        if not (
            getattr(value, item.name) is None
            and (
                (type(value) is r.ReportCell and item.name in _OPTIONAL_CELL)
                or (
                    type(value) in (r.ReportSelection, r.ExportSelection)
                    and item.name == "xray_run_id"
                )
                or (type(value) is r.ReportSelection and item.name == "risk_run_id")
                or item.name in _OPTIONAL_V3.get(type(value), frozenset())
            )
        )
    )


def _original_primitive(value: object) -> codec.JsonValue:
    if type(value) is tuple:
        return [_original_primitive(item) for item in value]
    if type(value) in codec._RECORDS:
        return {
            name: _original_primitive(getattr(value, name))
            for name in _original_field_names(cast(r.ReportRecord, value))
        }
    # The original scalar normalizer is intentionally unchanged by this task.
    return codec._primitive(value)


def _original_stream(value: codec.JsonValue, maximum: int) -> bytes:
    output = bytearray()
    for part in json.JSONEncoder(
        ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).iterencode(value):
        try:
            encoded = part.encode("utf-8")
        except UnicodeEncodeError:
            fail_validation("Report text must be valid Unicode.", field="text")
        r.report_limit(len(output) + len(encoded) <= maximum, "encoded_bytes")
        output.extend(encoded)
    return bytes(output)


def _records(value: object) -> Iterator[r.ReportRecord]:
    if type(value) is tuple:
        for item in value:
            yield from _records(item)
    elif type(value) in codec._RECORDS:
        record = cast(r.ReportRecord, value)
        yield record
        for item in fields(record):
            yield from _records(getattr(record, item.name))


@pytest.mark.parametrize("capture", _PROFILES, ids=_PROFILE_NAMES)
def test_every_profile_keeps_frozen_omission_policy_and_streaming_bytes(
    capture: Callable[[], ReportCaptureContract],
) -> None:
    summary = capture()
    manifest = codec.build_report_manifest(summary)
    for value in (summary.header.selection, summary.header, summary.proof, summary, manifest):
        for record in _records(value):
            parameters = getattr(type(record), "__dataclass_params__", None)
            assert parameters is not None and parameters.frozen
            assert codec._field_names(record) == _original_field_names(record)
        expected = _original_stream(_original_primitive(value), r.MAX_REPORT_DOCUMENT_BYTES)
        assert codec._encode(value, len(expected)) == expected
        with pytest.raises(DomainError) as rejected:
            codec._encode(value, len(expected) - 1)
        assert rejected.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
        assert rejected.value.field == "encoded_bytes"


@pytest.mark.parametrize("capture", _PROFILES, ids=_PROFILE_NAMES)
def test_class_field_policy_reuses_only_public_reflection_and_keeps_instance_omissions(
    capture: Callable[[], ReportCaptureContract], monkeypatch: pytest.MonkeyPatch
) -> None:
    values = tuple(_records(capture()))
    expected = tuple(_original_field_names(value) for value in values)
    reflected: Counter[type[object]] = Counter()
    original = fields

    def observe(value: r.ReportRecord | type[r.ReportRecord]) -> tuple[Field[object], ...]:
        reflected[value if isinstance(value, type) else type(value)] += 1
        return original(value)

    monkeypatch.setattr(codec, "fields", observe)
    for _ in range(3):
        assert tuple(codec._field_names(value) for value in values) == expected
    assert all(count <= 1 for count in reflected.values()), reflected


def _proof(*, notes: int, text: str) -> r.ReportProof:
    template = document().capture.proof.notes[0]
    return r.ReportProof(
        notes=tuple(replace(template, key=f"note.{index}", text=text) for index in range(notes))
    )


def test_small_frozen_graph_uses_c_json_only_after_exact_utf8_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mixed-width text also covers controls, quotes, backslashes, combining marks
    # and non-BMP characters without an ASCII-only surrogate escape shortcut.
    proof = _proof(notes=3, text='ASCII "\\\n Ελληνικά 中 e\u0301 \U0001f600\u2028\u2029')
    expected = _original_stream(_original_primitive(proof), r.MAX_REPORT_MANIFEST_BYTES)
    measured = False
    calls = []
    measure, primitive, dumps = codec._measure, codec._primitive, json.dumps

    def observe_measure(value: object, maximum: int) -> int:
        nonlocal measured
        size = measure(value, maximum)
        if value is proof:
            measured = True
            assert size == len(expected)
        return size

    def observe_primitive(value: object) -> codec.JsonValue:
        if value is proof:
            assert measured, "Primitive graph construction preceded the complete UTF8 preflight."
        return primitive(value)

    def observe_dumps(
        value: object, *, ensure_ascii: bool, separators: tuple[str, str], allow_nan: bool
    ) -> str:
        assert measured
        assert ensure_ascii is False and separators == (",", ":") and allow_nan is False
        calls.append(value)
        return dumps(value, ensure_ascii=ensure_ascii, separators=separators, allow_nan=allow_nan)

    monkeypatch.setattr(codec, "_measure", observe_measure)
    monkeypatch.setattr(codec, "_primitive", observe_primitive)
    monkeypatch.setattr(json, "dumps", observe_dumps)
    assert codec._encode(proof, len(expected)) == expected
    assert len(calls) == 1


def test_large_legal_graph_keeps_original_streaming_path_without_a_new_admission_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = _proof(notes=513, text="a" * 4095 + "\U0001f600")
    expected = _original_stream(_original_primitive(proof), r.MAX_REPORT_DOCUMENT_BYTES)
    assert r.MAX_REPORT_MANIFEST_BYTES < len(expected) < r.MAX_REPORT_DOCUMENT_BYTES

    def forbidden(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("A large legal capture must retain the streaming allocation path.")

    monkeypatch.setattr(json, "dumps", forbidden)
    assert codec._encode(proof, len(expected)) == expected


def test_oversized_graph_is_rejected_before_either_json_or_primitive_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = _proof(notes=3, text="\U0001f600" * 4096)
    original = codec._primitive

    def observe(value: object) -> codec.JsonValue:
        assert value is not proof, "The oversized root primitive graph was allocated."
        return original(value)

    def forbidden(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("The oversized graph reached JSON output allocation.")

    monkeypatch.setattr(codec, "_primitive", observe)
    monkeypatch.setattr(json, "dumps", forbidden)
    with pytest.raises(DomainError) as rejected:
        codec._encode(proof, 128)
    assert rejected.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    assert rejected.value.field == "encoded_bytes"


@pytest.mark.parametrize("value", ["\ud800", "\udfff", "prefix\ud800suffix", "\ud83d\ude00"])
@pytest.mark.parametrize("maximum", [0, 1, 100])
def test_c_path_preserves_frozen_stream_invalid_unicode_errors_before_allocation(
    value: str, maximum: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(DomainError) as reference:
        _original_stream(value, maximum)

    def forbidden(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("Invalid Unicode reached JSON output allocation.")

    monkeypatch.setattr(json, "dumps", forbidden)
    with pytest.raises(DomainError) as actual:
        codec._encode(cast(r.ReportRecord, value), maximum)
    assert (actual.value.code, actual.value.field, actual.value.message) == (
        reference.value.code,
        reference.value.field,
        reference.value.message,
    )
