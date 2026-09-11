"""Closed report/export contracts shared by HTTP, MCP and generated web clients."""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from .sources import CalendarDate, SourceAvailability, SourceLicensePermission, SourceQuality
from .targets import AwareInstant, CurrencyString, Cursor, Digest, IdempotencyKey, UUIDString

ReportType = Literal[
    "monthly",
    "quarterly",
    "annual",
    "portfolio_summary",
    "target_drift",
    "contribution_plan",
    "performance_benchmark",
    "dividend_income",
    "portfolio_xray",
    "quality_reconciliation",
]
ReportFormat = Literal["pdf", "csv", "json", "xlsx"]
ExportFormat = Literal["csv", "json", "xlsx"]
ReportSection = Literal[
    "overview",
    "allocation",
    "targets",
    "drift",
    "contribution_plan",
    "performance",
    "benchmark",
    "income",
    "cash_flows",
    "attribution",
    "xray",
    "quality",
    "activity",
]
ExportDataset = Literal[
    "positions",
    "activity",
    "dividends",
    "targets",
    "plans",
    "performance",
    "xray",
    "alerts",
]
ExportFieldSet = Literal["standard", "audit"]
ReportJobState = Literal["queued", "running", "succeeded", "failed", "expired", "cancelled"]
ReportFailureCode = Literal[
    "invalid_input",
    "input_unavailable",
    "input_changed",
    "access_denied",
    "source_restricted",
    "limit_exceeded",
    "render_failed",
    "storage_unavailable",
    "publication_unavailable",
    "lease_expired",
    "attempts_exhausted",
]
ReportMimeType = Literal[
    "application/pdf",
    "text/csv; charset=utf-8",
    "application/json",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
]
ReportFamily = Literal[
    "snapshot",
    "activity",
    "target",
    "planning",
    "performance",
    "benchmark",
    "income",
    "cash_flows",
    "attribution",
    "xray",
    "reconciliation",
    "alerts",
]
ReportInputRole = Literal[
    "snapshot",
    "input",
    "result",
    "calculation",
    "policy",
    "target_version",
    "plan_revision",
    "benchmark_version",
    "source",
    "mapping",
    "license",
    "calendar",
    "event_revision",
    "reconciliation",
]
ReportText = Annotated[str, StringConstraints(strict=True, max_length=4096, pattern=r"^[^\x00]*$")]
ReportKey = Annotated[
    str,
    StringConstraints(
        strict=True, min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$"
    ),
]
ReportCount = Annotated[StrictInt, Field(ge=0, le=2**63 - 1)]
ReportTTL = Annotated[StrictInt, Field(ge=1, le=30)]
ArtifactToken = Annotated[
    str, StringConstraints(strict=True, min_length=32, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
]


def _unique[T](values: list[T]) -> list[T]:
    if len(values) != len(set(values)):
        raise ValueError("Repeated report selectors are not permitted.")
    return values


def _integer_query(value: object) -> object:
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,2}", value):
        return int(value)
    raise ValueError("A bounded integer selector is required.")


ReportSections = Annotated[
    list[ReportSection], Field(min_length=1, max_length=13), AfterValidator(_unique)
]
ReportFormats = Annotated[
    list[ReportFormat], Field(min_length=1, max_length=4), AfterValidator(_unique)
]
ReportPageLimit = Annotated[StrictInt, Field(ge=1, le=100), BeforeValidator(_integer_query)]


class ReportSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def no_unknown_field_reflection(cls, value: object) -> object:
        if isinstance(value, dict) and any(key not in cls.model_fields for key in value):
            raise ValueError("The bounded report object contains unexpected fields.")
        return value


class ReportSelection(ReportSchema):
    account_id: UUIDString
    start_date: CalendarDate
    end_date: CalendarDate
    source_cutoff_at: AwareInstant
    snapshot_id: UUIDString
    reporting_currency: CurrencyString
    report_type: ReportType
    sections: ReportSections
    formats: ReportFormats
    target_version_id: UUIDString | None = None
    plan_revision_id: UUIDString | None = None
    benchmark_version_id: UUIDString | None = None
    constituent_snapshot_id: UUIDString | None = None
    template_version: Literal["report_template_v1"] = "report_template_v1"

    @model_validator(mode="after")
    def bounded_period(self) -> Self:
        if not 0 <= (self.end_date - self.start_date).days <= 3660:
            raise ValueError("The report period exceeds its date bounds.")
        return self


