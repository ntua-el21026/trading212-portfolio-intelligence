"""Explicit projection document profile; prior report context types remain unchanged."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime
from uuid import UUID

from . import reports as r
from .enums import QualityState
from .errors import fail_validation
from .values import CurrencyCode

REPORT_V4_SCHEMA_VERSION = "4.0.0"
REPORT_V4_PROFILE_VERSION = "report_sections_v4"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportProjectionRunSelection(r.ReportRecord):
    run_id: UUID
    family: r.ReportFamily = r.ReportFamily.PROJECTION

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        if self.family is not r.ReportFamily.PROJECTION:
            fail_validation("Profile four requires an actual projection run.", field="family")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportSelectionV4(r.ReportRecord):
    account_id: UUID
    start_date: date
    end_date: date
    source_cutoff_at: datetime
    snapshot_id: UUID
    reporting_currency: CurrencyCode
    report_type: r.ReportType
    sections: tuple[r.ReportSection, ...]
    formats: tuple[r.ReportFormat, ...]
    premium_run: ReportProjectionRunSelection
    target_version_id: UUID | None = None
    plan_revision_id: UUID | None = None
    benchmark_version_id: UUID | None = None
    constituent_snapshot_id: UUID | None = None
    xray_run_id: UUID | None = None
    template_version: str = r.REPORT_TEMPLATE_VERSION
    profile_version: str = REPORT_V4_PROFILE_VERSION

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        if self.profile_version != REPORT_V4_PROFILE_VERSION or (
            r.ReportSection.PROJECTION not in self.sections
            or set(self.sections)
            & {r.ReportSection.RISK, r.ReportSection.SCENARIO, r.ReportSection.RESEARCH}
            or len(set(self.sections)) != len(self.sections)
        ):
            fail_validation("An explicit projection section/profile is required.", field="sections")
        base = report_base_selection_v4(self)
        r.report_limit(len(self.sections) <= 15, "sections")
        object.__setattr__(
            self,
            "sections",
            tuple(section for section in r.ReportSection if section in self.sections),
        )
        object.__setattr__(self, "formats", base.formats)


def report_base_selection_v4(value: ReportSelectionV4) -> r.ReportSelection:
    return r.ReportSelection(
        account_id=value.account_id,
        start_date=value.start_date,
        end_date=value.end_date,
        source_cutoff_at=value.source_cutoff_at,
        snapshot_id=value.snapshot_id,
        reporting_currency=value.reporting_currency,
        report_type=value.report_type,
        sections=tuple(
            section
            for section in value.sections
            if section not in {r.ReportSection.PROJECTION, r.ReportSection.GOAL}
        ),
        formats=value.formats,
        target_version_id=value.target_version_id,
        plan_revision_id=value.plan_revision_id,
        benchmark_version_id=value.benchmark_version_id,
        constituent_snapshot_id=value.constituent_snapshot_id,
        xray_run_id=value.xray_run_id,
        template_version=value.template_version,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportContextV4(r.ReportRecord):
    key: str
    family: r.ReportFamily
    method_key: str
    method_version: str
    valuation_at: datetime | None
    source_cutoff_at: datetime | None
    quality: QualityState
    provenance_set_key: str
    coverage_set_key: str
    note_set_key: str
    source_at: datetime | None = None
    reconciliation_key: str | None = None
    schema_version: str = REPORT_V4_SCHEMA_VERSION

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        if self.schema_version != REPORT_V4_SCHEMA_VERSION or self.family in {
            r.ReportFamily.RISK,
            r.ReportFamily.SCENARIO,
            r.ReportFamily.RESEARCH,
        }:
            fail_validation("Unsupported profile-four context.", field="schema_version")
        if self.family not in {r.ReportFamily.PROJECTION, r.ReportFamily.GOAL} and (
            self.valuation_at is None or self.source_cutoff_at is None
        ):
            fail_validation(
                "Ordinary report context requires its actual clocks.", field="valuation_at"
            )
        if self.family in {r.ReportFamily.PROJECTION, r.ReportFamily.GOAL} and self.quality in {
            QualityState.FRESH,
            QualityState.STALE,
        }:
            fail_validation("Projection results retain modeled quality.", field="quality")


def promote_report_context_v4(value: r.ReportContext) -> ReportContextV4:
    """Restamp an ordinary context without changing its source clocks or method."""
    return ReportContextV4(
        key=value.key,
        family=value.family,
        method_key=value.method_key,
        method_version=value.method_version,
        valuation_at=value.valuation_at,
        source_cutoff_at=value.source_cutoff_at,
        quality=value.quality,
        provenance_set_key=value.provenance_set_key,
        coverage_set_key=value.coverage_set_key,
        note_set_key=value.note_set_key,
        source_at=value.source_at,
        reconciliation_key=value.reconciliation_key,
    )


def report_tables_v4(selection: ReportSelectionV4) -> tuple[r.ReportTableKey, ...]:
    from .report_projection_schema import PROJECTION_TABLE_COLUMNS
    from .report_schema import report_tables

    selected = set(report_tables(report_base_selection_v4(selection))) | set(
        PROJECTION_TABLE_COLUMNS
    )
    return tuple(table for table in r.ReportTableKey if table in selected)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportProjectionVersionBinding(r.ReportRecord):
    aggregate_id: UUID
    version_id: UUID
    version_number: int
    predecessor_id: UUID | None
    name: str
    description: str
    content_digest: str
    created_at: datetime

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        if (
            not 1 <= self.version_number <= 512
            or (self.version_number == 1) != (self.predecessor_id is None)
            or not self.name.strip()
            or len(self.name) > 120
            or len(self.description) > 1024
        ):
            fail_validation(
                "Projection immutable definition metadata differs.", field="version_number"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportProjectionObservedBinding(r.ReportRecord):
    snapshot_id: UUID
    snapshot_digest: str
    valuation_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportContextSnapshotBinding(r.ReportRecord):
    snapshot_id: UUID
    snapshot_digest: str
    valuation_at: datetime
    source_cutoff_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportProjectionRunBinding(r.ReportRecord):
    root_id: UUID
    run_id: UUID
    input_id: UUID
    result_id: UUID
    capture_digest: str
    numerical_input_digest: str
    result_digest: str
    owner_id: UUID
    account_id: UUID
    reporting_currency: CurrencyCode
    assumption: ReportProjectionVersionBinding
    goal: ReportProjectionVersionBinding | None
    initial_kind: str
    observed: ReportProjectionObservedBinding | None
    anchor_date: date
    terminal_date: date
    months: int
    path_count: int
    retained_point_count: int
    variant_count: int
    asset_count: int
    source_count: int
    source_cutoff_at: datetime | None
    created_at: datetime
    calculated_at: datetime
    completed_at: datetime
    expires_at: datetime
    report_context: ReportContextSnapshotBinding
    family: r.ReportFamily = r.ReportFamily.PROJECTION
    state: r.ReportJobState = r.ReportJobState.SUCCEEDED

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        if (
            self.root_id != self.run_id
            or self.family is not r.ReportFamily.PROJECTION
            or self.state is not r.ReportJobState.SUCCEEDED
            or not self.created_at <= self.calculated_at <= self.completed_at < self.expires_at
        ):
            fail_validation(
                "A succeeded retained projection run is required.", field="premium_binding"
            )
        if self.assumption.created_at > self.created_at or (
            self.goal is not None and self.goal.created_at > self.created_at
        ):
            fail_validation("Pinned definitions postdate the run.", field="premium_binding")
        if (
            self.initial_kind not in {"modeled_value", "observed_snapshot"}
            or (self.initial_kind == "observed_snapshot") != (self.observed is not None)
            or self.anchor_date >= self.terminal_date
        ):
            fail_validation("Projection initial basis is incomplete.", field="initial_kind")
        if not (
            1 <= self.months <= 600
            and 1 <= self.path_count <= 4096
            and 2 <= self.retained_point_count <= 121
            and self.variant_count in (1, 3)
            and 1 <= self.asset_count <= 12
            and 0 <= self.source_count <= 257
        ):
            fail_validation("Projection cardinality bounds differ.", field="premium_binding")
        if self.observed is not None and self.observed.valuation_at.date() != self.anchor_date:
            fail_validation("Observed anchor differs from original valuation.", field="anchor_date")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportDocumentHeaderV4(r.ReportRecord):
    selection: ReportSelectionV4
    owner_id: UUID
    valuation_at: datetime
    context_digest: str
    tables: tuple[r.ReportTableDescriptor, ...]
    document_digest: str
    premium_binding: ReportProjectionRunBinding
    document_schema_version: str = REPORT_V4_SCHEMA_VERSION

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        from .report_risk_schema import RISK_PROOF_TABLES, RISK_REPORT_TABLES
        from .report_scenario_schema import SCENARIO_PROOF_TABLES, SCENARIO_REPORT_TABLES

        selected, pin = self.selection, self.premium_binding
        context = pin.report_context
        if self.document_schema_version != REPORT_V4_SCHEMA_VERSION or (
            selected.premium_run.run_id != pin.run_id
            or self.owner_id != pin.owner_id
            or selected.account_id != pin.account_id
            or selected.reporting_currency != pin.reporting_currency
            or selected.snapshot_id != context.snapshot_id
            or selected.source_cutoff_at != context.source_cutoff_at
            or self.valuation_at != context.valuation_at
            or (r.ReportSection.GOAL in selected.sections and pin.goal is None)
        ):
            fail_validation("Projection/report-context identities differ.", field="premium_binding")
        supplied = {table.table for table in self.tables}
        r.report_limit(len(self.tables) <= 128, "tables")
        if (
            len(supplied) != len(self.tables)
            or supplied != set(report_tables_v4(selected))
            or supplied
            & set(
                (
                    *RISK_REPORT_TABLES,
                    *RISK_PROOF_TABLES,
                    *SCENARIO_REPORT_TABLES,
                    *SCENARIO_PROOF_TABLES,
                )
            )
        ):
            fail_validation("Profile-four tables are incomplete or foreign.", field="tables")
        if any(
            table.dataset is not None
            or (table.section is not None and table.section not in selected.sections)
            for table in self.tables
        ):
            fail_validation("Report table section differs.", field="tables")
        for key in (
            r.ReportTableKey.PROJECTION_BASIS_V1,
            r.ReportTableKey.PROJECTION_ASSUMPTIONS_V1,
            r.ReportTableKey.PROJECTION_GOAL_STATE_V1,
        ):
            if next(table.row_count for table in self.tables if table.table is key) != 1:
                fail_validation("Projection canonical basis is incomplete.", field="tables")
        expected = {
            r.ReportTableKey.PROJECTION_DEFINITIONS_V1: 1 + int(pin.goal is not None),
            r.ReportTableKey.PROJECTION_ASSETS_V1: pin.asset_count,
            r.ReportTableKey.PROJECTION_CORRELATIONS_V1: pin.asset_count * pin.asset_count,
            r.ReportTableKey.PROJECTION_CALENDAR_V1: pin.months + 1,
            r.ReportTableKey.PROJECTION_SENSITIVITY_V1: int(pin.variant_count == 3),
            r.ReportTableKey.PROJECTION_VARIANTS_V1: pin.variant_count,
            r.ReportTableKey.PROJECTION_PATHS_V1: pin.variant_count * pin.path_count,
            r.ReportTableKey.PROJECTION_POINTS_V1: pin.variant_count
            * pin.path_count
            * pin.retained_point_count,
            r.ReportTableKey.PROJECTION_POINT_ASSETS_V1: pin.variant_count
            * pin.path_count
            * pin.retained_point_count
            * pin.asset_count,
            r.ReportTableKey.PROJECTION_DISTRIBUTIONS_V1: pin.variant_count
            * pin.retained_point_count,
            r.ReportTableKey.PROJECTION_QUANTILES_V1: pin.variant_count
            * (10 * pin.retained_point_count + 5 * int(pin.goal is not None)),
            r.ReportTableKey.PROJECTION_HISTOGRAMS_V1: pin.variant_count * 2,
            r.ReportTableKey.PROJECTION_GOAL_DEFINITION_V1: int(pin.goal is not None),
            r.ReportTableKey.PROJECTION_GOAL_RESULTS_V1: pin.variant_count
            if pin.goal is not None
            else 0,
            r.ReportTableKey.PROJECTION_SOURCE_HEADERS_V1: pin.source_count,
        }
        if any(
            table.row_count != expected[table.table]
            for table in self.tables
            if table.table in expected
        ):
            fail_validation("Complete projection cardinalities differ.", field="tables")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportProofV4(r.ReportRecord):
    contexts: tuple[ReportContextV4, ...] = ()
    source_references: tuple[r.ReportSourceReference, ...] = ()
    source_memberships: tuple[r.ReportSourceMembership, ...] = ()
    note_memberships: tuple[r.ReportNoteMembership, ...] = ()
    license_references: tuple[r.ReportLicenseReference, ...] = ()
    coverage: tuple[r.ReportCoverageFact, ...] = ()
    bounds: tuple[r.ReportBoundFact, ...] = ()
    notes: tuple[r.ReportNote, ...] = ()
    proof_relations: tuple[r.ReportProofRelation, ...] = ()
    reconciliation: tuple[r.ReportReconciliationBinding, ...] = ()

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        # Reuse sorting of unchanged proof members, without constructing old contexts.
        ordinary = r.ReportProof(
            **{
                field.name: getattr(self, field.name)
                for field in fields(r.ReportProof)
                if field.name != "contexts"
            }
        )
        for field in fields(r.ReportProof):
            if field.name != "contexts":
                object.__setattr__(self, field.name, getattr(ordinary, field.name))
        object.__setattr__(
            self,
            "contexts",
            tuple(sorted(self.contexts, key=lambda context: (context.family.value, context.key))),
        )


def validate_report_profile_v4(
    header: ReportDocumentHeaderV4, proof: ReportProofV4, bindings: tuple[r.ReportBinding, ...]
) -> None:
    r.report_limit(len(proof.contexts) <= 256, "contexts")
    r.report_limit(len(proof.license_references) <= 256, "license_references")
    from .report_risk_schema import RISK_PROOF_TABLES, RISK_REPORT_TABLES
    from .report_scenario_schema import SCENARIO_PROOF_TABLES, SCENARIO_REPORT_TABLES

    foreign_tables = set(
        (*RISK_PROOF_TABLES, *RISK_REPORT_TABLES, *SCENARIO_PROOF_TABLES, *SCENARIO_REPORT_TABLES)
    )
    if any(item.table in foreign_tables for item in proof.proof_relations):
        fail_validation("Foreign premium table in projection proof.", field="proof_relations")
    pin = header.premium_binding
    forbidden = {r.ReportFamily.RISK, r.ReportFamily.SCENARIO, r.ReportFamily.RESEARCH}
    if any(
        item.family in forbidden
        for group in (proof.contexts, proof.coverage, proof.bounds, proof.notes, bindings)
        for item in group
    ):
        fail_validation("Unselected premium family in projection report.", field="family")
    contexts = tuple(item for item in proof.contexts if item.family is r.ReportFamily.PROJECTION)
    if not contexts or any(
        item.method_key != "projection_v1"
        or item.method_version != "1.0.0"
        or item.valuation_at != (None if pin.observed is None else pin.observed.valuation_at)
        or item.source_cutoff_at != pin.source_cutoff_at
        for item in contexts
    ):
        fail_validation("Original projection clocks differ.", field="contexts")
    goals = tuple(item for item in proof.contexts if item.family is r.ReportFamily.GOAL)
    if (
        (goals and pin.goal is None)
        or (pin.goal is not None and not goals)
        or any(
            item.method_key != "goal_analysis_v1"
            or item.method_version != "1.0.0"
            or item.valuation_at != (None if pin.observed is None else pin.observed.valuation_at)
            or item.source_cutoff_at != pin.source_cutoff_at
            for item in goals
        )
    ):
        fail_validation("Goal proof and original clocks differ.", field="contexts")
    required = {
        (r.ReportFamily.PROJECTION, r.ReportInputRole.INPUT, pin.run_id, pin.capture_digest, None),
        (
            r.ReportFamily.PROJECTION,
            r.ReportInputRole.RESULT,
            pin.result_id,
            pin.result_digest,
            pin.run_id,
        ),
        (
            r.ReportFamily.PROJECTION,
            r.ReportInputRole.POLICY,
            pin.assumption.version_id,
            pin.assumption.content_digest,
            pin.assumption.aggregate_id,
        ),
        (
            r.ReportFamily.SNAPSHOT,
            r.ReportInputRole.SNAPSHOT,
            pin.report_context.snapshot_id,
            pin.report_context.snapshot_digest,
            None,
        ),
    }
    if pin.goal is not None:
        required.add(
            (
                r.ReportFamily.GOAL,
                r.ReportInputRole.POLICY,
                pin.goal.version_id,
                pin.goal.content_digest,
                pin.goal.aggregate_id,
            )
        )
    actual = {
        (item.family, item.role, item.subject_id, item.content_digest, item.parent_id)
        for item in bindings
    }
    if not required <= actual or {
        item for item in actual if item[0] in {r.ReportFamily.PROJECTION, r.ReportFamily.GOAL}
    } != {item for item in required if item[0] in {r.ReportFamily.PROJECTION, r.ReportFamily.GOAL}}:
        fail_validation("Projection immutable proof is incomplete or foreign.", field="bindings")
    if any(item.kind in r.SCENARIO_REPORT_SOURCE_KINDS for item in proof.source_references):
        fail_validation("Foreign premium source in projection report.", field="sources")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportCaptureSummaryV4(r.ReportRecord):
    header: ReportDocumentHeaderV4
    canonical_byte_length: int
    chunk_count: int
    immutable_bindings: tuple[r.ReportBinding, ...]
    proof: ReportProofV4
    proof_digest: str
    renderer_profile: r.ReportRendererProfile
    copy_expires_at: datetime | None = None

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        r.report_limit(
            0 <= self.canonical_byte_length <= r.MAX_REPORT_DOCUMENT_BYTES, "canonical_byte_length"
        )
        r.report_limit(0 <= self.chunk_count <= r.MAX_REPORT_DATASET_ROWS, "chunk_count")
        if (
            self.copy_expires_at is None
            or self.copy_expires_at > self.header.premium_binding.expires_at
        ):
            fail_validation(
                "Projection report requires a bounded copy lifetime.", field="copy_expires_at"
            )
        validate_report_profile_v4(self.header, self.proof, self.immutable_bindings)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportManifestV4(r.ReportRecord):
    document: ReportDocumentHeaderV4
    renderer_profile: r.ReportRendererProfile
    bindings: tuple[r.ReportBinding, ...]
    contexts: tuple[ReportContextV4, ...] = ()
    source_references: tuple[r.ReportSourceReference, ...] = ()
    source_memberships: tuple[r.ReportSourceMembership, ...] = ()
    note_memberships: tuple[r.ReportNoteMembership, ...] = ()
    license_references: tuple[r.ReportLicenseReference, ...] = ()
    coverage: tuple[r.ReportCoverageFact, ...] = ()
    bounds: tuple[r.ReportBoundFact, ...] = ()
    notes: tuple[r.ReportNote, ...] = ()
    proof_relations: tuple[r.ReportProofRelation, ...] = ()
    reconciliation: tuple[r.ReportReconciliationBinding, ...] = ()
    method: str = r.REPORT_METHOD
    method_version: str = r.REPORT_METHOD_VERSION
    escaping_version: str = "report_csv_text_v1"

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        if (self.method, self.method_version, self.escaping_version) != (
            r.REPORT_METHOD,
            r.REPORT_METHOD_VERSION,
            "report_csv_text_v1",
        ):
            fail_validation("Report manifest version is unsupported.", field="method_version")
        proof = ReportProofV4(**{x.name: getattr(self, x.name) for x in fields(ReportProofV4)})
        validate_report_profile_v4(self.document, proof, self.bindings)
        for item in fields(ReportProofV4):
            object.__setattr__(self, item.name, getattr(proof, item.name))
        object.__setattr__(
            self,
            "bindings",
            tuple(
                sorted(
                    self.bindings,
                    key=lambda x: (
                        x.family.value,
                        x.role.value,
                        str(x.subject_id),
                        x.content_digest,
                    ),
                )
            ),
        )
