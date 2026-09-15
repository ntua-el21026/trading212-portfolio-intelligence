"""Normalized immutable projection/goal storage and shared premium publication guards.

Revision ID: 20260915_0022
Revises: 20260915_0021
"""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0022"
down_revision = "20260915_0021"
branch_labels = None
depends_on = None

_DDL = (
    r"""CREATE TABLE assumption_sets (
 "name" VARCHAR(120) NOT NULL,
 "revision" INTEGER NOT NULL,
 "updated_at" TIMESTAMP WITH TIME ZONE NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_assumption_sets_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT ck_assumption_sets_revision_bound CHECK (revision BETWEEN 1 AND 512),
 CONSTRAINT ck_assumption_sets_name_bound CHECK (char_length(name) BETWEEN 1 AND 120),
 CONSTRAINT fk_assumption_sets_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_assumption_sets_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_assumption_sets PRIMARY KEY (id)
)""",
    r"""CREATE INDEX ix_assumption_sets_0 ON assumption_sets (owner_id, account_id, created_at, id)""",
    r"""CREATE TABLE goals (
 "name" VARCHAR(120) NOT NULL,
 "revision" INTEGER NOT NULL,
 "updated_at" TIMESTAMP WITH TIME ZONE NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_goals_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT ck_goals_revision_bound CHECK (revision BETWEEN 1 AND 512),
 CONSTRAINT ck_goals_name_bound CHECK (char_length(name) BETWEEN 1 AND 120),
 CONSTRAINT fk_goals_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_goals_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_goals PRIMARY KEY (id)
)""",
    r"""CREATE INDEX ix_goals_0 ON goals (owner_id, account_id, created_at, id)""",
    r"""CREATE TABLE assumption_versions (
 "set_id" UUID NOT NULL,
 "version_number" INTEGER NOT NULL,
 "predecessor_id" UUID,
 "name" VARCHAR(120) NOT NULL,
 "description" VARCHAR(1024) NOT NULL,
 "content_digest" VARCHAR(64) NOT NULL,
 "sealed" BOOLEAN NOT NULL,
 "reporting_currency" VARCHAR(3) NOT NULL,
 "annual_inflation" NUMERIC(38,18) NOT NULL,
 "annual_fee" NUMERIC(38,18) NOT NULL,
 "annual_tax_drag" NUMERIC(38,18),
 "rebalance" VARCHAR(10) NOT NULL,
 "asset_count" INTEGER NOT NULL,
 "calibration_count" INTEGER NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_assumption_versions_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_assumption_versions_set_id_version_number UNIQUE ("set_id", "version_number"),
 CONSTRAINT uq_assumption_versions_owner_id_account_id_set_id_id UNIQUE ("owner_id", "account_id", "set_id", "id"),
 CONSTRAINT uq_assumption_versions_owner_id_account_id_id_content_digest UNIQUE ("owner_id", "account_id", "id", "content_digest"),
 CONSTRAINT ck_assumption_versions_revision_bound CHECK (version_number BETWEEN 1 AND 512 AND ((version_number=1)=(predecessor_id IS NULL))),
 CONSTRAINT ck_assumption_versions_name_bound CHECK (char_length(name) BETWEEN 1 AND 120),
 CONSTRAINT ck_assumption_versions_content_digest_format CHECK (content_digest ~ '^[0-9a-f]{64}$'),
 CONSTRAINT ck_assumption_versions_currency_format CHECK (reporting_currency ~ '^[A-Z]{3}$'),
 CONSTRAINT ck_assumption_versions_assumption_bounds CHECK (annual_inflation BETWEEN -.1 AND .5 AND annual_fee BETWEEN 0 AND .2 AND (annual_tax_drag IS NULL OR annual_tax_drag BETWEEN 0 AND .2) AND rebalance IN ('monthly','annual','none') AND asset_count BETWEEN 1 AND 12 AND calibration_count BETWEEN 0 AND 256),
 CONSTRAINT ck_assumption_versions_annual_inflation_finite CHECK (annual_inflation IS NULL OR (annual_inflation > '-Infinity'::numeric AND annual_inflation < 'Infinity'::numeric)),
 CONSTRAINT ck_assumption_versions_annual_fee_finite CHECK (annual_fee IS NULL OR (annual_fee > '-Infinity'::numeric AND annual_fee < 'Infinity'::numeric)),
 CONSTRAINT ck_assumption_versions_annual_tax_drag_finite CHECK (annual_tax_drag IS NULL OR (annual_tax_drag > '-Infinity'::numeric AND annual_tax_drag < 'Infinity'::numeric)),
 CONSTRAINT fk_assumption_versions_0_assumption_sets FOREIGN KEY ("owner_id", "account_id", "set_id") REFERENCES assumption_sets ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_assumption_versions_1_assumption_versions FOREIGN KEY ("owner_id", "account_id", "set_id", "predecessor_id") REFERENCES assumption_versions ("owner_id", "account_id", "set_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_assumption_versions_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_assumption_versions_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_assumption_versions PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_assumption_assets (
 "version_id" UUID NOT NULL,
 "asset_index" INTEGER NOT NULL,
 "asset_key" VARCHAR(120) NOT NULL,
 "annual_mean_log_return" NUMERIC(38,18) NOT NULL,
 "annual_volatility" NUMERIC(38,18) NOT NULL,
 "weight" NUMERIC(38,18) NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_assumption_assets_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_assumption_assets_version_id_asset_index UNIQUE ("version_id", "asset_index"),
 CONSTRAINT uq_projection_assumption_assets_version_id_asset_key UNIQUE ("version_id", "asset_key"),
 CONSTRAINT uq_projection_assumption_assets_owner_id_account_id__c6f7ae7ff0 UNIQUE ("owner_id", "account_id", "version_id", "asset_index"),
 CONSTRAINT ck_projection_assumption_assets_index_bound CHECK (asset_index BETWEEN 0 AND 11),
 CONSTRAINT ck_projection_assumption_assets_key_format CHECK (asset_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$'),
 CONSTRAINT ck_projection_assumption_assets_amount_bounds CHECK (annual_mean_log_return BETWEEN -.5 AND .5 AND annual_volatility BETWEEN 0 AND 1 AND weight BETWEEN 0 AND 1),
 CONSTRAINT ck_projection_assumption_assets_annual_mean_log_return_finite CHECK (annual_mean_log_return IS NULL OR (annual_mean_log_return > '-Infinity'::numeric AND annual_mean_log_return < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_assumption_assets_annual_volatility_finite CHECK (annual_volatility IS NULL OR (annual_volatility > '-Infinity'::numeric AND annual_volatility < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_assumption_assets_weight_finite CHECK (weight IS NULL OR (weight > '-Infinity'::numeric AND weight < 'Infinity'::numeric)),
 CONSTRAINT fk_projection_assumption_assets_0_assumption_versions FOREIGN KEY ("owner_id", "account_id", "version_id") REFERENCES assumption_versions ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_assumption_assets_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_assumption_assets_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_assumption_assets PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_correlation_cells (
 "version_id" UUID NOT NULL,
 "row_index" INTEGER NOT NULL,
 "column_index" INTEGER NOT NULL,
 "value" NUMERIC(38,18) NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_correlation_cells_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_correlation_cells_version_id_row_index_1fc125c0fd UNIQUE ("version_id", "row_index", "column_index"),
 CONSTRAINT ck_projection_correlation_cells_indices_bound CHECK (row_index BETWEEN 0 AND 11 AND column_index BETWEEN 0 AND 11),
 CONSTRAINT ck_projection_correlation_cells_value_bound CHECK (value BETWEEN -1 AND 1 AND (row_index<>column_index OR value=1)),
 CONSTRAINT ck_projection_correlation_cells_value_finite CHECK (value IS NULL OR (value > '-Infinity'::numeric AND value < 'Infinity'::numeric)),
 CONSTRAINT fk_projection_correlation_cells_0_assumption_versions FOREIGN KEY ("owner_id", "account_id", "version_id") REFERENCES assumption_versions ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_correlation_cells_1_projection_assumption_assets FOREIGN KEY ("owner_id", "account_id", "version_id", "row_index") REFERENCES projection_assumption_assets ("owner_id", "account_id", "version_id", "asset_index") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_correlation_cells_2_projection_assumption_assets FOREIGN KEY ("owner_id", "account_id", "version_id", "column_index") REFERENCES projection_assumption_assets ("owner_id", "account_id", "version_id", "asset_index") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_correlation_cells_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_correlation_cells_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_correlation_cells PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_calibration_pins (
 "version_id" UUID NOT NULL,
 "subject_id" UUID NOT NULL,
 "content_digest" VARCHAR(64) NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_calibration_pins_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_calibration_pins_version_id_subject_id UNIQUE ("version_id", "subject_id"),
 CONSTRAINT uq_projection_calibration_pins_owner_id_account_id_v_f26056c98a UNIQUE ("owner_id", "account_id", "version_id", "subject_id", "content_digest"),
 CONSTRAINT ck_projection_calibration_pins_content_digest_format CHECK (content_digest ~ '^[0-9a-f]{64}$'),
 CONSTRAINT fk_projection_calibration_pins_0_assumption_versions FOREIGN KEY ("owner_id", "account_id", "version_id") REFERENCES assumption_versions ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_calibration_pins_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_calibration_pins_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_calibration_pins PRIMARY KEY (id)
)""",
    r"""CREATE TABLE goal_versions (
 "goal_id" UUID NOT NULL,
 "version_number" INTEGER NOT NULL,
 "predecessor_id" UUID,
 "name" VARCHAR(120) NOT NULL,
 "description" VARCHAR(1024) NOT NULL,
 "content_digest" VARCHAR(64) NOT NULL,
 "sealed" BOOLEAN NOT NULL,
 "assumption_version_id" UUID NOT NULL,
 "reporting_currency" VARCHAR(3) NOT NULL,
 "target" NUMERIC(38,18) NOT NULL,
 "target_date" DATE NOT NULL,
 "months" INTEGER NOT NULL,
 "basis" VARCHAR(10) NOT NULL,
 "probability_objective" NUMERIC(38,18) NOT NULL,
 "base_monthly" NUMERIC(38,18) NOT NULL,
 "annual_growth" NUMERIC(38,18) NOT NULL,
 "pause_count" INTEGER NOT NULL,
 "entry_count" INTEGER NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_goal_versions_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_goal_versions_goal_id_version_number UNIQUE ("goal_id", "version_number"),
 CONSTRAINT uq_goal_versions_owner_id_account_id_goal_id_id UNIQUE ("owner_id", "account_id", "goal_id", "id"),
 CONSTRAINT uq_goal_versions_owner_id_account_id_id_content_digest UNIQUE ("owner_id", "account_id", "id", "content_digest"),
 CONSTRAINT ck_goal_versions_revision_bound CHECK (version_number BETWEEN 1 AND 512 AND ((version_number=1)=(predecessor_id IS NULL))),
 CONSTRAINT ck_goal_versions_name_bound CHECK (char_length(name) BETWEEN 1 AND 120),
 CONSTRAINT ck_goal_versions_content_digest_format CHECK (content_digest ~ '^[0-9a-f]{64}$'),
 CONSTRAINT ck_goal_versions_currency_format CHECK (reporting_currency ~ '^[A-Z]{3}$'),
 CONSTRAINT ck_goal_versions_goal_bounds CHECK (target>=0 AND months BETWEEN 1 AND 600 AND basis IN ('nominal','real') AND probability_objective BETWEEN 0 AND 1 AND base_monthly>=0 AND annual_growth BETWEEN -1 AND 1 AND pause_count>=0 AND entry_count>=0 AND pause_count+entry_count<=128),
 CONSTRAINT ck_goal_versions_target_finite CHECK (target IS NULL OR (target > '-Infinity'::numeric AND target < 'Infinity'::numeric)),
 CONSTRAINT ck_goal_versions_probability_objective_finite CHECK (probability_objective IS NULL OR (probability_objective > '-Infinity'::numeric AND probability_objective < 'Infinity'::numeric)),
 CONSTRAINT ck_goal_versions_base_monthly_finite CHECK (base_monthly IS NULL OR (base_monthly > '-Infinity'::numeric AND base_monthly < 'Infinity'::numeric)),
 CONSTRAINT ck_goal_versions_annual_growth_finite CHECK (annual_growth IS NULL OR (annual_growth > '-Infinity'::numeric AND annual_growth < 'Infinity'::numeric)),
 CONSTRAINT ck_goal_versions_target_date_date_bound CHECK ("target_date" BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
 CONSTRAINT fk_goal_versions_0_goals FOREIGN KEY ("owner_id", "account_id", "goal_id") REFERENCES goals ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_goal_versions_1_assumption_versions FOREIGN KEY ("owner_id", "account_id", "assumption_version_id") REFERENCES assumption_versions ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_goal_versions_2_goal_versions FOREIGN KEY ("owner_id", "account_id", "goal_id", "predecessor_id") REFERENCES goal_versions ("owner_id", "account_id", "goal_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_goal_versions_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_goal_versions_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_goal_versions PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_goal_pauses (
 "version_id" UUID NOT NULL,
 "on" DATE NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_goal_pauses_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_goal_pauses_version_id_on UNIQUE ("version_id", "on"),
 CONSTRAINT ck_projection_goal_pauses_on_date_bound CHECK ("on" BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
 CONSTRAINT fk_projection_goal_pauses_0_goal_versions FOREIGN KEY ("owner_id", "account_id", "version_id") REFERENCES goal_versions ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_goal_pauses_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_goal_pauses_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_goal_pauses PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_goal_schedule_entries (
 "version_id" UUID NOT NULL,
 "entry_key" VARCHAR(120) NOT NULL,
 "on" DATE NOT NULL,
 "kind" VARCHAR(12) NOT NULL,
 "value" NUMERIC(38,18) NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_goal_schedule_entries_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_goal_schedule_entries_version_id_entry_key UNIQUE ("version_id", "entry_key"),
 CONSTRAINT ck_projection_goal_schedule_entries_kind_allowed CHECK (kind IN ('lump_sum','withdrawal')),
 CONSTRAINT ck_projection_goal_schedule_entries_key_format CHECK (entry_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$'),
 CONSTRAINT ck_projection_goal_schedule_entries_value_bound CHECK (value>=0),
 CONSTRAINT ck_projection_goal_schedule_entries_value_finite CHECK (value IS NULL OR (value > '-Infinity'::numeric AND value < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_goal_schedule_entries_on_date_bound CHECK ("on" BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
 CONSTRAINT fk_projection_goal_schedule_entries_0_goal_versions FOREIGN KEY ("owner_id", "account_id", "version_id") REFERENCES goal_versions ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_goal_schedule_entries_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_goal_schedule_entries_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_goal_schedule_entries PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_runs (
 "assumption_version_id" UUID NOT NULL,
 "assumption_digest" VARCHAR(64) NOT NULL,
 "goal_version_id" UUID,
 "goal_digest" VARCHAR(64),
 "numerical_input_digest" VARCHAR(64) NOT NULL,
 "capture_digest" VARCHAR(64) NOT NULL,
 "seed" BIGINT NOT NULL,
 "months" INTEGER NOT NULL,
 "path_count" INTEGER NOT NULL,
 "asset_count" INTEGER NOT NULL,
 "retained_point_count" INTEGER NOT NULL,
 "variant_count" INTEGER NOT NULL,
 "source_count" INTEGER NOT NULL,
 "stored_bytes" BIGINT NOT NULL DEFAULT 0,
 "payload_rows" INTEGER NOT NULL DEFAULT 0,
 "retained_source_rows" INTEGER NOT NULL DEFAULT 0,
 "retained_source_bytes" BIGINT NOT NULL DEFAULT 0,
 "initial_kind" VARCHAR(20) NOT NULL,
 "snapshot_id" UUID,
 "snapshot_digest" VARCHAR(64),
 "snapshot_valuation_at" TIMESTAMP WITH TIME ZONE,
 "anchor_date" DATE NOT NULL,
 "reporting_currency" VARCHAR(3) NOT NULL,
 "calendar_rule" VARCHAR(40) NOT NULL,
 "sealed" BOOLEAN NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_runs_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_runs_owner_id_account_id_id_numerical__7391546e3f UNIQUE ("owner_id", "account_id", "id", "numerical_input_digest"),
 CONSTRAINT ck_projection_runs_assumption_digest_format CHECK (assumption_digest ~ '^[0-9a-f]{64}$'),
 CONSTRAINT ck_projection_runs_goal_digest_format CHECK (goal_digest ~ '^[0-9a-f]{64}$'),
 CONSTRAINT ck_projection_runs_numerical_input_digest_format CHECK (numerical_input_digest ~ '^[0-9a-f]{64}$'),
 CONSTRAINT ck_projection_runs_capture_digest_format CHECK (capture_digest ~ '^[0-9a-f]{64}$'),
 CONSTRAINT ck_projection_runs_snapshot_digest_format CHECK (snapshot_digest ~ '^[0-9a-f]{64}$'),
 CONSTRAINT ck_projection_runs_currency_format CHECK (reporting_currency ~ '^[A-Z]{3}$'),
 CONSTRAINT ck_projection_runs_goal_pin CHECK ((goal_version_id IS NULL)=(goal_digest IS NULL)),
 CONSTRAINT ck_projection_runs_input_bounds CHECK (seed BETWEEN 0 AND 4294967295 AND months BETWEEN 1 AND 600 AND path_count BETWEEN 1 AND 4096 AND asset_count BETWEEN 1 AND 12 AND retained_point_count BETWEEN 2 AND 121 AND retained_point_count<=months+1 AND variant_count IN (1,3) AND asset_count*months*path_count*variant_count<=1000000 AND source_count BETWEEN 0 AND 257),
 CONSTRAINT ck_projection_runs_initial_pin CHECK ((initial_kind='modeled_value' AND snapshot_id IS NULL AND snapshot_digest IS NULL AND snapshot_valuation_at IS NULL) OR (initial_kind='observed_snapshot' AND snapshot_id IS NOT NULL AND snapshot_digest IS NOT NULL AND snapshot_valuation_at IS NOT NULL AND anchor_date=(snapshot_valuation_at AT TIME ZONE 'UTC')::date)),
 CONSTRAINT ck_projection_runs_calendar_rule CHECK (calendar_rule='calendar_anniversary_clamped_v1'),
 CONSTRAINT ck_projection_runs_anchor_date_date_bound CHECK ("anchor_date" BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
 CONSTRAINT fk_projection_runs_0_premium_runs FOREIGN KEY ("owner_id", "account_id", "id") REFERENCES premium_runs ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_runs_1_assumption_versions FOREIGN KEY ("owner_id", "account_id", "assumption_version_id", "assumption_digest") REFERENCES assumption_versions ("owner_id", "account_id", "id", "content_digest") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_runs_2_goal_versions FOREIGN KEY ("owner_id", "account_id", "goal_version_id", "goal_digest") REFERENCES goal_versions ("owner_id", "account_id", "id", "content_digest") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_runs_3_portfolio_snapshots FOREIGN KEY ("snapshot_id") REFERENCES portfolio_snapshots ("id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_runs_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_runs_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_runs PRIMARY KEY (id)
,
 CONSTRAINT ck_projection_runs_physical_counter_bound CHECK(stored_bytes BETWEEN 0 AND 33554432 AND payload_rows>=0 AND retained_source_rows BETWEEN 0 AND 100000 AND retained_source_bytes>=0 AND retained_source_bytes<=stored_bytes AND ((retained_source_rows=0)=(retained_source_bytes=0)) AND (payload_rows<>0 OR stored_bytes=retained_source_bytes))
)""",
    r"""CREATE TABLE projection_inputs (
 "run_id" UUID NOT NULL,
 "initial_value" NUMERIC(38,18) NOT NULL,
 "base_monthly" NUMERIC(38,18) NOT NULL,
 "annual_growth" NUMERIC(38,18) NOT NULL,
 "contribution_delta" NUMERIC(38,18),
 "annual_mean_log_delta" NUMERIC(38,18),
 "pause_count" INTEGER NOT NULL,
 "entry_count" INTEGER NOT NULL,
 "capture_bytes" INTEGER NOT NULL,
 "input_bytes" INTEGER NOT NULL,
 "canonical_capture" BYTEA NOT NULL,
 "canonical_input" BYTEA NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_inputs_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_inputs_run_id UNIQUE ("run_id"),
 CONSTRAINT ck_projection_inputs_amount_bounds CHECK (initial_value>=0 AND base_monthly>=0 AND annual_growth BETWEEN -1 AND 1),
 CONSTRAINT ck_projection_inputs_sensitivity_pair CHECK ((contribution_delta IS NULL)=(annual_mean_log_delta IS NULL)),
 CONSTRAINT ck_projection_inputs_schedule_bound CHECK (pause_count>=0 AND entry_count>=0 AND pause_count+entry_count<=128),
 CONSTRAINT ck_projection_inputs_bytes_bound CHECK (capture_bytes BETWEEN 1 AND 33554432 AND input_bytes BETWEEN 1 AND 33554432 AND octet_length(canonical_capture)=capture_bytes AND octet_length(canonical_input)=input_bytes AND capture_bytes+input_bytes<=33554432),
 CONSTRAINT ck_projection_inputs_initial_value_finite CHECK (initial_value IS NULL OR (initial_value > '-Infinity'::numeric AND initial_value < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_inputs_base_monthly_finite CHECK (base_monthly IS NULL OR (base_monthly > '-Infinity'::numeric AND base_monthly < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_inputs_annual_growth_finite CHECK (annual_growth IS NULL OR (annual_growth > '-Infinity'::numeric AND annual_growth < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_inputs_contribution_delta_finite CHECK (contribution_delta IS NULL OR (contribution_delta > '-Infinity'::numeric AND contribution_delta < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_inputs_annual_mean_log_delta_finite CHECK (annual_mean_log_delta IS NULL OR (annual_mean_log_delta > '-Infinity'::numeric AND annual_mean_log_delta < 'Infinity'::numeric)),
 CONSTRAINT fk_projection_inputs_0_projection_runs FOREIGN KEY ("owner_id", "account_id", "run_id") REFERENCES projection_runs ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_inputs_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_inputs_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_inputs PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_run_allocations (
 "run_id" UUID NOT NULL,
 "asset_index" INTEGER NOT NULL,
 "asset_key" VARCHAR(120) NOT NULL,
 "weight" NUMERIC(38,18) NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_run_allocations_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_run_allocations_run_id_asset_index UNIQUE ("run_id", "asset_index"),
 CONSTRAINT uq_projection_run_allocations_run_id_asset_key UNIQUE ("run_id", "asset_key"),
 CONSTRAINT uq_projection_run_allocations_owner_id_account_id_ru_2a094e5b4f UNIQUE ("owner_id", "account_id", "run_id", "asset_index"),
 CONSTRAINT ck_projection_run_allocations_index_bound CHECK (asset_index BETWEEN 0 AND 11),
 CONSTRAINT ck_projection_run_allocations_weight_bound CHECK (weight BETWEEN 0 AND 1),
 CONSTRAINT ck_projection_run_allocations_weight_finite CHECK (weight IS NULL OR (weight > '-Infinity'::numeric AND weight < 'Infinity'::numeric)),
 CONSTRAINT fk_projection_run_allocations_0_projection_runs FOREIGN KEY ("owner_id", "account_id", "run_id") REFERENCES projection_runs ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_run_allocations_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_run_allocations_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_run_allocations PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_calendar_boundaries (
 "run_id" UUID NOT NULL,
 "month" INTEGER NOT NULL,
 "on" DATE NOT NULL,
 "point_index" INTEGER,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_calendar_boundaries_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_calendar_boundaries_run_id_month UNIQUE ("run_id", "month"),
 CONSTRAINT uq_projection_calendar_boundaries_run_id_on UNIQUE ("run_id", "on"),
 CONSTRAINT uq_projection_calendar_boundaries_run_id_point_index UNIQUE ("run_id", "point_index"),
 CONSTRAINT uq_projection_calendar_boundaries_owner_id_account_i_67e9884add UNIQUE ("owner_id", "account_id", "run_id", "month"),
 CONSTRAINT ck_projection_calendar_boundaries_index_bound CHECK (month BETWEEN 0 AND 600 AND (point_index IS NULL OR point_index BETWEEN 0 AND 120)),
 CONSTRAINT ck_projection_calendar_boundaries_on_date_bound CHECK ("on" BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
 CONSTRAINT fk_projection_calendar_boundaries_0_projection_runs FOREIGN KEY ("owner_id", "account_id", "run_id") REFERENCES projection_runs ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_calendar_boundaries_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_calendar_boundaries_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_calendar_boundaries PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_run_pauses (
 "run_id" UUID NOT NULL,
 "on" DATE NOT NULL,
 "month" INTEGER NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_run_pauses_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_run_pauses_run_id_on UNIQUE ("run_id", "on"),
 CONSTRAINT uq_projection_run_pauses_run_id_month UNIQUE ("run_id", "month"),
 CONSTRAINT ck_projection_run_pauses_month_bound CHECK (month BETWEEN 1 AND 600),
 CONSTRAINT ck_projection_run_pauses_on_date_bound CHECK ("on" BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
 CONSTRAINT fk_projection_run_pauses_0_projection_runs FOREIGN KEY ("owner_id", "account_id", "run_id") REFERENCES projection_runs ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_run_pauses_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_run_pauses_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_run_pauses PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_run_schedule_entries (
 "run_id" UUID NOT NULL,
 "entry_key" VARCHAR(120) NOT NULL,
 "on" DATE NOT NULL,
 "month" INTEGER NOT NULL,
 "kind" VARCHAR(12) NOT NULL,
 "value" NUMERIC(38,18) NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_run_schedule_entries_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_run_schedule_entries_run_id_entry_key UNIQUE ("run_id", "entry_key"),
 CONSTRAINT ck_projection_run_schedule_entries_month_bound CHECK (month BETWEEN 1 AND 600),
 CONSTRAINT ck_projection_run_schedule_entries_kind_allowed CHECK (kind IN ('lump_sum','withdrawal')),
 CONSTRAINT ck_projection_run_schedule_entries_value_bound CHECK (value>=0),
 CONSTRAINT ck_projection_run_schedule_entries_value_finite CHECK (value IS NULL OR (value > '-Infinity'::numeric AND value < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_run_schedule_entries_on_date_bound CHECK ("on" BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
 CONSTRAINT fk_projection_run_schedule_entries_0_projection_runs FOREIGN KEY ("owner_id", "account_id", "run_id") REFERENCES projection_runs ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_run_schedule_entries_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_run_schedule_entries_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_run_schedule_entries PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_run_sources (
 "run_id" UUID NOT NULL,
 "kind" VARCHAR(20) NOT NULL,
 "subject_id" UUID NOT NULL,
 "content_digest" VARCHAR(64) NOT NULL,
 "original_created_at" TIMESTAMP WITH TIME ZONE NOT NULL,
 "source_expires_at" TIMESTAMP WITH TIME ZONE NOT NULL,
 "quality" VARCHAR(20) NOT NULL,
 "proof_digest" VARCHAR(64) NOT NULL,
 "proof_bytes" INTEGER NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_run_sources_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_run_sources_run_id_kind_subject_id UNIQUE ("run_id", "kind", "subject_id"),
 CONSTRAINT ck_projection_run_sources_content_digest_format CHECK (content_digest ~ '^[0-9a-f]{64}$'),
 CONSTRAINT ck_projection_run_sources_proof_digest_format CHECK (proof_digest ~ '^[0-9a-f]{64}$'),
 CONSTRAINT ck_projection_run_sources_kind_allowed CHECK (kind IN ('initial_snapshot','calibration')),
 CONSTRAINT ck_projection_run_sources_expiry_order CHECK (source_expires_at>original_created_at),
 CONSTRAINT ck_projection_run_sources_quality_allowed CHECK (quality IN ('fresh','stale','partial','estimated','unreconciled','failed')),
 CONSTRAINT ck_projection_run_sources_proof_bound CHECK (proof_bytes BETWEEN 1 AND 33554432),
 CONSTRAINT fk_projection_run_sources_0_projection_runs FOREIGN KEY ("owner_id", "account_id", "run_id") REFERENCES projection_runs ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_run_sources_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_run_sources_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_run_sources PRIMARY KEY (id)
)""",
    r"""CREATE INDEX ix_projection_run_sources_0 ON projection_run_sources (subject_id, content_digest, run_id)""",
    r"""CREATE INDEX ix_projection_run_sources_1 ON projection_run_sources (source_expires_at, run_id)""",
    r"""CREATE TABLE projection_source_proofs (
 "run_id" UUID NOT NULL,
 "source_id" UUID NOT NULL,
 "canonical_proof" BYTEA NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_source_proofs_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_source_proofs_source_id UNIQUE ("source_id"),
 CONSTRAINT ck_projection_source_proofs_proof_bound CHECK (octet_length(canonical_proof) BETWEEN 1 AND 33554432),
 CONSTRAINT fk_projection_source_proofs_0_projection_runs FOREIGN KEY ("owner_id", "account_id", "run_id") REFERENCES projection_runs ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_source_proofs_1_projection_run_sources FOREIGN KEY ("owner_id", "account_id", "source_id") REFERENCES projection_run_sources ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_source_proofs_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_source_proofs_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_source_proofs PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_source_licenses (
 "run_id" UUID NOT NULL,
 "source_id" UUID NOT NULL,
 "run_license_id" UUID NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_source_licenses_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_source_licenses_source_id_run_license_id UNIQUE ("source_id", "run_license_id"),
 CONSTRAINT fk_projection_source_licenses_0_projection_runs FOREIGN KEY ("owner_id", "account_id", "run_id") REFERENCES projection_runs ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_source_licenses_1_projection_run_sources FOREIGN KEY ("owner_id", "account_id", "source_id") REFERENCES projection_run_sources ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_source_licenses_2_premium_run_licenses FOREIGN KEY ("owner_id", "account_id", "run_license_id") REFERENCES premium_run_licenses ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_source_licenses_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_source_licenses_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_source_licenses PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_chunks (
 "run_id" UUID NOT NULL,
 "job_id" UUID NOT NULL,
 "lease_token" UUID NOT NULL,
 "consumer_attempt" INTEGER NOT NULL,
 "variant" VARCHAR(24) NOT NULL,
 "first_path" INTEGER NOT NULL,
 "path_count" INTEGER NOT NULL,
 "input_digest" VARCHAR(64) NOT NULL,
 "content_digest" VARCHAR(64) NOT NULL,
 "byte_length" INTEGER NOT NULL,
 "canonical_chunk" BYTEA NOT NULL,
 "sealed" BOOLEAN NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_chunks_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_chunks_run_id_variant_first_path UNIQUE ("run_id", "variant", "first_path"),
 CONSTRAINT ck_projection_chunks_variant_allowed CHECK (variant IN ('baseline','contribution_delta','mean_log_delta')),
 CONSTRAINT ck_projection_chunks_input_digest_format CHECK (input_digest ~ '^[0-9a-f]{64}$'),
 CONSTRAINT ck_projection_chunks_content_digest_format CHECK (content_digest ~ '^[0-9a-f]{64}$'),
 CONSTRAINT ck_projection_chunks_path_bounds CHECK (first_path BETWEEN 0 AND 4095 AND path_count BETWEEN 1 AND 32 AND first_path+path_count<=4096),
 CONSTRAINT ck_projection_chunks_attempt_bound CHECK (consumer_attempt BETWEEN 1 AND 4),
 CONSTRAINT ck_projection_chunks_bytes_bound CHECK (byte_length BETWEEN 1 AND 33554432 AND octet_length(canonical_chunk)=byte_length),
 CONSTRAINT fk_projection_chunks_0_projection_runs FOREIGN KEY ("owner_id", "account_id", "run_id") REFERENCES projection_runs ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_chunks_1_premium_jobs FOREIGN KEY ("owner_id", "account_id", "job_id") REFERENCES premium_jobs ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_chunks_2_projection_runs FOREIGN KEY ("owner_id", "account_id", "run_id", "input_digest") REFERENCES projection_runs ("owner_id", "account_id", "id", "numerical_input_digest") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_chunks_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_chunks_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_chunks PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_paths (
 "run_id" UUID NOT NULL,
 "chunk_id" UUID NOT NULL,
 "variant" VARCHAR(24) NOT NULL,
 "path_index" INTEGER NOT NULL,
 "first_unpaid_month" INTEGER,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_paths_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_paths_run_id_variant_path_index UNIQUE ("run_id", "variant", "path_index"),
 CONSTRAINT ck_projection_paths_variant_allowed CHECK (variant IN ('baseline','contribution_delta','mean_log_delta')),
 CONSTRAINT ck_projection_paths_path_bound CHECK (path_index BETWEEN 0 AND 4095 AND (first_unpaid_month IS NULL OR first_unpaid_month BETWEEN 1 AND 600)),
 CONSTRAINT fk_projection_paths_0_projection_runs FOREIGN KEY ("owner_id", "account_id", "run_id") REFERENCES projection_runs ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_paths_1_projection_chunks FOREIGN KEY ("owner_id", "account_id", "chunk_id") REFERENCES projection_chunks ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_paths_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_paths_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_paths PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_points (
 "run_id" UUID NOT NULL,
 "path_id" UUID NOT NULL,
 "month" INTEGER NOT NULL,
 "point_index" INTEGER NOT NULL,
 "nominal" NUMERIC(38,18) NOT NULL,
 "real" NUMERIC(38,18) NOT NULL,
 "contributions" NUMERIC(38,18) NOT NULL,
 "withdrawals_requested" NUMERIC(38,18) NOT NULL,
 "withdrawals_funded" NUMERIC(38,18) NOT NULL,
 "unpaid_withdrawals" NUMERIC(38,18) NOT NULL,
 "investment_effect" NUMERIC(38,18) NOT NULL,
 "fees" NUMERIC(38,18) NOT NULL,
 "tax_drag" NUMERIC(38,18) NOT NULL,
 "wealth_residual" NUMERIC(38,18) NOT NULL,
 "allocation_residual" NUMERIC(38,18) NOT NULL,
 "withdrawal_residual" NUMERIC(38,18) NOT NULL,
 "funding_failed" BOOLEAN NOT NULL,
 "unpaid_positive_below_quantum" BOOLEAN NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_points_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_points_path_id_month UNIQUE ("path_id", "month"),
 CONSTRAINT uq_projection_points_path_id_point_index UNIQUE ("path_id", "point_index"),
 CONSTRAINT ck_projection_points_indices_bound CHECK (month BETWEEN 0 AND 600 AND point_index BETWEEN 0 AND 120),
 CONSTRAINT ck_projection_points_nonnegative CHECK (nominal>=0 AND real>=0 AND contributions>=0 AND withdrawals_requested>=0 AND withdrawals_funded>=0 AND unpaid_withdrawals>=0 AND fees>=0 AND tax_drag>=0),
 CONSTRAINT ck_projection_points_funding_consistency CHECK (withdrawals_funded<=withdrawals_requested AND withdrawal_residual=withdrawals_requested-withdrawals_funded-unpaid_withdrawals AND (unpaid_withdrawals=0 OR funding_failed) AND unpaid_positive_below_quantum=(funding_failed AND unpaid_withdrawals=0)),
 CONSTRAINT ck_projection_points_nominal_finite CHECK (nominal IS NULL OR (nominal > '-Infinity'::numeric AND nominal < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_points_real_finite CHECK (real IS NULL OR (real > '-Infinity'::numeric AND real < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_points_contributions_finite CHECK (contributions IS NULL OR (contributions > '-Infinity'::numeric AND contributions < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_points_withdrawals_requested_finite CHECK (withdrawals_requested IS NULL OR (withdrawals_requested > '-Infinity'::numeric AND withdrawals_requested < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_points_withdrawals_funded_finite CHECK (withdrawals_funded IS NULL OR (withdrawals_funded > '-Infinity'::numeric AND withdrawals_funded < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_points_unpaid_withdrawals_finite CHECK (unpaid_withdrawals IS NULL OR (unpaid_withdrawals > '-Infinity'::numeric AND unpaid_withdrawals < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_points_investment_effect_finite CHECK (investment_effect IS NULL OR (investment_effect > '-Infinity'::numeric AND investment_effect < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_points_fees_finite CHECK (fees IS NULL OR (fees > '-Infinity'::numeric AND fees < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_points_tax_drag_finite CHECK (tax_drag IS NULL OR (tax_drag > '-Infinity'::numeric AND tax_drag < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_points_wealth_residual_finite CHECK (wealth_residual IS NULL OR (wealth_residual > '-Infinity'::numeric AND wealth_residual < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_points_allocation_residual_finite CHECK (allocation_residual IS NULL OR (allocation_residual > '-Infinity'::numeric AND allocation_residual < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_points_withdrawal_residual_finite CHECK (withdrawal_residual IS NULL OR (withdrawal_residual > '-Infinity'::numeric AND withdrawal_residual < 'Infinity'::numeric)),
 CONSTRAINT fk_projection_points_0_projection_runs FOREIGN KEY ("owner_id", "account_id", "run_id") REFERENCES projection_runs ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_points_1_projection_paths FOREIGN KEY ("owner_id", "account_id", "path_id") REFERENCES projection_paths ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_points_2_projection_calendar_boundaries FOREIGN KEY ("owner_id", "account_id", "run_id", "month") REFERENCES projection_calendar_boundaries ("owner_id", "account_id", "run_id", "month") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_points_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_points_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_points PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_point_assets (
 "run_id" UUID NOT NULL,
 "point_id" UUID NOT NULL,
 "asset_index" INTEGER NOT NULL,
 "value" NUMERIC(38,18) NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_point_assets_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_point_assets_point_id_asset_index UNIQUE ("point_id", "asset_index"),
 CONSTRAINT ck_projection_point_assets_value_bound CHECK (value>=0),
 CONSTRAINT ck_projection_point_assets_value_finite CHECK (value IS NULL OR (value > '-Infinity'::numeric AND value < 'Infinity'::numeric)),
 CONSTRAINT fk_projection_point_assets_0_projection_runs FOREIGN KEY ("owner_id", "account_id", "run_id") REFERENCES projection_runs ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_point_assets_1_projection_points FOREIGN KEY ("owner_id", "account_id", "point_id") REFERENCES projection_points ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_point_assets_2_projection_run_allocations FOREIGN KEY ("owner_id", "account_id", "run_id", "asset_index") REFERENCES projection_run_allocations ("owner_id", "account_id", "run_id", "asset_index") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_point_assets_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_point_assets_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_point_assets PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_results (
 "run_id" UUID NOT NULL,
 "job_id" UUID NOT NULL,
 "lease_token" UUID NOT NULL,
 "consumer_attempt" INTEGER NOT NULL,
 "input_digest" VARCHAR(64) NOT NULL,
 "content_digest" VARCHAR(64) NOT NULL,
 "byte_length" INTEGER NOT NULL,
 "canonical_result" BYTEA NOT NULL,
 "quality" VARCHAR(20) NOT NULL,
 "sampler" VARCHAR(40) NOT NULL,
 "sealed" BOOLEAN NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_results_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_results_run_id UNIQUE ("run_id"),
 CONSTRAINT ck_projection_results_input_digest_format CHECK (input_digest ~ '^[0-9a-f]{64}$'),
 CONSTRAINT ck_projection_results_content_digest_format CHECK (content_digest ~ '^[0-9a-f]{64}$'),
 CONSTRAINT ck_projection_results_bytes_bound CHECK (byte_length BETWEEN 1 AND 33554432 AND octet_length(canonical_result) IN (0,byte_length)),
 CONSTRAINT ck_projection_results_quality_allowed CHECK (quality IN ('estimated','stale','partial','unreconciled','failed')),
 CONSTRAINT ck_projection_results_sampler_fixed CHECK (sampler='sha256_counter_polar_v1'),
 CONSTRAINT ck_projection_results_attempt_bound CHECK (consumer_attempt BETWEEN 1 AND 4),
 CONSTRAINT fk_projection_results_0_projection_runs FOREIGN KEY ("owner_id", "account_id", "run_id") REFERENCES projection_runs ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_results_1_premium_jobs FOREIGN KEY ("owner_id", "account_id", "job_id") REFERENCES premium_jobs ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_results_2_projection_runs FOREIGN KEY ("owner_id", "account_id", "run_id", "input_digest") REFERENCES projection_runs ("owner_id", "account_id", "id", "numerical_input_digest") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_results_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_results_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_results PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_zero_pivots (
 "result_id" UUID NOT NULL,
 "asset_index" INTEGER NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_zero_pivots_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_zero_pivots_result_id_asset_index UNIQUE ("result_id", "asset_index"),
 CONSTRAINT ck_projection_zero_pivots_index_bound CHECK (asset_index BETWEEN 0 AND 11),
 CONSTRAINT fk_projection_zero_pivots_0_projection_results FOREIGN KEY ("owner_id", "account_id", "result_id") REFERENCES projection_results ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_zero_pivots_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_zero_pivots_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_zero_pivots PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_distributions (
 "result_id" UUID NOT NULL,
 "variant" VARCHAR(24) NOT NULL,
 "month" INTEGER NOT NULL,
 "nominal_mean" NUMERIC(38,18) NOT NULL,
 "real_mean" NUMERIC(38,18) NOT NULL,
 "funding_failed_paths" INTEGER NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_distributions_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_distributions_result_id_variant_month UNIQUE ("result_id", "variant", "month"),
 CONSTRAINT ck_projection_distributions_variant_allowed CHECK (variant IN ('baseline','contribution_delta','mean_log_delta')),
 CONSTRAINT ck_projection_distributions_bounds CHECK (month BETWEEN 0 AND 600 AND nominal_mean>=0 AND real_mean>=0 AND funding_failed_paths BETWEEN 0 AND 4096),
 CONSTRAINT ck_projection_distributions_nominal_mean_finite CHECK (nominal_mean IS NULL OR (nominal_mean > '-Infinity'::numeric AND nominal_mean < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_distributions_real_mean_finite CHECK (real_mean IS NULL OR (real_mean > '-Infinity'::numeric AND real_mean < 'Infinity'::numeric)),
 CONSTRAINT fk_projection_distributions_0_projection_results FOREIGN KEY ("owner_id", "account_id", "result_id") REFERENCES projection_results ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_distributions_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_distributions_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_distributions PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_distribution_quantiles (
 "distribution_id" UUID NOT NULL,
 "basis" VARCHAR(10) NOT NULL,
 "probability" NUMERIC(38,18) NOT NULL,
 "value" NUMERIC(38,18) NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_distribution_quantiles_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_distribution_quantiles_distribution_id_fdd448dadb UNIQUE ("distribution_id", "basis", "probability"),
 CONSTRAINT ck_projection_distribution_quantiles_basis_allowed CHECK (basis IN ('nominal','real')),
 CONSTRAINT ck_projection_distribution_quantiles_bounds CHECK (probability IN (.05,.25,.50,.75,.95) AND value>=0),
 CONSTRAINT ck_projection_distribution_quantiles_probability_finite CHECK (probability IS NULL OR (probability > '-Infinity'::numeric AND probability < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_distribution_quantiles_value_finite CHECK (value IS NULL OR (value > '-Infinity'::numeric AND value < 'Infinity'::numeric)),
 CONSTRAINT fk_projection_distribution_quantiles_0_projection_distributions FOREIGN KEY ("owner_id", "account_id", "distribution_id") REFERENCES projection_distributions ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_distribution_quantiles_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_distribution_quantiles_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_distribution_quantiles PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_histograms (
 "result_id" UUID NOT NULL,
 "variant" VARCHAR(24) NOT NULL,
 "basis" VARCHAR(10) NOT NULL,
 "observed_minimum" NUMERIC(38,18) NOT NULL,
 "observed_maximum" NUMERIC(38,18) NOT NULL,
 "bin_count" INTEGER NOT NULL,
 "boundary_rule" VARCHAR(40) NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_histograms_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_histograms_result_id_variant_basis UNIQUE ("result_id", "variant", "basis"),
 CONSTRAINT ck_projection_histograms_variant_allowed CHECK (variant IN ('baseline','contribution_delta','mean_log_delta')),
 CONSTRAINT ck_projection_histograms_basis_allowed CHECK (basis IN ('nominal','real')),
 CONSTRAINT ck_projection_histograms_bounds CHECK (observed_minimum>=0 AND observed_maximum>=observed_minimum AND bin_count BETWEEN 1 AND 20),
 CONSTRAINT ck_projection_histograms_rule_fixed CHECK (boundary_rule='q18_enclosing_ceiling_v1'),
 CONSTRAINT ck_projection_histograms_observed_minimum_finite CHECK (observed_minimum IS NULL OR (observed_minimum > '-Infinity'::numeric AND observed_minimum < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_histograms_observed_maximum_finite CHECK (observed_maximum IS NULL OR (observed_maximum > '-Infinity'::numeric AND observed_maximum < 'Infinity'::numeric)),
 CONSTRAINT fk_projection_histograms_0_projection_results FOREIGN KEY ("owner_id", "account_id", "result_id") REFERENCES projection_results ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_histograms_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_histograms_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_histograms PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_histogram_bins (
 "histogram_id" UUID NOT NULL,
 "bin_index" INTEGER NOT NULL,
 "lower" NUMERIC(38,18) NOT NULL,
 "upper" NUMERIC(38,18) NOT NULL,
 "upper_inclusive" BOOLEAN NOT NULL,
 "count" INTEGER NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_histogram_bins_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_histogram_bins_histogram_id_bin_index UNIQUE ("histogram_id", "bin_index"),
 CONSTRAINT ck_projection_histogram_bins_bounds CHECK (bin_index BETWEEN 0 AND 19 AND lower>=0 AND upper>=lower AND count BETWEEN 0 AND 4096),
 CONSTRAINT ck_projection_histogram_bins_lower_finite CHECK (lower IS NULL OR (lower > '-Infinity'::numeric AND lower < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_histogram_bins_upper_finite CHECK (upper IS NULL OR (upper > '-Infinity'::numeric AND upper < 'Infinity'::numeric)),
 CONSTRAINT fk_projection_histogram_bins_0_projection_histograms FOREIGN KEY ("owner_id", "account_id", "histogram_id") REFERENCES projection_histograms ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_histogram_bins_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_histogram_bins_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_histogram_bins PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_goal_analyses (
 "result_id" UUID NOT NULL,
 "goal_version_id" UUID NOT NULL,
 "variant" VARCHAR(24) NOT NULL,
 "basis" VARCHAR(10) NOT NULL,
 "target" NUMERIC(38,18) NOT NULL,
 "paths" INTEGER NOT NULL,
 "successes" INTEGER NOT NULL,
 "probability" NUMERIC(38,18) NOT NULL,
 "interval_low" NUMERIC(38,18) NOT NULL,
 "interval_high" NUMERIC(38,18) NOT NULL,
 "probability_objective" NUMERIC(38,18) NOT NULL,
 "mean_shortfall" NUMERIC(38,18) NOT NULL,
 "objective_met" BOOLEAN NOT NULL,
 "funding_failed_paths" INTEGER NOT NULL,
 "method" VARCHAR(40) NOT NULL,
 "interval_method" VARCHAR(40) NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_goal_analyses_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_goal_analyses_result_id_variant UNIQUE ("result_id", "variant"),
 CONSTRAINT ck_projection_goal_analyses_variant_allowed CHECK (variant IN ('baseline','contribution_delta','mean_log_delta')),
 CONSTRAINT ck_projection_goal_analyses_basis_allowed CHECK (basis IN ('nominal','real')),
 CONSTRAINT ck_projection_goal_analyses_bounds CHECK (target>=0 AND paths BETWEEN 1 AND 4096 AND successes BETWEEN 0 AND paths AND probability BETWEEN 0 AND 1 AND interval_low BETWEEN 0 AND probability AND interval_high BETWEEN probability AND 1 AND probability_objective BETWEEN 0 AND 1 AND mean_shortfall>=0 AND funding_failed_paths BETWEEN 0 AND paths AND successes<=paths-funding_failed_paths AND objective_met=(probability>=probability_objective)),
 CONSTRAINT ck_projection_goal_analyses_method_fixed CHECK (method='goal_analysis_v1' AND interval_method='wilson_95_v1'),
 CONSTRAINT ck_projection_goal_analyses_target_finite CHECK (target IS NULL OR (target > '-Infinity'::numeric AND target < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_goal_analyses_probability_finite CHECK (probability IS NULL OR (probability > '-Infinity'::numeric AND probability < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_goal_analyses_interval_low_finite CHECK (interval_low IS NULL OR (interval_low > '-Infinity'::numeric AND interval_low < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_goal_analyses_interval_high_finite CHECK (interval_high IS NULL OR (interval_high > '-Infinity'::numeric AND interval_high < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_goal_analyses_probability_objective_finite CHECK (probability_objective IS NULL OR (probability_objective > '-Infinity'::numeric AND probability_objective < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_goal_analyses_mean_shortfall_finite CHECK (mean_shortfall IS NULL OR (mean_shortfall > '-Infinity'::numeric AND mean_shortfall < 'Infinity'::numeric)),
 CONSTRAINT fk_projection_goal_analyses_0_projection_results FOREIGN KEY ("owner_id", "account_id", "result_id") REFERENCES projection_results ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_goal_analyses_1_goal_versions FOREIGN KEY ("owner_id", "account_id", "goal_version_id") REFERENCES goal_versions ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_goal_analyses_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_goal_analyses_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_goal_analyses PRIMARY KEY (id)
)""",
    r"""CREATE TABLE projection_goal_shortfall_quantiles (
 "analysis_id" UUID NOT NULL,
 "probability" NUMERIC(38,18) NOT NULL,
 "value" NUMERIC(38,18) NOT NULL,
 "id" UUID NOT NULL,
 "owner_id" UUID NOT NULL,
 "account_id" UUID NOT NULL,
 "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT uq_projection_goal_shortfall_quantiles_owner_id_account_id_id UNIQUE ("owner_id", "account_id", "id"),
 CONSTRAINT uq_projection_goal_shortfall_quantiles_analysis_id_probability UNIQUE ("analysis_id", "probability"),
 CONSTRAINT ck_projection_goal_shortfall_quantiles_bounds CHECK (probability IN (.05,.25,.50,.75,.95) AND value>=0),
 CONSTRAINT ck_projection_goal_shortfall_quantiles_probability_finite CHECK (probability IS NULL OR (probability > '-Infinity'::numeric AND probability < 'Infinity'::numeric)),
 CONSTRAINT ck_projection_goal_shortfall_quantiles_value_finite CHECK (value IS NULL OR (value > '-Infinity'::numeric AND value < 'Infinity'::numeric)),
 CONSTRAINT fk_projection_goal_shortfall_quantiles_0_projection__ed20457ecb FOREIGN KEY ("owner_id", "account_id", "analysis_id") REFERENCES projection_goal_analyses ("owner_id", "account_id", "id") ON DELETE RESTRICT,
 CONSTRAINT fk_projection_goal_shortfall_quantiles_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_goal_shortfall_quantiles_account_id_broke_f66e FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT pk_projection_goal_shortfall_quantiles PRIMARY KEY (id)
)""",
)

