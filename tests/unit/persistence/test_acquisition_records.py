"""Original deadline and private metadata validation independent of transport parsers."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from trading212_persistence.acquisition_records import (
    AcquisitionAttemptReceipt,
    AcquisitionOutcome,
    AcquisitionPublicationClock,
    AcquisitionStorageDenied,
    retry_due,
)

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


def receipt() -> AcquisitionAttemptReceipt:
    return AcquisitionAttemptReceipt(
        id=uuid4(),
        request_id=uuid4(),
        owner_id=uuid4(),
        provider_id=uuid4(),
        request_digest="a" * 64,
        ordinal=1,
        first_started_at=NOW,
        reserved_at=NOW,
        deadline=NOW + timedelta(seconds=20),
        lease_expires_at=NOW + timedelta(seconds=20),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"ordinal": True},
        {"ordinal": 4},
        {"request_digest": "secret-canary"},
        {"deadline": NOW + timedelta(seconds=21)},
        {"lease_expires_at": NOW + timedelta(seconds=21)},
        {"reserved_at": NOW + timedelta(seconds=20)},
    ],
)
def test_receipt_cannot_reset_original_deadline_or_invent_ordinal(
    changes: dict[str, Any],
) -> None:
    with pytest.raises(AcquisitionStorageDenied, match="not authorized"):
        replace(receipt(), **changes)


def test_retry_is_scheduled_with_original_deadline_and_exact_backoff() -> None:
    end = NOW + timedelta(seconds=20)
    assert retry_due(
        AcquisitionOutcome.TRANSIENT_FAILURE,
        1,
        observed_at=NOW,
        deadline=end,
        requested=NOW + timedelta(seconds=1),
    ) == NOW + timedelta(seconds=1)
    assert retry_due(
        AcquisitionOutcome.RATE_LIMITED,
        2,
        observed_at=NOW,
        deadline=end,
        requested=NOW + timedelta(seconds=5),
    ) == NOW + timedelta(seconds=5)
    for outcome, ordinal, delay in (
        (AcquisitionOutcome.INVALID_SCHEMA, 1, 1),
        (AcquisitionOutcome.TRANSIENT_FAILURE, 3, 3),
        (AcquisitionOutcome.RATE_LIMITED, 1, 20),
        (AcquisitionOutcome.TRANSIENT_FAILURE, 2, 1),
    ):
        with pytest.raises(AcquisitionStorageDenied):
            retry_due(
                outcome,
                ordinal,
                observed_at=NOW,
                deadline=end,
                requested=NOW + timedelta(seconds=delay),
            )


def test_original_publication_clock_is_not_sql_insert_time() -> None:
    clock = AcquisitionPublicationClock(
        acquired_at=NOW,
        first_known_at=NOW,
        expires_at=NOW + timedelta(days=1),
        content_digest="b" * 64,
    )
    assert clock.first_known_at == NOW
    with pytest.raises(AcquisitionStorageDenied):
        replace(clock, first_known_at=NOW + timedelta(seconds=1))
    with pytest.raises(AcquisitionStorageDenied):
        replace(clock, expires_at=NOW + timedelta(days=31))