class GenerateReportRequest(ReportSelection):
    ttl_days: ReportTTL = 7


class ExportSelection(ReportSchema):
    account_id: UUIDString
    start_date: CalendarDate
    end_date: CalendarDate
    source_cutoff_at: AwareInstant
    snapshot_id: UUIDString
    reporting_currency: CurrencyString
    dataset: ExportDataset
    field_set: ExportFieldSet
    format: ExportFormat
    target_version_id: UUIDString | None = None
    plan_revision_id: UUIDString | None = None
    benchmark_version_id: UUIDString | None = None
    constituent_snapshot_id: UUIDString | None = None

    @model_validator(mode="after")
    def bounded_period(self) -> Self:
        if not 0 <= (self.end_date - self.start_date).days <= 3660:
            raise ValueError("The export period exceeds its date bounds.")
        return self


class CreateExportRequest(ExportSelection):
    ttl_days: ReportTTL = 7


class McpGenerateReportRequest(ReportSchema):
    account_id: UUIDString
    idempotency_key: IdempotencyKey
    start_date: CalendarDate
    end_date: CalendarDate
    source_cutoff_at: AwareInstant
    snapshot_id: UUIDString
    reporting_currency: CurrencyString
    report_type: ReportType
    format: ReportFormat
    sections: ReportSections
    target_version_id: UUIDString | None = None
    plan_revision_id: UUIDString | None = None
    benchmark_version_id: UUIDString | None = None
    constituent_snapshot_id: UUIDString | None = None

    @model_validator(mode="after")
    def bounded_period(self) -> Self:
        if not 0 <= (self.end_date - self.start_date).days <= 3660:
            raise ValueError("The report period exceeds its date bounds.")
        return self


class ReportAccountQuery(ReportSchema):
    account_id: UUIDString


class ReportListQuery(ReportAccountQuery):
    cursor: Cursor | None = None
    limit: ReportPageLimit = 25
    state: ReportJobState | Literal["all"] = "all"
    report_type: ReportType | Literal["all"] = "all"
    start_date: CalendarDate | None = None
    end_date: CalendarDate | None = None
    sort: Literal["created_desc"] = "created_desc"

    @model_validator(mode="after")
    def paired_period(self) -> Self:
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("Both report history dates are required.")
        if (
            self.start_date is not None
            and self.end_date is not None
            and not 0 <= (self.end_date - self.start_date).days <= 3660
        ):
            raise ValueError("The report history period exceeds its date bounds.")
        return self


class ExportListQuery(ReportAccountQuery):
    cursor: Cursor | None = None
    limit: ReportPageLimit = 25
    state: ReportJobState | Literal["all"] = "all"
    dataset: ExportDataset | Literal["all"] = "all"
    sort: Literal["created_desc"] = "created_desc"


class EmptyReportRequest(ReportSchema):
    pass


class ReportNote(ReportSchema):
    key: ReportKey
    kind: Literal["warning", "assumption", "limitation", "unavailable_reason", "reconciliation"]
    family: ReportFamily
    code: ReportKey
    text: ReportText
    related_provenance_set_key: ReportKey | None


class ReportInputPin(ReportSchema):
    family: ReportFamily
    role: ReportInputRole
    subject_id: UUIDString
    content_digest: Digest
    parent_id: UUIDString | None
    method_key: ReportKey | None
    method_version: ReportKey | None


class ReportQualitySummary(ReportSchema):
    state: SourceQuality
    availability: SourceAvailability
    evaluated_at: AwareInstant
    warnings: Annotated[list[ReportNote], Field(max_length=64)]
    warning_count: ReportCount
    warning_omitted_count: ReportCount

    @model_validator(mode="after")
    def warning_counts(self) -> Self:
        if self.warning_count != len(self.warnings) + self.warning_omitted_count:
            raise ValueError("Report warning counts disagree.")
        return self


