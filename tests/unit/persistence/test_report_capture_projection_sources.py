"""Reconstruct original licensed proof without a serialized document cell."""

import json
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from typing import Any

import pytest
from trading212_domain import reports as r
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.historical_serialization import historical_input_digest
from trading212_domain.serialization import canonical_json
from trading212_persistence.projection_definition_store import ProjectionStorageError
from trading212_persistence.projection_source_store import (
    ProjectionCapturedSource,
    ProjectionSourceHeader,
)
from trading212_persistence.report_capture_projection_sources import (
    preflight_projection_report_sources,
    projection_report_source_parts,
    source_tree,
)

from tests.unit.analytics.historical_factories import fixture
from tests.unit.persistence.test_projection_source_presentation import (
    AT,
    _source,
    provider,
    snapshot,
    uid,
)

pytestmark = pytest.mark.unit


def history() -> ProjectionCapturedSource:
    original = fixture()
    header = ProjectionSourceHeader(
        kind="historical_input",
        role="calibration",
        subject_id=uid(800),
        content_digest=historical_input_digest(original),
        original_created_at=AT,
        expires_at=AT + timedelta(days=20),
        metadata=(
            {
                "table": "historical_input_snapshots",
                "id": uid(800),
                "source_cutoff_at": original.selection.window.source_cutoff_at,
            },
        ),
        license_version_ids=(),
    )
    return _source(header, canonical_input=canonical_json(original))


def restore(part: object) -> Any:
    records = list(source_tree(part))
    nodes: dict[Any, dict[str, Any]] = {row["node"]: row for kind, row in records if kind == "node"}
    scalars: dict[Any, dict[str, Any]] = {
        row["node"]: row for kind, row in records if kind == "scalar"
    }
    edges: dict[Any, list[dict[str, Any]]] = {}
    for kind, row in records:
        if kind == "member":
            edges.setdefault(row["parent_node"], []).append(row)

    def node(identifier: Any) -> Any:
        kind = nodes[identifier]["kind"]
        children = sorted(edges.get(identifier, []), key=lambda row: row["ordinal"])
        assert len(children) == nodes[identifier]["child_count"]
        if kind == "object":
            return {row["member_key"]: node(row["child_node"]) for row in children}
        if kind == "array":
            return [node(row["child_node"]) for row in children]
        scalar = scalars[identifier]
        return (
            scalar[{"string": "text", "integer": "integer", "boolean": "boolean"}[kind]]
            if kind != "null"
            else None
        )

    return node(0)


@pytest.mark.parametrize("source_factory", [snapshot, provider, history])
def test_all_original_parts_reconstruct_original_bytes_and_digest(source_factory: Any) -> None:
    source = source_factory()
    split = projection_report_source_parts(source)
    parts = {key: restore(value) for key, value in split.parts}
    if source.header.kind == "historical_input":
        document = canonical_json(parts["canonical_input"])
        assert len(document) > r.MAX_REPORT_TEXT_CHARS
        assert sha256(document.encode()).hexdigest() == split.historical_document_digest
        # This formerly large serialized string is now a structured document part.
        assert isinstance(dict(split.parts)["canonical_input"], dict)
        parts["canonical_input"] = document
    header = parts.pop("header")
    rebuilt = canonical_json({**header, **parts}).encode()
    assert rebuilt == source.canonical_proof
    assert sha256(rebuilt).hexdigest() == source.proof_digest
    assert preflight_projection_report_sources((source,)) == (split,)


def test_empty_containers_null_and_boolean_false_do_not_collapse() -> None:
    value: dict[str, object] = {
        "empty_array": [],
        "empty_object": {},
        "missing": None,
        "false": False,
        "zero": 0,
        "empty_string": "",
    }
    assert restore(value) == value
    assert len([row for kind, row in source_tree(value) if kind == "scalar"]) == 4


@pytest.mark.parametrize("value", [1.5, {"money": 0.1}, {"field": object()}])
def test_unknown_or_binary_float_source_leaves_fail_closed(value: object) -> None:
    with pytest.raises(DomainError):
        list(source_tree(value))


def test_unknown_source_root_and_aggregate_row_bound_fail_without_partial_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = provider()
    raw = json.loads(source.canonical_proof)
    raw["arbitrary_dataset"] = []
    with pytest.raises((DomainError, ProjectionStorageError)):
        projection_report_source_parts(
            replace(source, canonical_proof=canonical_json(raw).encode())
        )
    monkeypatch.setattr(r, "MAX_REPORT_DATASET_ROWS", 10)
    with pytest.raises(DomainError) as error:
        preflight_projection_report_sources((source,))
    assert error.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
