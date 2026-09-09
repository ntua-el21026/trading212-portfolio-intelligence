"""X-ray intelligence and bounded shared source retention.

Revision ID: 20260909_0013
Revises: 20260907_0012
"""

import sqlalchemy as sa
from alembic import op

revision = "20260909_0013"
down_revision = "20260907_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _xray_catalog_schema()
    _source_retention_schema()
    _shared_xray_schema()
    _pending_payload_indexes()
    _xray_guards()
    _xray_retention_guards()
    op.execute(SOURCE_RETENTION_WORK_GUARD)
    op.execute(SOURCE_IMMUTABLE_GUARD)
    op.execute(HISTORICAL_RETENTION_WRITE)
    op.execute(SOURCE_EXPIRY_GUARD)


def _source_retention_schema() -> None:
    op.create_table(
        "source_retention_work",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("removed_observation_count", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("price_snapshot_id", sa.Uuid()),
        sa.Column("fx_snapshot_id", sa.Uuid()),
        sa.Column("benchmark_snapshot_id", sa.Uuid()),
        sa.Column("corporate_action_snapshot_id", sa.Uuid()),
        sa.UniqueConstraint("owner_id", "id"),
        sa.ForeignKeyConstraint(
            ["owner_id", "price_snapshot_id"],
            ["price_snapshots.owner_id", "price_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("price_snapshot_id"),
        sa.ForeignKeyConstraint(
            ["owner_id", "fx_snapshot_id"],
            ["fx_snapshots.owner_id", "fx_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("fx_snapshot_id"),
        sa.ForeignKeyConstraint(
            ["owner_id", "benchmark_snapshot_id"],
            ["benchmark_snapshots.owner_id", "benchmark_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("benchmark_snapshot_id"),
        sa.ForeignKeyConstraint(
            ["owner_id", "corporate_action_snapshot_id"],
            ["corporate_action_snapshots.owner_id", "corporate_action_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("corporate_action_snapshot_id"),
        sa.CheckConstraint(
            "num_nonnulls(price_snapshot_id, fx_snapshot_id, benchmark_snapshot_id, corporate_action_snapshot_id) = 1",
            name=op.f("ck_source_retention_work_snapshot_xor"),
        ),
        sa.CheckConstraint(
            "phase IN ('copies','observations','coverage','complete')",
            name=op.f("ck_source_retention_work_phase_allowed"),
        ),
        sa.CheckConstraint(
            "removed_observation_count BETWEEN 0 AND 100000",
            name=op.f("ck_source_retention_work_removed_bound"),
        ),
        sa.CheckConstraint(
            "(phase='complete') = (completed_at IS NOT NULL)",
            name=op.f("ck_source_retention_work_completion_state"),
        ),
        sa.CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_source_retention_work_content_digest_format"),
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name=op.f("ck_source_retention_work_time_order"),
        ),
    )
    op.create_index(
        "ix_source_retention_pending", "source_retention_work", ["owner_id", "phase", "id"]
    )


def _pending_payload_indexes() -> None:
    op.create_index(
        "ix_retention_performance_points",
        "performance_points",
        ["run_id", "id"],
        postgresql_where=sa.text(
            "canonical_row <> '\\x'::bytea OR portfolio_value IS NOT NULL OR cash_value IS NOT NULL OR wealth IS NOT NULL OR period_return IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_retention_performance_period_returns",
        "performance_period_returns",
        ["run_id", "id"],
        postgresql_where=sa.text("canonical_row <> '\\x'::bytea OR period_return IS NOT NULL"),
    )
    op.create_index(
        "ix_retention_income_components",
        "income_components",
        ["run_id", "id"],
        postgresql_where=sa.text(
            "canonical_row <> '\\x'::bytea OR net IS NOT NULL OR gross IS NOT NULL OR withholding IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_retention_attribution_components",
        "attribution_components",
        ["run_id", "id"],
        postgresql_where=sa.text(
            "canonical_row <> '\\x'::bytea OR gain IS NOT NULL OR return_contribution IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_retention_historical_cash_flow_points",
        "historical_cash_flow_points",
        ["run_id", "id"],
        postgresql_where=sa.text("canonical_row <> '\\x'::bytea OR amount IS NOT NULL"),
    )
    op.create_index(
        "ix_retention_historical_conversions",
        "historical_conversions",
        ["run_id", "id"],
        postgresql_where=sa.text("rate IS NOT NULL"),
    )
    op.create_index(
        "ix_retention_historical_composite_benchmarks",
        "historical_composite_benchmarks",
        ["run_id", "id"],
        postgresql_where=sa.text("canonical_composite <> '\\x'::bytea"),
    )
    op.create_index(
        "ix_retention_benchmark_composite_points",
        "benchmark_composite_points",
        ["snapshot_id", "id"],
        postgresql_where=sa.text(
            "canonical_point <> '\\x'::bytea OR wealth IS NOT NULL OR interval_return IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_retention_dependency_price",
        "historical_dependencies",
        ["price_snapshot_id", "input_id", "id"],
    )
    op.create_index(
        "ix_retention_dependency_fx",
        "historical_dependencies",
        ["fx_snapshot_id", "input_id", "id"],
    )
    op.create_index(
        "ix_retention_dependency_actions",
        "historical_dependencies",
        ["action_snapshot_id", "input_id", "id"],
    )
    op.create_index(
        "ix_retention_dependency_benchmark",
        "historical_dependencies",
        ["benchmark_snapshot_id", "input_id", "id"],
    )
    op.create_index("ix_retention_runs_input", "historical_analytics_runs", ["input_id", "id"])
    op.create_index("ix_retention_price_observations", "price_observations", ["snapshot_id", "id"])
    op.create_index("ix_retention_fx_observations", "fx_observations", ["snapshot_id", "id"])
    op.create_index(
        "ix_retention_benchmark_observations", "benchmark_observations", ["snapshot_id", "id"]
    )
    op.create_index(
        "ix_retention_corporate_action_observations",
        "corporate_action_observations",
        ["snapshot_id", "id"],
    )
    op.create_index("ix_retention_gaps_price", "source_coverage_gaps", ["price_snapshot_id", "id"])
    op.create_index("ix_retention_gaps_fx", "source_coverage_gaps", ["fx_snapshot_id", "id"])
    op.create_index(
        "ix_retention_gaps_benchmark", "source_coverage_gaps", ["benchmark_snapshot_id", "id"]
    )
    op.create_index(
        "ix_retention_gaps_corporate_action",
        "source_coverage_gaps",
        ["corporate_action_snapshot_id", "id"],
    )


def downgrade() -> None:
    _drop_xray_retention_guards()
    _drop_xray_guards()
    _drop_shared_xray_schema()
    op.execute(OLD_SOURCE_IMMUTABLE_GUARD)
    op.execute(OLD_SOURCE_EXPIRY_GUARD)
    op.execute(OLD_HISTORICAL_RETENTION_WRITE)
    op.execute("DROP TRIGGER source_retention_progress ON source_retention_work")
    op.execute("DROP FUNCTION source_retention_work_guard()")
    op.drop_index("ix_retention_gaps_corporate_action", table_name="source_coverage_gaps")
    op.drop_index("ix_retention_gaps_benchmark", table_name="source_coverage_gaps")
    op.drop_index("ix_retention_gaps_fx", table_name="source_coverage_gaps")
    op.drop_index("ix_retention_gaps_price", table_name="source_coverage_gaps")
    op.drop_index(
        "ix_retention_corporate_action_observations", table_name="corporate_action_observations"
    )
    op.drop_index("ix_retention_benchmark_observations", table_name="benchmark_observations")
    op.drop_index("ix_retention_fx_observations", table_name="fx_observations")
    op.drop_index("ix_retention_price_observations", table_name="price_observations")
    op.drop_index("ix_retention_runs_input", table_name="historical_analytics_runs")
    op.drop_index("ix_retention_dependency_benchmark", table_name="historical_dependencies")
    op.drop_index("ix_retention_dependency_actions", table_name="historical_dependencies")
    op.drop_index("ix_retention_dependency_fx", table_name="historical_dependencies")
    op.drop_index("ix_retention_dependency_price", table_name="historical_dependencies")
    op.drop_index(
        "ix_retention_benchmark_composite_points", table_name="benchmark_composite_points"
    )
    op.drop_index(
        "ix_retention_historical_composite_benchmarks", table_name="historical_composite_benchmarks"
    )
    op.drop_index("ix_retention_historical_conversions", table_name="historical_conversions")
    op.drop_index(
        "ix_retention_historical_cash_flow_points", table_name="historical_cash_flow_points"
    )
    op.drop_index("ix_retention_attribution_components", table_name="attribution_components")
    op.drop_index("ix_retention_income_components", table_name="income_components")
    op.drop_index(
        "ix_retention_performance_period_returns", table_name="performance_period_returns"
    )
    op.drop_index("ix_retention_performance_points", table_name="performance_points")
    op.drop_index("ix_source_retention_pending", table_name="source_retention_work")
    op.drop_table("source_retention_work")
    _drop_xray_catalog()


SOURCE_RETENTION_WORK_GUARD = r"""
CREATE FUNCTION source_retention_work_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE reference text; snapshot uuid; retained record; old_rank integer; new_rank integer;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Source retention work must be retained' USING ERRCODE='23514'; END IF;
 reference := CASE WHEN NEW.price_snapshot_id IS NOT NULL THEN 'price_snapshot' WHEN NEW.fx_snapshot_id IS NOT NULL THEN 'fx_snapshot' WHEN NEW.benchmark_snapshot_id IS NOT NULL THEN 'benchmark_snapshot' WHEN NEW.constituent_snapshot_id IS NOT NULL THEN 'constituent_snapshot' ELSE 'corporate_action_snapshot' END;
 snapshot := (to_jsonb(NEW)->>(reference||'_id'))::uuid;
 EXECUTE format('SELECT expires_at,content_digest FROM %I WHERE id=$1 AND owner_id=$2',reference||'s') INTO retained USING snapshot,NEW.owner_id;
 IF retained.expires_at IS NULL OR retained.expires_at>NEW.started_at OR retained.content_digest IS DISTINCT FROM NEW.content_digest THEN
  RAISE EXCEPTION 'Source pending retention authorization mismatch' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.phase<>'copies' OR NEW.removed_observation_count<>0 OR NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'Source retention must start pending' USING ERRCODE='23514'; END IF;
 ELSE
  IF (to_jsonb(OLD)-ARRAY['phase','removed_observation_count','completed_at']) IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['phase','removed_observation_count','completed_at']) THEN RAISE EXCEPTION 'Source retention identity is immutable' USING ERRCODE='23514'; END IF;
  old_rank:=array_position(ARRAY['copies','observations','coverage','complete'],OLD.phase);
  new_rank:=array_position(ARRAY['copies','observations','coverage','complete'],NEW.phase);
  IF OLD.phase='complete' OR new_rank<old_rank OR new_rank>old_rank+1 OR NEW.removed_observation_count<OLD.removed_observation_count OR (NEW.removed_observation_count<>OLD.removed_observation_count AND OLD.phase<>'observations') THEN RAISE EXCEPTION 'Source retention progress must be monotonic' USING ERRCODE='23514'; END IF;
  IF NEW.phase='complete' THEN
   EXECUTE format('SELECT removed_at,removed_observation_count FROM source_expiry_events WHERE owner_id=$1 AND %I=$2',reference||'_id') INTO retained USING NEW.owner_id,snapshot;
   IF retained.removed_at IS NULL OR retained.removed_at IS DISTINCT FROM NEW.completed_at OR retained.removed_observation_count<>NEW.removed_observation_count THEN RAISE EXCEPTION 'Source retention completion requires exact expiry evidence' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER source_retention_progress BEFORE INSERT OR UPDATE OR DELETE ON source_retention_work FOR EACH ROW EXECUTE FUNCTION source_retention_work_guard();
"""


SOURCE_IMMUTABLE_GUARD = r"""
CREATE OR REPLACE FUNCTION source_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE permitted boolean; reference text; snapshot uuid;
BEGIN
 IF TG_OP = 'DELETE' AND TG_TABLE_NAME IN ('price_observations','fx_observations','benchmark_observations','corporate_action_observations','source_coverage_gaps') THEN
  IF TG_TABLE_NAME = 'source_coverage_gaps' THEN
   reference := CASE WHEN OLD.price_snapshot_id IS NOT NULL THEN 'price_snapshot_id' WHEN OLD.fx_snapshot_id IS NOT NULL THEN 'fx_snapshot_id' WHEN OLD.benchmark_snapshot_id IS NOT NULL THEN 'benchmark_snapshot_id' WHEN OLD.constituent_snapshot_id IS NOT NULL THEN 'constituent_snapshot_id' ELSE 'corporate_action_snapshot_id' END;
   snapshot := (to_jsonb(OLD)->>reference)::uuid;
  ELSE
   reference := replace(TG_TABLE_NAME,'observations','snapshot_id'); snapshot := OLD.snapshot_id;
  END IF;
  EXECUTE format('SELECT EXISTS(SELECT 1 FROM source_retention_work WHERE owner_id=$1 AND %I=$2 AND phase IN (''observations'',''coverage'',''complete''))',reference) INTO permitted USING OLD.owner_id,snapshot;
  IF permitted THEN RETURN OLD; END IF;
 END IF;
 RAISE EXCEPTION 'Immutable source content cannot be changed' USING ERRCODE='23514';
END $$;
"""


HISTORICAL_RETENTION_WRITE = r"""
CREATE OR REPLACE FUNCTION historical_retention_write(relation text, old_row jsonb, new_row jsonb)
RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE input uuid; permitted text[]; column_name text; snapshot uuid;
BEGIN
 permitted := CASE relation
 WHEN 'historical_input_snapshots' THEN ARRAY['canonical_input']
 WHEN 'analytics_runs' THEN ARRAY['canonical_input','canonical_result']
 WHEN 'performance_points' THEN ARRAY['canonical_row','portfolio_value','cash_value','wealth','period_return']
 WHEN 'performance_period_returns' THEN ARRAY['canonical_row','period_return']
 WHEN 'income_components' THEN ARRAY['canonical_row','net','gross','withholding']
 WHEN 'attribution_components' THEN ARRAY['canonical_row','gain','return_contribution']
 WHEN 'historical_cash_flow_points' THEN ARRAY['canonical_row','amount']
 WHEN 'historical_conversions' THEN ARRAY['rate']
 WHEN 'historical_composite_benchmarks' THEN ARRAY['canonical_composite']
 WHEN 'benchmark_composite_points' THEN ARRAY['canonical_point','wealth','interval_return']
 ELSE NULL END;
 IF permitted IS NULL OR old_row-permitted IS DISTINCT FROM new_row-permitted THEN RETURN false; END IF;
 FOREACH column_name IN ARRAY permitted LOOP
  IF column_name LIKE 'canonical_%' THEN
   IF new_row->>column_name IS DISTINCT FROM '\x' THEN RETURN false; END IF;
  ELSIF new_row->column_name IS DISTINCT FROM 'null'::jsonb THEN RETURN false;
  END IF;
 END LOOP;
 IF relation='historical_input_snapshots' THEN input:=(old_row->>'id')::uuid;
 ELSIF relation='analytics_runs' THEN SELECT input_id INTO input FROM historical_analytics_runs WHERE analytics_run_id=(old_row->>'id')::uuid AND owner_id=(old_row->>'owner_id')::uuid;
 ELSIF relation IN ('historical_composite_benchmarks','benchmark_composite_points') THEN
  SELECT r.input_id INTO input FROM historical_composite_benchmarks c JOIN historical_analytics_runs r ON r.id=c.run_id JOIN historical_retention_events e ON e.input_id=r.input_id
   WHERE c.snapshot_id=(old_row->>'snapshot_id')::uuid AND c.owner_id=(old_row->>'owner_id')::uuid LIMIT 1;
 ELSE SELECT input_id INTO input FROM historical_analytics_runs WHERE id=(old_row->>'run_id')::uuid AND owner_id=(old_row->>'owner_id')::uuid;
 END IF;
 IF relation='analytics_runs' AND EXISTS(SELECT 1 FROM historical_analytics_runs r WHERE r.analytics_run_id=(old_row->>'id')::uuid AND r.owner_id=(old_row->>'owner_id')::uuid AND (EXISTS(SELECT 1 FROM performance_points WHERE run_id=r.id AND (canonical_row <> '\x'::bytea OR portfolio_value IS NOT NULL OR cash_value IS NOT NULL OR wealth IS NOT NULL OR period_return IS NOT NULL)) OR EXISTS(SELECT 1 FROM performance_period_returns WHERE run_id=r.id AND (canonical_row <> '\x'::bytea OR period_return IS NOT NULL)) OR EXISTS(SELECT 1 FROM income_components WHERE run_id=r.id AND (canonical_row <> '\x'::bytea OR net IS NOT NULL OR gross IS NOT NULL OR withholding IS NOT NULL)) OR EXISTS(SELECT 1 FROM attribution_components WHERE run_id=r.id AND (canonical_row <> '\x'::bytea OR gain IS NOT NULL OR return_contribution IS NOT NULL)) OR EXISTS(SELECT 1 FROM historical_cash_flow_points WHERE run_id=r.id AND (canonical_row <> '\x'::bytea OR amount IS NOT NULL)) OR EXISTS(SELECT 1 FROM historical_conversions WHERE run_id=r.id AND (rate IS NOT NULL)) OR EXISTS(SELECT 1 FROM historical_composite_benchmarks WHERE run_id=r.id AND (canonical_composite <> '\x'::bytea)) OR EXISTS(SELECT 1 FROM benchmark_composite_points p JOIN historical_composite_benchmarks c ON c.snapshot_id=p.snapshot_id WHERE c.run_id=r.id AND (p.canonical_point <> '\x'::bytea OR p.wealth IS NOT NULL OR p.interval_return IS NOT NULL)))) THEN RETURN false; END IF;
 RETURN EXISTS(SELECT 1 FROM historical_retention_events WHERE input_id=input AND owner_id=(old_row->>'owner_id')::uuid);
END $$;
"""


SOURCE_EXPIRY_GUARD = r"""
CREATE OR REPLACE FUNCTION source_expiry_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE reference text; snapshot uuid; retained record; work record; pending boolean; observation_table text;
BEGIN
 reference := CASE WHEN NEW.price_snapshot_id IS NOT NULL THEN 'price_snapshot' WHEN NEW.fx_snapshot_id IS NOT NULL THEN 'fx_snapshot' WHEN NEW.benchmark_snapshot_id IS NOT NULL THEN 'benchmark_snapshot' WHEN NEW.constituent_snapshot_id IS NOT NULL THEN 'constituent_snapshot' ELSE 'corporate_action_snapshot' END;
 snapshot := (to_jsonb(NEW)->>(reference||'_id'))::uuid;
 EXECUTE format('SELECT expires_at,content_digest FROM %I WHERE id=$1 AND owner_id=$2',reference||'s') INTO retained USING snapshot,NEW.owner_id;
 IF retained.expires_at IS NULL OR retained.expires_at>NEW.removed_at OR retained.content_digest IS DISTINCT FROM NEW.content_digest THEN RAISE EXCEPTION 'Source retention authorization mismatch' USING ERRCODE='23514'; END IF;
 EXECUTE format('SELECT phase,started_at,removed_observation_count FROM source_retention_work WHERE owner_id=$1 AND %I=$2',reference||'_id') INTO work USING NEW.owner_id,snapshot;
 IF work.phase IS DISTINCT FROM 'coverage' OR work.started_at>NEW.removed_at OR work.removed_observation_count IS DISTINCT FROM NEW.removed_observation_count THEN RAISE EXCEPTION 'Source expiry requires completed pending phases' USING ERRCODE='23514'; END IF;
 observation_table:=CASE WHEN reference='constituent_snapshot' THEN 'constituent_holdings' ELSE replace(reference,'snapshot','observations') END;
 EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I WHERE owner_id=$1 AND snapshot_id=$2)',observation_table) INTO pending USING NEW.owner_id,snapshot;
 IF pending THEN RAISE EXCEPTION 'Source observation payload remains pending' USING ERRCODE='23514'; END IF;
 EXECUTE format('SELECT EXISTS(SELECT 1 FROM source_coverage_gaps WHERE owner_id=$1 AND %I=$2)',reference||'_id') INTO pending USING NEW.owner_id,snapshot;
 IF pending THEN RAISE EXCEPTION 'Source coverage payload remains pending' USING ERRCODE='23514'; END IF;
 IF reference<>'constituent_snapshot' THEN
 reference:=CASE reference WHEN 'corporate_action_snapshot' THEN 'action_snapshot_id' ELSE reference||'_id' END;
 EXECUTE format('SELECT EXISTS(SELECT 1 FROM historical_dependencies d JOIN historical_input_snapshots i ON i.id=d.input_id WHERE d.owner_id=$1 AND d.%I=$2 AND (i.canonical_input<>''\x''::bytea OR EXISTS(SELECT 1 FROM historical_analytics_runs r JOIN analytics_runs a ON a.id=r.analytics_run_id WHERE r.input_id=i.id AND (a.canonical_input<>''\x''::bytea OR a.canonical_result<>''\x''::bytea))))',reference) INTO pending USING NEW.owner_id,snapshot;
 IF pending THEN RAISE EXCEPTION 'Historical payload remains pending' USING ERRCODE='23514'; END IF;
 END IF;
 IF NEW.constituent_snapshot_id IS NOT NULL OR NEW.fx_snapshot_id IS NOT NULL THEN
  reference:=CASE WHEN NEW.constituent_snapshot_id IS NOT NULL THEN 'constituent_snapshot_id' ELSE 'fx_snapshot_id' END;
  EXECUTE format('SELECT EXISTS(SELECT 1 FROM xray_input_dependencies d JOIN xray_input_snapshots i ON i.id=d.input_id WHERE d.owner_id=$1 AND d.%I=$2 AND (i.canonical_input<>''\x''::bytea OR xray_payloads_pending(i.id)))',reference) INTO pending USING NEW.owner_id,snapshot;
  IF pending OR EXISTS(SELECT 1 FROM xray_collection_bindings WHERE constituent_snapshot_id=NEW.constituent_snapshot_id) THEN RAISE EXCEPTION 'X-ray payload remains pending' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
"""


OLD_SOURCE_IMMUTABLE_GUARD = r"""
CREATE OR REPLACE FUNCTION source_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE permitted boolean; reference text; snapshot uuid;
BEGIN
 IF TG_OP = 'DELETE' AND TG_TABLE_NAME IN ('price_observations','fx_observations','benchmark_observations','corporate_action_observations','source_coverage_gaps') THEN
  IF TG_TABLE_NAME = 'source_coverage_gaps' THEN
   reference := CASE WHEN OLD.price_snapshot_id IS NOT NULL THEN 'price_snapshot_id' WHEN OLD.fx_snapshot_id IS NOT NULL THEN 'fx_snapshot_id' WHEN OLD.benchmark_snapshot_id IS NOT NULL THEN 'benchmark_snapshot_id' ELSE 'corporate_action_snapshot_id' END;
   snapshot := (to_jsonb(OLD)->>reference)::uuid;
  ELSE
   reference := replace(TG_TABLE_NAME,'observations','snapshot_id'); snapshot := OLD.snapshot_id;
  END IF;
  EXECUTE format('SELECT EXISTS(SELECT 1 FROM source_expiry_events WHERE owner_id=$1 AND %I=$2)',reference) INTO permitted USING OLD.owner_id,snapshot;
  IF permitted THEN RETURN OLD; END IF;
 END IF;
 RAISE EXCEPTION 'Immutable source content cannot be changed' USING ERRCODE='23514';
END $$;
"""


OLD_SOURCE_EXPIRY_GUARD = r"""
CREATE OR REPLACE FUNCTION source_expiry_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE reference text; snapshot uuid; retained record;
BEGIN
 reference := CASE WHEN NEW.price_snapshot_id IS NOT NULL THEN 'price_snapshot' WHEN NEW.fx_snapshot_id IS NOT NULL THEN 'fx_snapshot' WHEN NEW.benchmark_snapshot_id IS NOT NULL THEN 'benchmark_snapshot' ELSE 'corporate_action_snapshot' END;
 snapshot := (to_jsonb(NEW)->>(reference||'_id'))::uuid;
 EXECUTE format('SELECT expires_at,content_digest FROM %I WHERE id=$1 AND owner_id=$2',reference||'s') INTO retained USING snapshot,NEW.owner_id;
 IF retained.expires_at IS NULL OR retained.expires_at > NEW.removed_at OR retained.content_digest IS DISTINCT FROM NEW.content_digest THEN
  RAISE EXCEPTION 'Source retention authorization mismatch' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
"""


OLD_HISTORICAL_RETENTION_WRITE = r"""
CREATE OR REPLACE FUNCTION historical_retention_write(relation text, old_row jsonb, new_row jsonb)
RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE input uuid; permitted text[]; column_name text; snapshot uuid;
BEGIN
 permitted := CASE relation
 WHEN 'historical_input_snapshots' THEN ARRAY['canonical_input']
 WHEN 'analytics_runs' THEN ARRAY['canonical_input','canonical_result']
 WHEN 'performance_points' THEN ARRAY['canonical_row','portfolio_value','cash_value','wealth','period_return']
 WHEN 'performance_period_returns' THEN ARRAY['canonical_row','period_return']
 WHEN 'income_components' THEN ARRAY['canonical_row','net','gross','withholding']
 WHEN 'attribution_components' THEN ARRAY['canonical_row','gain','return_contribution']
 WHEN 'historical_cash_flow_points' THEN ARRAY['canonical_row','amount']
 WHEN 'historical_conversions' THEN ARRAY['rate']
 WHEN 'historical_composite_benchmarks' THEN ARRAY['canonical_composite']
 WHEN 'benchmark_composite_points' THEN ARRAY['canonical_point','wealth','interval_return']
 ELSE NULL END;
 IF permitted IS NULL OR old_row-permitted IS DISTINCT FROM new_row-permitted THEN RETURN false; END IF;
 FOREACH column_name IN ARRAY permitted LOOP
  IF column_name LIKE 'canonical_%' THEN
   IF new_row->>column_name IS DISTINCT FROM '\x' THEN RETURN false; END IF;
  ELSIF new_row->column_name IS DISTINCT FROM 'null'::jsonb THEN RETURN false;
  END IF;
 END LOOP;
 IF relation='historical_input_snapshots' THEN input:=(old_row->>'id')::uuid;
 ELSIF relation='analytics_runs' THEN SELECT input_id INTO input FROM historical_analytics_runs WHERE analytics_run_id=(old_row->>'id')::uuid AND owner_id=(old_row->>'owner_id')::uuid;
 ELSIF relation IN ('historical_composite_benchmarks','benchmark_composite_points') THEN
  SELECT r.input_id INTO input FROM historical_composite_benchmarks c JOIN historical_analytics_runs r ON r.id=c.run_id JOIN historical_retention_events e ON e.input_id=r.input_id
   WHERE c.snapshot_id=(old_row->>'snapshot_id')::uuid AND c.owner_id=(old_row->>'owner_id')::uuid LIMIT 1;
 ELSE SELECT input_id INTO input FROM historical_analytics_runs WHERE id=(old_row->>'run_id')::uuid AND owner_id=(old_row->>'owner_id')::uuid;
 END IF;
 RETURN EXISTS(SELECT 1 FROM historical_retention_events WHERE input_id=input AND owner_id=(old_row->>'owner_id')::uuid);
END $$;
"""


def _shared_xray_schema() -> None:
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_resource_allowed"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_resource_allowed"),
        "collection_query_snapshots",
        "resource IN ('activity','dividends','instruments','positions_market_value','positions_weight','positions_ticker','portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','contribution_plans','plan_lines','actual_target_rows','plan_revisions','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings')",
    )
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_resource_sort_match"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_resource_sort_match"),
        "collection_query_snapshots",
        "(resource IN ('historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings') AND sort_specification = 'ordinal_asc') OR (resource = 'activity' AND sort_specification = 'occurred_at_desc_id_desc') OR (resource = 'dividends' AND sort_specification = 'paid_on_desc_id_desc') OR (resource = 'instruments' AND sort_specification = 'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR (resource = 'positions_market_value' AND sort_specification = 'market_value_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_weight' AND sort_specification = 'direct_weight_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_ticker' AND sort_specification = 'ticker_asc_listing_id_asc') OR (resource = 'portfolios_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'portfolios_updated' AND sort_specification = 'updated_at_desc_id_desc') OR (resource = 'target_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource = 'target_events' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'target_nodes' AND sort_specification = 'depth_first_order_key') OR (resource = 'plan_revisions' AND sort_specification = 'revision_number_desc_id_desc') OR (resource = 'contribution_plans' AND sort_specification = 'created_at_desc_id_desc') OR (resource IN ('plan_lines','actual_target_rows','plan_revisions') AND sort_specification = 'ordinal_asc') OR (resource = 'market_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'benchmark_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'fx_source_status' AND sort_specification = 'base_quote_provider_asc') OR (resource = 'price_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'fx_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_defs_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'benchmark_defs_created' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'benchmark_versions' AND sort_specification = 'version_number_desc_id_desc')",
    )
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_account_scope_match"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_account_scope_match"),
        "collection_query_snapshots",
        "((resource IN ('activity','dividends','positions_market_value','positions_weight','positions_ticker','contribution_plans','plan_lines','actual_target_rows','plan_revisions','historical_performance','historical_cash_flows','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities') AND broker_account_id IS NOT NULL) OR (resource = 'instruments' AND broker_account_id IS NULL) OR resource IN ('portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','composite_benchmark_points','constituent_holdings'))",
    )
    for table in (
        "source_retrieval_occurrences",
        "source_expiry_events",
        "source_coverage_gaps",
        "source_retention_work",
    ):
        op.add_column(table, sa.Column("constituent_snapshot_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_{table}_owner_id_constituent_snapshots"),
            table,
            "constituent_snapshots",
            ["owner_id", "constituent_snapshot_id"],
            ["owner_id", "id"],
            ondelete="RESTRICT",
        )
        op.drop_constraint(op.f(f"ck_{table}_snapshot_xor"), table, type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_snapshot_xor"),
            table,
            "num_nonnulls(price_snapshot_id,fx_snapshot_id,benchmark_snapshot_id,corporate_action_snapshot_id,constituent_snapshot_id)=1",
        )
    for table in ("source_expiry_events", "source_retention_work"):
        op.create_unique_constraint(
            op.f(f"uq_{table}_constituent_snapshot_id"), table, ["constituent_snapshot_id"]
        )
    op.add_column("analytics_run_sources", sa.Column("xray_input_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_analytics_run_sources_owner_id_xray_input_snapshots"),
        "analytics_run_sources",
        "xray_input_snapshots",
        ["owner_id", "xray_input_id"],
        ["owner_id", "id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        op.f("ck_analytics_run_sources_one_source"), "analytics_run_sources", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_analytics_run_sources_one_source"),
        "analytics_run_sources",
        "num_nonnulls(snapshot_id,target_version_id,source_record_id,historical_input_id,xray_input_id)=1",
    )
    op.drop_constraint(op.f("ck_analytics_runs_kind_allowed"), "analytics_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_analytics_runs_kind_allowed"),
        "analytics_runs",
        "kind IN ('actual_vs_target','drift','performance','benchmark','income','attribution','cash_flow','xray')",
    )


def _drop_shared_xray_schema() -> None:
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_resource_allowed"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_resource_allowed"),
        "collection_query_snapshots",
        "resource IN ('activity','dividends','instruments','positions_market_value','positions_weight','positions_ticker','portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','contribution_plans','plan_lines','actual_target_rows','plan_revisions','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','historical_performance','historical_cash_flows','composite_benchmark_points')",
    )
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_resource_sort_match"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_resource_sort_match"),
        "collection_query_snapshots",
        "(resource IN ('historical_performance','historical_cash_flows','composite_benchmark_points') AND sort_specification = 'ordinal_asc') OR (resource = 'activity' AND sort_specification = 'occurred_at_desc_id_desc') OR (resource = 'dividends' AND sort_specification = 'paid_on_desc_id_desc') OR (resource = 'instruments' AND sort_specification = 'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR (resource = 'positions_market_value' AND sort_specification = 'market_value_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_weight' AND sort_specification = 'direct_weight_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_ticker' AND sort_specification = 'ticker_asc_listing_id_asc') OR (resource = 'portfolios_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'portfolios_updated' AND sort_specification = 'updated_at_desc_id_desc') OR (resource = 'target_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource = 'target_events' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'target_nodes' AND sort_specification = 'depth_first_order_key') OR (resource = 'plan_revisions' AND sort_specification = 'revision_number_desc_id_desc') OR (resource = 'contribution_plans' AND sort_specification = 'created_at_desc_id_desc') OR (resource IN ('plan_lines','actual_target_rows','plan_revisions') AND sort_specification = 'ordinal_asc') OR (resource = 'market_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'benchmark_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'fx_source_status' AND sort_specification = 'base_quote_provider_asc') OR (resource = 'price_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'fx_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_defs_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'benchmark_defs_created' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'benchmark_versions' AND sort_specification = 'version_number_desc_id_desc')",
    )
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_account_scope_match"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_account_scope_match"),
        "collection_query_snapshots",
        "((resource IN ('activity','dividends','positions_market_value','positions_weight','positions_ticker','contribution_plans','plan_lines','actual_target_rows','plan_revisions','historical_performance','historical_cash_flows') AND broker_account_id IS NOT NULL) OR (resource = 'instruments' AND broker_account_id IS NULL) OR resource IN ('portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','composite_benchmark_points'))",
    )
    op.drop_constraint(
        op.f("fk_analytics_run_sources_owner_id_xray_input_snapshots"),
        "analytics_run_sources",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("ck_analytics_run_sources_one_source"), "analytics_run_sources", type_="check"
    )
    op.drop_column("analytics_run_sources", "xray_input_id")
    op.create_check_constraint(
        op.f("ck_analytics_run_sources_one_source"),
        "analytics_run_sources",
        "num_nonnulls(snapshot_id,target_version_id,source_record_id,historical_input_id)=1",
    )
    op.drop_constraint(op.f("ck_analytics_runs_kind_allowed"), "analytics_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_analytics_runs_kind_allowed"),
        "analytics_runs",
        "kind IN ('actual_vs_target','drift','performance','benchmark','income','attribution','cash_flow')",
    )
    for table in (
        "source_retrieval_occurrences",
        "source_expiry_events",
        "source_coverage_gaps",
        "source_retention_work",
    ):
        op.drop_constraint(op.f(f"ck_{table}_snapshot_xor"), table, type_="check")
        op.drop_constraint(
            op.f(f"fk_{table}_owner_id_constituent_snapshots"), table, type_="foreignkey"
        )
        if table in ("source_expiry_events", "source_retention_work"):
            op.drop_constraint(op.f(f"uq_{table}_constituent_snapshot_id"), table, type_="unique")
        op.drop_column(table, "constituent_snapshot_id")
        op.create_check_constraint(
            op.f(f"ck_{table}_snapshot_xor"),
            table,
            "num_nonnulls(price_snapshot_id,fx_snapshot_id,benchmark_snapshot_id,corporate_action_snapshot_id)=1",
        )


