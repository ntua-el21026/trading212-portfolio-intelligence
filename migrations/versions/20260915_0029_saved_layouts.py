"""Bounded durable owner layouts and immutable typed saved-view versions."""

from alembic import op
from sqlalchemy import text

revision = "20260915_0029"
down_revision = "20260915_0028"
branch_labels = None
depends_on = None

_DDL = (
    r"""CREATE TABLE owner_layouts (
 id UUID NOT NULL,
 created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
 owner_id UUID NOT NULL,
 "current_version_id" UUID,
 "revision" INTEGER NOT NULL,
 "state" VARCHAR(10) NOT NULL,
 "actor_id" UUID NOT NULL,
 "updated_at" TIMESTAMP WITH TIME ZONE NOT NULL,
 "archived_at" TIMESTAMP WITH TIME ZONE,
 CONSTRAINT pk_owner_layouts PRIMARY KEY (id),
 CONSTRAINT fk_owner_layouts_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT uq_owner_layouts_owner_id UNIQUE ("owner_id", "id"),
 CONSTRAINT fk_owner_layouts_owner_id_principals FOREIGN KEY ("owner_id", "actor_id") REFERENCES principals ("owner_id", "id"),
 CONSTRAINT ck_owner_layouts_revision_bound CHECK (revision BETWEEN 1 AND 129),
 CONSTRAINT ck_owner_layouts_state_shape CHECK ((state='active' AND archived_at IS NULL AND current_version_id IS NOT NULL) OR (state='archived' AND archived_at IS NOT NULL AND current_version_id IS NOT NULL) OR (state='erasing' AND current_version_id IS NULL))
)""",
    r"""CREATE INDEX ix_owner_layouts_owner_created ON owner_layouts ("owner_id", "created_at", "id")""",
    r"""CREATE TABLE saved_view_versions (
 id UUID NOT NULL,
 created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
 owner_id UUID NOT NULL,
 "layout_id" UUID NOT NULL,
 "version_number" INTEGER NOT NULL,
 "parent_version_id" UUID,
 "schema_version" INTEGER NOT NULL,
 "actor_id" UUID NOT NULL,
 "account_id" UUID,
 "name" VARCHAR(80) NOT NULL,
 "description" VARCHAR(400) NOT NULL,
 "columns" INTEGER NOT NULL,
 "density" VARCHAR(12) NOT NULL,
 "content_digest" VARCHAR(64) NOT NULL,
 "canonical_content" BYTEA NOT NULL,
 CONSTRAINT pk_saved_view_versions PRIMARY KEY (id),
 CONSTRAINT fk_saved_view_versions_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_saved_view_versions_account_id_broker_accounts FOREIGN KEY ("account_id") REFERENCES broker_accounts (id) ON DELETE RESTRICT,
 CONSTRAINT uq_saved_view_versions_owner_id UNIQUE ("owner_id", "layout_id", "id"),
 CONSTRAINT uq_saved_view_versions_layout_id UNIQUE ("layout_id", "version_number"),
 CONSTRAINT fk_saved_view_versions_owner_id_owner_layouts FOREIGN KEY ("owner_id", "layout_id") REFERENCES owner_layouts ("owner_id", "id") DEFERRABLE INITIALLY DEFERRED,
 CONSTRAINT fk_saved_view_versions_owner_id_saved_view_versions FOREIGN KEY ("owner_id", "layout_id", "parent_version_id") REFERENCES saved_view_versions ("owner_id", "layout_id", "id"),
 CONSTRAINT fk_saved_view_versions_owner_id_principals FOREIGN KEY ("owner_id", "actor_id") REFERENCES principals ("owner_id", "id"),
 CONSTRAINT ck_saved_view_versions_version_bound CHECK (version_number BETWEEN 1 AND 128 AND schema_version=1),
 CONSTRAINT ck_saved_view_versions_presentation CHECK (columns BETWEEN 1 AND 3 AND density IN ('comfortable','compact')),
 CONSTRAINT ck_saved_view_versions_text_bound CHECK (length(name) BETWEEN 1 AND 80 AND length(description)<=400),
 CONSTRAINT ck_saved_view_versions_content_bound CHECK (octet_length(canonical_content) BETWEEN 1 AND 16384 AND content_digest ~ '^[0-9a-f]{64}$')
)""",
    r"""CREATE INDEX ix_saved_view_version_cutoff ON saved_view_versions ("owner_id", "layout_id", "created_at", "version_number")""",
    r"""CREATE TABLE saved_layout_widgets (
 id UUID NOT NULL,
 created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
 owner_id UUID NOT NULL,
 "layout_id" UUID NOT NULL,
 "version_id" UUID NOT NULL,
 "widget_id" UUID NOT NULL,
 "ordinal" INTEGER NOT NULL,
 "kind" VARCHAR(24) NOT NULL,
 "label" VARCHAR(80) NOT NULL,
 "selection_kind" VARCHAR(12),
 "route" VARCHAR(20),
 "pane" VARCHAR(12),
 "run_family" VARCHAR(12),
 "risk_run_id" UUID,
 "scenario_run_id" UUID,
 "projection_run_id" UUID,
 "xray_run_id" UUID,
 "snapshot_id" UUID,
 "capture_id" UUID,
 "entity_id" UUID,
 "start_date" DATE,
 "end_date" DATE,
 "source_cutoff_at" TIMESTAMP WITH TIME ZONE,
 "reporting_currency" VARCHAR(3),
 "method" VARCHAR(20),
 "frequency" VARCHAR(8),
 "knowledge" VARCHAR(16),
 "coverage" VARCHAR(20),
 "view" VARCHAR(16),
 "grouping" VARCHAR(12),
 "flow_kind" VARCHAR(20),
 "rolling" VARCHAR(20),
 "calendar" VARCHAR(8),
 "event_kind" VARCHAR(24),
 "review_state" VARCHAR(16),
 CONSTRAINT pk_saved_layout_widgets PRIMARY KEY (id),
 CONSTRAINT fk_saved_layout_widgets_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_saved_layout_widgets_risk_run_id_risk_runs FOREIGN KEY ("risk_run_id") REFERENCES risk_runs (id) ON DELETE RESTRICT,
 CONSTRAINT fk_saved_layout_widgets_scenario_run_id_scenario_runs FOREIGN KEY ("scenario_run_id") REFERENCES scenario_runs (id) ON DELETE RESTRICT,
 CONSTRAINT fk_saved_layout_widgets_projection_run_id_projection_runs FOREIGN KEY ("projection_run_id") REFERENCES projection_runs (id) ON DELETE RESTRICT,
 CONSTRAINT fk_saved_layout_widgets_xray_run_id_xray_runs FOREIGN KEY ("xray_run_id") REFERENCES xray_runs (id) ON DELETE RESTRICT,
 CONSTRAINT fk_saved_layout_widgets_snapshot_id_portfolio_snapshots FOREIGN KEY ("snapshot_id") REFERENCES portfolio_snapshots (id) ON DELETE RESTRICT,
 CONSTRAINT fk_saved_layout_widgets_capture_id_historical_input_snapshots FOREIGN KEY ("capture_id") REFERENCES historical_input_snapshots (id) ON DELETE RESTRICT,
 CONSTRAINT fk_saved_layout_widgets_entity_id_economic_entities FOREIGN KEY ("entity_id") REFERENCES economic_entities (id) ON DELETE RESTRICT,
 CONSTRAINT fk_saved_layout_widgets_owner_id_saved_view_versions FOREIGN KEY ("owner_id", "layout_id", "version_id") REFERENCES saved_view_versions ("owner_id", "layout_id", "id") ON DELETE RESTRICT,
 CONSTRAINT uq_saved_layout_widget_identity UNIQUE ("version_id", "widget_id"),
 CONSTRAINT uq_saved_layout_widget_ordinal UNIQUE ("version_id", "ordinal"),
 CONSTRAINT ck_saved_layout_widgets_ordinal_bound CHECK (ordinal BETWEEN 0 AND 23),
 CONSTRAINT ck_saved_layout_widgets_kind_allowed CHECK (kind IN ('portfolio_summary','direct_allocation','holdings_preview','data_quality','saved_view')),
 CONSTRAINT ck_saved_layout_widgets_selection_kind CHECK ((kind='saved_view' AND selection_kind IN ('workspace','historical','saved_run','research')) OR (kind<>'saved_view' AND selection_kind IS NULL)),
 CONSTRAINT ck_saved_layout_widgets_one_run CHECK (num_nonnulls(risk_run_id,scenario_run_id,projection_run_id,xray_run_id)<=1)
)""",
    r"""CREATE INDEX ix_saved_layout_widgets_owner_version ON saved_layout_widgets ("owner_id", "version_id", "ordinal")""",
    r"""CREATE TABLE owner_layout_command_identities (
 id UUID NOT NULL,
 created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
 owner_id UUID NOT NULL,
 "layout_id" UUID NOT NULL,
 "version_id" UUID NOT NULL,
 "command" VARCHAR(40) NOT NULL,
 "idempotency_key" VARCHAR(180) NOT NULL,
 "command_digest" VARCHAR(64) NOT NULL,
 "actor_id" UUID NOT NULL,
 "correlation_id" VARCHAR(120) NOT NULL,
 "result_revision" INTEGER NOT NULL,
 "audit_id" UUID NOT NULL,
 CONSTRAINT pk_owner_layout_command_identities PRIMARY KEY (id),
 CONSTRAINT fk_owner_layout_command_identities_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
 CONSTRAINT fk_owner_layout_command_identities_audit_id_audit_events FOREIGN KEY ("audit_id") REFERENCES audit_events (id) ON DELETE RESTRICT,
 CONSTRAINT fk_owner_layout_command_identities_owner_id_saved_view_versions FOREIGN KEY ("owner_id", "layout_id", "version_id") REFERENCES saved_view_versions ("owner_id", "layout_id", "id"),
 CONSTRAINT fk_owner_layout_command_identities_owner_id_principals FOREIGN KEY ("owner_id", "actor_id") REFERENCES principals ("owner_id", "id"),
 CONSTRAINT uq_owner_layout_command_identities_owner_id UNIQUE ("owner_id", "command", "idempotency_key"),
 CONSTRAINT uq_owner_layout_command_identities_layout_id UNIQUE ("layout_id", "result_revision"),
 CONSTRAINT ck_owner_layout_command_identities_command_allowed CHECK (command IN ('preferences.layout.create.v1','preferences.layout.update.v1','preferences.layout.archive.v1')),
 CONSTRAINT ck_owner_layout_command_identities_identity_format CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{1,180}$' AND command_digest ~ '^[0-9a-f]{64}$'),
 CONSTRAINT ck_owner_layout_command_identities_revision_bound CHECK (result_revision BETWEEN 1 AND 129)
)""",
    r"""CREATE INDEX ix_layout_commands_owner_layout ON owner_layout_command_identities ("owner_id", "layout_id", "result_revision")""",
    r"""ALTER TABLE owner_layouts ADD CONSTRAINT fk_owner_layout_current_version FOREIGN KEY ("owner_id", "id", "current_version_id") REFERENCES saved_view_versions ("owner_id", "layout_id", "id") DEFERRABLE INITIALLY DEFERRED""",
)

