"""Actual source rows and acquisition grants; one reused PostgreSQL service, no HTTP."""

from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select, text, update
from trading212_analytics.source_policy import assess_fx_coverage
from trading212_application import sources as app
from trading212_application.queries import CursorValidationError
from trading212_application.source_ingestion import SourceProviderRegistration
from trading212_application.source_providers import (
    FxPair,
    FxRatePage,
    FxRatesRequest,
    SourceCapability,
)
from trading212_domain import CurrencyCode
from trading212_domain.sources import (
    FxObservation,
    FxSnapshot,
    MarketSession,
    SourceCalendar,
    SourcePeriod,
    source_snapshot_digest,
)
from trading212_persistence.acquisition_authority import grant_digest
from trading212_persistence.acquisition_models import ProviderCapabilityGrantModel
from trading212_persistence.acquisition_records import AcquisitionCapability
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_persistence.source_models import FxObservationModel, SourceRetentionWorkModel
from trading212_persistence.source_service import PostgresSourceService
from trading212_security.principals import AuthorizationError
from trading212_worker.premium_acquisition_runtime import PostgresPremiumAcquisitionRuntime
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.provider_acquisition_case import AcquisitionCase, acquisition_case
from tests.integration.test_provider_publication_postgres import batch
from tests.integration.test_scenario_runs_postgres import grant_scenario_identity
from tests.integration.test_sources_postgres import KEY, NOW, Case, attach_account, source_case
from tests.integration.test_xray_reads_postgres import (
    XrayReadCase,
)
from tests.integration.test_xray_reads_postgres import (
    xray_read_case as xray_read_case,
)

pytestmark = pytest.mark.integration


async def ordinary(case: XrayReadCase) -> tuple[Case, str, FxSnapshot]:
    """Forty real dates in two pairs, ingested through the normal typed boundary."""
    source = await source_case(case.sessions)
    account = attach_account(source)
    grant_scenario_identity(source.sessions, source.principal, NOW)
    await source.service.configure_source_provider(
        source.principal,
        SourceProviderRegistration(
            id=source.series.provider_id,
            key="synthetic-source",
            name="Synthetic source",
            adapter_version="synthetic-v1",
            configuration_state=app.ProviderConfigurationState.CONFIGURED,
            synthetic=True,
            capabilities=(SourceCapability.FX_RATES,),
            supported_price_bases=(),
        ),
        idempotency_key="reference-provider",
        correlation_id="reference-test",
    )
    start = NOW.date() - timedelta(days=39)
    calendar = SourceCalendar(
        id="reference-calendar-" + uuid4().hex,
        version="1",
        timezone="UTC",
        period=SourcePeriod(start=start, end=NOW.date()),
        sessions=tuple(
            MarketSession(
                session_date=start + timedelta(days=i),
                close_at=datetime.combine(start + timedelta(days=i), time(12), UTC),
            )
            for i in range(40)
        ),
    )
    await source.service.register_source_calendar(
        source.principal,
        calendar,
        idempotency_key="reference-calendar",
        correlation_id="reference-test",
    )
    pairs = tuple(
        FxPair(base=CurrencyCode("EUR"), quote=CurrencyCode(currency))
        for currency in ("USD", "GBP")
    )
    observations = tuple(
        FxObservation(
            base=pair.base,
            quote=pair.quote,
            session_date=day.session_date,
            effective_at=day.close_at,
            rate=Decimal("1.123456789123456789"),
            batch_key="reference-fixing",
        )
        for day in calendar.sessions
        for pair in pairs
    )
    request = FxRatesRequest(
        provider_id=source.series.provider_id,
        license_version_id=source.license.id,
        calendar_id=calendar.id,
        calendar_version=calendar.version,
        pairs=pairs,
        period=calendar.period,
        source_cutoff_at=NOW,
    )
    saved = await source.service.ingest_fx_rates(
        source.principal,
        request,
        (
            FxRatePage(
                provenance=replace(
                    source.pages[0].provenance,
                    effective_at=NOW,
                    first_observed_at=NOW,
                    source_revision="reference-v1",
                ),
                period=calendar.period,
                coverage=assess_fx_coverage(
                    calendar,
                    calendar.period,
                    observations,
                    pairs=tuple((x.base, x.quote) for x in pairs),
                ),
                observations=observations,
            ),
        ),
        idempotency_key="references",
        correlation_id="reference-test",
    )
    return source, account, saved


def query(
    account: str, *, cutoff: datetime = NOW, limit: int = 25, effective: datetime | None = None
) -> app.FxObservationReferenceQuery:
    return app.FxObservationReferenceQuery(
        account_id=account,
        base=CurrencyCode("EUR"),
        quote=CurrencyCode("USD"),
        source_cutoff_at=cutoff,
        effective_at_lte=effective,
        limit=limit,
    )


