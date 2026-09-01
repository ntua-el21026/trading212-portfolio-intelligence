from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from trading212_application.ingestion import (
    CURRENT_REFRESH_ORDER,
    FULL_REFRESH_ORDER,
    HISTORY_REFRESH_ORDER,
    Checkpoint,
    FailureCategory,
    IngestionCapability,
    IngestionCoordinator,
    IngestionFailure,
    IngestionRun,
    InMemoryIngestionStore,
    InMemoryRateCoordinator,
    RateObservation,
    RefreshScope,
    RunLease,
    RunMode,
    RunStatus,
    SourcePage,
    SourceRecord,
    capabilities_for_scope,
    validate_refresh_capabilities,
)
from trading212_application.refresh_semantics import (
    RefreshIdempotencyConflictError,
    RefreshRequestSemantics,
)

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        (RefreshScope.CURRENT, CURRENT_REFRESH_ORDER),
        (RefreshScope.HISTORY, HISTORY_REFRESH_ORDER),
        (RefreshScope.ALL, FULL_REFRESH_ORDER),
    ],
)
def test_refresh_scopes_map_to_frozen_capability_orders(
    scope: RefreshScope,
    expected: tuple[IngestionCapability, ...],
) -> None:
    assert capabilities_for_scope(scope) == expected
    assert validate_refresh_capabilities(expected) == expected


def test_refresh_selection_rejects_arbitrary_capability_subsets() -> None:
    with pytest.raises(ValueError, match="supported refresh scope"):
        validate_refresh_capabilities((IngestionCapability.ACCOUNT,))


def _record(
    record_id: str,
    *,
    amount: str = "10.00",
    timestamp: datetime = NOW,
) -> SourceRecord:
    return SourceRecord(
        provider_record_id=record_id,
        source_timestamp=timestamp,
        observed_at=NOW,
        payload={"id": record_id, "amount": Decimal(amount), "currency": "EUR"},
        schema_version="trading212-v0-20260831",
    )


class ScriptedProvider:
    def __init__(
        self,
        scripts: dict[
            IngestionCapability,
            Callable[[Checkpoint | None], SourcePage],
        ],
    ) -> None:
        self.scripts = scripts
        self.calls: list[tuple[IngestionCapability, Checkpoint | None]] = []

    async def read_page(
        self,
        *,
        owner_id: str,
        account_id: str,
        capability: IngestionCapability,
        checkpoint: Checkpoint | None,
        correlation_id: str,
    ) -> SourcePage:
        del owner_id, account_id, correlation_id
        self.calls.append((capability, checkpoint))
        return self.scripts[capability](checkpoint)


def _coordinator(
    provider: ScriptedProvider,
    store: InMemoryIngestionStore | None = None,
    *,
    max_pages: int = 10,
) -> tuple[IngestionCoordinator, InMemoryIngestionStore]:
    selected_store = store or InMemoryIngestionStore()
    return (
        IngestionCoordinator(
            provider=provider,
            store=selected_store,
            clock=lambda: NOW,
            max_pages_per_capability=max_pages,
        ),
        selected_store,
    )


async def _begin_memory_run(
    store: InMemoryIngestionStore,
    *,
    owner_id: str = "owner-1",
    account_id: str = "account-1",
    mode: RunMode = RunMode.FULL,
    capabilities: tuple[IngestionCapability, ...] = (IngestionCapability.ACCOUNT,),
    idempotency_key: str = "semantic-refresh",
    correlation_id: str = "semantic-refresh-correlation",
    now: datetime = NOW,
    lease_duration: timedelta = timedelta(minutes=5),
) -> tuple[IngestionRun, RunLease | None]:
    return await store.begin_run(
        owner_id=owner_id,
        account_id=account_id,
        mode=mode,
        capabilities=capabilities,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        now=now,
        lease_duration=lease_duration,
    )


@pytest.mark.asyncio
async def test_repeated_ingestion_is_idempotent() -> None:
    capability = IngestionCapability.TRANSACTIONS
    provider = ScriptedProvider({capability: lambda _: SourcePage((_record("tx-1"),), None, True)})
    coordinator, store = _coordinator(provider)
    first = await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.FULL,
        idempotency_key="refresh-1",
        capabilities=(capability,),
    )
    second = await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.INCREMENTAL,
        idempotency_key="refresh-2",
        capabilities=(capability,),
    )
    assert first.status is second.status is RunStatus.SUCCEEDED
    assert first.steps[0].inserted == 1
    assert second.steps[0].unchanged == 1
    assert len(store.source_records) == 1


