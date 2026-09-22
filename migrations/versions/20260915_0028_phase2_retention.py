"""Indexed physical source/X-ray/historical retention; unchanged canonical bytes.

Revision ID:20260915_0028; previous20260915_0027. Source permission/publication
checks remain authoritative. Operational state proves physical absence only.
"""

from alembic import op

revision = "20260915_0028"
down_revision = "20260915_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_SCHEMA)
    op.execute(_CORE)
    op.execute(_BACKFILL)
    op.execute(_GUARDS)
    op.execute(_TRIGGERS)


def downgrade() -> None:
    op.execute(r"""DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM historical_retention_events WHERE source_dependency_id IS NOT NULL)
       OR EXISTS(SELECT 1 FROM source_retention_work WHERE completed_at IS NULL)
       OR EXISTS(SELECT 1 FROM enrichment_retention_work WHERE completed_at IS NULL)
       OR EXISTS(SELECT 1 FROM xray_physical_state s JOIN xray_retention_events e ON e.input_id=s.input_id WHERE s.input_pending OR s.payload_rows>0)
       OR EXISTS(SELECT 1 FROM historical_physical_runs s JOIN historical_retention_events e ON e.input_id=s.input_id WHERE s.child_rows>0 OR s.analytics_pending)
       OR EXISTS(SELECT 1 FROM phase2_retention_sweeps WHERE after_id IS NOT NULL OR pending_id IS NOT NULL) THEN
        RAISE EXCEPTION 'Finish Phase2 retention or retain its exact leaf witness before downgrade' USING ERRCODE='23514';
      END IF;
    END $$;""")
    op.execute("DROP TRIGGER phase2_sources_complete ON historical_input_snapshots")
    op.execute("DROP TRIGGER phase2_sources_complete ON xray_input_snapshots")
    op.execute("DROP TRIGGER phase2_collection_complete ON xray_collection_bindings")
    op.execute("DROP TRIGGER phase2_parent_drain ON xray_fund_compositions")
    op.execute("DROP TRIGGER phase2_parent_drain ON xray_exposure_paths")
    op.execute("DROP TRIGGER phase2_source_capture ON historical_dependencies")
    op.execute("DROP TRIGGER phase2_source_capture ON xray_input_dependencies")
    op.execute("DROP TRIGGER phase2_collection_drain ON xray_collection_bindings")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_collection_bindings")
    op.execute("DROP TRIGGER phase2_copy_counter ON historical_composite_benchmarks")
    op.execute("DROP TRIGGER phase2_copy_counter ON historical_conversions")
    op.execute("DROP TRIGGER phase2_copy_counter ON historical_cash_flow_points")
    op.execute("DROP TRIGGER phase2_copy_counter ON attribution_components")
    op.execute("DROP TRIGGER phase2_copy_counter ON income_components")
    op.execute("DROP TRIGGER phase2_copy_counter ON performance_period_returns")
    op.execute("DROP TRIGGER phase2_copy_counter ON performance_points")
    op.execute("DROP TRIGGER phase2_copy_counter ON benchmark_composite_points")
    op.execute("DROP TRIGGER phase2_copy_counter ON benchmark_snapshots")
    op.execute("DROP TRIGGER phase2_historical_copy_counter ON analytics_runs")
    op.execute("DROP TRIGGER phase2_copy_counter ON historical_analytics_runs")
    op.execute("DROP TRIGGER phase2_xray_copy_counter ON analytics_runs")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_fund_entities")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_path_edges")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_exposures")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_fund_compositions")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_exposure_paths")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_held_funds")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_direct_positions")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_classification_decisions")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_residuals")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_warnings")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_dimensions")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_runs")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_run_sources")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_input_source_selections")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_input_dependencies")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_input_cash")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_input_positions")
    op.execute("DROP TRIGGER phase2_copy_counter ON xray_input_snapshots")
    op.execute("DROP TRIGGER phase2_erasure_owned ON historical_composite_erasures")
    op.execute("DROP TRIGGER phase2_source_owned ON historical_retained_sources")
    op.execute("DROP TRIGGER phase2_source_owned ON xray_retained_sources")
    op.execute("DROP TRIGGER phase2_counter_owned ON historical_composite_physical")
    op.execute("DROP TRIGGER phase2_counter_owned ON historical_physical_runs")
    op.execute("DROP TRIGGER phase2_counter_owned ON xray_physical_state")
    op.execute(_RESTORE)
    op.execute("DROP FUNCTION phase2_source_membership_complete()")
    op.execute("DROP FUNCTION phase2_collection_root_complete()")
    op.execute("DROP FUNCTION phase2_xray_parent_drain_guard()")
    op.execute("DROP FUNCTION phase2_historical_rows_oracle(uuid)")
    op.execute("DROP FUNCTION phase2_xray_rows_oracle(uuid)")
    op.execute("DROP FUNCTION phase2_capture_sources()")
    op.execute("DROP FUNCTION phase2_collection_drain_guard()")
    op.execute("DROP FUNCTION phase2_collection_counter()")
    op.execute("DROP FUNCTION phase2_historical_counter()")
    op.execute("DROP FUNCTION phase2_xray_counter()")
    op.execute("DROP FUNCTION phase2_present(jsonb,text[])")
    op.execute("DROP FUNCTION phase2_retained_source_guard()")
    op.execute("DROP FUNCTION phase2_source_copies_pending(uuid,text,uuid)")
    op.execute("DROP FUNCTION phase2_input_pending(uuid,text,uuid)")
    op.execute("DROP FUNCTION phase2_composite_erasure_guard()")
    op.execute("DROP FUNCTION phase2_counter_guard()")
    op.execute("DROP FUNCTION phase2_source_erasure_authorized(uuid,text,uuid,timestamptz)")
    op.execute("DROP FUNCTION phase2_source_work_started(uuid,text,uuid)")
    op.execute("DROP FUNCTION phase2_owner_lock(uuid)")
    op.execute("DROP INDEX ix_p2_assignment_reference")
    op.execute("DROP INDEX ix_p2_edge_holding")
    op.execute("DROP INDEX ix_p2_xray_dependency")
    op.execute("DROP INDEX ix_p2_history_root")
    op.execute("DROP INDEX ix_p2_history_leaf")
    op.execute("DROP INDEX ix_p2_erasure_run")
    op.execute("DROP INDEX ix_p2_erasure_event")
    op.execute("DROP INDEX ix_p2_history_marker_leaf")
    op.execute("DROP INDEX ix_p2_work_fund_mapping")
    op.execute("DROP INDEX ix_p2_work_fund_definition")
    op.execute("DROP INDEX ix_p2_work_classification_snapshot")
    op.execute("DROP INDEX ix_p2_work_entity_evidence_version")
    op.execute("DROP INDEX ix_p2_work_constituent_snapshot")
    op.execute("DROP INDEX ix_p2_work_corporate_action_snapshot")
    op.execute("DROP INDEX ix_p2_work_benchmark_snapshot")
    op.execute("DROP INDEX ix_p2_work_fx_snapshot")
    op.execute("DROP INDEX ix_p2_work_price_snapshot")
    op.execute("DROP INDEX ix_p2_share_classes_pending")
    op.execute("DROP INDEX ix_p2_instrument_entity_relationships_pending")
    op.execute("DROP INDEX ix_p2_entity_evidence_references_pending")
    op.execute("DROP INDEX ix_p2_benchmark_composite_points_pending")
    op.execute("DROP INDEX ix_p2_historical_composite_benchmarks_pending")
    op.execute("DROP INDEX ix_p2_historical_conversions_pending")
    op.execute("DROP INDEX ix_p2_historical_cash_flow_points_pending")
    op.execute("DROP INDEX ix_p2_attribution_components_pending")
    op.execute("DROP INDEX ix_p2_income_components_pending")
    op.execute("DROP INDEX ix_p2_performance_period_returns_pending")
    op.execute("DROP INDEX ix_p2_performance_points_pending")
    op.execute("DROP INDEX ix_historical_retained_input")
    op.execute("DROP INDEX ix_historical_retained_source")
    op.execute("DROP INDEX ix_xray_retained_input")
    op.execute("DROP INDEX ix_xray_retained_source")
    op.execute("DROP INDEX ix_historical_physical_pending")
    op.drop_constraint(
        "fk_historical_retention_source_leaf", "historical_retention_events", type_="foreignkey"
    )
    op.drop_column("historical_retention_events", "source_dependency_id")
    op.drop_table("source_retention_dispatch")
    op.drop_table("phase2_retention_sweeps")
    op.drop_table("historical_retained_sources")
    op.drop_table("xray_retained_sources")
    op.drop_table("historical_composite_erasures")
    op.drop_table("historical_composite_physical")
    op.drop_table("historical_physical_runs")
    op.drop_table("xray_physical_state")


