"""Actual retained canonical publication, source authority and no monetary SELECTs."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import event
from trading212_application import source_fallback as app
from trading212_application.source_providers import FxPair
from trading212_domain import CurrencyCode
from trading212_domain.sources import FxSnapshot, PriceBasis, PriceSnapshot, source_snapshot_digest
from trading212_persistence.acquisition_records import AcquisitionCapability
from trading212_persistence.source_fallback import PostgresCompatibleSourceReader
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
async def test_actual_source_selection_replays_original_success_without_new_attempt_or_decode(
    xray_read_case: XrayReadCase, capability: AcquisitionCapability, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = acquisition_case(xray_read_case, capability=capability)
    runtime = PostgresPremiumAcquisitionRuntime(
        sessions=case.xray.sessions,
        principal=case.xray.principal,
        cursor_signing_key=XRAY_CURSOR_KEY,
        enabled=True,
    )
    acquired = await batch(case, runtime)
    saved = await runtime.publish(acquired)
    assert isinstance(saved, (PriceSnapshot, FxSnapshot)) and case.mapping.calendar_id is not None
    pin = app.RetainedSourceCandidate(
        snapshot_id=UUID(saved.id), content_digest=source_snapshot_digest(saved)
    )
    selected_at = datetime.now(UTC)
    reader = PostgresCompatibleSourceReader(
        sessions=case.xray.sessions, cursor_signing_key=XRAY_CURSOR_KEY
    )
    plan: app.PriceFallbackPlan | app.FxFallbackPlan
    if isinstance(saved, PriceSnapshot):
        assert saved.series.instrument_id is not None
        plan = app.PriceFallbackPlan(
            owner_id=case.selection.owner_id,
            account_id=case.selection.account_id,
            calendar_id=case.mapping.calendar_id,
            calendar_version=case.calendar.version,
            period=case.calendar.period,
            source_cutoff_at=selected_at,
            candidates=(pin,),
            enabled=True,
            accepted_qualities=(saved.coverage.quality,),
            instrument_id=UUID(saved.series.instrument_id),
            currency=saved.series.currency,
            basis=PriceBasis.RAW_CLOSE,
        )
    else:
        plan = app.FxFallbackPlan(
            owner_id=case.selection.owner_id,
            account_id=case.selection.account_id,
            calendar_id=case.mapping.calendar_id,
            calendar_version=case.calendar.version,
            period=case.calendar.period,
            source_cutoff_at=selected_at,
            candidates=(pin,),
            enabled=True,
            accepted_qualities=(saved.coverage.quality,),
            pairs=(FxPair(base=CurrencyCode("EUR"), quote=CurrencyCode("USD")),),
        )
    statements: list[str] = []

    def before(*args: Any) -> None:
        statements.append(str(args[2]).lower())

    event.listen(case.xray.engine, "before_cursor_execute", before)
    try:
        result = (
            await app.ExplicitSourceFallback(reader).select_price(case.xray.principal, plan)
            if isinstance(plan, app.PriceFallbackPlan)
            else await app.ExplicitSourceFallback(reader).select_fx(case.xray.principal, plan)
        )
    finally:
        event.remove(case.xray.engine, "before_cursor_execute", before)
    assert result.selected is not None and result.selected.snapshot_id == pin.snapshot_id
    assert result.selected.expected_count == result.selected.available_count == 1
    assert result.selected.first_known_at == acquired.provenance.first_known_at
    assert result.selected.original_expires_at == acquired.provenance.expires_at
    assert not any(
        "price_observations.value" in sql or "fx_observations.rate" in sql for sql in statements
    )

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("A saved success must not acquire again")

    monkeypatch.setattr(runtime.acquisition, "acquire_daily_adjusted", forbidden)
    monkeypatch.setattr(runtime.acquisition, "acquire_ecb_reference_fx", forbidden)
    bridge = ConfiguredCompatibleSourceAcquisition(runtime)
    replay = replace(
        plan,
        candidates=(),
        acquisition=app.FallbackAcquisitionPin(
            request_id=case.selection.request_id,
            mapping_version_id=case.selection.mapping_version_id,
        ),
    )
    with pytest.raises(app.SourceFallbackError) as denied:
        if isinstance(replay, app.PriceFallbackPlan):
            await bridge.acquire_price(
                replace(case.xray.principal, subject="other-current-principal"), replay
            )
        else:
            await bridge.acquire_fx(
                replace(case.xray.principal, subject="other-current-principal"), replay
            )
    assert denied.value.reason is app.SourceFallbackReason.ACCESS_DENIED
    candidate = (
        await bridge.acquire_price(case.xray.principal, replay)
        if isinstance(replay, app.PriceFallbackPlan)
        else await bridge.acquire_fx(case.xray.principal, replay)
    )
    assert candidate == pin
    revoke(case)
    with pytest.raises(app.SourceFallbackError):
        if isinstance(plan, app.PriceFallbackPlan):
            await reader.inspect_price(case.xray.principal, plan, pin)
        else:
            await reader.inspect_fx(case.xray.principal, plan, pin)
