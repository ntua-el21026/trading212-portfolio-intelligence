"""Premium report semantics are explicit while legacy bytes retain their identity."""

import hashlib
import json
from dataclasses import replace
from typing import Any

import pytest
from trading212_domain import reports as r
from trading212_domain.errors import DomainError
from trading212_domain.report_manifest import (
    build_report_manifest,
    decode_report_capture,
    decode_report_context,
    decode_report_header,
    decode_report_manifest,
    decode_report_selection,
    encode_report_capture,
    encode_report_context,
    encode_report_header,
    encode_report_manifest,
    encode_report_proof,
    encode_report_schema,
    encode_report_selection,
    report_document_digest,
    report_table_digest,
)
from trading212_domain.report_risk_schema import RISK_PROOF_TABLES, RISK_REPORT_TABLES
from trading212_domain.report_schema import report_tables, section_tables, table_schema

from tests.unit.domain.report_factories import ZERO_DIGEST, document, selection, uid
from tests.unit.domain.test_report_company_compatibility import drift_selection, legacy_bytes

pytestmark = pytest.mark.unit


def _premium(value: r.ReportSelection | None = None) -> r.ReportSelection:
    value = value or selection()
    return replace(value, sections=(*value.sections, r.ReportSection.RISK), risk_run_id=uid(90))


def _capture() -> r.ReportCaptureSummary:
    original = document().capture
    assert isinstance(original.header.selection, r.ReportSelection)
    selection_v2 = _premium(original.header.selection)
    contexts = tuple(
        replace(item, schema_version=r.PREMIUM_REPORT_SCHEMA_VERSION)
        for item in original.proof.contexts
    )
    risk = replace(
        contexts[0],
        key="risk.fixture",
        family=r.ReportFamily.RISK,
        method_key="risk_v1",
        method_version="1.0.0",
    )
    proof = replace(original.proof, contexts=(*contexts, risk))
    tables = (
        *original.header.tables,
        *(
            r.ReportTableDescriptor(
                table=table,
                schema_digest=hashlib.sha256(encode_report_schema(table_schema(table))).hexdigest(),
                row_count=0,
                content_digest=report_table_digest(table, ()),
                section=r.ReportSection.RISK if table in RISK_REPORT_TABLES else None,
            )
            for table in (*RISK_REPORT_TABLES, *RISK_PROOF_TABLES)
        ),
    )
    proof_digest = hashlib.sha256(encode_report_proof(proof)).hexdigest()
    header = replace(
        original.header,
        selection=selection_v2,
        document_schema_version=r.PREMIUM_REPORT_SCHEMA_VERSION,
        tables=tables,
        context_digest=proof_digest,
        document_digest=ZERO_DIGEST,
    )
    header = replace(header, document_digest=report_document_digest(header))
    return replace(original, header=header, proof=proof, proof_digest=proof_digest)


@pytest.mark.parametrize("company", [False, True])
def test_absent_risk_pin_preserves_independent_legacy_bytes_and_company_extension(
    company: bool,
) -> None:
    original = drift_selection()
    if company:
        original = replace(original, xray_run_id=uid(9))
        expected_fields = json.loads(legacy_bytes(original))
        template = expected_fields.pop("template_version")
        expected_fields["xray_run_id"] = str(uid(9))
        expected_fields["template_version"] = template
        expected = json.dumps(expected_fields, ensure_ascii=False, separators=(",", ":")).encode()
    else:
        expected = legacy_bytes(original)
    assert encode_report_selection(original) == expected
    assert b"risk_run_id" not in expected
    assert encode_report_selection(decode_report_selection(expected)) == expected
    assert r.report_schema_version(original) == "1.0.0"
    assert r.report_profile_version(original) == "report_sections_v1"


@pytest.mark.parametrize("company", [False, True])
def test_risk_pin_is_encoded_only_when_selected_and_changes_immutable_identity(
    company: bool,
) -> None:
    original = drift_selection()
    if company:
        original = replace(original, xray_run_id=uid(9))
    chosen = _premium(original)
    encoded = encode_report_selection(chosen)
    assert decode_report_selection(encoded) == chosen
    assert json.loads(encoded)["risk_run_id"] == str(uid(90))
    assert set(json.loads(encoded)) == set(json.loads(encode_report_selection(original))) | {
        "risk_run_id"
    }
    assert (
        hashlib.sha256(encoded).digest()
        != hashlib.sha256(encode_report_selection(original)).digest()
    )
    assert r.report_schema_version(chosen) == "2.0.0"
    assert r.report_profile_version(chosen) == "report_sections_v2"
    assert chosen.template_version == original.template_version == "report_template_v1"
    restored = replace(chosen, risk_run_id=None, sections=original.sections)
    assert encode_report_selection(restored) == encode_report_selection(original)


@pytest.mark.parametrize(
    "change",
    [
        {"risk_run_id": uid(90)},
        {"sections": (*selection().sections, r.ReportSection.RISK)},
        {"risk_run_id": "latest"},
        {"risk_run_id": True},
    ],
)
def test_risk_section_and_canonical_pin_are_required_together(change: dict[str, Any]) -> None:
    with pytest.raises(DomainError):
        replace(selection(), **change)


@pytest.mark.parametrize("bad", [None, True, "latest", "null", 1])
def test_decoder_rejects_explicit_null_or_non_uuid_risk_pin(bad: object) -> None:
    raw = json.loads(encode_report_selection(_premium()))
    raw["risk_run_id"] = bad
    with pytest.raises(DomainError):
        decode_report_selection(json.dumps(raw, separators=(",", ":")).encode())


