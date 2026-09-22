"""Supported canonical publication through real attempt/grant storage; no HTTP calls."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError
from trading212_application.research import ResearchServiceError
from trading212_application.sources import SourceServiceError
from trading212_domain import CurrencyCode
from trading212_domain.reports import ReportSourceUse
from trading212_domain.research import ResearchEventKind
from trading212_domain.research_sources import ResearchNewsFacts
from trading212_domain.sources import FxSnapshot, PriceSnapshot, SourceUse
from trading212_persistence.acquisition_authority import acquisition_auth, grant_digest
from trading212_persistence.acquisition_models import ProviderCapabilityGrantModel as Grant
from trading212_persistence.acquisition_records import (
    AcquisitionCapability,
    AcquisitionStorageDenied,
)
from trading212_persistence.acquisition_research_authority import _as_scope
from trading212_persistence.projection_definition_store import ProjectionStorageError
from trading212_persistence.projection_source_store import ProjectionSourceStore
from trading212_persistence.report_sources import _physical_permit
from trading212_persistence.research_models import (
    ResearchSourceOriginModel,
    ResearchSourceVersionModel,
)
from trading212_persistence.research_permissions import ResearchCapabilityRequest
from trading212_persistence.source_models import FxSnapshotModel, PriceSnapshotModel
from trading212_persistence.source_store import SourceStore
from trading212_reference_data.premium_acquisition import acquisition_request_digest
from trading212_reference_data.premium_acquisition_types import (
    AcquireDailyAdjusted,
    AcquireEcbReferenceFx,
    AcquireNewsSentiment,
    AcquisitionCommand,
)
from trading212_reference_data.premium_facts import (
    AcquiredSourceBatch,
    AcquisitionProvenance,
    DailyAdjustedFacts,
    DailyAdjustedRow,
    EcbReferenceFacts,
    EcbReferenceRow,
    NewsItemFact,
    NewsSentimentFacts,
    PremiumFacts,
    premium_facts_digest,
)
from trading212_security.principals import AuthorizationError
from trading212_worker.premium_acquisition_runtime import PostgresPremiumAcquisitionRuntime
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.provider_acquisition_case import AcquisitionCase, acquisition_case
from tests.integration.test_xray_reads_postgres import (
    XrayReadCase,
)
from tests.integration.test_xray_reads_postgres import (
    xray_read_case as xray_read_case,
)

pytestmark = pytest.mark.integration


async def batch(
    case: AcquisitionCase, runtime: PostgresPremiumAcquisitionRuntime
) -> AcquiredSourceBatch:
    s = case.selection
    now = datetime.now(UTC)
    command: AcquisitionCommand
    facts: PremiumFacts
    if s.capability is AcquisitionCapability.DAILY_ADJUSTED:
        command = AcquireDailyAdjusted(
            owner_id=s.owner_id,
            account_id=s.account_id,
            request_id=s.request_id,
            mapping_version_id=s.mapping_version_id,
            period=case.calendar.period,
        )
    elif s.capability is AcquisitionCapability.REFERENCE_FX:
        command = AcquireEcbReferenceFx(
            owner_id=s.owner_id,
            account_id=s.account_id,
            request_id=s.request_id,
            mapping_version_id=s.mapping_version_id,
        )
    else:
        end = now.replace(second=0, microsecond=0)
        command = AcquireNewsSentiment(
            owner_id=s.owner_id,
            account_id=s.account_id,
            request_id=s.request_id,
            mapping_version_id=s.mapping_version_id,
            time_from=end - timedelta(days=1),
            time_to=end,
            limit=100,
        )
    permit = await runtime.resolve(command, now=now)
    assert permit is not None
    digest = acquisition_request_digest(command, permit)
    attempt = await runtime.reserve(command, permit, request_digest=digest, now=now)
    assert attempt is not None
    observed = datetime.now(UTC)
    day = case.calendar.period.start
    amount = Decimal("123.456789123456789123")
    if s.capability is AcquisitionCapability.DAILY_ADJUSTED:
        facts = DailyAdjustedFacts(
            symbol="ALPHA",
            price_currency=CurrencyCode("EUR"),
            period=case.calendar.period,
            provider_rows_validated=1,
            rows=(
                DailyAdjustedRow(
                    session_date=day,
                    open=amount,
                    high=amount,
                    low=amount,
                    close=amount,
                    adjusted_close=Decimal("120"),
                    volume=100,
                    dividend=Decimal("0"),
                    split_coefficient=Decimal("1"),
                ),
            ),
        )
    elif s.capability is AcquisitionCapability.REFERENCE_FX:
        facts = EcbReferenceFacts(
            first_date=day,
            last_date=day,
            date_count=1,
            rows=(
                EcbReferenceRow(
                    session_date=day,
                    quote=CurrencyCode("USD"),
                    rate=Decimal("1.123456789123456789"),
                    source_key=f"ecb:{day}:EUR:USD",
                ),
            ),
        )
    else:
        assert isinstance(command, AcquireNewsSentiment)
        facts = NewsSentimentFacts(
            symbol="ALPHA",
            time_from=command.time_from,
            time_to=command.time_to,
            requested_limit=100,
            items=(
                NewsItemFact(
                    source_key="synthetic-publisher-item",
                    facts=ResearchNewsFacts(
                        publisher="Synthetic publisher",
                        title="Exact original source clocks",
                        summary="Inert source prose <script>never execute</script>",
                        published_at=observed - timedelta(hours=1),
                    ),
                ),
            ),
            limit_reached=False,
        )
    assert await runtime.finish(attempt, outcome=None, observed_at=datetime.now(UTC), retry_at=None)
    provenance = AcquisitionProvenance(
        owner_id=s.owner_id,
        account_id=s.account_id,
        provider_id=permit.provider_id,
        instrument_id=permit.instrument_id,
        entity_id=permit.entity_id,
        canonical_market_mapping_id=permit.canonical_market_mapping_id,
        capability=permit.capability,
        mapping_version_id=permit.mapping_version_id,
        mapping_digest=permit.mapping_digest,
        policy_version_id=permit.policy_version_id,
        policy_digest=permit.policy_digest,
        grant_id=permit.grant_id,
        grant_digest=permit.grant_digest,
        license=permit.license,
        request_id=command.request_id,
        request_digest=digest,
        attempt_id=attempt.id,
        adapter_version="premium_fixed_get_v1",
        observed_at=observed,
        first_known_at=observed,
        expires_at=min(permit.expires_at, observed + timedelta(days=1)),
        content_digest=premium_facts_digest(facts),
    )
    return AcquiredSourceBatch(command=command, provenance=provenance, facts=facts)


def revoke(case: AcquisitionCase) -> None:
    now = datetime.now(UTC)
    old = case.grant
    row = Grant(
        id=uuid4(),
        owner_id=old.owner_id,
        provider_id=old.provider_id,
        scope_id=old.scope_id,
        version_number=2,
        license_version_id=old.license_version_id,
        effective_at=now,
        expires_at=now + timedelta(days=1),
        store_allowed=False,
        display_allowed=False,
        report_allowed=False,
        export_allowed=False,
        daily_allowance=0,
        evidence_key="synthetic-revoked",
        content_digest="0" * 64,
        created_at=now,
    )
    row.content_digest = grant_digest(row)
    with case.xray.sessions() as session, session.begin():
        session.add(row)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "capability",
    [
        AcquisitionCapability.DAILY_ADJUSTED,
        AcquisitionCapability.REFERENCE_FX,
        AcquisitionCapability.NEWS_SENTIMENT,
    ],
)
async def test_original_clocks_exact_amounts_and_current_grant_revocation(
    xray_read_case: XrayReadCase, capability: AcquisitionCapability
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
    if isinstance(saved, (PriceSnapshot, FxSnapshot)):
        kind = "price" if isinstance(saved, PriceSnapshot) else "fx"
        assert saved.provenance.first_observed_at == acquired.provenance.observed_at
        if isinstance(saved, PriceSnapshot):
            assert saved.observations[0].value == Decimal("123.456789123456789123")
        else:
            assert saved.observations[0].rate == Decimal("1.123456789123456789")
        identifier = UUID(saved.id)
        model = PriceSnapshotModel if kind == "price" else FxSnapshotModel
        with case.xray.sessions() as session:
            row = session.get(model, identifier)
            assert row is not None and row.first_observed_at == acquired.provenance.first_known_at
            assert (
                row.expires_at == acquired.provenance.expires_at
                and row.created_at >= row.first_observed_at
            )
    else:
        assert len(saved) == 1
        source = saved[0].citations[0].source
        assert (
            source.observed_at
            == source.first_known_at
            == source.retained_at
            == acquired.provenance.observed_at
        )
        assert source.expires_at == acquired.provenance.expires_at
        identifier = source.version_id
        kind = "research"
    with case.xray.sessions() as session:
        assert (
            session.scalar(
                text("SELECT acquisition_source_restricted(:owner,:kind,:source,:at,'store')"),
                {
                    "owner": case.selection.owner_id,
                    "kind": kind,
                    "source": identifier,
                    "at": datetime.now(UTC),
                },
            )
            is False
        )
    assert await runtime.publish(acquired) == saved
    revoke(case)
    with case.xray.sessions() as session:
        assert (
            session.scalar(
                text("SELECT acquisition_source_restricted(:owner,:kind,:source,:at,'store')"),
                {
                    "owner": case.selection.owner_id,
                    "kind": kind,
                    "source": identifier,
                    "at": datetime.now(UTC),
                },
            )
            is True
        )
    with pytest.raises(AcquisitionStorageDenied):
        await runtime.publish(acquired)


@pytest.mark.asyncio
async def test_mutated_fact_or_request_digest_never_publishes(xray_read_case: XrayReadCase) -> None:
    case = acquisition_case(xray_read_case)
    runtime = PostgresPremiumAcquisitionRuntime(
        sessions=case.xray.sessions,
        principal=case.xray.principal,
        cursor_signing_key=XRAY_CURSOR_KEY,
        enabled=True,
    )
    acquired = await batch(case, runtime)
    with pytest.raises(AcquisitionStorageDenied):
        await runtime.publish(
            replace(acquired, provenance=replace(acquired.provenance, request_digest="f" * 64))
        )
    assert isinstance(acquired.facts, DailyAdjustedFacts)
    wrong = replace(acquired.facts, rows=(replace(acquired.facts.rows[0], close=Decimal("999")),))
    with pytest.raises(AcquisitionStorageDenied):
        await runtime.publish(replace(acquired, facts=wrong))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "capability", [AcquisitionCapability.DAILY_ADJUSTED, AcquisitionCapability.REFERENCE_FX]
)
async def test_retained_source_report_projection_recheck_same_grant(
    xray_read_case: XrayReadCase, capability: AcquisitionCapability
) -> None:
    case = acquisition_case(xray_read_case, capability=capability)
    runtime = PostgresPremiumAcquisitionRuntime(
        sessions=case.xray.sessions,
        principal=case.xray.principal,
        cursor_signing_key=XRAY_CURSOR_KEY,
        enabled=True,
    )
    saved = await runtime.publish(await batch(case, runtime))
    assert isinstance(saved, (PriceSnapshot, FxSnapshot))
    kind = "price" if isinstance(saved, PriceSnapshot) else "fx"
    model = PriceSnapshotModel if kind == "price" else FxSnapshotModel
    identifier = UUID(saved.id)
    sources = SourceStore(sessions=case.xray.sessions, cursor_signing_key=XRAY_CURSOR_KEY)
    projections = ProjectionSourceStore(case.xray.sessions, cursor_signing_key=XRAY_CURSOR_KEY)
    with case.xray.sessions() as session, session.begin():
        auth = acquisition_auth(session, case.xray.principal, case.selection, now=datetime.now(UTC))
        row = session.get(model, identifier)
        assert row is not None
        sources._snapshot_permit(session, row, SourceUse.DISPLAY)
        _physical_permit(
            session, row, kind, source_use=ReportSourceUse.REPORT, now=datetime.now(UTC)
        )
        before = projections._physical(session, auth, model, identifier)
        assert (
            "adapter_version" not in before[0]
        )  # Old normalized source proof stays byte-compatible.
    revoke(case)
    with case.xray.sessions() as session, session.begin():
        auth = acquisition_auth(session, case.xray.principal, case.selection, now=datetime.now(UTC))
        row = session.get(model, identifier)
        assert row is not None
        with pytest.raises(SourceServiceError):
            sources._snapshot_permit(session, row, SourceUse.DISPLAY)
        with pytest.raises(AuthorizationError):
            _physical_permit(
                session, row, kind, source_use=ReportSourceUse.REPORT, now=datetime.now(UTC)
            )
        with pytest.raises(ProjectionStorageError):
            projections._physical(session, auth, model, identifier)


@pytest.mark.asyncio
async def test_real_research_authority_one_statement_exact_members_and_revocation(
    xray_read_case: XrayReadCase,
) -> None:
    case = acquisition_case(xray_read_case, capability=AcquisitionCapability.NEWS_SENTIMENT)
    runtime = PostgresPremiumAcquisitionRuntime(
        sessions=case.xray.sessions,
        principal=case.xray.principal,
        cursor_signing_key=XRAY_CURSOR_KEY,
        enabled=True,
    )
    saved = await runtime.publish(await batch(case, runtime))
    assert isinstance(saved, tuple) and len(saved) == 1
    source_id = saved[0].citations[0].source.version_id
    authority = runtime.research_authority
    with case.xray.sessions() as session:
        header = session.get(ResearchSourceVersionModel, source_id)
        assert header is not None
        origin = session.get(ResearchSourceOriginModel, header.origin_id)
        assert origin is not None
        request = ResearchCapabilityRequest(
            source_version_id=header.id,
            owner_id=header.owner_id,
            provider_id=header.provider_id,
            entity_id=header.entity_id,
            capability=ResearchEventKind(header.capability),
            license_version_id=header.license_version_id,
            grant_id=header.capability_grant_id,
            grant_digest=header.capability_grant_digest,
            retained_at=header.retained_at,
            original_retained_at=origin.original_retained_at,
            effective_expires_at=header.effective_expires_at,
        )
        statements = []

        def record(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _many: bool,
        ) -> None:
            statements.append(statement)

        connection = session.connection()
        event.listen(connection, "before_cursor_execute", record)
        try:
            grants = authority.authorize_research_capabilities(
                session, requests=(request,), now=datetime.now(UTC)
            )
        finally:
            event.remove(connection, "before_cursor_execute", record)
        assert len(statements) == 1 and grants[0].grant_id == case.grant.id
        assert all("research_source_payloads" not in statement for statement in statements)
        with pytest.raises(ResearchServiceError):
            authority.authorize_research_capabilities(
                session, requests=(replace(request, entity_id=uuid4()),), now=datetime.now(UTC)
            )
        with pytest.raises(ResearchServiceError):
            authority.authorize_research_capabilities(
                session, requests=(replace(request, grant_digest="f" * 64),), now=datetime.now(UTC)
            )
        eligible = (
            select(ResearchSourceVersionModel.id)
            .join(
                ResearchSourceOriginModel,
                ResearchSourceOriginModel.id == ResearchSourceVersionModel.origin_id,
            )
            .where(
                ResearchSourceVersionModel.id == source_id,
                authority.research_source_eligibility(
                    _as_scope(ResearchSourceVersionModel, ResearchSourceOriginModel),
                    now=datetime.now(UTC),
                ),
            )
        )
        assert session.scalar(eligible) == source_id
    revoke(case)
    with case.xray.sessions() as session:
        with pytest.raises(ResearchServiceError):
            authority.authorize_research_capabilities(
                session, requests=(request,), now=datetime.now(UTC)
            )
        assert (
            session.scalar(
                select(ResearchSourceVersionModel.id)
                .join(
                    ResearchSourceOriginModel,
                    ResearchSourceOriginModel.id == ResearchSourceVersionModel.origin_id,
                )
                .where(
                    ResearchSourceVersionModel.id == source_id,
                    authority.research_source_eligibility(
                        _as_scope(ResearchSourceVersionModel, ResearchSourceOriginModel),
                        now=datetime.now(UTC),
                    ),
                )
            )
            is None
        )


@pytest.mark.asyncio
async def test_batched_research_xray_parent_expression_rechecks_real_acquired_fx(
    xray_read_case: XrayReadCase,
) -> None:
    from trading212_persistence.research_xray_read import _parents_sql

    case = acquisition_case(xray_read_case, capability=AcquisitionCapability.REFERENCE_FX)
    runtime = PostgresPremiumAcquisitionRuntime(
        sessions=case.xray.sessions,
        principal=case.xray.principal,
        cursor_signing_key=XRAY_CURSOR_KEY,
        enabled=True,
    )
    saved = await runtime.publish(await batch(case, runtime))
    assert isinstance(saved, FxSnapshot)
    # Real retained source metadata, with a closed synthetic dependency header.
    # The same expression runs inside both whole X-ray metadata checks.
    statement = text(
        """WITH deps AS (SELECT cast(:dependency AS uuid) id,
      cast(:source AS uuid) fx_snapshot_id, NULL::uuid entity_evidence_version_id,
      NULL::uuid classification_snapshot_id, NULL::uuid fund_definition_id,
      NULL::uuid fund_mapping_id, NULL::uuid constituent_snapshot_id,
      NULL::uuid valuation_run_id, NULL::uuid reconciliation_run_id,
      NULL::uuid broker_source_record_id, NULL::uuid threshold_policy_id)
    """
        + _parents_sql()
    )
    params = {
        "dependency": uuid4(),
        "owner": case.selection.owner_id,
        "account": case.selection.account_id,
        "source": UUID(saved.id),
        "now": datetime.now(UTC),
    }
    with case.xray.sessions() as session:
        rows = session.execute(statement, params).mappings().all()
        assert (
            len(rows) == 1
            and rows[0]["target"] == "fx_snapshot_id"
            and rows[0]["marker_clear"] is True
        )
    revoke(case)
    with case.xray.sessions() as session:
        rows = session.execute(statement, {**params, "now": datetime.now(UTC)}).mappings().all()
        assert len(rows) == 1 and rows[0]["marker_clear"] is False


@pytest.mark.asyncio
async def test_canonical_source_cannot_commit_without_successful_publication_receipt(
    xray_read_case: XrayReadCase,
) -> None:
    from trading212_persistence.acquisition_records import AcquisitionPublicationClock
    from trading212_reference_data.premium_projection import build_price_history_pages

    case = acquisition_case(xray_read_case)
    runtime = PostgresPremiumAcquisitionRuntime(
        sessions=case.xray.sessions,
        principal=case.xray.principal,
        cursor_signing_key=XRAY_CURSOR_KEY,
        enabled=True,
    )
    acquired = await batch(case, runtime)
    basis = await runtime._store.resolve(case.selection)
    assert basis is not None
    metadata = await runtime._store.market_metadata(case.selection, basis)
    assert metadata.series is not None
    request, pages = build_price_history_pages(acquired, metadata.series, metadata.calendar)
    clock = AcquisitionPublicationClock(
        acquired_at=acquired.provenance.observed_at,
        first_known_at=acquired.provenance.first_known_at,
        expires_at=acquired.provenance.expires_at,
        content_digest=acquired.provenance.content_digest,
    )
    with (
        pytest.raises(IntegrityError, match="Canonical acquisition publication"),
        case.xray.sessions() as session,
        session.begin(),
    ):
        snapshot = runtime._store._sources._assemble(
            session, case.selection.owner_id, request, pages, original_clock=clock
        )
        runtime._store._sources._persist_snapshot(session, snapshot, original_clock=clock)
    with case.xray.sessions() as session:
        assert (
            session.scalar(
                select(PriceSnapshotModel.id).where(
                    PriceSnapshotModel.owner_id == case.selection.owner_id,
                    PriceSnapshotModel.provider_id == basis.provider_id,
                )
            )
            is None
        )


@pytest.mark.asyncio
async def test_real_entitlement_authority_preserves_whole_summary_twelve_statement_budget(
    xray_read_case: XrayReadCase,
) -> None:
    from trading212_application.research import ResearchSummaryQuery

    from tests.integration.test_xray_reads_postgres import company

    case = acquisition_case(xray_read_case, capability=AcquisitionCapability.NEWS_SENTIMENT)
    case.xray.now[0] = datetime.now(UTC)
    xray = await company(case.xray)
    runtime = PostgresPremiumAcquisitionRuntime(
        sessions=case.xray.sessions,
        principal=case.xray.principal,
        cursor_signing_key=XRAY_CURSOR_KEY,
        enabled=True,
    )
    published = await runtime.publish(await batch(case, runtime))
    assert isinstance(published, tuple) and len(published) == 1
    service = runtime._store._research
    query = ResearchSummaryQuery(
        account_id=case.selection.account_id,
        xray_run_id=UUID(xray.context.run_id),
        source_cutoff_at=datetime.now(UTC),
        limit=25,
    )
    statements = []

    def record(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _many: bool,
    ) -> None:
        statements.append(statement)

    event.listen(case.xray.engine, "before_cursor_execute", record)
    try:
        summary = await service.get_research_summary(case.xray.principal, query)
    finally:
        event.remove(case.xray.engine, "before_cursor_execute", record)
    assert len(statements) <= 12
    assert summary.total == 1 and len(summary.items) == 1
    assert summary.items[0].source.event_id == published[0].event_id
    revoke(case)
    statements.clear()
    event.listen(case.xray.engine, "before_cursor_execute", record)
    try:
        denied = await service.get_research_summary(case.xray.principal, query)
    finally:
        event.remove(case.xray.engine, "before_cursor_execute", record)
    assert len(statements) <= 12 and denied.total == 0 and not denied.items
