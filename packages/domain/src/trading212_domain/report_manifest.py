"""Explicit closed report codecs and chunk-independent semantic byte hashes."""

from __future__ import annotations

import hashlib
import json
import types
from collections.abc import Callable, Collection, Iterable
from dataclasses import fields
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import cast, get_args, get_origin, overload
from uuid import UUID

from . import report_v3 as v3
from . import reports as r
from .errors import DomainError, fail_validation
from .values import CurrencyCode

_RECORDS = (
    r.ReportSelection,
    r.ExportSelection,
    r.ReportCell,
    r.ReportColumn,
    r.ReportTableSchema,
    r.ReportRow,
    r.ReportTableDescriptor,
    r.ReportDocumentHeader,
    r.ReportContext,
    r.ReportSourceReference,
    r.ReportSourceMembership,
    r.ReportNoteMembership,
    r.ReportLicenseReference,
    r.ReportNote,
    r.ReportCoverageFact,
    r.ReportBoundFact,
    r.ReportBinding,
    r.ReportReconciliationBinding,
    r.ReportProofRelation,
    r.ReportProof,
    r.ReportCaptureSummary,
    r.ReportRendererVersion,
    r.ReportFontReference,
    r.ReportRendererProfile,
    r.ReportManifest,
    v3.ReportRiskRunSelection,
    v3.ReportScenarioRunSelection,
    v3.ReportSelectionV3,
    v3.ReportXrayRunBinding,
    v3.ReportHistoricalInputBinding,
    v3.ReportRiskRunBinding,
    v3.ReportScenarioRunBinding,
    v3.ReportDocumentHeaderV3,
    v3.ReportCaptureSummaryV3,
    v3.ReportManifestV3,
)
type JsonValue = bool | int | str | list[JsonValue] | dict[str, JsonValue] | None
_OPTIONAL_CELL_FIELDS = frozenset(
    {
        "decimal_role",
        "currency",
        "context_key",
        "reason_key",
        "bound_key",
        "quality",
        "origin",
        "coverage_key",
        "confidence",
        "method_key",
        "method_version",
        "provenance_set_key",
        "note_set_key",
    }
)


_OPTIONAL_V3_FIELDS: dict[type[r.ReportRecord], frozenset[str]] = {
    v3.ReportSelectionV3: frozenset({"xray_run_id"}),
    v3.ReportRiskRunBinding: frozenset({"xray", "benchmark_version_id"}),
    v3.ReportScenarioRunBinding: frozenset({"historical"}),
}


def _field_names(value: r.ReportRecord) -> tuple[str, ...]:
    return tuple(
        field.name
        for field in fields(value)
        if not (
            getattr(value, field.name) is None
            and (
                (type(value) is r.ReportCell and field.name in _OPTIONAL_CELL_FIELDS)
                or (
                    type(value) in (r.ReportSelection, r.ExportSelection)
                    and field.name == "xray_run_id"
                )
                or (type(value) is r.ReportSelection and field.name == "risk_run_id")
                or field.name in _OPTIONAL_V3_FIELDS.get(type(value), frozenset())
            )
        )
    )


def _instant(value: datetime) -> str:
    value = value.astimezone(UTC)
    text = value.isoformat(timespec="microseconds").removesuffix("+00:00")
    return text.rstrip("0").rstrip(".") + "Z"


def _decimal(value: Decimal) -> str:
    if not value.is_finite():
        fail_validation("Report decimal must be finite.", field="decimal")
    if value.is_zero():
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def canonical_report_cell_value(cell: r.ReportCell) -> str:
    """Present the supplied exact scalar; never calculate, round or escape CSV here."""
    value = cell.value
    if value is None:
        return ""
    if type(value) is Decimal:
        return _decimal(value)
    if type(value) is datetime:
        return _instant(value)
    if type(value) is date:
        return value.isoformat()
    if type(value) is bool:
        return "true" if value else "false"
    return str(value)


def _primitive(value: object) -> JsonValue:
    if value is None or type(value) in (str, bool, int):
        return cast("str | bool | int | None", value)
    if isinstance(value, StrEnum):
        return value.value
    if type(value) is CurrencyCode:
        return value.value
    if type(value) is UUID:
        return str(value)
    if type(value) is Decimal:
        return _decimal(value)
    if type(value) is datetime:
        return _instant(value)
    if type(value) is date:
        return value.isoformat()
    if type(value) is tuple:
        return [_primitive(item) for item in value]
    if type(value) in _RECORDS:
        return {
            name: _primitive(getattr(value, name))
            for name in _field_names(cast("r.ReportRecord", value))
        }
    fail_validation("Only closed report records can be encoded.", field="record")