def _rate_reads(
    statements: list[str],
) -> Callable[[object, object, str, object, object, bool], None]:
    def capture(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if "FROM fx_observations" in statement:
            statements.append(statement)

    return capture


@pytest.mark.asyncio
async def test_reference_keyset_exact_rates_restart_pair_and_valuation_bound(
    xray_read_case: XrayReadCase,
) -> None:
    source, account, saved = await ordinary(xray_read_case)
    statements: list[str] = []
    listener = _rate_reads(statements)
    event.listen(xray_read_case.engine, "before_cursor_execute", listener)
    try:
        first = await source.service.list_fx_observation_references(
            source.principal, saved.id, query=query(account)
        )
        assert len(first.items) == 25 and first.next_cursor is not None
        restarted = PostgresSourceService(
            sessions=source.sessions, cursor_signing_key=KEY, clock=lambda: NOW
        )
        last = await restarted.list_fx_observation_references(
            source.principal, saved.id, query=replace(query(account), cursor=first.next_cursor)
        )
        assert len(last.items) == 15 and last.next_cursor is None
        items = first.items + last.items
        assert len({x.observation_id for x in items}) == 40
        assert all(x.rate == Decimal("1.123456789123456789") for x in items)
        assert tuple(x.effective_at for x in items) == tuple(
            sorted((x.effective_at for x in items), reverse=True)
        )
        effective = NOW - timedelta(days=10, microseconds=1)
        bounded = await restarted.list_fx_observation_references(
            source.principal, saved.id, query=query(account, effective=effective)
        )
        assert bounded.effective_at_lte == effective and bounded.first_observed_at == NOW
        assert all(x.effective_at <= effective for x in bounded.items)
        assert bounded.items[0].effective_at == NOW - timedelta(days=11)
        inverse = await restarted.list_fx_observation_references(
            source.principal,
            saved.id,
            query=replace(query(account), base=CurrencyCode("USD"), quote=CurrencyCode("EUR")),
        )
        assert inverse.items == () and inverse.next_cursor is None
    finally:
        event.remove(xray_read_case.engine, "before_cursor_execute", listener)
    # Four direct pages, each one limited rate query; no full membership preload.
    assert len(statements) == 4 and all(
        ".rate" in x and "LIMIT" in x and "OFFSET" not in x for x in statements
    )
    with source.sessions() as session:
        expected = set(
            session.scalars(
                select(FxObservationModel.id).where(
                    FxObservationModel.snapshot_id == UUID(saved.id),
                    FxObservationModel.quote == "USD",
                )
            )
        )
        assert {UUID(x.observation_id) for x in items} == expected
        session.execute(text("ANALYZE fx_observations"))
        # Prove the ordered index path is available and bounded. On this tiny
        # fixture the cost model may prefer sorting40 rows; production latency
        # and default-planner selection belong to the separate load measurement.
        session.execute(text("SET LOCAL enable_seqscan=off"))
        session.execute(text("SET LOCAL enable_sort=off"))
        plan = session.execute(
            text("""EXPLAIN (ANALYZE,FORMAT JSON) SELECT id,effective_at,rate
          FROM fx_observations WHERE owner_id=:owner AND snapshot_id=:snapshot AND base='EUR'
          AND quote='USD' AND effective_at<=:at ORDER BY effective_at DESC,id DESC LIMIT 26"""),
            {"owner": UUID(source.principal.owner_id), "snapshot": UUID(saved.id), "at": NOW},
        ).scalar_one()[0]["Plan"]

        def nodes(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
            yield node
            for child in node.get("Plans", []):
                yield from nodes(child)

        all_nodes = tuple(nodes(plan))
        assert any(x.get("Index Name") == "ix_fx_observation_reference_page" for x in all_nodes), (
            plan
        )
        assert all(
            x.get("Actual Rows", 0) <= 26 and x.get("Rows Removed by Filter", 0) == 0
            for x in all_nodes
        )


@pytest.mark.asyncio
async def test_reference_cursor_pins_account_pair_cutoff_and_effective_bound_before_rates(
    xray_read_case: XrayReadCase,
) -> None:
    source, account, saved = await ordinary(xray_read_case)
    first = await source.service.list_fx_observation_references(
        source.principal, saved.id, query=query(account, limit=1)
    )
    assert first.next_cursor
    other_account = attach_account(source)
    statements: list[str] = []
    listener = _rate_reads(statements)
    event.listen(xray_read_case.engine, "before_cursor_execute", listener)
    try:
        original = replace(query(account, limit=1), cursor=first.next_cursor)
        for changed in (
            replace(original, account_id=other_account),
            replace(original, quote=CurrencyCode("GBP")),
            replace(original, source_cutoff_at=NOW + timedelta(microseconds=1)),
            replace(original, effective_at_lte=NOW - timedelta(microseconds=1)),
            replace(original, limit=2),
            replace(original, cursor=first.next_cursor + "a"),
        ):
            with pytest.raises(CursorValidationError):
                await source.service.list_fx_observation_references(
                    source.principal, saved.id, query=changed
                )
        with pytest.raises(app.SourceServiceError):
            await source.service.list_fx_observation_references(
                source.principal,
                saved.id,
                query=query(account, cutoff=NOW - timedelta(microseconds=1)),
            )
        with pytest.raises(AuthorizationError):
            await source.service.list_fx_observation_references(
                replace(source.principal, owner_id=str(uuid4())), saved.id, query=query(account)
            )
        with source.sessions() as session, session.begin():
            session.execute(
                update(PrincipalScopeGrantModel)
                .where(PrincipalScopeGrantModel.scope == "portfolio:read")
                .values(revoked_at=NOW)
            )
        with pytest.raises(AuthorizationError):
            await source.service.list_fx_observation_references(
                source.principal, saved.id, query=query(account)
            )
    finally:
        event.remove(xray_read_case.engine, "before_cursor_execute", listener)
    assert statements == []


@pytest.mark.asyncio
async def test_reference_final_clock_fence_does_not_return_already_loaded_rates(
    xray_read_case: XrayReadCase,
) -> None:
    source, account, saved = await ordinary(xray_read_case)
    count = 0

    def expire(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        nonlocal count
        if "fx_observations.rate" in statement:
            count += 1
            source.now[0] = source.principal.expires_at

    event.listen(xray_read_case.engine, "after_cursor_execute", expire)
    try:
        with pytest.raises(AuthorizationError):
            await source.service.list_fx_observation_references(
                source.principal, saved.id, query=query(account)
            )
    finally:
        event.remove(xray_read_case.engine, "after_cursor_execute", expire)
    assert count == 1


def next_grant(case: AcquisitionCase, *, version: int, store: bool, display: bool) -> None:
    old = case.grant
    now = datetime.now(UTC)
    grant = ProviderCapabilityGrantModel(
        id=uuid4(),
        owner_id=old.owner_id,
        provider_id=old.provider_id,
        scope_id=old.scope_id,
        version_number=version,
        license_version_id=old.license_version_id,
        effective_at=now,
        expires_at=old.expires_at,
        store_allowed=store,
        display_allowed=display,
        report_allowed=False,
        export_allowed=False,
        daily_allowance=24,
        evidence_key="synthetic-reference-authority",
        content_digest="0" * 64,
        created_at=now,
    )
    grant.content_digest = grant_digest(grant)
    with case.xray.sessions() as session, session.begin():
        session.add(grant)


@pytest.mark.asyncio
@pytest.mark.parametrize("denied", ["store", "display"])
async def test_reference_actual_acquisition_revocation_and_permanent_marker_before_rates(
    xray_read_case: XrayReadCase, denied: str
) -> None:
    case = acquisition_case(xray_read_case, capability=AcquisitionCapability.REFERENCE_FX)
    runtime = PostgresPremiumAcquisitionRuntime(
        sessions=case.xray.sessions,
        principal=case.xray.principal,
        cursor_signing_key=XRAY_CURSOR_KEY,
        enabled=True,
    )
    acquired = await batch(case, runtime)
    saved = await runtime.publish(acquired)
    assert isinstance(saved, FxSnapshot)
    service = PostgresSourceService(sessions=case.xray.sessions, cursor_signing_key=XRAY_CURSOR_KEY)
    selected = query(XRAY_ACCOUNT_ID, cutoff=datetime.now(UTC))
    allowed = await service.list_fx_observation_references(
        case.xray.principal, saved.id, query=selected
    )
    assert allowed.items[0].rate == Decimal("1.123456789123456789")
    next_grant(case, version=2, store=denied != "store", display=denied != "display")
    statements: list[str] = []
    listener = _rate_reads(statements)
    event.listen(case.xray.engine, "before_cursor_execute", listener)
    try:
        with pytest.raises(app.SourceServiceError):
            await service.list_fx_observation_references(
                case.xray.principal, saved.id, query=selected
            )
        now = datetime.now(UTC)
        with case.xray.sessions() as session, session.begin():
            session.add(
                SourceRetentionWorkModel(
                    id=uuid4(),
                    owner_id=case.selection.owner_id,
                    fx_snapshot_id=UUID(saved.id),
                    started_at=now,
                    created_at=now,
                    content_digest=source_snapshot_digest(saved),
                    phase="copies",
                    removed_observation_count=0,
                )
            )
        next_grant(case, version=3, store=True, display=True)
        with pytest.raises(app.SourceServiceError):
            await service.list_fx_observation_references(
                case.xray.principal, saved.id, query=selected
            )
    finally:
        event.remove(case.xray.engine, "before_cursor_execute", listener)
    assert statements == []
