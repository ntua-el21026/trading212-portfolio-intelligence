"""Exact research item/revision selection has no implicit current-head lookup."""

import json
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from trading212_domain import reports as r
from trading212_domain.errors import DomainError
from trading212_domain.report_manifest import (
    build_report_manifest,
    decode_report_capture_v3,
    decode_report_header_v3,
    decode_report_manifest_v3,
    decode_report_selection,
    decode_report_selection_v3,
    encode_report_capture,
    encode_report_header,
    encode_report_manifest,
    encode_report_selection,
)
from trading212_domain.report_research import ReportResearchBinding, ReportResearchSelection
from trading212_domain.report_research_schema import RESEARCH_PROOF_TABLES, RESEARCH_REPORT_TABLES
from trading212_domain.report_schema import report_tables

from tests.unit.domain.report_factories import uid
from tests.unit.domain.report_research_factories import research_binding, research_capture
from tests.unit.domain.report_v3_factories import selection_v3

pytestmark = pytest.mark.unit


def test_research_selection_round_trips_exact_ids_without_a_fabricated_run() -> None:
    raw = json.loads(encode_report_selection(selection_v3()))
    raw["sections"] = ["overview", "allocation", "quality", "research"]
    raw["premium_run"] = {
        "item_id": str(uid(91)),
        "note_revision_ids": [str(uid(92)), str(uid(93))],
        "review_acknowledgment_id": str(uid(94)),
        "family": "research",
    }
    selected = decode_report_selection_v3(json.dumps(raw, separators=(",", ":")).encode())
    pin = selected.premium_run
    assert isinstance(pin, ReportResearchSelection)
    assert pin.family == "research"
    assert pin.item_id == uid(91)
    assert pin.note_revision_ids == (uid(92), uid(93))
    assert pin.review_acknowledgment_id == uid(94)
    assert not hasattr(pin, "run_id")
    assert decode_report_selection_v3(encode_report_selection(selected)) == selected


@pytest.mark.parametrize("notes,review", [(False, False), (True, False), (True, True)])
def test_complete_research_header_capture_and_manifest_round_trip(
    notes: bool, review: bool
) -> None:
    capture = research_capture(notes=notes, review=review)
    manifest = build_report_manifest(capture)
    assert decode_report_header_v3(encode_report_header(capture.header)) == capture.header
    assert decode_report_capture_v3(encode_report_capture(capture)) == capture
    assert decode_report_manifest_v3(encode_report_manifest(manifest)) == manifest
    pin = capture.header.premium_binding
    assert isinstance(pin, ReportResearchBinding)
    assert pin.source_cutoff_at != pin.xray_pin.source_cutoff_at
    assert not hasattr(pin, "run_id")
    assert not hasattr(pin, "completed_at")
    assert (b'"review_acknowledgment":' in encode_report_header(capture.header)) == review
    assert (
        b'"review_acknowledgment_id":' in encode_report_selection(capture.header.selection)
    ) == review
    with pytest.raises(DomainError):
        decode_report_selection(encode_report_selection(capture.header.selection))


@pytest.mark.parametrize(
    "change",
    [
        {"run_id": str(uid(99))},
        {"item_id": "latest"},
        {"note_revision_ids": None},
        {"note_revision_ids": [str(uid(92)), str(uid(92))]},
        {"note_revision_ids": [str(uid(200 + i)) for i in range(65)]},
        {"review_acknowledgment_id": None},
        {"family": "scenario"},
    ],
)
def test_research_codec_rejects_implicit_duplicate_null_and_extra_pins(
    change: dict[str, Any],
) -> None:
    raw = json.loads(encode_report_selection(research_capture().header.selection))
    raw["premium_run"].update(change)
    with pytest.raises(DomainError):
        decode_report_selection_v3(json.dumps(raw).encode())


def test_exact_note_set_is_required_and_canonicalized_without_latest_resolution() -> None:
    raw = json.loads(encode_report_selection(research_capture().header.selection))
    del raw["premium_run"]["note_revision_ids"]
    with pytest.raises(DomainError):
        decode_report_selection_v3(json.dumps(raw).encode())
    chosen = ReportResearchSelection(item_id=uid(80), note_revision_ids=(uid(93), uid(92)))
    assert chosen.note_revision_ids == (uid(92), uid(93))
    assert chosen.review_acknowledgment_id is None