def _json(value: JsonValue, maximum: int) -> bytes:
    # Incremental encoding enforces the cap before joining a complete oversized payload.
    output = bytearray()
    for part in json.JSONEncoder(
        ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).iterencode(value):
        try:
            encoded = part.encode("utf-8")
        except UnicodeEncodeError:
            fail_validation("Report text must be valid Unicode.", field="text")
        r.report_limit(len(output) + len(encoded) <= maximum, "encoded_bytes")
        output.extend(encoded)
    return bytes(output)


def _measure(value: object, maximum: int) -> int:
    """Check aggregate bytes before constructing the serialized object graph."""
    if type(value) is tuple:
        size = 2
        for index, item in enumerate(value):
            size += (1 if index else 0) + _measure(item, maximum - size)
            r.report_limit(size <= maximum, "encoded_bytes")
        return size
    if type(value) in _RECORDS:
        size = 2
        for index, name in enumerate(_field_names(cast("r.ReportRecord", value))):
            size += (1 if index else 0) + len(json.dumps(name)) + 1
            r.report_limit(size <= maximum, "encoded_bytes")
            size += _measure(getattr(value, name), maximum - size)
            r.report_limit(size <= maximum, "encoded_bytes")
        return size
    return len(_json(_primitive(value), maximum))


def _encode(value: r.ReportRecord, maximum: int) -> bytes:
    _measure(value, maximum)
    return _json(_primitive(value), maximum)


def _reject_number(value: str) -> None:
    fail_validation("Report JSON cannot contain floating point numbers.", field="json")


def _object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            fail_validation("Report JSON contains duplicate keys.", field="json")
        result[key] = value
    return result


def _load(payload: bytes, maximum: int) -> JsonValue:
    if type(payload) is not bytes:
        fail_validation("Report codec requires bytes.", field="payload")
    r.report_limit(len(payload) <= maximum, "payload")
    try:
        return cast(
            "JsonValue",
            json.loads(
                payload,
                parse_float=_reject_number,
                parse_constant=_reject_number,
                object_pairs_hook=_object,
            ),
        )
    except (ValueError, UnicodeError, RecursionError):
        fail_validation("Report bytes are not valid canonical JSON.", field="payload")


def _decode(value: JsonValue, annotation: object) -> object:
    origin = get_origin(annotation)
    if origin is types.UnionType:
        parts = get_args(annotation)
        if value is None and type(None) in parts:
            return None
        for part in parts:
            if part is type(None):
                continue
            try:
                return _decode(value, part)
            except DomainError:
                continue
        fail_validation("Report union variant is invalid.", field="variant")
    if origin is tuple:
        if type(value) is not list:
            fail_validation("Report tuple must be an array.", field="tuple")
        r.report_limit(len(value) <= r.MAX_REPORT_DATASET_ROWS, "tuple")
        return tuple(_decode(item, get_args(annotation)[0]) for item in value)
    if isinstance(annotation, type) and annotation in _RECORDS:
        names = {item.name for item in fields(annotation)}
        optional = (
            _OPTIONAL_CELL_FIELDS
            if annotation is r.ReportCell
            else frozenset({"xray_run_id", "risk_run_id"})
            if annotation is r.ReportSelection
            else frozenset({"xray_run_id"})
            if annotation is r.ExportSelection
            else _OPTIONAL_V3_FIELDS.get(annotation, frozenset())
        )
        if type(value) is not dict or not names - optional <= set(value) <= names:
            fail_validation("Report record fields differ from its schema.", field="record")
        # Legacy exact fields or the explicit present-pin fields only. A null
        # present pin is noncanonical, never an alias for the legacy encoding.
        if (
            annotation in (r.ReportSelection, r.ExportSelection)
            and "xray_run_id" in value
            and value["xray_run_id"] is None
        ):
            fail_validation("A present company run pin must be a UUID.", field="xray_run_id")
        if (
            annotation is r.ReportSelection
            and "risk_run_id" in value
            and value["risk_run_id"] is None
        ):
            fail_validation("A present risk run pin must be a UUID.", field="risk_run_id")
        if annotation in _OPTIONAL_V3_FIELDS and any(
            name in value and value[name] is None for name in _OPTIONAL_V3_FIELDS[annotation]
        ):
            fail_validation("Optional profile-three pins are omitted when absent.", field="record")
        hints = r._record_hints(annotation)
        result = {
            name: _decode(item, hints[name])
            for name, item in value.items()
            if not (annotation is r.ReportCell and name == "value")
        }
        if annotation is r.ReportCell:
            kind = r.CellKind(cast("str", value["kind"]))
            cell_type = {
                r.CellKind.TEXT: str,
                r.CellKind.IDENTIFIER: str,
                r.CellKind.ENUM: str,
                r.CellKind.DECIMAL: Decimal,
                r.CellKind.INTEGER: int,
                r.CellKind.BOOLEAN: bool,
                r.CellKind.DATE: date,
                r.CellKind.INSTANT: datetime,
            }[kind]
            result["value"] = None if value["value"] is None else _decode(value["value"], cell_type)
        # The closed class whitelist and each declared field were checked above.
        constructor = cast("Callable[..., r.ReportRecord]", annotation)
        return constructor(**result)
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        if type(value) is not str:
            fail_validation("Report enum must be a string.", field="enum")
        try:
            return annotation(value)
        except ValueError:
            fail_validation("Report enum value is unknown.", field="enum")
    if annotation in (str, bool, int):
        if type(value) is not annotation:
            fail_validation("Report scalar has an invalid type.", field="scalar")
        return value
    if annotation in (UUID, Decimal, date, datetime, CurrencyCode):
        if type(value) is not str:
            fail_validation("Report typed scalar must be a string.", field="scalar")
        try:
            if annotation is UUID:
                return UUID(value)
            if annotation is Decimal:
                return Decimal(value)
            if annotation is date:
                return date.fromisoformat(value)
            if annotation is datetime:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            return CurrencyCode(value)
        except (ValueError, ArithmeticError):
            fail_validation("Report typed scalar is invalid.", field="scalar")
    fail_validation("Report codec type is not supported.", field="type")


