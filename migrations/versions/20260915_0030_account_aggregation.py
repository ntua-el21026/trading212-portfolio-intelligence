"""Bounded owner-scoped account aggregation with immutable original-source proof.

Revision ID:20260915_0030
Revises:20260915_0029
"""

from hashlib import md5

from alembic import op

revision = "20260915_0030"
down_revision = "20260915_0029"
branch_labels = None
depends_on = None


# Closed migration-only table inventory. Every physical source FK is explicit;
# the public service accepts IDs of existing canonical records, never SQL names.
def _constraint_name(value: str) -> str:
    # Match SQLAlchemy's deterministic naming-convention truncation on PostgreSQL.
    return value if len(value) <= 63 else value[:55] + "_" + md5(value.encode(), usedforsecurity=False).hexdigest()[-4:]


def _fk(table: str, column: str, parent: str, *, scoped: bool = False) -> str:
    columns = "owner_id,"+column if scoped else column
    targets = "owner_id,id" if scoped else "id"
    first = "owner_id" if scoped else column
    return f"CONSTRAINT {_constraint_name(f'fk_{table}_{first}_{parent}')} FOREIGN KEY ({columns}) REFERENCES {parent}({targets}) ON DELETE RESTRICT"


def _owned(table: str) -> str:
    return f"id uuid NOT NULL CONSTRAINT pk_{table} PRIMARY KEY,owner_id uuid NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),CONSTRAINT uq_{table}_owner_id UNIQUE(owner_id,id),"+_fk(table,"owner_id","owners")


def _projection(table: str, maximum: int) -> str:
    return (_owned(table)+",run_id uuid NOT NULL,ordinal integer NOT NULL,payload bytea NOT NULL,content_digest varchar(64) NOT NULL,"+
        _fk(table,"run_id","aggregate_runs",scoped=True)+f",CONSTRAINT uq_{table}_ordinal UNIQUE(run_id,ordinal),"+
        f"CONSTRAINT ck_{table}_ordinal_bound CHECK(ordinal BETWEEN 0 AND {maximum-1}),"+
        f"CONSTRAINT ck_{table}_digest_format CHECK(content_digest ~ '^[0-9a-f]{{64}}$'),"+
        f"CONSTRAINT ck_{table}_payload_bound CHECK(octet_length(payload) BETWEEN 1 AND 2097152)")


_TABLES = (
("aggregate_selections", _owned("aggregate_selections")+""",
 command_id uuid NOT NULL CONSTRAINT uq_aggregate_selections_command_id UNIQUE,actor_id uuid NOT NULL,content_digest varchar(64) NOT NULL,
 revision integer NOT NULL,member_count integer NOT NULL,reporting_currency varchar(3) NOT NULL,
 source_cutoff_at timestamptz NOT NULL,identity_policy varchar(40) NOT NULL,sealed boolean NOT NULL,
 CONSTRAINT ck_aggregate_selection_revision CHECK(revision BETWEEN 1 AND 2147483647),
 CONSTRAINT ck_aggregate_selection_members CHECK(member_count BETWEEN 1 AND 8),
 CONSTRAINT ck_aggregate_selection_digest CHECK(content_digest ~ '^[0-9a-f]{64}$'),
 CONSTRAINT ck_aggregate_selection_currency CHECK(reporting_currency ~ '^[A-Z]{3}$'),
 CONSTRAINT ck_aggregate_selection_policy CHECK(identity_policy='canonical_instrument_v1'),
 """+_fk("aggregate_selections","command_id","application_command_identities")+","+_fk("aggregate_selections","actor_id","principals",scoped=True)),
("aggregate_account_members", _owned("aggregate_account_members")+""",
 selection_id uuid NOT NULL,ordinal integer NOT NULL,account_id uuid NOT NULL,snapshot_id uuid NOT NULL,
 CONSTRAINT uq_aggregate_members_ordinal UNIQUE(selection_id,ordinal),
 CONSTRAINT uq_aggregate_members_account UNIQUE(selection_id,account_id),
 CONSTRAINT uq_aggregate_members_snapshot UNIQUE(selection_id,snapshot_id),
 CONSTRAINT uq_aggregate_members_scope UNIQUE(owner_id,selection_id,account_id),
 CONSTRAINT ck_aggregate_member_ordinal CHECK(ordinal BETWEEN 0 AND 7),
 """+_fk("aggregate_account_members","selection_id","aggregate_selections",scoped=True)+","+_fk("aggregate_account_members","account_id","broker_accounts")+","+_fk("aggregate_account_members","snapshot_id","portfolio_snapshots")),
("aggregate_selection_payloads",_owned("aggregate_selection_payloads")+""",
 selection_id uuid NOT NULL CONSTRAINT uq_aggregate_selection_payloads_selection_id UNIQUE,payload bytea NOT NULL,
 CONSTRAINT ck_aggregate_selection_payload CHECK(octet_length(payload) BETWEEN 1 AND 65536),
 """+_fk("aggregate_selection_payloads","selection_id","aggregate_selections",scoped=True)),
("aggregate_runs",_owned("aggregate_runs")+""",
 selection_id uuid NOT NULL,selection_revision integer NOT NULL,command_id uuid NOT NULL CONSTRAINT uq_aggregate_runs_command_id UNIQUE,actor_id uuid NOT NULL,
 holdings_input_digest varchar(64),holdings_result_digest varchar(64),activity_input_digest varchar(64),activity_result_digest varchar(64),
 activity_requested boolean NOT NULL,activity_start_at timestamptz,activity_end_at timestamptz,
 expires_at timestamptz NOT NULL,completed_at timestamptz,sealed boolean NOT NULL,
 reserved_bytes bigint NOT NULL,retained_bytes bigint NOT NULL,financial_rows integer NOT NULL,
 CONSTRAINT uq_aggregate_runs_selection_id UNIQUE(selection_id,selection_revision),
 CONSTRAINT ck_aggregate_run_revision CHECK(selection_revision BETWEEN 2 AND 2147483647),
 CONSTRAINT ck_aggregate_run_digests CHECK((holdings_input_digest IS NULL OR holdings_input_digest ~ '^[0-9a-f]{64}$') AND (holdings_result_digest IS NULL OR holdings_result_digest ~ '^[0-9a-f]{64}$') AND (activity_input_digest IS NULL OR activity_input_digest ~ '^[0-9a-f]{64}$') AND (activity_result_digest IS NULL OR activity_result_digest ~ '^[0-9a-f]{64}$')),
 CONSTRAINT ck_aggregate_run_retention CHECK(expires_at>created_at AND expires_at<=created_at+interval '30 days'),
 CONSTRAINT ck_aggregate_run_capacity CHECK(reserved_bytes>=0 AND retained_bytes>=0 AND reserved_bytes+retained_bytes<=33554432 AND financial_rows>=0),
 CONSTRAINT ck_aggregate_run_publication CHECK((sealed AND reserved_bytes=0 AND completed_at IS NOT NULL AND holdings_input_digest IS NOT NULL AND holdings_result_digest IS NOT NULL) OR (NOT sealed AND completed_at IS NULL)),
 CONSTRAINT ck_aggregate_run_activity CHECK((activity_requested AND activity_start_at IS NOT NULL AND activity_end_at IS NOT NULL AND activity_end_at>activity_start_at AND activity_end_at<=activity_start_at+interval '3660 days') OR (NOT activity_requested AND activity_start_at IS NULL AND activity_end_at IS NULL AND activity_input_digest IS NULL AND activity_result_digest IS NULL)),
 """+_fk("aggregate_runs","selection_id","aggregate_selections",scoped=True)+","+_fk("aggregate_runs","command_id","application_command_identities")+","+_fk("aggregate_runs","actor_id","principals",scoped=True)),
)

_PAYLOAD_TABLES = ("aggregate_holdings_payloads","aggregate_activity_payloads")
_PROJECTIONS = (
("aggregate_input_members",8,"account_id uuid NOT NULL,snapshot_id uuid NOT NULL,calculation_run_id uuid NOT NULL,CONSTRAINT uq_aggregate_input_account UNIQUE(run_id,account_id)",(("account_id","broker_accounts",False),("snapshot_id","portfolio_snapshots",False),("calculation_run_id","calculation_runs",False))),
("aggregate_fx_uses",256,"account_id uuid NOT NULL,source_currency varchar(3) NOT NULL,target_currency varchar(3) NOT NULL,fx_snapshot_id uuid NOT NULL,fx_observation_id uuid NOT NULL,license_version_id uuid NOT NULL,original_rate numeric(38,18),state varchar(20) NOT NULL,inverted boolean NOT NULL,CONSTRAINT uq_aggregate_fx_pair UNIQUE(run_id,account_id,source_currency),CONSTRAINT ck_aggregate_fx_rate CHECK((state='available' AND original_rate IS NOT NULL AND original_rate>0) OR (state IN ('missing','unsupported','disputed') AND original_rate IS NULL))",(("account_id","broker_accounts",False),("fx_snapshot_id","fx_snapshots",True),("fx_observation_id","fx_observations",True),("license_version_id","provider_license_versions",True))),
("aggregate_components",10256,"""component_id uuid NOT NULL,account_id uuid NOT NULL,snapshot_id uuid NOT NULL,kind varchar(10) NOT NULL,
 position_id uuid,cash_id uuid,listing_id uuid,instrument_id uuid,quantity numeric(38,18),native_currency varchar(3) NOT NULL,
 native_value numeric(38,18),reporting_currency varchar(3) NOT NULL,converted_value numeric(38,18),fx_observation_id uuid,
 quality varchar(20) NOT NULL,origin varchar(30) NOT NULL,reason varchar(40),
 CONSTRAINT uq_aggregate_component_identity UNIQUE(run_id,component_id),
 CONSTRAINT ck_aggregate_component_kind CHECK((kind='position' AND position_id IS NOT NULL AND cash_id IS NULL AND listing_id IS NOT NULL AND instrument_id IS NOT NULL AND quantity IS NOT NULL) OR (kind='cash' AND cash_id IS NOT NULL AND position_id IS NULL AND listing_id IS NULL AND instrument_id IS NULL AND quantity IS NULL)),
 CONSTRAINT ck_aggregate_component_availability CHECK((converted_value IS NULL)=(reason IS NOT NULL))""",(("account_id","broker_accounts",False),("snapshot_id","portfolio_snapshots",False),("position_id","snapshot_positions",False),("cash_id","snapshot_cash",False),("listing_id","listings",False),("instrument_id","instruments",False),("fx_observation_id","fx_observations",False))),
("aggregate_holdings",10000,"instrument_id uuid NOT NULL,quantity numeric(38,18) NOT NULL,currency varchar(3) NOT NULL,value numeric(38,18),known_value numeric(38,18) NOT NULL,known_count integer NOT NULL,total_count integer NOT NULL,CONSTRAINT uq_aggregate_holding_identity UNIQUE(run_id,instrument_id)",(("instrument_id","instruments",False),)),
("aggregate_account_totals",8,"account_id uuid NOT NULL,currency varchar(3) NOT NULL,value numeric(38,18),known_value numeric(38,18) NOT NULL,known_count integer NOT NULL,total_count integer NOT NULL,CONSTRAINT uq_aggregate_account_total UNIQUE(run_id,account_id)",(("account_id","broker_accounts",False),)),
("aggregate_transfer_evidence",10000,"account_id uuid NOT NULL,source_record_id uuid NOT NULL,selected boolean NOT NULL,amount numeric(38,18),currency varchar(3),CONSTRAINT uq_aggregate_evidence_source UNIQUE(owner_id,run_id,source_record_id)",(("account_id","broker_accounts",False),("source_record_id","source_records",False))),
("aggregate_activity_coverage",10000,"account_id uuid NOT NULL,coverage_id uuid NOT NULL,evidence_id uuid NOT NULL,evidence_digest varchar(64) NOT NULL,ingestion_run_id uuid NOT NULL,capability varchar(100) NOT NULL,start_at timestamptz NOT NULL,end_at timestamptz NOT NULL,first_observed_at timestamptz NOT NULL,complete boolean NOT NULL,CONSTRAINT uq_aggregate_coverage_identity UNIQUE(run_id,coverage_id)",(("account_id","broker_accounts",False),("coverage_id","historical_activity_coverage",True),("evidence_id","historical_evidence_sets",True),("ingestion_run_id","ingestion_runs",False))),
("aggregate_activity_revisions",10000,"account_id uuid NOT NULL,evidence_id uuid NOT NULL,new_source_record_id uuid NOT NULL,superseded_source_record_id uuid NOT NULL,CONSTRAINT uq_aggregate_revision_identity UNIQUE(run_id,evidence_id)",(("account_id","broker_accounts",False),("evidence_id","activity_revision_evidence",True),("new_source_record_id","source_records",False),("superseded_source_record_id","source_records",False))),
("aggregate_flow_legs",10000,"""account_id uuid NOT NULL,source_record_id uuid NOT NULL,amount numeric(38,18),currency varchar(3),classification varchar(30) NOT NULL,counterpart_record_id uuid,
 CONSTRAINT uq_aggregate_flow_source UNIQUE(owner_id,run_id,source_record_id),
 CONSTRAINT fk_aggregate_flow_legs_owner_id_aggregate_transfer_evidence FOREIGN KEY(owner_id,run_id,source_record_id) REFERENCES aggregate_transfer_evidence(owner_id,run_id,source_record_id) ON DELETE RESTRICT""",(("account_id","broker_accounts",False),("counterpart_record_id","source_records",False))),
("aggregate_transfer_matches",5000,"""outgoing_record_id uuid NOT NULL,incoming_record_id uuid NOT NULL,outgoing_account_id uuid NOT NULL,incoming_account_id uuid NOT NULL,
 outgoing_principal numeric(38,18) NOT NULL,incoming_principal numeric(38,18) NOT NULL,outgoing_currency varchar(3) NOT NULL,incoming_currency varchar(3) NOT NULL,fx_rate numeric(38,18),
 CONSTRAINT uq_aggregate_transfer_out UNIQUE(run_id,outgoing_record_id),CONSTRAINT uq_aggregate_transfer_in UNIQUE(run_id,incoming_record_id),
 CONSTRAINT ck_aggregate_transfer_principals CHECK(outgoing_principal<0 AND incoming_principal>0 AND outgoing_account_id<>incoming_account_id),
 CONSTRAINT fk_aggregate_transfer_out_flow FOREIGN KEY(owner_id,run_id,outgoing_record_id) REFERENCES aggregate_flow_legs(owner_id,run_id,source_record_id) ON DELETE RESTRICT,
 CONSTRAINT fk_aggregate_transfer_in_flow FOREIGN KEY(owner_id,run_id,incoming_record_id) REFERENCES aggregate_flow_legs(owner_id,run_id,source_record_id) ON DELETE RESTRICT""",(("outgoing_account_id","broker_accounts",False),("incoming_account_id","broker_accounts",False))),
)

