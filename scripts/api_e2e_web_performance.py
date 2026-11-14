"""Declared 100-holding/1000-event workload through normal canonical publication."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from threading import Event, Lock, Thread
from time import perf_counter
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from starlette.responses import JSONResponse
from trading212_application import research as research_app
from trading212_application import source_providers as ports
from trading212_application import xray as xray_app
from trading212_application.ingestion import (
    Checkpoint,
    IngestionCapability,
    IngestionCoordinator,
    RunMode,
    RunStatus,
    SourcePage,
)
from trading212_application.source_ingestion import SourceProviderRegistration
from trading212_application.sources import ProviderConfigurationState
from trading212_application.xray_ingestion import (
    EconomicEntityRegistration,
    EntityEvidenceRegistration,
    EntityMappingRegistration,
    XrayPolicyRegistration,
    XrayTaxonomyRegistration,
)
from trading212_domain import CurrencyCode, build_synthetic_identity
from trading212_domain.entities import Instrument
from trading212_domain.identifiers import BrokerAccountId, InstrumentId, ListingId
from trading212_domain.research import ResearchEventKind
from trading212_domain.research_serialization import research_record_digest
from trading212_domain.research_sources import (
    ResearchCitation,
    ResearchEventRevision,
    ResearchNewsFacts,
    ResearchSourceVersion,
)
from trading212_domain.serialization import canonical_json
from trading212_domain.source_details import ClassificationDimension, ClassificationObservation
from trading212_domain.sources import LicensePermission, SourceLicense
from trading212_domain.values import Instant
from trading212_domain.xray import XrayDimension
from trading212_persistence import create_database_engine, create_session_factory
from trading212_persistence.acquisition_authority import grant_digest
from trading212_persistence.acquisition_models import (
    ProviderCapabilityGrantModel,
    ProviderCapabilityScopeModel,
)
from trading212_persistence.acquisition_research_authority import (
    PostgresResearchCapabilityAuthority,
)
from trading212_persistence.mappers import account_to_model, instrument_to_model, listing_to_model
from trading212_persistence.models import (
    ListingModel,
    PortfolioSnapshotModel,
    SnapshotPositionModel,
)
from trading212_persistence.premium_models import PremiumCapacityModel
from trading212_persistence.report_authorization import authorize_report_request
from trading212_persistence.research_models import (
    ResearchEventRevisionModel,
    ResearchSourceVersionModel,
    ResearchWitnessModel,
)
from trading212_persistence.research_service import PostgresResearchService
from trading212_persistence.source_models import (
    MarketDataProviderModel,
    ProviderLicenseVersionModel,
)
from trading212_persistence.source_service import PostgresSourceService
from trading212_persistence.source_store import license_view
from trading212_persistence.xray_service import PostgresXrayService
from trading212_reference_data.xray_replay import XrayReplayProvider
from trading212_security.principals import Principal, Scope
from trading212_worker.materializer import PostgresCanonicalMaterializer
from trading212_worker.postgres_store import PostgresIngestionStore
from trading212_worker.source_seed import collect_source_pages
from trading212_worker.synthetic_grants import seed_synthetic_grants
from trading212_worker.xray_fixture import (
    XrayFixture,
    XrayFixtureListing,
    build_xray_fixture,
    synthetic_xray_policy,
)
from trading212_worker.xray_provider import SyntheticXrayBrokerProvider
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from scripts.api_e2e_research_reports import _require_disposable

_NAMESPACE = uuid5(NAMESPACE_URL, "t212pi/phase3/web-performance/100-holdings-1000-events/v1")


class WebPerformancePreparation:
    """One owned setup thread; readiness is published only after its complete return."""

    def __init__(
        self,
        prepare: Callable[[Event], dict[str, object]],
        *,
        cleanup_ready: Event,
    ) -> None:
        self._prepare = prepare
        self._cleanup_ready = cleanup_ready
        self._stop = Event()
        self._lock = Lock()
        self._metadata: dict[str, object] | None = None
        self._error_type: str | None = None
        self._started = False
        self._thread = Thread(target=self._run, name="web-performance-preparation", daemon=False)

    def start(self) -> None:
        if self._started:
            raise RuntimeError("Performance preparation can start only once.")
        self._cleanup_ready.clear()
        try:
            self._thread.start()
        except BaseException:
            self._cleanup_ready.set()
            raise
        self._started = True

    def _run(self) -> None:
        try:
            metadata = self._prepare(self._stop)
        except BaseException as error:
            with self._lock:
                # Exception text may contain DSNs/private SQL values; never retain it.
                self._error_type = type(error).__name__[:64]
        else:
            with self._lock:
                self._metadata = dict(metadata)

    def response(self) -> JSONResponse:
        with self._lock:
            if self._error_type is not None:
                return JSONResponse(
                    {"state": "failed", "error_type": self._error_type},
                    status_code=500,
                    headers={"Cache-Control": "no-store"},
                )
            if self._metadata is not None:
                return JSONResponse(self._metadata, headers={"Cache-Control": "no-store"})
        return JSONResponse(
            {"state": "preparing"},
            status_code=503,
            headers={"Cache-Control": "no-store", "Retry-After": "1"},
        )

    def stop_and_join(self, *, timeout: float = 7) -> bool:
        if not 0 < timeout <= 7:
            raise ValueError("Preparation join must use its bounded shutdown allowance.")
        self._stop.set()
        if self._started:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                return False
        self._cleanup_ready.set()
        return True


def build_web_performance_preparation(
    database_url: str, *, cleanup_ready: Event
) -> WebPerformancePreparation:
    """The preparation thread creates and disposes every connection it owns."""

    def prepare(stop: Event) -> dict[str, object]:
        parsed = make_url(database_url)
        if parsed.database is None or not parsed.database.startswith("t212pi_web_e2e_"):
            raise RuntimeError("Performance preparation requires its generated disposable DB.")
        engine = create_database_engine(
            parsed.update_query_dict(
                {
                    "connect_timeout": "2",
                    "options": "-c statement_timeout=5000 -c lock_timeout=2000",
                }
            )
        )
        try:
            return asyncio.run(
                seed_web_performance_scenario(create_session_factory(engine), stop=stop)
            )
        finally:
            engine.dispose()

    return WebPerformancePreparation(prepare, cleanup_ready=cleanup_ready)


def _check_stop(stop: Event | None) -> None:
    if stop is not None and stop.is_set():
        raise InterruptedError("Performance preparation was stopped before completion.")


def identifier(name: str) -> UUID:
    return uuid5(_NAMESPACE, name)


def _setup_progress(phase: str, started: float, *, completed: int = 0) -> None:
    """Bounded fixture diagnostics contain no private records or identifiers."""
    fields = {
        "phase": phase,
        "completed": completed,
        "elapsed_seconds": perf_counter() - started,
    }
    try:
        sys.stderr.write("e2e.performance.setup " + json.dumps(fields) + "\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        # Losing diagnostics must not change canonical publication or setup outcomes.
        pass


class PerformanceBrokerProvider(SyntheticXrayBrokerProvider):
    """Fixed exact EUR economics; actual observation clocks enter normal source records."""

    def __init__(self, at: datetime) -> None:
        super().__init__()
        template = build_xray_fixture()
        account = replace(
            template.account,
            id=BrokerAccountId(identifier("account")),
            provider_account_id="synthetic-web-performance-v1",
            display_name="Performance 100 holdings",
            first_seen_at=Instant(at),
            last_seen_at=Instant(at),
        )
        rows = []
        for index in range(100):
            instrument = Instrument(
                InstrumentId(identifier(f"instrument/{index}")),
                f"Performance company {index:03d}",
                "equity",
                f"XS{index + 1000:010d}",
            )
            listing = replace(
                template.listings[0].listing,
                id=ListingId(identifier(f"listing/{index}")),
                instrument_id=instrument.id,
                provider_instrument_id=f"PERF{index:03d}",
                ticker=f"PERF{index:03d}",
            )
            rows.append(
                XrayFixtureListing(
                    key=f"performance-{index}",
                    instrument=instrument,
                    listing=listing,
                    held_value=Decimal("10"),
                )
            )
        self.fixture = XrayFixture(account=account, listings=tuple(rows))
        self.financial_at = at

    async def read_page(
        self,
        *,
        owner_id: str,
        account_id: str,
        capability: IngestionCapability,
        checkpoint: Checkpoint | None,
        correlation_id: str,
    ) -> SourcePage:
        page = await super().read_page(
            owner_id=owner_id,
            account_id=account_id,
            capability=capability,
            checkpoint=checkpoint,
            correlation_id=correlation_id,
        )
        return replace(
            page,
            records=tuple(
                replace(record, source_timestamp=self.financial_at, observed_at=datetime.now(UTC))
                for record in page.records
            ),
        )


async def seed_web_performance_scenario(
    sessions: sessionmaker[Session], *, stop: Event | None = None
) -> dict[str, object]:
    """Setup is outside measurement; no counters, result payloads or clocks are rewritten."""
    started = perf_counter()
    _check_stop(stop)
    _setup_progress("started", started)
    with sessions() as session:
        _require_disposable(session)
    identity, at = build_synthetic_identity(), datetime.now(UTC)
    provider = PerformanceBrokerProvider(at)
    account = provider.fixture.account.id
    scopes = research_app.RESEARCH_WRITE_SCOPES | {Scope.TARGETS_WRITE}
    seed_synthetic_grants(sessions, app_environment="test", at=at, scopes=scopes)
    principal = Principal(
        str(identity.principal.id),
        str(identity.owner.id),
        "local.synthetic",
        "synthetic-owner",
        scopes,
        at - timedelta(seconds=1),
        at + timedelta(hours=2),
    )
    with sessions() as session, session.begin():
        _require_disposable(session)
        session.add(account_to_model(provider.fixture.account))
        for row in provider.fixture.listings:
            session.add(instrument_to_model(row.instrument, observed_at=Instant(at)))
            session.add(listing_to_model(row.listing))
    _setup_progress("broker_catalog_committed", started, completed=100)
    _check_stop(stop)
    ingestion = await IngestionCoordinator(
        provider=provider,
        store=PostgresIngestionStore(
            sessions, provider="synthetic", materializer=PostgresCanonicalMaterializer()
        ),
        clock=lambda: datetime.now(UTC),
    ).refresh(
        owner_id=str(identity.owner.id),
        account_id=str(account),
        mode=RunMode.FULL,
        idempotency_key="web-performance-broker-v1",
        correlation_id="web-performance-fixture",
    )
    if ingestion.status is not RunStatus.SUCCEEDED:
        raise RuntimeError("The real 100-position performance ingestion did not succeed.")
    _setup_progress("broker_ingestion_completed", started, completed=100)
    _check_stop(stop)
    source_service = PostgresSourceService(sessions=sessions, cursor_signing_key=XRAY_CURSOR_KEY)
    catalog_id, license_id = str(identifier("catalog/provider")), str(identifier("catalog/license"))
    await source_service.configure_source_provider(
        principal,
        SourceProviderRegistration(
            id=catalog_id,
            key="synthetic-web-performance-catalog",
            name="Synthetic performance entity evidence",
            adapter_version="synthetic-xray-replay-v1",
            configuration_state=ProviderConfigurationState.CONFIGURED,
            synthetic=True,
            capabilities=(ports.SourceCapability.CLASSIFICATIONS,),
            freshness_policy_version="web-performance-freshness-v1",
            max_age_seconds=7 * 86400,
        ),
        idempotency_key="web-performance-catalog",
        correlation_id="web-performance-fixture",
    )
    license = SourceLicense(
        id=license_id,
        provider_id=catalog_id,
        version="web-performance-1",
        effective_at=at - timedelta(days=1),
        store=LicensePermission.ALLOWED,
        display=LicensePermission.ALLOWED,
        report=LicensePermission.ALLOWED,
        export=LicensePermission.DENIED,
        retention_days=30,
        attribution="Synthetic performance workload only.",
        evidence_key="synthetic-performance-v1",
    )
    await source_service.register_source_license(
        principal,
        license,
        idempotency_key="web-performance-license",
        correlation_id="web-performance-fixture",
    )
    _setup_progress("source_license_registered", started)
    _check_stop(stop)
    xray = PostgresXrayService(sessions=sessions, cursor_signing_key=XRAY_CURSOR_KEY)
    original_policy = synthetic_xray_policy()
    policy = replace(
        original_policy,
        id=identifier("policy"),
        provider_selection_policy=replace(
            original_policy.provider_selection_policy,
            id=identifier("provider-policy"),
            provider_order=(catalog_id,),
        ),
    )
    await xray.register_xray_policy(
        principal,
        str(account),
        XrayPolicyRegistration(
            key="web-performance-v1",
            effective_at=at - timedelta(days=1),
            policy=policy,
            taxonomies=tuple(
                XrayTaxonomyRegistration(
                    id=str(taxonomy.taxonomy_id),
                    dimension=taxonomy.dimension,
                    key=taxonomy.key,
                    version=taxonomy.version,
                )
                for taxonomy in policy.taxonomy_versions
            ),
        ),
        idempotency_key="web-performance-policy",
        correlation_id="web-performance-fixture",
    )
    await xray.register_entity_evidence(
        principal,
        EntityEvidenceRegistration(
            id=str(identifier("entity-evidence")),
            key="web-performance-entities",
            provider_id=catalog_id,
            license_version_id=license_id,
            revision=1,
            effective_at=at - timedelta(days=1),
            valid_until=None,
            entities=tuple(
                EconomicEntityRegistration(
                    id=str(identifier(f"entity/{index}")),
                    key=f"performance-company-{index:03d}",
                    display_name=f"Performance company {index:03d}",
                )
                for index in range(100)
            ),
            mappings=tuple(
                EntityMappingRegistration(
                    id=str(identifier(f"mapping/{index}")),
                    instrument_id=str(row.instrument.id),
                    entity_id=str(identifier(f"entity/{index}")),
                    listing_id=str(row.listing.id),
                    effective_at=at - timedelta(days=1),
                    valid_until=None,
                    confidence=Decimal("1"),
                )
                for index, row in enumerate(provider.fixture.listings)
            ),
            share_classes=(),
            relationships=(),
        ),
        idempotency_key="web-performance-entity-evidence",
        correlation_id="web-performance-fixture",
    )
    _setup_progress("entity_evidence_registered", started, completed=100)
    known = datetime.now(UTC)
    classifications = tuple(
        ClassificationObservation(
            instrument_id=str(row.instrument.id),
            dimension=ClassificationDimension.ECONOMIC_CURRENCY
            if dimension is XrayDimension.CURRENCY
            else ClassificationDimension(dimension.value),
            taxonomy=f"synthetic-xray-{dimension.value}",
            taxonomy_version="1",
            category={
                XrayDimension.SECTOR: "technology",
                XrayDimension.INDUSTRY: "software",
                XrayDimension.COUNTRY: "GR",
                XrayDimension.REGION: "europe",
                XrayDimension.CURRENCY: "EUR",
            }[dimension],
            evidence_key=f"performance-{dimension.value}-{index}",
            valid_from=at - timedelta(days=1),
            valid_to=None,
            confidence=Decimal("1"),
        )
        for dimension in XrayDimension
        if dimension is not XrayDimension.COMPANY
        for index, row in enumerate(provider.fixture.listings)
    )
    replay = XrayReplayProvider(
        owner_id=principal.owner_id,
        license=license,
        known_at=known,
        funds=(),
        classifications=classifications,
        clock=lambda: datetime.now(UTC),
    )
    dimensions_completed = 0
    for dimension in XrayDimension:
        if dimension is XrayDimension.COMPANY:
            continue
        request = ports.ClassificationRequest(
            instrument_ids=tuple(str(row.instrument.id) for row in provider.fixture.listings),
            taxonomy=f"synthetic-xray-{dimension.value}",
            taxonomy_version="1",
            source_cutoff_at=datetime.now(UTC),
        )

        async def fetch(
            cursor: str | None, request: ports.ClassificationRequest = request
        ) -> ports.ClassificationPage | ports.SourceFailure:
            return await replay.get_classifications(replace(request, continuation=cursor))

        pages = await collect_source_pages(
            fetch,
            page_type=ports.ClassificationPage,
            next_cursor=lambda page: page.continuation,
            row_count=lambda page: len(page.observations),
        )
        await xray.ingest_classifications(
            principal,
            request,
            pages,
            idempotency_key=f"web-performance-classification-{dimension.value}",
            correlation_id="web-performance-fixture",
        )
        dimensions_completed += 1
        _setup_progress(
            "classification_dimension_ingested", started, completed=dimensions_completed
        )
    with sessions() as session:
        snapshot = session.scalar(
            select(PortfolioSnapshotModel).where(
                PortfolioSnapshotModel.broker_account_id == account
            )
        )
        if snapshot is None:
            raise RuntimeError("The performance canonical snapshot is unavailable.")
        snapshot_id = snapshot.id
    _setup_progress("xray_calculation_started", started)
    financial = await xray.get_effective_exposure(
        principal,
        str(account),
        query=xray_app.EffectiveExposureQuery(
            request=xray_app.XrayRunRequest(
                snapshot_id=str(snapshot_id),
                source_cutoff_at=datetime.now(UTC),
                currency=xray_app.ExplicitCurrency(reporting_currency=CurrencyCode("EUR")),
            ),
            limit=100,
        ),
    )
    if (
        not isinstance(financial, xray_app.ExposuresView)
        or financial.summary.total.value is None
        or (
            financial.summary.total.value.amount != Decimal("1000")
            or financial.summary.company_known_weight.value != Decimal("1")
            or financial.exposures.total != 100
            or any(
                row.effective.value is None or row.effective.value.amount != Decimal("10")
                for row in financial.exposures.items
            )
        )
    ):
        raise RuntimeError("The independently declared 100-by-EUR10 X-ray values differ.")
    _setup_progress("xray_calculation_completed", started, completed=100)
    _check_stop(stop)
    research = PostgresResearchService(
        sessions,
        cursor_signing_key=XRAY_CURSOR_KEY,
        capability_authority=PostgresResearchCapabilityAuthority(),
    )
    with sessions() as session, session.begin():
        news_provider = MarketDataProviderModel(
            id=identifier("news/provider"),
            owner_id=identity.owner.id,
            key="alpha_vantage",
            name="Synthetic 1000-event performance evidence",
            adapter_version="performance-research-v1",
            configuration_state="configured",
            synthetic=True,
            revision=1,
            capabilities=[],
            supported_price_bases=[],
            freshness_policy_version=None,
            max_age_seconds=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(news_provider)
        session.flush()
        news_license = ProviderLicenseVersionModel(
            id=identifier("news/license"),
            owner_id=identity.owner.id,
            provider_id=news_provider.id,
            version_number=1,
            version="performance-news-v1",
            effective_at=at - timedelta(hours=1),
            store_permission="allowed",
            display_permission="allowed",
            report_permission="allowed",
            export_permission="denied",
            retention_days=30,
            attribution="Synthetic performance research facts.",
            evidence_key="synthetic-performance-research-license",
            created_at=datetime.now(UTC),
        )
        session.add(news_license)
        session.flush()
        license_value = license_view(news_license)
        for index in range(100):
            _check_stop(stop)
            scope = ProviderCapabilityScopeModel(
                id=identifier(f"news/scope/{index}"),
                owner_id=identity.owner.id,
                provider_id=news_provider.id,
                capability="news_sentiment",
                subject_kind="entity",
                subject_id=identifier(f"entity/{index}"),
                created_at=datetime.now(UTC),
            )
            session.add(scope)
            session.flush()
            grant = ProviderCapabilityGrantModel(
                id=identifier(f"news/grant/{index}"),
                owner_id=identity.owner.id,
                provider_id=news_provider.id,
                scope_id=scope.id,
                version_number=1,
                license_version_id=news_license.id,
                effective_at=at - timedelta(minutes=30),
                expires_at=at + timedelta(days=30),
                store_allowed=True,
                display_allowed=True,
                report_allowed=True,
                export_allowed=False,
                daily_allowance=25,
                evidence_key="synthetic-performance-research-approval",
                content_digest="0" * 64,
                created_at=datetime.now(UTC),
            )
            grant.content_digest = grant_digest(grant)
            session.add(grant)
    _setup_progress("research_authority_committed", started, completed=100)
    _check_stop(stop)
    actual = sha256()
    _setup_progress("event_publication_started", started)
    with sessions() as session, session.begin():
        auth = authorize_report_request(
            session, principal, account_id=account, required_scopes=scopes, now=datetime.now(UTC)
        )
        for index in range(1000):
            _check_stop(stop)
            observed, entity = datetime.now(UTC), identifier(f"entity/{index % 100}")
            facts = ResearchNewsFacts(
                publisher="Synthetic performance publisher",
                title=f"Performance event {index:04d}",
                summary=(
                    f"Distinct synthetic source statement {index:04d}; "
                    "no portfolio amounts are inferred from prose."
                ),
                published_at=at - timedelta(seconds=1000 - index),
            )
            source = ResearchSourceVersion(
                source_id=identifier(f"news/source/{index}"),
                version_id=identifier(f"news/version/{index}"),
                owner_id=identity.owner.id,
                provider_id=UUID(license_value.provider_id),
                entity_id=entity,
                facts_digest=research_record_digest(facts),
                license_version_id=UUID(license_value.id),
                license=license_value,
                capability=ResearchEventKind.NEWS,
                adapter_version="performance-research-v1",
                request_digest=sha256(str(index).encode()).hexdigest(),
                observed_at=observed,
                first_known_at=observed,
                source_cutoff_at=observed,
                retained_at=observed,
                expires_at=observed + timedelta(days=7),
                synthetic=True,
            )
            key = f"performance-event-{index:04d}"
            citation = ResearchCitation(
                citation_id=identifier(f"news/citation/{index}"),
                source=source,
                provider_event_key=key,
                entity_id=entity,
                facts_digest=source.facts_digest,
                published_at=facts.published_at,
            )
            incoming = ResearchEventRevision(
                event_id=identifier(f"news/event/{index}"),
                revision_id=identifier(f"news/revision/{index}"),
                revision=1,
                previous_revision_id=None,
                owner_id=identity.owner.id,
                entity_id=entity,
                provider_id=source.provider_id,
                provider_event_key=key,
                facts=facts,
                citations=(citation,),
                created_at=observed,
            )
            published = research.publish_event(session, auth, incoming)
            _check_stop(stop)
            actual.update(f"{published.revision_id}:{published.content_digest}\n".encode())
            if (index + 1) % 100 == 0:
                _setup_progress("event_publication_progress", started, completed=index + 1)
        _setup_progress("event_publication_ready_to_commit", started, completed=1000)
        _check_stop(stop)
    _setup_progress("event_publication_committed", started, completed=1000)
    _check_stop(stop)
    cutoff = datetime.now(UTC)
    with sessions() as session:
        positions = session.execute(
            select(SnapshotPositionModel, ListingModel.instrument_id)
            .join(ListingModel, ListingModel.id == SnapshotPositionModel.listing_id)
            .where(SnapshotPositionModel.snapshot_id == snapshot_id)
        ).all()
        counts = {
            label: session.scalar(
                select(func.count()).select_from(model).where(model.owner_id == identity.owner.id)
            )
            for label, model in (
                ("events", ResearchEventRevisionModel),
                ("source_versions", ResearchSourceVersionModel),
                ("witnesses", ResearchWitnessModel),
            )
        }
        capacity = session.get(PremiumCapacityModel, identity.owner.id)
        if (
            len(positions) != 100
            or len({instrument for _, instrument in positions}) != 100
            or any(
                position.market_value != Decimal("10")
                or position.quantity != Decimal("1")
                or position.currency != "EUR"
                for position, _ in positions
            )
            or any(value != 1000 for value in counts.values())
        ):
            raise RuntimeError("The persisted 100-holding/1000-event workload differs.")
        if capacity is None or not 0 < capacity.retained_bytes <= 268435456:
            raise RuntimeError(
                "The normal retained-capacity charge is outside its original budget."
            )
        retained = capacity.retained_bytes
        quality = sorted({position.quality_state for position, _ in positions})
    _setup_progress("verified", started, completed=1000)
    _check_stop(stop)
    return {
        "account_id": str(account),
        "setup_elapsed_seconds": perf_counter() - started,
        "snapshot_id": str(snapshot_id),
        "run_id": financial.context.run_id,
        "cutoff": cutoff.isoformat().replace("+00:00", "Z"),
        "holdings": 100,
        **counts,
        "retained_bytes": retained,
        "position_quality_states": quality,
        "recipe_digest": sha256(
            canonical_json(
                ("web-performance-v1", 100, "10", "EUR", 1000, "10-events-per-entity")
            ).encode()
        ).hexdigest(),
        "published_revision_digest": actual.hexdigest(),
        "xray_input_digest": financial.context.input_digest,
        "xray_result_digest": financial.context.content_digest,
    }
