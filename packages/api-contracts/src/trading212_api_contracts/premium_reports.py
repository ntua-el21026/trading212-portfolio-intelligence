"""Closed V2 premium reports without widening the frozen V1 API/MCP contracts."""

from __future__ import annotations

import calendar
from datetime import date
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, StrictBool, StrictInt, model_validator

from . import reports as legacy
from .sources import CalendarDate, SourceAvailability, SourceQuality
from .targets import AwareInstant, CurrencyString, Cursor, Digest, UUIDString

# These contracts have no premium-specific semantics. Reuse their validation and
# renderer/cell layouts, rather than creating subtly different V2 copies.
ReportSchema = legacy.ReportSchema
ReportType = legacy.ReportType
ReportFormat = legacy.ReportFormat
ReportFormats = legacy.ReportFormats
ReportText = legacy.ReportText
ReportKey = legacy.ReportKey
ReportCount = legacy.ReportCount
ReportTTL = legacy.ReportTTL
ReportJobState = legacy.ReportJobState
ReportFailureCode = legacy.ReportFailureCode
ReportInputRole = legacy.ReportInputRole
ReportAccountQuery = legacy.ReportAccountQuery
ReportListQuery = legacy.ReportListQuery
EmptyReportRequest = legacy.EmptyReportRequest
ArtifactGrant = legacy.ArtifactGrant
ReportArtifactMetadata = legacy.ReportArtifactMetadata
ReportCell = legacy.ReportCell
ReportRow = legacy.ReportRow
ReportRendererProfile = legacy.ReportRendererProfile
ReportSourceReference = legacy.ReportSourceReference
ReportSourceMembership = legacy.ReportSourceMembership
ReportNoteMembership = legacy.ReportNoteMembership
ReportLicenseReference = legacy.ReportLicenseReference
ReportReconciliationBinding = legacy.ReportReconciliationBinding

ReportSection = Literal[legacy.ReportSection, "risk"]
ReportFamily = Literal[legacy.ReportFamily, "risk"]
RiskReportTableKey = Literal[
    "risk_basis_v1",
    "risk_definition_v1",
    "risk_observed_v1",
    "risk_rolling_v1",
    "risk_matrix_summary_v1",
    "risk_matrix_axes_v1",
    "risk_matrix_cells_v1",
    "risk_tails_v1",
    "risk_modeled_v1",
    "risk_components_v1",
    "risk_concentration_v1",
    "risk_run_assets_v1",
    "risk_series_v1",
    "risk_intervals_v1",
    "risk_history_context_v1",
    "risk_history_members_v1",
    "risk_xray_paths_v1",
]
ReportTableKey = Literal[legacy.ReportTableKey, RiskReportTableKey]


def _unique_sections(values: list[ReportSection]) -> list[ReportSection]:
    if len(values) != len(set(values)):
        raise ValueError("Repeated report selectors are not permitted.")
    return values


ReportSections = Annotated[
    list[ReportSection], Field(min_length=1, max_length=14), AfterValidator(_unique_sections)
]

_CALENDAR_SECTIONS = ("overview", "allocation", "performance", "income", "cash_flows", "quality")
_REQUIRED_SECTIONS = {
    "monthly": _CALENDAR_SECTIONS,
    "quarterly": _CALENDAR_SECTIONS,
    "annual": _CALENDAR_SECTIONS,
    "portfolio_summary": ("overview", "allocation", "quality"),
    "target_drift": ("overview", "targets", "drift", "quality"),
    "contribution_plan": ("overview", "targets", "contribution_plan", "quality"),
    "performance_benchmark": ("overview", "performance", "benchmark", "quality"),
    "dividend_income": ("overview", "income", "cash_flows", "quality"),
    "portfolio_xray": ("overview", "xray", "quality"),
    "quality_reconciliation": ("overview", "quality", "activity"),
}