_SOURCE_FIELDS = (("snapshot","snapshot_id","portfolio_snapshots"),("calculation","calculation_run_id","calculation_runs"),
 ("broker_record","source_record_id","source_records"),("fx","fx_snapshot_id","fx_snapshots"),
 ("fx_observation","fx_observation_id","fx_observations"),("coverage","coverage_id","historical_activity_coverage"),
 ("coverage_parent","evidence_id","historical_evidence_sets"),("revision","revision_id","activity_revision_evidence"))


def _create_tables() -> None:
    for table,columns in _TABLES:
        op.execute(f"CREATE TABLE {table} ({columns})")
    for table in _PAYLOAD_TABLES:
        kind="holdings" if table=="aggregate_holdings_payloads" else "activity"
        op.execute(f"CREATE TABLE {table} ("+_owned(table)+",run_id uuid NOT NULL CONSTRAINT uq_"+table+"_run_id UNIQUE,input_payload bytea NOT NULL,result_payload bytea NOT NULL,summary_payload bytea NOT NULL,summary_digest varchar(64) NOT NULL,"+_fk(table,"run_id","aggregate_runs",scoped=True)+f",CONSTRAINT ck_aggregate_{kind}_payload_bytes CHECK(octet_length(input_payload)>0 AND octet_length(result_payload)>0 AND octet_length(summary_payload)>0 AND octet_length(input_payload)+octet_length(result_payload)+octet_length(summary_payload)<=33554432))")
    for table,maximum,columns,fks in _PROJECTIONS:
        op.execute(f"CREATE TABLE {table} ("+_projection(table,maximum)+","+columns+","+",".join(_fk(table,c,p,scoped=s) for c,p,s in fks)+")")
    table="aggregate_sources"
    names=",".join(c for _,c,_ in _SOURCE_FIELDS)
    binding=" OR ".join(f"(source_kind='{kind}' AND source_id IS NOT DISTINCT FROM {column} AND num_nonnulls({names})=1)" for kind,column,_ in _SOURCE_FIELDS)
    op.execute(f"CREATE TABLE {table} ("+_owned(table)+",run_id uuid NOT NULL,view_kind varchar(10) NOT NULL,source_kind varchar(20) NOT NULL,source_id uuid NOT NULL,"+",".join(c+" uuid" for _,c,_ in _SOURCE_FIELDS)+","+_fk(table,"run_id","aggregate_runs",scoped=True)+","+",".join(_fk(table,c,p) for _,c,p in _SOURCE_FIELDS)+f",CONSTRAINT uq_aggregate_sources_run_id UNIQUE(run_id,view_kind,source_kind,source_id),CONSTRAINT ck_aggregate_source_view CHECK(view_kind IN ('holdings','activity')),CONSTRAINT ck_aggregate_source_binding CHECK({binding}))")
    op.execute("CREATE TABLE aggregate_retention_work ("+_owned("aggregate_retention_work")+",run_id uuid NOT NULL CONSTRAINT uq_aggregate_retention_work_run_id UNIQUE,reason varchar(20) NOT NULL,source_fx_snapshot_id uuid,source_evidence_id uuid,completed_at timestamptz,"+_fk("aggregate_retention_work","run_id","aggregate_runs",scoped=True)+","+_fk("aggregate_retention_work","source_fx_snapshot_id","fx_snapshots")+","+_fk("aggregate_retention_work","source_evidence_id","historical_evidence_sets")+",CONSTRAINT ck_aggregate_retention_reason CHECK(reason IN ('expired','source','owner_erasure')),CONSTRAINT ck_aggregate_retention_time CHECK(completed_at IS NULL OR completed_at>=created_at))")
    op.execute("CREATE TABLE aggregate_owner_erasure(owner_id uuid NOT NULL CONSTRAINT pk_aggregate_owner_erasure PRIMARY KEY,created_at timestamptz NOT NULL,completed_at timestamptz,CONSTRAINT fk_aggregate_owner_erasure_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners(id) ON DELETE RESTRICT)")
    op.execute("CREATE TABLE aggregate_retention_cursor(key varchar(50) NOT NULL CONSTRAINT pk_aggregate_retention_cursor PRIMARY KEY,owner_id uuid,last_owner_id uuid,last_run_id uuid,last_source_id uuid,updated_at timestamptz NOT NULL,CONSTRAINT ck_aggregate_cursor_scope CHECK((key='aggregate' AND owner_id IS NULL) OR key='aggregate:'||owner_id::text),CONSTRAINT ck_aggregate_cursor_pair CHECK((last_owner_id IS NULL)=(last_run_id IS NULL)),"+_fk("aggregate_retention_cursor","owner_id","owners")+","+_fk("aggregate_retention_cursor","last_owner_id","owners")+","+_fk("aggregate_retention_cursor","last_run_id","aggregate_runs")+")")
    for table in (*_PAYLOAD_TABLES,*(x[0] for x in _PROJECTIONS),"aggregate_sources","aggregate_retention_work"):
        op.execute(f"CREATE INDEX ix_{table}_run ON {table}(owner_id,run_id,id)")
    for table,*_ in _PROJECTIONS:
        op.execute(f"CREATE INDEX ix_{table}_page ON {table}(owner_id,run_id,ordinal)")
    for statement in _INDEXES:
        op.execute(statement)


_INDEXES=(
 "CREATE INDEX ix_aggregate_selections_owner_created ON aggregate_selections(owner_id,created_at,id)",
 "CREATE INDEX ix_aggregate_members_account ON aggregate_account_members(owner_id,account_id,selection_id)",
 "CREATE INDEX ix_aggregate_runs_selection_created ON aggregate_runs(owner_id,selection_id,created_at,id)",
 "CREATE INDEX ix_aggregate_runs_owner_expiry ON aggregate_runs(owner_id,expires_at,id)",
 "CREATE INDEX ix_aggregate_runs_retained ON aggregate_runs(owner_id,id) WHERE retained_bytes>0",
 "CREATE INDEX ix_aggregate_runs_selection_retained ON aggregate_runs(owner_id,selection_id,id) WHERE retained_bytes>0",
 "CREATE INDEX ix_aggregate_runs_owner_copies ON aggregate_runs(owner_id,id) WHERE retained_bytes+reserved_bytes>0",
 "CREATE INDEX ix_aggregate_sources_pending ON aggregate_sources(owner_id,source_kind,source_id,run_id)",
 "CREATE INDEX ix_aggregate_sources_fx_progress ON aggregate_sources(owner_id,run_id,id) WHERE source_kind='fx'",
 "CREATE INDEX ix_fx_observation_reference_page ON fx_observations(owner_id,snapshot_id,base,quote,effective_at,id)",
 "CREATE INDEX ix_aggregate_fx_observation_reverse ON aggregate_fx_uses(owner_id,fx_observation_id)",
 "CREATE INDEX ix_aggregate_component_fx_reverse ON aggregate_components(fx_observation_id)",
 "CREATE INDEX ix_aggregate_retention_pending ON aggregate_retention_work(owner_id,id) WHERE completed_at IS NULL",
)

_COMMON = r"""
CREATE FUNCTION aggregate_digest(p_payload bytea) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT encode(sha256(convert_to('t212pi.aggregation.record.v1','UTF8')||decode('00','hex')||p_payload),'hex')
$$;
CREATE FUNCTION aggregate_owner_lock(p_owner uuid) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF NOT pg_try_advisory_xact_lock(hashtextextended('sources:'||p_owner::text,0))
 OR NOT pg_try_advisory_xact_lock(hashtextextended('xray:'||p_owner::text,0))
 OR NOT pg_try_advisory_xact_lock(hashtextextended('historical:'||p_owner::text,0))
 OR NOT pg_try_advisory_xact_lock(hashtextextended('premium:'||p_owner::text,0))
 OR NOT pg_try_advisory_xact_lock(hashtextextended('aggregate:'||p_owner::text,0)) THEN
  RAISE EXCEPTION 'aggregate owner busy' USING ERRCODE='55P03';
 END IF;
END $$;
CREATE FUNCTION aggregate_actor_valid(p_owner uuid,p_actor uuid,p_write boolean,p_activity boolean)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM principals p WHERE p.owner_id=p_owner AND p.id=p_actor AND p.status='active')
 AND NOT EXISTS(SELECT 1 FROM aggregate_owner_erasure e WHERE e.owner_id=p_owner)
 AND NOT EXISTS(SELECT 1 FROM research_owner_erasure e WHERE e.owner_id=p_owner)
 AND NOT EXISTS(SELECT 1 FROM unnest(ARRAY['portfolio:read','analytics:read','aggregate:read']::text[]
   ||CASE WHEN p_write THEN ARRAY['aggregate:write']::text[] ELSE ARRAY[]::text[] END
   ||CASE WHEN p_activity THEN ARRAY['activity:read']::text[] ELSE ARRAY[]::text[] END) required(scope)
 WHERE NOT EXISTS(SELECT 1 FROM principal_scope_grants g WHERE g.principal_id=p_actor AND g.scope=required.scope
   AND g.granted_at<=statement_timestamp() AND g.revoked_at IS NULL AND (g.expires_at IS NULL OR g.expires_at>statement_timestamp())))
$$;
CREATE FUNCTION aggregate_fx_until(p_owner uuid,p_source uuid,p_at timestamptz)
RETURNS timestamptz LANGUAGE plpgsql STABLE AS $$
DECLARE s fx_snapshots; pinned provider_license_versions; current_license provider_license_versions;
BEGIN
 SELECT * INTO s FROM fx_snapshots WHERE owner_id=p_owner AND id=p_source;
 IF s.id IS NULL OR s.expires_at<=p_at OR EXISTS(SELECT 1 FROM source_retention_work WHERE owner_id=p_owner AND fx_snapshot_id=s.id)
 OR EXISTS(SELECT 1 FROM source_expiry_events WHERE owner_id=p_owner AND fx_snapshot_id=s.id)
 OR acquisition_source_restricted(p_owner,'fx',s.id,p_at,'store')
 OR acquisition_source_restricted(p_owner,'fx',s.id,p_at,'display') THEN RETURN NULL; END IF;
 SELECT * INTO pinned FROM provider_license_versions WHERE owner_id=p_owner AND id=s.license_version_id AND provider_id=s.provider_id;
 SELECT * INTO current_license FROM provider_license_versions WHERE owner_id=p_owner AND provider_id=s.provider_id AND effective_at<=p_at
 ORDER BY effective_at DESC,version_number DESC,id DESC LIMIT 1;
 IF pinned.id IS NULL OR current_license.id IS NULL OR pinned.effective_at>p_at OR pinned.store_permission<>'allowed'
 OR pinned.display_permission<>'allowed' OR current_license.store_permission<>'allowed' OR current_license.display_permission<>'allowed'
 OR pinned.retention_days IS NULL OR current_license.retention_days IS NULL
 OR NOT EXISTS(SELECT 1 FROM market_data_providers WHERE owner_id=p_owner AND id=s.provider_id AND configuration_state='configured')
 OR s.expires_at>s.first_observed_at+make_interval(days=>least(pinned.retention_days,current_license.retention_days)) THEN RETURN NULL; END IF;
 RETURN s.expires_at;
END $$;
CREATE FUNCTION aggregate_q18_ratio(p_n numeric,p_d numeric) RETURNS numeric LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE whole numeric; remainder numeric; denominator numeric; numerator numeric; direction integer;
BEGIN
 IF p_d=0 THEN RAISE EXCEPTION 'zero aggregate denominator' USING ERRCODE='23514'; END IF;
 direction:=CASE WHEN (p_n<0)<>(p_d<0) THEN -1 ELSE 1 END;
 numerator:=abs(p_n)*1000000000000000000; denominator:=abs(p_d);
 whole:=div(numerator,denominator); remainder:=mod(numerator,denominator);
 IF remainder*2>denominator OR (remainder*2=denominator AND mod(whole,2)=1) THEN whole:=whole+1; END IF;
 RETURN (direction*whole/1000000000000000000)::numeric(38,18);
END $$;
CREATE FUNCTION aggregate_parent_has_copies(p_owner uuid,p_kind text,p_source uuid)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM aggregate_sources WHERE owner_id=p_owner AND source_kind=p_kind AND source_id=p_source)
$$;
"""