_TABLES = (
    "assumption_sets",
    "goals",
    "assumption_versions",
    "projection_assumption_assets",
    "projection_correlation_cells",
    "projection_calibration_pins",
    "goal_versions",
    "projection_goal_pauses",
    "projection_goal_schedule_entries",
    "projection_runs",
    "projection_inputs",
    "projection_run_allocations",
    "projection_calendar_boundaries",
    "projection_run_pauses",
    "projection_run_schedule_entries",
    "projection_run_sources",
    "projection_source_proofs",
    "projection_source_licenses",
    "projection_chunks",
    "projection_paths",
    "projection_points",
    "projection_point_assets",
    "projection_results",
    "projection_zero_pivots",
    "projection_distributions",
    "projection_distribution_quantiles",
    "projection_histograms",
    "projection_histogram_bins",
    "projection_goal_analyses",
    "projection_goal_shortfall_quantiles",
)

_PREVIOUS_COMMAND_CHECKS = {
    "command_allowed": "command IN ('reports.generate.v1','reports.generate.v2','exports.generate.v1','risk.definition.create.v1','risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1','scenario.definition.create.v1','scenario.version.create.v1','scenario.run.create.v1','scenario.run.cancel.v1')",
    "parent_kind": "(command IN ('reports.generate.v1','reports.generate.v2') AND report_job_id IS NOT NULL AND export_job_id IS NULL AND premium_resource_id IS NULL AND premium_actor_id IS NULL AND premium_correlation_id IS NULL) OR (command='exports.generate.v1' AND export_job_id IS NOT NULL AND report_job_id IS NULL AND premium_resource_id IS NULL AND premium_actor_id IS NULL AND premium_correlation_id IS NULL) OR (command IN ('risk.definition.create.v1','risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1','scenario.definition.create.v1','scenario.version.create.v1','scenario.run.create.v1','scenario.run.cancel.v1') AND report_job_id IS NULL AND export_job_id IS NULL AND premium_resource_id IS NOT NULL AND premium_actor_id IS NOT NULL AND premium_correlation_id IS NOT NULL)",
}

