"""Real Redis proof for the explicitly non-authoritative coordination boundary."""

from __future__ import annotations

import os
from typing import cast
from uuid import uuid4

import pytest
import redis


@pytest.mark.integration
def test_redis_coordination_round_trip_is_bounded_and_ephemeral() -> None:
    client = redis.Redis.from_url(
        os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    key = f"t212pi:test:coordination:{uuid4()}"
    try:
        assert client.ping() is True
        assert client.set(key, "wake-up", ex=30, nx=True) is True
        assert client.get(key) == "wake-up"
        ttl = cast(int, client.ttl(key))
        assert 0 < ttl <= 30
    finally:
        client.delete(key)
        client.close()
