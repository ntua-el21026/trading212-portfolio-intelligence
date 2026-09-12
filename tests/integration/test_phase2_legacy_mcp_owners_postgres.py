"""The original nine MCP tools enforce actual owner and snapshot associations."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from trading212_persistence.models import DividendModel, SnapshotPositionModel, TransactionModel
from trading212_security.principals import Scope

from tests.integration.phase2_authorization_cases import AccountPin, OwnerGrid, retained_state
from tests.integration.phase2_authorization_cases import owner_grid as owner_grid
from tests.integration.phase2_mcp_owner_transport import (
    call,
    denied,
    items,
    legacy_client,
    mapping,
    payload,
)
from tests.integration.test_alert_postgres import alert_database as alert_database

pytestmark = pytest.mark.integration
STATE = (
    "portfolio_snapshots",
    "source_records",
    "ingestion_runs",
    "transactions",
    "dividends",
    "snapshot_positions",
    "snapshot_cash",
    "calculation_runs",
    "reconciliation_runs",
    "reconciliation_discrepancies",
)


class Tool(StrEnum):
    SUMMARY = "get_account_summary"
    SNAPSHOT = "get_portfolio_snapshot"
    POSITIONS = "list_positions"
    TRANSACTIONS = "list_recent_transactions"
    DIVIDENDS = "get_dividend_summary"
    ALLOCATION = "get_direct_allocation"
    COMPARE = "compare_portfolio_snapshots"
    RECONCILIATION = "get_reconciliation_status"
    QUALITY = "get_data_quality_summary"


def arguments(tool: Tool, pin: AccountPin) -> dict[str, object]:
    result: dict[str, object] = {"account_id": str(pin.account_id)}
    if tool is Tool.SNAPSHOT:
        result["snapshot_id"] = str(pin.snapshot_id)
    elif tool is Tool.COMPARE:
        # A zero-length comparison is an intentional identity positive control.
        result.update(start_snapshot_id=str(pin.snapshot_id), end_snapshot_id=str(pin.snapshot_id))
    elif tool in {Tool.TRANSACTIONS, Tool.DIVIDENDS}:
        result.update(start_date="2026-01-01", end_date="2026-09-07")
    return result


def assert_retained_rows(
    grid: OwnerGrid,
    tool: Tool,
    pin: AccountPin,
    value: dict[str, object],
) -> None:
    if tool is Tool.POSITIONS:
        rows = items(value["positions"])
        # Position wire IDs are listing IDs; membership is bound by the saved snapshot.
        statement = select(SnapshotPositionModel.listing_id).where(
            SnapshotPositionModel.snapshot_id == pin.snapshot_id,
        )
    elif tool is Tool.TRANSACTIONS:
        rows = items(value["transactions"])
        statement = select(TransactionModel.id).where(
            TransactionModel.broker_account_id == pin.account_id,
        )
    elif tool is Tool.DIVIDENDS:
        rows = items(value["recent_dividends"])
        statement = select(DividendModel.id).where(
            DividendModel.broker_account_id == pin.account_id,
        )
    else:
        return
    identifiers: set[UUID] = set()
    for row in rows:
        identifier = row["id"]
        assert isinstance(identifier, str)
        identifiers.add(UUID(identifier))
    assert identifiers
    with grid.sessions() as session:
        assert identifiers <= set(session.scalars(statement))


@pytest.mark.parametrize("tool", tuple(Tool), ids=lambda tool: tool.value)
def test_original_nine_real_owners_and_both_owned_accounts(
    owner_grid: OwnerGrid,
    tool: Tool,
) -> None:
    grid = owner_grid
    with legacy_client(grid) as (client, bearer):
        for actor, other in (grid.actors, tuple(reversed(grid.actors))):
            # Both actual owners can access each of their two real materialized accounts.
            for pin in actor.accounts:
                value = payload(call(client, actor, tool.value, arguments(tool, pin)))
                assert value
                assert_retained_rows(grid, tool, pin, value)
                if tool is Tool.SUMMARY:
                    assert mapping(value["account"])["id"] == str(pin.account_id)
                elif tool is Tool.SNAPSHOT:
                    assert value["id"] == str(pin.snapshot_id)
                elif tool is Tool.COMPARE:
                    assert mapping(value["start"])["id"] == str(pin.snapshot_id)
                    assert mapping(value["end"])["id"] == str(pin.snapshot_id)
                private = (
                    other.principal.owner_id,
                    str(other.accounts[0].account_id),
                    str(other.accounts[0].snapshot_id),
                )
                assert all(identifier not in str(value) for identifier in private)
            before = retained_state(grid, STATE)
            required = (
                (Scope.PORTFOLIO_READ, Scope.ACTIVITY_READ)
                if tool
                in (
                    Tool.TRANSACTIONS,
                    Tool.DIVIDENDS,
                    Tool.QUALITY,
                )
                else (Scope.PORTFOLIO_READ,)
            )
            for scope in required:
                bearer.omitted = scope
                try:
                    denied(
                        call(client, actor, tool.value, arguments(tool, actor.accounts[0])),
                        "ACCESS_DENIED",
                        (str(actor.accounts[0].account_id),),
                    )
                finally:
                    bearer.omitted = None
                assert retained_state(grid, STATE) == before
            foreign = arguments(tool, other.accounts[0])
            denied(
                call(client, actor, tool.value, foreign),
                "ACCESS_DENIED",
                (
                    other.principal.owner_id,
                    str(other.accounts[0].account_id),
                    str(other.accounts[0].snapshot_id),
                ),
            )
            missing = {**foreign, "account_id": str(uuid4())}
            denied(
                call(client, actor, tool.value, missing),
                "ACCESS_DENIED",
                (
                    str(missing["account_id"]),
                    str(other.accounts[0].snapshot_id),
                ),
            )
            assert retained_state(grid, STATE) == before


@pytest.mark.parametrize("field", ("snapshot_id", "start_snapshot_id", "end_snapshot_id"))
def test_legacy_snapshot_pins_cannot_cross_real_owner_or_account(
    owner_grid: OwnerGrid,
    field: str,
) -> None:
    grid = owner_grid
    tool = Tool.SNAPSHOT if field == "snapshot_id" else Tool.COMPARE
    with legacy_client(grid) as (client, _):
        for actor, other in (grid.actors, tuple(reversed(grid.actors))):
            own, second = actor.accounts
            payload(call(client, actor, tool.value, arguments(tool, own)))
            payload(call(client, actor, tool.value, arguments(tool, second)))
            before = retained_state(grid, STATE)
            for bad in (second.snapshot_id, other.accounts[0].snapshot_id, uuid4()):
                request = {**arguments(tool, own), field: str(bad)}
                denied(call(client, actor, tool.value, request), "NOT_FOUND", (str(bad),))
            assert retained_state(grid, STATE) == before


def test_legacy_transaction_cursor_keeps_owner_account_and_filter_binding(
    owner_grid: OwnerGrid,
) -> None:
    grid = owner_grid
    tool = Tool.TRANSACTIONS
    with legacy_client(grid) as (client, _):
        for actor, other in (grid.actors, tuple(reversed(grid.actors))):
            request = {**arguments(tool, actor.accounts[0]), "limit": 1}
            first = call(client, actor, tool.value, request)
            payload(first)
            assert first.structured_content is not None
            cursor = mapping(first.structured_content["pagination"])["next_cursor"]
            assert isinstance(cursor, str)
            payload(call(client, actor, tool.value, {**request, "cursor": cursor}))
            before = retained_state(grid, STATE)
            for caller, changed in (
                (actor, {"account_id": str(actor.accounts[1].account_id)}),
                (other, {"account_id": str(other.accounts[0].account_id)}),
                (actor, {"start_date": "2026-01-02"}),
            ):
                denied(
                    call(
                        client,
                        caller,
                        tool.value,
                        {
                            **request,
                            **changed,
                            "cursor": cursor,
                        },
                    ),
                    "CURSOR_INVALID",
                    (cursor, str(actor.accounts[0].snapshot_id)),
                )
            assert retained_state(grid, STATE) == before
