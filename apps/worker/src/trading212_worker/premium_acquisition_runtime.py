"""Private composition of fixed GET adapters and real PostgreSQL authority/receipts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import NAMESPACE_OID, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application.source_providers import FxPair
from trading212_domain import CurrencyCode
from trading212_domain.research import ResearchEventKind
from trading212_domain.research_serialization import research_record_digest
from trading212_domain.research_sources import (
    ResearchCitation,
    ResearchEventRevision,
    ResearchSourceFacts,
    ResearchSourceVersion,
)
from trading212_domain.sources import FxSnapshot, PriceSnapshot, SourcePeriod
from trading212_persistence.acquisition_authority import acquisition_auth
from trading212_persistence.acquisition_models import (
    ProviderAcquisitionAttemptModel,
    ProviderAcquisitionRequestModel,
)
from trading212_persistence.acquisition_publication import PostgresAcquisitionPublisher
from trading212_persistence.acquisition_records import (
    AcquisitionAttemptReceipt,
    AcquisitionAuthorityBasis,
    AcquisitionOutcome,
    AcquisitionPublicationClock,
    AcquisitionSelection,
    AcquisitionStorageDenied,
)
from trading212_persistence.acquisition_records import (
    AcquisitionCapability as StoredCapability,
)
from trading212_persistence.acquisition_research_authority import (
    PostgresResearchCapabilityAuthority,
)
from trading212_persistence.acquisition_store import acquisition_lock, attempt_receipt
from trading212_reference_data.premium_acquisition import (
    ConfiguredPremiumAcquisition,
    acquisition_request_digest,
)
from trading212_reference_data.premium_acquisition_types import (
    ADAPTER_VERSION,
    AcquisitionAttempt,
    AcquisitionCommand,
    AcquisitionCredentialPort,
    AcquisitionFailureCode,
    AcquisitionPermit,
    capability,
)
from trading212_reference_data.premium_facts import (
    AcquiredSourceBatch,
    CompanyOverviewFacts,
    DailyAdjustedFacts,
    EcbReferenceFacts,
    NewsSentimentFacts,
    premium_facts_digest,
)
from trading212_reference_data.premium_projection import (
    build_ecb_fx_pages,
    build_price_history_pages,
)
from trading212_security.principals import Principal


def _selection(command: AcquisitionCommand) -> AcquisitionSelection:
    return AcquisitionSelection(
        owner_id=command.owner_id,
        account_id=command.account_id,
        request_id=command.request_id,
        mapping_version_id=command.mapping_version_id,
        capability=StoredCapability(capability(command).value),
    )


def _permit(basis: AcquisitionAuthorityBasis) -> AcquisitionPermit:
    from trading212_reference_data.premium_acquisition_types import AcquisitionCapability

    return AcquisitionPermit(
        owner_id=basis.owner_id,
        account_id=basis.account_id,
        mapping_version_id=basis.mapping_version_id,
        mapping_digest=basis.mapping_digest,
        provider_id=basis.provider_id,
        capability=AcquisitionCapability(basis.capability.value),
        policy_version_id=basis.policy_version_id,
        policy_digest=basis.policy_digest,
        grant_id=basis.grant_id,
        grant_digest=basis.grant_digest,
        license=basis.license,
        effective_at=basis.effective_at,
        expires_at=basis.expires_at,
        symbol=basis.symbol,
        price_currency=basis.price_currency,
        instrument_id=basis.instrument_id,
        entity_id=basis.entity_id,
        canonical_market_mapping_id=basis.canonical_market_mapping_id,
        credential_reference=None
        if basis.provider_key == "ecb"
        else f"reference-data/alpha-vantage/{basis.owner_id}/{basis.provider_id}",
    )


def _receipt(attempt: AcquisitionAttempt) -> AcquisitionAttemptReceipt:
    return AcquisitionAttemptReceipt(
        id=attempt.id,
        request_id=attempt.request_id,
        owner_id=attempt.owner_id,
        provider_id=attempt.provider_id,
        request_digest=attempt.request_digest,
        ordinal=attempt.ordinal,
        first_started_at=attempt.first_started_at,
        reserved_at=attempt.reserved_at,
        deadline=attempt.deadline,
        lease_expires_at=attempt.lease_expires_at,
    )


class PostgresPremiumAcquisitionRuntime:
    """No default credential or grant. This object is never a public request endpoint."""

    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        principal: Principal,
        cursor_signing_key: bytes,
        enabled: bool = False,
        credentials: AcquisitionCredentialPort | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = PostgresAcquisitionPublisher(
            sessions=sessions,
            principal=principal,
            cursor_signing_key=cursor_signing_key,
            enabled=enabled,
            clock=clock,
        )
        self.research_authority = PostgresResearchCapabilityAuthority()
        self.acquisition = ConfiguredPremiumAcquisition(
            enabled=enabled, authority=self, attempts=self, credentials=credentials, clock=clock
        )

    async def resolve(
        self, command: AcquisitionCommand, *, now: datetime
    ) -> AcquisitionPermit | None:
        # The store obtains its own current time; caller-supplied time is never authority.
        basis = await self._store.resolve(_selection(command))
        return None if basis is None else _permit(basis)

    async def recheck(
        self, command: AcquisitionCommand, permit: AcquisitionPermit, *, now: datetime
    ) -> bool:
        basis = await self._store.resolve(_selection(command))
        return basis is not None and _permit(basis) == permit

    async def reserve(
        self,
        command: AcquisitionCommand,
        permit: AcquisitionPermit,
        *,
        request_digest: str,
        now: datetime,
    ) -> AcquisitionAttempt | None:
        basis = await self._store.resolve(_selection(command))
        if (
            basis is None
            or _permit(basis) != permit
            or acquisition_request_digest(command, permit) != request_digest
        ):
            return None
        receipt = await self._store.reserve(
            _selection(command), basis, request_digest=request_digest
        )
        if receipt is None:
            return None
        return AcquisitionAttempt(
            id=receipt.id,
            request_id=receipt.request_id,
            owner_id=receipt.owner_id,
            provider_id=receipt.provider_id,
            request_digest=receipt.request_digest,
            ordinal=receipt.ordinal,
            first_started_at=receipt.first_started_at,
            reserved_at=receipt.reserved_at,
            deadline=receipt.deadline,
            lease_expires_at=receipt.lease_expires_at,
        )

    async def finish(
        self,
        attempt: AcquisitionAttempt,
        *,
        outcome: AcquisitionFailureCode | None,
        observed_at: datetime,
        retry_at: datetime | None,
    ) -> bool:
        return await self._store.finish(
            _receipt(attempt),
            outcome=None if outcome is None else AcquisitionOutcome(outcome.value),
            observed_at=observed_at,
            retry_at=retry_at,
        )

    async def _successful_receipt(
        self, selection: AcquisitionSelection, attempt_id: UUID
    ) -> AcquisitionAttemptReceipt:
        def operation(session: Session) -> AcquisitionAttemptReceipt:
            acquisition_lock(session, selection.owner_id)
            auth = acquisition_auth(
                session, self._store._principal, selection, now=self._store._now()
            )
            row = session.scalar(
                select(ProviderAcquisitionAttemptModel).where(
                    ProviderAcquisitionAttemptModel.owner_id == auth.owner_id,
                    ProviderAcquisitionAttemptModel.id == attempt_id,
                    ProviderAcquisitionAttemptModel.request_id == selection.request_id,
                )
            )
            root = session.scalar(
                select(ProviderAcquisitionRequestModel).where(
                    ProviderAcquisitionRequestModel.owner_id == auth.owner_id,
                    ProviderAcquisitionRequestModel.id == selection.request_id,
                )
            )
            if (
                row is None
                or row.finished_at is None
                or row.outcome is not None
                or root is None
                or root.state != "succeeded"
                or root.principal_id != auth.principal_id
                or root.account_id != auth.account_id
            ):
                raise AcquisitionStorageDenied()
            return attempt_receipt(row)

        return await self._store._execute(operation)

    async def publish(
        self, batch: AcquiredSourceBatch
    ) -> PriceSnapshot | FxSnapshot | tuple[ResearchEventRevision, ...]:
        """Only complete supported normalized facts may enter canonical publication."""
        if type(batch) is not AcquiredSourceBatch:
            raise AcquisitionStorageDenied()
        selection = _selection(batch.command)
        basis = await self._store.resolve(selection)
        value = batch.provenance
        if basis is None:
            raise AcquisitionStorageDenied()
        if (
            premium_facts_digest(batch.facts) != value.content_digest
            or acquisition_request_digest(batch.command, _permit(basis)) != value.request_digest
            or value.adapter_version != ADAPTER_VERSION
            or value.synthetic
            or (
                value.owner_id,
                value.account_id,
                value.provider_id,
                value.mapping_version_id,
                value.mapping_digest,
                value.policy_version_id,
                value.policy_digest,
                value.grant_id,
                value.grant_digest,
                value.license,
                value.instrument_id,
                value.entity_id,
                value.canonical_market_mapping_id,
            )
            != (
                basis.owner_id,
                basis.account_id,
                basis.provider_id,
                basis.mapping_version_id,
                basis.mapping_digest,
                basis.policy_version_id,
                basis.policy_digest,
                basis.grant_id,
                basis.grant_digest,
                basis.license,
                basis.instrument_id,
                basis.entity_id,
                basis.canonical_market_mapping_id,
            )
        ):
            raise AcquisitionStorageDenied()
        receipt = await self._successful_receipt(selection, value.attempt_id)
        if receipt.request_digest != value.request_digest or value.request_id != receipt.request_id:
            raise AcquisitionStorageDenied()
        clock = AcquisitionPublicationClock(
            acquired_at=value.observed_at,
            first_known_at=value.first_known_at,
            expires_at=value.expires_at,
            content_digest=value.content_digest,
        )
        if type(batch.facts) is DailyAdjustedFacts:
            metadata = await self._store.market_metadata(selection, basis)
            if metadata.series is None:
                raise AcquisitionStorageDenied()
            request, pages = build_price_history_pages(batch, metadata.series, metadata.calendar)
            return await self._store.publish_market(
                selection, basis, receipt, clock, request, pages
            )
        if type(batch.facts) is EcbReferenceFacts:
            metadata = await self._store.market_metadata(selection, basis)
            quotes = sorted({row.quote.value for row in batch.facts.rows})
            if len(quotes) > 32:
                # The canonical FxRatesRequest bound is frozen; never truncate the feed.
                raise AcquisitionStorageDenied()
            pairs = tuple(
                FxPair(base=CurrencyCode("EUR"), quote=CurrencyCode(quote)) for quote in quotes
            )
            fx_request, fx_pages = build_ecb_fx_pages(
                batch,
                metadata.calendar,
                pairs,
                SourcePeriod(start=batch.facts.first_date, end=batch.facts.last_date),
            )
            return await self._store.publish_market(
                selection, basis, receipt, clock, fx_request, fx_pages
            )
        if type(batch.facts) in (CompanyOverviewFacts, NewsSentimentFacts):
            return await self._store.publish_research(
                selection, basis, receipt, clock, self._events(batch)
            )
        raise AcquisitionStorageDenied()

    @staticmethod
    def _events(batch: AcquiredSourceBatch) -> tuple[ResearchEventRevision, ...]:
        value = batch.provenance
        if value.entity_id is None:
            raise AcquisitionStorageDenied()
        items: tuple[tuple[str, ResearchSourceFacts], ...]
        if type(batch.facts) is CompanyOverviewFacts:
            items = ((f"overview:{value.entity_id}", batch.facts.source),)
        elif type(batch.facts) is NewsSentimentFacts:
            items = tuple((item.source_key, item.facts) for item in batch.facts.items)
        else:
            raise AcquisitionStorageDenied()
        output = []
        for key, facts in items:
            identity = f"premium:{value.owner_id}:{value.provider_id}:{value.entity_id}:{key}"
            source = ResearchSourceVersion(
                source_id=uuid5(NAMESPACE_OID, identity),
                version_id=uuid5(value.attempt_id, key),
                owner_id=value.owner_id,
                provider_id=value.provider_id,
                entity_id=value.entity_id,
                facts_digest=research_record_digest(facts),
                license_version_id=UUID(value.license.id),
                license=value.license,
                capability=ResearchEventKind(facts.kind),
                adapter_version=value.adapter_version,
                request_digest=value.request_digest,
                observed_at=value.observed_at,
                first_known_at=value.first_known_at,
                source_cutoff_at=value.first_known_at,
                retained_at=value.observed_at,
                expires_at=value.expires_at,
                synthetic=False,
            )
            citation = ResearchCitation(
                citation_id=uuid5(source.version_id, "citation"),
                source=source,
                provider_event_key=key,
                entity_id=value.entity_id,
                facts_digest=source.facts_digest,
                published_at=facts.published_at,
            )
            # These are acquisition witness identities, not invented provider revision numbers.
            output.append(
                ResearchEventRevision(
                    event_id=uuid5(NAMESPACE_OID, identity),
                    revision_id=uuid5(source.version_id, "witness"),
                    revision=1,
                    previous_revision_id=None,
                    owner_id=value.owner_id,
                    entity_id=value.entity_id,
                    provider_id=value.provider_id,
                    provider_event_key=key,
                    facts=facts,
                    citations=(citation,),
                    created_at=value.observed_at,
                )
            )
        return tuple(output)
