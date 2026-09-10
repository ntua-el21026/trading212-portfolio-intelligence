from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from trading212_application.report_jobs import ReportJobClaim, ReportTaskMessage
from trading212_application.reports import (
    ArtifactGrant,
    GenerateReportCommand,
    ReportJobStatus,
    ReportPinnedContext,
    ReportQualitySummary,
    decode_report_pinned_context,
    encode_report_pinned_context,
    report_request_digest,
)
from trading212_domain import reports as r
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError
from trading212_domain.report_manifest import encode_report_manifest
from trading212_domain.sources import SourceAvailability

from tests.unit.domain.report_factories import AT, document, selection, uid

pytestmark = pytest.mark.unit


def context() -> ReportPinnedContext:
    value = document()
    return ReportPinnedContext(
        snapshot_id=uid(2),
        valuation_at=AT,
        source_cutoff_at=AT,
        reporting_currency=value.header.selection.reporting_currency,
        input_digest="1" * 64,
        document_digest=value.header.document_digest,
        pins=value.capture.immutable_bindings,
        quality=ReportQualitySummary(
            state=QualityState.PARTIAL,
            availability=SourceAvailability.PARTIAL,
            evaluated_at=AT,
            warnings=value.capture.proof.notes,
            warning_count=1,
            warning_omitted_count=0,
        ),
    )


def test_queued_status_has_exact_pins_and_quality_without_successful_artifacts() -> None:
    value = ReportJobStatus(
        account_id=uid(1),
        context=context(),
        job_id=uid(9),
        state=r.ReportJobState.QUEUED,
        requested_at=AT,
        expires_at=AT + timedelta(days=7),
        report_type=r.ReportType.PORTFOLIO_SUMMARY,
        formats=(r.ReportFormat.JSON,),
    )
    assert value.context is not None
    assert (
        decode_report_pinned_context(encode_report_pinned_context(value.context)) == value.context
    )
    with pytest.raises(DomainError):
        replace(value, context=None)
    expired = replace(value, context=None, state=r.ReportJobState.EXPIRED)
    assert expired.job_id == value.job_id and expired.context is None
    with pytest.raises(DomainError):
        replace(value, state=r.ReportJobState.SUCCEEDED)


def test_request_digest_uses_command_ttl_but_not_idempotency_key_or_execution_identity() -> None:
    a = GenerateReportCommand(selection=selection(), idempotency_key="report-a")
    b = replace(a, idempotency_key="report-b")
    assert report_request_digest(a) == report_request_digest(b)
    assert report_request_digest(a) != report_request_digest(replace(a, ttl_days=8))
    canonical = encode_report_manifest(document().manifest)
    assert b'"ttl_days"' not in canonical and b'"idempotency_key"' not in canonical


@pytest.mark.parametrize(
    "change",
    [
        {"ttl_days": 0},
        {"ttl_days": 31},
        {"ttl_days": True},
        {"idempotency_key": "bad key"},
        {"idempotency_key": "x" * 181},
    ],
)
def test_command_rejects_bad_retention_or_idempotency(change: dict[str, object]) -> None:
    with pytest.raises(DomainError):
        GenerateReportCommand(
            selection=selection(), idempotency_key="key", **cast(Any, change)
        ) if "idempotency_key" not in change else GenerateReportCommand(
            selection=selection(), **cast(Any, change)
        )


def test_fixed_task_message_never_admits_payload_or_destination_and_claim_fence_is_integer() -> (
    None
):
    message = ReportTaskMessage(
        job_id=uid(1), owner_id=uid(2), account_id=uid(3), capture_id=uid(4), input_digest="a" * 64
    )
    assert ReportTaskMessage.from_wire(message.to_wire()) == message
    for mutation in (
        {**message.to_wire(), "url": "https://example.invalid"},
        {**message.to_wire(), "input_digest": "bad"},
        {**message.to_wire(), "job_id": 1},
    ):
        with pytest.raises(DomainError):
            ReportTaskMessage.from_wire(mutation)
    for fence in (0, True, Decimal("1")):
        with pytest.raises(DomainError):
            ReportJobClaim(
                message=message,
                lease_id=uid(5),
                fence=cast(Any, fence),
                lease_expires_at=AT + timedelta(seconds=60),
                consumer_attempt=1,
            )


def test_sensitive_grant_is_redacted_and_excluded_from_ordinary_report_codec() -> None:
    grant = ArtifactGrant(
        artifact_id=uid(1), token="synthetic-sensitive-grant", expires_at=AT + timedelta(minutes=5)
    )
    assert grant.token not in repr(grant)
    with pytest.raises(DomainError):
        encode_report_manifest(cast(Any, grant))