def _read[T: r.ReportRecord](payload: bytes, kind: type[T], maximum: int) -> T:
    result = cast("T", _decode(_load(payload, maximum), kind))
    if _encode(result, maximum) != payload:
        fail_validation("Report bytes are not canonical.", field="payload")
    return result


def encode_report_row(value: r.ReportRow) -> bytes:
    return _encode(value, r.MAX_REPORT_CHUNK_BYTES)


def decode_report_row(payload: bytes) -> r.ReportRow:
    return _read(payload, r.ReportRow, r.MAX_REPORT_CHUNK_BYTES)


def encode_report_header(value: v3.ReportHeaderContract) -> bytes:
    return _encode(value, r.MAX_REPORT_MANIFEST_BYTES)


def decode_report_header(payload: bytes) -> r.ReportDocumentHeader:
    return _read(payload, r.ReportDocumentHeader, r.MAX_REPORT_MANIFEST_BYTES)


def encode_report_selection(value: v3.ReportSelectionContract) -> bytes:
    return _encode(value, 64 * 1024)


def decode_report_selection(payload: bytes) -> r.ReportSelection:
    return _read(payload, r.ReportSelection, 64 * 1024)


def decode_export_selection(payload: bytes) -> r.ExportSelection:
    return _read(payload, r.ExportSelection, 64 * 1024)


def encode_report_profile(value: r.ReportRendererProfile) -> bytes:
    return _encode(value, 64 * 1024)


def decode_report_profile(payload: bytes) -> r.ReportRendererProfile:
    return _read(payload, r.ReportRendererProfile, 64 * 1024)


def encode_report_proof(value: r.ReportProof) -> bytes:
    return _encode(value, r.MAX_REPORT_MANIFEST_BYTES)


def decode_report_proof(payload: bytes) -> r.ReportProof:
    return _read(payload, r.ReportProof, r.MAX_REPORT_MANIFEST_BYTES)


def encode_report_schema(value: r.ReportTableSchema) -> bytes:
    return _encode(value, r.MAX_REPORT_MANIFEST_BYTES)


def encode_report_context(value: r.ReportContext) -> bytes:
    return _encode(value, r.MAX_REPORT_MANIFEST_BYTES)


def decode_report_context(payload: bytes) -> r.ReportContext:
    result = _read(payload, r.ReportContext, r.MAX_REPORT_MANIFEST_BYTES)
    if result.schema_version not in {r.REPORT_SCHEMA_VERSION, r.PREMIUM_REPORT_SCHEMA_VERSION}:
        fail_validation("An earlier report context is required.", field="schema_version")
    return result


