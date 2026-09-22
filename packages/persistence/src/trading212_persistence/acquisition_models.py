"""Normalized private provider authority and content-free durable attempt receipts."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .source_models import SourceOwned, owned, owner_fk
from .types import UTCDateTime

CAPABILITIES = "('daily_adjusted','etf_profile','company_overview','news_sentiment','reference_fx')"
OUTCOMES = (
    "('not_configured','access_denied','license_denied','aut"
    "hentication_failed','rate_limited','timeout','transient"
    "_failure','invalid_schema','payload_too_large','unsuppo"
    "rted','permanent_failure','attempt_fence_lost')"
)


class ProviderCapabilityScopeModel(SourceOwned):
    __tablename__ = "provider_capability_scopes"
    __table_args__ = (
        owned(),
        owner_fk("provider_id", "market_data_providers"),
        CheckConstraint(f"capability IN {CAPABILITIES}", name="capability"),
        CheckConstraint(
            (
                "(capability IN ('daily_adjusted','etf_profile') AND sub"
                "ject_kind='instrument' AND subject_id IS NOT NULL) OR ("
                "capability IN ('company_overview','news_sentiment') AND"
                " subject_kind='entity' AND subject_id IS NOT NULL) OR ("
                "capability='reference_fx' AND subject_kind='reference_f"
                "x' AND subject_id IS NULL)"
            ),
            name="subject",
        ),
        UniqueConstraint("owner_id", "provider_id", "id", name="uq_acq_scope_provider"),
        Index(
            "uq_acq_subject_scope",
            "owner_id",
            "provider_id",
            "capability",
            "subject_id",
            unique=True,
            postgresql_where=text("subject_id IS NOT NULL"),
        ),
        Index(
            "uq_acq_fx_scope",
            "owner_id",
            "provider_id",
            "capability",
            unique=True,
            postgresql_where=text("subject_id IS NULL"),
        ),
    )
    provider_id: Mapped[UUID] = mapped_column()
    capability: Mapped[str] = mapped_column(String(24))
    subject_kind: Mapped[str] = mapped_column(String(16))
    subject_id: Mapped[UUID | None] = mapped_column()


class ProviderCapabilityGrantModel(SourceOwned):
    __tablename__ = "provider_capability_grants"
    __table_args__ = (
        owned(),
        ForeignKeyConstraint(
            ["owner_id", "provider_id", "scope_id"],
            [
                "provider_capability_scopes.owner_id",
                "provider_capability_scopes.provider_id",
                "provider_capability_scopes.id",
            ],
        ),
        ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id"],
            [
                "provider_license_versions.owner_id",
                "provider_license_versions.provider_id",
                "provider_license_versions.id",
            ],
        ),
        UniqueConstraint("scope_id", "version_number"),
        CheckConstraint(
            (
                "version_number >= 1 AND expires_at > effective_at AND d"
                "aily_allowance BETWEEN 0 AND 25"
            ),
            name="bounds",
        ),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest"),
        Index(
            "ix_acq_grant_current", "owner_id", "scope_id", "effective_at", "version_number", "id"
        ),
    )
    provider_id: Mapped[UUID] = mapped_column()
    scope_id: Mapped[UUID] = mapped_column()
    version_number: Mapped[int] = mapped_column(Integer)
    license_version_id: Mapped[UUID] = mapped_column()
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    store_allowed: Mapped[bool] = mapped_column(Boolean)
    display_allowed: Mapped[bool] = mapped_column(Boolean)
    report_allowed: Mapped[bool] = mapped_column(Boolean)
    export_allowed: Mapped[bool] = mapped_column(Boolean)
    daily_allowance: Mapped[int] = mapped_column(Integer)
    evidence_key: Mapped[str] = mapped_column(String(120))
    content_digest: Mapped[str] = mapped_column(String(64))


class ProviderAcquisitionPolicyModel(SourceOwned):
    __tablename__ = "provider_acquisition_policies"
    __table_args__ = (
        owned(),
        owner_fk("provider_id", "market_data_providers"),
        UniqueConstraint("provider_id", "version_number"),
        CheckConstraint(
            (
                "version_number >= 1 AND expires_at > effective_at AND d"
                "aily_allowance BETWEEN 0 AND 25 AND (NOT enabled OR dai"
                "ly_allowance > 0)"
            ),
            name="bounds",
        ),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest"),
        Index(
            "ix_acq_policy_current",
            "owner_id",
            "provider_id",
            "effective_at",
            "version_number",
            "id",
        ),
    )
    provider_id: Mapped[UUID] = mapped_column()
    version_number: Mapped[int] = mapped_column(Integer)
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    enabled: Mapped[bool] = mapped_column(Boolean)
    daily_allowance: Mapped[int] = mapped_column(Integer)
    evidence_key: Mapped[str] = mapped_column(String(120))
    content_digest: Mapped[str] = mapped_column(String(64))


class ProviderAcquisitionMappingModel(SourceOwned):
    __tablename__ = "provider_acquisition_mappings"
    __table_args__ = (
        owned(),
        owner_fk("scope_id", "provider_capability_scopes"),
        owner_fk("market_mapping_id", "market_data_instruments"),
        owner_fk("calendar_id", "source_calendars"),
        owner_fk("source_series_id", "market_source_series"),
        UniqueConstraint("scope_id", "version_number"),
        CheckConstraint("version_number >= 1 AND expires_at > effective_at", name="bounds"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest"),
        Index(
            "ix_acq_mapping_current", "owner_id", "scope_id", "effective_at", "version_number", "id"
        ),
    )
    scope_id: Mapped[UUID] = mapped_column()
    version_number: Mapped[int] = mapped_column(Integer)
    market_mapping_id: Mapped[UUID | None] = mapped_column()
    calendar_id: Mapped[UUID | None] = mapped_column()
    source_series_id: Mapped[UUID | None] = mapped_column()
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    evidence_key: Mapped[str] = mapped_column(String(120))
    content_digest: Mapped[str] = mapped_column(String(64))


class ProviderAcquisitionRequestModel(SourceOwned):
    __tablename__ = "provider_acquisition_requests"
    __table_args__ = (
        owned(),
        owner_fk("provider_id", "market_data_providers"),
        owner_fk("mapping_version_id", "provider_acquisition_mappings"),
        owner_fk("policy_version_id", "provider_acquisition_policies"),
        owner_fk("grant_id", "provider_capability_grants"),
        ForeignKeyConstraint(
            ["owner_id", "principal_id"], ["principals.owner_id", "principals.id"]
        ),
        CheckConstraint(
            (
                "request_digest ~ '^[0-9a-f]{64}$' AND mapping_digest ~ "
                "'^[0-9a-f]{64}$' AND policy_digest ~ '^[0-9a-f]{64}$' A"
                "ND grant_digest ~ '^[0-9a-f]{64}$'"
            ),
            name="digests",
        ),
        CheckConstraint(f"capability IN {CAPABILITIES}", name="capability"),
        CheckConstraint(
            (
                "attempt_count BETWEEN 1 AND 3 AND deadline > first_star"
                "ted_at AND deadline <= first_started_at + interval '20 "
                "seconds'"
            ),
            name="deadline",
        ),
        CheckConstraint(
            (
                "state IN ('inflight','retry','succeeded','failed') AND "
                "((state='retry' AND retry_at IS NOT NULL AND retry_at <"
                " deadline) OR (state<>'retry' AND retry_at IS NULL))"
            ),
            name="state",
        ),
        Index("ix_acq_request_owner", "owner_id", "id"),
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    principal_id: Mapped[UUID] = mapped_column()
    provider_id: Mapped[UUID] = mapped_column()
    capability: Mapped[str] = mapped_column(String(24))
    mapping_version_id: Mapped[UUID] = mapped_column()
    mapping_digest: Mapped[str] = mapped_column(String(64))
    policy_version_id: Mapped[UUID] = mapped_column()
    policy_digest: Mapped[str] = mapped_column(String(64))
    grant_id: Mapped[UUID] = mapped_column()
    grant_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    first_started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    deadline: Mapped[datetime] = mapped_column(UTCDateTime())
    attempt_count: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(12))
    retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ProviderAcquisitionDayModel(SourceOwned):
    __tablename__ = "provider_acquisition_days"
    __table_args__ = (
        owned(),
        owner_fk("provider_id", "market_data_providers"),
        UniqueConstraint("owner_id", "provider_id", "utc_day", name="uq_acq_daily_provider"),
        CheckConstraint("charged_attempts BETWEEN 0 AND 25", name="charged"),
    )
    provider_id: Mapped[UUID] = mapped_column()
    utc_day: Mapped[date] = mapped_column(Date)
    charged_attempts: Mapped[int] = mapped_column(Integer)


class ProviderAcquisitionAttemptModel(SourceOwned):
    __tablename__ = "provider_acquisition_attempts"
    __table_args__ = (
        owned(),
        owner_fk("request_id", "provider_acquisition_requests"),
        owner_fk("provider_id", "market_data_providers"),
        owner_fk("day_id", "provider_acquisition_days"),
        UniqueConstraint("request_id", "ordinal"),
        CheckConstraint(
            (
                "ordinal BETWEEN 1 AND 3 AND reserved_at < lease_expires"
                "_at AND lease_expires_at <= deadline AND deadline <= fi"
                "rst_started_at + interval '20 seconds' AND reserved_at "
                ">= first_started_at"
            ),
            name="times",
        ),
        CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name="digest"),
        CheckConstraint(f"outcome IS NULL OR outcome IN {OUTCOMES}", name="outcome"),
        CheckConstraint(
            (
                "(finished_at IS NULL AND outcome IS NULL AND retry_at I"
                "S NULL) OR (finished_at >= reserved_at AND (retry_at IS"
                " NULL OR (outcome IN ('rate_limited','timeout','transie"
                "nt_failure') AND ordinal < 3 AND retry_at >= finished_a"
                "t + ordinal * interval '1 second' AND retry_at <= finis"
                "hed_at + interval '60 seconds' AND retry_at < deadline)"
                "))"
            ),
            name="finish",
        ),
        Index("ix_acq_attempt_day", "owner_id", "day_id", "id"),
    )
    request_id: Mapped[UUID] = mapped_column()
    provider_id: Mapped[UUID] = mapped_column()
    day_id: Mapped[UUID] = mapped_column()
    request_digest: Mapped[str] = mapped_column(String(64))
    ordinal: Mapped[int] = mapped_column(Integer)
    first_started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    reserved_at: Mapped[datetime] = mapped_column(UTCDateTime())
    deadline: Mapped[datetime] = mapped_column(UTCDateTime())
    lease_expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    outcome: Mapped[str | None] = mapped_column(String(32))
    retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ProviderAcquisitionSlotModel(SourceOwned):
    __tablename__ = "provider_acquisition_slots"
    __table_args__ = (
        owned(),
        owner_fk("provider_id", "market_data_providers"),
        owner_fk("attempt_id", "provider_acquisition_attempts"),
        UniqueConstraint("owner_id", "provider_id", name="uq_acq_active_provider_slot"),
        UniqueConstraint("attempt_id"),
    )
    provider_id: Mapped[UUID] = mapped_column()
    attempt_id: Mapped[UUID | None] = mapped_column()


class ProviderAcquisitionPublicationModel(SourceOwned):
    __tablename__ = "provider_acquisition_publications"
    __table_args__ = (
        owned(),
        owner_fk("attempt_id", "provider_acquisition_attempts"),
        UniqueConstraint("attempt_id", "source_kind", "source_id"),
        UniqueConstraint("owner_id", "source_kind", "source_id", name="uq_acq_original_source"),
        CheckConstraint(
            (
                "source_kind IN ('price','fx','research') AND content_di"
                "gest ~ '^[0-9a-f]{64}$' AND acquisition_digest ~ '^[0-9"
                "a-f]{64}$'"
            ),
            name="identity",
        ),
        CheckConstraint(
            (
                "first_known_at=acquired_at AND published_at >= acquired"
                "_at AND expires_at > published_at AND expires_at <= acq"
                "uired_at + interval '30 days'"
            ),
            name="original_clock",
        ),
    )
    attempt_id: Mapped[UUID] = mapped_column()
    source_kind: Mapped[str] = mapped_column(String(12))
    source_id: Mapped[UUID] = mapped_column()
    content_digest: Mapped[str] = mapped_column(String(64))
    acquisition_digest: Mapped[str] = mapped_column(String(64))
    acquired_at: Mapped[datetime] = mapped_column(UTCDateTime())
    first_known_at: Mapped[datetime] = mapped_column(UTCDateTime())
    published_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ProviderAcquisitionMarketResultModel(SourceOwned):
    """An attempt result points to the unchanged original source publication."""

    __tablename__ = "provider_acquisition_market_results"
    __table_args__ = (
        owned(),
        owner_fk("attempt_id", "provider_acquisition_attempts"),
        owner_fk("publication_id", "provider_acquisition_publications"),
        UniqueConstraint("attempt_id"),
    )
    attempt_id: Mapped[UUID] = mapped_column()
    publication_id: Mapped[UUID] = mapped_column()
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime())


ACQUISITION_MODELS = (
    ProviderCapabilityScopeModel,
    ProviderCapabilityGrantModel,
    ProviderAcquisitionPolicyModel,
    ProviderAcquisitionMappingModel,
    ProviderAcquisitionRequestModel,
    ProviderAcquisitionDayModel,
    ProviderAcquisitionAttemptModel,
    ProviderAcquisitionSlotModel,
    ProviderAcquisitionPublicationModel,
    ProviderAcquisitionMarketResultModel,
)
