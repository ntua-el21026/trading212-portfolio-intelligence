"""Consolidated synthetic ingestion transitions from the Phase 1 manifest."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from trading212_application.ingestion import (
    Checkpoint,
    FailureCategory,
    IngestionCapability,
    IngestionCoordinator,
    IngestionFailure,
    InMemoryIngestionStore,
    InMemoryRateCoordinator,
    RateObservation,
    RunMode,
    RunStatus,
    SourcePage,
    SourceRecord,
)

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
CAPABILITY = IngestionCapability.TRANSACTIONS


def _record(record_id: str, observed_at: datetime) -> SourceRecord:
    return SourceRecord(
        provider_record_id=record_id,
        source_timestamp=observed_at,
        observed_at=observed_at,
        payload={
            "amount": Decimal("10"),
            "currency": "EUR",
            "id": record_id,
        },
        schema_version="synthetic-phase1-acceptance",
    )


@pytest.mark.asyncio
async def test_rate_limited_page_pauses_then_resumes_and_commits_successfully() -> None:
    current = NOW
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        nonlocal current
        delays.append(delay)
        current += timedelta(seconds=delay)

    class RateLimitedProvider:
        calls = 0

        async def read_page(
            self,
            *,
            owner_id: str,
            account_id: str,
            capability: IngestionCapability,
            checkpoint: Checkpoint | None,
            correlation_id: str,
        ) -> SourcePage:
            del owner_id, account_id, capability, correlation_id
            self.calls += 1
            if checkpoint is None:
                return SourcePage(
                    records=(_record("tx-1", current),),
                    next_checkpoint=Checkpoint(cursor="page-2"),
                    complete=False,
                    rate=RateObservation(
                        limit=1,
                        period_seconds=5,
                        remaining=0,
                        reset_at=NOW + timedelta(seconds=5),
                        used=1,
                    ),
                )
            assert checkpoint == Checkpoint(cursor="page-2")
            assert current == NOW + timedelta(seconds=5)
            return SourcePage(
                records=(_record("tx-2", current),),
                next_checkpoint=None,
                complete=True,
            )

    provider = RateLimitedProvider()
    store = InMemoryIngestionStore()
    run = await IngestionCoordinator(
        provider=provider,
        store=store,
        rate_coordinator=InMemoryRateCoordinator(clock=lambda: current, sleep=sleep),
        clock=lambda: current,
    ).refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.INCREMENTAL,
        idempotency_key="rate-limit-resume",
        capabilities=(CAPABILITY,),
    )

    assert run.status is RunStatus.SUCCEEDED
    assert run.steps[0].pages == 2
    assert provider.calls == 2
    assert delays == [5.0]
    assert len(store.source_records) == 2


@pytest.mark.asyncio
async def test_schema_incompatible_page_preserves_last_atomic_checkpoint() -> None:
    safe_checkpoint = Checkpoint(cursor="schema-page-2")

    class SchemaDriftProvider:
        async def read_page(
            self,
            *,
            owner_id: str,
            account_id: str,
            capability: IngestionCapability,
            checkpoint: Checkpoint | None,
            correlation_id: str,
        ) -> SourcePage:
            del owner_id, account_id, capability, correlation_id
            if checkpoint is None:
                return SourcePage(
                    records=(_record("tx-safe", NOW),),
                    next_checkpoint=safe_checkpoint,
                    complete=False,
                )
            raise IngestionFailure(
                FailureCategory.CONTRACT,
                "synthetic provider schema is incompatible",
            )

    store = InMemoryIngestionStore()
    run = await IngestionCoordinator(
        provider=SchemaDriftProvider(),
        store=store,
        clock=lambda: NOW,
    ).refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.INCREMENTAL,
        idempotency_key="schema-drift",
        capabilities=(CAPABILITY,),
    )

    assert run.status is RunStatus.FAILED
    assert run.steps[0].failure_category is FailureCategory.CONTRACT
    assert run.steps[0].records_seen == 1
    assert store.checkpoints[("account-1", CAPABILITY)] == Checkpoint(
        cursor="schema-page-2",
        source_timestamp=NOW,
    )
    assert len(store.source_records) == 1
