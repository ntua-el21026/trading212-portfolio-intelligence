"""Bounded owner preferences: closed presentation choices, never financial records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from .errors import fail_validation
from .research import ResearchEventKind, ResearchReviewState
from .values import CurrencyCode, require_utc

LAYOUT_SCHEMA_VERSION = 1
MAX_OWNER_LAYOUTS = 32
MAX_LAYOUT_WIDGETS = 24
MAX_LAYOUT_VERSIONS = 128
MAX_LAYOUT_CONTENT_BYTES = 16 * 1024
MAX_LAYOUT_RESPONSE_BYTES = 2 * 1024 * 1024


class LayoutWidgetKind(StrEnum):
    PORTFOLIO_SUMMARY = "portfolio_summary"
    DIRECT_ALLOCATION = "direct_allocation"
    HOLDINGS_PREVIEW = "holdings_preview"
    DATA_QUALITY = "data_quality"
    SAVED_VIEW = "saved_view"


class LayoutRoute(StrEnum):
    OVERVIEW = "overview"
    HOLDINGS = "holdings"
    ALLOCATION = "allocation"
    ACTIVITY = "activity"
    DIVIDENDS = "dividends"
    SNAPSHOTS = "snapshots"
    SYNCHRONIZATION = "synchronization"
    QUALITY = "quality"
    PIES = "pies"
    DRIFT = "drift"
    PLANNER = "planner"
    SOURCES = "sources"
    PERFORMANCE = "performance"
    RISK = "risk"
    SCENARIOS = "scenarios"
    PROJECTIONS = "projections"
    RESEARCH = "research"
    INCOME = "income"
    XRAY = "xray"
    REPORTS = "reports"
    ALERTS = "alerts"
    SETTINGS = "settings"


class LayoutRunFamily(StrEnum):
    RISK = "risk"
    SCENARIO = "scenario"
    PROJECTION = "projection"
    XRAY = "xray"


WORKSPACE_LAYOUT_PANES: dict[LayoutRoute, frozenset[str]] = {
    LayoutRoute.RISK: frozenset({"runs", "definitions"}),
    LayoutRoute.SCENARIOS: frozenset({"runs", "definitions"}),
    LayoutRoute.PROJECTIONS: frozenset({"runs", "assumptions", "goals"}),
}


def layout_bound(condition: bool, field: str) -> None:
    if not condition:
        fail_validation("The saved layout selection is invalid or exceeds its bounds.", field=field)


def layout_text(value: str, field: str, maximum: int, *, empty: bool = False) -> None:
    layout_bound(type(value) is str and len(value) <= maximum, field)
    layout_bound(
        (empty or bool(value.strip())) and not any(ord(c) < 32 or ord(c) == 127 for c in value),
        field,
    )


def layout_uuid(value: UUID | None, field: str, *, optional: bool = False) -> None:
    layout_bound(type(value) is UUID or (optional and value is None), field)


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceLayoutSelection:
    route: LayoutRoute
    pane: str | None = None
    kind: Literal["workspace"] = "workspace"

    def __post_init__(self) -> None:
        layout_bound(type(self.route) is LayoutRoute and self.kind == "workspace", "route")
        layout_bound(
            self.pane is None or self.pane in WORKSPACE_LAYOUT_PANES.get(self.route, frozenset()),
            "pane",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalLayoutSelection:
    route: Literal["performance", "income"]
    start_date: date
    end_date: date
    source_cutoff_at: datetime
    reporting_currency: CurrencyCode
    method: Literal["twr", "mwr", "modified_dietz"] = "twr"
    frequency: Literal["daily", "monthly"] = "monthly"
    knowledge: Literal["as_of_cutoff", "point_in_time"] = "as_of_cutoff"
    coverage: Literal["require_complete", "allow_degraded"] = "require_complete"
    view: str = "summary"
    grouping: Literal["holding", "group", "sector", "asset_class", "currency"] = "holding"
    flow_kind: str = "all"
    rolling: Literal["none", "calendar_days_30", "calendar_days_90", "calendar_days_365"] = "none"
    calendar: Literal["none", "month", "quarter", "year"] = "none"
    capture_id: UUID | None = None
    kind: Literal["historical"] = "historical"

    def __post_init__(self) -> None:
        layout_bound(self.kind == "historical" and self.route in {"performance", "income"}, "route")
        layout_bound(type(self.start_date) is date and type(self.end_date) is date, "period")
        layout_bound(0 <= (self.end_date - self.start_date).days <= 3660, "period")
        object.__setattr__(self, "source_cutoff_at", require_utc(self.source_cutoff_at))
        layout_bound(type(self.reporting_currency) is CurrencyCode, "reporting_currency")
        layout_bound(self.method in {"twr", "mwr", "modified_dietz"}, "method")
        layout_bound(self.frequency in {"daily", "monthly"}, "frequency")
        layout_bound(self.knowledge in {"as_of_cutoff", "point_in_time"}, "knowledge")
        layout_bound(self.coverage in {"require_complete", "allow_degraded"}, "coverage")
        layout_bound(
            self.grouping in {"holding", "group", "sector", "asset_class", "currency"}, "grouping"
        )
        layout_bound(
            self.rolling in {"none", "calendar_days_30", "calendar_days_90", "calendar_days_365"},
            "rolling",
        )
        layout_bound(self.calendar in {"none", "month", "quarter", "year"}, "calendar")
        views = (
            {"summary", "series", "rolling", "calendar", "attribution"}
            if self.route == "performance"
            else {"income", "cash_flows"}
        )
        layout_bound(self.view in views, "view")
        layout_bound(self.view != "rolling" or self.rolling != "none", "rolling")
        layout_bound(self.view != "calendar" or self.calendar != "none", "calendar")
        layout_bound(
            self.flow_kind
            in {
                "all",
                "deposit",
                "withdrawal",
                "transfer_in",
                "transfer_out",
                "buy",
                "sell",
                "dividend",
                "interest",
                "fee",
                "tax",
                "internal_transfer",
                "fx_conversion",
                "corporate_action",
                "unknown",
            },
            "flow_kind",
        )
        layout_bound(self.route != "income" or self.grouping in {"holding", "group"}, "grouping")
        layout_bound(self.view != "attribution" or self.method != "mwr", "method")
        layout_uuid(self.capture_id, "capture_id", optional=True)


@dataclass(frozen=True, slots=True, kw_only=True)
class RunLayoutSelection:
    family: LayoutRunFamily
    run_id: UUID
    pane: Literal["result", "goal"] = "result"
    snapshot_id: UUID | None = None
    source_cutoff_at: datetime | None = None
    reporting_currency: CurrencyCode | None = None
    kind: Literal["saved_run"] = "saved_run"

    def __post_init__(self) -> None:
        layout_bound(self.kind == "saved_run" and type(self.family) is LayoutRunFamily, "family")
        layout_uuid(self.run_id, "run_id")
        if self.family is LayoutRunFamily.XRAY:
            layout_uuid(self.snapshot_id, "snapshot_id")
            layout_bound(
                self.source_cutoff_at is not None and type(self.reporting_currency) is CurrencyCode,
                "xray_context",
            )
            if self.source_cutoff_at is not None:
                object.__setattr__(self, "source_cutoff_at", require_utc(self.source_cutoff_at))
        else:
            layout_bound(
                self.snapshot_id is None
                and self.source_cutoff_at is None
                and self.reporting_currency is None,
                "run_context",
            )
        layout_bound(
            self.pane == "result"
            or (self.pane == "goal" and self.family is LayoutRunFamily.PROJECTION),
            "pane",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchLayoutSelection:
    xray_run_id: UUID
    source_cutoff_at: datetime
    entity_id: UUID | None = None
    event_kind: ResearchEventKind | None = None
    review_state: ResearchReviewState = ResearchReviewState.ALL
    kind: Literal["research"] = "research"

    def __post_init__(self) -> None:
        layout_bound(self.kind == "research", "kind")
        layout_uuid(self.xray_run_id, "xray_run_id")
        layout_uuid(self.entity_id, "entity_id", optional=True)
        object.__setattr__(self, "source_cutoff_at", require_utc(self.source_cutoff_at))
        layout_bound(
            self.event_kind is None or type(self.event_kind) is ResearchEventKind, "event_kind"
        )
        layout_bound(type(self.review_state) is ResearchReviewState, "review_state")


type LayoutSelection = (
    WorkspaceLayoutSelection
    | HistoricalLayoutSelection
    | RunLayoutSelection
    | ResearchLayoutSelection
)
_SELECTIONS = (
    WorkspaceLayoutSelection,
    HistoricalLayoutSelection,
    RunLayoutSelection,
    ResearchLayoutSelection,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnerLayoutWidget:
    id: UUID
    kind: LayoutWidgetKind
    label: str = ""
    selection: LayoutSelection | None = None

    def __post_init__(self) -> None:
        layout_uuid(self.id, "widget_id")
        layout_bound(type(self.kind) is LayoutWidgetKind, "widget_kind")
        layout_text(self.label, "label", 80, empty=True)
        layout_bound(
            (self.kind is LayoutWidgetKind.SAVED_VIEW and type(self.selection) in _SELECTIONS)
            or (self.kind is not LayoutWidgetKind.SAVED_VIEW and self.selection is None),
            "selection",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnerLayoutContent:
    name: str
    description: str
    account_id: UUID | None
    widgets: tuple[OwnerLayoutWidget, ...]
    columns: Literal[1, 2, 3] = 2
    density: Literal["comfortable", "compact"] = "comfortable"
    schema_version: Literal[1] = 1

    def __post_init__(self) -> None:
        layout_text(self.name, "name", 80)
        layout_text(self.description, "description", 400, empty=True)
        layout_uuid(self.account_id, "account_id", optional=True)
        layout_bound(
            type(self.widgets) is tuple
            and 1 <= len(self.widgets) <= MAX_LAYOUT_WIDGETS
            and all(type(widget) is OwnerLayoutWidget for widget in self.widgets),
            "widgets",
        )
        layout_bound(len({widget.id for widget in self.widgets}) == len(self.widgets), "widget_id")
        previews = [
            widget.kind for widget in self.widgets if widget.kind is not LayoutWidgetKind.SAVED_VIEW
        ]
        layout_bound(len(previews) == len(set(previews)), "duplicate_preview")
        layout_bound(type(self.columns) is int and self.columns in (1, 2, 3), "columns")
        layout_bound(self.density in {"comfortable", "compact"}, "density")
        layout_bound(
            type(self.schema_version) is int and self.schema_version == 1, "schema_version"
        )
        if self.account_id is None:
            layout_bound(
                all(
                    widget.selection is None or type(widget.selection) is WorkspaceLayoutSelection
                    for widget in self.widgets
                ),
                "account_id",
            )
