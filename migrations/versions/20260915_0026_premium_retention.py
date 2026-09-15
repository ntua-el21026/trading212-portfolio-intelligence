"""Indexed risk/scenario cleanup state and shared sensitivity copy ownership.

Revision ID:20260915_0026; down revision20260915_0025.
Existing published financial bytes and original read/seal authority are preserved.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0026"
down_revision = "20260915_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # All backfill is migration-only; source guards are restored before return.
    op.execute(_DDL)
    for table, column, kind, default in _COLUMNS:
        op.add_column(
            table,
            sa.Column(
                column,
                sa.Boolean() if kind == "boolean" else sa.Uuid(),
                nullable=default is None,
                server_default=None if default is None else sa.text(default),
            ),
        )
    for table in _SOURCE_BACKFILL_TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE TRIGGER scenario_source_guard")
    op.execute(_BACKFILL)
    for table in _SOURCE_BACKFILL_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE TRIGGER scenario_source_guard")
    for name, table, columns in _INDICES:
        op.create_index(name, table, columns)
    op.execute(_RUN)
    op.execute(_SOURCE)
    for table, name, event, function in _TRIGGERS:
        op.execute(
            f"CREATE TRIGGER {name} {event} ON {table} FOR EACH ROW EXECUTE FUNCTION {function}"
        )


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
     IF EXISTS(SELECT 1 FROM premium_retention_scans WHERE phase<>9)
      OR EXISTS(SELECT 1 FROM premium_retention_sweeps WHERE after_id IS NOT NULL OR deferred)
      OR EXISTS(SELECT 1 FROM scenario_sensitivity_retention WHERE evidence_after_id IS NOT NULL)
     THEN RAISE EXCEPTION 'Premium cleanup continuation must finish before downgrade' USING ERRCODE='23514'; END IF;
    END $$;""")
    for table, name, _event, _function in reversed(_TRIGGERS):
        op.execute(f"DROP TRIGGER {name} ON {table}")
    op.execute(_PREVIOUS)
    for function in _FUNCTIONS:
        op.execute(f"DROP FUNCTION {function}")
    for name, table, _columns in reversed(_INDICES):
        op.drop_index(name, table_name=table)
    for table, column, _kind, _default in reversed(_COLUMNS):
        op.drop_column(table, column)
    for table in (
        "premium_retention_scans",
        "premium_retention_sweeps",
        "premium_retained_parents",
        "premium_retention_state",
    ):
        op.drop_table(table)


_COLUMNS = [
    ("scenario_sensitivity_versions", "retention_closed", "boolean", "false"),
    ("scenario_sensitivity_observations", "payload_present", "boolean", "false"),
    ("scenario_sensitivity_evidence_links", "copy_pending", "boolean", "true"),
    ("scenario_sensitivity_evidence_links", "payload_pending", "boolean", "true"),
    ("scenario_sensitivity_retention", "evidence_after_id", "uuid", None),
]

_SOURCE_BACKFILL_TABLES = (
    "scenario_sensitivity_versions",
    "scenario_sensitivity_observations",
    "scenario_sensitivity_evidence_links",
)

_INDICES = [
    ("ix_risk_matrix_row_cleanup", "risk_matrix_cells", ["result_id", "row_series_id"]),
    ("ix_risk_matrix_col_cleanup", "risk_matrix_cells", ["result_id", "column_series_id"]),
    ("ix_premium_license_scan", "premium_run_licenses", ["owner_id", "run_id", "id"]),
    ("ix_scenario_version_scan", "scenario_run_sensitivity_versions", ["owner_id", "run_id", "id"]),
    ("ix_scenario_component_cleanup", "scenario_components", ["owner_id", "result_id", "id"]),
    (
        "ix_scenario_applied_cleanup",
        "scenario_applied_sensitivities",
        ["owner_id", "result_id", "id"],
    ),
    (
        "ix_sensitivity_cleanup_global",
        "scenario_sensitivity_versions",
        ["sealed", "retention_closed", "id"],
    ),
    (
        "ix_sensitivity_cleanup_owner",
        "scenario_sensitivity_versions",
        ["owner_id", "sealed", "retention_closed", "id"],
    ),
    (
        "ix_sensitivity_observation_pending",
        "scenario_sensitivity_observations",
        ["owner_id", "version_id", "payload_present", "id"],
    ),
    (
        "ix_sensitivity_evidence_owned",
        "scenario_sensitivity_evidence_links",
        ["owner_id", "evidence_id", "copy_pending", "id"],
    ),
    (
        "ix_sensitivity_version_owned",
        "scenario_sensitivity_evidence_links",
        ["owner_id", "version_id", "copy_pending", "id"],
    ),
    (
        "ix_sensitivity_version_payload",
        "scenario_sensitivity_evidence_links",
        ["owner_id", "version_id", "payload_pending", "id"],
    ),
    (
        "ix_sensitivity_link_scan",
        "scenario_sensitivity_evidence_links",
        ["owner_id", "version_id", "id"],
    ),
]