@pytest.mark.asyncio
async def test_interrupted_ingestion_resumes_from_last_atomic_checkpoint() -> None:
    capability = IngestionCapability.TRANSACTIONS
    fail_once = True

    def script(checkpoint: Checkpoint | None) -> SourcePage:
        nonlocal fail_once
        if checkpoint is None:
            return SourcePage((_record("tx-1"),), Checkpoint(cursor="page-2"), False)
        if fail_once:
            fail_once = False
            raise IngestionFailure(FailureCategory.INTERRUPTED, "synthetic worker stop")
        return SourcePage((_record("tx-2"),), None, True)

    provider = ScriptedProvider({capability: script})
    coordinator, store = _coordinator(provider)
    interrupted = await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.FULL,
        idempotency_key="interrupted",
        capabilities=(capability,),
    )
    assert interrupted.status is RunStatus.FAILED
    assert store.checkpoints[("account-1", capability)] == Checkpoint(
        cursor="page-2",
        source_timestamp=NOW,
    )

    resumed = await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.INCREMENTAL,
        idempotency_key="resumed",
        capabilities=(capability,),
    )
    assert resumed.status is RunStatus.SUCCEEDED
    assert provider.calls[-1] == (
        capability,
        Checkpoint(cursor="page-2", source_timestamp=NOW),
    )
    assert len(store.source_records) == 2


@pytest.mark.asyncio
async def test_duplicate_and_updated_provider_records_remain_auditable() -> None:
    capability = IngestionCapability.DIVIDENDS
    pages = iter(
        [
            SourcePage((_record("div-1"), _record("div-1")), None, True),
            SourcePage((_record("div-1", amount="12.00"),), None, True),
        ]
    )
    provider = ScriptedProvider({capability: lambda _: next(pages)})
    coordinator, store = _coordinator(provider)
    first = await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.FULL,
        idempotency_key="first",
        capabilities=(capability,),
    )
    second = await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.INCREMENTAL,
        idempotency_key="second",
        capabilities=(capability,),
    )
    assert first.steps[0].inserted == 1
    assert first.steps[0].unchanged == 1
    assert second.steps[0].updated == 1
    assert len(store.source_records) == 2


@pytest.mark.asyncio
async def test_completed_transaction_checkpoint_drives_bounded_incremental_overlap() -> None:
    capability = IngestionCapability.TRANSACTIONS
    source_at = NOW - timedelta(days=2)
    provider = ScriptedProvider(
        {
            capability: lambda _: SourcePage(
                (_record("tx-watermark", timestamp=source_at),), None, True
            )
        }
    )
    coordinator, _ = _coordinator(provider)

    await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.FULL,
        idempotency_key="watermark-full",
        capabilities=(capability,),
    )
    await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.INCREMENTAL,
        idempotency_key="watermark-incremental",
        capabilities=(capability,),
    )
    await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.FULL,
        idempotency_key="watermark-full-again",
        capabilities=(capability,),
    )

    assert provider.calls[0] == (capability, None)
    assert provider.calls[1] == (
        capability,
        Checkpoint(
            source_timestamp=source_at,
            overlap_started_at=source_at - timedelta(days=7),
        ),
    )
    assert provider.calls[2] == (capability, None)


@pytest.mark.asyncio
async def test_empty_completed_transaction_has_no_false_incremental_watermark() -> None:
    capability = IngestionCapability.TRANSACTIONS
    provider = ScriptedProvider({capability: lambda _: SourcePage((), None, True)})
    coordinator, _ = _coordinator(provider)

    await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.FULL,
        idempotency_key="empty-watermark-full",
        capabilities=(capability,),
    )
    await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.INCREMENTAL,
        idempotency_key="empty-watermark-incremental",
        capabilities=(capability,),
    )

    assert provider.calls == [(capability, None), (capability, None)]


@pytest.mark.asyncio
async def test_repeated_page_and_max_page_bounds_fail_visibly() -> None:
    capability = IngestionCapability.TRANSACTIONS
    repeated = SourcePage((), Checkpoint(cursor="same"), False)
    provider = ScriptedProvider({capability: lambda _: repeated})
    coordinator, _ = _coordinator(provider, max_pages=5)
    run = await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.FULL,
        idempotency_key="loop",
        capabilities=(capability,),
    )
    assert run.status is RunStatus.FAILED
    assert run.steps[0].failure_category is FailureCategory.PAGINATION
    assert "repeated" in (run.steps[0].failure_message or "")