def decode_report_context_v3(payload: bytes) -> r.ReportContext:
    result = _read(payload, r.ReportContext, r.MAX_REPORT_MANIFEST_BYTES)
    if result.schema_version != v3.REPORT_V3_SCHEMA_VERSION:
        fail_validation("A profile-three report context is required.", field="schema_version")
    return result


def encode_report_capture(value: v3.ReportCaptureContract) -> bytes:
    return _encode(value, r.MAX_REPORT_DOCUMENT_BYTES)


def decode_report_capture(payload: bytes) -> r.ReportCaptureSummary:
    return _read(payload, r.ReportCaptureSummary, r.MAX_REPORT_DOCUMENT_BYTES)


def _chunk_payload(table: r.ReportTableKey, ordinal: int, rows: tuple[r.ReportRow, ...]) -> bytes:
    _measure(rows, r.MAX_REPORT_CHUNK_BYTES)
    return _json(
        {"table": table.value, "ordinal": ordinal, "rows": _primitive(rows)},
        r.MAX_REPORT_CHUNK_BYTES,
    )


def build_report_chunk(
    table: r.ReportTableKey, ordinal: int, rows: tuple[r.ReportRow, ...]
) -> r.ReportChunk:
    from .report_schema import validate_report_row

    for row in rows:
        validate_report_row(table, row)
    payload = _chunk_payload(table, ordinal, rows)
    return r.ReportChunk(
        table=table,
        ordinal=ordinal,
        rows=rows,
        canonical_bytes=payload,
        digest=hashlib.sha256(payload).hexdigest(),
    )


def encode_report_chunk(value: r.ReportChunk) -> bytes:
    payload = _chunk_payload(value.table, value.ordinal, value.rows)
    if payload != value.canonical_bytes or hashlib.sha256(payload).hexdigest() != value.digest:
        fail_validation("Report chunk binding differs.", field="chunk")
    return payload


def decode_report_chunk(payload: bytes) -> r.ReportChunk:
    raw = _load(payload, r.MAX_REPORT_CHUNK_BYTES)
    if type(raw) is not dict or set(raw) != {"table", "ordinal", "rows"}:
        fail_validation("Report chunk shape is invalid.", field="chunk")
    result = build_report_chunk(
        cast("r.ReportTableKey", _decode(raw["table"], r.ReportTableKey)),
        cast("int", _decode(raw["ordinal"], int)),
        cast("tuple[r.ReportRow, ...]", _decode(raw["rows"], tuple[r.ReportRow, ...])),
    )
    if result.canonical_bytes != payload:
        fail_validation("Report chunk is not canonical.", field="chunk")
    return result


def _proof_of(value: v3.ReportManifestContract) -> r.ReportProof:
    return r.ReportProof(**{item.name: getattr(value, item.name) for item in fields(r.ReportProof)})