_COMMAND_CHECKS = {
    "command_allowed": "command IN ('reports.generate.v1','reports.generate.v2','exports.generate.v1','risk.definition.create.v1','risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1','scenario.definition.create.v1','scenario.version.create.v1','scenario.run.create.v1','scenario.run.cancel.v1','projection.assumption.create.v1','projection.assumption.version.create.v1','projection.goal.create.v1','projection.goal.version.create.v1','projection.run.create.v1','projection.run.cancel.v1')",
    "parent_kind": "(command IN ('reports.generate.v1','reports.generate.v2') AND report_job_id IS NOT NULL AND export_job_id IS NULL AND premium_resource_id IS NULL AND premium_actor_id IS NULL AND premium_correlation_id IS NULL) OR (command='exports.generate.v1' AND export_job_id IS NOT NULL AND report_job_id IS NULL AND premium_resource_id IS NULL AND premium_actor_id IS NULL AND premium_correlation_id IS NULL) OR (command IN ('risk.definition.create.v1','risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1','scenario.definition.create.v1','scenario.version.create.v1','scenario.run.create.v1','scenario.run.cancel.v1','projection.assumption.create.v1','projection.assumption.version.create.v1','projection.goal.create.v1','projection.goal.version.create.v1','projection.run.create.v1','projection.run.cancel.v1') AND report_job_id IS NULL AND export_job_id IS NULL AND premium_resource_id IS NOT NULL AND premium_actor_id IS NOT NULL AND premium_correlation_id IS NOT NULL)",
}

_PREVIOUS_COLLECTION_CHECKS = {
    "account_scope_match": "((resource IN ('risk_definitions','risk_versions','risk_runs','scenario_definitions','scenario_versions','scenario_runs','intelligence_quality_sources','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations','reports','premium_reports','exports','activity','dividends','positions_market_value','positions_weight','positions_ticker','contribution_plans','plan_lines','actual_target_rows','plan_revisions','historical_performance','historical_cash_flows','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities') AND broker_account_id IS NOT NULL) OR (resource = 'instruments' AND broker_account_id IS NULL) OR resource IN ('portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','composite_benchmark_points','constituent_holdings'))",
    "resource_allowed": "resource IN ('risk_definitions','risk_versions','risk_runs','scenario_definitions','scenario_versions','scenario_runs','intelligence_quality_sources','activity','dividends','instruments','positions_market_value','positions_weight','positions_ticker','portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','contribution_plans','plan_lines','actual_target_rows','plan_revisions','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings','reports','premium_reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations')",
    "resource_sort_match": "(resource IN ('intelligence_quality_sources','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings') AND sort_specification = 'ordinal_asc') OR (resource = 'activity' AND sort_specification = 'occurred_at_desc_id_desc') OR (resource = 'dividends' AND sort_specification = 'paid_on_desc_id_desc') OR (resource = 'instruments' AND sort_specification = 'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR (resource = 'positions_market_value' AND sort_specification = 'market_value_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_weight' AND sort_specification = 'direct_weight_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_ticker' AND sort_specification = 'ticker_asc_listing_id_asc') OR (resource = 'portfolios_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'portfolios_updated' AND sort_specification = 'updated_at_desc_id_desc') OR (resource = 'target_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource = 'target_events' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'target_nodes' AND sort_specification = 'depth_first_order_key') OR (resource = 'plan_revisions' AND sort_specification = 'revision_number_desc_id_desc') OR (resource = 'contribution_plans' AND sort_specification = 'created_at_desc_id_desc') OR (resource IN ('plan_lines','actual_target_rows','plan_revisions') AND sort_specification = 'ordinal_asc') OR (resource = 'market_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'benchmark_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'fx_source_status' AND sort_specification = 'base_quote_provider_asc') OR (resource = 'price_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'fx_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_defs_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'benchmark_defs_created' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'benchmark_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource IN ('reports','premium_reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations') AND sort_specification = 'created_at_desc_id_desc') OR (resource IN ('risk_definitions','risk_runs','scenario_definitions','scenario_runs') AND sort_specification='created_at_desc_id_desc') OR (resource IN ('risk_versions','scenario_versions') AND sort_specification='version_number_desc_id_desc')",
}

_COLLECTION_CHECKS = {
    "account_scope_match": "((resource IN ('risk_definitions','risk_versions','risk_runs','scenario_definitions','scenario_versions','scenario_runs','assumption_sets','assumption_versions','goals','goal_versions','projection_runs','intelligence_quality_sources','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations','reports','premium_reports','exports','activity','dividends','positions_market_value','positions_weight','positions_ticker','contribution_plans','plan_lines','actual_target_rows','plan_revisions','historical_performance','historical_cash_flows','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities') AND broker_account_id IS NOT NULL) OR (resource = 'instruments' AND broker_account_id IS NULL) OR resource IN ('portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','composite_benchmark_points','constituent_holdings'))",
    "resource_allowed": "resource IN ('risk_definitions','risk_versions','risk_runs','scenario_definitions','scenario_versions','scenario_runs','assumption_sets','assumption_versions','goals','goal_versions','projection_runs','intelligence_quality_sources','activity','dividends','instruments','positions_market_value','positions_weight','positions_ticker','portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','contribution_plans','plan_lines','actual_target_rows','plan_revisions','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings','reports','premium_reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations')",
    "resource_sort_match": "(resource IN ('intelligence_quality_sources','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings') AND sort_specification = 'ordinal_asc') OR (resource = 'activity' AND sort_specification = 'occurred_at_desc_id_desc') OR (resource = 'dividends' AND sort_specification = 'paid_on_desc_id_desc') OR (resource = 'instruments' AND sort_specification = 'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR (resource = 'positions_market_value' AND sort_specification = 'market_value_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_weight' AND sort_specification = 'direct_weight_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_ticker' AND sort_specification = 'ticker_asc_listing_id_asc') OR (resource = 'portfolios_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'portfolios_updated' AND sort_specification = 'updated_at_desc_id_desc') OR (resource = 'target_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource = 'target_events' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'target_nodes' AND sort_specification = 'depth_first_order_key') OR (resource = 'plan_revisions' AND sort_specification = 'revision_number_desc_id_desc') OR (resource = 'contribution_plans' AND sort_specification = 'created_at_desc_id_desc') OR (resource IN ('plan_lines','actual_target_rows','plan_revisions') AND sort_specification = 'ordinal_asc') OR (resource = 'market_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'benchmark_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'fx_source_status' AND sort_specification = 'base_quote_provider_asc') OR (resource = 'price_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'fx_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_defs_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'benchmark_defs_created' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'benchmark_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource IN ('reports','premium_reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations') AND sort_specification = 'created_at_desc_id_desc') OR (resource IN ('risk_definitions','risk_runs','scenario_definitions','scenario_runs','assumption_sets','goals','projection_runs') AND sort_specification='created_at_desc_id_desc') OR (resource IN ('risk_versions','scenario_versions','assumption_versions','goal_versions') AND sort_specification='version_number_desc_id_desc')",
}

_PREVIOUS_SHARED_GUARDS = r"""CREATE OR REPLACE FUNCTION premium_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual uuid; pinned boolean; version integer; family text; snapshot uuid; cutoff timestamptz;
BEGIN
 IF TG_TABLE_NAME='application_command_identities' THEN
  IF NEW.command NOT LIKE 'risk.%' AND NEW.command NOT LIKE 'scenario.%' THEN RETURN NEW; END IF;
 END IF;
 SELECT c.owner_id INTO actual FROM broker_accounts a JOIN broker_connections c ON c.id=a.connection_id WHERE a.id=NEW.account_id;
 IF actual IS DISTINCT FROM NEW.owner_id THEN RAISE EXCEPTION 'Premium account scope mismatch' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='premium_runs' THEN
  SELECT owner_id INTO actual FROM principals WHERE id=NEW.actor_principal_id;
  IF actual IS DISTINCT FROM NEW.owner_id THEN RAISE EXCEPTION 'Premium principal scope mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_runs' THEN
  SELECT premium_resource_id INTO actual FROM application_command_identities WHERE id=NEW.command_id AND command=CASE NEW.kind WHEN 'risk' THEN 'risk.run.create.v1' WHEN 'scenario' THEN 'scenario.run.create.v1' END AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
  IF actual IS DISTINCT FROM NEW.id THEN RAISE EXCEPTION 'Premium run command mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='risk_definition_versions' AND TG_OP='INSERT' THEN
  PERFORM owner_id FROM premium_owner_capacity WHERE owner_id=NEW.owner_id FOR UPDATE;
  IF NOT FOUND OR (SELECT count(*) FROM risk_definition_versions WHERE owner_id=NEW.owner_id)+(SELECT count(*) FROM scenario_definition_versions WHERE owner_id=NEW.owner_id)>=512 THEN RAISE EXCEPTION 'Premium version capacity unavailable' USING ERRCODE='23514'; END IF;
  SELECT revision INTO version FROM risk_definitions WHERE id=NEW.definition_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
  IF version IS DISTINCT FROM NEW.version_number THEN RAISE EXCEPTION 'Risk aggregate revision mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.predecessor_id IS NOT NULL THEN
   SELECT version_number INTO version FROM risk_definition_versions WHERE id=NEW.predecessor_id AND definition_id=NEW.definition_id;
   IF version IS DISTINCT FROM NEW.version_number-1 THEN RAISE EXCEPTION 'Risk predecessor mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF TG_TABLE_NAME='risk_runs' THEN
  SELECT kind INTO family FROM premium_runs WHERE id=NEW.id AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
  IF family IS DISTINCT FROM 'risk' THEN RAISE EXCEPTION 'Risk run family mismatch' USING ERRCODE='23514'; END IF;
  SELECT broker_account_id, sealed INTO actual,pinned FROM historical_input_snapshots WHERE owner_id=NEW.owner_id AND id=NEW.historical_input_id AND input_digest=NEW.historical_input_digest;
  IF actual IS DISTINCT FROM NEW.account_id OR NOT coalesce(pinned,false) THEN RAISE EXCEPTION 'Risk history binding mismatch' USING ERRCODE='23514'; END IF;
  SELECT broker_account_id INTO actual FROM portfolio_snapshots WHERE id=NEW.portfolio_snapshot_id;
  IF actual IS DISTINCT FROM NEW.account_id THEN RAISE EXCEPTION 'Risk snapshot binding mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.xray_run_id IS NOT NULL THEN
   SELECT i.account_id,i.snapshot_id,i.source_cutoff_at INTO actual,snapshot,cutoff FROM xray_runs r JOIN xray_input_snapshots i ON i.id=r.input_id WHERE r.id=NEW.xray_run_id AND r.owner_id=NEW.owner_id AND r.sealed_at IS NOT NULL AND i.sealed_at IS NOT NULL;
   IF actual IS DISTINCT FROM NEW.account_id OR snapshot IS DISTINCT FROM NEW.portfolio_snapshot_id OR cutoff IS DISTINCT FROM NEW.source_cutoff_at THEN RAISE EXCEPTION 'Risk X-ray binding mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF TG_TABLE_NAME='risk_run_assets' THEN
  SELECT instrument_id INTO actual FROM market_source_series WHERE id=NEW.source_series_id AND owner_id=NEW.owner_id;
  IF actual IS DISTINCT FROM NEW.instrument_id THEN RAISE EXCEPTION 'Risk asset source mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_dispatch_outbox' THEN
  SELECT r.kind INTO family FROM premium_jobs j JOIN premium_runs r ON r.id=j.run_id WHERE j.id=NEW.job_id;
  IF NEW.task_name IS DISTINCT FROM (CASE family WHEN 'risk' THEN 'risk.calculate.v1' WHEN 'scenario' THEN 'scenarios.calculate.v1' WHEN 'projection' THEN 'projections.calculate.v1' END) THEN RAISE EXCEPTION 'Premium task identity mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_jobs' THEN
  PERFORM owner_id FROM premium_owner_capacity WHERE owner_id=NEW.owner_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Premium capacity reservation missing' USING ERRCODE='23514'; END IF;
  IF NEW.state IN ('queued','running') AND (SELECT count(*) FROM premium_jobs WHERE owner_id=NEW.owner_id AND id<>NEW.id AND state IN ('queued','running')) >= 2 THEN RAISE EXCEPTION 'Premium owner active capacity exceeded' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION premium_command_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual uuid; account uuid;
BEGIN
 IF NEW.command NOT LIKE 'risk.%' AND NEW.command NOT LIKE 'scenario.%' THEN RETURN NEW; END IF;
 IF NEW.command='risk.definition.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM risk_definitions WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command='risk.version.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM risk_definition_versions WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command IN ('risk.run.create.v1','risk.run.cancel.v1') THEN SELECT owner_id,account_id INTO actual,account FROM premium_runs WHERE id=NEW.premium_resource_id AND kind='risk';
 ELSIF NEW.command='scenario.definition.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM scenario_definitions WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command='scenario.version.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM scenario_definition_versions WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command IN ('scenario.run.create.v1','scenario.run.cancel.v1') THEN SELECT owner_id,account_id INTO actual,account FROM premium_runs WHERE id=NEW.premium_resource_id AND kind='scenario'; END IF;
 IF actual IS DISTINCT FROM NEW.owner_id OR account IS DISTINCT FROM NEW.account_id THEN RAISE EXCEPTION 'Premium command target mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION premium_run_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE pinned boolean; jobs integer;
BEGIN
 IF NEW.kind NOT IN ('risk','scenario') THEN RAISE EXCEPTION 'Premium handler is not implemented' USING ERRCODE='23514'; END IF;
 IF NEW.kind='risk' THEN SELECT sealed INTO pinned FROM risk_runs WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.id;
 ELSE pinned:=scenario_capture_complete(NEW.id); END IF;
 SELECT count(*) INTO jobs FROM premium_jobs j JOIN premium_dispatch_outbox o ON o.job_id=j.id AND o.owner_id=j.owner_id AND o.account_id=j.account_id WHERE j.run_id=NEW.id;
 IF NOT coalesce(pinned,false) OR jobs<>1 THEN RAISE EXCEPTION 'Premium request publication incomplete' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION premium_job_success_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE job premium_jobs; family text; result uuid;
BEGIN
 SELECT * INTO job FROM premium_jobs WHERE id=NEW.id;
 IF job.state IS DISTINCT FROM 'succeeded' THEN RETURN NEW; END IF;
 SELECT kind INTO family FROM premium_runs WHERE id=job.run_id AND owner_id=job.owner_id AND account_id=job.account_id;
 IF family='risk' THEN
  SELECT id INTO result FROM risk_results WHERE run_id=job.run_id AND owner_id=job.owner_id AND account_id=job.account_id;
  PERFORM premium_risk_result_complete_check(result,job.run_id,job.owner_id,job.account_id);
 ELSIF family='scenario' THEN
  SELECT id INTO result FROM scenario_results WHERE run_id=job.run_id AND owner_id=job.owner_id AND account_id=job.account_id;
  PERFORM scenario_result_complete_check(result);
 ELSE RAISE EXCEPTION 'Premium handler is not implemented' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION premium_run_license_guard() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE pinned boolean; family text;
      BEGIN
        IF TG_OP <> 'INSERT' THEN
          RAISE EXCEPTION 'Premium license lineage is immutable' USING ERRCODE='23514';
        END IF;
        SELECT kind INTO family FROM premium_runs WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
        IF family='risk' THEN SELECT sealed INTO pinned FROM risk_runs WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
        ELSIF family='scenario' THEN SELECT sealed INTO pinned FROM scenario_runs WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
        ELSE RAISE EXCEPTION 'Premium handler is not implemented' USING ERRCODE='23514'; END IF;
        IF pinned IS DISTINCT FROM false OR
          (SELECT count(*) FROM premium_run_licenses WHERE run_id=NEW.run_id)>=8192 THEN
          RAISE EXCEPTION 'Premium license lineage is sealed or over capacity' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
      END $$;"""

_SHARED_GUARDS = r"""CREATE OR REPLACE FUNCTION premium_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual uuid; pinned boolean; version integer; family text; snapshot uuid; cutoff timestamptz;
BEGIN
 IF TG_TABLE_NAME='application_command_identities' THEN
  IF NEW.command NOT LIKE 'risk.%' AND NEW.command NOT LIKE 'scenario.%' AND NEW.command NOT LIKE 'projection.%' THEN RETURN NEW; END IF;
 END IF;
 SELECT c.owner_id INTO actual FROM broker_accounts a JOIN broker_connections c ON c.id=a.connection_id WHERE a.id=NEW.account_id;
 IF actual IS DISTINCT FROM NEW.owner_id THEN RAISE EXCEPTION 'Premium account scope mismatch' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='premium_runs' THEN
  SELECT owner_id INTO actual FROM principals WHERE id=NEW.actor_principal_id;
  IF actual IS DISTINCT FROM NEW.owner_id THEN RAISE EXCEPTION 'Premium principal scope mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_runs' THEN
  SELECT premium_resource_id INTO actual FROM application_command_identities WHERE id=NEW.command_id AND command=CASE NEW.kind WHEN 'risk' THEN 'risk.run.create.v1' WHEN 'scenario' THEN 'scenario.run.create.v1' WHEN 'projection' THEN 'projection.run.create.v1' END AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
  IF actual IS DISTINCT FROM NEW.id THEN RAISE EXCEPTION 'Premium run command mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='risk_definition_versions' AND TG_OP='INSERT' THEN
  PERFORM owner_id FROM premium_owner_capacity WHERE owner_id=NEW.owner_id FOR UPDATE;
  IF NOT FOUND OR (SELECT count(*) FROM risk_definition_versions WHERE owner_id=NEW.owner_id)+(SELECT count(*) FROM scenario_definition_versions WHERE owner_id=NEW.owner_id)>=512 THEN RAISE EXCEPTION 'Premium version capacity unavailable' USING ERRCODE='23514'; END IF;
  SELECT revision INTO version FROM risk_definitions WHERE id=NEW.definition_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
  IF version IS DISTINCT FROM NEW.version_number THEN RAISE EXCEPTION 'Risk aggregate revision mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.predecessor_id IS NOT NULL THEN
   SELECT version_number INTO version FROM risk_definition_versions WHERE id=NEW.predecessor_id AND definition_id=NEW.definition_id;
   IF version IS DISTINCT FROM NEW.version_number-1 THEN RAISE EXCEPTION 'Risk predecessor mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF TG_TABLE_NAME='risk_runs' THEN
  SELECT kind INTO family FROM premium_runs WHERE id=NEW.id AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
  IF family IS DISTINCT FROM 'risk' THEN RAISE EXCEPTION 'Risk run family mismatch' USING ERRCODE='23514'; END IF;
  SELECT broker_account_id, sealed INTO actual,pinned FROM historical_input_snapshots WHERE owner_id=NEW.owner_id AND id=NEW.historical_input_id AND input_digest=NEW.historical_input_digest;
  IF actual IS DISTINCT FROM NEW.account_id OR NOT coalesce(pinned,false) THEN RAISE EXCEPTION 'Risk history binding mismatch' USING ERRCODE='23514'; END IF;
  SELECT broker_account_id INTO actual FROM portfolio_snapshots WHERE id=NEW.portfolio_snapshot_id;
  IF actual IS DISTINCT FROM NEW.account_id THEN RAISE EXCEPTION 'Risk snapshot binding mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.xray_run_id IS NOT NULL THEN
   SELECT i.account_id,i.snapshot_id,i.source_cutoff_at INTO actual,snapshot,cutoff FROM xray_runs r JOIN xray_input_snapshots i ON i.id=r.input_id WHERE r.id=NEW.xray_run_id AND r.owner_id=NEW.owner_id AND r.sealed_at IS NOT NULL AND i.sealed_at IS NOT NULL;
   IF actual IS DISTINCT FROM NEW.account_id OR snapshot IS DISTINCT FROM NEW.portfolio_snapshot_id OR cutoff IS DISTINCT FROM NEW.source_cutoff_at THEN RAISE EXCEPTION 'Risk X-ray binding mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF TG_TABLE_NAME='risk_run_assets' THEN
  SELECT instrument_id INTO actual FROM market_source_series WHERE id=NEW.source_series_id AND owner_id=NEW.owner_id;
  IF actual IS DISTINCT FROM NEW.instrument_id THEN RAISE EXCEPTION 'Risk asset source mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_dispatch_outbox' THEN
  SELECT r.kind INTO family FROM premium_jobs j JOIN premium_runs r ON r.id=j.run_id WHERE j.id=NEW.job_id;
  IF NEW.task_name IS DISTINCT FROM (CASE family WHEN 'risk' THEN 'risk.calculate.v1' WHEN 'scenario' THEN 'scenarios.calculate.v1' WHEN 'projection' THEN 'projections.calculate.v1' END) THEN RAISE EXCEPTION 'Premium task identity mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_jobs' THEN
  PERFORM owner_id FROM premium_owner_capacity WHERE owner_id=NEW.owner_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Premium capacity reservation missing' USING ERRCODE='23514'; END IF;
  IF NEW.state IN ('queued','running') AND (SELECT count(*) FROM premium_jobs WHERE owner_id=NEW.owner_id AND id<>NEW.id AND state IN ('queued','running')) >= 2 THEN RAISE EXCEPTION 'Premium owner active capacity exceeded' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION premium_command_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual uuid; account uuid;
BEGIN
 IF NEW.command NOT LIKE 'risk.%' AND NEW.command NOT LIKE 'scenario.%' AND NEW.command NOT LIKE 'projection.%' THEN RETURN NEW; END IF;
 IF NEW.command='risk.definition.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM risk_definitions WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command='risk.version.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM risk_definition_versions WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command IN ('risk.run.create.v1','risk.run.cancel.v1') THEN SELECT owner_id,account_id INTO actual,account FROM premium_runs WHERE id=NEW.premium_resource_id AND kind='risk';
 ELSIF NEW.command='scenario.definition.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM scenario_definitions WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command='scenario.version.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM scenario_definition_versions WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command IN ('scenario.run.create.v1','scenario.run.cancel.v1') THEN SELECT owner_id,account_id INTO actual,account FROM premium_runs WHERE id=NEW.premium_resource_id AND kind='scenario';
 ELSIF NEW.command='projection.assumption.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM assumption_sets WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command='projection.assumption.version.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM assumption_versions WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command='projection.goal.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM goals WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command='projection.goal.version.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM goal_versions WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command IN ('projection.run.create.v1','projection.run.cancel.v1') THEN SELECT owner_id,account_id INTO actual,account FROM premium_runs WHERE id=NEW.premium_resource_id AND kind='projection'; END IF;
 IF actual IS DISTINCT FROM NEW.owner_id OR account IS DISTINCT FROM NEW.account_id THEN RAISE EXCEPTION 'Premium command target mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION premium_run_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE pinned boolean; jobs integer;
BEGIN
 IF NEW.kind NOT IN ('risk','scenario','projection') THEN RAISE EXCEPTION 'Premium handler is not implemented' USING ERRCODE='23514'; END IF;
 IF NEW.kind='risk' THEN SELECT sealed INTO pinned FROM risk_runs WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.id;
 ELSIF NEW.kind='scenario' THEN pinned:=scenario_capture_complete(NEW.id); ELSE pinned:=projection_capture_complete(NEW.id); END IF;
 SELECT count(*) INTO jobs FROM premium_jobs j JOIN premium_dispatch_outbox o ON o.job_id=j.id AND o.owner_id=j.owner_id AND o.account_id=j.account_id WHERE j.run_id=NEW.id;
 IF NOT coalesce(pinned,false) OR jobs<>1 THEN RAISE EXCEPTION 'Premium request publication incomplete' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION premium_job_success_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE job premium_jobs; family text; result uuid;
BEGIN
 SELECT * INTO job FROM premium_jobs WHERE id=NEW.id;
 IF job.state IS DISTINCT FROM 'succeeded' THEN RETURN NEW; END IF;
 SELECT kind INTO family FROM premium_runs WHERE id=job.run_id AND owner_id=job.owner_id AND account_id=job.account_id;
 IF family='risk' THEN
  SELECT id INTO result FROM risk_results WHERE run_id=job.run_id AND owner_id=job.owner_id AND account_id=job.account_id;
  PERFORM premium_risk_result_complete_check(result,job.run_id,job.owner_id,job.account_id);
 ELSIF family='scenario' THEN
  SELECT id INTO result FROM scenario_results WHERE run_id=job.run_id AND owner_id=job.owner_id AND account_id=job.account_id;
  PERFORM scenario_result_complete_check(result);
 ELSIF family='projection' THEN
  SELECT id INTO result FROM projection_results WHERE run_id=job.run_id AND owner_id=job.owner_id AND account_id=job.account_id;
  PERFORM projection_result_complete_check(result);
 ELSE RAISE EXCEPTION 'Premium handler is not implemented' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION premium_run_license_guard() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE pinned boolean; family text;
      BEGIN
        IF TG_OP <> 'INSERT' THEN
          RAISE EXCEPTION 'Premium license lineage is immutable' USING ERRCODE='23514';
        END IF;
        SELECT kind INTO family FROM premium_runs WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
        IF family='risk' THEN SELECT sealed INTO pinned FROM risk_runs WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
        ELSIF family='scenario' THEN SELECT sealed INTO pinned FROM scenario_runs WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
        ELSIF family='projection' THEN SELECT sealed INTO pinned FROM projection_runs WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
        ELSE RAISE EXCEPTION 'Premium handler is not implemented' USING ERRCODE='23514'; END IF;
        IF pinned IS DISTINCT FROM false OR
          (SELECT count(*) FROM premium_run_licenses WHERE run_id=NEW.run_id)>=8192 THEN
          RAISE EXCEPTION 'Premium license lineage is sealed or over capacity' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
      END $$;"""