_DDL += (
    "CREATE INDEX ix_owner_layout_current_version ON owner_layouts(current_version_id)",
    "CREATE INDEX ix_saved_view_version_parent ON saved_view_versions(parent_version_id)",
    "CREATE INDEX ix_saved_layout_widgets_owner_layout ON saved_layout_widgets(owner_id,layout_id,version_id,ordinal)",
    "CREATE INDEX ix_layout_commands_owner_version ON owner_layout_command_identities(owner_id,version_id,result_revision)",
)

_ERASURE_DDL = (
    "CREATE TABLE owner_layout_erasure (owner_id UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ, CONSTRAINT pk_owner_layout_erasure PRIMARY KEY(owner_id), CONSTRAINT fk_owner_layout_erasure_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners(id) ON DELETE RESTRICT, CONSTRAINT ck_owner_layout_erasure_completion_order CHECK(completed_at IS NULL OR completed_at>=created_at))",
    "CREATE INDEX ix_broker_connections_layout_active_owner ON broker_connections(owner_id) WHERE status='active'",
)

_FUNCTIONS = (
    r"""CREATE FUNCTION owner_layout_utc(value timestamptz) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT to_char(value AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS') ||
 CASE WHEN extract(microseconds FROM value)::bigint%1000000=0 THEN ''
 ELSE '.'||to_char(value AT TIME ZONE 'UTC','US') END || 'Z'
$$""",
    r"""CREATE FUNCTION owner_layout_canonical_json(value jsonb) RETURNS text LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE result text;
BEGIN
 CASE jsonb_typeof(value)
 WHEN 'object' THEN SELECT '{'||coalesce(string_agg(to_jsonb(key)::text||':'||owner_layout_canonical_json(val),',' ORDER BY key COLLATE "C"),'')||'}'
   INTO result FROM jsonb_each(value) AS f(key,val);
 WHEN 'array' THEN SELECT '['||coalesce(string_agg(owner_layout_canonical_json(val),',' ORDER BY ordinal),'')||']'
   INTO result FROM jsonb_array_elements(value) WITH ORDINALITY AS f(val,ordinal);
 ELSE result:=value::text;
 END CASE;
 RETURN result;
END $$""",
    r"""CREATE FUNCTION owner_layout_selection(w saved_layout_widgets) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
 IF w.selection_kind IS NULL THEN RETURN 'null'::jsonb; END IF;
 CASE w.selection_kind
 WHEN 'workspace' THEN RETURN jsonb_build_object('kind','workspace','route',w.route,'pane',w.pane);
 WHEN 'saved_run' THEN RETURN jsonb_build_object('kind','saved_run','family',w.run_family,'pane',w.pane,
   'run_id',coalesce(w.risk_run_id,w.scenario_run_id,w.projection_run_id,w.xray_run_id),
   'snapshot_id',w.snapshot_id,'source_cutoff_at',owner_layout_utc(w.source_cutoff_at),'reporting_currency',w.reporting_currency);
 WHEN 'historical' THEN RETURN jsonb_build_object('kind','historical','route',w.route,'start_date',w.start_date::text,
   'end_date',w.end_date::text,'source_cutoff_at',owner_layout_utc(w.source_cutoff_at),'reporting_currency',w.reporting_currency,
   'method',w.method,'frequency',w.frequency,'knowledge',w.knowledge,'coverage',w.coverage,'view',w.view,
   'grouping',w.grouping,'flow_kind',w.flow_kind,'rolling',w.rolling,'calendar',w.calendar,'capture_id',w.capture_id);
 WHEN 'research' THEN RETURN jsonb_build_object('kind','research','xray_run_id',w.xray_run_id,
   'source_cutoff_at',owner_layout_utc(w.source_cutoff_at),'entity_id',w.entity_id,'event_kind',w.event_kind,'review_state',w.review_state);
 ELSE RAISE EXCEPTION 'unsupported layout selection' USING ERRCODE='23514';
 END CASE;
END $$""",
    r"""CREATE FUNCTION owner_layout_widget_valid(w saved_layout_widgets,a uuid) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE allowed text[]; extras jsonb;
BEGIN
 IF char_length(w.label)>80 OR w.label ~ '[\x00-\x1f\x7f]' THEN RETURN false; END IF;
 allowed:=ARRAY['id','owner_id','created_at','layout_id','version_id','widget_id','ordinal','kind','label','selection_kind'];
 CASE w.selection_kind
 WHEN 'workspace' THEN
  allowed:=allowed||ARRAY['route','pane'];
  IF w.route IS NULL OR w.route NOT IN ('overview','holdings','allocation','activity','dividends','snapshots','synchronization','quality','pies','drift','planner','sources','performance','risk','scenarios','projections','research','income','xray','reports','alerts','settings')
   OR (w.pane IS NOT NULL AND NOT ((w.route IN ('risk','scenarios') AND w.pane IN ('runs','definitions')) OR (w.route='projections' AND w.pane IN ('runs','assumptions','goals')))) THEN RETURN false; END IF;
 WHEN 'saved_run' THEN
  allowed:=allowed||ARRAY['run_family','pane','risk_run_id','scenario_run_id','projection_run_id','xray_run_id','snapshot_id','source_cutoff_at','reporting_currency'];
  IF (w.run_family='xray' AND (num_nonnulls(w.snapshot_id,w.source_cutoff_at,w.reporting_currency)<>3 OR w.reporting_currency !~ '^[A-Z]{3}$'))
   OR (w.run_family<>'xray' AND num_nonnulls(w.snapshot_id,w.source_cutoff_at,w.reporting_currency)<>0) THEN RETURN false; END IF;
  IF a IS NULL OR w.run_family IS NULL OR w.pane IS NULL OR NOT (w.pane='result' OR (w.pane='goal' AND w.run_family='projection'))
   OR num_nonnulls(w.risk_run_id,w.scenario_run_id,w.projection_run_id,w.xray_run_id)<>1
   OR NOT ((w.run_family='risk' AND w.risk_run_id IS NOT NULL) OR (w.run_family='scenario' AND w.scenario_run_id IS NOT NULL)
    OR (w.run_family='projection' AND w.projection_run_id IS NOT NULL) OR (w.run_family='xray' AND w.xray_run_id IS NOT NULL)) THEN RETURN false; END IF;
 WHEN 'historical' THEN
  allowed:=allowed||ARRAY['route','start_date','end_date','source_cutoff_at','reporting_currency','method','frequency','knowledge','coverage','view','grouping','flow_kind','rolling','calendar','capture_id'];
  IF a IS NULL OR num_nonnulls(w.route,w.start_date,w.end_date,w.source_cutoff_at,w.reporting_currency,w.method,w.frequency,w.knowledge,w.coverage,w.view,w.grouping,w.flow_kind,w.rolling,w.calendar)<>14
   OR w.route NOT IN ('performance','income') OR w.end_date-w.start_date NOT BETWEEN 0 AND 3660 OR w.reporting_currency !~ '^[A-Z]{3}$'
   OR w.method NOT IN ('twr','mwr','modified_dietz') OR w.frequency NOT IN ('daily','monthly') OR w.knowledge NOT IN ('as_of_cutoff','point_in_time')
   OR w.coverage NOT IN ('require_complete','allow_degraded') OR w."grouping" NOT IN ('holding','group','sector','asset_class','currency')
   OR w.rolling NOT IN ('none','calendar_days_30','calendar_days_90','calendar_days_365') OR w.calendar NOT IN ('none','month','quarter','year')
   OR NOT ((w.route='performance' AND w.view IN ('summary','series','rolling','calendar','attribution')) OR (w.route='income' AND w.view IN ('income','cash_flows')))
   OR (w.route='income' AND w."grouping" NOT IN ('holding','group')) OR (w.view='attribution' AND w.method='mwr')
   OR (w.view='rolling' AND w.rolling='none') OR (w.view='calendar' AND w.calendar='none')
   OR w.flow_kind NOT IN ('all','deposit','withdrawal','transfer_in','transfer_out','buy','sell','dividend','interest','fee','tax','internal_transfer','fx_conversion','corporate_action','unknown') THEN RETURN false; END IF;
 WHEN 'research' THEN
  allowed:=allowed||ARRAY['xray_run_id','source_cutoff_at','entity_id','event_kind','review_state'];
  IF a IS NULL OR w.xray_run_id IS NULL OR w.source_cutoff_at IS NULL OR w.review_state IS NULL OR w.review_state NOT IN ('all','reviewed','unreviewed')
   OR (w.event_kind IS NOT NULL AND w.event_kind NOT IN ('news','company_overview')) THEN RETURN false; END IF;
 ELSE IF w.selection_kind IS NOT NULL OR w.kind='saved_view' THEN RETURN false; END IF;
 END CASE;
 extras:=jsonb_strip_nulls(to_jsonb(w)-allowed);
 IF extras<>'{}'::jsonb THEN RETURN false; END IF;
 IF w.risk_run_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM risk_runs x WHERE x.id=w.risk_run_id AND x.owner_id=w.owner_id AND x.account_id=a) THEN RETURN false; END IF;
 IF w.scenario_run_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM scenario_runs x WHERE x.id=w.scenario_run_id AND x.owner_id=w.owner_id AND x.account_id=a) THEN RETURN false; END IF;
 IF w.projection_run_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM projection_runs x WHERE x.id=w.projection_run_id AND x.owner_id=w.owner_id AND x.account_id=a) THEN RETURN false; END IF;
 IF w.xray_run_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM xray_runs x JOIN xray_input_snapshots i ON i.id=x.input_id AND i.owner_id=x.owner_id
  WHERE x.id=w.xray_run_id AND x.owner_id=w.owner_id AND i.account_id=a AND x.sealed_at IS NOT NULL AND (w.selection_kind<>'saved_run' OR (i.snapshot_id=w.snapshot_id AND i.source_cutoff_at=w.source_cutoff_at AND i.reporting_currency=w.reporting_currency))) THEN RETURN false; END IF;
 IF w.capture_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM historical_input_snapshots h WHERE h.id=w.capture_id AND h.owner_id=w.owner_id AND h.broker_account_id=a AND h.sealed
  AND h.period_start=w.start_date AND h.period_end=w.end_date AND h.source_cutoff_at=w.source_cutoff_at AND h.reporting_currency=w.reporting_currency AND h.knowledge_policy=w.knowledge) THEN RETURN false; END IF;
 IF w.entity_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM economic_entities e WHERE e.id=w.entity_id AND e.owner_id=w.owner_id) THEN RETURN false; END IF;
 RETURN true;
END $$""",
    r"""CREATE FUNCTION owner_layout_version_complete(v saved_view_versions) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE count_widgets integer; projected jsonb; w saved_layout_widgets; position integer:=0; previews text[]:=ARRAY[]::text[]; items jsonb:='[]'::jsonb;
BEGIN
 IF v.name !~ '[^[:space:]]' OR v.name ~ '[\x00-\x1f\x7f]' OR v.description ~ '[\x00-\x1f\x7f]' THEN RETURN false; END IF;
 IF v.account_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM broker_accounts a JOIN broker_connections c ON c.id=a.connection_id WHERE a.id=v.account_id AND c.owner_id=v.owner_id) THEN RETURN false; END IF;
 SELECT count(*) INTO count_widgets FROM (SELECT id FROM saved_layout_widgets WHERE owner_id=v.owner_id AND version_id=v.id LIMIT 25) bounded;
 IF count_widgets NOT BETWEEN 1 AND 24 THEN RETURN false; END IF;
 FOR w IN SELECT * FROM saved_layout_widgets WHERE owner_id=v.owner_id AND version_id=v.id ORDER BY ordinal LOOP
  IF w.layout_id<>v.layout_id OR w.ordinal<>position OR w.created_at<>v.created_at OR NOT owner_layout_widget_valid(w,v.account_id) THEN RETURN false; END IF;
  IF w.kind<>'saved_view' THEN
   IF w.kind=ANY(previews) THEN RETURN false; END IF;
   previews:=previews||w.kind;
  END IF;
  items:=items||jsonb_build_array(jsonb_build_object('id',w.widget_id,'kind',w.kind,'label',w.label,'selection',owner_layout_selection(w)));
  position:=position+1;
 END LOOP;
 projected:=jsonb_build_object('schema_version',v.schema_version,'name',v.name,'description',v.description,'account_id',v.account_id,'columns',v.columns,'density',v.density,'widgets',items);
 RETURN convert_to(owner_layout_canonical_json(projected),'UTF8')=v.canonical_content
  AND encode(sha256(convert_to('owner-layout-content-v1','UTF8')||decode('00','hex')||v.canonical_content),'hex')=v.content_digest;
END $$""",
    r"""CREATE FUNCTION owner_layout_write_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner uuid; root owner_layouts; parent saved_view_versions; source saved_view_versions; count_rows integer;
BEGIN
 owner:=NEW.owner_id;
 PERFORM pg_advisory_xact_lock(hashtextextended('preferences:'||owner::text,0));
 IF EXISTS(SELECT 1 FROM owner_layout_erasure e WHERE e.owner_id=owner) THEN
  IF TG_TABLE_NAME='owner_layouts' AND TG_OP='UPDATE' THEN
   IF NEW.state='erasing' AND NEW.current_version_id IS NULL AND OLD.state IN ('active','archived')
    AND (to_jsonb(NEW)-ARRAY['state','current_version_id'])=(to_jsonb(OLD)-ARRAY['state','current_version_id']) THEN RETURN NEW; END IF;
  END IF;
  RAISE EXCEPTION 'terminated owner cannot publish layouts' USING ERRCODE='23514';
 END IF;
 IF TG_TABLE_NAME='owner_layouts' THEN
  IF TG_OP='INSERT'  THEN
   SELECT count(*) INTO count_rows FROM (SELECT id FROM owner_layouts WHERE owner_id=owner LIMIT 33) bounded;
   IF count_rows>=32 OR NEW.state<>'active' OR NEW.revision<>1 OR NEW.created_at<>NEW.updated_at THEN
    RAISE EXCEPTION 'owner layout admission bound' USING ERRCODE='23514'; END IF;
  ELSE
   IF NEW.id<>OLD.id OR NEW.owner_id<>OLD.owner_id OR NEW.created_at<>OLD.created_at OR NEW.revision<>OLD.revision+1 OR NEW.updated_at<OLD.updated_at OR OLD.state<>'active'
    OR NOT ((NEW.state='active' AND NEW.current_version_id<>OLD.current_version_id AND NEW.archived_at IS NULL)
       OR (NEW.state='archived' AND NEW.current_version_id=OLD.current_version_id AND NEW.archived_at=NEW.updated_at)) THEN
    RAISE EXCEPTION 'invalid owner layout transition' USING ERRCODE='23514'; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='saved_view_versions' THEN
  IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'saved layout versions are immutable' USING ERRCODE='23514'; END IF;
  SELECT * INTO root FROM owner_layouts WHERE id=NEW.layout_id AND owner_id=owner;
  IF NOT FOUND OR root.state<>'active' OR root.actor_id<>NEW.actor_id OR root.updated_at<>NEW.created_at THEN
   RAISE EXCEPTION 'saved layout version scope differs' USING ERRCODE='23514'; END IF;
  IF NEW.version_number=1 THEN
   IF NEW.parent_version_id IS NOT NULL OR root.created_at<>NEW.created_at THEN RAISE EXCEPTION 'invalid first layout version' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT * INTO parent FROM saved_view_versions WHERE id=NEW.parent_version_id AND owner_id=owner AND layout_id=NEW.layout_id;
   IF NOT FOUND OR parent.version_number+1<>NEW.version_number OR NEW.created_at<parent.created_at OR NEW.content_digest=parent.content_digest THEN
    RAISE EXCEPTION 'saved layout version chain differs' USING ERRCODE='23514'; END IF;
  END IF;
 ELSIF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'saved layout records are immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$""",
    r"""CREATE FUNCTION owner_layout_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE root owner_layouts; source saved_view_versions; receipt owner_layout_command_identities; identifier uuid; owner uuid; total integer; expected_command text; command_shape jsonb; expected_digest text;
BEGIN
 owner:=NEW.owner_id;
 IF EXISTS(SELECT 1 FROM owner_layout_erasure e WHERE e.owner_id=owner) THEN RETURN NEW; END IF;
 IF TG_TABLE_NAME='owner_layouts' THEN identifier:=NEW.id; ELSE identifier:=NEW.layout_id; END IF;
 SELECT * INTO root FROM owner_layouts WHERE id=identifier AND owner_id=owner;
 IF NOT FOUND THEN RAISE EXCEPTION 'owner layout root missing' USING ERRCODE='23514'; END IF;
 SELECT * INTO source FROM saved_view_versions WHERE id=root.current_version_id AND owner_id=owner AND layout_id=root.id;
 IF NOT FOUND OR root.revision<>source.version_number+(CASE WHEN root.state='archived' THEN 1 ELSE 0 END) THEN
  RAISE EXCEPTION 'owner layout current version differs' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME IN ('saved_view_versions','saved_layout_widgets') THEN
  IF TG_TABLE_NAME='saved_view_versions' THEN identifier:=NEW.id; ELSE identifier:=NEW.version_id; END IF;
  SELECT * INTO source FROM saved_view_versions WHERE id=identifier AND owner_id=owner AND layout_id=root.id;
  IF NOT FOUND OR NOT owner_layout_version_complete(source) THEN RAISE EXCEPTION 'saved layout normalized content differs' USING ERRCODE='23514'; END IF;
 END IF;
 SELECT * INTO receipt FROM owner_layout_command_identities WHERE owner_id=owner AND layout_id=root.id AND result_revision=root.revision;
 expected_command:=CASE WHEN root.state='archived' THEN 'preferences.layout.archive.v1' WHEN root.revision=1 THEN 'preferences.layout.create.v1' ELSE 'preferences.layout.update.v1' END;
 IF NOT FOUND OR receipt.version_id<>root.current_version_id OR receipt.actor_id<>root.actor_id OR receipt.created_at<>root.updated_at OR receipt.command<>expected_command
  OR NOT EXISTS(SELECT 1 FROM audit_events a WHERE a.id=receipt.audit_id AND a.owner_id=owner AND a.principal_id=receipt.actor_id AND a.broker_account_id IS NULL
   AND a.action=receipt.command AND a.resource_type='owner_layout' AND a.resource_id=root.id::text AND a.outcome='success' AND a.occurred_at=receipt.created_at
   AND a.correlation_id=receipt.correlation_id AND a.safe_metadata=jsonb_build_object('revision',receipt.result_revision,'version_id',receipt.version_id::text)) THEN
  RAISE EXCEPTION 'owner layout command audit differs' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='owner_layout_command_identities' THEN
  SELECT * INTO source FROM saved_view_versions WHERE id=NEW.version_id AND owner_id=owner AND layout_id=root.id;
  IF NOT FOUND OR NEW.result_revision<>source.version_number+(CASE WHEN NEW.command='preferences.layout.archive.v1' THEN 1 ELSE 0 END)
   OR (NEW.command='preferences.layout.create.v1' AND source.version_number<>1)
   OR (NEW.command='preferences.layout.update.v1' AND source.version_number<=1)
   OR (NEW.command<>'preferences.layout.archive.v1' AND NEW.created_at<>source.created_at) THEN
   RAISE EXCEPTION 'owner layout receipt version differs' USING ERRCODE='23514'; END IF;
  command_shape:=CASE NEW.command
   WHEN 'preferences.layout.create.v1' THEN jsonb_build_array(NEW.command,source.content_digest)
   WHEN 'preferences.layout.update.v1' THEN jsonb_build_array(NEW.command,root.id::text,NEW.result_revision-1,source.content_digest)
   WHEN 'preferences.layout.archive.v1' THEN jsonb_build_array(NEW.command,root.id::text,NEW.result_revision-1)
   ELSE NULL END;
  expected_digest:=encode(sha256(convert_to('owner-layout-command-v1','UTF8')||decode('00','hex')||convert_to(owner_layout_canonical_json(command_shape),'UTF8')),'hex');
  IF command_shape IS NULL OR NEW.command_digest IS DISTINCT FROM expected_digest
   OR NOT EXISTS(SELECT 1 FROM audit_events a WHERE a.id=NEW.audit_id AND a.owner_id=owner AND a.principal_id=NEW.actor_id AND a.broker_account_id IS NULL
    AND a.action=NEW.command AND a.resource_type='owner_layout' AND a.resource_id=root.id::text AND a.outcome='success' AND a.occurred_at=NEW.created_at
    AND a.correlation_id=NEW.correlation_id AND a.safe_metadata=jsonb_build_object('revision',NEW.result_revision,'version_id',NEW.version_id::text)) THEN
   RAISE EXCEPTION 'owner layout receipt identity differs' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$""",
)