def validate_report_references(
    proof: r.ReportProof,
    *,
    context_keys: Collection[str] = (),
    reason_keys: Collection[str] = (),
    bound_keys: Collection[str] = (),
    provenance_set_keys: Collection[str] = (),
    note_set_keys: Collection[str] = (),
    coverage_keys: Collection[str] = (),
) -> None:
    """Resolve both inline cells and bounded references collected while streaming rows.

    A context explicitly declares its sets even when they have no members. Metric
    coverage references may instead name an actual measure: historical measures
    retain their expected/available/complete facts under that measure's base key.
    Shared cross-family provenance remains valid; it need not belong to the row's
    presentation family.
    """
    supplied = {
        "context_key": context_keys,
        "reason_key": reason_keys,
        "bound_key": bound_keys,
        "provenance_set_key": provenance_set_keys,
        "note_set_key": note_set_keys,
        "coverage_key": coverage_keys,
    }
    references: dict[str, set[str]] = {}
    for name, keys in supplied.items():
        maximum = 256 if name == "context_key" else r.MAX_REPORT_DATASET_ROWS
        r.report_limit(len(keys) <= maximum, name)
        references[name] = set(keys)

    def add(name: str, key: str | None) -> None:
        if key is not None:
            references[name].add(key)
            maximum = 256 if name == "context_key" else r.MAX_REPORT_DATASET_ROWS
            r.report_limit(len(references[name]) <= maximum, name)

    def cell_references(cell: r.ReportCell) -> None:
        for name in supplied:
            add(name, getattr(cell, name))

    for relation in proof.proof_relations:
        add("context_key", relation.row.context_key)
        for cell in relation.row.cells:
            cell_references(cell)
    for fact in proof.coverage:
        cell_references(fact.value)
    for note in proof.notes:
        add("provenance_set_key", note.related_provenance_set_key)
    reconciliations = {item.key for item in proof.reconciliation}
    if any(
        item.reconciliation_key is not None and item.reconciliation_key not in reconciliations
        for item in proof.contexts
    ):
        fail_validation("Report context reconciliation is unresolved.", field="reconciliation_key")

    measure_fields: dict[tuple[str, str], set[str]] = {}
    labels = {"expected_count", "available_count", "complete"}
    for fact in proof.coverage:
        base, separator, label = fact.metric_key.rpartition(".")
        if separator and label in labels:
            measure_fields.setdefault((fact.set_key, base), set()).add(label)
    valid = {
        "context_key": {item.key for item in proof.contexts},
        "reason_key": {item.key for item in proof.notes},
        "bound_key": {item.key for item in proof.bounds},
        "provenance_set_key": {item.provenance_set_key for item in proof.contexts}
        | {item.provenance_set_key for item in proof.source_memberships},
        "note_set_key": {item.note_set_key for item in proof.contexts}
        | {item.note_set_key for item in proof.note_memberships},
        "coverage_key": {item.coverage_set_key for item in proof.contexts}
        | {item.set_key for item in proof.coverage}
        | {item.metric_key for item in proof.coverage}
        | {base for (_, base), actual in measure_fields.items() if actual == labels},
    }
    for name, keys in references.items():
        if not keys <= valid[name]:
            fail_validation("Report cell reference is unresolved.", field=name)


def _validate_proof(proof: r.ReportProof) -> None:
    sources = {item.key for item in proof.source_references}
    contexts = {item.key for item in proof.contexts}
    notes = {item.key for item in proof.notes}
    bounds = {item.key for item in proof.bounds}
    for name, records, keys in (
        ("sources", proof.source_references, sources),
        ("contexts", proof.contexts, contexts),
        ("notes", proof.notes, notes),
        ("bounds", proof.bounds, bounds),
        (
            "licenses",
            proof.license_references,
            {item.version_id for item in proof.license_references},
        ),
        ("reconciliation", proof.reconciliation, {item.key for item in proof.reconciliation}),
    ):
        if len(records) != len(keys):
            fail_validation("Report proof identities conflict.", field=name)
    if any(item.source_key not in sources for item in proof.source_memberships) or any(
        item.note_key not in notes for item in proof.note_memberships
    ):
        fail_validation("Report proof membership is unresolved.", field="proof")
    licenses = {item.version_id for item in proof.license_references}
    if any(
        item.license_version_id is not None and item.license_version_id not in licenses
        for item in proof.source_references
    ):
        fail_validation("Report source license reference is unresolved.", field="licenses")
    for relation in proof.proof_relations:
        from .report_schema import validate_report_row

        validate_report_row(relation.table, relation.row)
    validate_report_references(proof)


def encode_report_manifest(value: v3.ReportManifestContract) -> bytes:
    if type(value) not in (r.ReportManifest, v3.ReportManifestV3):
        fail_validation("A typed report manifest is required.", field="manifest")
    _validate_manifest(value)
    return _encode(value, r.MAX_REPORT_MANIFEST_BYTES)


def _validate_manifest(value: v3.ReportManifestContract) -> None:
    from .report_schema import table_schema

    proof = _proof_of(value)
    _validate_proof(proof)
    notes = {item.key for item in proof.notes}
    if any(
        item.reason_key is not None and item.reason_key not in notes
        for item in value.document.tables
    ):
        fail_validation("Report table reason is unresolved.", field="reason_key")
    if value.document.context_digest != hashlib.sha256(encode_report_proof(proof)).hexdigest():
        fail_validation("Report proof differs from its pinned digest.", field="context_digest")
    if value.document.document_digest != report_document_digest(value.document):
        fail_validation("Report header differs from its pinned digest.", field="document_digest")
    for descriptor in value.document.tables:
        expected = hashlib.sha256(encode_report_schema(table_schema(descriptor.table))).hexdigest()
        if descriptor.schema_digest != expected:
            fail_validation("Report table schema differs from its registry.", field="schema_digest")
    selection = value.document.selection
    formats = (
        selection.formats
        if not isinstance(selection, r.ExportSelection)
        else (r.ReportFormat(selection.format.value),)
    )
    if {item.format for item in value.renderer_profile.renderer_versions} != set(formats):
        fail_validation("Report renderer formats differ from selection.", field="renderer_profile")
    identities = {(item.family, item.role, item.subject_id) for item in value.bindings}
    if len(identities) != len(value.bindings):
        fail_validation("Report immutable binding identities conflict.", field="bindings")