# Frozen catalog/enrichment DDL; no imports from mutable application/ORM modules.
COMMAND_KINDS = "'policy.register','entity.register','fund.register','fund_mapping.register','classification.ingest','constituent.ingest'"


def _xc_owned():
    return sa.UniqueConstraint("owner_id", "id")


def _xc_owner_fk(column, table):
    return sa.ForeignKeyConstraint(
        ["owner_id", column],
        [f"{table}.owner_id", f"{table}.id"],
        ondelete="RESTRICT",
        name=f"xray_{column}_{table}_fk",
    )


def _xc_licensed() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["owner_id", "provider_id", "license_version_id"],
        [
            "provider_license_versions.owner_id",
            "provider_license_versions.provider_id",
            "provider_license_versions.id",
        ],
        ondelete="RESTRICT",
    )


def _xc_evidence_constraints() -> tuple[object, ...]:
    return (
        _xc_owned(),
        _xc_licensed(),
        sa.CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        sa.CheckConstraint("expires_at > first_observed_at", name="retention_interval"),
        sa.CheckConstraint("valid_until IS NULL OR valid_until > effective_at", name="validity"),
        sa.CheckConstraint(
            "revision_order IS NULL OR revision_order >= 0", name="revision_nonnegative"
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_bound"
        ),
    )


