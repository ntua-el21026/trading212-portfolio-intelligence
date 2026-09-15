"""Closed original provenance projection after retained-source authorization and verification.

These pure helpers neither authorize a subject nor reopen source storage. A UUID,
digest or typed input is not permission to invoke them with private source bytes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from trading212_application.projection_presentation import ProjectionRetainedEvidence
from trading212_domain.errors import DomainError
from trading212_domain.historical_serialization import (
    historical_input_digest,
    historical_input_from_json,
)
from trading212_domain.projection import PROJECTION_MAX_BYTES
from trading212_domain.serialization import canonical_json
from trading212_domain.values import require_utc, utc_string

from .projection_source_store import ProjectionCapturedSource, ProjectionSourceBundle, unavailable

_BASE = frozenset(
    (
        "schema",
        "source_kind",
        "subject_id",
        "content_digest",
        "original_created_at",
        "physical_expires_at",
        "metadata",
        "licenses",
    )
)
_ROOTS = {
    "portfolio_snapshot": "portfolio_snapshots",
    "historical_input": "historical_input_snapshots",
    "price_total_return": "price_snapshots",
    "benchmark_total_return": "benchmark_snapshots",
}
_PARTS = {
    "portfolio_snapshot": frozenset(("snapshot", "calculation", "positions", "cash")),
    "historical_input": frozenset(("canonical_input",)),
    "price_total_return": frozenset(
        (
            "snapshot",
            "original_observations",
            "original_gaps",
            "series",
            "mapping",
            "mapping_candidates",
            "calendar",
            "calendar_sessions",
        )
    ),
    "benchmark_total_return": frozenset(
        (
            "snapshot",
            "original_observations",
            "original_gaps",
            "series",
            "mapping",
            "mapping_candidates",
            "calendar",
            "calendar_sessions",
        )
    ),
}
# Only declared source identity columns are recognized. Owner/account identities,
# labels, free text and UUID-looking values elsewhere are deliberately not traversed.
_FIELDS = {
    "historical_input_snapshots": ("id", "policy_id", "benchmark_version_id", "target_version_id"),
    "ingestion_runs": ("id",),
    "source_records": ("id",),
    "source_record_occurrences": ("id", "source_record_id"),
    "portfolio_snapshots": ("id", "calculation_run_id"),
    "calculation_runs": ("id",),
    "reconciliation_runs": ("id",),
    "price_snapshots": ("id", "provider_id", "license_version_id", "series_id"),
    "fx_snapshots": ("id", "provider_id", "license_version_id", "calendar_id"),
    "corporate_action_snapshots": ("id", "provider_id", "license_version_id"),
    "benchmark_snapshots": ("id", "provider_id", "license_version_id", "series_id"),
    "market_data_instruments": ("id", "provider_id", "instrument_id", "listing_id"),
    "source_calendars": ("id",),
    "provider_license_versions": ("id", "provider_id"),
    "benchmark_versions": ("id",),
    "target_versions": ("id",),
    "historical_classification_evidence": ("id", "instrument_id", "license_version_id"),
    "historical_evidence_sets": ("id",),
    "activity_revision_evidence": (
        "id",
        "source_record_id",
        "new_source_record_id",
        "superseded_source_record_id",
    ),
    "market_source_series": (
        "id",
        "provider_id",
        "license_version_id",
        "calendar_id",
        "mapping_id",
        "instrument_id",
        "listing_id",
    ),
}
_HISTORY_TABLES = frozenset(_FIELDS) - {"market_source_series"}
_TABLES = {
    "portfolio_snapshot": frozenset(("portfolio_snapshots", "calculation_runs")),
    "historical_input": _HISTORY_TABLES,
    "price_total_return": frozenset(
        ("price_snapshots", "market_source_series", "source_calendars", "market_data_instruments")
    ),
    "benchmark_total_return": frozenset(
        (
            "benchmark_snapshots",
            "market_source_series",
            "source_calendars",
            "market_data_instruments",
        )
    ),
}
_MAX_IDS = PROJECTION_MAX_BYTES // 36


@dataclass(frozen=True, slots=True)
class ProjectionSourcePresentationFacts:
    evidence: ProjectionRetainedEvidence
    source_cutoff_at: datetime | None
    first_observed_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProjectionSourcePresentation:
    evidence: tuple[ProjectionRetainedEvidence, ...]
    source_cutoff_at: datetime | None
    sources: tuple[ProjectionSourcePresentationFacts, ...]


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise unavailable()
    return value


def _rows(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)) or len(value) > _MAX_IDS:
        raise unavailable()
    return tuple(_object(row) for row in value)


def _uuid(value: object) -> UUID:
    if type(value) is UUID:
        return value
    if type(value) is not str:
        raise unavailable()
    result = UUID(value)
    if str(result) != value:
        raise unavailable()
    return result


def _time(value: object) -> datetime:
    if type(value) is datetime:
        return require_utc(value)
    if type(value) is not str:
        raise unavailable()
    result = require_utc(datetime.fromisoformat(value))
    if utc_string(result) != value:
        raise unavailable()
    return result


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in pairs:
        if key in result:
            raise unavailable()
        result[key] = item
    return result


class _Identities:
    def __init__(self) -> None:
        self.values: set[UUID] = set()

    def add(self, value: object) -> None:
        self.values.add(_uuid(value))
        if len(self.values) > _MAX_IDS:
            raise unavailable()

    def columns(self, row: dict[str, Any], names: tuple[str, ...]) -> None:
        for name in names:
            value = row[name] if name == "id" else row.get(name)
            if value is not None:
                self.add(value)

    def sequence(self, value: object) -> None:
        if not isinstance(value, (list, tuple)) or len(value) > _MAX_IDS:
            raise unavailable()
        for item in value:
            self.add(item)


def _facts(source: ProjectionCapturedSource) -> ProjectionSourcePresentationFacts:
    header = source.header
    if header.kind not in _ROOTS or not 0 < len(source.canonical_proof) <= PROJECTION_MAX_BYTES:
        raise unavailable()
    if header.role != (
        "initial_snapshot" if header.kind == "portfolio_snapshot" else "calibration"
    ):
        raise unavailable()
    proof = _object(json.loads(source.canonical_proof, object_pairs_hook=_pairs))
    if (
        set(proof) != _BASE | _PARTS[header.kind]
        or proof["schema"] != "projection_source_proof_v1"
        or proof["source_kind"] != header.kind
        or _uuid(proof["subject_id"]) != header.subject_id
        or proof["content_digest"] != header.content_digest
        or _time(proof["original_created_at"]) != header.original_created_at
        or canonical_json(proof["metadata"]) != canonical_json(header.metadata)
        or canonical_json(proof).encode() != source.canonical_proof
    ):
        raise unavailable()
    metadata = _rows(proof["metadata"])
    if (
        not metadata
        or metadata[0].get("table") != _ROOTS[header.kind]
        or _uuid(metadata[0].get("id")) != header.subject_id
    ):
        raise unavailable()
    ids = _Identities()
    for row in metadata:
        table = row.get("table")
        if table not in _TABLES[header.kind]:
            raise unavailable()
        ids.columns(row, _FIELDS[table])
    licenses = _rows(proof["licenses"])
    if tuple(sorted(_uuid(row["id"]) for row in licenses)) != header.license_version_ids:
        raise unavailable()
    for row in licenses:
        ids.columns(row, ("id", "provider_id"))
    cutoff: datetime | None = None
    observed: datetime | None = None
    if header.kind == "portfolio_snapshot":
        snapshot, calculation = _object(proof["snapshot"]), _object(proof["calculation"])
        if _uuid(snapshot["id"]) != header.subject_id or _uuid(
            snapshot["calculation_run_id"]
        ) != _uuid(calculation["id"]):
            raise unavailable()
        cutoff = _time(snapshot["source_cutoff_at"])
        if cutoff != _time(metadata[0]["source_cutoff_at"]) or cutoff != _time(
            calculation["source_cutoff_at"]
        ):
            raise unavailable()
        ids.sequence(calculation["input_ids"])
        for name in ("positions", "cash"):
            for row in _rows(proof[name]):
                ids.columns(row, ("id", "snapshot_id", "listing_id"))
                ids.sequence(_object(row["provenance"])["source_record_ids"])
    elif header.kind == "historical_input":
        payload = proof["canonical_input"]
        if type(payload) is not str:
            raise unavailable()
        value = historical_input_from_json(payload.encode())
        if historical_input_digest(value) != header.content_digest:
            raise unavailable()
        cutoff = _time(metadata[0]["source_cutoff_at"])
        if cutoff != value.selection.window.source_cutoff_at:
            raise unavailable()
        # HistoricalSourceReference is the canonical closed evidence identity contract.
        for reference in value.sources:
            ids.add(reference.id)
            ids.sequence(reference.parent_ids)
    else:
        snapshot = _object(proof["snapshot"])
        if _uuid(snapshot["id"]) != header.subject_id:
            raise unavailable()
        provenance = _object(snapshot["provenance"])
        observed = _time(provenance["first_observed_at"])
        if observed != _time(metadata[0]["first_observed_at"]):
            raise unavailable()
        ids.columns(provenance, ("provider_id", "license_version_id"))
        # SQL calendar identity is explicit in metadata; domain calendar.id is a source key.
        ids.columns(_object(proof["series"]), _FIELDS["market_source_series"])
        ids.columns(_object(proof["calendar"]), ("id",))
        for name, columns in (
            ("original_observations", ("id", "snapshot_id")),
            ("original_gaps", ("id", "price_snapshot_id", "benchmark_snapshot_id")),
            ("mapping", _FIELDS["market_data_instruments"]),
            ("mapping_candidates", ("id", "mapping_id", "instrument_id", "listing_id")),
            ("calendar_sessions", ("id", "calendar_id")),
        ):
            for row in _rows(proof[name]):
                ids.columns(row, columns)
    if (
        header.kind in ("portfolio_snapshot", "historical_input")
        and proof["physical_expires_at"] is not None
    ):
        raise unavailable()
    evidence = ProjectionRetainedEvidence(
        role="observed_snapshot" if header.role == "initial_snapshot" else "calibration",
        subject_id=header.subject_id,
        content_digest=header.content_digest,
        quality=source.quality,
        source_reference_ids=tuple(sorted(ids.values)),
    )
    return ProjectionSourcePresentationFacts(evidence, cutoff, observed)


def projection_source_presentation(
    source: ProjectionCapturedSource,
) -> ProjectionSourcePresentationFacts:
    """Project one already authorized/verified original source, with no implicit cutoff."""
    try:
        return _facts(source)
    except (DomainError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise unavailable() from None


def projection_sources_presentation(bundle: ProjectionSourceBundle) -> ProjectionSourcePresentation:
    """Keep an overall cutoff only when every source declares that exact concept."""
    if (
        len(bundle.sources) > 257
        or sum(len(source.canonical_proof) for source in bundle.sources) > PROJECTION_MAX_BYTES
    ):
        raise unavailable()
    facts = tuple(projection_source_presentation(source) for source in bundle.sources)
    cutoffs = tuple(item.source_cutoff_at for item in facts if item.source_cutoff_at is not None)
    cutoff = max(cutoffs) if cutoffs and len(cutoffs) == len(facts) else None
    return ProjectionSourcePresentation(tuple(item.evidence for item in facts), cutoff, facts)
