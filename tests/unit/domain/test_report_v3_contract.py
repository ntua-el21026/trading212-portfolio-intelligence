"""Explicit profile-three semantics cannot reinterpret the legacy report contracts."""

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from trading212_domain import report_v3 as v3
from trading212_domain import reports as r
from trading212_domain.errors import DomainError
from trading212_domain.report_manifest import (
    build_report_manifest,
    decode_report_capture,
    decode_report_capture_v3,
    decode_report_header,
    decode_report_header_v3,
    decode_report_manifest,
    decode_report_manifest_v3,
    decode_report_selection,
    decode_report_selection_v3,
    encode_report_capture,
    encode_report_header,
    encode_report_manifest,
    encode_report_selection,
)
from trading212_domain.report_scenario_schema import SCENARIO_PROOF_TABLES, SCENARIO_REPORT_TABLES
from trading212_domain.report_schema import report_tables, section_tables
from trading212_domain.values import CurrencyCode

from tests.unit.domain.report_factories import AT, selection, uid
from tests.unit.domain.report_v3_factories import binding_v3, capture_v3, selection_v3
from tests.unit.domain.test_premium_report_versions import _capture as capture_v2

pytestmark = pytest.mark.unit


def _bytes(raw: object) -> bytes:
    return json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode()


@pytest.mark.parametrize("risk", [False, True])
def test_v3_selection_has_one_explicit_variant_and_independent_fixed_bytes(risk: bool) -> None:
    value = selection_v3(risk=risk)
    family = "risk" if risk else "scenario"
    # Fixed wire fields/order; do not derive this expectation from dataclass fields/codec output.
    expected = _bytes(
        {
            "account_id": str(uid(1)),
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "source_cutoff_at": "2026-08-31T21:00:00Z",
            "snapshot_id": str(uid(2)),
            "reporting_currency": "EUR",
            "report_type": "portfolio_summary",
            "sections": ["overview", "allocation", "quality", family],
            "formats": ["pdf", "csv", "json", "xlsx"],
            "premium_run": {"run_id": str(uid(90)), "family": family},
            "target_version_id": None,
            "plan_revision_id": None,
            "benchmark_version_id": None,
            "constituent_snapshot_id": None,
            "template_version": "report_template_v1",
            "profile_version": "report_sections_v3",
        }
    )
    assert encode_report_selection(value) == expected
    assert decode_report_selection_v3(expected) == value
    assert r.report_schema_version(value) == "3.0.0"
    assert r.report_profile_version(value) == "report_sections_v3"
    assert b"risk_run_id" not in expected
    assert b"scenario_run_id" not in expected
    with pytest.raises(DomainError):
        decode_report_selection(expected)
    assert (
        hashlib.sha256(expected).digest()
        != hashlib.sha256(encode_report_selection(selection())).digest()
    )


@pytest.mark.parametrize(
    "change",
    [
        {"premium_run": None},
        {"premium_run": []},
        {"premium_run": {"run_id": str(uid(90)), "family": "projection"}},
        {"premium_run": {"run_id": "latest", "family": "scenario"}},
        {
            "premium_run": {
                "run_id": str(uid(90)),
                "family": "scenario",
                "risk_run_id": str(uid(91)),
            }
        },
        {"premium_runs": []},
        {"risk_run_id": str(uid(91))},
        {"profile_version": "report_sections_v2"},
        {"sections": ["overview", "allocation", "quality", "risk", "scenario"]},
        {"sections": ["overview", "allocation", "quality"]},
        {"xray_run_id": None},
    ],
)
def test_v3_decoder_rejects_implicit_unknown_null_and_multiple_variants(
    change: dict[str, Any],
) -> None:
    raw = json.loads(encode_report_selection(selection_v3()))
    raw.update(change)
    with pytest.raises(DomainError):
        decode_report_selection_v3(_bytes(raw))


