"""Independent earlier-profile fields/tables protect bytes during registry additions."""

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from trading212_domain import reports as r
from trading212_domain.report_manifest import (
    build_report_manifest,
    encode_report_capture,
    encode_report_context,
    encode_report_header,
    encode_report_manifest,
    encode_report_selection,
)
from trading212_domain.report_schema import table_schema
from trading212_domain.values import CurrencyCode

from tests.unit.domain.report_factories import document
from tests.unit.domain.test_premium_report_versions import _capture as capture_v2

pytestmark = pytest.mark.unit
FIXTURES = Path(__file__).with_name("fixtures")
FIELDS: dict[str, list[str]] = json.loads(
    (FIXTURES / "report-legacy-record-fields.json").read_text()
)
COLUMNS: dict[str, list[list[str]]] = json.loads(
    (FIXTURES / "report-legacy-table-columns.json").read_text()
)
# Frozen omissions from the pre-V3 contract, independent of the current field registry.
CELL_OPTIONAL = frozenset(
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


def _legacy(value: object) -> Any:
    if value is None or type(value) in (str, bool, int):
        return value
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, CurrencyCode):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return (
            value.astimezone(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "")
            .rstrip("0")
            .rstrip(".")
            + "Z"
        )
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        text = format(value, "f")
        return "0" if value == 0 else text.rstrip("0").rstrip(".") if "." in text else text
    if isinstance(value, tuple):
        return [_legacy(x) for x in value]
    name = type(value).__name__
    assert name in FIELDS
    result = {}
    for field in FIELDS[name]:
        item = getattr(value, field)
        omitted = item is None and (
            (name == "ReportCell" and field in CELL_OPTIONAL)
            or (name in {"ReportSelection", "ExportSelection"} and field == "xray_run_id")
            or (name == "ReportSelection" and field == "risk_run_id")
        )
        if not omitted:
            result[field] = _legacy(item)
    return result


def _bytes(value: object) -> bytes:
    return json.dumps(_legacy(value), ensure_ascii=False, separators=(",", ":")).encode()


@pytest.mark.parametrize("premium", [False, True])
def test_full_earlier_selection_context_header_capture_manifest_bytes_are_unchanged(
    premium: bool,
) -> None:
    capture = capture_v2() if premium else document().capture
    manifest = build_report_manifest(capture)
    for value, encode in (
        (capture.header.selection, encode_report_selection),
        (capture.header, encode_report_header),
        (capture, encode_report_capture),
        (manifest, encode_report_manifest),
    ):
        actual = encode(value)  # type: ignore[arg-type]
        expected = _bytes(value)
        assert actual == expected
        assert hashlib.sha256(actual).digest() == hashlib.sha256(expected).digest()
        assert b"premium_run" not in actual
        assert b"premium_binding" not in actual
        assert b"report_sections_v3" not in actual
    for context in capture.proof.contexts:
        assert encode_report_context(context) == _bytes(context)


@pytest.mark.parametrize("name", tuple(COLUMNS))
def test_every_legacy_table_retains_exact_order_kind_role_optionality_and_version(
    name: str,
) -> None:
    schema = table_schema(r.ReportTableKey[name])
    role = {
        "M": "money",
        "R": "ratio",
        "Q": "quantity",
        "D(score)": "score",
        "D": "score",
        "D(price)": "price",
        "D(fx)": "fx",
        "D(residual)": "residual",
        "D(money)": "money",
    }
    scalar = {
        "id": "identifier",
        "text": "text",
        "enum": "enum",
        "date": "date",
        "utc": "instant",
        "int": "integer",
        "bool": "boolean",
    }
    expected = []
    for key, code in COLUMNS[name]:
        actual = code.removesuffix("?")
        expected.append(
            (
                key,
                None if actual == "N" else "decimal" if actual in role else scalar[actual],
                role.get(actual),
                code.endswith("?"),
            )
        )
    assert [
        (
            x.key,
            None if x.kind is None else x.kind.value,
            None if x.decimal_role is None else x.decimal_role.value,
            x.optional,
        )
        for x in schema.columns
    ] == expected
    assert schema.schema_version == "1.0.0"
    assert schema.order.value == "canonical"
