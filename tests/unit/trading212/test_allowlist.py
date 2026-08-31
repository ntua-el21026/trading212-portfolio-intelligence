from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError
from trading212_provider.allowlist import CAPABILITIES
from trading212_provider.configuration import BrokerEnvironment, Trading212Settings
from trading212_provider.errors import CapabilityError


def test_allowlist_is_exactly_the_frozen_ten_get_capabilities() -> None:
    assert tuple(CAPABILITIES) == (
        "account_summary",
        "metadata_instruments",
        "metadata_exchanges",
        "portfolio_positions",
        "pending_orders",
        "order_detail",
        "historical_orders",
        "historical_transactions",
        "historical_dividends",
        "historical_exports",
    )
    assert all(
        capability.path_template.startswith("/equity/") for capability in CAPABILITIES.values()
    )


def test_demo_is_default_and_origins_are_not_configurable() -> None:
    settings = Trading212Settings()
    assert settings.environment is BrokerEnvironment.DEMO
    assert settings.base_url == "https://demo.trading212.com/api/v0"
    assert "base_url" not in Trading212Settings.model_fields


def test_live_mode_requires_explicit_gate() -> None:
    with pytest.raises(ValidationError, match="explicit read-only enablement"):
        Trading212Settings(environment=BrokerEnvironment.LIVE)
    settings = Trading212Settings(
        environment=BrokerEnvironment.LIVE,
        live_mode_explicitly_enabled=True,
    )
    assert settings.base_url == "https://live.trading212.com/api/v0"


@pytest.mark.parametrize("limit", [0, 51, True, "20"])
def test_page_limit_is_bounded_and_typed(limit: object) -> None:
    with pytest.raises(CapabilityError):
        CAPABILITIES["historical_orders"].normalize_query({"limit": limit})


def test_naive_transaction_time_and_unknown_query_fail_closed() -> None:
    capability = CAPABILITIES["historical_transactions"]
    with pytest.raises(CapabilityError, match="timezone-aware"):
        capability.normalize_query({"time": datetime(2026, 1, 1)})
    with pytest.raises(CapabilityError, match="unsupported query"):
        capability.normalize_query({"url": "https://example.invalid"})


@pytest.mark.parametrize("order_id", ["", "-1", "1/positions", "9223372036854775808"])
def test_order_id_cannot_inject_a_path(order_id: str) -> None:
    with pytest.raises(CapabilityError):
        CAPABILITIES["order_detail"].resolve_path(order_id=order_id)