_TRIGGERS = [
    (
        "premium_retention_state",
        "premium_retention_state_guard",
        "BEFORE INSERT OR UPDATE OR DELETE",
        "premium_retention_state_guard()",
    ),
    (
        "premium_runs",
        "z_premium_retention_state",
        "AFTER INSERT",
        "premium_retention_state_create()",
    ),
    (
        "premium_retained_parents",
        "premium_retained_parent_guard",
        "BEFORE INSERT OR UPDATE OR DELETE",
        "premium_retained_parent_guard()",
    ),
    (
        "premium_retention_events",
        "z_premium_retention_complete",
        "AFTER UPDATE",
        "premium_retention_state_complete()",
    ),
    (
        "scenario_sensitivity_observation_payloads",
        "z_scenario_retention_flags",
        "AFTER INSERT OR DELETE",
        "scenario_retention_flags()",
    ),
    (
        "scenario_sensitivity_retention",
        "z_scenario_retention_flags",
        "AFTER UPDATE",
        "scenario_retention_flags()",
    ),
    (
        "risk_run_assets",
        "z_premium_retention_counter",
        "AFTER INSERT OR UPDATE OR DELETE",
        "premium_retention_counter_write()",
    ),
    (
        "risk_results",
        "z_premium_retention_counter",
        "AFTER INSERT OR UPDATE OR DELETE",
        "premium_retention_counter_write()",
    ),
    (
        "risk_series",
        "z_premium_retention_counter",
        "AFTER INSERT OR UPDATE OR DELETE",
        "premium_retention_counter_write()",
    ),
    (
        "risk_intervals",
        "z_premium_retention_counter",
        "AFTER INSERT OR UPDATE OR DELETE",
        "premium_retention_counter_write()",
    ),
    (
        "risk_matrix_cells",
        "z_premium_retention_counter",
        "AFTER INSERT OR UPDATE OR DELETE",
        "premium_retention_counter_write()",
    ),
    (
        "risk_metrics",
        "z_premium_retention_counter",
        "AFTER INSERT OR UPDATE OR DELETE",
        "premium_retention_counter_write()",
    ),
    (
        "risk_components",
        "z_premium_retention_counter",
        "AFTER INSERT OR UPDATE OR DELETE",
        "premium_retention_counter_write()",
    ),
    (
        "scenario_run_payloads",
        "z_premium_retention_counter",
        "AFTER INSERT OR UPDATE OR DELETE",
        "premium_retention_counter_write()",
    ),
    (
        "scenario_results",
        "z_premium_retention_counter",
        "AFTER INSERT OR UPDATE OR DELETE",
        "premium_retention_counter_write()",
    ),
    (
        "scenario_components",
        "z_premium_retention_counter",
        "AFTER INSERT OR UPDATE OR DELETE",
        "premium_retention_counter_write()",
    ),
    (
        "scenario_applied_sensitivities",
        "z_premium_retention_counter",
        "AFTER INSERT OR UPDATE OR DELETE",
        "premium_retention_counter_write()",
    ),
    (
        "scenario_run_sensitivity_versions",
        "z_premium_retention_counter",
        "AFTER INSERT OR UPDATE OR DELETE",
        "premium_retention_counter_write()",
    ),
    (
        "scenario_run_sensitivity_observations",
        "z_premium_retention_counter",
        "AFTER INSERT OR UPDATE OR DELETE",
        "premium_retention_counter_write()",
    ),
    (
        "scenario_run_sensitivity_memberships",
        "z_premium_retention_counter",
        "AFTER INSERT OR UPDATE OR DELETE",
        "premium_retention_counter_write()",
    ),
    (
        "scenario_run_sensitivity_evidence",
        "z_premium_retention_counter",
        "AFTER INSERT OR UPDATE OR DELETE",
        "premium_retention_counter_write()",
    ),
    ("risk_runs", "z_premium_retained_parent", "AFTER INSERT", "premium_retained_parent_capture()"),
    (
        "scenario_runs",
        "z_premium_retained_parent",
        "AFTER INSERT",
        "premium_retained_parent_capture()",
    ),
    (
        "scenario_run_sensitivity_versions",
        "z_premium_retained_parent",
        "AFTER INSERT",
        "premium_retained_parent_capture()",
    ),
    ("risk_runs", "z_premium_cleanup_epoch", "AFTER INSERT", "projection_retention_policy_epoch()"),
    (
        "scenario_runs",
        "z_premium_cleanup_epoch",
        "AFTER INSERT",
        "projection_retention_policy_epoch()",
    ),
    (
        "scenario_sensitivity_versions",
        "z_premium_cleanup_epoch",
        "AFTER INSERT",
        "projection_retention_policy_epoch()",
    ),
]

_FUNCTIONS = [
    "scenario_retention_flags()",
    "premium_retention_state_complete()",
    "premium_retained_parent_capture()",
    "premium_retained_parent_guard()",
    "premium_retained_parent_matches(uuid,uuid,uuid,text,uuid)",
    "premium_retention_counter_write()",
    "premium_retention_state_create()",
    "premium_retention_state_guard()",
]

_DDL = r"""CREATE TABLE premium_retention_state (
 run_id UUID NOT NULL,owner_id UUID NOT NULL,account_id UUID NOT NULL,kind VARCHAR(10) NOT NULL,
 financial_rows BIGINT NOT NULL DEFAULT 0,stored_bytes BIGINT NOT NULL DEFAULT 0,metadata_bytes BIGINT NOT NULL DEFAULT 0,closed BOOLEAN NOT NULL DEFAULT false,
 CONSTRAINT pk_premium_retention_state PRIMARY KEY(run_id),
 CONSTRAINT fk_premium_retention_state_run FOREIGN KEY(owner_id,account_id,run_id) REFERENCES premium_runs(owner_id,account_id,id) ON DELETE RESTRICT,
 CONSTRAINT ck_premium_retention_state_kind_bound CHECK(kind IN ('risk','scenario')),
 CONSTRAINT ck_premium_retention_state_counter_bound CHECK(financial_rows>=0 AND stored_bytes BETWEEN 0 AND 33554432 AND metadata_bytes>=0 AND (kind='scenario' OR (stored_bytes=0 AND metadata_bytes=0)))
);
CREATE INDEX ix_premium_cleanup_roots ON premium_retention_state(kind,closed,run_id);
CREATE INDEX ix_premium_cleanup_owner ON premium_retention_state(owner_id,kind,closed,run_id);
CREATE TABLE premium_retained_parents (
 id UUID NOT NULL,owner_id UUID NOT NULL,account_id UUID NOT NULL,run_id UUID NOT NULL,parent_kind VARCHAR(16) NOT NULL,parent_id UUID NOT NULL,
 CONSTRAINT pk_premium_retained_parents PRIMARY KEY(id),
 CONSTRAINT fk_premium_retained_parent_run FOREIGN KEY(owner_id,account_id,run_id) REFERENCES premium_runs(owner_id,account_id,id) ON DELETE RESTRICT,
 CONSTRAINT ck_premium_retained_parents_kind_bound CHECK(parent_kind IN ('historical','xray_input','xray_run','sensitivity'))
);
CREATE UNIQUE INDEX uq_premium_retained_parent ON premium_retained_parents(run_id,parent_kind,parent_id);
CREATE INDEX ix_premium_retained_source ON premium_retained_parents(owner_id,parent_kind,parent_id,run_id);
CREATE INDEX ix_premium_retained_cleanup ON premium_retained_parents(owner_id,run_id,id);
CREATE TABLE premium_retention_sweeps (
 scope_id UUID NOT NULL,family VARCHAR(20) NOT NULL,after_id UUID,deferred BOOLEAN NOT NULL DEFAULT false,
 policy_epoch BIGINT NOT NULL DEFAULT 0,evaluated_at TIMESTAMP WITH TIME ZONE,earliest_deadline TIMESTAMP WITH TIME ZONE,next_policy_at TIMESTAMP WITH TIME ZONE,
 CONSTRAINT pk_premium_retention_sweeps PRIMARY KEY(scope_id,family),
 CONSTRAINT ck_premium_retention_sweeps_family_bound CHECK(family IN ('risk','scenario','sensitivity','entity_evidence','classification','fund_mapping','fund_definition'))
);
CREATE TABLE premium_retention_scans (
 owner_id UUID NOT NULL,family VARCHAR(12) NOT NULL,subject_id UUID NOT NULL,phase SMALLINT NOT NULL,cursor UUID,version_id UUID,child_cursor UUID,
 policy_epoch BIGINT NOT NULL,evaluated_at TIMESTAMP WITH TIME ZONE NOT NULL,earliest_deadline TIMESTAMP WITH TIME ZONE,next_policy_at TIMESTAMP WITH TIME ZONE,
 CONSTRAINT pk_premium_retention_scans PRIMARY KEY(owner_id,family),
 CONSTRAINT fk_premium_retention_scans_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners(id) ON DELETE RESTRICT,
 CONSTRAINT ck_premium_retention_scans_phase_bound CHECK(family IN ('risk','scenario','sensitivity') AND phase BETWEEN 0 AND 9 AND policy_epoch>=0)
);
"""

