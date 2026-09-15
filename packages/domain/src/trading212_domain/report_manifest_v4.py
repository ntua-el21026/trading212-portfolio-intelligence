"""Profile-four-only codecs; old decode entrypoints retain their original types."""

from __future__ import annotations

from dataclasses import fields
from hashlib import sha256
from typing import cast

from . import report_manifest as shared
from . import report_v4 as v
from . import reports as r
from .errors import fail_validation
from .report_schema import table_schema


def encode_report_selection_v4(value: v.ReportSelectionV4) -> bytes:
    return shared._encode(value, 64 * 1024)


def decode_report_selection_v4(payload: bytes) -> v.ReportSelectionV4:
    return shared._read(payload, v.ReportSelectionV4, 64 * 1024)


def encode_report_context_v4(value: v.ReportContextV4) -> bytes:
    return shared._encode(value, r.MAX_REPORT_MANIFEST_BYTES)


def decode_report_context_v4(payload: bytes) -> v.ReportContextV4:
    return shared._read(payload, v.ReportContextV4, r.MAX_REPORT_MANIFEST_BYTES)


def encode_report_proof_v4(value: v.ReportProofV4) -> bytes:
    return shared._encode(value, r.MAX_REPORT_MANIFEST_BYTES)


def decode_report_proof_v4(payload: bytes) -> v.ReportProofV4:
    return shared._read(payload, v.ReportProofV4, r.MAX_REPORT_MANIFEST_BYTES)


def encode_report_header_v4(value: v.ReportDocumentHeaderV4) -> bytes:
    return shared._encode(value, r.MAX_REPORT_MANIFEST_BYTES)


def decode_report_header_v4(payload: bytes) -> v.ReportDocumentHeaderV4:
    return shared._read(payload, v.ReportDocumentHeaderV4, r.MAX_REPORT_MANIFEST_BYTES)


def encode_report_capture_v4(value: v.ReportCaptureSummaryV4) -> bytes:
    return shared._encode(value, r.MAX_REPORT_DOCUMENT_BYTES)


def decode_report_capture_v4(payload: bytes) -> v.ReportCaptureSummaryV4:
    return shared._read(payload, v.ReportCaptureSummaryV4, r.MAX_REPORT_DOCUMENT_BYTES)


def report_document_digest_v4(value: v.ReportDocumentHeaderV4) -> str:
    raw = cast(dict[str, shared.JsonValue], shared._primitive(value))
    del raw["document_digest"]
    return sha256(shared._json(raw, r.MAX_REPORT_MANIFEST_BYTES)).hexdigest()


def validate_report_manifest_v4(value: v.ReportManifestV4) -> None:
    proof = v.ReportProofV4(
        **{field.name: getattr(value, field.name) for field in fields(v.ReportProofV4)}
    )
    shared._validate_proof(proof)
    notes = {note.key for note in proof.notes}
    if any(
        table.reason_key is not None and table.reason_key not in notes
        for table in value.document.tables
    ):
        fail_validation("Unresolved table reason.", field="reason_key")
    if value.document.context_digest != sha256(
        encode_report_proof_v4(proof)
    ).hexdigest() or value.document.document_digest != report_document_digest_v4(value.document):
        fail_validation("Profile-four document proof differs.", field="document_digest")
    for table in value.document.tables:
        if (
            table.schema_digest
            != sha256(shared.encode_report_schema(table_schema(table.table))).hexdigest()
        ):
            fail_validation("Projection table schema differs.", field="schema_digest")
    if {version.format for version in value.renderer_profile.renderer_versions} != set(
        value.document.selection.formats
    ) or len(
        {(binding.family, binding.role, binding.subject_id) for binding in value.bindings}
    ) != len(value.bindings):
        fail_validation("Renderer or immutable binding identities differ.", field="bindings")


def encode_report_manifest_v4(value: v.ReportManifestV4) -> bytes:
    validate_report_manifest_v4(value)
    return shared._encode(value, r.MAX_REPORT_MANIFEST_BYTES)


def decode_report_manifest_v4(payload: bytes) -> v.ReportManifestV4:
    value = shared._read(payload, v.ReportManifestV4, r.MAX_REPORT_MANIFEST_BYTES)
    validate_report_manifest_v4(value)
    return value


def build_report_manifest_v4(capture: v.ReportCaptureSummaryV4) -> v.ReportManifestV4:
    if capture.proof_digest != sha256(encode_report_proof_v4(capture.proof)).hexdigest():
        fail_validation("Projection capture proof differs.", field="proof_digest")
    result = v.ReportManifestV4(
        document=capture.header,
        renderer_profile=capture.renderer_profile,
        bindings=capture.immutable_bindings,
        **{field.name: getattr(capture.proof, field.name) for field in fields(v.ReportProofV4)},
    )
    encode_report_manifest_v4(result)
    return result
