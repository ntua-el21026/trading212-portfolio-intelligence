"""Real held-fund discovery beyond one request and bounded repeated pair retention."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from trading212_application import xray as app
from trading212_application.ingestion import IngestionCoordinator, RunMode, RunStatus
from trading212_application.xray_ingestion import FundDefinitionRegistration
from trading212_domain.errors import DomainError
from trading212_domain.identifiers import InstrumentId, ListingId
from trading212_persistence.mappers import instrument_to_model, listing_to_model
from trading212_persistence.models import CollectionQuerySnapshotModel, PortfolioSnapshotModel
from trading212_persistence.xray_run_models import EtfOverlapPairModel, XrayFundCompositionModel
from trading212_persistence.xray_service import PostgresXrayService
from trading212_worker.materializer import PostgresCanonicalMaterializer
from trading212_worker.postgres_store import PostgresIngestionStore
from trading212_worker.xray_fixture import (
    XRAY_ACCOUNT_ID,
    XRAY_AT,
    XRAY_EFFECTIVE,
    XRAY_LICENSE_ID,
    XRAY_PROVIDER_ID,
    xray_id,
)
from trading212_worker.xray_provider import SyntheticXrayBrokerProvider
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


async def _ingest_forty_funds(case: XrayReadCase) -> None:
    """Add 38 actual zero-valued positions through broker ingestion, not X-ray SQL."""
    provider = SyntheticXrayBrokerProvider()
    template = next(row for row in provider.fixture.listings if row.key == "fund-a")
    additional = []
    for index in range(38):
        key = f"zero-fund-{index:02}"
        instrument = replace(
            template.instrument,
            id=InstrumentId(UUID(xray_id(f"instrument/{key}"))),
            canonical_name=f"Synthetic Zero Fund {index:02}",
            isin=f"XS{10000 + index:010}",
        )
        listing = replace(
            template.listing,
            id=ListingId(UUID(xray_id(f"listing/{key}"))),
            instrument_id=instrument.id,
            provider_instrument_id=f"XRAY_ZERO_{index:02}",
            ticker=f"XRAY_ZERO_{index:02}",
        )
        additional.append(
            replace(
                template, key=key, instrument=instrument, listing=listing, held_value=Decimal(0)
            )
        )
        with case.sessions.begin() as session:
            session.add(instrument_to_model(instrument, observed_at=listing.valid_from))
            session.flush()
            session.add(listing_to_model(listing))
        await case.service.register_fund_definition(
            case.principal,
            FundDefinitionRegistration(
                id=xray_id(f"fund-definition/{key}"),
                key=f"synthetic-{key}",
                instrument_id=str(instrument.id),
                fund_type="etf",
                provider_id=XRAY_PROVIDER_ID,
                license_version_id=XRAY_LICENSE_ID,
                revision=1,
                effective_at=XRAY_EFFECTIVE,
                valid_until=None,
                evidence_key=f"synthetic-{key}-definition",
                confidence=Decimal("0.99"),
            ),
            idempotency_key=f"forty-funds:{key}",
            correlation_id="forty-funds",
        )
    provider.fixture = replace(
        provider.fixture, listings=provider.fixture.listings + tuple(additional)
    )
    case.now[0] = XRAY_AT + timedelta(seconds=1)
    receipt = await IngestionCoordinator(
        provider=provider,
        store=PostgresIngestionStore(
            case.sessions, provider="synthetic", materializer=PostgresCanonicalMaterializer()
        ),
        clock=lambda: case.now[0],
    ).refresh(
        owner_id=case.principal.owner_id,
        account_id=XRAY_ACCOUNT_ID,
        mode=RunMode.FULL,
        idempotency_key="forty-funds",
        correlation_id="forty-funds",
    )
    assert receipt.status is RunStatus.SUCCEEDED
    with case.sessions() as session:
        snapshot = session.scalar(
            select(PortfolioSnapshotModel)
            .where(PortfolioSnapshotModel.broker_account_id == UUID(XRAY_ACCOUNT_ID))
            .order_by(PortfolioSnapshotModel.valuation_at.desc())
            .limit(1)
        )
        assert snapshot is not None
        assert str(snapshot.id) != case.seed["snapshot_id"]
        case.seed["snapshot_id"] = str(snapshot.id)
        case.seed["source_cutoff_at"] = snapshot.source_cutoff_at.isoformat()


def test_forty_real_funds_page_and_repeated_subsets_charge_owned_capacity(
    xray_read_case: XrayReadCase,
) -> None:
    async def run() -> None:
        case = xray_read_case
        await _ingest_forty_funds(case)
        first = await case.service.get_effective_exposure(
            case.principal,
            XRAY_ACCOUNT_ID,
            query=app.EffectiveExposureQuery(
                request=case.request(), options=app.HeldFunds(), limit=17
            ),
        )
        assert isinstance(first, app.HeldFundsView)
        assert first.held_funds.total == 40
        assert first.summary.total.value is not None
        assert first.summary.total.value.amount == Decimal("1000")
        found = list(first.held_funds.items)
        cursor = first.held_funds.next_cursor
        while cursor is not None:
            page = await case.service.get_effective_exposure(
                case.principal,
                XRAY_ACCOUNT_ID,
                query=app.EffectiveExposureQuery(
                    request=case.request(first.context.run_id),
                    options=app.HeldFunds(),
                    cursor=cursor,
                    limit=17,
                ),
            )
            assert isinstance(page, app.HeldFundsView)
            assert page.context == first.context and page.summary == first.summary
            found.extend(page.held_funds.items)
            cursor = page.held_funds.next_cursor
        fund_ids = tuple(row.instrument_id for row in found)
        assert len(set(fund_ids)) == 40
        assert all(row.position_count == 1 for row in found)
        with pytest.raises(DomainError):
            app.Pairs(fund_ids=fund_ids[:33])
        with case.sessions() as session:
            assert session.scalar(select(func.count()).select_from(XrayFundCompositionModel)) == 40
            assert session.scalar(select(func.count()).select_from(EtfOverlapPairModel)) == 0
            active = session.scalar(select(func.count()).select_from(CollectionQuerySnapshotModel))
        assert active is not None
        case.service = PostgresXrayService(
            sessions=case.sessions,
            cursor_signing_key=XRAY_CURSOR_KEY,
            clock=lambda: case.now[0],
            max_active_collection_snapshots_per_owner=active + 2,
        )
        subsets = (fund_ids[:32], fund_ids[8:], fund_ids[4:36])
        for subset in subsets[:2]:
            result = await case.service.get_etf_overlap(
                case.principal,
                XRAY_ACCOUNT_ID,
                query=app.EtfOverlapQuery(
                    request=case.request(first.context.run_id), options=app.Pairs(fund_ids=subset)
                ),
            )
            assert isinstance(result, app.OverlapPairsView)
            assert result.pairs.total == 496
            assert result.summary == first.summary and result.context == first.context
        with case.sessions() as session:
            assert session.scalar(select(func.count()).select_from(EtfOverlapPairModel)) == 992
            retained = tuple(
                session.execute(
                    select(
                        CollectionQuerySnapshotModel.id, CollectionQuerySnapshotModel.expires_at
                    ).order_by(CollectionQuerySnapshotModel.id)
                )
            )
        repeated = await case.service.get_etf_overlap(
            case.principal,
            XRAY_ACCOUNT_ID,
            query=app.EtfOverlapQuery(
                request=case.request(first.context.run_id),
                options=app.Pairs(fund_ids=subsets[0]),
                limit=100,
            ),
        )
        assert isinstance(repeated, app.OverlapPairsView) and repeated.pairs.total == 496
        with pytest.raises(app.XrayServiceError) as full:
            await case.service.get_etf_overlap(
                case.principal,
                XRAY_ACCOUNT_ID,
                query=app.EtfOverlapQuery(
                    request=case.request(first.context.run_id),
                    options=app.Pairs(fund_ids=subsets[2]),
                ),
            )
        assert full.value.code is app.XrayServiceErrorCode.RESULT_TOO_LARGE
        with case.sessions() as session:
            assert session.scalar(select(func.count()).select_from(EtfOverlapPairModel)) == 992
            assert (
                tuple(
                    session.execute(
                        select(
                            CollectionQuerySnapshotModel.id, CollectionQuerySnapshotModel.expires_at
                        ).order_by(CollectionQuerySnapshotModel.id)
                    )
                )
                == retained
            )

    asyncio.run(run())