_SCHEMA = r"""CREATE TABLE xray_physical_state (
 input_id uuid NOT NULL,
 CONSTRAINT pk_xray_physical_state PRIMARY KEY(input_id),
 owner_id uuid NOT NULL,
 input_pending boolean NOT NULL,
 payload_rows bigint NOT NULL DEFAULT 0,
 CONSTRAINT fk_xray_physical_input FOREIGN KEY(owner_id,input_id) REFERENCES xray_input_snapshots(owner_id,id) ON DELETE RESTRICT,
 CONSTRAINT ck_xray_physical_state_rows_bound CHECK(payload_rows>=0)
);

CREATE TABLE historical_physical_runs (
 run_id uuid NOT NULL,
 CONSTRAINT pk_historical_physical_runs PRIMARY KEY(run_id),
 owner_id uuid NOT NULL,
 input_id uuid NOT NULL,
 child_rows bigint NOT NULL DEFAULT 0,
 analytics_pending boolean NOT NULL,
 CONSTRAINT fk_historical_physical_run FOREIGN KEY(owner_id,run_id) REFERENCES historical_analytics_runs(owner_id,id) ON DELETE RESTRICT,
 CONSTRAINT fk_historical_physical_input FOREIGN KEY(owner_id,input_id) REFERENCES historical_input_snapshots(owner_id,id) ON DELETE RESTRICT,
 CONSTRAINT ck_historical_physical_runs_rows_bound CHECK(child_rows>=0)
);

CREATE TABLE historical_composite_physical (
 snapshot_id uuid NOT NULL,
 CONSTRAINT pk_historical_composite_physical PRIMARY KEY(snapshot_id),
 owner_id uuid NOT NULL,
 point_rows bigint NOT NULL DEFAULT 0,
 CONSTRAINT fk_historical_composite_physical FOREIGN KEY(owner_id,snapshot_id) REFERENCES benchmark_snapshots(owner_id,id) ON DELETE RESTRICT,
 CONSTRAINT ck_historical_composite_physical_rows_bound CHECK(point_rows>=0)
);

CREATE TABLE historical_composite_erasures (
 snapshot_id uuid NOT NULL,
 CONSTRAINT pk_historical_composite_erasures PRIMARY KEY(snapshot_id),
 owner_id uuid NOT NULL,
 run_id uuid NOT NULL,
 event_id uuid NOT NULL,
 CONSTRAINT fk_historical_erasure_snapshot FOREIGN KEY(owner_id,snapshot_id) REFERENCES benchmark_snapshots(owner_id,id) ON DELETE RESTRICT,
 CONSTRAINT fk_historical_erasure_run FOREIGN KEY(owner_id,run_id) REFERENCES historical_analytics_runs(owner_id,id) ON DELETE RESTRICT,
 CONSTRAINT fk_historical_erasure_event FOREIGN KEY(owner_id,event_id) REFERENCES historical_retention_events(owner_id,id) ON DELETE RESTRICT
);

CREATE TABLE xray_retained_sources (
 dependency_id uuid NOT NULL,
 CONSTRAINT pk_xray_retained_sources PRIMARY KEY(dependency_id),
 owner_id uuid NOT NULL,
 input_id uuid NOT NULL,
 source_kind varchar(24) NOT NULL,
 source_id uuid NOT NULL,
 CONSTRAINT fk_xray_retained_input FOREIGN KEY(owner_id,input_id) REFERENCES xray_input_snapshots(owner_id,id) ON DELETE RESTRICT,
 CONSTRAINT fk_xray_retained_dependency FOREIGN KEY(owner_id,dependency_id) REFERENCES xray_input_dependencies(owner_id,id) ON DELETE RESTRICT,
 CONSTRAINT ck_xray_retained_sources_kind_bound CHECK(source_kind IN ('fx','entity_evidence','classification','fund_definition','fund_mapping','constituent'))
);

CREATE TABLE historical_retained_sources (
 dependency_id uuid NOT NULL,
 leaf_id uuid NOT NULL,
 owner_id uuid NOT NULL,
 input_id uuid NOT NULL,
 source_kind varchar(24) NOT NULL,
 source_id uuid NOT NULL,
 CONSTRAINT pk_historical_retained_sources PRIMARY KEY(dependency_id,leaf_id),
 CONSTRAINT fk_historical_retained_input FOREIGN KEY(owner_id,input_id) REFERENCES historical_input_snapshots(owner_id,id) ON DELETE RESTRICT,
 CONSTRAINT fk_historical_retained_dependency FOREIGN KEY(owner_id,dependency_id) REFERENCES historical_dependencies(owner_id,id) ON DELETE RESTRICT,
 CONSTRAINT fk_historical_retained_leaf FOREIGN KEY(owner_id,leaf_id) REFERENCES historical_dependencies(owner_id,id) ON DELETE RESTRICT,
 CONSTRAINT ck_historical_retained_sources_kind_bound CHECK(source_kind IN ('price','fx','corporate_action','benchmark'))
);

CREATE TABLE phase2_retention_sweeps (
 family varchar(24) NOT NULL,
 scope_id uuid NOT NULL,
 CONSTRAINT pk_phase2_retention_sweeps PRIMARY KEY(family,scope_id),
 after_id uuid,
 pending_id uuid,
 evaluated_at timestamptz,
 CONSTRAINT ck_phase2_retention_sweeps_family_bound CHECK(family IN ('price','fx','benchmark','corporate_action','constituent','xray_collection','entity_evidence','classification','fund_definition','fund_mapping'))
);

CREATE TABLE source_retention_dispatch (
 family varchar(16) NOT NULL,
 CONSTRAINT pk_source_retention_dispatch PRIMARY KEY(family),
 next_family smallint NOT NULL DEFAULT 0,
 CONSTRAINT ck_source_retention_dispatch_family_bound CHECK((family='dispatch' AND next_family BETWEEN 0 AND 6) OR (family='source' AND next_family BETWEEN 0 AND 4) OR (family='enrichment' AND next_family BETWEEN 0 AND 3))
);


CREATE INDEX ix_historical_physical_pending ON historical_physical_runs(owner_id,input_id,run_id) WHERE child_rows>0 OR analytics_pending;

CREATE INDEX ix_xray_retained_source ON xray_retained_sources(owner_id,source_kind,source_id,input_id,dependency_id);

CREATE INDEX ix_xray_retained_input ON xray_retained_sources(owner_id,input_id,dependency_id);

CREATE INDEX ix_historical_retained_source ON historical_retained_sources(owner_id,source_kind,source_id,input_id,dependency_id,leaf_id);

CREATE INDEX ix_historical_retained_input ON historical_retained_sources(owner_id,input_id,dependency_id,leaf_id);

CREATE INDEX ix_p2_performance_points_pending ON performance_points(run_id,id) WHERE (canonical_row <> '\x'::bytea OR portfolio_value IS NOT NULL OR cash_value IS NOT NULL OR wealth IS NOT NULL OR period_return IS NOT NULL);

CREATE INDEX ix_p2_performance_period_returns_pending ON performance_period_returns(run_id,id) WHERE (canonical_row <> '\x'::bytea OR period_return IS NOT NULL);

CREATE INDEX ix_p2_income_components_pending ON income_components(run_id,id) WHERE (canonical_row <> '\x'::bytea OR net IS NOT NULL OR gross IS NOT NULL OR withholding IS NOT NULL);

CREATE INDEX ix_p2_attribution_components_pending ON attribution_components(run_id,id) WHERE (canonical_row <> '\x'::bytea OR gain IS NOT NULL OR return_contribution IS NOT NULL);

CREATE INDEX ix_p2_historical_cash_flow_points_pending ON historical_cash_flow_points(run_id,id) WHERE (canonical_row <> '\x'::bytea OR amount IS NOT NULL);

CREATE INDEX ix_p2_historical_conversions_pending ON historical_conversions(run_id,id) WHERE (rate IS NOT NULL);

CREATE INDEX ix_p2_historical_composite_benchmarks_pending ON historical_composite_benchmarks(run_id,id) WHERE (canonical_composite <> '\x'::bytea);

CREATE INDEX ix_p2_benchmark_composite_points_pending ON benchmark_composite_points(snapshot_id,id) WHERE (canonical_point <> '\x'::bytea OR wealth IS NOT NULL OR interval_return IS NOT NULL);

CREATE INDEX ix_p2_entity_evidence_references_pending ON entity_evidence_references(evidence_version_id,id) WHERE (display_name IS NOT NULL OR lei IS NOT NULL OR confidence IS NOT NULL);

CREATE INDEX ix_p2_instrument_entity_relationships_pending ON instrument_entity_relationships(evidence_version_id,id) WHERE (units_per_receipt IS NOT NULL OR confidence IS NOT NULL);

CREATE INDEX ix_p2_share_classes_pending ON share_classes(evidence_version_id,id) WHERE (class_key IS NOT NULL OR confidence IS NOT NULL);
CREATE INDEX ix_p2_work_price_snapshot ON source_retention_work(id) WHERE price_snapshot_id IS NOT NULL AND completed_at IS NULL;
CREATE INDEX ix_p2_work_fx_snapshot ON source_retention_work(id) WHERE fx_snapshot_id IS NOT NULL AND completed_at IS NULL;
CREATE INDEX ix_p2_work_benchmark_snapshot ON source_retention_work(id) WHERE benchmark_snapshot_id IS NOT NULL AND completed_at IS NULL;
CREATE INDEX ix_p2_work_corporate_action_snapshot ON source_retention_work(id) WHERE corporate_action_snapshot_id IS NOT NULL AND completed_at IS NULL;
CREATE INDEX ix_p2_work_constituent_snapshot ON source_retention_work(id) WHERE constituent_snapshot_id IS NOT NULL AND completed_at IS NULL;
CREATE INDEX ix_p2_work_entity_evidence_version ON enrichment_retention_work(id) WHERE entity_evidence_version_id IS NOT NULL AND completed_at IS NULL;
CREATE INDEX ix_p2_work_classification_snapshot ON enrichment_retention_work(id) WHERE classification_snapshot_id IS NOT NULL AND completed_at IS NULL;
CREATE INDEX ix_p2_work_fund_definition ON enrichment_retention_work(id) WHERE fund_definition_id IS NOT NULL AND completed_at IS NULL;
CREATE INDEX ix_p2_work_fund_mapping ON enrichment_retention_work(id) WHERE fund_mapping_id IS NOT NULL AND completed_at IS NULL;
ALTER TABLE historical_retention_events ADD COLUMN source_dependency_id uuid;
ALTER TABLE historical_retention_events ADD CONSTRAINT fk_historical_retention_source_leaf FOREIGN KEY(owner_id,source_dependency_id) REFERENCES historical_dependencies(owner_id,id) ON DELETE RESTRICT;
CREATE INDEX ix_p2_history_marker_leaf ON historical_retention_events(owner_id,source_dependency_id);
CREATE INDEX ix_p2_erasure_event ON historical_composite_erasures(owner_id,event_id);
CREATE INDEX ix_p2_erasure_run ON historical_composite_erasures(owner_id,run_id);
CREATE INDEX ix_p2_history_leaf ON historical_retained_sources(owner_id,leaf_id);
CREATE INDEX ix_p2_history_root ON historical_retained_sources(owner_id,dependency_id);
CREATE INDEX ix_p2_xray_dependency ON xray_retained_sources(owner_id,dependency_id);

CREATE INDEX ix_p2_edge_holding ON xray_path_edges(owner_id,holding_id);
CREATE INDEX ix_p2_assignment_reference ON classification_snapshot_assignments(owner_id,assignment_id);
"""


