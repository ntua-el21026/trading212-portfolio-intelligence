"""Actual canonical capture plus transport-only status fixtures for profile four."""

from dataclasses import replace
from hashlib import sha256
from typing import Any, Final

from trading212_domain.report_manifest import build_report_chunk
from trading212_domain.report_manifest_v4 import (
    build_report_manifest_v4,
    encode_report_proof_v4,
    report_document_digest_v4,
)
from trading212_domain.report_profile import renderer_profile
from trading212_domain.report_v4 import (
    ReportCaptureSummaryV4,
    ReportDocumentHeaderV4,
    ReportManifestV4,
    ReportProofV4,
)
from trading212_domain.serialization import to_primitive
from trading212_persistence.report_capture_projection import project_projection

from tests.unit.api.report_factories import BODY, JOB, job
from tests.unit.persistence.projection_report_factories import case

PROFILE: Final = "report_sections_v4"


def body_v4() -> dict[str, Any]:
    return {
        **BODY,
        "profile_version": PROFILE,
        "premium_run": {"family": "projection", "run_id": JOB},
        "sections": [*BODY["sections"], "projection"],
    }


def status_v4() -> dict[str, Any]:
    value: dict[str, Any] = to_primitive(job())
    value["context"].update(profile_version=PROFILE, schema_version="4.0.0")
    return value


def manifest_v4() -> ReportManifestV4:
    fixture = case(goal=False, sensitive=False)
    binding = project_projection(fixture.builder, fixture.captured, fixture.saved, fixture.metadata)
    proof = ReportProofV4(
        contexts=tuple(fixture.builder.contexts.values()),
        notes=tuple(fixture.builder.notes.values()),
        note_memberships=tuple(fixture.builder.note_memberships),
    )
    proof_digest = sha256(encode_report_proof_v4(proof)).hexdigest()
    header = ReportDocumentHeaderV4(
        selection=fixture.builder.selection,
        owner_id=fixture.builder.owner_id,
        valuation_at=fixture.builder.valuation_at,
        context_digest=proof_digest,
        tables=fixture.builder.descriptors(),
        document_digest="0" * 64,
        premium_binding=binding,
    )
    header = replace(header, document_digest=report_document_digest_v4(header))
    chunks = tuple(
        build_report_chunk(table, index, rows)
        for index, (table, rows) in enumerate(fixture.builder.rows.items())
        if rows
    )
    capture = ReportCaptureSummaryV4(
        header=header,
        canonical_byte_length=sum(len(chunk.canonical_bytes) for chunk in chunks),
        chunk_count=len(chunks),
        immutable_bindings=tuple(fixture.builder.bindings),
        proof=proof,
        proof_digest=proof_digest,
        renderer_profile=renderer_profile(fixture.builder.selection.formats),
        copy_expires_at=fixture.metadata.expires_at,
    )
    return build_report_manifest_v4(capture)