_ROOT_GUARD = r"""
CREATE FUNCTION aggregate_root_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE root aggregate_runs; selection aggregate_selections; anchor uuid; n bigint; complete boolean;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'aggregate root is a permanent tombstone' USING ERRCODE='23514'; END IF;
 PERFORM aggregate_owner_lock(NEW.owner_id);
 IF TG_OP='UPDATE' THEN
  IF NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
  IF TG_TABLE_NAME='aggregate_selections' THEN
   IF NOT OLD.sealed AND NEW.sealed AND (to_jsonb(NEW)-'sealed')=(to_jsonb(OLD)-'sealed') THEN RETURN NEW; END IF;
   IF OLD.sealed AND NEW.revision=OLD.revision+1 AND (to_jsonb(NEW)-'revision')=(to_jsonb(OLD)-'revision') THEN RETURN NEW; END IF;
  ELSE
   IF pg_trigger_depth()>1 AND (to_jsonb(NEW)-ARRAY['reserved_bytes','retained_bytes','financial_rows'])=(to_jsonb(OLD)-ARRAY['reserved_bytes','retained_bytes','financial_rows']) THEN RETURN NEW; END IF;
   IF NOT OLD.sealed AND NEW.expires_at<=OLD.expires_at AND NEW.expires_at>clock_timestamp()
    AND (to_jsonb(NEW)-ARRAY['holdings_input_digest','holdings_result_digest','activity_input_digest','activity_result_digest','expires_at','sealed','completed_at','reserved_bytes'])
     =(to_jsonb(OLD)-ARRAY['holdings_input_digest','holdings_result_digest','activity_input_digest','activity_result_digest','expires_at','sealed','completed_at','reserved_bytes']) THEN
    IF NEW.sealed THEN
     IF NEW.reserved_bytes<>0 OR NEW.completed_at IS NULL OR NEW.completed_at<NEW.created_at THEN RAISE EXCEPTION 'aggregate sealing is incomplete' USING ERRCODE='23514'; END IF;
     UPDATE premium_owner_capacity SET reserved_bytes=reserved_bytes-OLD.reserved_bytes,updated_at=statement_timestamp() WHERE owner_id=NEW.owner_id;
    ELSIF NEW.reserved_bytes<>OLD.reserved_bytes THEN RAISE EXCEPTION 'aggregate reservation is trigger-owned' USING ERRCODE='23514'; END IF;
    RETURN NEW;
   END IF;
  END IF;
  RAISE EXCEPTION 'aggregate root is immutable' USING ERRCODE='23514';
 END IF;
 IF TG_TABLE_NAME='aggregate_selections' THEN
  IF NEW.sealed OR NEW.revision<>1 OR NOT aggregate_actor_valid(NEW.owner_id,NEW.actor_id,true,false) THEN RAISE EXCEPTION 'aggregate selection admission invalid' USING ERRCODE='23514'; END IF;
 ELSE
  IF NOT pg_try_advisory_xact_lock(hashtextextended('premium:single-execution-slot',0))
   OR EXISTS(SELECT 1 FROM premium_jobs WHERE state='running') THEN RAISE EXCEPTION 'premium executor busy' USING ERRCODE='55P03'; END IF;
  SELECT * INTO selection FROM aggregate_selections WHERE owner_id=NEW.owner_id AND id=NEW.selection_id FOR UPDATE;
  IF selection.id IS NULL OR NOT selection.sealed OR NEW.selection_revision<>selection.revision+1
   OR NEW.sealed OR NEW.completed_at IS NOT NULL OR NEW.holdings_input_digest IS NOT NULL OR NEW.holdings_result_digest IS NOT NULL
   OR NEW.activity_input_digest IS NOT NULL OR NEW.activity_result_digest IS NOT NULL
   OR NEW.reserved_bytes<>33554432 OR NEW.retained_bytes<>0 OR NEW.financial_rows<>0
   OR NOT aggregate_actor_valid(NEW.owner_id,NEW.actor_id,true,NEW.activity_requested)
   OR EXISTS(SELECT 1 FROM aggregate_owner_erasure WHERE owner_id=NEW.owner_id)
   THEN RAISE EXCEPTION 'aggregate run admission invalid' USING ERRCODE='23514'; END IF;
  INSERT INTO premium_owner_capacity(owner_id,reserved_bytes,retained_bytes,active_jobs,definition_versions,updated_at)
   VALUES(NEW.owner_id,0,0,0,0,statement_timestamp()) ON CONFLICT(owner_id) DO NOTHING;
  UPDATE premium_owner_capacity SET reserved_bytes=reserved_bytes+NEW.reserved_bytes,updated_at=statement_timestamp()
   WHERE owner_id=NEW.owner_id AND active_jobs<2 AND reserved_bytes+retained_bytes+NEW.reserved_bytes<=268435456;
  IF NOT FOUND THEN RAISE EXCEPTION 'aggregate owner capacity exceeded' USING ERRCODE='23514'; END IF;
  IF (SELECT count(*) FROM premium_jobs WHERE owner_id=NEW.owner_id AND state IN ('queued','running'))>=2 THEN
   RAISE EXCEPTION 'aggregate owner active capacity exceeded' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION aggregate_selection_child_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE selection aggregate_selections;
BEGIN
 IF TG_OP<>'INSERT' THEN
  IF TG_OP='DELETE' AND TG_TABLE_NAME='aggregate_selection_payloads' THEN
   PERFORM aggregate_owner_lock(OLD.owner_id);
   IF EXISTS(SELECT 1 FROM aggregate_owner_erasure WHERE owner_id=OLD.owner_id)
    AND NOT EXISTS(SELECT 1 FROM aggregate_runs WHERE owner_id=OLD.owner_id AND selection_id=OLD.selection_id AND retained_bytes>0) THEN RETURN OLD; END IF;
  END IF;
  RAISE EXCEPTION 'aggregate selected identity is immutable' USING ERRCODE='23514';
 END IF;
 SELECT * INTO selection FROM aggregate_selections WHERE owner_id=NEW.owner_id AND id=NEW.selection_id FOR UPDATE;
 IF selection.id IS NULL OR selection.sealed OR EXISTS(SELECT 1 FROM aggregate_owner_erasure WHERE owner_id=NEW.owner_id) THEN RAISE EXCEPTION 'aggregate selection is sealed or absent' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='aggregate_account_members' THEN
  IF NEW.ordinal>=selection.member_count OR NOT EXISTS(SELECT 1 FROM broker_accounts a JOIN broker_connections c ON c.id=a.connection_id
    JOIN portfolio_snapshots s ON s.broker_account_id=a.id WHERE a.id=NEW.account_id AND s.id=NEW.snapshot_id
    AND c.owner_id=NEW.owner_id AND a.status='active' AND c.status='active' AND s.source_cutoff_at<=selection.source_cutoff_at) THEN
   RAISE EXCEPTION 'aggregate member snapshot differs from its owner/account' USING ERRCODE='23514'; END IF;
 ELSE
  IF aggregate_digest(NEW.payload)<>selection.content_digest THEN RAISE EXCEPTION 'aggregate selection digest differs' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
"""