_BACKFILL = r"""INSERT INTO premium_retention_state(run_id,owner_id,account_id,kind,financial_rows,stored_bytes,metadata_bytes,closed)
 SELECT r.id,r.owner_id,r.account_id,r.kind,0,0,0,EXISTS(SELECT 1 FROM premium_retention_events e WHERE e.owner_id=r.owner_id AND e.run_id=r.id AND e.completed_at IS NOT NULL)
 FROM premium_runs r WHERE r.kind IN ('risk','scenario');
UPDATE premium_retention_state s SET financial_rows=(SELECT count(*) FROM risk_run_assets p WHERE p.run_id=s.run_id)+(SELECT count(*) FROM risk_results p WHERE p.run_id=s.run_id AND octet_length(p.canonical_result)>0)+(SELECT count(*) FROM risk_series p WHERE p.result_id IN (SELECT id FROM risk_results WHERE run_id=s.run_id))+(SELECT count(*) FROM risk_intervals p WHERE p.result_id IN (SELECT id FROM risk_results WHERE run_id=s.run_id))+(SELECT count(*) FROM risk_matrix_cells p WHERE p.result_id IN (SELECT id FROM risk_results WHERE run_id=s.run_id))+(SELECT count(*) FROM risk_metrics p WHERE p.result_id IN (SELECT id FROM risk_results WHERE run_id=s.run_id))+(SELECT count(*) FROM risk_components p WHERE p.result_id IN (SELECT id FROM risk_results WHERE run_id=s.run_id)) WHERE kind='risk';
UPDATE premium_retention_state s SET financial_rows=(SELECT count(*) FROM scenario_run_payloads p WHERE p.run_id=s.run_id)+(SELECT count(*) FROM scenario_results p WHERE p.run_id=s.run_id AND octet_length(p.canonical_result)>0)+(SELECT count(*) FROM scenario_components p WHERE p.result_id IN (SELECT id FROM scenario_results WHERE run_id=s.run_id))+(SELECT count(*) FROM scenario_applied_sensitivities p WHERE p.result_id IN (SELECT id FROM scenario_results WHERE run_id=s.run_id)) WHERE kind='scenario';
UPDATE premium_retention_state s SET metadata_bytes=(SELECT coalesce(sum(pg_column_size(p)),0) FROM scenario_run_sensitivity_versions p WHERE p.run_id=s.run_id)+(SELECT coalesce(sum(pg_column_size(p)),0) FROM scenario_run_sensitivity_observations p WHERE p.run_id=s.run_id)+(SELECT coalesce(sum(pg_column_size(p)),0) FROM scenario_run_sensitivity_memberships p WHERE p.run_id=s.run_id)+(SELECT coalesce(sum(pg_column_size(p)),0) FROM scenario_run_sensitivity_evidence p WHERE p.run_id=s.run_id),stored_bytes=scenario_storage_bytes(s.run_id) WHERE kind='scenario';
INSERT INTO premium_retained_parents(id,owner_id,account_id,run_id,parent_kind,parent_id)
 SELECT gen_random_uuid(),r.owner_id,r.account_id,r.id,p.kind,p.id FROM risk_runs r JOIN premium_retention_state s ON s.run_id=r.id LEFT JOIN xray_runs x ON x.id=r.xray_run_id AND x.owner_id=r.owner_id
 CROSS JOIN LATERAL (VALUES('historical',r.historical_input_id),('xray_input',x.input_id),('xray_run',r.xray_run_id)) p(kind,id)
 WHERE NOT s.closed AND p.id IS NOT NULL;
INSERT INTO premium_retained_parents(id,owner_id,account_id,run_id,parent_kind,parent_id)
 SELECT gen_random_uuid(),r.owner_id,r.account_id,r.id,p.kind,p.id FROM scenario_runs r JOIN premium_retention_state s ON s.run_id=r.id
 CROSS JOIN LATERAL (VALUES('historical',r.historical_input_id),('xray_input',r.xray_input_id),('xray_run',r.xray_run_id)) p(kind,id)
 WHERE NOT s.closed AND p.id IS NOT NULL;
INSERT INTO premium_retained_parents(id,owner_id,account_id,run_id,parent_kind,parent_id)
 SELECT gen_random_uuid(),v.owner_id,v.account_id,v.run_id,'sensitivity',v.version_id FROM scenario_run_sensitivity_versions v JOIN premium_retention_state s ON s.run_id=v.run_id WHERE NOT s.closed;
UPDATE scenario_sensitivity_versions v SET retention_closed=EXISTS(SELECT 1 FROM scenario_sensitivity_retention r WHERE r.owner_id=v.owner_id AND r.version_id=v.id AND r.completed_at IS NOT NULL);
UPDATE scenario_sensitivity_observations o SET payload_present=EXISTS(SELECT 1 FROM scenario_sensitivity_observation_payloads p WHERE p.owner_id=o.owner_id AND p.observation_id=o.id);
UPDATE scenario_sensitivity_evidence_links l SET copy_pending=NOT EXISTS(SELECT 1 FROM scenario_sensitivity_retention r WHERE r.owner_id=l.owner_id AND r.version_id=l.version_id) OR EXISTS(SELECT 1 FROM premium_retained_parents p WHERE p.owner_id=l.owner_id AND p.parent_kind='sensitivity' AND p.parent_id=l.version_id),payload_pending=EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_payloads p WHERE p.owner_id=l.owner_id AND p.evidence_id=l.evidence_id);
"""

