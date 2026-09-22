"""Explicit version-one preference codec with a closed, bounded record graph."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from datetime import date, datetime
from typing import Any, cast
from uuid import UUID

from .errors import DomainError, fail_validation
from .owner_layouts import (
    MAX_LAYOUT_CONTENT_BYTES,
    HistoricalLayoutSelection,
    LayoutRoute,
    LayoutRunFamily,
    LayoutSelection,
    LayoutWidgetKind,
    OwnerLayoutContent,
    OwnerLayoutWidget,
    ResearchLayoutSelection,
    RunLayoutSelection,
    WorkspaceLayoutSelection,
    layout_bound,
)
from .research import ResearchEventKind, ResearchReviewState
from .serialization import canonical_json
from .values import CurrencyCode


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        layout_bound(key not in value, "duplicate_key")
        value[key] = item
    return value


def _forbidden(_: str) -> None:
    fail_validation("A layout cannot contain binary numbers or nonfinite values.")


def _record(value: object, record: type[object]) -> dict[str, Any]:
    layout_bound(type(value) is dict, "record")
    obj = cast(dict[str, Any], value)
    expected = {field.name for field in fields(record)}  # type: ignore[arg-type]
    layout_bound(set(obj) == expected, "fields")
    return obj


def _uuid(value: object) -> UUID:
    layout_bound(type(value) is str, "id")
    result = UUID(cast(str, value))
    layout_bound(str(result) == value, "id")
    return result


def _day(value: object) -> date:
    layout_bound(type(value) is str, "date")
    result = date.fromisoformat(cast(str, value))
    layout_bound(result.isoformat() == value, "date")
    return result


def _instant(value: object) -> datetime:
    layout_bound(type(value) is str, "instant")
    return datetime.fromisoformat(cast(str, value).replace("Z", "+00:00"))


def layout_selection_from_value(value: object) -> LayoutSelection:
    layout_bound(type(value) is dict, "selection")
    kind = cast(dict[str, object], value).get("kind")
    if kind == "workspace":
        obj = _record(value, WorkspaceLayoutSelection)
        return WorkspaceLayoutSelection(route=LayoutRoute(obj["route"]), pane=obj["pane"])
    if kind == "historical":
        obj = _record(value, HistoricalLayoutSelection)
        obj = {
            **obj,
            "start_date": _day(obj["start_date"]),
            "end_date": _day(obj["end_date"]),
            "source_cutoff_at": _instant(obj["source_cutoff_at"]),
            "reporting_currency": CurrencyCode(obj["reporting_currency"]),
            "capture_id": None if obj["capture_id"] is None else _uuid(obj["capture_id"]),
        }
        return HistoricalLayoutSelection(**obj)
    if kind == "saved_run":
        obj = _record(value, RunLayoutSelection)
        return RunLayoutSelection(
            family=LayoutRunFamily(obj["family"]),
            run_id=_uuid(obj["run_id"]),
            pane=obj["pane"],
            snapshot_id=None if obj["snapshot_id"] is None else _uuid(obj["snapshot_id"]),
            source_cutoff_at=None
            if obj["source_cutoff_at"] is None
            else _instant(obj["source_cutoff_at"]),
            reporting_currency=None
            if obj["reporting_currency"] is None
            else CurrencyCode(obj["reporting_currency"]),
        )
    if kind == "research":
        obj = _record(value, ResearchLayoutSelection)
        return ResearchLayoutSelection(
            xray_run_id=_uuid(obj["xray_run_id"]),
            source_cutoff_at=_instant(obj["source_cutoff_at"]),
            entity_id=None if obj["entity_id"] is None else _uuid(obj["entity_id"]),
            event_kind=None if obj["event_kind"] is None else ResearchEventKind(obj["event_kind"]),
            review_state=ResearchReviewState(obj["review_state"]),
        )
    fail_validation("The saved view kind is unsupported.", field="kind")


def owner_layout_bytes(value: OwnerLayoutContent) -> bytes:
    layout_bound(type(value) is OwnerLayoutContent, "content")
    encoded = canonical_json(value).encode("utf-8")
    layout_bound(len(encoded) <= MAX_LAYOUT_CONTENT_BYTES, "content_bytes")
    return encoded


def owner_layout_digest(value: OwnerLayoutContent) -> str:
    return hashlib.sha256(b"owner-layout-content-v1\0" + owner_layout_bytes(value)).hexdigest()


def owner_layout_from_json(
    payload: bytes, *, expected_digest: str | None = None
) -> OwnerLayoutContent:
    layout_bound(
        type(payload) is bytes and len(payload) <= MAX_LAYOUT_CONTENT_BYTES, "content_bytes"
    )
    try:
        raw = json.loads(
            payload, object_pairs_hook=_pairs, parse_float=_forbidden, parse_constant=_forbidden
        )
        obj = _record(raw, OwnerLayoutContent)
        widgets = obj["widgets"]
        layout_bound(type(widgets) is list and 1 <= len(widgets) <= 24, "widgets")
        decoded = []
        for value in widgets:
            row = _record(value, OwnerLayoutWidget)
            decoded.append(
                OwnerLayoutWidget(
                    id=_uuid(row["id"]),
                    kind=LayoutWidgetKind(row["kind"]),
                    label=row["label"],
                    selection=None
                    if row["selection"] is None
                    else layout_selection_from_value(row["selection"]),
                )
            )
        result = OwnerLayoutContent(
            name=obj["name"],
            description=obj["description"],
            account_id=None if obj["account_id"] is None else _uuid(obj["account_id"]),
            widgets=tuple(decoded),
            columns=obj["columns"],
            density=obj["density"],
            schema_version=obj["schema_version"],
        )
        if expected_digest is not None:
            layout_bound(owner_layout_digest(result) == expected_digest, "content_digest")
        layout_bound(owner_layout_bytes(result) == payload, "canonical_content")
        return result
    except (DomainError, ValueError, TypeError, UnicodeError, RecursionError, KeyError):
        pass
    fail_validation("The retained saved layout is invalid.")
