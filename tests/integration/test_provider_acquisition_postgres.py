"""Real concurrent quota, restart and immutable receipt boundaries; no provider I/O."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from trading212_persistence.acquisition_authority import grant_digest
from trading212_persistence.acquisition_models import (
    ProviderAcquisitionAttemptModel as Attempt,
)
from trading212_persistence.acquisition_models import (
    ProviderAcquisitionDayModel as Day,
)
from trading212_persistence.acquisition_models import (
    ProviderAcquisitionRequestModel as Request,
)
from trading212_persistence.acquisition_models import (
    ProviderAcquisitionSlotModel as Slot,
)
from trading212_persistence.acquisition_models import (
    ProviderCapabilityGrantModel as Grant,
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


@pytest.mark.asyncio
async def test_concurrent_restart_reservation_has_one_slot_and_one_charge(
    xray_read_case: XrayReadCase,
) -> None:
    case = acquisition_case(xray_read_case)
    basis = await case.store.resolve(case.selection)
    assert basis is not None
    other = PostgresAcquisitionStore(
        sessions=case.xray.sessions, principal=case.xray.principal, enabled=True
    )
    results = await asyncio.gather(
        case.store.reserve(case.selection, basis, request_digest="a" * 64),
        other.reserve(case.selection, basis, request_digest="a" * 64),
    )
    successful = [value for value in results if value is not None]
    assert len(successful) == 1
    receipt = successful[0]
    with case.xray.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Attempt)
                .where(Attempt.owner_id == case.selection.owner_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(Day.charged_attempts).where(Day.owner_id == case.selection.owner_id)
            )
            == 1
        )
        assert (
            session.scalar(select(Slot.attempt_id).where(Slot.owner_id == case.selection.owner_id))
            == receipt.id
        )
    observed = datetime.now(UTC)
    assert await other.finish(
        receipt,
        outcome=AcquisitionOutcome.AUTHENTICATION_FAILED,
        observed_at=observed,
        retry_at=None,
    )
    assert await case.store.finish(
        receipt,
        outcome=AcquisitionOutcome.AUTHENTICATION_FAILED,
        observed_at=observed,
        retry_at=None,
    )
    assert not await case.store.finish(receipt, outcome=None, observed_at=observed, retry_at=None)
    assert await other.reserve(case.selection, basis, request_digest="a" * 64) is None
    with case.xray.sessions() as session:
        assert (
            session.scalar(
                select(Day.charged_attempts).where(Day.owner_id == case.selection.owner_id)
            )
            == 1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "capability,ceiling",
    [(AcquisitionCapability.DAILY_ADJUSTED, 25), (AcquisitionCapability.REFERENCE_FX, 24)],
)
async def test_actual_provider_cap_counts_every_failed_reservation(
    xray_read_case: XrayReadCase, capability: AcquisitionCapability, ceiling: int
) -> None:
    case = acquisition_case(xray_read_case, capability=capability)
    basis = await case.store.resolve(case.selection)
    assert basis is not None
    for ordinal in range(ceiling):
        selection = replace(case.selection, request_id=uuid4())
        receipt = await case.store.reserve(selection, basis, request_digest=f"{ordinal:064x}")
        assert receipt is not None
        assert await case.store.finish(
            receipt,
            outcome=AcquisitionOutcome.INVALID_SCHEMA,
            observed_at=datetime.now(UTC),
            retry_at=None,
        )
    assert (
        await case.store.reserve(
            replace(case.selection, request_id=uuid4()), basis, request_digest="f" * 64
        )
        is None
    )
    with case.xray.sessions() as session:
        assert (
            session.scalar(
                select(Day.charged_attempts).where(Day.owner_id == case.selection.owner_id)
            )
            == ceiling
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(Attempt)
                .where(Attempt.owner_id == case.selection.owner_id)
            )
            == ceiling
        )


@pytest.mark.asyncio
async def test_stricter_actual_allowance_and_current_denied_revision(
    xray_read_case: XrayReadCase,
) -> None:
    case = acquisition_case(xray_read_case, allowance=1)
    basis = await case.store.resolve(case.selection)
    assert basis is not None and basis.daily_allowance == 1
    receipt = await case.store.reserve(case.selection, basis, request_digest="a" * 64)
    assert receipt is not None
    assert await case.store.finish(
        receipt,
        outcome=AcquisitionOutcome.AUTHENTICATION_FAILED,
        observed_at=datetime.now(UTC),
        retry_at=None,
    )
    assert (
        await case.store.reserve(
            replace(case.selection, request_id=uuid4()), basis, request_digest="b" * 64
        )
        is None
    )
    now = datetime.now(UTC)
    revoked = Grant(
        id=uuid4(),
        owner_id=case.grant.owner_id,
        provider_id=case.grant.provider_id,
        scope_id=case.grant.scope_id,
        version_number=2,
        license_version_id=case.grant.license_version_id,
        effective_at=now,
        expires_at=now + timedelta(days=1),
        store_allowed=False,
        display_allowed=False,
        report_allowed=False,
        export_allowed=False,
        daily_allowance=0,
        evidence_key="synthetic-revocation",
        content_digest="0" * 64,
        created_at=now,
    )
    revoked.content_digest = grant_digest(revoked)
    with case.xray.sessions() as session, session.begin():
        session.add(revoked)
    assert await case.store.resolve(case.selection) is None
    assert not await case.store.recheck(case.selection, basis)


@pytest.mark.asyncio
async def test_three_scheduled_attempts_keep_original_twenty_second_deadline(
    xray_read_case: XrayReadCase,
) -> None:
    case = acquisition_case(xray_read_case)
    basis = await case.store.resolve(case.selection)
    assert basis is not None
    receipts = []
    for ordinal in range(1, 4):
        receipt = await case.store.reserve(case.selection, basis, request_digest="a" * 64)
        assert receipt is not None and receipt.ordinal == ordinal
        receipts.append(receipt)
        at = datetime.now(UTC)
        due = None if ordinal == 3 else at + timedelta(seconds=ordinal)
        assert await case.store.finish(
            receipt, outcome=AcquisitionOutcome.TRANSIENT_FAILURE, observed_at=at, retry_at=due
        )
        if due is not None:
            assert await case.store.reserve(case.selection, basis, request_digest="a" * 64) is None
            await asyncio.sleep(ordinal + 0.02)
    assert {value.deadline for value in receipts} == {receipts[0].deadline}
    assert {value.first_started_at for value in receipts} == {receipts[0].first_started_at}
    assert await case.store.reserve(case.selection, basis, request_digest="a" * 64) is None
    assert await case.store.reserve(case.selection, basis, request_digest="b" * 64) is None


@pytest.mark.asyncio
async def test_expired_process_receipt_is_never_refunded_or_allowed_to_finish(
    xray_read_case: XrayReadCase,
) -> None:
    case = acquisition_case(xray_read_case)
    basis = await case.store.resolve(case.selection)
    assert basis is not None
    receipt = await case.store.reserve(case.selection, basis, request_digest="a" * 64)
    assert receipt is not None
    # The injected clock exercises restart expiry without a 20-second fixture sleep.
    restarted = PostgresAcquisitionStore(
        sessions=case.xray.sessions,
        principal=case.xray.principal,
        enabled=True,
        clock=lambda: receipt.deadline + timedelta(microseconds=1),
    )
    assert await restarted.reserve(case.selection, basis, request_digest="a" * 64) is None
    assert not await restarted.finish(
        receipt, outcome=None, observed_at=receipt.deadline, retry_at=None
    )
    with case.xray.sessions() as session:
        row = session.get(Attempt, receipt.id)
        assert row is not None and row.outcome == "attempt_fence_lost"
        assert (
            session.scalar(
                select(Day.charged_attempts).where(Day.owner_id == case.selection.owner_id)
            )
            == 1
        )
        assert (
            session.scalar(select(Slot.attempt_id).where(Slot.owner_id == case.selection.owner_id))
            is None
        )


@pytest.mark.asyncio
async def test_direct_sql_cannot_refund_quota_or_reset_terminal_request(
    xray_read_case: XrayReadCase,
) -> None:
    case = acquisition_case(xray_read_case)
    basis = await case.store.resolve(case.selection)
    assert basis is not None
    receipt = await case.store.reserve(case.selection, basis, request_digest="a" * 64)
    assert receipt is not None
    assert await case.store.finish(
        receipt,
        outcome=AcquisitionOutcome.INVALID_SCHEMA,
        observed_at=datetime.now(UTC),
        retry_at=None,
    )
    for statement in (
        update(Day).where(Day.owner_id == case.selection.owner_id).values(charged_attempts=0),
        update(Request).where(Request.id == case.selection.request_id).values(state="inflight"),
        update(Attempt).where(Attempt.id == receipt.id).values(outcome=None),
    ):
        with pytest.raises(IntegrityError), case.xray.sessions() as session, session.begin():
            session.execute(statement)


@pytest.mark.asyncio
async def test_disabled_missing_and_foreign_account_have_no_attempt(
    xray_read_case: XrayReadCase,
) -> None:
    case = acquisition_case(xray_read_case)
    disabled = PostgresAcquisitionStore(sessions=case.xray.sessions, principal=case.xray.principal)
    assert await disabled.resolve(case.selection) is None
    assert await case.store.resolve(replace(case.selection, mapping_version_id=uuid4())) is None
    assert await case.store.resolve(replace(case.selection, account_id=uuid4())) is None
    with case.xray.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Attempt)) == 0