_RUN = r"""CREATE FUNCTION premium_retention_state_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF pg_trigger_depth()<=1 OR TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Premium retention state is trigger-owned' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION premium_retention_state_create() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.kind IN ('risk','scenario') THEN
  INSERT INTO premium_retention_state(run_id,owner_id,account_id,kind,financial_rows,stored_bytes,metadata_bytes,closed)
  VALUES(NEW.id,NEW.owner_id,NEW.account_id,NEW.kind,0,0,0,false);
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION premium_retention_counter_write() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE selected_run uuid; selected_owner uuid; selected_account uuid; selected_result uuid;
 state premium_retention_state; before_rows bigint:=0; after_rows bigint:=0;
 before_bytes bigint:=0; after_bytes bigint:=0; before_metadata bigint:=0; after_metadata bigint:=0;
 next_rows bigint; next_metadata bigint; next_bytes bigint; financial_bytes bigint;
BEGIN
 IF TG_OP='DELETE' THEN selected_owner:=OLD.owner_id;selected_account:=OLD.account_id;
 ELSE selected_owner:=NEW.owner_id;selected_account:=NEW.account_id; END IF;
 IF TG_TABLE_NAME IN ('risk_run_assets','risk_results','scenario_run_payloads','scenario_results',
  'scenario_run_sensitivity_versions','scenario_run_sensitivity_observations',
  'scenario_run_sensitivity_memberships','scenario_run_sensitivity_evidence') THEN
  IF TG_OP='DELETE' THEN selected_run:=OLD.run_id; ELSE selected_run:=NEW.run_id; END IF;
 ELSE
  IF TG_OP='DELETE' THEN selected_result:=OLD.result_id; ELSE selected_result:=NEW.result_id; END IF;
  IF TG_TABLE_NAME LIKE 'risk_%' THEN
   SELECT run_id INTO selected_run FROM risk_results WHERE owner_id=selected_owner AND account_id=selected_account AND id=selected_result;
  ELSE
   SELECT run_id INTO selected_run FROM scenario_results WHERE owner_id=selected_owner AND account_id=selected_account AND id=selected_result;
  END IF;
 END IF;
 IF NOT pg_try_advisory_xact_lock(hashtextextended('sources:'||selected_owner::text,0))
  OR NOT pg_try_advisory_xact_lock(hashtextextended('premium:'||selected_owner::text,0)) THEN
  RAISE EXCEPTION 'Premium retention owner is busy' USING ERRCODE='55P03'; END IF;
 SELECT * INTO state FROM premium_retention_state WHERE owner_id=selected_owner AND account_id=selected_account AND run_id=selected_run FOR UPDATE;
 IF state.run_id IS NULL THEN RAISE EXCEPTION 'Premium retention counter parent absent' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' AND (state.closed OR EXISTS(SELECT 1 FROM premium_retention_events WHERE owner_id=selected_owner AND run_id=selected_run)) THEN
  RAISE EXCEPTION 'Retired premium copies cannot be republished' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME LIKE 'scenario_run_sensitivity_%' THEN
  IF TG_OP<>'INSERT' THEN before_metadata:=pg_column_size(OLD); END IF;
  IF TG_OP<>'DELETE' THEN after_metadata:=pg_column_size(NEW); END IF;
 ELSE
  IF TG_OP<>'INSERT' THEN
   before_rows:=1;
   IF TG_TABLE_NAME IN ('risk_results','scenario_results') THEN before_rows:=(octet_length(OLD.canonical_result)>0)::int; END IF;
   IF TG_TABLE_NAME='scenario_run_payloads' THEN before_bytes:=octet_length(OLD.canonical_input);
   ELSIF TG_TABLE_NAME='scenario_results' THEN before_bytes:=octet_length(OLD.canonical_result);
   ELSIF TG_TABLE_NAME='scenario_components' THEN
    before_bytes:=octet_length(OLD.canonical_component)+pg_column_size(ROW(OLD.id,OLD.owner_id,OLD.account_id,OLD.result_id,OLD.path_key,OLD.root_key,OLD.root_kind,OLD.position_id,OLD.snapshot_cash_id,OLD.root_instrument_id,OLD.partition,OLD.money_basis,OLD.currency,OLD.pre_value,OLD.post_value,OLD.impact,OLD.rounding_residual,OLD.quality,OLD.reason,OLD.applied_use_count,OLD.created_at));
   ELSIF TG_TABLE_NAME='scenario_applied_sensitivities' THEN before_bytes:=pg_column_size(OLD);
   END IF;
  END IF;
  IF TG_OP<>'DELETE' THEN
   after_rows:=1;
   IF TG_TABLE_NAME IN ('risk_results','scenario_results') THEN after_rows:=(octet_length(NEW.canonical_result)>0)::int; END IF;
   IF TG_TABLE_NAME='scenario_run_payloads' THEN after_bytes:=octet_length(NEW.canonical_input);
   ELSIF TG_TABLE_NAME='scenario_results' THEN after_bytes:=octet_length(NEW.canonical_result);
   ELSIF TG_TABLE_NAME='scenario_components' THEN
    after_bytes:=octet_length(NEW.canonical_component)+pg_column_size(ROW(NEW.id,NEW.owner_id,NEW.account_id,NEW.result_id,NEW.path_key,NEW.root_key,NEW.root_kind,NEW.position_id,NEW.snapshot_cash_id,NEW.root_instrument_id,NEW.partition,NEW.money_basis,NEW.currency,NEW.pre_value,NEW.post_value,NEW.impact,NEW.rounding_residual,NEW.quality,NEW.reason,NEW.applied_use_count,NEW.created_at));
   ELSIF TG_TABLE_NAME='scenario_applied_sensitivities' THEN after_bytes:=pg_column_size(NEW);
   END IF;
  END IF;
 END IF;
 IF before_rows=after_rows AND before_bytes=after_bytes AND before_metadata=after_metadata THEN RETURN coalesce(NEW,OLD); END IF;
 next_rows:=state.financial_rows+after_rows-before_rows;
 next_metadata:=state.metadata_bytes+after_metadata-before_metadata;
 financial_bytes:=CASE WHEN state.financial_rows>0 THEN state.stored_bytes-state.metadata_bytes ELSE 0 END;
 next_bytes:=CASE WHEN next_rows=0 THEN 0 ELSE financial_bytes+after_bytes-before_bytes+next_metadata END;
 IF next_rows<0 OR next_metadata<0 OR next_bytes<0 OR next_bytes>33554432 OR (state.closed AND next_rows>0) THEN
  RAISE EXCEPTION 'Premium retained counter bound violated' USING ERRCODE='23514'; END IF;
 UPDATE premium_retention_state SET financial_rows=next_rows,stored_bytes=next_bytes,metadata_bytes=next_metadata WHERE run_id=selected_run;
 RETURN coalesce(NEW,OLD);
END $$;

CREATE OR REPLACE FUNCTION scenario_capacity_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE selected_run uuid; bytes bigint; root premium_runs;
BEGIN
 IF TG_TABLE_NAME='premium_runs' THEN selected_run:=NEW.id; ELSE selected_run:=NEW.run_id; END IF;
 SELECT * INTO root FROM premium_runs WHERE id=selected_run;
 IF root.kind<>'scenario' THEN RETURN NEW; END IF;
 SELECT stored_bytes INTO bytes FROM premium_retention_state WHERE owner_id=root.owner_id AND account_id=root.account_id AND run_id=selected_run;
 IF bytes IS NULL OR bytes>33554432 OR root.reserved_bytes+root.retained_bytes>33554432 OR bytes>root.reserved_bytes+root.retained_bytes THEN
  RAISE EXCEPTION 'Scenario retained byte capacity exceeded' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION premium_retained_parent_matches(p_owner uuid,p_account uuid,p_run uuid,p_kind text,p_parent uuid)
RETURNS boolean LANGUAGE plpgsql STABLE AS $$
BEGIN
 IF p_kind='historical' THEN
  RETURN EXISTS(SELECT 1 FROM risk_runs WHERE owner_id=p_owner AND account_id=p_account AND id=p_run AND historical_input_id=p_parent)
   OR EXISTS(SELECT 1 FROM scenario_runs WHERE owner_id=p_owner AND account_id=p_account AND id=p_run AND historical_input_id=p_parent);
 ELSIF p_kind='xray_run' THEN
  RETURN EXISTS(SELECT 1 FROM risk_runs WHERE owner_id=p_owner AND account_id=p_account AND id=p_run AND xray_run_id=p_parent)
   OR EXISTS(SELECT 1 FROM scenario_runs WHERE owner_id=p_owner AND account_id=p_account AND id=p_run AND xray_run_id=p_parent);
 ELSIF p_kind='xray_input' THEN
  RETURN EXISTS(SELECT 1 FROM risk_runs r JOIN xray_runs x ON x.id=r.xray_run_id AND x.owner_id=r.owner_id WHERE r.owner_id=p_owner AND r.account_id=p_account AND r.id=p_run AND x.input_id=p_parent)
   OR EXISTS(SELECT 1 FROM scenario_runs WHERE owner_id=p_owner AND account_id=p_account AND id=p_run AND xray_input_id=p_parent);
 ELSIF p_kind='sensitivity' THEN
  RETURN EXISTS(SELECT 1 FROM scenario_run_sensitivity_versions WHERE owner_id=p_owner AND account_id=p_account AND run_id=p_run AND version_id=p_parent);
 END IF;
 RETURN false;
END $$;

CREATE FUNCTION premium_retained_parent_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE state premium_retention_state;
BEGIN
 IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'Retained premium parent identity is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' THEN
  IF pg_trigger_depth()<=1 OR NOT premium_retained_parent_matches(NEW.owner_id,NEW.account_id,NEW.run_id,NEW.parent_kind,NEW.parent_id) THEN
   RAISE EXCEPTION 'Retained premium parent is not its original source' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF NOT pg_try_advisory_xact_lock(hashtextextended('sources:'||OLD.owner_id::text,0))
  OR NOT pg_try_advisory_xact_lock(hashtextextended('premium:'||OLD.owner_id::text,0)) THEN
  RAISE EXCEPTION 'Premium retained parent owner is busy' USING ERRCODE='55P03'; END IF;
 SELECT * INTO state FROM premium_retention_state WHERE owner_id=OLD.owner_id AND account_id=OLD.account_id AND run_id=OLD.run_id FOR UPDATE;
 IF state.run_id IS NULL OR state.financial_rows<>0
  OR NOT EXISTS(SELECT 1 FROM premium_retention_events WHERE owner_id=OLD.owner_id AND account_id=OLD.account_id AND run_id=OLD.run_id AND completed_at IS NULL)
  OR EXISTS(SELECT 1 FROM report_input_premium_dependencies WHERE owner_id=OLD.owner_id AND run_id=OLD.run_id AND copy_pending) THEN
  RAISE EXCEPTION 'Retained premium parent still owns copies' USING ERRCODE='23514'; END IF;
 RETURN OLD;
END $$;

CREATE FUNCTION premium_retained_parent_capture() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE history uuid; xray_input uuid; xray_run uuid;
BEGIN
 IF TG_TABLE_NAME='scenario_run_sensitivity_versions' THEN
  INSERT INTO premium_retained_parents(id,owner_id,account_id,run_id,parent_kind,parent_id)
  VALUES(gen_random_uuid(),NEW.owner_id,NEW.account_id,NEW.run_id,'sensitivity',NEW.version_id);
  RETURN NEW;
 END IF;
 history:=NEW.historical_input_id;xray_run:=NEW.xray_run_id;
 IF TG_TABLE_NAME='scenario_runs' THEN xray_input:=NEW.xray_input_id;
 ELSIF xray_run IS NOT NULL THEN SELECT input_id INTO xray_input FROM xray_runs WHERE owner_id=NEW.owner_id AND id=xray_run;
 END IF;
 INSERT INTO premium_retained_parents(id,owner_id,account_id,run_id,parent_kind,parent_id)
 SELECT gen_random_uuid(),NEW.owner_id,NEW.account_id,NEW.id,p.kind,p.id
 FROM (VALUES('historical',history),('xray_input',xray_input),('xray_run',xray_run)) AS p(kind,id) WHERE p.id IS NOT NULL;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION scenario_source_copy_pending(p_version uuid) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE selected_owner uuid;
BEGIN
 SELECT owner_id INTO selected_owner FROM scenario_sensitivity_versions WHERE id=p_version;
 RETURN EXISTS(SELECT 1 FROM premium_retained_parents WHERE owner_id=selected_owner AND parent_kind='sensitivity' AND parent_id=p_version);
END $$;

CREATE OR REPLACE FUNCTION scenario_retention_copy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE selected_run uuid; selected_kind text; selected_parent uuid; state premium_retention_state;
BEGIN
 IF TG_OP='INSERT' THEN
  SELECT kind INTO selected_kind FROM premium_runs WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
  IF selected_kind IN ('risk','scenario') AND NEW.completed_at IS NOT NULL THEN
   RAISE EXCEPTION 'Premium retention cannot begin completed' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF TG_OP='UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
 IF TG_TABLE_NAME='premium_retention_events' THEN
  IF NEW.completed_at IS NULL THEN RETURN NEW; END IF;
  selected_run:=OLD.run_id;
 ELSIF TG_TABLE_NAME='premium_runs' THEN
  IF NEW.kind<>'scenario' OR NEW.retained_bytes<>0 OR OLD.retained_bytes=0 THEN RETURN NEW; END IF;
  selected_run:=OLD.id;
 ELSIF TG_TABLE_NAME='xray_input_snapshots' THEN selected_kind:='xray_input';selected_parent:=OLD.id;
 ELSIF TG_TABLE_NAME='xray_runs' THEN selected_kind:='xray_run';selected_parent:=OLD.id;
 ELSIF TG_TABLE_NAME='historical_input_snapshots' THEN selected_kind:='historical';selected_parent:=OLD.id;
 END IF;
 IF selected_run IS NOT NULL THEN
  SELECT * INTO state FROM premium_retention_state WHERE owner_id=OLD.owner_id AND run_id=selected_run;
  IF state.run_id IS NOT NULL AND (state.financial_rows<>0 OR EXISTS(SELECT 1 FROM premium_retained_parents WHERE owner_id=OLD.owner_id AND run_id=selected_run)) THEN
   RAISE EXCEPTION 'Premium retained copies remain' USING ERRCODE='23514'; END IF;
 ELSIF selected_kind IS NOT NULL AND EXISTS(SELECT 1 FROM premium_retained_parents WHERE owner_id=OLD.owner_id AND parent_kind=selected_kind AND parent_id=selected_parent) THEN
  RAISE EXCEPTION 'Premium parent copies require cleanup first' USING ERRCODE='23514';
 END IF;
 RETURN coalesce(NEW,OLD);
END $$;

CREATE FUNCTION premium_retention_state_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.completed_at IS NULL AND NEW.completed_at IS NOT NULL THEN
  UPDATE premium_retention_state SET closed=true WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND run_id=NEW.run_id;
 END IF;
 RETURN NEW;
END $$;
"""

