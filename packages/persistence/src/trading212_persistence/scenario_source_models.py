"""Owned sensitivity identities with separately purgeable licensed financial payloads."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .premium_models import digest_constraint
from .source_models import SourceOwned, owned, owner_fk
from .types import ExactNumeric, UTCDateTime

SCENARIO_QUALITY = "'fresh','stale','partial','estimated','unreconciled','failed'"
SCENARIO_REASONS = (
    "'missing_value','missing_identity','ambiguous_identity','missing_classification',"
    "'ambiguous_classification','incompatible_taxonomy','missing_economic_currency',"
    "'unsupported_economic_currency','uncertain_exclusion','uncertain_price_priority',"
    "'missing_sensitivity','ambiguous_sensitivity','unsupported_sensitivity',"
    "'incompatible_sensitivity_currency','unknown_driver_equivalence','missing_replay_mapping',"
    "'missing_replay_source','fx_decomposition_unavailable','historical_holdings_unavailable',"
    "'incompatible_basis','uncertain_money','zero_denominator'"
)


def scenario_finite(column: str) -> CheckConstraint:
    return CheckConstraint(
        f"{column} IS NULL OR ({column} > '-Infinity'::numeric AND {column} < 'Infinity'::numeric)",
        name=f"{column}_finite",
    )


def scenario_reason(column: str) -> CheckConstraint:
    return CheckConstraint(
        f"{column} IS NULL OR {column} IN ({SCENARIO_REASONS})", name=f"{column}_allowed"
    )


def source_license() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["owner_id", "provider_id", "license_version_id"],
        [
            "provider_license_versions.owner_id",
            "provider_license_versions.provider_id",
            "provider_license_versions.id",
        ],
        ondelete="RESTRICT",
    )


def source_times() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint("valid_until IS NULL OR valid_until > valid_from", name="validity_order"),
        CheckConstraint("revision >= 1", name="revision_positive"),
    )


class ScenarioSensitivitySetModel(SourceOwned):
    __tablename__ = "scenario_sensitivity_sets"
    __table_args__ = (
        owned(),
        owner_fk("provider_id", "market_data_providers"),
        UniqueConstraint(
            "owner_id",
            "provider_id",
            "id",
            name="uq_scenario_sensitivity_set_provider",
        ),
    )
    provider_id: Mapped[UUID] = mapped_column()


class ScenarioSensitivityVersionModel(SourceOwned):
    """Permanent opaque identity; definitions reference this header after source expiry."""

    __tablename__ = "scenario_sensitivity_versions"
    __table_args__ = (
        owned(),
        source_license(),
        ForeignKeyConstraint(
            ["owner_id", "provider_id", "source_set_id"],
            [
                "scenario_sensitivity_sets.owner_id",
                "scenario_sensitivity_sets.provider_id",
                "scenario_sensitivity_sets.id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("source_set_id", "revision"),
        UniqueConstraint(
            "owner_id",
            "id",
            "content_digest",
            name="uq_scenario_sensitivity_version_digest",
        ),
        digest_constraint("content_digest"),
        CheckConstraint("driver_definition_digest ~ '^[0-9a-f]{64}$'", name="driver_digest_format"),
        CheckConstraint("revision >= 1 AND expires_at > created_at", name="identity_bounds"),
        CheckConstraint(
            "observation_count >= 0 AND membership_count >= 0 AND evidence_count >= 0 AND o"
            "bservation_count + membership_count + evidence_count <= 100000",
            name="source_count_bound",
        ),
        Index("ix_scenario_sensitivity_expiry", "expires_at", "id"),
    )
    source_set_id: Mapped[UUID] = mapped_column()
    provider_id: Mapped[UUID] = mapped_column()
    license_version_id: Mapped[UUID] = mapped_column()
    content_digest: Mapped[str] = mapped_column(String(64))
    driver_id: Mapped[UUID] = mapped_column()
    driver_definition_version_id: Mapped[UUID] = mapped_column()
    driver_definition_digest: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer)
    observation_count: Mapped[int] = mapped_column(Integer)
    membership_count: Mapped[int] = mapped_column(Integer)
    evidence_count: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    sealed: Mapped[bool] = mapped_column(Boolean, default=False)


class ScenarioSensitivityVersionPayloadModel(SourceOwned):
    __tablename__ = "scenario_sensitivity_version_payloads"
    __table_args__ = (
        owned(),
        owner_fk("version_id", "scenario_sensitivity_versions"),
        UniqueConstraint("version_id"),
        owner_fk("equivalence_entity_id", "economic_entities"),
        owner_fk("equivalence_taxonomy_id", "xray_taxonomies"),
        *source_times(),
        CheckConstraint(
            "driver_kind IN ('rate','factor') AND shock_unit = CASE driver_kind WHEN 'rate'"
            " THEN 'absolute_rate_change' ELSE 'simple_factor_return' END",
            name="driver_units",
        ),
        CheckConstraint(
            "(equivalence_kind='rate' AND equivalence_rate_id IS NOT NULL AND equivalence_f"
            "actor_id IS NULL AND equivalence_currency IS NOT NULL AND equivalence_selector"
            "_kind IS NULL AND equivalence_instrument_id IS NULL AND equivalence_entity_id "
            "IS NULL AND equivalence_taxonomy_id IS NULL AND equivalence_taxonomy_version I"
            "S NULL AND equivalence_bucket_key IS NULL AND equivalence_reason IS NULL) OR ("
            "equivalence_kind='factor' AND equivalence_rate_id IS NULL AND equivalence_fact"
            "or_id IS NOT NULL AND equivalence_currency IS NULL AND equivalence_selector_ki"
            "nd IS NULL AND equivalence_instrument_id IS NULL AND equivalence_entity_id IS "
            "NULL AND equivalence_taxonomy_id IS NULL AND equivalence_taxonomy_version IS N"
            "ULL AND equivalence_bucket_key IS NULL AND equivalence_reason IS NULL) OR (equ"
            "ivalence_kind='fx' AND equivalence_rate_id IS NULL AND equivalence_factor_id I"
            "S NULL AND equivalence_currency IS NOT NULL AND equivalence_selector_kind IS N"
            "ULL AND equivalence_instrument_id IS NULL AND equivalence_entity_id IS NULL AN"
            "D equivalence_taxonomy_id IS NULL AND equivalence_taxonomy_version IS NULL AND"
            " equivalence_bucket_key IS NULL AND equivalence_reason IS NULL) OR (equivalenc"
            "e_kind='unknown' AND equivalence_rate_id IS NULL AND equivalence_factor_id IS "
            "NULL AND equivalence_currency IS NULL AND equivalence_selector_kind IS NULL AN"
            "D equivalence_instrument_id IS NULL AND equivalence_entity_id IS NULL AND equi"
            "valence_taxonomy_id IS NULL AND equivalence_taxonomy_version IS NULL AND equiv"
            "alence_bucket_key IS NULL AND equivalence_reason IS NOT NULL) OR (equivalence_"
            "kind='price' AND equivalence_rate_id IS NULL AND equivalence_factor_id IS NULL"
            " AND equivalence_currency IS NULL AND equivalence_selector_kind IS NOT NULL AN"
            "D equivalence_instrument_id IS NOT NULL AND equivalence_entity_id IS NULL AND "
            "equivalence_taxonomy_id IS NULL AND equivalence_taxonomy_version IS NULL AND e"
            "quivalence_bucket_key IS NULL AND equivalence_reason IS NULL AND equivalence_s"
            "elector_kind='instrument') OR (equivalence_kind='price' AND equivalence_rate_i"
            "d IS NULL AND equivalence_factor_id IS NULL AND equivalence_currency IS NULL A"
            "ND equivalence_selector_kind IS NOT NULL AND equivalence_instrument_id IS NULL"
            " AND equivalence_entity_id IS NOT NULL AND equivalence_taxonomy_id IS NULL AND"
            " equivalence_taxonomy_version IS NULL AND equivalence_bucket_key IS NULL AND e"
            "quivalence_reason IS NULL AND equivalence_selector_kind='entity') OR (equivale"
            "nce_kind='price' AND equivalence_rate_id IS NULL AND equivalence_factor_id IS "
            "NULL AND equivalence_currency IS NULL AND equivalence_selector_kind IS NOT NUL"
            "L AND equivalence_instrument_id IS NULL AND equivalence_entity_id IS NULL AND "
            "equivalence_taxonomy_id IS NOT NULL AND equivalence_taxonomy_version IS NOT NU"
            "LL AND equivalence_bucket_key IS NOT NULL AND equivalence_reason IS NULL AND e"
            "quivalence_selector_kind='sector') OR (equivalence_kind='price' AND equivalenc"
            "e_rate_id IS NULL AND equivalence_factor_id IS NULL AND equivalence_currency I"
            "S NULL AND equivalence_selector_kind IS NOT NULL AND equivalence_instrument_id"
            " IS NULL AND equivalence_entity_id IS NULL AND equivalence_taxonomy_id IS NOT "
            "NULL AND equivalence_taxonomy_version IS NOT NULL AND equivalence_bucket_key I"
            "S NOT NULL AND equivalence_reason IS NULL AND equivalence_selector_kind='regio"
            "n')",
            name="equivalence_identity",
        ),
        CheckConstraint(
            f"equivalence_reason IS NULL OR equivalence_reason IN ({SCENARIO_REASONS})",
            name="eq_reason_allowed",
        ),
        CheckConstraint(
            "equivalence_currency IS NULL OR equivalence_currency ~ '^[A-Z]{3}$'",
            name="eq_currency_format",
        ),
        CheckConstraint(
            "availability IN ('available','partial','unavailable','failed')",
            name="availability_allowed",
        ),
        CheckConstraint(f"quality IN ({SCENARIO_QUALITY})", name="quality_allowed"),
        CheckConstraint(
            "char_length(adapter_id) BETWEEN 1 AND 120 AND char_length(adapter_version) BET"
            "WEEN 1 AND 120",
            name="adapter_bounds",
        ),
        CheckConstraint(
            "octet_length(canonical_payload) BETWEEN 1 AND 33554432", name="payload_bound"
        ),
    )
    version_id: Mapped[UUID] = mapped_column()
    driver_kind: Mapped[str] = mapped_column(String(10))
    shock_unit: Mapped[str] = mapped_column(String(30))
    equivalence_kind: Mapped[str] = mapped_column(String(10))
    equivalence_rate_id: Mapped[UUID | None] = mapped_column()
    equivalence_factor_id: Mapped[UUID | None] = mapped_column()
    equivalence_currency: Mapped[str | None] = mapped_column(String(3))
    equivalence_selector_kind: Mapped[str | None] = mapped_column(String(20))
    equivalence_instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    equivalence_entity_id: Mapped[UUID | None] = mapped_column()
    equivalence_taxonomy_id: Mapped[UUID | None] = mapped_column()
    equivalence_taxonomy_version: Mapped[str | None] = mapped_column(String(120))
    equivalence_bucket_key: Mapped[str | None] = mapped_column(String(120))
    equivalence_reason: Mapped[str | None] = mapped_column(String(60))
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    first_known_at: Mapped[datetime] = mapped_column(UTCDateTime())
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime())
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revision: Mapped[int] = mapped_column(Integer)
    adapter_id: Mapped[str] = mapped_column(String(120))
    adapter_version: Mapped[str] = mapped_column(String(120))
    availability: Mapped[str] = mapped_column(String(20))
    quality: Mapped[str] = mapped_column(String(20))
    canonical_payload: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class ScenarioSensitivityObservationModel(SourceOwned):
    __tablename__ = "scenario_sensitivity_observations"
    __table_args__ = (
        owned(),
        source_license(),
        owner_fk("version_id", "scenario_sensitivity_versions"),
        UniqueConstraint(
            "owner_id",
            "version_id",
            "id",
            name="uq_scenario_sensitivity_observation_version",
        ),
        UniqueConstraint(
            "owner_id",
            "id",
            "content_digest",
            name="uq_scenario_sensitivity_observation_digest",
        ),
        digest_constraint("content_digest"),
        Index("ix_scenario_observations_version", "version_id", "id"),
    )
    version_id: Mapped[UUID] = mapped_column()
    provider_id: Mapped[UUID] = mapped_column()
    license_version_id: Mapped[UUID] = mapped_column()
    content_digest: Mapped[str] = mapped_column(String(64))
    driver_id: Mapped[UUID] = mapped_column()
    driver_definition_version_id: Mapped[UUID] = mapped_column()


class ScenarioSensitivityObservationPayloadModel(SourceOwned):
    __tablename__ = "scenario_sensitivity_observation_payloads"
    __table_args__ = (
        owned(),
        owner_fk("observation_id", "scenario_sensitivity_observations"),
        owner_fk("entity_id", "economic_entities"),
        UniqueConstraint("observation_id"),
        *source_times(),
        CheckConstraint(
            "(subject_kind='instrument' AND instrument_id IS NOT NULL AND entity_id IS NULL"
            ") OR (subject_kind='entity' AND entity_id IS NOT NULL AND instrument_id IS NUL"
            "L)",
            name="subject_identity",
        ),
        CheckConstraint(
            "state IN ('available','missing','unsupported','disputed')", name="state_allowed"
        ),
        CheckConstraint(
            "(state='available') = (coefficient IS NOT NULL) AND (coefficient IS NULL) = (r"
            "eason IS NOT NULL) AND (state<>'available' OR (response_basis='local_economic_"
            "value' AND response_currency IS NOT NULL))",
            name="coeff_availability",
        ),
        scenario_finite("coefficient"),
        scenario_finite("confidence"),
        scenario_reason("reason"),
        CheckConstraint(
            "coefficient IS NULL OR coefficient BETWEEN -100 AND 100", name="coefficient_bound"
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_bound"
        ),
        CheckConstraint(
            "shock_unit IN ('absolute_rate_change','simple_factor_return') AND response_uni"
            "t='local_value_simple_return'",
            name="units_allowed",
        ),
        CheckConstraint(
            "response_basis IN ('local_economic_value','fx_inclusive','unknown') AND (respo"
            "nse_currency IS NULL OR response_currency ~ '^[A-Z]{3}$')",
            name="response_basis",
        ),
        CheckConstraint(f"quality IN ({SCENARIO_QUALITY})", name="quality_allowed"),
        CheckConstraint(
            "octet_length(canonical_payload) BETWEEN 1 AND 33554432", name="payload_bound"
        ),
    )
    observation_id: Mapped[UUID] = mapped_column()
    subject_kind: Mapped[str] = mapped_column(String(12))
    instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    entity_id: Mapped[UUID | None] = mapped_column()
    coefficient: Mapped[Decimal | None] = mapped_column(ExactNumeric(), deferred=True)
    shock_unit: Mapped[str] = mapped_column(String(30))
    response_unit: Mapped[str] = mapped_column(String(30))
    response_basis: Mapped[str] = mapped_column(String(30))
    response_currency: Mapped[str | None] = mapped_column(String(3))
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    first_known_at: Mapped[datetime] = mapped_column(UTCDateTime())
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime())
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20))
    quality: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    reason: Mapped[str | None] = mapped_column(String(60))
    canonical_payload: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class ScenarioSensitivityMembershipModel(SourceOwned):
    __tablename__ = "scenario_sensitivity_memberships"
    __table_args__ = (
        owned(),
        ForeignKeyConstraint(
            ["owner_id", "version_id", "version_digest"],
            [
                "scenario_sensitivity_versions.owner_id",
                "scenario_sensitivity_versions.id",
                "scenario_sensitivity_versions.content_digest",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "version_id", "observation_id"],
            [
                "scenario_sensitivity_observations.owner_id",
                "scenario_sensitivity_observations.version_id",
                "scenario_sensitivity_observations.id",
            ],
            ondelete="RESTRICT",
            name="fk_scenario_membership_observation_version",
        ),
        ForeignKeyConstraint(
            ["owner_id", "observation_id", "observation_digest"],
            [
                "scenario_sensitivity_observations.owner_id",
                "scenario_sensitivity_observations.id",
                "scenario_sensitivity_observations.content_digest",
            ],
            ondelete="RESTRICT",
            name="fk_scenario_membership_observation_digest",
        ),
        UniqueConstraint("version_id", "observation_id"),
    )
    version_id: Mapped[UUID] = mapped_column()
    version_digest: Mapped[str] = mapped_column(String(64))
    observation_id: Mapped[UUID] = mapped_column()
    observation_digest: Mapped[str] = mapped_column(String(64))


class ScenarioSensitivityEvidenceModel(SourceOwned):
    """source_record_id is an opaque fixed-adapter identity, not a broker raw-record FK."""

    __tablename__ = "scenario_sensitivity_evidence"
    __table_args__ = (
        owned(),
        source_license(),
        digest_constraint("content_digest"),
        UniqueConstraint(
            "owner_id",
            "id",
            "content_digest",
            name="uq_scenario_sensitivity_evidence_digest",
        ),
    )
    provider_id: Mapped[UUID] = mapped_column()
    license_version_id: Mapped[UUID] = mapped_column()
    source_record_id: Mapped[UUID] = mapped_column()
    content_digest: Mapped[str] = mapped_column(String(64))


class ScenarioSensitivityEvidencePayloadModel(SourceOwned):
    __tablename__ = "scenario_sensitivity_evidence_payloads"
    __table_args__ = (
        owned(),
        owner_fk("evidence_id", "scenario_sensitivity_evidence"),
        UniqueConstraint("evidence_id"),
        CheckConstraint(
            "transformation IN ('identity_local_simple_return_v1','unsupported')",
            name="transform_allowed",
        ),
        CheckConstraint(
            "char_length(adapter_id) BETWEEN 1 AND 120 AND char_length(adapter_version) BET"
            "WEEN 1 AND 120",
            name="adapter_bounds",
        ),
        CheckConstraint(
            "octet_length(canonical_payload) BETWEEN 1 AND 33554432", name="payload_bound"
        ),
    )
    evidence_id: Mapped[UUID] = mapped_column()
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    first_known_at: Mapped[datetime] = mapped_column(UTCDateTime())
    adapter_id: Mapped[str] = mapped_column(String(120))
    adapter_version: Mapped[str] = mapped_column(String(120))
    transformation: Mapped[str] = mapped_column(String(40))
    canonical_payload: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class ScenarioSensitivityEvidenceLinkModel(SourceOwned):
    __tablename__ = "scenario_sensitivity_evidence_links"
    __table_args__ = (
        owned(),
        owner_fk("version_id", "scenario_sensitivity_versions"),
        owner_fk("evidence_id", "scenario_sensitivity_evidence"),
        ForeignKeyConstraint(
            ["owner_id", "version_id", "observation_id"],
            [
                "scenario_sensitivity_observations.owner_id",
                "scenario_sensitivity_observations.version_id",
                "scenario_sensitivity_observations.id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "version_id", "observation_id", "evidence_id", postgresql_nulls_not_distinct=True
        ),
        Index("ix_scenario_evidence_links_evidence", "evidence_id", "version_id"),
    )
    version_id: Mapped[UUID] = mapped_column()
    observation_id: Mapped[UUID | None] = mapped_column()
    evidence_id: Mapped[UUID] = mapped_column()


class ScenarioSensitivityRetentionModel(SourceOwned):
    __tablename__ = "scenario_sensitivity_retention"
    __table_args__ = (
        owned(),
        owner_fk("version_id", "scenario_sensitivity_versions"),
        UniqueConstraint("version_id"),
        CheckConstraint(
            "reason IN ('source_restricted','source_expired','owner_erasure')",
            name="reason_allowed",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at", name="completion_order"
        ),
        Index("ix_scenario_sensitivity_retention_pending", "completed_at", "owner_id", "id"),
    )
    version_id: Mapped[UUID] = mapped_column()
    reason: Mapped[str] = mapped_column(String(30))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


SCENARIO_SOURCE_MODELS = (
    ScenarioSensitivitySetModel,
    ScenarioSensitivityVersionModel,
    ScenarioSensitivityVersionPayloadModel,
    ScenarioSensitivityObservationModel,
    ScenarioSensitivityObservationPayloadModel,
    ScenarioSensitivityMembershipModel,
    ScenarioSensitivityEvidenceModel,
    ScenarioSensitivityEvidencePayloadModel,
    ScenarioSensitivityEvidenceLinkModel,
    ScenarioSensitivityRetentionModel,
)