_CHILD_GUARD = r"""
CREATE FUNCTION aggregate_child_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE root aggregate_runs; selection aggregate_selections; body jsonb; native jsonb; actual record; expected numeric;
 owner uuid; target uuid; original bytea; current_limit timestamptz;
BEGIN
 IF TG_OP='DELETE' THEN owner:=OLD.owner_id; target:=OLD.run_id; ELSE owner:=NEW.owner_id; target:=NEW.run_id; END IF;
 PERFORM aggregate_owner_lock(owner);
 SELECT * INTO root FROM aggregate_runs WHERE owner_id=owner AND id=target FOR UPDATE;
 IF root.id IS NULL THEN RAISE EXCEPTION 'aggregate run absent' USING ERRCODE='23514'; END IF;
 IF TG_OP<>'INSERT' THEN
  IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'aggregate financial projection is immutable' USING ERRCODE='23514'; END IF;
  IF NOT EXISTS(SELECT 1 FROM aggregate_retention_work WHERE owner_id=owner AND run_id=target) THEN
   RAISE EXCEPTION 'aggregate purge requires its permanent marker' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME='aggregate_sources' AND root.financial_rows<>0 THEN
   RAISE EXCEPTION 'aggregate source membership outlives every financial copy' USING ERRCODE='23514'; END IF;
  RETURN OLD;
 END IF;
 IF root.sealed OR root.expires_at<=clock_timestamp() OR EXISTS(SELECT 1 FROM aggregate_retention_work WHERE owner_id=owner AND run_id=target) THEN
  RAISE EXCEPTION 'aggregate run is sealed or expired' USING ERRCODE='23514'; END IF;
 SELECT * INTO selection FROM aggregate_selections WHERE owner_id=owner AND id=root.selection_id;
 IF TG_TABLE_NAME IN ('aggregate_holdings_payloads','aggregate_activity_payloads') THEN
  IF aggregate_digest(NEW.input_payload) IS DISTINCT FROM (CASE TG_TABLE_NAME WHEN 'aggregate_holdings_payloads' THEN root.holdings_input_digest ELSE root.activity_input_digest END)
   OR aggregate_digest(NEW.result_payload) IS DISTINCT FROM (CASE TG_TABLE_NAME WHEN 'aggregate_holdings_payloads' THEN root.holdings_result_digest ELSE root.activity_result_digest END)
   OR aggregate_digest(NEW.summary_payload) IS DISTINCT FROM NEW.summary_digest THEN RAISE EXCEPTION 'aggregate canonical payload digest differs' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME='aggregate_activity_payloads' AND NOT root.activity_requested THEN RAISE EXCEPTION 'aggregate activity was not selected' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='aggregate_sources' THEN RETURN NEW; END IF;
 IF aggregate_digest(NEW.payload) IS DISTINCT FROM NEW.content_digest THEN RAISE EXCEPTION 'aggregate projection digest differs' USING ERRCODE='23514'; END IF;
 body:=convert_from(NEW.payload,'UTF8')::jsonb;
 IF TG_TABLE_NAME IN ('aggregate_input_members','aggregate_fx_uses','aggregate_components','aggregate_account_totals','aggregate_transfer_evidence','aggregate_activity_coverage','aggregate_activity_revisions','aggregate_flow_legs') THEN
  IF NOT EXISTS(SELECT 1 FROM aggregate_account_members m JOIN broker_accounts a ON a.id=m.account_id JOIN broker_connections c ON c.id=a.connection_id
   WHERE m.owner_id=owner AND m.selection_id=root.selection_id AND m.account_id=NEW.account_id AND a.status='active' AND c.status='active' AND c.owner_id=owner) THEN
   RAISE EXCEPTION 'aggregate projection account is outside selected members' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='aggregate_input_members' THEN
  SELECT s.*,r.output_fingerprint INTO actual FROM portfolio_snapshots s JOIN calculation_runs r ON r.id=s.calculation_run_id
   JOIN aggregate_account_members m ON m.snapshot_id=s.id AND m.account_id=s.broker_account_id
   WHERE m.owner_id=owner AND m.selection_id=root.selection_id AND m.ordinal=NEW.ordinal AND s.id=NEW.snapshot_id AND s.broker_account_id=NEW.account_id;
  IF actual.id IS NULL OR actual.calculation_run_id<>NEW.calculation_run_id OR body->>'content_digest' IS DISTINCT FROM actual.output_fingerprint
   OR (body->>'portfolio_snapshot_id')::uuid IS DISTINCT FROM actual.id OR (body->>'account_id')::uuid IS DISTINCT FROM actual.broker_account_id
   OR (body->>'calculation_run_id')::uuid IS DISTINCT FROM actual.calculation_run_id OR (body->>'valuation_at')::timestamptz IS DISTINCT FROM actual.valuation_at
   OR (body->>'source_cutoff_at')::timestamptz IS DISTINCT FROM actual.source_cutoff_at OR body->>'calculation_version' IS DISTINCT FROM actual.calculation_version
   OR body->>'quality' IS DISTINCT FROM actual.quality_state OR body->>'reporting_currency' IS DISTINCT FROM actual.reporting_currency THEN
   RAISE EXCEPTION 'aggregate saved snapshot proof differs' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='aggregate_fx_uses' THEN
  SELECT o.*,s.provider_id,s.license_version_id,s.content_digest,s.first_observed_at,s.quality INTO actual FROM fx_observations o JOIN fx_snapshots s ON s.owner_id=o.owner_id AND s.id=o.snapshot_id
   WHERE o.owner_id=owner AND o.id=NEW.fx_observation_id AND s.id=NEW.fx_snapshot_id;
  current_limit:=aggregate_fx_until(owner,NEW.fx_snapshot_id,clock_timestamp());
  IF actual.id IS NULL OR current_limit IS NULL OR root.expires_at>current_limit OR actual.rate IS DISTINCT FROM NEW.original_rate OR actual.state IS DISTINCT FROM NEW.state
   OR actual.license_version_id IS DISTINCT FROM NEW.license_version_id OR NEW.target_currency<>selection.reporting_currency
   OR NEW.source_currency=NEW.target_currency OR (CASE WHEN NEW.inverted THEN ROW(actual.quote,actual.base) ELSE ROW(actual.base,actual.quote) END) IS DISTINCT FROM ROW(NEW.source_currency,NEW.target_currency)
   OR body->>'snapshot_digest' IS DISTINCT FROM actual.content_digest OR (body->>'provider_id')::uuid IS DISTINCT FROM actual.provider_id
   OR (body->>'effective_at')::timestamptz IS DISTINCT FROM actual.effective_at OR (body->>'first_known_at')::timestamptz IS DISTINCT FROM actual.first_observed_at
   OR body->>'quality' IS DISTINCT FROM actual.quality OR (body->>'original_rate')::numeric IS DISTINCT FROM actual.rate
   OR NOT EXISTS(SELECT 1 FROM aggregate_input_members m JOIN portfolio_snapshots s ON s.id=m.snapshot_id WHERE m.owner_id=owner AND m.run_id=target AND m.account_id=NEW.account_id AND actual.effective_at<=s.valuation_at AND actual.first_observed_at<=selection.source_cutoff_at) THEN
   RAISE EXCEPTION 'aggregate original FX proof differs or is unavailable' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='aggregate_components' THEN
  native:=body->'native';
  IF NEW.kind='position' THEN
   SELECT p.snapshot_id,p.id,p.listing_id,l.instrument_id,p.quantity,p.market_value AS value,p.currency,p.quality_state,p.value_origin,p.provenance INTO actual FROM snapshot_positions p JOIN listings l ON l.id=p.listing_id WHERE p.id=NEW.position_id;
  ELSE
   SELECT c.snapshot_id,c.id,NULL::uuid AS listing_id,NULL::uuid AS instrument_id,NULL::numeric AS quantity,c.amount AS value,c.currency,c.quality_state,c.value_origin,c.provenance INTO actual FROM snapshot_cash c WHERE c.id=NEW.cash_id;
  END IF;
  IF actual.id IS NULL OR ROW(actual.id,actual.snapshot_id,actual.listing_id,actual.instrument_id,actual.quantity,actual.value,actual.currency,actual.value_origin)
    IS DISTINCT FROM ROW(NEW.component_id,NEW.snapshot_id,NEW.listing_id,NEW.instrument_id,NEW.quantity,NEW.native_value,NEW.native_currency,NEW.origin)
   OR NOT EXISTS(SELECT 1 FROM aggregate_input_members WHERE owner_id=owner AND run_id=target AND account_id=NEW.account_id AND snapshot_id=NEW.snapshot_id)
   OR (native->>'component_id')::uuid IS DISTINCT FROM actual.id OR (native->>'portfolio_snapshot_id')::uuid IS DISTINCT FROM actual.snapshot_id
   OR (native->>'account_id')::uuid IS DISTINCT FROM NEW.account_id OR native->>'kind' IS DISTINCT FROM NEW.kind
   OR (native->>'listing_id')::uuid IS DISTINCT FROM actual.listing_id OR (native->>'instrument_id')::uuid IS DISTINCT FROM actual.instrument_id
   OR (native->>'quantity')::numeric IS DISTINCT FROM actual.quantity OR (native->>'native_value')::numeric IS DISTINCT FROM actual.value
   OR native->>'native_currency' IS DISTINCT FROM actual.currency OR native->>'quality' IS DISTINCT FROM actual.quality_state
   OR native->>'origin' IS DISTINCT FROM actual.value_origin
   OR ARRAY(SELECT jsonb_array_elements_text(native->'source_record_ids') ORDER BY 1) IS DISTINCT FROM ARRAY(SELECT jsonb_array_elements_text(actual.provenance->'source_record_ids') ORDER BY 1)
   OR body->>'reporting_currency' IS DISTINCT FROM selection.reporting_currency OR NEW.reporting_currency<>selection.reporting_currency
   OR (body->>'converted_value')::numeric IS DISTINCT FROM NEW.converted_value OR body->>'reason' IS DISTINCT FROM NEW.reason OR body->>'quality' IS DISTINCT FROM NEW.quality THEN
   RAISE EXCEPTION 'aggregate native component proof differs' USING ERRCODE='23514'; END IF;
  IF NEW.native_currency=NEW.reporting_currency THEN expected:=NEW.native_value;
  ELSIF NEW.native_value IS NULL THEN expected:=NULL;
  ELSE
   SELECT original_rate,inverted,fx_observation_id INTO actual FROM aggregate_fx_uses WHERE owner_id=owner AND run_id=target AND account_id=NEW.account_id AND source_currency=NEW.native_currency;
   expected:=CASE WHEN actual.original_rate IS NULL THEN NULL WHEN actual.inverted THEN aggregate_q18_ratio(NEW.native_value,actual.original_rate) ELSE aggregate_q18_ratio(NEW.native_value*actual.original_rate,1) END;
   IF actual.fx_observation_id IS DISTINCT FROM NEW.fx_observation_id THEN RAISE EXCEPTION 'aggregate FX identity differs' USING ERRCODE='23514'; END IF;
  END IF;
  IF NEW.converted_value IS DISTINCT FROM expected THEN RAISE EXCEPTION 'aggregate Q18 conversion differs' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='aggregate_transfer_evidence' THEN
  SELECT * INTO actual FROM source_records WHERE id=NEW.source_record_id AND broker_account_id=NEW.account_id AND observed_at<=selection.source_cutoff_at;
  IF actual.id IS NULL OR actual.sanitized_payload IS NULL OR body->>'payload_digest' IS DISTINCT FROM actual.payload_fingerprint
   OR body->>'provider' IS DISTINCT FROM actual.provider OR body->>'external_record_id' IS DISTINCT FROM actual.provider_record_id
   OR body->>'schema_version' IS DISTINCT FROM actual.schema_version OR (body->>'source_updated_at')::timestamptz IS DISTINCT FROM actual.source_updated_at
   OR (body->>'first_observed_at')::timestamptz IS DISTINCT FROM actual.observed_at OR (body->>'source_record_id')::uuid IS DISTINCT FROM actual.id
   OR (body->>'account_id')::uuid IS DISTINCT FROM actual.broker_account_id OR (body->>'amount')::numeric IS DISTINCT FROM NEW.amount
   OR body->>'currency' IS DISTINCT FROM NEW.currency OR (body->>'selected')::boolean IS DISTINCT FROM NEW.selected THEN
   RAISE EXCEPTION 'aggregate activity source proof differs' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='aggregate_activity_coverage' THEN
  SELECT c.*,h.broker_account_id,h.content_digest,h.sealed,octet_length(h.canonical_evidence) AS bytes,r.broker_account_id AS ingestion_account INTO actual
   FROM historical_activity_coverage c JOIN historical_evidence_sets h ON h.owner_id=c.owner_id AND h.id=c.evidence_id JOIN ingestion_runs r ON r.id=c.ingestion_run_id
   WHERE c.owner_id=owner AND c.id=NEW.coverage_id;
  IF actual.id IS NULL OR NOT actual.sealed OR actual.bytes=0 OR ROW(actual.evidence_id,actual.content_digest,actual.broker_account_id,actual.ingestion_account,actual.ingestion_run_id,actual.capability,actual.start_at,actual.end_at,actual.first_observed_at,actual.coverage_complete)
   IS DISTINCT FROM ROW(NEW.evidence_id,NEW.evidence_digest,NEW.account_id,NEW.account_id,NEW.ingestion_run_id,NEW.capability,NEW.start_at,NEW.end_at,NEW.first_observed_at,NEW.complete)
   OR actual.first_observed_at>selection.source_cutoff_at OR (body->>'coverage_id')::uuid IS DISTINCT FROM actual.id
   OR (body->>'historical_evidence_id')::uuid IS DISTINCT FROM actual.evidence_id OR body->>'evidence_digest' IS DISTINCT FROM actual.content_digest
   OR (body->>'account_id')::uuid IS DISTINCT FROM actual.broker_account_id OR (body->>'ingestion_run_id')::uuid IS DISTINCT FROM actual.ingestion_run_id
   OR body->>'capability' IS DISTINCT FROM actual.capability OR (body->>'start_at')::timestamptz IS DISTINCT FROM actual.start_at
   OR (body->>'end_at')::timestamptz IS DISTINCT FROM actual.end_at OR (body->>'first_observed_at')::timestamptz IS DISTINCT FROM actual.first_observed_at
   OR (body->>'complete')::boolean IS DISTINCT FROM actual.coverage_complete THEN
   RAISE EXCEPTION 'aggregate coverage parent or original limitations differ' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='aggregate_activity_revisions' THEN
  SELECT * INTO actual FROM activity_revision_evidence WHERE owner_id=owner AND id=NEW.evidence_id;
  IF actual.id IS NULL OR ROW(actual.broker_account_id,actual.new_source_record_id,actual.superseded_source_record_id) IS DISTINCT FROM ROW(NEW.account_id,NEW.new_source_record_id,NEW.superseded_source_record_id)
   OR actual.first_observed_at>selection.source_cutoff_at OR body->>'content_digest' IS DISTINCT FROM actual.content_digest
   OR (body->>'owner_id')::uuid IS DISTINCT FROM actual.owner_id OR (body->>'principal_id')::uuid IS DISTINCT FROM actual.principal_id
   OR body->>'authority' IS DISTINCT FROM actual.authority OR body->>'evidence_key' IS DISTINCT FROM actual.evidence_key
   OR body->>'economic_key' IS DISTINCT FROM actual.economic_key OR (body->>'first_observed_at')::timestamptz IS DISTINCT FROM actual.first_observed_at THEN
   RAISE EXCEPTION 'aggregate original revision proof differs' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='aggregate_flow_legs' THEN
  SELECT * INTO actual FROM aggregate_transfer_evidence WHERE owner_id=owner AND run_id=target AND source_record_id=NEW.source_record_id;
  IF actual.id IS NULL OR NOT actual.selected OR ROW(actual.account_id,actual.amount,actual.currency) IS DISTINCT FROM ROW(NEW.account_id,NEW.amount,NEW.currency)
   OR (body->>'source_record_id')::uuid IS DISTINCT FROM NEW.source_record_id OR body->>'classification' IS DISTINCT FROM NEW.classification
   OR (body->>'counterpart_record_id')::uuid IS DISTINCT FROM NEW.counterpart_record_id THEN RAISE EXCEPTION 'aggregate flow proof differs' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
"""