def decode_report_manifest(payload: bytes) -> r.ReportManifest:
    result = _read(payload, r.ReportManifest, r.MAX_REPORT_MANIFEST_BYTES)
    _validate_manifest(result)
    return result


def report_manifest_digest(value: v3.ReportManifestContract) -> str:
    return hashlib.sha256(encode_report_manifest(value)).hexdigest()


@overload
def build_report_manifest(
    capture: r.ReportCaptureSummary,
    *,
    proof: r.ReportProof | None = None,
    profile: r.ReportRendererProfile | None = None,
) -> r.ReportManifest: ...


@overload
def build_report_manifest(
    capture: v3.ReportCaptureSummaryV3,
    *,
    proof: r.ReportProof | None = None,
    profile: r.ReportRendererProfile | None = None,
) -> v3.ReportManifestV3: ...


@overload
def build_report_manifest(
    capture: v3.ReportCaptureContract,
    *,
    proof: r.ReportProof | None = None,
    profile: r.ReportRendererProfile | None = None,
) -> v3.ReportManifestContract: ...


def build_report_manifest(
    capture: v3.ReportCaptureContract,
    *,
    proof: r.ReportProof | None = None,
    profile: r.ReportRendererProfile | None = None,
) -> v3.ReportManifestContract:
    proof = capture.proof if proof is None else proof
    profile = capture.renderer_profile if profile is None else profile
    if (
        proof != capture.proof
        or profile != capture.renderer_profile
        or hashlib.sha256(encode_report_proof(proof)).hexdigest() != capture.proof_digest
    ):
        fail_validation("Pinned report proof/profile differs.", field="capture")
    result: v3.ReportManifestContract
    if isinstance(capture, v3.ReportCaptureSummaryV3):
        result = v3.ReportManifestV3(
            document=capture.header,
            renderer_profile=profile,
            bindings=capture.immutable_bindings,
            **{item.name: getattr(proof, item.name) for item in fields(r.ReportProof)},
        )
    else:
        result = r.ReportManifest(
            document=capture.header,
            renderer_profile=profile,
            bindings=capture.immutable_bindings,
            **{item.name: getattr(proof, item.name) for item in fields(r.ReportProof)},
        )
    encode_report_manifest(result)
    return result


def report_table_digest(table: r.ReportTableKey, rows: Iterable[r.ReportRow]) -> str:
    from .report_schema import table_schema, validate_report_row

    digest = hashlib.sha256()
    schema = encode_report_schema(table_schema(table))
    digest.update(len(schema).to_bytes(8, "big"))
    digest.update(schema)
    for count, row in enumerate(rows, start=1):
        r.report_limit(count <= r.MAX_REPORT_DATASET_ROWS, "rows")
        validate_report_row(table, row)
        payload = encode_report_row(row)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def report_document_digest(value: v3.ReportHeaderContract) -> str:
    raw = cast("dict[str, JsonValue]", _primitive(value))
    del raw["document_digest"]
    return hashlib.sha256(_json(raw, r.MAX_REPORT_MANIFEST_BYTES)).hexdigest()


def decode_report_selection_v3(payload: bytes) -> v3.ReportSelectionV3:
    """Called only after the explicit profile-three request/metadata boundary."""
    return _read(payload, v3.ReportSelectionV3, 64 * 1024)


def decode_report_header_v3(payload: bytes) -> v3.ReportDocumentHeaderV3:
    return _read(payload, v3.ReportDocumentHeaderV3, r.MAX_REPORT_MANIFEST_BYTES)


def decode_report_capture_v3(payload: bytes) -> v3.ReportCaptureSummaryV3:
    return _read(payload, v3.ReportCaptureSummaryV3, r.MAX_REPORT_DOCUMENT_BYTES)


def decode_report_manifest_v3(payload: bytes) -> v3.ReportManifestV3:
    result = _read(payload, v3.ReportManifestV3, r.MAX_REPORT_MANIFEST_BYTES)
    _validate_manifest(result)
    return result