class ReportPinnedContext(ReportSchema):
    snapshot_id: UUIDString
    valuation_at: AwareInstant
    source_cutoff_at: AwareInstant
    reporting_currency: CurrencyString
    input_digest: Digest
    document_digest: Digest
    profile_version: Literal["report_sections_v1"]
    schema_version: Literal["1.0.0"]
    pins: Annotated[list[ReportInputPin], Field(max_length=256)]
    quality: ReportQualitySummary


class ReportArtifactMetadata(ReportSchema):
    artifact_id: UUIDString
    format: ReportFormat
    mime_type: ReportMimeType
    byte_length: Annotated[StrictInt, Field(ge=1, le=10 * 1024 * 1024)]
    content_digest: Digest
    expires_at: AwareInstant

    @model_validator(mode="after")
    def format_mime(self) -> Self:
        expected = {
            "pdf": "application/pdf",
            "csv": "text/csv; charset=utf-8",
            "json": "application/json",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        if expected[self.format] != self.mime_type:
            raise ValueError("Artifact format and MIME type disagree.")
        return self


class ReportJobStatus(ReportSchema):
    account_id: UUIDString
    context: ReportPinnedContext | None
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


class ExportJobStatus(ReportSchema):
    account_id: UUIDString
    context: ReportPinnedContext | None
    export_id: UUIDString
    state: ReportJobState
    requested_at: AwareInstant
    completed_at: AwareInstant | None
    expires_at: AwareInstant
    failure_code: ReportFailureCode | None
    dataset: ExportDataset
    field_set: ExportFieldSet
    format: ExportFormat
    manifest_digest: Digest | None
    artifacts: Annotated[list[ReportArtifactMetadata], Field(max_length=1)]

    @model_validator(mode="after")
    def atomic_result(self) -> Self:
        if self.state == "succeeded":
            if (
                self.manifest_digest is None
                or self.completed_at is None
                or self.failure_code is not None
                or len(self.artifacts) != 1
                or self.artifacts[0].format != self.format
            ):
                raise ValueError("A successful export requires its requested artifact.")
        elif self.state != "expired" and self.artifacts:
            raise ValueError("An incomplete export cannot expose artifacts.")
        if self.context is None and self.state not in {"expired", "cancelled"}:
            raise ValueError("An active export requires its immutable input context.")
        if any(item.expires_at > self.expires_at for item in self.artifacts):
            raise ValueError("An artifact cannot outlive its export.")
        return self


class ReportPage(ReportSchema):
    items: Annotated[list[ReportJobStatus], Field(max_length=100)]
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: ReportCount

    @model_validator(mode="after")
    def page_counts(self) -> Self:
        if len(self.items) > self.limit or len(self.items) > self.total:
            raise ValueError("The report page exceeds its declared bounds.")
        return self


class ExportPage(ReportSchema):
    items: Annotated[list[ExportJobStatus], Field(max_length=100)]
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: ReportCount

    @model_validator(mode="after")
    def page_counts(self) -> Self:
        if len(self.items) > self.limit or len(self.items) > self.total:
            raise ValueError("The export page exceeds its declared bounds.")
        return self


class ArtifactGrant(ReportSchema):
    artifact_id: UUIDString
    token: Annotated[ArtifactToken, Field(repr=False)]
    expires_at: AwareInstant


ReportSourceKind = Literal[
    "broker_source_record",
    "broker_source_occurrence",
    "ingestion_run",
    "portfolio_snapshot",
    "snapshot_position",
    "snapshot_cash",
    "calculation",
    "activity_revision",
    "activity_revision_evidence",
    "activity_coverage",
    "reconciliation",
    "target_version",
    "plan_revision",
    "historical_input",
    "historical_result",
    "xray_input",
    "xray_result",
    "price_snapshot",
    "fx_snapshot",
    "fx_observation",
    "fx_coverage_gap",
    "benchmark",
    "constituent_snapshot",
    "constituent_holding",
    "identity",
    "classification",
    "fund_mapping",
    "mapping",
    "taxonomy",
    "policy",
    "calendar",
    "license",
    "opening",
    "corporate_action",
    "source_coverage",
    "historical_evidence",
    "fund_definition",
    "price_observation",
    "reconciliation_discrepancy",
    "entity_evidence_version",
    "entity_evidence_reference",
    "relationship",
    "classification_snapshot",
    "classification_assignment",
    "historical_classification",
    "benchmark_version",
]
ReportTableKey = Literal[
    "alert_events",
    "alert_evaluations",
    "alert_observations",
    "alert_rule_versions",
    "alert_predicates",
    "alert_rule_destinations",
    "alert_acknowledgments",
    "alert_notifications",
    "alert_transitions",
    "alert_source_references",
    "alert_canonical_bindings",
    "alert_context_details",
    "alert_context_members",
    "alert_fx_conversions",
    "alert_fx_legs",
    "benchmark_composite",
    "benchmark_components",
    "benchmark_component_members",
    "benchmark_observations",
    "historical_options",
    "historical_warning_coverage",
    "xray_direct_positions",
    "xray_fund_entities",
    "xray_path_weights",
    "xray_members",
    "xray_policy",
    "xray_policy_components",
    "xray_policy_limits",
    "xray_taxonomies",
    "xray_threshold_policy",
    "plan_input_header",
    "plan_valuation",
    "plan_valuation_positions",
    "plan_valuation_cash",
    "plan_fx",
    "plan_options",
    "plan_input_members",
    "plan_listing_preferences",
    "plan_holding_constraints",
    "plan_allocation_constraints",
    "plan_node_identities",
    "plan_catalog_instruments",
    "plan_catalog_listings",
    "plan_source_details",
    "plan_effective_constraints",
    "snapshot_totals",
    "positions",
    "allocation_buckets",
    "target_nodes",
    "target_holdings",
    "target_constraints",
    "drift_rows",
    "drift_totals",
    "plan_summary",
    "plan_lines",
    "plan_objectives",
    "plan_relations",
    "performance_summary",
    "performance_points",
    "performance_periods",
    "benchmark_summary",
    "benchmark_points",
    "benchmark_periods",
    "income_summary",
    "income_components",
    "income_totals",
    "income_periods",
    "income_reporting_periods",
    "cash_flow_summary",
    "cash_flow_totals",
    "cash_flow_periods",
    "cash_flow_events",
    "attribution_summary",
    "attribution_components",
    "attribution_effects",
    "xray_summary",
    "xray_quality",
    "xray_dimensions",
    "xray_exposures",
    "xray_paths",
    "xray_held_funds",
    "xray_overlap_pairs",
    "xray_overlap_entities",
    "xray_concentrations",
    "xray_concentration_members",
    "xray_thresholds",
    "xray_residuals",
    "xray_path_relations",
    "reconciliation",
    "reconciliation_issues",
    "coverage",
    "notes",
    "activity",
    "historical_use_consumers",
    "historical_observation_uses",
    "historical_evidence_uses",
    "historical_missing_uses",
    "historical_use_candidates",
    "historical_conversion_uses",
    "historical_conversion_legs",
    "historical_event_memberships",
    "xray_selections",
    "xray_selection_evidence",
    "xray_source_uses",
    "xray_fund_edges",
    "xray_path_classifications",
    "xray_classification_decisions",
    "xray_classification_memberships",
    "dividends",
    "contexts",
    "source_references",
    "source_memberships",
    "note_memberships",
    "license_references",
    "coverage_facts",
    "bound_facts",
    "bindings",
    "reconciliation_bindings",
    "historical_source_details",
    "historical_source_parents",
    "historical_event_identities",
    "xray_valuation_roots",
    "xray_broker_fx",
    "xray_licensed_fx",
    "xray_fx_legs",
    "xray_dependency_identities",
    "target_exclusions",
    "historical_anchor_reconciliation",
    "historical_reconciliation_lines",
    "historical_reconciliation_anchors",
    "xray_reconciliation",
    "xray_warning_paths",
]
ReportDecimal = Annotated[
    str,
    StringConstraints(strict=True, max_length=4096, pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"),
]
ReportMetricOrigin = Literal[
    "observed_provider",
    "normalized_provider",
    "derived_deterministic",
    "estimated",
    "unavailable",
    "provider",
    "derived",
]
ReportConfidence = Annotated[
    str, StringConstraints(strict=True, pattern=r"^(?:0(?:\.[0-9]{1,18})?|1(?:\.0{1,18})?)$")
]
ReportDecimalRole = Literal["money", "quantity", "price", "fx", "ratio", "score", "residual"]


class ReportCellBase(ReportSchema):
    state: Literal["available", "partial", "unavailable", "failed", "not_applicable"]
    currency: CurrencyString | None = None
    context_key: ReportKey | None = None
    reason_key: ReportKey | None = None
    bound_key: ReportKey | None = None
    quality: SourceQuality | None = None
    origin: ReportMetricOrigin | None = None
    coverage_key: ReportKey | None = None
    confidence: ReportConfidence | None = None
    method_key: ReportKey | None = None
    method_version: ReportKey | None = None
    provenance_set_key: ReportKey | None = None
    note_set_key: ReportKey | None = None

    @model_validator(mode="after")
    def explicit_cell_state(self) -> Self:
        if (self.method_key is None) != (self.method_version is None):
            raise ValueError("A report cell methodology requires its version.")
        value = getattr(self, "value", None)
        unavailable = self.state in {"unavailable", "failed", "not_applicable"}
        if unavailable != (value is None):
            raise ValueError("The report cell value and availability disagree.")
        if self.state in {"unavailable", "failed"} and self.reason_key is None:
            raise ValueError("Unavailable report cells require a reason.")
        if getattr(self, "kind", None) != "decimal" and self.currency is not None:
            raise ValueError("Only decimal report cells may carry currency.")
        return self


class ReportTextCell(ReportCellBase):
    kind: Literal["text", "identifier", "enum"]
    value: ReportText | None
    decimal_role: None = None


class ReportDecimalCell(ReportCellBase):
    kind: Literal["decimal"]
    value: ReportDecimal | None
    decimal_role: ReportDecimalRole

    @model_validator(mode="after")
    def monetary_currency(self) -> Self:
        if self.decimal_role in {"money", "price"} and self.currency is None:
            raise ValueError("Monetary report cells require explicit currency.")
        return self


class ReportIntegerCell(ReportCellBase):
    kind: Literal["integer"]
    value: Annotated[StrictInt, Field(ge=-(2**63), le=2**63 - 1)] | None
    decimal_role: None = None


class ReportBooleanCell(ReportCellBase):
    kind: Literal["boolean"]
    value: StrictBool | None
    decimal_role: None = None


class ReportDateCell(ReportCellBase):
    kind: Literal["date"]
    value: CalendarDate | None
    decimal_role: None = None


class ReportInstantCell(ReportCellBase):
    kind: Literal["instant"]
    value: AwareInstant | None
    decimal_role: None = None


type ReportCell = Annotated[
    ReportTextCell
    | ReportDecimalCell
    | ReportIntegerCell
    | ReportBooleanCell
    | ReportDateCell
    | ReportInstantCell,
    Field(discriminator="kind"),
]


class ReportRow(ReportSchema):
    key: ReportKey
    context_key: ReportKey
    cells: Annotated[list[ReportCell], Field(min_length=1, max_length=64)]


class ReportTableDescriptor(ReportSchema):
    table: ReportTableKey
    schema_digest: Digest
    row_count: Annotated[StrictInt, Field(ge=0, le=100000)]
    content_digest: Digest
    section: ReportSection | None
    dataset: ExportDataset | None
    state: SourceAvailability
    reason_key: ReportKey | None


class ReportDocumentHeader(ReportSchema):
    selection: ReportSelection | ExportSelection
    owner_id: UUIDString
    valuation_at: AwareInstant
    context_digest: Digest
    tables: Annotated[list[ReportTableDescriptor], Field(max_length=128)]
    document_digest: Digest
    document_schema_version: Literal["1.0.0"]


class ReportRendererVersion(ReportSchema):
    format: ReportFormat
    name: ReportKey
    version: ReportKey


class ReportFontReference(ReportSchema):
    name: ReportText
    version: ReportKey
    content_digest: Digest
    license_digest: Digest


class ReportRendererProfile(ReportSchema):
    renderer_versions: Annotated[list[ReportRendererVersion], Field(min_length=1, max_length=4)]
    fonts: Annotated[list[ReportFontReference], Field(max_length=2)]
    profile_version: Literal["report_render_v1"]
    template_version: Literal["report_template_v1"]
    locale: Literal["en-GB"]
    timezone: Literal["UTC"]
    chart_order_version: Literal["report_chart_order_v1"]
    accessibility_profile_version: Literal["report_visual_accessibility_v1"]


class ReportContext(ReportSchema):
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
    schema_version: Literal["1.0.0"]


class ReportSourceReference(ReportSchema):
    key: ReportKey
    kind: ReportSourceKind
    subject_id: UUIDString
    content_digest: Digest
    parent_id: UUIDString | None
    source_at: AwareInstant | None
    first_observed_at: AwareInstant | None
    provider_id: UUIDString | None
    license_version_id: UUIDString | None
    mapping_version_id: UUIDString | None


class ReportSourceMembership(ReportSchema):
    provenance_set_key: ReportKey
    source_key: ReportKey


class ReportNoteMembership(ReportSchema):
    note_set_key: ReportKey
    note_key: ReportKey


class ReportLicenseReference(ReportSchema):
    version_id: UUIDString
    provider_id: UUIDString
    license_digest: Digest
    attribution: ReportText
    pinned_store: SourceLicensePermission
    pinned_display: SourceLicensePermission
    pinned_report: SourceLicensePermission
    pinned_export: SourceLicensePermission
    valid_from: AwareInstant
    expires_at: AwareInstant | None


class ReportCoverageFact(ReportSchema):
    set_key: ReportKey
    family: ReportFamily
    metric_key: ReportKey
    value: ReportCell


class ReportBoundFact(ReportSchema):
    key: ReportKey
    family: ReportFamily
    kind: Literal["exact", "lower_bound", "unavailable"]
    quantum: ReportDecimal | None
    rounding: ReportKey | None
    positive_below_quantum: StrictBool


class ReportReconciliationBinding(ReportSchema):
    key: ReportKey
    absent: StrictBool
    run_id: UUIDString | None
    content_digest: Digest | None

    @model_validator(mode="after")
    def explicit_absence(self) -> Self:
        if self.absent != (self.run_id is None) or self.absent != (self.content_digest is None):
            raise ValueError("Reconciliation absence and identity disagree.")
        return self


class ReportProofRelation(ReportSchema):
    table: ReportTableKey
    row: ReportRow


class ReportManifest(ReportSchema):
    document: ReportDocumentHeader
    renderer_profile: ReportRendererProfile
    bindings: Annotated[list[ReportInputPin], Field(max_length=256)]
    contexts: Annotated[list[ReportContext], Field(max_length=100000)]
    source_references: Annotated[list[ReportSourceReference], Field(max_length=100000)]
    source_memberships: Annotated[list[ReportSourceMembership], Field(max_length=100000)]
    note_memberships: Annotated[list[ReportNoteMembership], Field(max_length=100000)]
    license_references: Annotated[list[ReportLicenseReference], Field(max_length=100000)]
    coverage: Annotated[list[ReportCoverageFact], Field(max_length=100000)]
    bounds: Annotated[list[ReportBoundFact], Field(max_length=100000)]
    notes: Annotated[list[ReportNote], Field(max_length=100000)]
    proof_relations: Annotated[list[ReportProofRelation], Field(max_length=100000)]
    reconciliation: Annotated[list[ReportReconciliationBinding], Field(max_length=100000)]
    method: Literal["report_manifest_v1"]
    method_version: Literal["1.0.0"]
    escaping_version: Literal["report_csv_text_v1"]
