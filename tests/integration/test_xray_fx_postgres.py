"""Actual licensed FX observations and empty-batch gaps preserve the saved broker basis."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from trading212_analytics.source_policy import assess_fx_coverage
from trading212_application import source_providers as ports
from trading212_application import sources as sources_app
from trading212_application import xray as app
from trading212_application.source_ingestion import SourceProviderRegistration
from trading212_domain import xray as d
from trading212_domain.sources import (
    FxObservation,
    MarketSession,
    ObservationState,
    SourceCalendar,
    SourcePeriod,
    SourceProvenance,
)
from trading212_domain.values import CurrencyCode
from trading212_domain.xray_codec import decode_xray_input
from trading212_persistence.source_models import FxObservationModel, SourceCoverageGapModel
from trading212_persistence.source_service import PostgresSourceService
from trading212_persistence.xray_run_models import XrayInputSnapshotModel
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID, XRAY_AT, XRAY_EFFECTIVE
from trading212_worker.xray_seed import XRAY_CURSOR_KEY
from trading212_worker.xray_source_fixture import xray_license

from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def _service(case: XrayReadCase) -> PostgresSourceService:
    return PostgresSourceService(
        sessions=case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now[0]
    )


async def _fx_setup(case: XrayReadCase) -> SourceCalendar:
    source = _service(case)
    await source.configure_source_provider(
        case.principal,
        SourceProviderRegistration(
            id=xray_license().provider_id,
            key="synthetic-xray",
            name="Synthetic X-ray FX reference",
            adapter_version="synthetic-xray-fx-v1",
            configuration_state=sources_app.ProviderConfigurationState.CONFIGURED,
            synthetic=True,
            capabilities=(
                ports.SourceCapability.CLASSIFICATIONS,
                ports.SourceCapability.CONSTITUENTS,
                ports.SourceCapability.FX_RATES,
            ),
        ),
        idempotency_key="xray-fx:provider",
        correlation_id="xray-fx",
    )
    calendar = SourceCalendar(
        id="synthetic-xray-fx-calendar",
        version="1",
        timezone="UTC",
        period=SourcePeriod(start=XRAY_AT.date(), end=XRAY_AT.date()),
        sessions=(MarketSession(session_date=XRAY_AT.date(), close_at=XRAY_AT),),
    )
    await source.register_source_calendar(
        case.principal, calendar, idempotency_key="xray-fx:calendar", correlation_id="xray-fx"
    )
    return calendar


async def _ingest_fx(
    case: XrayReadCase,
    calendar: SourceCalendar,
    rates: tuple[tuple[str, str, str], ...],
    *,
    revision: int = 1,
    missing: str | None = None,
) -> str:
    license = xray_license()
    pairs = tuple((CurrencyCode(base), CurrencyCode(quote)) for base, quote, _ in rates)
    request = ports.FxRatesRequest(
        provider_id=license.provider_id,
        license_version_id=license.id,
        pairs=tuple(ports.FxPair(base=base, quote=quote) for base, quote in pairs),
        period=calendar.period,
        source_cutoff_at=case.now[0],
        calendar_id=calendar.id,
        calendar_version=calendar.version,
    )
    observations = (
        ()
        if missing == "empty"
        else tuple(
            FxObservation(
                base=CurrencyCode(base),
                quote=CurrencyCode(quote),
                session_date=XRAY_AT.date(),
                effective_at=XRAY_AT,
                rate=None if missing else Decimal(rate),
                state=ObservationState.MISSING if missing else ObservationState.AVAILABLE,
                batch_key="synthetic-xray-fx-fixing",
            )
            for base, quote, rate in rates
        )
    )
    page = ports.FxRatePage(
        provenance=SourceProvenance(
            provider_id=license.provider_id,
            license_version_id=license.id,
            adapter_version="synthetic-xray-fx-v1",
            schema_version="1",
            source_revision=f"fx-{revision}",
            revision_order=revision,
            effective_at=XRAY_AT,
            first_observed_at=XRAY_EFFECTIVE,
            synthetic=True,
        ),
        period=calendar.period,
        coverage=assess_fx_coverage(calendar, calendar.period, observations, pairs=pairs),
        observations=observations,
    )
    result = await _service(case).ingest_fx_rates(
        case.principal,
        request,
        (page,),
        idempotency_key=f"xray-fx:revision:{revision}",
        correlation_id="xray-fx",
    )
    return result.id


async def _gbp(case: XrayReadCase) -> app.ExposuresView:
    result = await case.service.get_effective_exposure(
        case.principal,
        XRAY_ACCOUNT_ID,
        query=app.EffectiveExposureQuery(
            request=replace(
                case.request(),
                currency=app.ExplicitCurrency(reporting_currency=CurrencyCode("GBP")),
            )
        ),
    )
    assert isinstance(result, app.ExposuresView)
    return result


def _input(case: XrayReadCase, view: app.ExposuresView) -> d.XrayInput:
    with case.sessions() as session:
        capture = session.get(XrayInputSnapshotModel, UUID(view.context.input_snapshot_id))
        assert capture is not None
        return decode_xray_input(capture.canonical_input)


@pytest.mark.parametrize(
    "rates,operations",
    [
        ((("EUR", "GBP", "0.8"),), ("multiply",)),
        ((("GBP", "EUR", "1.25"),), ("divide",)),
        ((("EUR", "USD", "1.25"), ("USD", "GBP", "0.64")), ("multiply", "multiply")),
    ],
)
def test_real_licensed_routes_convert_saved_reporting_money_once(
    xray_read_case: XrayReadCase,
    rates: tuple[tuple[str, str, str], ...],
    operations: tuple[str, ...],
) -> None:
    case = xray_read_case
    calendar = asyncio.run(_fx_setup(case))
    snapshot_id = asyncio.run(_ingest_fx(case, calendar, rates))
    response = asyncio.run(_gbp(case))
    assert response.summary.total.value is not None
    assert response.summary.total.value.amount == Decimal("800")
    value = _input(case, response)
    broker = value.broker_fx[0]
    root = next(row for row in value.positions if row.root.key == broker.root_key)
    attempt = next(row for row in value.licensed_fx if row.consumer_key == broker.root_key)
    assert root.original_value.value is not None and root.original_value.value.amount == Decimal(
        "62.50"
    )
    assert root.original_value.value.currency.value == "USD"
    assert attempt.input_value.value is not None and attempt.input_value.value.amount == Decimal(
        "50"
    )
    assert attempt.input_value.value.currency.value == "EUR"
    assert root.reporting_value.value is not None and root.reporting_value.value.amount == Decimal(
        "40"
    )
    assert tuple(leg.operation for leg in attempt.legs) == operations
    with case.sessions() as session:
        for leg in attempt.legs:
            assert leg.snapshot_id == UUID(snapshot_id)
            assert leg.first_known_at.value == XRAY_AT
            observation = session.get(FxObservationModel, leg.observation_id)
            assert observation is not None and observation.snapshot_id == leg.snapshot_id


@pytest.mark.parametrize("missing", ["empty", "observation"])
def test_new_missing_fx_blocks_older_quote_and_retains_actual_gap_identity(
    xray_read_case: XrayReadCase,
    missing: str,
) -> None:
    case = xray_read_case
    calendar = asyncio.run(_fx_setup(case))
    rates = (("EUR", "GBP", "0.8"),)
    asyncio.run(_ingest_fx(case, calendar, rates))
    first = asyncio.run(_gbp(case))
    gap_snapshot = asyncio.run(_ingest_fx(case, calendar, rates, revision=2, missing=missing))
    response = asyncio.run(_gbp(case))
    assert response.context.run_id != first.context.run_id
    assert response.summary.total.value is None
    value = _input(case, response)
    attempt = next(
        row for row in value.licensed_fx if row.consumer_key == value.broker_fx[0].root_key
    )
    assert attempt.input_value.value is not None and attempt.input_value.value.amount == Decimal(
        "50"
    )
    assert len(attempt.legs) == 1
    leg = attempt.legs[0]
    assert leg.snapshot_id == UUID(gap_snapshot) and leg.rate is None
    assert leg.state is ObservationState.MISSING
    dependency = next(row for row in value.source_dependencies if row.id == leg.source_reference_id)
    with case.sessions() as session:
        if missing == "empty":
            assert leg.observation_id is None and leg.coverage_gap_id is not None
            gap = session.get(SourceCoverageGapModel, leg.coverage_gap_id)
            assert gap is not None and gap.fx_snapshot_id == leg.snapshot_id
            assert gap.source_key == "EUR:GBP"
            assert dependency.reference.kind is d.XrayReferenceKind.FX_COVERAGE_GAP
        else:
            assert leg.observation_id is not None and leg.coverage_gap_id is None
            assert session.get(FxObservationModel, leg.observation_id) is not None
            assert dependency.reference.kind is d.XrayReferenceKind.FX_OBSERVATION


def test_future_first_known_fx_gap_does_not_rewrite_old_cutoff(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    calendar = asyncio.run(_fx_setup(case))
    rates = (("EUR", "GBP", "0.8"),)
    asyncio.run(_ingest_fx(case, calendar, rates))
    first = asyncio.run(_gbp(case))
    case.now[0] += timedelta(minutes=1)
    asyncio.run(_ingest_fx(case, calendar, rates, revision=2, missing="empty"))
    replay = asyncio.run(_gbp(case))
    assert replay.context.run_id == first.context.run_id
    assert replay.summary.total.value is not None
    assert replay.summary.total.value.amount == Decimal("800")


def test_triangulation_requires_one_retained_snapshot_and_fixing(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    calendar = asyncio.run(_fx_setup(case))
    first = (("EUR", "USD", "1.25"),)
    second = (("USD", "GBP", "0.64"),)
    asyncio.run(_ingest_fx(case, calendar, first))
    asyncio.run(_ingest_fx(case, calendar, second, revision=2))
    unavailable = asyncio.run(_gbp(case))
    assert unavailable.summary.total.value is None
    compatible = asyncio.run(_ingest_fx(case, calendar, first + second, revision=3))
    available = asyncio.run(_gbp(case))
    assert available.summary.total.value is not None
    assert available.summary.total.value.amount == Decimal("800")
    value = _input(case, available)
    assert all(str(leg.snapshot_id) == compatible for row in value.licensed_fx for leg in row.legs)