@pytest.mark.asyncio
async def test_empty_intermediate_page_is_explicit_but_resumable() -> None:
    capability = IngestionCapability.HISTORICAL_ORDERS

    def script(checkpoint: Checkpoint | None) -> SourcePage:
        if checkpoint is None:
            return SourcePage((), Checkpoint(cursor="next"), False)
        return SourcePage((_record("order-history-1"),), None, True)

    coordinator, _ = _coordinator(ScriptedProvider({capability: script}))
    run = await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.FULL,
        idempotency_key="empty-page",
        capabilities=(capability,),
    )
    assert run.status is RunStatus.SUCCEEDED
    assert run.steps[0].pages == 2
    assert "empty intermediate page" in run.steps[0].warnings[0]


@pytest.mark.asyncio
async def test_partial_capability_failure_never_reports_success() -> None:
    account = IngestionCapability.ACCOUNT
    positions = IngestionCapability.POSITIONS

    def fail(_: Checkpoint | None) -> SourcePage:
        raise IngestionFailure(FailureCategory.CONTRACT, "schema changed")

    provider = ScriptedProvider(
        {
            account: lambda _: SourcePage((_record("account"),), None, True),
            positions: fail,
        }
    )
    coordinator, _ = _coordinator(provider)
    run = await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.FULL,
        idempotency_key="partial",
        capabilities=(account, positions),
    )
    assert run.status is RunStatus.PARTIAL
    assert [step.status for step in run.steps] == [RunStatus.SUCCEEDED, RunStatus.FAILED]


@pytest.mark.asyncio
async def test_atomic_commit_failure_does_not_advance_checkpoint_or_source_state() -> None:
    capability = IngestionCapability.TRANSACTIONS
    provider = ScriptedProvider(
        {
            capability: lambda _: SourcePage(
                (_record("tx-1"),),
                Checkpoint(cursor="unsafe-to-advance"),
                False,
            )
        }
    )
    store = InMemoryIngestionStore()
    store.fail_next_commit = True
    coordinator, _ = _coordinator(provider, store)
    run = await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.FULL,
        idempotency_key="rollback",
        capabilities=(capability,),
    )
    assert run.status is RunStatus.FAILED
    assert ("account-1", capability) not in store.checkpoints
    assert store.source_records == {}


@pytest.mark.asyncio
async def test_concurrent_identical_refreshes_coalesce() -> None:
    capability = IngestionCapability.ACCOUNT
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingProvider(ScriptedProvider):
        async def read_page(self, **kwargs: object) -> SourcePage:
            entered.set()
            await release.wait()
            return SourcePage((_record("account"),), None, True)

    provider = BlockingProvider({})
    coordinator, _ = _coordinator(provider)
    first_task = asyncio.create_task(
        coordinator.refresh(
            owner_id="owner-1",
            account_id="account-1",
            mode=RunMode.FULL,
            idempotency_key="same-refresh",
            capabilities=(capability,),
        )
    )
    await entered.wait()
    coalesced = await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.FULL,
        idempotency_key="same-refresh",
        capabilities=(capability,),
    )
    assert coalesced.status is RunStatus.RUNNING
    release.set()
    completed = await first_task
    assert completed.id == coalesced.id
    assert completed.status is RunStatus.SUCCEEDED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("owner_id", "mode", "capabilities"),
    [
        ("owner-2", RunMode.FULL, (IngestionCapability.ACCOUNT,)),
        ("owner-1", RunMode.INCREMENTAL, (IngestionCapability.ACCOUNT,)),
        ("owner-1", RunMode.FULL, (IngestionCapability.POSITIONS,)),
    ],
)
async def test_active_idempotency_key_rejects_mismatched_requested_semantics(
    owner_id: str,
    mode: RunMode,
    capabilities: tuple[IngestionCapability, ...],
) -> None:
    store = InMemoryIngestionStore()
    first, first_lease = await _begin_memory_run(store)
    expected = RefreshRequestSemantics.create(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.FULL,
        capabilities=(IngestionCapability.ACCOUNT,),
    )

    with pytest.raises(RefreshIdempotencyConflictError):
        await _begin_memory_run(
            store,
            owner_id=owner_id,
            mode=mode,
            capabilities=capabilities,
        )

    coalesced, retry_lease = await _begin_memory_run(store)
    assert first_lease is not None
    assert coalesced.id == first.id
    assert retry_lease is None
    assert len(store.runs) == 1
    assert store._idempotency[("account-1", "semantic-refresh")] == (
        first.id,
        expected.fingerprint,
    )