_CORE = r"""CREATE FUNCTION phase2_source_work_started(p_owner uuid,p_kind text,p_source uuid) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE reference text; work_table text; present boolean;
BEGIN
 SELECT v.r,v.t INTO reference,work_table FROM (VALUES
 ('price','price_snapshot_id','source_retention_work'),('fx','fx_snapshot_id','source_retention_work'),('benchmark','benchmark_snapshot_id','source_retention_work'),('corporate_action','corporate_action_snapshot_id','source_retention_work'),('constituent','constituent_snapshot_id','source_retention_work'),
 ('entity_evidence','entity_evidence_version_id','enrichment_retention_work'),('classification','classification_snapshot_id','enrichment_retention_work'),('fund_definition','fund_definition_id','enrichment_retention_work'),('fund_mapping','fund_mapping_id','enrichment_retention_work')) v(k,r,t) WHERE v.k=p_kind;
 IF reference IS NULL THEN RETURN true; END IF;
 EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I WHERE owner_id=$1 AND %I=$2)',work_table,reference) INTO present USING p_owner,p_source;
 RETURN present;
END $$;

CREATE FUNCTION phase2_owner_lock(p_owner uuid) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('sources:'||p_owner::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('xray:'||p_owner::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('historical:'||p_owner::text,0));
END $$;
CREATE FUNCTION phase2_counter_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' OR pg_trigger_depth()<=1 THEN
  RAISE EXCEPTION 'Physical copy counters are trigger maintained' USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' AND (to_jsonb(OLD)-ARRAY['input_pending','payload_rows','child_rows','analytics_pending','point_rows'])
  IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['input_pending','payload_rows','child_rows','analytics_pending','point_rows']) THEN
  RAISE EXCEPTION 'Physical counter identity is immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION phase2_composite_erasure_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Composite erasure witness is immutable' USING ERRCODE='23514'; END IF;
 PERFORM phase2_owner_lock(NEW.owner_id);
 IF NOT EXISTS(SELECT 1 FROM historical_composite_benchmarks c
   JOIN historical_analytics_runs r ON r.id=c.run_id AND r.owner_id=c.owner_id
   JOIN historical_retention_events e ON e.input_id=r.input_id AND e.owner_id=r.owner_id
   WHERE c.run_id=NEW.run_id AND c.snapshot_id=NEW.snapshot_id AND c.owner_id=NEW.owner_id AND e.id=NEW.event_id) THEN
  RAISE EXCEPTION 'Composite erasure requires an exact retained input marker' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION phase2_input_pending(p_owner uuid,p_family text,p_input uuid) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
BEGIN
 IF p_family='xray' THEN
  RETURN COALESCE((SELECT input_pending OR payload_rows>0 FROM xray_physical_state WHERE owner_id=p_owner AND input_id=p_input),true);
 ELSIF p_family='historical' THEN
  RETURN COALESCE((SELECT canonical_input<>'\x'::bytea FROM historical_input_snapshots WHERE owner_id=p_owner AND id=p_input),true)
    OR EXISTS(SELECT 1 FROM historical_physical_runs WHERE owner_id=p_owner AND input_id=p_input AND (child_rows>0 OR analytics_pending));
 END IF;
 RETURN true;
END $$;
CREATE FUNCTION phase2_source_copies_pending(p_owner uuid,p_kind text,p_source uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM xray_retained_sources WHERE owner_id=p_owner AND source_kind=p_kind AND source_id=p_source)
 OR EXISTS(SELECT 1 FROM historical_retained_sources WHERE owner_id=p_owner AND source_kind=p_kind AND source_id=p_source)
 OR (p_kind='constituent' AND EXISTS(SELECT 1 FROM xray_collection_bindings WHERE owner_id=p_owner AND constituent_snapshot_id=p_source));
$$;
CREATE FUNCTION phase2_retained_source_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE family text:=CASE TG_TABLE_NAME WHEN 'xray_retained_sources' THEN 'xray' ELSE 'historical' END;
BEGIN
 IF TG_OP='INSERT' THEN
  IF pg_trigger_depth()<=1 THEN RAISE EXCEPTION 'Retained source membership is trigger maintained' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 ELSIF TG_OP='UPDATE' THEN RAISE EXCEPTION 'Retained source identity is immutable' USING ERRCODE='23514';
 END IF;
 PERFORM phase2_owner_lock(OLD.owner_id);
 IF phase2_input_pending(OLD.owner_id,family,OLD.input_id) OR
  (family='xray' AND NOT EXISTS(SELECT 1 FROM xray_retention_events WHERE owner_id=OLD.owner_id AND input_id=OLD.input_id)) OR
  (family='historical' AND NOT EXISTS(SELECT 1 FROM historical_retention_events WHERE owner_id=OLD.owner_id AND input_id=OLD.input_id)) THEN
  RAISE EXCEPTION 'Retained source copies remain pending' USING ERRCODE='23514';
 END IF;
 RETURN OLD;
END $$;
CREATE FUNCTION phase2_present(p_row jsonb,p_columns text[]) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE field text;
BEGIN
 IF p_row IS NULL THEN RETURN false; END IF;
 FOREACH field IN ARRAY p_columns LOOP
  IF field LIKE 'canonical_%' THEN
   IF COALESCE(p_row->>field,'\x')<>'\x' THEN RETURN true; END IF;
  ELSIF p_row->field IS NOT NULL AND p_row->field<>'null'::jsonb THEN RETURN true;
  END IF;
 END LOOP;
 RETURN false;
END $$;
CREATE FUNCTION phase2_xray_counter() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b jsonb:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 p_input uuid; delta integer; initial integer:=0;
BEGIN
 PERFORM phase2_owner_lock((b->>'owner_id')::uuid);
 IF TG_TABLE_NAME='xray_input_snapshots' THEN
  IF TG_OP='INSERT' THEN
   INSERT INTO xray_physical_state(input_id,owner_id,input_pending,payload_rows) VALUES(NEW.id,NEW.owner_id,NEW.canonical_input<>'\x'::bytea,0);
  ELSE
   UPDATE xray_physical_state SET input_pending=NEW.canonical_input<>'\x'::bytea WHERE input_id=NEW.id AND owner_id=NEW.owner_id;
   IF NOT FOUND THEN RAISE EXCEPTION 'Missing X-ray physical state' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NULL;
 END IF;
 p_input:=xray_input_for_row(TG_TABLE_NAME,b);
 IF p_input IS NULL THEN RETURN NULL; END IF;
 delta:=(CASE WHEN TG_OP='DELETE' THEN 0 ELSE phase2_present(to_jsonb(NEW),string_to_array(TG_ARGV[0],','))::integer END)
       -(CASE WHEN TG_OP='INSERT' THEN 0 ELSE phase2_present(CASE WHEN TG_OP='DELETE' THEN b ELSE to_jsonb(OLD) END,string_to_array(TG_ARGV[0],','))::integer END);
 IF TG_OP='INSERT' AND TG_TABLE_NAME='xray_runs' THEN
  SELECT (canonical_input<>'\x'::bytea OR canonical_result<>'\x'::bytea)::integer INTO initial FROM analytics_runs WHERE id=NEW.analytics_run_id AND owner_id=NEW.owner_id;
  IF initial IS NULL THEN RAISE EXCEPTION 'Missing X-ray analytics payload' USING ERRCODE='23514'; END IF;
 END IF;
 IF delta+initial>0 AND EXISTS(SELECT 1 FROM xray_retention_events WHERE owner_id=(b->>'owner_id')::uuid AND input_id=p_input) THEN
  RAISE EXCEPTION 'Purged X-ray input cannot receive new copies' USING ERRCODE='23514'; END IF;
 IF delta+initial<>0 THEN
  UPDATE xray_physical_state SET payload_rows=payload_rows+delta+initial WHERE owner_id=(b->>'owner_id')::uuid AND input_id=p_input;
  IF NOT FOUND THEN RAISE EXCEPTION 'Missing X-ray physical state' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION phase2_historical_counter() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b jsonb:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 p_run uuid; p_input uuid; p_owner uuid:=(b->>'owner_id')::uuid; delta integer; pending boolean;
BEGIN
 PERFORM phase2_owner_lock(p_owner);
 IF TG_TABLE_NAME='historical_analytics_runs' THEN
  SELECT canonical_input<>'\x'::bytea OR canonical_result<>'\x'::bytea INTO pending FROM analytics_runs WHERE id=NEW.analytics_run_id AND owner_id=NEW.owner_id;
  IF pending IS NULL OR EXISTS(SELECT 1 FROM historical_retention_events WHERE input_id=NEW.input_id AND owner_id=NEW.owner_id) THEN
   RAISE EXCEPTION 'Purged historical input cannot receive results' USING ERRCODE='23514'; END IF;
  INSERT INTO historical_physical_runs(run_id,owner_id,input_id,child_rows,analytics_pending) VALUES(NEW.id,NEW.owner_id,NEW.input_id,0,pending);
  RETURN NULL;
 ELSIF TG_TABLE_NAME='analytics_runs' THEN
  SELECT id,input_id INTO p_run,p_input FROM historical_analytics_runs WHERE analytics_run_id=(b->>'id')::uuid AND owner_id=p_owner;
  IF p_run IS NULL THEN RETURN NULL; END IF;
  pending:=TG_OP<>'DELETE' AND phase2_present(to_jsonb(NEW),ARRAY['canonical_input','canonical_result']);
  IF pending AND EXISTS(SELECT 1 FROM historical_retention_events WHERE input_id=p_input AND owner_id=p_owner) THEN RAISE EXCEPTION 'Purged historical input cannot receive copies' USING ERRCODE='23514'; END IF;
  UPDATE historical_physical_runs SET analytics_pending=pending WHERE run_id=p_run AND owner_id=p_owner;
  IF NOT FOUND THEN RAISE EXCEPTION 'Missing historical physical state' USING ERRCODE='23514'; END IF;
  RETURN NULL;
 ELSIF TG_TABLE_NAME='benchmark_snapshots' THEN
  IF NEW.snapshot_kind='composite' THEN INSERT INTO historical_composite_physical(snapshot_id,owner_id,point_rows) VALUES(NEW.id,NEW.owner_id,0); END IF;
  RETURN NULL;
 ELSIF TG_TABLE_NAME='benchmark_composite_points' THEN
  delta:=(CASE WHEN TG_OP='DELETE' THEN 0 ELSE phase2_present(to_jsonb(NEW),ARRAY['canonical_point','wealth','interval_return'])::integer END)
       -(CASE WHEN TG_OP='INSERT' THEN 0 ELSE phase2_present(CASE WHEN TG_OP='DELETE' THEN b ELSE to_jsonb(OLD) END,ARRAY['canonical_point','wealth','interval_return'])::integer END);
  IF delta>0 AND EXISTS(SELECT 1 FROM historical_composite_erasures WHERE snapshot_id=(b->>'snapshot_id')::uuid AND owner_id=p_owner) THEN
   RAISE EXCEPTION 'Erased composite cannot receive new points' USING ERRCODE='23514'; END IF;
  UPDATE historical_composite_physical SET point_rows=point_rows+delta WHERE snapshot_id=(b->>'snapshot_id')::uuid AND owner_id=p_owner;
  IF NOT FOUND THEN RAISE EXCEPTION 'Missing composite physical state' USING ERRCODE='23514'; END IF;
  RETURN NULL;
 END IF;
 p_run:=(b->>'run_id')::uuid;
 SELECT input_id INTO p_input FROM historical_physical_runs WHERE run_id=p_run AND owner_id=p_owner;
 IF p_input IS NULL THEN RAISE EXCEPTION 'Missing historical physical state' USING ERRCODE='23514'; END IF;
 delta:=(CASE WHEN TG_OP='DELETE' THEN 0 ELSE phase2_present(to_jsonb(NEW),string_to_array(TG_ARGV[0],','))::integer END)
       -(CASE WHEN TG_OP='INSERT' THEN 0 ELSE phase2_present(CASE WHEN TG_OP='DELETE' THEN b ELSE to_jsonb(OLD) END,string_to_array(TG_ARGV[0],','))::integer END);
 IF delta>0 AND EXISTS(SELECT 1 FROM historical_retention_events WHERE input_id=p_input AND owner_id=p_owner) THEN RAISE EXCEPTION 'Purged historical input cannot receive copies' USING ERRCODE='23514'; END IF;
 UPDATE historical_physical_runs SET child_rows=child_rows+delta WHERE run_id=p_run AND owner_id=p_owner;
 RETURN NULL;
END $$;
CREATE FUNCTION phase2_collection_counter() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b jsonb:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END; p_input uuid;
BEGIN
 IF b->>'run_id' IS NULL THEN RETURN NULL; END IF;
 SELECT input_id INTO p_input FROM xray_runs WHERE id=(b->>'run_id')::uuid AND owner_id=(b->>'owner_id')::uuid;
 IF p_input IS NULL THEN RAISE EXCEPTION 'Collection run is absent' USING ERRCODE='23514'; END IF;
 PERFORM phase2_owner_lock((b->>'owner_id')::uuid);
 IF TG_OP='INSERT' AND EXISTS(SELECT 1 FROM xray_retention_events WHERE input_id=p_input AND owner_id=(b->>'owner_id')::uuid) THEN
  RAISE EXCEPTION 'Purged X-ray input cannot receive collections' USING ERRCODE='23514'; END IF;
 UPDATE xray_physical_state SET payload_rows=payload_rows+(CASE WHEN TG_OP='DELETE' THEN -1 ELSE 1 END) WHERE input_id=p_input AND owner_id=(b->>'owner_id')::uuid;
 IF NOT FOUND THEN RAISE EXCEPTION 'Missing X-ray physical state' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION phase2_collection_drain_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM collection_query_snapshot_members WHERE snapshot_id=OLD.collection_id)
 OR EXISTS(SELECT 1 FROM etf_overlap_entities WHERE collection_id=OLD.collection_id AND owner_id=OLD.owner_id)
 OR EXISTS(SELECT 1 FROM etf_overlap_pairs WHERE collection_id=OLD.collection_id AND owner_id=OLD.owner_id) THEN
  RAISE EXCEPTION 'Physical collection copies must drain before binding' USING ERRCODE='23514'; END IF;
 RETURN OLD;
END $$;

CREATE FUNCTION phase2_capture_sources() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p_input uuid; p_owner uuid:=NEW.owner_id;
BEGIN
 PERFORM phase2_owner_lock(p_owner);
 IF TG_TABLE_NAME='xray_input_dependencies' THEN
  IF EXISTS(SELECT 1 FROM xray_retention_events WHERE input_id=NEW.input_id AND owner_id=p_owner) THEN RAISE EXCEPTION 'Purged X-ray dependency' USING ERRCODE='23514'; END IF;
  IF NEW.fx_snapshot_id IS NOT NULL THEN IF phase2_source_work_started(p_owner,'fx',NEW.fx_snapshot_id) THEN RAISE EXCEPTION 'Source is pending physical erasure' USING ERRCODE='23514'; END IF; INSERT INTO xray_retained_sources(dependency_id,owner_id,input_id,source_kind,source_id) VALUES(NEW.id,p_owner,NEW.input_id,'fx',NEW.fx_snapshot_id); END IF;
  IF NEW.entity_evidence_version_id IS NOT NULL THEN IF phase2_source_work_started(p_owner,'entity_evidence',NEW.entity_evidence_version_id) THEN RAISE EXCEPTION 'Source is pending physical erasure' USING ERRCODE='23514'; END IF; INSERT INTO xray_retained_sources(dependency_id,owner_id,input_id,source_kind,source_id) VALUES(NEW.id,p_owner,NEW.input_id,'entity_evidence',NEW.entity_evidence_version_id); END IF;
  IF NEW.classification_snapshot_id IS NOT NULL THEN IF phase2_source_work_started(p_owner,'classification',NEW.classification_snapshot_id) THEN RAISE EXCEPTION 'Source is pending physical erasure' USING ERRCODE='23514'; END IF; INSERT INTO xray_retained_sources(dependency_id,owner_id,input_id,source_kind,source_id) VALUES(NEW.id,p_owner,NEW.input_id,'classification',NEW.classification_snapshot_id); END IF;
  IF NEW.fund_definition_id IS NOT NULL THEN IF phase2_source_work_started(p_owner,'fund_definition',NEW.fund_definition_id) THEN RAISE EXCEPTION 'Source is pending physical erasure' USING ERRCODE='23514'; END IF; INSERT INTO xray_retained_sources(dependency_id,owner_id,input_id,source_kind,source_id) VALUES(NEW.id,p_owner,NEW.input_id,'fund_definition',NEW.fund_definition_id); END IF;
  IF NEW.fund_mapping_id IS NOT NULL THEN IF phase2_source_work_started(p_owner,'fund_mapping',NEW.fund_mapping_id) THEN RAISE EXCEPTION 'Source is pending physical erasure' USING ERRCODE='23514'; END IF; INSERT INTO xray_retained_sources(dependency_id,owner_id,input_id,source_kind,source_id) VALUES(NEW.id,p_owner,NEW.input_id,'fund_mapping',NEW.fund_mapping_id); END IF;
  IF NEW.constituent_snapshot_id IS NOT NULL THEN IF phase2_source_work_started(p_owner,'constituent',NEW.constituent_snapshot_id) THEN RAISE EXCEPTION 'Source is pending physical erasure' USING ERRCODE='23514'; END IF; INSERT INTO xray_retained_sources(dependency_id,owner_id,input_id,source_kind,source_id) VALUES(NEW.id,p_owner,NEW.input_id,'constituent',NEW.constituent_snapshot_id); END IF;
 ELSE
  p_input:=NEW.input_id;
  IF p_input IS NULL THEN RETURN NULL; END IF;
  IF EXISTS(SELECT 1 FROM historical_retention_events WHERE input_id=p_input AND owner_id=p_owner) THEN RAISE EXCEPTION 'Purged historical dependency' USING ERRCODE='23514'; END IF;
  IF NEW.price_snapshot_id IS NOT NULL THEN IF phase2_source_work_started(p_owner,'price',NEW.price_snapshot_id) THEN RAISE EXCEPTION 'Source is pending physical erasure' USING ERRCODE='23514'; END IF; INSERT INTO historical_retained_sources(dependency_id,leaf_id,owner_id,input_id,source_kind,source_id) VALUES(NEW.id,NEW.id,p_owner,p_input,'price',NEW.price_snapshot_id); END IF;
  IF NEW.fx_snapshot_id IS NOT NULL THEN IF phase2_source_work_started(p_owner,'fx',NEW.fx_snapshot_id) THEN RAISE EXCEPTION 'Source is pending physical erasure' USING ERRCODE='23514'; END IF; INSERT INTO historical_retained_sources(dependency_id,leaf_id,owner_id,input_id,source_kind,source_id) VALUES(NEW.id,NEW.id,p_owner,p_input,'fx',NEW.fx_snapshot_id); END IF;
  IF NEW.action_snapshot_id IS NOT NULL THEN IF phase2_source_work_started(p_owner,'corporate_action',NEW.action_snapshot_id) THEN RAISE EXCEPTION 'Source is pending physical erasure' USING ERRCODE='23514'; END IF; INSERT INTO historical_retained_sources(dependency_id,leaf_id,owner_id,input_id,source_kind,source_id) VALUES(NEW.id,NEW.id,p_owner,p_input,'corporate_action',NEW.action_snapshot_id); END IF;
  IF NEW.benchmark_snapshot_id IS NOT NULL THEN IF phase2_source_work_started(p_owner,'benchmark',NEW.benchmark_snapshot_id) THEN RAISE EXCEPTION 'Source is pending physical erasure' USING ERRCODE='23514'; END IF; INSERT INTO historical_retained_sources(dependency_id,leaf_id,owner_id,input_id,source_kind,source_id) VALUES(NEW.id,NEW.id,p_owner,p_input,'benchmark',NEW.benchmark_snapshot_id); END IF;
  IF NEW.registered_evidence_id IS NOT NULL THEN IF EXISTS(SELECT 1 FROM historical_dependencies d WHERE d.owner_id=p_owner AND d.evidence_id=NEW.registered_evidence_id AND d.price_snapshot_id IS NOT NULL AND phase2_source_work_started(p_owner,'price',d.price_snapshot_id)) THEN RAISE EXCEPTION 'Source is pending physical erasure' USING ERRCODE='23514'; END IF; INSERT INTO historical_retained_sources(dependency_id,leaf_id,owner_id,input_id,source_kind,source_id) SELECT NEW.id,d.id,p_owner,p_input,'price',d.price_snapshot_id FROM historical_dependencies d WHERE d.owner_id=p_owner AND d.evidence_id=NEW.registered_evidence_id AND d.price_snapshot_id IS NOT NULL; END IF;
  IF NEW.registered_evidence_id IS NOT NULL THEN IF EXISTS(SELECT 1 FROM historical_dependencies d WHERE d.owner_id=p_owner AND d.evidence_id=NEW.registered_evidence_id AND d.fx_snapshot_id IS NOT NULL AND phase2_source_work_started(p_owner,'fx',d.fx_snapshot_id)) THEN RAISE EXCEPTION 'Source is pending physical erasure' USING ERRCODE='23514'; END IF; INSERT INTO historical_retained_sources(dependency_id,leaf_id,owner_id,input_id,source_kind,source_id) SELECT NEW.id,d.id,p_owner,p_input,'fx',d.fx_snapshot_id FROM historical_dependencies d WHERE d.owner_id=p_owner AND d.evidence_id=NEW.registered_evidence_id AND d.fx_snapshot_id IS NOT NULL; END IF;
  IF NEW.registered_evidence_id IS NOT NULL THEN IF EXISTS(SELECT 1 FROM historical_dependencies d WHERE d.owner_id=p_owner AND d.evidence_id=NEW.registered_evidence_id AND d.action_snapshot_id IS NOT NULL AND phase2_source_work_started(p_owner,'corporate_action',d.action_snapshot_id)) THEN RAISE EXCEPTION 'Source is pending physical erasure' USING ERRCODE='23514'; END IF; INSERT INTO historical_retained_sources(dependency_id,leaf_id,owner_id,input_id,source_kind,source_id) SELECT NEW.id,d.id,p_owner,p_input,'corporate_action',d.action_snapshot_id FROM historical_dependencies d WHERE d.owner_id=p_owner AND d.evidence_id=NEW.registered_evidence_id AND d.action_snapshot_id IS NOT NULL; END IF;
  IF NEW.registered_evidence_id IS NOT NULL THEN IF EXISTS(SELECT 1 FROM historical_dependencies d WHERE d.owner_id=p_owner AND d.evidence_id=NEW.registered_evidence_id AND d.benchmark_snapshot_id IS NOT NULL AND phase2_source_work_started(p_owner,'benchmark',d.benchmark_snapshot_id)) THEN RAISE EXCEPTION 'Source is pending physical erasure' USING ERRCODE='23514'; END IF; INSERT INTO historical_retained_sources(dependency_id,leaf_id,owner_id,input_id,source_kind,source_id) SELECT NEW.id,d.id,p_owner,p_input,'benchmark',d.benchmark_snapshot_id FROM historical_dependencies d WHERE d.owner_id=p_owner AND d.evidence_id=NEW.registered_evidence_id AND d.benchmark_snapshot_id IS NOT NULL; END IF;
 END IF; RETURN NULL; END $$;
CREATE FUNCTION phase2_xray_rows_oracle(p_input uuid) RETURNS bigint LANGUAGE sql STABLE AS $$ SELECT (SELECT count(*) FROM xray_input_positions p WHERE p.input_id=p_input AND (p.canonical_position <> '\x'::bytea)) + (SELECT count(*) FROM xray_input_cash p WHERE p.input_id=p_input AND (p.canonical_cash <> '\x'::bytea)) + (SELECT count(*) FROM xray_input_dependencies p WHERE p.input_id=p_input AND (p.canonical_reference <> '\x'::bytea)) + (SELECT count(*) FROM xray_input_source_selections p WHERE p.input_id=p_input AND (p.canonical_selection <> '\x'::bytea)) + (SELECT count(*) FROM xray_run_sources p WHERE (SELECT input_id FROM xray_runs WHERE id=p.run_id)=p_input AND (p.canonical_use <> '\x'::bytea)) + (SELECT count(*) FROM xray_runs p WHERE p.input_id=p_input AND (p.canonical_summary <> '\x'::bytea OR p.canonical_reconciliation <> '\x'::bytea OR p.canonical_exact_state <> '\x'::bytea)) + (SELECT count(*) FROM xray_dimensions p WHERE (SELECT input_id FROM xray_runs WHERE id=p.run_id)=p_input AND (p.canonical_payload <> '\x'::bytea)) + (SELECT count(*) FROM xray_warnings p WHERE (SELECT input_id FROM xray_runs WHERE id=p.run_id)=p_input AND (p.canonical_payload <> '\x'::bytea)) + (SELECT count(*) FROM xray_residuals p WHERE (SELECT input_id FROM xray_runs WHERE id=p.run_id)=p_input AND (p.canonical_payload <> '\x'::bytea)) + (SELECT count(*) FROM xray_classification_decisions p WHERE (SELECT input_id FROM xray_runs WHERE id=p.run_id)=p_input AND (p.canonical_payload <> '\x'::bytea)) + (SELECT count(*) FROM xray_direct_positions p WHERE (SELECT input_id FROM xray_runs WHERE id=p.run_id)=p_input AND (p.canonical_payload <> '\x'::bytea)) + (SELECT count(*) FROM xray_held_funds p WHERE (SELECT input_id FROM xray_runs WHERE id=p.run_id)=p_input AND (p.canonical_payload <> '\x'::bytea)) + (SELECT count(*) FROM xray_exposure_paths p WHERE (SELECT input_id FROM xray_runs WHERE id=p.run_id)=p_input AND (p.canonical_payload <> '\x'::bytea)) + (SELECT count(*) FROM xray_fund_compositions p WHERE (SELECT input_id FROM xray_runs WHERE id=p.run_id)=p_input AND (p.canonical_payload <> '\x'::bytea)) + (SELECT count(*) FROM xray_exposures p WHERE (SELECT input_id FROM xray_runs WHERE id=p.run_id)=p_input AND (p.canonical_payload <> '\x'::bytea OR p.bucket_key IS NOT NULL)) + (SELECT count(*) FROM xray_path_edges p WHERE (SELECT r.input_id FROM xray_exposure_paths parent JOIN xray_runs r ON r.id=parent.run_id WHERE parent.id=p.path_id)=p_input AND (p.canonical_edge <> '\x'::bytea)) + (SELECT count(*) FROM xray_fund_entities p WHERE (SELECT r.input_id FROM xray_fund_compositions parent JOIN xray_runs r ON r.id=parent.run_id WHERE parent.id=p.composition_id)=p_input AND (p.canonical_payload <> '\x'::bytea OR p.relative_coefficient IS NOT NULL)) + (SELECT count(*) FROM analytics_runs a JOIN xray_runs r ON r.analytics_run_id=a.id WHERE r.input_id=p_input AND (a.canonical_input<>'\x'::bytea OR a.canonical_result<>'\x'::bytea)) + (SELECT count(*) FROM xray_collection_bindings b JOIN xray_runs r ON r.id=b.run_id WHERE r.input_id=p_input); $$;
CREATE FUNCTION phase2_historical_rows_oracle(p_run uuid) RETURNS bigint LANGUAGE sql STABLE AS $$ SELECT (SELECT count(*) FROM performance_points p WHERE p.run_id=p_run AND (p.canonical_row <> '\x'::bytea OR p.portfolio_value IS NOT NULL OR p.cash_value IS NOT NULL OR p.wealth IS NOT NULL OR p.period_return IS NOT NULL)) + (SELECT count(*) FROM performance_period_returns p WHERE p.run_id=p_run AND (p.canonical_row <> '\x'::bytea OR p.period_return IS NOT NULL)) + (SELECT count(*) FROM income_components p WHERE p.run_id=p_run AND (p.canonical_row <> '\x'::bytea OR p.net IS NOT NULL OR p.gross IS NOT NULL OR p.withholding IS NOT NULL)) + (SELECT count(*) FROM attribution_components p WHERE p.run_id=p_run AND (p.canonical_row <> '\x'::bytea OR p.gain IS NOT NULL OR p.return_contribution IS NOT NULL)) + (SELECT count(*) FROM historical_cash_flow_points p WHERE p.run_id=p_run AND (p.canonical_row <> '\x'::bytea OR p.amount IS NOT NULL)) + (SELECT count(*) FROM historical_conversions p WHERE p.run_id=p_run AND (p.rate IS NOT NULL)) + (SELECT count(*) FROM historical_composite_benchmarks p WHERE p.run_id=p_run AND (p.canonical_composite <> '\x'::bytea)); $$;

CREATE FUNCTION phase2_xray_parent_drain_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.canonical_payload<>'\x'::bytea THEN RETURN NEW; END IF;
 IF TG_TABLE_NAME='xray_exposure_paths' THEN
  IF EXISTS(SELECT 1 FROM xray_path_edges WHERE owner_id=NEW.owner_id AND path_id=NEW.id) THEN
   RAISE EXCEPTION 'X-ray path edges remain pending' USING ERRCODE='23514'; END IF;
 ELSE
  IF EXISTS(SELECT 1 FROM xray_fund_entities WHERE owner_id=NEW.owner_id AND composition_id=NEW.id AND (canonical_payload<>'\x'::bytea OR relative_coefficient IS NOT NULL)) THEN
   RAISE EXCEPTION 'X-ray composition entities remain pending' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION phase2_collection_root_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM collection_query_snapshots WHERE owner_id=OLD.owner_id AND id=OLD.collection_id) THEN
  RAISE EXCEPTION 'Collection binding removal requires physical root removal' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION phase2_source_membership_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE mismatch boolean;
BEGIN
 IF TG_TABLE_NAME='xray_input_snapshots' THEN
  WITH expected AS (SELECT d.id AS dependency_id,d.owner_id,d.input_id,'fx'::varchar(24) AS source_kind,d.fx_snapshot_id AS source_id FROM xray_input_dependencies d WHERE d.input_id=NEW.id AND d.owner_id=NEW.owner_id AND d.fx_snapshot_id IS NOT NULL UNION ALL SELECT d.id AS dependency_id,d.owner_id,d.input_id,'entity_evidence'::varchar(24) AS source_kind,d.entity_evidence_version_id AS source_id FROM xray_input_dependencies d WHERE d.input_id=NEW.id AND d.owner_id=NEW.owner_id AND d.entity_evidence_version_id IS NOT NULL UNION ALL SELECT d.id AS dependency_id,d.owner_id,d.input_id,'classification'::varchar(24) AS source_kind,d.classification_snapshot_id AS source_id FROM xray_input_dependencies d WHERE d.input_id=NEW.id AND d.owner_id=NEW.owner_id AND d.classification_snapshot_id IS NOT NULL UNION ALL SELECT d.id AS dependency_id,d.owner_id,d.input_id,'fund_definition'::varchar(24) AS source_kind,d.fund_definition_id AS source_id FROM xray_input_dependencies d WHERE d.input_id=NEW.id AND d.owner_id=NEW.owner_id AND d.fund_definition_id IS NOT NULL UNION ALL SELECT d.id AS dependency_id,d.owner_id,d.input_id,'fund_mapping'::varchar(24) AS source_kind,d.fund_mapping_id AS source_id FROM xray_input_dependencies d WHERE d.input_id=NEW.id AND d.owner_id=NEW.owner_id AND d.fund_mapping_id IS NOT NULL UNION ALL SELECT d.id AS dependency_id,d.owner_id,d.input_id,'constituent'::varchar(24) AS source_kind,d.constituent_snapshot_id AS source_id FROM xray_input_dependencies d WHERE d.input_id=NEW.id AND d.owner_id=NEW.owner_id AND d.constituent_snapshot_id IS NOT NULL), actual AS (SELECT dependency_id,owner_id,input_id,source_kind,source_id FROM xray_retained_sources WHERE input_id=NEW.id AND owner_id=NEW.owner_id)
  SELECT EXISTS((SELECT * FROM expected EXCEPT SELECT * FROM actual) UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM expected)) INTO mismatch;
 ELSE
  WITH expected AS (SELECT d.id AS dependency_id,d.id AS leaf_id,d.owner_id,d.input_id,'price'::varchar(24) AS source_kind,d.price_snapshot_id AS source_id FROM historical_dependencies d WHERE d.input_id=NEW.id AND d.owner_id=NEW.owner_id AND d.price_snapshot_id IS NOT NULL UNION ALL SELECT d.id AS dependency_id,l.id AS leaf_id,d.owner_id,d.input_id,'price'::varchar(24) AS source_kind,l.price_snapshot_id AS source_id FROM historical_dependencies d JOIN historical_dependencies l ON l.owner_id=d.owner_id AND l.evidence_id=d.registered_evidence_id WHERE d.input_id=NEW.id AND d.owner_id=NEW.owner_id AND l.price_snapshot_id IS NOT NULL UNION ALL SELECT d.id AS dependency_id,d.id AS leaf_id,d.owner_id,d.input_id,'fx'::varchar(24) AS source_kind,d.fx_snapshot_id AS source_id FROM historical_dependencies d WHERE d.input_id=NEW.id AND d.owner_id=NEW.owner_id AND d.fx_snapshot_id IS NOT NULL UNION ALL SELECT d.id AS dependency_id,l.id AS leaf_id,d.owner_id,d.input_id,'fx'::varchar(24) AS source_kind,l.fx_snapshot_id AS source_id FROM historical_dependencies d JOIN historical_dependencies l ON l.owner_id=d.owner_id AND l.evidence_id=d.registered_evidence_id WHERE d.input_id=NEW.id AND d.owner_id=NEW.owner_id AND l.fx_snapshot_id IS NOT NULL UNION ALL SELECT d.id AS dependency_id,d.id AS leaf_id,d.owner_id,d.input_id,'corporate_action'::varchar(24) AS source_kind,d.action_snapshot_id AS source_id FROM historical_dependencies d WHERE d.input_id=NEW.id AND d.owner_id=NEW.owner_id AND d.action_snapshot_id IS NOT NULL UNION ALL SELECT d.id AS dependency_id,l.id AS leaf_id,d.owner_id,d.input_id,'corporate_action'::varchar(24) AS source_kind,l.action_snapshot_id AS source_id FROM historical_dependencies d JOIN historical_dependencies l ON l.owner_id=d.owner_id AND l.evidence_id=d.registered_evidence_id WHERE d.input_id=NEW.id AND d.owner_id=NEW.owner_id AND l.action_snapshot_id IS NOT NULL UNION ALL SELECT d.id AS dependency_id,d.id AS leaf_id,d.owner_id,d.input_id,'benchmark'::varchar(24) AS source_kind,d.benchmark_snapshot_id AS source_id FROM historical_dependencies d WHERE d.input_id=NEW.id AND d.owner_id=NEW.owner_id AND d.benchmark_snapshot_id IS NOT NULL UNION ALL SELECT d.id AS dependency_id,l.id AS leaf_id,d.owner_id,d.input_id,'benchmark'::varchar(24) AS source_kind,l.benchmark_snapshot_id AS source_id FROM historical_dependencies d JOIN historical_dependencies l ON l.owner_id=d.owner_id AND l.evidence_id=d.registered_evidence_id WHERE d.input_id=NEW.id AND d.owner_id=NEW.owner_id AND l.benchmark_snapshot_id IS NOT NULL), actual AS (SELECT dependency_id,leaf_id,owner_id,input_id,source_kind,source_id FROM historical_retained_sources WHERE input_id=NEW.id AND owner_id=NEW.owner_id)
  SELECT EXISTS((SELECT * FROM expected EXCEPT SELECT * FROM actual) UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM expected)) INTO mismatch;
 END IF;
 IF mismatch THEN RAISE EXCEPTION 'Complete retained source membership differs from original dependencies' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
"""


