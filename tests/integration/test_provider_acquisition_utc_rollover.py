"""Simulated UTC rollover exercises real PG guards without renewing request budgets."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from trading212_persistence.acquisition_models import (
    ProviderAcquisitionDayModel as Day,
)
from trading212_persistence.acquisition_models import (
    ProviderAcquisitionRequestModel as Request,
)
from trading212_persistence.acquisition_records import AcquisitionCapability, AcquisitionOutcome
from trading212_persistence.acquisition_store import PostgresAcquisitionStore

from tests.integration.provider_acquisition_case import acquisition_case
from tests.integration.test_xray_reads_postgres import (
    XrayReadCase,
)
from tests.integration.test_xray_reads_postgres import (
    xray_read_case as xray_read_case,
)

pytestmark = pytest.mark.integration


@contextmanager
def controlled_acquisition_clock(
    case: XrayReadCase, now: list[datetime]
) -> Iterator[Callable[[datetime], None]]:
    """Control the clock input, preserving every guard in this disposable DB.

    Waiting for wall-clock midnight is neither bounded nor deterministic. Replace
    only clock calls in the exact trigger function, then restore its definition.
    The test still exercises all state, quota, identity and deadline comparisons.
    No production function exposes a caller-controlled clock.
    """
    definition = text("SELECT pg_get_functiondef('acquisition_owned_guard()'::regprocedure)")
    with case.engine.begin() as connection:
        original = connection.scalar(definition)
        assert isinstance(original, str) and "clock_timestamp()" in original
        connection.exec_driver_sql("CREATE SCHEMA acquisition_test_clock")
        connection.exec_driver_sql(
            "CREATE TABLE acquisition_test_clock.instant "
            "(id integer PRIMARY KEY CHECK(id=1), at timestamptz NOT NULL)"
        )
        connection.execute(
            text("INSERT INTO acquisition_test_clock.instant VALUES(1,:at)"), {"at": now[0]}
        )
        connection.exec_driver_sql(
            "CREATE FUNCTION acquisition_test_clock.now() RETURNS timestamptz "
            "LANGUAGE sql STABLE AS $$ SELECT at FROM acquisition_test_clock.instant "
            "WHERE id=1 $$"
        )
        controlled = original.replace("clock_timestamp()", "acquisition_test_clock.now()")
        assert controlled.replace("acquisition_test_clock.now()", "clock_timestamp()") == original
        connection.exec_driver_sql(controlled)

    def advance(value: datetime) -> None:
        now[0] = value
        with case.engine.begin() as connection:
            connection.execute(
                text("UPDATE acquisition_test_clock.instant SET at=:at WHERE id=1"), {"at": value}
            )

    try:
        yield advance
    finally:
        with case.engine.begin() as connection:
            connection.exec_driver_sql(original)
            assert connection.scalar(definition) == original
            connection.exec_driver_sql("DROP FUNCTION acquisition_test_clock.now()")
            connection.exec_driver_sql("DROP TABLE acquisition_test_clock.instant")
            connection.exec_driver_sql("DROP SCHEMA acquisition_test_clock")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "capability", [AcquisitionCapability.DAILY_ADJUSTED, AcquisitionCapability.REFERENCE_FX]
)
async def test_same_request_retry_crosses_simulated_utc_daily_counter_boundary(
    xray_read_case: XrayReadCase, capability: AcquisitionCapability
) -> None:
    case = acquisition_case(xray_read_case, capability=capability, allowance=1)
    midnight = datetime.combine(datetime.now(UTC).date() + timedelta(days=1), time(), UTC)
    now = [midnight - timedelta(seconds=2)]
    store = PostgresAcquisitionStore(
        sessions=case.xray.sessions,
        principal=case.xray.principal,
        enabled=True,
        clock=lambda: now[0],
    )
    with controlled_acquisition_clock(case.xray, now) as advance:
        basis = await store.resolve(case.selection)
        assert basis is not None
        # A Python-only future clock is still rejected by the unchanged SQL guard.
        original = now[0]
        now[0] += timedelta(microseconds=1)
        assert await store.reserve(case.selection, basis, request_digest="a" * 64) is None
        now[0] = original
        first = await store.reserve(case.selection, basis, request_digest="a" * 64)
        assert first is not None
        advance(now[0] + timedelta(milliseconds=100))
        assert await store.finish(
            first,
            outcome=AcquisitionOutcome.RATE_LIMITED,
            observed_at=now[0],
            retry_at=now[0] + timedelta(seconds=1),
        )
        advance(midnight - timedelta(milliseconds=500))
        assert await store.reserve(case.selection, basis, request_digest="a" * 64) is None
        advance(midnight)
        second = await store.reserve(case.selection, basis, request_digest="a" * 64)
        assert second is not None
        assert (
            second.ordinal == 2
            and second.request_id == first.request_id
            and second.first_started_at == first.first_started_at
        )
        assert (
            second.deadline == first.deadline
            and second.deadline - first.first_started_at <= timedelta(seconds=20)
        )
        advance(now[0] + timedelta(milliseconds=100))
        assert await store.finish(
            second, outcome=AcquisitionOutcome.INVALID_SCHEMA, observed_at=now[0], retry_at=None
        )
        assert (
            await store.reserve(
                replace(case.selection, request_id=uuid4()), basis, request_digest="b" * 64
            )
            is None
        )
        with case.xray.sessions() as session:
            days = session.execute(
                select(Day.utc_day, Day.charged_attempts)
                .where(
                    Day.owner_id == case.selection.owner_id, Day.provider_id == basis.provider_id
                )
                .order_by(Day.utc_day)
            ).all()
            assert [(day, count) for day, count in days] == [
                (midnight.date() - timedelta(days=1), 1),
                (midnight.date(), 1),
            ]
            request = session.get(Request, first.request_id)
            assert request is not None
            assert (
                request.attempt_count == 2
                and request.first_started_at == first.first_started_at
                and request.deadline == first.deadline
            )
        advance(first.deadline + timedelta(seconds=1))
        assert await store.reserve(case.selection, basis, request_digest="a" * 64) is None