@pytest.mark.parametrize("family", ["projection", "goal", "research"])
def test_reserved_family_cannot_be_selected_or_rendered_as_success(family: str) -> None:
    section = r.ReportSection(family)
    with pytest.raises(DomainError):
        replace(selection_v3(), sections=(*selection().sections, section))
    with pytest.raises(DomainError):
        section_tables(section)
    with pytest.raises(DomainError):
        replace(capture_v3().proof.contexts[0], family=r.ReportFamily(family))


@pytest.mark.parametrize("risk", [False, True])
def test_v3_capture_manifest_and_header_round_trip_through_explicit_codecs(risk: bool) -> None:
    capture = capture_v3(risk=risk)
    header = encode_report_header(capture.header)
    encoded = encode_report_capture(capture)
    manifest = build_report_manifest(capture)
    rendered = encode_report_manifest(manifest)
    assert decode_report_header_v3(header) == capture.header
    assert decode_report_capture_v3(encoded) == capture
    assert decode_report_manifest_v3(rendered) == manifest
    for old_decoder, payload in (
        (decode_report_header, header),
        (decode_report_capture, encoded),
        (decode_report_manifest, rendered),
    ):
        with pytest.raises(DomainError):
            old_decoder(payload)
    with pytest.raises(DomainError):
        decode_report_capture_v3(encode_report_capture(capture_v2()))


@pytest.mark.parametrize(
    "change",
    [
        {"owner_id": uid(333)},
        {"account_id": uid(333)},
        {"snapshot_id": uid(333)},
        {"reporting_currency": CurrencyCode("USD")},
        {"source_cutoff_at": AT + timedelta(seconds=1)},
        {"valuation_at": AT + timedelta(seconds=1)},
        {"run_id": uid(333)},
    ],
)
def test_header_rejects_cross_owner_account_run_and_monetary_basis(change: dict[str, Any]) -> None:
    capture = capture_v3()
    with pytest.raises(DomainError):
        replace(capture.header, premium_binding=replace(capture.header.premium_binding, **change))


@pytest.mark.parametrize(
    "state",
    [
        r.ReportJobState.QUEUED,
        r.ReportJobState.RUNNING,
        r.ReportJobState.FAILED,
        r.ReportJobState.CANCELLED,
        r.ReportJobState.EXPIRED,
    ],
)
def test_binding_requires_succeeded_complete_unexpired_metadata(state: r.ReportJobState) -> None:
    with pytest.raises(DomainError):
        replace(binding_v3(), state=state)
    with pytest.raises(DomainError):
        replace(binding_v3(), expires_at=binding_v3().completed_at)


@pytest.mark.parametrize(
    "field", ["input_digest", "result_digest", "snapshot_digest", "scenario_version_digest"]
)
def test_capture_rejects_typed_pin_digest_that_is_not_the_original_proof(field: str) -> None:
    original = capture_v3()
    change: dict[str, Any] = {field: "9" * 64}
    pin = replace(original.header.premium_binding, **change)
    header = replace(original.header, premium_binding=pin)
    with pytest.raises(DomainError):
        replace(original, header=header)


@pytest.mark.parametrize("index", range(7))
def test_capture_requires_every_original_run_definition_snapshot_xray_history_binding(
    index: int,
) -> None:
    original = capture_v3()
    changed = tuple(value for i, value in enumerate(original.immutable_bindings) if i != index)
    with pytest.raises(DomainError):
        replace(original, immutable_bindings=changed)


def test_same_family_extra_run_cannot_enter_the_single_run_report() -> None:
    original = capture_v3()
    extra = replace(original.immutable_bindings[0], subject_id=uid(456))
    with pytest.raises(DomainError):
        replace(original, immutable_bindings=(*original.immutable_bindings, extra))


def test_proof_cannot_mix_context_versions_or_other_premium_families() -> None:
    original = capture_v3()
    for change in ({"schema_version": "2.0.0"}, {"family": r.ReportFamily.RISK}):
        with pytest.raises(DomainError):
            context = replace(original.proof.contexts[0], **change)
            replace(
                original,
                proof=replace(original.proof, contexts=(context, *original.proof.contexts[1:])),
            )
    with pytest.raises(DomainError):
        replace(
            original,
            copy_expires_at=original.header.premium_binding.expires_at + timedelta(seconds=1),
        )
    with pytest.raises(DomainError):
        replace(original, copy_expires_at=None)


