"""New licensed copies require current storage permission through publication."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from trading212_analytics.xray import calculate_overlap_pairs, calculate_xray
from trading212_application import source_providers as ports
from trading212_application import xray as app
from trading212_domain.sources import LicensePermission
from trading212_domain.xray import XrayInput
from trading212_domain.xray_codec import XrayComponent, encode_xray_component
from trading212_domain.xray_result import CanonicalOverlapPair, XrayCalculation
from trading212_persistence import xray_overlap_reads as overlap_reads
from trading212_persistence import xray_publication as publication
from trading212_persistence.models import (
    CollectionQuerySnapshotMemberModel,
    CollectionQuerySnapshotModel,
)
from trading212_persistence.planning_models import AnalyticsRunModel
from trading212_persistence.source_service import PostgresSourceService
from trading212_persistence.xray_catalog_models import ConstituentSnapshotModel
from trading212_persistence.xray_run_models import (
    EtfOverlapEntityModel,
    EtfOverlapPairModel,
    XrayCollectionBindingModel,
    XrayInputSnapshotModel,
    XrayRunModel,
)
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID, XRAY_AT, xray_id
from trading212_worker.xray_seed import XRAY_CURSOR_KEY
from trading212_worker.xray_source_fixture import xray_license, xray_replay

from tests.integration.test_xray_reads_postgres import XrayReadCase, company
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def _counts(case: XrayReadCase) -> tuple[int, ...]:
    with case.sessions() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model)) or 0
            for model in (
                XrayInputSnapshotModel,
                XrayRunModel,
                AnalyticsRunModel,
                CollectionQuerySnapshotModel,
                CollectionQuerySnapshotMemberModel,
                XrayCollectionBindingModel,
                EtfOverlapPairModel,
                EtfOverlapEntityModel,
            )
        )


async def _license(
    case: XrayReadCase,
    *,
    store: LicensePermission,
    display: LicensePermission = LicensePermission.ALLOWED,
    effective_at: datetime | None = None,
) -> None:
    case.now[0] += timedelta(seconds=1)
    key = str(uuid4())
    source = PostgresSourceService(
        sessions=case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now[0]
    )
    await source.register_source_license(
        case.principal,
        replace(
            xray_license(),
            id=key,
            version=f"storage-{key}",
            effective_at=effective_at or case.now[0],
            store=store,
            display=display,
        ),
        idempotency_key=key,
        correlation_id="xray-store-permission",
    )


async def _empty_source(case: XrayReadCase) -> str:
    request = ports.ConstituentRequest(
        fund_series_id=xray_id("fund-mapping/fund-a"),
        effective_at=XRAY_AT,
        source_cutoff_at=XRAY_AT,
    )
    page = await xray_replay(case.principal.owner_id).get_constituents(request)
    assert isinstance(page, ports.ConstituentPage)
    empty = replace(
        page,
        provenance=replace(
            page.provenance, source_revision="empty-storage-check", revision_order=2
        ),
        holdings=(),
        stated_coverage=Decimal("0"),
        unresolved_weight=Decimal("1"),
        cash_weight=Decimal("0"),
        continuation=None,
    )
    result = await case.service.ingest_constituents(
        case.principal,
        request,
        (empty,),
        idempotency_key="empty-storage-check",
        correlation_id="empty-storage-check",
    )
    return result.id


@pytest.mark.parametrize("permission", [LicensePermission.DENIED, LicensePermission.UNKNOWN])
def test_split_storage_permission_blocks_all_new_copies_but_preserves_retained_reads(
    xray_read_case: XrayReadCase, permission: LicensePermission
) -> None:
    async def run() -> None:
        case = xray_read_case
        first = await company(case, limit=1)
        request = case.request(first.context.run_id)
        source = case.seed["fund-a_snapshot_id"]
        holdings = await case.service.list_constituent_holdings(
            case.principal, source, query=app.ConstituentHoldingsQuery(limit=1)
        )
        empty_source = await _empty_source(case)
        pairs = app.Pairs(fund_ids=case.funds)
        common = app.CommonEntities(
            fund_ids=case.funds, left_fund_id=case.funds[0], right_fund_id=case.funds[1]
        )
        overlap_options: tuple[app.Pairs | app.CommonEntities, ...] = (pairs, common)
        await _license(case, store=permission)
        before = _counts(case)
        for exposure_options in (
            app.Exposures(normalized_known_only=True),
            app.Paths(),
            app.HeldFunds(),
        ):
            with pytest.raises(app.XrayServiceError) as denied:
                await case.service.get_effective_exposure(
                    case.principal,
                    XRAY_ACCOUNT_ID,
                    query=app.EffectiveExposureQuery(request=request, options=exposure_options),
                )
            assert denied.value.code is app.XrayServiceErrorCode.ACCESS_DENIED
            assert _counts(case) == before
        for options in overlap_options:
            with pytest.raises(app.XrayServiceError) as denied:
                await case.service.get_etf_overlap(
                    case.principal,
                    XRAY_ACCOUNT_ID,
                    query=app.EtfOverlapQuery(request=request, options=options),
                )
            assert denied.value.code is app.XrayServiceErrorCode.ACCESS_DENIED
            assert _counts(case) == before
        for identifier in (case.seed["fund-b_snapshot_id"], empty_source):
            with pytest.raises(app.XrayServiceError) as denied:
                await case.service.list_constituent_holdings(
                    case.principal, identifier, query=app.ConstituentHoldingsQuery()
                )
            assert denied.value.code is app.XrayServiceErrorCode.ACCESS_DENIED
            assert _counts(case) == before
        header = await case.service.get_constituent_snapshot(
            case.principal, empty_source, query=app.ConstituentSnapshotQuery()
        )
        assert header.holding_count == 0
        repeated = await case.service.get_effective_exposure(
            case.principal,
            XRAY_ACCOUNT_ID,
            query=app.EffectiveExposureQuery(request=request, limit=1),
        )
        assert isinstance(repeated, app.ExposuresView)
        assert repeated.exposures.next_cursor is not None
        # Cursor issue time may change; all retained economic and page fields
        # must agree, and the original cursor must still resume its membership.
        assert (
            replace(
                repeated,
                exposures=replace(repeated.exposures, next_cursor=first.exposures.next_cursor),
            )
            == first
        )
        tail = await case.service.get_effective_exposure(
            case.principal,
            XRAY_ACCOUNT_ID,
            query=app.EffectiveExposureQuery(
                request=request, cursor=first.exposures.next_cursor, limit=100
            ),
        )
        assert isinstance(tail, app.ExposuresView) and len(tail.exposures.items) == 1
        assert tail.exposures.items[0].id != first.exposures.items[0].id
        continued = await case.service.list_constituent_holdings(
            case.principal,
            source,
            query=app.ConstituentHoldingsQuery(cursor=holdings.next_cursor, limit=100),
        )
        assert continued.total == holdings.total and len(continued.items) == 2
        top = await case.service.get_etf_overlap(
            case.principal,
            XRAY_ACCOUNT_ID,
            query=app.EtfOverlapQuery(
                request=request,
                options=app.McpTopPair(
                    left_fund_id=case.funds[0], right_fund_id=case.funds[1], top_n=1
                ),
            ),
        )
        assert isinstance(top, app.McpTopPairView) and top.pair.overlap.value == Decimal("0.5")
        assert _counts(case) == before
        # Existing licensed payload pages also remain readable after STORE-only
        # denial. No new source selection or durable representation is needed.
        await _license(case, store=LicensePermission.ALLOWED)
        saved = [
            await case.service.get_etf_overlap(
                case.principal,
                XRAY_ACCOUNT_ID,
                query=app.EtfOverlapQuery(request=request, options=options, limit=100),
            )
            for options in overlap_options
        ]
        await _license(case, store=permission)
        before = _counts(case)
        for options, original in zip(overlap_options, saved, strict=True):
            replay = await case.service.get_etf_overlap(
                case.principal,
                XRAY_ACCOUNT_ID,
                query=app.EtfOverlapQuery(request=request, options=options, limit=100),
            )
            assert replay == original
        assert _counts(case) == before

    asyncio.run(run())


def _expiry(case: XrayReadCase) -> datetime:
    with case.sessions() as session:
        value = session.scalar(select(func.min(ConstituentSnapshotModel.expires_at)))
        assert value is not None
        return value + timedelta(microseconds=1)


@pytest.mark.parametrize("boundary", ["store", "display", "expiry"])
def test_publication_rechecks_time_activated_permissions_and_source_expiry_before_sealing(
    xray_read_case: XrayReadCase, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    case = xray_read_case
    activated_at = _expiry(case) if boundary == "expiry" else case.now[0] + timedelta(minutes=1)
    if boundary != "expiry":
        asyncio.run(
            _license(
                case,
                store=LicensePermission.DENIED
                if boundary == "store"
                else LicensePermission.ALLOWED,
                display=LicensePermission.DENIED
                if boundary == "display"
                else LicensePermission.ALLOWED,
                effective_at=activated_at,
            )
        )
    calculate = calculate_xray

    def cross_boundary(value: XrayInput) -> XrayCalculation:
        result = calculate(value)
        case.now[0] = activated_at
        return result

    monkeypatch.setattr(publication, "calculate_xray", cross_boundary)
    before = _counts(case)
    with pytest.raises(app.XrayServiceError) as denied:
        asyncio.run(company(case))
    assert denied.value.code is app.XrayServiceErrorCode.ACCESS_DENIED
    assert _counts(case) == before


@pytest.mark.parametrize("boundary", ["store", "expiry"])
@pytest.mark.parametrize("phase", ["calculation", "payload_encoding"])
def test_projection_rechecks_time_boundary_before_and_after_new_payloads(
    xray_read_case: XrayReadCase,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    phase: str,
) -> None:
    case = xray_read_case
    first = asyncio.run(company(case))
    activated_at = _expiry(case) if boundary == "expiry" else case.now[0] + timedelta(minutes=1)
    if boundary == "store":
        asyncio.run(_license(case, store=LicensePermission.DENIED, effective_at=activated_at))
    if phase == "calculation":
        calculate = calculate_overlap_pairs

        def cross_calculation(
            value: XrayCalculation, funds: tuple[UUID, ...]
        ) -> tuple[CanonicalOverlapPair, ...]:
            result = calculate(value, funds)
            case.now[0] = activated_at
            return result

        monkeypatch.setattr(overlap_reads, "calculate_overlap_pairs", cross_calculation)
    else:
        encode = encode_xray_component

        def cross_encoding(value: XrayComponent) -> bytes:
            result = encode(value)
            case.now[0] = activated_at
            return result

        monkeypatch.setattr(overlap_reads, "encode_xray_component", cross_encoding)
    before = _counts(case)
    with pytest.raises(app.XrayServiceError) as denied:
        asyncio.run(
            case.service.get_etf_overlap(
                case.principal,
                XRAY_ACCOUNT_ID,
                query=app.EtfOverlapQuery(
                    request=case.request(first.context.run_id),
                    options=app.Pairs(fund_ids=case.funds),
                ),
            )
        )
    assert denied.value.code is app.XrayServiceErrorCode.ACCESS_DENIED
    assert _counts(case) == before