_BACKFILL = r"""INSERT INTO xray_physical_state(input_id,owner_id,input_pending,payload_rows) SELECT id,owner_id,canonical_input<>'\x'::bytea,phase2_xray_rows_oracle(id) FROM xray_input_snapshots;
INSERT INTO historical_physical_runs(run_id,owner_id,input_id,child_rows,analytics_pending) SELECT r.id,r.owner_id,r.input_id,phase2_historical_rows_oracle(r.id),(a.canonical_input<>'\x'::bytea OR a.canonical_result<>'\x'::bytea) FROM historical_analytics_runs r JOIN analytics_runs a ON a.id=r.analytics_run_id;
INSERT INTO historical_composite_physical(snapshot_id,owner_id,point_rows) SELECT s.id,s.owner_id,(SELECT count(*) FROM benchmark_composite_points p WHERE p.snapshot_id=s.id AND (p.canonical_point<>'\x'::bytea OR p.wealth IS NOT NULL OR p.interval_return IS NOT NULL)) FROM benchmark_snapshots s WHERE s.snapshot_kind='composite';
INSERT INTO xray_retained_sources(dependency_id,owner_id,input_id,source_kind,source_id) SELECT d.id,d.owner_id,d.input_id,'fx',d.fx_snapshot_id FROM xray_input_dependencies d WHERE d.fx_snapshot_id IS NOT NULL AND phase2_input_pending(d.owner_id,'xray',d.input_id);
INSERT INTO xray_retained_sources(dependency_id,owner_id,input_id,source_kind,source_id) SELECT d.id,d.owner_id,d.input_id,'entity_evidence',d.entity_evidence_version_id FROM xray_input_dependencies d WHERE d.entity_evidence_version_id IS NOT NULL AND phase2_input_pending(d.owner_id,'xray',d.input_id);
INSERT INTO xray_retained_sources(dependency_id,owner_id,input_id,source_kind,source_id) SELECT d.id,d.owner_id,d.input_id,'classification',d.classification_snapshot_id FROM xray_input_dependencies d WHERE d.classification_snapshot_id IS NOT NULL AND phase2_input_pending(d.owner_id,'xray',d.input_id);
INSERT INTO xray_retained_sources(dependency_id,owner_id,input_id,source_kind,source_id) SELECT d.id,d.owner_id,d.input_id,'fund_definition',d.fund_definition_id FROM xray_input_dependencies d WHERE d.fund_definition_id IS NOT NULL AND phase2_input_pending(d.owner_id,'xray',d.input_id);
INSERT INTO xray_retained_sources(dependency_id,owner_id,input_id,source_kind,source_id) SELECT d.id,d.owner_id,d.input_id,'fund_mapping',d.fund_mapping_id FROM xray_input_dependencies d WHERE d.fund_mapping_id IS NOT NULL AND phase2_input_pending(d.owner_id,'xray',d.input_id);
INSERT INTO xray_retained_sources(dependency_id,owner_id,input_id,source_kind,source_id) SELECT d.id,d.owner_id,d.input_id,'constituent',d.constituent_snapshot_id FROM xray_input_dependencies d WHERE d.constituent_snapshot_id IS NOT NULL AND phase2_input_pending(d.owner_id,'xray',d.input_id);
INSERT INTO historical_retained_sources(dependency_id,leaf_id,owner_id,input_id,source_kind,source_id) SELECT d.id,d.id,d.owner_id,d.input_id,'price',d.price_snapshot_id FROM historical_dependencies d WHERE d.input_id IS NOT NULL AND d.price_snapshot_id IS NOT NULL AND phase2_input_pending(d.owner_id,'historical',d.input_id);
INSERT INTO historical_retained_sources(dependency_id,leaf_id,owner_id,input_id,source_kind,source_id) SELECT d.id,l.id,d.owner_id,d.input_id,'price',l.price_snapshot_id FROM historical_dependencies d JOIN historical_dependencies l ON l.owner_id=d.owner_id AND l.evidence_id=d.registered_evidence_id WHERE d.input_id IS NOT NULL AND l.price_snapshot_id IS NOT NULL AND phase2_input_pending(d.owner_id,'historical',d.input_id);
INSERT INTO historical_retained_sources(dependency_id,leaf_id,owner_id,input_id,source_kind,source_id) SELECT d.id,d.id,d.owner_id,d.input_id,'fx',d.fx_snapshot_id FROM historical_dependencies d WHERE d.input_id IS NOT NULL AND d.fx_snapshot_id IS NOT NULL AND phase2_input_pending(d.owner_id,'historical',d.input_id);
INSERT INTO historical_retained_sources(dependency_id,leaf_id,owner_id,input_id,source_kind,source_id) SELECT d.id,l.id,d.owner_id,d.input_id,'fx',l.fx_snapshot_id FROM historical_dependencies d JOIN historical_dependencies l ON l.owner_id=d.owner_id AND l.evidence_id=d.registered_evidence_id WHERE d.input_id IS NOT NULL AND l.fx_snapshot_id IS NOT NULL AND phase2_input_pending(d.owner_id,'historical',d.input_id);
INSERT INTO historical_retained_sources(dependency_id,leaf_id,owner_id,input_id,source_kind,source_id) SELECT d.id,d.id,d.owner_id,d.input_id,'corporate_action',d.action_snapshot_id FROM historical_dependencies d WHERE d.input_id IS NOT NULL AND d.action_snapshot_id IS NOT NULL AND phase2_input_pending(d.owner_id,'historical',d.input_id);
INSERT INTO historical_retained_sources(dependency_id,leaf_id,owner_id,input_id,source_kind,source_id) SELECT d.id,l.id,d.owner_id,d.input_id,'corporate_action',l.action_snapshot_id FROM historical_dependencies d JOIN historical_dependencies l ON l.owner_id=d.owner_id AND l.evidence_id=d.registered_evidence_id WHERE d.input_id IS NOT NULL AND l.action_snapshot_id IS NOT NULL AND phase2_input_pending(d.owner_id,'historical',d.input_id);
INSERT INTO historical_retained_sources(dependency_id,leaf_id,owner_id,input_id,source_kind,source_id) SELECT d.id,d.id,d.owner_id,d.input_id,'benchmark',d.benchmark_snapshot_id FROM historical_dependencies d WHERE d.input_id IS NOT NULL AND d.benchmark_snapshot_id IS NOT NULL AND phase2_input_pending(d.owner_id,'historical',d.input_id);
INSERT INTO historical_retained_sources(dependency_id,leaf_id,owner_id,input_id,source_kind,source_id) SELECT d.id,l.id,d.owner_id,d.input_id,'benchmark',l.benchmark_snapshot_id FROM historical_dependencies d JOIN historical_dependencies l ON l.owner_id=d.owner_id AND l.evidence_id=d.registered_evidence_id WHERE d.input_id IS NOT NULL AND l.benchmark_snapshot_id IS NOT NULL AND phase2_input_pending(d.owner_id,'historical',d.input_id);
"""