@pytest.mark.asyncio
async def test_terminal_identical_retry_returns_same_logical_run_without_provider_read() -> None:
    capability = IngestionCapability.ACCOUNT
    provider = ScriptedProvider(
        {capability: lambda _: SourcePage((_record("account"),), None, True)}
    )
    coordinator, store = _coordinator(provider)

    first = await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.FULL,
        idempotency_key="terminal-semantic-refresh",
        capabilities=(capability,),
    )
    retry = await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.FULL,
        idempotency_key="terminal-semantic-refresh",
        capabilities=(capability,),
        correlation_id="terminal-retry-correlation",
    )

    assert retry == first
    assert len(store.runs) == 1
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_terminal_idempotency_key_rejects_mismatch_without_mutation() -> None:
    capability = IngestionCapability.ACCOUNT
    provider = ScriptedProvider(
        {capability: lambda _: SourcePage((_record("account"),), None, True)}
    )
    coordinator, store = _coordinator(provider)
    first = await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.FULL,
        idempotency_key="terminal-conflict",
        capabilities=(capability,),
    )

    with pytest.raises(RefreshIdempotencyConflictError):
        await coordinator.refresh(
            owner_id="owner-1",
            account_id="account-1",
            mode=RunMode.INCREMENTAL,
            idempotency_key="terminal-conflict",
            capabilities=(capability,),
        )

    assert store.runs == {first.id: first}
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_same_textual_idempotency_key_is_isolated_by_account() -> None:
    capability = IngestionCapability.ACCOUNT
    provider = ScriptedProvider(
        {capability: lambda _: SourcePage((_record("account"),), None, True)}
    )
    coordinator, store = _coordinator(provider)

    first = await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.FULL,
        idempotency_key="shared-textual-key",
        capabilities=(capability,),
    )
    second = await coordinator.refresh(
        owner_id="owner-1",
        account_id="account-2",
        mode=RunMode.FULL,
        idempotency_key="shared-textual-key",
        capabilities=(capability,),
    )

    assert first.id != second.id
    assert len(store.runs) == 2
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_concurrent_mismatched_refresh_conflicts_without_second_run() -> None:
    capability = IngestionCapability.ACCOUNT
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingProvider(ScriptedProvider):
        async def read_page(self, **kwargs: object) -> SourcePage:
            del kwargs
            entered.set()
            await release.wait()
            return SourcePage((_record("account"),), None, True)

    provider = BlockingProvider({})
    coordinator, store = _coordinator(provider)
    first_task = asyncio.create_task(
        coordinator.refresh(
            owner_id="owner-1",
            account_id="account-1",
            mode=RunMode.FULL,
            idempotency_key="concurrent-semantic-conflict",
            capabilities=(capability,),
        )
    )
    await entered.wait()
    try:
        with pytest.raises(RefreshIdempotencyConflictError):
            await coordinator.refresh(
                owner_id="owner-1",
                account_id="account-1",
                mode=RunMode.INCREMENTAL,
                idempotency_key="concurrent-semantic-conflict",
                capabilities=(capability,),
            )
    finally:
        release.set()

    completed = await first_task
    assert completed.status is RunStatus.SUCCEEDED
    assert len(store.runs) == 1


@pytest.mark.asyncio
async def test_expired_lease_takeover_retains_logical_run_and_terminal_binding() -> None:
    store = InMemoryIngestionStore()
    first, first_lease = await _begin_memory_run(
        store,
        lease_duration=timedelta(seconds=5),
    )
    before_expiry, before_expiry_lease = await _begin_memory_run(
        store,
        now=NOW + timedelta(seconds=4),
        lease_duration=timedelta(seconds=5),
    )
    takeover, takeover_lease = await _begin_memory_run(
        store,
        correlation_id="takeover-correlation",
        now=NOW + timedelta(seconds=6),
        lease_duration=timedelta(seconds=5),
    )

    assert first_lease is not None
    assert before_expiry.id == first.id
    assert before_expiry_lease is None
    assert takeover.id == first.id
    assert takeover_lease is not None
    assert takeover_lease.token != first_lease.token
    assert len(store.runs) == 1
    with pytest.raises(IngestionFailure, match="lease"):
        await store.heartbeat(
            run_id=first.id,
            lease_token=first_lease.token,
            now=NOW + timedelta(seconds=7),
        )

    finished = await store.finish_run(
        run_id=takeover.id,
        status=RunStatus.SUCCEEDED,
        steps=(),
        lease_token=takeover_lease.token,
        now=NOW + timedelta(seconds=7),
    )
    terminal_retry, terminal_lease = await _begin_memory_run(
        store,
        now=NOW + timedelta(seconds=8),
    )
    assert terminal_retry == finished
    assert terminal_lease is None