# Upgrade constructs static branches from only the just-created, closed table
# inventory. No catalog access/dynamic table dispatch occurs on row mutation.
_COSTS = r"""
DO $migration$
DECLARE table_name text; meta text; payload text; expression_new text; expression_old text;
 table_expression text; charge text:=''; storage text:=''; selected text:='';
BEGIN
 FOREACH table_name IN ARRAY ARRAY['aggregate_holdings_payloads','aggregate_activity_payloads','aggregate_input_members','aggregate_fx_uses','aggregate_components','aggregate_holdings','aggregate_account_totals','aggregate_transfer_evidence','aggregate_activity_coverage','aggregate_activity_revisions','aggregate_flow_legs','aggregate_transfer_matches','aggregate_sources'] LOOP
  SELECT string_agg(format('%I',a.attname),',' ORDER BY a.attnum) INTO meta FROM pg_attribute a
   WHERE a.attrelid=table_name::regclass AND a.attnum>0 AND NOT a.attisdropped AND a.atttypid<>'bytea'::regtype;
  SELECT string_agg(format('octet_length(NEW.%I)',a.attname),'+' ORDER BY a.attnum) INTO payload FROM pg_attribute a
   WHERE a.attrelid=table_name::regclass AND a.attnum>0 AND NOT a.attisdropped AND a.atttypid='bytea'::regtype;
  expression_new:='pg_column_size(ROW(NEW.'||replace(meta,',',',NEW.')||'))'||CASE WHEN payload IS NULL THEN '' ELSE '+'||payload END;
  expression_old:=replace(expression_new,'NEW.','OLD.');
  table_expression:=replace(expression_new,'NEW.','t.');
  charge:=charge||format('WHEN %L THEN IF TG_OP=''DELETE'' THEN delta:=-(%s); ELSE delta:=(%s); END IF;',table_name,expression_old,expression_new);
  storage:=storage||CASE WHEN storage='' THEN '' ELSE ' UNION ALL ' END||format('SELECT (%s)::bigint bytes FROM %I t WHERE t.run_id=p_run',table_expression,table_name);
  selected:=selected||format('WHEN %L THEN SELECT (%s)::bigint INTO result FROM %I t WHERE t.id=p_id;',table_name,table_expression,table_name);
 END LOOP;
 EXECUTE 'CREATE FUNCTION aggregate_storage_bytes(p_run uuid) RETURNS bigint LANGUAGE sql STABLE AS $fn$ SELECT coalesce(sum(bytes),0)::bigint FROM ('||storage||') bounded_rows $fn$';
 EXECUTE 'CREATE FUNCTION aggregate_row_cost(p_table text,p_id uuid) RETURNS bigint LANGUAGE plpgsql STABLE AS $fn$ DECLARE result bigint; BEGIN CASE p_table '||selected||' ELSE RAISE EXCEPTION ''unknown aggregate cost table'' USING ERRCODE=''23514''; END CASE; RETURN result; END $fn$';
 EXECUTE 'CREATE FUNCTION aggregate_payload_charge() RETURNS trigger LANGUAGE plpgsql AS $fn$
 DECLARE owner uuid; target uuid; delta bigint; released bigint; root aggregate_runs; row_delta integer;
 BEGIN
  IF TG_OP=''DELETE'' THEN owner:=OLD.owner_id; target:=OLD.run_id; row_delta:=-1;
  ELSE owner:=NEW.owner_id; target:=NEW.run_id; row_delta:=1; END IF;
  PERFORM aggregate_owner_lock(owner);
  CASE TG_TABLE_NAME '||charge||' ELSE RAISE EXCEPTION ''unknown aggregate payload table'' USING ERRCODE=''23514''; END CASE;
  SELECT * INTO root FROM aggregate_runs WHERE owner_id=owner AND id=target FOR UPDATE;
  released:=CASE WHEN delta>0 THEN least(root.reserved_bytes,delta) ELSE 0 END;
  IF delta>0 AND (root.sealed OR released<>delta) THEN RAISE EXCEPTION ''aggregate reserved capacity exhausted'' USING ERRCODE=''23514''; END IF;
  UPDATE aggregate_runs SET retained_bytes=retained_bytes+delta,reserved_bytes=reserved_bytes-released,
   financial_rows=financial_rows+CASE WHEN TG_TABLE_NAME=''aggregate_sources'' THEN 0 ELSE row_delta END WHERE id=target AND owner_id=owner;
  UPDATE premium_owner_capacity SET retained_bytes=retained_bytes+delta,reserved_bytes=reserved_bytes-released,updated_at=statement_timestamp() WHERE owner_id=owner;
  IF NOT FOUND THEN RAISE EXCEPTION ''aggregate shared capacity absent'' USING ERRCODE=''23514''; END IF;
  RETURN NULL;
 END $fn$';
END $migration$;
"""

_COMPLETE = r"""
CREATE FUNCTION aggregate_projection_inventory(p_run uuid,p_table text,p_expected jsonb)
RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE count_rows bigint; last_ordinal integer; mismatch boolean;
BEGIN
 IF p_table NOT IN ('aggregate_input_members','aggregate_fx_uses','aggregate_components','aggregate_holdings','aggregate_account_totals','aggregate_transfer_evidence','aggregate_activity_coverage','aggregate_activity_revisions','aggregate_flow_legs','aggregate_transfer_matches')
  OR jsonb_typeof(p_expected) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 EXECUTE format('SELECT count(*),max(ordinal),coalesce(bool_or(convert_from(payload,''UTF8'')::jsonb IS DISTINCT FROM $2->ordinal),false) FROM %I WHERE run_id=$1',p_table)
  INTO count_rows,last_ordinal,mismatch USING p_run,p_expected;
 RETURN count_rows=jsonb_array_length(p_expected) AND (count_rows=0 OR last_ordinal=count_rows-1) AND NOT mismatch;
END $$;
CREATE FUNCTION aggregate_sources_complete(p_run uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 WITH wanted(view_kind,source_kind,source_id) AS (
  SELECT 'holdings','snapshot',snapshot_id FROM aggregate_input_members WHERE run_id=p_run
  UNION SELECT 'holdings','calculation',calculation_run_id FROM aggregate_input_members WHERE run_id=p_run
  UNION SELECT 'holdings','broker_record',value::uuid FROM aggregate_components c CROSS JOIN LATERAL jsonb_array_elements_text(convert_from(c.payload,'UTF8')::jsonb->'native'->'source_record_ids') value WHERE c.run_id=p_run
  UNION SELECT 'holdings','fx',fx_snapshot_id FROM aggregate_fx_uses WHERE run_id=p_run
  UNION SELECT 'holdings','fx_observation',fx_observation_id FROM aggregate_fx_uses WHERE run_id=p_run
  UNION SELECT 'activity','broker_record',source_record_id FROM aggregate_transfer_evidence WHERE run_id=p_run
  UNION SELECT 'activity','coverage',coverage_id FROM aggregate_activity_coverage WHERE run_id=p_run
  UNION SELECT 'activity','coverage_parent',evidence_id FROM aggregate_activity_coverage WHERE run_id=p_run
  UNION SELECT 'activity','revision',evidence_id FROM aggregate_activity_revisions WHERE run_id=p_run
 ), actual AS (SELECT view_kind,source_kind,source_id FROM aggregate_sources WHERE run_id=p_run)
 SELECT NOT EXISTS((SELECT * FROM wanted EXCEPT SELECT * FROM actual) UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM wanted))
$$;
CREATE FUNCTION aggregate_run_complete(p_run uuid) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE root aggregate_runs; selected aggregate_selections; selection_body jsonb; input_body jsonb; result_body jsonb; summary_body jsonb;
 input_activity jsonb; result_activity jsonb; summary_activity jsonb; financial_count bigint; actual_bytes bigint; original_members jsonb;
BEGIN
 SELECT * INTO root FROM aggregate_runs WHERE id=p_run;
 IF root.id IS NULL OR NOT root.sealed OR root.reserved_bytes<>0 OR root.completed_at IS NULL OR root.expires_at<=root.completed_at THEN RETURN false; END IF;
 SELECT * INTO selected FROM aggregate_selections WHERE owner_id=root.owner_id AND id=root.selection_id;
 SELECT convert_from(payload,'UTF8')::jsonb INTO selection_body FROM aggregate_selection_payloads WHERE owner_id=root.owner_id AND selection_id=root.selection_id;
 SELECT convert_from(input_payload,'UTF8')::jsonb,convert_from(result_payload,'UTF8')::jsonb,convert_from(summary_payload,'UTF8')::jsonb
  INTO input_body,result_body,summary_body FROM aggregate_holdings_payloads WHERE owner_id=root.owner_id AND run_id=root.id;
 IF selected.id IS NULL OR NOT selected.sealed OR selection_body IS NULL OR input_body IS NULL OR result_body IS NULL OR summary_body IS NULL
  OR selected.revision<root.selection_revision OR input_body->'selection' IS DISTINCT FROM selection_body
  OR (input_body->>'owner_id')::uuid IS DISTINCT FROM root.owner_id OR result_body->>'input_digest' IS DISTINCT FROM root.holdings_input_digest
  OR result_body->'snapshots' IS DISTINCT FROM input_body->'snapshots'
  OR result_body->>'reporting_currency' IS DISTINCT FROM selected.reporting_currency
  OR (result_body->>'source_cutoff_at')::timestamptz IS DISTINCT FROM selected.source_cutoff_at
  OR result_body->>'method' IS DISTINCT FROM 'account_aggregation_v1' OR result_body->>'method_version' IS DISTINCT FROM '1.0.0'
  OR result_body->>'schema_version' IS DISTINCT FROM '1.0.0' OR result_body->>'numeric_profile' IS DISTINCT FROM 'premium_decimal96_q18_v1'
  OR NOT aggregate_projection_inventory(root.id,'aggregate_input_members',input_body->'snapshots')
  OR NOT aggregate_projection_inventory(root.id,'aggregate_fx_uses',input_body->'fx_uses')
  OR NOT aggregate_projection_inventory(root.id,'aggregate_components',result_body->'components')
  OR NOT aggregate_projection_inventory(root.id,'aggregate_holdings',result_body->'holdings')
  OR NOT aggregate_projection_inventory(root.id,'aggregate_account_totals',result_body->'accounts') THEN RETURN false; END IF;
 IF input_body->'components' IS DISTINCT FROM (SELECT coalesce(jsonb_agg(convert_from(payload,'UTF8')::jsonb->'native' ORDER BY ordinal),'[]'::jsonb) FROM aggregate_components WHERE run_id=root.id) THEN RETURN false; END IF;
 IF (summary_body-ARRAY['component_count','holding_count']) IS DISTINCT FROM (result_body-ARRAY['components','holdings','accounts','method','method_version','schema_version','numeric_profile'])
  OR (summary_body->>'component_count')::integer IS DISTINCT FROM jsonb_array_length(result_body->'components')
  OR (summary_body->>'holding_count')::integer IS DISTINCT FROM jsonb_array_length(result_body->'holdings') THEN RETURN false; END IF;
 IF root.activity_requested THEN
  SELECT convert_from(input_payload,'UTF8')::jsonb,convert_from(result_payload,'UTF8')::jsonb,convert_from(summary_payload,'UTF8')::jsonb
   INTO input_activity,result_activity,summary_activity FROM aggregate_activity_payloads WHERE owner_id=root.owner_id AND run_id=root.id;
  IF input_activity IS NULL OR result_activity IS NULL OR summary_activity IS NULL OR root.activity_input_digest IS NULL OR root.activity_result_digest IS NULL
   OR input_activity->>'holdings_input_digest' IS DISTINCT FROM root.holdings_input_digest
   OR result_activity->>'input_digest' IS DISTINCT FROM root.activity_input_digest OR result_activity->>'holdings_input_digest' IS DISTINCT FROM root.holdings_input_digest
   OR result_activity->'window' IS DISTINCT FROM input_activity->'window'
   OR (input_activity->'window'->>'start_at')::timestamptz IS DISTINCT FROM root.activity_start_at
   OR (input_activity->'window'->>'end_at')::timestamptz IS DISTINCT FROM root.activity_end_at
   OR input_activity->'account_ids' IS DISTINCT FROM (SELECT jsonb_agg(account_id ORDER BY ordinal) FROM aggregate_account_members WHERE selection_id=root.selection_id)
   OR NOT aggregate_projection_inventory(root.id,'aggregate_transfer_evidence',input_activity->'candidates')
   OR NOT aggregate_projection_inventory(root.id,'aggregate_activity_coverage',input_activity->'coverage')
   OR NOT aggregate_projection_inventory(root.id,'aggregate_activity_revisions',input_activity->'revisions')
   OR NOT aggregate_projection_inventory(root.id,'aggregate_flow_legs',result_activity->'legs')
   OR NOT aggregate_projection_inventory(root.id,'aggregate_transfer_matches',result_activity->'matches') THEN RETURN false; END IF;
  IF (summary_activity-'match_count') IS DISTINCT FROM (result_activity-ARRAY['legs','matches','method','method_version','schema_version','numeric_profile'])
   OR (summary_activity->>'match_count')::integer IS DISTINCT FROM jsonb_array_length(result_activity->'matches') THEN RETURN false; END IF;
 ELSE
  IF EXISTS(SELECT 1 FROM aggregate_activity_payloads WHERE run_id=root.id)
   OR EXISTS(SELECT 1 FROM aggregate_transfer_evidence WHERE run_id=root.id)
   OR EXISTS(SELECT 1 FROM aggregate_activity_coverage WHERE run_id=root.id)
   OR EXISTS(SELECT 1 FROM aggregate_activity_revisions WHERE run_id=root.id)
   OR EXISTS(SELECT 1 FROM aggregate_flow_legs WHERE run_id=root.id)
   OR EXISTS(SELECT 1 FROM aggregate_transfer_matches WHERE run_id=root.id) THEN RETURN false; END IF;
 END IF;
 IF NOT aggregate_sources_complete(root.id) THEN RETURN false; END IF;
 SELECT (SELECT count(*) FROM aggregate_holdings_payloads WHERE run_id=root.id)+(SELECT count(*) FROM aggregate_activity_payloads WHERE run_id=root.id)
  +(SELECT count(*) FROM aggregate_input_members WHERE run_id=root.id)+(SELECT count(*) FROM aggregate_fx_uses WHERE run_id=root.id)
  +(SELECT count(*) FROM aggregate_components WHERE run_id=root.id)+(SELECT count(*) FROM aggregate_holdings WHERE run_id=root.id)
  +(SELECT count(*) FROM aggregate_account_totals WHERE run_id=root.id)+(SELECT count(*) FROM aggregate_transfer_evidence WHERE run_id=root.id)
  +(SELECT count(*) FROM aggregate_activity_coverage WHERE run_id=root.id)+(SELECT count(*) FROM aggregate_activity_revisions WHERE run_id=root.id)
  +(SELECT count(*) FROM aggregate_flow_legs WHERE run_id=root.id)+(SELECT count(*) FROM aggregate_transfer_matches WHERE run_id=root.id) INTO financial_count;
 actual_bytes:=aggregate_storage_bytes(root.id);
 RETURN financial_count=root.financial_rows AND actual_bytes=root.retained_bytes AND actual_bytes<=33554432;
END $$;
CREATE FUNCTION aggregate_complete_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE selected aggregate_selections; body jsonb; root aggregate_runs; anchor uuid; target uuid;
BEGIN
 IF TG_TABLE_NAME='aggregate_runs' THEN
  IF NOT aggregate_run_complete(NEW.id) OR NOT aggregate_financial_complete(NEW.id) THEN RAISE EXCEPTION 'aggregate publication incomplete' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='aggregate_selections' THEN
  SELECT * INTO selected FROM aggregate_selections WHERE id=NEW.id;
  SELECT convert_from(payload,'UTF8')::jsonb INTO body FROM aggregate_selection_payloads WHERE selection_id=NEW.id;
  IF NOT selected.sealed OR body IS NULL OR body->>'economic_identity_policy' IS DISTINCT FROM selected.identity_policy
   OR body->>'reporting_currency' IS DISTINCT FROM selected.reporting_currency OR (body->>'source_cutoff_at')::timestamptz IS DISTINCT FROM selected.source_cutoff_at
   OR body->'members' IS DISTINCT FROM (SELECT jsonb_agg(jsonb_build_object('account_id',account_id,'portfolio_snapshot_id',snapshot_id) ORDER BY ordinal) FROM aggregate_account_members WHERE selection_id=NEW.id)
   OR selected.member_count<>jsonb_array_length(body->'members') THEN RAISE EXCEPTION 'aggregate selection publication incomplete' USING ERRCODE='23514'; END IF;
  IF selected.revision>1 AND NOT EXISTS(SELECT 1 FROM aggregate_runs WHERE selection_id=selected.id AND selection_revision=selected.revision AND sealed) THEN
   RAISE EXCEPTION 'aggregate operational revision has no completed run' USING ERRCODE='23514'; END IF;
 ELSE
  IF NEW.command='aggregate.selection.create.v1' THEN
   SELECT * INTO selected FROM aggregate_selections WHERE owner_id=NEW.owner_id AND id=NEW.premium_resource_id AND command_id=NEW.id AND actor_id=NEW.premium_actor_id;
   target:=selected.id;
  ELSIF NEW.command='aggregate.run.create.v1' THEN
   SELECT * INTO root FROM aggregate_runs WHERE owner_id=NEW.owner_id AND id=NEW.premium_resource_id AND command_id=NEW.id AND actor_id=NEW.premium_actor_id AND sealed;
   target:=root.selection_id;
  ELSE RETURN NEW; END IF;
  SELECT account_id INTO anchor FROM aggregate_account_members WHERE owner_id=NEW.owner_id AND selection_id=target AND ordinal=0;
  IF target IS NULL OR anchor IS DISTINCT FROM NEW.account_id THEN RAISE EXCEPTION 'aggregate command anchor or original actor differs' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
"""