_GUARDS = r"""
CREATE FUNCTION phase2_source_erasure_authorized(p_owner uuid,p_kind text,p_source uuid,p_at timestamptz) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE source_table text; reference text; header record; started timestamptz;
BEGIN
 SELECT v.t,v.r INTO source_table,reference FROM (VALUES
 ('price','price_snapshots','price_snapshot_id'),('fx','fx_snapshots','fx_snapshot_id'),
 ('corporate_action','corporate_action_snapshots','corporate_action_snapshot_id'),('benchmark','benchmark_snapshots','benchmark_snapshot_id'),
 ('constituent','constituent_snapshots','constituent_snapshot_id'),('entity_evidence','entity_evidence_versions','entity_evidence_version_id'),
 ('classification','classification_snapshots','classification_snapshot_id'),('fund_definition','fund_definitions','fund_definition_id'),('fund_mapping','fund_source_mappings','fund_mapping_id')) v(k,t,r) WHERE v.k=p_kind;
 IF source_table IS NULL THEN RETURN false; END IF;
 EXECUTE format('SELECT expires_at,content_digest FROM %I WHERE owner_id=$1 AND id=$2',source_table) INTO header USING p_owner,p_source;
 IF header.expires_at IS NULL THEN RETURN false; END IF;
 IF header.expires_at<=p_at THEN RETURN true; END IF;
 IF p_kind IN ('price','fx','corporate_action','benchmark','constituent') THEN
  EXECUTE format('SELECT started_at FROM source_retention_work WHERE owner_id=$1 AND %I=$2 AND content_digest=$3',reference) INTO started USING p_owner,p_source,header.content_digest;
 ELSE
  EXECUTE format('SELECT started_at FROM enrichment_retention_work WHERE owner_id=$1 AND %I=$2 AND content_digest=$3',reference) INTO started USING p_owner,p_source,header.content_digest;
 END IF;
 RETURN started IS NOT NULL AND started<=p_at;
END $$;
CREATE OR REPLACE FUNCTION xray_payloads_pending(input uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT COALESCE((SELECT payload_rows>0 FROM xray_physical_state WHERE input_id=input),true);
$$;
CREATE OR REPLACE FUNCTION historical_retention_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE selected_input uuid; registered uuid; leaf_input uuid; evidence uuid; p_kind text; p_source uuid;
BEGIN
 PERFORM phase2_owner_lock(NEW.owner_id);
 SELECT input_id,registered_evidence_id INTO selected_input,registered FROM historical_dependencies WHERE id=NEW.dependency_id AND owner_id=NEW.owner_id;
 IF selected_input IS DISTINCT FROM NEW.input_id THEN RAISE EXCEPTION 'Historical retention dependency mismatch' USING ERRCODE='23514'; END IF;
 SELECT d.input_id,d.evidence_id,v.kind,v.source INTO leaf_input,evidence,p_kind,p_source
  FROM historical_dependencies d CROSS JOIN LATERAL (VALUES
  ('price',d.price_snapshot_id),('fx',d.fx_snapshot_id),('corporate_action',d.action_snapshot_id),('benchmark',d.benchmark_snapshot_id)) v(kind,source)
  WHERE d.id=COALESCE(NEW.source_dependency_id,NEW.dependency_id) AND d.owner_id=NEW.owner_id AND v.source IS NOT NULL;
 IF (NEW.source_dependency_id IS NULL AND leaf_input IS DISTINCT FROM NEW.input_id)
  OR (NEW.source_dependency_id IS NOT NULL AND (registered IS NULL OR evidence IS DISTINCT FROM registered OR leaf_input IS NOT NULL))
  OR NOT phase2_source_erasure_authorized(NEW.owner_id,p_kind,p_source,NEW.removed_at) THEN
  RAISE EXCEPTION 'Historical retention authorization mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION xray_retention_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p_input uuid; p_kind text; p_source uuid;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'X-ray retention evidence is immutable' USING ERRCODE='23514'; END IF;
 PERFORM phase2_owner_lock(NEW.owner_id);
 SELECT d.input_id,v.kind,v.source INTO p_input,p_kind,p_source FROM xray_input_dependencies d
 CROSS JOIN LATERAL (VALUES('fx',d.fx_snapshot_id),('entity_evidence',d.entity_evidence_version_id),('classification',d.classification_snapshot_id),('fund_definition',d.fund_definition_id),('fund_mapping',d.fund_mapping_id),('constituent',d.constituent_snapshot_id)) v(kind,source)
 WHERE d.id=NEW.dependency_id AND d.owner_id=NEW.owner_id AND v.source IS NOT NULL;
 IF p_input IS DISTINCT FROM NEW.input_id OR NOT phase2_source_erasure_authorized(NEW.owner_id,p_kind,p_source,NEW.expired_at) THEN
  RAISE EXCEPTION 'X-ray retention requires an exact restricted source' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
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
 ELSIF relation='analytics_runs' THEN
  SELECT r.input_id INTO input FROM historical_analytics_runs r JOIN historical_physical_runs s ON s.run_id=r.id AND s.owner_id=r.owner_id
  WHERE r.analytics_run_id=(old_row->>'id')::uuid AND r.owner_id=(old_row->>'owner_id')::uuid AND s.child_rows=0;
  IF input IS NULL OR EXISTS(SELECT 1 FROM historical_analytics_runs r
   JOIN historical_composite_benchmarks c ON c.run_id=r.id AND c.owner_id=r.owner_id
   JOIN historical_composite_physical p ON p.snapshot_id=c.snapshot_id AND p.owner_id=c.owner_id
   WHERE r.analytics_run_id=(old_row->>'id')::uuid AND r.owner_id=(old_row->>'owner_id')::uuid AND p.point_rows>0) THEN RETURN false; END IF;
 ELSIF relation='benchmark_composite_points' THEN
  SELECT r.input_id INTO input FROM historical_composite_erasures w JOIN historical_analytics_runs r ON r.id=w.run_id AND r.owner_id=w.owner_id
  WHERE w.snapshot_id=(old_row->>'snapshot_id')::uuid AND w.owner_id=(old_row->>'owner_id')::uuid;
 ELSIF relation='historical_composite_benchmarks' THEN
  IF NOT EXISTS(SELECT 1 FROM historical_composite_physical WHERE owner_id=(old_row->>'owner_id')::uuid AND snapshot_id=(old_row->>'snapshot_id')::uuid AND point_rows=0) THEN RETURN false; END IF;
  SELECT input_id INTO input FROM historical_analytics_runs WHERE id=(old_row->>'run_id')::uuid AND owner_id=(old_row->>'owner_id')::uuid;
 ELSE SELECT input_id INTO input FROM historical_analytics_runs WHERE id=(old_row->>'run_id')::uuid AND owner_id=(old_row->>'owner_id')::uuid;
 END IF;
 RETURN EXISTS(SELECT 1 FROM historical_retention_events WHERE input_id=input AND owner_id=(old_row->>'owner_id')::uuid);
END $$;
CREATE OR REPLACE FUNCTION source_retention_work_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE reference text; snapshot uuid; retained record; old_rank integer; new_rank integer; kind text;
BEGIN
 PERFORM phase2_owner_lock(NEW.owner_id);
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Source retention work must be retained' USING ERRCODE='23514'; END IF;
 reference := CASE WHEN NEW.price_snapshot_id IS NOT NULL THEN 'price_snapshot' WHEN NEW.fx_snapshot_id IS NOT NULL THEN 'fx_snapshot' WHEN NEW.benchmark_snapshot_id IS NOT NULL THEN 'benchmark_snapshot' WHEN NEW.constituent_snapshot_id IS NOT NULL THEN 'constituent_snapshot' ELSE 'corporate_action_snapshot' END;
 snapshot := (to_jsonb(NEW)->>(reference||'_id'))::uuid;
 EXECUTE format('SELECT expires_at,content_digest FROM %I WHERE id=$1 AND owner_id=$2',reference||'s') INTO retained USING snapshot,NEW.owner_id;
 kind:=replace(reference,'_snapshot','');
 IF retained.expires_at IS NULL OR retained.content_digest IS DISTINCT FROM NEW.content_digest OR
  (TG_OP='INSERT' AND retained.expires_at>NEW.started_at AND (kind NOT IN ('price','fx') OR acquisition_source_restricted(NEW.owner_id,kind,snapshot,NEW.started_at,'store') IS DISTINCT FROM true)) THEN
  RAISE EXCEPTION 'Source pending retention authorization mismatch' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.phase<>'copies' OR NEW.removed_observation_count<>0 OR NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'Source retention must start pending' USING ERRCODE='23514'; END IF;
 ELSE
  IF (to_jsonb(OLD)-ARRAY['phase','removed_observation_count','completed_at']) IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['phase','removed_observation_count','completed_at']) THEN RAISE EXCEPTION 'Source retention identity is immutable' USING ERRCODE='23514'; END IF;
  old_rank:=array_position(ARRAY['copies','observations','coverage','complete'],OLD.phase);
  new_rank:=array_position(ARRAY['copies','observations','coverage','complete'],NEW.phase);
  IF OLD.phase='complete' OR new_rank<old_rank OR new_rank>old_rank+1 OR NEW.removed_observation_count<OLD.removed_observation_count OR (NEW.removed_observation_count<>OLD.removed_observation_count AND OLD.phase<>'observations') THEN RAISE EXCEPTION 'Source retention progress must be monotonic' USING ERRCODE='23514'; END IF;
  IF OLD.phase='copies' AND NEW.phase='observations' AND kind='benchmark' AND EXISTS(SELECT 1 FROM historical_composite_physical WHERE owner_id=NEW.owner_id AND snapshot_id=snapshot AND point_rows>0) THEN RAISE EXCEPTION 'Composite point copies remain pending' USING ERRCODE='23514'; END IF;
  IF OLD.phase='copies' AND NEW.phase='observations' AND phase2_source_copies_pending(NEW.owner_id,kind,snapshot) THEN RAISE EXCEPTION 'Source copies remain pending' USING ERRCODE='23514'; END IF;
  IF NEW.phase='complete' THEN
   EXECUTE format('SELECT removed_at,removed_observation_count FROM source_expiry_events WHERE owner_id=$1 AND %I=$2',reference||'_id') INTO retained USING NEW.owner_id,snapshot;
   IF retained.removed_at IS NULL OR retained.removed_at IS DISTINCT FROM NEW.completed_at OR retained.removed_observation_count<>NEW.removed_observation_count THEN RAISE EXCEPTION 'Source retention completion requires exact expiry evidence' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION source_expiry_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE reference text; snapshot uuid; retained record; work record; pending boolean; observation_table text;
BEGIN
 PERFORM phase2_owner_lock(NEW.owner_id);
 reference := CASE WHEN NEW.price_snapshot_id IS NOT NULL THEN 'price_snapshot' WHEN NEW.fx_snapshot_id IS NOT NULL THEN 'fx_snapshot' WHEN NEW.benchmark_snapshot_id IS NOT NULL THEN 'benchmark_snapshot' WHEN NEW.constituent_snapshot_id IS NOT NULL THEN 'constituent_snapshot' ELSE 'corporate_action_snapshot' END;
 snapshot := (to_jsonb(NEW)->>(reference||'_id'))::uuid;
 EXECUTE format('SELECT expires_at,content_digest FROM %I WHERE id=$1 AND owner_id=$2',reference||'s') INTO retained USING snapshot,NEW.owner_id;
 IF retained.expires_at IS NULL OR retained.content_digest IS DISTINCT FROM NEW.content_digest THEN RAISE EXCEPTION 'Source retention authorization mismatch' USING ERRCODE='23514'; END IF;
 EXECUTE format('SELECT phase,started_at,removed_observation_count FROM source_retention_work WHERE owner_id=$1 AND %I=$2',reference||'_id') INTO work USING NEW.owner_id,snapshot;
 IF work.phase IS DISTINCT FROM 'coverage' OR work.started_at>NEW.removed_at OR work.removed_observation_count IS DISTINCT FROM NEW.removed_observation_count THEN RAISE EXCEPTION 'Source expiry requires completed pending phases' USING ERRCODE='23514'; END IF;
 observation_table:=CASE WHEN reference='constituent_snapshot' THEN 'constituent_holdings' ELSE replace(reference,'snapshot','observations') END;
 EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I WHERE owner_id=$1 AND snapshot_id=$2)',observation_table) INTO pending USING NEW.owner_id,snapshot;
 IF pending THEN RAISE EXCEPTION 'Source observation payload remains pending' USING ERRCODE='23514'; END IF;
 EXECUTE format('SELECT EXISTS(SELECT 1 FROM source_coverage_gaps WHERE owner_id=$1 AND %I=$2)',reference||'_id') INTO pending USING NEW.owner_id,snapshot;
 IF pending THEN RAISE EXCEPTION 'Source coverage payload remains pending' USING ERRCODE='23514'; END IF;

 IF reference='benchmark_snapshot' AND EXISTS(SELECT 1 FROM historical_composite_physical WHERE owner_id=NEW.owner_id AND snapshot_id=snapshot AND point_rows>0) THEN RAISE EXCEPTION 'Composite point copies remain pending' USING ERRCODE='23514'; END IF;
 IF phase2_source_copies_pending(NEW.owner_id,replace(reference,'_snapshot',''),snapshot) THEN
  RAISE EXCEPTION 'Source copied payload remains pending' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION enrichment_retention_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b jsonb:=to_jsonb(NEW); reference text; source uuid; retained record; work record; old_rank integer; new_rank integer; pending boolean;
BEGIN
 PERFORM phase2_owner_lock(CASE WHEN TG_OP='DELETE' THEN OLD.owner_id ELSE NEW.owner_id END);
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
    SELECT EXISTS(SELECT 1 FROM xray_retained_sources WHERE owner_id=NEW.owner_id AND source_id=source AND source_kind=CASE reference WHEN 'entity_evidence_version_id' THEN 'entity_evidence' WHEN 'classification_snapshot_id' THEN 'classification' WHEN 'fund_definition_id' THEN 'fund_definition' ELSE 'fund_mapping' END)
     INTO pending;
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
  SELECT EXISTS(SELECT 1 FROM xray_retained_sources WHERE owner_id=NEW.owner_id AND source_id=source AND source_kind=CASE reference WHEN 'entity_evidence_version_id' THEN 'entity_evidence' WHEN 'classification_snapshot_id' THEN 'classification' WHEN 'fund_definition_id' THEN 'fund_definition' ELSE 'fund_mapping' END)
   INTO pending;
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


_TRIGGERS = r"""CREATE TRIGGER phase2_counter_owned BEFORE INSERT OR UPDATE OR DELETE ON xray_physical_state FOR EACH ROW EXECUTE FUNCTION phase2_counter_guard();
CREATE TRIGGER phase2_counter_owned BEFORE INSERT OR UPDATE OR DELETE ON historical_physical_runs FOR EACH ROW EXECUTE FUNCTION phase2_counter_guard();
CREATE TRIGGER phase2_counter_owned BEFORE INSERT OR UPDATE OR DELETE ON historical_composite_physical FOR EACH ROW EXECUTE FUNCTION phase2_counter_guard();
CREATE TRIGGER phase2_source_owned BEFORE INSERT OR UPDATE OR DELETE ON xray_retained_sources FOR EACH ROW EXECUTE FUNCTION phase2_retained_source_guard();
CREATE TRIGGER phase2_source_owned BEFORE INSERT OR UPDATE OR DELETE ON historical_retained_sources FOR EACH ROW EXECUTE FUNCTION phase2_retained_source_guard();
CREATE TRIGGER phase2_erasure_owned BEFORE INSERT OR UPDATE OR DELETE ON historical_composite_erasures FOR EACH ROW EXECUTE FUNCTION phase2_composite_erasure_guard();
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE ON xray_input_snapshots FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_input');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON xray_input_positions FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_position');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON xray_input_cash FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_cash');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON xray_input_dependencies FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_reference');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON xray_input_source_selections FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_selection');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON xray_run_sources FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_use');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON xray_runs FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_summary,canonical_reconciliation,canonical_exact_state');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON xray_dimensions FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_payload');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON xray_warnings FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_payload');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON xray_residuals FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_payload');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON xray_classification_decisions FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_payload');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON xray_direct_positions FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_payload');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON xray_held_funds FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_payload');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON xray_exposure_paths FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_payload');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON xray_fund_compositions FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_payload');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON xray_exposures FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_payload,bucket_key');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON xray_path_edges FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_edge');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON xray_fund_entities FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_payload,relative_coefficient');
CREATE TRIGGER phase2_xray_copy_counter AFTER UPDATE OR DELETE ON analytics_runs FOR EACH ROW EXECUTE FUNCTION phase2_xray_counter('canonical_input,canonical_result');
CREATE TRIGGER phase2_copy_counter AFTER INSERT ON historical_analytics_runs FOR EACH ROW EXECUTE FUNCTION phase2_historical_counter();
CREATE TRIGGER phase2_historical_copy_counter AFTER UPDATE OR DELETE ON analytics_runs FOR EACH ROW EXECUTE FUNCTION phase2_historical_counter();
CREATE TRIGGER phase2_copy_counter AFTER INSERT ON benchmark_snapshots FOR EACH ROW EXECUTE FUNCTION phase2_historical_counter();
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON benchmark_composite_points FOR EACH ROW EXECUTE FUNCTION phase2_historical_counter();
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON performance_points FOR EACH ROW EXECUTE FUNCTION phase2_historical_counter('canonical_row,portfolio_value,cash_value,wealth,period_return');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON performance_period_returns FOR EACH ROW EXECUTE FUNCTION phase2_historical_counter('canonical_row,period_return');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON income_components FOR EACH ROW EXECUTE FUNCTION phase2_historical_counter('canonical_row,net,gross,withholding');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON attribution_components FOR EACH ROW EXECUTE FUNCTION phase2_historical_counter('canonical_row,gain,return_contribution');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON historical_cash_flow_points FOR EACH ROW EXECUTE FUNCTION phase2_historical_counter('canonical_row,amount');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON historical_conversions FOR EACH ROW EXECUTE FUNCTION phase2_historical_counter('rate');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR UPDATE OR DELETE ON historical_composite_benchmarks FOR EACH ROW EXECUTE FUNCTION phase2_historical_counter('canonical_composite');
CREATE TRIGGER phase2_copy_counter AFTER INSERT OR DELETE ON xray_collection_bindings FOR EACH ROW EXECUTE FUNCTION phase2_collection_counter();
CREATE TRIGGER phase2_collection_drain BEFORE DELETE ON xray_collection_bindings FOR EACH ROW EXECUTE FUNCTION phase2_collection_drain_guard();
CREATE TRIGGER phase2_source_capture AFTER INSERT ON xray_input_dependencies FOR EACH ROW EXECUTE FUNCTION phase2_capture_sources();
CREATE TRIGGER phase2_source_capture AFTER INSERT ON historical_dependencies FOR EACH ROW EXECUTE FUNCTION phase2_capture_sources();
CREATE TRIGGER phase2_parent_drain BEFORE UPDATE ON xray_exposure_paths FOR EACH ROW EXECUTE FUNCTION phase2_xray_parent_drain_guard();
CREATE TRIGGER phase2_parent_drain BEFORE UPDATE ON xray_fund_compositions FOR EACH ROW EXECUTE FUNCTION phase2_xray_parent_drain_guard();
CREATE CONSTRAINT TRIGGER phase2_collection_complete AFTER DELETE ON xray_collection_bindings DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION phase2_collection_root_complete();
CREATE CONSTRAINT TRIGGER phase2_sources_complete AFTER INSERT ON xray_input_snapshots DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION phase2_source_membership_complete();
CREATE CONSTRAINT TRIGGER phase2_sources_complete AFTER INSERT ON historical_input_snapshots DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION phase2_source_membership_complete();
"""


_RESTORE = r"""CREATE OR REPLACE FUNCTION source_retention_work_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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

