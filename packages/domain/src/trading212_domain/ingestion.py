"""The fixed broker read capability vocabulary, shared without layer inversion."""

from enum import StrEnum


class IngestionCapability(StrEnum):
    INSTRUMENTS = "metadata_instruments"
    EXCHANGES = "metadata_exchanges"
    ACCOUNT = "account_summary"
    POSITIONS = "portfolio_positions"
    PENDING_ORDERS = "pending_orders"
    HISTORICAL_ORDERS = "historical_orders"
    TRANSACTIONS = "historical_transactions"
    DIVIDENDS = "historical_dividends"
    EXPORT_METADATA = "historical_exports"
