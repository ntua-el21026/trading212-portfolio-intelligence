"""Closed report selections and immutable, bounded canonical document records."""

from __future__ import annotations

import calendar
import re
import types
from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from typing import cast, get_args, get_origin, get_type_hints
from uuid import UUID

from .enums import QualityState
from .errors import DomainError, ErrorCode, fail_validation
from .sources import LicensePermission, SourceAvailability
from .values import CurrencyCode, require_utc

REPORT_SCHEMA_VERSION = "1.0.0"
REPORT_METHOD = "report_manifest_v1"
REPORT_METHOD_VERSION = "1.0.0"
REPORT_PROFILE_VERSION = "report_sections_v1"
REPORT_TEMPLATE_VERSION = "report_template_v1"
MAX_REPORT_DOCUMENT_BYTES = 32 * 1024 * 1024
MAX_REPORT_CHUNK_BYTES = 1024 * 1024
MAX_REPORT_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_REPORT_ARTIFACT_BYTES = 10 * 1024 * 1024
MAX_REPORT_JOB_BYTES = 25 * 1024 * 1024
MAX_REPORT_DATASET_ROWS = 100_000
MAX_REPORT_COLUMNS = 64
MAX_REPORT_TEXT_CHARS = 4096
MAX_REPORT_PDF_PAGES = 1000
MAX_REPORT_SCRATCH_BYTES = 192 * 1024 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")