class PremiumReportSelection(ReportSchema):
    account_id: UUIDString
    start_date: CalendarDate
    end_date: CalendarDate
    source_cutoff_at: AwareInstant
    snapshot_id: UUIDString
    reporting_currency: CurrencyString
    report_type: ReportType
    sections: ReportSections
    formats: ReportFormats
    risk_run_id: UUIDString
    target_version_id: UUIDString | None = None
    plan_revision_id: UUIDString | None = None
    benchmark_version_id: UUIDString | None = None
    constituent_snapshot_id: UUIDString | None = None
    xray_run_id: UUIDString | None = None
    template_version: Literal["report_template_v1"] = "report_template_v1"

    @model_validator(mode="after")
    def bounded_selection(self) -> Self:
        if not 0 <= (self.end_date - self.start_date).days <= 3660:
            raise ValueError("The report period exceeds its date bounds.")
        selected = set(self.sections)
        if "risk" not in selected:
            raise ValueError("A premium report requires the pinned risk section.")
        if not set(_REQUIRED_SECTIONS[self.report_type]).issubset(selected):
            raise ValueError("Required report sections are missing.")
        if self.xray_run_id is not None and "drift" not in selected:
            raise ValueError("Company actuals require a drift section.")
        wants_target = bool(selected & {"targets", "drift", "contribution_plan"})
        if wants_target and self.target_version_id is None and self.plan_revision_id is None:
            raise ValueError("A published target reference is required.")
        for name, wanted, value in (
            ("target_version_id", wants_target, self.target_version_id),
            ("plan_revision_id", "contribution_plan" in selected, self.plan_revision_id),
            ("benchmark_version_id", "benchmark" in selected, self.benchmark_version_id),
            ("constituent_snapshot_id", "xray" in selected, self.constituent_snapshot_id),
        ):
            if value is not None and not wanted:
                raise ValueError("A report reference is irrelevant.")
            if wanted and name in {"plan_revision_id", "benchmark_version_id"} and value is None:
                raise ValueError("A required report reference is missing.")
        _calendar_period(self.report_type, self.start_date, self.end_date)
        return self


def _calendar_period(kind: ReportType, start: date, end: date) -> None:
    if kind == "monthly":
        valid = start.day == 1 and end == date(
            start.year, start.month, calendar.monthrange(start.year, start.month)[1]
        )
    elif kind == "quarterly":
        final_month = start.month + 2
        valid = (
            start.day == 1
            and start.month in {1, 4, 7, 10}
            and end
            == date(start.year, final_month, calendar.monthrange(start.year, final_month)[1])
            if final_month <= 12
            else False
        )
    elif kind == "annual":
        valid = start == date(start.year, 1, 1) and end == date(start.year, 12, 31)
    else:
        return
    if not valid:
        raise ValueError("A complete calendar period is required.")


class GeneratePremiumReportRequest(PremiumReportSelection):
    ttl_days: ReportTTL = 7


class PremiumReportNote(ReportSchema):
    key: ReportKey
    kind: Literal["warning", "assumption", "limitation", "unavailable_reason", "reconciliation"]
    family: ReportFamily
    code: ReportKey
    text: ReportText
    related_provenance_set_key: ReportKey | None


class PremiumReportInputPin(ReportSchema):
    family: ReportFamily
    role: ReportInputRole
    subject_id: UUIDString
    content_digest: Digest
    parent_id: UUIDString | None
    method_key: ReportKey | None
    method_version: ReportKey | None


class PremiumReportQualitySummary(ReportSchema):
    state: SourceQuality
    availability: SourceAvailability
    evaluated_at: AwareInstant
    warnings: Annotated[list[PremiumReportNote], Field(max_length=64)]
    warning_count: ReportCount
    warning_omitted_count: ReportCount

    @model_validator(mode="after")
    def warning_counts(self) -> Self:
        if self.warning_count != len(self.warnings) + self.warning_omitted_count:
            raise ValueError("Report warning counts disagree.")
        return self


class PremiumReportPinnedContext(ReportSchema):
    snapshot_id: UUIDString
    valuation_at: AwareInstant
    source_cutoff_at: AwareInstant
    reporting_currency: CurrencyString
    input_digest: Digest
    document_digest: Digest
    profile_version: Literal["report_sections_v2"]
    schema_version: Literal["2.0.0"]
    pins: Annotated[list[PremiumReportInputPin], Field(max_length=256)]
    quality: PremiumReportQualitySummary


class PremiumReportJobStatus(ReportSchema):
    account_id: UUIDString
    context: PremiumReportPinnedContext | None
    job_id: UUIDString
    report_id: UUIDString | None
    state: ReportJobState
    requested_at: AwareInstant
    completed_at: AwareInstant | None
    expires_at: AwareInstant
    failure_code: ReportFailureCode | None
    report_type: ReportType
    formats: ReportFormats
    manifest_digest: Digest | None
    artifacts: Annotated[list[ReportArtifactMetadata], Field(max_length=4)]

    @model_validator(mode="after")
    def atomic_result(self) -> Self:
        if self.state == "succeeded":
            if (
                self.report_id != self.job_id
                or self.manifest_digest is None
                or self.completed_at is None
                or self.failure_code is not None
                or len(self.artifacts) != len(self.formats)
                or {item.format for item in self.artifacts} != set(self.formats)
            ):
                raise ValueError("A successful report requires every requested artifact.")
        elif self.state != "expired" and self.artifacts:
            raise ValueError("An incomplete report cannot expose artifacts.")
        if self.context is None and self.state not in {"expired", "cancelled"}:
            raise ValueError("An active report requires its immutable input context.")
        if sum(item.byte_length for item in self.artifacts) > 25 * 1024 * 1024:
            raise ValueError("The report exceeds its total artifact byte bound.")
        if any(item.expires_at > self.expires_at for item in self.artifacts):
            raise ValueError("An artifact cannot outlive its report.")
        return self


