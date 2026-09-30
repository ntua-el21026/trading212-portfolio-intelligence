"""The browser consumes canonical native facts and an actually authorized FX reference."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from trading212_application.sources import FxObservationReferenceQuery
from trading212_domain import CurrencyCode
from trading212_persistence.aggregation_models import AggregateRunModel, AggregateSelectionModel
from trading212_persistence.models import (
    ListingModel,
    PortfolioSnapshotModel,
    SnapshotPositionModel,
)
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_persistence.source_service import PostgresSourceService
from trading212_security.principals import Scope

from scripts.api_e2e_aggregation import (
    CURSOR_KEY,
    EUR_ACCOUNT_ID,
    USD_ACCOUNT_ID,
    seed_aggregation_browser_scenario,
)
from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


async def test_native_browser_inputs_have_real_identity_clocks_and_picker_reference(
    xray_read_case: XrayReadCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = xray_read_case
    monkeypatch.setenv("T212PI_E2E_AGGREGATION", "1")
    now = datetime.now(UTC).replace(microsecond=0)
    metadata = await seed_aggregation_browser_scenario(
        case.sessions, app_environment="test", at=now
    )
    eur_snapshot = UUID(metadata["eur_snapshot_id"])
    usd_snapshot = UUID(metadata["usd_snapshot_id"])
    with case.sessions() as session:
        snapshots = tuple(
            session.scalars(
                select(PortfolioSnapshotModel).where(
                    PortfolioSnapshotModel.id.in_((eur_snapshot, usd_snapshot))
                )
            )
        )
        assert {row.broker_account_id: row.valuation_at for row in snapshots} == {
            EUR_ACCOUNT_ID: now - timedelta(hours=2),
            USD_ACCOUNT_ID: now - timedelta(hours=1),
        }
        positions = session.execute(
            select(SnapshotPositionModel, ListingModel.instrument_id)
            .join(ListingModel, ListingModel.id == SnapshotPositionModel.listing_id)
            .where(SnapshotPositionModel.snapshot_id.in_((eur_snapshot, usd_snapshot)))
        ).all()
        assert len(positions) == 2
        assert len({row.instrument_id for row in positions}) == 1
        assert len({row.SnapshotPositionModel.listing_id for row in positions}) == 2
        assert {
            (
                row.SnapshotPositionModel.currency,
                row.SnapshotPositionModel.quantity,
                row.SnapshotPositionModel.market_value,
            )
            for row in positions
        } == {
            ("EUR", Decimal("400"), Decimal("236000")),
            ("USD", Decimal("3"), Decimal("150")),
        }
        grants = set(
            session.scalars(
                select(PrincipalScopeGrantModel.scope).where(
                    PrincipalScopeGrantModel.principal_id == UUID(case.principal.principal_id),
                    PrincipalScopeGrantModel.revoked_at.is_(None),
                )
            )
        )
        assert {
            Scope.PORTFOLIO_READ.value,
            Scope.ANALYTICS_READ.value,
            Scope.AGGREGATE_READ.value,
            Scope.AGGREGATE_WRITE.value,
        } <= grants
        # Seeding stores only source facts: selection and derived output must be made through
        # UI/API.
        assert session.scalar(select(func.count()).select_from(AggregateSelectionModel)) == 0
        assert session.scalar(select(func.count()).select_from(AggregateRunModel)) == 0
    principal = replace(
        case.principal,
        authenticated_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(hours=1),
    )
    source = PostgresSourceService(
        sessions=case.sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: now
    )
    reference = await source.list_fx_observation_references(
        principal,
        metadata["fx_snapshot_id"],
        query=FxObservationReferenceQuery(
            account_id=str(USD_ACCOUNT_ID),
            base=CurrencyCode("USD"),
            quote=CurrencyCode("EUR"),
            source_cutoff_at=now,
            effective_at_lte=now - timedelta(hours=1),
            limit=25,
        ),
    )
    assert len(reference.items) == 1 and reference.next_cursor is None
    assert reference.items[0].observation_id == metadata["fx_observation_id"]
    assert reference.items[0].rate == Decimal("0.8")
    assert reference.items[0].effective_at <= reference.effective_at_lte
    assert reference.first_observed_at == now
    with pytest.raises(RuntimeError, match="fresh disposable database"):
        await seed_aggregation_browser_scenario(case.sessions, app_environment="test", at=now)
