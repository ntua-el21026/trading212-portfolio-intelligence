"""Independent closed preference and canonical version regression oracles."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from trading212_domain import owner_layouts as d
from trading212_domain.errors import DomainError
from trading212_domain.owner_layout_codec import (
    owner_layout_bytes,
    owner_layout_digest,
    owner_layout_from_json,
)
from trading212_domain.values import CurrencyCode

pytestmark = pytest.mark.unit
AT = datetime(2026, 9, 15, 12, 30, 20, 123456, tzinfo=UTC)


def content(*, account: UUID | None = None) -> d.OwnerLayoutContent:
    return d.OwnerLayoutContent(
        name="My daily review",
        description="Original saved view choices",
        account_id=account,
        widgets=(
            d.OwnerLayoutWidget(id=UUID(int=1), kind=d.LayoutWidgetKind.PORTFOLIO_SUMMARY),
            d.OwnerLayoutWidget(
                id=UUID(int=2),
                kind=d.LayoutWidgetKind.SAVED_VIEW,
                selection=d.WorkspaceLayoutSelection(route=d.LayoutRoute.QUALITY),
            ),
        ),
    )


def test_version_round_trip_is_byte_exact_and_identity_sensitive() -> None:
    original = content()
    encoded = owner_layout_bytes(original)
    assert (
        owner_layout_bytes(
            owner_layout_from_json(encoded, expected_digest=owner_layout_digest(original))
        )
        == encoded
    )
    assert json.loads(encoded)["widgets"][1]["selection"] == {
        "kind": "workspace",
        "pane": None,
        "route": "quality",
    }
    assert owner_layout_digest(replace(original, name="New name")) != owner_layout_digest(original)
    assert owner_layout_digest(
        replace(original, widgets=tuple(reversed(original.widgets)))
    ) != owner_layout_digest(original)


def test_all_closed_selections_round_trip_and_xray_original_pins_are_required() -> None:
    choices: tuple[d.LayoutSelection, ...] = (
        d.WorkspaceLayoutSelection(route=d.LayoutRoute.PROJECTIONS, pane="goals"),
        d.HistoricalLayoutSelection(
            route="income",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            source_cutoff_at=AT,
            reporting_currency=CurrencyCode("EUR"),
            view="cash_flows",
        ),
        d.RunLayoutSelection(family=d.LayoutRunFamily.SCENARIO, run_id=UUID(int=31)),
        d.RunLayoutSelection(
            family=d.LayoutRunFamily.XRAY,
            run_id=UUID(int=32),
            snapshot_id=UUID(int=33),
            source_cutoff_at=AT,
            reporting_currency=CurrencyCode("USD"),
        ),
        d.ResearchLayoutSelection(xray_run_id=UUID(int=34), source_cutoff_at=AT),
    )
    for choice in choices:
        value = replace(
            content(account=UUID(int=20)),
            widgets=(
                d.OwnerLayoutWidget(
                    id=UUID(int=35), kind=d.LayoutWidgetKind.SAVED_VIEW, selection=choice
                ),
            ),
        )
        assert owner_layout_from_json(owner_layout_bytes(value)) == value
    with pytest.raises(DomainError):
        d.RunLayoutSelection(family=d.LayoutRunFamily.XRAY, run_id=UUID(int=32))
    with pytest.raises(DomainError):
        d.RunLayoutSelection(
            family=d.LayoutRunFamily.RISK, run_id=UUID(int=32), snapshot_id=UUID(int=33)
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_root",
        "url",
        "query",
        "token",
        "float",
        "duplicate",
        "noncanonical",
        "foreign_kind",
        "too_many_widgets",
        "same_widget",
    ],
)
def test_unapproved_payloads_and_truncation_never_become_saved_preferences(mutation: str) -> None:
    value = json.loads(owner_layout_bytes(content()))
    if mutation == "unknown_root":
        value["financial_value"] = "100"
    elif mutation in {"url", "query", "token"}:
        value["widgets"][1]["selection"][mutation] = "private-unapproved"
    elif mutation == "float":
        value["columns"] = 1.0
    elif mutation == "foreign_kind":
        value["widgets"][1]["selection"]["kind"] = "generic_query"
    elif mutation == "too_many_widgets":
        value["widgets"] = value["widgets"] * 13
    elif mutation == "same_widget":
        value["widgets"][1]["id"] = value["widgets"][0]["id"]
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if mutation == "duplicate":
        encoded = encoded.replace(b'"name":', b'"name":"hidden","name":', 1)
    if mutation == "noncanonical":
        encoded += b" "
    with pytest.raises(DomainError):
        owner_layout_from_json(encoded)


def test_complete_utf8_bytes_not_widget_count_control_bound() -> None:
    widgets = tuple(
        d.OwnerLayoutWidget(
            id=UUID(int=100 + index),
            kind=d.LayoutWidgetKind.SAVED_VIEW,
            label="\u03b1" * 80,
            selection=d.WorkspaceLayoutSelection(route=d.LayoutRoute.OVERVIEW),
        )
        for index in range(24)
    )
    valid = replace(content(), widgets=widgets)
    assert owner_layout_from_json(owner_layout_bytes(valid)) == valid
    historical = d.HistoricalLayoutSelection(
        route="performance",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        source_cutoff_at=AT,
        reporting_currency=CurrencyCode("EUR"),
    )
    oversized = replace(
        valid,
        account_id=UUID(int=20),
        widgets=tuple(replace(widget, label="𐀀" * 80, selection=historical) for widget in widgets),
        description="𐀀" * 400,
        name="𐀀" * 80,
    )
    # Every field and row count is permitted; the complete UTF-8 document is not.
    with pytest.raises(DomainError):
        owner_layout_bytes(oversized)
    with pytest.raises(DomainError):
        owner_layout_from_json(b" " * 16385)


def test_account_free_templates_cannot_hide_private_run_or_historical_pins() -> None:
    with pytest.raises(DomainError):
        replace(
            content(),
            widgets=(
                d.OwnerLayoutWidget(
                    id=UUID(int=1),
                    kind=d.LayoutWidgetKind.SAVED_VIEW,
                    selection=d.RunLayoutSelection(
                        family=d.LayoutRunFamily.PROJECTION, run_id=UUID(int=99)
                    ),
                ),
            ),
        )
    with pytest.raises(DomainError):
        replace(
            content(),
            widgets=(content().widgets[0], replace(content().widgets[0], id=UUID(int=99))),
        )
