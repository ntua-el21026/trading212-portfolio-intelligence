"""CSV and XLSX retain complete proof schemas and canonical rows in bounded cells."""

import csv
from dataclasses import replace
from hashlib import sha256
from io import BytesIO, StringIO
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from trading212_domain import reports as r
from trading212_domain.report_manifest import (
    build_report_chunk,
    decode_report_row,
    encode_report_manifest,
    encode_report_row,
    encode_report_schema,
    report_document_digest,
    report_table_digest,
)
from trading212_domain.report_schema import table_schema
from trading212_persistence.report_capture_common import capture_row

from tests.unit.domain.report_factories import AT, ReportFixture, document, uid
from tests.unit.persistence.test_report_capture_builder import builder
from tests.unit.worker.test_private_report_renderers import render

pytestmark = pytest.mark.unit
TABLE = r.ReportTableKey.PLAN_SOURCE_DETAILS


def proof_document() -> ReportFixture:
    fixture = document()
    target, _ = builder()
    context = fixture.capture.proof.contexts[0]
    target.add_context(context)
    rows = tuple(
        capture_row(
            target,
            context,
            TABLE,
            key=f"proof.source.{ordinal}",
            values={
                "context_key": context.key,
                "kind": "snapshot",
                "id": uid(2),
                "version": ' =SUM(1,2); "Ελληνική"\n' + "λ" * 4060,
                "content_digest": "0" * 64,
                "effective_at": AT,
                "first_observed_at": AT,
            },
        )
        for ordinal in range(2)
    )
    descriptor = r.ReportTableDescriptor(
        table=TABLE,
        row_count=len(rows),
        schema_digest=sha256(encode_report_schema(table_schema(TABLE))).hexdigest(),
        content_digest=report_table_digest(TABLE, rows),
    )
    header = replace(fixture.header, tables=(*fixture.header.tables, descriptor))
    header = replace(header, document_digest=report_document_digest(header))
    chunk = build_report_chunk(TABLE, 0, rows)
    fixture = replace(
        fixture,
        chunks=(*fixture.chunks, chunk),
        capture=replace(
            fixture.capture, header=header, chunk_count=fixture.capture.chunk_count + 1
        ),
    )
    return replace(
        fixture,
        capture=replace(
            fixture.capture,
            canonical_byte_length=sum(len(chunk.canonical_bytes) for chunk in fixture.chunks)
            + len(encode_report_manifest(fixture.manifest)),
        ),
    )


@pytest.mark.parametrize("format", [r.ReportFormat.CSV, r.ReportFormat.XLSX])
def test_proof_fragments_reconstruct_all_rows_schema_and_hashes(format: r.ReportFormat) -> None:
    fixture = proof_document()
    payload = render(fixture, format)
    if format is r.ReportFormat.CSV:
        records = list(csv.DictReader(StringIO(payload.decode(), newline="")))
    else:
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        records = []
        with ZipFile(BytesIO(payload)) as archive:
            for name in archive.namelist():
                if not name.startswith("xl/worksheets/sheet"):
                    continue
                sheet = ElementTree.fromstring(archive.read(name))  # noqa: S314 - local rendered fixture
                assert not sheet.findall(".//s:f", ns)
                assert not sheet.findall(".//s:hyperlink", ns)
                values = [
                    [node.text or "" for node in row.findall("s:c/s:is/s:t", ns)]
                    for row in sheet.findall("s:sheetData/s:row", ns)
                ]
                if values and values[0][0] == "section":
                    records.extend(dict(zip(values[0], row, strict=True)) for row in values[1:])
    proof = [row for row in records if row["section"] == "proof"]
    assert proof and all(row["table"] == TABLE.value for row in proof)
    assert all(row["value"].startswith("json:") and len(row["value"]) <= 4005 for row in proof)
    schemas = [row for row in proof if row["column_key"].startswith("schema.")]
    assert [row["column_key"] for row in schemas] == [
        f"schema.{ordinal:06d}" for ordinal in range(len(schemas))
    ]
    schema_bytes = "".join(row["value"][5:] for row in schemas).encode()
    assert schema_bytes == encode_report_schema(table_schema(TABLE))
    expected = fixture.chunks[-1].rows
    decoded = []
    for ordinal, original in enumerate(expected):
        pieces = [row for row in proof if row["column_key"].startswith(f"row.{ordinal:06d}.")]
        assert len(pieces) > 1
        assert [row["column_key"] for row in pieces] == [
            f"row.{ordinal:06d}.{index:06d}" for index in range(len(pieces))
        ]
        assert all(row["row_key"] == original.key for row in pieces)
        assert all(row["context_key"] == original.context_key for row in pieces)
        canonical = "".join(row["value"][5:] for row in pieces).encode()
        assert canonical == encode_report_row(original)
        decoded.append(decode_report_row(canonical))
    assert tuple(decoded) == expected
    assert report_table_digest(TABLE, decoded) == fixture.header.tables[-1].content_digest
