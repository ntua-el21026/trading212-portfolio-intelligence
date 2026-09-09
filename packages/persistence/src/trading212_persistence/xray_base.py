"""Shared owner/license transaction boundary for X-ray commands and reads."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from trading212_application.sources import SourceServiceError
from trading212_application.sources import SourceServiceErrorCode as SourceCode
from trading212_application.xray import XrayServiceError, XrayServiceErrorCode
from trading212_domain.sources import SourceUse
from trading212_security.principals import Principal

from .source_store import SourceStore


def xray_error(code: XrayServiceErrorCode) -> XrayServiceError:
    return XrayServiceError(
        code,
        {
            XrayServiceErrorCode.NOT_FOUND: "The requested X-ray resource was not found.",
            XrayServiceErrorCode.ACCESS_DENIED: "Source use is not permitted.",
            XrayServiceErrorCode.IDEMPOTENCY_KEY_REUSED: "Idempotency request mismatch.",
            XrayServiceErrorCode.SOURCE_REVISION_CONFLICT: "Source revision conflict.",
            XrayServiceErrorCode.INPUT_SNAPSHOT_MISMATCH: (
                "The retained input does not match the request."
            ),
            XrayServiceErrorCode.RESULT_TOO_LARGE: "The X-ray request exceeds a retained bound.",
            XrayServiceErrorCode.VALIDATION_FAILED: "The X-ray request is invalid.",
            XrayServiceErrorCode.XRAY_UNAVAILABLE: "The X-ray request cannot be completed.",
        }[code],
    )


class XrayStore(SourceStore):
    """Reuse SourceStore constructor, scope/owner checks and pinned/current licenses."""

    def _permit_xray_storage_licenses(
        self,
        session: Session,
        owner: UUID,
        license_ids: Iterable[UUID],
        *,
        expires_at: datetime | None,
    ) -> None:
        """Recheck current permissions at a new-copy boundary under the owner locks."""
        if expires_at is not None and expires_at <= self._now():
            raise xray_error(XrayServiceErrorCode.ACCESS_DENIED)
        for identifier in sorted(set(license_ids), key=str):
            self._permit(session, owner, identifier, SourceUse.DISPLAY)
            self._permit(session, owner, identifier, SourceUse.STORE)

    def _xray_storage_expires_at(
        self, session: Session, owner: UUID, input_id: UUID
    ) -> datetime | None:
        """Freeze the earliest actual dependency deadline, without loading payloads."""
        from .source_models import FxSnapshotModel
        from .xray_catalog_models import (
            ClassificationSnapshotModel,
            ConstituentSnapshotModel,
            EntityEvidenceVersionModel,
            FundDefinitionModel,
            FundSourceMappingModel,
        )
        from .xray_run_models import XrayInputDependencyModel

        dependency = XrayInputDependencyModel
        deadlines: list[datetime] = []
        for model, column in (
            (FxSnapshotModel, "fx_snapshot_id"),
            (ConstituentSnapshotModel, "constituent_snapshot_id"),
            (ClassificationSnapshotModel, "classification_snapshot_id"),
            (EntityEvidenceVersionModel, "entity_evidence_version_id"),
            (FundDefinitionModel, "fund_definition_id"),
            (FundSourceMappingModel, "fund_mapping_id"),
        ):
            deadline = session.scalar(
                select(func.min(model.expires_at))
                .join(dependency, getattr(dependency, column) == model.id)
                .where(
                    model.owner_id == owner,
                    dependency.owner_id == owner,
                    dependency.input_id == input_id,
                )
            )
            if deadline is not None:
                deadlines.append(deadline)
        return min(deadlines) if deadlines else None

    async def _xrun[T](
        self,
        principal: Principal,
        operation: Callable[[Session, UUID], T],
        *,
        write: bool = False,
    ) -> T:
        def locked(session: Session, owner: UUID) -> T:
            # SourceStore already holds sources:{owner}; collection capacity is acquired last.
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"xray:{owner}"},
            )
            return operation(session, owner)

        try:
            return await self._run(principal, locked, write=write)
        except SourceServiceError as exc:
            codes = {
                SourceCode.NOT_FOUND: XrayServiceErrorCode.NOT_FOUND,
                SourceCode.ACCESS_DENIED: XrayServiceErrorCode.ACCESS_DENIED,
                SourceCode.IDEMPOTENCY_KEY_REUSED: XrayServiceErrorCode.IDEMPOTENCY_KEY_REUSED,
                SourceCode.SOURCE_REVISION_CONFLICT: XrayServiceErrorCode.SOURCE_REVISION_CONFLICT,
                SourceCode.RESULT_TOO_LARGE: XrayServiceErrorCode.RESULT_TOO_LARGE,
                SourceCode.VALIDATION_FAILED: XrayServiceErrorCode.VALIDATION_FAILED,
            }
            raise xray_error(codes.get(exc.code, XrayServiceErrorCode.XRAY_UNAVAILABLE)) from None
