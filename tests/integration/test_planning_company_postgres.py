"""Real company publication, reads, permissions and canonical parity."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Never
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from starlette.requests import Request
from trading212_api.planning_schemas import planning_response
from trading212_api_contracts import planning as wire
from trading212_application import planning as app
from trading212_application import targets as targets_app
from trading212_application.queries import CursorValidationError
from trading212_domain import CurrencyCode, build_synthetic_identity
from trading212_domain.planning_company import PlanningDriftRowView
from trading212_domain.sources import LicensePermission
from trading212_domain.targets import TargetContent, TargetNode, TargetNodeKind
from trading212_mcp.planning_gateway import _payload
from trading212_persistence import planning_company_store, planning_service, xray_run_store
from trading212_persistence.planning_models import AnalyticsRunModel
from trading212_persistence.planning_service import PostgresPlanningService
from trading212_persistence.target_service import PostgresTargetService
from trading212_persistence.xray_catalog_models import ConstituentSnapshotModel
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID, XRAY_AT, xray_id
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.test_virtual_targets import publish
from tests.integration.test_xray_reads_postgres import XrayReadCase, company
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case
from tests.integration.test_xray_store_permission_postgres import _license

pytestmark = pytest.mark.integration


def service(case: XrayReadCase) -> PostgresPlanningService:
    return PostgresPlanningService(
        sessions=case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now[0]
    )


async def request(case: XrayReadCase, run_id: str | None) -> app.ActualVsTargetQuery:
    targets = PostgresTargetService(
        sessions=case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now[0]
    )
    portfolio = await targets.create_virtual_portfolio(
        case.principal,
        targets_app.CreateVirtualPortfolioCommand(
            "Company actual fixture", CurrencyCode("EUR"), XRAY_ACCOUNT_ID
        ),
        idempotency_key=uuid4().hex,
        correlation_id="company-projection",
    )
    # Cash target keeps every ingested equity as an actual unclassified position;
    # no mutable target-catalog entity enrichment supplies the company mapping.
    version = await targets.create_target_version(
        case.principal,
        portfolio.id,
        targets_app.CreateTargetVersionCommand(
            XRAY_AT,
            content=TargetContent(
                (TargetNode("cash", None, TargetNodeKind.CASH, "Cash", 0, Decimal(1)),)
            ),
        ),
        if_match=portfolio.etag,
        idempotency_key=uuid4().hex,
        correlation_id="company-projection",
    )
    version = await publish(targets, case.principal, version)
    return app.ActualVsTargetQuery(
        snapshot_id=case.seed["snapshot_id"],
        virtual_portfolio_id=portfolio.id,
        target_version_id=version.id,
        reporting_currency=CurrencyCode("EUR"),
        xray_run_id=run_id,
        limit=100,
    )


def test_real_producers_paging_restart_top_and_http_mcp_keep_full_metrics_and_base_bytes(
    xray_read_case: XrayReadCase,
) -> None:
    async def run() -> None:
        case = xray_read_case
        full = await company(case)
        query = await request(case, None)
        planning = service(case)
        base = await planning.get_actual_vs_target(case.principal, XRAY_ACCOUNT_ID, query=query)
        with case.sessions() as session:
            before = tuple(
                session.execute(
                    select(
                        AnalyticsRunModel.id,
                        AnalyticsRunModel.canonical_input,
                        AnalyticsRunModel.canonical_result,
                        AnalyticsRunModel.content_digest,
                    ).where(AnalyticsRunModel.kind == "actual_vs_target")
                ).all()
            )
        query = replace(query, xray_run_id=full.context.run_id)
        enriched = await planning.get_actual_vs_target(case.principal, XRAY_ACCOUNT_ID, query=query)
        alpha_rows: list[PlanningDriftRowView] = []
        for row in enriched.rows.items:
            assert isinstance(row, PlanningDriftRowView)
            if row.company.entity_id == UUID(xray_id("entity/alpha")):
                alpha_rows.append(row)
        assert len(alpha_rows) == 4
        assert all(row.effective_weight == Decimal("0.56") for row in alpha_rows)
        assert {row.listing_id for row in alpha_rows} >= {
            xray_id("listing/alpha-primary"),
            xray_id("listing/alpha-secondary"),
        }
        assert enriched.content_digest == base.content_digest
        assert enriched.totals == base.totals
        assert enriched.projection_digest is not None
        with case.sessions() as session:
            after = tuple(
                session.execute(
                    select(
                        AnalyticsRunModel.id,
                        AnalyticsRunModel.canonical_input,
                        AnalyticsRunModel.canonical_result,
                        AnalyticsRunModel.content_digest,
                    ).where(AnalyticsRunModel.kind == "actual_vs_target")
                ).all()
            )
        assert after == before
        first = await planning.get_actual_vs_target(
            case.principal, XRAY_ACCOUNT_ID, query=replace(query, limit=1)
        )
        assert first.rows.next_cursor is not None
        replay = await service(case).get_actual_vs_target(
            case.principal, XRAY_ACCOUNT_ID, query=replace(query, cursor=first.rows.next_cursor)
        )
        assert replay.projection_digest == first.projection_digest == enriched.projection_digest
        assert replay.company_basis == enriched.company_basis
        assert first.rows.items + replay.rows.items == enriched.rows.items
        with pytest.raises(CursorValidationError):
            await planning.get_actual_vs_target(
                case.principal,
                XRAY_ACCOUNT_ID,
                query=replace(query, xray_run_id=None, cursor=first.rows.next_cursor),
            )
        drift_query = app.DriftAnalysisQuery(
            snapshot_id=query.snapshot_id,
            virtual_portfolio_id=query.virtual_portfolio_id,
            target_version_id=query.target_version_id,
            reporting_currency=query.reporting_currency,
            xray_run_id=query.xray_run_id,
            top_n=1,
        )
        top = await planning.get_drift_analysis(case.principal, XRAY_ACCOUNT_ID, query=drift_query)
        larger = await planning.get_drift_analysis(
            case.principal, XRAY_ACCOUNT_ID, query=replace(drift_query, top_n=50)
        )
        assert top.projection_digest == larger.projection_digest
        assert top.company_basis == larger.company_basis
        for row in (*larger.groups, *larger.leaves, *larger.cash_and_unclassified):
            assert isinstance(row, PlanningDriftRowView)
            assert row.company.drift_reason == "effective_exposure_target_unavailable"
        http = planning_response(
            Request({"type": "http", "headers": []}),
            enriched,
            wire.ActualVsTargetResult,
            conditional=True,
        )
        assert http.status_code == 200
        mcp = _payload(enriched, wire.ActualVsTargetResult).model_dump(mode="json")
        assert json.loads(bytes(http.body)) == mcp
        conditional = planning_response(
            Request(
                {"type": "http", "headers": [(b"if-none-match", http.headers["etag"].encode())]}
            ),
            enriched,
            wire.ActualVsTargetResult,
            conditional=True,
        )
        assert conditional.status_code == 304
        page_http = planning_response(
            Request({"type": "http", "headers": []}),
            first,
            wire.ActualVsTargetResult,
            conditional=True,
        )
        assert page_http.headers["etag"] != http.headers["etag"]

    asyncio.run(run())


def forbidden_decode(*args: object, **kwargs: object) -> Never:
    raise AssertionError("Canonical payload decoded before the current source/retention guard")


def guard_decoders(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("decode_xray_component", "decode_xray_input", "decode_xray_result"):
        monkeypatch.setattr(xray_run_store, name, forbidden_decode)
    monkeypatch.setattr(planning_company_store, "decode_xray_input", forbidden_decode)
    monkeypatch.setattr(planning_service, "planning_input_from_json", forbidden_decode)


@pytest.mark.parametrize(
    "store,display",
    [
        (LicensePermission.DENIED, LicensePermission.ALLOWED),
        (LicensePermission.UNKNOWN, LicensePermission.ALLOWED),
        (LicensePermission.ALLOWED, LicensePermission.DENIED),
    ],
)
def test_current_permission_before_decode_on_initial_read_and_cursor_resume(
    xray_read_case: XrayReadCase,
    monkeypatch: pytest.MonkeyPatch,
    store: LicensePermission,
    display: LicensePermission,
) -> None:
    async def run() -> None:
        case = xray_read_case
        full = await company(case)
        query = await request(case, full.context.run_id)
        first = await service(case).get_actual_vs_target(
            case.principal, XRAY_ACCOUNT_ID, query=replace(query, limit=1)
        )
        assert first.rows.next_cursor is not None
        await _license(case, store=store, display=display)
        guard_decoders(monkeypatch)
        for cursor in (None, first.rows.next_cursor):
            with pytest.raises(app.PlanningServiceError) as denied:
                await service(case).get_actual_vs_target(
                    case.principal, XRAY_ACCOUNT_ID, query=replace(query, cursor=cursor)
                )
            assert denied.value.code is app.PlanningServiceErrorCode.ACCESS_DENIED

    asyncio.run(run())


def test_physical_expiry_denied_before_decode_without_new_run_fallback(
    xray_read_case: XrayReadCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        case = xray_read_case
        full = await company(case)
        query = await request(case, full.context.run_id)
        with case.sessions() as session:
            capture = session.get(ConstituentSnapshotModel, UUID(case.seed["fund-a_snapshot_id"]))
            assert capture is not None and capture.expires_at is not None
            expiry = capture.expires_at
        case.now[0] = expiry + timedelta(seconds=1)
        guard_decoders(monkeypatch)
        with pytest.raises(app.PlanningServiceError):
            await service(case).get_actual_vs_target(case.principal, XRAY_ACCOUNT_ID, query=query)

    asyncio.run(run())


def test_foreign_account_selected_run_has_no_metadata_or_decode(
    xray_read_case: XrayReadCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        case = xray_read_case
        full = await company(case)
        query = await request(case, full.context.run_id)
        guard_decoders(monkeypatch)
        with pytest.raises(app.PlanningServiceError) as denied:
            await service(case).get_actual_vs_target(
                case.principal, str(build_synthetic_identity().account.id), query=query
            )
        assert denied.value.code is app.PlanningServiceErrorCode.NOT_FOUND
        assert full.context.run_id not in str(denied.value)

    asyncio.run(run())
