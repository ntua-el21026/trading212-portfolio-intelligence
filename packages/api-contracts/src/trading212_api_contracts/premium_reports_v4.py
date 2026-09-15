"""Explicit projection report DTOs; prior profiles stay separate and unchanged."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal, Self, get_args

from pydantic import AfterValidator, Field, StrictBool, StrictInt, model_validator

from . import premium_reports as v2
from . import premium_reports_v3 as v3
from . import reports as legacy
from .sources import CalendarDate, SourceAvailability, SourceQuality
from .targets import AwareInstant, CurrencyString, Cursor, Digest, UUIDString

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
ReportCell = legacy.ReportCell
ReportRow = legacy.ReportRow
ReportRendererProfile = legacy.ReportRendererProfile
ReportArtifactMetadata = legacy.ReportArtifactMetadata
ReportSourceMembership = legacy.ReportSourceMembership
ReportNoteMembership = legacy.ReportNoteMembership
ReportLicenseReference = legacy.ReportLicenseReference
ReportReconciliationBinding = legacy.ReportReconciliationBinding
ArtifactGrant = legacy.ArtifactGrant
EmptyReportRequest = legacy.EmptyReportRequest

PremiumReportProfile = Literal["report_sections_v2", "report_sections_v3", "report_sections_v4"]
ReportFamily = Literal[legacy.ReportFamily, "projection", "goal"]
ReportSection = Literal[legacy.ReportSection, "projection", "goal"]
ReportSourceKind = legacy.ReportSourceKind


class PremiumReportProfileQuery(ReportSchema):
    profile: PremiumReportProfile = "report_sections_v2"


class ProfiledReportAccountQuery(legacy.ReportAccountQuery):
    profile: PremiumReportProfile = "report_sections_v2"


class ProfiledReportListQuery(legacy.ReportListQuery):
    profile: PremiumReportProfile = "report_sections_v2"


def premium_report_profile_from_query(items: Sequence[tuple[str, str]]) -> PremiumReportProfile:
    values = [value for key, value in items if key == "profile"]
    if len(values) > 1:
        raise ValueError("A single explicit report profile is required.")
    value = values[0] if values else "report_sections_v2"
    if value == "report_sections_v2":
        return "report_sections_v2"
    if value == "report_sections_v3":
        return "report_sections_v3"
    if value == "report_sections_v4":
        return "report_sections_v4"
    raise ValueError("The report profile is unsupported.")


def _unique_sections(values: list[ReportSection]) -> list[ReportSection]:
    if len(values) != len(set(values)):
        raise ValueError("Repeated report selectors are not permitted.")
    return values


ReportSections = Annotated[
    list[ReportSection], Field(min_length=1, max_length=15), AfterValidator(_unique_sections)
]


class PremiumReportProjectionRunSelectionV4(ReportSchema):
    run_id: UUIDString
    family: Literal["projection"]


class PremiumReportSelectionV4(ReportSchema):
    account_id: UUIDString
    start_date: CalendarDate
    end_date: CalendarDate
    source_cutoff_at: AwareInstant
    snapshot_id: UUIDString
    reporting_currency: CurrencyString
    report_type: ReportType
    sections: ReportSections
    formats: ReportFormats
    premium_run: PremiumReportProjectionRunSelectionV4
    target_version_id: UUIDString | None = None
    plan_revision_id: UUIDString | None = None
    benchmark_version_id: UUIDString | None = None
    constituent_snapshot_id: UUIDString | None = None
    xray_run_id: UUIDString | None = None
    template_version: Literal["report_template_v1"] = "report_template_v1"
    profile_version: Literal["report_sections_v4"]

    @model_validator(mode="after")
    def bounded_selection(self) -> Self:
        if not 0 <= (self.end_date - self.start_date).days <= 3660:
            raise ValueError("The report period exceeds its date bounds.")
        selected = set(self.sections)
        if "projection" not in selected:
            raise ValueError("Exactly one implemented premium section is required.")
        if not set(v2._REQUIRED_SECTIONS[self.report_type]) <= selected:
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
        v2._calendar_period(self.report_type, self.start_date, self.end_date)
        return self


class GeneratePremiumReportRequestV4(PremiumReportSelectionV4):
    ttl_days: ReportTTL = 7


class PremiumReportProjectionVersionBindingV4(ReportSchema):
    aggregate_id: UUIDString
    version_id: UUIDString
    version_number: Annotated[StrictInt, Field(ge=1, le=512)]
    predecessor_id: UUIDString | None
    name: Annotated[str, Field(min_length=1, max_length=120)]
    description: Annotated[str, Field(max_length=1024)]
    content_digest: Digest
    created_at: AwareInstant

    @model_validator(mode="after")
    def version_chain(self) -> Self:
        if not self.name.strip() or (self.version_number == 1) != (self.predecessor_id is None):
            raise ValueError("The immutable version metadata differs.")
        return self


class PremiumReportProjectionObservedBindingV4(ReportSchema):
    snapshot_id: UUIDString
    snapshot_digest: Digest
    valuation_at: AwareInstant


class PremiumReportContextSnapshotBindingV4(ReportSchema):
    snapshot_id: UUIDString
    snapshot_digest: Digest
    valuation_at: AwareInstant
    source_cutoff_at: AwareInstant


class PremiumReportProjectionRunBindingV4(ReportSchema):
    root_id: UUIDString
    run_id: UUIDString
    input_id: UUIDString
    result_id: UUIDString
    capture_digest: Digest
    numerical_input_digest: Digest
    result_digest: Digest
    owner_id: UUIDString
    account_id: UUIDString
    reporting_currency: CurrencyString
    assumption: PremiumReportProjectionVersionBindingV4
    goal: PremiumReportProjectionVersionBindingV4 | None
    initial_kind: Literal["modeled_value", "observed_snapshot"]
    observed: PremiumReportProjectionObservedBindingV4 | None
    anchor_date: CalendarDate
    terminal_date: CalendarDate
    months: Annotated[StrictInt, Field(ge=1, le=600)]
    path_count: Annotated[StrictInt, Field(ge=1, le=4096)]
    retained_point_count: Annotated[StrictInt, Field(ge=2, le=121)]
    variant_count: Annotated[StrictInt, Field(ge=1, le=3)]
    asset_count: Annotated[StrictInt, Field(ge=1, le=12)]
    source_count: Annotated[StrictInt, Field(ge=0, le=257)]
    source_cutoff_at: AwareInstant | None
    created_at: AwareInstant
    calculated_at: AwareInstant
    completed_at: AwareInstant
    expires_at: AwareInstant
    report_context: PremiumReportContextSnapshotBindingV4
    family: Literal["projection"]
    state: Literal["succeeded"]

    @model_validator(mode="after")
    def actual_retained_basis(self) -> Self:
        if (
            self.variant_count not in (1, 3)
            or self.root_id != self.run_id
            or not self.created_at <= self.calculated_at <= self.completed_at < self.expires_at
        ):
            raise ValueError("The succeeded retained projection lifetime differs.")
        if self.assumption.created_at > self.created_at or (
            self.goal is not None and self.goal.created_at > self.created_at
        ):
            raise ValueError("Pinned definitions postdate the run.")
        if (self.initial_kind == "observed_snapshot") != (
            self.observed is not None
        ) or self.anchor_date >= self.terminal_date:
            raise ValueError("The original model basis is incomplete.")
        if self.observed is not None and self.observed.valuation_at.date() != self.anchor_date:
            raise ValueError("The observed anchor differs from the original valuation.")
        return self


ProjectionReportTableKey = Literal[
    "projection_basis_v1",
    "projection_definitions_v1",
    "projection_assumptions_v1",
    "projection_assets_v1",
    "projection_correlations_v1",
    "projection_calendar_v1",
    "projection_schedule_v1",
    "projection_sensitivity_v1",
    "projection_variants_v1",
    "projection_paths_v1",
    "projection_points_v1",
    "projection_point_assets_v1",
    "projection_distributions_v1",
    "projection_quantiles_v1",
    "projection_histograms_v1",
    "projection_histogram_bins_v1",
    "projection_goal_state_v1",
    "projection_goal_definition_v1",
    "projection_goal_results_v1",
    "projection_members_v1",
    "projection_source_headers_v1",
    "projection_source_nodes_v1",
    "projection_source_members_v1",
    "projection_source_scalars_v1",
]
ReportTableKey = Literal[legacy.ReportTableKey, ProjectionReportTableKey]


class PremiumReportNoteV4(ReportSchema):
    key: ReportKey
    kind: Literal["warning", "assumption", "limitation", "unavailable_reason", "reconciliation"]
    family: ReportFamily
    code: ReportKey
    text: ReportText
    related_provenance_set_key: ReportKey | None


class PremiumReportInputPinV4(ReportSchema):
    family: ReportFamily
    role: ReportInputRole
    subject_id: UUIDString
    content_digest: Digest
    parent_id: UUIDString | None
    method_key: ReportKey | None
    method_version: ReportKey | None


class PremiumReportQualitySummaryV4(ReportSchema):
    state: SourceQuality
    availability: SourceAvailability
    evaluated_at: AwareInstant
    warnings: Annotated[list[PremiumReportNoteV4], Field(max_length=64)]
    warning_count: ReportCount
    warning_omitted_count: ReportCount

    @model_validator(mode="after")
    def warning_counts(self) -> Self:
        if self.warning_count != len(self.warnings) + self.warning_omitted_count:
            raise ValueError("Report warning counts disagree.")
        return self


class PremiumReportPinnedContextV4(ReportSchema):
    snapshot_id: UUIDString
    valuation_at: AwareInstant
    source_cutoff_at: AwareInstant
    reporting_currency: CurrencyString
    input_digest: Digest
    document_digest: Digest
    profile_version: Literal["report_sections_v4"]
    schema_version: Literal["4.0.0"]
    pins: Annotated[list[PremiumReportInputPinV4], Field(max_length=256)]
    quality: PremiumReportQualitySummaryV4


class PremiumReportJobStatusV4(ReportSchema):
    profile_version: Literal["report_sections_v4"]
    account_id: UUIDString
    context: PremiumReportPinnedContextV4 | None
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


class PremiumReportPageV4(ReportSchema):
    profile_version: Literal["report_sections_v4"]
    items: Annotated[list[PremiumReportJobStatusV4], Field(max_length=100)]
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: ReportCount

    @model_validator(mode="after")
    def page_counts(self) -> Self:
        if len(self.items) > self.limit or len(self.items) > self.total:
            raise ValueError("The report page exceeds its declared bounds.")
        return self


class PremiumReportTableDescriptorV4(ReportSchema):
    table: ReportTableKey
    schema_digest: Digest
    row_count: Annotated[StrictInt, Field(ge=0, le=100000)]
    content_digest: Digest
    section: ReportSection | None
    dataset: None
    state: SourceAvailability
    reason_key: ReportKey | None


class PremiumReportDocumentHeaderV4(ReportSchema):
    selection: PremiumReportSelectionV4
    owner_id: UUIDString
    valuation_at: AwareInstant
    context_digest: Digest
    tables: Annotated[list[PremiumReportTableDescriptorV4], Field(max_length=128)]
    document_digest: Digest
    premium_binding: PremiumReportProjectionRunBindingV4
    document_schema_version: Literal["4.0.0"]

    @model_validator(mode="after")
    def selected_retained_basis(self) -> Self:
        selected, pin = self.selection, self.premium_binding
        context = pin.report_context
        if (
            selected.premium_run.run_id != pin.run_id
            or selected.account_id != pin.account_id
            or self.owner_id != pin.owner_id
            or selected.reporting_currency != pin.reporting_currency
            or selected.snapshot_id != context.snapshot_id
            or selected.source_cutoff_at != context.source_cutoff_at
            or self.valuation_at != context.valuation_at
            or ("goal" in selected.sections and pin.goal is None)
        ):
            raise ValueError("The projection and independent report context differ.")
        supplied = {item.table for item in self.tables}
        if (
            len(supplied) != len(self.tables)
            or not set(get_args(ProjectionReportTableKey)) <= supplied
        ):
            raise ValueError("Every complete projection table descriptor is required.")
        if any(
            item.section is not None and item.section not in selected.sections
            for item in self.tables
        ):
            raise ValueError("The table section differs from selection.")
        counts = {
            "projection_basis_v1": 1,
            "projection_assumptions_v1": 1,
            "projection_goal_state_v1": 1,
            "projection_definitions_v1": 1 + int(pin.goal is not None),
            "projection_assets_v1": pin.asset_count,
            "projection_correlations_v1": pin.asset_count**2,
            "projection_calendar_v1": pin.months + 1,
            "projection_sensitivity_v1": int(pin.variant_count == 3),
            "projection_variants_v1": pin.variant_count,
            "projection_paths_v1": pin.variant_count * pin.path_count,
            "projection_points_v1": pin.variant_count * pin.path_count * pin.retained_point_count,
            "projection_point_assets_v1": pin.variant_count
            * pin.path_count
            * pin.retained_point_count
            * pin.asset_count,
            "projection_distributions_v1": pin.variant_count * pin.retained_point_count,
            "projection_quantiles_v1": pin.variant_count
            * (10 * pin.retained_point_count + 5 * int(pin.goal is not None)),
            "projection_histograms_v1": pin.variant_count * 2,
            "projection_goal_definition_v1": int(pin.goal is not None),
            "projection_goal_results_v1": pin.variant_count if pin.goal is not None else 0,
            "projection_source_headers_v1": pin.source_count,
        }
        if any(
            item.table in counts and item.row_count != counts[item.table] for item in self.tables
        ):
            raise ValueError("The complete saved projection cardinalities differ.")
        return self


class PremiumReportContextV4(ReportSchema):
    key: ReportKey
    family: ReportFamily
    method_key: ReportKey
    method_version: ReportKey
    valuation_at: AwareInstant | None
    source_cutoff_at: AwareInstant | None
    quality: SourceQuality
    provenance_set_key: ReportKey
    coverage_set_key: ReportKey
    note_set_key: ReportKey
    source_at: AwareInstant | None
    reconciliation_key: ReportKey | None
    schema_version: Literal["4.0.0"]

    @model_validator(mode="after")
    def original_clocks(self) -> Self:
        if self.family not in {"projection", "goal"} and (
            self.valuation_at is None or self.source_cutoff_at is None
        ):
            raise ValueError("Ordinary report context requires its actual clocks.")
        if self.family in {"projection", "goal"} and self.quality in {"fresh", "stale"}:
            raise ValueError("Projection quality must retain modeled uncertainty.")
        return self


class PremiumReportCoverageFactV4(ReportSchema):
    set_key: ReportKey
    family: ReportFamily
    metric_key: ReportKey
    value: ReportCell


class PremiumReportBoundFactV4(ReportSchema):
    key: ReportKey
    family: ReportFamily
    kind: Literal["exact", "lower_bound", "unavailable"]
    quantum: legacy.ReportDecimal | None
    rounding: ReportKey | None
    positive_below_quantum: StrictBool


class PremiumReportProofRelationV4(ReportSchema):
    table: ReportTableKey
    row: ReportRow


class PremiumReportSourceReferenceV4(ReportSchema):
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


class PremiumReportManifestV4(ReportSchema):
    document: PremiumReportDocumentHeaderV4
    renderer_profile: ReportRendererProfile
    bindings: Annotated[list[PremiumReportInputPinV4], Field(max_length=256)]
    contexts: Annotated[list[PremiumReportContextV4], Field(max_length=256)]
    source_references: Annotated[list[PremiumReportSourceReferenceV4], Field(max_length=100000)]
    source_memberships: Annotated[list[ReportSourceMembership], Field(max_length=100000)]
    note_memberships: Annotated[list[ReportNoteMembership], Field(max_length=100000)]
    license_references: Annotated[list[ReportLicenseReference], Field(max_length=256)]
    coverage: Annotated[list[PremiumReportCoverageFactV4], Field(max_length=100000)]
    bounds: Annotated[list[PremiumReportBoundFactV4], Field(max_length=100000)]
    notes: Annotated[list[PremiumReportNoteV4], Field(max_length=100000)]
    proof_relations: Annotated[list[PremiumReportProofRelationV4], Field(max_length=100000)]
    reconciliation: Annotated[list[ReportReconciliationBinding], Field(max_length=100000)]
    method: Literal["report_manifest_v1"]
    method_version: Literal["1.0.0"]
    escaping_version: Literal["report_csv_text_v1"]

    @model_validator(mode="after")
    def selected_complete_proof(self) -> Self:
        pin = self.document.premium_binding
        contexts = [item for item in self.contexts if item.family == "projection"]
        goals = [item for item in self.contexts if item.family == "goal"]
        valuation = None if pin.observed is None else pin.observed.valuation_at
        if not contexts or bool(goals) != (pin.goal is not None):
            raise ValueError("The complete projection and goal contexts are required.")
        if any(
            item.valuation_at != valuation
            or item.source_cutoff_at != pin.source_cutoff_at
            or item.method_key != ("goal_analysis_v1" if item.family == "goal" else "projection_v1")
            or item.method_version != "1.0.0"
            for item in (*contexts, *goals)
        ):
            raise ValueError("Original projection clocks and methods differ.")
        required = {
            ("projection", "input", pin.run_id, pin.capture_digest, None),
            ("projection", "result", pin.result_id, pin.result_digest, pin.run_id),
            (
                "projection",
                "policy",
                pin.assumption.version_id,
                pin.assumption.content_digest,
                pin.assumption.aggregate_id,
            ),
            (
                "snapshot",
                "snapshot",
                pin.report_context.snapshot_id,
                pin.report_context.snapshot_digest,
                None,
            ),
        }
        if pin.goal is not None:
            required.add(
                (
                    "goal",
                    "policy",
                    pin.goal.version_id,
                    pin.goal.content_digest,
                    pin.goal.aggregate_id,
                )
            )
        actual = {
            (item.family, item.role, item.subject_id, item.content_digest, item.parent_id)
            for item in self.bindings
        }
        if (
            len({(item.family, item.role, item.subject_id) for item in self.bindings})
            != len(self.bindings)
            or not required <= actual
        ):
            raise ValueError("Immutable projection bindings are incomplete or duplicated.")
        if {item for item in actual if item[0] in {"projection", "goal"}} != {
            item for item in required if item[0] in {"projection", "goal"}
        }:
            raise ValueError("A foreign projection or goal entered the report proof.")
        return self


# Composition aliases do not alter the old classes or their serialization.
GeneratePremiumReportRequestV3 = v3.GeneratePremiumReportRequestV3
PremiumReportRiskRunSelectionV3 = v3.PremiumReportRiskRunSelectionV3
PremiumReportJobStatusV3 = v3.PremiumReportJobStatusV3
PremiumReportPageV3 = v3.PremiumReportPageV3
PremiumReportManifestV3 = v3.PremiumReportManifestV3
GeneratePremiumReportRequest = (
    v2.GeneratePremiumReportRequest
    | v3.GeneratePremiumReportRequestV3
    | GeneratePremiumReportRequestV4
)
PremiumReportJobStatus = (
    v2.PremiumReportJobStatus | v3.PremiumReportJobStatusV3 | PremiumReportJobStatusV4
)
PremiumReportPage = v2.PremiumReportPage | v3.PremiumReportPageV3 | PremiumReportPageV4
PremiumReportManifest = (
    v2.PremiumReportManifest | v3.PremiumReportManifestV3 | PremiumReportManifestV4
)


def validate_premium_request_profile(
    profile: PremiumReportProfile, value: GeneratePremiumReportRequest
) -> None:
    expected = {
        "report_sections_v2": v2.GeneratePremiumReportRequest,
        "report_sections_v3": v3.GeneratePremiumReportRequestV3,
        "report_sections_v4": GeneratePremiumReportRequestV4,
    }
    if profile not in expected or type(value) is not expected[profile]:
        raise ValueError("The explicit report profile and request differ.")
