"""Explicit premium profile-three DTOs; profile two remains an unchanged module."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal, Self, get_args

from pydantic import AfterValidator, Field, StrictBool, StrictInt, model_validator

from . import premium_reports as v2
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

PremiumReportProfile = Literal["report_sections_v2", "report_sections_v3"]
PremiumReportFamilyV3 = Literal[v2.ReportFamily, "scenario", "projection", "goal", "research"]
ReportFamily = Literal[v2.ReportFamily, "scenario"]
ReportSection = Literal[v2.ReportSection, "scenario", "projection", "goal", "research"]
ReportSourceKind = Literal[
    legacy.ReportSourceKind,
    "scenario_run",
    "scenario_result",
    "scenario_version",
    "scenario_sensitivity_version",
    "scenario_sensitivity_observation",
    "scenario_sensitivity_evidence",
]


class PremiumReportProfileQuery(ReportSchema):
    profile: PremiumReportProfile = "report_sections_v2"


class ProfiledReportAccountQuery(legacy.ReportAccountQuery):
    profile: PremiumReportProfile = "report_sections_v2"


class ProfiledReportListQuery(legacy.ReportListQuery):
    profile: PremiumReportProfile = "report_sections_v2"


def premium_report_profile_from_query(items: Sequence[tuple[str, str]]) -> PremiumReportProfile:
    """Read actual query multi-items; never collapse duplicate profile selectors."""
    values = [value for key, value in items if key == "profile"]
    if len(values) > 1:
        raise ValueError("A single explicit report profile is required.")
    if not values or values[0] == "report_sections_v2":
        return "report_sections_v2"
    if values[0] == "report_sections_v3":
        return "report_sections_v3"
    raise ValueError("The report profile is unsupported.")


def _unique_sections(values: list[ReportSection]) -> list[ReportSection]:
    if len(values) != len(set(values)):
        raise ValueError("Repeated report selectors are not permitted.")
    return values


ReportSections = Annotated[
    list[ReportSection], Field(min_length=1, max_length=14), AfterValidator(_unique_sections)
]


class PremiumReportRiskRunSelectionV3(ReportSchema):
    run_id: UUIDString
    family: Literal["risk"]


class PremiumReportScenarioRunSelectionV3(ReportSchema):
    run_id: UUIDString
    family: Literal["scenario"]


PremiumReportRunSelectionV3 = Annotated[
    PremiumReportRiskRunSelectionV3 | PremiumReportScenarioRunSelectionV3,
    Field(discriminator="family"),
]


class PremiumReportSelectionV3(ReportSchema):
    account_id: UUIDString
    start_date: CalendarDate
    end_date: CalendarDate
    source_cutoff_at: AwareInstant
    snapshot_id: UUIDString
    reporting_currency: CurrencyString
    report_type: ReportType
    sections: ReportSections
    formats: ReportFormats
    premium_run: PremiumReportRunSelectionV3
    target_version_id: UUIDString | None = None
    plan_revision_id: UUIDString | None = None
    benchmark_version_id: UUIDString | None = None
    constituent_snapshot_id: UUIDString | None = None
    xray_run_id: UUIDString | None = None
    template_version: Literal["report_template_v1"] = "report_template_v1"
    profile_version: Literal["report_sections_v3"]

    @model_validator(mode="after")
    def bounded_selection(self) -> Self:
        if not 0 <= (self.end_date - self.start_date).days <= 3660:
            raise ValueError("The report period exceeds its date bounds.")
        selected = set(self.sections)
        if selected & {"risk", "scenario", "projection", "goal", "research"} != {
            self.premium_run.family
        }:
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
        if "xray_run_id" in self.model_fields_set and self.xray_run_id is None:
            raise ValueError("An absent optional run pin must be omitted.")
        v2._calendar_period(self.report_type, self.start_date, self.end_date)
        return self


class GeneratePremiumReportRequestV3(PremiumReportSelectionV3):
    ttl_days: ReportTTL = 7


def validate_premium_request_profile(
    profile: PremiumReportProfile,
    value: v2.GeneratePremiumReportRequest | GeneratePremiumReportRequestV3,
) -> None:
    if profile not in ("report_sections_v2", "report_sections_v3"):
        raise ValueError("The report profile is unsupported.")
    if (profile == "report_sections_v2" and type(value) is not v2.GeneratePremiumReportRequest) or (
        profile == "report_sections_v3" and type(value) is not GeneratePremiumReportRequestV3
    ):
        raise ValueError("The explicit report profile and request differ.")


class PremiumReportXrayRunBindingV3(ReportSchema):
    run_id: UUIDString
    input_id: UUIDString
    input_digest: Digest
    result_digest: Digest


class PremiumReportHistoricalInputBindingV3(ReportSchema):
    input_snapshot_id: UUIDString
    input_digest: Digest


class _PremiumRunBindingV3(ReportSchema):
    run_id: UUIDString
    result_id: UUIDString
    input_digest: Digest
    result_digest: Digest
    owner_id: UUIDString
    account_id: UUIDString
    snapshot_id: UUIDString
    snapshot_digest: Digest
    reporting_currency: CurrencyString
    source_cutoff_at: AwareInstant
    valuation_at: AwareInstant
    created_at: AwareInstant
    completed_at: AwareInstant
    expires_at: AwareInstant
    state: Literal["succeeded"]

    @model_validator(mode="after")
    def completed_retained_lifetime(self) -> Self:
        if not self.created_at <= self.completed_at < self.expires_at:
            raise ValueError("The succeeded retained run lifetime is invalid.")
        return self


class PremiumReportRiskRunBindingV3(_PremiumRunBindingV3):
    definition_id: UUIDString
    definition_version_id: UUIDString
    definition_digest: Digest
    start_date: CalendarDate
    end_date: CalendarDate
    historical: PremiumReportHistoricalInputBindingV3
    xray: PremiumReportXrayRunBindingV3 | None = None
    benchmark_version_id: UUIDString | None = None
    family: Literal["risk"]

    @model_validator(mode="after")
    def risk_window(self) -> Self:
        if not 0 <= (self.end_date - self.start_date).days <= 3660:
            raise ValueError("The retained risk window is invalid.")
        if any(
            name in self.model_fields_set and getattr(self, name) is None
            for name in ("xray", "benchmark_version_id")
        ):
            raise ValueError("An absent optional retained pin must be omitted.")
        return self


class PremiumReportScenarioRunBindingV3(_PremiumRunBindingV3):
    scenario_id: UUIDString
    scenario_version_id: UUIDString
    scenario_version_digest: Digest
    xray: PremiumReportXrayRunBindingV3
    historical: PremiumReportHistoricalInputBindingV3 | None = None
    family: Literal["scenario"]

    @model_validator(mode="after")
    def omitted_history(self) -> Self:
        if "historical" in self.model_fields_set and self.historical is None:
            raise ValueError("An absent historical pin must be omitted.")
        return self


PremiumReportRunBindingV3 = Annotated[
    PremiumReportRiskRunBindingV3 | PremiumReportScenarioRunBindingV3,
    Field(discriminator="family"),
]

ScenarioReportTableKey = Literal[
    "scenario_basis_v1",
    "scenario_definition_v1",
    "scenario_shocks_v1",
    "scenario_exclusions_v1",
    "scenario_summary_v1",
    "scenario_components_v1",
    "scenario_channels_v1",
    "scenario_applied_sensitivities_v1",
    "scenario_diagnostics_v1",
    "scenario_replay_changes_v1",
    "scenario_subjects_v1",
    "scenario_classifications_v1",
    "scenario_currencies_v1",
    "scenario_members_v1",
    "scenario_sensitivity_versions_v1",
    "scenario_drivers_v1",
    "scenario_sensitivity_observations_v1",
    "scenario_sensitivity_memberships_v1",
    "scenario_sensitivity_evidence_v1",
    "scenario_source_licenses_v1",
    "scenario_replay_basis_v1",
    "scenario_replay_bindings_v1",
    "scenario_replay_methods_v1",
    "scenario_replay_coverage_v1",
    "scenario_replay_warnings_v1",
    "scenario_xray_paths_v1",
    "scenario_source_headers_v1",
]
ReportTableKey = Literal[v2.ReportTableKey, ScenarioReportTableKey]


class PremiumReportNoteV3(ReportSchema):
    key: ReportKey
    kind: Literal["warning", "assumption", "limitation", "unavailable_reason", "reconciliation"]
    family: ReportFamily
    code: ReportKey
    text: ReportText
    related_provenance_set_key: ReportKey | None


class PremiumReportInputPinV3(ReportSchema):
    family: ReportFamily
    role: ReportInputRole
    subject_id: UUIDString
    content_digest: Digest
    parent_id: UUIDString | None
    method_key: ReportKey | None
    method_version: ReportKey | None


class PremiumReportQualitySummaryV3(ReportSchema):
    state: SourceQuality
    availability: SourceAvailability
    evaluated_at: AwareInstant
    warnings: Annotated[list[PremiumReportNoteV3], Field(max_length=64)]
    warning_count: ReportCount
    warning_omitted_count: ReportCount

    @model_validator(mode="after")
    def warning_counts(self) -> Self:
        if self.warning_count != len(self.warnings) + self.warning_omitted_count:
            raise ValueError("Report warning counts disagree.")
        return self


class PremiumReportPinnedContextV3(ReportSchema):
    snapshot_id: UUIDString
    valuation_at: AwareInstant
    source_cutoff_at: AwareInstant
    reporting_currency: CurrencyString
    input_digest: Digest
    document_digest: Digest
    profile_version: Literal["report_sections_v3"]
    schema_version: Literal["3.0.0"]
    pins: Annotated[list[PremiumReportInputPinV3], Field(max_length=256)]
    quality: PremiumReportQualitySummaryV3


class PremiumReportJobStatusV3(ReportSchema):
    profile_version: Literal["report_sections_v3"]
    account_id: UUIDString
    context: PremiumReportPinnedContextV3 | None
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


class PremiumReportPageV3(ReportSchema):
    profile_version: Literal["report_sections_v3"]
    items: Annotated[list[PremiumReportJobStatusV3], Field(max_length=100)]
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: ReportCount

    @model_validator(mode="after")
    def page_counts(self) -> Self:
        if len(self.items) > self.limit or len(self.items) > self.total:
            raise ValueError("The report page exceeds its declared bounds.")
        return self


class PremiumReportTableDescriptorV3(ReportSchema):
    table: ReportTableKey
    schema_digest: Digest
    row_count: Annotated[StrictInt, Field(ge=0, le=100000)]
    content_digest: Digest
    section: ReportSection | None
    dataset: None
    state: SourceAvailability
    reason_key: ReportKey | None


class PremiumReportDocumentHeaderV3(ReportSchema):
    selection: PremiumReportSelectionV3
    owner_id: UUIDString
    valuation_at: AwareInstant
    context_digest: Digest
    tables: Annotated[list[PremiumReportTableDescriptorV3], Field(max_length=128)]
    document_digest: Digest
    document_schema_version: Literal["3.0.0"]
    premium_binding: PremiumReportRunBindingV3

    @model_validator(mode="after")
    def selected_retained_basis(self) -> Self:
        selected, pin = self.selection, self.premium_binding
        if (
            (selected.premium_run.family, selected.premium_run.run_id) != (pin.family, pin.run_id)
            or selected.account_id != pin.account_id
            or self.owner_id != pin.owner_id
            or selected.snapshot_id != pin.snapshot_id
            or selected.reporting_currency != pin.reporting_currency
            or selected.source_cutoff_at != pin.source_cutoff_at
            or self.valuation_at != pin.valuation_at
        ):
            raise ValueError("The selected retained run and monetary basis differ.")
        if isinstance(pin, PremiumReportRiskRunBindingV3) and (
            selected.start_date,
            selected.end_date,
        ) != (pin.start_date, pin.end_date):
            raise ValueError("The retained risk window differs.")
        risk = frozenset(get_args(v2.RiskReportTableKey))
        scenario = frozenset(get_args(ScenarioReportTableKey))
        required, forbidden = (risk, scenario) if pin.family == "risk" else (scenario, risk)
        supplied = {item.table for item in self.tables}
        if len(supplied) != len(self.tables) or not required <= supplied or supplied & forbidden:
            raise ValueError("The complete selected premium table inventory differs.")
        if any(
            item.section is not None and item.section not in selected.sections
            for item in self.tables
        ):
            raise ValueError("The table section differs from selection.")
        if pin.family == "scenario" and any(
            item.row_count != 1
            for item in self.tables
            if item.table in {"scenario_basis_v1", "scenario_definition_v1", "scenario_summary_v1"}
        ):
            raise ValueError("Scenario basis, definition and summary must be complete.")
        return self


class PremiumReportContextV3(ReportSchema):
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
    schema_version: Literal["3.0.0"]


class PremiumReportCoverageFactV3(ReportSchema):
    set_key: ReportKey
    family: ReportFamily
    metric_key: ReportKey
    value: ReportCell


class PremiumReportBoundFactV3(ReportSchema):
    key: ReportKey
    family: ReportFamily
    kind: Literal["exact", "lower_bound", "unavailable"]
    quantum: legacy.ReportDecimal | None
    rounding: ReportKey | None
    positive_below_quantum: StrictBool


class PremiumReportProofRelationV3(ReportSchema):
    table: ReportTableKey
    row: ReportRow


class PremiumReportSourceReferenceV3(ReportSchema):
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


class PremiumReportManifestV3(ReportSchema):
    document: PremiumReportDocumentHeaderV3
    renderer_profile: ReportRendererProfile
    bindings: Annotated[list[PremiumReportInputPinV3], Field(max_length=256)]
    contexts: Annotated[list[PremiumReportContextV3], Field(max_length=256)]
    source_references: Annotated[list[PremiumReportSourceReferenceV3], Field(max_length=100000)]
    source_memberships: Annotated[list[ReportSourceMembership], Field(max_length=100000)]
    note_memberships: Annotated[list[ReportNoteMembership], Field(max_length=100000)]
    license_references: Annotated[list[ReportLicenseReference], Field(max_length=256)]
    coverage: Annotated[list[PremiumReportCoverageFactV3], Field(max_length=100000)]
    bounds: Annotated[list[PremiumReportBoundFactV3], Field(max_length=100000)]
    notes: Annotated[list[PremiumReportNoteV3], Field(max_length=100000)]
    proof_relations: Annotated[list[PremiumReportProofRelationV3], Field(max_length=100000)]
    reconciliation: Annotated[list[ReportReconciliationBinding], Field(max_length=100000)]
    method: Literal["report_manifest_v1"]
    method_version: Literal["1.0.0"]
    escaping_version: Literal["report_csv_text_v1"]

    @model_validator(mode="after")
    def selected_complete_proof(self) -> Self:
        pin = self.document.premium_binding
        other = "scenario" if pin.family == "risk" else "risk"
        groups = (self.contexts, self.coverage, self.bounds, self.notes, self.bindings)
        if any(item.family == other for group in groups for item in group) or not any(
            item.family == pin.family for item in self.contexts
        ):
            raise ValueError("The report proof family differs from its selected run.")
        forbidden = frozenset(
            get_args(ScenarioReportTableKey)
            if pin.family == "risk"
            else get_args(v2.RiskReportTableKey)
        )
        if any(item.table in forbidden for item in self.proof_relations):
            raise ValueError("The proof table family differs from selection.")
        if pin.family == "risk" and any(
            item.kind.startswith("scenario_") for item in self.source_references
        ):
            raise ValueError("Risk reports cannot contain scenario source references.")
        required = {
            (pin.family, "input", pin.run_id, pin.input_digest, None),
            (pin.family, "result", pin.result_id, pin.result_digest, pin.run_id),
            ("snapshot", "snapshot", pin.snapshot_id, pin.snapshot_digest, None),
        }
        if isinstance(pin, PremiumReportRiskRunBindingV3):
            required.add(
                (
                    pin.family,
                    "policy",
                    pin.definition_version_id,
                    pin.definition_digest,
                    pin.definition_id,
                )
            )
        else:
            required.add(
                (
                    pin.family,
                    "policy",
                    pin.scenario_version_id,
                    pin.scenario_version_digest,
                    pin.scenario_id,
                )
            )
        if pin.xray is not None:
            required.add(("xray", "input", pin.xray.input_id, pin.xray.input_digest, None))
            required.add(("xray", "result", pin.xray.run_id, pin.xray.result_digest, None))
        if pin.historical is not None:
            required.add(
                (
                    "performance",
                    "input",
                    pin.historical.input_snapshot_id,
                    pin.historical.input_digest,
                    None,
                )
            )
        actual = {
            (x.family, x.role, x.subject_id, x.content_digest, x.parent_id) for x in self.bindings
        }
        identities = {(x.family, x.role, x.subject_id) for x in self.bindings}
        if len(identities) != len(self.bindings) or not required <= actual:
            raise ValueError("The selected retained run proof is incomplete or duplicated.")
        if {x for x in actual if x[0] == pin.family} != {x for x in required if x[0] == pin.family}:
            raise ValueError("The proof contains an unrelated premium run.")
        return self


GeneratePremiumReportRequest = v2.GeneratePremiumReportRequest | GeneratePremiumReportRequestV3
PremiumReportJobStatus = v2.PremiumReportJobStatus | PremiumReportJobStatusV3
PremiumReportPage = v2.PremiumReportPage | PremiumReportPageV3
PremiumReportManifest = v2.PremiumReportManifest | PremiumReportManifestV3
