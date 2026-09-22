"""Five bounded owner-preference operations with closed presentation selections."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import (
    BeforeValidator,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from .historical import (
    HistoricalCalendarPeriod,
    HistoricalCashFlowKind,
    HistoricalCoveragePolicy,
    HistoricalFrequency,
    HistoricalGrouping,
    HistoricalKnowledgePolicy,
    HistoricalMethod,
    HistoricalPageLimit,
    HistoricalRollingWindow,
    HistoricalSchema,
)
from .sources import CalendarDate
from .targets import AwareInstant, CurrencyString, Cursor, Digest, UUIDString

LayoutName = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=80, pattern=r"^[^\x00-\x1f\x7f]*$")
]
LayoutLabel = Annotated[
    str, StringConstraints(strict=True, max_length=80, pattern=r"^[^\x00-\x1f\x7f]*$")
]
LayoutDescription = Annotated[
    str, StringConstraints(strict=True, max_length=400, pattern=r"^[^\x00-\x1f\x7f]*$")
]
LayoutRevision = Annotated[StrictInt, Field(ge=1, le=129)]
LayoutVersionNumber = Annotated[StrictInt, Field(ge=1, le=128)]
LayoutRoute = Literal[
    "overview",
    "holdings",
    "allocation",
    "activity",
    "dividends",
    "snapshots",
    "synchronization",
    "quality",
    "pies",
    "drift",
    "planner",
    "sources",
    "performance",
    "risk",
    "scenarios",
    "projections",
    "research",
    "income",
    "xray",
    "reports",
    "alerts",
    "settings",
]
LayoutWidgetKind = Literal[
    "portfolio_summary", "direct_allocation", "holdings_preview", "data_quality", "saved_view"
]


def _schema_one(value: object) -> int:
    if type(value) is not int or value != 1:
        raise ValueError("Layout schema version must be the integer 1.")
    return value


class OwnerLayoutSchema(HistoricalSchema):
    pass


class WorkspaceLayoutSelection(OwnerLayoutSchema):
    kind: Literal["workspace"]
    route: LayoutRoute
    pane: Literal["runs", "definitions", "assumptions", "goals"] | None = None

    @model_validator(mode="after")
    def compatible_pane(self) -> Self:
        panes = {
            "risk": {"runs", "definitions"},
            "scenarios": {"runs", "definitions"},
            "projections": {"runs", "assumptions", "goals"},
        }
        if self.pane is not None and self.pane not in panes.get(self.route, set()):
            raise ValueError("The workspace pane is unavailable.")
        return self


class HistoricalLayoutSelection(OwnerLayoutSchema):
    kind: Literal["historical"]
    route: Literal["performance", "income"]
    start_date: CalendarDate
    end_date: CalendarDate
    source_cutoff_at: AwareInstant
    reporting_currency: CurrencyString
    method: HistoricalMethod = "twr"
    frequency: HistoricalFrequency = "monthly"
    knowledge: HistoricalKnowledgePolicy = "as_of_cutoff"
    coverage: HistoricalCoveragePolicy = "require_complete"
    view: Literal[
        "summary", "series", "rolling", "calendar", "attribution", "income", "cash_flows"
    ] = "summary"
    grouping: HistoricalGrouping = "holding"
    flow_kind: HistoricalCashFlowKind | Literal["all"] = "all"
    rolling: HistoricalRollingWindow = "none"
    calendar: HistoricalCalendarPeriod = "none"
    capture_id: UUIDString | None = None

    @model_validator(mode="after")
    def compatible_window(self) -> Self:
        if not 0 <= (self.end_date - self.start_date).days <= 3660:
            raise ValueError("The saved period exceeds its bound.")
        allowed = (
            {"summary", "series", "rolling", "calendar", "attribution"}
            if self.route == "performance"
            else {"income", "cash_flows"}
        )
        if (
            self.view not in allowed
            or (self.view == "rolling" and self.rolling == "none")
            or (self.view == "calendar" and self.calendar == "none")
        ):
            raise ValueError("The historical view is incompatible with its selectors.")
        if self.route == "income" and self.grouping not in {"holding", "group"}:
            raise ValueError("Income grouping is unsupported.")
        if self.view == "attribution" and self.method == "mwr":
            raise ValueError("Attribution does not support MWR.")
        return self


class RunLayoutSelection(OwnerLayoutSchema):
    kind: Literal["saved_run"]
    family: Literal["risk", "scenario", "projection", "xray"]
    run_id: UUIDString
    pane: Literal["result", "goal"] = "result"
    snapshot_id: UUIDString | None = None
    source_cutoff_at: AwareInstant | None = None
    reporting_currency: CurrencyString | None = None

    @model_validator(mode="after")
    def compatible_pane(self) -> Self:
        if self.family == "xray":
            if (
                self.snapshot_id is None
                or self.source_cutoff_at is None
                or self.reporting_currency is None
            ):
                raise ValueError("The original X-ray context is required.")
        elif (
            self.snapshot_id is not None
            or self.source_cutoff_at is not None
            or self.reporting_currency is not None
        ):
            raise ValueError("Only an X-ray selection accepts these context pins.")
        if self.pane == "goal" and self.family != "projection":
            raise ValueError("Only a projection has a goal pane.")
        return self


class ResearchLayoutSelection(OwnerLayoutSchema):
    kind: Literal["research"]
    xray_run_id: UUIDString
    source_cutoff_at: AwareInstant
    entity_id: UUIDString | None = None
    event_kind: Literal["news", "company_overview"] | None = None
    review_state: Literal["all", "reviewed", "unreviewed"] = "all"


LayoutSelection = Annotated[
    WorkspaceLayoutSelection
    | HistoricalLayoutSelection
    | RunLayoutSelection
    | ResearchLayoutSelection,
    Field(discriminator="kind"),
]


class OwnerLayoutWidget(OwnerLayoutSchema):
    id: UUIDString
    kind: LayoutWidgetKind
    label: LayoutLabel = ""
    selection: LayoutSelection | None = None

    @model_validator(mode="after")
    def selection_shape(self) -> Self:
        if (self.kind == "saved_view") != (self.selection is not None):
            raise ValueError("A saved view needs its exact typed selection.")
        return self


class OwnerLayoutContent(OwnerLayoutSchema):
    schema_version: Annotated[Literal[1], BeforeValidator(_schema_one)] = 1
    name: LayoutName
    description: LayoutDescription = ""
    account_id: UUIDString | None = None
    columns: Annotated[StrictInt, Field(ge=1, le=3)] = 2
    density: Literal["comfortable", "compact"] = "comfortable"
    widgets: Annotated[list[OwnerLayoutWidget], Field(min_length=1, max_length=24)]

    @model_validator(mode="after")
    def complete_bound(self) -> Self:
        if not self.name.strip() or type(self.schema_version) is not int:
            raise ValueError("The saved layout name or schema is invalid.")
        if len({widget.id for widget in self.widgets}) != len(self.widgets):
            raise ValueError("Widget identities must be distinct.")
        previews = [widget.kind for widget in self.widgets if widget.kind != "saved_view"]
        if len(set(previews)) != len(previews):
            raise ValueError("A financial preview may appear once.")
        if self.account_id is None and any(
            widget.selection is not None and widget.selection.kind != "workspace"
            for widget in self.widgets
        ):
            raise ValueError("This saved selection requires an explicit account.")
        if len(self.model_dump_json().encode("utf-8")) > 16 * 1024:
            raise ValueError("The complete layout exceeds its byte bound.")
        return self


class CreateOwnerLayoutRequest(OwnerLayoutSchema):
    content: OwnerLayoutContent


class UpdateOwnerLayoutRequest(CreateOwnerLayoutRequest):
    pass


class ArchiveOwnerLayoutRequest(OwnerLayoutSchema):
    pass


def _boolean_query(value: object) -> object:
    if value is True or value == "true":
        return True
    if value is False or value == "false":
        return False
    raise ValueError("A strict boolean selector is required.")


class OwnerLayoutPageQuery(OwnerLayoutSchema):
    limit: HistoricalPageLimit = 25
    cursor: Cursor | None = None
    include_archived: Annotated[StrictBool, BeforeValidator(_boolean_query)] = False


class OwnerLayoutDetailQuery(OwnerLayoutSchema):
    version_id: UUIDString | None = None


class OwnerLayoutVersionHeader(OwnerLayoutSchema):
    id: UUIDString
    number: LayoutVersionNumber
    created_at: AwareInstant
    content_digest: Digest


class OwnerLayoutSummary(OwnerLayoutSchema):
    id: UUIDString
    name: LayoutName
    revision: LayoutRevision
    state: Literal["active", "archived"]
    created_at: AwareInstant
    updated_at: AwareInstant
    availability: Literal["available", "restricted"]
    reason: Literal["account_unavailable", "selection_unavailable"] | None

    @model_validator(mode="after")
    def reason_shape(self) -> Self:
        if (self.availability == "available") != (self.reason is None):
            raise ValueError("The availability reason is inconsistent.")
        return self


class OwnerLayoutView(OwnerLayoutSchema):
    id: UUIDString
    revision: LayoutRevision
    state: Literal["active", "archived"]
    version: OwnerLayoutVersionHeader
    content: OwnerLayoutContent
    versions: Annotated[list[OwnerLayoutVersionHeader], Field(min_length=1, max_length=128)]


class OwnerLayoutArchiveReceipt(OwnerLayoutSchema):
    id: UUIDString
    revision: LayoutRevision
    state: Literal["archived"]
    archived_at: AwareInstant


class OwnerLayoutPage(OwnerLayoutSchema):
    items: Annotated[list[OwnerLayoutSummary], Field(max_length=32)]
    total: Annotated[StrictInt, Field(ge=0, le=32)]
    limit: HistoricalPageLimit
    next_cursor: Cursor | None
    read_cutoff_at: AwareInstant