@pytest.mark.asyncio
async def test_requested_fingerprint_is_not_rebuilt_from_promoted_execution_mode() -> None:
    store = InMemoryIngestionStore()
    requested, lease = await _begin_memory_run(store, mode=RunMode.INCREMENTAL)
    assert lease is not None
    store.runs[requested.id] = replace(requested, mode=RunMode.FULL)

    same_request, same_request_lease = await _begin_memory_run(
        store,
        mode=RunMode.INCREMENTAL,
    )
    assert same_request.id == requested.id
    assert same_request.mode is RunMode.FULL
    assert same_request_lease is None
    with pytest.raises(RefreshIdempotencyConflictError):
        await _begin_memory_run(store, mode=RunMode.FULL)


@pytest.mark.asyncio
async def test_long_rate_and_provider_waits_renew_the_fenced_run_lease() -> None:
    capability = IngestionCapability.ACCOUNT
    stage = {"current": "idle"}

    class CountingStore(InMemoryIngestionStore):
        def __init__(self) -> None:
            super().__init__()
            self.renewals = {"rate": 0, "provider": 0}

        async def heartbeat(self, *, run_id: str, lease_token: str, now: datetime) -> None:
            current = stage["current"]
            if current in self.renewals:
                self.renewals[current] += 1
            await super().heartbeat(run_id=run_id, lease_token=lease_token, now=now)

    class SlowRateCoordinator:
        async def before_read(self, *, account_id: str, capability: IngestionCapability) -> None:
            del account_id, capability
            stage["current"] = "rate"
            await asyncio.sleep(0.7)
            stage["current"] = "idle"

        async def observe(
            self,
            *,
            account_id: str,
            capability: IngestionCapability,
            observation: RateObservation | None,
        ) -> None:
            del account_id, capability, observation

    class SlowProvider(ScriptedProvider):
        async def read_page(self, **kwargs: object) -> SourcePage:
            del kwargs
            stage["current"] = "provider"
            await asyncio.sleep(0.7)
            stage["current"] = "idle"
            return SourcePage((_record("slow-account"),), None, True)

    store = CountingStore()
    run = await IngestionCoordinator(
        provider=SlowProvider({}),
        store=store,
        rate_coordinator=SlowRateCoordinator(),
        clock=lambda: datetime.now(UTC),
        lease_duration=timedelta(milliseconds=300),
    ).refresh(
        owner_id="owner-1",
        account_id="account-1",
        mode=RunMode.FULL,
        idempotency_key="slow-provider-lease-renewal",
        capabilities=(capability,),
    )

    assert run.status is RunStatus.SUCCEEDED
    assert store.renewals["rate"] >= 3
    assert store.renewals["provider"] >= 3


@pytest.mark.asyncio
async def test_rate_observation_defers_the_next_account_capability_read() -> None:
    current = NOW
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        nonlocal current
        delays.append(delay)
        current += timedelta(seconds=delay)

    coordinator = InMemoryRateCoordinator(clock=lambda: current, sleep=sleep)
    observation = RateObservation(
        limit=1,
        period_seconds=5,
        remaining=0,
        reset_at=NOW + timedelta(seconds=5),
        used=1,
    )
    await coordinator.observe(
        account_id="account-1",
        capability=IngestionCapability.ACCOUNT,
        observation=observation,
    )
    await coordinator.before_read(
        account_id="account-1",
        capability=IngestionCapability.ACCOUNT,
    )
    assert delays == [5.0]


def test_source_payload_rejects_secret_shaped_fields() -> None:
    with pytest.raises(ValueError, match="sensitive"):
        SourceRecord(
            provider_record_id="bad",
            source_timestamp=NOW,
            observed_at=NOW,
            payload={"authorization": "synthetic-canary"},
            schema_version="test",
        )


def test_naive_source_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        SourceRecord(
            provider_record_id="bad-time",
            source_timestamp=datetime(2026, 1, 1),
            observed_at=NOW,
            payload={"id": "bad-time"},
            schema_version="test",
        )