def _xc_provider_snapshot_constraints(table: str) -> tuple[object, ...]:
    return (
        *_xc_evidence_constraints(),
        sa.UniqueConstraint("owner_id", "content_digest", name=f"uq_{table}_owner_content"),
        sa.CheckConstraint(
            "economic_digest ~ '^[0-9a-f]{64}$' AND request_digest ~ '^[0-9a-f]{64}$'",
            name="request_digest_format",
        ),
        sa.CheckConstraint("row_count BETWEEN 0 AND 100000", name="row_count_bound"),
    )


def _xc_enrichment_references() -> tuple[object, ...]:
    return (
        _xc_owned(),
        _xc_owner_fk("entity_evidence_version_id", "entity_evidence_versions"),
        _xc_owner_fk("classification_snapshot_id", "classification_snapshots"),
        _xc_owner_fk("fund_definition_id", "fund_definitions"),
        _xc_owner_fk("fund_mapping_id", "fund_source_mappings"),
        sa.CheckConstraint(
            "num_nonnulls(entity_evidence_version_id,classification_snapshot_id,"
            "fund_definition_id,fund_mapping_id) = 1",
            name="one_source",
        ),
    )


def _xc_payload_bound(column: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"octet_length({column}) <= 33554432", name=f"{column}_bound")


