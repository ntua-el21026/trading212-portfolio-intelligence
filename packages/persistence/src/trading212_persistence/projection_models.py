"""Normalized immutable projection definitions, captures and retained path records.

The shared premium root/job/outbox owns admission and execution. Licensed financial
copies are separate from opaque source/audit identities and require retention markers
before deletion. Frozen migration 0022 adds the matching relational publication guards.
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
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

from .premium_models import PremiumOwned
from .types import ExactNumeric, UTCDateTime


class AssumptionSetModel(PremiumOwned):
    __tablename__ = "assumption_sets"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_assumption_sets_owner_id_account_id_id"
        ),
        CheckConstraint("revision BETWEEN 1 AND 512", name="revision_bound"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="name_bound"),
        Index("ix_assumption_sets_0", "owner_id", "account_id", "created_at", "id"),
    )
    name: Mapped[str] = mapped_column(String(120))
    revision: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class GoalModel(PremiumOwned):
    __tablename__ = "goals"
    __table_args__ = (
        UniqueConstraint("owner_id", "account_id", "id", name="uq_goals_owner_id_account_id_id"),
        CheckConstraint("revision BETWEEN 1 AND 512", name="revision_bound"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="name_bound"),
        Index("ix_goals_0", "owner_id", "account_id", "created_at", "id"),
    )
    name: Mapped[str] = mapped_column(String(120))
    revision: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class AssumptionVersionModel(PremiumOwned):
    __tablename__ = "assumption_versions"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_assumption_versions_owner_id_account_id_id"
        ),
        UniqueConstraint(
            "set_id", "version_number", name="uq_assumption_versions_set_id_version_number"
        ),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "set_id",
            "id",
            name="uq_assumption_versions_owner_id_account_id_set_id_id",
        ),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "id",
            "content_digest",
            name="uq_assumption_versions_owner_id_account_id_id_content_digest",
        ),
        CheckConstraint(
            "version_number BETWEEN 1 AND 512 AND ((version_number=1)=(predecessor_id IS NULL))",
            name="revision_bound",
        ),
        CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="name_bound"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="content_digest_format"),
        CheckConstraint("reporting_currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint(
            "annual_inflation BETWEEN -.1 AND .5 AND annual_fee BETWEEN 0 AND .2 AN"
            "D (annual_tax_drag IS NULL OR annual_tax_drag BETWEEN 0 AND .2) AND re"
            "balance IN ('monthly','annual','none') AND asset_count BETWEEN 1 AND 1"
            "2 AND calibration_count BETWEEN 0 AND 256",
            name="assumption_bounds",
        ),
        CheckConstraint(
            "annual_inflation IS NULL OR (annual_inflation > '-Infinity'::numeric A"
            "ND annual_inflation < 'Infinity'::numeric)",
            name="annual_inflation_finite",
        ),
        CheckConstraint(
            "annual_fee IS NULL OR (annual_fee > '-Infinity'::numeric AND annual_fe"
            "e < 'Infinity'::numeric)",
            name="annual_fee_finite",
        ),
        CheckConstraint(
            "annual_tax_drag IS NULL OR (annual_tax_drag > '-Infinity'::numeric AND"
            " annual_tax_drag < 'Infinity'::numeric)",
            name="annual_tax_drag_finite",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "set_id"],
            ["assumption_sets.owner_id", "assumption_sets.account_id", "assumption_sets.id"],
            ondelete="RESTRICT",
            name="fk_assumption_versions_0_assumption_sets",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "set_id", "predecessor_id"],
            [
                "assumption_versions.owner_id",
                "assumption_versions.account_id",
                "assumption_versions.set_id",
                "assumption_versions.id",
            ],
            ondelete="RESTRICT",
            name="fk_assumption_versions_1_assumption_versions",
        ),
    )
    set_id: Mapped[UUID] = mapped_column(Uuid())
    version_number: Mapped[int] = mapped_column(Integer)
    predecessor_id: Mapped[UUID | None] = mapped_column(Uuid())
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(1024))
    content_digest: Mapped[str] = mapped_column(String(64))
    sealed: Mapped[bool] = mapped_column(Boolean)
    reporting_currency: Mapped[str] = mapped_column(String(3))
    annual_inflation: Mapped[Decimal] = mapped_column(ExactNumeric())
    annual_fee: Mapped[Decimal] = mapped_column(ExactNumeric())
    annual_tax_drag: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    rebalance: Mapped[str] = mapped_column(String(10))
    asset_count: Mapped[int] = mapped_column(Integer)
    calibration_count: Mapped[int] = mapped_column(Integer)


class ProjectionAssumptionAssetModel(PremiumOwned):
    __tablename__ = "projection_assumption_assets"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "account_id",
            "id",
            name="uq_projection_assumption_assets_owner_id_account_id_id",
        ),
        UniqueConstraint(
            "version_id",
            "asset_index",
            name="uq_projection_assumption_assets_version_id_asset_index",
        ),
        UniqueConstraint(
            "version_id", "asset_key", name="uq_projection_assumption_assets_version_id_asset_key"
        ),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "version_id",
            "asset_index",
            name="uq_projection_assumption_assets_owner_id_account_id__c6f7ae7ff0",
        ),
        CheckConstraint("asset_index BETWEEN 0 AND 11", name="index_bound"),
        CheckConstraint("asset_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$'", name="key_format"),
        CheckConstraint(
            "annual_mean_log_return BETWEEN -.5 AND .5 AND annual_volatility BETWEE"
            "N 0 AND 1 AND weight BETWEEN 0 AND 1",
            name="amount_bounds",
        ),
        CheckConstraint(
            "annual_mean_log_return IS NULL OR (annual_mean_log_return > '-Infinity"
            "'::numeric AND annual_mean_log_return < 'Infinity'::numeric)",
            name="annual_mean_log_return_finite",
        ),
        CheckConstraint(
            "annual_volatility IS NULL OR (annual_volatility > '-Infinity'::numeric"
            " AND annual_volatility < 'Infinity'::numeric)",
            name="annual_volatility_finite",
        ),
        CheckConstraint(
            "weight IS NULL OR (weight > '-Infinity'::numeric AND weight < 'Infinity'::numeric)",
            name="weight_finite",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "version_id"],
            [
                "assumption_versions.owner_id",
                "assumption_versions.account_id",
                "assumption_versions.id",
            ],
            ondelete="RESTRICT",
            name="fk_projection_assumption_assets_0_assumption_versions",
        ),
    )
    version_id: Mapped[UUID] = mapped_column(Uuid())
    asset_index: Mapped[int] = mapped_column(Integer)
    asset_key: Mapped[str] = mapped_column(String(120))
    annual_mean_log_return: Mapped[Decimal] = mapped_column(ExactNumeric())
    annual_volatility: Mapped[Decimal] = mapped_column(ExactNumeric())
    weight: Mapped[Decimal] = mapped_column(ExactNumeric())


class ProjectionCorrelationCellModel(PremiumOwned):
    __tablename__ = "projection_correlation_cells"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "account_id",
            "id",
            name="uq_projection_correlation_cells_owner_id_account_id_id",
        ),
        UniqueConstraint(
            "version_id",
            "row_index",
            "column_index",
            name="uq_projection_correlation_cells_version_id_row_index_1fc125c0fd",
        ),
        CheckConstraint(
            "row_index BETWEEN 0 AND 11 AND column_index BETWEEN 0 AND 11", name="indices_bound"
        ),
        CheckConstraint(
            "value BETWEEN -1 AND 1 AND (row_index<>column_index OR value=1)", name="value_bound"
        ),
        CheckConstraint(
            "value IS NULL OR (value > '-Infinity'::numeric AND value < 'Infinity'::numeric)",
            name="value_finite",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "version_id"],
            [
                "assumption_versions.owner_id",
                "assumption_versions.account_id",
                "assumption_versions.id",
            ],
            ondelete="RESTRICT",
            name="fk_projection_correlation_cells_0_assumption_versions",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "version_id", "row_index"],
            [
                "projection_assumption_assets.owner_id",
                "projection_assumption_assets.account_id",
                "projection_assumption_assets.version_id",
                "projection_assumption_assets.asset_index",
            ],
            ondelete="RESTRICT",
            name="fk_projection_correlation_cells_1_projection_assumption_assets",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "version_id", "column_index"],
            [
                "projection_assumption_assets.owner_id",
                "projection_assumption_assets.account_id",
                "projection_assumption_assets.version_id",
                "projection_assumption_assets.asset_index",
            ],
            ondelete="RESTRICT",
            name="fk_projection_correlation_cells_2_projection_assumption_assets",
        ),
    )
    version_id: Mapped[UUID] = mapped_column(Uuid())
    row_index: Mapped[int] = mapped_column(Integer)
    column_index: Mapped[int] = mapped_column(Integer)
    value: Mapped[Decimal] = mapped_column(ExactNumeric())


class ProjectionCalibrationPinModel(PremiumOwned):
    __tablename__ = "projection_calibration_pins"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "account_id",
            "id",
            name="uq_projection_calibration_pins_owner_id_account_id_id",
        ),
        UniqueConstraint(
            "version_id", "subject_id", name="uq_projection_calibration_pins_version_id_subject_id"
        ),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "version_id",
            "subject_id",
            "content_digest",
            name="uq_projection_calibration_pins_owner_id_account_id_v_f26056c98a",
        ),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="content_digest_format"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "version_id"],
            [
                "assumption_versions.owner_id",
                "assumption_versions.account_id",
                "assumption_versions.id",
            ],
            ondelete="RESTRICT",
            name="fk_projection_calibration_pins_0_assumption_versions",
        ),
    )
    version_id: Mapped[UUID] = mapped_column(Uuid())
    subject_id: Mapped[UUID] = mapped_column(Uuid())
    content_digest: Mapped[str] = mapped_column(String(64))


class GoalVersionModel(PremiumOwned):
    __tablename__ = "goal_versions"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_goal_versions_owner_id_account_id_id"
        ),
        UniqueConstraint(
            "goal_id", "version_number", name="uq_goal_versions_goal_id_version_number"
        ),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "goal_id",
            "id",
            name="uq_goal_versions_owner_id_account_id_goal_id_id",
        ),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "id",
            "content_digest",
            name="uq_goal_versions_owner_id_account_id_id_content_digest",
        ),
        CheckConstraint(
            "version_number BETWEEN 1 AND 512 AND ((version_number=1)=(predecessor_id IS NULL))",
            name="revision_bound",
        ),
        CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="name_bound"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="content_digest_format"),
        CheckConstraint("reporting_currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint(
            "target>=0 AND months BETWEEN 1 AND 600 AND basis IN ('nominal','real')"
            " AND probability_objective BETWEEN 0 AND 1 AND base_monthly>=0 AND ann"
            "ual_growth BETWEEN -1 AND 1 AND pause_count>=0 AND entry_count>=0 AND "
            "pause_count+entry_count<=128",
            name="goal_bounds",
        ),
        CheckConstraint(
            "target IS NULL OR (target > '-Infinity'::numeric AND target < 'Infinity'::numeric)",
            name="target_finite",
        ),
        CheckConstraint(
            "probability_objective IS NULL OR (probability_objective > '-Infinity':"
            ":numeric AND probability_objective < 'Infinity'::numeric)",
            name="probability_objective_finite",
        ),
        CheckConstraint(
            "base_monthly IS NULL OR (base_monthly > '-Infinity'::numeric AND base_"
            "monthly < 'Infinity'::numeric)",
            name="base_monthly_finite",
        ),
        CheckConstraint(
            "annual_growth IS NULL OR (annual_growth > '-Infinity'::numeric AND ann"
            "ual_growth < 'Infinity'::numeric)",
            name="annual_growth_finite",
        ),
        CheckConstraint(
            "\"target_date\" BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'",
            name="target_date_date_bound",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "goal_id"],
            ["goals.owner_id", "goals.account_id", "goals.id"],
            ondelete="RESTRICT",
            name="fk_goal_versions_0_goals",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "assumption_version_id"],
            [
                "assumption_versions.owner_id",
                "assumption_versions.account_id",
                "assumption_versions.id",
            ],
            ondelete="RESTRICT",
            name="fk_goal_versions_1_assumption_versions",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "goal_id", "predecessor_id"],
            [
                "goal_versions.owner_id",
                "goal_versions.account_id",
                "goal_versions.goal_id",
                "goal_versions.id",
            ],
            ondelete="RESTRICT",
            name="fk_goal_versions_2_goal_versions",
        ),
    )
    goal_id: Mapped[UUID] = mapped_column(Uuid())
    version_number: Mapped[int] = mapped_column(Integer)
    predecessor_id: Mapped[UUID | None] = mapped_column(Uuid())
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(1024))
    content_digest: Mapped[str] = mapped_column(String(64))
    sealed: Mapped[bool] = mapped_column(Boolean)
    assumption_version_id: Mapped[UUID] = mapped_column(Uuid())
    reporting_currency: Mapped[str] = mapped_column(String(3))
    target: Mapped[Decimal] = mapped_column(ExactNumeric())
    target_date: Mapped[date] = mapped_column(Date())
    months: Mapped[int] = mapped_column(Integer)
    basis: Mapped[str] = mapped_column(String(10))
    probability_objective: Mapped[Decimal] = mapped_column(ExactNumeric())
    base_monthly: Mapped[Decimal] = mapped_column(ExactNumeric())
    annual_growth: Mapped[Decimal] = mapped_column(ExactNumeric())
    pause_count: Mapped[int] = mapped_column(Integer)
    entry_count: Mapped[int] = mapped_column(Integer)


class ProjectionGoalPauseModel(PremiumOwned):
    __tablename__ = "projection_goal_pauses"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_projection_goal_pauses_owner_id_account_id_id"
        ),
        UniqueConstraint("version_id", "on", name="uq_projection_goal_pauses_version_id_on"),
        CheckConstraint(
            "\"on\" BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'", name="on_date_bound"
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "version_id"],
            ["goal_versions.owner_id", "goal_versions.account_id", "goal_versions.id"],
            ondelete="RESTRICT",
            name="fk_projection_goal_pauses_0_goal_versions",
        ),
    )
    version_id: Mapped[UUID] = mapped_column(Uuid())
    on: Mapped[date] = mapped_column(Date())


class ProjectionGoalScheduleEntryModel(PremiumOwned):
    __tablename__ = "projection_goal_schedule_entries"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "account_id",
            "id",
            name="uq_projection_goal_schedule_entries_owner_id_account_id_id",
        ),
        UniqueConstraint(
            "version_id",
            "entry_key",
            name="uq_projection_goal_schedule_entries_version_id_entry_key",
        ),
        CheckConstraint("kind IN ('lump_sum','withdrawal')", name="kind_allowed"),
        CheckConstraint("entry_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$'", name="key_format"),
        CheckConstraint("value>=0", name="value_bound"),
        CheckConstraint(
            "value IS NULL OR (value > '-Infinity'::numeric AND value < 'Infinity'::numeric)",
            name="value_finite",
        ),
        CheckConstraint(
            "\"on\" BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'", name="on_date_bound"
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "version_id"],
            ["goal_versions.owner_id", "goal_versions.account_id", "goal_versions.id"],
            ondelete="RESTRICT",
            name="fk_projection_goal_schedule_entries_0_goal_versions",
        ),
    )
    version_id: Mapped[UUID] = mapped_column(Uuid())
    entry_key: Mapped[str] = mapped_column(String(120))
    on: Mapped[date] = mapped_column(Date())
    kind: Mapped[str] = mapped_column(String(12))
    value: Mapped[Decimal] = mapped_column(ExactNumeric())


class ProjectionRunModel(PremiumOwned):
    __tablename__ = "projection_runs"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_projection_runs_owner_id_account_id_id"
        ),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "id",
            "numerical_input_digest",
            name="uq_projection_runs_owner_id_account_id_id_numerical__7391546e3f",
        ),
        CheckConstraint("assumption_digest ~ '^[0-9a-f]{64}$'", name="assumption_digest_format"),
        CheckConstraint("goal_digest ~ '^[0-9a-f]{64}$'", name="goal_digest_format"),
        CheckConstraint(
            "numerical_input_digest ~ '^[0-9a-f]{64}$'", name="numerical_input_digest_format"
        ),
        CheckConstraint("capture_digest ~ '^[0-9a-f]{64}$'", name="capture_digest_format"),
        CheckConstraint("snapshot_digest ~ '^[0-9a-f]{64}$'", name="snapshot_digest_format"),
        CheckConstraint("reporting_currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("(goal_version_id IS NULL)=(goal_digest IS NULL)", name="goal_pin"),
        CheckConstraint(
            "seed BETWEEN 0 AND 4294967295 AND months BETWEEN 1 AND 600 AND path_co"
            "unt BETWEEN 1 AND 4096 AND asset_count BETWEEN 1 AND 12 AND retained_p"
            "oint_count BETWEEN 2 AND 121 AND retained_point_count<=months+1 AND va"
            "riant_count IN (1,3) AND asset_count*months*path_count*variant_count<="
            "1000000 AND source_count BETWEEN 0 AND 257",
            name="input_bounds",
        ),
        CheckConstraint(
            "(initial_kind='modeled_value' AND snapshot_id IS NULL AND snapshot_dig"
            "est IS NULL AND snapshot_valuation_at IS NULL) OR (initial_kind='obser"
            "ved_snapshot' AND snapshot_id IS NOT NULL AND snapshot_digest IS NOT N"
            "ULL AND snapshot_valuation_at IS NOT NULL AND anchor_date=(snapshot_va"
            "luation_at AT TIME ZONE 'UTC')::date)",
            name="initial_pin",
        ),
        CheckConstraint("calendar_rule='calendar_anniversary_clamped_v1'", name="calendar_rule"),
        CheckConstraint(
            "stored_bytes BETWEEN 0 AND 33554432 AND payload_rows>=0 AND "
            "retained_source_rows BETWEEN 0 AND 100000 AND retained_source_bytes>=0 "
            "AND retained_source_bytes<=stored_bytes AND "
            "((retained_source_rows=0)=(retained_source_bytes=0)) AND "
            "(payload_rows<>0 OR stored_bytes=retained_source_bytes)",
            name="physical_counter_bound",
        ),
        CheckConstraint(
            "\"anchor_date\" BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'",
            name="anchor_date_date_bound",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "id"],
            ["premium_runs.owner_id", "premium_runs.account_id", "premium_runs.id"],
            ondelete="RESTRICT",
            name="fk_projection_runs_0_premium_runs",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "assumption_version_id", "assumption_digest"],
            [
                "assumption_versions.owner_id",
                "assumption_versions.account_id",
                "assumption_versions.id",
                "assumption_versions.content_digest",
            ],
            ondelete="RESTRICT",
            name="fk_projection_runs_1_assumption_versions",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "goal_version_id", "goal_digest"],
            [
                "goal_versions.owner_id",
                "goal_versions.account_id",
                "goal_versions.id",
                "goal_versions.content_digest",
            ],
            ondelete="RESTRICT",
            name="fk_projection_runs_2_goal_versions",
        ),
        ForeignKeyConstraint(
            ["snapshot_id"],
            ["portfolio_snapshots.id"],
            ondelete="RESTRICT",
            name="fk_projection_runs_3_portfolio_snapshots",
        ),
    )
    assumption_version_id: Mapped[UUID] = mapped_column(Uuid())
    assumption_digest: Mapped[str] = mapped_column(String(64))
    goal_version_id: Mapped[UUID | None] = mapped_column(Uuid())
    goal_digest: Mapped[str | None] = mapped_column(String(64))
    numerical_input_digest: Mapped[str] = mapped_column(String(64))
    capture_digest: Mapped[str] = mapped_column(String(64))
    seed: Mapped[int] = mapped_column(BigInteger)
    months: Mapped[int] = mapped_column(Integer)
    path_count: Mapped[int] = mapped_column(Integer)
    asset_count: Mapped[int] = mapped_column(Integer)
    retained_point_count: Mapped[int] = mapped_column(Integer)
    variant_count: Mapped[int] = mapped_column(Integer)
    source_count: Mapped[int] = mapped_column(Integer)
    stored_bytes: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    payload_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    retained_source_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    retained_source_bytes: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    initial_kind: Mapped[str] = mapped_column(String(20))
    snapshot_id: Mapped[UUID | None] = mapped_column(Uuid())
    snapshot_digest: Mapped[str | None] = mapped_column(String(64))
    snapshot_valuation_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    anchor_date: Mapped[date] = mapped_column(Date())
    reporting_currency: Mapped[str] = mapped_column(String(3))
    calendar_rule: Mapped[str] = mapped_column(String(40))
    sealed: Mapped[bool] = mapped_column(Boolean)


class ProjectionInputModel(PremiumOwned):
    __tablename__ = "projection_inputs"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_projection_inputs_owner_id_account_id_id"
        ),
        UniqueConstraint("run_id", name="uq_projection_inputs_run_id"),
        CheckConstraint(
            "initial_value>=0 AND base_monthly>=0 AND annual_growth BETWEEN -1 AND 1",
            name="amount_bounds",
        ),
        CheckConstraint(
            "(contribution_delta IS NULL)=(annual_mean_log_delta IS NULL)", name="sensitivity_pair"
        ),
        CheckConstraint(
            "pause_count>=0 AND entry_count>=0 AND pause_count+entry_count<=128",
            name="schedule_bound",
        ),
        CheckConstraint(
            "capture_bytes BETWEEN 1 AND 33554432 AND input_bytes BETWEEN 1 AND 335"
            "54432 AND octet_length(canonical_capture)=capture_bytes AND octet_leng"
            "th(canonical_input)=input_bytes AND capture_bytes+input_bytes<=3355443"
            "2",
            name="bytes_bound",
        ),
        CheckConstraint(
            "initial_value IS NULL OR (initial_value > '-Infinity'::numeric AND ini"
            "tial_value < 'Infinity'::numeric)",
            name="initial_value_finite",
        ),
        CheckConstraint(
            "base_monthly IS NULL OR (base_monthly > '-Infinity'::numeric AND base_"
            "monthly < 'Infinity'::numeric)",
            name="base_monthly_finite",
        ),
        CheckConstraint(
            "annual_growth IS NULL OR (annual_growth > '-Infinity'::numeric AND ann"
            "ual_growth < 'Infinity'::numeric)",
            name="annual_growth_finite",
        ),
        CheckConstraint(
            "contribution_delta IS NULL OR (contribution_delta > '-Infinity'::numer"
            "ic AND contribution_delta < 'Infinity'::numeric)",
            name="contribution_delta_finite",
        ),
        CheckConstraint(
            "annual_mean_log_delta IS NULL OR (annual_mean_log_delta > '-Infinity':"
            ":numeric AND annual_mean_log_delta < 'Infinity'::numeric)",
            name="annual_mean_log_delta_finite",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["projection_runs.owner_id", "projection_runs.account_id", "projection_runs.id"],
            ondelete="RESTRICT",
            name="fk_projection_inputs_0_projection_runs",
        ),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid())
    initial_value: Mapped[Decimal] = mapped_column(ExactNumeric())
    base_monthly: Mapped[Decimal] = mapped_column(ExactNumeric())
    annual_growth: Mapped[Decimal] = mapped_column(ExactNumeric())
    contribution_delta: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    annual_mean_log_delta: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    pause_count: Mapped[int] = mapped_column(Integer)
    entry_count: Mapped[int] = mapped_column(Integer)
    capture_bytes: Mapped[int] = mapped_column(Integer)
    input_bytes: Mapped[int] = mapped_column(Integer)
    canonical_capture: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    canonical_input: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class ProjectionRunAllocationModel(PremiumOwned):
    __tablename__ = "projection_run_allocations"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "account_id",
            "id",
            name="uq_projection_run_allocations_owner_id_account_id_id",
        ),
        UniqueConstraint(
            "run_id", "asset_index", name="uq_projection_run_allocations_run_id_asset_index"
        ),
        UniqueConstraint(
            "run_id", "asset_key", name="uq_projection_run_allocations_run_id_asset_key"
        ),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "run_id",
            "asset_index",
            name="uq_projection_run_allocations_owner_id_account_id_ru_2a094e5b4f",
        ),
        CheckConstraint("asset_index BETWEEN 0 AND 11", name="index_bound"),
        CheckConstraint("weight BETWEEN 0 AND 1", name="weight_bound"),
        CheckConstraint(
            "weight IS NULL OR (weight > '-Infinity'::numeric AND weight < 'Infinity'::numeric)",
            name="weight_finite",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["projection_runs.owner_id", "projection_runs.account_id", "projection_runs.id"],
            ondelete="RESTRICT",
            name="fk_projection_run_allocations_0_projection_runs",
        ),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid())
    asset_index: Mapped[int] = mapped_column(Integer)
    asset_key: Mapped[str] = mapped_column(String(120))
    weight: Mapped[Decimal] = mapped_column(ExactNumeric())


class ProjectionCalendarBoundaryModel(PremiumOwned):
    __tablename__ = "projection_calendar_boundaries"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "account_id",
            "id",
            name="uq_projection_calendar_boundaries_owner_id_account_id_id",
        ),
        UniqueConstraint("run_id", "month", name="uq_projection_calendar_boundaries_run_id_month"),
        UniqueConstraint("run_id", "on", name="uq_projection_calendar_boundaries_run_id_on"),
        UniqueConstraint(
            "run_id", "point_index", name="uq_projection_calendar_boundaries_run_id_point_index"
        ),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "run_id",
            "month",
            name="uq_projection_calendar_boundaries_owner_id_account_i_67e9884add",
        ),
        CheckConstraint(
            "month BETWEEN 0 AND 600 AND (point_index IS NULL OR point_index BETWEEN 0 AND 120)",
            name="index_bound",
        ),
        CheckConstraint(
            "\"on\" BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'", name="on_date_bound"
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["projection_runs.owner_id", "projection_runs.account_id", "projection_runs.id"],
            ondelete="RESTRICT",
            name="fk_projection_calendar_boundaries_0_projection_runs",
        ),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid())
    month: Mapped[int] = mapped_column(Integer)
    on: Mapped[date] = mapped_column(Date())
    point_index: Mapped[int | None] = mapped_column(Integer)


class ProjectionRunPauseModel(PremiumOwned):
    __tablename__ = "projection_run_pauses"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_projection_run_pauses_owner_id_account_id_id"
        ),
        UniqueConstraint("run_id", "on", name="uq_projection_run_pauses_run_id_on"),
        UniqueConstraint("run_id", "month", name="uq_projection_run_pauses_run_id_month"),
        CheckConstraint("month BETWEEN 1 AND 600", name="month_bound"),
        CheckConstraint(
            "\"on\" BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'", name="on_date_bound"
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["projection_runs.owner_id", "projection_runs.account_id", "projection_runs.id"],
            ondelete="RESTRICT",
            name="fk_projection_run_pauses_0_projection_runs",
        ),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid())
    on: Mapped[date] = mapped_column(Date())
    month: Mapped[int] = mapped_column(Integer)


class ProjectionRunScheduleEntryModel(PremiumOwned):
    __tablename__ = "projection_run_schedule_entries"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "account_id",
            "id",
            name="uq_projection_run_schedule_entries_owner_id_account_id_id",
        ),
        UniqueConstraint(
            "run_id", "entry_key", name="uq_projection_run_schedule_entries_run_id_entry_key"
        ),
        CheckConstraint("month BETWEEN 1 AND 600", name="month_bound"),
        CheckConstraint("kind IN ('lump_sum','withdrawal')", name="kind_allowed"),
        CheckConstraint("value>=0", name="value_bound"),
        CheckConstraint(
            "value IS NULL OR (value > '-Infinity'::numeric AND value < 'Infinity'::numeric)",
            name="value_finite",
        ),
        CheckConstraint(
            "\"on\" BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'", name="on_date_bound"
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["projection_runs.owner_id", "projection_runs.account_id", "projection_runs.id"],
            ondelete="RESTRICT",
            name="fk_projection_run_schedule_entries_0_projection_runs",
        ),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid())
    entry_key: Mapped[str] = mapped_column(String(120))
    on: Mapped[date] = mapped_column(Date())
    month: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(12))
    value: Mapped[Decimal] = mapped_column(ExactNumeric())


class ProjectionRunSourceModel(PremiumOwned):
    __tablename__ = "projection_run_sources"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_projection_run_sources_owner_id_account_id_id"
        ),
        UniqueConstraint(
            "run_id", "kind", "subject_id", name="uq_projection_run_sources_run_id_kind_subject_id"
        ),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="content_digest_format"),
        CheckConstraint("proof_digest ~ '^[0-9a-f]{64}$'", name="proof_digest_format"),
        CheckConstraint("kind IN ('initial_snapshot','calibration')", name="kind_allowed"),
        CheckConstraint("source_expires_at>original_created_at", name="expiry_order"),
        CheckConstraint(
            "quality IN ('fresh','stale','partial','estimated','unreconciled','failed')",
            name="quality_allowed",
        ),
        CheckConstraint("proof_bytes BETWEEN 1 AND 33554432", name="proof_bound"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["projection_runs.owner_id", "projection_runs.account_id", "projection_runs.id"],
            ondelete="RESTRICT",
            name="fk_projection_run_sources_0_projection_runs",
        ),
        Index("ix_projection_run_sources_0", "subject_id", "content_digest", "run_id"),
        Index("ix_projection_run_sources_1", "source_expires_at", "run_id"),
        Index("ix_projection_retention_source_keyset", "owner_id", "account_id", "run_id", "id"),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid())
    kind: Mapped[str] = mapped_column(String(20))
    subject_id: Mapped[UUID] = mapped_column(Uuid())
    content_digest: Mapped[str] = mapped_column(String(64))
    original_created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    source_expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    quality: Mapped[str] = mapped_column(String(20))
    proof_digest: Mapped[str] = mapped_column(String(64))
    proof_bytes: Mapped[int] = mapped_column(Integer)


class ProjectionSourceProofModel(PremiumOwned):
    __tablename__ = "projection_source_proofs"
    __table_args__ = (
        Index("ix_projection_source_proofs_retention", "owner_id", "account_id", "run_id", "id"),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "id",
            name="uq_projection_source_proofs_owner_id_account_id_id",
        ),
        UniqueConstraint("source_id", name="uq_projection_source_proofs_source_id"),
        CheckConstraint("octet_length(canonical_proof) BETWEEN 1 AND 33554432", name="proof_bound"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["projection_runs.owner_id", "projection_runs.account_id", "projection_runs.id"],
            ondelete="RESTRICT",
            name="fk_projection_source_proofs_0_projection_runs",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "source_id"],
            [
                "projection_run_sources.owner_id",
                "projection_run_sources.account_id",
                "projection_run_sources.id",
            ],
            ondelete="RESTRICT",
            name="fk_projection_source_proofs_1_projection_run_sources",
        ),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid())
    source_id: Mapped[UUID] = mapped_column(Uuid())
    canonical_proof: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class ProjectionSourceLicenseModel(PremiumOwned):
    __tablename__ = "projection_source_licenses"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "account_id",
            "id",
            name="uq_projection_source_licenses_owner_id_account_id_id",
        ),
        UniqueConstraint(
            "source_id",
            "run_license_id",
            name="uq_projection_source_licenses_source_id_run_license_id",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["projection_runs.owner_id", "projection_runs.account_id", "projection_runs.id"],
            ondelete="RESTRICT",
            name="fk_projection_source_licenses_0_projection_runs",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "source_id"],
            [
                "projection_run_sources.owner_id",
                "projection_run_sources.account_id",
                "projection_run_sources.id",
            ],
            ondelete="RESTRICT",
            name="fk_projection_source_licenses_1_projection_run_sources",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_license_id"],
            [
                "premium_run_licenses.owner_id",
                "premium_run_licenses.account_id",
                "premium_run_licenses.id",
            ],
            ondelete="RESTRICT",
            name="fk_projection_source_licenses_2_premium_run_licenses",
        ),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid())
    source_id: Mapped[UUID] = mapped_column(Uuid())
    run_license_id: Mapped[UUID] = mapped_column(Uuid())


class ProjectionChunkModel(PremiumOwned):
    __tablename__ = "projection_chunks"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_projection_chunks_owner_id_account_id_id"
        ),
        UniqueConstraint(
            "run_id", "variant", "first_path", name="uq_projection_chunks_run_id_variant_first_path"
        ),
        CheckConstraint(
            "variant IN ('baseline','contribution_delta','mean_log_delta')", name="variant_allowed"
        ),
        CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name="input_digest_format"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="content_digest_format"),
        CheckConstraint(
            "first_path BETWEEN 0 AND 4095 AND path_count BETWEEN 1 AND 32 AND firs"
            "t_path+path_count<=4096",
            name="path_bounds",
        ),
        CheckConstraint("consumer_attempt BETWEEN 1 AND 4", name="attempt_bound"),
        CheckConstraint(
            "byte_length BETWEEN 1 AND 33554432 AND octet_length(canonical_chunk)=byte_length",
            name="bytes_bound",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["projection_runs.owner_id", "projection_runs.account_id", "projection_runs.id"],
            ondelete="RESTRICT",
            name="fk_projection_chunks_0_projection_runs",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "job_id"],
            ["premium_jobs.owner_id", "premium_jobs.account_id", "premium_jobs.id"],
            ondelete="RESTRICT",
            name="fk_projection_chunks_1_premium_jobs",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id", "input_digest"],
            [
                "projection_runs.owner_id",
                "projection_runs.account_id",
                "projection_runs.id",
                "projection_runs.numerical_input_digest",
            ],
            ondelete="RESTRICT",
            name="fk_projection_chunks_2_projection_runs",
        ),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid())
    job_id: Mapped[UUID] = mapped_column(Uuid())
    lease_token: Mapped[UUID] = mapped_column(Uuid())
    consumer_attempt: Mapped[int] = mapped_column(Integer)
    variant: Mapped[str] = mapped_column(String(24))
    first_path: Mapped[int] = mapped_column(Integer)
    path_count: Mapped[int] = mapped_column(Integer)
    input_digest: Mapped[str] = mapped_column(String(64))
    content_digest: Mapped[str] = mapped_column(String(64))
    byte_length: Mapped[int] = mapped_column(Integer)
    canonical_chunk: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    sealed: Mapped[bool] = mapped_column(Boolean)


class ProjectionPathModel(PremiumOwned):
    __tablename__ = "projection_paths"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_projection_paths_owner_id_account_id_id"
        ),
        UniqueConstraint(
            "run_id", "variant", "path_index", name="uq_projection_paths_run_id_variant_path_index"
        ),
        CheckConstraint(
            "variant IN ('baseline','contribution_delta','mean_log_delta')", name="variant_allowed"
        ),
        CheckConstraint(
            "path_index BETWEEN 0 AND 4095 AND (first_unpaid_month IS NULL OR first"
            "_unpaid_month BETWEEN 1 AND 600)",
            name="path_bound",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["projection_runs.owner_id", "projection_runs.account_id", "projection_runs.id"],
            ondelete="RESTRICT",
            name="fk_projection_paths_0_projection_runs",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "chunk_id"],
            ["projection_chunks.owner_id", "projection_chunks.account_id", "projection_chunks.id"],
            ondelete="RESTRICT",
            name="fk_projection_paths_1_projection_chunks",
        ),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid())
    chunk_id: Mapped[UUID] = mapped_column(Uuid())
    variant: Mapped[str] = mapped_column(String(24))
    path_index: Mapped[int] = mapped_column(Integer)
    first_unpaid_month: Mapped[int | None] = mapped_column(Integer)


class ProjectionPointModel(PremiumOwned):
    __tablename__ = "projection_points"
    __table_args__ = (
        Index("ix_projection_points_retention", "owner_id", "account_id", "run_id", "id"),
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_projection_points_owner_id_account_id_id"
        ),
        UniqueConstraint("path_id", "month", name="uq_projection_points_path_id_month"),
        UniqueConstraint("path_id", "point_index", name="uq_projection_points_path_id_point_index"),
        CheckConstraint(
            "month BETWEEN 0 AND 600 AND point_index BETWEEN 0 AND 120", name="indices_bound"
        ),
        CheckConstraint(
            "nominal>=0 AND real>=0 AND contributions>=0 AND withdrawals_requested>"
            "=0 AND withdrawals_funded>=0 AND unpaid_withdrawals>=0 AND fees>=0 AND"
            " tax_drag>=0",
            name="nonnegative",
        ),
        CheckConstraint(
            "withdrawals_funded<=withdrawals_requested AND withdrawal_residual=with"
            "drawals_requested-withdrawals_funded-unpaid_withdrawals AND (unpaid_wi"
            "thdrawals=0 OR funding_failed) AND unpaid_positive_below_quantum=(fund"
            "ing_failed AND unpaid_withdrawals=0)",
            name="funding_consistency",
        ),
        CheckConstraint(
            "nominal IS NULL OR (nominal > '-Infinity'::numeric AND nominal < 'Infinity'::numeric)",
            name="nominal_finite",
        ),
        CheckConstraint(
            "real IS NULL OR (real > '-Infinity'::numeric AND real < 'Infinity'::numeric)",
            name="real_finite",
        ),
        CheckConstraint(
            "contributions IS NULL OR (contributions > '-Infinity'::numeric AND con"
            "tributions < 'Infinity'::numeric)",
            name="contributions_finite",
        ),
        CheckConstraint(
            "withdrawals_requested IS NULL OR (withdrawals_requested > '-Infinity':"
            ":numeric AND withdrawals_requested < 'Infinity'::numeric)",
            name="withdrawals_requested_finite",
        ),
        CheckConstraint(
            "withdrawals_funded IS NULL OR (withdrawals_funded > '-Infinity'::numer"
            "ic AND withdrawals_funded < 'Infinity'::numeric)",
            name="withdrawals_funded_finite",
        ),
        CheckConstraint(
            "unpaid_withdrawals IS NULL OR (unpaid_withdrawals > '-Infinity'::numer"
            "ic AND unpaid_withdrawals < 'Infinity'::numeric)",
            name="unpaid_withdrawals_finite",
        ),
        CheckConstraint(
            "investment_effect IS NULL OR (investment_effect > '-Infinity'::numeric"
            " AND investment_effect < 'Infinity'::numeric)",
            name="investment_effect_finite",
        ),
        CheckConstraint(
            "fees IS NULL OR (fees > '-Infinity'::numeric AND fees < 'Infinity'::numeric)",
            name="fees_finite",
        ),
        CheckConstraint(
            "tax_drag IS NULL OR (tax_drag > '-Infinity'::numeric AND tax_drag < 'I"
            "nfinity'::numeric)",
            name="tax_drag_finite",
        ),
        CheckConstraint(
            "wealth_residual IS NULL OR (wealth_residual > '-Infinity'::numeric AND"
            " wealth_residual < 'Infinity'::numeric)",
            name="wealth_residual_finite",
        ),
        CheckConstraint(
            "allocation_residual IS NULL OR (allocation_residual > '-Infinity'::num"
            "eric AND allocation_residual < 'Infinity'::numeric)",
            name="allocation_residual_finite",
        ),
        CheckConstraint(
            "withdrawal_residual IS NULL OR (withdrawal_residual > '-Infinity'::num"
            "eric AND withdrawal_residual < 'Infinity'::numeric)",
            name="withdrawal_residual_finite",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["projection_runs.owner_id", "projection_runs.account_id", "projection_runs.id"],
            ondelete="RESTRICT",
            name="fk_projection_points_0_projection_runs",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "path_id"],
            ["projection_paths.owner_id", "projection_paths.account_id", "projection_paths.id"],
            ondelete="RESTRICT",
            name="fk_projection_points_1_projection_paths",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id", "month"],
            [
                "projection_calendar_boundaries.owner_id",
                "projection_calendar_boundaries.account_id",
                "projection_calendar_boundaries.run_id",
                "projection_calendar_boundaries.month",
            ],
            ondelete="RESTRICT",
            name="fk_projection_points_2_projection_calendar_boundaries",
        ),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid())
    path_id: Mapped[UUID] = mapped_column(Uuid())
    month: Mapped[int] = mapped_column(Integer)
    point_index: Mapped[int] = mapped_column(Integer)
    nominal: Mapped[Decimal] = mapped_column(ExactNumeric())
    real: Mapped[Decimal] = mapped_column(ExactNumeric())
    contributions: Mapped[Decimal] = mapped_column(ExactNumeric())
    withdrawals_requested: Mapped[Decimal] = mapped_column(ExactNumeric())
    withdrawals_funded: Mapped[Decimal] = mapped_column(ExactNumeric())
    unpaid_withdrawals: Mapped[Decimal] = mapped_column(ExactNumeric())
    investment_effect: Mapped[Decimal] = mapped_column(ExactNumeric())
    fees: Mapped[Decimal] = mapped_column(ExactNumeric())
    tax_drag: Mapped[Decimal] = mapped_column(ExactNumeric())
    wealth_residual: Mapped[Decimal] = mapped_column(ExactNumeric())
    allocation_residual: Mapped[Decimal] = mapped_column(ExactNumeric())
    withdrawal_residual: Mapped[Decimal] = mapped_column(ExactNumeric())
    funding_failed: Mapped[bool] = mapped_column(Boolean)
    unpaid_positive_below_quantum: Mapped[bool] = mapped_column(Boolean)


class ProjectionPointAssetModel(PremiumOwned):
    __tablename__ = "projection_point_assets"
    __table_args__ = (
        Index("ix_projection_point_assets_retention", "owner_id", "account_id", "run_id", "id"),
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_projection_point_assets_owner_id_account_id_id"
        ),
        UniqueConstraint(
            "point_id", "asset_index", name="uq_projection_point_assets_point_id_asset_index"
        ),
        CheckConstraint("value>=0", name="value_bound"),
        CheckConstraint(
            "value IS NULL OR (value > '-Infinity'::numeric AND value < 'Infinity'::numeric)",
            name="value_finite",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["projection_runs.owner_id", "projection_runs.account_id", "projection_runs.id"],
            ondelete="RESTRICT",
            name="fk_projection_point_assets_0_projection_runs",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "point_id"],
            ["projection_points.owner_id", "projection_points.account_id", "projection_points.id"],
            ondelete="RESTRICT",
            name="fk_projection_point_assets_1_projection_points",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id", "asset_index"],
            [
                "projection_run_allocations.owner_id",
                "projection_run_allocations.account_id",
                "projection_run_allocations.run_id",
                "projection_run_allocations.asset_index",
            ],
            ondelete="RESTRICT",
            name="fk_projection_point_assets_2_projection_run_allocations",
        ),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid())
    point_id: Mapped[UUID] = mapped_column(Uuid())
    asset_index: Mapped[int] = mapped_column(Integer)
    value: Mapped[Decimal] = mapped_column(ExactNumeric())


class ProjectionResultModel(PremiumOwned):
    __tablename__ = "projection_results"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_projection_results_owner_id_account_id_id"
        ),
        UniqueConstraint("run_id", name="uq_projection_results_run_id"),
        CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name="input_digest_format"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="content_digest_format"),
        CheckConstraint(
            "byte_length BETWEEN 1 AND 33554432 AND octet_length(canonical_result) "
            "IN (0,byte_length)",
            name="bytes_bound",
        ),
        CheckConstraint(
            "quality IN ('estimated','stale','partial','unreconciled','failed')",
            name="quality_allowed",
        ),
        CheckConstraint("sampler='sha256_counter_polar_v1'", name="sampler_fixed"),
        CheckConstraint("consumer_attempt BETWEEN 1 AND 4", name="attempt_bound"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["projection_runs.owner_id", "projection_runs.account_id", "projection_runs.id"],
            ondelete="RESTRICT",
            name="fk_projection_results_0_projection_runs",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "job_id"],
            ["premium_jobs.owner_id", "premium_jobs.account_id", "premium_jobs.id"],
            ondelete="RESTRICT",
            name="fk_projection_results_1_premium_jobs",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id", "input_digest"],
            [
                "projection_runs.owner_id",
                "projection_runs.account_id",
                "projection_runs.id",
                "projection_runs.numerical_input_digest",
            ],
            ondelete="RESTRICT",
            name="fk_projection_results_2_projection_runs",
        ),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid())
    job_id: Mapped[UUID] = mapped_column(Uuid())
    lease_token: Mapped[UUID] = mapped_column(Uuid())
    consumer_attempt: Mapped[int] = mapped_column(Integer)
    input_digest: Mapped[str] = mapped_column(String(64))
    content_digest: Mapped[str] = mapped_column(String(64))
    byte_length: Mapped[int] = mapped_column(Integer)
    canonical_result: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    quality: Mapped[str] = mapped_column(String(20))
    sampler: Mapped[str] = mapped_column(String(40))
    sealed: Mapped[bool] = mapped_column(Boolean)


class ProjectionZeroPivotModel(PremiumOwned):
    __tablename__ = "projection_zero_pivots"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_projection_zero_pivots_owner_id_account_id_id"
        ),
        UniqueConstraint(
            "result_id", "asset_index", name="uq_projection_zero_pivots_result_id_asset_index"
        ),
        CheckConstraint("asset_index BETWEEN 0 AND 11", name="index_bound"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "result_id"],
            [
                "projection_results.owner_id",
                "projection_results.account_id",
                "projection_results.id",
            ],
            ondelete="RESTRICT",
            name="fk_projection_zero_pivots_0_projection_results",
        ),
    )
    result_id: Mapped[UUID] = mapped_column(Uuid())
    asset_index: Mapped[int] = mapped_column(Integer)


class ProjectionDistributionModel(PremiumOwned):
    __tablename__ = "projection_distributions"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "account_id",
            "id",
            name="uq_projection_distributions_owner_id_account_id_id",
        ),
        UniqueConstraint(
            "result_id",
            "variant",
            "month",
            name="uq_projection_distributions_result_id_variant_month",
        ),
        CheckConstraint(
            "variant IN ('baseline','contribution_delta','mean_log_delta')", name="variant_allowed"
        ),
        CheckConstraint(
            "month BETWEEN 0 AND 600 AND nominal_mean>=0 AND real_mean>=0 AND fundi"
            "ng_failed_paths BETWEEN 0 AND 4096",
            name="bounds",
        ),
        CheckConstraint(
            "nominal_mean IS NULL OR (nominal_mean > '-Infinity'::numeric AND nomin"
            "al_mean < 'Infinity'::numeric)",
            name="nominal_mean_finite",
        ),
        CheckConstraint(
            "real_mean IS NULL OR (real_mean > '-Infinity'::numeric AND real_mean <"
            " 'Infinity'::numeric)",
            name="real_mean_finite",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "result_id"],
            [
                "projection_results.owner_id",
                "projection_results.account_id",
                "projection_results.id",
            ],
            ondelete="RESTRICT",
            name="fk_projection_distributions_0_projection_results",
        ),
    )
    result_id: Mapped[UUID] = mapped_column(Uuid())
    variant: Mapped[str] = mapped_column(String(24))
    month: Mapped[int] = mapped_column(Integer)
    nominal_mean: Mapped[Decimal] = mapped_column(ExactNumeric())
    real_mean: Mapped[Decimal] = mapped_column(ExactNumeric())
    funding_failed_paths: Mapped[int] = mapped_column(Integer)


class ProjectionDistributionQuantileModel(PremiumOwned):
    __tablename__ = "projection_distribution_quantiles"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "account_id",
            "id",
            name="uq_projection_distribution_quantiles_owner_id_account_id_id",
        ),
        UniqueConstraint(
            "distribution_id",
            "basis",
            "probability",
            name="uq_projection_distribution_quantiles_distribution_id_fdd448dadb",
        ),
        CheckConstraint("basis IN ('nominal','real')", name="basis_allowed"),
        CheckConstraint("probability IN (.05,.25,.50,.75,.95) AND value>=0", name="bounds"),
        CheckConstraint(
            "probability IS NULL OR (probability > '-Infinity'::numeric AND probabi"
            "lity < 'Infinity'::numeric)",
            name="probability_finite",
        ),
        CheckConstraint(
            "value IS NULL OR (value > '-Infinity'::numeric AND value < 'Infinity'::numeric)",
            name="value_finite",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "distribution_id"],
            [
                "projection_distributions.owner_id",
                "projection_distributions.account_id",
                "projection_distributions.id",
            ],
            ondelete="RESTRICT",
            name="fk_projection_distribution_quantiles_0_projection_distributions",
        ),
    )
    distribution_id: Mapped[UUID] = mapped_column(Uuid())
    basis: Mapped[str] = mapped_column(String(10))
    probability: Mapped[Decimal] = mapped_column(ExactNumeric())
    value: Mapped[Decimal] = mapped_column(ExactNumeric())


class ProjectionHistogramModel(PremiumOwned):
    __tablename__ = "projection_histograms"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_projection_histograms_owner_id_account_id_id"
        ),
        UniqueConstraint(
            "result_id", "variant", "basis", name="uq_projection_histograms_result_id_variant_basis"
        ),
        CheckConstraint(
            "variant IN ('baseline','contribution_delta','mean_log_delta')", name="variant_allowed"
        ),
        CheckConstraint("basis IN ('nominal','real')", name="basis_allowed"),
        CheckConstraint(
            "observed_minimum>=0 AND observed_maximum>=observed_minimum AND bin_cou"
            "nt BETWEEN 1 AND 20",
            name="bounds",
        ),
        CheckConstraint("boundary_rule='q18_enclosing_ceiling_v1'", name="rule_fixed"),
        CheckConstraint(
            "observed_minimum IS NULL OR (observed_minimum > '-Infinity'::numeric A"
            "ND observed_minimum < 'Infinity'::numeric)",
            name="observed_minimum_finite",
        ),
        CheckConstraint(
            "observed_maximum IS NULL OR (observed_maximum > '-Infinity'::numeric A"
            "ND observed_maximum < 'Infinity'::numeric)",
            name="observed_maximum_finite",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "result_id"],
            [
                "projection_results.owner_id",
                "projection_results.account_id",
                "projection_results.id",
            ],
            ondelete="RESTRICT",
            name="fk_projection_histograms_0_projection_results",
        ),
    )
    result_id: Mapped[UUID] = mapped_column(Uuid())
    variant: Mapped[str] = mapped_column(String(24))
    basis: Mapped[str] = mapped_column(String(10))
    observed_minimum: Mapped[Decimal] = mapped_column(ExactNumeric())
    observed_maximum: Mapped[Decimal] = mapped_column(ExactNumeric())
    bin_count: Mapped[int] = mapped_column(Integer)
    boundary_rule: Mapped[str] = mapped_column(String(40))


class ProjectionHistogramBinModel(PremiumOwned):
    __tablename__ = "projection_histogram_bins"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "account_id",
            "id",
            name="uq_projection_histogram_bins_owner_id_account_id_id",
        ),
        UniqueConstraint(
            "histogram_id", "bin_index", name="uq_projection_histogram_bins_histogram_id_bin_index"
        ),
        CheckConstraint(
            "bin_index BETWEEN 0 AND 19 AND lower>=0 AND upper>=lower AND count BETWEEN 0 AND 4096",
            name="bounds",
        ),
        CheckConstraint(
            "lower IS NULL OR (lower > '-Infinity'::numeric AND lower < 'Infinity'::numeric)",
            name="lower_finite",
        ),
        CheckConstraint(
            "upper IS NULL OR (upper > '-Infinity'::numeric AND upper < 'Infinity'::numeric)",
            name="upper_finite",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "histogram_id"],
            [
                "projection_histograms.owner_id",
                "projection_histograms.account_id",
                "projection_histograms.id",
            ],
            ondelete="RESTRICT",
            name="fk_projection_histogram_bins_0_projection_histograms",
        ),
    )
    histogram_id: Mapped[UUID] = mapped_column(Uuid())
    bin_index: Mapped[int] = mapped_column(Integer)
    lower: Mapped[Decimal] = mapped_column(ExactNumeric())
    upper: Mapped[Decimal] = mapped_column(ExactNumeric())
    upper_inclusive: Mapped[bool] = mapped_column(Boolean)
    count: Mapped[int] = mapped_column(Integer)


class ProjectionGoalAnalysisModel(PremiumOwned):
    __tablename__ = "projection_goal_analyses"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "account_id",
            "id",
            name="uq_projection_goal_analyses_owner_id_account_id_id",
        ),
        UniqueConstraint(
            "result_id", "variant", name="uq_projection_goal_analyses_result_id_variant"
        ),
        CheckConstraint(
            "variant IN ('baseline','contribution_delta','mean_log_delta')", name="variant_allowed"
        ),
        CheckConstraint("basis IN ('nominal','real')", name="basis_allowed"),
        CheckConstraint(
            "target>=0 AND paths BETWEEN 1 AND 4096 AND successes BETWEEN 0 AND pat"
            "hs AND probability BETWEEN 0 AND 1 AND interval_low BETWEEN 0 AND prob"
            "ability AND interval_high BETWEEN probability AND 1 AND probability_ob"
            "jective BETWEEN 0 AND 1 AND mean_shortfall>=0 AND funding_failed_paths"
            " BETWEEN 0 AND paths AND successes<=paths-funding_failed_paths AND obj"
            "ective_met=(probability>=probability_objective)",
            name="bounds",
        ),
        CheckConstraint(
            "method='goal_analysis_v1' AND interval_method='wilson_95_v1'", name="method_fixed"
        ),
        CheckConstraint(
            "target IS NULL OR (target > '-Infinity'::numeric AND target < 'Infinity'::numeric)",
            name="target_finite",
        ),
        CheckConstraint(
            "probability IS NULL OR (probability > '-Infinity'::numeric AND probabi"
            "lity < 'Infinity'::numeric)",
            name="probability_finite",
        ),
        CheckConstraint(
            "interval_low IS NULL OR (interval_low > '-Infinity'::numeric AND inter"
            "val_low < 'Infinity'::numeric)",
            name="interval_low_finite",
        ),
        CheckConstraint(
            "interval_high IS NULL OR (interval_high > '-Infinity'::numeric AND int"
            "erval_high < 'Infinity'::numeric)",
            name="interval_high_finite",
        ),
        CheckConstraint(
            "probability_objective IS NULL OR (probability_objective > '-Infinity':"
            ":numeric AND probability_objective < 'Infinity'::numeric)",
            name="probability_objective_finite",
        ),
        CheckConstraint(
            "mean_shortfall IS NULL OR (mean_shortfall > '-Infinity'::numeric AND m"
            "ean_shortfall < 'Infinity'::numeric)",
            name="mean_shortfall_finite",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "result_id"],
            [
                "projection_results.owner_id",
                "projection_results.account_id",
                "projection_results.id",
            ],
            ondelete="RESTRICT",
            name="fk_projection_goal_analyses_0_projection_results",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "goal_version_id"],
            ["goal_versions.owner_id", "goal_versions.account_id", "goal_versions.id"],
            ondelete="RESTRICT",
            name="fk_projection_goal_analyses_1_goal_versions",
        ),
    )
    result_id: Mapped[UUID] = mapped_column(Uuid())
    goal_version_id: Mapped[UUID] = mapped_column(Uuid())
    variant: Mapped[str] = mapped_column(String(24))
    basis: Mapped[str] = mapped_column(String(10))
    target: Mapped[Decimal] = mapped_column(ExactNumeric())
    paths: Mapped[int] = mapped_column(Integer)
    successes: Mapped[int] = mapped_column(Integer)
    probability: Mapped[Decimal] = mapped_column(ExactNumeric())
    interval_low: Mapped[Decimal] = mapped_column(ExactNumeric())
    interval_high: Mapped[Decimal] = mapped_column(ExactNumeric())
    probability_objective: Mapped[Decimal] = mapped_column(ExactNumeric())
    mean_shortfall: Mapped[Decimal] = mapped_column(ExactNumeric())
    objective_met: Mapped[bool] = mapped_column(Boolean)
    funding_failed_paths: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(40))
    interval_method: Mapped[str] = mapped_column(String(40))


class ProjectionGoalShortfallQuantileModel(PremiumOwned):
    __tablename__ = "projection_goal_shortfall_quantiles"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "account_id",
            "id",
            name="uq_projection_goal_shortfall_quantiles_owner_id_account_id_id",
        ),
        UniqueConstraint(
            "analysis_id",
            "probability",
            name="uq_projection_goal_shortfall_quantiles_analysis_id_probability",
        ),
        CheckConstraint("probability IN (.05,.25,.50,.75,.95) AND value>=0", name="bounds"),
        CheckConstraint(
            "probability IS NULL OR (probability > '-Infinity'::numeric AND probabi"
            "lity < 'Infinity'::numeric)",
            name="probability_finite",
        ),
        CheckConstraint(
            "value IS NULL OR (value > '-Infinity'::numeric AND value < 'Infinity'::numeric)",
            name="value_finite",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "analysis_id"],
            [
                "projection_goal_analyses.owner_id",
                "projection_goal_analyses.account_id",
                "projection_goal_analyses.id",
            ],
            ondelete="RESTRICT",
            name="fk_projection_goal_shortfall_quantiles_0_projection__ed20457ecb",
        ),
    )
    analysis_id: Mapped[UUID] = mapped_column(Uuid())
    probability: Mapped[Decimal] = mapped_column(ExactNumeric())
    value: Mapped[Decimal] = mapped_column(ExactNumeric())


PROJECTION_MODELS = (
    AssumptionSetModel,
    GoalModel,
    AssumptionVersionModel,
    ProjectionAssumptionAssetModel,
    ProjectionCorrelationCellModel,
    ProjectionCalibrationPinModel,
    GoalVersionModel,
    ProjectionGoalPauseModel,
    ProjectionGoalScheduleEntryModel,
    ProjectionRunModel,
    ProjectionInputModel,
    ProjectionRunAllocationModel,
    ProjectionCalendarBoundaryModel,
    ProjectionRunPauseModel,
    ProjectionRunScheduleEntryModel,
    ProjectionRunSourceModel,
    ProjectionSourceProofModel,
    ProjectionSourceLicenseModel,
    ProjectionChunkModel,
    ProjectionPathModel,
    ProjectionPointModel,
    ProjectionPointAssetModel,
    ProjectionResultModel,
    ProjectionZeroPivotModel,
    ProjectionDistributionModel,
    ProjectionDistributionQuantileModel,
    ProjectionHistogramModel,
    ProjectionHistogramBinModel,
    ProjectionGoalAnalysisModel,
    ProjectionGoalShortfallQuantileModel,
)


class ProjectionRetainedSourceModel(PremiumOwned):
    """Exact owned physical source membership, removed after all dependent copies."""

    __tablename__ = "projection_retained_source_memberships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_projection_retained_sources_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["account_id"],
            ["broker_accounts.id"],
            name="fk_projection_retained_sources_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["projection_runs.owner_id", "projection_runs.account_id", "projection_runs.id"],
            name="fk_projection_retained_sources_run",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "run_id", "source_kind", "source_id", name="uq_projection_retained_source"
        ),
        CheckConstraint(
            "source_kind IN ('price','fx','corporate_action','benchmark',"
            "'historical','license','classification')",
            name="kind_allowed",
        ),
        Index("ix_projection_retained_parent", "owner_id", "source_kind", "source_id", "run_id"),
        Index("ix_projection_retained_cleanup", "owner_id", "account_id", "run_id", "id"),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid())
    source_kind: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[UUID] = mapped_column(Uuid())
    original_created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    owner_id: Mapped[UUID] = mapped_column(Uuid())
    account_id: Mapped[UUID] = mapped_column(Uuid())


# Exact-parent cleanup keysets align LIMIT with the physical index order.
Index(
    "ix_projection_inputs_purge_key",
    ProjectionInputModel.owner_id,
    ProjectionInputModel.account_id,
    ProjectionInputModel.run_id,
    ProjectionInputModel.id,
)
Index(
    "ix_projection_run_allocations_purge_key",
    ProjectionRunAllocationModel.owner_id,
    ProjectionRunAllocationModel.account_id,
    ProjectionRunAllocationModel.run_id,
    ProjectionRunAllocationModel.id,
)
Index(
    "ix_projection_calendar_boundaries_purge_key",
    ProjectionCalendarBoundaryModel.owner_id,
    ProjectionCalendarBoundaryModel.account_id,
    ProjectionCalendarBoundaryModel.run_id,
    ProjectionCalendarBoundaryModel.id,
)
Index(
    "ix_projection_run_pauses_purge_key",
    ProjectionRunPauseModel.owner_id,
    ProjectionRunPauseModel.account_id,
    ProjectionRunPauseModel.run_id,
    ProjectionRunPauseModel.id,
)
Index(
    "ix_projection_run_schedule_entries_purge_key",
    ProjectionRunScheduleEntryModel.owner_id,
    ProjectionRunScheduleEntryModel.account_id,
    ProjectionRunScheduleEntryModel.run_id,
    ProjectionRunScheduleEntryModel.id,
)
Index(
    "ix_projection_source_proofs_purge_key",
    ProjectionSourceProofModel.owner_id,
    ProjectionSourceProofModel.account_id,
    ProjectionSourceProofModel.run_id,
    ProjectionSourceProofModel.id,
)
Index(
    "ix_projection_chunks_purge_key",
    ProjectionChunkModel.owner_id,
    ProjectionChunkModel.account_id,
    ProjectionChunkModel.run_id,
    ProjectionChunkModel.id,
)
Index(
    "ix_projection_paths_purge_key",
    ProjectionPathModel.owner_id,
    ProjectionPathModel.account_id,
    ProjectionPathModel.run_id,
    ProjectionPathModel.id,
)
Index(
    "ix_projection_points_purge_key",
    ProjectionPointModel.owner_id,
    ProjectionPointModel.account_id,
    ProjectionPointModel.run_id,
    ProjectionPointModel.id,
)
Index(
    "ix_projection_point_assets_purge_key",
    ProjectionPointAssetModel.owner_id,
    ProjectionPointAssetModel.account_id,
    ProjectionPointAssetModel.run_id,
    ProjectionPointAssetModel.id,
)
Index(
    "ix_projection_results_purge_key",
    ProjectionResultModel.owner_id,
    ProjectionResultModel.account_id,
    ProjectionResultModel.run_id,
    ProjectionResultModel.id,
)
Index(
    "ix_projection_zero_pivots_purge_key",
    ProjectionZeroPivotModel.owner_id,
    ProjectionZeroPivotModel.account_id,
    ProjectionZeroPivotModel.result_id,
    ProjectionZeroPivotModel.id,
)
Index(
    "ix_projection_distributions_purge_key",
    ProjectionDistributionModel.owner_id,
    ProjectionDistributionModel.account_id,
    ProjectionDistributionModel.result_id,
    ProjectionDistributionModel.id,
)
Index(
    "ix_projection_histograms_purge_key",
    ProjectionHistogramModel.owner_id,
    ProjectionHistogramModel.account_id,
    ProjectionHistogramModel.result_id,
    ProjectionHistogramModel.id,
)
Index(
    "ix_projection_goal_analyses_purge_key",
    ProjectionGoalAnalysisModel.owner_id,
    ProjectionGoalAnalysisModel.account_id,
    ProjectionGoalAnalysisModel.result_id,
    ProjectionGoalAnalysisModel.id,
)
Index(
    "ix_projection_distribution_quantiles_purge_key",
    ProjectionDistributionQuantileModel.owner_id,
    ProjectionDistributionQuantileModel.account_id,
    ProjectionDistributionQuantileModel.distribution_id,
    ProjectionDistributionQuantileModel.id,
)
Index(
    "ix_projection_histogram_bins_purge_key",
    ProjectionHistogramBinModel.owner_id,
    ProjectionHistogramBinModel.account_id,
    ProjectionHistogramBinModel.histogram_id,
    ProjectionHistogramBinModel.id,
)
Index(
    "ix_projection_goal_shortfall_quantiles_purge_key",
    ProjectionGoalShortfallQuantileModel.owner_id,
    ProjectionGoalShortfallQuantileModel.account_id,
    ProjectionGoalShortfallQuantileModel.analysis_id,
    ProjectionGoalShortfallQuantileModel.id,
)
Index(
    "ix_projection_paths_purge_fk",
    ProjectionPathModel.owner_id,
    ProjectionPathModel.account_id,
    ProjectionPathModel.chunk_id,
)
Index(
    "ix_projection_points_purge_fk",
    ProjectionPointModel.owner_id,
    ProjectionPointModel.account_id,
    ProjectionPointModel.path_id,
)
Index(
    "ix_projection_point_assets_purge_fk",
    ProjectionPointAssetModel.owner_id,
    ProjectionPointAssetModel.account_id,
    ProjectionPointAssetModel.point_id,
)
