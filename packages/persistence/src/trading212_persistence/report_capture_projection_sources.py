"""Lossless source trees from the four closed, already authorized projection proofs."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from trading212_domain import reports as r
from trading212_domain.errors import fail_validation
from trading212_domain.historical_serialization import (
    historical_canonical_bytes,
    historical_input_from_json,
)
from trading212_domain.report_projection_schema import PROJECTION_SOURCE_PARTS

from .projection_source_presentation import projection_source_presentation
from .projection_source_store import ProjectionCapturedSource
from .report_capture_common import ReportValue
from .report_capture_projection_cells import ProjectionReportWriter

_BASE = frozenset(
    {
        "schema",
        "source_kind",
        "subject_id",
        "content_digest",
        "original_created_at",
        "physical_expires_at",
    }
)


@dataclass(frozen=True, slots=True)
class ProjectionReportSourceParts:
    source: ProjectionCapturedSource
    parts: tuple[tuple[str, object], ...]
    historical_document_digest: str | None


def _number(_: str) -> None:
    fail_validation("Source proof cannot contain a binary financial number.", field="source")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    if len({key for key, _ in pairs}) != len(pairs):
        fail_validation("Source proof repeats a field.", field="source")
    return dict(pairs)


def projection_report_source_parts(source: ProjectionCapturedSource) -> ProjectionReportSourceParts:
    # The established helper checks the known kind, exact part inventory, canonical
    # outer bytes, original metadata identities, source digest and license membership.
    projection_source_presentation(source)
    raw = json.loads(
        source.canonical_proof,
        object_pairs_hook=_pairs,
        parse_float=_number,
        parse_constant=_number,
    )
    parts = {key: value for key, value in raw.items() if key not in _BASE}
    parts["header"] = {key: raw[key] for key in sorted(_BASE)}
    original_digest = None
    if source.header.kind == "historical_input":
        payload = raw["canonical_input"].encode("utf-8")
        value = historical_input_from_json(payload)
        # Historical storage emits this known canonical codec. Preserve its exact
        # byte digest and reconstruct its serialized field from the typed document.
        if historical_canonical_bytes(value) != payload:
            fail_validation("Historical source spelling is not canonical.", field="source")
        original_digest = sha256(payload).hexdigest()
        parts["canonical_input"] = json.loads(
            payload, object_pairs_hook=_pairs, parse_float=_number, parse_constant=_number
        )
    if set(parts) != PROJECTION_SOURCE_PARTS[source.header.kind]:
        fail_validation("Unknown source proof part.", field="source")
    return ProjectionReportSourceParts(source, tuple(sorted(parts.items())), original_digest)


def source_tree(part: object) -> Iterator[tuple[str, dict[str, ReportValue]]]:
    """Fixed primitive encoding, called only for a validated closed source part.

    Containers have explicit membership/order, including empty containers and nulls.
    String leaves retain source spelling; financial interpretation remains in the
    known canonical source schema and the report's separately typed money tables.
    """
    counter = 0

    def visit(value: object, *, depth: int = 0) -> Iterator[tuple[str, dict[str, ReportValue]]]:
        nonlocal counter
        r.report_limit(depth <= 64 and counter < r.MAX_REPORT_DATASET_ROWS, "source_nodes")
        node = counter
        counter += 1
        kind = (
            "null"
            if value is None
            else {
                dict: "object",
                list: "array",
                str: "string",
                int: "integer",
                bool: "boolean",
            }.get(type(value))
        )
        if kind is None:
            fail_validation("Unsupported original source scalar.", field="source")
        if isinstance(value, str):
            r.report_limit(len(value) <= r.MAX_REPORT_TEXT_CHARS, "source_text")
        children = len(value) if isinstance(value, list | dict) else 0
        yield "node", {"node": node, "kind": kind, "child_count": children}
        if isinstance(value, dict | list):
            entries = sorted(value.items()) if isinstance(value, dict) else enumerate(value)
            for ordinal, (key, child) in enumerate(entries):
                member = key if isinstance(value, dict) else None
                if member is not None and (
                    type(member) is not str or len(member) > r.MAX_REPORT_TEXT_CHARS
                ):
                    fail_validation("Invalid original source field.", field="source")
                yield (
                    "member",
                    {
                        "parent_node": node,
                        "ordinal": ordinal,
                        "member_key": member,
                        "child_node": counter,
                    },
                )
                yield from visit(child, depth=depth + 1)
        else:
            yield (
                "scalar",
                {
                    "node": node,
                    "kind": kind,
                    "text": value if type(value) is str else None,
                    "integer": value if type(value) is int else None,
                    "boolean": value if type(value) is bool else None,
                },
            )

    yield from visit(part)


def preflight_projection_report_sources(
    sources: tuple[ProjectionCapturedSource, ...],
) -> tuple[ProjectionReportSourceParts, ...]:
    r.report_limit(len(sources) <= 257, "sources")
    r.report_limit(
        sum(len(source.canonical_proof) for source in sources) <= r.MAX_REPORT_DOCUMENT_BYTES,
        "source_bytes",
    )
    parts = tuple(projection_report_source_parts(source) for source in sources)
    counts = {"node": 0, "member": 0, "scalar": 0}
    for source in parts:
        for _, value in source.parts:
            for kind, _ in source_tree(value):
                counts[kind] += 1
                r.report_limit(counts[kind] <= r.MAX_REPORT_DATASET_ROWS, "source_rows")
    return parts


def capture_projection_source_tables(
    writer: ProjectionReportWriter, sources: tuple[ProjectionReportSourceParts, ...]
) -> None:
    def headers() -> Iterator[r.ReportRow]:
        for ordinal, item in enumerate(sources):
            source, facts = item.source, projection_source_presentation(item.source)
            header = source.header
            root = dict(item.parts)["header"]
            physical = root["physical_expires_at"] if isinstance(root, dict) else None
            from datetime import datetime

            yield writer.row(
                r.ReportTableKey.PROJECTION_SOURCE_HEADERS_V1,
                ordinal,
                {
                    "ordinal": ordinal,
                    "kind": header.kind,
                    "role": header.role,
                    "subject_id": header.subject_id,
                    "content_digest": header.content_digest,
                    "proof_digest": source.proof_digest,
                    "proof_bytes": len(source.canonical_proof),
                    "original_created_at": header.original_created_at,
                    "physical_expires_at": None
                    if physical is None
                    else datetime.fromisoformat(physical),
                    "authorized_copy_expires_at": header.expires_at,
                    "source_cutoff_at": facts.source_cutoff_at,
                    "first_observed_at": facts.first_observed_at,
                    "quality": source.quality,
                    "historical_document_digest": item.historical_document_digest,
                },
                reasons={"source_cutoff_at": "original_source_cutoff_not_supplied"}
                if facts.source_cutoff_at is None
                else None,
            )

    writer.table(r.ReportTableKey.PROJECTION_SOURCE_HEADERS_V1, headers())
    for kind, table in (
        ("node", r.ReportTableKey.PROJECTION_SOURCE_NODES_V1),
        ("member", r.ReportTableKey.PROJECTION_SOURCE_MEMBERS_V1),
        ("scalar", r.ReportTableKey.PROJECTION_SOURCE_SCALARS_V1),
    ):

        def rows(kind: str = kind, table: r.ReportTableKey = table) -> Iterator[r.ReportRow]:
            for ordinal, source in enumerate(sources):
                for part, value in source.parts:
                    for index, (actual, fields) in enumerate(source_tree(value)):
                        if actual == kind:
                            yield writer.row(
                                table,
                                f"{ordinal}.{part}.{index}",
                                {"source_ordinal": ordinal, "part": part, **fields},
                            )

        writer.table(table, rows())
