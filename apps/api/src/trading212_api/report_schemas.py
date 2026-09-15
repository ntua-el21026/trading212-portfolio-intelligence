"""Report commands and validated JSON/binary responses for the fixed HTTP surface."""

from __future__ import annotations

import hashlib
from uuid import UUID

from fastapi import Request, Response
from pydantic import BaseModel
from trading212_api_contracts import reports as wire
from trading212_application import reports as application
from trading212_domain import reports as domain
from trading212_domain.report_manifest import encode_report_manifest
from trading212_domain.serialization import to_primitive
from trading212_domain.values import CurrencyCode

from .target_routes import _error

MAX_REPORT_JSON_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_BYTES = 10 * 1024 * 1024


def _uuid(value: str | None) -> UUID | None:
    return UUID(value) if value is not None else None


def report_command(
    value: wire.GenerateReportRequest, key: str
) -> application.GenerateReportCommand:
    return application.GenerateReportCommand(
        selection=application.ReportSelection(
            account_id=UUID(value.account_id),
            start_date=value.start_date,
            end_date=value.end_date,
            source_cutoff_at=value.source_cutoff_at,
            snapshot_id=UUID(value.snapshot_id),
            reporting_currency=CurrencyCode(value.reporting_currency),
            report_type=domain.ReportType(value.report_type),
            sections=tuple(domain.ReportSection(item) for item in value.sections),
            formats=tuple(domain.ReportFormat(item) for item in value.formats),
            target_version_id=_uuid(value.target_version_id),
            plan_revision_id=_uuid(value.plan_revision_id),
            benchmark_version_id=_uuid(value.benchmark_version_id),
            constituent_snapshot_id=_uuid(value.constituent_snapshot_id),
            xray_run_id=_uuid(value.xray_run_id),
            template_version=value.template_version,
        ),
        idempotency_key=key,
        ttl_days=value.ttl_days,
    )


def export_command(value: wire.CreateExportRequest, key: str) -> application.CreateExportCommand:
    return application.CreateExportCommand(
        selection=application.ExportSelection(
            account_id=UUID(value.account_id),
            start_date=value.start_date,
            end_date=value.end_date,
            source_cutoff_at=value.source_cutoff_at,
            snapshot_id=UUID(value.snapshot_id),
            reporting_currency=CurrencyCode(value.reporting_currency),
            dataset=domain.ExportDataset(value.dataset),
            field_set=domain.ExportFieldSet(value.field_set),
            format=domain.ExportFormat(value.format),
            target_version_id=_uuid(value.target_version_id),
            plan_revision_id=_uuid(value.plan_revision_id),
            benchmark_version_id=_uuid(value.benchmark_version_id),
            constituent_snapshot_id=_uuid(value.constituent_snapshot_id),
            xray_run_id=_uuid(value.xray_run_id),
        ),
        idempotency_key=key,
        ttl_days=value.ttl_days,
    )


def report_response[T: BaseModel](
    request: Request,
    value: object,
    schema: type[T],
    *,
    status_code: int = 200,
    conditional: bool = False,
) -> Response:
    try:
        if schema is wire.ReportManifest:
            if not isinstance(value, domain.ReportManifest):
                raise TypeError
            # Preserve the bytes bound by the published semantic manifest digest.
            payload = encode_report_manifest(value)
            schema.model_validate_json(payload)
        else:
            checked = schema.model_validate(to_primitive(value))
            payload = checked.model_dump_json().encode("utf-8")
    except (KeyError, TypeError, ValueError):
        return _error(request, 500, "INTERNAL_ERROR", "The private report operation failed.")
    if len(payload) > MAX_REPORT_JSON_BYTES:
        return _error(request, 422, "RESULT_TOO_LARGE", "The report result exceeds its byte bound.")
    headers = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
    # Authorization and complete DTO/byte validation precede conditional responses.
    if conditional:
        etag = '"' + hashlib.sha256(payload).hexdigest() + '"'
        headers["ETag"] = etag
        supplied = {
            item.strip().removeprefix("W/")
            for item in request.headers.get("if-none-match", "").split(",")
        }
        if etag in supplied or "*" in supplied:
            return Response(status_code=304, headers=headers)
    return Response(
        payload, status_code=status_code, media_type="application/json", headers=headers
    )


def report_artifact_response(
    request: Request, value: application.ReportArtifactDownload, *, artifact_id: UUID
) -> Response:
    try:
        metadata = wire.ReportArtifactMetadata.model_validate(to_primitive(value.metadata))
        if (
            UUID(metadata.artifact_id) != artifact_id
            or type(value.content) is not bytes
            or len(value.content) != metadata.byte_length
            or len(value.content) > MAX_ARTIFACT_BYTES
            or hashlib.sha256(value.content).hexdigest() != metadata.content_digest
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return _error(request, 500, "INTERNAL_ERROR", "The private artifact could not be verified.")
    # A fixed opaque identity supplies the filename; arbitrary stored labels never enter headers.
    filename = f"portfolio-artifact-{metadata.artifact_id}.{metadata.format}"
    return Response(
        value.content,
        media_type=metadata.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(metadata.byte_length),
            "X-Artifact-SHA256": metadata.content_digest,
        },
    )