_SOURCE = r"""CREATE OR REPLACE FUNCTION scenario_source_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE body jsonb; v uuid; o uuid; e uuid; pinned boolean; version scenario_sensitivity_versions;
BEGIN
 IF TG_OP='UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
 IF TG_OP='INSERT' THEN body:=to_jsonb(NEW); ELSE body:=to_jsonb(OLD); END IF;
 -- Normal cleanup prelocks the owner before DELETE. Direct SQL must not wait
 -- for that owner while already holding the physical target payload tuple.
 IF TG_OP='DELETE' AND TG_TABLE_NAME IN ('scenario_sensitivity_version_payloads','scenario_sensitivity_observation_payloads','scenario_sensitivity_evidence_payloads') THEN
  IF NOT pg_try_advisory_xact_lock(hashtextextended('sources:'||(body->>'owner_id'),0)) THEN
   RAISE EXCEPTION 'Sensitivity source purge owner is busy' USING ERRCODE='55P03';
  END IF;
 END IF;
 IF TG_TABLE_NAME='scenario_sensitivity_versions' THEN v:=(body->>'id')::uuid;
 ELSIF TG_TABLE_NAME='scenario_sensitivity_observation_payloads' THEN
  SELECT version_id INTO v FROM scenario_sensitivity_observations WHERE id=(body->>'observation_id')::uuid AND owner_id=(body->>'owner_id')::uuid;
 ELSIF TG_TABLE_NAME NOT IN ('scenario_sensitivity_sets','scenario_sensitivity_evidence','scenario_sensitivity_evidence_payloads') THEN v:=(body->>'version_id')::uuid; END IF;
 IF TG_TABLE_NAME IN ('scenario_sensitivity_evidence_links','scenario_sensitivity_evidence_payloads') THEN
  e:=(body->>'evidence_id')::uuid;
  PERFORM id FROM scenario_sensitivity_evidence WHERE id=e AND owner_id=(body->>'owner_id')::uuid FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Sensitivity evidence identity unavailable' USING ERRCODE='23514'; END IF;
 END IF;
 IF v IS NOT NULL THEN SELECT * INTO version FROM scenario_sensitivity_versions WHERE id=v AND owner_id=(body->>'owner_id')::uuid FOR UPDATE; END IF;
 IF TG_OP='INSERT' THEN
  IF TG_TABLE_NAME='scenario_sensitivity_versions' THEN
   IF NEW.retention_closed THEN RAISE EXCEPTION 'Sensitivity cleanup cannot begin closed' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_observations' THEN
   IF NEW.payload_present THEN RAISE EXCEPTION 'Observation payload flag is trigger-owned' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_evidence_links' THEN
   IF (NOT NEW.copy_pending OR NOT NEW.payload_pending) THEN RAISE EXCEPTION 'Evidence copies cannot begin cleared' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_retention' THEN
   IF NEW.evidence_after_id IS NOT NULL THEN RAISE EXCEPTION 'Sensitivity cleanup must begin at its first link' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_versions' THEN
   IF NEW.sealed THEN RAISE EXCEPTION 'Sensitivity source must begin unsealed' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='scenario_sensitivity_retention' THEN
   IF version.id IS NULL OR NOT version.sealed OR NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'Sensitivity retention binding invalid' USING ERRCODE='23514'; END IF;
  ELSIF v IS NOT NULL AND (version.id IS NULL OR version.sealed OR EXISTS(SELECT 1 FROM scenario_sensitivity_retention WHERE version_id=v)) THEN
   RAISE EXCEPTION 'Sensitivity source is sealed or restricted' USING ERRCODE='23514';
  END IF;
  IF TG_TABLE_NAME IN ('scenario_sensitivity_versions','scenario_sensitivity_observations','scenario_sensitivity_evidence') THEN
   IF NOT EXISTS(SELECT 1 FROM provider_license_versions WHERE owner_id=NEW.owner_id AND provider_id=NEW.provider_id AND id=NEW.license_version_id AND store_permission='allowed' AND retention_days IS NOT NULL) THEN RAISE EXCEPTION 'Sensitivity storage license unavailable' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_evidence_links' THEN
   IF NOT EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_payloads WHERE evidence_id=e AND owner_id=NEW.owner_id) THEN RAISE EXCEPTION 'Sensitivity evidence payload unavailable' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_version_payloads' THEN
   IF NEW.revision IS DISTINCT FROM version.revision THEN RAISE EXCEPTION 'Sensitivity revision mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_observation_payloads' THEN
   IF NOT EXISTS(SELECT 1 FROM scenario_sensitivity_version_payloads p WHERE p.version_id=v AND p.shock_unit=NEW.shock_unit) THEN RAISE EXCEPTION 'Sensitivity observation units mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_observations' THEN
   IF (NEW.driver_id IS DISTINCT FROM version.driver_id OR NEW.driver_definition_version_id IS DISTINCT FROM version.driver_definition_version_id) THEN RAISE EXCEPTION 'Sensitivity observation driver mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_evidence_payloads' THEN
   IF EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_links l JOIN scenario_sensitivity_versions s ON s.id=l.version_id WHERE l.evidence_id=NEW.evidence_id AND (s.sealed OR EXISTS(SELECT 1 FROM scenario_sensitivity_retention WHERE version_id=s.id))) THEN RAISE EXCEPTION 'Published evidence payload is immutable' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='scenario_sensitivity_observations' THEN
  IF pg_trigger_depth()>1 AND (to_jsonb(NEW)-'payload_present')=(body-'payload_present') AND
   NEW.payload_present=EXISTS(SELECT 1 FROM scenario_sensitivity_observation_payloads WHERE owner_id=OLD.owner_id AND observation_id=OLD.id) THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='scenario_sensitivity_evidence_links' THEN
  IF (to_jsonb(NEW)-ARRAY['copy_pending','payload_pending'])=(body-ARRAY['copy_pending','payload_pending']) AND
   (NOT NEW.copy_pending OR OLD.copy_pending) AND (NOT NEW.payload_pending OR OLD.payload_pending) AND
   EXISTS(SELECT 1 FROM scenario_sensitivity_retention WHERE owner_id=OLD.owner_id AND version_id=OLD.version_id) THEN
   IF OLD.copy_pending AND NOT NEW.copy_pending AND scenario_source_copy_pending(OLD.version_id) THEN RAISE EXCEPTION 'Evidence version copies remain' USING ERRCODE='23514'; END IF;
   IF OLD.payload_pending AND NOT NEW.payload_pending AND EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_payloads WHERE owner_id=OLD.owner_id AND evidence_id=OLD.evidence_id) THEN RAISE EXCEPTION 'Evidence physical copy remains' USING ERRCODE='23514'; END IF;
   RETURN NEW;
  END IF;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='scenario_sensitivity_retention' THEN
  IF NEW.completed_at IS NULL AND OLD.completed_at IS NULL AND
   (to_jsonb(NEW)-'evidence_after_id')=(body-'evidence_after_id') THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='scenario_sensitivity_versions' THEN
  IF pg_trigger_depth()>1 AND NOT OLD.retention_closed AND NEW.retention_closed AND
   (to_jsonb(NEW)-'retention_closed')=(body-'retention_closed') AND EXISTS(SELECT 1 FROM scenario_sensitivity_retention WHERE owner_id=OLD.owner_id AND version_id=OLD.id AND completed_at IS NOT NULL) THEN RETURN NEW; END IF;
  IF NOT OLD.sealed AND NEW.sealed AND (to_jsonb(NEW)-'sealed')=(body-'sealed') THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='scenario_sensitivity_retention' THEN
  IF OLD.completed_at IS NULL AND NEW.completed_at IS NOT NULL AND (to_jsonb(NEW)-'completed_at')=(body-'completed_at') THEN
   IF scenario_source_copy_pending(v)
    OR EXISTS(SELECT 1 FROM scenario_sensitivity_version_payloads WHERE owner_id=OLD.owner_id AND version_id=v)
    OR EXISTS(SELECT 1 FROM scenario_sensitivity_observations WHERE owner_id=OLD.owner_id AND version_id=v AND payload_present)
    OR EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_links WHERE owner_id=OLD.owner_id AND version_id=v AND payload_pending)
    THEN RAISE EXCEPTION 'Sensitivity source copies remain' USING ERRCODE='23514'; END IF;
   RETURN NEW;
  END IF;
 END IF;
 IF TG_OP='DELETE' AND TG_TABLE_NAME IN ('scenario_sensitivity_version_payloads','scenario_sensitivity_observation_payloads') THEN
  IF EXISTS(SELECT 1 FROM scenario_sensitivity_retention WHERE version_id=v) AND NOT scenario_source_copy_pending(v) THEN RETURN OLD; END IF;
 END IF;
 IF TG_OP='DELETE' AND TG_TABLE_NAME='scenario_sensitivity_evidence_payloads' THEN
  -- Evidence header already locked above. Ownership is released link by link,
  -- under each marked version, so no fan-out of all sibling version locks occurs.
  IF EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_links WHERE owner_id=OLD.owner_id AND evidence_id=OLD.evidence_id) AND NOT EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_links WHERE owner_id=OLD.owner_id AND evidence_id=OLD.evidence_id AND copy_pending) THEN RETURN OLD; END IF;
 END IF;
 RAISE EXCEPTION 'Sensitivity source identity or published payload is immutable' USING ERRCODE='23514';
END $$;

CREATE FUNCTION scenario_retention_flags() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='scenario_sensitivity_observation_payloads' THEN
  IF TG_OP='DELETE' THEN
   UPDATE scenario_sensitivity_observations SET payload_present=false WHERE owner_id=OLD.owner_id AND id=OLD.observation_id;
  ELSE
   UPDATE scenario_sensitivity_observations SET payload_present=true WHERE owner_id=NEW.owner_id AND id=NEW.observation_id;
  END IF;
 ELSIF TG_TABLE_NAME='scenario_sensitivity_retention' AND OLD.completed_at IS NULL AND NEW.completed_at IS NOT NULL THEN
  UPDATE scenario_sensitivity_versions SET retention_closed=true WHERE owner_id=NEW.owner_id AND id=NEW.version_id;
 END IF;
 RETURN coalesce(NEW,OLD);
END $$;
"""