def _xc_coefficient_bound(column: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(
        f"{column} IS NULL OR {column} ~ '^(0|[1-9][0-9]{{0,249}})$'", name=f"{column}_exact"
    )


def _xc_run_payload_constraints() -> tuple[object, ...]:
    return (
        _xc_owned(),
        _xc_owner_fk("run_id", "xray_runs"),
        sa.UniqueConstraint("run_id", "ordinal"),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 99999", name="ordinal_bound"),
        _xc_payload_bound("canonical_payload"),
    )


def _xray_catalog_schema() -> None:
    op.create_table(
        "xray_taxonomies",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("version", sa.String(120), nullable=False),
        sa.Column("dimension", sa.String(20), nullable=False),
        _xc_owned(),
        sa.UniqueConstraint(
            "owner_id", "key", "version", name="uq_xray_taxonomies_owner_id_key_version"
        ),
        sa.CheckConstraint(
            "dimension IN ('sector','industry','country','region','currency')",
            name="dimension_allowed",
        ),
    )
    op.create_table(
        "xray_policy_versions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("broker_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("version", sa.String(120), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canonical_policy", sa.LargeBinary, nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        _xc_owned(),
        sa.UniqueConstraint(
            "owner_id",
            "account_id",
            "key",
            "version",
            name="uq_xray_policy_versions_owner_id_account_id_key_version",
        ),
        sa.CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        sa.CheckConstraint(
            "octet_length(canonical_policy) BETWEEN 1 AND 2097152", name="payload_bound"
        ),
    )
    op.create_index(
        "ix_xray_policy_selection",
        "xray_policy_versions",
        ["owner_id", "account_id", "effective_at", "first_observed_at", "id"],
    )
    op.create_table(
        "xray_policy_taxonomies",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("taxonomy_id", sa.Uuid(), nullable=False),
        _xc_owned(),
        _xc_owner_fk("policy_id", "xray_policy_versions"),
        _xc_owner_fk("taxonomy_id", "xray_taxonomies"),
        sa.UniqueConstraint(
            "policy_id", "taxonomy_id", name="uq_xray_policy_taxonomies_policy_id_taxonomy_id"
        ),
    )
    op.create_table(
        "entity_evidence_versions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("license_version_id", sa.Uuid(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision_order", sa.BigInteger, nullable=True),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=True),
        sa.Column("key", sa.String(120), nullable=False),
        *_xc_evidence_constraints(),
        sa.UniqueConstraint(
            "owner_id",
            "provider_id",
            "key",
            "revision_order",
            name="uq_entity_evidence_versions_owner_id_provider_id_key_r_4f7e99fd",
        ),
        sa.CheckConstraint(
            "revision_order IS NOT NULL AND revision_order >= 1", name="revision_required"
        ),
    )
    op.create_index("ix_entity_evidence_expiry", "entity_evidence_versions", ["expires_at", "id"])
    op.create_index(
        "ix_entity_evidence_selection",
        "entity_evidence_versions",
        ["owner_id", "effective_at", "first_observed_at", "id"],
    )
    op.create_table(
        "economic_entities",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("key", sa.String(120), nullable=False),
        _xc_owned(),
        sa.UniqueConstraint("owner_id", "key", name="uq_economic_entities_owner_id_key"),
    )
    op.create_table(
        "entity_evidence_references",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("evidence_version_id", sa.Uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("instruments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "listing_id",
            sa.Uuid(),
            sa.ForeignKey("listings.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("display_name", sa.String(300), nullable=True),
        sa.Column("lei", sa.String(20), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=True),
        _xc_owned(),
        _xc_owner_fk("evidence_version_id", "entity_evidence_versions"),
        _xc_owner_fk("entity_id", "economic_entities"),
        sa.UniqueConstraint(
            "evidence_version_id",
            "ordinal",
            name="uq_entity_evidence_references_evidence_version_id_ordinal",
        ),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 99999", name="ordinal_bound"),
        sa.CheckConstraint("kind IN ('entity','instrument_mapping')", name="kind_allowed"),
        sa.CheckConstraint(
            "(kind = 'entity' AND instrument_id IS NULL AND listing_id IS NULL) OR (kind = 'instrument_mapping' AND instrument_id IS NOT NULL)",
            name="subject_shape",
        ),
        sa.CheckConstraint("valid_until IS NULL OR valid_until > effective_at", name="validity"),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_bound"
        ),
    )
    op.create_index(
        "ix_entity_reference_parent", "entity_evidence_references", ["evidence_version_id", "id"]
    )
    op.create_index(
        "ix_entity_reference_subject",
        "entity_evidence_references",
        ["owner_id", "instrument_id", "listing_id", "id"],
    )
    op.create_table(
        "share_classes",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("evidence_version_id", sa.Uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("instruments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("class_key", sa.String(120), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=True),
        _xc_owned(),
        _xc_owner_fk("evidence_version_id", "entity_evidence_versions"),
        _xc_owner_fk("entity_id", "economic_entities"),
        sa.UniqueConstraint(
            "evidence_version_id",
            "instrument_id",
            "class_key",
            name="uq_share_classes_evidence_version_id_instrument_id_class_key",
        ),
        sa.CheckConstraint("valid_until IS NULL OR valid_until > effective_at", name="validity"),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_bound"
        ),
    )
    op.create_index("ix_share_class_parent", "share_classes", ["evidence_version_id", "id"])
    op.create_index("ix_share_class_subject", "share_classes", ["owner_id", "instrument_id", "id"])
    op.create_table(
        "instrument_entity_relationships",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("evidence_version_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("instruments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "listing_id",
            sa.Uuid(),
            sa.ForeignKey("listings.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("share_class_id", sa.Uuid(), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column(
            "underlying_instrument_id",
            sa.Uuid(),
            sa.ForeignKey("instruments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("parent_entity_id", sa.Uuid(), nullable=True),
        sa.Column("units_per_receipt", sa.Numeric(38, 18), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=True),
        _xc_owned(),
        _xc_owner_fk("evidence_version_id", "entity_evidence_versions"),
        _xc_owner_fk("entity_id", "economic_entities"),
        _xc_owner_fk("parent_entity_id", "economic_entities"),
        _xc_owner_fk("share_class_id", "share_classes"),
        sa.CheckConstraint(
            "kind IN ('listing_of','share_class_of','depositary_receipt_of','issuer_parent')",
            name="kind_allowed",
        ),
        sa.CheckConstraint(
            "(kind = 'listing_of' AND listing_id IS NOT NULL AND instrument_id IS NOT NULL AND share_class_id IS NULL AND entity_id IS NULL AND underlying_instrument_id IS NULL AND parent_entity_id IS NULL) OR (kind = 'share_class_of' AND instrument_id IS NOT NULL AND share_class_id IS NOT NULL AND entity_id IS NOT NULL AND listing_id IS NULL AND underlying_instrument_id IS NULL AND parent_entity_id IS NULL) OR (kind = 'depositary_receipt_of' AND instrument_id IS NOT NULL AND underlying_instrument_id IS NOT NULL AND entity_id IS NOT NULL AND instrument_id <> underlying_instrument_id AND listing_id IS NULL AND share_class_id IS NULL AND parent_entity_id IS NULL) OR (kind = 'issuer_parent' AND entity_id IS NOT NULL AND parent_entity_id IS NOT NULL AND entity_id <> parent_entity_id AND instrument_id IS NULL AND underlying_instrument_id IS NULL AND listing_id IS NULL AND share_class_id IS NULL)",
            name="endpoint_shape",
        ),
        sa.CheckConstraint(
            "units_per_receipt IS NULL OR (kind = 'depositary_receipt_of' AND units_per_receipt > 0)",
            name="receipt_ratio",
        ),
        sa.CheckConstraint("valid_until IS NULL OR valid_until > effective_at", name="validity"),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_bound"
        ),
    )
    op.create_index(
        "ix_entity_relationship_parent",
        "instrument_entity_relationships",
        ["evidence_version_id", "id"],
    )
    op.create_index(
        "ix_entity_relationship_subject",
        "instrument_entity_relationships",
        ["owner_id", "instrument_id", "id"],
    )
    op.create_table(
        "fund_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("license_version_id", sa.Uuid(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision_order", sa.BigInteger, nullable=True),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=True),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("instruments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("share_class_id", sa.Uuid(), nullable=True),
        sa.Column("fund_type", sa.String(120), nullable=True),
        sa.Column("evidence_key", sa.String(120), nullable=True),
        *_xc_evidence_constraints(),
        _xc_owner_fk("share_class_id", "share_classes"),
        sa.UniqueConstraint(
            "owner_id",
            "key",
            "revision_order",
            name="uq_fund_definitions_owner_id_key_revision_order",
        ),
        sa.CheckConstraint(
            "revision_order IS NOT NULL AND revision_order >= 1", name="revision_required"
        ),
    )
    op.create_index(
        "ix_fund_definition_subject",
        "fund_definitions",
        ["owner_id", "instrument_id", "effective_at", "id"],
    )
    op.create_index("ix_fund_definition_expiry", "fund_definitions", ["expires_at", "id"])
    op.create_table(
        "fund_source_mappings",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("license_version_id", sa.Uuid(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision_order", sa.BigInteger, nullable=True),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=True),
        sa.Column("fund_definition_id", sa.Uuid(), nullable=False),
        sa.Column("provider_fund_key", sa.String(120), nullable=True),
        sa.Column("evidence_key", sa.String(120), nullable=True),
        *_xc_evidence_constraints(),
        _xc_owner_fk("fund_definition_id", "fund_definitions"),
        sa.UniqueConstraint(
            "owner_id",
            "provider_id",
            "provider_fund_key",
            "revision_order",
            name="uq_fund_source_mappings_owner_id_provider_id_provider__21a67a0a",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "provider_id",
            "license_version_id",
            "id",
            name="uq_fund_source_mappings_owner_id_provider_id_license_v_bef58582",
        ),
        sa.CheckConstraint(
            "revision_order IS NOT NULL AND revision_order >= 1", name="revision_required"
        ),
    )
    op.create_index(
        "ix_fund_mapping_parent",
        "fund_source_mappings",
        ["fund_definition_id", "effective_at", "id"],
    )
    op.create_index("ix_fund_mapping_expiry", "fund_source_mappings", ["expires_at", "id"])
    op.create_table(
        "classification_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("license_version_id", sa.Uuid(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision_order", sa.BigInteger, nullable=True),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=True),
        sa.Column("adapter_version", sa.String(120), nullable=False),
        sa.Column("schema_version", sa.String(120), nullable=False),
        sa.Column("source_revision", sa.String(120), nullable=False),
        sa.Column("economic_digest", sa.String(64), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("synthetic", sa.Boolean, nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False),
        sa.Column("quality", sa.String(20), nullable=False),
        sa.Column("taxonomy_id", sa.Uuid(), nullable=False),
        *_xc_provider_snapshot_constraints("classification_snapshots"),
        _xc_owner_fk("taxonomy_id", "xray_taxonomies"),
    )
    op.create_index(
        "ix_classification_snapshot_selection",
        "classification_snapshots",
        ["owner_id", "taxonomy_id", "effective_at", "first_observed_at", "id"],
    )
    op.create_index(
        "ix_classification_snapshot_expiry", "classification_snapshots", ["expires_at", "id"]
    )
    op.create_table(
        "classification_snapshot_instruments",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("instruments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer, nullable=False),
        _xc_owned(),
        _xc_owner_fk("snapshot_id", "classification_snapshots"),
        sa.UniqueConstraint(
            "snapshot_id",
            "instrument_id",
            name="uq_classification_snapshot_instruments_snapshot_id_ins_fe7b5049",
        ),
        sa.UniqueConstraint(
            "snapshot_id",
            "ordinal",
            name="uq_classification_snapshot_instruments_snapshot_id_ordinal",
        ),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 99", name="ordinal_bound"),
    )
    op.create_index(
        "ix_classification_request_subject",
        "classification_snapshot_instruments",
        ["owner_id", "instrument_id", "snapshot_id"],
    )
    op.create_index(
        "ix_classification_instrument_parent",
        "classification_snapshot_instruments",
        ["snapshot_id", "id"],
    )
    op.create_table(
        "classification_assignments",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("instruments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("source_key", sa.String(120), nullable=False),
        sa.Column("dimension", sa.String(20), nullable=False),
        sa.Column("bucket_key", sa.String(120), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=True),
        sa.Column("evidence_key", sa.String(120), nullable=True),
        sa.Column("state", sa.String(20), nullable=False),
        _xc_owned(),
        _xc_owner_fk("snapshot_id", "classification_snapshots"),
        _xc_owner_fk("entity_id", "economic_entities"),
        sa.UniqueConstraint(
            "snapshot_id", "source_key", name="uq_classification_assignments_snapshot_id_source_key"
        ),
        sa.CheckConstraint(
            "dimension IN ('sector','industry','country','region','currency')",
            name="dimension_allowed",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_bound"
        ),
        sa.CheckConstraint("valid_until IS NULL OR valid_until > effective_at", name="validity"),
    )
    op.create_index(
        "ix_classification_assignment_parent", "classification_assignments", ["snapshot_id", "id"]
    )
    op.create_table(
        "classification_snapshot_assignments",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        _xc_owned(),
        _xc_owner_fk("snapshot_id", "classification_snapshots"),
        _xc_owner_fk("assignment_id", "classification_assignments"),
        sa.UniqueConstraint(
            "snapshot_id",
            "assignment_id",
            name="uq_classification_snapshot_assignments_snapshot_id_ass_feb45c51",
        ),
        sa.UniqueConstraint(
            "snapshot_id",
            "ordinal",
            name="uq_classification_snapshot_assignments_snapshot_id_ordinal",
        ),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 99999", name="ordinal_bound"),
    )
    op.create_index(
        "ix_classification_member_parent",
        "classification_snapshot_assignments",
        ["snapshot_id", "id"],
    )
    op.create_table(
        "constituent_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("license_version_id", sa.Uuid(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision_order", sa.BigInteger, nullable=True),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=True),
        sa.Column("adapter_version", sa.String(120), nullable=False),
        sa.Column("schema_version", sa.String(120), nullable=False),
        sa.Column("source_revision", sa.String(120), nullable=False),
        sa.Column("economic_digest", sa.String(64), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("synthetic", sa.Boolean, nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False),
        sa.Column("quality", sa.String(20), nullable=False),
        sa.Column("fund_mapping_id", sa.Uuid(), nullable=False),
        sa.Column("known_weight", sa.Numeric(38, 18), nullable=True),
        sa.Column("unresolved_weight", sa.Numeric(38, 18), nullable=True),
        sa.Column("cash_weight", sa.Numeric(38, 18), nullable=True),
        *_xc_provider_snapshot_constraints("constituent_snapshots"),
        _xc_owner_fk("fund_mapping_id", "fund_source_mappings"),
        sa.ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id", "fund_mapping_id"],
            [
                "fund_source_mappings.owner_id",
                "fund_source_mappings.provider_id",
                "fund_source_mappings.license_version_id",
                "fund_source_mappings.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "(known_weight IS NULL AND unresolved_weight IS NULL AND cash_weight IS NULL) OR (known_weight IS NOT NULL AND unresolved_weight IS NOT NULL AND cash_weight IS NOT NULL AND known_weight BETWEEN 0 AND 1 AND unresolved_weight BETWEEN 0 AND 1 AND cash_weight BETWEEN 0 AND 1 AND known_weight + unresolved_weight + cash_weight <= 1)",
            name="coverage_bound",
        ),
    )
    op.create_index(
        "ix_constituent_snapshot_selection",
        "constituent_snapshots",
        ["owner_id", "fund_mapping_id", "effective_at", "first_observed_at", "id"],
    )
    op.create_index("ix_constituent_snapshot_expiry", "constituent_snapshots", ["expires_at", "id"])
    op.create_table(
        "constituent_holdings",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("source_key", sa.String(120), nullable=False),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("instruments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("weight", sa.Numeric(38, 18), nullable=False),
        sa.Column("name", sa.String(300), nullable=True),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=True),
        sa.Column("evidence_key", sa.String(120), nullable=True),
        _xc_owned(),
        _xc_owner_fk("snapshot_id", "constituent_snapshots"),
        _xc_owner_fk("entity_id", "economic_entities"),
        sa.UniqueConstraint(
            "snapshot_id", "source_key", name="uq_constituent_holdings_snapshot_id_source_key"
        ),
        sa.UniqueConstraint(
            "snapshot_id", "ordinal", name="uq_constituent_holdings_snapshot_id_ordinal"
        ),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 99999", name="ordinal_bound"),
        sa.CheckConstraint("weight BETWEEN 0 AND 1", name="weight_bound"),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_bound"
        ),
        sa.CheckConstraint(
            "(state = 'resolved' AND (instrument_id IS NOT NULL OR entity_id IS NOT NULL)) OR (state IN ('cash','unresolved') AND instrument_id IS NULL AND entity_id IS NULL)",
            name="holding_shape",
        ),
    )
    op.create_index("ix_constituent_holding_parent", "constituent_holdings", ["snapshot_id", "id"])
    op.create_table(
        "xray_command_identities",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("result_id", sa.Uuid(), nullable=False),
        sa.Column("actor_principal_id", sa.String(120), nullable=False),
        sa.Column("correlation_id", sa.String(100), nullable=False),
        _xc_owned(),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_xray_command_identities_owner_id_idempotency_key",
        ),
        sa.CheckConstraint(f"kind IN ({COMMAND_KINDS})", name="kind_allowed"),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
    )
    op.create_table(
        "xray_audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("actor_principal_id", sa.String(120), nullable=False),
        sa.Column("correlation_id", sa.String(100), nullable=False),
        _xc_owned(),
        _xc_owner_fk("command_id", "xray_command_identities"),
        sa.UniqueConstraint("command_id", name="uq_xray_audit_events_command_id"),
        sa.CheckConstraint(f"kind IN ({COMMAND_KINDS})", name="kind_allowed"),
    )
    op.create_table(
        "enrichment_retrieval_occurrences",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("entity_evidence_version_id", sa.Uuid(), nullable=True),
        sa.Column("classification_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("fund_definition_id", sa.Uuid(), nullable=True),
        sa.Column("fund_mapping_id", sa.Uuid(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        *_xc_enrichment_references(),
    )
    op.create_index(
        "ix_enrichment_receipt_entity",
        "enrichment_retrieval_occurrences",
        ["entity_evidence_version_id", "retrieved_at", "id"],
    )
    op.create_index(
        "ix_enrichment_receipt_classification",
        "enrichment_retrieval_occurrences",
        ["classification_snapshot_id", "retrieved_at", "id"],
    )
    op.create_index(
        "ix_enrichment_receipt_definition",
        "enrichment_retrieval_occurrences",
        ["fund_definition_id", "retrieved_at", "id"],
    )
    op.create_index(
        "ix_enrichment_receipt_mapping",
        "enrichment_retrieval_occurrences",
        ["fund_mapping_id", "retrieved_at", "id"],
    )
    op.create_table(
        "enrichment_retention_work",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("entity_evidence_version_id", sa.Uuid(), nullable=True),
        sa.Column("classification_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("fund_definition_id", sa.Uuid(), nullable=True),
        sa.Column("fund_mapping_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("removed_row_count", sa.Integer, nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_xc_enrichment_references(),
        *(
            sa.UniqueConstraint(name)
            for name in (
                "entity_evidence_version_id",
                "classification_snapshot_id",
                "fund_definition_id",
                "fund_mapping_id",
            )
        ),
        sa.CheckConstraint("phase IN ('copies','payloads','complete')", name="phase_allowed"),
        sa.CheckConstraint(
            "(phase = 'complete') = (completed_at IS NOT NULL)", name="completion_shape"
        ),
        sa.CheckConstraint("removed_row_count BETWEEN 0 AND 1000000", name="removed_count_bound"),
        sa.CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
    )
    op.create_index(
        "ix_enrichment_retention_pending", "enrichment_retention_work", ["owner_id", "phase", "id"]
    )
    op.create_table(
        "enrichment_expiry_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("entity_evidence_version_id", sa.Uuid(), nullable=True),
        sa.Column("classification_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("fund_definition_id", sa.Uuid(), nullable=True),
        sa.Column("fund_mapping_id", sa.Uuid(), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("removed_row_count", sa.Integer, nullable=False),
        *_xc_enrichment_references(),
        *(
            sa.UniqueConstraint(name)
            for name in (
                "entity_evidence_version_id",
                "classification_snapshot_id",
                "fund_definition_id",
                "fund_mapping_id",
            )
        ),
        sa.CheckConstraint("removed_row_count BETWEEN 0 AND 1000000", name="removed_count_bound"),
        sa.CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
    )
    op.create_table(
        "xray_input_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("broker_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "valuation_run_id",
            sa.Uuid(),
            sa.ForeignKey("calculation_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "reconciliation_run_id",
            sa.Uuid(),
            sa.ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("reporting_currency", sa.String(3), nullable=False),
        sa.Column("valuation_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("canonical_input", sa.LargeBinary, nullable=False),
        _xc_owned(),
        _xc_owner_fk("policy_id", "xray_policy_versions"),
        sa.UniqueConstraint(
            "owner_id",
            "account_id",
            "input_digest",
            name="uq_xray_input_snapshots_owner_id_account_id_input_digest",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "account_id",
            "snapshot_id",
            "id",
            name="uq_xray_input_snapshots_owner_id_account_id_snapshot_id_id",
        ),
        sa.CheckConstraint("reporting_currency ~ '^[A-Z]{3}$'", name="currency_format"),
        sa.CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        sa.CheckConstraint("sealed_at IS NULL OR sealed_at >= captured_at", name="sealed_order"),
        _xc_payload_bound("canonical_input"),
    )
    op.create_index(
        "ix_xray_input_snapshot",
        "xray_input_snapshots",
        ["owner_id", "account_id", "snapshot_id", "id"],
    )
    op.create_index(
        "ix_xray_input_pending",
        "xray_input_snapshots",
        ["owner_id", "id"],
        postgresql_where=sa.text("canonical_input <> '\\x'::bytea"),
    )
    op.create_table(
        "xray_input_positions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column(
            "position_id",
            sa.Uuid(),
            sa.ForeignKey("snapshot_positions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("canonical_position", sa.LargeBinary, nullable=False),
        _xc_owned(),
        _xc_owner_fk("input_id", "xray_input_snapshots"),
        sa.UniqueConstraint(
            "input_id", "position_id", name="uq_xray_input_positions_input_id_position_id"
        ),
        sa.UniqueConstraint("input_id", "ordinal", name="uq_xray_input_positions_input_id_ordinal"),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 9999", name="ordinal_bound"),
        _xc_payload_bound("canonical_position"),
    )
    op.create_index("ix_xray_position_parent", "xray_input_positions", ["input_id", "id"])
    op.create_index(
        "ix_xray_input_positions_pending",
        "xray_input_positions",
        ["input_id", "id"],
        postgresql_where=sa.text("canonical_position <> '\\x'::bytea"),
    )
    op.create_table(
        "xray_input_cash",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column(
            "cash_id",
            sa.Uuid(),
            sa.ForeignKey("snapshot_cash.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("canonical_cash", sa.LargeBinary, nullable=False),
        _xc_owned(),
        _xc_owner_fk("input_id", "xray_input_snapshots"),
        sa.UniqueConstraint("input_id", "cash_id", name="uq_xray_input_cash_input_id_cash_id"),
        sa.UniqueConstraint("input_id", "ordinal", name="uq_xray_input_cash_input_id_ordinal"),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 31", name="ordinal_bound"),
        _xc_payload_bound("canonical_cash"),
    )
    op.create_index("ix_xray_cash_parent", "xray_input_cash", ["input_id", "id"])
    op.create_index(
        "ix_xray_input_cash_pending",
        "xray_input_cash",
        ["input_id", "id"],
        postgresql_where=sa.text("canonical_cash <> '\\x'::bytea"),
    )
    op.create_table(
        "xray_input_dependencies",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column("reference_id", sa.Uuid(), nullable=False),
        sa.Column(
            "valuation_run_id",
            sa.Uuid(),
            sa.ForeignKey("calculation_runs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "reconciliation_run_id",
            sa.Uuid(),
            sa.ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "broker_source_record_id",
            sa.Uuid(),
            sa.ForeignKey("source_records.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("threshold_policy_id", sa.Uuid(), nullable=True),
        sa.Column("fx_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("entity_evidence_version_id", sa.Uuid(), nullable=True),
        sa.Column("classification_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("fund_definition_id", sa.Uuid(), nullable=True),
        sa.Column("fund_mapping_id", sa.Uuid(), nullable=True),
        sa.Column("constituent_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("provider_id", sa.Uuid(), nullable=True),
        sa.Column("license_version_id", sa.Uuid(), nullable=True),
        sa.Column("canonical_reference", sa.LargeBinary, nullable=False),
        _xc_owned(),
        _xc_owner_fk("input_id", "xray_input_snapshots"),
        sa.UniqueConstraint(
            "input_id", "reference_id", name="uq_xray_input_dependencies_input_id_reference_id"
        ),
        _xc_owner_fk("fx_snapshot_id", "fx_snapshots"),
        _xc_owner_fk("entity_evidence_version_id", "entity_evidence_versions"),
        _xc_owner_fk("classification_snapshot_id", "classification_snapshots"),
        _xc_owner_fk("fund_definition_id", "fund_definitions"),
        _xc_owner_fk("fund_mapping_id", "fund_source_mappings"),
        _xc_owner_fk("constituent_snapshot_id", "constituent_snapshots"),
        _xc_owner_fk("threshold_policy_id", "xray_policy_versions"),
        sa.CheckConstraint(
            "num_nonnulls(valuation_run_id,reconciliation_run_id,broker_source_record_id,threshold_policy_id,fx_snapshot_id,entity_evidence_version_id,classification_snapshot_id,fund_definition_id,fund_mapping_id,constituent_snapshot_id)=1",
            name="one_source",
        ),
        sa.CheckConstraint(
            "(provider_id IS NULL) = (license_version_id IS NULL)", name="license_pair"
        ),
        sa.CheckConstraint(
            "(provider_id IS NULL) = (valuation_run_id IS NOT NULL OR reconciliation_run_id IS NOT NULL OR broker_source_record_id IS NOT NULL OR threshold_policy_id IS NOT NULL)",
            name="internal_license_shape",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id"],
            [
                "provider_license_versions.owner_id",
                "provider_license_versions.provider_id",
                "provider_license_versions.id",
            ],
            ondelete="RESTRICT",
        ),
        _xc_payload_bound("canonical_reference"),
    )
    op.create_index("ix_xray_dependency_parent", "xray_input_dependencies", ["input_id", "id"])
    op.create_index(
        "ix_xray_dependency_fx", "xray_input_dependencies", ["fx_snapshot_id", "input_id", "id"]
    )
    op.create_index(
        "ix_xray_dependency_entity",
        "xray_input_dependencies",
        ["entity_evidence_version_id", "input_id", "id"],
    )
    op.create_index(
        "ix_xray_dependency_classification",
        "xray_input_dependencies",
        ["classification_snapshot_id", "input_id", "id"],
    )
    op.create_index(
        "ix_xray_dependency_definition",
        "xray_input_dependencies",
        ["fund_definition_id", "input_id", "id"],
    )
    op.create_index(
        "ix_xray_dependency_mapping",
        "xray_input_dependencies",
        ["fund_mapping_id", "input_id", "id"],
    )
    op.create_index(
        "ix_xray_dependency_constituents",
        "xray_input_dependencies",
        ["constituent_snapshot_id", "input_id", "id"],
    )
    op.create_index(
        "ix_xray_input_dependencies_pending",
        "xray_input_dependencies",
        ["input_id", "id"],
        postgresql_where=sa.text("canonical_reference <> '\\x'::bytea"),
    )
    op.create_table(
        "xray_runs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column("analytics_run_id", sa.Uuid(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("canonical_summary", sa.LargeBinary, nullable=False),
        sa.Column("canonical_reconciliation", sa.LargeBinary, nullable=False),
        sa.Column("canonical_exact_state", sa.LargeBinary, nullable=False),
        _xc_owned(),
        _xc_owner_fk("input_id", "xray_input_snapshots"),
        _xc_owner_fk("analytics_run_id", "analytics_runs"),
        sa.UniqueConstraint("input_id", name="uq_xray_runs_input_id"),
        sa.UniqueConstraint("analytics_run_id", name="uq_xray_runs_analytics_run_id"),
        sa.CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        sa.CheckConstraint("sealed_at IS NULL OR sealed_at >= calculated_at", name="sealed_order"),
        _xc_payload_bound("canonical_summary"),
        _xc_payload_bound("canonical_reconciliation"),
        _xc_payload_bound("canonical_exact_state"),
    )
    op.create_index("ix_xray_run_parent", "xray_runs", ["input_id", "id"])
    op.create_table(
        "xray_input_source_selections",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(1024), nullable=False),
        sa.Column("canonical_selection", sa.LargeBinary, nullable=False),
        _xc_owned(),
        _xc_owner_fk("input_id", "xray_input_snapshots"),
        sa.UniqueConstraint("input_id", "key", name="uq_xray_input_source_selections_input_id_key"),
        _xc_payload_bound("canonical_selection"),
    )
    op.create_index("ix_xray_selection_parent", "xray_input_source_selections", ["input_id", "id"])
    op.create_index(
        "ix_xray_input_source_selections_pending",
        "xray_input_source_selections",
        ["input_id", "id"],
        postgresql_where=sa.text("canonical_selection <> '\\x'::bytea"),
    )
    op.create_table(
        "xray_selection_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("selection_id", sa.Uuid(), nullable=False),
        sa.Column("dependency_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("selected", sa.Boolean, nullable=False),
        _xc_owned(),
        _xc_owner_fk("selection_id", "xray_input_source_selections"),
        _xc_owner_fk("dependency_id", "xray_input_dependencies"),
        sa.UniqueConstraint(
            "selection_id",
            "evidence_id",
            name="uq_xray_selection_candidates_selection_id_evidence_id",
        ),
    )
    op.create_index(
        "ix_xray_selection_candidate_parent", "xray_selection_candidates", ["selection_id", "id"]
    )
    op.create_table(
        "xray_run_sources",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("dependency_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("canonical_use", sa.LargeBinary, nullable=False),
        _xc_owned(),
        _xc_owner_fk("run_id", "xray_runs"),
        _xc_owner_fk("dependency_id", "xray_input_dependencies"),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_xray_run_sources_run_id_ordinal"),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 99999", name="ordinal_bound"),
        _xc_payload_bound("canonical_use"),
    )
    op.create_index("ix_xray_run_source_parent", "xray_run_sources", ["run_id", "id"])
    op.create_index(
        "ix_xray_run_sources_pending",
        "xray_run_sources",
        ["run_id", "id"],
        postgresql_where=sa.text("canonical_use <> '\\x'::bytea"),
    )
    op.create_table(
        "xray_dimensions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("canonical_payload", sa.LargeBinary, nullable=False),
        sa.Column("dimension", sa.String(20), nullable=False),
        *_xc_run_payload_constraints(),
    )
    op.create_index("ix_xray_dimensions_parent", "xray_dimensions", ["run_id", "id"])
    op.create_index(
        "ix_xray_dimensions_pending",
        "xray_dimensions",
        ["run_id", "id"],
        postgresql_where=sa.text("canonical_payload <> '\\x'::bytea"),
    )
    op.create_table(
        "xray_warnings",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("canonical_payload", sa.LargeBinary, nullable=False),
        *_xc_run_payload_constraints(),
    )
    op.create_index("ix_xray_warnings_parent", "xray_warnings", ["run_id", "id"])
    op.create_index(
        "ix_xray_warnings_pending",
        "xray_warnings",
        ["run_id", "id"],
        postgresql_where=sa.text("canonical_payload <> '\\x'::bytea"),
    )
    op.create_table(
        "xray_residuals",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("canonical_payload", sa.LargeBinary, nullable=False),
        sa.Column("consumer_key", sa.String(2048), nullable=False),
        *_xc_run_payload_constraints(),
    )
    op.create_index("ix_xray_residuals_parent", "xray_residuals", ["run_id", "id"])
    op.create_index(
        "ix_xray_residuals_pending",
        "xray_residuals",
        ["run_id", "id"],
        postgresql_where=sa.text("canonical_payload <> '\\x'::bytea"),
    )
    op.create_table(
        "xray_classification_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("canonical_payload", sa.LargeBinary, nullable=False),
        sa.Column("key", sa.String(2048), nullable=False),
        *_xc_run_payload_constraints(),
    )
    op.create_index(
        "ix_xray_classification_decisions_parent", "xray_classification_decisions", ["run_id", "id"]
    )
    op.create_index(
        "ix_xray_classification_decisions_pending",
        "xray_classification_decisions",
        ["run_id", "id"],
        postgresql_where=sa.text("canonical_payload <> '\\x'::bytea"),
    )
    op.create_table(
        "xray_direct_positions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("canonical_payload", sa.LargeBinary, nullable=False),
        sa.Column(
            "position_id",
            sa.Uuid(),
            sa.ForeignKey("snapshot_positions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *_xc_run_payload_constraints(),
    )
    op.create_index("ix_xray_direct_positions_parent", "xray_direct_positions", ["run_id", "id"])
    op.create_index(
        "ix_xray_direct_positions_pending",
        "xray_direct_positions",
        ["run_id", "id"],
        postgresql_where=sa.text("canonical_payload <> '\\x'::bytea"),
    )
    op.create_table(
        "xray_held_funds",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("canonical_payload", sa.LargeBinary, nullable=False),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("instruments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *_xc_run_payload_constraints(),
    )
    op.create_index("ix_xray_held_funds_parent", "xray_held_funds", ["run_id", "id"])
    op.create_index(
        "ix_xray_held_funds_pending",
        "xray_held_funds",
        ["run_id", "id"],
        postgresql_where=sa.text("canonical_payload <> '\\x'::bytea"),
    )
    op.create_table(
        "xray_exposures",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("canonical_payload", sa.LargeBinary, nullable=False),
        sa.Column("dimension", sa.String(20), nullable=False),
        sa.Column("bucket_key", sa.String(120), nullable=True),
        *_xc_run_payload_constraints(),
        sa.UniqueConstraint(
            "run_id",
            "dimension",
            "bucket_key",
            name="uq_xray_exposures_run_id_dimension_bucket_key",
        ),
    )
    op.create_index(
        "ix_xray_exposure_page", "xray_exposures", ["run_id", "dimension", "ordinal", "id"]
    )
    op.create_index("ix_xray_exposure_parent", "xray_exposures", ["run_id", "id"])
    op.create_index(
        "ix_xray_exposures_pending",
        "xray_exposures",
        ["run_id", "id"],
        postgresql_where=sa.text("canonical_payload <> '\\x'::bytea"),
    )
    op.create_table(
        "xray_exposure_paths",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("canonical_payload", sa.LargeBinary, nullable=False),
        sa.Column("path_key", sa.String(2048), nullable=False),
        sa.Column("root_key", sa.String(45), nullable=False),
        sa.Column("identity_decision_ids", sa.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("source_reference_ids", sa.ARRAY(sa.Uuid()), nullable=False),
        *_xc_run_payload_constraints(),
        sa.UniqueConstraint("run_id", "path_key", name="uq_xray_exposure_paths_run_id_path_key"),
        sa.CheckConstraint(
            "cardinality(identity_decision_ids) <= 256 AND cardinality(source_reference_ids) <= 256",
            name="proof_bound",
        ),
        sa.CheckConstraint("root_key ~ '^(position|cash):[0-9a-f-]{36}$'", name="root_key_format"),
    )
    op.create_index("ix_xray_path_parent", "xray_exposure_paths", ["run_id", "id"])
    op.create_index(
        "ix_xray_exposure_paths_pending",
        "xray_exposure_paths",
        ["run_id", "id"],
        postgresql_where=sa.text("canonical_payload <> '\\x'::bytea"),
    )
    op.create_table(
        "xray_path_edges",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("path_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("fund_mapping_id", sa.Uuid(), nullable=False),
        sa.Column("constituent_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("holding_id", sa.Uuid(), nullable=True),
        sa.Column("canonical_edge", sa.LargeBinary, nullable=False),
        _xc_owned(),
        _xc_owner_fk("path_id", "xray_exposure_paths"),
        _xc_owner_fk("fund_mapping_id", "fund_source_mappings"),
        _xc_owner_fk("constituent_snapshot_id", "constituent_snapshots"),
        _xc_owner_fk("holding_id", "constituent_holdings"),
        sa.UniqueConstraint("path_id", "ordinal", name="uq_xray_path_edges_path_id_ordinal"),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 3", name="ordinal_bound"),
        _xc_payload_bound("canonical_edge"),
    )
    op.create_index("ix_xray_edge_parent", "xray_path_edges", ["path_id", "id"])
    op.create_index(
        "ix_xray_path_edges_pending",
        "xray_path_edges",
        ["path_id", "id"],
        postgresql_where=sa.text("canonical_edge <> '\\x'::bytea"),
    )
    op.create_table(
        "xray_exposure_path_buckets",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("path_id", sa.Uuid(), nullable=False),
        sa.Column("exposure_id", sa.Uuid(), nullable=False),
        sa.Column("dimension", sa.String(20), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        _xc_owned(),
        _xc_owner_fk("path_id", "xray_exposure_paths"),
        _xc_owner_fk("exposure_id", "xray_exposures"),
        sa.UniqueConstraint(
            "path_id", "dimension", name="uq_xray_exposure_path_buckets_path_id_dimension"
        ),
    )
    op.create_index("ix_xray_path_bucket_parent", "xray_exposure_path_buckets", ["path_id", "id"])
    op.create_index(
        "ix_xray_path_bucket_page", "xray_exposure_path_buckets", ["exposure_id", "ordinal", "id"]
    )
    op.create_table(
        "xray_fund_compositions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("canonical_payload", sa.LargeBinary, nullable=False),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("instruments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("composition_root_key", sa.String(45), nullable=False),
        sa.Column("position_count", sa.Integer, nullable=False),
        *_xc_run_payload_constraints(),
        sa.UniqueConstraint(
            "run_id", "instrument_id", name="uq_xray_fund_compositions_run_id_instrument_id"
        ),
        sa.CheckConstraint("position_count BETWEEN 1 AND 10000", name="position_count_bound"),
    )
    op.create_index("ix_xray_fund_parent", "xray_fund_compositions", ["run_id", "id"])
    op.create_index(
        "ix_xray_fund_compositions_pending",
        "xray_fund_compositions",
        ["run_id", "id"],
        postgresql_where=sa.text("canonical_payload <> '\\x'::bytea"),
    )
    op.create_table(
        "xray_fund_entities",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("composition_id", sa.Uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("relative_coefficient", sa.String(250), nullable=True),
        sa.Column("canonical_payload", sa.LargeBinary, nullable=False),
        _xc_owned(),
        _xc_owner_fk("composition_id", "xray_fund_compositions"),
        _xc_owner_fk("entity_id", "economic_entities"),
        sa.UniqueConstraint(
            "composition_id", "entity_id", name="uq_xray_fund_entities_composition_id_entity_id"
        ),
        sa.UniqueConstraint(
            "composition_id", "ordinal", name="uq_xray_fund_entities_composition_id_ordinal"
        ),
        _xc_coefficient_bound("relative_coefficient"),
        _xc_payload_bound("canonical_payload"),
    )
    op.create_index("ix_xray_fund_entity_parent", "xray_fund_entities", ["composition_id", "id"])
    op.create_index(
        "ix_xray_fund_entities_pending",
        "xray_fund_entities",
        ["composition_id", "id"],
        postgresql_where=sa.text("canonical_payload <> '\\x'::bytea"),
    )
    op.create_table(
        "xray_collection_bindings",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("constituent_snapshot_id", sa.Uuid(), nullable=True),
        _xc_owned(),
        _xc_owner_fk("collection_id", "collection_query_snapshots"),
        _xc_owner_fk("run_id", "xray_runs"),
        _xc_owner_fk("constituent_snapshot_id", "constituent_snapshots"),
        sa.UniqueConstraint("collection_id", name="uq_xray_collection_bindings_collection_id"),
        sa.CheckConstraint("num_nonnulls(run_id,constituent_snapshot_id)=1", name="one_parent"),
    )
    op.create_index("ix_xray_collection_run", "xray_collection_bindings", ["run_id", "id"])
    op.create_index(
        "ix_xray_collection_source", "xray_collection_bindings", ["constituent_snapshot_id", "id"]
    )
    op.create_table(
        "etf_overlap_pairs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("left_composition_id", sa.Uuid(), nullable=False),
        sa.Column("right_composition_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("canonical_payload", sa.LargeBinary, nullable=False),
        _xc_owned(),
        _xc_owner_fk("collection_id", "collection_query_snapshots"),
        _xc_owner_fk("run_id", "xray_runs"),
        _xc_owner_fk("left_composition_id", "xray_fund_compositions"),
        _xc_owner_fk("right_composition_id", "xray_fund_compositions"),
        sa.UniqueConstraint(
            "collection_id",
            "left_composition_id",
            "right_composition_id",
            name="uq_etf_overlap_pairs_collection_id_left_composition_id_c0d32d48",
        ),
        sa.UniqueConstraint(
            "collection_id", "ordinal", name="uq_etf_overlap_pairs_collection_id_ordinal"
        ),
        sa.CheckConstraint("left_composition_id <> right_composition_id", name="distinct_pair"),
        _xc_payload_bound("canonical_payload"),
    )
    op.create_index("ix_xray_pair_collection", "etf_overlap_pairs", ["collection_id", "id"])
    op.create_index("ix_xray_pair_run", "etf_overlap_pairs", ["run_id", "id"])
    op.create_table(
        "etf_overlap_entities",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("pair_id", sa.Uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("canonical_payload", sa.LargeBinary, nullable=False),
        _xc_owned(),
        _xc_owner_fk("collection_id", "collection_query_snapshots"),
        _xc_owner_fk("pair_id", "etf_overlap_pairs"),
        _xc_owner_fk("entity_id", "economic_entities"),
        sa.UniqueConstraint(
            "pair_id", "entity_id", name="uq_etf_overlap_entities_pair_id_entity_id"
        ),
        sa.UniqueConstraint("pair_id", "ordinal", name="uq_etf_overlap_entities_pair_id_ordinal"),
        _xc_payload_bound("canonical_payload"),
    )
    op.create_index("ix_xray_common_collection", "etf_overlap_entities", ["collection_id", "id"])
    op.create_index("ix_xray_common_parent", "etf_overlap_entities", ["pair_id", "id"])
    op.create_table(
        "xray_retention_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column("dependency_id", sa.Uuid(), nullable=False),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=False),
        _xc_owned(),
        _xc_owner_fk("input_id", "xray_input_snapshots"),
        _xc_owner_fk("dependency_id", "xray_input_dependencies"),
        sa.UniqueConstraint(
            "input_id", "dependency_id", name="uq_xray_retention_events_input_id_dependency_id"
        ),
    )
    op.create_index("ix_xray_retention_input", "xray_retention_events", ["input_id", "id"])


def _drop_xray_catalog() -> None:
    op.drop_table("xray_retention_events")
    op.drop_table("etf_overlap_entities")
    op.drop_table("etf_overlap_pairs")
    op.drop_table("xray_collection_bindings")
    op.drop_table("xray_fund_entities")
    op.drop_table("xray_fund_compositions")
    op.drop_table("xray_exposure_path_buckets")
    op.drop_table("xray_path_edges")
    op.drop_table("xray_exposure_paths")
    op.drop_table("xray_exposures")
    op.drop_table("xray_held_funds")
    op.drop_table("xray_direct_positions")
    op.drop_table("xray_classification_decisions")
    op.drop_table("xray_residuals")
    op.drop_table("xray_warnings")
    op.drop_table("xray_dimensions")
    op.drop_table("xray_run_sources")
    op.drop_table("xray_selection_candidates")
    op.drop_table("xray_input_source_selections")
    op.drop_table("xray_runs")
    op.drop_table("xray_input_dependencies")
    op.drop_table("xray_input_cash")
    op.drop_table("xray_input_positions")
    op.drop_table("xray_input_snapshots")
    op.drop_table("enrichment_expiry_events")
    op.drop_table("enrichment_retention_work")
    op.drop_table("enrichment_retrieval_occurrences")
    op.drop_table("xray_audit_events")
    op.drop_table("xray_command_identities")
    op.drop_table("constituent_holdings")
    op.drop_table("constituent_snapshots")
    op.drop_table("classification_snapshot_assignments")
    op.drop_table("classification_assignments")
    op.drop_table("classification_snapshot_instruments")
    op.drop_table("classification_snapshots")
    op.drop_table("fund_source_mappings")
    op.drop_table("fund_definitions")
    op.drop_table("instrument_entity_relationships")
    op.drop_table("share_classes")
    op.drop_table("entity_evidence_references")
    op.drop_table("economic_entities")
    op.drop_table("entity_evidence_versions")
    op.drop_table("xray_policy_taxonomies")
    op.drop_table("xray_policy_versions")
    op.drop_table("xray_taxonomies")


XRAY_SOURCE_COLUMNS = {
    "fx_snapshot_id": "fx_snapshots",
    "entity_evidence_version_id": "entity_evidence_versions",
    "classification_snapshot_id": "classification_snapshots",
    "fund_definition_id": "fund_definitions",
    "fund_mapping_id": "fund_source_mappings",
    "constituent_snapshot_id": "constituent_snapshots",
}
XRAY_COPY_PAYLOADS = {
    "xray_input_snapshots": ("canonical_input",),
    "xray_input_positions": ("canonical_position",),
    "xray_input_cash": ("canonical_cash",),
    "xray_input_dependencies": ("canonical_reference",),
    "xray_input_source_selections": ("canonical_selection",),
    "xray_run_sources": ("canonical_use",),
    "xray_runs": ("canonical_summary", "canonical_reconciliation", "canonical_exact_state"),
    "xray_dimensions": ("canonical_payload",),
    "xray_warnings": ("canonical_payload",),
    "xray_residuals": ("canonical_payload",),
    "xray_classification_decisions": ("canonical_payload",),
    "xray_direct_positions": ("canonical_payload",),
    "xray_held_funds": ("canonical_payload",),
    "xray_exposures": ("canonical_payload", "bucket_key"),
    "xray_exposure_paths": ("canonical_payload",),
    "xray_path_edges": ("canonical_edge",),
    "xray_fund_compositions": ("canonical_payload",),
    "xray_fund_entities": ("canonical_payload", "relative_coefficient"),
}
XRAY_SCOPE_TABLES = (
    "xray_policy_versions",
    "xray_input_snapshots",
    "xray_input_positions",
    "xray_input_cash",
    "xray_input_dependencies",
    "xray_runs",
    "xray_input_source_selections",
    "xray_selection_candidates",
    "xray_run_sources",
    "xray_dimensions",
    "xray_warnings",
    "xray_residuals",
    "xray_classification_decisions",
    "xray_direct_positions",
    "xray_held_funds",
    "xray_exposures",
    "xray_exposure_paths",
    "xray_path_edges",
    "xray_exposure_path_buckets",
    "xray_fund_compositions",
    "xray_fund_entities",
    "xray_collection_bindings",
    "etf_overlap_pairs",
    "etf_overlap_entities",
    "xray_retention_events",
)

XRAY_SCOPE_GUARD = r"""
CREATE FUNCTION xray_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b jsonb:=to_jsonb(NEW); i xray_input_snapshots; r xray_runs; a analytics_runs;
        parent uuid; target uuid; reference jsonb; okay boolean:=true;
BEGIN
 IF TG_TABLE_NAME='xray_policy_versions' THEN
  okay:=EXISTS(SELECT 1 FROM broker_accounts b JOIN broker_connections c ON c.id=b.connection_id
    WHERE b.id=NEW.account_id AND c.owner_id=NEW.owner_id);
 ELSIF TG_TABLE_NAME='xray_input_snapshots' THEN
  okay:=EXISTS(SELECT 1 FROM portfolio_snapshots s JOIN calculation_runs v ON v.id=s.calculation_run_id
   JOIN broker_accounts b ON b.id=s.broker_account_id JOIN broker_connections c ON c.id=b.connection_id
   JOIN xray_policy_versions p ON p.id=NEW.policy_id
   WHERE s.id=NEW.snapshot_id AND s.broker_account_id=NEW.account_id AND c.owner_id=NEW.owner_id
   AND v.id=NEW.valuation_run_id AND v.broker_account_id=NEW.account_id AND p.owner_id=NEW.owner_id
   AND p.account_id=NEW.account_id AND s.valuation_at=NEW.valuation_at
   AND p.effective_at<=s.valuation_at AND p.first_observed_at<=NEW.source_cutoff_at
   AND s.source_cutoff_at<=NEW.source_cutoff_at)
   AND (NEW.reconciliation_run_id IS NULL OR EXISTS(SELECT 1 FROM reconciliation_runs
    WHERE id=NEW.reconciliation_run_id AND broker_account_id=NEW.account_id));
 ELSE
  IF b->>'input_id' IS NOT NULL THEN SELECT * INTO i FROM xray_input_snapshots WHERE id=(b->>'input_id')::uuid;
  ELSIF b->>'run_id' IS NOT NULL THEN
   SELECT * INTO r FROM xray_runs WHERE id=(b->>'run_id')::uuid;
   SELECT * INTO i FROM xray_input_snapshots WHERE id=r.input_id;
  ELSIF b->>'path_id' IS NOT NULL THEN
   SELECT run_id INTO parent FROM xray_exposure_paths WHERE id=(b->>'path_id')::uuid;
   SELECT * INTO r FROM xray_runs WHERE id=parent; SELECT * INTO i FROM xray_input_snapshots WHERE id=r.input_id;
  ELSIF b->>'composition_id' IS NOT NULL THEN
   SELECT run_id INTO parent FROM xray_fund_compositions WHERE id=(b->>'composition_id')::uuid;
   SELECT * INTO r FROM xray_runs WHERE id=parent; SELECT * INTO i FROM xray_input_snapshots WHERE id=r.input_id;
  ELSIF b->>'selection_id' IS NOT NULL THEN
   SELECT input_id INTO parent FROM xray_input_source_selections WHERE id=(b->>'selection_id')::uuid;
   SELECT * INTO i FROM xray_input_snapshots WHERE id=parent;
  ELSIF b->>'pair_id' IS NOT NULL THEN
   SELECT run_id INTO parent FROM etf_overlap_pairs WHERE id=(b->>'pair_id')::uuid;
   SELECT * INTO r FROM xray_runs WHERE id=parent; SELECT * INTO i FROM xray_input_snapshots WHERE id=r.input_id;
  END IF;
  IF i.id IS NOT NULL AND i.owner_id IS DISTINCT FROM NEW.owner_id THEN okay:=false; END IF;
  IF TG_TABLE_NAME='xray_input_positions' THEN
   okay:=okay AND EXISTS(SELECT 1 FROM snapshot_positions p WHERE p.id=NEW.position_id AND p.snapshot_id=i.snapshot_id);
  ELSIF TG_TABLE_NAME='xray_input_cash' THEN
   okay:=okay AND EXISTS(SELECT 1 FROM snapshot_cash c WHERE c.id=NEW.cash_id AND c.snapshot_id=i.snapshot_id);
  ELSIF TG_TABLE_NAME='xray_input_dependencies' THEN
   IF NEW.valuation_run_id IS NOT NULL THEN okay:=okay AND NEW.valuation_run_id=i.valuation_run_id;
   ELSIF NEW.reconciliation_run_id IS NOT NULL THEN okay:=okay AND EXISTS(SELECT 1 FROM reconciliation_runs WHERE id=NEW.reconciliation_run_id AND broker_account_id=i.account_id);
   ELSIF NEW.broker_source_record_id IS NOT NULL THEN
    okay:=okay AND EXISTS(SELECT 1 FROM source_records s JOIN calculation_runs c ON c.id=i.valuation_run_id
      WHERE s.id=NEW.broker_source_record_id AND s.broker_account_id=i.account_id
      AND c.input_ids ? s.id::text AND s.observed_at<=i.source_cutoff_at);
   ELSIF NEW.threshold_policy_id IS NOT NULL THEN okay:=okay AND NEW.threshold_policy_id=i.policy_id;
   END IF;
   reference:=convert_from(NEW.canonical_reference,'UTF8')::jsonb->'value';
   okay:=okay AND reference->>'id'=NEW.reference_id::text AND reference->>'owner_id'=NEW.owner_id::text
     AND reference->>'account_id'=i.account_id::text AND reference->>'snapshot_id'=i.snapshot_id::text;
  ELSIF TG_TABLE_NAME='xray_runs' THEN
   SELECT * INTO a FROM analytics_runs WHERE id=NEW.analytics_run_id;
   okay:=okay AND a.owner_id=NEW.owner_id AND a.broker_account_id=i.account_id AND a.kind='xray'
     AND a.input_digest=i.input_digest AND a.content_digest=NEW.content_digest;
  ELSIF TG_TABLE_NAME IN ('xray_run_sources','xray_selection_candidates','xray_retention_events') THEN
   okay:=okay AND EXISTS(SELECT 1 FROM xray_input_dependencies d WHERE d.id=NEW.dependency_id
    AND d.owner_id=NEW.owner_id AND d.input_id=i.id);
  ELSIF TG_TABLE_NAME='xray_path_edges' THEN
   okay:=okay AND EXISTS(SELECT 1 FROM constituent_snapshots s WHERE s.id=NEW.constituent_snapshot_id
    AND s.owner_id=NEW.owner_id AND s.fund_mapping_id=NEW.fund_mapping_id)
    AND (NEW.holding_id IS NULL OR EXISTS(SELECT 1 FROM constituent_holdings h
      WHERE h.id=NEW.holding_id AND h.snapshot_id=NEW.constituent_snapshot_id AND h.owner_id=NEW.owner_id));
  ELSIF TG_TABLE_NAME='xray_exposure_path_buckets' THEN
   okay:=okay AND EXISTS(SELECT 1 FROM xray_exposures e WHERE e.id=NEW.exposure_id
     AND e.owner_id=NEW.owner_id AND e.run_id=r.id AND e.dimension=NEW.dimension);
  ELSIF TG_TABLE_NAME='xray_collection_bindings' THEN
   okay:=okay AND EXISTS(SELECT 1 FROM collection_query_snapshots c WHERE c.id=NEW.collection_id
     AND c.owner_id=NEW.owner_id AND ((NEW.run_id IS NOT NULL AND c.broker_account_id=i.account_id
     AND c.resource IN ('xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities'))
     OR (NEW.constituent_snapshot_id IS NOT NULL AND c.resource='constituent_holdings')));
  ELSIF TG_TABLE_NAME='etf_overlap_pairs' THEN
   okay:=okay AND EXISTS(SELECT 1 FROM xray_collection_bindings b WHERE b.collection_id=NEW.collection_id
      AND b.owner_id=NEW.owner_id AND b.run_id=NEW.run_id)
    AND EXISTS(SELECT 1 FROM xray_fund_compositions f WHERE f.id=NEW.left_composition_id AND f.run_id=NEW.run_id)
    AND EXISTS(SELECT 1 FROM xray_fund_compositions f WHERE f.id=NEW.right_composition_id AND f.run_id=NEW.run_id);
  ELSIF TG_TABLE_NAME='etf_overlap_entities' THEN
   okay:=okay AND EXISTS(SELECT 1 FROM etf_overlap_pairs p WHERE p.id=NEW.pair_id
     AND p.owner_id=NEW.owner_id AND p.collection_id=NEW.collection_id);
  END IF;
 END IF;
 IF okay IS DISTINCT FROM true THEN RAISE EXCEPTION 'X-ray scope or membership mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""

XRAY_IMMUTABLE_GUARD = r"""
CREATE FUNCTION xray_input_for_row(relation text,b jsonb) RETURNS uuid LANGUAGE plpgsql STABLE AS $$
DECLARE input uuid; run uuid;
BEGIN
 IF relation='xray_input_snapshots' THEN RETURN (b->>'id')::uuid;
 ELSIF relation='xray_runs' THEN RETURN (b->>'input_id')::uuid;
 ELSIF b->>'input_id' IS NOT NULL THEN RETURN (b->>'input_id')::uuid;
 ELSIF relation='analytics_runs' THEN SELECT input_id INTO input FROM xray_runs WHERE analytics_run_id=(b->>'id')::uuid; RETURN input;
 ELSIF b->>'run_id' IS NOT NULL THEN run:=(b->>'run_id')::uuid;
 ELSIF b->>'path_id' IS NOT NULL THEN SELECT run_id INTO run FROM xray_exposure_paths WHERE id=(b->>'path_id')::uuid;
 ELSIF b->>'composition_id' IS NOT NULL THEN SELECT run_id INTO run FROM xray_fund_compositions WHERE id=(b->>'composition_id')::uuid;
 ELSIF b->>'selection_id' IS NOT NULL THEN SELECT input_id INTO input FROM xray_input_source_selections WHERE id=(b->>'selection_id')::uuid; RETURN input;
 END IF;
 SELECT input_id INTO input FROM xray_runs WHERE id=run; RETURN input;
END $$;
CREATE FUNCTION xray_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b jsonb:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
        input uuid; parent_sealed boolean; columns text[]; column_name text;
BEGIN
 input:=xray_input_for_row(TG_TABLE_NAME,b);
 IF TG_OP='INSERT' THEN
  IF TG_TABLE_NAME='xray_runs' THEN RETURN NEW; END IF;
  SELECT sealed_at IS NOT NULL INTO parent_sealed FROM xray_input_snapshots WHERE id=input;
  IF parent_sealed THEN RAISE EXCEPTION 'Sealed X-ray input cannot receive children' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME IN ('xray_input_snapshots','xray_runs')
  AND (to_jsonb(OLD)->>'sealed_at') IS NULL AND (to_jsonb(NEW)->>'sealed_at') IS NOT NULL
  AND to_jsonb(OLD)-'sealed_at'=to_jsonb(NEW)-'sealed_at' THEN
  IF TG_TABLE_NAME='xray_input_snapshots' THEN
   IF encode(sha256(NEW.canonical_input),'hex')<>NEW.input_digest THEN
    RAISE EXCEPTION 'X-ray input digest mismatch' USING ERRCODE='23514'; END IF;
  ELSE
   IF NOT EXISTS(SELECT 1 FROM analytics_runs a WHERE a.id=NEW.analytics_run_id
     AND encode(sha256(a.canonical_result),'hex')=NEW.content_digest) THEN
    RAISE EXCEPTION 'X-ray result digest mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM xray_retention_events WHERE input_id=input AND owner_id=(b->>'owner_id')::uuid) THEN
  RAISE EXCEPTION 'Immutable X-ray content cannot be changed' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='xray_input_snapshots' AND xray_payloads_pending(input) THEN
  RAISE EXCEPTION 'X-ray copies remain pending' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' AND TG_TABLE_NAME='xray_path_edges' THEN RETURN OLD; END IF;
 IF TG_OP<>'UPDATE' THEN RAISE EXCEPTION 'X-ray tombstones must be retained' USING ERRCODE='23514'; END IF;
 columns:=string_to_array(TG_ARGV[0],',');
 IF to_jsonb(OLD)-columns IS DISTINCT FROM to_jsonb(NEW)-columns THEN
  RAISE EXCEPTION 'X-ray retention cannot change identity' USING ERRCODE='23514'; END IF;
 FOREACH column_name IN ARRAY columns LOOP
  IF column_name LIKE 'canonical_%' THEN
   IF b->>column_name IS DISTINCT FROM '\x' THEN RAISE EXCEPTION 'X-ray payload must be empty' USING ERRCODE='23514'; END IF;
  ELSIF b->column_name IS DISTINCT FROM 'null'::jsonb THEN
   RAISE EXCEPTION 'X-ray payload must be absent' USING ERRCODE='23514';
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
"""


XRAY_FINAL_GUARDS = r"""
CREATE FUNCTION xray_final_seal() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE sealed boolean; valid boolean;
BEGIN
 EXECUTE format('SELECT sealed_at IS NOT NULL FROM %I WHERE id=$1 AND owner_id=$2',TG_TABLE_NAME)
  INTO sealed USING NEW.id,NEW.owner_id;
 IF sealed IS DISTINCT FROM true THEN
  RAISE EXCEPTION 'X-ray publication is incomplete' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='xray_input_snapshots' THEN
  SELECT encode(sha256(canonical_input),'hex')=input_digest INTO valid
   FROM xray_input_snapshots WHERE id=NEW.id AND owner_id=NEW.owner_id;
 ELSE
  SELECT i.sealed_at IS NOT NULL AND encode(sha256(a.canonical_result),'hex')=r.content_digest
   INTO valid FROM xray_runs r JOIN xray_input_snapshots i ON i.id=r.input_id
   JOIN analytics_runs a ON a.id=r.analytics_run_id WHERE r.id=NEW.id AND r.owner_id=NEW.owner_id;
 END IF;
 IF valid IS DISTINCT FROM true THEN
  RAISE EXCEPTION 'X-ray publication digest or parent seal mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION xray_registration_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE sealed boolean;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'X-ray registration is immutable' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='xray_policy_taxonomies' THEN
  SELECT pg_xact_status(xmin::text::xid8)='committed' INTO sealed FROM xray_policy_versions
   WHERE id=NEW.policy_id AND owner_id=NEW.owner_id;
  IF sealed IS DISTINCT FROM false THEN
   RAISE EXCEPTION 'X-ray policy taxonomy membership is sealed' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
"""

XRAY_REGISTRATION_TABLES = (
    "xray_taxonomies",
    "xray_policy_versions",
    "xray_policy_taxonomies",
    "economic_entities",
    "xray_command_identities",
    "xray_audit_events",
    "enrichment_retrieval_occurrences",
)


def _xray_guards() -> None:
    op.execute(XRAY_SCOPE_GUARD)
    op.execute(XRAY_IMMUTABLE_GUARD)
    op.execute(XRAY_FINAL_GUARDS)
    for table in ("xray_input_snapshots", "xray_runs"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER xray_final AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION xray_final_seal()"
        )
    for table in XRAY_REGISTRATION_TABLES:
        op.execute(
            f"CREATE TRIGGER xray_registration_immutable BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION xray_registration_guard()"
        )
    for table in XRAY_SCOPE_TABLES:
        op.execute(
            f"CREATE TRIGGER xray_scope BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION xray_scope_guard()"
        )
    for table, columns in {
        **XRAY_COPY_PAYLOADS,
        "xray_selection_candidates": (),
        "xray_exposure_path_buckets": (),
    }.items():
        op.execute(
            f"CREATE TRIGGER xray_immutable BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION xray_immutable_guard('{','.join(columns)}')"
        )


def _drop_xray_guards() -> None:
    for table in ("xray_input_snapshots", "xray_runs"):
        op.execute(f"DROP TRIGGER xray_final ON {table}")
    for table in XRAY_REGISTRATION_TABLES:
        op.execute(f"DROP TRIGGER xray_registration_immutable ON {table}")
    op.execute("DROP FUNCTION xray_final_seal()")
    op.execute("DROP FUNCTION xray_registration_guard()")
    for table in XRAY_SCOPE_TABLES:
        op.execute(f"DROP TRIGGER xray_scope ON {table}")
    for table in (*XRAY_COPY_PAYLOADS, "xray_selection_candidates", "xray_exposure_path_buckets"):
        op.execute(f"DROP TRIGGER xray_immutable ON {table}")
    op.execute("DROP FUNCTION xray_scope_guard()")
    op.execute("DROP FUNCTION xray_immutable_guard()")
    op.execute("DROP FUNCTION xray_input_for_row(text,jsonb)")


XRAY_RETENTION_GUARDS = r"""
CREATE FUNCTION xray_retention_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE dependency xray_input_dependencies; reference text; source uuid; expiry timestamptz;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'X-ray retention evidence is immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO dependency FROM xray_input_dependencies WHERE id=NEW.dependency_id AND owner_id=NEW.owner_id;
 IF dependency.input_id IS DISTINCT FROM NEW.input_id THEN RAISE EXCEPTION 'X-ray retention input mismatch' USING ERRCODE='23514'; END IF;
 FOREACH reference IN ARRAY ARRAY['fx_snapshot_id','entity_evidence_version_id','classification_snapshot_id','fund_definition_id','fund_mapping_id','constituent_snapshot_id'] LOOP
  source:=(to_jsonb(dependency)->>reference)::uuid;
  IF source IS NOT NULL THEN
   EXECUTE format('SELECT expires_at FROM %I WHERE id=$1 AND owner_id=$2',CASE reference
     WHEN 'fund_mapping_id' THEN 'fund_source_mappings' ELSE replace(reference,'_id','')||'s' END)
    INTO expiry USING source,NEW.owner_id;
  END IF;
 END LOOP;
 IF expiry IS NULL OR expiry>NEW.expired_at THEN RAISE EXCEPTION 'X-ray retention requires expired exact source' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION xray_collection_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b jsonb:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
        collection uuid; binding xray_collection_bindings; expires timestamptz; permitted boolean:=false;
BEGIN
 collection:=CASE WHEN TG_TABLE_NAME='collection_query_snapshots' THEN (b->>'id')::uuid
   WHEN TG_TABLE_NAME='collection_query_snapshot_members' THEN (b->>'snapshot_id')::uuid ELSE (b->>'collection_id')::uuid END;
 SELECT * INTO binding FROM xray_collection_bindings WHERE collection_id=collection;
 IF TG_TABLE_NAME='collection_query_snapshots' AND TG_OP='UPDATE' THEN
  SELECT pg_xact_status(xmin::text::xid8)='committed' INTO permitted FROM collection_query_snapshots WHERE id=collection;
  IF NOT permitted AND to_jsonb(OLD)-'exact_total'=to_jsonb(NEW)-'exact_total'
   AND (b->>'exact_total')::bigint=(SELECT count(*) FROM collection_query_snapshot_members WHERE snapshot_id=collection) THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='INSERT' THEN
  IF TG_TABLE_NAME='xray_collection_bindings' THEN RETURN NEW; END IF;
  SELECT pg_xact_status(xmin::text::xid8)='committed' INTO permitted FROM collection_query_snapshots WHERE id=collection;
  IF permitted THEN RAISE EXCEPTION 'Sealed X-ray collection cannot receive rows' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF binding.id IS NULL AND TG_TABLE_NAME IN ('collection_query_snapshots','collection_query_snapshot_members') THEN
  RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
 END IF;
 SELECT expires_at INTO expires FROM collection_query_snapshots WHERE id=collection;
 permitted:=expires<=CURRENT_TIMESTAMP;
 IF binding.run_id IS NOT NULL THEN
  permitted:=permitted OR EXISTS(SELECT 1 FROM xray_runs r JOIN xray_retention_events e ON e.input_id=r.input_id
    WHERE r.id=binding.run_id AND e.owner_id=binding.owner_id);
 ELSIF binding.constituent_snapshot_id IS NOT NULL THEN
  permitted:=permitted OR EXISTS(SELECT 1 FROM constituent_snapshots s WHERE s.id=binding.constituent_snapshot_id
    AND s.owner_id=binding.owner_id AND s.expires_at<=CURRENT_TIMESTAMP);
 END IF;
 IF TG_OP='DELETE' AND permitted THEN RETURN OLD; END IF;
 RAISE EXCEPTION 'Immutable X-ray collection cannot be changed' USING ERRCODE='23514';
END $$;
CREATE FUNCTION xray_catalog_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b jsonb:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
        reference text:=TG_ARGV[0]; parent_table text:=TG_ARGV[1]; parent_field text:=TG_ARGV[2];
        columns text[]:=string_to_array(TG_ARGV[3],','); source uuid; parent jsonb; sealed boolean; permitted boolean; column_name text;
BEGIN
 source:=(b->>parent_field)::uuid;
 EXECUTE format('SELECT to_jsonb(p), pg_xact_status(xmin::text::xid8)=''committed'' FROM %I p WHERE id=$1 AND owner_id=$2',parent_table)
  INTO parent,sealed USING source,(b->>'owner_id')::uuid;
 IF TG_OP='INSERT' THEN
  IF TG_TABLE_NAME<>parent_table AND (parent IS NULL OR sealed) THEN RAISE EXCEPTION 'Licensed X-ray source is sealed' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF reference='constituent_snapshot_id' THEN
  SELECT EXISTS(SELECT 1 FROM source_retention_work WHERE constituent_snapshot_id=source AND owner_id=(b->>'owner_id')::uuid
   AND phase IN ('observations','coverage')) INTO permitted;
 ELSE
  EXECUTE format('SELECT EXISTS(SELECT 1 FROM enrichment_retention_work WHERE %I=$1 AND owner_id=$2 AND phase=''payloads'')',reference)
   INTO permitted USING source,(b->>'owner_id')::uuid;
 END IF;
 IF NOT permitted THEN RAISE EXCEPTION 'Immutable licensed X-ray evidence' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' AND TG_TABLE_NAME IN ('constituent_holdings','classification_snapshot_assignments','classification_assignments','classification_snapshot_instruments') THEN RETURN OLD; END IF;
 IF TG_OP<>'UPDATE' OR to_jsonb(OLD)-columns IS DISTINCT FROM to_jsonb(NEW)-columns THEN
  RAISE EXCEPTION 'Licensed X-ray retention cannot change identity' USING ERRCODE='23514'; END IF;
 FOREACH column_name IN ARRAY columns LOOP
  IF b->column_name IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'Licensed X-ray payload must be absent' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE FUNCTION enrichment_retention_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b jsonb:=to_jsonb(NEW); reference text; source uuid; retained record; work record; old_rank integer; new_rank integer; pending boolean;
BEGIN
 IF TG_OP='DELETE' OR (TG_TABLE_NAME='enrichment_expiry_events' AND TG_OP<>'INSERT') THEN
  RAISE EXCEPTION 'Enrichment retention evidence must be retained' USING ERRCODE='23514'; END IF;
 FOREACH reference IN ARRAY ARRAY['entity_evidence_version_id','classification_snapshot_id','fund_definition_id','fund_mapping_id'] LOOP
  source:=(b->>reference)::uuid; EXIT WHEN source IS NOT NULL;
 END LOOP;
 EXECUTE format('SELECT expires_at,content_digest FROM %I WHERE id=$1 AND owner_id=$2',CASE reference WHEN 'fund_mapping_id' THEN 'fund_source_mappings' ELSE replace(reference,'_id','')||'s' END)
  INTO retained USING source,NEW.owner_id;
 IF retained.expires_at IS NULL OR retained.expires_at>COALESCE((b->>'started_at')::timestamptz,(b->>'expired_at')::timestamptz)
  OR retained.content_digest IS DISTINCT FROM NEW.content_digest THEN
  RAISE EXCEPTION 'Enrichment retention authorization mismatch' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='enrichment_retention_work' THEN
  IF TG_OP='INSERT' AND (NEW.phase<>'copies' OR NEW.removed_row_count<>0 OR NEW.completed_at IS NOT NULL) THEN
   RAISE EXCEPTION 'Enrichment expiry must start pending' USING ERRCODE='23514'; END IF;
  IF TG_OP='UPDATE' THEN
   old_rank:=array_position(ARRAY['copies','payloads','complete'],OLD.phase);
   new_rank:=array_position(ARRAY['copies','payloads','complete'],NEW.phase);
   IF to_jsonb(OLD)-ARRAY['phase','removed_row_count','completed_at'] IS DISTINCT FROM to_jsonb(NEW)-ARRAY['phase','removed_row_count','completed_at']
    OR OLD.phase='complete' OR new_rank<old_rank OR new_rank>old_rank+1 OR NEW.removed_row_count<OLD.removed_row_count THEN
    RAISE EXCEPTION 'Enrichment retention progress must be monotonic' USING ERRCODE='23514'; END IF;
   IF NEW.phase='payloads' AND OLD.phase='copies' THEN
    EXECUTE format('SELECT EXISTS(SELECT 1 FROM xray_input_dependencies d JOIN xray_input_snapshots i ON i.id=d.input_id WHERE d.owner_id=$1 AND d.%I=$2 AND (i.canonical_input<>''\x''::bytea OR xray_payloads_pending(i.id)))',reference)
     INTO pending USING NEW.owner_id,source;
    IF pending THEN RAISE EXCEPTION 'Enrichment X-ray copies remain pending' USING ERRCODE='23514'; END IF;
   END IF;
   IF NEW.phase='complete' THEN
    EXECUTE format('SELECT expired_at,removed_row_count FROM enrichment_expiry_events WHERE owner_id=$1 AND %I=$2',reference)
     INTO work USING NEW.owner_id,source;
    IF work.expired_at IS DISTINCT FROM NEW.completed_at OR work.removed_row_count IS DISTINCT FROM NEW.removed_row_count THEN
     RAISE EXCEPTION 'Enrichment completion requires expiry evidence' USING ERRCODE='23514'; END IF;
   END IF;
  END IF;
 ELSE
  EXECUTE format('SELECT phase,removed_row_count FROM enrichment_retention_work WHERE owner_id=$1 AND %I=$2',reference)
   INTO work USING NEW.owner_id,source;
  IF work.phase IS DISTINCT FROM 'payloads' OR work.removed_row_count IS DISTINCT FROM NEW.removed_row_count THEN
   RAISE EXCEPTION 'Enrichment expiry phases remain pending' USING ERRCODE='23514'; END IF;
  EXECUTE format('SELECT EXISTS(SELECT 1 FROM xray_input_dependencies d JOIN xray_input_snapshots i ON i.id=d.input_id WHERE d.owner_id=$1 AND d.%I=$2 AND (i.canonical_input<>''\x''::bytea OR xray_payloads_pending(i.id)))',reference)
   INTO pending USING NEW.owner_id,source;
  IF pending THEN RAISE EXCEPTION 'Enrichment X-ray copies remain pending' USING ERRCODE='23514'; END IF;
  CASE reference
   WHEN 'entity_evidence_version_id' THEN
    pending:=EXISTS(SELECT 1 FROM entity_evidence_versions WHERE id=source AND confidence IS NOT NULL)
     OR EXISTS(SELECT 1 FROM entity_evidence_references WHERE evidence_version_id=source AND (display_name IS NOT NULL OR lei IS NOT NULL OR confidence IS NOT NULL))
     OR EXISTS(SELECT 1 FROM instrument_entity_relationships WHERE evidence_version_id=source AND (units_per_receipt IS NOT NULL OR confidence IS NOT NULL))
     OR EXISTS(SELECT 1 FROM share_classes WHERE evidence_version_id=source AND (class_key IS NOT NULL OR confidence IS NOT NULL));
   WHEN 'classification_snapshot_id' THEN
    pending:=EXISTS(SELECT 1 FROM classification_snapshots WHERE id=source AND confidence IS NOT NULL)
     OR EXISTS(SELECT 1 FROM classification_snapshot_assignments WHERE snapshot_id=source)
     OR EXISTS(SELECT 1 FROM classification_assignments WHERE snapshot_id=source)
     OR EXISTS(SELECT 1 FROM classification_snapshot_instruments WHERE snapshot_id=source);
   WHEN 'fund_definition_id' THEN
    pending:=EXISTS(SELECT 1 FROM fund_definitions WHERE id=source AND (fund_type IS NOT NULL OR evidence_key IS NOT NULL OR confidence IS NOT NULL));
   WHEN 'fund_mapping_id' THEN
    pending:=EXISTS(SELECT 1 FROM fund_source_mappings WHERE id=source AND (provider_fund_key IS NOT NULL OR evidence_key IS NOT NULL OR confidence IS NOT NULL));
   ELSE pending:=true;
  END CASE;
  IF pending THEN RAISE EXCEPTION 'Enrichment licensed payloads remain pending' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
"""

XRAY_CATALOG_GUARDS = (
    (
        "entity_evidence_versions",
        "entity_evidence_version_id",
        "entity_evidence_versions",
        "id",
        "confidence",
    ),
    (
        "entity_evidence_references",
        "entity_evidence_version_id",
        "entity_evidence_versions",
        "evidence_version_id",
        "display_name,lei,confidence",
    ),
    (
        "instrument_entity_relationships",
        "entity_evidence_version_id",
        "entity_evidence_versions",
        "evidence_version_id",
        "units_per_receipt,confidence",
    ),
    (
        "share_classes",
        "entity_evidence_version_id",
        "entity_evidence_versions",
        "evidence_version_id",
        "class_key,confidence",
    ),
    (
        "fund_definitions",
        "fund_definition_id",
        "fund_definitions",
        "id",
        "fund_type,evidence_key,confidence",
    ),
    (
        "fund_source_mappings",
        "fund_mapping_id",
        "fund_source_mappings",
        "id",
        "provider_fund_key,evidence_key,confidence",
    ),
    (
        "classification_snapshots",
        "classification_snapshot_id",
        "classification_snapshots",
        "id",
        "confidence",
    ),
    (
        "classification_snapshot_assignments",
        "classification_snapshot_id",
        "classification_snapshots",
        "snapshot_id",
        "assignment_id,ordinal",
    ),
    (
        "classification_snapshot_instruments",
        "classification_snapshot_id",
        "classification_snapshots",
        "snapshot_id",
        "instrument_id,ordinal",
    ),
    (
        "classification_assignments",
        "classification_snapshot_id",
        "classification_snapshots",
        "snapshot_id",
        "bucket_key,confidence,evidence_key",
    ),
    (
        "constituent_snapshots",
        "constituent_snapshot_id",
        "constituent_snapshots",
        "id",
        "known_weight,unresolved_weight,cash_weight,confidence",
    ),
    (
        "constituent_holdings",
        "constituent_snapshot_id",
        "constituent_snapshots",
        "snapshot_id",
        "weight,name,confidence,evidence_key",
    ),
)


def _xray_retention_guards() -> None:
    terms = []
    for table, columns in XRAY_COPY_PAYLOADS.items():
        if table == "xray_input_snapshots":
            continue
        remaining = " OR ".join(
            f"p.{column}<> '\\x'::bytea"
            if column.startswith("canonical_")
            else f"p.{column} IS NOT NULL"
            for column in columns
        )
        if table.startswith("xray_input_") or table == "xray_runs":
            parent = "p.input_id=input"
        elif table == "xray_path_edges":
            parent = "p.path_id IN (SELECT t.id FROM xray_exposure_paths t JOIN xray_runs r ON r.id=t.run_id WHERE r.input_id=input)"
        elif table == "xray_fund_entities":
            parent = "p.composition_id IN (SELECT c.id FROM xray_fund_compositions c JOIN xray_runs r ON r.id=c.run_id WHERE r.input_id=input)"
        else:
            parent = "p.run_id IN (SELECT r.id FROM xray_runs r WHERE r.input_id=input)"
        terms.append(f"EXISTS(SELECT 1 FROM {table} p WHERE {parent} AND ({remaining}))")  # noqa: S608 -- frozen migration inventory
    terms.append(
        "EXISTS(SELECT 1 FROM analytics_runs a JOIN xray_runs r ON r.analytics_run_id=a.id WHERE r.input_id=input AND (a.canonical_input<>'\\x'::bytea OR a.canonical_result<>'\\x'::bytea))"
    )
    terms.append(
        "EXISTS(SELECT 1 FROM xray_collection_bindings b JOIN xray_runs r ON r.id=b.run_id WHERE r.input_id=input)"
    )
    op.execute(
        "CREATE FUNCTION xray_payloads_pending(input uuid) RETURNS boolean LANGUAGE sql STABLE AS $$ SELECT "
        + " OR ".join(terms)
        + " $$"
    )
    op.execute(XRAY_RETENTION_GUARDS)
    op.execute(
        "CREATE TRIGGER xray_retention_authorized BEFORE INSERT OR UPDATE OR DELETE ON xray_retention_events FOR EACH ROW EXECUTE FUNCTION xray_retention_guard()"
    )
    for table, reference, parent, field, columns in XRAY_CATALOG_GUARDS:
        op.execute(
            f"CREATE TRIGGER xray_catalog_immutable BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION xray_catalog_guard('{reference}','{parent}','{field}','{columns}')"
        )
    for table in ("etf_overlap_pairs", "etf_overlap_entities", "xray_collection_bindings"):
        op.execute(
            f"CREATE TRIGGER xray_collection_immutable BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION xray_collection_guard()"
        )
    for table in ("collection_query_snapshots", "collection_query_snapshot_members"):
        op.execute(
            f"CREATE TRIGGER xray_collection_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION xray_collection_guard()"
        )
    for table in ("enrichment_retention_work", "enrichment_expiry_events"):
        op.execute(
            f"CREATE TRIGGER enrichment_retention_authorized BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION enrichment_retention_guard()"
        )
    op.execute(r"""CREATE OR REPLACE FUNCTION planning_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE input uuid;
    BEGIN
      IF TG_OP='UPDATE' AND TG_TABLE_NAME='analytics_runs' THEN
        IF historical_retention_write(TG_TABLE_NAME,to_jsonb(OLD),to_jsonb(NEW)) THEN RETURN NEW; END IF;
        input:=xray_input_for_row(TG_TABLE_NAME,to_jsonb(OLD));
        IF input IS NOT NULL AND EXISTS(SELECT 1 FROM xray_retention_events WHERE input_id=input AND owner_id=OLD.owner_id)
          AND to_jsonb(OLD)-ARRAY['canonical_input','canonical_result']=to_jsonb(NEW)-ARRAY['canonical_input','canonical_result']
          AND NEW.canonical_input='\x'::bytea AND NEW.canonical_result='\x'::bytea THEN RETURN NEW; END IF;
      END IF;
      RAISE EXCEPTION 'Immutable planning record' USING ERRCODE='23514';
    END $$;""")


def _drop_xray_retention_guards() -> None:
    op.execute("DROP TRIGGER xray_retention_authorized ON xray_retention_events")
    for table, *_ in XRAY_CATALOG_GUARDS:
        op.execute(f"DROP TRIGGER xray_catalog_immutable ON {table}")
    for table in (
        "etf_overlap_pairs",
        "etf_overlap_entities",
        "xray_collection_bindings",
        "collection_query_snapshots",
        "collection_query_snapshot_members",
    ):
        op.execute(f"DROP TRIGGER xray_collection_immutable ON {table}")
    for table in ("enrichment_retention_work", "enrichment_expiry_events"):
        op.execute(f"DROP TRIGGER enrichment_retention_authorized ON {table}")
    op.execute("""CREATE OR REPLACE FUNCTION planning_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP='UPDATE' AND TG_TABLE_NAME='analytics_runs' AND historical_retention_write(TG_TABLE_NAME,to_jsonb(OLD),to_jsonb(NEW)) THEN RETURN NEW; END IF;
      RAISE EXCEPTION 'Immutable planning record' USING ERRCODE='23514'; END $$;""")
    for name in (
        "xray_retention_guard",
        "xray_collection_guard",
        "xray_catalog_guard",
        "enrichment_retention_guard",
    ):
        op.execute(f"DROP FUNCTION {name}()")
    op.execute("DROP FUNCTION xray_payloads_pending(uuid)")
