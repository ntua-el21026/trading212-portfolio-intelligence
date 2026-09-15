"""V2 report commands and semantic manifest bytes over the shared report service."""

from __future__ import annotations

import hashlib
from uuid import UUID

from fastapi import Request, Response
from pydantic import BaseModel
from trading212_api_contracts import premium_reports as wire
from trading212_api_contracts import premium_reports_v3 as profiles
from trading212_application import reports as application
from trading212_domain import report_v3 as v3
from trading212_domain import reports as domain
from trading212_domain.errors import DomainError
from trading212_domain.report_manifest import encode_report_manifest
from trading212_domain.serialization import to_primitive
from trading212_domain.values import CurrencyCode

from .report_schemas import MAX_REPORT_JSON_BYTES, _uuid
from .target_routes import _error


def report_command(
    value: profiles.GeneratePremiumReportRequest, key: str
) -> application.GenerateReportCommand:
    if isinstance(value, profiles.GeneratePremiumReportRequestV3):
        return application.GenerateReportCommand(
            selection=v3.ReportSelectionV3(
                account_id=UUID(value.account_id),
                start_date=value.start_date,
                end_date=value.end_date,
                source_cutoff_at=value.source_cutoff_at,
                snapshot_id=UUID(value.snapshot_id),
                reporting_currency=CurrencyCode(value.reporting_currency),
                report_type=domain.ReportType(value.report_type),
                sections=tuple(domain.ReportSection(item) for item in value.sections),
                formats=tuple(domain.ReportFormat(item) for item in value.formats),
                premium_run=(
                    v3.ReportRiskRunSelection(run_id=UUID(value.premium_run.run_id))
                    if isinstance(value.premium_run, profiles.PremiumReportRiskRunSelectionV3)
                    else v3.ReportScenarioRunSelection(run_id=UUID(value.premium_run.run_id))
                ),
                target_version_id=_uuid(value.target_version_id),
                plan_revision_id=_uuid(value.plan_revision_id),
                benchmark_version_id=_uuid(value.benchmark_version_id),
                constituent_snapshot_id=_uuid(value.constituent_snapshot_id),
                xray_run_id=_uuid(value.xray_run_id),
                template_version=value.template_version,
                profile_version=value.profile_version,
            ),
            idempotency_key=key,
            ttl_days=value.ttl_days,
        )
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
            risk_run_id=UUID(value.risk_run_id),
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
        if schema is profiles.PremiumReportManifestV3:
            if not isinstance(value, v3.ReportManifestV3):
                raise TypeError
            # Canonical V3 serialization deliberately omits absent optional pins.
            payload = encode_report_manifest(value)
            schema.model_validate_json(payload)
        elif schema is wire.ReportManifest:
            schema.model_validate(to_primitive(value))
            if not isinstance(value, domain.ReportManifest):
                raise TypeError
            # Preserve the bytes bound by the published semantic manifest digest.
            payload = encode_report_manifest(value)
        else:
            primitive = to_primitive(value)
            if schema in (profiles.PremiumReportJobStatusV3, profiles.PremiumReportPageV3):
                # This mapper is selected only after the profile-specific service
                # has authorized normalized owner/account/profile metadata.
                if not isinstance(primitive, dict) or "profile_version" in primitive:
                    raise TypeError
                primitive = {**primitive, "profile_version": "report_sections_v3"}
                if schema is profiles.PremiumReportPageV3:
                    items = primitive.get("items")
                    if not isinstance(items, list) or any(
                        not isinstance(item, dict) or "profile_version" in item for item in items
                    ):
                        raise TypeError
                    primitive["items"] = [
                        {**item, "profile_version": "report_sections_v3"} for item in items
                    ]
            checked = schema.model_validate(primitive)
            payload = checked.model_dump_json().encode("utf-8")
    except (DomainError, KeyError, TypeError, ValueError):
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