@pytest.mark.parametrize("key", (*SCENARIO_REPORT_TABLES, *SCENARIO_PROOF_TABLES))
def test_complete_registry_descriptors_required_even_when_proof_has_zero_rows(
    key: r.ReportTableKey,
) -> None:
    original = capture_v3().header
    assert key in report_tables(original.selection)
    with pytest.raises(DomainError):
        replace(original, tables=tuple(x for x in original.tables if x.table is not key))


def test_zero_optional_proof_is_explicit_but_empty_scenario_success_is_rejected() -> None:
    original = capture_v3().header
    assert all(x.row_count == 0 for x in original.tables if x.table in SCENARIO_PROOF_TABLES)
    for key in (
        r.ReportTableKey.SCENARIO_BASIS_V1,
        r.ReportTableKey.SCENARIO_DEFINITION_V1,
        r.ReportTableKey.SCENARIO_SUMMARY_V1,
    ):
        with pytest.raises(DomainError):
            replace(
                original,
                tables=tuple(
                    replace(x, row_count=0) if x.table is key else x for x in original.tables
                ),
            )


def test_legacy_profile_cannot_hide_scenario_proof_in_ordinary_table_or_context() -> None:
    original = capture_v2()
    newer = capture_v3()
    scenario_table = next(
        x for x in newer.header.tables if x.table is r.ReportTableKey.SCENARIO_SUBJECTS_V1
    )
    with pytest.raises(DomainError):
        replace(original.header, tables=(*original.header.tables, scenario_table))
    with pytest.raises(DomainError):
        replace(
            original,
            proof=replace(
                original.proof,
                notes=(
                    r.ReportNote(
                        key="scenario.hidden",
                        kind=r.ReportNoteKind.WARNING,
                        family=r.ReportFamily.SCENARIO,
                        code="hidden",
                        text="hidden",
                    ),
                ),
            ),
        )
    with pytest.raises(DomainError):
        replace(
            original,
            proof=replace(
                original.proof,
                source_references=(
                    r.ReportSourceReference(
                        key="scenario.hidden",
                        kind=r.ReportSourceKind.SCENARIO_SENSITIVITY_EVIDENCE,
                        subject_id=uid(1),
                        content_digest="0" * 64,
                    ),
                ),
            ),
        )


def test_shared_dispatch_reads_only_actual_typed_run_pins() -> None:
    ordinary = selection()
    risk = selection_v3(risk=True)
    scenario = selection_v3()
    assert v3.is_report_selection(ordinary)
    assert v3.is_report_selection(scenario)
    assert v3.selected_risk_run_id(ordinary) is None
    assert v3.selected_scenario_run_id(ordinary) is None
    assert v3.selected_risk_run_id(risk) == uid(90)
    assert v3.selected_scenario_run_id(risk) is None
    assert v3.selected_risk_run_id(scenario) is None
    assert v3.selected_scenario_run_id(scenario) == uid(90)
    assert v3.selected_report_formats(scenario) == ordinary.formats
    assert v3.report_base_selection(scenario) == ordinary


def test_explicit_risk_profile_keeps_its_actual_historical_window() -> None:
    original = capture_v3(risk=True).header
    pin = original.premium_binding
    assert isinstance(pin, v3.ReportRiskRunBinding)
    with pytest.raises(DomainError):
        replace(
            original, premium_binding=replace(pin, start_date=pin.start_date + timedelta(days=1))
        )


def test_new_context_uses_explicit_codec_and_does_not_widen_old_context_decoder() -> None:
    from trading212_domain.report_manifest import (
        decode_report_context,
        decode_report_context_v3,
        encode_report_context,
    )

    actual = capture_v3().proof.contexts[0]
    encoded = encode_report_context(actual)
    assert decode_report_context_v3(encoded) == actual
    with pytest.raises(DomainError):
        decode_report_context(encoded)