CREATE OR REPLACE FUNCTION historical_retention_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE dependency historical_dependencies; expiry timestamptz;
BEGIN
 SELECT * INTO dependency FROM historical_dependencies WHERE id=NEW.dependency_id AND owner_id=NEW.owner_id AND input_id=NEW.input_id;
 IF dependency.id IS NULL THEN RAISE EXCEPTION 'Historical retention dependency mismatch' USING ERRCODE='23514'; END IF;
 IF dependency.price_snapshot_id IS NOT NULL THEN SELECT expires_at INTO expiry FROM price_snapshots WHERE id=dependency.price_snapshot_id AND owner_id=NEW.owner_id;
 ELSIF dependency.fx_snapshot_id IS NOT NULL THEN SELECT expires_at INTO expiry FROM fx_snapshots WHERE id=dependency.fx_snapshot_id AND owner_id=NEW.owner_id;
 ELSIF dependency.action_snapshot_id IS NOT NULL THEN SELECT expires_at INTO expiry FROM corporate_action_snapshots WHERE id=dependency.action_snapshot_id AND owner_id=NEW.owner_id;
 ELSIF dependency.benchmark_snapshot_id IS NOT NULL THEN SELECT expires_at INTO expiry FROM benchmark_snapshots WHERE id=dependency.benchmark_snapshot_id AND owner_id=NEW.owner_id;
 END IF;
 IF expiry IS NULL OR expiry>NEW.removed_at THEN RAISE EXCEPTION 'Historical retention authorization mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

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