_PROJECTION_GUARDS = r"""CREATE FUNCTION projection_version_capacity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM owner_id FROM premium_owner_capacity WHERE owner_id=NEW.owner_id FOR UPDATE;
 IF NOT FOUND OR (SELECT count(*) FROM risk_definition_versions WHERE owner_id=NEW.owner_id)+(SELECT count(*) FROM scenario_definition_versions WHERE owner_id=NEW.owner_id)+(SELECT count(*) FROM assumption_versions WHERE owner_id=NEW.owner_id)+(SELECT count(*) FROM goal_versions WHERE owner_id=NEW.owner_id)>=512 THEN
  RAISE EXCEPTION 'Premium version capacity unavailable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION projection_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual uuid; n integer; pinned boolean; run projection_runs; root premium_runs;
        body jsonb; version assumption_versions; goal goal_versions; job premium_jobs;
        chunk projection_chunks; path projection_paths; point projection_points; source projection_run_sources;
        result projection_results; at_month date; stamp timestamptz; currency text;
BEGIN
 SELECT c.owner_id INTO actual FROM broker_accounts a JOIN broker_connections c ON c.id=a.connection_id WHERE a.id=NEW.account_id;
 IF actual IS DISTINCT FROM NEW.owner_id THEN RAISE EXCEPTION 'Projection account scope mismatch' USING ERRCODE='23514'; END IF;
 body:=to_jsonb(NEW);
 IF TG_TABLE_NAME IN ('assumption_versions','goal_versions') THEN
  IF TG_TABLE_NAME='assumption_versions' THEN
   SELECT revision INTO n FROM assumption_sets WHERE id=NEW.set_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
   IF NEW.predecessor_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM assumption_versions v WHERE v.id=NEW.predecessor_id AND v.set_id=NEW.set_id AND v.version_number=NEW.version_number-1 AND v.sealed) THEN RAISE EXCEPTION 'Projection predecessor mismatch' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT revision INTO n FROM goals WHERE id=NEW.goal_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
   IF NEW.predecessor_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM goal_versions v WHERE v.id=NEW.predecessor_id AND v.goal_id=NEW.goal_id AND v.version_number=NEW.version_number-1 AND v.sealed) THEN RAISE EXCEPTION 'Goal predecessor mismatch' USING ERRCODE='23514'; END IF;
   SELECT * INTO version FROM assumption_versions WHERE id=NEW.assumption_version_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR SHARE;
   IF NOT coalesce(version.sealed,false) OR version.reporting_currency IS DISTINCT FROM NEW.reporting_currency THEN RAISE EXCEPTION 'Goal assumption basis mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  IF n IS DISTINCT FROM NEW.version_number OR NEW.sealed THEN RAISE EXCEPTION 'Projection revision publication invalid' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME IN ('projection_assumption_assets','projection_correlation_cells','projection_calibration_pins','projection_goal_pauses','projection_goal_schedule_entries') THEN
  IF TG_TABLE_NAME IN ('projection_goal_pauses','projection_goal_schedule_entries') THEN SELECT sealed INTO pinned FROM goal_versions WHERE id=NEW.version_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
  ELSE SELECT sealed INTO pinned FROM assumption_versions WHERE id=NEW.version_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE; END IF;
  IF pinned IS DISTINCT FROM false THEN RAISE EXCEPTION 'Projection version is sealed' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME IN ('assumption_sets','goals') THEN RETURN NEW; END IF;
 IF TG_TABLE_NAME='projection_runs' THEN
  SELECT * INTO root FROM premium_runs WHERE id=NEW.id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
  IF root.kind IS DISTINCT FROM 'projection' OR root.input_digest IS DISTINCT FROM NEW.capture_digest OR root.method_version IS DISTINCT FROM '1.0.0' OR root.schema_version IS DISTINCT FROM '1.0.0' OR root.numerical_profile IS DISTINCT FROM 'premium_decimal96_q18_v1' OR NEW.sealed OR NEW.stored_bytes<>0 OR NEW.payload_rows<>0 OR NEW.retained_source_rows<>0 OR NEW.retained_source_bytes<>0 OR EXISTS(SELECT 1 FROM premium_retention_events WHERE run_id=NEW.id) THEN RAISE EXCEPTION 'Projection root binding invalid' USING ERRCODE='23514'; END IF;
  SELECT * INTO version FROM assumption_versions WHERE id=NEW.assumption_version_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR SHARE;
  IF NOT coalesce(version.sealed,false) OR version.asset_count IS DISTINCT FROM NEW.asset_count OR version.reporting_currency IS DISTINCT FROM NEW.reporting_currency OR NEW.source_count IS DISTINCT FROM version.calibration_count+(CASE WHEN NEW.initial_kind='observed_snapshot' THEN 1 ELSE 0 END) THEN RAISE EXCEPTION 'Projection assumption binding invalid' USING ERRCODE='23514'; END IF;
  IF NEW.goal_version_id IS NOT NULL THEN
   SELECT * INTO goal FROM goal_versions WHERE id=NEW.goal_version_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR SHARE;
   IF NOT coalesce(goal.sealed,false) OR goal.assumption_version_id IS DISTINCT FROM NEW.assumption_version_id OR goal.months IS DISTINCT FROM NEW.months OR goal.reporting_currency IS DISTINCT FROM NEW.reporting_currency THEN RAISE EXCEPTION 'Projection goal binding invalid' USING ERRCODE='23514'; END IF;
  END IF;
  IF NEW.snapshot_id IS NOT NULL THEN
   SELECT broker_account_id,valuation_at,reporting_currency INTO actual,stamp,currency FROM portfolio_snapshots WHERE id=NEW.snapshot_id FOR SHARE;
   IF actual IS DISTINCT FROM NEW.account_id OR stamp IS DISTINCT FROM NEW.snapshot_valuation_at OR currency IS DISTINCT FROM NEW.reporting_currency THEN RAISE EXCEPTION 'Projection snapshot binding invalid' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF body ? 'run_id' THEN
  SELECT * INTO run FROM projection_runs WHERE id=(body->>'run_id')::uuid AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
 ELSIF body ? 'result_id' THEN
  SELECT * INTO result FROM projection_results WHERE id=(body->>'result_id')::uuid AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
  SELECT * INTO run FROM projection_runs WHERE id=result.run_id;
 ELSIF TG_TABLE_NAME='projection_distribution_quantiles' THEN
  SELECT r.* INTO result FROM projection_results r JOIN projection_distributions d ON d.result_id=r.id WHERE d.id=NEW.distribution_id AND d.owner_id=NEW.owner_id AND d.account_id=NEW.account_id FOR UPDATE OF r;
  SELECT * INTO run FROM projection_runs WHERE id=result.run_id;
 ELSIF TG_TABLE_NAME='projection_histogram_bins' THEN
  SELECT r.* INTO result FROM projection_results r JOIN projection_histograms h ON h.result_id=r.id WHERE h.id=NEW.histogram_id AND h.owner_id=NEW.owner_id AND h.account_id=NEW.account_id FOR UPDATE OF r;
  SELECT * INTO run FROM projection_runs WHERE id=result.run_id;
 ELSIF TG_TABLE_NAME='projection_goal_shortfall_quantiles' THEN
  SELECT r.* INTO result FROM projection_results r JOIN projection_goal_analyses a ON a.result_id=r.id WHERE a.id=NEW.analysis_id AND a.owner_id=NEW.owner_id AND a.account_id=NEW.account_id FOR UPDATE OF r;
  SELECT * INTO run FROM projection_runs WHERE id=result.run_id;
 END IF;
 IF run.id IS NULL OR EXISTS(SELECT 1 FROM premium_retention_events WHERE run_id=run.id) THEN RAISE EXCEPTION 'Projection input is unavailable' USING ERRCODE='23514'; END IF;
 SELECT * INTO root FROM premium_runs WHERE id=run.id FOR UPDATE;
 IF root.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'Projection input expired' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME IN ('projection_inputs','projection_run_allocations','projection_calendar_boundaries','projection_run_pauses','projection_run_schedule_entries','projection_run_sources','projection_source_proofs','projection_source_licenses') THEN
  IF run.sealed THEN RAISE EXCEPTION 'Projection capture is sealed' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME='projection_run_allocations' THEN IF NOT EXISTS(SELECT 1 FROM projection_assumption_assets a WHERE a.version_id=run.assumption_version_id AND a.asset_index=NEW.asset_index AND a.asset_key=NEW.asset_key AND a.weight=NEW.weight) THEN RAISE EXCEPTION 'Projection allocation mismatch' USING ERRCODE='23514'; END IF; END IF;
  IF TG_TABLE_NAME='projection_run_sources' THEN
   IF NEW.source_expires_at<root.expires_at OR NEW.original_created_at>NEW.created_at THEN RAISE EXCEPTION 'Projection source lifetime mismatch' USING ERRCODE='23514'; END IF;
   IF NEW.kind='calibration' AND NOT EXISTS(SELECT 1 FROM projection_calibration_pins p WHERE p.version_id=run.assumption_version_id AND p.subject_id=NEW.subject_id AND p.content_digest=NEW.content_digest) THEN RAISE EXCEPTION 'Projection calibration identity mismatch' USING ERRCODE='23514'; END IF;
   IF NEW.kind='initial_snapshot' AND (run.initial_kind<>'observed_snapshot' OR NEW.subject_id IS DISTINCT FROM run.snapshot_id OR NEW.content_digest IS DISTINCT FROM run.snapshot_digest OR NOT EXISTS(SELECT 1 FROM portfolio_snapshots s WHERE s.id=run.snapshot_id AND s.created_at=NEW.original_created_at)) THEN RAISE EXCEPTION 'Projection observed source mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME IN ('projection_source_proofs','projection_source_licenses') THEN
   SELECT * INTO source FROM projection_run_sources WHERE id=NEW.source_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
   IF source.run_id IS DISTINCT FROM run.id THEN RAISE EXCEPTION 'Projection source copy scope mismatch' USING ERRCODE='23514'; END IF;
   IF TG_TABLE_NAME='projection_source_proofs' THEN IF (octet_length(NEW.canonical_proof)<>source.proof_bytes OR encode(sha256(NEW.canonical_proof),'hex') IS DISTINCT FROM source.proof_digest) THEN RAISE EXCEPTION 'Projection source proof mismatch' USING ERRCODE='23514'; END IF; END IF;
   IF TG_TABLE_NAME='projection_source_licenses' THEN IF NOT EXISTS(SELECT 1 FROM premium_run_licenses l WHERE l.id=NEW.run_license_id AND l.run_id=run.id) THEN RAISE EXCEPTION 'Projection source license scope mismatch' USING ERRCODE='23514'; END IF; END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF NOT run.sealed THEN RAISE EXCEPTION 'Projection capture is incomplete' USING ERRCODE='23514'; END IF;
 IF body ? 'variant' AND run.variant_count=1 AND body->>'variant'<>'baseline' THEN RAISE EXCEPTION 'Projection unrequested variant' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='projection_chunks' THEN
  SELECT * INTO job FROM premium_jobs WHERE id=NEW.job_id AND run_id=run.id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
  IF job.state IS DISTINCT FROM 'running' OR job.lease_token IS DISTINCT FROM NEW.lease_token OR job.consumer_attempts IS DISTINCT FROM NEW.consumer_attempt OR job.lease_expires_at<=clock_timestamp() OR job.deadline_at<=clock_timestamp() OR NEW.sealed OR NEW.first_path+NEW.path_count>run.path_count OR EXISTS(SELECT 1 FROM projection_results WHERE run_id=run.id) THEN RAISE EXCEPTION 'Projection chunk fence invalid' USING ERRCODE='23514'; END IF;
  IF EXISTS(SELECT 1 FROM projection_chunks c WHERE c.run_id=run.id AND c.variant=NEW.variant AND int4range(c.first_path,c.first_path+c.path_count,'[)') && int4range(NEW.first_path,NEW.first_path+NEW.path_count,'[)')) THEN RAISE EXCEPTION 'Projection chunk path overlap' USING ERRCODE='23514'; END IF;
  IF encode(sha256(NEW.canonical_chunk),'hex') IS DISTINCT FROM NEW.content_digest THEN RAISE EXCEPTION 'Projection chunk digest mismatch' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME IN ('projection_paths','projection_points','projection_point_assets') THEN
  IF TG_TABLE_NAME='projection_paths' THEN SELECT * INTO chunk FROM projection_chunks WHERE id=NEW.chunk_id AND run_id=run.id FOR UPDATE;
  ELSIF TG_TABLE_NAME='projection_points' THEN
   SELECT * INTO path FROM projection_paths WHERE id=NEW.path_id AND run_id=run.id;
   SELECT * INTO chunk FROM projection_chunks WHERE id=path.chunk_id AND run_id=run.id FOR UPDATE;
  ELSE
   SELECT * INTO point FROM projection_points WHERE id=NEW.point_id AND run_id=run.id;
   SELECT * INTO path FROM projection_paths WHERE id=point.path_id AND run_id=run.id;
   SELECT * INTO chunk FROM projection_chunks WHERE id=path.chunk_id AND run_id=run.id FOR UPDATE;
  END IF;
  IF chunk.id IS NULL OR chunk.sealed THEN RAISE EXCEPTION 'Projection checkpoint is sealed' USING ERRCODE='23514'; END IF;
  SELECT * INTO job FROM premium_jobs WHERE id=chunk.job_id FOR UPDATE;
  IF job.state IS DISTINCT FROM 'running' OR job.lease_token IS DISTINCT FROM chunk.lease_token OR job.consumer_attempts IS DISTINCT FROM chunk.consumer_attempt OR job.lease_expires_at<=clock_timestamp() OR job.deadline_at<=clock_timestamp() THEN RAISE EXCEPTION 'Projection point fence invalid' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME='projection_paths' THEN IF (NEW.variant IS DISTINCT FROM chunk.variant OR NEW.path_index<chunk.first_path OR NEW.path_index>=chunk.first_path+chunk.path_count OR NEW.first_unpaid_month>run.months) THEN RAISE EXCEPTION 'Projection path identity mismatch' USING ERRCODE='23514'; END IF; END IF;
  IF TG_TABLE_NAME='projection_points' THEN IF NOT EXISTS(SELECT 1 FROM projection_calendar_boundaries b WHERE b.run_id=run.id AND b.month=NEW.month AND b.point_index=NEW.point_index) THEN RAISE EXCEPTION 'Projection point identity mismatch' USING ERRCODE='23514'; END IF; END IF;
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='projection_results' THEN
  SELECT * INTO job FROM premium_jobs WHERE run_id=run.id FOR UPDATE;
  IF job.id IS DISTINCT FROM NEW.job_id OR job.lease_token IS DISTINCT FROM NEW.lease_token OR job.consumer_attempts IS DISTINCT FROM NEW.consumer_attempt OR job.state IS DISTINCT FROM 'running' OR job.lease_expires_at<=clock_timestamp() OR job.deadline_at<=clock_timestamp() OR NEW.sealed OR octet_length(NEW.canonical_result)=0 OR encode(sha256(NEW.canonical_result),'hex') IS DISTINCT FROM NEW.content_digest THEN RAISE EXCEPTION 'Projection result fence or digest invalid' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF result.id IS NULL OR result.sealed THEN RAISE EXCEPTION 'Projection result is sealed' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='projection_zero_pivots' THEN IF NEW.asset_index>=run.asset_count THEN RAISE EXCEPTION 'Projection pivot identity mismatch' USING ERRCODE='23514'; END IF; END IF;
 IF TG_TABLE_NAME='projection_distributions' THEN IF (NEW.funding_failed_paths>run.path_count OR NOT EXISTS(SELECT 1 FROM projection_calendar_boundaries b WHERE b.run_id=run.id AND b.month=NEW.month AND b.point_index IS NOT NULL)) THEN RAISE EXCEPTION 'Projection distribution identity mismatch' USING ERRCODE='23514'; END IF; END IF;
 IF TG_TABLE_NAME='projection_goal_analyses' THEN IF (NEW.goal_version_id IS DISTINCT FROM run.goal_version_id OR NEW.paths IS DISTINCT FROM run.path_count) THEN RAISE EXCEPTION 'Projection goal result identity mismatch' USING ERRCODE='23514'; END IF; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION projection_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE body jsonb; run_id uuid; parent_result uuid; root premium_runs; marker premium_retention_events;
BEGIN
 IF TG_OP='UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
 IF TG_TABLE_NAME='projection_runs' AND TG_OP='UPDATE' AND pg_trigger_depth()>1 AND (to_jsonb(NEW)-ARRAY['stored_bytes','payload_rows','retained_source_rows','retained_source_bytes'])=(to_jsonb(OLD)-ARRAY['stored_bytes','payload_rows','retained_source_rows','retained_source_bytes']) THEN RETURN NEW; END IF;
 body:=to_jsonb(OLD);
 IF TG_OP='UPDATE' THEN
  IF TG_TABLE_NAME IN ('assumption_sets','goals') THEN
   IF NEW.revision=OLD.revision+1 AND NEW.updated_at>=OLD.updated_at AND (to_jsonb(NEW)-ARRAY['revision','name','updated_at'])=(body-ARRAY['revision','name','updated_at']) THEN RETURN NEW; END IF;
  ELSIF TG_TABLE_NAME IN ('assumption_versions','goal_versions','projection_runs','projection_chunks','projection_results') THEN
   IF NOT OLD.sealed AND NEW.sealed AND (to_jsonb(NEW)-'sealed')=(body-'sealed') THEN RETURN NEW; END IF;
  END IF;
 END IF;
 IF TG_TABLE_NAME IN ('assumption_sets','assumption_versions','projection_assumption_assets','projection_correlation_cells','projection_calibration_pins','goals','goal_versions','projection_goal_pauses','projection_goal_schedule_entries','projection_runs','projection_run_sources','projection_source_licenses') THEN RAISE EXCEPTION 'Published projection content is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP<>'DELETE' THEN
  IF TG_TABLE_NAME<>'projection_results' THEN RAISE EXCEPTION 'Published projection content is immutable' USING ERRCODE='23514'; END IF;
  IF NEW.canonical_result<>'\x'::bytea OR (to_jsonb(NEW)-'canonical_result')<>(body-'canonical_result') THEN RAISE EXCEPTION 'Published projection content is immutable' USING ERRCODE='23514'; END IF;
 END IF;
 IF body ? 'run_id' THEN run_id:=(body->>'run_id')::uuid;
 ELSIF body ? 'result_id' THEN SELECT r.run_id INTO run_id FROM projection_results r WHERE r.id=(body->>'result_id')::uuid;
 ELSIF TG_TABLE_NAME='projection_distribution_quantiles' THEN SELECT r.run_id INTO run_id FROM projection_results r JOIN projection_distributions d ON d.result_id=r.id WHERE d.id=OLD.distribution_id;
 ELSIF TG_TABLE_NAME='projection_histogram_bins' THEN SELECT r.run_id INTO run_id FROM projection_results r JOIN projection_histograms h ON h.result_id=r.id WHERE h.id=OLD.histogram_id;
 ELSIF TG_TABLE_NAME='projection_goal_shortfall_quantiles' THEN SELECT r.run_id INTO run_id FROM projection_results r JOIN projection_goal_analyses a ON a.result_id=r.id WHERE a.id=OLD.analysis_id; END IF;
 SELECT * INTO root FROM premium_runs WHERE id=run_id FOR UPDATE;
 SELECT * INTO marker FROM premium_retention_events e WHERE e.run_id=root.id AND e.owner_id=OLD.owner_id AND e.account_id=OLD.account_id;
 IF root.kind IS DISTINCT FROM 'projection' OR marker.id IS NULL OR marker.completed_at IS NOT NULL THEN RAISE EXCEPTION 'Projection retention marker required' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN RETURN NEW; END IF;
 RETURN OLD;
END $$;

CREATE FUNCTION projection_definition_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE identity uuid; head record; current record; version assumption_versions; goal goal_versions;
BEGIN
 IF TG_TABLE_NAME IN ('assumption_sets','assumption_versions') THEN
  identity:=CASE WHEN TG_TABLE_NAME='assumption_sets' THEN NEW.id ELSE (to_jsonb(NEW)->>'set_id')::uuid END;
  SELECT * INTO head FROM assumption_sets WHERE id=identity;
  SELECT * INTO current FROM assumption_versions WHERE set_id=identity ORDER BY version_number DESC LIMIT 1;
  IF current.id IS NULL OR NOT current.sealed OR head.revision IS DISTINCT FROM current.version_number OR head.name IS DISTINCT FROM current.name THEN RAISE EXCEPTION 'Projection assumption head incomplete' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME='assumption_versions' THEN SELECT * INTO version FROM assumption_versions WHERE id=NEW.id; ELSE SELECT * INTO version FROM assumption_versions WHERE id=current.id; END IF;
  IF NOT version.sealed OR version.asset_count<>(SELECT count(*) FROM projection_assumption_assets WHERE version_id=version.id) OR version.asset_count-1<>(SELECT max(asset_index) FROM projection_assumption_assets WHERE version_id=version.id) OR 1<>(SELECT sum(weight) FROM projection_assumption_assets WHERE version_id=version.id) OR version.asset_count*version.asset_count<>(SELECT count(*) FROM projection_correlation_cells WHERE version_id=version.id) OR version.calibration_count<>(SELECT count(*) FROM projection_calibration_pins WHERE version_id=version.id) THEN RAISE EXCEPTION 'Projection assumption children incomplete' USING ERRCODE='23514'; END IF;
  IF NOT EXISTS(SELECT 1 FROM application_command_identities c JOIN premium_audit_events a ON a.command_id=c.id AND a.kind='created' WHERE c.owner_id=version.owner_id AND c.account_id=version.account_id AND c.premium_resource_id=CASE WHEN version.version_number=1 THEN version.set_id ELSE version.id END AND c.command=CASE WHEN version.version_number=1 THEN 'projection.assumption.create.v1' ELSE 'projection.assumption.version.create.v1' END) THEN RAISE EXCEPTION 'Projection assumption audit missing' USING ERRCODE='23514'; END IF;
  IF EXISTS(SELECT 1 FROM projection_correlation_cells c LEFT JOIN projection_correlation_cells t ON t.version_id=c.version_id AND t.row_index=c.column_index AND t.column_index=c.row_index WHERE c.version_id=version.id AND c.value IS DISTINCT FROM t.value) OR EXISTS(SELECT 1 FROM projection_assumption_assets a JOIN projection_assumption_assets b ON b.version_id=a.version_id AND b.asset_index=a.asset_index+1 WHERE a.version_id=version.id AND a.asset_key COLLATE "C">=b.asset_key COLLATE "C") THEN RAISE EXCEPTION 'Projection canonical asset matrix mismatch' USING ERRCODE='23514'; END IF;
 ELSE
  identity:=CASE WHEN TG_TABLE_NAME='goals' THEN NEW.id ELSE (to_jsonb(NEW)->>'goal_id')::uuid END;
  SELECT * INTO head FROM goals WHERE id=identity;
  SELECT * INTO current FROM goal_versions WHERE goal_id=identity ORDER BY version_number DESC LIMIT 1;
  IF current.id IS NULL OR NOT current.sealed OR head.revision IS DISTINCT FROM current.version_number OR head.name IS DISTINCT FROM current.name THEN RAISE EXCEPTION 'Projection goal head incomplete' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME='goal_versions' THEN SELECT * INTO goal FROM goal_versions WHERE id=NEW.id; ELSE SELECT * INTO goal FROM goal_versions WHERE id=current.id; END IF;
  IF NOT EXISTS(SELECT 1 FROM application_command_identities c JOIN premium_audit_events a ON a.command_id=c.id AND a.kind='created' WHERE c.owner_id=goal.owner_id AND c.account_id=goal.account_id AND c.premium_resource_id=CASE WHEN goal.version_number=1 THEN goal.goal_id ELSE goal.id END AND c.command=CASE WHEN goal.version_number=1 THEN 'projection.goal.create.v1' ELSE 'projection.goal.version.create.v1' END) THEN RAISE EXCEPTION 'Projection goal audit missing' USING ERRCODE='23514'; END IF;
  IF NOT goal.sealed OR goal.pause_count<>(SELECT count(*) FROM projection_goal_pauses WHERE version_id=goal.id) OR goal.entry_count<>(SELECT count(*) FROM projection_goal_schedule_entries WHERE version_id=goal.id) THEN RAISE EXCEPTION 'Projection goal schedule incomplete' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION projection_capture_complete(p_run uuid) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE run projection_runs; input projection_inputs; goal goal_versions; canonical jsonb; captured jsonb;
BEGIN
 SELECT * INTO run FROM projection_runs WHERE id=p_run;
 SELECT * INTO input FROM projection_inputs WHERE run_id=p_run;
 IF run.id IS NULL OR NOT run.sealed OR input.id IS NULL OR NOT projection_source_membership_complete(p_run) THEN RETURN false; END IF;
 IF encode(sha256(convert_to('t212pi.projection.capture.v1','UTF8')||decode('00','hex')||input.canonical_capture),'hex') IS DISTINCT FROM run.capture_digest OR encode(sha256(convert_to('t212pi.projection.input.v1','UTF8')||decode('00','hex')||input.canonical_input),'hex') IS DISTINCT FROM run.numerical_input_digest THEN RETURN false; END IF;
 canonical:=convert_from(input.canonical_input,'UTF8')::jsonb; captured:=convert_from(input.canonical_capture,'UTF8')::jsonb;
 IF captured->'inputs' IS DISTINCT FROM canonical OR captured->>'numerical_input_digest' IS DISTINCT FROM run.numerical_input_digest OR captured->'selection'->>'account_id' IS DISTINCT FROM run.account_id::text OR canonical->>'assumption_version_id' IS DISTINCT FROM run.assumption_version_id::text OR (canonical->>'seed')::bigint IS DISTINCT FROM run.seed OR (canonical->>'months')::integer IS DISTINCT FROM run.months OR (canonical->>'paths')::integer IS DISTINCT FROM run.path_count OR canonical->'initial'->>'kind' IS DISTINCT FROM run.initial_kind OR (canonical->'initial'->'value'->>'amount')::numeric IS DISTINCT FROM input.initial_value OR canonical->'initial'->'value'->>'currency' IS DISTINCT FROM run.reporting_currency THEN RETURN false; END IF;
 IF (input.contribution_delta IS NOT NULL) IS DISTINCT FROM (run.variant_count=3) OR (canonical->'schedule'->'base_monthly'->>'amount')::numeric IS DISTINCT FROM input.base_monthly OR (canonical->'schedule'->>'annual_growth')::numeric IS DISTINCT FROM input.annual_growth THEN RETURN false; END IF;
 IF run.variant_count=3 AND ((canonical->'sensitivity'->'contribution_delta'->>'amount')::numeric IS DISTINCT FROM input.contribution_delta OR (canonical->'sensitivity'->>'annual_mean_log_delta')::numeric IS DISTINCT FROM input.annual_mean_log_delta OR input.base_monthly+input.contribution_delta<0 OR EXISTS(SELECT 1 FROM projection_assumption_assets a WHERE a.version_id=run.assumption_version_id AND a.annual_mean_log_return+input.annual_mean_log_delta NOT BETWEEN -.5 AND .5)) THEN RETURN false; END IF;
 IF run.initial_kind='observed_snapshot' AND NOT EXISTS(SELECT 1 FROM portfolio_snapshots s WHERE s.id=run.snapshot_id AND s.broker_account_id=run.account_id AND s.portfolio_total=input.initial_value AND s.reporting_currency=run.reporting_currency) THEN RETURN false; END IF;
 IF run.asset_count<>(SELECT count(*) FROM projection_run_allocations WHERE run_id=p_run) OR run.months+1<>(SELECT count(*) FROM projection_calendar_boundaries WHERE run_id=p_run) OR run.retained_point_count<>(SELECT count(*) FROM projection_calendar_boundaries WHERE run_id=p_run AND point_index IS NOT NULL) OR input.pause_count<>(SELECT count(*) FROM projection_run_pauses WHERE run_id=p_run) OR input.entry_count<>(SELECT count(*) FROM projection_run_schedule_entries WHERE run_id=p_run) OR run.source_count<>(SELECT count(*) FROM projection_run_sources WHERE run_id=p_run) OR run.source_count<>(SELECT count(*) FROM projection_source_proofs WHERE run_id=p_run) THEN RETURN false; END IF;
 IF EXISTS(SELECT 1 FROM projection_calendar_boundaries b WHERE b.run_id=p_run AND (b.month>run.months OR b."on"<>(run.anchor_date+make_interval(months=>b.month))::date OR (b.month=0 AND b.point_index IS DISTINCT FROM 0) OR (b.month=run.months AND b.point_index IS DISTINCT FROM run.retained_point_count-1))) OR EXISTS(SELECT 1 FROM (SELECT point_index,row_number() OVER(ORDER BY month)-1 ordinal FROM projection_calendar_boundaries WHERE run_id=p_run AND point_index IS NOT NULL) b WHERE b.point_index<>b.ordinal) THEN RETURN false; END IF;
 IF (SELECT jsonb_agg(month ORDER BY month) FROM projection_calendar_boundaries WHERE run_id=p_run AND point_index IS NOT NULL) IS DISTINCT FROM canonical->'retained_months' THEN RETURN false; END IF;
 IF EXISTS(SELECT 1 FROM projection_run_pauses p LEFT JOIN projection_calendar_boundaries b ON b.run_id=p.run_id AND b.month=p.month-1 WHERE p.run_id=p_run AND (p.month>run.months OR p."on" IS DISTINCT FROM b."on")) OR EXISTS(SELECT 1 FROM projection_run_schedule_entries e LEFT JOIN projection_calendar_boundaries b ON b.run_id=e.run_id AND b.month=e.month-1 WHERE e.run_id=p_run AND (e.month>run.months OR e."on" IS DISTINCT FROM b."on")) THEN RETURN false; END IF;
 IF run.goal_version_id IS NOT NULL THEN
  SELECT * INTO goal FROM goal_versions WHERE id=run.goal_version_id;
  IF goal.target_date<>(run.anchor_date+make_interval(months=>run.months))::date OR goal.base_monthly IS DISTINCT FROM input.base_monthly OR goal.annual_growth IS DISTINCT FROM input.annual_growth OR goal.pause_count<>input.pause_count OR goal.entry_count<>input.entry_count THEN RETURN false; END IF;
  IF EXISTS(SELECT 1 FROM projection_goal_pauses p WHERE p.version_id=goal.id AND NOT EXISTS(SELECT 1 FROM projection_run_pauses r WHERE r.run_id=p_run AND r."on"=p."on")) OR EXISTS(SELECT 1 FROM projection_goal_schedule_entries e WHERE e.version_id=goal.id AND NOT EXISTS(SELECT 1 FROM projection_run_schedule_entries r WHERE r.run_id=p_run AND r.entry_key=e.entry_key AND r."on"=e."on" AND r.kind=e.kind AND r.value=e.value)) THEN RETURN false; END IF;
 END IF;
 IF EXISTS(SELECT 1 FROM projection_calibration_pins p WHERE p.version_id=run.assumption_version_id AND NOT EXISTS(SELECT 1 FROM projection_run_sources s WHERE s.run_id=p_run AND s.kind='calibration' AND s.subject_id=p.subject_id AND s.content_digest=p.content_digest)) THEN RETURN false; END IF;
 IF EXISTS(SELECT 1 FROM premium_run_licenses l WHERE l.run_id=p_run AND NOT EXISTS(SELECT 1 FROM projection_source_licenses s WHERE s.run_id=p_run AND s.run_license_id=l.id)) THEN RETURN false; END IF;
 IF captured->'calendar'->>'anchor_date' IS DISTINCT FROM to_char(run.anchor_date,'YYYY-MM-DD') OR (captured->'calendar'->>'months')::integer IS DISTINCT FROM run.months OR captured->'calendar'->>'rule' IS DISTINCT FROM run.calendar_rule OR captured->'calendar'->'boundaries' IS DISTINCT FROM (SELECT jsonb_agg(to_char(b."on",'YYYY-MM-DD') ORDER BY b.month) FROM projection_calendar_boundaries b WHERE b.run_id=p_run) THEN RETURN false; END IF;
 IF captured->'selection'->>'assumption_version_id' IS DISTINCT FROM run.assumption_version_id::text OR captured->'selection'->>'goal_version_id' IS DISTINCT FROM run.goal_version_id::text OR captured->'selection'->'initial'->>'kind' IS DISTINCT FROM run.initial_kind THEN RETURN false; END IF;
 IF captured->'assumption_version'->>'content_digest' IS DISTINCT FROM run.assumption_digest OR captured->'assumption_version'->>'version_id' IS DISTINCT FROM run.assumption_version_id::text OR captured->'assumption_version'->'content' IS DISTINCT FROM canonical->'assumptions' THEN RETURN false; END IF;
 IF NOT EXISTS(SELECT 1 FROM assumption_versions v WHERE v.id=run.assumption_version_id AND v.reporting_currency=canonical->'assumptions'->>'reporting_currency' AND v.annual_inflation=(canonical->'assumptions'->>'annual_inflation')::numeric AND v.annual_fee=(canonical->'assumptions'->>'annual_fee')::numeric AND v.annual_tax_drag IS NOT DISTINCT FROM (canonical->'assumptions'->>'annual_tax_drag')::numeric AND v.rebalance=canonical->'assumptions'->>'rebalance') THEN RETURN false; END IF;
 IF jsonb_array_length(canonical->'assumptions'->'assets') IS DISTINCT FROM run.asset_count OR jsonb_array_length(canonical->'assumptions'->'correlation') IS DISTINCT FROM run.asset_count OR jsonb_array_length(canonical->'allocation') IS DISTINCT FROM run.asset_count THEN RETURN false; END IF;
 IF EXISTS(SELECT 1 FROM projection_assumption_assets a WHERE a.version_id=run.assumption_version_id AND (canonical->'assumptions'->'assets'->a.asset_index->>'key' IS DISTINCT FROM a.asset_key OR (canonical->'assumptions'->'assets'->a.asset_index->>'weight')::numeric IS DISTINCT FROM a.weight OR (canonical->'assumptions'->'assets'->a.asset_index->>'annual_mean_log_return')::numeric IS DISTINCT FROM a.annual_mean_log_return OR (canonical->'assumptions'->'assets'->a.asset_index->>'annual_volatility')::numeric IS DISTINCT FROM a.annual_volatility OR jsonb_array_length(canonical->'assumptions'->'correlation'->a.asset_index) IS DISTINCT FROM run.asset_count OR canonical->'allocation'->a.asset_index->>'key' IS DISTINCT FROM a.asset_key OR (canonical->'allocation'->a.asset_index->>'weight')::numeric IS DISTINCT FROM a.weight)) OR EXISTS(SELECT 1 FROM projection_correlation_cells c WHERE c.version_id=run.assumption_version_id AND (canonical->'assumptions'->'correlation'->c.row_index->>c.column_index)::numeric IS DISTINCT FROM c.value) THEN RETURN false; END IF;
 IF jsonb_array_length(canonical->'assumptions'->'calibration_pins') IS DISTINCT FROM (SELECT calibration_count FROM assumption_versions WHERE id=run.assumption_version_id) OR EXISTS(SELECT 1 FROM jsonb_array_elements(canonical->'assumptions'->'calibration_pins') p WHERE NOT EXISTS(SELECT 1 FROM projection_calibration_pins c WHERE c.version_id=run.assumption_version_id AND c.subject_id::text=p->>'subject_id' AND c.content_digest=p->>'content_digest')) THEN RETURN false; END IF;
 IF coalesce((SELECT jsonb_agg(month ORDER BY month) FROM projection_run_pauses WHERE run_id=p_run),'[]'::jsonb) IS DISTINCT FROM canonical->'schedule'->'paused_months' OR jsonb_array_length(canonical->'schedule'->'entries') IS DISTINCT FROM input.entry_count OR EXISTS(SELECT 1 FROM jsonb_array_elements(canonical->'schedule'->'entries') e WHERE NOT EXISTS(SELECT 1 FROM projection_run_schedule_entries n WHERE n.run_id=p_run AND n.entry_key=e->>'key' AND n.month=(e->>'month')::integer AND n.kind=e->>'kind' AND n.value=(e->'value'->>'amount')::numeric AND e->'value'->>'currency'=run.reporting_currency)) THEN RETURN false; END IF;
 IF run.goal_version_id IS NULL THEN
  IF canonical->'goal' IS DISTINCT FROM 'null'::jsonb OR captured->'goal_version' IS DISTINCT FROM 'null'::jsonb THEN RETURN false; END IF;
 ELSE
  IF captured->'goal_version'->>'version_id' IS DISTINCT FROM run.goal_version_id::text OR captured->'goal_version'->>'content_digest' IS DISTINCT FROM run.goal_digest OR canonical->'goal'->>'version_id' IS DISTINCT FROM run.goal_version_id::text OR canonical->'goal'->>'assumption_version_id' IS DISTINCT FROM run.assumption_version_id::text OR canonical->'goal'->'schedule' IS DISTINCT FROM canonical->'schedule' OR (canonical->'goal'->>'months')::integer IS DISTINCT FROM goal.months OR (canonical->'goal'->'target'->>'amount')::numeric IS DISTINCT FROM goal.target OR canonical->'goal'->'target'->>'currency' IS DISTINCT FROM goal.reporting_currency OR canonical->'goal'->>'basis' IS DISTINCT FROM goal.basis OR (canonical->'goal'->>'probability_objective')::numeric IS DISTINCT FROM goal.probability_objective THEN RETURN false; END IF;
 END IF;
 RETURN true;
END $$;

CREATE FUNCTION projection_chunk_complete_check(p_chunk uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE chunk projection_chunks; run projection_runs; canonical jsonb; path_json jsonb; point_json jsonb; asset_json jsonb;
        path projection_paths; point projection_points; asset record; n integer; i integer; j integer; value_name text;
BEGIN
 SELECT * INTO chunk FROM projection_chunks WHERE id=p_chunk;
 SELECT * INTO run FROM projection_runs WHERE id=chunk.run_id;
 IF chunk.id IS NULL OR NOT chunk.sealed OR (SELECT count(*) FROM projection_paths WHERE chunk_id=p_chunk)<>chunk.path_count THEN RAISE EXCEPTION 'Projection checkpoint incomplete' USING ERRCODE='23514'; END IF;
 canonical:=convert_from(chunk.canonical_chunk,'UTF8')::jsonb;
 IF canonical->>'input_digest' IS DISTINCT FROM chunk.input_digest OR canonical->>'variant' IS DISTINCT FROM chunk.variant OR jsonb_typeof(canonical->'paths') IS DISTINCT FROM 'array' OR jsonb_array_length(canonical->'paths')<>chunk.path_count THEN RAISE EXCEPTION 'Projection checkpoint bytes differ' USING ERRCODE='23514'; END IF;
 FOR path IN SELECT * FROM projection_paths WHERE chunk_id=p_chunk ORDER BY path_index LOOP
  path_json:=canonical->'paths'->(path.path_index-chunk.first_path);
  IF (path_json->>'index')::integer IS DISTINCT FROM path.path_index OR path_json->>'reporting_currency' IS DISTINCT FROM run.reporting_currency OR (path_json->>'first_unpaid_month')::integer IS DISTINCT FROM path.first_unpaid_month OR jsonb_typeof(path_json->'points') IS DISTINCT FROM 'array' OR jsonb_array_length(path_json->'points')<>run.retained_point_count OR (SELECT count(*) FROM projection_points WHERE path_id=path.id)<>run.retained_point_count THEN RAISE EXCEPTION 'Projection retained path incomplete' USING ERRCODE='23514'; END IF;
  FOR point IN SELECT * FROM projection_points WHERE path_id=path.id ORDER BY point_index LOOP
   point_json:=path_json->'points'->point.point_index;
   IF (point_json->>'month')::integer IS DISTINCT FROM point.month OR (point_json->>'funding_failed')::boolean IS DISTINCT FROM point.funding_failed OR (point_json->>'unpaid_positive_below_quantum')::boolean IS DISTINCT FROM point.unpaid_positive_below_quantum OR jsonb_typeof(point_json->'assets') IS DISTINCT FROM 'array' OR jsonb_array_length(point_json->'assets')<>run.asset_count OR (SELECT count(*) FROM projection_point_assets WHERE point_id=point.id)<>run.asset_count THEN RAISE EXCEPTION 'Projection point bytes differ' USING ERRCODE='23514'; END IF;
   FOREACH value_name IN ARRAY ARRAY['nominal','real','contributions','withdrawals_requested','withdrawals_funded','unpaid_withdrawals','investment_effect','fees','tax_drag','wealth_residual','allocation_residual','withdrawal_residual'] LOOP
    IF jsonb_typeof(point_json->value_name) IS DISTINCT FROM 'string' OR (point_json->>value_name)::numeric IS DISTINCT FROM (to_jsonb(point)->>value_name)::numeric THEN RAISE EXCEPTION 'Projection retained money differs' USING ERRCODE='23514'; END IF;
   END LOOP;
   FOR asset IN SELECT a.asset_index,a.value,w.asset_key FROM projection_point_assets a JOIN projection_run_allocations w ON w.run_id=a.run_id AND w.asset_index=a.asset_index WHERE a.point_id=point.id ORDER BY a.asset_index LOOP
    asset_json:=point_json->'assets'->asset.asset_index;
    IF asset_json->>'key' IS DISTINCT FROM asset.asset_key OR jsonb_typeof(asset_json->'value') IS DISTINCT FROM 'string' OR (asset_json->>'value')::numeric IS DISTINCT FROM asset.value THEN RAISE EXCEPTION 'Projection retained asset differs' USING ERRCODE='23514'; END IF;
   END LOOP;
   IF point.allocation_residual IS DISTINCT FROM point.nominal-(SELECT sum(value) FROM projection_point_assets WHERE point_id=point.id) OR point.funding_failed IS DISTINCT FROM (path.first_unpaid_month IS NOT NULL AND point.month>=path.first_unpaid_month) THEN RAISE EXCEPTION 'Projection retained funding differs' USING ERRCODE='23514'; END IF;
  END LOOP;
 END LOOP;
END $$;

CREATE FUNCTION projection_chunk_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM premium_retention_events WHERE run_id=NEW.run_id) THEN PERFORM projection_chunk_complete_check(NEW.id); END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION projection_result_complete_check(p_result uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE result projection_results; run projection_runs; input projection_inputs; canonical jsonb; variant_json jsonb; path_json jsonb; point_json jsonb; summary projection_distributions; histogram projection_histograms; bin projection_histogram_bins; goal projection_goal_analyses; body jsonb; quantile record; i integer; index integer; field_name text; chunk projection_chunks;
BEGIN
 SELECT * INTO result FROM projection_results WHERE id=p_result;
 SELECT * INTO run FROM projection_runs WHERE id=result.run_id;
 SELECT * INTO input FROM projection_inputs WHERE run_id=run.id;
 IF result.id IS NULL OR NOT result.sealed OR NOT EXISTS(SELECT 1 FROM premium_jobs j WHERE j.run_id=run.id AND j.state='succeeded') OR input.id IS NULL THEN RAISE EXCEPTION 'Projection result publication incomplete' USING ERRCODE='23514'; END IF;
 canonical:=convert_from(result.canonical_result,'UTF8')::jsonb;
 IF canonical->>'input_digest' IS DISTINCT FROM run.numerical_input_digest OR canonical->'inputs' IS DISTINCT FROM convert_from(input.canonical_input,'UTF8')::jsonb OR canonical->>'method' IS DISTINCT FROM 'projection_v1' OR canonical->>'method_version' IS DISTINCT FROM '1.0.0' OR canonical->>'numeric_profile' IS DISTINCT FROM 'premium_decimal96_q18_v1' OR canonical->>'sampler' IS DISTINCT FROM 'sha256_counter_polar_v1' OR jsonb_typeof(canonical->'variants') IS DISTINCT FROM 'array' OR jsonb_array_length(canonical->'variants')<>run.variant_count THEN RAISE EXCEPTION 'Projection result input binding differs' USING ERRCODE='23514'; END IF;
 IF coalesce((SELECT jsonb_agg(asset_index ORDER BY asset_index) FROM projection_zero_pivots WHERE result_id=p_result),'[]'::jsonb) IS DISTINCT FROM canonical->'numerical_zero_pivots' THEN RAISE EXCEPTION 'Projection pivot summary differs' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM projection_paths WHERE run_id=run.id)<>run.variant_count*run.path_count OR (SELECT count(*) FROM projection_distributions WHERE result_id=p_result)<>run.variant_count*run.retained_point_count OR (SELECT count(*) FROM projection_histograms WHERE result_id=p_result)<>run.variant_count*2 OR (SELECT count(*) FROM projection_goal_analyses WHERE result_id=p_result)<>(CASE WHEN run.goal_version_id IS NULL THEN 0 ELSE run.variant_count END) THEN RAISE EXCEPTION 'Projection result path or summary set incomplete' USING ERRCODE='23514'; END IF;
 FOR chunk IN SELECT * FROM projection_chunks WHERE run_id=run.id LOOP
  PERFORM projection_chunk_complete_check(chunk.id);
 END LOOP;
 FOR index IN 0..run.variant_count-1 LOOP
  variant_json:=canonical->'variants'->index;
  IF variant_json->>'variant' IS DISTINCT FROM (ARRAY['baseline','contribution_delta','mean_log_delta'])[index+1] OR jsonb_typeof(variant_json->'paths') IS DISTINCT FROM 'array' OR jsonb_array_length(variant_json->'paths')<>run.path_count OR jsonb_typeof(variant_json->'distributions') IS DISTINCT FROM 'array' OR jsonb_array_length(variant_json->'distributions')<>run.retained_point_count THEN RAISE EXCEPTION 'Projection result variant incomplete' USING ERRCODE='23514'; END IF;
  IF (SELECT count(*) FROM projection_paths WHERE run_id=run.id AND projection_paths.variant=variant_json->>'variant')<>run.path_count THEN RAISE EXCEPTION 'Projection result requested paths incomplete' USING ERRCODE='23514'; END IF;
  FOR chunk IN SELECT * FROM projection_chunks WHERE run_id=run.id AND projection_chunks.variant=variant_json->>'variant' LOOP
   FOR i IN 0..chunk.path_count-1 LOOP
    IF variant_json->'paths'->(chunk.first_path+i) IS DISTINCT FROM convert_from(chunk.canonical_chunk,'UTF8')::jsonb->'paths'->i THEN RAISE EXCEPTION 'Projection result retained path differs' USING ERRCODE='23514'; END IF;
   END LOOP;
  END LOOP;
  FOR i IN 0..run.retained_point_count-1 LOOP
   body:=variant_json->'distributions'->i;
   SELECT d.* INTO summary FROM projection_distributions d JOIN projection_calendar_boundaries b ON b.run_id=run.id AND b.month=d.month WHERE d.result_id=p_result AND d.variant=variant_json->>'variant' AND b.point_index=i;
   IF summary.id IS NULL OR (body->>'month')::integer IS DISTINCT FROM summary.month OR (body->>'nominal_mean')::numeric IS DISTINCT FROM summary.nominal_mean OR (body->>'real_mean')::numeric IS DISTINCT FROM summary.real_mean OR (body->>'funding_failed_paths')::integer IS DISTINCT FROM summary.funding_failed_paths OR (SELECT count(*) FROM projection_distribution_quantiles WHERE distribution_id=summary.id)<>10 THEN RAISE EXCEPTION 'Projection distribution summary differs' USING ERRCODE='23514'; END IF;
   FOR quantile IN SELECT * FROM projection_distribution_quantiles WHERE distribution_id=summary.id LOOP
    IF body->quantile.basis->'probabilities' IS DISTINCT FROM '["0.05","0.25","0.5","0.75","0.95"]'::jsonb OR (body->quantile.basis->'values'->>(array_position(ARRAY[.05,.25,.50,.75,.95]::numeric[],quantile.probability)-1))::numeric IS DISTINCT FROM quantile.value THEN RAISE EXCEPTION 'Projection distribution quantile differs' USING ERRCODE='23514'; END IF;
   END LOOP;
  END LOOP;
  FOR histogram IN SELECT * FROM projection_histograms WHERE result_id=p_result AND projection_histograms.variant=variant_json->>'variant' LOOP
   body:=variant_json->(histogram.basis||'_histogram');
   IF (body->>'observed_minimum')::numeric IS DISTINCT FROM histogram.observed_minimum OR (body->>'observed_maximum')::numeric IS DISTINCT FROM histogram.observed_maximum OR body->>'boundary_rule' IS DISTINCT FROM histogram.boundary_rule OR jsonb_array_length(body->'bins') IS DISTINCT FROM histogram.bin_count OR (SELECT count(*) FROM projection_histogram_bins WHERE histogram_id=histogram.id)<>histogram.bin_count OR (SELECT sum(count) FROM projection_histogram_bins WHERE histogram_id=histogram.id)<>run.path_count THEN RAISE EXCEPTION 'Projection histogram summary differs' USING ERRCODE='23514'; END IF;
   FOR bin IN SELECT * FROM projection_histogram_bins WHERE histogram_id=histogram.id LOOP
    point_json:=body->'bins'->bin.bin_index;
    IF (point_json->>'lower')::numeric IS DISTINCT FROM bin.lower OR (point_json->>'upper')::numeric IS DISTINCT FROM bin.upper OR (point_json->>'upper_inclusive')::boolean IS DISTINCT FROM bin.upper_inclusive OR (point_json->>'count')::integer IS DISTINCT FROM bin.count OR bin.bin_index>=histogram.bin_count THEN RAISE EXCEPTION 'Projection histogram bin differs' USING ERRCODE='23514'; END IF;
   END LOOP;
  END LOOP;
  IF run.goal_version_id IS NULL THEN
   IF variant_json->'goal' IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'Projection unrequested goal result' USING ERRCODE='23514'; END IF;
  ELSE
   body:=variant_json->'goal';
   SELECT * INTO goal FROM projection_goal_analyses WHERE result_id=p_result AND projection_goal_analyses.variant=variant_json->>'variant';
   IF goal.id IS NULL OR body->>'goal_version_id' IS DISTINCT FROM goal.goal_version_id::text OR body->>'basis' IS DISTINCT FROM goal.basis OR body->>'method' IS DISTINCT FROM goal.method OR body->>'interval_method' IS DISTINCT FROM goal.interval_method OR (body->>'objective_met')::boolean IS DISTINCT FROM goal.objective_met OR (SELECT count(*) FROM projection_goal_shortfall_quantiles WHERE analysis_id=goal.id)<>5 THEN RAISE EXCEPTION 'Projection goal analysis differs' USING ERRCODE='23514'; END IF;
   FOREACH field_name IN ARRAY ARRAY['target','paths','successes','probability','interval_low','interval_high','probability_objective','mean_shortfall','funding_failed_paths'] LOOP
    IF (body->>field_name)::numeric IS DISTINCT FROM (to_jsonb(goal)->>field_name)::numeric THEN RAISE EXCEPTION 'Projection goal money or probability differs' USING ERRCODE='23514'; END IF;
   END LOOP;
   FOR quantile IN SELECT * FROM projection_goal_shortfall_quantiles WHERE analysis_id=goal.id LOOP
    IF body->'shortfalls'->'probabilities' IS DISTINCT FROM '["0.05","0.25","0.5","0.75","0.95"]'::jsonb OR (body->'shortfalls'->'values'->>(array_position(ARRAY[.05,.25,.50,.75,.95]::numeric[],quantile.probability)-1))::numeric IS DISTINCT FROM quantile.value THEN RAISE EXCEPTION 'Projection goal shortfall differs' USING ERRCODE='23514'; END IF;
   END LOOP;
  END IF;
 END LOOP;
END $$;

CREATE FUNCTION projection_result_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM premium_retention_events WHERE run_id=NEW.run_id) THEN PERFORM projection_result_complete_check(NEW.id); END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION projection_run_has_payload(p_run uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM projection_runs WHERE id=p_run AND (payload_rows>0 OR retained_source_rows>0))
$$;

CREATE FUNCTION projection_retention_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE root premium_runs; selected_run uuid;
BEGIN
 IF TG_TABLE_NAME='premium_retention_events' THEN
  IF TG_OP='DELETE' THEN selected_run:=OLD.run_id; ELSE selected_run:=NEW.run_id; END IF;
  SELECT * INTO root FROM premium_runs WHERE premium_runs.id=selected_run FOR UPDATE;
  IF root.kind IS DISTINCT FROM 'projection' THEN RETURN coalesce(NEW,OLD); END IF;
  IF TG_OP='DELETE' OR (NEW.completed_at IS NOT NULL AND projection_run_has_payload(root.id)) THEN RAISE EXCEPTION 'Projection retention copies remain' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='premium_runs' THEN
  IF OLD.kind='projection' AND projection_run_has_payload(OLD.id) AND (TG_OP='DELETE' OR NEW.reserved_bytes+NEW.retained_bytes=0) THEN RAISE EXCEPTION 'Projection retained bytes remain' USING ERRCODE='23514'; END IF;
  RETURN coalesce(NEW,OLD);
 END IF;
 RETURN coalesce(NEW,OLD);
END $$;

CREATE FUNCTION projection_financial_payload_present(p_run uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM projection_inputs WHERE run_id=p_run)
 OR EXISTS(SELECT 1 FROM projection_run_allocations WHERE run_id=p_run)
 OR EXISTS(SELECT 1 FROM projection_calendar_boundaries WHERE run_id=p_run)
 OR EXISTS(SELECT 1 FROM projection_run_pauses WHERE run_id=p_run)
 OR EXISTS(SELECT 1 FROM projection_run_schedule_entries WHERE run_id=p_run)
 OR EXISTS(SELECT 1 FROM projection_source_proofs WHERE run_id=p_run)
 OR EXISTS(SELECT 1 FROM projection_chunks WHERE run_id=p_run)
 OR EXISTS(SELECT 1 FROM projection_paths WHERE run_id=p_run)
 OR EXISTS(SELECT 1 FROM projection_points WHERE run_id=p_run)
 OR EXISTS(SELECT 1 FROM projection_point_assets WHERE run_id=p_run)
 OR EXISTS(SELECT 1 FROM projection_results WHERE run_id=p_run AND octet_length(canonical_result)>0)
 OR EXISTS(SELECT 1 FROM projection_distributions d JOIN projection_results r ON r.id=d.result_id WHERE r.run_id=p_run)
 OR EXISTS(SELECT 1 FROM projection_histograms h JOIN projection_results r ON r.id=h.result_id WHERE r.run_id=p_run)
 OR EXISTS(SELECT 1 FROM projection_goal_analyses a JOIN projection_results r ON r.id=a.result_id WHERE r.run_id=p_run)
 OR EXISTS(SELECT 1 FROM projection_zero_pivots z JOIN projection_results r ON r.id=z.result_id WHERE r.run_id=p_run)
$$;

CREATE FUNCTION projection_storage_bytes(p_run uuid) RETURNS bigint LANGUAGE sql STABLE AS $$
 SELECT CASE WHEN projection_financial_payload_present(p_run) OR EXISTS(SELECT 1 FROM projection_retained_source_memberships WHERE run_id=p_run) THEN coalesce(sum(bytes),0)::bigint ELSE 0::bigint END FROM (
 SELECT (pg_column_size(ROW(t."run_id",t."initial_value",t."base_monthly",t."annual_growth",t."contribution_delta",t."annual_mean_log_delta",t."pause_count",t."entry_count",t."capture_bytes",t."input_bytes",t."id",t."owner_id",t."account_id",t."created_at"))+octet_length(t.canonical_capture)+octet_length(t.canonical_input))::bigint bytes FROM projection_inputs t WHERE t.run_id=p_run
 UNION ALL SELECT (pg_column_size(t))::bigint bytes FROM projection_run_allocations t WHERE t.run_id=p_run
 UNION ALL SELECT (pg_column_size(t))::bigint bytes FROM projection_calendar_boundaries t WHERE t.run_id=p_run
 UNION ALL SELECT (pg_column_size(t))::bigint bytes FROM projection_run_pauses t WHERE t.run_id=p_run
 UNION ALL SELECT (pg_column_size(t))::bigint bytes FROM projection_run_schedule_entries t WHERE t.run_id=p_run
 UNION ALL SELECT (pg_column_size(ROW(t."run_id",t."source_id",t."id",t."owner_id",t."account_id",t."created_at"))+octet_length(t.canonical_proof))::bigint bytes FROM projection_source_proofs t WHERE t.run_id=p_run
 UNION ALL SELECT (pg_column_size(ROW(t."run_id",t."job_id",t."lease_token",t."consumer_attempt",t."variant",t."first_path",t."path_count",t."input_digest",t."content_digest",t."byte_length",t."sealed",t."id",t."owner_id",t."account_id",t."created_at"))+octet_length(t.canonical_chunk))::bigint bytes FROM projection_chunks t WHERE t.run_id=p_run
 UNION ALL SELECT (pg_column_size(t))::bigint bytes FROM projection_paths t WHERE t.run_id=p_run
 UNION ALL SELECT (pg_column_size(t))::bigint bytes FROM projection_points t WHERE t.run_id=p_run
 UNION ALL SELECT (pg_column_size(t))::bigint bytes FROM projection_point_assets t WHERE t.run_id=p_run
 UNION ALL SELECT (pg_column_size(ROW(t."run_id",t."job_id",t."lease_token",t."consumer_attempt",t."input_digest",t."content_digest",t."byte_length",t."quality",t."sampler",t."sealed",t."id",t."owner_id",t."account_id",t."created_at"))+octet_length(t.canonical_result))::bigint bytes FROM projection_results t WHERE t.run_id=p_run AND projection_financial_payload_present(p_run)
 UNION ALL SELECT (pg_column_size(t))::bigint bytes FROM projection_zero_pivots t JOIN projection_results r ON r.id=t.result_id WHERE r.run_id=p_run
 UNION ALL SELECT (pg_column_size(t))::bigint bytes FROM projection_distributions t JOIN projection_results r ON r.id=t.result_id WHERE r.run_id=p_run
 UNION ALL SELECT (pg_column_size(t))::bigint bytes FROM projection_distribution_quantiles t JOIN projection_distributions d ON d.id=t.distribution_id JOIN projection_results r ON r.id=d.result_id WHERE r.run_id=p_run
 UNION ALL SELECT (pg_column_size(t))::bigint bytes FROM projection_histograms t JOIN projection_results r ON r.id=t.result_id WHERE r.run_id=p_run
 UNION ALL SELECT (pg_column_size(t))::bigint bytes FROM projection_histogram_bins t JOIN projection_histograms h ON h.id=t.histogram_id JOIN projection_results r ON r.id=h.result_id WHERE r.run_id=p_run
 UNION ALL SELECT (pg_column_size(t))::bigint bytes FROM projection_goal_analyses t JOIN projection_results r ON r.id=t.result_id WHERE r.run_id=p_run
 UNION ALL SELECT (pg_column_size(t))::bigint bytes FROM projection_goal_shortfall_quantiles t JOIN projection_goal_analyses a ON a.id=t.analysis_id JOIN projection_results r ON r.id=a.result_id WHERE r.run_id=p_run
 UNION ALL SELECT pg_column_size(t)::bigint bytes FROM projection_retained_source_memberships t WHERE t.run_id=p_run
 ) stored
$$;
CREATE FUNCTION projection_capacity_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE root premium_runs; run uuid; bytes bigint;
BEGIN
 IF TG_TABLE_NAME='premium_runs' THEN run:=NEW.id; ELSE run:=NEW.run_id; END IF;
 SELECT * INTO root FROM premium_runs WHERE id=run;
 IF root.kind IS DISTINCT FROM 'projection' THEN RETURN NEW; END IF;
 -- Publication retains independent aggregate parity. Purge/root accounting only
 -- reads the trigger-owned exact counter: no financial scan is hidden at COMMIT.
 SELECT stored_bytes INTO bytes FROM projection_runs WHERE id=run;
 IF bytes IS NULL THEN RAISE EXCEPTION 'Projection byte counter absent' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME<>'premium_runs' AND TG_OP='INSERT' THEN
  IF bytes IS DISTINCT FROM projection_storage_bytes(run) THEN
   RAISE EXCEPTION 'Projection publication byte counter differs' USING ERRCODE='23514'; END IF;
 END IF;
 IF bytes>33554432 OR root.reserved_bytes+root.retained_bytes>33554432 OR bytes>root.reserved_bytes+root.retained_bytes THEN RAISE EXCEPTION 'Projection retained byte capacity exceeded' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""

_TRIGGERS = (
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON assumption_sets FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON assumption_sets FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON goals FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON goals FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON assumption_versions FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON assumption_versions FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_assumption_assets FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_assumption_assets FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_correlation_cells FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_correlation_cells FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_calibration_pins FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_calibration_pins FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON goal_versions FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON goal_versions FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_goal_pauses FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_goal_pauses FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_goal_schedule_entries FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_goal_schedule_entries FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_runs FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_runs FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_inputs FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_inputs FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_run_allocations FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_run_allocations FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_calendar_boundaries FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_calendar_boundaries FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_run_pauses FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_run_pauses FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_run_schedule_entries FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_run_schedule_entries FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_run_sources FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_run_sources FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_source_proofs FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_source_proofs FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_source_licenses FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_source_licenses FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_chunks FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_chunks FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_paths FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_paths FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_points FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_points FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_point_assets FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_point_assets FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_results FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_results FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_zero_pivots FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_zero_pivots FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_distributions FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_distributions FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_distribution_quantiles FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_distribution_quantiles FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_histograms FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_histograms FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_histogram_bins FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_histogram_bins FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_goal_analyses FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_goal_analyses FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE TRIGGER projection_scope_guard BEFORE INSERT ON projection_goal_shortfall_quantiles FOR EACH ROW EXECUTE FUNCTION projection_scope_guard()",
    "CREATE TRIGGER projection_immutable_guard BEFORE UPDATE OR DELETE ON projection_goal_shortfall_quantiles FOR EACH ROW EXECUTE FUNCTION projection_immutable_guard()",
    "CREATE CONSTRAINT TRIGGER projection_definition_complete AFTER INSERT OR UPDATE ON assumption_sets DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION projection_definition_complete()",
    "CREATE CONSTRAINT TRIGGER projection_definition_complete AFTER INSERT OR UPDATE ON assumption_versions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION projection_definition_complete()",
    "CREATE CONSTRAINT TRIGGER projection_definition_complete AFTER INSERT OR UPDATE ON goals DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION projection_definition_complete()",
    "CREATE CONSTRAINT TRIGGER projection_definition_complete AFTER INSERT OR UPDATE ON goal_versions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION projection_definition_complete()",
    "CREATE TRIGGER projection_version_capacity_guard BEFORE INSERT ON risk_definition_versions FOR EACH ROW EXECUTE FUNCTION projection_version_capacity_guard()",
    "CREATE TRIGGER projection_version_capacity_guard BEFORE INSERT ON scenario_definition_versions FOR EACH ROW EXECUTE FUNCTION projection_version_capacity_guard()",
    "CREATE TRIGGER projection_version_capacity_guard BEFORE INSERT ON assumption_versions FOR EACH ROW EXECUTE FUNCTION projection_version_capacity_guard()",
    "CREATE TRIGGER projection_version_capacity_guard BEFORE INSERT ON goal_versions FOR EACH ROW EXECUTE FUNCTION projection_version_capacity_guard()",
    "CREATE CONSTRAINT TRIGGER projection_chunk_complete AFTER INSERT ON projection_chunks DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION projection_chunk_complete()",
    "CREATE CONSTRAINT TRIGGER projection_result_complete AFTER INSERT ON projection_results DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION projection_result_complete()",
    "CREATE CONSTRAINT TRIGGER projection_capacity_complete AFTER INSERT OR UPDATE ON premium_runs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION projection_capacity_complete()",
    "CREATE CONSTRAINT TRIGGER projection_capacity_complete AFTER INSERT OR UPDATE ON projection_inputs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION projection_capacity_complete()",
    "CREATE CONSTRAINT TRIGGER projection_capacity_complete AFTER INSERT OR UPDATE ON projection_chunks DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION projection_capacity_complete()",
    "CREATE CONSTRAINT TRIGGER projection_capacity_complete AFTER INSERT OR UPDATE ON projection_results DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION projection_capacity_complete()",
    "CREATE TRIGGER projection_retention_guard BEFORE UPDATE OR DELETE ON premium_runs FOR EACH ROW EXECUTE FUNCTION projection_retention_guard()",
    "CREATE TRIGGER projection_retention_guard BEFORE INSERT OR UPDATE OR DELETE ON premium_retention_events FOR EACH ROW EXECUTE FUNCTION projection_retention_guard()",
)

_EXTERNAL_TRIGGERS = (
    ("risk_definition_versions", "projection_version_capacity_guard"),
    ("scenario_definition_versions", "projection_version_capacity_guard"),
    ("premium_runs", "projection_capacity_complete"),
    ("premium_runs", "projection_retention_guard"),
    ("premium_retention_events", "projection_retention_guard"),
)

_FUNCTIONS = (
    "projection_capacity_complete()",
    "projection_storage_bytes(uuid)",
    "projection_financial_payload_present(uuid)",
    "projection_retention_guard()",
    "projection_run_has_payload(uuid)",
    "projection_result_complete()",
    "projection_result_complete_check(uuid)",
    "projection_chunk_complete()",
    "projection_chunk_complete_check(uuid)",
    "projection_capture_complete(uuid)",
    "projection_definition_complete()",
    "projection_immutable_guard()",
    "projection_scope_guard()",
    "projection_version_capacity_guard()",
)


_RETENTION_GUARDS = r"""-- Fixed original source lineage, bounded at the existing 100,000 admitted rows.
-- UNION eliminates repeated evidence edges and terminates cycles. The sentinel
-- 100,001st row rejects overlarge graphs; it is never silently treated as complete.
-- Return the recursive stream directly: no outer join/sort consumes the full graph.
CREATE FUNCTION projection_history_links(p_owner uuid,p_input uuid)
RETURNS SETOF historical_dependencies LANGUAGE sql STABLE AS $$
 WITH RECURSIVE walk AS (
  SELECT d.* FROM historical_dependencies d
  WHERE d.owner_id=p_owner AND d.input_id=p_input
  UNION
  SELECT d.* FROM historical_dependencies d
  JOIN walk w ON d.evidence_id=w.registered_evidence_id WHERE d.owner_id=p_owner
 )
 SELECT * FROM walk LIMIT 100001
