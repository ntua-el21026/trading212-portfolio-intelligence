"""Complete-chain licensed classification and dedicated fund constituent ingestion."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4, uuid5

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from trading212_application.source_providers import (
    ClassificationPage,
    ClassificationRequest,
    ConstituentPage,
    ConstituentRequest,
)
from trading212_application.xray import XrayServiceErrorCode
from trading212_application.xray_ingestion import XrayRegistrationReceipt
from trading212_domain.sources import SourceUse
from trading212_security.principals import Principal

from .source_store import digest
from .xray_base import xray_error
from .xray_catalog_models import (
    ClassificationAssignmentModel,
    ClassificationSnapshotAssignmentModel,
    ClassificationSnapshotInstrumentModel,
    ClassificationSnapshotModel,
    ConstituentHoldingModel,
    ConstituentSnapshotModel,
    EconomicEntityModel,
    FundDefinitionModel,
    FundSourceMappingModel,
    XrayTaxonomyModel,
)
from .xray_ingestion_pages import classifications, constituents
from .xray_ingestion_store import receipt
from .xray_policy_registrations import XrayPolicyRegistrations


class XrayIngestion(XrayPolicyRegistrations):
    async def ingest_classifications(
        self,
        principal: Principal,
        request: ClassificationRequest,
        pages: tuple[ClassificationPage, ...],
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> XrayRegistrationReceipt:
        batch = classifications(request, pages)

        def operation(session: Session, owner: UUID) -> XrayRegistrationReceipt:
            kind = "classification.ingest"
            previous, fingerprint = self._command(
                session,
                owner,
                kind,
                idempotency_key,
                correlation_id,
                (request, batch.economic_digest),
            )
            provenance = batch.provenance
            license = self._registration_license(
                session, owner, provenance.provider_id, provenance.license_version_id
            )
            taxonomy = session.scalar(
                select(XrayTaxonomyModel).where(
                    XrayTaxonomyModel.owner_id == owner,
                    XrayTaxonomyModel.key == request.taxonomy,
                    XrayTaxonomyModel.version == request.taxonomy_version,
                )
            )
            if taxonomy is None:
                raise xray_error(XrayServiceErrorCode.NOT_FOUND)
            for identifier in request.instrument_ids:
                self._instrument(session, identifier)
            content = digest((str(owner), batch.economic_digest))
            same_revision = (
                ClassificationSnapshotModel.source_revision == provenance.source_revision
            )
            if provenance.revision_order is not None:
                same_revision = or_(
                    same_revision,
                    ClassificationSnapshotModel.revision_order == provenance.revision_order,
                )
            row = session.scalar(
                select(ClassificationSnapshotModel)
                .where(
                    ClassificationSnapshotModel.owner_id == owner,
                    ClassificationSnapshotModel.provider_id == UUID(provenance.provider_id),
                    ClassificationSnapshotModel.license_version_id
                    == UUID(provenance.license_version_id),
                    ClassificationSnapshotModel.request_digest == batch.request_digest,
                    ClassificationSnapshotModel.effective_at == provenance.effective_at,
                    same_revision,
                )
                .limit(1)
            )
            if previous is not None:
                row = self._owned(session, owner, ClassificationSnapshotModel, previous.result_id)
            if row is not None:
                if row.content_digest != content:
                    raise xray_error(XrayServiceErrorCode.SOURCE_REVISION_CONFLICT)
                self._evidence_permit(session, row, SourceUse.STORE)
                if previous is not None:
                    return receipt(row)
            else:
                observed = self._now()
                row = ClassificationSnapshotModel(
                    id=uuid4(),
                    owner_id=owner,
                    provider_id=UUID(provenance.provider_id),
                    license_version_id=UUID(provenance.license_version_id),
                    taxonomy_id=taxonomy.id,
                    adapter_version=provenance.adapter_version,
                    schema_version=provenance.schema_version,
                    source_revision=provenance.source_revision,
                    revision_order=provenance.revision_order,
                    effective_at=provenance.effective_at,
                    valid_until=None,
                    first_observed_at=observed,
                    expires_at=self._expires(license, observed),
                    synthetic=provenance.synthetic,
                    row_count=len(batch.observations),
                    quality="fresh",
                    confidence=None,
                    economic_digest=batch.economic_digest,
                    request_digest=batch.request_digest,
                    content_digest=content,
                    created_at=observed,
                )
                session.add(row)
                session.flush()
                session.add_all(
                    ClassificationSnapshotInstrumentModel(
                        owner_id=owner,
                        snapshot_id=row.id,
                        instrument_id=UUID(identifier),
                        ordinal=ordinal,
                        created_at=observed,
                    )
                    for ordinal, identifier in enumerate(sorted(request.instrument_ids))
                )
                for ordinal, observation in enumerate(batch.observations):
                    dimension = (
                        "currency"
                        if observation.dimension.value == "economic_currency"
                        else observation.dimension.value
                    )
                    if dimension != taxonomy.dimension:
                        raise xray_error(XrayServiceErrorCode.VALIDATION_FAILED)
                    assignment_id = uuid5(row.id, digest(observation))
                    session.add(
                        ClassificationAssignmentModel(
                            id=assignment_id,
                            owner_id=owner,
                            snapshot_id=row.id,
                            instrument_id=UUID(observation.instrument_id),
                            entity_id=None,
                            source_key=digest(observation),
                            dimension=dimension,
                            bucket_key=observation.category,
                            effective_at=observation.valid_from,
                            valid_until=observation.valid_to,
                            confidence=observation.confidence,
                            evidence_key=observation.evidence_key,
                            state="available",
                            created_at=observed,
                        )
                    )
                    session.add(
                        ClassificationSnapshotAssignmentModel(
                            owner_id=owner,
                            snapshot_id=row.id,
                            assignment_id=assignment_id,
                            ordinal=ordinal,
                            created_at=observed,
                        )
                    )
                    if (ordinal + 1) % 512 == 0:
                        session.flush()
                session.flush()
            self._enrichment_receipt(session, row)
            return self._command_receipt(
                session, principal, kind, idempotency_key, fingerprint, correlation_id, row
            )

        return await self._xrun(principal, operation, write=True)

    async def ingest_constituents(
        self,
        principal: Principal,
        request: ConstituentRequest,
        pages: tuple[ConstituentPage, ...],
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> XrayRegistrationReceipt:
        batch = constituents(request, pages)

        def operation(session: Session, owner: UUID) -> XrayRegistrationReceipt:
            kind = "constituent.ingest"
            previous, fingerprint = self._command(
                session,
                owner,
                kind,
                idempotency_key,
                correlation_id,
                (request, batch.economic_digest),
            )
            provenance = batch.header.provenance
            mapping = self._owned(session, owner, FundSourceMappingModel, request.fund_series_id)
            definition = self._owned(
                session, owner, FundDefinitionModel, mapping.fund_definition_id
            )
            self._evidence_permit(session, mapping, SourceUse.STORE)
            self._evidence_permit(session, definition, SourceUse.STORE)
            license = self._registration_license(
                session, owner, provenance.provider_id, provenance.license_version_id
            )
            if mapping.provider_id != UUID(
                provenance.provider_id
            ) or mapping.license_version_id != UUID(provenance.license_version_id):
                raise xray_error(XrayServiceErrorCode.ACCESS_DENIED)
            content = digest((str(owner), batch.economic_digest))
            same_revision = ConstituentSnapshotModel.source_revision == provenance.source_revision
            if provenance.revision_order is not None:
                same_revision = or_(
                    same_revision,
                    ConstituentSnapshotModel.revision_order == provenance.revision_order,
                )
            row = session.scalar(
                select(ConstituentSnapshotModel)
                .where(
                    ConstituentSnapshotModel.owner_id == owner,
                    ConstituentSnapshotModel.fund_mapping_id == mapping.id,
                    ConstituentSnapshotModel.provider_id == UUID(provenance.provider_id),
                    ConstituentSnapshotModel.license_version_id
                    == UUID(provenance.license_version_id),
                    ConstituentSnapshotModel.effective_at == provenance.effective_at,
                    same_revision,
                )
                .limit(1)
            )
            if previous is not None:
                row = self._owned(session, owner, ConstituentSnapshotModel, previous.result_id)
            if row is not None:
                if row.content_digest != content:
                    raise xray_error(XrayServiceErrorCode.SOURCE_REVISION_CONFLICT)
                self._evidence_permit(session, row, SourceUse.STORE)
                if previous is not None:
                    return receipt(row)
            else:
                observed = self._now()
                header = batch.header
                row = ConstituentSnapshotModel(
                    id=uuid4(),
                    owner_id=owner,
                    provider_id=mapping.provider_id,
                    license_version_id=mapping.license_version_id,
                    fund_mapping_id=mapping.id,
                    adapter_version=provenance.adapter_version,
                    schema_version=provenance.schema_version,
                    source_revision=provenance.source_revision,
                    revision_order=provenance.revision_order,
                    effective_at=header.effective_at,
                    valid_until=None,
                    first_observed_at=observed,
                    expires_at=self._expires(license, observed),
                    synthetic=provenance.synthetic,
                    row_count=len(batch.holdings),
                    quality="partial"
                    if header.unresolved_weight is None or header.unresolved_weight > Decimal("0")
                    else "fresh",
                    confidence=None,
                    economic_digest=batch.economic_digest,
                    request_digest=batch.request_digest,
                    content_digest=content,
                    known_weight=header.stated_coverage,
                    unresolved_weight=header.unresolved_weight,
                    cash_weight=header.cash_weight,
                    created_at=observed,
                )
                session.add(row)
                session.flush()
                for ordinal, holding in enumerate(batch.holdings):
                    if holding.instrument_id is not None:
                        self._instrument(session, holding.instrument_id)
                    if holding.entity_id is not None:
                        self._owned(session, owner, EconomicEntityModel, holding.entity_id)
                    session.add(
                        ConstituentHoldingModel(
                            id=uuid5(row.id, holding.source_key),
                            owner_id=owner,
                            snapshot_id=row.id,
                            ordinal=ordinal,
                            source_key=holding.source_key,
                            instrument_id=None
                            if holding.instrument_id is None
                            else UUID(holding.instrument_id),
                            entity_id=None
                            if holding.entity_id is None
                            else UUID(holding.entity_id),
                            state=holding.state.value,
                            currency=holding.currency.value,
                            weight=holding.weight,
                            name=None,
                            confidence=None,
                            evidence_key=holding.evidence_key,
                            created_at=observed,
                        )
                    )
                    if (ordinal + 1) % 512 == 0:
                        session.flush()
                session.flush()
            self._enrichment_receipt(session, row)
            return self._command_receipt(
                session, principal, kind, idempotency_key, fingerprint, correlation_id, row
            )

        return await self._xrun(principal, operation, write=True)
