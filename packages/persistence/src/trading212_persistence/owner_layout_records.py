"""Exact typed layout-to-column projection; no arbitrary query documents."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any
from uuid import UUID

from trading212_domain import owner_layouts as d
from trading212_domain.owner_layout_codec import owner_layout_from_json

from .owner_layout_models import SavedLayoutWidgetModel, SavedViewVersionModel

SELECTION_COLUMNS = (
    "selection_kind",
    "route",
    "pane",
    "run_family",
    "risk_run_id",
    "scenario_run_id",
    "projection_run_id",
    "xray_run_id",
    "snapshot_id",
    "capture_id",
    "entity_id",
    "start_date",
    "end_date",
    "source_cutoff_at",
    "reporting_currency",
    "method",
    "frequency",
    "knowledge",
    "coverage",
    "view",
    "grouping",
    "flow_kind",
    "rolling",
    "calendar",
    "event_kind",
    "review_state",
)
type LayoutColumn = str | int | UUID | date | datetime | None


def layout_widget_columns(widget: d.OwnerLayoutWidget) -> dict[str, LayoutColumn]:
    values: dict[str, LayoutColumn] = dict.fromkeys(SELECTION_COLUMNS)
    values.update(widget_id=widget.id, kind=widget.kind.value, label=widget.label)
    choice = widget.selection
    if choice is None:
        return values
    values["selection_kind"] = choice.kind
    if isinstance(choice, d.WorkspaceLayoutSelection):
        values.update(route=choice.route.value, pane=choice.pane)
    elif isinstance(choice, d.HistoricalLayoutSelection):
        values.update(
            route=choice.route,
            start_date=choice.start_date,
            end_date=choice.end_date,
            source_cutoff_at=choice.source_cutoff_at,
            reporting_currency=choice.reporting_currency.value,
            method=choice.method,
            frequency=choice.frequency,
            knowledge=choice.knowledge,
            coverage=choice.coverage,
            view=choice.view,
            grouping=choice.grouping,
            flow_kind=choice.flow_kind,
            rolling=choice.rolling,
            calendar=choice.calendar,
            capture_id=choice.capture_id,
        )
    elif isinstance(choice, d.RunLayoutSelection):
        values.update(
            run_family=choice.family.value,
            pane=choice.pane,
            snapshot_id=choice.snapshot_id,
            source_cutoff_at=choice.source_cutoff_at,
            reporting_currency=None
            if choice.reporting_currency is None
            else choice.reporting_currency.value,
        )
        values[f"{choice.family.value}_run_id"] = choice.run_id
    elif isinstance(choice, d.ResearchLayoutSelection):
        values.update(
            xray_run_id=choice.xray_run_id,
            source_cutoff_at=choice.source_cutoff_at,
            entity_id=choice.entity_id,
            event_kind=None if choice.event_kind is None else choice.event_kind.value,
            review_state=choice.review_state.value,
        )
    return values


def layout_widget_models(
    content: d.OwnerLayoutContent, *, owner: UUID, layout: UUID, version: UUID, at: datetime
) -> tuple[SavedLayoutWidgetModel, ...]:
    return tuple(
        SavedLayoutWidgetModel(
            owner_id=owner,
            layout_id=layout,
            version_id=version,
            ordinal=ordinal,
            created_at=at,
            **layout_widget_columns(widget),
        )
        for ordinal, widget in enumerate(content.widgets)
    )


def decode_layout_version(
    version: SavedViewVersionModel, payload: bytes, widgets: tuple[SavedLayoutWidgetModel, ...]
) -> d.OwnerLayoutContent:
    """Called only after account/source metadata authorization in the same transaction."""
    content = owner_layout_from_json(payload, expected_digest=version.content_digest)
    d.layout_bound(
        (
            content.name,
            content.description,
            content.account_id,
            content.columns,
            content.density,
            content.schema_version,
        )
        == (
            version.name,
            version.description,
            version.account_id,
            version.columns,
            version.density,
            version.schema_version,
        ),
        "version",
    )
    d.layout_bound(len(widgets) == len(content.widgets), "widgets")
    for index, (row, widget) in enumerate(zip(widgets, content.widgets, strict=True)):
        d.layout_bound(
            row.owner_id == version.owner_id
            and row.layout_id == version.layout_id
            and row.version_id == version.id
            and row.ordinal == index,
            "widget_parent",
        )
        d.layout_bound(
            all(getattr(row, key) == value for key, value in layout_widget_columns(widget).items()),
            "widget_projection",
        )
    return content


def layout_reference_record(
    account: UUID | None, widget: SavedLayoutWidgetModel | Mapping[str, Any]
) -> dict[str, Any]:
    """Only the closed identity fields consumed by the metadata authority SQL."""

    def field(key: str) -> Any:
        return widget[key] if isinstance(widget, Mapping) else getattr(widget, key)

    return {
        "account_id": None if account is None else str(account),
        **{
            key: None if field(key) is None else str(field(key))
            for key in (
                "risk_run_id",
                "scenario_run_id",
                "projection_run_id",
                "xray_run_id",
                "snapshot_id",
                "capture_id",
                "entity_id",
            )
        },
        **{key: field(key) for key in ("selection_kind", "route", "knowledge")},
        **{
            key: None if field(key) is None else field(key).isoformat()
            for key in ("start_date", "end_date", "source_cutoff_at")
        },
        "reporting_currency": field("reporting_currency"),
    }