CREATE OR REPLACE FUNCTION xray_retention_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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

CREATE OR REPLACE FUNCTION enrichment_retention_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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

CREATE OR REPLACE FUNCTION xray_payloads_pending(input uuid) RETURNS boolean LANGUAGE sql STABLE AS $$ SELECT EXISTS(SELECT 1 FROM xray_input_positions p WHERE p.input_id=input AND (p.canonical_position<> '\x'::bytea)) OR EXISTS(SELECT 1 FROM xray_input_cash p WHERE p.input_id=input AND (p.canonical_cash<> '\x'::bytea)) OR EXISTS(SELECT 1 FROM xray_input_dependencies p WHERE p.input_id=input AND (p.canonical_reference<> '\x'::bytea)) OR EXISTS(SELECT 1 FROM xray_input_source_selections p WHERE p.input_id=input AND (p.canonical_selection<> '\x'::bytea)) OR EXISTS(SELECT 1 FROM xray_run_sources p WHERE p.run_id IN (SELECT r.id FROM xray_runs r WHERE r.input_id=input) AND (p.canonical_use<> '\x'::bytea)) OR EXISTS(SELECT 1 FROM xray_runs p WHERE p.input_id=input AND (p.canonical_summary<> '\x'::bytea OR p.canonical_reconciliation<> '\x'::bytea OR p.canonical_exact_state<> '\x'::bytea)) OR EXISTS(SELECT 1 FROM xray_dimensions p WHERE p.run_id IN (SELECT r.id FROM xray_runs r WHERE r.input_id=input) AND (p.canonical_payload<> '\x'::bytea)) OR EXISTS(SELECT 1 FROM xray_warnings p WHERE p.run_id IN (SELECT r.id FROM xray_runs r WHERE r.input_id=input) AND (p.canonical_payload<> '\x'::bytea)) OR EXISTS(SELECT 1 FROM xray_residuals p WHERE p.run_id IN (SELECT r.id FROM xray_runs r WHERE r.input_id=input) AND (p.canonical_payload<> '\x'::bytea)) OR EXISTS(SELECT 1 FROM xray_classification_decisions p WHERE p.run_id IN (SELECT r.id FROM xray_runs r WHERE r.input_id=input) AND (p.canonical_payload<> '\x'::bytea)) OR EXISTS(SELECT 1 FROM xray_direct_positions p WHERE p.run_id IN (SELECT r.id FROM xray_runs r WHERE r.input_id=input) AND (p.canonical_payload<> '\x'::bytea)) OR EXISTS(SELECT 1 FROM xray_held_funds p WHERE p.run_id IN (SELECT r.id FROM xray_runs r WHERE r.input_id=input) AND (p.canonical_payload<> '\x'::bytea)) OR EXISTS(SELECT 1 FROM xray_exposures p WHERE p.run_id IN (SELECT r.id FROM xray_runs r WHERE r.input_id=input) AND (p.canonical_payload<> '\x'::bytea OR p.bucket_key IS NOT NULL)) OR EXISTS(SELECT 1 FROM xray_exposure_paths p WHERE p.run_id IN (SELECT r.id FROM xray_runs r WHERE r.input_id=input) AND (p.canonical_payload<> '\x'::bytea)) OR EXISTS(SELECT 1 FROM xray_path_edges p WHERE p.path_id IN (SELECT t.id FROM xray_exposure_paths t JOIN xray_runs r ON r.id=t.run_id WHERE r.input_id=input) AND (p.canonical_edge<> '\x'::bytea)) OR EXISTS(SELECT 1 FROM xray_fund_compositions p WHERE p.run_id IN (SELECT r.id FROM xray_runs r WHERE r.input_id=input) AND (p.canonical_payload<> '\x'::bytea)) OR EXISTS(SELECT 1 FROM xray_fund_entities p WHERE p.composition_id IN (SELECT c.id FROM xray_fund_compositions c JOIN xray_runs r ON r.id=c.run_id WHERE r.input_id=input) AND (p.canonical_payload<> '\x'::bytea OR p.relative_coefficient IS NOT NULL)) OR EXISTS(SELECT 1 FROM analytics_runs a JOIN xray_runs r ON r.analytics_run_id=a.id WHERE r.input_id=input AND (a.canonical_input<>'\x'::bytea OR a.canonical_result<>'\x'::bytea)) OR EXISTS(SELECT 1 FROM xray_collection_bindings b JOIN xray_runs r ON r.id=b.run_id WHERE r.input_id=input) $$;
"""
