"""Legacy schema oracle and explicit pin codec regressions; UNEXECUTED draft."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

import pytest
from trading212_application.reports import GenerateReportCommand, report_request_digest
from trading212_domain import report_manifest as codec
from trading212_domain import reports as r
from trading212_domain.errors import DomainError
from trading212_domain.report_schema import report_tables, table_schema

from tests.unit.domain.report_factories import document, selection, uid

pytestmark = pytest.mark.unit

# Literal field order from frozen 0d7aa9b reports.py. This is a source-derived
# independent legacy schema oracle, not an observed historical runtime receipt.
LEGACY_REPORT_FIELDS = (
    "account_id",
    "start_date",
    "end_date",
    "source_cutoff_at",
    "snapshot_id",
    "reporting_currency",
    "report_type",
    "sections",
    "formats",
    "target_version_id",
    "plan_revision_id",
    "benchmark_version_id",
    "constituent_snapshot_id",
    "template_version",
)
LEGACY_EXPORT_FIELDS = (
    "account_id",
    "start_date",
    "end_date",
    "source_cutoff_at",
    "snapshot_id",
    "reporting_currency",
    "dataset",
    "field_set",
    "format",
    "target_version_id",
    "plan_revision_id",
    "benchmark_version_id",
    "constituent_snapshot_id",
)


def dump(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def legacy_bytes(value: r.ReportSelection | r.ExportSelection) -> bytes:
    names = LEGACY_REPORT_FIELDS if isinstance(value, r.ReportSelection) else LEGACY_EXPORT_FIELDS
    return dump({name: codec._primitive(getattr(value, name)) for name in names})


def drift_selection() -> r.ReportSelection:
    return replace(
        selection(),
        report_type=r.ReportType.TARGET_DRIFT,
        sections=(
            r.ReportSection.OVERVIEW,
            r.ReportSection.TARGETS,
            r.ReportSection.DRIFT,
            r.ReportSection.QUALITY,
        ),
        target_version_id=uid(7),
    )


def target_export() -> r.ExportSelection:
    value = drift_selection()
    return r.ExportSelection(
        account_id=value.account_id,
        start_date=value.start_date,
        end_date=value.end_date,
        source_cutoff_at=value.source_cutoff_at,
        snapshot_id=value.snapshot_id,
        reporting_currency=value.reporting_currency,
        dataset=r.ExportDataset.TARGETS,
        field_set=r.ExportFieldSet.AUDIT,
        format=r.ExportFormat.JSON,
        target_version_id=value.target_version_id,
    )


@pytest.mark.parametrize(
    "factory,decode",
    [
        (drift_selection, codec.decode_report_selection),
        (target_export, codec.decode_export_selection),
    ],
)
def test_absent_pin_exact_legacy_fields_bytes_and_digest_survive(factory: Any, decode: Any) -> None:
    value = factory()
    expected = legacy_bytes(value)
    assert b"xray_run_id" not in expected
    assert codec.encode_report_selection(value) == expected
    assert codec.encode_report_selection(decode(expected)) == expected
    assert (
        hashlib.sha256(codec.encode_report_selection(decode(expected))).digest()
        == hashlib.sha256(expected).digest()
    )
    extended = replace(value, xray_run_id=uid(9))
    payload = codec.encode_report_selection(extended)
    assert decode(payload) == extended
    assert hashlib.sha256(payload).digest() != hashlib.sha256(expected).digest()
    assert set(json.loads(payload)) == set(json.loads(expected)) | {"xray_run_id"}
    assert codec.encode_report_selection(replace(extended, xray_run_id=None)) == expected


def test_request_idempotency_framing_remains_exact_without_pin_and_binds_present_pin() -> None:
    command = GenerateReportCommand(
        selection=drift_selection(), idempotency_key="same-request", ttl_days=7
    )
    assert isinstance(command.selection, r.ReportSelection)
    legacy = legacy_bytes(command.selection)
    expected = hashlib.sha256(
        b"report_request_v1\0GenerateReportCommand\0"
        + len(legacy).to_bytes(8, "big")
        + legacy
        + b"\x07"
    ).hexdigest()
    assert report_request_digest(command) == expected
    assert (
        report_request_digest(
            replace(command, selection=replace(command.selection, xray_run_id=uid(9)))
        )
        != expected
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"xray_run_id": None},
        {"xray_run_id": True},
        {"xray_run_id": "latest"},
        {"company_basis": "unexpected"},
    ],
)
def test_stored_selection_accepts_only_legacy_or_explicit_uuid_pin_set(
    extra: dict[str, object],
) -> None:
    for value, decode in (
        (drift_selection(), codec.decode_report_selection),
        (target_export(), codec.decode_export_selection),
    ):
        raw = json.loads(legacy_bytes(value))
        # Insert before template_version for the canonical ReportSelection order.
        if "template_version" in raw:
            template = raw.pop("template_version")
            raw.update(extra)
            raw["template_version"] = template
        else:
            raw.update(extra)
        with pytest.raises(DomainError):
            decode(dump(raw))
        raw.pop("target_version_id")
        with pytest.raises(DomainError):
            decode(dump(raw))


def test_whole_legacy_manifest_bytes_match_the_frozen_field_order_oracle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = codec.encode_report_manifest(document().manifest)
    original = codec._field_names

    def legacy_fields(value: r.ReportRecord) -> tuple[str, ...]:
        if type(value) is r.ReportSelection:
            return LEGACY_REPORT_FIELDS
        if type(value) is r.ExportSelection:
            return LEGACY_EXPORT_FIELDS
        return original(value)

    with monkeypatch.context() as scope:
        scope.setattr(codec, "_field_names", legacy_fields)
        expected = codec.encode_report_manifest(document().manifest)
    assert current == expected
    assert codec.encode_report_manifest(codec.decode_report_manifest(expected)) == expected
    assert codec.report_manifest_digest(document().manifest) == hashlib.sha256(expected).hexdigest()


def test_additive_tables_require_pin_and_leave_all_legacy_schemas_unchanged() -> None:
    legacy = drift_selection()
    old = report_tables(legacy)
    added = report_tables(replace(legacy, xray_run_id=uid(9)))
    assert r.ReportTableKey.PLANNING_COMPANY_ACTUALS_V1 not in old
    assert r.ReportTableKey.PLANNING_COMPANY_BASIS_V1 not in old
    assert all(table in added for table in old)
    assert r.ReportTableKey.PLANNING_COMPANY_ACTUALS_V1 in added
    assert "company" not in " ".join(
        column.key for column in table_schema(r.ReportTableKey.DRIFT_ROWS).columns
    )
    assert codec.encode_report_selection(legacy) == legacy_bytes(legacy)
    with pytest.raises(DomainError):
        replace(selection(), xray_run_id=uid(9))
    with pytest.raises(DomainError):
        replace(
            target_export(),
            dataset=r.ExportDataset.POSITIONS,
            target_version_id=None,
            xray_run_id=uid(9),
        )


def test_valid_extended_selection_cannot_omit_any_legacy_field_or_add_generic_fields() -> None:
    for value, decode, names in (
        (drift_selection(), codec.decode_report_selection, LEGACY_REPORT_FIELDS),
        (target_export(), codec.decode_export_selection, LEGACY_EXPORT_FIELDS),
    ):
        payload = codec.encode_report_selection(replace(value, xray_run_id=uid(9)))
        assert decode(payload).xray_run_id == uid(9)
        raw = json.loads(payload)
        for name in names:
            changed = dict(raw)
            del changed[name]
            with pytest.raises(DomainError):
                decode(dump(changed))
        with pytest.raises(DomainError):
            decode(dump({**raw, "unexpected": "private-canary"}))
