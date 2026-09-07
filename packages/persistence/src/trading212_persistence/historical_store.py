"""Canonical historical evidence registration and immutable input store."""

from .historical_capture import HistoricalCaptureStore


class PostgresHistoricalStore(HistoricalCaptureStore):
    """Share owner-locked evidence registration, capture and replay boundaries."""