_ECONOMICS = r"""
CREATE FUNCTION aggregate_money_matches(p_money jsonb,p_currency text,p_count bigint,p_known bigint,p_sum numeric)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT p_money->>'currency'=p_currency
 AND (p_money->>'total_count')::bigint=p_count AND (p_money->>'known_count')::bigint=p_known
 AND (p_money->>'known_value')::numeric=coalesce(p_sum,0)
 AND (p_money->>'value')::numeric IS NOT DISTINCT FROM CASE WHEN p_count=p_known THEN coalesce(p_sum,0) ELSE NULL END
$$;
CREATE FUNCTION aggregate_financial_complete(p_run uuid) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE body jsonb; currency text; row record; money jsonb; total bigint; known bigint; amount numeric;
BEGIN
 SELECT convert_from(result_payload,'UTF8')::jsonb INTO body FROM aggregate_holdings_payloads WHERE run_id=p_run;
 currency:=body->>'reporting_currency';
 FOR row IN SELECT category FROM unnest(ARRAY['total','securities','cash']) category LOOP
  SELECT count(*),count(converted_value),sum(converted_value) INTO total,known,amount FROM aggregate_components
   WHERE run_id=p_run AND (row.category='total' OR (row.category='cash' AND kind='cash') OR (row.category='securities' AND kind='position'));
  IF NOT coalesce(aggregate_money_matches(body->row.category,currency,total,known,amount),false) THEN RETURN false; END IF;
 END LOOP;
 FOR row IN SELECT h.*,convert_from(h.payload,'UTF8')::jsonb AS body,c.quantity AS wanted_quantity,c.amount,c.total,c.known
  FROM aggregate_holdings h JOIN (SELECT instrument_id,sum(quantity) quantity,sum(converted_value) amount,count(*) total,count(converted_value) known FROM aggregate_components WHERE run_id=p_run AND kind='position' GROUP BY instrument_id) c ON c.instrument_id=h.instrument_id WHERE h.run_id=p_run LOOP
  IF ROW(row.quantity,row.value,row.known_value,row.known_count,row.total_count,row.currency) IS DISTINCT FROM
   ROW(row.wanted_quantity,CASE WHEN row.total=row.known THEN coalesce(row.amount,0) ELSE NULL END,coalesce(row.amount,0),row.known,row.total,currency)
   OR NOT coalesce(aggregate_money_matches(row.body->'money',currency,row.total,row.known,row.amount),false)
   OR (row.body->>'instrument_id')::uuid IS DISTINCT FROM row.instrument_id OR (row.body->>'quantity')::numeric IS DISTINCT FROM row.quantity THEN RETURN false; END IF;
 END LOOP;
 IF (SELECT count(*) FROM aggregate_holdings WHERE run_id=p_run)<>(SELECT count(DISTINCT instrument_id) FROM aggregate_components WHERE run_id=p_run AND kind='position') THEN RETURN false; END IF;
 FOR row IN SELECT a.*,convert_from(a.payload,'UTF8')::jsonb AS body FROM aggregate_account_totals a WHERE run_id=p_run LOOP
  SELECT count(*),count(converted_value),sum(converted_value) INTO total,known,amount FROM aggregate_components WHERE run_id=p_run AND account_id=row.account_id;
  IF ROW(row.value,row.known_value,row.known_count,row.total_count,row.currency) IS DISTINCT FROM
   ROW(CASE WHEN total=known THEN coalesce(amount,0) ELSE NULL END,coalesce(amount,0),known,total,currency)
   OR NOT coalesce(aggregate_money_matches(row.body->'money',currency,total,known,amount),false)
   OR (row.body->>'account_id')::uuid IS DISTINCT FROM row.account_id THEN RETURN false; END IF;
 END LOOP;
 IF EXISTS(SELECT 1 FROM aggregate_transfer_matches t
  JOIN aggregate_transfer_evidence e ON e.owner_id=t.owner_id AND e.run_id=t.run_id AND e.source_record_id=t.outgoing_record_id
  JOIN (SELECT candidate.run_id, convert_from(candidate.payload,'UTF8')::jsonb->'transfer'->>'transfer_reference' reference,
    least(candidate.account_id,(convert_from(candidate.payload,'UTF8')::jsonb->'transfer'->>'counterparty_account_id')::uuid) first_account,
    greatest(candidate.account_id,(convert_from(candidate.payload,'UTF8')::jsonb->'transfer'->>'counterparty_account_id')::uuid) second_account,count(*) candidates
   FROM aggregate_transfer_evidence candidate JOIN aggregate_runs root ON root.id=candidate.run_id
   WHERE candidate.run_id=p_run AND candidate.selected AND convert_from(candidate.payload,'UTF8')::jsonb->'transfer'<>'null'::jsonb
    AND (convert_from(candidate.payload,'UTF8')::jsonb->>'occurred_at')::timestamptz>=root.activity_start_at
    AND (convert_from(candidate.payload,'UTF8')::jsonb->>'occurred_at')::timestamptz<root.activity_end_at
   GROUP BY candidate.run_id,reference,first_account,second_account) g ON g.run_id=t.run_id
    AND g.reference=convert_from(e.payload,'UTF8')::jsonb->'transfer'->>'transfer_reference'
    AND g.first_account=least(t.outgoing_account_id,t.incoming_account_id) AND g.second_account=greatest(t.outgoing_account_id,t.incoming_account_id)
  WHERE t.run_id=p_run AND g.candidates<>2) THEN RETURN false; END IF;
 IF EXISTS(SELECT fee FROM aggregate_transfer_matches t CROSS JOIN LATERAL jsonb_array_elements_text(convert_from(t.payload,'UTF8')::jsonb->'fee_record_ids') fee WHERE t.run_id=p_run GROUP BY fee HAVING count(*)>1) THEN RETURN false; END IF;
 RETURN true;
END $$;
CREATE FUNCTION aggregate_native_proof_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE original source_records; body jsonb; proof jsonb; witness jsonb; a jsonb; b jsonb; left_row aggregate_transfer_evidence; right_row aggregate_transfer_evidence; fee aggregate_transfer_evidence;
 expected numeric; denominator numeric; fee_id uuid; leg record; ambiguous bigint;
BEGIN
 body:=convert_from(NEW.payload,'UTF8')::jsonb;
 IF TG_TABLE_NAME='aggregate_transfer_evidence' THEN
  SELECT * INTO original FROM source_records WHERE id=NEW.source_record_id AND broker_account_id=NEW.account_id;
  witness:=body->'transfer'; proof:=original.sanitized_payload->'custodyTransfer';
  IF witness IS NOT NULL AND witness<>'null'::jsonb THEN
   IF original.provider<>'synthetic' OR original.schema_version<>'synthetic-custody-v1:historical_transactions'
    OR original.sanitized_payload->>'type'<>'TRANSFER' OR proof IS NULL
    OR body->>'kind' IS DISTINCT FROM 'transfer'
    OR (body->>'occurred_at')::timestamptz IS DISTINCT FROM (original.sanitized_payload->>'dateTime')::timestamptz
    OR NEW.amount IS DISTINCT FROM (original.sanitized_payload->>'amount')::numeric
    OR NEW.currency IS DISTINCT FROM original.sanitized_payload->>'currency'
    OR (witness->>'counterparty_account_id')::uuid IS DISTINCT FROM (proof->>'counterpartyAccountId')::uuid
    OR witness->>'transfer_reference' IS DISTINCT FROM proof->>'transferReference'
    OR (witness->>'principal')::numeric IS DISTINCT FROM (proof->>'principal')::numeric
    OR witness->>'currency' IS DISTINCT FROM proof->>'currency'
    OR (witness->>'fx_rate')::numeric IS DISTINCT FROM (proof->>'fxRate')::numeric
    OR witness->>'fx_base_currency' IS DISTINCT FROM proof->>'fxBaseCurrency'
    OR witness->>'fx_quote_currency' IS DISTINCT FROM proof->>'fxQuoteCurrency'
    OR witness->>'fee_record_key' IS DISTINCT FROM proof->>'feeRecordKey'
    OR (witness->>'fee_amount')::numeric IS DISTINCT FROM (proof->>'feeAmount')::numeric
    OR witness->>'fee_currency' IS DISTINCT FROM proof->>'feeCurrency' THEN
    RAISE EXCEPTION 'aggregate native transfer witness was substituted' USING ERRCODE='23514'; END IF;
   fee_id:=(witness->>'fee_record_id')::uuid;
   IF fee_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM source_records WHERE id=fee_id AND broker_account_id=NEW.account_id
    AND provider_record_id=proof->>'feeRecordKey') THEN RAISE EXCEPTION 'aggregate fee source differs' USING ERRCODE='23514'; END IF;
  ELSIF original.provider='synthetic' AND original.schema_version='synthetic-custody-v1:historical_transactions' AND proof IS NOT NULL AND proof<>'null'::jsonb THEN
   RAISE EXCEPTION 'aggregate native proof was silently omitted' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO left_row FROM aggregate_transfer_evidence WHERE owner_id=NEW.owner_id AND run_id=NEW.run_id AND source_record_id=NEW.outgoing_record_id AND selected;
 SELECT * INTO right_row FROM aggregate_transfer_evidence WHERE owner_id=NEW.owner_id AND run_id=NEW.run_id AND source_record_id=NEW.incoming_record_id AND selected;
 a:=convert_from(left_row.payload,'UTF8')::jsonb->'transfer'; b:=convert_from(right_row.payload,'UTF8')::jsonb->'transfer';
 IF left_row.id IS NULL OR right_row.id IS NULL OR a IS NULL OR a='null'::jsonb OR b IS NULL OR b='null'::jsonb
  OR (a->>'counterparty_account_id')::uuid IS DISTINCT FROM right_row.account_id OR (b->>'counterparty_account_id')::uuid IS DISTINCT FROM left_row.account_id
  OR a->>'transfer_reference' IS DISTINCT FROM b->>'transfer_reference' OR body->>'transfer_reference' IS DISTINCT FROM a->>'transfer_reference'
  OR ROW(left_row.account_id,right_row.account_id,left_row.amount,right_row.amount,left_row.currency,right_row.currency) IS DISTINCT FROM
   ROW(NEW.outgoing_account_id,NEW.incoming_account_id,NEW.outgoing_principal,NEW.incoming_principal,NEW.outgoing_currency,NEW.incoming_currency)
  OR (body->>'outgoing_record_id')::uuid IS DISTINCT FROM NEW.outgoing_record_id OR (body->>'incoming_record_id')::uuid IS DISTINCT FROM NEW.incoming_record_id
  OR (body->>'outgoing_account_id')::uuid IS DISTINCT FROM NEW.outgoing_account_id OR (body->>'incoming_account_id')::uuid IS DISTINCT FROM NEW.incoming_account_id
  OR (body->>'outgoing_principal')::numeric IS DISTINCT FROM NEW.outgoing_principal OR (body->>'incoming_principal')::numeric IS DISTINCT FROM NEW.incoming_principal
  OR body->>'outgoing_currency' IS DISTINCT FROM NEW.outgoing_currency OR body->>'incoming_currency' IS DISTINCT FROM NEW.incoming_currency
  OR (body->>'fx_rate')::numeric IS DISTINCT FROM NEW.fx_rate THEN
  RAISE EXCEPTION 'aggregate mutual transfer proof differs' USING ERRCODE='23514'; END IF;
 IF NEW.outgoing_currency=NEW.incoming_currency THEN
  IF NEW.outgoing_principal+NEW.incoming_principal<>0 OR NEW.fx_rate IS NOT NULL THEN RAISE EXCEPTION 'aggregate same currency principal differs' USING ERRCODE='23514'; END IF;
 ELSE
  IF a->>'fx_rate' IS DISTINCT FROM b->>'fx_rate' OR a->>'fx_base_currency' IS DISTINCT FROM b->>'fx_base_currency'
   OR a->>'fx_quote_currency' IS DISTINCT FROM b->>'fx_quote_currency' OR (a->>'fx_rate')::numeric IS DISTINCT FROM NEW.fx_rate
   OR body->>'fx_base_currency' IS DISTINCT FROM a->>'fx_base_currency' OR body->>'fx_quote_currency' IS DISTINCT FROM a->>'fx_quote_currency'
   OR NEW.fx_rate IS NULL OR NEW.fx_rate<=0 OR (a->>'fx_base_currency') NOT IN (NEW.outgoing_currency,NEW.incoming_currency)
   OR (a->>'fx_quote_currency') NOT IN (NEW.outgoing_currency,NEW.incoming_currency) OR a->>'fx_base_currency'=a->>'fx_quote_currency' THEN
   RAISE EXCEPTION 'aggregate transfer FX witness differs' USING ERRCODE='23514'; END IF;
  expected:=CASE WHEN a->>'fx_base_currency'=NEW.outgoing_currency THEN aggregate_q18_ratio(-NEW.outgoing_principal*NEW.fx_rate,1) ELSE aggregate_q18_ratio(NEW.incoming_principal*NEW.fx_rate,1) END;
  IF expected<>(CASE WHEN a->>'fx_base_currency'=NEW.outgoing_currency THEN NEW.incoming_principal ELSE -NEW.outgoing_principal END) THEN RAISE EXCEPTION 'aggregate transfer FX principal differs' USING ERRCODE='23514'; END IF;
  FOR leg IN SELECT * FROM (VALUES(left_row.account_id,a,0),(right_row.account_id,b,1)) v(account_id,proof,ordinal) LOOP
   fee_id:=(leg.proof->>'fee_record_id')::uuid;
   SELECT * INTO fee FROM aggregate_transfer_evidence WHERE owner_id=NEW.owner_id AND run_id=NEW.run_id AND source_record_id=fee_id AND selected;
   IF fee.id IS NULL OR fee.account_id<>leg.account_id OR fee.amount IS DISTINCT FROM (leg.proof->>'fee_amount')::numeric
    OR fee.currency IS DISTINCT FROM leg.proof->>'fee_currency' OR convert_from(fee.payload,'UTF8')::jsonb->>'kind'<>'fee'
    OR (body->'fee_record_ids'->>leg.ordinal)::uuid IS DISTINCT FROM fee.source_record_id THEN RAISE EXCEPTION 'aggregate original fee proof differs' USING ERRCODE='23514'; END IF;
  END LOOP;
 END IF;
 RETURN NEW;
END $$;
"""