@pytest.mark.parametrize("table", (*RESEARCH_REPORT_TABLES, *RESEARCH_PROOF_TABLES))
def test_every_research_descriptor_is_required_even_for_unselected_optional_evidence(
    table: r.ReportTableKey,
) -> None:
    header = research_capture(notes=False, review=False).header
    assert table in report_tables(header.selection)
    with pytest.raises(DomainError):
        replace(header, tables=tuple(item for item in header.tables if item.table is not table))


@pytest.mark.parametrize(
    "table",
    [
        r.ReportTableKey.RESEARCH_BASIS_V1,
        r.ReportTableKey.RESEARCH_EVENT_V1,
        r.ReportTableKey.RESEARCH_PORTFOLIO_V1,
        r.ReportTableKey.RESEARCH_XRAY_PIN_V1,
    ],
)
def test_research_canonical_singletons_cannot_be_empty(table: r.ReportTableKey) -> None:
    header = research_capture().header
    with pytest.raises(DomainError):
        replace(
            header,
            tables=tuple(
                replace(item, row_count=0) if item.table is table else item
                for item in header.tables
            ),
        )


@pytest.mark.parametrize("index", range(7))
def test_each_exact_item_event_note_review_snapshot_and_xray_binding_is_required(
    index: int,
) -> None:
    capture = research_capture()
    assert len(capture.immutable_bindings) == 7
    with pytest.raises(DomainError):
        replace(
            capture,
            immutable_bindings=tuple(
                item for ordinal, item in enumerate(capture.immutable_bindings) if ordinal != index
            ),
        )


@pytest.mark.parametrize(
    "kind",
    [
        r.ReportSourceKind.RESEARCH_ITEM,
        r.ReportSourceKind.RESEARCH_EVENT_REVISION,
        r.ReportSourceKind.RESEARCH_NOTE_REVISION,
        r.ReportSourceKind.RESEARCH_REVIEW_ACKNOWLEDGMENT,
        r.ReportSourceKind.RESEARCH_SOURCE_VERSION,
    ],
)
def test_selected_original_research_source_proof_cannot_disappear(kind: r.ReportSourceKind) -> None:
    capture = research_capture()
    with pytest.raises(DomainError):
        replace(
            capture,
            proof=replace(
                capture.proof,
                source_references=tuple(
                    source for source in capture.proof.source_references if source.kind is not kind
                ),
            ),
        )


def test_wrong_item_revision_review_or_selected_note_digest_does_not_relabel_a_capture() -> None:
    capture = research_capture()
    pin = capture.header.premium_binding
    assert isinstance(pin, ReportResearchBinding)
    with pytest.raises(DomainError):
        replace(pin, event_revision_id=uid(999))
    with pytest.raises(DomainError):
        replace(
            capture.header,
            selection=replace(
                capture.header.selection,
                premium_run=ReportResearchSelection(item_id=uid(999), note_revision_ids=()),
            ),
        )
    assert pin.review_acknowledgment is not None
    with pytest.raises(DomainError):
        replace(pin, review_acknowledgment=replace(pin.review_acknowledgment, account_id=uid(999)))
    changed = replace(
        pin, note_revisions=(replace(pin.note_revisions[0], content_digest="9" * 64),)
    )
    with pytest.raises(DomainError):
        replace(capture, header=replace(capture.header, premium_binding=changed))


def test_disabled_synthesis_is_explicit_and_cannot_be_removed_from_research_proof() -> None:
    capture = research_capture()
    with pytest.raises(DomainError):
        replace(
            capture,
            proof=replace(
                capture.proof,
                notes=tuple(
                    note
                    for note in capture.proof.notes
                    if note.code != "optional_synthesis_disabled"
                ),
            ),
        )


def test_selected_owner_revision_clocks_are_not_backdated_to_item_visibility_cutoff() -> None:
    pin = research_binding()
    assert pin.review_acknowledgment is not None
    later = replace(
        pin.review_acknowledgment, reviewed_at=pin.source_cutoff_at + timedelta(hours=1)
    )
    assert replace(pin, review_acknowledgment=later).review_acknowledgment == later


@pytest.mark.parametrize("kind", tuple(r.RESEARCH_REPORT_SOURCE_KINDS))
def test_research_source_vocabulary_cannot_be_hidden_in_earlier_profile3(
    kind: r.ReportSourceKind,
) -> None:
    from tests.unit.domain.report_v3_factories import capture_v3

    original = capture_v3()
    with pytest.raises(DomainError):
        replace(
            original,
            proof=replace(
                original.proof,
                source_references=(
                    r.ReportSourceReference(
                        key="research.hidden",
                        kind=kind,
                        subject_id=uid(80),
                        content_digest="0" * 64,
                    ),
                ),
            ),
        )
