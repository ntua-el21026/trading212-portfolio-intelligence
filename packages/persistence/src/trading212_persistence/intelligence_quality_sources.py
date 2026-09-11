"""Closed, scalar-only physical source reads and current DISPLAY/STORE guards."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session
from trading212_application import intelligence_quality as q
from trading212_application.sources import SourceFreshnessState, SourceFreshnessView
from trading212_application.views import ViewQuality
from trading212_security.principals import AuthorizationError

from . import historical_models as hm
from . import models as m
from . import source_models as sm
from . import xray_catalog_models as xm
from .activity_revision_models import ActivityRevisionEvidenceModel
from .base import Base
from .target_models import TargetVersionModel
from .xray_lifecycle_models import EnrichmentExpiryEventModel, EnrichmentRetentionWorkModel

K = q.QualitySourceKind
R = q.QualityReason


@dataclass(frozen=True, slots=True)
class SourceSpec:
    model: type[Base]
    expiry_column: str | None = None
    enrichment: bool = False
    parent_column: str | None = None
    parent_kind: K | None = None


SPECS = {
    K.PORTFOLIO_SNAPSHOT: SourceSpec(m.PortfolioSnapshotModel),
    K.POSITION: SourceSpec(
        m.SnapshotPositionModel, parent_column="snapshot_id", parent_kind=K.PORTFOLIO_SNAPSHOT
    ),
    K.CASH: SourceSpec(
        m.SnapshotCashModel, parent_column="snapshot_id", parent_kind=K.PORTFOLIO_SNAPSHOT
    ),
    K.CALCULATION: SourceSpec(m.CalculationRunModel),
    K.INGESTION: SourceSpec(m.IngestionRunModel),
    K.BROKER_RECORD: SourceSpec(m.SourceRecordModel),
    K.BROKER_OCCURRENCE: SourceSpec(
        m.SourceRecordOccurrenceModel, parent_column="source_record_id", parent_kind=K.BROKER_RECORD
    ),
    K.RECONCILIATION: SourceSpec(m.ReconciliationRunModel),
    K.PRICE: SourceSpec(sm.PriceSnapshotModel, "price_snapshot_id"),
    K.FX: SourceSpec(sm.FxSnapshotModel, "fx_snapshot_id"),
    K.BENCHMARK: SourceSpec(sm.BenchmarkSnapshotModel, "benchmark_snapshot_id"),
    K.ACTION: SourceSpec(sm.CorporateActionSnapshotModel, "corporate_action_snapshot_id"),
    K.MAPPING: SourceSpec(sm.MarketDataInstrumentModel),
    K.CALENDAR: SourceSpec(sm.SourceCalendarModel),
    K.LICENSE: SourceSpec(sm.ProviderLicenseVersionModel),
    K.BENCHMARK_VERSION: SourceSpec(sm.BenchmarkVersionModel),
    K.TARGET: SourceSpec(TargetVersionModel),
    K.CLASSIFICATION: SourceSpec(
        hm.HistoricalClassificationModel, parent_column="evidence_id", parent_kind=K.EVIDENCE
    ),
    K.EVIDENCE: SourceSpec(hm.HistoricalEvidenceModel),
    K.REVISION: SourceSpec(ActivityRevisionEvidenceModel),
    K.ENTITY: SourceSpec(xm.EntityEvidenceVersionModel, "entity_evidence_version_id", True),
    K.XRAY_CLASSIFICATION: SourceSpec(
        xm.ClassificationSnapshotModel, "classification_snapshot_id", True
    ),
    K.FUND: SourceSpec(xm.FundDefinitionModel, "fund_definition_id", True),
    K.FUND_MAPPING: SourceSpec(xm.FundSourceMappingModel, "fund_mapping_id", True),
    K.CONSTITUENT: SourceSpec(xm.ConstituentSnapshotModel, "constituent_snapshot_id"),
    K.XRAY_POLICY: SourceSpec(xm.XrayPolicyVersionModel),
}

# Metadata allowlist deliberately excludes BYTEA, JSON, financial values, evidence
# keys, attribution prose, provider URLs and configuration credentials.
HEADER_FIELDS = frozenset(
    {
        "id",
        "owner_id",
        "broker_account_id",
        "account_id",
        "created_at",
        "provider_id",
        "license_version_id",
        "effective_at",
        "first_observed_at",
        "expires_at",
        "content_digest",
        "quality",
        "quality_state",
        "expected_count",
        "available_count",
        "observed_at",
        "source_updated_at",
        "payload_fingerprint",
        "valuation_at",
        "source_cutoff_at",
        "input_fingerprint",
        "output_fingerprint",
        "status",
        "completed_at",
        "request_fingerprint",
        "snapshot_id",
        "source_record_id",
        "evidence_id",
        "valid_from",
        "published_at",
        "sealed",
        "calculation_run_id",
        "new_source_record_id",
        "superseded_source_record_id",
        "capability",
        "as_of",
        "coverage_complete",
        "discrepancy_count",
        "version_number",
        "retention_days",
        "store_permission",
        "display_permission",
    }
)


def header(
    session: Session, spec: SourceSpec, identifier: UUID, owner: UUID, account: UUID
) -> RowMapping | None:
    table = spec.model.__table__
    query = select(*(column for column in table.c if column.name in HEADER_FIELDS)).where(
        table.c.id == identifier
    )
    if "owner_id" in table.c:
        query = query.where(table.c.owner_id == owner)
    if "broker_account_id" in table.c:
        query = query.where(table.c.broker_account_id == account)
    if "account_id" in table.c:
        query = query.where((table.c.account_id == account) | table.c.account_id.is_(None))
    return session.execute(query.with_for_update(read=True)).mappings().one_or_none()


def _instant(row: RowMapping, *names: str) -> datetime | None:
    for name in names:
        value = row.get(name)
        if isinstance(value, datetime):
            return value
    return None


def _digest(row: RowMapping) -> str | None:
    for name in (
        "content_digest",
        "payload_fingerprint",
        "output_fingerprint",
        "request_fingerprint",
    ):
        value = row.get(name)
        if (
            isinstance(value, str)
            and len(value) == 64
            and all(c in "0123456789abcdef" for c in value)
        ):
            return value
    return None


def _quality(row: RowMapping) -> ViewQuality | None:
    value = row.get("quality", row.get("quality_state"))
    try:
        return ViewQuality(value) if isinstance(value, str) else None
    except ValueError:
        return None


def source_freshness(
    *,
    now: datetime,
    reference_at: datetime | None,
    policy_version: str | None,
    max_age_seconds: int | None,
    inclusive_boundary: bool = False,
) -> SourceFreshnessView:
    if reference_at is None or policy_version is None or max_age_seconds is None:
        return SourceFreshnessView()
    age = now - reference_at
    threshold = timedelta(seconds=max_age_seconds)
    stale = age >= threshold if inclusive_boundary else age > threshold
    return SourceFreshnessView(
        state=SourceFreshnessState.STALE if stale else SourceFreshnessState.FRESH,
        reference_at=reference_at,
        policy_version=policy_version,
        max_age_seconds=max_age_seconds,
    )


class QualitySourceReader:
    def __init__(self, session: Session, owner: UUID, account: UUID, now: datetime) -> None:
        self.session, self.owner, self.account, self.now = session, owner, account, now

    def _license(
        self,
        license_id: UUID,
        provider_id: UUID | None,
        observed: datetime | None,
    ) -> tuple[UUID | None, q.QualityReason | None, datetime | None]:
        table = sm.ProviderLicenseVersionModel
        columns = (
            table.id,
            table.provider_id,
            table.effective_at,
            table.store_permission,
            table.display_permission,
            table.retention_days,
        )
        pinned = self.session.execute(
            select(*columns)
            .where(table.id == license_id, table.owner_id == self.owner)
            .with_for_update(read=True)
        ).one_or_none()
        if pinned is None or (provider_id is not None and pinned.provider_id != provider_id):
            raise AuthorizationError("access denied")
        current = self.session.execute(
            select(*columns)
            .where(
                table.owner_id == self.owner,
                table.provider_id == pinned.provider_id,
                table.effective_at <= self.now,
            )
            .order_by(table.effective_at.desc(), table.version_number.desc(), table.id.desc())
            .limit(1)
            .with_for_update(read=True)
        ).one_or_none()
        if current is None or pinned.effective_at > self.now:
            return pinned.provider_id, R.SOURCE_LICENSE_UNKNOWN, None
        expiry = None
        for row in (pinned, current):
            permissions = (row.store_permission, row.display_permission)
            if "denied" in permissions:
                return pinned.provider_id, R.SOURCE_LICENSE_DENIED, None
            if permissions != ("allowed", "allowed") or row.retention_days is None:
                return pinned.provider_id, R.SOURCE_LICENSE_UNKNOWN, None
            if observed is not None:
                candidate = observed + timedelta(days=row.retention_days)
                expiry = candidate if expiry is None else min(expiry, candidate)
        return pinned.provider_id, None, expiry

    def read(self, identity: q.QualitySourceIdentity) -> q.QualitySource:
        spec = SPECS[identity.kind]
        row = header(self.session, spec, identity.id, self.owner, self.account)
        # Never echo an unverified foreign/missing identity from a corrupted binding.
        # Invalidating the traversal preserves exact totals without silent omissions.
        if row is None:
            raise AuthorizationError("access denied")
        parent = None
        if spec.parent_column is not None:
            parent_id = row.get(spec.parent_column)
            if not isinstance(parent_id, UUID) or spec.parent_kind is None:
                raise AuthorizationError("access denied")
            if identity.parent_id != parent_id:
                raise AuthorizationError("access denied")
            parent = header(
                self.session, SPECS[spec.parent_kind], parent_id, self.owner, self.account
            )
            if parent is None:
                raise AuthorizationError("access denied")
        elif identity.parent_id is not None:
            raise AuthorizationError("access denied")

        observed = _instant(row, "first_observed_at", "observed_at", "published_at", "created_at")
        effective = _instant(
            row, "effective_at", "valuation_at", "source_updated_at", "valid_from", "as_of"
        )
        provider = cast(UUID | None, row.get("provider_id"))
        license_id = (
            identity.id
            if identity.kind is K.LICENSE
            else cast(UUID | None, row.get("license_version_id"))
        )
        expiry = _instant(row, "expires_at")
        reason = None
        if license_id is not None:
            provider, reason, license_expiry = self._license(license_id, provider, observed)
            if license_expiry is not None and identity.kind is not K.LICENSE:
                expiry = license_expiry if expiry is None else min(expiry, license_expiry)
        elif provider is not None and identity.kind is not K.MAPPING:
            reason = R.SOURCE_LICENSE_UNKNOWN
        if spec.expiry_column is not None:
            events = (
                (EnrichmentExpiryEventModel, EnrichmentRetentionWorkModel)
                if spec.enrichment
                else (
                    sm.SourceExpiryEventModel,
                    sm.SourceRetentionWorkModel,
                )
            )
            if any(
                self.session.scalar(
                    select(model.id)
                    .where(
                        model.owner_id == self.owner,
                        getattr(model, spec.expiry_column) == identity.id,
                    )
                    .limit(1)
                )
                is not None
                for model in events
            ):
                reason = R.SOURCE_PURGED
        if expiry is not None and expiry <= self.now:
            reason = R.SOURCE_EXPIRED
        if row.get("sealed") is False:
            reason = R.METADATA_UNAVAILABLE
        if identity.kind is K.INGESTION and (
            row.get("status") != "succeeded" or row.get("completed_at") is None
        ):
            reason = R.METADATA_UNAVAILABLE
        if identity.kind is K.TARGET and row.get("published_at") is None:
            reason = R.METADATA_UNAVAILABLE

        base = q.QualitySource(
            identity=identity,
            current_usability="blocked" if reason is not None else "usable",
            retention="expired"
            if reason is R.SOURCE_EXPIRED
            else "purged"
            if reason is R.SOURCE_PURGED
            else "retained",
            license_applicability="licensed" if license_id is not None else "not_applicable",
            reasons=() if reason is None else (reason,),
        )
        if reason is not None:
            return base
        freshness = SourceFreshnessView()
        if provider is not None and identity.kind is not K.MAPPING:
            policy = self.session.execute(
                select(
                    sm.MarketDataProviderModel.freshness_policy_version,
                    sm.MarketDataProviderModel.max_age_seconds,
                    sm.MarketDataProviderModel.configuration_state,
                )
                .where(
                    sm.MarketDataProviderModel.id == provider,
                    sm.MarketDataProviderModel.owner_id == self.owner,
                )
                .with_for_update(read=True)
            ).one_or_none()
            if policy is None:
                raise AuthorizationError("access denied")
            freshness = source_freshness(
                now=self.now,
                reference_at=effective,
                policy_version=policy.freshness_policy_version,
                max_age_seconds=policy.max_age_seconds,
                inclusive_boundary=True,
            )
        elif identity.kind in {K.PORTFOLIO_SNAPSHOT, K.CALCULATION, K.POSITION, K.CASH}:
            reference = parent if parent is not None else row
            freshness = source_freshness(
                now=self.now,
                reference_at=_instant(reference, "source_cutoff_at"),
                policy_version="portfolio_service._FRESHNESS_SECONDS@0d7aa9b",
                max_age_seconds=900,
            )
            if parent is not None:
                observed = _instant(parent, "created_at")
                effective = _instant(parent, "valuation_at")
        return replace(
            base,
            provider_id=provider,
            license_version_id=license_id,
            content_digest=_digest(row),
            effective_at=effective,
            first_observed_at=observed,
            expires_at=expiry,
            recorded_quality=_quality(row),
            expected_count=cast(int | None, row.get("expected_count")),
            available_count=cast(int | None, row.get("available_count")),
            freshness=freshness,
            reasons=(R.SOURCE_STALE,)
            if freshness.state is SourceFreshnessState.STALE
            else (R.FRESHNESS_POLICY_MISSING,)
            if freshness.state is SourceFreshnessState.UNAVAILABLE
            else (),
        )
