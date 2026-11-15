"""Frozen chunk bytes and actual one-MiB envelope admission, without payload reuse."""

import json
from dataclasses import replace
from hashlib import sha256
from typing import cast

import pytest
from trading212_domain import report_manifest as codec
from trading212_domain import reports as r
from trading212_domain.errors import DomainError, ErrorCode

from tests.unit.domain.report_factories import document
from tests.unit.domain.test_report_encoding_stream_parity import (
    _original_primitive,
    _original_stream,
)

pytestmark = pytest.mark.unit


def _frozen(table: r.ReportTableKey, ordinal: int, rows: tuple[r.ReportRow, ...]) -> bytes:
    return _original_stream(
        {"table": table.value, "ordinal": ordinal, "rows": _original_primitive(rows)},
        r.MAX_REPORT_DOCUMENT_BYTES,
    )


@pytest.mark.parametrize("ordinal", [0, 99999])
def test_existing_financial_chunks_keep_frozen_complete_bytes_and_digests(ordinal: int) -> None:
    for original in document().chunks:
        expected = _frozen(original.table, ordinal, original.rows)
        candidate = r.ReportChunk(
            table=original.table,
            ordinal=ordinal,
            rows=original.rows,
            canonical_bytes=expected,
            digest=sha256(expected).hexdigest(),
        )
        assert codec.encode_report_chunk(candidate) == expected
        assert codec.decode_report_chunk(expected).digest == candidate.digest


def test_small_chunk_uses_c_json_after_exact_complete_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = document().chunks[0]
    expected = _frozen(original.table, original.ordinal, original.rows)
    dumps = json.dumps
    seen: list[object] = []

    def observed(
        value: object, *, ensure_ascii: bool, separators: tuple[str, str], allow_nan: bool
    ) -> str:
        assert ensure_ascii is False and separators == (",", ":") and allow_nan is False
        seen.append(value)
        return dumps(value, ensure_ascii=ensure_ascii, separators=separators, allow_nan=allow_nan)

    monkeypatch.setattr(json, "dumps", observed)
    assert codec.encode_report_chunk(original) == expected
    assert len(seen) == 1, "Each bounded chunk should use one preflighted C JSON encoding."


def _row(index: int, text: str) -> r.ReportRow:
    return r.ReportRow(
        key=f"row.{index}",
        context_key="context.snapshot",
        cells=(r.ReportCell(kind=r.CellKind.TEXT, value=text),),
    )


def _fitted_rows(target_bytes: int) -> tuple[r.ReportRow, ...]:
    """Fit the real fixed codec ceiling using an independent JSON row oracle."""
    rows: list[r.ReportRow] = []
    size = 2
    for index in range(512):
        item = _row(index, "A" * 4096)
        cost = len(_original_stream(_original_primitive(item), r.MAX_REPORT_CHUNK_BYTES))
        separator = int(bool(rows))
        if size + separator + cost <= target_bytes:
            rows.append(item)
            size += separator + cost
            continue
        empty = _row(index, "")
        empty_cost = len(_original_stream(_original_primitive(empty), r.MAX_REPORT_CHUNK_BYTES))
        padding = target_bytes - size - separator - empty_cost
        if padding < 0:
            assert rows
            previous = rows[-1]
            cell = previous.cells[0]
            previous_text = cast(str, cell.value)
            assert len(previous_text) >= -padding
            rows[-1] = replace(previous, cells=(replace(cell, value=previous_text[:padding]),))
            size += padding
            padding = 0
        assert 0 <= padding <= 4096
        rows.append(_row(index, "A" * padding))
        result = tuple(rows)
        assert (
            len(_original_stream(_original_primitive(result), r.MAX_REPORT_DOCUMENT_BYTES))
            == target_bytes
        )
        return result
    raise AssertionError("The fixed bounded fixture must fit within 512 ordinary rows.")


def test_actual_chunk_byte_limit_accepts_exact_envelope_and_rejects_one_more() -> None:
    table, ordinal = r.ReportTableKey.NOTES, 99999
    envelope = len(_frozen(table, ordinal, ())) - 2
    rows = _fitted_rows(r.MAX_REPORT_CHUNK_BYTES - envelope)
    expected = _frozen(table, ordinal, rows)
    assert len(expected) == r.MAX_REPORT_CHUNK_BYTES
    assert codec._chunk_payload(table, ordinal, rows) == expected
    last = rows[-1]
    cell = last.cells[0]
    oversized = (
        *rows[:-1],
        replace(last, cells=(replace(cell, value=cast(str, cell.value) + "A"),)),
    )
    with pytest.raises(DomainError) as rejected:
        codec._chunk_payload(table, ordinal, oversized)
    assert rejected.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    assert rejected.value.field == "encoded_bytes"


def test_envelope_overflow_rejects_before_constructing_the_complete_rows_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Rows themselves fit. The real one-MiB limit is crossed only by their fixed
    # table/ordinal/object envelope, which must be charged before graph allocation.
    rows = _fitted_rows(r.MAX_REPORT_CHUNK_BYTES - 1)
    table, ordinal = r.ReportTableKey.NOTES, 0
    assert len(_frozen(table, ordinal, rows)) > r.MAX_REPORT_CHUNK_BYTES
    primitive = codec._primitive

    def observed(value: object) -> codec.JsonValue:
        assert value is not rows, "The complete oversized chunk graph was allocated."
        return primitive(value)

    monkeypatch.setattr(codec, "_primitive", observed)
    with pytest.raises(DomainError) as rejected:
        codec._chunk_payload(table, ordinal, rows)
    assert rejected.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    assert rejected.value.field == "encoded_bytes"


@pytest.mark.parametrize("text", ['quotes" \\ \n Ελληνικά 中 😀', "\ud800"])
def test_chunk_unicode_bytes_and_failure_semantics_match_frozen_stream(text: str) -> None:
    rows = (_row(0, text),)
    try:
        expected = _frozen(r.ReportTableKey.NOTES, 0, rows)
    except DomainError as original:
        with pytest.raises(DomainError) as current:
            codec._chunk_payload(r.ReportTableKey.NOTES, 0, rows)
        assert (current.value.code, current.value.field) == (original.code, original.field)
    else:
        assert codec._chunk_payload(r.ReportTableKey.NOTES, 0, rows) == expected
