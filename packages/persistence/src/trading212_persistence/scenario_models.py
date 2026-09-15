"""Immutable owner assumptions and normalized source-bound scenario publication."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .premium_models import PremiumOwned, digest_constraint, parent, scoped
from .scenario_source_models import SCENARIO_QUALITY, scenario_finite, scenario_reason
from .source_models import owner_fk
from .types import ExactNumeric, UTCDateTime


def selector_check(*, optional: bool = False, price_only: bool = False) -> CheckConstraint:
    # Exhaustive alternatives prevent stray values from changing canonical selector identity.
    columns = (
        "instrument_id",
        "entity_id",
        "taxonomy_id",
        "taxonomy_version",
        "bucket_key",
        "currency",
    )
    alternatives = []
    for kind, required in (
        ("instrument", ("instrument_id",)),
        ("entity", ("entity_id",)),
        ("sector", ("taxonomy_id", "taxonomy_version", "bucket_key")),
        ("region", ("taxonomy_id", "taxonomy_version", "bucket_key")),
        ("economic_currency", ("currency",)),
    ):
        if price_only and kind == "economic_currency":
            continue
        conditions = [f"selector_kind='{kind}'"]
        conditions.extend(
            f"{column} IS {'NOT ' if column in required else ''}NULL" for column in columns
        )
        alternatives.append("(" + " AND ".join(conditions) + ")")
    if optional:
        alternatives.append(
            "(" + " AND ".join(f"{column} IS NULL" for column in ("selector_kind", *columns)) + ")"
        )
    return CheckConstraint(" OR ".join(alternatives), name="selector_identity")


class ScenarioSelectorFields:
    selector_kind: Mapped[str | None] = mapped_column(String(20))
    instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    entity_id: Mapped[UUID | None] = mapped_column()
    taxonomy_id: Mapped[UUID | None] = mapped_column()
    taxonomy_version: Mapped[str | None] = mapped_column(String(120))
    bucket_key: Mapped[str | None] = mapped_column(String(120))
    currency: Mapped[str | None] = mapped_column(String(3))


class ScenarioDefinitionModel(PremiumOwned):
    __tablename__ = "scenario_definitions"
    __table_args__ = (
        scoped(),
        CheckConstraint("revision BETWEEN 1 AND 512", name="revision_bound"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="name_bound"),
        Index(
            "ix_scenario_definitions_owner_account_created",
            "owner_id",
            "account_id",
            "created_at",
            "id",
        ),
    )
    name: Mapped[str] = mapped_column(String(120))
    revision: Mapped[int] = mapped_column(Integer)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ScenarioVersionModel(PremiumOwned):
    __tablename__ = "scenario_definition_versions"
    __table_args__ = (
        scoped(),
        parent("definition_id", "scenario_definitions"),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "definition_id",
            "id",
            name="uq_scenario_version_definition_identity",
        ),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "id",
            "content_digest",
            name="uq_scenario_version_content_identity",
        ),
        UniqueConstraint("definition_id", "version_number"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "definition_id", "predecessor_id"],
            [
                "scenario_definition_versions.owner_id",
                "scenario_definition_versions.account_id",
                "scenario_definition_versions.definition_id",
                "scenario_definition_versions.id",
            ],
            ondelete="RESTRICT",
            name="fk_scenario_version_predecessor",
        ),
        digest_constraint("content_digest"),
        CheckConstraint(
            "version_number BETWEEN 1 AND 512 AND (version_number=1)=(predecessor_id IS NULL)",
            name="version_order",
        ),
        CheckConstraint(
            "mode IN ('first_order','compounded') AND method_version='1.0.0'", name="method_allowed"
        ),
        CheckConstraint(
            "char_length(name) BETWEEN 1 AND 120 AND char_length(description)<=1024",
            name="text_bound",
        ),
        CheckConstraint(
            "shock_count BETWEEN 0 AND 128 AND exclusion_count BETWEEN 0 AND 128",
            name="count_bound",
        ),
        Index("ix_scenario_versions_definition_number", "definition_id", "version_number", "id"),
    )
    definition_id: Mapped[UUID] = mapped_column()
    version_number: Mapped[int] = mapped_column(Integer)
    predecessor_id: Mapped[UUID | None] = mapped_column()
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(1024))
    mode: Mapped[str] = mapped_column(String(20))
    method_version: Mapped[str] = mapped_column(String(40))
    content_digest: Mapped[str] = mapped_column(String(64))
    shock_count: Mapped[int] = mapped_column(Integer)
    exclusion_count: Mapped[int] = mapped_column(Integer)
    sealed: Mapped[bool] = mapped_column(Boolean, default=False)


class ScenarioShockModel(ScenarioSelectorFields, PremiumOwned):
    """Owner shock sizes and source pins only; never provider coefficients or copies."""

    __tablename__ = "scenario_shocks"
    __table_args__ = (
        scoped(),
        parent("version_id", "scenario_definition_versions"),
        owner_fk("entity_id", "economic_entities"),
        owner_fk("taxonomy_id", "xray_taxonomies"),
        ForeignKeyConstraint(
            ["owner_id", "source_version_id", "source_version_digest"],
            [
                "scenario_sensitivity_versions.owner_id",
                "scenario_sensitivity_versions.id",
                "scenario_sensitivity_versions.content_digest",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("version_id", "rule_key"),
        CheckConstraint("rule_key ~ '^shock:[0-9a-f]{64}$'", name="rule_key_format"),
        selector_check(optional=True, price_only=True),
        scenario_finite("size"),
        CheckConstraint(
            "(kind='price' AND selector_kind IS NOT NULL AND shock_currency IS NULL AND sou"
            "rce_version_id IS NULL AND source_version_digest IS NULL AND driver_id IS NULL"
            " AND driver_definition_version_id IS NULL) OR (kind='fx' AND selector_kind IS "
            "NULL AND shock_currency IS NOT NULL AND source_version_id IS NULL AND source_v"
            "ersion_digest IS NULL AND driver_id IS NULL AND driver_definition_version_id I"
            "S NULL) OR (kind IN ('rate','factor') AND selector_kind IS NULL AND shock_curr"
            "ency IS NULL AND source_version_id IS NOT NULL AND source_version_digest IS NO"
            "T NULL AND driver_id IS NOT NULL AND driver_definition_version_id IS NOT NULL)",
            name="shock_identity",
        ),
        CheckConstraint(
            "size >= -1 AND size <= CASE WHEN kind IN ('price','fx') THEN 5 ELSE 1 END",
            name="size_bound",
        ),
        CheckConstraint(
            "shock_currency IS NULL OR shock_currency ~ '^[A-Z]{3}$'", name="currency_format"
        ),
        Index("ix_scenario_shocks_source_version", "source_version_id", "version_id"),
        Index(
            "uq_scenario_shock_driver",
            "version_id",
            "driver_id",
            unique=True,
            postgresql_where=text("driver_id IS NOT NULL"),
        ),
        UniqueConstraint(
            "version_id",
            "kind",
            "selector_kind",
            "instrument_id",
            "entity_id",
            "taxonomy_id",
            "taxonomy_version",
            "bucket_key",
            "currency",
            "shock_currency",
            "driver_id",
            name="uq_scenario_shock_selector",
            postgresql_nulls_not_distinct=True,
        ),
    )
    version_id: Mapped[UUID] = mapped_column()
    rule_key: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(10))
    size: Mapped[Decimal] = mapped_column(ExactNumeric())
    shock_currency: Mapped[str | None] = mapped_column(String(3))
    source_version_id: Mapped[UUID | None] = mapped_column()
    source_version_digest: Mapped[str | None] = mapped_column(String(64))
    driver_id: Mapped[UUID | None] = mapped_column()
    driver_definition_version_id: Mapped[UUID | None] = mapped_column()


class ScenarioExclusionModel(ScenarioSelectorFields, PremiumOwned):
    __tablename__ = "scenario_exclusions"
    __table_args__ = (
        scoped(),
        parent("version_id", "scenario_definition_versions"),
        owner_fk("entity_id", "economic_entities"),
        owner_fk("taxonomy_id", "xray_taxonomies"),
        UniqueConstraint("version_id", "rule_key"),
        CheckConstraint("rule_key ~ '^exclusion:[0-9a-f]{64}$'", name="rule_key_format"),
        selector_check(),
        CheckConstraint("currency IS NULL OR currency ~ '^[A-Z]{3}$'", name="currency_format"),
        UniqueConstraint(
            "version_id",
            "selector_kind",
            "instrument_id",
            "entity_id",
            "taxonomy_id",
            "taxonomy_version",
            "bucket_key",
            "currency",
            name="uq_scenario_exclusion_selector",
            postgresql_nulls_not_distinct=True,
        ),
    )
    selector_kind: Mapped[str] = mapped_column(String(20))
    version_id: Mapped[UUID] = mapped_column()
    rule_key: Mapped[str] = mapped_column(String(80))


class ScenarioRunModel(PremiumOwned):
    __tablename__ = "scenario_runs"
    __table_args__ = (
        scoped(),
        parent("id", "premium_runs"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "definition_version_id", "definition_digest"],
            [
                "scenario_definition_versions.owner_id",
                "scenario_definition_versions.account_id",
                "scenario_definition_versions.id",
                "scenario_definition_versions.content_digest",
            ],
            ondelete="RESTRICT",
            name="fk_scenario_run_definition_digest",
        ),
        owner_fk("xray_run_id", "xray_runs"),
        owner_fk("xray_input_id", "xray_input_snapshots"),
        owner_fk("historical_input_id", "historical_input_snapshots"),
        *[
            digest_constraint(name)
            for name in (
                "definition_digest",
                "portfolio_snapshot_digest",
                "xray_input_digest",
                "xray_result_digest",
            )
        ],
        CheckConstraint(
            "historical_input_digest IS NULL OR historical_input_digest ~ '^[0-9a-f]{64}$'",
            name="history_digest_format",
        ),
        CheckConstraint("reporting_currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint(
            "(historical_input_id IS NULL AND historical_input_digest IS NULL AND replay_st"
            "art_date IS NULL AND replay_end_date IS NULL AND market_knowledge_cutoff_at IS"
            " NULL AND holdings_basis IS NULL AND knowledge_basis IS NULL) OR (historical_i"
            "nput_id IS NOT NULL AND historical_input_digest IS NOT NULL AND replay_start_d"
            "ate IS NOT NULL AND replay_end_date IS NOT NULL AND replay_start_date < replay"
            "_end_date AND market_knowledge_cutoff_at IS NOT NULL AND holdings_basis IN ('c"
            "urrent_holdings','historical_holdings') AND knowledge_basis IN ('point_in_time"
            "','retrospective'))",
            name="replay_identity",
        ),
        CheckConstraint(
            "sensitivity_version_count BETWEEN 0 AND 128 AND sensitivity_observation_count "
            ">= 0 AND sensitivity_membership_count >= 0 AND sensitivity_evidence_count >= 0"
            " AND sensitivity_observation_count+sensitivity_membership_count+sensitivity_ev"
            "idence_count <= 100000",
            name="source_count_bound",
        ),
        CheckConstraint(
            "historical_input_id IS NULL OR (holdings_basis IS NOT NULL AND knowledge_basis"
            " IS NOT NULL)",
            name="replay_basis_present",
        ),
        Index("ix_scenario_runs_xray", "xray_run_id", "id"),
        Index("ix_scenario_runs_historical", "historical_input_id", "id"),
    )
    definition_version_id: Mapped[UUID] = mapped_column()
    definition_digest: Mapped[str] = mapped_column(String(64))
    portfolio_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT")
    )
    portfolio_snapshot_digest: Mapped[str] = mapped_column(String(64))
    xray_run_id: Mapped[UUID] = mapped_column()
    xray_input_id: Mapped[UUID] = mapped_column()
    xray_input_digest: Mapped[str] = mapped_column(String(64))
    xray_result_digest: Mapped[str] = mapped_column(String(64))
    reporting_currency: Mapped[str] = mapped_column(String(3))
    source_cutoff_at: Mapped[datetime] = mapped_column(UTCDateTime())
    historical_input_id: Mapped[UUID | None] = mapped_column()
    historical_input_digest: Mapped[str | None] = mapped_column(String(64))
    replay_start_date: Mapped[date | None] = mapped_column(Date)
    replay_end_date: Mapped[date | None] = mapped_column(Date)
    market_knowledge_cutoff_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    holdings_basis: Mapped[str | None] = mapped_column(String(20))
    knowledge_basis: Mapped[str | None] = mapped_column(String(20))
    sensitivity_version_count: Mapped[int] = mapped_column(Integer)
    sensitivity_observation_count: Mapped[int] = mapped_column(Integer)
    sensitivity_membership_count: Mapped[int] = mapped_column(Integer)
    sensitivity_evidence_count: Mapped[int] = mapped_column(Integer)
    sealed: Mapped[bool] = mapped_column(Boolean, default=False)


class ScenarioRunPayloadModel(PremiumOwned):
    """Complete typed execution envelope, physically deleted on retention."""

    __tablename__ = "scenario_run_payloads"
    __table_args__ = (
        scoped(),
        parent("run_id", "scenario_runs"),
        UniqueConstraint("run_id"),
        CheckConstraint(
            "octet_length(canonical_input) BETWEEN 1 AND 33554432", name="payload_bound"
        ),
    )
    run_id: Mapped[UUID] = mapped_column()
    canonical_input: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class ScenarioRunSensitivityVersionModel(PremiumOwned):
    __tablename__ = "scenario_run_sensitivity_versions"
    __table_args__ = (
        Index("ix_scenario_version_scan", "owner_id", "run_id", "id"),
        scoped(),
        parent("run_id", "scenario_runs"),
        ForeignKeyConstraint(
            ["owner_id", "version_id", "content_digest"],
            [
                "scenario_sensitivity_versions.owner_id",
                "scenario_sensitivity_versions.id",
                "scenario_sensitivity_versions.content_digest",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("run_id", "version_id"),
        UniqueConstraint(
            "owner_id", "account_id", "run_id", "version_id", name="uq_scenario_run_source_version"
        ),
    )
    run_id: Mapped[UUID] = mapped_column()
    version_id: Mapped[UUID] = mapped_column()
    content_digest: Mapped[str] = mapped_column(String(64))


class ScenarioRunSensitivityObservationModel(PremiumOwned):
    __tablename__ = "scenario_run_sensitivity_observations"
    __table_args__ = (
        scoped(),
        parent("run_id", "scenario_runs"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id", "version_id"],
            [
                "scenario_run_sensitivity_versions.owner_id",
                "scenario_run_sensitivity_versions.account_id",
                "scenario_run_sensitivity_versions.run_id",
                "scenario_run_sensitivity_versions.version_id",
            ],
            ondelete="RESTRICT",
            name="fk_scenario_run_observation_version",
        ),
        ForeignKeyConstraint(
            ["owner_id", "version_id", "observation_id"],
            [
                "scenario_sensitivity_observations.owner_id",
                "scenario_sensitivity_observations.version_id",
                "scenario_sensitivity_observations.id",
            ],
            ondelete="RESTRICT",
            name="fk_scenario_capture_observation_version",
        ),
        ForeignKeyConstraint(
            ["owner_id", "observation_id", "content_digest"],
            [
                "scenario_sensitivity_observations.owner_id",
                "scenario_sensitivity_observations.id",
                "scenario_sensitivity_observations.content_digest",
            ],
            ondelete="RESTRICT",
            name="fk_scenario_capture_observation_digest",
        ),
        UniqueConstraint("run_id", "observation_id"),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "run_id",
            "version_id",
            "observation_id",
            name="uq_scenario_run_source_observation",
        ),
    )
    run_id: Mapped[UUID] = mapped_column()
    version_id: Mapped[UUID] = mapped_column()
    observation_id: Mapped[UUID] = mapped_column()
    content_digest: Mapped[str] = mapped_column(String(64))


class ScenarioRunSensitivityMembershipModel(PremiumOwned):
    __tablename__ = "scenario_run_sensitivity_memberships"
    __table_args__ = (
        scoped(),
        parent("run_id", "scenario_runs"),
        owner_fk("membership_id", "scenario_sensitivity_memberships"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id", "version_id", "observation_id"],
            [
                "scenario_run_sensitivity_observations.owner_id",
                "scenario_run_sensitivity_observations.account_id",
                "scenario_run_sensitivity_observations.run_id",
                "scenario_run_sensitivity_observations.version_id",
                "scenario_run_sensitivity_observations.observation_id",
            ],
            ondelete="RESTRICT",
            name="fk_scenario_run_membership_observation",
        ),
        UniqueConstraint(
            "run_id",
            "membership_id",
            name="uq_scenario_capture_membership",
        ),
        UniqueConstraint(
            "run_id",
            "version_id",
            "observation_id",
            name="uq_scenario_capture_membership_observation",
        ),
    )
    run_id: Mapped[UUID] = mapped_column()
    version_id: Mapped[UUID] = mapped_column()
    observation_id: Mapped[UUID] = mapped_column()
    membership_id: Mapped[UUID] = mapped_column()


class ScenarioRunSensitivityEvidenceModel(PremiumOwned):
    __tablename__ = "scenario_run_sensitivity_evidence"
    __table_args__ = (
        scoped(),
        parent("run_id", "scenario_runs"),
        ForeignKeyConstraint(
            ["owner_id", "evidence_id", "content_digest"],
            [
                "scenario_sensitivity_evidence.owner_id",
                "scenario_sensitivity_evidence.id",
                "scenario_sensitivity_evidence.content_digest",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("run_id", "evidence_id"),
    )
    run_id: Mapped[UUID] = mapped_column()
    evidence_id: Mapped[UUID] = mapped_column()
    content_digest: Mapped[str] = mapped_column(String(64))


class ScenarioResultModel(PremiumOwned):
    __tablename__ = "scenario_results"
    __table_args__ = (
        scoped(),
        parent("run_id", "scenario_runs"),
        UniqueConstraint("run_id"),
        digest_constraint("content_digest"),
        CheckConstraint("octet_length(canonical_result)<=33554432", name="payload_bound"),
        CheckConstraint(
            "component_count BETWEEN 0 AND 10000 AND sensitivity_source_row_count >= 0 AND "
            "applied_use_count >= 0 AND sensitivity_source_row_count+applied_use_count <= 1"
            "00000",
            name="count_bound",
        ),
    )
    run_id: Mapped[UUID] = mapped_column()
    content_digest: Mapped[str] = mapped_column(String(64))
    canonical_result: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    component_count: Mapped[int] = mapped_column(Integer)
    sensitivity_source_row_count: Mapped[int] = mapped_column(Integer)
    applied_use_count: Mapped[int] = mapped_column(Integer)
    sealed: Mapped[bool] = mapped_column(Boolean, default=False)


class ScenarioComponentModel(PremiumOwned):
    """Queryable financial summary plus complete typed canonical component proof."""

    __tablename__ = "scenario_components"
    __table_args__ = (
        Index("ix_scenario_component_cleanup", "owner_id", "result_id", "id"),
        scoped(),
        parent("result_id", "scenario_results"),
        UniqueConstraint("result_id", "path_key"),
        CheckConstraint(
            "char_length(path_key) BETWEEN 1 AND 1024 AND char_length(root_key) BETWEEN 1 AND 1024",
            name="path_bounds",
        ),
        CheckConstraint(
            "(root_kind='position' AND position_id IS NOT NULL AND snapshot_cash_id IS NULL"
            " AND root_instrument_id IS NOT NULL) OR (root_kind='cash' AND position_id IS N"
            "ULL AND snapshot_cash_id IS NOT NULL AND root_instrument_id IS NULL)",
            name="root_identity",
        ),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "result_id",
            "id",
            name="uq_scenario_component_result_identity",
        ),
        CheckConstraint(
            "partition IN ('covered','uncovered','excluded') AND money_basis IN ('resolved'"
            ",'zero_pre_value','provably_zero_effect','unavailable')",
            name="coverage_allowed",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint(f"quality IN ({SCENARIO_QUALITY})", name="quality_allowed"),
        CheckConstraint(
            "(post_value IS NULL)=(reason IS NOT NULL) AND (post_value IS NULL)=(impact IS NULL)",
            name="monetary_availability",
        ),
        *[
            scenario_finite(name)
            for name in ("pre_value", "post_value", "impact", "rounding_residual")
        ],
        scenario_reason("reason"),
        CheckConstraint(
            "octet_length(canonical_component) BETWEEN 1 AND 33554432", name="payload_bound"
        ),
        CheckConstraint("applied_use_count BETWEEN 0 AND 128", name="use_count_bound"),
    )
    result_id: Mapped[UUID] = mapped_column()
    path_key: Mapped[str] = mapped_column(String(1024))
    root_key: Mapped[str] = mapped_column(String(1024))
    root_kind: Mapped[str] = mapped_column(String(10))
    position_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("snapshot_positions.id", ondelete="RESTRICT")
    )
    snapshot_cash_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("snapshot_cash.id", ondelete="RESTRICT")
    )
    root_instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    partition: Mapped[str] = mapped_column(String(20))
    money_basis: Mapped[str] = mapped_column(String(30))
    currency: Mapped[str] = mapped_column(String(3))
    pre_value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    post_value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    impact: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    rounding_residual: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    quality: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(60))
    applied_use_count: Mapped[int] = mapped_column(Integer)
    canonical_component: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class ScenarioAppliedSensitivityModel(PremiumOwned):
    __tablename__ = "scenario_applied_sensitivities"
    __table_args__ = (
        Index("ix_scenario_applied_cleanup", "owner_id", "result_id", "id"),
        scoped(),
        parent("result_id", "scenario_results"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "result_id", "component_id"],
            [
                "scenario_components.owner_id",
                "scenario_components.account_id",
                "scenario_components.result_id",
                "scenario_components.id",
            ],
            ondelete="RESTRICT",
            name="fk_scenario_applied_component",
        ),
        owner_fk("version_id", "scenario_sensitivity_versions"),
        owner_fk("observation_id", "scenario_sensitivity_observations"),
        UniqueConstraint("component_id", "rule_key"),
        CheckConstraint("rule_key ~ '^shock:[0-9a-f]{64}$'", name="rule_key_format"),
        CheckConstraint(
            "cardinality(candidate_observation_ids)<=100000 AND array_position(candidate_ob"
            "servation_ids,NULL) IS NULL",
            name="candidates_bound",
        ),
        *[scenario_finite(name) for name in ("coefficient", "shock_size", "effect_ratio")],
        scenario_reason("reason"),
        CheckConstraint(
            "coefficient IS NULL OR coefficient BETWEEN -100 AND 100", name="coefficient_bound"
        ),
        CheckConstraint("shock_size BETWEEN -1 AND 1", name="shock_bound"),
        CheckConstraint(
            "(reason IS NOT NULL OR (observation_id IS NOT NULL AND coefficient IS NOT NULL"
            ")) AND (effect_ratio IS NULL)=(effect_reason IS NOT NULL)",
            name="availability",
        ),
        CheckConstraint(
            "coefficient IS NULL OR observation_id IS NOT NULL",
            name="coeff_observation_required",
        ),
        scenario_reason("effect_reason"),
        CheckConstraint(f"effect_quality IN ({SCENARIO_QUALITY})", name="effect_quality_allowed"),
    )
    result_id: Mapped[UUID] = mapped_column()
    component_id: Mapped[UUID] = mapped_column()
    rule_key: Mapped[str] = mapped_column(String(80))
    version_id: Mapped[UUID] = mapped_column()
    driver_id: Mapped[UUID] = mapped_column()
    driver_definition_version_id: Mapped[UUID] = mapped_column()
    candidate_observation_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid()))
    observation_id: Mapped[UUID | None] = mapped_column()
    coefficient: Mapped[Decimal | None] = mapped_column(ExactNumeric(), deferred=True)
    shock_size: Mapped[Decimal] = mapped_column(ExactNumeric())
    effect_ratio: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    effect_reason: Mapped[str | None] = mapped_column(String(60))
    effect_quality: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(60))


SCENARIO_MODELS = (
    ScenarioDefinitionModel,
    ScenarioVersionModel,
    ScenarioShockModel,
    ScenarioExclusionModel,
    ScenarioRunModel,
    ScenarioRunPayloadModel,
    ScenarioRunSensitivityVersionModel,
    ScenarioRunSensitivityObservationModel,
    ScenarioRunSensitivityMembershipModel,
    ScenarioRunSensitivityEvidenceModel,
    ScenarioResultModel,
    ScenarioComponentModel,
    ScenarioAppliedSensitivityModel,
)