class ReportType(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    PORTFOLIO_SUMMARY = "portfolio_summary"
    TARGET_DRIFT = "target_drift"
    CONTRIBUTION_PLAN = "contribution_plan"
    PERFORMANCE_BENCHMARK = "performance_benchmark"
    DIVIDEND_INCOME = "dividend_income"
    PORTFOLIO_XRAY = "portfolio_xray"
    QUALITY_RECONCILIATION = "quality_reconciliation"


class ReportFormat(StrEnum):
    PDF = "pdf"
    CSV = "csv"
    JSON = "json"
    XLSX = "xlsx"


class ExportFormat(StrEnum):
    CSV = "csv"
    JSON = "json"
    XLSX = "xlsx"


class ReportSection(StrEnum):
    OVERVIEW = "overview"
    ALLOCATION = "allocation"
    TARGETS = "targets"
    DRIFT = "drift"
    CONTRIBUTION_PLAN = "contribution_plan"
    PERFORMANCE = "performance"
    BENCHMARK = "benchmark"
    INCOME = "income"
    CASH_FLOWS = "cash_flows"
    ATTRIBUTION = "attribution"
    XRAY = "xray"
    QUALITY = "quality"
    ACTIVITY = "activity"


class ExportDataset(StrEnum):
    POSITIONS = "positions"
    ACTIVITY = "activity"
    DIVIDENDS = "dividends"
    TARGETS = "targets"
    PLANS = "plans"
    PERFORMANCE = "performance"
    XRAY = "xray"
    ALERTS = "alerts"


class ExportFieldSet(StrEnum):
    STANDARD = "standard"
    AUDIT = "audit"


class ReportJobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ReportFailureCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    INPUT_UNAVAILABLE = "input_unavailable"
    INPUT_CHANGED = "input_changed"
    ACCESS_DENIED = "access_denied"
    SOURCE_RESTRICTED = "source_restricted"
    LIMIT_EXCEEDED = "limit_exceeded"
    RENDER_FAILED = "render_failed"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    PUBLICATION_UNAVAILABLE = "publication_unavailable"
    LEASE_EXPIRED = "lease_expired"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"


class ReportSourceUse(StrEnum):
    REPORT = "report"
    EXPORT = "export"


class ReportFamily(StrEnum):
    SNAPSHOT = "snapshot"
    ACTIVITY = "activity"
    TARGET = "target"
    PLANNING = "planning"
    PERFORMANCE = "performance"
    BENCHMARK = "benchmark"
    INCOME = "income"
    CASH_FLOWS = "cash_flows"
    ATTRIBUTION = "attribution"
    XRAY = "xray"
    RECONCILIATION = "reconciliation"
    ALERTS = "alerts"


class ReportInputRole(StrEnum):
    SNAPSHOT = "snapshot"
    INPUT = "input"
    RESULT = "result"
    CALCULATION = "calculation"
    POLICY = "policy"
    TARGET_VERSION = "target_version"
    PLAN_REVISION = "plan_revision"
    BENCHMARK_VERSION = "benchmark_version"
    SOURCE = "source"
    MAPPING = "mapping"
    LICENSE = "license"
    CALENDAR = "calendar"
    EVENT_REVISION = "event_revision"
    RECONCILIATION = "reconciliation"


class ReportSourceKind(StrEnum):
    BROKER_SOURCE_RECORD = "broker_source_record"
    BROKER_SOURCE_OCCURRENCE = "broker_source_occurrence"
    INGESTION_RUN = "ingestion_run"
    PORTFOLIO_SNAPSHOT = "portfolio_snapshot"
    SNAPSHOT_POSITION = "snapshot_position"
    SNAPSHOT_CASH = "snapshot_cash"
    CALCULATION = "calculation"
    ACTIVITY_REVISION = "activity_revision"
    ACTIVITY_COVERAGE = "activity_coverage"
    RECONCILIATION = "reconciliation"
    TARGET_VERSION = "target_version"
    PLAN_REVISION = "plan_revision"
    HISTORICAL_INPUT = "historical_input"
    HISTORICAL_RESULT = "historical_result"
    XRAY_INPUT = "xray_input"
    XRAY_RESULT = "xray_result"
    PRICE_SNAPSHOT = "price_snapshot"
    FX_SNAPSHOT = "fx_snapshot"
    FX_OBSERVATION = "fx_observation"
    FX_COVERAGE_GAP = "fx_coverage_gap"
    BENCHMARK = "benchmark"
    CONSTITUENT_SNAPSHOT = "constituent_snapshot"
    CONSTITUENT_HOLDING = "constituent_holding"
    IDENTITY = "identity"
    CLASSIFICATION = "classification"
    FUND_MAPPING = "fund_mapping"
    MAPPING = "mapping"
    TAXONOMY = "taxonomy"
    POLICY = "policy"
    CALENDAR = "calendar"
    LICENSE = "license"
    OPENING = "opening"
    CORPORATE_ACTION = "corporate_action"
    SOURCE_COVERAGE = "source_coverage"
    HISTORICAL_EVIDENCE = "historical_evidence"
    FUND_DEFINITION = "fund_definition"
    PRICE_OBSERVATION = "price_observation"
    RECONCILIATION_DISCREPANCY = "reconciliation_discrepancy"
    ENTITY_EVIDENCE_VERSION = "entity_evidence_version"
    ENTITY_EVIDENCE_REFERENCE = "entity_evidence_reference"
    RELATIONSHIP = "relationship"
    CLASSIFICATION_SNAPSHOT = "classification_snapshot"
    CLASSIFICATION_ASSIGNMENT = "classification_assignment"
    HISTORICAL_CLASSIFICATION = "historical_classification"
    BENCHMARK_VERSION = "benchmark_version"


class CellKind(StrEnum):
    TEXT = "text"
    IDENTIFIER = "identifier"
    ENUM = "enum"
    DECIMAL = "decimal"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    DATE = "date"
    INSTANT = "instant"


class CellState(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class DecimalRole(StrEnum):
    MONEY = "money"
    QUANTITY = "quantity"
    PRICE = "price"
    FX = "fx"
    RATIO = "ratio"
    SCORE = "score"
    RESIDUAL = "residual"


class ReportMetricOrigin(StrEnum):
    OBSERVED_PROVIDER = "observed_provider"
    NORMALIZED_PROVIDER = "normalized_provider"
    DERIVED_DETERMINISTIC = "derived_deterministic"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"
    PROVIDER = "provider"
    DERIVED = "derived"


class ReportNoteKind(StrEnum):
    WARNING = "warning"
    ASSUMPTION = "assumption"
    LIMITATION = "limitation"
    UNAVAILABLE_REASON = "unavailable_reason"
    RECONCILIATION = "reconciliation"


class ReportBoundKind(StrEnum):
    EXACT = "exact"
    LOWER_BOUND = "lower_bound"
    UNAVAILABLE = "unavailable"


class ReportMimeType(StrEnum):
    PDF = "application/pdf"
    CSV = "text/csv; charset=utf-8"
    JSON = "application/json"
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def report_mime_type(format: ReportFormat | ExportFormat) -> ReportMimeType:
    return ReportMimeType[format.name]


def report_limit(condition: bool, field: str) -> None:
    if not condition:
        raise DomainError(
            ErrorCode.INPUT_BOUND_EXCEEDED, "Report content exceeds its limit.", field
        )


def report_digest(value: str, field: str = "digest") -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        fail_validation("A canonical report digest is required.", field=field)
    return value


def report_key(value: str, field: str = "key") -> str:
    if type(value) is not str or _KEY.fullmatch(value) is None:
        fail_validation("A bounded report key is required.", field=field)
    return value


@lru_cache(maxsize=128)
def _record_hints(kind: type[ReportRecord]) -> dict[str, object]:
    return get_type_hints(kind)


def _typed(value: object, annotation: object) -> bool:
    origin = get_origin(annotation)
    if origin is types.UnionType:
        return any(_typed(value, part) for part in get_args(annotation))
    if origin is tuple:
        args = get_args(annotation)
        return type(value) is tuple and all(_typed(item, args[0]) for item in value)
    if annotation is type(None):
        return value is None
    return isinstance(annotation, type) and type(value) is annotation


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportRecord:
    """Only explicitly declared immutable report records enter the report codec."""

    def __post_init__(self) -> None:
        hints = _record_hints(cast("type", type(self)))
        for item in fields(self):
            value = getattr(self, item.name)
            if not _typed(value, hints[item.name]):
                fail_validation("A typed report field is required.", field=item.name)
            if type(value) is str:
                report_limit(len(value) <= MAX_REPORT_TEXT_CHARS, item.name)
                if item.name.endswith("digest"):
                    report_digest(value, item.name)
            elif type(value) is datetime:
                object.__setattr__(self, item.name, require_utc(value))
            elif type(value) is tuple:
                report_limit(len(value) <= MAX_REPORT_DATASET_ROWS, item.name)
            elif type(value) is bytes:
                report_limit(len(value) <= MAX_REPORT_DOCUMENT_BYTES, item.name)
            elif type(value) is Decimal and not value.is_finite():
                fail_validation("Report decimals must be finite.", field=item.name)


def _selection_window(start: date, end: date) -> None:
    if start > end or (end - start).days > 3660:
        fail_validation("Report period is outside its bound.", field="end_date")


_REQUIRED_SECTIONS = {
    ReportType.MONTHLY: (
        "overview",
        "allocation",
        "performance",
        "income",
        "cash_flows",
        "quality",
    ),
    ReportType.QUARTERLY: (
        "overview",
        "allocation",
        "performance",
        "income",
        "cash_flows",
        "quality",
    ),
    ReportType.ANNUAL: ("overview", "allocation", "performance", "income", "cash_flows", "quality"),
    ReportType.PORTFOLIO_SUMMARY: ("overview", "allocation", "quality"),
    ReportType.TARGET_DRIFT: ("overview", "targets", "drift", "quality"),
    ReportType.CONTRIBUTION_PLAN: ("overview", "targets", "contribution_plan", "quality"),
    ReportType.PERFORMANCE_BENCHMARK: ("overview", "performance", "benchmark", "quality"),
    ReportType.DIVIDEND_INCOME: ("overview", "income", "cash_flows", "quality"),
    ReportType.PORTFOLIO_XRAY: ("overview", "xray", "quality"),
    ReportType.QUALITY_RECONCILIATION: ("overview", "quality", "activity"),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportSelection(ReportRecord):
    account_id: UUID
    start_date: date
    end_date: date
    source_cutoff_at: datetime
    snapshot_id: UUID
    reporting_currency: CurrencyCode
    report_type: ReportType
    sections: tuple[ReportSection, ...]
    formats: tuple[ReportFormat, ...]
    target_version_id: UUID | None = None
    plan_revision_id: UUID | None = None
    benchmark_version_id: UUID | None = None
    constituent_snapshot_id: UUID | None = None
    template_version: str = REPORT_TEMPLATE_VERSION

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        _selection_window(self.start_date, self.end_date)
        for name, items, maximum in (("sections", self.sections, 13), ("formats", self.formats, 4)):
            if not 1 <= len(items) <= maximum or len(set(items)) != len(items):
                fail_validation("Report selections must be unique and bounded.", field=name)
        if not set(_REQUIRED_SECTIONS[self.report_type]).issubset(self.sections):
            fail_validation("Required report sections are missing.", field="sections")
        if self.template_version != REPORT_TEMPLATE_VERSION:
            fail_validation("Report template is unsupported.", field="template_version")
        selected = set(self.sections)
        wants_target = bool(
            selected & {ReportSection.TARGETS, ReportSection.DRIFT, ReportSection.CONTRIBUTION_PLAN}
        )
        if wants_target and self.target_version_id is None and self.plan_revision_id is None:
            fail_validation("A published target reference is required.", field="target_version_id")
        for name, wanted in (
            ("target_version_id", wants_target),
            ("plan_revision_id", ReportSection.CONTRIBUTION_PLAN in selected),
            ("benchmark_version_id", ReportSection.BENCHMARK in selected),
            ("constituent_snapshot_id", ReportSection.XRAY in selected),
        ):
            value = getattr(self, name)
            if value is not None and not wanted:
                fail_validation("A report reference is irrelevant.", field=name)
            if wanted and name in {"plan_revision_id", "benchmark_version_id"} and value is None:
                fail_validation("A required report reference is missing.", field=name)
        if self.report_type in {ReportType.MONTHLY, ReportType.QUARTERLY, ReportType.ANNUAL}:
            start, end = self.start_date, self.end_date
            if self.report_type is ReportType.MONTHLY:
                valid = start.day == 1 and end == date(
                    start.year, start.month, calendar.monthrange(start.year, start.month)[1]
                )
            elif self.report_type is ReportType.QUARTERLY:
                final_month = start.month + 2
                valid = (
                    start.day == 1
                    and start.month in {1, 4, 7, 10}
                    and end
                    == date(
                        start.year, final_month, calendar.monthrange(start.year, final_month)[1]
                    )
                    if final_month <= 12
                    else False
                )
            else:
                valid = start == date(start.year, 1, 1) and end == date(start.year, 12, 31)
            if not valid:
                fail_validation("A complete calendar period is required.", field="end_date")
        object.__setattr__(
            self, "sections", tuple(item for item in ReportSection if item in selected)
        )
        object.__setattr__(
            self, "formats", tuple(item for item in ReportFormat if item in self.formats)
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportSelection(ReportRecord):
    account_id: UUID
    start_date: date
    end_date: date
    source_cutoff_at: datetime
    snapshot_id: UUID
    reporting_currency: CurrencyCode
    dataset: ExportDataset
    field_set: ExportFieldSet
    format: ExportFormat
    target_version_id: UUID | None = None
    plan_revision_id: UUID | None = None
    benchmark_version_id: UUID | None = None
    constituent_snapshot_id: UUID | None = None

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        _selection_window(self.start_date, self.end_date)
        if self.dataset is ExportDataset.ALERTS:
            fail_validation("The canonical alerts export producer is unavailable.", field="dataset")
        for name, allowed in (
            ("target_version_id", {ExportDataset.TARGETS, ExportDataset.PLANS}),
            ("plan_revision_id", {ExportDataset.PLANS}),
            ("benchmark_version_id", set()),
            ("constituent_snapshot_id", {ExportDataset.XRAY}),
        ):
            value = getattr(self, name)
            if value is not None and self.dataset not in allowed:
                fail_validation("An export reference is irrelevant.", field=name)
        if self.dataset is ExportDataset.TARGETS and self.target_version_id is None:
            fail_validation("A target version is required.", field="target_version_id")
        if self.dataset is ExportDataset.PLANS and self.plan_revision_id is None:
            fail_validation("A plan revision is required.", field="plan_revision_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportCell(ReportRecord):
    kind: CellKind
    value: str | Decimal | int | bool | date | datetime | None
    state: CellState = CellState.AVAILABLE
    decimal_role: DecimalRole | None = None
    currency: CurrencyCode | None = None
    context_key: str | None = None
    reason_key: str | None = None
    bound_key: str | None = None
    quality: QualityState | None = None
    origin: ReportMetricOrigin | None = None
    coverage_key: str | None = None
    confidence: Decimal | None = None
    method_key: str | None = None
    method_version: str | None = None
    provenance_set_key: str | None = None
    note_set_key: str | None = None

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        for name in (
            "coverage_key",
            "method_key",
            "method_version",
            "provenance_set_key",
            "note_set_key",
        ):
            if (metadata_key := getattr(self, name)) is not None:
                report_key(metadata_key, name)
        if (self.method_key is None) != (self.method_version is None):
            fail_validation("Metric methodology requires its version.", field="method_version")
        if self.confidence is not None:
            exponent = self.confidence.as_tuple().exponent
            if not 0 <= self.confidence <= 1 or not isinstance(exponent, int) or exponent < -18:
                fail_validation(
                    "Metric confidence must be an exact bounded ratio.", field="confidence"
                )
        if self.value is None:
            if self.state not in {
                CellState.UNAVAILABLE,
                CellState.FAILED,
                CellState.NOT_APPLICABLE,
            }:
                fail_validation("A missing cell requires an explicit state.", field="value")
            if self.state is not CellState.NOT_APPLICABLE and self.reason_key is None:
                fail_validation("An unavailable cell requires a reason.", field="reason_key")
        else:
            expected = {
                CellKind.TEXT: str,
                CellKind.IDENTIFIER: str,
                CellKind.ENUM: str,
                CellKind.DECIMAL: Decimal,
                CellKind.INTEGER: int,
                CellKind.BOOLEAN: bool,
                CellKind.DATE: date,
                CellKind.INSTANT: datetime,
            }[self.kind]
            if type(self.value) is not expected or self.state in {
                CellState.UNAVAILABLE,
                CellState.FAILED,
                CellState.NOT_APPLICABLE,
            }:
                fail_validation("A report cell has an incompatible value/state.", field="value")
        if self.kind is CellKind.DECIMAL:
            if self.decimal_role is None:
                fail_validation("A decimal role is required.", field="decimal_role")
            if (
                self.decimal_role in {DecimalRole.MONEY, DecimalRole.PRICE}
                and self.currency is None
            ):
                fail_validation("Monetary cells require currency.", field="currency")
            if isinstance(self.value, Decimal):
                exponent = self.value.as_tuple().exponent
                if (
                    not isinstance(exponent, int)
                    or exponent < -18
                    or len(self.value.as_tuple().digits) > 128
                    or self.value.adjusted() > 127
                ):
                    fail_validation("Report decimal exceeds its public role bound.", field="value")
        elif self.decimal_role is not None or self.currency is not None:
            fail_validation("Nondecimal cells cannot carry a financial role.", field="decimal_role")
        for name in ("context_key", "reason_key", "bound_key"):
            if (value := getattr(self, name)) is not None:
                report_key(value, name)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportRendererVersion(ReportRecord):
    format: ReportFormat
    name: str
    version: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportFontReference(ReportRecord):
    name: str
    version: str
    content_digest: str
    license_digest: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportRendererProfile(ReportRecord):
    renderer_versions: tuple[ReportRendererVersion, ...]
    fonts: tuple[ReportFontReference, ...]
    profile_version: str = "report_render_v1"
    template_version: str = REPORT_TEMPLATE_VERSION
    locale: str = "en-GB"
    timezone: str = "UTC"
    chart_order_version: str = "report_chart_order_v1"
    accessibility_profile_version: str = "report_visual_accessibility_v1"

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        if (
            self.profile_version,
            self.template_version,
            self.locale,
            self.timezone,
            self.chart_order_version,
            self.accessibility_profile_version,
        ) != (
            "report_render_v1",
            REPORT_TEMPLATE_VERSION,
            "en-GB",
            "UTC",
            "report_chart_order_v1",
            "report_visual_accessibility_v1",
        ):
            fail_validation("Report renderer profile is unsupported.", field="renderer_profile")
        if not 1 <= len(self.renderer_versions) <= 4 or len(
            {x.format for x in self.renderer_versions}
        ) != len(self.renderer_versions):
            fail_validation("Report renderer versions must be unique.", field="renderer_versions")
        report_limit(len(self.fonts) <= 2, "fonts")
        object.__setattr__(
            self,
            "renderer_versions",
            tuple(sorted(self.renderer_versions, key=lambda x: list(ReportFormat).index(x.format))),
        )
        object.__setattr__(
            self, "fonts", tuple(sorted(self.fonts, key=lambda x: (x.name, x.content_digest)))
        )


class ReportTableKey(StrEnum):
    BENCHMARK_COMPOSITE = "benchmark_composite"
    BENCHMARK_COMPONENTS = "benchmark_components"
    BENCHMARK_COMPONENT_MEMBERS = "benchmark_component_members"
    BENCHMARK_OBSERVATIONS = "benchmark_observations"
    HISTORICAL_OPTIONS = "historical_options"
    HISTORICAL_WARNING_COVERAGE = "historical_warning_coverage"
    XRAY_DIRECT_POSITIONS = "xray_direct_positions"
    XRAY_FUND_ENTITIES = "xray_fund_entities"
    XRAY_PATH_WEIGHTS = "xray_path_weights"
    XRAY_MEMBERS = "xray_members"
    XRAY_POLICY = "xray_policy"
    XRAY_POLICY_COMPONENTS = "xray_policy_components"
    XRAY_POLICY_LIMITS = "xray_policy_limits"
    XRAY_TAXONOMIES = "xray_taxonomies"
    XRAY_THRESHOLD_POLICY = "xray_threshold_policy"
    PLAN_INPUT_HEADER = "plan_input_header"
    PLAN_VALUATION = "plan_valuation"
    PLAN_VALUATION_POSITIONS = "plan_valuation_positions"
    PLAN_VALUATION_CASH = "plan_valuation_cash"
    PLAN_FX = "plan_fx"
    PLAN_OPTIONS = "plan_options"
    PLAN_INPUT_MEMBERS = "plan_input_members"
    PLAN_LISTING_PREFERENCES = "plan_listing_preferences"
    PLAN_HOLDING_CONSTRAINTS = "plan_holding_constraints"
    PLAN_ALLOCATION_CONSTRAINTS = "plan_allocation_constraints"
    PLAN_NODE_IDENTITIES = "plan_node_identities"
    PLAN_CATALOG_INSTRUMENTS = "plan_catalog_instruments"
    PLAN_CATALOG_LISTINGS = "plan_catalog_listings"
    PLAN_SOURCE_DETAILS = "plan_source_details"
    PLAN_EFFECTIVE_CONSTRAINTS = "plan_effective_constraints"
    SNAPSHOT_TOTALS = "snapshot_totals"
    POSITIONS = "positions"
    ALLOCATION_BUCKETS = "allocation_buckets"
    TARGET_NODES = "target_nodes"
    TARGET_HOLDINGS = "target_holdings"
    TARGET_CONSTRAINTS = "target_constraints"
    DRIFT_ROWS = "drift_rows"
    DRIFT_TOTALS = "drift_totals"
    PLAN_SUMMARY = "plan_summary"
    PLAN_LINES = "plan_lines"
    PLAN_OBJECTIVES = "plan_objectives"
    PLAN_RELATIONS = "plan_relations"
    PERFORMANCE_SUMMARY = "performance_summary"
    PERFORMANCE_POINTS = "performance_points"
    PERFORMANCE_PERIODS = "performance_periods"
    BENCHMARK_SUMMARY = "benchmark_summary"
    BENCHMARK_POINTS = "benchmark_points"
    BENCHMARK_PERIODS = "benchmark_periods"
    INCOME_SUMMARY = "income_summary"
    INCOME_COMPONENTS = "income_components"
    INCOME_TOTALS = "income_totals"
    INCOME_PERIODS = "income_periods"
    INCOME_REPORTING_PERIODS = "income_reporting_periods"
    CASH_FLOW_SUMMARY = "cash_flow_summary"
    CASH_FLOW_TOTALS = "cash_flow_totals"
    CASH_FLOW_PERIODS = "cash_flow_periods"
    CASH_FLOW_EVENTS = "cash_flow_events"
    ATTRIBUTION_SUMMARY = "attribution_summary"
    ATTRIBUTION_COMPONENTS = "attribution_components"
    ATTRIBUTION_EFFECTS = "attribution_effects"
    XRAY_SUMMARY = "xray_summary"
    XRAY_QUALITY = "xray_quality"
    XRAY_DIMENSIONS = "xray_dimensions"
    XRAY_EXPOSURES = "xray_exposures"
    XRAY_PATHS = "xray_paths"
    XRAY_HELD_FUNDS = "xray_held_funds"
    XRAY_OVERLAP_PAIRS = "xray_overlap_pairs"
    XRAY_OVERLAP_ENTITIES = "xray_overlap_entities"
    XRAY_CONCENTRATIONS = "xray_concentrations"
    XRAY_CONCENTRATION_MEMBERS = "xray_concentration_members"
    XRAY_THRESHOLDS = "xray_thresholds"
    XRAY_RESIDUALS = "xray_residuals"
    XRAY_PATH_RELATIONS = "xray_path_relations"
    RECONCILIATION = "reconciliation"
    RECONCILIATION_ISSUES = "reconciliation_issues"
    COVERAGE = "coverage"
    NOTES = "notes"
    ACTIVITY = "activity"
    HISTORICAL_USE_CONSUMERS = "historical_use_consumers"
    HISTORICAL_OBSERVATION_USES = "historical_observation_uses"
    HISTORICAL_EVIDENCE_USES = "historical_evidence_uses"
    HISTORICAL_MISSING_USES = "historical_missing_uses"
    HISTORICAL_USE_CANDIDATES = "historical_use_candidates"
    HISTORICAL_CONVERSION_USES = "historical_conversion_uses"
    HISTORICAL_CONVERSION_LEGS = "historical_conversion_legs"
    HISTORICAL_EVENT_MEMBERSHIPS = "historical_event_memberships"
    XRAY_SELECTIONS = "xray_selections"
    XRAY_SELECTION_EVIDENCE = "xray_selection_evidence"
    XRAY_SOURCE_USES = "xray_source_uses"
    XRAY_FUND_EDGES = "xray_fund_edges"
    XRAY_PATH_CLASSIFICATIONS = "xray_path_classifications"
    XRAY_CLASSIFICATION_DECISIONS = "xray_classification_decisions"
    XRAY_CLASSIFICATION_MEMBERSHIPS = "xray_classification_memberships"
    DIVIDENDS = "dividends"
    CONTEXTS = "contexts"
    SOURCE_REFERENCES = "source_references"
    SOURCE_MEMBERSHIPS = "source_memberships"
    NOTE_MEMBERSHIPS = "note_memberships"
    LICENSE_REFERENCES = "license_references"
    COVERAGE_FACTS = "coverage_facts"
    BOUND_FACTS = "bound_facts"
    BINDINGS = "bindings"
    RECONCILIATION_BINDINGS = "reconciliation_bindings"
    HISTORICAL_SOURCE_DETAILS = "historical_source_details"
    HISTORICAL_SOURCE_PARENTS = "historical_source_parents"
    HISTORICAL_EVENT_IDENTITIES = "historical_event_identities"
    XRAY_VALUATION_ROOTS = "xray_valuation_roots"
    XRAY_BROKER_FX = "xray_broker_fx"
    XRAY_LICENSED_FX = "xray_licensed_fx"
    XRAY_FX_LEGS = "xray_fx_legs"
    XRAY_DEPENDENCY_IDENTITIES = "xray_dependency_identities"
    TARGET_EXCLUSIONS = "target_exclusions"
    HISTORICAL_ANCHOR_RECONCILIATION = "historical_anchor_reconciliation"
    HISTORICAL_RECONCILIATION_LINES = "historical_reconciliation_lines"
    HISTORICAL_RECONCILIATION_ANCHORS = "historical_reconciliation_anchors"
    XRAY_RECONCILIATION = "xray_reconciliation"
    XRAY_WARNING_PATHS = "xray_warning_paths"


class ReportRowOrder(StrEnum):
    KEY_ASC = "key_asc"
    ORDINAL_ASC = "ordinal_asc"
    CANONICAL = "canonical"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportColumn(ReportRecord):
    key: str
    kind: CellKind | None
    decimal_role: DecimalRole | None = None
    optional: bool = False

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        report_key(self.key)
        if (self.kind is CellKind.DECIMAL) != (self.decimal_role is not None):
            fail_validation("Column decimal role disagrees with its kind.", field="columns")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportTableSchema(ReportRecord):
    key: ReportTableKey
    columns: tuple[ReportColumn, ...]
    order: ReportRowOrder = ReportRowOrder.CANONICAL
    schema_version: str = REPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        report_limit(1 <= len(self.columns) <= MAX_REPORT_COLUMNS, "columns")
        if self.schema_version != REPORT_SCHEMA_VERSION or len(
            {c.key for c in self.columns}
        ) != len(self.columns):
            fail_validation("Report table schema is invalid.", field="schema")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportRow(ReportRecord):
    key: str
    context_key: str
    cells: tuple[ReportCell, ...]

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        report_key(self.key)
        report_key(self.context_key, "context_key")
        report_limit(1 <= len(self.cells) <= MAX_REPORT_COLUMNS, "cells")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportTableDescriptor(ReportRecord):
    table: ReportTableKey
    schema_digest: str
    row_count: int
    content_digest: str
    section: ReportSection | None = None
    dataset: ExportDataset | None = None
    state: SourceAvailability = SourceAvailability.AVAILABLE
    reason_key: str | None = None

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        report_limit(0 <= self.row_count <= MAX_REPORT_DATASET_ROWS, "row_count")
        if self.state is not SourceAvailability.AVAILABLE and self.reason_key is None:
            fail_validation("Incomplete tables require a reason.", field="reason_key")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportDocumentHeader(ReportRecord):
    selection: ReportSelection | ExportSelection
    owner_id: UUID
    valuation_at: datetime
    context_digest: str
    tables: tuple[ReportTableDescriptor, ...]
    document_digest: str
    document_schema_version: str = REPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        if self.document_schema_version != REPORT_SCHEMA_VERSION or len(
            {x.table for x in self.tables}
        ) != len(self.tables):
            fail_validation("Report document schema/tables are invalid.", field="tables")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportContext(ReportRecord):
    key: str
    family: ReportFamily
    method_key: str
    method_version: str
    valuation_at: datetime
    source_cutoff_at: datetime
    quality: QualityState
    provenance_set_key: str
    coverage_set_key: str
    note_set_key: str
    source_at: datetime | None = None
    reconciliation_key: str | None = None
    schema_version: str = REPORT_SCHEMA_VERSION


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportSourceReference(ReportRecord):
    key: str
    kind: ReportSourceKind
    subject_id: UUID
    content_digest: str
    parent_id: UUID | None = None
    source_at: datetime | None = None
    first_observed_at: datetime | None = None
    provider_id: UUID | None = None
    license_version_id: UUID | None = None
    mapping_version_id: UUID | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportSourceMembership(ReportRecord):
    provenance_set_key: str
    source_key: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportNoteMembership(ReportRecord):
    note_set_key: str
    note_key: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportLicenseReference(ReportRecord):
    version_id: UUID
    provider_id: UUID
    license_digest: str
    attribution: str
    pinned_store: LicensePermission
    pinned_display: LicensePermission
    pinned_report: LicensePermission
    pinned_export: LicensePermission
    valid_from: datetime
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportNote(ReportRecord):
    key: str
    kind: ReportNoteKind
    family: ReportFamily
    code: str
    text: str
    related_provenance_set_key: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportCoverageFact(ReportRecord):
    set_key: str
    family: ReportFamily
    metric_key: str
    value: ReportCell


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportBoundFact(ReportRecord):
    key: str
    family: ReportFamily
    kind: ReportBoundKind
    quantum: Decimal | None = None
    rounding: str | None = None
    positive_below_quantum: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportBinding(ReportRecord):
    family: ReportFamily
    role: ReportInputRole
    subject_id: UUID
    content_digest: str
    parent_id: UUID | None = None
    method_key: str | None = None
    method_version: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportReconciliationBinding(ReportRecord):
    key: str
    absent: bool
    run_id: UUID | None = None
    content_digest: str | None = None

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        if self.absent != (self.run_id is None) or self.absent != (self.content_digest is None):
            fail_validation("Reconciliation absence and identity disagree.", field="reconciliation")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportProofRelation(ReportRecord):
    table: ReportTableKey
    row: ReportRow


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportProof(ReportRecord):
    contexts: tuple[ReportContext, ...] = ()
    source_references: tuple[ReportSourceReference, ...] = ()
    source_memberships: tuple[ReportSourceMembership, ...] = ()
    note_memberships: tuple[ReportNoteMembership, ...] = ()
    license_references: tuple[ReportLicenseReference, ...] = ()
    coverage: tuple[ReportCoverageFact, ...] = ()
    bounds: tuple[ReportBoundFact, ...] = ()
    notes: tuple[ReportNote, ...] = ()
    proof_relations: tuple[ReportProofRelation, ...] = ()
    reconciliation: tuple[ReportReconciliationBinding, ...] = ()

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        keys = {
            "contexts": lambda x: (x.family.value, x.key),
            "source_references": lambda x: (x.kind.value, str(x.subject_id), x.key),
            "source_memberships": lambda x: (x.provenance_set_key, x.source_key),
            "note_memberships": lambda x: (x.note_set_key, x.note_key),
            "license_references": lambda x: str(x.version_id),
            "coverage": lambda x: (x.set_key, x.family.value, x.metric_key),
            "bounds": lambda x: (x.family.value, x.key),
            "notes": lambda x: (x.family.value, x.key),
            "proof_relations": lambda x: (x.table.value, x.row.key),
            "reconciliation": lambda x: x.key,
        }
        for name, key in keys.items():
            object.__setattr__(self, name, tuple(sorted(getattr(self, name), key=key)))


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportChunk(ReportRecord):
    table: ReportTableKey
    ordinal: int
    rows: tuple[ReportRow, ...]
    canonical_bytes: bytes
    digest: str

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        report_limit(0 <= self.ordinal < MAX_REPORT_DATASET_ROWS, "ordinal")
        report_limit(len(self.canonical_bytes) <= MAX_REPORT_CHUNK_BYTES, "canonical_bytes")
        report_limit(1 <= len(self.rows) <= MAX_REPORT_DATASET_ROWS, "rows")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportCaptureSummary(ReportRecord):
    header: ReportDocumentHeader
    canonical_byte_length: int
    chunk_count: int
    immutable_bindings: tuple[ReportBinding, ...]
    proof: ReportProof
    proof_digest: str
    renderer_profile: ReportRendererProfile

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        report_limit(
            0 <= self.canonical_byte_length <= MAX_REPORT_DOCUMENT_BYTES, "canonical_byte_length"
        )
        report_limit(0 <= self.chunk_count <= MAX_REPORT_DATASET_ROWS, "chunk_count")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportManifest(ReportRecord):
    document: ReportDocumentHeader
    renderer_profile: ReportRendererProfile
    bindings: tuple[ReportBinding, ...]
    contexts: tuple[ReportContext, ...] = ()
    source_references: tuple[ReportSourceReference, ...] = ()
    source_memberships: tuple[ReportSourceMembership, ...] = ()
    note_memberships: tuple[ReportNoteMembership, ...] = ()
    license_references: tuple[ReportLicenseReference, ...] = ()
    coverage: tuple[ReportCoverageFact, ...] = ()
    bounds: tuple[ReportBoundFact, ...] = ()
    notes: tuple[ReportNote, ...] = ()
    proof_relations: tuple[ReportProofRelation, ...] = ()
    reconciliation: tuple[ReportReconciliationBinding, ...] = ()
    method: str = REPORT_METHOD
    method_version: str = REPORT_METHOD_VERSION
    escaping_version: str = "report_csv_text_v1"

    def __post_init__(self) -> None:
        ReportRecord.__post_init__(self)
        if (self.method, self.method_version, self.escaping_version) != (
            REPORT_METHOD,
            REPORT_METHOD_VERSION,
            "report_csv_text_v1",
        ):
            fail_validation("Report manifest version is unsupported.", field="method_version")
        proof = ReportProof(**{item.name: getattr(self, item.name) for item in fields(ReportProof)})
        for item in fields(ReportProof):
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


# Top-level public pins share the exact typed immutable binding representation.
ReportInputPin = ReportBinding
ReportColumnKey = str
