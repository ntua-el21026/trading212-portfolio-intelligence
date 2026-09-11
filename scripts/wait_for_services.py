#!/usr/bin/env python3
"""Bounded readiness wait compatible with Docker Compose v1 and v2."""

from __future__ import annotations

import argparse
import os
import time
from collections.abc import Callable

import psycopg
from redis import Redis, RedisError
from redis.backoff import NoBackoff
from redis.retry import Retry

DEFAULT_POSTGRES_URL = "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio"
DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"


def postgres_ready() -> bool:
    """Return whether PostgreSQL accepts a trivial query without logging its URL."""
    database_url = os.environ.get(
        "TEST_DATABASE_URL",
        os.environ.get("DATABASE_URL", DEFAULT_POSTGRES_URL),
    ).replace("postgresql+psycopg://", "postgresql://", 1)
    try:
        with psycopg.connect(database_url, connect_timeout=2) as connection:
            connection.execute("SELECT 1")
    except psycopg.Error:
        return False
    return True


def redis_ready() -> bool:
    """Return whether the optional local Redis endpoint responds to PING."""
    try:
        with Redis.from_url(
            os.environ.get("REDIS_URL", DEFAULT_REDIS_URL),
            socket_connect_timeout=2,
            socket_timeout=2,
            retry=Retry(NoBackoff(), 0),
        ) as client:
            return client.ping() is True
    except (RedisError, ValueError, OSError):
        return False


def wait_until(name: str, check: Callable[[], bool], deadline: float) -> None:
    """Wait until a dependency is ready or fail at the shared monotonic deadline."""
    while time.monotonic() < deadline:
        if check():
            print(f"{name} is ready.")
            return
        time.sleep(1)
    raise TimeoutError(f"{name} did not become ready before the configured timeout")


def main() -> int:
    """Wait for PostgreSQL and, when requested, non-authoritative Redis."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--redis", action="store_true", help="also require local Redis readiness")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    if args.timeout <= 0 or args.timeout > 300:
        parser.error("--timeout must be greater than 0 and no more than 300 seconds")

    deadline = time.monotonic() + args.timeout
    wait_until("PostgreSQL", postgres_ready, deadline)
    if args.redis:
        wait_until("Redis", redis_ready, deadline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
