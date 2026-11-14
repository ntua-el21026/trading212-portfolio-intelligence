"""The additional native fixture stays explicitly restricted to disposable tests."""

from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import Mock, patch

import pytest
from alembic import command
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import aggregation as app
from trading212_application.ingestion import (
    FULL_REFRESH_ORDER,
    IngestionCapability,
    SourceRecord,
    _fingerprint,
)
from trading212_domain.aggregation import AggregateActivityWindow
from trading212_persistence.aggregation_activity_capture import capture_activity
from trading212_persistence.aggregation_authorization import AggregateAuthorization
from trading212_persistence.historical_normalization import normalize_record
from trading212_persistence.models import SourceRecordModel
from trading212_security.principals import Scope
from trading212_worker.postgres_store import _json_value
from trading212_worker.synthetic import SyntheticIngestionProvider

from scripts import run_api_backed_e2e as runner
from scripts.api_e2e_aggregation import (
    EUR_ACCOUNT_ID,
    AggregationBrowserIngestionProvider,
    aggregation_enabled,
    fixture_id,
    seed_aggregation_browser_scenario,
)

AT = datetime(2026, 11, 14, tzinfo=UTC)


def retained(source: SourceRecord, capability: IngestionCapability) -> SourceRecordModel:
    return SourceRecordModel(
        id=fixture_id("record/" + str(source.provider_record_id)),
        broker_account_id=EUR_ACCOUNT_ID,
        provider="synthetic",
        capability=capability.value,
        provider_record_id=source.provider_record_id,
        source_updated_at=source.source_timestamp,
        observed_at=source.observed_at,
        schema_version=source.schema_version,
        payload_fingerprint=source.payload_sha256,
        sanitized_payload=_json_value(source.payload),
    )


@pytest.mark.parametrize(("value", "expected"), [("0", False), ("1", True)])
def test_selector_requires_exact_explicit_value(value: str, expected: bool) -> None:
    assert aggregation_enabled(value) is expected


@pytest.mark.parametrize("value", ["", "true", "01", " 1", "CANARY"])
def test_invalid_selector_precedes_migration(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("T212PI_E2E_AGGREGATION", value)
    with patch.object(command, "upgrade") as migrate:
        with pytest.raises(RuntimeError, match="must be 0 or 1") as raised:
            runner._serve_fixture("postgresql://unused")
        migrate.assert_not_called()
    assert "CANARY" not in str(raised.value)


@pytest.mark.parametrize(
    ("environment", "selector"),
    [("production", "1"), ("local", "1"), ("test", "0"), ("test", "CANARY")],
)
async def test_guard_rejects_before_any_session_or_grant(
    environment: str, selector: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("T212PI_E2E_AGGREGATION", selector)
    sessions = Mock()
    with pytest.raises(RuntimeError):
        await seed_aggregation_browser_scenario(
            cast(sessionmaker[Session], sessions),
            app_environment=environment,
            at=datetime(2026, 9, 22, tzinfo=UTC),
        )
    assert sessions.mock_calls == []


async def test_browser_fixture_preserves_sources_with_explicit_empty_fill_collection() -> None:
    original = SyntheticIngestionProvider(clock=lambda: AT)
    browser = AggregationBrowserIngestionProvider(clock=lambda: AT)
    activity_records = 0
    for capability in FULL_REFRESH_ORDER:
        pages = [
            await provider.read_page(
                owner_id="synthetic-owner",
                account_id=str(EUR_ACCOUNT_ID),
                capability=capability,
                checkpoint=None,
                correlation_id="aggregation-fixture-regression",
            )
            for provider in (original, browser)
        ]
        expected, actual = pages
        if capability is IngestionCapability.HISTORICAL_ORDERS:
            assert len(expected.records) == 1 and expected.records[0].payload["fill"] is None
            assert actual.records == () and actual.complete and actual.next_checkpoint is None
        else:
            assert actual == expected
        if capability in (IngestionCapability.TRANSACTIONS, IngestionCapability.DIVIDENDS):
            for source in actual.records:
                assert normalize_record(retained(source, capability), None, ()) is not None
                activity_records += 1
    assert activity_records == 3


async def test_original_order_without_fill_still_denies_activity_capture() -> None:
    page = await SyntheticIngestionProvider(clock=lambda: AT).read_page(
        owner_id="synthetic-owner",
        account_id=str(EUR_ACCOUNT_ID),
        capability=IngestionCapability.HISTORICAL_ORDERS,
        checkpoint=None,
        correlation_id="aggregation-fixture-negative",
    )
    row = retained(page.records[0], IngestionCapability.HISTORICAL_ORDERS)
    assert _fingerprint(row.sanitized_payload) == row.payload_fingerprint
    assert normalize_record(row, None, ()) is None
    sessions = Mock(spec=Session)
    sessions.execute.return_value.one.return_value = (1, 1)
    sessions.scalars.side_effect = [(row,), AssertionError("Unsupported order was not rejected")]
    authority = Mock(spec=AggregateAuthorization)
    authority.account_ids = (EUR_ACCOUNT_ID,)
    authority.scopes = frozenset({Scope.ACTIVITY_READ})
    with pytest.raises(app.AggregateServiceError) as denied:
        capture_activity(
            cast(Session, sessions),
            cast(AggregateAuthorization, authority),
            holdings_input_digest="0" * 64,
            window=AggregateActivityWindow(start_at=AT - timedelta(days=1), end_at=AT),
            cutoff=AT,
            now=AT,
            check_deadline=lambda: None,
        )
    assert denied.value.code is app.AggregateErrorCode.SOURCE_UNAVAILABLE