_RETENTION = r"""
CREATE FUNCTION aggregate_retention_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE root aggregate_runs; owner uuid; permitted boolean; actual_now timestamptz:=clock_timestamp();
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'aggregate retention marker is permanent' USING ERRCODE='23514'; END IF;
 IF NEW.created_at>actual_now OR (NEW.completed_at IS NOT NULL AND NEW.completed_at>actual_now) THEN
  RAISE EXCEPTION 'aggregate retention metadata is in the future' USING ERRCODE='23514'; END IF;
 owner:=NEW.owner_id; PERFORM aggregate_owner_lock(owner);
 IF TG_TABLE_NAME='aggregate_owner_erasure' THEN
  IF TG_OP='INSERT' THEN
   IF EXISTS(SELECT 1 FROM principals WHERE owner_id=owner AND status='active')
    OR EXISTS(SELECT 1 FROM broker_connections WHERE owner_id=owner AND status='active') THEN
    RAISE EXCEPTION 'aggregate owner remains active' USING ERRCODE='23514'; END IF;
   IF NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'aggregate owner marker must begin pending' USING ERRCODE='23514'; END IF;
  ELSE
   IF (to_jsonb(NEW)-'completed_at') IS DISTINCT FROM (to_jsonb(OLD)-'completed_at') OR OLD.completed_at IS NOT NULL
    OR NEW.completed_at IS NULL OR NEW.completed_at<NEW.created_at
    OR EXISTS(SELECT 1 FROM aggregate_runs WHERE owner_id=owner AND retained_bytes+reserved_bytes>0)
    OR EXISTS(SELECT 1 FROM aggregate_selection_payloads WHERE owner_id=owner) THEN
    RAISE EXCEPTION 'aggregate owner copies remain' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO root FROM aggregate_runs WHERE owner_id=owner AND id=NEW.run_id FOR UPDATE;
 IF root.id IS NULL OR NOT root.sealed THEN RAISE EXCEPTION 'aggregate purge root is absent' USING ERRCODE='23514'; END IF;
 IF NEW.created_at<root.created_at THEN RAISE EXCEPTION 'aggregate marker predates its run' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-'completed_at') IS DISTINCT FROM (to_jsonb(OLD)-'completed_at') OR OLD.completed_at IS NOT NULL
   OR NEW.completed_at IS NULL OR root.retained_bytes<>0 OR root.reserved_bytes<>0 OR root.financial_rows<>0
   OR EXISTS(SELECT 1 FROM aggregate_sources WHERE owner_id=owner AND run_id=root.id) THEN
   RAISE EXCEPTION 'aggregate physical copies remain' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'aggregate marker must begin pending' USING ERRCODE='23514'; END IF;
 permitted:=false;
 IF NEW.reason='expired' THEN permitted:=root.expires_at<=NEW.created_at AND NEW.source_fx_snapshot_id IS NULL AND NEW.source_evidence_id IS NULL;
 ELSIF NEW.reason='owner_erasure' THEN permitted:=EXISTS(SELECT 1 FROM aggregate_owner_erasure WHERE owner_id=owner) AND NEW.source_fx_snapshot_id IS NULL AND NEW.source_evidence_id IS NULL;
 ELSIF NEW.reason='source' THEN
  permitted:=NEW.source_fx_snapshot_id IS NOT NULL AND NEW.source_evidence_id IS NULL
   AND EXISTS(SELECT 1 FROM aggregate_sources WHERE owner_id=owner AND run_id=root.id AND source_kind='fx' AND source_id=NEW.source_fx_snapshot_id)
   AND aggregate_fx_until(owner,NEW.source_fx_snapshot_id,actual_now) IS NULL;
 END IF;
 IF NOT permitted THEN RAISE EXCEPTION 'aggregate purge has no original restricted witness' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION aggregate_parent_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner uuid; kind text; source uuid;
BEGIN
 IF TG_OP='UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
 source:=OLD.id;
 IF TG_TABLE_NAME IN ('source_records','portfolio_snapshots','calculation_runs') THEN
  SELECT c.owner_id INTO owner FROM broker_accounts a JOIN broker_connections c ON c.id=a.connection_id WHERE a.id=OLD.broker_account_id;
  kind:=CASE TG_TABLE_NAME WHEN 'source_records' THEN 'broker_record' WHEN 'portfolio_snapshots' THEN 'snapshot' ELSE 'calculation' END;
 ELSE
  owner:=OLD.owner_id;
  kind:=CASE TG_TABLE_NAME WHEN 'fx_snapshots' THEN 'fx' WHEN 'fx_observations' THEN 'fx_observation'
   WHEN 'historical_evidence_sets' THEN 'coverage_parent' WHEN 'historical_activity_coverage' THEN 'coverage' ELSE 'revision' END;
 END IF;
 IF aggregate_parent_has_copies(owner,kind,source) THEN
  RAISE EXCEPTION 'aggregate original dependency still has physical copies' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION aggregate_definition_capacity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual bigint; recorded integer;
BEGIN
 PERFORM aggregate_owner_lock(NEW.owner_id);
 INSERT INTO premium_owner_capacity(owner_id,reserved_bytes,retained_bytes,active_jobs,definition_versions,updated_at)
  VALUES(NEW.owner_id,0,0,0,0,statement_timestamp()) ON CONFLICT(owner_id) DO NOTHING;
 SELECT definition_versions INTO recorded FROM premium_owner_capacity WHERE owner_id=NEW.owner_id FOR UPDATE;
 SELECT (SELECT count(*) FROM risk_definition_versions WHERE owner_id=NEW.owner_id)
  +(SELECT count(*) FROM scenario_definition_versions WHERE owner_id=NEW.owner_id)
  +(SELECT count(*) FROM assumption_versions WHERE owner_id=NEW.owner_id)
  +(SELECT count(*) FROM goal_versions WHERE owner_id=NEW.owner_id)
  +(SELECT count(*) FROM research_note_revisions WHERE owner_id=NEW.owner_id)
  +(SELECT count(*) FROM aggregate_selections WHERE owner_id=NEW.owner_id) INTO actual;
 IF greatest(actual,recorded)>=512 THEN RAISE EXCEPTION 'aggregate shared definition capacity exceeded' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='aggregate_selections' THEN
  UPDATE premium_owner_capacity SET definition_versions=definition_versions+1,updated_at=statement_timestamp() WHERE owner_id=NEW.owner_id;
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION aggregate_selection_charge() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner uuid; delta bigint;
BEGIN
 IF TG_OP='DELETE' THEN owner:=OLD.owner_id; delta:=-octet_length(OLD.payload);
 ELSE owner:=NEW.owner_id; delta:=octet_length(NEW.payload); END IF;
 UPDATE premium_owner_capacity SET retained_bytes=retained_bytes+delta,updated_at=statement_timestamp() WHERE owner_id=owner;
 IF NOT FOUND THEN RAISE EXCEPTION 'aggregate shared capacity absent' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
"""