_PREVIOUS = r"""CREATE OR REPLACE FUNCTION scenario_capacity_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE run uuid; bytes bigint; root premium_runs;
BEGIN
 IF TG_TABLE_NAME='premium_runs' THEN run:=NEW.id; ELSE run:=NEW.run_id; END IF;
 SELECT * INTO root FROM premium_runs WHERE id=run;
 IF root.kind<>'scenario' THEN RETURN NEW; END IF;
 bytes:=scenario_storage_bytes(run);
 IF bytes>33554432 OR root.reserved_bytes+root.retained_bytes>33554432 OR bytes>root.reserved_bytes+root.retained_bytes THEN RAISE EXCEPTION 'Scenario retained byte capacity exceeded' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION scenario_retention_copy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE run uuid; input uuid; root uuid; body jsonb;
BEGIN
 IF TG_OP='INSERT' THEN
  PERFORM id FROM premium_runs WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
  IF NEW.completed_at IS NOT NULL AND EXISTS(SELECT 1 FROM premium_runs WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id AND kind='scenario') THEN RAISE EXCEPTION 'Scenario retention cannot begin completed' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF TG_OP='UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
 body:=to_jsonb(OLD);
 IF TG_TABLE_NAME='premium_retention_events' THEN
  IF NEW.completed_at IS NULL THEN RETURN NEW; END IF;
  run:=OLD.run_id;
 ELSIF TG_TABLE_NAME='premium_runs' THEN
  IF NEW.kind<>'scenario' OR NEW.retained_bytes<>0 OR OLD.retained_bytes=0 THEN RETURN NEW; END IF;
  run:=OLD.id;
 END IF;
 IF run IS NOT NULL AND scenario_run_has_payload(run) THEN RAISE EXCEPTION 'Scenario retained copies remain' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='xray_input_snapshots' THEN input:=OLD.id;
 ELSIF TG_TABLE_NAME='xray_runs' THEN root:=OLD.id;
 ELSIF TG_TABLE_NAME='historical_input_snapshots' THEN input:=OLD.id;
 END IF;
 IF TG_TABLE_NAME IN ('xray_input_snapshots','xray_runs') AND EXISTS(SELECT 1 FROM scenario_runs s WHERE (s.xray_input_id=input OR s.xray_run_id=root) AND scenario_run_has_payload(s.id)) THEN RAISE EXCEPTION 'Scenario X-ray copies require cleanup first' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='historical_input_snapshots' AND EXISTS(SELECT 1 FROM scenario_runs s WHERE s.historical_input_id=input AND scenario_run_has_payload(s.id)) THEN RAISE EXCEPTION 'Scenario historical copies require cleanup first' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION scenario_source_copy_pending(p_version uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM scenario_run_sensitivity_versions v WHERE v.version_id=p_version AND (
  scenario_run_has_payload(v.run_id) OR EXISTS(SELECT 1 FROM report_input_premium_dependencies d WHERE d.owner_id=v.owner_id AND d.run_id=v.run_id AND d.copy_pending)))
$$;

CREATE OR REPLACE FUNCTION scenario_source_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE body jsonb; v uuid; o uuid; e uuid; pinned boolean; version scenario_sensitivity_versions;
BEGIN
 IF TG_OP='UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
 IF TG_OP='INSERT' THEN body:=to_jsonb(NEW); ELSE body:=to_jsonb(OLD); END IF;
 -- Normal cleanup prelocks the owner before DELETE. Direct SQL must not wait
 -- for that owner while already holding the physical target payload tuple.
 IF TG_OP='DELETE' AND TG_TABLE_NAME IN ('scenario_sensitivity_version_payloads','scenario_sensitivity_observation_payloads','scenario_sensitivity_evidence_payloads') THEN
  IF NOT pg_try_advisory_xact_lock(hashtextextended('sources:'||(body->>'owner_id'),0)) THEN
   RAISE EXCEPTION 'Sensitivity source purge owner is busy' USING ERRCODE='55P03';
  END IF;
 END IF;
 IF TG_TABLE_NAME='scenario_sensitivity_versions' THEN v:=(body->>'id')::uuid;
 ELSIF TG_TABLE_NAME='scenario_sensitivity_observation_payloads' THEN
  SELECT version_id INTO v FROM scenario_sensitivity_observations WHERE id=(body->>'observation_id')::uuid AND owner_id=(body->>'owner_id')::uuid;
 ELSIF TG_TABLE_NAME NOT IN ('scenario_sensitivity_sets','scenario_sensitivity_evidence','scenario_sensitivity_evidence_payloads') THEN v:=(body->>'version_id')::uuid; END IF;
 IF TG_TABLE_NAME IN ('scenario_sensitivity_evidence_links','scenario_sensitivity_evidence_payloads') THEN
  e:=(body->>'evidence_id')::uuid;
  PERFORM id FROM scenario_sensitivity_evidence WHERE id=e AND owner_id=(body->>'owner_id')::uuid FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Sensitivity evidence identity unavailable' USING ERRCODE='23514'; END IF;
 END IF;
 IF v IS NOT NULL THEN SELECT * INTO version FROM scenario_sensitivity_versions WHERE id=v AND owner_id=(body->>'owner_id')::uuid FOR UPDATE; END IF;
 IF TG_OP='INSERT' THEN
  IF TG_TABLE_NAME='scenario_sensitivity_versions' THEN
   IF NEW.sealed THEN RAISE EXCEPTION 'Sensitivity source must begin unsealed' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='scenario_sensitivity_retention' THEN
   IF version.id IS NULL OR NOT version.sealed OR NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'Sensitivity retention binding invalid' USING ERRCODE='23514'; END IF;
  ELSIF v IS NOT NULL AND (version.id IS NULL OR version.sealed OR EXISTS(SELECT 1 FROM scenario_sensitivity_retention WHERE version_id=v)) THEN
   RAISE EXCEPTION 'Sensitivity source is sealed or restricted' USING ERRCODE='23514';
  END IF;
  IF TG_TABLE_NAME IN ('scenario_sensitivity_versions','scenario_sensitivity_observations','scenario_sensitivity_evidence') THEN
   IF NOT EXISTS(SELECT 1 FROM provider_license_versions WHERE owner_id=NEW.owner_id AND provider_id=NEW.provider_id AND id=NEW.license_version_id AND store_permission='allowed' AND retention_days IS NOT NULL) THEN RAISE EXCEPTION 'Sensitivity storage license unavailable' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_evidence_links' THEN
   IF NOT EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_payloads WHERE evidence_id=e AND owner_id=NEW.owner_id) THEN RAISE EXCEPTION 'Sensitivity evidence payload unavailable' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_version_payloads' THEN
   IF NEW.revision IS DISTINCT FROM version.revision THEN RAISE EXCEPTION 'Sensitivity revision mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_observation_payloads' THEN
   IF NOT EXISTS(SELECT 1 FROM scenario_sensitivity_version_payloads p WHERE p.version_id=v AND p.shock_unit=NEW.shock_unit) THEN RAISE EXCEPTION 'Sensitivity observation units mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_observations' THEN
   IF (NEW.driver_id IS DISTINCT FROM version.driver_id OR NEW.driver_definition_version_id IS DISTINCT FROM version.driver_definition_version_id) THEN RAISE EXCEPTION 'Sensitivity observation driver mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_evidence_payloads' THEN
   IF EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_links l JOIN scenario_sensitivity_versions s ON s.id=l.version_id WHERE l.evidence_id=NEW.evidence_id AND (s.sealed OR EXISTS(SELECT 1 FROM scenario_sensitivity_retention WHERE version_id=s.id))) THEN RAISE EXCEPTION 'Published evidence payload is immutable' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='scenario_sensitivity_versions' THEN
  IF NOT OLD.sealed AND NEW.sealed AND (to_jsonb(NEW)-'sealed')=(body-'sealed') THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='scenario_sensitivity_retention' THEN
  IF OLD.completed_at IS NULL AND NEW.completed_at IS NOT NULL AND (to_jsonb(NEW)-'completed_at')=(body-'completed_at') THEN
   IF scenario_source_copy_pending(v) OR EXISTS(SELECT 1 FROM scenario_sensitivity_version_payloads WHERE version_id=v) OR EXISTS(SELECT 1 FROM scenario_sensitivity_observation_payloads p JOIN scenario_sensitivity_observations o ON o.id=p.observation_id WHERE o.version_id=v) OR EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_payloads p JOIN scenario_sensitivity_evidence_links l ON l.evidence_id=p.evidence_id WHERE l.version_id=v) THEN RAISE EXCEPTION 'Sensitivity source copies remain' USING ERRCODE='23514'; END IF;
   RETURN NEW;
  END IF;
 END IF;
 IF TG_OP='DELETE' AND TG_TABLE_NAME IN ('scenario_sensitivity_version_payloads','scenario_sensitivity_observation_payloads') THEN
  IF EXISTS(SELECT 1 FROM scenario_sensitivity_retention WHERE version_id=v) AND NOT scenario_source_copy_pending(v) THEN RETURN OLD; END IF;
 END IF;
 IF TG_OP='DELETE' AND TG_TABLE_NAME='scenario_sensitivity_evidence_payloads' THEN
  -- A shared evidence payload cannot be removed while any published version still needs it.
  PERFORM s.id FROM scenario_sensitivity_versions s JOIN scenario_sensitivity_evidence_links l ON l.version_id=s.id WHERE l.evidence_id=OLD.evidence_id ORDER BY s.id FOR UPDATE OF s;
  IF EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_links WHERE evidence_id=OLD.evidence_id) AND NOT EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_links l WHERE l.evidence_id=OLD.evidence_id AND (NOT EXISTS(SELECT 1 FROM scenario_sensitivity_retention WHERE version_id=l.version_id) OR scenario_source_copy_pending(l.version_id))) THEN RETURN OLD; END IF;
 END IF;
 RAISE EXCEPTION 'Sensitivity source identity or published payload is immutable' USING ERRCODE='23514';
END $$;
"""
