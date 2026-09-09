"""Owner-authorized immutable entity/fund registrations from typed internal commands."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application.xray import XrayServiceErrorCode
from trading212_application.xray_ingestion import (
    EntityEvidenceRegistration,
    FundDefinitionRegistration,
    FundSourceMappingRegistration,
    XrayRegistrationReceipt,
)
from trading212_domain.sources import SourceUse
from trading212_security.principals import Principal

from .xray_base import xray_error
from .xray_catalog_models import (
    EconomicEntityModel,
    EntityEvidenceReferenceModel,
    EntityEvidenceVersionModel,
    FundDefinitionModel,
    FundSourceMappingModel,
    InstrumentEntityRelationshipModel,
    ShareClassModel,
)
from .xray_ingestion_store import XrayIngestionStore, receipt


class XrayRegistrations(XrayIngestionStore):
    async def register_entity_evidence(
        self,
        principal: Principal,
        registration: EntityEvidenceRegistration,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> XrayRegistrationReceipt:
        if not isinstance(registration, EntityEvidenceRegistration):
            raise xray_error(XrayServiceErrorCode.VALIDATION_FAILED)

        def operation(session: Session, owner: UUID) -> XrayRegistrationReceipt:
            kind = "entity.register"
            previous, fingerprint = self._command(
                session,
                owner,
                kind,
                idempotency_key,
                correlation_id,
                registration,
            )
            license = self._registration_license(
                session,
                owner,
                registration.provider_id,
                registration.license_version_id,
            )
            existing = session.scalar(
                select(EntityEvidenceVersionModel).where(
                    EntityEvidenceVersionModel.owner_id == owner,
                    EntityEvidenceVersionModel.provider_id == UUID(registration.provider_id),
                    EntityEvidenceVersionModel.key == registration.key,
                    EntityEvidenceVersionModel.revision_order == registration.revision,
                )
            )
            if previous is not None:
                existing = self._owned(
                    session, owner, EntityEvidenceVersionModel, previous.result_id
                )
            if existing is not None:
                if existing.id != UUID(registration.id) or existing.content_digest != fingerprint:
                    raise xray_error(XrayServiceErrorCode.SOURCE_REVISION_CONFLICT)
                self._evidence_permit(session, existing, SourceUse.STORE)
                if previous is not None:
                    return receipt(existing)
                row = existing
            else:
                observed = self._now()
                row = EntityEvidenceVersionModel(
                    id=UUID(registration.id),
                    owner_id=owner,
                    key=registration.key,
                    provider_id=UUID(registration.provider_id),
                    license_version_id=UUID(registration.license_version_id),
                    revision_order=registration.revision,
                    effective_at=registration.effective_at,
                    valid_until=registration.valid_until,
                    first_observed_at=observed,
                    expires_at=self._expires(license, observed),
                    confidence=None,
                    content_digest=fingerprint,
                    created_at=observed,
                )
                session.add(row)
                session.flush()
                self._entity_rows(session, owner, row, registration)
            self._enrichment_receipt(session, row)
            return self._command_receipt(
                session,
                principal,
                kind,
                idempotency_key,
                fingerprint,
                correlation_id,
                row,
            )

        return await self._xrun(principal, operation, write=True)

    def _entity_rows(
        self,
        session: Session,
        owner: UUID,
        parent: EntityEvidenceVersionModel,
        registration: EntityEvidenceRegistration,
    ) -> None:
        for ordinal, item in enumerate(sorted(registration.entities, key=lambda item: item.id)):
            entity = session.scalar(
                select(EconomicEntityModel).where(
                    EconomicEntityModel.owner_id == owner,
                    EconomicEntityModel.id == UUID(item.id),
                )
            )
            if entity is None:
                entity = EconomicEntityModel(
                    id=UUID(item.id), owner_id=owner, key=item.key, created_at=self._now()
                )
                session.add(entity)
                session.flush()
            elif entity.key != item.key:
                raise xray_error(XrayServiceErrorCode.SOURCE_REVISION_CONFLICT)
            session.add(
                EntityEvidenceReferenceModel(
                    id=uuid4(),
                    owner_id=owner,
                    evidence_version_id=parent.id,
                    entity_id=entity.id,
                    kind="entity",
                    ordinal=ordinal,
                    instrument_id=None,
                    listing_id=None,
                    display_name=item.display_name,
                    lei=item.lei,
                    effective_at=parent.effective_at,
                    valid_until=parent.valid_until,
                    confidence=None,
                    created_at=self._now(),
                )
            )
        for ordinal, mapping in enumerate(
            sorted(registration.mappings, key=lambda mapping: mapping.id),
            start=len(registration.entities),
        ):
            self._instrument(session, mapping.instrument_id, mapping.listing_id)
            self._owned(session, owner, EconomicEntityModel, mapping.entity_id)
            session.add(
                EntityEvidenceReferenceModel(
                    id=UUID(mapping.id),
                    owner_id=owner,
                    evidence_version_id=parent.id,
                    entity_id=UUID(mapping.entity_id),
                    kind="instrument_mapping",
                    ordinal=ordinal,
                    instrument_id=UUID(mapping.instrument_id),
                    listing_id=None if mapping.listing_id is None else UUID(mapping.listing_id),
                    display_name=None,
                    lei=None,
                    effective_at=mapping.effective_at,
                    valid_until=mapping.valid_until,
                    confidence=mapping.confidence,
                    created_at=self._now(),
                )
            )
        for share in registration.share_classes:
            self._instrument(session, share.instrument_id)
            self._owned(session, owner, EconomicEntityModel, share.entity_id)
            session.add(
                ShareClassModel(
                    id=UUID(share.id),
                    owner_id=owner,
                    evidence_version_id=parent.id,
                    instrument_id=UUID(share.instrument_id),
                    entity_id=UUID(share.entity_id),
                    class_key=share.class_key,
                    effective_at=share.effective_at,
                    valid_until=share.valid_until,
                    confidence=share.confidence,
                    created_at=self._now(),
                )
            )
        session.flush()
        for relation in registration.relationships:
            if relation.instrument_id is not None:
                self._instrument(session, relation.instrument_id, relation.listing_id)
            if relation.underlying_instrument_id is not None:
                self._instrument(session, relation.underlying_instrument_id)
            if relation.entity_id is not None:
                self._owned(session, owner, EconomicEntityModel, relation.entity_id)
            if relation.parent_entity_id is not None:
                self._owned(session, owner, EconomicEntityModel, relation.parent_entity_id)
            if relation.share_class_id is not None:
                share_row = self._owned(session, owner, ShareClassModel, relation.share_class_id)
                if (
                    str(share_row.instrument_id) != relation.instrument_id
                    or str(share_row.entity_id) != relation.entity_id
                ):
                    raise xray_error(XrayServiceErrorCode.VALIDATION_FAILED)
                share_parent = self._owned(
                    session, owner, EntityEvidenceVersionModel, share_row.evidence_version_id
                )
                self._evidence_permit(session, share_parent, SourceUse.STORE)
            session.add(
                InstrumentEntityRelationshipModel(
                    id=UUID(relation.id),
                    owner_id=owner,
                    evidence_version_id=parent.id,
                    kind=relation.kind,
                    **{
                        name: None
                        if getattr(relation, name) is None
                        else UUID(getattr(relation, name))
                        for name in (
                            "instrument_id",
                            "listing_id",
                            "share_class_id",
                            "entity_id",
                            "underlying_instrument_id",
                            "parent_entity_id",
                        )
                    },
                    units_per_receipt=relation.units_per_receipt,
                    effective_at=relation.effective_at,
                    valid_until=relation.valid_until,
                    confidence=relation.confidence,
                    created_at=self._now(),
                )
            )
        session.flush()

    async def register_fund_definition(
        self,
        principal: Principal,
        registration: FundDefinitionRegistration,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> XrayRegistrationReceipt:
        if not isinstance(registration, FundDefinitionRegistration):
            raise xray_error(XrayServiceErrorCode.VALIDATION_FAILED)

        def operation(session: Session, owner: UUID) -> XrayRegistrationReceipt:
            kind = "fund.register"
            previous, fingerprint = self._command(
                session, owner, kind, idempotency_key, correlation_id, registration
            )
            license = self._registration_license(
                session, owner, registration.provider_id, registration.license_version_id
            )
            self._instrument(session, registration.instrument_id)
            if registration.share_class_id is not None:
                share = self._owned(session, owner, ShareClassModel, registration.share_class_id)
                if share.instrument_id != UUID(registration.instrument_id):
                    raise xray_error(XrayServiceErrorCode.VALIDATION_FAILED)
                self._evidence_permit(
                    session,
                    self._owned(
                        session, owner, EntityEvidenceVersionModel, share.evidence_version_id
                    ),
                    SourceUse.STORE,
                )
            row = session.scalar(
                select(FundDefinitionModel).where(
                    FundDefinitionModel.owner_id == owner,
                    FundDefinitionModel.key == registration.key,
                    FundDefinitionModel.revision_order == registration.revision,
                )
            )
            if previous is not None:
                row = self._owned(session, owner, FundDefinitionModel, previous.result_id)
            if row is not None:
                if row.id != UUID(registration.id) or row.content_digest != fingerprint:
                    raise xray_error(XrayServiceErrorCode.SOURCE_REVISION_CONFLICT)
                self._evidence_permit(session, row, SourceUse.STORE)
                if previous is not None:
                    return receipt(row)
            else:
                observed = self._now()
                row = FundDefinitionModel(
                    id=UUID(registration.id),
                    owner_id=owner,
                    key=registration.key,
                    instrument_id=UUID(registration.instrument_id),
                    fund_type=registration.fund_type,
                    share_class_id=None
                    if registration.share_class_id is None
                    else UUID(registration.share_class_id),
                    provider_id=UUID(registration.provider_id),
                    license_version_id=UUID(registration.license_version_id),
                    revision_order=registration.revision,
                    effective_at=registration.effective_at,
                    valid_until=registration.valid_until,
                    first_observed_at=observed,
                    expires_at=self._expires(license, observed),
                    evidence_key=registration.evidence_key,
                    confidence=registration.confidence,
                    content_digest=fingerprint,
                    created_at=observed,
                )
                session.add(row)
                session.flush()
            self._enrichment_receipt(session, row)
            return self._command_receipt(
                session, principal, kind, idempotency_key, fingerprint, correlation_id, row
            )

        return await self._xrun(principal, operation, write=True)

    async def register_fund_mapping(
        self,
        principal: Principal,
        registration: FundSourceMappingRegistration,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> XrayRegistrationReceipt:
        if not isinstance(registration, FundSourceMappingRegistration):
            raise xray_error(XrayServiceErrorCode.VALIDATION_FAILED)

        def operation(session: Session, owner: UUID) -> XrayRegistrationReceipt:
            kind = "fund_mapping.register"
            previous, fingerprint = self._command(
                session, owner, kind, idempotency_key, correlation_id, registration
            )
            license = self._registration_license(
                session, owner, registration.provider_id, registration.license_version_id
            )
            definition = self._owned(
                session, owner, FundDefinitionModel, registration.fund_definition_id
            )
            self._evidence_permit(session, definition, SourceUse.STORE)
            row = session.scalar(
                select(FundSourceMappingModel).where(
                    FundSourceMappingModel.owner_id == owner,
                    FundSourceMappingModel.provider_id == UUID(registration.provider_id),
                    FundSourceMappingModel.provider_fund_key == registration.provider_fund_key,
                    FundSourceMappingModel.revision_order == registration.revision,
                )
            )
            if previous is not None:
                row = self._owned(session, owner, FundSourceMappingModel, previous.result_id)
            if row is not None:
                if row.id != UUID(registration.id) or row.content_digest != fingerprint:
                    raise xray_error(XrayServiceErrorCode.SOURCE_REVISION_CONFLICT)
                self._evidence_permit(session, row, SourceUse.STORE)
                if previous is not None:
                    return receipt(row)
            else:
                observed = self._now()
                row = FundSourceMappingModel(
                    id=UUID(registration.id),
                    owner_id=owner,
                    fund_definition_id=definition.id,
                    provider_id=UUID(registration.provider_id),
                    license_version_id=UUID(registration.license_version_id),
                    provider_fund_key=registration.provider_fund_key,
                    revision_order=registration.revision,
                    effective_at=registration.effective_at,
                    valid_until=registration.valid_until,
                    first_observed_at=observed,
                    expires_at=self._expires(license, observed),
                    evidence_key=registration.evidence_key,
                    confidence=registration.confidence,
                    content_digest=fingerprint,
                    created_at=observed,
                )
                session.add(row)
                session.flush()
            self._enrichment_receipt(session, row)
            return self._command_receipt(
                session, principal, kind, idempotency_key, fingerprint, correlation_id, row
            )

        return await self._xrun(principal, operation, write=True)
