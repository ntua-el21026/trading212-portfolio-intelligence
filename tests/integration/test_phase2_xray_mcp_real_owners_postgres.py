"""Both actual owners can read held-fund runs while mismatched saved snapshots fail closed."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient
from trading212_mcp.server import create_runtime
from trading212_mcp.settings import McpSettings
from trading212_persistence.xray_run_models import XrayInputSnapshotModel, XrayRunModel
from trading212_security.principals import Scope

from tests.integration.phase2_authorization_cases import SETTINGS, AccountPin, retained_state
from tests.integration.phase2_authorization_cases import owner_grid as owner_grid
from tests.integration.phase2_mcp_owner_transport import (
    ScopedGridBearer,
    call,
    denied,
    mapping,
    payload,
)
from tests.integration.phase2_mcp_xray_owners import XrayOwners
from tests.integration.phase2_mcp_xray_owners import xray_owners as xray_owners
from tests.integration.test_alert_postgres import alert_database as alert_database

pytestmark = pytest.mark.integration


class Tool(StrEnum):
    EXPOSURE = "get_effective_exposure"
    OVERLAP = "get_etf_overlap"


def arguments(case: XrayOwners, tool: Tool, pin: AccountPin) -> dict[str, object]:
    result: dict[str, object] = {
        "account_id": str(pin.account_id),
        "snapshot_id": str(pin.snapshot_id),
        "source_cutoff_at": case.grid.at.isoformat(),
    }
    if tool is Tool.EXPOSURE:
        result.update(reporting_currency="EUR", dimension="company")
    else:
        result.update(left_fund_id=case.funds[0], right_fund_id=case.funds[1])
    return result


@pytest.mark.parametrize("tool", tuple(Tool), ids=lambda tool: tool.value)
def test_xray_mcp_real_owner_and_account_associations_with_retained_positive_runs(
    xray_owners: XrayOwners,
    tool: Tool,
) -> None:
    case = xray_owners
    grid = case.grid
    bearer = ScopedGridBearer(grid.actors)
    runtime = create_runtime(
        security_settings=SETTINGS.model_copy(update={"issuer": "https://issuer.example"}),
        mcp_settings=McpSettings.model_validate({"public_base_url": "https://portfolio.example"}),
        service=grid.portfolio,
        xray_service=case.service,
        bearer_authenticator=bearer,
        clock=lambda: grid.at,
    )
    tables = (
        XrayInputSnapshotModel.__tablename__,
        XrayRunModel.__tablename__,
        "analytics_runs",
        "portfolio_snapshots",
        "source_records",
    )
    with TestClient(runtime.asgi_app(), base_url="http://localhost") as client:
        for actor, other in (grid.actors, tuple(reversed(grid.actors))):
            for original in actor.accounts:
                pin = case.pins[original.account_id]
                request = arguments(case, tool, pin)
                value = payload(call(client, actor, tool.value, request))
                context = mapping(value["context"])
                assert context["account_id"] == str(pin.account_id)
                assert context["snapshot_id"] == str(pin.snapshot_id)
                # Persisted canonical runs, not a synthetic service return, are the control.
                with grid.sessions() as session:
                    row = session.execute(
                        select(XrayRunModel, XrayInputSnapshotModel)
                        .join(
                            XrayInputSnapshotModel,
                            XrayInputSnapshotModel.id == XrayRunModel.input_id,
                        )
                        .where(XrayRunModel.id == UUID(str(context["run_id"])))
                    ).one()
                    assert row[0].owner_id == row[1].owner_id == UUID(actor.principal.owner_id)
                    assert row[1].account_id == pin.account_id
                before = retained_state(grid, tables)
                for scope in (Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ):
                    bearer.omitted = scope
                    try:
                        denied(
                            call(client, actor, tool.value, request),
                            "ACCESS_DENIED",
                            (
                                str(pin.snapshot_id),
                                str(context["run_id"]),
                            ),
                        )
                    finally:
                        bearer.omitted = None
                    assert retained_state(grid, tables) == before
            own = case.pins[actor.accounts[0].account_id]
            second = case.pins[actor.accounts[1].account_id]
            foreign = case.pins[other.accounts[0].account_id]
            request = arguments(case, tool, own)
            before = retained_state(grid, tables)
            for pin in (foreign, AccountPin(uuid4(), foreign.snapshot_id)):
                denied(
                    call(client, actor, tool.value, arguments(case, tool, pin)),
                    "NOT_FOUND",
                    (
                        str(pin.account_id),
                        str(pin.snapshot_id),
                        other.principal.owner_id,
                    ),
                )
            for snapshot in (second.snapshot_id, foreign.snapshot_id, uuid4()):
                denied(
                    call(
                        client,
                        actor,
                        tool.value,
                        {
                            **request,
                            "snapshot_id": str(snapshot),
                        },
                    ),
                    "NOT_FOUND",
                    (str(snapshot),),
                )
            assert retained_state(grid, tables) == before
            if tool is Tool.OVERLAP:
                # Existing tests cover the full non-held-fund and license matrix; this
                # checks it remains enforced for the separately provisioned second owner.
                nonheld = str(uuid4())
                denied(
                    call(
                        client,
                        actor,
                        tool.value,
                        {
                            **request,
                            "left_fund_id": nonheld,
                        },
                    ),
                    "VALIDATION_FAILED",
                    (nonheld,),
                )
                assert retained_state(grid, tables) == before