_ERASURE_FUNCTIONS = (
    r"""CREATE FUNCTION owner_layout_erasure_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner uuid;
BEGIN
 owner:=CASE WHEN TG_OP='DELETE' THEN OLD.owner_id ELSE NEW.owner_id END;
 IF NOT pg_try_advisory_xact_lock(hashtextextended('preferences:'||owner::text,0)) THEN
  RAISE EXCEPTION 'layout owner is busy' USING ERRCODE='55P03'; END IF;
 IF TG_TABLE_NAME='owner_layout_erasure' THEN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'owner erasure identity is immutable' USING ERRCODE='23514'; END IF;
  IF TG_OP='INSERT' THEN
   IF EXISTS(SELECT 1 FROM principals WHERE owner_id=owner AND status='active')
     OR EXISTS(SELECT 1 FROM broker_connections WHERE owner_id=owner AND status='active') OR NEW.completed_at IS NOT NULL THEN
    RAISE EXCEPTION 'layout owner has not terminated' USING ERRCODE='23514'; END IF;
  ELSE
   IF OLD.completed_at IS NOT NULL OR NEW.completed_at IS NULL OR NEW.owner_id<>OLD.owner_id OR NEW.created_at<>OLD.created_at
     OR EXISTS(SELECT 1 FROM owner_layouts WHERE owner_id=owner) THEN
    RAISE EXCEPTION 'owner layout erasure is incomplete or immutable' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM owner_layout_erasure WHERE owner_id=owner) THEN
  RAISE EXCEPTION 'owner layout erasure marker required' USING ERRCODE='23514'; END IF;
 RETURN OLD;
END $$""",
)


