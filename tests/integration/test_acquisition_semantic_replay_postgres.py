"""Two independently charged requests must retain one original market source receipt."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from trading212_application import source_fallback as app
from trading212_application.source_providers import FxPair
from trading212_domain import CurrencyCode
from trading212_domain.sources import FxSnapshot, PriceBasis, PriceSnapshot, source_snapshot_digest
from trading212_persistence.acquisition_models import (
    ProviderAcquisitionAttemptModel as Attempt,
)
from trading212_persistence.acquisition_models import (
    ProviderAcquisitionDayModel as Day,
)
from trading212_persistence.acquisition_models import (
    ProviderAcquisitionMarketResultModel as MarketResult,
)
from trading212_persistence.acquisition_models import (
    ProviderAcquisitionPublicationModel as Publication,
)
from trading212_persistence.acquisition_records import AcquisitionCapability
from trading212_reference_data.premium_acquisition import acquisition_request_digest
from trading212_reference_data.premium_acquisition_types import AcquisitionFailureCode
from trading212_worker.premium_acquisition_runtime import PostgresPremiumAcquisitionRuntime
from trading212_worker.provider_source_fallback import ConfiguredCompatibleSourceAcquisition
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.provider_acquisition_case import acquisition_case
from tests.integration.test_provider_publication_postgres import batch, revoke
from tests.integration.test_xray_reads_postgres import (
    XrayReadCase,
)
from tests.integration.test_xray_reads_postgres import (
    xray_read_case as xray_read_case,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "capability", [AcquisitionCapability.DAILY_ADJUSTED, AcquisitionCapability.REFERENCE_FX]
)
async def test_new_request_replays_semantically_reused_original_market_source(
    xray_read_case: XrayReadCase,
    capability: AcquisitionCapability,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = acquisition_case(xray_read_case, capability=capability)
    runtime = PostgresPremiumAcquisitionRuntime(
        sessions=case.xray.sessions,
        principal=case.xray.principal,
        cursor_signing_key=XRAY_CURSOR_KEY,
        enabled=True,
    )
    first_batch = await batch(case, runtime)
    first_batch = replace(
        first_batch,
        provenance=replace(
            first_batch.provenance,
            expires_at=first_batch.provenance.observed_at + timedelta(hours=1),
        ),
    )
    first = await runtime.publish(first_batch)
    assert isinstance(first, (PriceSnapshot, FxSnapshot))
    second_case = replace(case, selection=replace(case.selection, request_id=uuid4()))
    second_batch = await batch(second_case, runtime)
    assert first_batch.provenance.attempt_id != second_batch.provenance.attempt_id
    assert first_batch.command.request_id != second_batch.command.request_id
    assert first_batch.facts == second_batch.facts
    assert first_batch.provenance.expires_at < second_batch.provenance.expires_at
    second = await runtime.publish(second_batch)
    assert isinstance(second, (PriceSnapshot, FxSnapshot))
    # The second success must not renew the retained source or its original grant.
    assert second == first
    assert second.provenance.first_observed_at == first_batch.provenance.first_known_at
    with case.xray.sessions() as session:
        publications = tuple(
            session.scalars(
                select(Publication).where(Publication.owner_id == case.selection.owner_id)
            )
        )
        assert len(publications) == 1
        original = publications[0]
        assert original.attempt_id == first_batch.provenance.attempt_id
        assert original.first_known_at == first_batch.provenance.first_known_at
        assert original.expires_at == first_batch.provenance.expires_at
        results = tuple(
            session.scalars(
                select(MarketResult).where(MarketResult.owner_id == case.selection.owner_id)
            )
        )
        assert {result.attempt_id for result in results} == {
            first_batch.provenance.attempt_id,
            second_batch.provenance.attempt_id,
        }
        assert {result.publication_id for result in results} == {original.id}
        original_publication_id = original.id
        second_result = next(
            result for result in results if result.attempt_id == second_batch.provenance.attempt_id
        )
        second_result_id = second_result.id
    for statement in (
        update(MarketResult)
        .where(MarketResult.id == second_result_id)
        .values(publication_id=original_publication_id),
        delete(MarketResult).where(MarketResult.id == second_result_id),
    ):
        with (
            pytest.raises(IntegrityError, match="Acquisition market results are immutable"),
            case.xray.sessions() as session,
            session.begin(),
        ):
            session.execute(statement)

    def charged() -> tuple[int, int]:
        with case.xray.sessions() as session:
            attempts = session.scalar(
                select(func.count())
                .select_from(Attempt)
                .where(Attempt.owner_id == case.selection.owner_id)
            )
            days = session.scalar(
                select(func.sum(Day.charged_attempts)).where(
                    Day.owner_id == case.selection.owner_id
                )
            )
            assert attempts is not None and days is not None
            return attempts, days

    assert charged() == (2, 2)
    pin = app.RetainedSourceCandidate(
        snapshot_id=UUID(first.id), content_digest=source_snapshot_digest(first)
    )
    assert case.mapping.calendar_id is not None
    common: dict[str, Any] = {
        "owner_id": case.selection.owner_id,
        "account_id": case.selection.account_id,
        "calendar_id": case.mapping.calendar_id,
        "calendar_version": case.calendar.version,
        "period": case.calendar.period,
        "source_cutoff_at": datetime.now(UTC),
        "candidates": (),
        "enabled": True,
        "accepted_qualities": (first.coverage.quality,),
        "acquisition": app.FallbackAcquisitionPin(
            request_id=second_case.selection.request_id,
            mapping_version_id=case.selection.mapping_version_id,
        ),
    }
    plan: app.PriceFallbackPlan | app.FxFallbackPlan
    if isinstance(first, PriceSnapshot):
        assert first.series.instrument_id is not None
        plan = app.PriceFallbackPlan(
            **common,
            instrument_id=UUID(first.series.instrument_id),
            currency=first.series.currency,
            basis=PriceBasis.RAW_CLOSE,
        )
    else:
        plan = app.FxFallbackPlan(
            **common,
            pairs=(FxPair(base=CurrencyCode("EUR"), quote=CurrencyCode("USD")),),
        )

    async def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("A semantically reused successful request must not acquire again")

    monkeypatch.setattr(runtime.acquisition, "acquire_daily_adjusted", forbidden)
    monkeypatch.setattr(runtime.acquisition, "acquire_ecb_reference_fx", forbidden)
    bridge = ConfiguredCompatibleSourceAcquisition(runtime)
    replay = (
        await bridge.acquire_price(case.xray.principal, plan)
        if isinstance(plan, app.PriceFallbackPlan)
        else await bridge.acquire_fx(case.xray.principal, plan)
    )
    assert replay == pin
    assert charged() == (2, 2)
    # Reuse association cannot override current original-source authority.
    revoke(case)
    with pytest.raises(app.SourceFallbackError) as denied:
        if isinstance(plan, app.PriceFallbackPlan):
            await bridge.acquire_price(case.xray.principal, plan)
        else:
            await bridge.acquire_fx(case.xray.principal, plan)
    assert denied.value.reason is app.SourceFallbackReason.ACQUISITION_UNAVAILABLE
    assert charged() == (2, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke_original_rights", [False, True])
async def test_sql_market_result_requires_success_and_current_original_authority(
    xray_read_case: XrayReadCase, revoke_original_rights: bool
) -> None:
    case = acquisition_case(xray_read_case)
    runtime = PostgresPremiumAcquisitionRuntime(
        sessions=case.xray.sessions,
        principal=case.xray.principal,
        cursor_signing_key=XRAY_CURSOR_KEY,
        enabled=True,
    )
    successful = await batch(case, runtime)
    saved = await runtime.publish(successful)
    assert isinstance(saved, PriceSnapshot)
    with case.xray.sessions() as session:
        publication_id = session.scalar(
            select(Publication.id).where(
                Publication.owner_id == case.selection.owner_id,
                Publication.source_id == UUID(saved.id),
            )
        )
        assert publication_id is not None
    command = replace(successful.command, request_id=uuid4())
    now = datetime.now(UTC)
    permit = await runtime.resolve(command, now=now)
    assert permit is not None
    attempt = await runtime.reserve(
        command, permit, request_digest=acquisition_request_digest(command, permit), now=now
    )
    assert attempt is not None
    observed = datetime.now(UTC)
    assert await runtime.finish(
        attempt,
        outcome=None if revoke_original_rights else AcquisitionFailureCode.PERMANENT_FAILURE,
        observed_at=observed,
        retry_at=None,
    )
    if revoke_original_rights:
        revoke(case)
    reason = (
        "Market result must retain exact original source authority"
        if revoke_original_rights
        else "Market result requires a successful matching acquisition"
    )
    with (
        pytest.raises(IntegrityError, match=reason),
        case.xray.sessions() as session,
        session.begin(),
    ):
        session.add(
            MarketResult(
                owner_id=case.selection.owner_id,
                attempt_id=attempt.id,
                publication_id=publication_id,
                observed_at=observed,
                created_at=datetime.now(UTC),
            )
        )
        session.flush()