def test_decoder_rejects_unknown_selection_version_or_field() -> None:
    raw = json.loads(encode_report_selection(_premium()))
    raw["profile_version"] = "report_sections_v3"
    with pytest.raises(DomainError):
        decode_report_selection(json.dumps(raw, separators=(",", ":")).encode())


def test_complete_section_selection_keeps_legacy_order_and_appends_risk() -> None:
    original = selection()
    chosen = replace(
        original,
        sections=tuple(
            r.ReportSection(x)
            for x in (
                "overview",
                "allocation",
                "targets",
                "drift",
                "contribution_plan",
                "performance",
                "benchmark",
                "income",
                "cash_flows",
                "attribution",
                "xray",
                "quality",
                "activity",
                "risk",
            )
        ),
        risk_run_id=uid(90),
        target_version_id=uid(7),
        plan_revision_id=uid(8),
        benchmark_version_id=uid(9),
        constituent_snapshot_id=uid(10),
    )
    assert len(chosen.sections) == 14
    assert chosen.sections[-1] is r.ReportSection.RISK
    assert section_tables(r.ReportSection.RISK) == RISK_REPORT_TABLES
    tables = report_tables(chosen)
    assert set((*RISK_REPORT_TABLES, *RISK_PROOF_TABLES)) <= set(tables)
    assert tuple(
        table for table in tables if table in (*RISK_REPORT_TABLES, *RISK_PROOF_TABLES)
    ) == (
        *RISK_REPORT_TABLES,
        *RISK_PROOF_TABLES,
    )
    assert not set(report_tables(original)) & set((*RISK_REPORT_TABLES, *RISK_PROOF_TABLES))


def test_premium_manifest_capture_header_and_context_roundtrip_use_explicit_v2() -> None:
    capture = _capture()
    manifest = build_report_manifest(capture)
    assert decode_report_header(encode_report_header(capture.header)) == capture.header
    assert decode_report_capture(encode_report_capture(capture)) == capture
    assert decode_report_manifest(encode_report_manifest(manifest)) == manifest
    assert manifest.document.document_schema_version == "2.0.0"
    assert {context.schema_version for context in manifest.contexts} == {"2.0.0"}
    assert manifest.method == "report_manifest_v1"
    assert manifest.method_version == "1.0.0"
    assert manifest.renderer_profile == document().capture.renderer_profile
    assert {table_schema(table).schema_version for table in RISK_REPORT_TABLES} == {"1.0.0"}
    for context in manifest.contexts:
        assert decode_report_context(encode_report_context(context)) == context


@pytest.mark.parametrize("version", ["1.0.0", "3.0.0", "", None])
def test_premium_header_rejects_old_unknown_or_null_document_version(version: object) -> None:
    raw = json.loads(encode_report_header(_capture().header))
    raw["document_schema_version"] = version
    with pytest.raises(DomainError):
        decode_report_header(json.dumps(raw, separators=(",", ":")).encode())


def test_legacy_header_rejects_premium_version_or_risk_tables() -> None:
    original = document().header
    with pytest.raises(DomainError):
        replace(original, document_schema_version="2.0.0")
    premium_table = next(
        table for table in _capture().header.tables if table.table in RISK_REPORT_TABLES
    )
    with pytest.raises(DomainError):
        replace(original, tables=(*original.tables, premium_table))


def test_premium_header_requires_all_analytical_and_proof_tables() -> None:
    header = _capture().header
    for table in (*RISK_REPORT_TABLES, *RISK_PROOF_TABLES):
        with pytest.raises(DomainError):
            replace(header, tables=tuple(item for item in header.tables if item.table is not table))


@pytest.mark.parametrize("version", ["1.0.0", "3.0.0", "", None])
def test_risk_context_rejects_legacy_unknown_and_null_versions(version: object) -> None:
    risk = next(item for item in _capture().proof.contexts if item.family is r.ReportFamily.RISK)
    raw = json.loads(encode_report_context(risk))
    raw["schema_version"] = version
    with pytest.raises(DomainError):
        decode_report_context(json.dumps(raw, separators=(",", ":")).encode())


def test_v2_capture_rejects_legacy_context_even_when_its_family_is_legacy() -> None:
    capture = _capture()
    legacy = next(item for item in capture.proof.contexts if item.family is not r.ReportFamily.RISK)
    wrong = replace(legacy, schema_version="1.0.0")
    proof = replace(
        capture.proof,
        contexts=tuple(wrong if item == legacy else item for item in capture.proof.contexts),
    )
    with pytest.raises(DomainError):
        replace(capture, proof=proof)
    manifest = build_report_manifest(capture)
    with pytest.raises(DomainError):
        replace(manifest, contexts=proof.contexts)


def test_v1_manifest_rejects_risk_proof_without_a_premium_selection() -> None:
    manifest = document().manifest
    risk_context = next(
        item for item in _capture().proof.contexts if item.family is r.ReportFamily.RISK
    )
    with pytest.raises(DomainError):
        replace(manifest, contexts=(*manifest.contexts, risk_context))
    risk_note = r.ReportNote(
        key="risk.warning",
        family=r.ReportFamily.RISK,
        text="incomplete_universe",
        kind=r.ReportNoteKind.WARNING,
        code="incomplete_universe",
    )
    with pytest.raises(DomainError):
        replace(manifest, notes=(*manifest.notes, risk_note))


def test_premium_manifest_cannot_omit_the_risk_family_context() -> None:
    manifest = build_report_manifest(_capture())
    with pytest.raises(DomainError):
        replace(
            manifest,
            contexts=tuple(
                item for item in manifest.contexts if item.family is not r.ReportFamily.RISK
            ),
        )
