"""Read-only readiness query for the durable refresh dispatcher heartbeat."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .models import RefreshDispatcherHeartbeatModel


def refresh_dispatcher_is_ready(
    sessions: sessionmaker[Session],
    *,
    now: datetime,
    max_age: timedelta = timedelta(seconds=30),
) -> bool:
    """Return whether any dispatcher has completed a fresh healthy cycle."""

    timestamp = _utc(now)
    if max_age <= timedelta(0) or max_age > timedelta(minutes=5):
        raise ValueError("dispatcher heartbeat maximum age is out of bounds")
    cutoff = timestamp - max_age
    with sessions() as session:
        return (
            session.scalar(
                select(RefreshDispatcherHeartbeatModel.id)
                .where(
                    RefreshDispatcherHeartbeatModel.state == "healthy",
                    RefreshDispatcherHeartbeatModel.heartbeat_at >= cutoff,
                    RefreshDispatcherHeartbeatModel.last_successful_cycle_at >= cutoff,
                )
                .limit(1)
            )
            is not None
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)
