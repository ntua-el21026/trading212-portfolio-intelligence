"""Bounded research facts, audit identities and owner-authored revisions.

Provider payloads are separate from permanent references. Financial X-ray values
are never copied into these tables: research items bind an exact retained run.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    desc,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv

from .base import Base
from .premium_models import PremiumOwned
from .source_models import SourceOwned
from .types import UTCDateTime


class ResearchCapacityModel(Base):
    __tablename__ = "research_owner_capacity"
    __table_args__ = (
        CheckConstraint(
            "retained_bytes BETWEEN 0 AND 268435456",
            name=conv("ck_research_owner_capacity_bytes_bound"),
        ),
        CheckConstraint(
            (
                "source_revisions>=0 AND event_revisions>=0 AND source_revisi"
                "ons+event_revisions<=10000"
            ),
            name=conv("ck_research_owner_capacity_revisions_bound"),
        ),
        CheckConstraint(
            "item_headers BETWEEN 0 AND 10000", name=conv("ck_research_owner_capacity_items_bound")
        ),
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"), primary_key=True
    )
    retained_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_revisions: Mapped[int] = mapped_column(Integer, nullable=False)
    event_revisions: Mapped[int] = mapped_column(Integer, nullable=False)
    item_headers: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ResearchAccountStateModel(PremiumOwned):
    __tablename__ = "research_account_states"
    __table_args__ = (
        UniqueConstraint("owner_id", "account_id", "id", name="uq_research_account_states_0"),
        UniqueConstraint("owner_id", "account_id", name="uq_research_account_states_1"),
        CheckConstraint(
            "revision BETWEEN 1 AND 9223372036854775807",
            name=conv("ck_research_account_states_revision_bound"),
        ),
    )
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ResearchSourceOriginModel(SourceOwned):
    __tablename__ = "research_source_origins"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "entity_id"],
            ["economic_entities.owner_id", "economic_entities.id"],
            ondelete="RESTRICT",
            name="fk_research_source_origins_entity_id",
        ),
        UniqueConstraint("owner_id", "id", name="uq_research_source_origins_0"),
        UniqueConstraint(
            "owner_id",
            "entity_id",
            "capability",
            "facts_digest",
            name="uq_research_source_origins_1",
        ),
        CheckConstraint(
            "capability IN ('news','company_overview')",
            name=conv("ck_research_source_origins_capability_allowed"),
        ),
        CheckConstraint(
            (
                "expires_at>original_retained_at AND expires_at<=original_ret"
                "ained_at+interval '30 days'"
            ),
            name=conv("ck_research_source_origins_expiry_order"),
        ),
        CheckConstraint(
            "facts_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_source_origins_facts_digest_format"),
        ),
    )
    entity_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    capability: Mapped[str] = mapped_column(String(30), nullable=False)
    facts_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    original_retained_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ResearchSourceModel(SourceOwned):
    __tablename__ = "research_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "provider_id"],
            ["market_data_providers.owner_id", "market_data_providers.id"],
            ondelete="RESTRICT",
            name="fk_research_sources_provider_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "entity_id"],
            ["economic_entities.owner_id", "economic_entities.id"],
            ondelete="RESTRICT",
            name="fk_research_sources_entity_id",
        ),
        UniqueConstraint("owner_id", "id", name="uq_research_sources_0"),
        CheckConstraint(
            "provider='alpha_vantage'", name=conv("ck_research_sources_provider_allowed")
        ),
        CheckConstraint(
            "capability IN ('news','company_overview')",
            name=conv("ck_research_sources_capability_allowed"),
        ),
    )
    provider_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    capability: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)


class ResearchSourceVersionModel(SourceOwned):
    __tablename__ = "research_source_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "source_id"],
            ["research_sources.owner_id", "research_sources.id"],
            ondelete="RESTRICT",
            name="fk_research_source_versions_source_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "origin_id"],
            ["research_source_origins.owner_id", "research_source_origins.id"],
            ondelete="RESTRICT",
            name="fk_research_source_versions_origin_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "provider_id"],
            ["market_data_providers.owner_id", "market_data_providers.id"],
            ondelete="RESTRICT",
            name="fk_research_source_versions_provider_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "entity_id"],
            ["economic_entities.owner_id", "economic_entities.id"],
            ondelete="RESTRICT",
            name="fk_research_source_versions_entity_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "license_version_id"],
            ["provider_license_versions.owner_id", "provider_license_versions.id"],
            ondelete="RESTRICT",
            name="fk_research_source_versions_license_version_id",
        ),
        UniqueConstraint("owner_id", "id", name="uq_research_source_versions_0"),
        CheckConstraint(
            "capability IN ('news','company_overview')",
            name=conv("ck_research_source_versions_capability_allowed"),
        ),
        CheckConstraint(
            ("retained_at<effective_expires_at AND effective_expires_at<=expires_at"),
            name=conv("ck_research_source_versions_effective_expiry"),
        ),
        CheckConstraint(
            (
                "observed_at<=first_known_at AND first_known_at<=source_cutof"
                "f_at AND source_cutoff_at<=retained_at AND retained_at<expir"
                "es_at AND expires_at<=retained_at+interval '30 days'"
            ),
            name=conv("ck_research_source_versions_time_order"),
        ),
        CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_source_versions_request_digest_format"),
        ),
        CheckConstraint(
            "facts_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_source_versions_facts_digest_format"),
        ),
        CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_source_versions_content_digest_format"),
        ),
        CheckConstraint(
            "capability_grant_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_source_versions_capability_grant_digest_format"),
        ),
        Index("ix_research_source_versions_0", "owner_id", "origin_id", "id"),
        Index("ix_research_source_versions_1", "owner_id", "effective_expires_at", "id"),
    )
    source_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    origin_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    provider_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    license_version_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    capability: Mapped[str] = mapped_column(String(30), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    facts_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    capability_grant_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    capability_grant_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    first_known_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    source_cutoff_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    retained_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    effective_expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sealed: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ResearchSourcePayloadModel(SourceOwned):
    __tablename__ = "research_source_payloads"
    __table_args__ = (
        Index("ix_research_source_payload_owner", "owner_id", "id"),
        ForeignKeyConstraint(
            ["owner_id", "version_id"],
            ["research_source_versions.owner_id", "research_source_versions.id"],
            ondelete="RESTRICT",
            name="fk_research_source_payloads_version_id",
        ),
        UniqueConstraint("owner_id", "id", name="uq_research_source_payloads_0"),
        UniqueConstraint("version_id", name="uq_research_source_payloads_1"),
        CheckConstraint(
            (
                "octet_length(canonical_source) BETWEEN 1 AND 16384 AND octet"
                "_length(canonical_facts) BETWEEN 1 AND 16384"
            ),
            name=conv("ck_research_source_payloads_payload_bound"),
        ),
        CheckConstraint(
            (
                "(kind='news' AND title IS NOT NULL AND summary IS NOT NULL A"
                "ND published_at IS NOT NULL AND company_name IS NULL AND des"
                "cription IS NULL AND publication_reason IS NULL) OR (kind='c"
                "ompany_overview' AND company_name IS NOT NULL AND descriptio"
                "n IS NOT NULL AND published_at IS NULL AND title IS NULL AND"
                " summary IS NULL AND publication_reason='provider_publicatio"
                "n_unavailable')"
            ),
            name=conv("ck_research_source_payloads_facts_shape"),
        ),
        CheckConstraint(
            (
                "char_length(publisher) BETWEEN 1 AND 4096 AND (title IS NULL"
                " OR char_length(title) BETWEEN 1 AND 4096) AND (summary IS N"
                "ULL OR char_length(summary)<=4096) AND (company_name IS NULL"
                " OR char_length(company_name) BETWEEN 1 AND 4096) AND (descr"
                "iption IS NULL OR char_length(description)<=4096)"
            ),
            name=conv("ck_research_source_payloads_text_bound"),
        ),
    )
    version_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    canonical_source: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    canonical_facts: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    publisher: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    publication_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)


class ResearchCitationModel(SourceOwned):
    __tablename__ = "research_citations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "source_version_id"],
            ["research_source_versions.owner_id", "research_source_versions.id"],
            ondelete="RESTRICT",
            name="fk_research_citations_source_version_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "entity_id"],
            ["economic_entities.owner_id", "economic_entities.id"],
            ondelete="RESTRICT",
            name="fk_research_citations_entity_id",
        ),
        UniqueConstraint("owner_id", "id", name="uq_research_citations_0"),
        UniqueConstraint("source_version_id", "provider_event_key", name="uq_research_citations_1"),
        CheckConstraint(
            "source_version_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_citations_source_version_digest_format"),
        ),
        CheckConstraint(
            "facts_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_citations_facts_digest_format"),
        ),
        CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_citations_content_digest_format"),
        ),
    )
    source_version_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    source_version_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    provider_event_key: Mapped[str] = mapped_column(String(128), nullable=False)
    facts_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)


class ResearchEventModel(PremiumOwned):
    __tablename__ = "research_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "entity_id"],
            ["economic_entities.owner_id", "economic_entities.id"],
            ondelete="RESTRICT",
            name="fk_research_events_entity_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "provider_id"],
            ["market_data_providers.owner_id", "market_data_providers.id"],
            ondelete="RESTRICT",
            name="fk_research_events_provider_id",
        ),
        UniqueConstraint("owner_id", "account_id", "id", name="uq_research_events_0"),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "provider_id",
            "provider_event_key",
            name="uq_research_events_1",
        ),
        CheckConstraint(
            "revision BETWEEN 1 AND 512", name=conv("ck_research_events_revision_bound")
        ),
        CheckConstraint(
            "kind IN ('news','company_overview')", name=conv("ck_research_events_kind_allowed")
        ),
        CheckConstraint(
            "head_digest ~ '^[0-9a-f]{64}$'", name=conv("ck_research_events_head_digest_format")
        ),
        Index("ix_research_events_0", "owner_id", "account_id", "entity_id", "id"),
    )
    entity_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    provider_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    provider_event_key: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    head_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ResearchEventRevisionModel(PremiumOwned):
    __tablename__ = "research_event_revisions"
    __table_args__ = (
        Index("ix_research_latest_visible", "owner_id", "account_id", "event_id", desc("revision")),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "event_id"],
            ["research_events.owner_id", "research_events.account_id", "research_events.id"],
            ondelete="RESTRICT",
            name="fk_research_event_revisions_event_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "previous_revision_id"],
            [
                "research_event_revisions.owner_id",
                "research_event_revisions.account_id",
                "research_event_revisions.id",
            ],
            ondelete="RESTRICT",
            name="fk_research_event_revisions_previous_revision_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "entity_id"],
            ["economic_entities.owner_id", "economic_entities.id"],
            ondelete="RESTRICT",
            name="fk_research_event_revisions_entity_id",
        ),
        UniqueConstraint("owner_id", "account_id", "id", name="uq_research_event_revisions_0"),
        UniqueConstraint("event_id", "revision", name="uq_research_event_revisions_1"),
        CheckConstraint(
            ("revision BETWEEN 1 AND 512 AND ((revision=1)=(previous_revision_id IS NULL))"),
            name=conv("ck_research_event_revisions_revision_bound"),
        ),
        CheckConstraint(
            "citation_count BETWEEN 1 AND 64",
            name=conv("ck_research_event_revisions_citation_bound"),
        ),
        CheckConstraint(
            "expires_at>created_at", name=conv("ck_research_event_revisions_expiry_order")
        ),
        CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_event_revisions_content_digest_format"),
        ),
        CheckConstraint(
            "facts_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_event_revisions_facts_digest_format"),
        ),
        CheckConstraint(
            "semantic_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_event_revisions_semantic_digest_format"),
        ),
        CheckConstraint(
            "material_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_event_revisions_material_digest_format"),
        ),
        Index("ix_research_event_revisions_0", "owner_id", "account_id", "semantic_digest", "id"),
    )
    event_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True)
    entity_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    facts_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    semantic_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    material_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    visible_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sealed: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ResearchEventPayloadModel(PremiumOwned):
    __tablename__ = "research_event_payloads"
    __table_args__ = (
        Index("ix_research_event_payload_owner", "owner_id", "id"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "revision_id"],
            [
                "research_event_revisions.owner_id",
                "research_event_revisions.account_id",
                "research_event_revisions.id",
            ],
            ondelete="RESTRICT",
            name="fk_research_event_payloads_revision_id",
        ),
        UniqueConstraint("owner_id", "account_id", "id", name="uq_research_event_payloads_0"),
        UniqueConstraint("revision_id", name="uq_research_event_payloads_1"),
        CheckConstraint(
            "octet_length(canonical_event) BETWEEN 1 AND 16384",
            name=conv("ck_research_event_payloads_payload_bound"),
        ),
    )
    revision_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    canonical_event: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class ResearchEventCitationModel(PremiumOwned):
    __tablename__ = "research_event_citations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "account_id", "revision_id"],
            [
                "research_event_revisions.owner_id",
                "research_event_revisions.account_id",
                "research_event_revisions.id",
            ],
            ondelete="RESTRICT",
            name="fk_research_event_citations_revision_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "citation_id"],
            ["research_citations.owner_id", "research_citations.id"],
            ondelete="RESTRICT",
            name="fk_research_event_citations_citation_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "source_version_id"],
            ["research_source_versions.owner_id", "research_source_versions.id"],
            ondelete="RESTRICT",
            name="fk_research_event_citations_source",
        ),
        Index(
            "ix_research_pending_event_source",
            "owner_id",
            "source_version_id",
            "copy_pending",
            "revision_id",
            "id",
        ),
        UniqueConstraint("owner_id", "account_id", "id", name="uq_research_event_citations_0"),
        UniqueConstraint("revision_id", "citation_id", name="uq_research_event_citations_1"),
        UniqueConstraint("revision_id", "ordinal", name="uq_research_event_citations_2"),
        CheckConstraint(
            "ordinal BETWEEN 0 AND 63", name=conv("ck_research_event_citations_ordinal_bound")
        ),
    )
    revision_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    citation_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    source_version_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    copy_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class ResearchAliasModel(PremiumOwned):
    __tablename__ = "research_event_aliases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "account_id", "event_id"],
            ["research_events.owner_id", "research_events.account_id", "research_events.id"],
            ondelete="RESTRICT",
            name="fk_research_event_aliases_event_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "provider_id"],
            ["market_data_providers.owner_id", "market_data_providers.id"],
            ondelete="RESTRICT",
            name="fk_research_event_aliases_provider_id",
        ),
        UniqueConstraint("owner_id", "account_id", "id", name="uq_research_event_aliases_0"),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "provider_id",
            "provider_event_key",
            name="uq_research_event_aliases_1",
        ),
    )
    event_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    provider_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    provider_event_key: Mapped[str] = mapped_column(String(128), nullable=False)


class ResearchWitnessModel(PremiumOwned):
    __tablename__ = "research_publication_witnesses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "account_id", "event_id"],
            ["research_events.owner_id", "research_events.account_id", "research_events.id"],
            ondelete="RESTRICT",
            name="fk_research_publication_witnesses_event_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "revision_id"],
            [
                "research_event_revisions.owner_id",
                "research_event_revisions.account_id",
                "research_event_revisions.id",
            ],
            ondelete="RESTRICT",
            name="fk_research_publication_witnesses_revision_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "actor_id"],
            ["principals.owner_id", "principals.id"],
            ondelete="RESTRICT",
            name="fk_research_publication_witnesses_actor_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "incoming_provider_id"],
            ["market_data_providers.owner_id", "market_data_providers.id"],
            ondelete="RESTRICT",
            name="fk_research_publication_witnesses_incoming_provider_id",
        ),
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_research_publication_witnesses_0"
        ),
        UniqueConstraint(
            "owner_id", "account_id", "incoming_digest", name="uq_research_publication_witnesses_1"
        ),
        CheckConstraint(
            (
                "incoming_revision BETWEEN 1 AND 512 AND ((incoming_revision="
                "1)=(incoming_previous_revision_id IS NULL))"
            ),
            name=conv("ck_research_publication_witnesses_incoming_order"),
        ),
        CheckConstraint(
            (
                "action IN ('new_event','exact_replay','retrieval_only','mate"
                "rial_revision','semantic_alias')"
            ),
            name=conv("ck_research_publication_witnesses_action_allowed"),
        ),
        CheckConstraint(
            "citation_count BETWEEN 1 AND 64",
            name=conv("ck_research_publication_witnesses_citation_bound"),
        ),
        CheckConstraint(
            "incoming_facts_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_publication_witnesses_incoming_facts_digest_format"),
        ),
        CheckConstraint(
            "incoming_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_publication_witnesses_incoming_digest_format"),
        ),
    )
    event_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    incoming_revision_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    incoming_event_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    incoming_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    incoming_previous_revision_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True)
    incoming_created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    incoming_provider_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    incoming_provider_event_key: Mapped[str] = mapped_column(String(128), nullable=False)
    incoming_facts_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    incoming_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    sealed: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ResearchWitnessCitationModel(PremiumOwned):
    __tablename__ = "research_witness_citations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "account_id", "witness_id"],
            [
                "research_publication_witnesses.owner_id",
                "research_publication_witnesses.account_id",
                "research_publication_witnesses.id",
            ],
            ondelete="RESTRICT",
            name="fk_research_witness_citations_witness_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "citation_id"],
            ["research_citations.owner_id", "research_citations.id"],
            ondelete="RESTRICT",
            name="fk_research_witness_citations_citation_id",
        ),
        UniqueConstraint("owner_id", "account_id", "id", name="uq_research_witness_citations_0"),
        UniqueConstraint("witness_id", "citation_id", name="uq_research_witness_citations_1"),
        UniqueConstraint("witness_id", "ordinal", name="uq_research_witness_citations_2"),
        CheckConstraint(
            "ordinal BETWEEN 0 AND 63", name=conv("ck_research_witness_citations_ordinal_bound")
        ),
    )
    witness_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    citation_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class ResearchAliasPromotionModel(PremiumOwned):
    __tablename__ = "research_alias_promotions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "account_id", "alias_id"],
            [
                "research_event_aliases.owner_id",
                "research_event_aliases.account_id",
                "research_event_aliases.id",
            ],
            ondelete="RESTRICT",
            name="fk_research_alias_promotions_alias_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "event_id"],
            ["research_events.owner_id", "research_events.account_id", "research_events.id"],
            ondelete="RESTRICT",
            name="fk_research_alias_promotions_event_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "witness_id"],
            [
                "research_publication_witnesses.owner_id",
                "research_publication_witnesses.account_id",
                "research_publication_witnesses.id",
            ],
            ondelete="RESTRICT",
            name="fk_research_alias_promotions_witness_id",
        ),
        UniqueConstraint("owner_id", "account_id", "id", name="uq_research_alias_promotions_0"),
        UniqueConstraint("alias_id", name="uq_research_alias_promotions_1"),
        UniqueConstraint("event_id", name="uq_research_alias_promotions_2"),
        UniqueConstraint("witness_id", name="uq_research_alias_promotions_3"),
    )
    alias_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    event_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    witness_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)


class ResearchItemModel(PremiumOwned):
    __tablename__ = "research_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "account_id", "revision_id"],
            [
                "research_event_revisions.owner_id",
                "research_event_revisions.account_id",
                "research_event_revisions.id",
            ],
            ondelete="RESTRICT",
            name="fk_research_items_revision_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "entity_id"],
            ["economic_entities.owner_id", "economic_entities.id"],
            ondelete="RESTRICT",
            name="fk_research_items_entity_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "xray_run_id"],
            ["xray_runs.owner_id", "xray_runs.id"],
            ondelete="RESTRICT",
            name="fk_research_items_xray_run_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "xray_input_id"],
            ["xray_input_snapshots.owner_id", "xray_input_snapshots.id"],
            ondelete="RESTRICT",
            name="fk_research_items_xray_input_id",
        ),
        ForeignKeyConstraint(
            ["snapshot_id"],
            ["portfolio_snapshots.id"],
            ondelete="RESTRICT",
            name="fk_research_items_snapshot_id",
        ),
        UniqueConstraint("owner_id", "account_id", "id", name="uq_research_items_0"),
        UniqueConstraint("owner_id", "account_id", "selection_digest", name="uq_research_items_1"),
        CheckConstraint("expires_at>created_at", name=conv("ck_research_items_expiry_order")),
        CheckConstraint(
            "revision_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_items_revision_digest_format"),
        ),
        CheckConstraint(
            "xray_input_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_items_xray_input_digest_format"),
        ),
        CheckConstraint(
            "xray_result_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_items_xray_result_digest_format"),
        ),
        CheckConstraint(
            "xray_pin_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_items_xray_pin_digest_format"),
        ),
        CheckConstraint(
            "selection_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_items_selection_digest_format"),
        ),
        Index("ix_research_items_0", "owner_id", "account_id", "expires_at", "id"),
    )
    revision_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    revision_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    xray_run_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    xray_input_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    snapshot_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    xray_input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    xray_result_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    xray_pin_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_cutoff_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    selection_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ResearchNoteModel(PremiumOwned):
    __tablename__ = "research_notes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "entity_id"],
            ["economic_entities.owner_id", "economic_entities.id"],
            ondelete="RESTRICT",
            name="fk_research_notes_entity_id",
        ),
        UniqueConstraint("owner_id", "account_id", "id", name="uq_research_notes_0"),
        CheckConstraint(
            "revision BETWEEN 1 AND 512", name=conv("ck_research_notes_revision_bound")
        ),
        CheckConstraint(
            "head_digest ~ '^[0-9a-f]{64}$'", name=conv("ck_research_notes_head_digest_format")
        ),
        Index("ix_research_notes_0", "owner_id", "account_id", "created_at", "id"),
    )
    entity_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    head_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ResearchNoteRevisionModel(PremiumOwned):
    __tablename__ = "research_note_revisions"
    __table_args__ = (
        Index(
            "ix_research_note_version_page",
            "owner_id",
            "account_id",
            "note_id",
            desc("revision"),
            desc("id"),
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "note_id"],
            ["research_notes.owner_id", "research_notes.account_id", "research_notes.id"],
            ondelete="RESTRICT",
            name="fk_research_note_revisions_note_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "previous_revision_id"],
            [
                "research_note_revisions.owner_id",
                "research_note_revisions.account_id",
                "research_note_revisions.id",
            ],
            ondelete="RESTRICT",
            name="fk_research_note_revisions_previous_revision_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "entity_id"],
            ["economic_entities.owner_id", "economic_entities.id"],
            ondelete="RESTRICT",
            name="fk_research_note_revisions_entity_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "actor_id"],
            ["principals.owner_id", "principals.id"],
            ondelete="RESTRICT",
            name="fk_research_note_revisions_actor_id",
        ),
        UniqueConstraint("owner_id", "account_id", "id", name="uq_research_note_revisions_0"),
        UniqueConstraint("note_id", "revision", name="uq_research_note_revisions_1"),
        CheckConstraint(
            ("revision BETWEEN 1 AND 512 AND ((revision=1)=(previous_revision_id IS NULL))"),
            name=conv("ck_research_note_revisions_revision_bound"),
        ),
        CheckConstraint(
            "citation_count BETWEEN 0 AND 64",
            name=conv("ck_research_note_revisions_citation_bound"),
        ),
        CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_note_revisions_content_digest_format"),
        ),
    )
    note_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True)
    entity_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sealed: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ResearchNotePayloadModel(PremiumOwned):
    __tablename__ = "research_note_payloads"
    __table_args__ = (
        Index("ix_research_note_payload_owner", "owner_id", "id"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "revision_id"],
            [
                "research_note_revisions.owner_id",
                "research_note_revisions.account_id",
                "research_note_revisions.id",
            ],
            ondelete="RESTRICT",
            name="fk_research_note_payloads_revision_id",
        ),
        UniqueConstraint("owner_id", "account_id", "id", name="uq_research_note_payloads_0"),
        UniqueConstraint("revision_id", name="uq_research_note_payloads_1"),
        CheckConstraint(
            "octet_length(canonical_note) BETWEEN 1 AND 131072",
            name=conv("ck_research_note_payloads_payload_bound"),
        ),
        CheckConstraint(
            (
                "char_length(title) BETWEEN 1 AND 4096 AND char_length(note)<"
                "=4096 AND char_length(thesis)<=4096 AND char_length(risks)<="
                "4096 AND char_length(catalysts)<=4096 AND char_length(break_"
                "conditions)<=4096"
            ),
            name=conv("ck_research_note_payloads_text_bound"),
        ),
    )
    revision_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    canonical_note: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    thesis: Mapped[str] = mapped_column(Text, nullable=False)
    risks: Mapped[str] = mapped_column(Text, nullable=False)
    catalysts: Mapped[str] = mapped_column(Text, nullable=False)
    break_conditions: Mapped[str] = mapped_column(Text, nullable=False)


class ResearchNoteCitationModel(PremiumOwned):
    __tablename__ = "research_note_citations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "account_id", "revision_id"],
            [
                "research_note_revisions.owner_id",
                "research_note_revisions.account_id",
                "research_note_revisions.id",
            ],
            ondelete="RESTRICT",
            name="fk_research_note_citations_revision_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "citation_id"],
            ["research_citations.owner_id", "research_citations.id"],
            ondelete="RESTRICT",
            name="fk_research_note_citations_citation_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "source_version_id"],
            ["research_source_versions.owner_id", "research_source_versions.id"],
            ondelete="RESTRICT",
            name="fk_research_note_citations_source_version_id",
        ),
        UniqueConstraint("owner_id", "account_id", "id", name="uq_research_note_citations_0"),
        UniqueConstraint("revision_id", "citation_id", name="uq_research_note_citations_1"),
        UniqueConstraint("revision_id", "ordinal", name="uq_research_note_citations_2"),
        CheckConstraint(
            "ordinal BETWEEN 0 AND 63", name=conv("ck_research_note_citations_ordinal_bound")
        ),
        CheckConstraint(
            "source_version_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_note_citations_source_version_digest_format"),
        ),
        CheckConstraint(
            "citation_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_note_citations_citation_digest_format"),
        ),
    )
    revision_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    citation_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    source_version_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    source_version_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    citation_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class ResearchReviewModel(PremiumOwned):
    __tablename__ = "research_review_acknowledgments"
    __table_args__ = (
        Index(
            "ix_research_revision_review",
            "owner_id",
            "account_id",
            "revision_id",
            desc("reviewed_at"),
            desc("id"),
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "event_id"],
            ["research_events.owner_id", "research_events.account_id", "research_events.id"],
            ondelete="RESTRICT",
            name="fk_research_review_acknowledgments_event_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "revision_id"],
            [
                "research_event_revisions.owner_id",
                "research_event_revisions.account_id",
                "research_event_revisions.id",
            ],
            ondelete="RESTRICT",
            name="fk_research_review_acknowledgments_revision_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "actor_id"],
            ["principals.owner_id", "principals.id"],
            ondelete="RESTRICT",
            name="fk_research_review_acknowledgments_actor_id",
        ),
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_research_review_acknowledgments_0"
        ),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "event_id",
            "revision_id",
            "actor_id",
            name="uq_research_review_acknowledgments_1",
        ),
        CheckConstraint(
            "revision_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_review_acknowledgments_revision_digest_format"),
        ),
        CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_research_review_acknowledgments_content_digest_format"),
        ),
    )
    event_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    revision_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)


class ResearchCommandModel(PremiumOwned):
    __tablename__ = "research_command_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "account_id", "command_id"],
            [
                "application_command_identities.owner_id",
                "application_command_identities.account_id",
                "application_command_identities.id",
            ],
            ondelete="RESTRICT",
            name="fk_research_command_results_command_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "note_revision_id"],
            [
                "research_note_revisions.owner_id",
                "research_note_revisions.account_id",
                "research_note_revisions.id",
            ],
            ondelete="RESTRICT",
            name="fk_research_command_results_note_revision_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "review_id"],
            [
                "research_review_acknowledgments.owner_id",
                "research_review_acknowledgments.account_id",
                "research_review_acknowledgments.id",
            ],
            ondelete="RESTRICT",
            name="fk_research_command_results_review_id",
        ),
        UniqueConstraint("owner_id", "account_id", "id", name="uq_research_command_results_0"),
        UniqueConstraint("command_id", name="uq_research_command_results_1"),
        CheckConstraint(
            "num_nonnulls(note_revision_id,review_id)=1",
            name=conv("ck_research_command_results_result_xor"),
        ),
    )
    command_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    note_revision_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True)
    review_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True)


class ResearchRetentionModel(SourceOwned):
    __tablename__ = "research_source_retention"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "source_version_id"],
            ["research_source_versions.owner_id", "research_source_versions.id"],
            ondelete="RESTRICT",
            name="fk_research_source_retention_source_version_id",
        ),
        UniqueConstraint("owner_id", "id", name="uq_research_source_retention_0"),
        UniqueConstraint("source_version_id", name="uq_research_source_retention_1"),
        CheckConstraint(
            ("reason IN ('source_expired','source_restricted','owner_erasure')"),
            name=conv("ck_research_source_retention_reason_allowed"),
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at>=created_at",
            name=conv("ck_research_source_retention_completion_order"),
        ),
        Index("ix_research_source_retention_0", "owner_id", "completed_at", "id"),
    )
    source_version_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ResearchOwnerErasureModel(Base):
    __tablename__ = "research_owner_erasure"
    __table_args__ = (
        CheckConstraint(
            "completed_at IS NULL OR completed_at>=created_at",
            name=conv("ck_research_owner_erasure_completion_order"),
        ),
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ResearchRetentionCursorModel(Base):
    """Fixed global/exact-owner raw-header watermarks; no private payload."""

    __tablename__ = "research_retention_cursor"
    __table_args__ = (
        CheckConstraint(
            "(key='research' AND scope_owner_id IS NULL) OR "
            "(scope_owner_id IS NOT NULL AND key='research:'||scope_owner_id::text)",
            name="singleton",
        ),
        CheckConstraint(
            "scope_owner_id IS NULL OR last_owner_id IS NULL OR scope_owner_id=last_owner_id",
            name="owner_scope",
        ),
        CheckConstraint("(last_owner_id IS NULL)=(last_version_id IS NULL)", name="cursor_pair"),
        ForeignKeyConstraint(
            ["last_owner_id", "last_version_id"],
            ["research_source_versions.owner_id", "research_source_versions.id"],
            ondelete="RESTRICT",
            name="fk_research_cursor_source",
        ),
    )
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    scope_owner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"), nullable=True
    )
    last_owner_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True)
    last_version_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


RESEARCH_MODELS = (
    ResearchCapacityModel,
    ResearchAccountStateModel,
    ResearchSourceOriginModel,
    ResearchSourceModel,
    ResearchSourceVersionModel,
    ResearchSourcePayloadModel,
    ResearchCitationModel,
    ResearchEventModel,
    ResearchEventRevisionModel,
    ResearchEventPayloadModel,
    ResearchEventCitationModel,
    ResearchAliasModel,
    ResearchWitnessModel,
    ResearchWitnessCitationModel,
    ResearchAliasPromotionModel,
    ResearchItemModel,
    ResearchNoteModel,
    ResearchNoteRevisionModel,
    ResearchNotePayloadModel,
    ResearchNoteCitationModel,
    ResearchReviewModel,
    ResearchCommandModel,
    ResearchRetentionModel,
    ResearchOwnerErasureModel,
    ResearchRetentionCursorModel,
)
