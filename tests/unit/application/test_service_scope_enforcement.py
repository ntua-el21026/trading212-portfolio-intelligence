from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from trading212_application.services import SyntheticPortfolioService
from trading212_application.views import AccountSummaryView
from trading212_persistence import PostgresPortfolioService
from trading212_security.principals import AuthorizationError, Principal, Scope

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 31, 10, 0, tzinfo=UTC)
CURSOR_SIGNING_KEY = b"scope-enforcement-cursor-key-v1-256"


def _principal(scopes: frozenset[Scope]) -> Principal:
    return Principal(
        principal_id="scope-test-principal",
        owner_id=SyntheticPortfolioService.OWNER_ID,
        issuer="scope-test",
        subject="scope-test-subject",
        scopes=scopes,
        authenticated_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )


class _NoReadSyntheticService(SyntheticPortfolioService):
    async def owner_for_account(self, account_id: str) -> str | None:
        del account_id
        raise AssertionError("owner lookup occurred before all required scopes were checked")

    async def get_summary(
        self,
        principal: Principal,
        account_id: str,
    ) -> AccountSummaryView:
        del principal, account_id
        raise AssertionError("portfolio data was read before all required scopes were checked")


def _deny_database_read() -> Any:
    raise AssertionError("database access occurred before all required scopes were checked")


@pytest.mark.asyncio
async def test_synthetic_connections_require_configuration_before_owner_read() -> None:
    service = _NoReadSyntheticService(clock=lambda: NOW)

    with pytest.raises(AuthorizationError, match="access denied"):
        await service.list_broker_connections(_principal(frozenset({Scope.PORTFOLIO_READ})))


@pytest.mark.asyncio
async def test_synthetic_connection_listing_accepts_configuration_only_principal() -> None:
    service = SyntheticPortfolioService(clock=lambda: NOW)

    connections = await service.list_broker_connections(
        _principal(frozenset({Scope.CONFIGURATION_READ}))
    )

    assert len(connections) == 1
    assert connections[0].provider == "synthetic"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scopes",
    [
        frozenset({Scope.PORTFOLIO_READ}),
        frozenset({Scope.ACTIVITY_READ}),
    ],
)
async def test_synthetic_data_quality_requires_both_scopes_before_data_read(
    scopes: frozenset[Scope],
) -> None:
    service = _NoReadSyntheticService(clock=lambda: NOW)

    with pytest.raises(AuthorizationError, match="access denied"):
        await service.get_data_quality_summary(_principal(scopes), service.ACCOUNT_ID)


@pytest.mark.asyncio
async def test_synthetic_data_quality_accepts_combined_read_scopes() -> None:
    service = SyntheticPortfolioService(clock=lambda: NOW)

    summary = await service.get_data_quality_summary(
        _principal(frozenset({Scope.PORTFOLIO_READ, Scope.ACTIVITY_READ})),
        service.ACCOUNT_ID,
    )

    assert summary.reporting_currency == "EUR"
    assert {item.capability for item in summary.capabilities} >= {"positions", "activity"}


@pytest.mark.asyncio
async def test_postgres_connections_require_configuration_before_database_read() -> None:
    service = PostgresPortfolioService(
        sessions=cast(Any, _deny_database_read),
        cursor_signing_key=CURSOR_SIGNING_KEY,
        clock=lambda: NOW,
    )

    with pytest.raises(AuthorizationError, match="access denied"):
        await service.list_broker_connections(_principal(frozenset({Scope.PORTFOLIO_READ})))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scopes",
    [
        frozenset({Scope.PORTFOLIO_READ}),
        frozenset({Scope.ACTIVITY_READ}),
    ],
)
async def test_postgres_data_quality_requires_both_scopes_before_database_read(
    scopes: frozenset[Scope],
) -> None:
    service = PostgresPortfolioService(
        sessions=cast(Any, _deny_database_read),
        cursor_signing_key=CURSOR_SIGNING_KEY,
        clock=lambda: NOW,
    )

    with pytest.raises(AuthorizationError, match="access denied"):
        await service.get_data_quality_summary(
            _principal(scopes),
            SyntheticPortfolioService.ACCOUNT_ID,
        )
