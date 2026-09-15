"""Private report application contracts shared by API, capture and render workers."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from trading212_domain.enums import QualityState
from trading212_domain.errors import fail_validation
from trading212_domain.report_v3 import (
    ReportCaptureContract,
    ReportHeaderContract,
    ReportManifestContract,
    ReportSelectionV3,
)
from trading212_domain.report_v4 import ReportSelectionV4
from trading212_domain.reports import (
    MAX_REPORT_ARTIFACT_BYTES,
    MAX_REPORT_JOB_BYTES,
    ExportDataset,
    ExportFieldSet,
    ExportFormat,
    ExportSelection,
    ReportCaptureSummary,
    ReportChunk,
    ReportDocumentHeader,
    ReportFailureCode,
    ReportFormat,
    ReportInputPin,
    ReportJobState,
    ReportManifest,
    ReportMimeType,
    ReportNote,
    ReportRecord,
    ReportRendererProfile,
    ReportSelection,
    ReportTableKey,
    ReportType,
    report_limit,
    report_mime_type,
    report_schema_version,
)
from trading212_domain.sources import SourceAvailability
from trading212_domain.values import CurrencyCode
from trading212_security.principals import Principal

from .views import Page

__all__ = [
    "ArtifactGrant",
    "BoundedArtifactBuffer",
    "BoundedArtifactSink",
    "CreateExportCommand",
    "ExportDataset",
    "ExportFieldSet",
    "ExportFormat",
    "ExportJobStatus",
    "ExportListQuery",
    "ExportSelection",
    "GenerateReportCommand",
    "RenderedArtifact",
    "ReportArtifactDownload",
    "ReportArtifactMetadata",
    "ReportCapturePort",
    "ReportCaptureSink",
    "ReportChunkSink",
    "ReportDocumentHeader",
    "ReportDocumentReader",
    "ReportInputPin",
    "ReportJobStatus",
    "ReportListQuery",
    "ReportManifest",
    "ReportPinnedContext",
    "ReportQualitySummary",
    "ReportRenderError",
    "ReportRenderGuard",
    "ReportRenderReceipt",
    "ReportRendererPort",
    "ReportSelection",
    "ReportService",
    "ReportServiceError",
    "ReportServiceErrorCode",
    "ReportsService",
]


class ReportServiceErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INPUT_BOUND_EXCEEDED = "INPUT_BOUND_EXCEEDED"
    CONFLICT = "CONFLICT"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    RATE_LIMITED = "RATE_LIMITED"
    ARTIFACT_EXPIRED = "ARTIFACT_EXPIRED"
    REPORT_UNAVAILABLE = "REPORT_UNAVAILABLE"
    RESULT_TOO_LARGE = "RESULT_TOO_LARGE"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    JOB_DISPATCH_UNAVAILABLE = "JOB_DISPATCH_UNAVAILABLE"


@dataclass(slots=True)
class ReportServiceError(Exception):
    code: ReportServiceErrorCode
    message: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.message


@dataclass(slots=True)
class ReportRenderError(Exception):
    code: ReportFailureCode
    retryable: bool = False

    def __str__(self) -> str:
        return "The private report artifact could not be generated."


def _command(key: str, ttl: int) -> None:
    if re.fullmatch(r"[A-Za-z0-9._:-]{1,180}", key) is None:
        fail_validation("A bounded idempotency key is required.", field="idempotency_key")
    if not 1 <= ttl <= 30:
        fail_validation("Report retention must be one through thirty days.", field="ttl_days")


@dataclass(frozen=True, slots=True, kw_only=True)
class GenerateReportCommand(ReportRecord):
    selection: ReportSelection | ReportSelectionV3 | ReportSelectionV4
    idempotency_key: str
    ttl_days: int = 7

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        _command(self.idempotency_key, self.ttl_days)


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateExportCommand(ReportRecord):
    selection: ExportSelection
    idempotency_key: str
    ttl_days: int = 7

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        _command(self.idempotency_key, self.ttl_days)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportQualitySummary(ReportRecord):
    state: QualityState
    availability: SourceAvailability
    evaluated_at: datetime
    warnings: tuple[ReportNote, ...] = ()
    warning_count: int = 0
    warning_omitted_count: int = 0

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        report_limit(len(self.warnings) <= 64, "warnings")
        if (
            self.warning_count < 0
            or self.warning_omitted_count < 0
            or len(self.warnings) + self.warning_omitted_count != self.warning_count
        ):
            fail_validation("Report warning counts disagree.", field="warnings")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportPinnedContext(ReportRecord):
    snapshot_id: UUID
    valuation_at: datetime
    source_cutoff_at: datetime
    reporting_currency: CurrencyCode
    input_digest: str
    document_digest: str
    pins: tuple[ReportInputPin, ...]
    quality: ReportQualitySummary
    profile_version: str = "report_sections_v1"
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        report_limit(len(self.pins) <= 256, "pins")
        if (self.profile_version, self.schema_version) not in {
            ("report_sections_v1", "1.0.0"),
            ("report_sections_v2", "2.0.0"),
        }:
            fail_validation("Report context profile is unsupported.", field="profile_version")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportPinnedContextV3(ReportPinnedContext):
    """Explicit V3 status copy; the legacy decoder remains closed to this profile."""

    profile_version: str = "report_sections_v3"
    schema_version: str = "3.0.0"

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        report_limit(len(self.pins) <= 256, "pins")
        if (self.profile_version, self.schema_version) != ("report_sections_v3", "3.0.0"):
            fail_validation("Report context profile is unsupported.", field="profile_version")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportPinnedContextV4(ReportPinnedContext):
    """Explicit V4 status context; its ordinary snapshot clocks remain required."""

    profile_version: str = "report_sections_v4"
    schema_version: str = "4.0.0"

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        report_limit(len(self.pins) <= 256, "pins")
        if (self.profile_version, self.schema_version) != ("report_sections_v4", "4.0.0"):
            fail_validation("Report context profile is unsupported.", field="profile_version")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportArtifactMetadata(ReportRecord):
    artifact_id: UUID
    format: ReportFormat
    mime_type: ReportMimeType
    byte_length: int
    content_digest: str
    expires_at: datetime

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        report_limit(0 < self.byte_length <= MAX_REPORT_ARTIFACT_BYTES, "byte_length")
        if self.mime_type is not report_mime_type(self.format):
            fail_validation("Artifact MIME does not match its format.", field="mime_type")


def _status(
    state: ReportJobState,
    context: ReportPinnedContext | ReportPinnedContextV3 | ReportPinnedContextV4 | None,
    digest: str | None,
    artifacts: tuple[ReportArtifactMetadata, ...],
    completed: datetime | None,
    failure: ReportFailureCode | None,
) -> None:
    if context is None and state not in {ReportJobState.EXPIRED, ReportJobState.CANCELLED}:
        fail_validation("Live report status requires its pinned context.", field="context")
    if state is ReportJobState.SUCCEEDED and (
        digest is None or completed is None or not artifacts or failure is not None
    ):
        fail_validation("Successful report metadata is incomplete.", field="state")
    if state in {ReportJobState.QUEUED, ReportJobState.RUNNING, ReportJobState.FAILED} and (
        digest is not None or artifacts
    ):
        fail_validation("Unsealed report cannot expose artifact metadata.", field="artifacts")
    if state is ReportJobState.FAILED and failure is None:
        fail_validation("Failed report requires a safe reason.", field="failure_code")
    report_limit(len(artifacts) <= 4, "artifacts")
    report_limit(
        sum(item.byte_length for item in artifacts) <= MAX_REPORT_JOB_BYTES, "artifact_bytes"
    )
    if len({item.artifact_id for item in artifacts}) != len(artifacts) or len(
        {item.format for item in artifacts}
    ) != len(artifacts):
        fail_validation("Artifact identities/formats must be unique.", field="artifacts")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportJobStatus(ReportRecord):
    account_id: UUID
    context: ReportPinnedContext | ReportPinnedContextV3 | ReportPinnedContextV4 | None
    job_id: UUID
    state: ReportJobState
    requested_at: datetime
    expires_at: datetime
    report_type: ReportType
    formats: tuple[ReportFormat, ...]
    report_id: UUID | None = None
    completed_at: datetime | None = None
    failure_code: ReportFailureCode | None = None
    manifest_digest: str | None = None
    artifacts: tuple[ReportArtifactMetadata, ...] = ()

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        _status(
            self.state,
            self.context,
            self.manifest_digest,
            self.artifacts,
            self.completed_at,
            self.failure_code,
        )
        if not 1 <= len(self.formats) <= 4 or len(set(self.formats)) != len(self.formats):
            fail_validation("Report formats must be bounded and unique.", field="formats")
        if self.report_id is not None and (
            self.report_id != self.job_id
            or self.state in {ReportJobState.QUEUED, ReportJobState.RUNNING, ReportJobState.FAILED}
        ):
            fail_validation(
                "Report identity requires a previously successful job.", field="report_id"
            )
        if self.state is ReportJobState.SUCCEEDED and (
            self.report_id != self.job_id
            or set(x.format for x in self.artifacts) != set(self.formats)
        ):
            fail_validation("Successful report formats are incomplete.", field="artifacts")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportJobStatus(ReportRecord):
    account_id: UUID
    context: ReportPinnedContext | None
    export_id: UUID
    state: ReportJobState
    requested_at: datetime
    expires_at: datetime
    dataset: ExportDataset
    field_set: ExportFieldSet
    format: ExportFormat
    completed_at: datetime | None = None
    failure_code: ReportFailureCode | None = None
    manifest_digest: str | None = None
    artifacts: tuple[ReportArtifactMetadata, ...] = ()

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        _status(
            self.state,
            self.context,
            self.manifest_digest,
            self.artifacts,
            self.completed_at,
            self.failure_code,
        )
        if self.state is ReportJobState.SUCCEEDED and (
            len(self.artifacts) != 1 or self.artifacts[0].format.value != self.format.value
        ):
            fail_validation("Successful export format is incomplete.", field="artifacts")


@dataclass(frozen=True, slots=True, kw_only=True)
class ArtifactGrant(ReportRecord):
    artifact_id: UUID
    token: str
    expires_at: datetime

    def __repr__(self) -> str:
        return (
            f"ArtifactGrant(artifact_id={self.artifact_id!r}, "
            f"token=<redacted>, expires_at={self.expires_at!r})"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RenderedArtifact(ReportRecord):
    format: ReportFormat
    mime_type: ReportMimeType
    content: bytes
    byte_length: int
    content_digest: str

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        report_limit(0 < self.byte_length <= MAX_REPORT_ARTIFACT_BYTES, "byte_length")
        if self.byte_length != len(self.content) or self.mime_type is not report_mime_type(
            self.format
        ):
            fail_validation("Rendered artifact metadata disagrees.", field="artifact")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportRenderReceipt(ReportRecord):
    format: ReportFormat
    mime_type: ReportMimeType

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        if self.mime_type is not report_mime_type(self.format):
            fail_validation("Rendered format and MIME disagree.", field="mime_type")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportArtifactDownload(ReportRecord):
    metadata: ReportArtifactMetadata
    filename: str
    content: bytes

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        report_limit(len(self.content) <= MAX_REPORT_ARTIFACT_BYTES, "content")
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.(pdf|csv|json|xlsx)", self.filename):
            fail_validation("A fixed safe artifact filename is required.", field="filename")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportListQuery(ReportRecord):
    limit: int = 25
    cursor: str | None = None
    state: ReportJobState | None = None
    report_type: ReportType | None = None
    start_date: date | None = None
    end_date: date | None = None
    sort: str = "created_desc"

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        if not 1 <= self.limit <= 100 or self.sort != "created_desc":
            fail_validation("Report listing is outside its bound.", field="query")
        if (self.start_date is None) != (self.end_date is None):
            fail_validation("Both report period boundaries are required.", field="period")
        if (
            self.start_date is not None
            and self.end_date is not None
            and (self.start_date > self.end_date or (self.end_date - self.start_date).days > 3660)
        ):
            fail_validation("Report period is outside its bound.", field="period")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportListQuery(ReportRecord):
    limit: int = 25
    cursor: str | None = None
    state: ReportJobState | None = None
    dataset: ExportDataset | None = None
    sort: str = "created_desc"

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        if not 1 <= self.limit <= 100 or self.sort != "created_desc":
            fail_validation("Export listing is outside its bound.", field="query")


class ReportChunkSink(Protocol):
    def append(self, chunk: ReportChunk) -> None: ...


class ReportCaptureSink(ReportChunkSink, Protocol):
    def finish(self, summary: ReportCaptureContract) -> None: ...


class ReportCapturePort(Protocol):
    def capture_report(
        self,
        selection: ReportSelection | ReportSelectionV3 | ReportSelectionV4,
        *,
        sink: ReportCaptureSink,
    ) -> ReportCaptureContract: ...
    def capture_export(
        self, selection: ExportSelection, *, sink: ReportCaptureSink
    ) -> ReportCaptureSummary: ...


class ReportDocumentReader(Protocol):
    @property
    def header(self) -> ReportHeaderContract: ...
    @property
    def manifest(self) -> ReportManifestContract: ...
    def iter_chunks(self, table: ReportTableKey) -> Iterator[ReportChunk]: ...


class BoundedArtifactSink(Protocol):
    def write(self, chunk: bytes) -> int: ...
    @property
    def byte_length(self) -> int: ...


class BoundedArtifactBuffer(BoundedArtifactSink, Protocol):
    def finish(self, receipt: ReportRenderReceipt) -> RenderedArtifact: ...


class ReportRenderGuard(Protocol):
    def check(self) -> None: ...


class ReportRendererPort(Protocol):
    def render(
        self,
        document: ReportDocumentReader,
        *,
        format: ReportFormat,
        profile: ReportRendererProfile,
        sink: BoundedArtifactSink,
        guard: ReportRenderGuard,
    ) -> ReportRenderReceipt: ...


class ReportService(Protocol):
    async def generate_report(
        self, principal: Principal, command: GenerateReportCommand
    ) -> ReportJobStatus: ...
    async def get_report_status(
        self, principal: Principal, account_id: UUID, job_id: UUID
    ) -> ReportJobStatus: ...
    async def list_reports(
        self, principal: Principal, account_id: UUID, *, query: ReportListQuery
    ) -> Page[ReportJobStatus]: ...
    async def get_report_manifest(
        self, principal: Principal, account_id: UUID, report_id: UUID
    ) -> ReportManifestContract: ...
    async def create_report_download_grant(
        self, principal: Principal, account_id: UUID, report_id: UUID, artifact_id: UUID
    ) -> ArtifactGrant: ...
    async def download_report_artifact(
        self,
        principal: Principal,
        account_id: UUID,
        report_id: UUID,
        artifact_id: UUID,
        *,
        grant_token: str,
    ) -> ReportArtifactDownload: ...
    async def create_export(
        self, principal: Principal, command: CreateExportCommand
    ) -> ExportJobStatus: ...
    async def get_export_status(
        self, principal: Principal, account_id: UUID, export_id: UUID
    ) -> ExportJobStatus: ...
    async def list_exports(
        self, principal: Principal, account_id: UUID, *, query: ExportListQuery
    ) -> Page[ExportJobStatus]: ...
    async def create_export_download_grant(
        self, principal: Principal, account_id: UUID, export_id: UUID, artifact_id: UUID
    ) -> ArtifactGrant: ...
    async def download_export_artifact(
        self,
        principal: Principal,
        account_id: UUID,
        export_id: UUID,
        artifact_id: UUID,
        *,
        grant_token: str,
    ) -> ReportArtifactDownload: ...


ReportsService = ReportService


def encode_report_pinned_context(
    value: ReportPinnedContext | ReportPinnedContextV3 | ReportPinnedContextV4,
) -> bytes:
    """Encode only the safe status projection; grants and artifact bytes are excluded."""
    from dataclasses import fields

    from trading212_domain import report_manifest as codec

    if type(value) not in (ReportPinnedContext, ReportPinnedContextV3, ReportPinnedContextV4):
        fail_validation("A typed report context is required.", field="context")
    raw = {
        item.name: (
            {
                field.name: codec._primitive(getattr(value.quality, field.name))
                for field in fields(ReportQualitySummary)
            }
            if item.name == "quality"
            else codec._primitive(getattr(value, item.name))
        )
        for item in fields(type(value))
    }
    return codec._json(raw, 2 * 1024 * 1024)


def decode_report_pinned_context(payload: bytes) -> ReportPinnedContext:
    return _decode_report_pinned_context(payload, ReportPinnedContext)


def decode_report_pinned_context_v3(payload: bytes) -> ReportPinnedContextV3:
    return _decode_report_pinned_context(payload, ReportPinnedContextV3)


def decode_report_pinned_context_v4(payload: bytes) -> ReportPinnedContextV4:
    return _decode_report_pinned_context(payload, ReportPinnedContextV4)


def _decode_report_pinned_context[T: ReportPinnedContext](payload: bytes, kind: type[T]) -> T:
    from dataclasses import fields
    from typing import Any, cast, get_type_hints

    from trading212_domain import report_manifest as codec
    from trading212_domain.reports import _record_hints

    hints = get_type_hints(kind)
    raw = codec._load(payload, 2 * 1024 * 1024)
    if type(raw) is not dict or set(raw) != {item.name for item in fields(kind)}:
        fail_validation("Pinned report context fields are invalid.", field="context")
    quality = raw["quality"]
    if type(quality) is not dict or set(quality) != {
        item.name for item in fields(ReportQualitySummary)
    }:
        fail_validation("Pinned report quality fields are invalid.", field="quality")
    quality_value = ReportQualitySummary(
        **cast(
            "Any",
            {
                name: codec._decode(item, _record_hints(ReportQualitySummary)[name])
                for name, item in quality.items()
            },
        )
    )
    values = {
        name: codec._decode(item, hints[name]) for name, item in raw.items() if name != "quality"
    }
    result = kind(quality=quality_value, **cast("Any", values))
    if encode_report_pinned_context(result) != payload:
        fail_validation("Pinned report context is not canonical.", field="context")
    return result


def report_request_digest(command: GenerateReportCommand | CreateExportCommand) -> str:
    """Bind semantic requested options including TTL, before resolving mutable inputs."""
    import hashlib

    from trading212_domain.report_manifest import encode_report_selection

    if type(command) not in (GenerateReportCommand, CreateExportCommand):
        fail_validation("A typed report command is required.", field="command")
    selection = encode_report_selection(command.selection)
    version = (
        b"report_request_v4\0"
        if report_schema_version(command.selection) == "4.0.0"
        else b"report_request_v3\0"
        if report_schema_version(command.selection) == "3.0.0"
        else b"report_request_v2\0"
        if report_schema_version(command.selection) == "2.0.0"
        else b"report_request_v1\0"
    )
    framing = version + type(command).__name__.encode("ascii") + b"\0"
    return hashlib.sha256(
        framing
        + len(selection).to_bytes(8, "big")
        + selection
        + command.ttl_days.to_bytes(1, "big")
    ).hexdigest()