$$;

CREATE FUNCTION projection_license_until(p_owner uuid,p_license uuid,p_original timestamptz,p_at timestamptz)
RETURNS timestamptz LANGUAGE plpgsql STABLE AS $$
DECLARE pinned provider_license_versions; current_license provider_license_versions;
BEGIN
 SELECT * INTO pinned FROM provider_license_versions WHERE id=p_license AND owner_id=p_owner;
 IF pinned.id IS NULL OR pinned.effective_at>p_at OR pinned.store_permission<>'allowed'
  OR pinned.display_permission<>'allowed' OR pinned.retention_days IS NULL THEN RETURN NULL; END IF;
 SELECT * INTO current_license FROM provider_license_versions
 WHERE owner_id=p_owner AND provider_id=pinned.provider_id AND effective_at<=p_at
 ORDER BY effective_at DESC,version_number DESC,id DESC LIMIT 1;
 IF current_license.id IS NULL OR current_license.store_permission<>'allowed'
  OR current_license.display_permission<>'allowed' OR current_license.retention_days IS NULL
  OR p_original>p_at THEN RETURN NULL; END IF;
 RETURN p_original+least(30,pinned.retention_days,current_license.retention_days)*interval '1 day';
END $$;

CREATE FUNCTION projection_physical_until(p_owner uuid,p_kind text,p_id uuid,p_at timestamptz)
RETURNS timestamptz LANGUAGE plpgsql STABLE AS $$
DECLARE original timestamptz; expiry timestamptz; pinned uuid; until_at timestamptz;
BEGIN
 IF p_kind NOT IN ('price','fx','corporate_action','benchmark') THEN RETURN NULL; END IF;
 SELECT h.created_at,h.expires_at,h.license_version_id INTO original,expiry,pinned FROM (
  SELECT created_at,expires_at,license_version_id FROM price_snapshots WHERE p_kind='price' AND owner_id=p_owner AND id=p_id
  UNION ALL SELECT created_at,expires_at,license_version_id FROM fx_snapshots WHERE p_kind='fx' AND owner_id=p_owner AND id=p_id
  UNION ALL SELECT created_at,expires_at,license_version_id FROM corporate_action_snapshots WHERE p_kind='corporate_action' AND owner_id=p_owner AND id=p_id
  UNION ALL SELECT created_at,expires_at,license_version_id FROM benchmark_snapshots WHERE p_kind='benchmark' AND owner_id=p_owner AND id=p_id
 ) h;
 IF original IS NULL OR EXISTS(SELECT 1 FROM source_retention_work m WHERE m.owner_id=p_owner AND
   (CASE p_kind WHEN 'price' THEN m.price_snapshot_id WHEN 'fx' THEN m.fx_snapshot_id WHEN 'corporate_action' THEN m.corporate_action_snapshot_id ELSE m.benchmark_snapshot_id END)=p_id)
 OR EXISTS(SELECT 1 FROM source_expiry_events m WHERE m.owner_id=p_owner AND
   (CASE p_kind WHEN 'price' THEN m.price_snapshot_id WHEN 'fx' THEN m.fx_snapshot_id WHEN 'corporate_action' THEN m.corporate_action_snapshot_id ELSE m.benchmark_snapshot_id END)=p_id)
 THEN RETURN NULL; END IF;
 until_at:=projection_license_until(p_owner,pinned,original,p_at);
 IF until_at IS NULL THEN RETURN NULL; END IF;
 RETURN least(expiry,until_at);
