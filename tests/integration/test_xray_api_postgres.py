"""Real PostgreSQL X-ray parity, conditional reads and cross-interface access boundaries."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult
from sqlalchemy import func, select
from trading212_api.main import create_app
from trading212_api_contracts import xray as wire
from trading212_domain.sources import LicensePermission
from trading212_mcp.auth import PrincipalResolver
from trading212_mcp.server import create_runtime
from trading212_persistence import PostgresPortfolioService
from trading212_persistence import xray_read_store as read_store
from trading212_persistence import xray_run_store as run_store
from trading212_persistence.source_service import PostgresSourceService
from trading212_persistence.xray_run_models import XrayInputSnapshotModel, XrayRunModel
from trading212_security.principals import AuthenticationError, Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID, XRAY_AT, xray_id
from trading212_worker.xray_seed import XRAY_CURSOR_KEY
from trading212_worker.xray_source_fixture import xray_license

from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration
ORIGIN = "https://testserver"
HEADERS = {"Authorization": "Bearer xray-owned"}
EXPOSURE_PATH = f"/api/v1/accounts/{XRAY_ACCOUNT_ID}/effective-exposure"
OVERLAP_PATH = f"/api/v1/accounts/{XRAY_ACCOUNT_ID}/etf-overlap"


class _Bearer:
    def __init__(self, case: XrayReadCase) -> None:
        self.principals = {
            "xray-owned": case.principal,
            "xray-foreign": replace(case.principal, owner_id=str(uuid4())),
            "xray-analytics-only": replace(
                case.principal, scopes=frozenset({Scope.ANALYTICS_READ})
            ),
            "xray-portfolio-only": replace(
                case.principal, scopes=frozenset({Scope.PORTFOLIO_READ})
            ),
        }

    async def authenticate(self, token: str) -> Principal:
        principal = self.principals.get(token)
        if principal is None:
            raise AuthenticationError("Invalid synthetic credential.")
        return principal


def _runtime(case: XrayReadCase) -> tuple[FastAPI, MCPServer[Any], _Bearer]:
    settings = SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=True,
        allowed_hosts=("testserver",),
        allowed_origins=(ORIGIN,),
    )
    portfolio = PostgresPortfolioService(
        sessions=case.sessions,
        cursor_signing_key=XRAY_CURSOR_KEY,
        clock=lambda: case.now[0],
    )
    bearer = _Bearer(case)
    api = create_app(
        settings=settings,
        service=portfolio,
        xray_service=case.service,
        bearer_authenticator=bearer,
        clock=lambda: case.now[0],
    )
    mcp = create_runtime(
        security_settings=settings,
        service=portfolio,
        xray_service=case.service,
        clock=lambda: case.now[0],
    ).server
    return api, mcp, bearer


def _query(case: XrayReadCase, run_id: str | None = None) -> dict[str, str]:
    result = {
        "snapshot_id": case.seed["snapshot_id"],
        "source_cutoff_at": XRAY_AT.isoformat(),
        "reporting_currency": "EUR",
    }
    if run_id is not None:
        result["run_id"] = run_id
    return result


def _tool_query(case: XrayReadCase, name: str) -> dict[str, Any]:
    if name == "get_effective_exposure":
        return {"account_id": XRAY_ACCOUNT_ID, **_query(case)}
    return {
        "account_id": XRAY_ACCOUNT_ID,
        "snapshot_id": case.seed["snapshot_id"],
        "source_cutoff_at": XRAY_AT.isoformat(),
        "left_fund_id": case.funds[0],
        "right_fund_id": case.funds[1],
        "top_n": 1,
    }


def _overlap_query(case: XrayReadCase, run_id: str) -> httpx.QueryParams:
    return httpx.QueryParams(
        tuple(_query(case, run_id).items())
        + tuple(("fund_ids", identifier) for identifier in case.funds)
    )


async def _tool(server: MCPServer[Any], name: str, arguments: dict[str, Any]) -> CallToolResult:
    result = await server.call_tool(name, arguments)
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None
    return result


def _run_counts(case: XrayReadCase) -> tuple[int, int]:
    with case.sessions() as session:
        return (
            session.scalar(select(func.count()).select_from(XrayInputSnapshotModel)) or 0,
            session.scalar(select(func.count()).select_from(XrayRunModel)) or 0,
        )


def _no_private_values(text: str, case: XrayReadCase, *values: str) -> None:
    for value in (
        XRAY_ACCOUNT_ID,
        case.principal.owner_id,
        case.seed["snapshot_id"],
        case.seed["fund-a_snapshot_id"],
        "Synthetic Alpha",
        "Synthetic Atlas Fund",
        "private-xray-canary",
        *values,
    ):
        assert value not in text


async def test_http_and_mcp_share_the_canonical_run_values_sources_and_constituent_pages(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    api, mcp, _ = _runtime(case)
    before = _run_counts(case)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url=ORIGIN, headers=HEADERS
    ) as client:
        response = await client.get(EXPOSURE_PATH, params=_query(case))
        assert response.status_code == 200, response.text
        wire.XrayExposuresResponse.model_validate(response.json())
        exposure = response.json()
        run = exposure["context"]["run_id"]
        assert response.headers["cache-control"] == "private, no-store"
        assert exposure["summary"]["total"]["value"] == {"amount": "1000", "currency": "EUR"}
        assert exposure["summary"]["company_known_weight"]["value"] == "0.95"
        assert exposure["summary"]["unresolved_weight"]["value"] == "0.05"
        assert exposure["summary"]["duplicated_exposure"]["value"] == "0.41"
        assert exposure["summary"]["hhi"]["value"] == "0.4657"
        alpha = next(
            row
            for row in exposure["exposures"]["items"]
            if row["bucket_key"] == xray_id("entity/alpha")
        )
        assert alpha["effective"]["value"] == {"amount": "560", "currency": "EUR"}
        tool = await _tool(
            mcp, "get_effective_exposure", _tool_query(case, "get_effective_exposure")
        )
        assert not tool.is_error, tool
        assert tool.structured_content is not None
        assert tool.structured_content["data"] == exposure
        assert tool.structured_content["selection"] == {"total": 2, "returned": 2, "omitted": 0}

        paths = await client.get(
            EXPOSURE_PATH,
            params={**_query(case, run), "view": "paths", "exposure_id": alpha["id"]},
        )
        assert paths.status_code == 200, paths.text
        wire.XrayPathsResponse.model_validate(paths.json())
        path_rows = paths.json()["paths"]["items"]
        assert len(path_rows) == 6
        assert all(
            [source["id"] for source in row["sources"]] == row["source_reference_ids"]
            for row in path_rows
        )
        assert any(source["kind"] == "broker_fx" for row in path_rows for source in row["sources"])

        response = await client.get(OVERLAP_PATH, params=_overlap_query(case, run))
        assert response.status_code == 200, response.text
        wire.XrayOverlapPairsResponse.model_validate(response.json())
        pairs = response.json()
        pair = pairs["pairs"]["items"][0]
        assert pairs["context"] == exposure["context"]
        assert pair["overlap"]["value"] == "0.5"
        assert pair["overlap"]["bound"] == "lower_bound"
        tool = await _tool(mcp, "get_etf_overlap", _tool_query(case, "get_etf_overlap"))
        assert not tool.is_error, tool
        assert tool.structured_content is not None
        top = tool.structured_content["data"]
        wire.XrayMcpTopPairResponse.model_validate(top)
        assert top["context"] == exposure["context"]
        assert top["summary"] == exposure["summary"]
        for key in ("left", "right", "overlap", "common_entity_count"):
            assert top["pair"][key] == pair[key]
        assert (top["total_count"], top["returned_count"], top["omitted_count"]) == (2, 1, 1)
        assert top["common_entities"][0]["entity_id"] == xray_id("entity/beta")
        assert top["common_entities"][0]["common_weight"]["value"] == "0.3"
        assert top["omitted_common_weight"]["value"] == "0.2"

        source_path = f"/api/v1/constituent-snapshots/{case.seed['fund-a_snapshot_id']}"
        scope = {"account_id": XRAY_ACCOUNT_ID, "run_id": run}
        header = await client.get(source_path, params=scope)
        assert header.status_code == 200, header.text
        wire.XrayConstituentSnapshotHeader.model_validate(header.json())
        assert header.json()["known_weight"] == "0.9"
        assert header.json()["unresolved_weight"] == "0.1"
        assert header.json()["holding_count"] == 3
        assert header.json()["license"]["id"] == xray_license().id
        first = await client.get(source_path + "/holdings", params={**scope, "limit": 1})
        assert first.status_code == 200, first.text
        wire.XrayConstituentHoldingPage.model_validate(first.json())
        assert first.json()["total"] == 3 and first.json()["next_cursor"] is not None
        tail = await client.get(
            source_path + "/holdings",
            params={**scope, "limit": 100, "cursor": first.json()["next_cursor"]},
        )
        assert tail.status_code == 200, tail.text
        wire.XrayConstituentHoldingPage.model_validate(tail.json())
        assert tail.json()["next_cursor"] is None
        holdings = first.json()["items"] + tail.json()["items"]
        assert len({row["id"] for row in holdings}) == 3
        assert {row["source_key"]: row["weight"] for row in holdings} == {
            "atlas-alpha": "0.6",
            "atlas-beta": "0.3",
            "atlas-unresolved": "0.1",
        }
    assert _run_counts(case) == (before[0] + 1, before[1] + 1)


async def test_current_license_denial_precedes_matching_etags_cursors_and_retained_decode(
    xray_read_case: XrayReadCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = xray_read_case
    api, mcp, _ = _runtime(case)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url=ORIGIN, headers=HEADERS
    ) as client:
        response = await client.get(EXPOSURE_PATH, params={**_query(case), "limit": 1})
        assert response.status_code == 200, response.text
        body = response.json()
        run = body["context"]["run_id"]
        cursor = body["exposures"]["next_cursor"]
        assert cursor is not None
        pinned: dict[str, str | int] = {**_query(case, run), "limit": 1}
        source_path = f"/api/v1/constituent-snapshots/{case.seed['fund-a_snapshot_id']}"
        scope = {"account_id": XRAY_ACCOUNT_ID, "run_id": run}
        header = await client.get(source_path, params=scope)
        holdings = await client.get(source_path + "/holdings", params={**scope, "limit": 1})
        overlap = await client.get(OVERLAP_PATH, params=_overlap_query(case, run))
        assert header.status_code == holdings.status_code == overlap.status_code == 200
        holding_cursor = holdings.json()["next_cursor"]
        assert holding_cursor is not None
        for path, params, original in (
            (EXPOSURE_PATH, httpx.QueryParams(pinned), response),
            (OVERLAP_PATH, _overlap_query(case, run), overlap),
            (source_path, httpx.QueryParams(scope), header),
            (source_path + "/holdings", httpx.QueryParams({**scope, "limit": 1}), holdings),
        ):
            unchanged = await client.get(
                path, params=params, headers={"If-None-Match": original.headers["etag"]}
            )
            assert unchanged.status_code == 304 and unchanged.content == b""
        before = _run_counts(case)
        forbidden_decode = Mock(side_effect=AssertionError("Revoked retained payload was decoded."))
        for name in (
            "decode_xray_component",
            "decode_xray_input",
            "decode_xray_policy",
            "decode_xray_result",
        ):
            monkeypatch.setattr(run_store, name, forbidden_decode)
        monkeypatch.setattr(read_store, "decode_xray_component", forbidden_decode)
        source_service = PostgresSourceService(
            sessions=case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now[0]
        )
        for index, permission in enumerate((LicensePermission.DENIED, LicensePermission.UNKNOWN)):
            case.now[0] += timedelta(seconds=1)
            await source_service.register_source_license(
                case.principal,
                replace(
                    xray_license(),
                    id=str(uuid4()),
                    version=f"synthetic-http-revoked-{index}",
                    effective_at=case.now[0],
                    display=permission,
                ),
                idempotency_key=f"xray-http-revoke-{index}",
                correlation_id="xray-http-revoke",
            )
            for path, params, etag in (
                (EXPOSURE_PATH, httpx.QueryParams(pinned), response.headers["etag"]),
                (
                    EXPOSURE_PATH,
                    httpx.QueryParams({**pinned, "cursor": cursor}),
                    response.headers["etag"],
                ),
                (OVERLAP_PATH, _overlap_query(case, run), overlap.headers["etag"]),
                (source_path, httpx.QueryParams(scope), header.headers["etag"]),
                (source_path, httpx.QueryParams(), header.headers["etag"]),
                (
                    source_path + "/holdings",
                    httpx.QueryParams({**scope, "cursor": holding_cursor, "limit": 1}),
                    holdings.headers["etag"],
                ),
            ):
                denied = await client.get(path, params=params, headers={"If-None-Match": etag})
                assert denied.status_code == 403, denied.text
                assert denied.json()["error"]["code"] == "ACCESS_DENIED"
                assert "etag" not in denied.headers
                _no_private_values(denied.text, case, run, body["context"]["input_digest"])
            for name in ("get_effective_exposure", "get_etf_overlap"):
                arguments = _tool_query(case, name)
                if name == "get_effective_exposure":
                    arguments.update(cursor=cursor, limit=1)
                denied_tool = await _tool(mcp, name, arguments)
                assert denied_tool.is_error
                assert denied_tool.structured_content is not None
                assert denied_tool.structured_content["data"] is None
                assert denied_tool.structured_content["selection"] is None
                assert denied_tool.structured_content["error"]["code"] == "ACCESS_DENIED"
                _no_private_values(denied_tool.model_dump_json(), case, run)
            forbidden_decode.assert_not_called()
            assert _run_counts(case) == before


async def test_owner_scope_and_authentication_denials_do_not_disclose_retained_resources(
    xray_read_case: XrayReadCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = xray_read_case
    api, mcp, bearer = _runtime(case)
    current: list[Principal | None] = [case.principal]

    async def principal(_: PrincipalResolver) -> Principal:
        if current[0] is None:
            raise AuthenticationError("private-xray-canary")
        return current[0]

    monkeypatch.setattr(PrincipalResolver, "resolve", principal)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        original = await client.get(EXPOSURE_PATH, params=_query(case), headers=HEADERS)
        assert original.status_code == 200, original.text
        run = original.json()["context"]["run_id"]
        source_path = f"/api/v1/constituent-snapshots/{case.seed['fund-a_snapshot_id']}"
        source_scope = {"account_id": XRAY_ACCOUNT_ID, "run_id": run}
        before = _run_counts(case)
        for token, status in (
            ("xray-foreign", 404),
            ("xray-analytics-only", 403),
            ("xray-portfolio-only", 403),
        ):
            headers = {
                "Authorization": f"Bearer {token}",
                "If-None-Match": original.headers["etag"],
            }
            for path, params in (
                (EXPOSURE_PATH, httpx.QueryParams(_query(case, run))),
                (OVERLAP_PATH, _overlap_query(case, run)),
                (source_path, httpx.QueryParams(source_scope)),
                (source_path + "/holdings", httpx.QueryParams(source_scope)),
            ):
                denied = await client.get(path, params=params, headers=headers)
                assert denied.status_code == status, denied.text
                _no_private_values(denied.text, case, run)
            current[0] = bearer.principals[token]
            for name in ("get_effective_exposure", "get_etf_overlap"):
                result = await _tool(mcp, name, _tool_query(case, name))
                assert result.is_error
                assert result.structured_content is not None
                assert result.structured_content["data"] is None
                assert result.structured_content["selection"] is None
                assert result.structured_content["error"]["code"] == (
                    "NOT_FOUND" if token == "xray-foreign" else "ACCESS_DENIED"
                )
                _no_private_values(result.model_dump_json(), case, run)
        # Direct source diagnostics require analytics scope, without adding portfolio scope.
        direct = await client.get(
            source_path, headers={"Authorization": "Bearer xray-analytics-only"}
        )
        assert direct.status_code == 200, direct.text
        for token in ("xray-foreign", "xray-portfolio-only"):
            direct = await client.get(source_path, headers={"Authorization": f"Bearer {token}"})
            assert direct.status_code == (404 if token == "xray-foreign" else 403)
            _no_private_values(direct.text, case, run)
        malformed = await client.get(
            EXPOSURE_PATH,
            params={"private-xray-canary": "private-xray-canary"},
            headers={"Authorization": "Bearer xray-portfolio-only"},
        )
        assert malformed.status_code == 403
        _no_private_values(malformed.text, case)
        unauthenticated = await client.get(EXPOSURE_PATH, params=_query(case))
        assert unauthenticated.status_code == 401
        _no_private_values(unauthenticated.text, case, run)
        current[0] = None
        for name in ("get_effective_exposure", "get_etf_overlap"):
            result = await _tool(mcp, name, _tool_query(case, name))
            assert result.is_error
            assert result.structured_content is not None
            assert result.structured_content["error"]["code"] == "AUTHENTICATION_REQUIRED"
            _no_private_values(result.model_dump_json(), case, run)
        assert _run_counts(case) == before
