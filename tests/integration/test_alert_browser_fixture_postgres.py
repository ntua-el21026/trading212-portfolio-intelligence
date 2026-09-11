"""The browser scenario produces actual durable alert results, not seeded result bytes."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from trading212_domain import build_synthetic_identity
from trading212_worker.scenarios import persist_quantity_cash_mismatch_scenario

from scripts.api_e2e_alerts import seed_alert_browser_scenario
from tests.integration.test_alert_postgres import alert_database as alert_database

pytestmark = pytest.mark.integration


async def test_actual_browser_alert_fixture_completes_in_app_without_external_configuration(
    alert_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = alert_database
    identity = build_synthetic_identity()
    with sessions.begin() as session:
        persist_quantity_cash_mismatch_scenario(
            session,
            account_id=identity.account.id,
            listing_id=identity.listing.id,
            as_of=datetime.now(UTC),
        )
    await seed_alert_browser_scenario(sessions)