END $$;

CREATE FUNCTION projection_history_until(p_owner uuid,p_input uuid,p_copy_at timestamptz,p_at timestamptz)
RETURNS timestamptz LANGUAGE plpgsql STABLE AS $$
DECLARE original timestamptz; item historical_dependencies; seen integer:=0;
 expiry timestamptz:=p_copy_at+interval '30 days'; until_at timestamptz;
 pinned uuid; stamp timestamptz; physical_kind text; physical_id uuid;
BEGIN
 SELECT created_at INTO original FROM historical_input_snapshots
 WHERE owner_id=p_owner AND id=p_input AND sealed AND octet_length(canonical_input)>0;
 IF original IS NULL OR original>p_at OR EXISTS(SELECT 1 FROM historical_retention_events
  WHERE owner_id=p_owner AND input_id=p_input) THEN RETURN NULL; END IF;
 FOR item IN SELECT * FROM projection_history_links(p_owner,p_input) LOOP
  seen:=seen+1; IF seen>100000 THEN RETURN NULL; END IF;
  physical_kind:=NULL; physical_id:=NULL; pinned:=NULL; stamp:=NULL;
  IF item.price_snapshot_id IS NOT NULL THEN physical_kind:='price'; physical_id:=item.price_snapshot_id;
  ELSIF item.fx_snapshot_id IS NOT NULL THEN physical_kind:='fx'; physical_id:=item.fx_snapshot_id;
  ELSIF item.action_snapshot_id IS NOT NULL THEN physical_kind:='corporate_action'; physical_id:=item.action_snapshot_id;
  ELSIF item.benchmark_snapshot_id IS NOT NULL THEN physical_kind:='benchmark'; physical_id:=item.benchmark_snapshot_id;
  ELSIF item.license_version_id IS NOT NULL THEN pinned:=item.license_version_id; stamp:=original;
  ELSIF item.classification_id IS NOT NULL THEN
   SELECT license_version_id,created_at INTO pinned,stamp FROM historical_classification_evidence
   WHERE id=item.classification_id AND owner_id=p_owner;
   IF pinned IS NULL THEN RETURN NULL; END IF;
  ELSIF item.registered_evidence_id IS NOT NULL THEN
   IF NOT EXISTS(SELECT 1 FROM historical_evidence_sets WHERE id=item.registered_evidence_id
    AND owner_id=p_owner AND sealed) THEN RETURN NULL; END IF;
  END IF;
  IF physical_id IS NOT NULL THEN
   until_at:=projection_physical_until(p_owner,physical_kind,physical_id,p_at);
   IF until_at IS NULL OR until_at<=p_at THEN RETURN NULL; END IF;
   expiry:=least(expiry,until_at);
  END IF;
  IF pinned IS NOT NULL THEN
   until_at:=projection_license_until(p_owner,pinned,stamp,p_at);
   IF until_at IS NULL OR until_at<=p_at THEN RETURN NULL; END IF;
   expiry:=least(expiry,until_at);
   until_at:=projection_license_until(p_owner,pinned,original,p_at);
   IF until_at IS NULL OR until_at<=p_at THEN RETURN NULL; END IF;
   expiry:=least(expiry,until_at);
  END IF;
 END LOOP;
 RETURN expiry;
END $$;

CREATE FUNCTION projection_original_sources_restricted(p_run uuid,p_at timestamptz)
RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE root premium_runs; capture projection_runs; item projection_run_sources;
 seen integer:=0; matches integer; stamp timestamptz; digest text; until_at timestamptz;
BEGIN
 SELECT * INTO root FROM premium_runs WHERE id=p_run AND kind='projection';
 SELECT * INTO capture FROM projection_runs WHERE id=p_run;
 IF root.id IS NULL OR capture.id IS NULL OR NOT capture.sealed OR root.expires_at<=p_at
  OR root.created_at>p_at OR root.owner_id IS DISTINCT FROM capture.owner_id
  OR root.account_id IS DISTINCT FROM capture.account_id THEN RETURN true; END IF;
 FOR item IN SELECT * FROM projection_run_sources WHERE run_id=p_run AND owner_id=root.owner_id
  AND account_id=root.account_id ORDER BY id LIMIT 258 LOOP
  seen:=seen+1; IF seen>257 OR item.source_expires_at<=p_at THEN RETURN true; END IF;
  IF item.kind='initial_snapshot' THEN CONTINUE; END IF;
  IF item.kind<>'calibration' THEN RETURN true; END IF;
  SELECT count(*) INTO matches FROM (
   SELECT id FROM historical_input_snapshots WHERE owner_id=root.owner_id AND broker_account_id=root.account_id AND id=item.subject_id
   UNION ALL SELECT id FROM price_snapshots WHERE owner_id=root.owner_id AND id=item.subject_id
   UNION ALL SELECT id FROM benchmark_snapshots WHERE owner_id=root.owner_id AND id=item.subject_id
  ) choices;
  IF matches<>1 THEN RETURN true; END IF;
  SELECT created_at,input_digest INTO stamp,digest FROM historical_input_snapshots
   WHERE owner_id=root.owner_id AND broker_account_id=root.account_id AND id=item.subject_id;
  IF FOUND THEN until_at:=projection_history_until(root.owner_id,item.subject_id,root.created_at,p_at);
  ELSE
   SELECT created_at,content_digest INTO stamp,digest FROM price_snapshots
    WHERE owner_id=root.owner_id AND id=item.subject_id;
   IF FOUND THEN until_at:=projection_physical_until(root.owner_id,'price',item.subject_id,p_at);
   ELSE
    SELECT created_at,content_digest INTO stamp,digest FROM benchmark_snapshots WHERE owner_id=root.owner_id AND id=item.subject_id;
    until_at:=projection_physical_until(root.owner_id,'benchmark',item.subject_id,p_at);
   END IF;
  END IF;
  IF stamp IS DISTINCT FROM item.original_created_at OR digest IS DISTINCT FROM item.content_digest
   OR until_at IS NULL OR until_at<=p_at OR root.expires_at>until_at THEN RETURN true; END IF;
 END LOOP;
 RETURN seen IS DISTINCT FROM capture.source_count;