# Every FK used while draining an aggregate has a supporting index. These fixed
# metadata probes are included in the runtime's conservative per-mutation cost.
_FK_INDEXES = (
 ("aggregate_flow_legs", "owner_id,run_id,source_record_id"),
 ("aggregate_transfer_matches", "owner_id,run_id,outgoing_record_id"),
 ("aggregate_transfer_matches", "owner_id,run_id,incoming_record_id"),
 ("aggregate_sources", "snapshot_id"), ("aggregate_sources", "calculation_run_id"),
 ("aggregate_sources", "source_record_id"), ("aggregate_sources", "fx_snapshot_id"),
 ("aggregate_sources", "fx_observation_id"), ("aggregate_sources", "coverage_id"),
 ("aggregate_sources", "evidence_id"), ("aggregate_sources", "revision_id"),
)
_PARENT_TABLES = ("source_records", "portfolio_snapshots", "calculation_runs", "fx_snapshots", "fx_observations", "historical_evidence_sets", "historical_activity_coverage", "activity_revision_evidence")
_VERSION_TABLES = ("risk_definition_versions", "scenario_definition_versions", "assumption_versions", "goal_versions", "research_note_revisions", "aggregate_selections")


_PREDECESSOR_COMMAND_CHECKS = {'ck_application_command_identities_command_allowed': "CHECK (command IN ('reports.generate.v1','reports.generate.v2','exports.generate.v1','risk.definition.create.v1','risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1','scenario.definition.create.v1','scenario.version.create.v1','scenario.run.create.v1','scenario.run.cancel.v1','projection.assumption.create.v1','projection.assumption.version.create.v1','projection.goal.create.v1','projection.goal.version.create.v1','projection.run.create.v1','projection.run.cancel.v1','research.note.create.v1','research.note.version.create.v1','research.event.review.v1'))", 'ck_application_command_identities_parent_kind': "CHECK ((command IN ('reports.generate.v1','reports.generate.v2') AND report_job_id IS NOT NULL AND export_job_id IS NULL AND premium_resource_id IS NULL AND premium_actor_id IS NULL AND premium_correlation_id IS NULL) OR (command='exports.generate.v1' AND export_job_id IS NOT NULL AND report_job_id IS NULL AND premium_resource_id IS NULL AND premium_actor_id IS NULL AND premium_correlation_id IS NULL) OR (command IN ('risk.definition.create.v1','risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1','scenario.definition.create.v1','scenario.version.create.v1','scenario.run.create.v1','scenario.run.cancel.v1','projection.assumption.create.v1','projection.assumption.version.create.v1','projection.goal.create.v1','projection.goal.version.create.v1','projection.run.create.v1','projection.run.cancel.v1','research.note.create.v1','research.note.version.create.v1','research.event.review.v1') AND report_job_id IS NULL AND export_job_id IS NULL AND premium_resource_id IS NOT NULL AND premium_actor_id IS NOT NULL AND premium_correlation_id IS NOT NULL))"}


def _command_constraints(*, include: bool) -> None:
    for name, original in _PREDECESSOR_COMMAND_CHECKS.items():
        definition = original.replace("'research.event.review.v1'", "'research.event.review.v1','aggregate.selection.create.v1','aggregate.run.create.v1'") if include else original
        op.execute("ALTER TABLE application_command_identities DROP CONSTRAINT " + name)
        op.execute("ALTER TABLE application_command_identities ADD CONSTRAINT " + name + " " + definition)


def upgrade() -> None:
    _create_tables()
    op.execute("ALTER TABLE source_retention_dispatch DROP CONSTRAINT ck_source_retention_dispatch_family_bound")
    op.execute("ALTER TABLE source_retention_dispatch ADD CONSTRAINT ck_source_retention_dispatch_family_bound CHECK((family='dispatch' AND next_family BETWEEN 0 AND 7) OR (family='source' AND next_family BETWEEN 0 AND 4) OR (family='enrichment' AND next_family BETWEEN 0 AND 3))")
    op.execute(_COMMON)
    op.execute(_ROOT_GUARD)
    op.execute(_CHILD_GUARD)
    op.execute(_COSTS)
    op.execute(_COMPLETE)
    op.execute(_ECONOMICS)
    op.execute(_RETENTION)
    _command_constraints(include=True)
    for table in ("aggregate_selections", "aggregate_runs"):
        op.execute(f"CREATE TRIGGER aggregate_root_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION aggregate_root_guard()")
        op.execute(f"CREATE CONSTRAINT TRIGGER aggregate_initial_complete AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION aggregate_complete_guard()")
        op.execute(f"CREATE CONSTRAINT TRIGGER aggregate_seal_complete AFTER UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NOT OLD.sealed AND NEW.sealed) EXECUTE FUNCTION aggregate_complete_guard()")
    op.execute("CREATE CONSTRAINT TRIGGER aggregate_revision_complete AFTER UPDATE ON aggregate_selections DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (OLD.sealed AND NEW.revision IS DISTINCT FROM OLD.revision) EXECUTE FUNCTION aggregate_complete_guard()")
    for table in ("aggregate_account_members", "aggregate_selection_payloads"):
        op.execute(f"CREATE TRIGGER aggregate_selection_child_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION aggregate_selection_child_guard()")
    op.execute("CREATE TRIGGER aggregate_selection_charge AFTER INSERT OR DELETE ON aggregate_selection_payloads FOR EACH ROW EXECUTE FUNCTION aggregate_selection_charge()")
    for table in (*_PAYLOAD_TABLES, *(x[0] for x in _PROJECTIONS), "aggregate_sources"):
        op.execute(f"CREATE TRIGGER aggregate_child_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION aggregate_child_guard()")
        op.execute(f"CREATE TRIGGER aggregate_payload_charge AFTER INSERT OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION aggregate_payload_charge()")
    for table in ("aggregate_transfer_evidence", "aggregate_transfer_matches"):
        op.execute(f"CREATE TRIGGER aggregate_native_proof_guard BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION aggregate_native_proof_guard()")
    for table in ("aggregate_retention_work", "aggregate_owner_erasure"):
        op.execute(f"CREATE TRIGGER aggregate_retention_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION aggregate_retention_guard()")
    op.execute("CREATE CONSTRAINT TRIGGER aggregate_command_complete AFTER INSERT ON application_command_identities DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION aggregate_complete_guard()")
    for table in _PARENT_TABLES:
        op.execute(f"CREATE TRIGGER aggregate_parent_guard BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION aggregate_parent_guard()")
    for table in _VERSION_TABLES:
        op.execute(f"CREATE TRIGGER aggregate_definition_capacity_guard BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION aggregate_definition_capacity_guard()")
    for index, (table, columns) in enumerate(_FK_INDEXES):
        op.execute(f"CREATE INDEX ix_aggregate_reverse_{index} ON {table}({columns})")


def downgrade() -> None:
    # Refuse rollback while meaningful aggregate financial data exists. Empty
    # migration round trips remove only this revision's tables/functions/hooks.
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM aggregate_selections) OR EXISTS(SELECT 1 FROM aggregate_owner_erasure) THEN RAISE EXCEPTION 'aggregate identities and permanent erasure markers prevent downgrade'; END IF; END $$")
    op.execute("DROP INDEX ix_fx_observation_reference_page")
    for table in _PARENT_TABLES:
        op.execute(f"DROP TRIGGER aggregate_parent_guard ON {table}")
    for table in _VERSION_TABLES:
        op.execute(f"DROP TRIGGER aggregate_definition_capacity_guard ON {table}")
    op.execute("DROP TRIGGER aggregate_command_complete ON application_command_identities")
    _command_constraints(include=False)
    op.execute("UPDATE source_retention_dispatch SET next_family=0 WHERE family='dispatch'")
    op.execute("ALTER TABLE source_retention_dispatch DROP CONSTRAINT ck_source_retention_dispatch_family_bound")
    op.execute("ALTER TABLE source_retention_dispatch ADD CONSTRAINT ck_source_retention_dispatch_family_bound CHECK((family='dispatch' AND next_family BETWEEN 0 AND 6) OR (family='source' AND next_family BETWEEN 0 AND 4) OR (family='enrichment' AND next_family BETWEEN 0 AND 3))")
    for table in ("aggregate_retention_cursor", "aggregate_owner_erasure", "aggregate_retention_work", "aggregate_sources", *(x[0] for x in reversed(_PROJECTIONS)), *reversed(_PAYLOAD_TABLES), "aggregate_runs", "aggregate_selection_payloads", "aggregate_account_members", "aggregate_selections"):
        op.execute(f"DROP TABLE {table}")
    for signature in ("aggregate_native_proof_guard()", "aggregate_financial_complete(uuid)", "aggregate_money_matches(jsonb,text,bigint,bigint,numeric)", "aggregate_selection_charge()", "aggregate_definition_capacity_guard()", "aggregate_parent_guard()", "aggregate_retention_guard()", "aggregate_complete_guard()", "aggregate_run_complete(uuid)", "aggregate_sources_complete(uuid)", "aggregate_projection_inventory(uuid,text,jsonb)", "aggregate_payload_charge()", "aggregate_storage_bytes(uuid)", "aggregate_row_cost(text,uuid)", "aggregate_child_guard()", "aggregate_selection_child_guard()", "aggregate_root_guard()", "aggregate_parent_has_copies(uuid,text,uuid)", "aggregate_q18_ratio(numeric,numeric)", "aggregate_fx_until(uuid,uuid,timestamptz)", "aggregate_actor_valid(uuid,uuid,boolean,boolean)", "aggregate_owner_lock(uuid)", "aggregate_digest(bytea)"):
        op.execute("DROP FUNCTION " + signature)
