"""Transactional idempotency, source permission and real subject binding helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application.targets import validate_target_idempotency_key
from trading212_application.xray import XrayServiceErrorCode
from trading212_application.xray_ingestion import XrayRegistrationReceipt
from trading212_domain.sources import SourceLicense, SourceUse
from trading212_security.principals import Principal

from .models import InstrumentModel, ListingModel
from .source_store import digest
from .xray_base import XrayStore, xray_error
from .xray_catalog_models import (
    ClassificationSnapshotModel,
    ConstituentSnapshotModel,
    EntityEvidenceVersionModel,
    FundDefinitionModel,
    FundSourceMappingModel,
    XrayEvidenceFields,
    XrayPolicyVersionModel,
)
from .xray_lifecycle_models import (
    EnrichmentRetrievalOccurrenceModel,
    XrayAuditEventModel,
    XrayCommandIdentityModel,
)


def receipt(row: XrayEvidenceFields | XrayPolicyVersionModel) -> XrayRegistrationReceipt:
    return XrayRegistrationReceipt(
        id=str(row.id), content_digest=row.content_digest, first_observed_at=row.first_observed_at
    )


class XrayIngestionStore(XrayStore):
    def _command(
        self,
        session: Session,
        owner: UUID,
        kind: str,
        key: str,
        correlation: str,
        payload: object,
    ) -> tuple[XrayCommandIdentityModel | None, str]:
        validate_target_idempotency_key(key)
        if (
            not isinstance(correlation, str)
            or not 1 <= len(correlation) <= 100
            or "\x00" in correlation
        ):
            raise xray_error(XrayServiceErrorCode.VALIDATION_FAILED)
        fingerprint = digest((str(owner), payload))
        previous = session.scalar(
            select(XrayCommandIdentityModel).where(
                XrayCommandIdentityModel.owner_id == owner,
                XrayCommandIdentityModel.idempotency_key == key,
            )
        )
        if previous is not None and (
            previous.kind != kind or previous.request_digest != fingerprint
        ):
            raise xray_error(XrayServiceErrorCode.IDEMPOTENCY_KEY_REUSED)
        return previous, fingerprint

    def _command_receipt(
        self,
        session: Session,
        principal: Principal,
        kind: str,
        key: str,
        fingerprint: str,
        correlation: str,
        row: XrayEvidenceFields | XrayPolicyVersionModel,
    ) -> XrayRegistrationReceipt:
        command = XrayCommandIdentityModel(
            id=uuid4(),
            owner_id=row.owner_id,
            kind=kind,
            idempotency_key=key,
            request_digest=fingerprint,
            result_id=row.id,
            actor_principal_id=principal.principal_id,
            correlation_id=correlation,
            created_at=self._now(),
        )
        session.add(command)
        session.flush()
        session.add(
            XrayAuditEventModel(
                owner_id=row.owner_id,
                command_id=command.id,
                kind=kind,
                resource_id=row.id,
                actor_principal_id=principal.principal_id,
                correlation_id=correlation,
                created_at=self._now(),
            )
        )
        session.flush()
        return receipt(row)

    def _evidence_permit(self, session: Session, row: XrayEvidenceFields, use: SourceUse) -> None:
        # The expiry instant denies even while physical copy cleanup remains pending.
        self._permit(session, row.owner_id, row.license_version_id, use)
        if row.expires_at <= self._now():
            raise xray_error(XrayServiceErrorCode.ACCESS_DENIED)
        from .source_models import SourceExpiryEventModel, SourceRetentionWorkModel
        from .xray_lifecycle_models import EnrichmentExpiryEventModel, EnrichmentRetentionWorkModel

        models: tuple[type[Any], ...]
        if isinstance(row, ConstituentSnapshotModel):
            models = (SourceExpiryEventModel, SourceRetentionWorkModel)
            name = "constituent_snapshot_id"
        else:
            models = (EnrichmentExpiryEventModel, EnrichmentRetentionWorkModel)
            name = {
                EntityEvidenceVersionModel: "entity_evidence_version_id",
                ClassificationSnapshotModel: "classification_snapshot_id",
                FundDefinitionModel: "fund_definition_id",
                FundSourceMappingModel: "fund_mapping_id",
            }[type(row)]
        if any(
            session.scalar(
                select(model.id)
                .where(model.owner_id == row.owner_id, getattr(model, name) == row.id)
                .limit(1)
            )
            is not None
            for model in models
        ):
            raise xray_error(XrayServiceErrorCode.ACCESS_DENIED)

    def _registration_license(
        self,
        session: Session,
        owner: UUID,
        provider: str,
        license_id: str,
    ) -> SourceLicense:
        license = self._permit(session, owner, UUID(license_id), SourceUse.STORE)
        if license.provider_id != provider or license.retention_days is None:
            raise xray_error(XrayServiceErrorCode.ACCESS_DENIED)
        return license

    def _expires(self, license: SourceLicense, observed: datetime) -> datetime:
        if license.retention_days is None:
            raise xray_error(XrayServiceErrorCode.ACCESS_DENIED)
        return observed + timedelta(days=license.retention_days)

    def _instrument(self, session: Session, instrument: str, listing: str | None = None) -> None:
        identifier = UUID(instrument)
        if (
            session.scalar(select(InstrumentModel.id).where(InstrumentModel.id == identifier))
            is None
        ):
            raise xray_error(XrayServiceErrorCode.NOT_FOUND)
        if (
            listing is not None
            and session.scalar(
                select(ListingModel.id).where(
                    ListingModel.id == UUID(listing),
                    ListingModel.instrument_id == identifier,
                )
            )
            is None
        ):
            raise xray_error(XrayServiceErrorCode.NOT_FOUND)

    def _enrichment_receipt(self, session: Session, row: XrayEvidenceFields) -> None:
        names = {
            EntityEvidenceVersionModel: "entity_evidence_version_id",
            ClassificationSnapshotModel: "classification_snapshot_id",
            FundDefinitionModel: "fund_definition_id",
            FundSourceMappingModel: "fund_mapping_id",
        }
        if isinstance(row, ConstituentSnapshotModel):
            from .source_models import SourceRetrievalOccurrenceModel

            session.add(
                SourceRetrievalOccurrenceModel(
                    owner_id=row.owner_id,
                    constituent_snapshot_id=row.id,
                    retrieved_at=self._now(),
                    created_at=self._now(),
                )
            )
        else:
            name = names.get(type(row))
            if name is None:
                raise xray_error(XrayServiceErrorCode.VALIDATION_FAILED)
            session.add(
                EnrichmentRetrievalOccurrenceModel(
                    owner_id=row.owner_id,
                    **{name: row.id},
                    retrieved_at=self._now(),
                    created_at=self._now(),
                )
            )
        session.flush()
