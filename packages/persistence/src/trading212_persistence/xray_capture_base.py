"""Bounded, nonfinancial capture helpers for retained X-ray source identities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy.orm import Session
from trading212_application.xray import XrayServiceErrorCode
from trading212_domain import xray as d
from trading212_domain.enums import QualityState
from trading212_domain.values import Instant

from .models import PortfolioSnapshotModel
from .source_store import digest
from .xray_base import xray_error


@dataclass(slots=True)
class XrayCaptureState:
    owner: UUID
    snapshot: PortfolioSnapshotModel
    cutoff: datetime
    policy: d.XrayPolicyVersion
    dependencies: dict[UUID, d.XraySourceDependency] = field(default_factory=dict)
    dependency_targets: dict[UUID, tuple[str, UUID]] = field(default_factory=dict)

    def dependency(
        self,
        kind: d.XrayDependencyKind,
        subject_kind: d.XraySubjectKind,
        subject: UUID,
        physical_kind: d.XrayReferenceKind,
        record: UUID,
        parent: UUID | None,
        *,
        target: tuple[str, UUID],
        source: Any = None,
        fingerprint: str | None = None,
    ) -> UUID:
        identifier = uuid5(
            self.snapshot.id,
            f"{kind.value}:{physical_kind.value}:{record}:{subject_kind.value}:{subject}",
        )
        value = d.XraySourceDependency(
            identifier,
            self.owner,
            self.snapshot.broker_account_id,
            self.snapshot.id,
            kind,
            subject_kind,
            subject,
            None if source is None else str(source.provider_id),
            None if source is None else source.license_version_id,
            fingerprint if fingerprint is not None else source.content_digest,
            d.XrayPhysicalReference(physical_kind, record, parent),
        )
        previous = self.dependencies.get(identifier)
        if previous is not None and previous != value:
            raise xray_error(XrayServiceErrorCode.XRAY_UNAVAILABLE)
        self.dependencies[identifier] = value
        self.dependency_targets[identifier] = target
        if len(self.dependencies) > 100_000:
            raise xray_error(XrayServiceErrorCode.RESULT_TOO_LARGE)
        return identifier

    def evidence(
        self,
        source: Any,
        identifier: UUID,
        reference: UUID,
        *,
        effective_at: datetime | None = None,
        valid_until: datetime | None = None,
        confidence: Any = None,
        gap: bool = False,
    ) -> d.XrayEvidence:
        return d.XrayEvidence(
            identifier,
            reference,
            Instant(source.effective_at if effective_at is None else effective_at),
            Instant(source.first_observed_at),
            None if valid_until is None else Instant(valid_until),
            0 if source.revision_order is None else source.revision_order,
            d.XraySourceState.GAP if gap else d.XraySourceState.AVAILABLE,
            QualityState(getattr(source, "quality", "fresh")),
            confidence,
        )


def bounded_rows(session: Session, query: Any, limit: int) -> list[Any]:
    rows = list(session.scalars(query.limit(limit + 1)))
    if len(rows) > limit:
        raise xray_error(XrayServiceErrorCode.RESULT_TOO_LARGE)
    return rows


def internal_digest(value: object) -> str:
    return digest(value)
