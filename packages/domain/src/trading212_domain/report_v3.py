"""Explicit profile-three selections and actual retained premium-run bindings.

Cells, rows, proof records, table semantics and renderer versions remain shared.
Only the selected-run contract and its document wrappers differ from profiles one/two.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime
from typing import TypeIs
from uuid import UUID

from . import report_v4 as v4
from . import reports as r
from .errors import fail_validation
from .values import CurrencyCode

REPORT_V3_SCHEMA_VERSION = "3.0.0"
REPORT_V3_PROFILE_VERSION = "report_sections_v3"
SUPPORTED_PREMIUM_FAMILIES = frozenset({r.ReportFamily.RISK, r.ReportFamily.SCENARIO})
RESERVED_PREMIUM_FAMILIES = frozenset(
    {r.ReportFamily.PROJECTION, r.ReportFamily.GOAL, r.ReportFamily.RESEARCH}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportRiskRunSelection(r.ReportRecord):
    run_id: UUID
    family: r.ReportFamily = r.ReportFamily.RISK

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        if self.family is not r.ReportFamily.RISK:
            fail_validation("Risk run selection family differs.", field="family")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportScenarioRunSelection(r.ReportRecord):
    run_id: UUID
    family: r.ReportFamily = r.ReportFamily.SCENARIO

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        if self.family is not r.ReportFamily.SCENARIO:
            fail_validation("Scenario run selection family differs.", field="family")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportSelectionV3(r.ReportRecord):
    account_id: UUID
    start_date: date
    end_date: date
    source_cutoff_at: datetime
    snapshot_id: UUID
    reporting_currency: CurrencyCode
    report_type: r.ReportType
    sections: tuple[r.ReportSection, ...]
    formats: tuple[r.ReportFormat, ...]
    premium_run: ReportRiskRunSelection | ReportScenarioRunSelection
    target_version_id: UUID | None = None
    plan_revision_id: UUID | None = None
    benchmark_version_id: UUID | None = None
    constituent_snapshot_id: UUID | None = None
    xray_run_id: UUID | None = None
    template_version: str = r.REPORT_TEMPLATE_VERSION
    profile_version: str = REPORT_V3_PROFILE_VERSION

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        if self.profile_version != REPORT_V3_PROFILE_VERSION:
            fail_validation("The explicit report profile differs.", field="profile_version")
        chosen = r.ReportSection(self.premium_run.family.value)
        premium = set(self.sections) & {
            r.ReportSection.RISK,
            r.ReportSection.SCENARIO,
            r.ReportSection.PROJECTION,
            r.ReportSection.GOAL,
            r.ReportSection.RESEARCH,
        }
        if premium != {chosen} or len(set(self.sections)) != len(self.sections):
            fail_validation(
                "Exactly one implemented premium section is required.", field="sections"
            )
        # Reuse every legacy period/reference/required-section rule without a fake risk pin.
        base = report_base_selection(self)
        r.report_limit(len(self.sections) <= 14, "sections")
        object.__setattr__(
            self, "sections", tuple(x for x in r.ReportSection if x in self.sections)
        )
        object.__setattr__(self, "formats", base.formats)


def report_base_selection(selection: ReportSelectionV3) -> r.ReportSelection:
    """Validate/project only ordinary sections; never invent a premium identifier."""
    return r.ReportSelection(
        account_id=selection.account_id,
        start_date=selection.start_date,
        end_date=selection.end_date,
        source_cutoff_at=selection.source_cutoff_at,
        snapshot_id=selection.snapshot_id,
        reporting_currency=selection.reporting_currency,
        report_type=selection.report_type,
        sections=tuple(
            x
            for x in selection.sections
            if x
            not in {
                r.ReportSection.RISK,
                r.ReportSection.SCENARIO,
                r.ReportSection.PROJECTION,
                r.ReportSection.GOAL,
                r.ReportSection.RESEARCH,
            }
        ),
        formats=selection.formats,
        target_version_id=selection.target_version_id,
        plan_revision_id=selection.plan_revision_id,
        benchmark_version_id=selection.benchmark_version_id,
        constituent_snapshot_id=selection.constituent_snapshot_id,
        xray_run_id=selection.xray_run_id,
        template_version=selection.template_version,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportXrayRunBinding(r.ReportRecord):
    run_id: UUID
    input_id: UUID
    input_digest: str
    result_digest: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportHistoricalInputBinding(r.ReportRecord):
    input_snapshot_id: UUID
    input_digest: str


@dataclass(frozen=True, slots=True, kw_only=True)
class _RunBinding(r.ReportRecord):
    run_id: UUID
    result_id: UUID
    input_digest: str
    result_digest: str
    owner_id: UUID
    account_id: UUID
    snapshot_id: UUID
    snapshot_digest: str
    reporting_currency: CurrencyCode
    source_cutoff_at: datetime
    valuation_at: datetime
    created_at: datetime
    completed_at: datetime
    expires_at: datetime
    state: r.ReportJobState = r.ReportJobState.SUCCEEDED

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        if self.state is not r.ReportJobState.SUCCEEDED or not (
            self.created_at <= self.completed_at < self.expires_at
        ):
            fail_validation(
                "A succeeded retained premium run is required.", field="premium_binding"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportRiskRunBinding(_RunBinding):
    definition_id: UUID
    definition_version_id: UUID
    definition_digest: str
    start_date: date
    end_date: date
    historical: ReportHistoricalInputBinding
    xray: ReportXrayRunBinding | None = None
    benchmark_version_id: UUID | None = None
    family: r.ReportFamily = r.ReportFamily.RISK

    def __post_init__(self) -> None:
        _RunBinding.__post_init__(self)
        if self.family is not r.ReportFamily.RISK:
            fail_validation("Risk run binding family differs.", field="family")
        r._selection_window(self.start_date, self.end_date)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportScenarioRunBinding(_RunBinding):
    scenario_id: UUID
    scenario_version_id: UUID
    scenario_version_digest: str
    xray: ReportXrayRunBinding
    historical: ReportHistoricalInputBinding | None = None
    family: r.ReportFamily = r.ReportFamily.SCENARIO

    def __post_init__(self) -> None:
        _RunBinding.__post_init__(self)
        if self.family is not r.ReportFamily.SCENARIO:
            fail_validation("Scenario run binding family differs.", field="family")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportDocumentHeaderV3(r.ReportRecord):
    selection: ReportSelectionV3
    owner_id: UUID
    valuation_at: datetime
    context_digest: str
    tables: tuple[r.ReportTableDescriptor, ...]
    document_digest: str
    premium_binding: ReportRiskRunBinding | ReportScenarioRunBinding
    document_schema_version: str = REPORT_V3_SCHEMA_VERSION

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        from .report_risk_schema import RISK_PROOF_TABLES, RISK_REPORT_TABLES
        from .report_scenario_schema import SCENARIO_PROOF_TABLES, SCENARIO_REPORT_TABLES

        selected, binding = self.selection, self.premium_binding
        if self.document_schema_version != REPORT_V3_SCHEMA_VERSION:
            fail_validation("Report document profile differs.", field="document_schema_version")
        if (
            (selected.premium_run.family, selected.premium_run.run_id)
            != (binding.family, binding.run_id)
            or selected.account_id != binding.account_id
            or self.owner_id != binding.owner_id
            or selected.snapshot_id != binding.snapshot_id
            or selected.reporting_currency != binding.reporting_currency
            or selected.source_cutoff_at != binding.source_cutoff_at
            or self.valuation_at != binding.valuation_at
        ):
            fail_validation(
                "Report retained run and monetary basis differ.", field="premium_binding"
            )
        if isinstance(binding, ReportRiskRunBinding) and (
            selected.start_date,
            selected.end_date,
        ) != (binding.start_date, binding.end_date):
            fail_validation("The selected risk history window differs.", field="premium_binding")
        r.report_limit(len(self.tables) <= 128, "tables")
        supplied = {x.table for x in self.tables}
        from .report_projection_schema import PROJECTION_TABLE_COLUMNS

        if supplied & set(PROJECTION_TABLE_COLUMNS):
            fail_validation("Projection tables require profile four.", field="tables")
        if len(supplied) != len(self.tables):
            fail_validation("Report document tables are duplicated.", field="tables")
        risk = frozenset((*RISK_REPORT_TABLES, *RISK_PROOF_TABLES))
        scenario = frozenset((*SCENARIO_REPORT_TABLES, *SCENARIO_PROOF_TABLES))
        required, forbidden = (
            (risk, scenario) if binding.family is r.ReportFamily.RISK else (scenario, risk)
        )
        if not required <= supplied or supplied & forbidden:
            fail_validation("Report selected premium tables differ.", field="tables")
        if any(
            x.dataset is not None or (x.section is not None and x.section not in selected.sections)
            for x in self.tables
        ):
            fail_validation("Report table section differs from selection.", field="tables")
        if binding.family is r.ReportFamily.SCENARIO:
            singleton = {
                r.ReportTableKey.SCENARIO_BASIS_V1,
                r.ReportTableKey.SCENARIO_DEFINITION_V1,
                r.ReportTableKey.SCENARIO_SUMMARY_V1,
            }
            if any(x.row_count != 1 for x in self.tables if x.table in singleton):
                fail_validation(
                    "A scenario report requires its canonical basis and summary.", field="tables"
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportCaptureSummaryV3(r.ReportRecord):
    header: ReportDocumentHeaderV3
    canonical_byte_length: int
    chunk_count: int
    immutable_bindings: tuple[r.ReportBinding, ...]
    proof: r.ReportProof
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
                "Premium copies require a bounded retained lifetime.", field="copy_expires_at"
            )
        validate_report_profile_v3(self.header, self.proof, self.immutable_bindings)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportManifestV3(r.ReportRecord):
    document: ReportDocumentHeaderV3
    renderer_profile: r.ReportRendererProfile
    bindings: tuple[r.ReportBinding, ...]
    contexts: tuple[r.ReportContext, ...] = ()
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
        proof = r.ReportProof(**{x.name: getattr(self, x.name) for x in fields(r.ReportProof)})
        validate_report_profile_v3(self.document, proof, self.bindings)
        for item in fields(r.ReportProof):
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


def validate_report_profile_v3(
    header: ReportDocumentHeaderV3, proof: r.ReportProof, bindings: tuple[r.ReportBinding, ...]
) -> None:
    """Resolve the singular typed run into the shared immutable proof graph."""
    from .report_projection_schema import PROJECTION_TABLE_COLUMNS
    from .report_risk_schema import RISK_PROOF_TABLES, RISK_REPORT_TABLES
    from .report_scenario_schema import SCENARIO_PROOF_TABLES, SCENARIO_REPORT_TABLES

    if any(item.table in PROJECTION_TABLE_COLUMNS for item in proof.proof_relations):
        fail_validation("Projection proof requires profile four.", field="proof_relations")
    r.report_limit(len(proof.contexts) <= 256, "contexts")
    r.report_limit(len(proof.license_references) <= 256, "license_references")
    pin = header.premium_binding
    other = r.ReportFamily.SCENARIO if pin.family is r.ReportFamily.RISK else r.ReportFamily.RISK
    forbidden = RESERVED_PREMIUM_FAMILIES | {other}
    families = tuple(
        x.family
        for group in (proof.contexts, proof.coverage, proof.bounds, proof.notes, bindings)
        for x in group
    )
    if any(x in forbidden for x in families) or not any(
        x.family is pin.family for x in proof.contexts
    ):
        fail_validation("Report proof family differs from its selected run.", field="family")
    if any(x.schema_version != REPORT_V3_SCHEMA_VERSION for x in proof.contexts):
        fail_validation("Report context and document profiles differ.", field="schema_version")
    if pin.family is r.ReportFamily.RISK:
        disallowed_tables = frozenset((*SCENARIO_REPORT_TABLES, *SCENARIO_PROOF_TABLES))
        if any(x.kind in r.SCENARIO_REPORT_SOURCE_KINDS for x in proof.source_references):
            fail_validation(
                "Risk report cannot contain scenario sources.", field="source_references"
            )
    else:
        disallowed_tables = frozenset((*RISK_REPORT_TABLES, *RISK_PROOF_TABLES))
    if any(x.table in disallowed_tables for x in proof.proof_relations):
        fail_validation("Report proof tables differ from selected family.", field="proof_relations")
    required = {
        (pin.family, r.ReportInputRole.INPUT, pin.run_id, pin.input_digest, None),
        (pin.family, r.ReportInputRole.RESULT, pin.result_id, pin.result_digest, pin.run_id),
        (
            r.ReportFamily.SNAPSHOT,
            r.ReportInputRole.SNAPSHOT,
            pin.snapshot_id,
            pin.snapshot_digest,
            None,
        ),
    }
    if isinstance(pin, ReportRiskRunBinding):
        required.add(
            (
                pin.family,
                r.ReportInputRole.POLICY,
                pin.definition_version_id,
                pin.definition_digest,
                pin.definition_id,
            )
        )
    else:
        required.add(
            (
                pin.family,
                r.ReportInputRole.POLICY,
                pin.scenario_version_id,
                pin.scenario_version_digest,
                pin.scenario_id,
            )
        )
    if pin.historical is not None:
        required.add(
            (
                r.ReportFamily.PERFORMANCE,
                r.ReportInputRole.INPUT,
                pin.historical.input_snapshot_id,
                pin.historical.input_digest,
                None,
            )
        )
    if pin.xray is not None:
        required.add(
            (
                r.ReportFamily.XRAY,
                r.ReportInputRole.INPUT,
                pin.xray.input_id,
                pin.xray.input_digest,
                None,
            )
        )
        required.add(
            (
                r.ReportFamily.XRAY,
                r.ReportInputRole.RESULT,
                pin.xray.run_id,
                pin.xray.result_digest,
                None,
            )
        )
    actual = {(x.family, x.role, x.subject_id, x.content_digest, x.parent_id) for x in bindings}
    if not required <= actual:
        fail_validation("The selected premium run proof is incomplete.", field="bindings")
    premium_actual = {x for x in actual if x[0] is pin.family}
    if premium_actual != {x for x in required if x[0] is pin.family}:
        fail_validation("Report proof contains an unrelated premium run.", field="bindings")


type ReportSelectionContract = (
    r.ReportSelection | r.ExportSelection | ReportSelectionV3 | v4.ReportSelectionV4
)
type ReportHeaderContract = (
    r.ReportDocumentHeader | ReportDocumentHeaderV3 | v4.ReportDocumentHeaderV4
)
type ReportCaptureContract = (
    r.ReportCaptureSummary | ReportCaptureSummaryV3 | v4.ReportCaptureSummaryV4
)
type ReportManifestContract = r.ReportManifest | ReportManifestV3 | v4.ReportManifestV4


def is_report_selection(
    selection: ReportSelectionContract,
) -> TypeIs[r.ReportSelection | ReportSelectionV3 | v4.ReportSelectionV4]:
    """Distinguish report formats/sections from exports without losing explicit premium profiles."""
    return isinstance(selection, (r.ReportSelection, ReportSelectionV3, v4.ReportSelectionV4))


def selected_risk_run_id(selection: ReportSelectionContract) -> UUID | None:
    if isinstance(selection, r.ReportSelection):
        return selection.risk_run_id
    if isinstance(selection, ReportSelectionV3) and isinstance(
        selection.premium_run, ReportRiskRunSelection
    ):
        return selection.premium_run.run_id
    return None


def selected_scenario_run_id(selection: ReportSelectionContract) -> UUID | None:
    if isinstance(selection, ReportSelectionV3) and isinstance(
        selection.premium_run, ReportScenarioRunSelection
    ):
        return selection.premium_run.run_id
    return None


def selected_report_formats(selection: ReportSelectionContract) -> tuple[r.ReportFormat, ...]:
    if is_report_selection(selection):
        return selection.formats
    return (r.ReportFormat(selection.format.value),)