END $$;

CREATE FUNCTION projection_references_source(p_owner uuid,p_run uuid,p_kind text,p_source uuid)
RETURNS boolean LANGUAGE plpgsql STABLE AS $$
BEGIN
 IF p_kind NOT IN ('price','fx','corporate_action','benchmark','historical') OR p_kind IS NULL THEN
  RAISE EXCEPTION 'Unknown projection source parent' USING ERRCODE='23514'; END IF;
 RETURN EXISTS(SELECT 1 FROM projection_retained_source_memberships
 WHERE owner_id=p_owner AND run_id=p_run AND source_kind=p_kind AND source_id=p_source);
END $$;

CREATE FUNCTION projection_parent_has_copies(p_owner uuid,p_kind text,p_id uuid)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM projection_retained_source_memberships
 WHERE owner_id=p_owner AND source_kind=p_kind AND source_id=p_id)
$$;

CREATE FUNCTION projection_source_parent_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE selected_owner uuid; selected_id uuid; kind text; stamp timestamptz; value_digest text;
 until_at timestamptz; source_count integer; account uuid; root premium_runs;
BEGIN
 IF TG_TABLE_NAME='projection_run_sources' THEN
  selected_owner:=NEW.owner_id;
  IF NOT pg_try_advisory_xact_lock(hashtextextended('sources:'||selected_owner::text,0)) THEN
   RAISE EXCEPTION 'Projection source owner is busy' USING ERRCODE='55P03'; END IF;
  IF NEW.kind<>'calibration' THEN RETURN NEW; END IF;
  SELECT * INTO root FROM premium_runs WHERE id=NEW.run_id AND owner_id=selected_owner AND account_id=NEW.account_id;
  IF root.id IS NULL THEN RAISE EXCEPTION 'Projection source root missing' USING ERRCODE='23514'; END IF;
  SELECT count(*) INTO source_count FROM (
   SELECT id FROM historical_input_snapshots WHERE owner_id=selected_owner AND id=NEW.subject_id
   UNION ALL SELECT id FROM price_snapshots WHERE owner_id=selected_owner AND id=NEW.subject_id
   UNION ALL SELECT id FROM benchmark_snapshots WHERE owner_id=selected_owner AND id=NEW.subject_id
  ) choices;
  IF source_count<>1 THEN RAISE EXCEPTION 'Projection source parent ambiguous or absent' USING ERRCODE='23514'; END IF;
  SELECT created_at,input_digest,broker_account_id INTO stamp,value_digest,account
   FROM historical_input_snapshots WHERE owner_id=selected_owner AND id=NEW.subject_id FOR SHARE;
  IF FOUND THEN
   IF account IS DISTINCT FROM NEW.account_id THEN RAISE EXCEPTION 'Projection history account differs' USING ERRCODE='23514'; END IF;
   until_at:=projection_history_until(selected_owner,NEW.subject_id,root.created_at,clock_timestamp());
  ELSE
   SELECT created_at,content_digest INTO stamp,value_digest FROM price_snapshots
    WHERE owner_id=selected_owner AND id=NEW.subject_id FOR SHARE;
   IF FOUND THEN until_at:=projection_physical_until(selected_owner,'price',NEW.subject_id,clock_timestamp());
   ELSE
    SELECT created_at,content_digest INTO stamp,value_digest FROM benchmark_snapshots
     WHERE owner_id=selected_owner AND id=NEW.subject_id FOR SHARE;
    until_at:=projection_physical_until(selected_owner,'benchmark',NEW.subject_id,clock_timestamp());
   END IF;
  END IF;
  IF stamp IS DISTINCT FROM NEW.original_created_at OR value_digest IS DISTINCT FROM NEW.content_digest
   OR until_at IS NULL OR until_at<=clock_timestamp() OR root.expires_at>until_at THEN
   RAISE EXCEPTION 'Projection original source unavailable' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='historical_input_snapshots' THEN
  IF TG_OP='UPDATE' THEN IF NEW.canonical_input IS NOT DISTINCT FROM OLD.canonical_input THEN RETURN NEW; END IF; END IF;
  selected_owner:=OLD.owner_id; selected_id:=OLD.id; kind:='historical';
 ELSIF TG_TABLE_NAME='historical_retention_events' THEN
  selected_owner:=NEW.owner_id; selected_id:=NEW.input_id; kind:='historical';
 ELSIF TG_TABLE_NAME IN ('price_observations','fx_observations','corporate_action_observations','benchmark_observations') THEN
  selected_owner:=OLD.owner_id; selected_id:=OLD.snapshot_id;
  kind:=CASE TG_TABLE_NAME WHEN 'price_observations' THEN 'price' WHEN 'fx_observations' THEN 'fx'
   WHEN 'corporate_action_observations' THEN 'corporate_action' ELSE 'benchmark' END;
 ELSIF TG_TABLE_NAME IN ('price_snapshots','fx_snapshots','corporate_action_snapshots','benchmark_snapshots') THEN
  selected_owner:=OLD.owner_id; selected_id:=OLD.id;
  kind:=CASE TG_TABLE_NAME WHEN 'price_snapshots' THEN 'price' WHEN 'fx_snapshots' THEN 'fx'
   WHEN 'corporate_action_snapshots' THEN 'corporate_action' ELSE 'benchmark' END;
 ELSIF TG_TABLE_NAME IN ('source_retention_work','source_expiry_events') THEN
  IF NEW.constituent_snapshot_id IS NOT NULL THEN RETURN NEW; END IF;
  selected_owner:=NEW.owner_id;
  selected_id:=coalesce(NEW.price_snapshot_id,NEW.fx_snapshot_id,NEW.corporate_action_snapshot_id,NEW.benchmark_snapshot_id);
  kind:=CASE WHEN NEW.price_snapshot_id IS NOT NULL THEN 'price' WHEN NEW.fx_snapshot_id IS NOT NULL THEN 'fx'
   WHEN NEW.corporate_action_snapshot_id IS NOT NULL THEN 'corporate_action' ELSE 'benchmark' END;
  IF NOT pg_try_advisory_xact_lock(hashtextextended('sources:'||selected_owner::text,0)) THEN
   RAISE EXCEPTION 'Projection source owner is busy' USING ERRCODE='55P03'; END IF;
  IF TG_TABLE_NAME='source_retention_work' THEN
   IF NEW.phase='copies' AND NEW.completed_at IS NULL THEN RETURN NEW; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='source_coverage_gaps' THEN
  selected_owner:=OLD.owner_id;
  IF OLD.constituent_snapshot_id IS NOT NULL THEN RETURN OLD; END IF;
  selected_id:=coalesce(OLD.price_snapshot_id,OLD.fx_snapshot_id,OLD.corporate_action_snapshot_id,OLD.benchmark_snapshot_id);
  kind:=CASE WHEN OLD.price_snapshot_id IS NOT NULL THEN 'price' WHEN OLD.fx_snapshot_id IS NOT NULL THEN 'fx'
   WHEN OLD.corporate_action_snapshot_id IS NOT NULL THEN 'corporate_action' ELSE 'benchmark' END;
 ELSE RAISE EXCEPTION 'Unknown projection retention participant' USING ERRCODE='23514'; END IF;
 -- A DELETE trigger may already hold the physical tuple. Never wait for the
 -- owner lock at that point: normal cleanup prelocks it; other callers retry.
 IF NOT pg_try_advisory_xact_lock(hashtextextended('sources:'||selected_owner::text,0)) THEN
  RAISE EXCEPTION 'Projection source owner is busy' USING ERRCODE='55P03'; END IF;
 IF projection_parent_has_copies(selected_owner,kind,selected_id) THEN
  RAISE EXCEPTION 'Projection source copies remain' USING ERRCODE='23514'; END IF;
 RETURN coalesce(NEW,OLD);
