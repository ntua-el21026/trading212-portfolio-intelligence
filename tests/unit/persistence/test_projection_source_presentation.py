"""Exact original identity locations and explicit knowledge-clock semantics."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from trading212_domain.enums import QualityState
from trading212_domain.historical_serialization import historical_input_digest
from trading212_domain.serialization import canonical_json
from trading212_persistence.projection_definition_store import ProjectionStorageError
from trading212_persistence.projection_source_presentation import (
    projection_source_presentation,
    projection_sources_presentation,
)
from trading212_persistence.projection_source_store import (
    ProjectionCapturedSource,
    ProjectionSourceBundle,
    ProjectionSourceHeader,
)

from tests.unit.analytics.historical_factories import fixture

pytestmark = pytest.mark.unit
AT = datetime(2026, 9, 1, 12, 1, 2, 123456, tzinfo=UTC)


def uid(value: int) -> UUID:
    return UUID(int=value)


def _source(header: ProjectionSourceHeader, **parts: Any) -> ProjectionCapturedSource:
    proof = {
        "schema": "projection_source_proof_v1",
        "source_kind": header.kind,
        "subject_id": header.subject_id,
        "content_digest": header.content_digest,
        "original_created_at": header.original_created_at,
        "physical_expires_at": None
        if header.kind in ("portfolio_snapshot", "historical_input")
        else header.expires_at,
        "metadata": header.metadata,
        "licenses": tuple(
            {"id": value, "provider_id": uid(90)} for value in header.license_version_ids
        ),
        **parts,
    }
    return ProjectionCapturedSource(
        header=header, quality=QualityState.PARTIAL, canonical_proof=canonical_json(proof).encode()
    )


def snapshot() -> ProjectionCapturedSource:
    metadata = (
        {
            "table": "portfolio_snapshots",
            "id": uid(1),
            "calculation_run_id": uid(2),
            "source_cutoff_at": AT,
            "owner_id": uid(999),
        },
        {"table": "calculation_runs", "id": uid(2), "source_cutoff_at": AT},
    )
    header = ProjectionSourceHeader(
        kind="portfolio_snapshot",
        role="initial_snapshot",
        subject_id=uid(1),
        content_digest="a" * 64,
        original_created_at=AT + timedelta(hours=1),
        expires_at=AT + timedelta(days=30),
        metadata=metadata,
        license_version_ids=(),
    )
    return _source(
        header,
        snapshot={"id": uid(1), "calculation_run_id": uid(2), "source_cutoff_at": AT},
        calculation={
            "id": uid(2),
            "input_ids": (uid(3), uid(4)),
            "source_cutoff_at": AT,
            "arbitrary_text": str(uid(999)),
        },
        positions=(
            {
                "id": uid(5),
                "snapshot_id": uid(1),
                "listing_id": uid(6),
                "provenance": {"source_record_ids": (uid(7),)},
                "comment": str(uid(998)),
            },
        ),
        cash=(
            {
                "id": uid(8),
                "snapshot_id": uid(1),
                "provenance": {"source_record_ids": (uid(9), uid(7))},
            },
        ),
    )


def provider() -> ProjectionCapturedSource:
    metadata = (
        {
            "table": "price_snapshots",
            "id": uid(20),
            "provider_id": uid(90),
            "license_version_id": uid(91),
            "series_id": uid(21),
            "first_observed_at": AT,
        },
        {
            "table": "market_source_series",
            "id": uid(21),
            "provider_id": uid(90),
            "license_version_id": uid(91),
            "calendar_id": uid(22),
            "mapping_id": uid(23),
            "instrument_id": uid(24),
            "listing_id": uid(25),
        },
        {"table": "source_calendars", "id": uid(22)},
        {
            "table": "market_data_instruments",
            "id": uid(23),
            "provider_id": uid(90),
            "instrument_id": uid(24),
            "listing_id": uid(25),
        },
    )
    header = ProjectionSourceHeader(
        kind="price_total_return",
        role="calibration",
        subject_id=uid(20),
        content_digest="b" * 64,
        original_created_at=AT + timedelta(hours=2),
        expires_at=AT + timedelta(days=20),
        metadata=metadata,
        license_version_ids=(uid(91),),
    )
    return _source(
        header,
        snapshot={
            "id": uid(20),
            "provenance": {
                "first_observed_at": AT,
                "effective_at": AT - timedelta(days=3),
                "provider_id": uid(90),
                "license_version_id": uid(91),
            },
        },
        original_observations=(
            {"id": uid(26), "snapshot_id": uid(20), "value": "100", "note": str(uid(999))},
        ),
        original_gaps=({"id": uid(27), "price_snapshot_id": uid(20)},),
        series=metadata[1],
        mapping=(metadata[3],),
        mapping_candidates=(
            {"id": uid(28), "mapping_id": uid(23), "instrument_id": uid(29), "listing_id": uid(30)},
        ),
        calendar={"id": uid(22), "key": str(uid(997))},
        calendar_sessions=({"id": uid(31), "calendar_id": uid(22)},),
    )


def bundle(*sources: ProjectionCapturedSource) -> ProjectionSourceBundle:
    return ProjectionSourceBundle(
        snapshot=None,
        sources=sources,
        expires_at=AT + timedelta(days=20),
        license_version_ids=tuple(
            sorted({v for source in sources for v in source.header.license_version_ids})
        ),
    )


def test_snapshot_exact_source_ids_and_microsecond_cutoff_without_uuid_text_walk() -> None:
    source = snapshot()
    value = projection_source_presentation(source)
    assert value.evidence.role == "observed_snapshot"
    assert value.evidence.source_reference_ids == tuple(uid(i) for i in range(1, 10))
    assert value.evidence.quality is QualityState.PARTIAL
    assert value.source_cutoff_at == AT and value.source_cutoff_at.microsecond == 123456
    assert value.first_observed_at is None
    assert projection_sources_presentation(bundle(source)).source_cutoff_at == AT


def test_provider_full_ids_and_original_observation_clock_never_become_cutoff() -> None:
    value = projection_source_presentation(provider())
    assert value.evidence.source_reference_ids == tuple(
        sorted((*[uid(i) for i in range(20, 32)], uid(90), uid(91)))
    )
    assert value.source_cutoff_at is None and value.first_observed_at == AT
    only = projection_sources_presentation(bundle(provider()))
    mixed = projection_sources_presentation(bundle(snapshot(), provider()))
    assert only.source_cutoff_at is None and mixed.source_cutoff_at is None
    assert mixed.sources[0].source_cutoff_at == AT
    assert mixed.sources[1].first_observed_at == AT


def test_exact_historical_source_reference_parents_and_original_cutoff() -> None:
    original = fixture()
    cutoff = original.selection.window.source_cutoff_at
    source_refs = original.sources
    assert source_refs
    # Existing canonical historical evidence declares parent identities explicitly.
    changed = replace(source_refs[0], parent_ids=(str(uid(801)),))
    original = replace(original, sources=(changed, *source_refs[1:]))
    digest = historical_input_digest(original)
    metadata = (
        {"table": "historical_input_snapshots", "id": uid(800), "source_cutoff_at": cutoff},
    )
    header = ProjectionSourceHeader(
        kind="historical_input",
        role="calibration",
        subject_id=uid(800),
        content_digest=digest,
        original_created_at=AT,
        expires_at=AT + timedelta(days=20),
        metadata=metadata,
        license_version_ids=(),
    )
    source = _source(header, canonical_input=canonical_json(original))
    result = projection_source_presentation(source)
    expected = {uid(800), uid(801), *(UUID(ref.id) for ref in original.sources)}
    assert result.evidence.source_reference_ids == tuple(sorted(expected))
    assert result.source_cutoff_at == cutoff
    assert result.first_observed_at is None


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_table",
        "missing_id",
        "clock",
        "foreign_metadata",
        "extra_proof",
        "noncanonical_uuid",
        "role",
    ],
)
def test_bad_retained_provenance_fails_closed(mutation: str) -> None:
    source = snapshot()
    data = json.loads(source.canonical_proof)
    if mutation == "unknown_table":
        data["metadata"][1]["table"] = "principals"
        source = replace(source, header=replace(source.header, metadata=tuple(data["metadata"])))
    elif mutation == "missing_id":
        del data["positions"][0]["id"]
    elif mutation == "clock":
        data["snapshot"]["source_cutoff_at"] = "2026-09-02T00:00:00Z"
    elif mutation == "foreign_metadata":
        data["metadata"][0]["id"] = str(uid(900))
    elif mutation == "extra_proof":
        data["extension"] = str(uid(900))
    elif mutation == "role":
        source = replace(source, header=replace(source.header, role="calibration"))
    else:
        data["positions"][0]["id"] = "00000000000000000000000000000005"
    source = replace(source, canonical_proof=canonical_json(data).encode())
    with pytest.raises(ProjectionStorageError):
        projection_source_presentation(source)


def test_empty_modeled_evidence_has_no_fabricated_identity_or_clock() -> None:
    value = projection_sources_presentation(bundle())
    assert value.evidence == () and value.sources == () and value.source_cutoff_at is None


def test_cutoff_is_maximum_explicit_original_cutoff_only_when_all_are_known() -> None:
    source = snapshot()
    data = json.loads(source.canonical_proof)
    newer = AT + timedelta(minutes=5)
    for row in data["metadata"]:
        row["source_cutoff_at"] = newer
    data["snapshot"]["source_cutoff_at"] = newer
    data["calculation"]["source_cutoff_at"] = newer
    header = replace(source.header, metadata=tuple(data["metadata"]))
    later = replace(source, header=header, canonical_proof=canonical_json(data).encode())
    value = projection_sources_presentation(bundle(source, later))
    assert value.source_cutoff_at == newer