def upgrade() -> None:
    for statement in _DDL + _ERASURE_DDL + _FUNCTIONS + _ERASURE_FUNCTIONS:
        op.execute(text(statement))
    for table in (
        "owner_layouts",
        "saved_view_versions",
        "saved_layout_widgets",
        "owner_layout_command_identities",
    ):
        op.execute(
            f"CREATE TRIGGER owner_layout_erasure_guard BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION owner_layout_erasure_guard()"
        )
        op.execute(
            f"CREATE TRIGGER owner_layout_write_guard BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION owner_layout_write_guard()"
        )
        op.execute(
            f"CREATE CONSTRAINT TRIGGER owner_layout_complete AFTER INSERT OR UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION owner_layout_complete()"
        )

    op.execute(
        "CREATE TRIGGER owner_layout_erasure_guard BEFORE INSERT OR UPDATE OR DELETE ON owner_layout_erasure FOR EACH ROW EXECUTE FUNCTION owner_layout_erasure_guard()"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM owner_layouts) OR EXISTS(SELECT 1 FROM owner_layout_erasure) THEN RAISE EXCEPTION 'Cannot remove populated saved layouts'; END IF; END $$"
    )
    for table in (
        "owner_layouts",
        "saved_view_versions",
        "saved_layout_widgets",
        "owner_layout_command_identities",
    ):
        op.execute(f"DROP TRIGGER owner_layout_erasure_guard ON {table}")
        op.execute(f"DROP TRIGGER owner_layout_complete ON {table}")
        op.execute(f"DROP TRIGGER owner_layout_write_guard ON {table}")
    op.execute("DROP TABLE owner_layout_erasure")
    op.execute("DROP INDEX ix_broker_connections_layout_active_owner")
    op.execute("DROP FUNCTION owner_layout_erasure_guard()")
    op.execute("DROP FUNCTION owner_layout_complete()")
    op.execute("DROP FUNCTION owner_layout_write_guard()")
    op.execute("DROP FUNCTION owner_layout_version_complete(saved_view_versions)")
    op.execute("DROP FUNCTION owner_layout_widget_valid(saved_layout_widgets,uuid)")
    op.execute("DROP FUNCTION owner_layout_selection(saved_layout_widgets)")
    op.execute("DROP FUNCTION owner_layout_canonical_json(jsonb)")
    op.execute("DROP FUNCTION owner_layout_utc(timestamptz)")
    op.execute("ALTER TABLE owner_layouts DROP CONSTRAINT fk_owner_layout_current_version")
    for table in (
        "owner_layout_command_identities",
        "saved_layout_widgets",
        "saved_view_versions",
        "owner_layouts",
    ):
        op.execute(f"DROP TABLE {table}")