END $$;
"""

_RETENTION_TRIGGERS = (
    ("projection_run_sources", "BEFORE INSERT"),
    ("source_retention_work", "BEFORE INSERT OR UPDATE"),
    ("source_expiry_events", "BEFORE INSERT OR UPDATE"),
    ("historical_input_snapshots", "BEFORE UPDATE OR DELETE"),
    ("historical_retention_events", "BEFORE INSERT OR UPDATE"),
    ("price_observations", "BEFORE DELETE"),
    ("fx_observations", "BEFORE DELETE"),
    ("corporate_action_observations", "BEFORE DELETE"),
    ("benchmark_observations", "BEFORE DELETE"),
    ("price_snapshots", "BEFORE DELETE"),
    ("fx_snapshots", "BEFORE DELETE"),
    ("corporate_action_snapshots", "BEFORE DELETE"),
    ("benchmark_snapshots", "BEFORE DELETE"),
    ("source_coverage_gaps", "BEFORE DELETE"),
)
_RETENTION_FUNCTIONS = (
    "projection_source_parent_guard()",
    "projection_parent_has_copies(uuid,text,uuid)",
    "projection_references_source(uuid,uuid,text,uuid)",
    "projection_original_sources_restricted(uuid,timestamptz)",
    "projection_history_until(uuid,uuid,timestamptz,timestamptz)",
    "projection_physical_until(uuid,text,uuid,timestamptz)",
    "projection_license_until(uuid,uuid,timestamptz,timestamptz)",
    "projection_history_links(uuid,uuid)",
)
_RETENTION_INDICES = (
    (
        "ix_projection_points_retention",
        "projection_points",
        ("owner_id", "account_id", "run_id", "id"),
    ),
    (
        "ix_projection_point_assets_retention",
        "projection_point_assets",
        ("owner_id", "account_id", "run_id", "id"),
    ),
    (
        "ix_projection_source_proofs_retention",
        "projection_source_proofs",
        ("owner_id", "account_id", "run_id", "id"),
    ),
    ("ix_projection_history_input", "historical_dependencies", ("owner_id", "input_id", "id")),
    (
        "ix_projection_history_evidence",
        "historical_dependencies",
        ("owner_id", "evidence_id", "id"),
    ),
)


_MAINTENANCE_DDL = (
    r"""CREATE TABLE projection_retention_epochs (
 owner_id UUID NOT NULL,
 epoch BIGINT NOT NULL DEFAULT 0,
 roots_epoch BIGINT NOT NULL DEFAULT 0,
 CONSTRAINT pk_projection_retention_epochs PRIMARY KEY(owner_id),
 CONSTRAINT fk_projection_retention_epochs_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners(id) ON DELETE RESTRICT,
 CONSTRAINT ck_projection_retention_epochs_epoch_bound CHECK(epoch>=0 AND roots_epoch>=0)
)""",
    r"""CREATE TABLE projection_retention_scans (
 run_id UUID NOT NULL,
 purpose VARCHAR(16) NOT NULL,
 target_kind VARCHAR(24), target_id UUID,
 phase VARCHAR(12) NOT NULL,
 policy_epoch BIGINT NOT NULL,
 evaluated_at TIMESTAMP WITH TIME ZONE NOT NULL,
 next_policy_at TIMESTAMP WITH TIME ZONE,
 earliest_deadline TIMESTAMP WITH TIME ZONE,
 source_cursor UUID, current_source_id UUID, history_input_id UUID,
 history_created_at TIMESTAMP WITH TIME ZONE,
 source_count INTEGER NOT NULL, dependencies_seen INTEGER NOT NULL, node_count INTEGER NOT NULL,
 id UUID NOT NULL,
 owner_id UUID NOT NULL,
 account_id UUID NOT NULL,
 created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT pk_projection_retention_scans PRIMARY KEY (id),
 CONSTRAINT fk_projection_retention_scans_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners(id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_retention_scans_account_id_broker_accounts FOREIGN KEY(account_id) REFERENCES broker_accounts(id) ON DELETE RESTRICT,
 CONSTRAINT uq_projection_retention_scans_scope UNIQUE(owner_id,account_id,id),
 CONSTRAINT uq_projection_retention_scans_run_purpose UNIQUE(run_id,purpose),
 CONSTRAINT fk_projection_retention_scans_run FOREIGN KEY(owner_id,account_id,run_id) REFERENCES projection_runs(owner_id,account_id,id) ON DELETE RESTRICT,
 CONSTRAINT ck_projection_retention_scans_phase_bound CHECK(purpose IN ('expiry','source_match') AND phase IN ('source','walk','clear','restart','clean','matched')),
 CONSTRAINT ck_projection_retention_scans_target_bound CHECK((purpose='expiry' AND target_kind IS NULL AND target_id IS NULL) OR (purpose='source_match' AND target_kind IN ('price','fx','corporate_action','benchmark','historical') AND target_id IS NOT NULL)),
 CONSTRAINT ck_projection_retention_scans_count_bound CHECK(policy_epoch>=0 AND source_count BETWEEN 0 AND 257 AND dependencies_seen BETWEEN 0 AND 100001 AND node_count BETWEEN 0 AND 100001)
)""",
    r"""CREATE TABLE projection_retention_frontier (
 scan_id UUID NOT NULL, subject_id UUID NOT NULL, is_evidence BOOLEAN NOT NULL,
 dependency_cursor UUID, complete BOOLEAN NOT NULL,
 id UUID NOT NULL,
 owner_id UUID NOT NULL,
 account_id UUID NOT NULL,
 created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT pk_projection_retention_frontier PRIMARY KEY (id),
 CONSTRAINT fk_projection_retention_frontier_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners(id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_retention_frontier_account_id_broker_accounts FOREIGN KEY(account_id) REFERENCES broker_accounts(id) ON DELETE RESTRICT,
 CONSTRAINT uq_projection_retention_frontier_visit UNIQUE(scan_id,subject_id,is_evidence),
 CONSTRAINT fk_projection_retention_frontier_scan FOREIGN KEY(owner_id,account_id,scan_id) REFERENCES projection_retention_scans(owner_id,account_id,id) ON DELETE RESTRICT
)""",
    r"""CREATE INDEX ix_projection_retention_scans_owner_run ON projection_retention_scans(owner_id,account_id,run_id,id)""",
    r"""CREATE INDEX ix_projection_retention_frontier_pending ON projection_retention_frontier(owner_id,account_id,scan_id,complete,id)""",
    r"""CREATE INDEX ix_projection_retention_frontier_cleanup ON projection_retention_frontier(owner_id,account_id,scan_id,id)""",
    r"""CREATE INDEX ix_projection_retention_source_keyset ON projection_run_sources(owner_id,account_id,run_id,id)""",
    r"""CREATE INDEX ix_projection_retention_policy_activation ON provider_license_versions(owner_id,effective_at)""",
    r"""CREATE INDEX ix_projection_retention_policy_selection ON provider_license_versions(owner_id,provider_id,effective_at,version_number,id)""",
    r"""CREATE TABLE projection_retention_targets (
 run_id UUID NOT NULL, target_kind VARCHAR(24) NOT NULL, target_id UUID NOT NULL, matched BOOLEAN NOT NULL,
 id UUID NOT NULL, owner_id UUID NOT NULL, account_id UUID NOT NULL,
 created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT pk_projection_retention_targets PRIMARY KEY(id),
 CONSTRAINT fk_projection_retention_targets_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners(id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_retention_targets_account_id_broker_accounts FOREIGN KEY(account_id) REFERENCES broker_accounts(id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_retention_targets_run FOREIGN KEY(owner_id,account_id,run_id) REFERENCES projection_runs(owner_id,account_id,id) ON DELETE RESTRICT,
 CONSTRAINT uq_projection_retention_targets_identity UNIQUE(run_id,target_kind,target_id),
 CONSTRAINT ck_projection_retention_targets_kind_bound CHECK(target_kind IN ('price','fx','corporate_action','benchmark','historical'))
)""",
    r"""CREATE TABLE projection_retention_sweeps (
 id UUID NOT NULL, key VARCHAR(160) NOT NULL, owner_id UUID, purpose VARCHAR(16) NOT NULL,
 target_kind VARCHAR(24), target_id UUID, after_id UUID, deferred BOOLEAN NOT NULL,
 policy_epoch BIGINT NOT NULL, evaluated_at TIMESTAMP WITH TIME ZONE NOT NULL,
 CONSTRAINT pk_projection_retention_sweeps PRIMARY KEY(id),
 CONSTRAINT uq_projection_retention_sweeps_key UNIQUE(key),
 CONSTRAINT fk_projection_retention_sweeps_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners(id) ON DELETE RESTRICT,
 CONSTRAINT ck_projection_retention_sweeps_purpose_bound CHECK(purpose IN ('expiry','source_match','owner_erasure')),
 CONSTRAINT ck_projection_retention_sweeps_scope_bound CHECK((purpose='expiry' AND target_kind IS NULL AND target_id IS NULL) OR (purpose='owner_erasure' AND owner_id IS NOT NULL AND target_kind IS NULL AND target_id IS NULL) OR (purpose='source_match' AND owner_id IS NOT NULL AND target_kind IN ('price','fx','corporate_action','benchmark','historical') AND target_id IS NOT NULL)),
 CONSTRAINT ck_projection_retention_sweeps_epoch_bound CHECK(policy_epoch>=0)
)""",
    r"""CREATE INDEX ix_projection_retention_targets_cleanup ON projection_retention_targets(owner_id,account_id,run_id,id)""",
    r"""CREATE INDEX ix_projection_retention_sweeps_owner ON projection_retention_sweeps(owner_id,key)""",
    r"""CREATE INDEX ix_projection_retention_root_cursor ON premium_runs(kind,id)""",
    r"""CREATE INDEX ix_projection_retention_owner_cursor ON premium_runs(owner_id,kind,id)""",
)

_MAINTENANCE_GUARDS = r"""CREATE FUNCTION projection_update_physical_counter() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE rid uuid; oid uuid; aid uuid; item uuid; current_bytes bigint; current_rows integer;
 old_cost bigint:=0; new_cost bigint:=0; old_part integer:=0; new_part integer:=0;
 next_rows integer; next_bytes bigint; membership_bytes bigint; expression text;
BEGIN
 IF TG_OP='DELETE' THEN oid:=OLD.owner_id; aid:=OLD.account_id; item:=OLD.id;
 ELSE oid:=NEW.owner_id; aid:=NEW.account_id; item:=NEW.id; END IF;
 IF TG_TABLE_NAME IN ('projection_inputs','projection_run_allocations','projection_calendar_boundaries','projection_run_pauses','projection_run_schedule_entries','projection_source_proofs','projection_chunks','projection_paths','projection_points','projection_point_assets','projection_results') THEN
  IF TG_OP='DELETE' THEN rid:=OLD.run_id; ELSE rid:=NEW.run_id; END IF;
 ELSIF TG_TABLE_NAME IN ('projection_zero_pivots','projection_distributions','projection_histograms','projection_goal_analyses') THEN
  IF TG_OP='DELETE' THEN SELECT run_id INTO rid FROM projection_results WHERE id=OLD.result_id AND owner_id=oid AND account_id=aid;
  ELSE SELECT run_id INTO rid FROM projection_results WHERE id=NEW.result_id AND owner_id=oid AND account_id=aid; END IF;
 ELSIF TG_TABLE_NAME='projection_distribution_quantiles' THEN
  IF TG_OP='DELETE' THEN SELECT r.run_id INTO rid FROM projection_distributions d JOIN projection_results r ON r.id=d.result_id WHERE d.id=OLD.distribution_id AND d.owner_id=oid AND d.account_id=aid;
  ELSE SELECT r.run_id INTO rid FROM projection_distributions d JOIN projection_results r ON r.id=d.result_id WHERE d.id=NEW.distribution_id AND d.owner_id=oid AND d.account_id=aid; END IF;
 ELSIF TG_TABLE_NAME='projection_histogram_bins' THEN
  IF TG_OP='DELETE' THEN SELECT r.run_id INTO rid FROM projection_histograms h JOIN projection_results r ON r.id=h.result_id WHERE h.id=OLD.histogram_id AND h.owner_id=oid AND h.account_id=aid;
  ELSE SELECT r.run_id INTO rid FROM projection_histograms h JOIN projection_results r ON r.id=h.result_id WHERE h.id=NEW.histogram_id AND h.owner_id=oid AND h.account_id=aid; END IF;
 ELSIF TG_TABLE_NAME='projection_goal_shortfall_quantiles' THEN
  IF TG_OP='DELETE' THEN SELECT r.run_id INTO rid FROM projection_goal_analyses g JOIN projection_results r ON r.id=g.result_id WHERE g.id=OLD.analysis_id AND g.owner_id=oid AND g.account_id=aid;
  ELSE SELECT r.run_id INTO rid FROM projection_goal_analyses g JOIN projection_results r ON r.id=g.result_id WHERE g.id=NEW.analysis_id AND g.owner_id=oid AND g.account_id=aid; END IF;
 ELSE RAISE EXCEPTION 'Unknown projection counter participant' USING ERRCODE='23514'; END IF;
 IF NOT pg_try_advisory_xact_lock(hashtextextended('premium:'||oid::text,0)) THEN
  RAISE EXCEPTION 'Projection counter owner is busy' USING ERRCODE='55P03'; END IF;
 PERFORM 1 FROM premium_runs WHERE id=rid AND owner_id=oid AND account_id=aid AND kind='projection' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Projection counter root absent' USING ERRCODE='23514'; END IF;
 SELECT stored_bytes,payload_rows,retained_source_bytes INTO current_bytes,current_rows,membership_bytes FROM projection_runs WHERE id=rid AND owner_id=oid AND account_id=aid FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Projection counter capture absent' USING ERRCODE='23514'; END IF;
 CASE TG_TABLE_NAME
 WHEN 'projection_inputs' THEN expression:='pg_column_size(ROW(t."run_id",t."initial_value",t."base_monthly",t."annual_growth",t."contribution_delta",t."annual_mean_log_delta",t."pause_count",t."entry_count",t."capture_bytes",t."input_bytes",t."id",t."owner_id",t."account_id",t."created_at"))+octet_length(t.canonical_capture)+octet_length(t.canonical_input)';
 WHEN 'projection_run_allocations' THEN expression:='pg_column_size(t)';
 WHEN 'projection_calendar_boundaries' THEN expression:='pg_column_size(t)';
 WHEN 'projection_run_pauses' THEN expression:='pg_column_size(t)';
 WHEN 'projection_run_schedule_entries' THEN expression:='pg_column_size(t)';
 WHEN 'projection_source_proofs' THEN expression:='pg_column_size(ROW(t."run_id",t."source_id",t."id",t."owner_id",t."account_id",t."created_at"))+octet_length(t.canonical_proof)';
 WHEN 'projection_chunks' THEN expression:='pg_column_size(ROW(t."run_id",t."job_id",t."lease_token",t."consumer_attempt",t."variant",t."first_path",t."path_count",t."input_digest",t."content_digest",t."byte_length",t."sealed",t."id",t."owner_id",t."account_id",t."created_at"))+octet_length(t.canonical_chunk)';
 WHEN 'projection_paths' THEN expression:='pg_column_size(t)';
 WHEN 'projection_points' THEN expression:='pg_column_size(t)';
 WHEN 'projection_point_assets' THEN expression:='pg_column_size(t)';
 WHEN 'projection_results' THEN expression:='pg_column_size(ROW(t."run_id",t."job_id",t."lease_token",t."consumer_attempt",t."input_digest",t."content_digest",t."byte_length",t."quality",t."sampler",t."sealed",t."id",t."owner_id",t."account_id",t."created_at"))+octet_length(t.canonical_result)';
 WHEN 'projection_zero_pivots' THEN expression:='pg_column_size(t)';
 WHEN 'projection_distributions' THEN expression:='pg_column_size(t)';
 WHEN 'projection_distribution_quantiles' THEN expression:='pg_column_size(t)';
 WHEN 'projection_histograms' THEN expression:='pg_column_size(t)';
 WHEN 'projection_histogram_bins' THEN expression:='pg_column_size(t)';
 WHEN 'projection_goal_analyses' THEN expression:='pg_column_size(t)';
 WHEN 'projection_goal_shortfall_quantiles' THEN expression:='pg_column_size(t)';
 ELSE RAISE EXCEPTION 'Unknown projection byte expression' USING ERRCODE='23514'; END CASE;
 -- AFTER INSERT/UPDATE reads the exact stored tuple; BEFORE DELETE reads it before
 -- removal. No approximate NEW-record layout replaces pg_column_size(table_row).
 EXECUTE 'SELECT ('||expression||')::bigint FROM '||quote_ident(TG_TABLE_NAME)||' t WHERE t.id=$1 AND t.owner_id=$2 AND t.account_id=$3'
 INTO new_cost USING item,oid,aid;
 IF new_cost IS NULL THEN RAISE EXCEPTION 'Projection counter row absent' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' THEN new_part:=1;
 ELSIF TG_OP='DELETE' THEN old_cost:=new_cost; new_cost:=0; old_part:=1;
 ELSE old_cost:=new_cost; old_part:=1; new_part:=1; END IF;
 IF TG_TABLE_NAME='projection_results' THEN
  IF TG_OP<>'DELETE' THEN new_part:=CASE WHEN octet_length(NEW.canonical_result)>0 THEN 1 ELSE 0 END; END IF;
  IF TG_OP<>'INSERT' THEN old_part:=CASE WHEN octet_length(OLD.canonical_result)>0 THEN 1 ELSE 0 END; END IF;
  IF TG_OP='UPDATE' THEN
   old_cost:=pg_column_size(ROW(OLD."run_id",OLD."job_id",OLD."lease_token",OLD."consumer_attempt",OLD."input_digest",OLD."content_digest",OLD."byte_length",OLD."quality",OLD."sampler",OLD."sealed",OLD."id",OLD."owner_id",OLD."account_id",OLD."created_at"))+octet_length(OLD.canonical_result);
  END IF;
  IF TG_OP='DELETE' AND current_rows=0 THEN old_cost:=0; END IF;
 END IF;
 next_rows:=current_rows+new_part-old_part;
 next_bytes:=CASE WHEN next_rows=0 THEN membership_bytes ELSE current_bytes+new_cost-old_cost END;
 IF next_rows<0 OR next_bytes<0 OR next_bytes>33554432 THEN
  RAISE EXCEPTION 'Projection physical counter bound violated' USING ERRCODE='23514'; END IF;
 UPDATE projection_runs SET stored_bytes=next_bytes,payload_rows=next_rows WHERE id=rid AND owner_id=oid AND account_id=aid;
 RETURN coalesce(NEW,OLD);
END $$;

CREATE FUNCTION projection_retention_policy_epoch() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE selected_owner uuid;
BEGIN
 selected_owner:=NEW.owner_id;
 IF TG_OP='UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
 IF NOT pg_try_advisory_xact_lock(hashtextextended('sources:'||selected_owner::text,0)) THEN
  RAISE EXCEPTION 'Projection policy owner is busy' USING ERRCODE='55P03'; END IF;
 INSERT INTO projection_retention_epochs(owner_id,epoch,roots_epoch)
 VALUES(selected_owner,CASE WHEN TG_TABLE_NAME='projection_runs' THEN 0 ELSE 1 END,
  CASE WHEN TG_TABLE_NAME='projection_runs' THEN 1 ELSE 0 END)
 ON CONFLICT(owner_id) DO UPDATE SET epoch=projection_retention_epochs.epoch+EXCLUDED.epoch,
  roots_epoch=projection_retention_epochs.roots_epoch+EXCLUDED.roots_epoch;
 RETURN NEW;
END $$;
CREATE FUNCTION projection_retention_epoch_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF pg_trigger_depth()<=1 THEN RAISE EXCEPTION 'Projection policy epoch is trigger-owned' USING ERRCODE='23514'; END IF;
 RETURN coalesce(NEW,OLD);
END $$;
"""

_MAINTENANCE_TRIGGERS = (
    (
        "projection_inputs",
        "z_projection_counter_write",
        "AFTER INSERT OR UPDATE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_inputs",
        "a_projection_counter_delete",
        "BEFORE DELETE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_run_allocations",
        "z_projection_counter_write",
        "AFTER INSERT OR UPDATE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_run_allocations",
        "a_projection_counter_delete",
        "BEFORE DELETE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_calendar_boundaries",
        "z_projection_counter_write",
        "AFTER INSERT OR UPDATE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_calendar_boundaries",
        "a_projection_counter_delete",
        "BEFORE DELETE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_run_pauses",
        "z_projection_counter_write",
        "AFTER INSERT OR UPDATE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_run_pauses",
        "a_projection_counter_delete",
        "BEFORE DELETE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_run_schedule_entries",
        "z_projection_counter_write",
        "AFTER INSERT OR UPDATE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_run_schedule_entries",
        "a_projection_counter_delete",
        "BEFORE DELETE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_source_proofs",
        "z_projection_counter_write",
        "AFTER INSERT OR UPDATE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_source_proofs",
        "a_projection_counter_delete",
        "BEFORE DELETE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_chunks",
        "z_projection_counter_write",
        "AFTER INSERT OR UPDATE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_chunks",
        "a_projection_counter_delete",
        "BEFORE DELETE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_paths",
        "z_projection_counter_write",
        "AFTER INSERT OR UPDATE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_paths",
        "a_projection_counter_delete",
        "BEFORE DELETE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_points",
        "z_projection_counter_write",
        "AFTER INSERT OR UPDATE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_points",
        "a_projection_counter_delete",
        "BEFORE DELETE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_point_assets",
        "z_projection_counter_write",
        "AFTER INSERT OR UPDATE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_point_assets",
        "a_projection_counter_delete",
        "BEFORE DELETE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_results",
        "z_projection_counter_write",
        "AFTER INSERT OR UPDATE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_results",
        "a_projection_counter_delete",
        "BEFORE DELETE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_zero_pivots",
        "z_projection_counter_write",
        "AFTER INSERT OR UPDATE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_zero_pivots",
        "a_projection_counter_delete",
        "BEFORE DELETE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_distributions",
        "z_projection_counter_write",
        "AFTER INSERT OR UPDATE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_distributions",
        "a_projection_counter_delete",
        "BEFORE DELETE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_distribution_quantiles",
        "z_projection_counter_write",
        "AFTER INSERT OR UPDATE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_distribution_quantiles",
        "a_projection_counter_delete",
        "BEFORE DELETE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_histograms",
        "z_projection_counter_write",
        "AFTER INSERT OR UPDATE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_histograms",
        "a_projection_counter_delete",
        "BEFORE DELETE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_histogram_bins",
        "z_projection_counter_write",
        "AFTER INSERT OR UPDATE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_histogram_bins",
        "a_projection_counter_delete",
        "BEFORE DELETE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_goal_analyses",
        "z_projection_counter_write",
        "AFTER INSERT OR UPDATE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_goal_analyses",
        "a_projection_counter_delete",
        "BEFORE DELETE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_goal_shortfall_quantiles",
        "z_projection_counter_write",
        "AFTER INSERT OR UPDATE",
        "projection_update_physical_counter()",
    ),
    (
        "projection_goal_shortfall_quantiles",
        "a_projection_counter_delete",
        "BEFORE DELETE",
        "projection_update_physical_counter()",
    ),
    (
        "provider_license_versions",
        "z_projection_retention_epoch",
        "AFTER INSERT OR UPDATE",
        "projection_retention_policy_epoch()",
    ),
    (
        "source_retention_work",
        "z_projection_retention_epoch",
        "AFTER INSERT",
        "projection_retention_policy_epoch()",
    ),
    (
        "source_expiry_events",
        "z_projection_retention_epoch",
        "AFTER INSERT",
        "projection_retention_policy_epoch()",
    ),
    (
        "historical_retention_events",
        "z_projection_retention_epoch",
        "AFTER INSERT",
        "projection_retention_policy_epoch()",
    ),
    (
        "projection_retention_epochs",
        "projection_retention_epoch_guard",
        "BEFORE INSERT OR UPDATE OR DELETE",
        "projection_retention_epoch_guard()",
    ),
    (
        "projection_runs",
        "z_projection_retention_epoch",
        "AFTER INSERT",
        "projection_retention_policy_epoch()",
    ),
)

_MEMBERSHIP_DDL = r"""CREATE TABLE projection_retained_source_memberships (
 run_id UUID NOT NULL, source_kind VARCHAR(20) NOT NULL, source_id UUID NOT NULL,
 original_created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 id UUID NOT NULL, owner_id UUID NOT NULL, account_id UUID NOT NULL, created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
 CONSTRAINT pk_projection_retained_source_memberships PRIMARY KEY(id),
 CONSTRAINT fk_projection_retained_sources_owner FOREIGN KEY(owner_id) REFERENCES owners(id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_retained_sources_account FOREIGN KEY(account_id) REFERENCES broker_accounts(id) ON DELETE RESTRICT,
 CONSTRAINT fk_projection_retained_sources_run FOREIGN KEY(owner_id,account_id,run_id) REFERENCES projection_runs(owner_id,account_id,id) ON DELETE RESTRICT,
 CONSTRAINT uq_projection_retained_source UNIQUE(run_id,source_kind,source_id),
 CONSTRAINT ck_projection_retained_source_memberships_kind_allowed CHECK(source_kind IN ('price','fx','corporate_action','benchmark','historical','license','classification'))
);
CREATE INDEX ix_projection_retained_parent ON projection_retained_source_memberships(owner_id,source_kind,source_id,run_id);
CREATE INDEX ix_projection_retained_cleanup ON projection_retained_source_memberships(owner_id,account_id,run_id,id);
CREATE INDEX ix_projection_paths_purge_fk ON projection_paths(owner_id,account_id,chunk_id);
CREATE INDEX ix_projection_points_purge_fk ON projection_points(owner_id,account_id,path_id);
CREATE INDEX ix_projection_point_assets_purge_fk ON projection_point_assets(owner_id,account_id,point_id);
CREATE INDEX ix_projection_inputs_purge_key ON projection_inputs(owner_id,account_id,run_id,id);
CREATE INDEX ix_projection_run_allocations_purge_key ON projection_run_allocations(owner_id,account_id,run_id,id);
CREATE INDEX ix_projection_calendar_boundaries_purge_key ON projection_calendar_boundaries(owner_id,account_id,run_id,id);
CREATE INDEX ix_projection_run_pauses_purge_key ON projection_run_pauses(owner_id,account_id,run_id,id);
CREATE INDEX ix_projection_run_schedule_entries_purge_key ON projection_run_schedule_entries(owner_id,account_id,run_id,id);
CREATE INDEX ix_projection_source_proofs_purge_key ON projection_source_proofs(owner_id,account_id,run_id,id);
CREATE INDEX ix_projection_chunks_purge_key ON projection_chunks(owner_id,account_id,run_id,id);
CREATE INDEX ix_projection_paths_purge_key ON projection_paths(owner_id,account_id,run_id,id);
CREATE INDEX ix_projection_points_purge_key ON projection_points(owner_id,account_id,run_id,id);
CREATE INDEX ix_projection_point_assets_purge_key ON projection_point_assets(owner_id,account_id,run_id,id);
CREATE INDEX ix_projection_results_purge_key ON projection_results(owner_id,account_id,run_id,id);
CREATE INDEX ix_projection_zero_pivots_purge_key ON projection_zero_pivots(owner_id,account_id,result_id,id);
CREATE INDEX ix_projection_distributions_purge_key ON projection_distributions(owner_id,account_id,result_id,id);
CREATE INDEX ix_projection_histograms_purge_key ON projection_histograms(owner_id,account_id,result_id,id);
CREATE INDEX ix_projection_goal_analyses_purge_key ON projection_goal_analyses(owner_id,account_id,result_id,id);
CREATE INDEX ix_projection_distribution_quantiles_purge_key ON projection_distribution_quantiles(owner_id,account_id,distribution_id,id);
CREATE INDEX ix_projection_histogram_bins_purge_key ON projection_histogram_bins(owner_id,account_id,histogram_id,id);
CREATE INDEX ix_projection_goal_shortfall_quantiles_purge_key ON projection_goal_shortfall_quantiles(owner_id,account_id,analysis_id,id);
"""

_MEMBERSHIP_GUARDS = r"""CREATE FUNCTION projection_expected_source_memberships(p_owner uuid,p_run uuid)
RETURNS TABLE(source_kind text,source_id uuid,original_created_at timestamptz)
LANGUAGE sql STABLE AS $$
 WITH calibrations AS (
  SELECT s.subject_id FROM projection_run_sources s
  WHERE s.owner_id=p_owner AND s.run_id=p_run AND s.kind='calibration'
 ), histories AS (
  SELECT h.id,h.created_at FROM historical_input_snapshots h
  JOIN calibrations c ON c.subject_id=h.id WHERE h.owner_id=p_owner
 ), direct_links AS (
  SELECT d.*,h.created_at history_created_at FROM historical_dependencies d
  JOIN histories h ON h.id=d.input_id WHERE d.owner_id=p_owner
 ), links AS (
  SELECT d.* FROM direct_links d
  UNION ALL
  SELECT d.*,p.history_created_at FROM historical_dependencies d
  JOIN direct_links p ON p.registered_evidence_id=d.evidence_id WHERE d.owner_id=p_owner
 ), origins AS (
  SELECT 'historical'::text source_kind,h.id source_id,h.created_at original_created_at FROM histories h
  UNION ALL SELECT 'price',p.id,p.created_at FROM price_snapshots p JOIN calibrations c ON c.subject_id=p.id WHERE p.owner_id=p_owner
  UNION ALL SELECT 'benchmark',b.id,b.created_at FROM benchmark_snapshots b JOIN calibrations c ON c.subject_id=b.id WHERE b.owner_id=p_owner
  UNION ALL SELECT 'price',p.id,p.created_at FROM links d JOIN price_snapshots p ON p.id=d.price_snapshot_id AND p.owner_id=p_owner
  UNION ALL SELECT 'fx',f.id,f.created_at FROM links d JOIN fx_snapshots f ON f.id=d.fx_snapshot_id AND f.owner_id=p_owner
  UNION ALL SELECT 'corporate_action',a.id,a.created_at FROM links d JOIN corporate_action_snapshots a ON a.id=d.action_snapshot_id AND a.owner_id=p_owner
  UNION ALL SELECT 'benchmark',b.id,b.created_at FROM links d JOIN benchmark_snapshots b ON b.id=d.benchmark_snapshot_id AND b.owner_id=p_owner
  UNION ALL SELECT 'license',d.license_version_id,d.history_created_at FROM links d WHERE d.license_version_id IS NOT NULL
  UNION ALL SELECT 'classification',c.id,least(c.created_at,d.history_created_at) FROM links d JOIN historical_classification_evidence c ON c.id=d.classification_id AND c.owner_id=p_owner
 ) SELECT o.source_kind,o.source_id,min(o.original_created_at) FROM origins o
 GROUP BY o.source_kind,o.source_id LIMIT 100001
$$;

CREATE FUNCTION projection_source_membership_complete(p_run uuid) RETURNS boolean
LANGUAGE plpgsql STABLE AS $$
DECLARE run projection_runs; expected_count integer; actual_count integer;
BEGIN
 SELECT * INTO run FROM projection_runs WHERE id=p_run;
 IF run.id IS NULL THEN RETURN false; END IF;
 -- Admission has always forbidden evidence -> evidence. Preserve that boundary
 -- explicitly instead of widening the admitted graph through a recursive CTE.
 IF EXISTS(SELECT 1 FROM projection_run_sources s
  JOIN historical_dependencies p ON p.owner_id=s.owner_id AND p.input_id=s.subject_id
  JOIN historical_dependencies child ON child.owner_id=p.owner_id AND child.evidence_id=p.registered_evidence_id
  WHERE s.run_id=p_run AND s.kind='calibration' AND child.registered_evidence_id IS NOT NULL)
 THEN RETURN false; END IF;
 SELECT count(*) INTO expected_count FROM projection_expected_source_memberships(run.owner_id,p_run);
 SELECT count(*) INTO actual_count FROM projection_retained_source_memberships WHERE owner_id=run.owner_id AND account_id=run.account_id AND run_id=p_run;
 IF expected_count>100000 OR expected_count<>actual_count OR actual_count<>run.retained_source_rows THEN RETURN false; END IF;
 RETURN NOT EXISTS(
  (SELECT * FROM projection_expected_source_memberships(run.owner_id,p_run)
   EXCEPT SELECT source_kind,source_id,original_created_at FROM projection_retained_source_memberships WHERE owner_id=run.owner_id AND account_id=run.account_id AND run_id=p_run)
  UNION ALL
  (SELECT source_kind,source_id,original_created_at FROM projection_retained_source_memberships WHERE owner_id=run.owner_id AND account_id=run.account_id AND run_id=p_run
   EXCEPT SELECT * FROM projection_expected_source_memberships(run.owner_id,p_run))
 );
END $$;

CREATE FUNCTION projection_retained_source_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE root premium_runs; run projection_runs; selected_owner uuid; selected_run uuid;
BEGIN
 IF TG_TABLE_NAME='projection_runs' THEN
  IF NOT OLD.sealed AND NEW.sealed AND NOT projection_source_membership_complete(NEW.id) THEN
   RAISE EXCEPTION 'Projection retained source membership is incomplete' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'Projection retained source membership is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN selected_owner:=OLD.owner_id; selected_run:=OLD.run_id;
 ELSE selected_owner:=NEW.owner_id; selected_run:=NEW.run_id; END IF;
 -- Runtime prelocks all owner namespaces; the trigger must never wait after a
 -- DELETE has acquired its physical tuple lock.
 IF NOT pg_try_advisory_xact_lock(hashtextextended('sources:'||selected_owner::text,0))
  OR NOT pg_try_advisory_xact_lock(hashtextextended('premium:'||selected_owner::text,0)) THEN
  RAISE EXCEPTION 'Projection retained source owner is busy' USING ERRCODE='55P03'; END IF;
 SELECT * INTO root FROM premium_runs WHERE owner_id=selected_owner AND id=selected_run FOR UPDATE;
 SELECT * INTO run FROM projection_runs WHERE owner_id=selected_owner AND id=selected_run FOR UPDATE;
 IF root.kind IS DISTINCT FROM 'projection' OR run.id IS NULL THEN
  RAISE EXCEPTION 'Projection retained source root absent' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' THEN
  IF run.sealed OR NEW.account_id IS DISTINCT FROM run.account_id OR NEW.created_at IS DISTINCT FROM root.created_at
   OR NEW.original_created_at>NEW.created_at OR run.retained_source_rows>=100000
   OR EXISTS(SELECT 1 FROM premium_retention_events WHERE owner_id=selected_owner AND run_id=selected_run)
  THEN RAISE EXCEPTION 'Projection retained source capture is closed' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF NOT run.sealed OR run.payload_rows<>0 OR NOT EXISTS(
  SELECT 1 FROM premium_retention_events WHERE owner_id=selected_owner AND account_id=OLD.account_id AND run_id=selected_run AND completed_at IS NULL
 ) THEN RAISE EXCEPTION 'Projection financial copies remain before source membership removal' USING ERRCODE='23514'; END IF;
 -- 0023 adds the indexed pending-report check here as well. Already in 0022 no
 -- report can bind a projection; 0023 financial-copy guards run before payload_rows=0.
 RETURN OLD;
END $$;

CREATE FUNCTION projection_retained_source_counter() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE item uuid; rid uuid; oid uuid; aid uuid; cost bigint; direction integer;
BEGIN
 IF TG_OP='DELETE' THEN item:=OLD.id; rid:=OLD.run_id; oid:=OLD.owner_id; aid:=OLD.account_id; direction:=-1;
 ELSE item:=NEW.id; rid:=NEW.run_id; oid:=NEW.owner_id; aid:=NEW.account_id; direction:=1; END IF;
 -- The preceding membership guard has acquired the exact root locks.
 SELECT pg_column_size(t)::bigint INTO cost FROM projection_retained_source_memberships t
 WHERE t.owner_id=oid AND t.account_id=aid AND t.run_id=rid AND t.id=item;
 IF cost IS NULL THEN RAISE EXCEPTION 'Projection retained source counter row absent' USING ERRCODE='23514'; END IF;
 UPDATE projection_runs SET stored_bytes=stored_bytes+direction*cost,
  retained_source_bytes=retained_source_bytes+direction*cost,
  retained_source_rows=retained_source_rows+direction
 WHERE owner_id=oid AND account_id=aid AND id=rid;
 IF NOT FOUND THEN RAISE EXCEPTION 'Projection retained source counter root absent' USING ERRCODE='23514'; END IF;
 RETURN coalesce(NEW,OLD);
END $$;
"""


def _checks(table: str, checks: dict[str, str]) -> None:
    for name, sql in checks.items():
        identity = op.f("ck_" + table + "_" + name)
        op.drop_constraint(identity, table, type_="check")
        op.create_check_constraint(identity, table, sql)


def upgrade() -> None:
    for sql in _DDL:
        op.execute(sa.text(sql))
    for sql in _MAINTENANCE_DDL:
        op.execute(sa.text(sql))
    op.execute(sa.text(_MEMBERSHIP_DDL))
    _checks("application_command_identities", _COMMAND_CHECKS)
    _checks("collection_query_snapshots", _COLLECTION_CHECKS)
    op.execute(sa.text(_PROJECTION_GUARDS))
    op.execute(sa.text(_SHARED_GUARDS))
    op.execute(sa.text(_RETENTION_GUARDS))
    op.execute(sa.text(_MAINTENANCE_GUARDS))
    op.execute(sa.text(_MEMBERSHIP_GUARDS))
    op.execute(
        sa.text(
            "CREATE TRIGGER a_projection_retained_source_guard BEFORE INSERT OR UPDATE OR DELETE ON projection_retained_source_memberships FOR EACH ROW EXECUTE FUNCTION projection_retained_source_guard()"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER projection_retained_source_seal BEFORE UPDATE ON projection_runs FOR EACH ROW EXECUTE FUNCTION projection_retained_source_guard()"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER z_projection_retained_source_counter AFTER INSERT ON projection_retained_source_memberships FOR EACH ROW EXECUTE FUNCTION projection_retained_source_counter()"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER z_projection_retained_source_counter_delete BEFORE DELETE ON projection_retained_source_memberships FOR EACH ROW EXECUTE FUNCTION projection_retained_source_counter()"
        )
    )
    for table, name, timing, function in _MAINTENANCE_TRIGGERS:
        op.execute(
            sa.text(
                "CREATE TRIGGER "
                + name
                + " "
                + timing
                + " ON "
                + table
                + " FOR EACH ROW EXECUTE FUNCTION "
                + function
            )
        )
    for table, timing in _RETENTION_TRIGGERS:
        op.execute(
            sa.text(
                "CREATE TRIGGER a_projection_source_parent_guard "
                + timing
                + " ON "
                + table
                + " FOR EACH ROW EXECUTE FUNCTION projection_source_parent_guard()"
            )
        )
    for name, table, columns in _RETENTION_INDICES:
        op.create_index(name, table, list(columns))
    for sql in _TRIGGERS:
        op.execute(sa.text(sql))


def downgrade() -> None:
    # Never silently discard immutable definitions, command or financial audit.
    retained = ["EXISTS(SELECT 1 FROM " + table + ")" for table in _TABLES]
    retained.extend(
        (
            "EXISTS(SELECT 1 FROM premium_runs WHERE kind='projection')",
            "EXISTS(SELECT 1 FROM application_command_identities WHERE command LIKE 'projection.%')",
            "EXISTS(SELECT 1 FROM collection_query_snapshots WHERE resource IN ('assumption_sets','assumption_versions','goals','goal_versions','projection_runs'))",
        )
    )
    op.execute(
        sa.text(
            "DO $$ BEGIN IF "
            + " OR ".join(retained)
            + " THEN RAISE EXCEPTION 'Projection metadata prevents downgrade' USING ERRCODE='23514'; END IF; END $$"
        )
    )
    op.execute(sa.text("DROP TRIGGER projection_retained_source_seal ON projection_runs"))
    for name in (
        "a_projection_retained_source_guard",
        "z_projection_retained_source_counter",
        "z_projection_retained_source_counter_delete",
    ):
        op.execute(sa.text("DROP TRIGGER " + name + " ON projection_retained_source_memberships"))
    op.execute(sa.text("DROP FUNCTION projection_retained_source_counter()"))
    op.execute(sa.text("DROP FUNCTION projection_retained_source_guard()"))
    # Callers are PL/pgSQL and do not retain static dependencies on these helpers.
    op.execute(sa.text("DROP FUNCTION projection_source_membership_complete(uuid)"))
    op.execute(sa.text("DROP FUNCTION projection_expected_source_memberships(uuid,uuid)"))
    for table, name, _, _ in reversed(_MAINTENANCE_TRIGGERS):
        op.execute(sa.text("DROP TRIGGER " + name + " ON " + table))
    op.execute(sa.text("DROP FUNCTION projection_update_physical_counter()"))
    op.execute(sa.text("DROP FUNCTION projection_retention_policy_epoch()"))
    op.execute(sa.text("DROP FUNCTION projection_retention_epoch_guard()"))
    op.drop_index("ix_projection_retention_source_keyset", table_name="projection_run_sources")
    op.drop_index(
        "ix_projection_retention_policy_activation", table_name="provider_license_versions"
    )
    op.drop_index(
        "ix_projection_retention_policy_selection", table_name="provider_license_versions"
    )
    op.drop_index("ix_projection_retention_root_cursor", table_name="premium_runs")
    op.drop_index("ix_projection_retention_owner_cursor", table_name="premium_runs")
    for table in (
        "projection_retention_sweeps",
        "projection_retention_targets",
        "projection_retention_frontier",
        "projection_retention_scans",
        "projection_retention_epochs",
    ):
        op.drop_table(table)
    for table, _ in _RETENTION_TRIGGERS:
        op.execute(sa.text("DROP TRIGGER a_projection_source_parent_guard ON " + table))
    for name, table, _ in _RETENTION_INDICES:
        op.drop_index(name, table_name=table)
    for function in _RETENTION_FUNCTIONS:
        op.execute(sa.text("DROP FUNCTION " + function))
    for table, trigger in _EXTERNAL_TRIGGERS:
        op.execute(sa.text("DROP TRIGGER " + trigger + " ON " + table))
    op.execute(sa.text(_PREVIOUS_SHARED_GUARDS))
    _checks("application_command_identities", _PREVIOUS_COMMAND_CHECKS)
    _checks("collection_query_snapshots", _PREVIOUS_COLLECTION_CHECKS)
    op.drop_table("projection_retained_source_memberships")
    for table in reversed(_TABLES):
        op.drop_table(table)
    for function in _FUNCTIONS:
        op.execute(sa.text("DROP FUNCTION " + function))
