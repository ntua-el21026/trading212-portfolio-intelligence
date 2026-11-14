"""Closed DTO parity over structural domain proofs; no financial rendering claim."""

import json
from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError
from trading212_api_contracts import premium_reports_v3 as wire
from trading212_domain.report_manifest import (
    build_report_manifest,
    encode_report_manifest,
    encode_report_selection,
)

from tests.unit.domain.report_research_factories import research_capture


def manifest(*, notes: bool = True, review: bool = True) -> dict[str, Any]:
    value = json.loads(
        encode_report_manifest(build_report_manifest(research_capture(notes=notes, review=review)))
    )
    assert isinstance(value, dict)
    return value


@pytest.mark.parametrize(("notes", "review"), ((False, False), (True, False), (True, True)))
def test_research_selection_and_complete_structural_manifest_match_closed_api_contracts(
    notes: bool,
    review: bool,
) -> None:
    capture = research_capture(notes=notes, review=review)
    chosen = wire.GeneratePremiumReportRequestV3.model_validate_json(
        encode_report_selection(capture.header.selection)
    )
    parsed = wire.PremiumReportManifestV3.model_validate(manifest(notes=notes, review=review))
    assert isinstance(chosen.premium_run, wire.PremiumReportResearchSelectionV3)
    assert isinstance(parsed.document.premium_binding, wire.PremiumReportResearchBindingV3)
    binding = parsed.document.premium_binding
    assert chosen.premium_run.item_id == binding.item_id
    assert chosen.premium_run.note_revision_ids == [
        note.revision_id for note in binding.note_revisions
    ]
    assert binding.source_cutoff_at != binding.xray_pin.source_cutoff_at
    assert not hasattr(binding, "run_id")
    assert not hasattr(binding, "completed_at")
    assert (binding.review_acknowledgment is not None) == review


@pytest.mark.parametrize(
    "changed",
    (
        "item_digest",
        "invented_run",
        "null_review",
        "table",
        "notes",
        "source",
        "context",
        "synthesis",
    ),
)
def test_mismatched_or_incomplete_research_manifest_fails_closed(changed: str) -> None:
    value = deepcopy(manifest())
    binding = value["document"]["premium_binding"]
    if changed == "item_digest":
        binding["item_selection_digest"] = "0" * 64
    elif changed == "invented_run":
        binding["run_id"] = binding["item_id"]
    elif changed == "null_review":
        binding["review_acknowledgment"] = None
    elif changed == "table":
        value["document"]["tables"] = [
            table
            for table in value["document"]["tables"]
            if table["table"] != "research_xray_pin_v1"
        ]
    elif changed == "notes":
        value["document"]["selection"]["premium_run"]["note_revision_ids"] = []
    elif changed == "source":
        value["source_references"] = [
            item for item in value["source_references"] if item["kind"] != "research_source_version"
        ]
    elif changed == "context":
        next(item for item in value["contexts"] if item["family"] == "research")["method_key"] = (
            "unsupported_method"
        )
    else:
        value["notes"] = [
            item for item in value["notes"] if item["code"] != "optional_synthesis_disabled"
        ]
    with pytest.raises(ValidationError):
        wire.PremiumReportManifestV3.model_validate(value)