class PremiumReportPage(ReportSchema):
    items: Annotated[list[PremiumReportJobStatus], Field(max_length=100)]
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: ReportCount

    @model_validator(mode="after")
    def page_counts(self) -> Self:
        if len(self.items) > self.limit or len(self.items) > self.total:
            raise ValueError("The report page exceeds its declared bounds.")
        return self


class PremiumReportTableDescriptor(ReportSchema):
    table: ReportTableKey
    schema_digest: Digest
    row_count: Annotated[StrictInt, Field(ge=0, le=100000)]
    content_digest: Digest
    section: ReportSection | None
    dataset: None
    state: SourceAvailability
    reason_key: ReportKey | None


class PremiumReportDocumentHeader(ReportSchema):
    selection: PremiumReportSelection
    owner_id: UUIDString
    valuation_at: AwareInstant
    context_digest: Digest
    tables: Annotated[list[PremiumReportTableDescriptor], Field(max_length=128)]
    document_digest: Digest
    document_schema_version: Literal["2.0.0"]


class PremiumReportContext(ReportSchema):
    key: ReportKey
    family: ReportFamily
    method_key: ReportKey
    method_version: ReportKey
    valuation_at: AwareInstant
    source_cutoff_at: AwareInstant
    quality: SourceQuality
    provenance_set_key: ReportKey
    coverage_set_key: ReportKey
    note_set_key: ReportKey
    source_at: AwareInstant | None
    reconciliation_key: ReportKey | None
    schema_version: Literal["2.0.0"]


class PremiumReportCoverageFact(ReportSchema):
    set_key: ReportKey
    family: ReportFamily
    metric_key: ReportKey
    value: ReportCell


class PremiumReportBoundFact(ReportSchema):
    key: ReportKey
    family: ReportFamily
    kind: Literal["exact", "lower_bound", "unavailable"]
    quantum: legacy.ReportDecimal | None
    rounding: ReportKey | None
    positive_below_quantum: StrictBool


class PremiumReportProofRelation(ReportSchema):
    table: ReportTableKey
    row: ReportRow


class PremiumReportManifest(ReportSchema):
    document: PremiumReportDocumentHeader
    renderer_profile: ReportRendererProfile
    bindings: Annotated[list[PremiumReportInputPin], Field(max_length=256)]
    contexts: Annotated[list[PremiumReportContext], Field(max_length=100000)]
    source_references: Annotated[list[ReportSourceReference], Field(max_length=100000)]
    source_memberships: Annotated[list[ReportSourceMembership], Field(max_length=100000)]
    note_memberships: Annotated[list[ReportNoteMembership], Field(max_length=100000)]
    license_references: Annotated[list[ReportLicenseReference], Field(max_length=256)]
    coverage: Annotated[list[PremiumReportCoverageFact], Field(max_length=100000)]
    bounds: Annotated[list[PremiumReportBoundFact], Field(max_length=100000)]
    notes: Annotated[list[PremiumReportNote], Field(max_length=100000)]
    proof_relations: Annotated[list[PremiumReportProofRelation], Field(max_length=100000)]
    reconciliation: Annotated[list[ReportReconciliationBinding], Field(max_length=100000)]
    method: Literal["report_manifest_v1"]
    method_version: Literal["1.0.0"]
    escaping_version: Literal["report_csv_text_v1"]


# Route adapters use familiar names; unique class names preserve V1 OpenAPI components.
ReportSelection = PremiumReportSelection
GenerateReportRequest = GeneratePremiumReportRequest
ReportNote = PremiumReportNote
ReportInputPin = PremiumReportInputPin
ReportQualitySummary = PremiumReportQualitySummary
ReportPinnedContext = PremiumReportPinnedContext
ReportJobStatus = PremiumReportJobStatus
ReportPage = PremiumReportPage
ReportTableDescriptor = PremiumReportTableDescriptor
ReportDocumentHeader = PremiumReportDocumentHeader
ReportContext = PremiumReportContext
ReportCoverageFact = PremiumReportCoverageFact
ReportBoundFact = PremiumReportBoundFact
ReportProofRelation = PremiumReportProofRelation
ReportManifest = PremiumReportManifest
