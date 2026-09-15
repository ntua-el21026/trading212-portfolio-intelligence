"""Additive bounded legacy report source expiry with preserved canonical bytes.

Revision ID:20260915_0025; down revision20260915_0024.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0025"
down_revision = "20260915_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "report_input_dependencies", sa.Column("copy_pending", sa.Boolean(), nullable=True)
    )
    op.add_column(
        "report_retention_work", sa.Column("legacy_source_kind", sa.String(20), nullable=True)
    )
    op.add_column("report_retention_work", sa.Column("legacy_source_id", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        "legacy_witness_bound",
        "report_retention_work",
        (
            "(legacy_source_kind IS NULL AND legacy_source_id IS NULL) OR (reason='source' "
            "AND legacy_source_kind IN ('physical','root','report_license','premium_license',"
            "'parents','history','version','observation','evidence') AND legacy_source_id IS "
            "NOT NULL AND projection_source_kind IS NULL AND projection_source_id IS NULL)"
        ),
    )
    op.execute(_DDL)
    for name, table, columns, predicate in _INDICES:
        op.create_index(
            name, table, columns, **({"postgresql_where": sa.text(predicate)} if predicate else {})
        )
    op.execute(_PROBES)
    op.execute(_OWNED)
    op.execute(
        "UPDATE report_input_dependencies SET "
        "copy_pending=report_capture_pending(owner_id,input_id)"
    )
    op.alter_column(
        "report_input_dependencies", "copy_pending", nullable=False, server_default=sa.text("true")
    )
    op.execute(_SOURCE)
    op.execute(_RETENTION)
    for table in _EPOCH_TABLES:
        op.execute(
            f"CREATE TRIGGER z_legacy_report_retention_epoch AFTER INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION projection_retention_policy_epoch()"
        )


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
     IF EXISTS(SELECT 1 FROM legacy_report_retention_scans WHERE phase<>9)
      OR EXISTS(SELECT 1 FROM report_retention_work WHERE legacy_source_kind IS NOT NULL AND completed_at IS NULL)
      OR EXISTS(SELECT 1 FROM legacy_report_retention_sweeps WHERE after_id IS NOT NULL OR pending_after_id IS NOT NULL OR deferred)
     THEN RAISE EXCEPTION 'Legacy report cleanup must finish before downgrade' USING ERRCODE='23514'; END IF;
    END $$""")
    for table in _EPOCH_TABLES:
        op.execute(f"DROP TRIGGER z_legacy_report_retention_epoch ON {table}")
    op.execute(_PREVIOUS_RETENTION)
    op.execute(_PREVIOUS_SOURCE)
    op.execute(_PREVIOUS_OWNED)
    op.execute("DROP FUNCTION legacy_report_witness_restricted(uuid,uuid,text,uuid,timestamptz)")
    op.execute("DROP FUNCTION legacy_report_retention_probe(uuid,uuid,text,uuid,timestamptz)")
    op.execute("DROP FUNCTION legacy_report_physical_probe(uuid,uuid,uuid,timestamptz)")
    op.execute(
        "DROP FUNCTION legacy_report_license_probe(uuid,uuid,uuid,timestamptz,timestamptz"
        ",timestamptz,text)"
    )
    for name, table, _columns, _predicate in reversed(_INDICES):
        op.drop_index(name, table_name=table)
    op.drop_table("legacy_report_retention_scans")
    op.drop_table("legacy_report_retention_sweeps")
    op.drop_constraint(
        op.f("ck_report_retention_work_legacy_witness_bound"),
        "report_retention_work",
        type_="check",
    )
    op.drop_column("report_retention_work", "legacy_source_id")
    op.drop_column("report_retention_work", "legacy_source_kind")
    op.drop_column("report_input_dependencies", "copy_pending")


_INDICES = [
    ("ix_report_pending_work", "report_retention_work", ["id"], "completed_at IS NULL"),
    (
        "ix_report_source_pending",
        "report_input_dependencies",
        ["owner_id", "kind", "source_id", "copy_pending", "input_id", "id"],
        None,
    ),
    (
        "ix_report_source_pending_input",
        "report_input_dependencies",
        ["owner_id", "input_id", "copy_pending", "id"],
        None,
    ),
    (
        "ix_report_legacy_pending",
        "report_input_premium_dependencies",
        ["id"],
        "copy_pending AND kind IN ('risk','scenario')",
    ),
    (
        "ix_legacy_report_licenses_input",
        "report_input_licenses",
        ["owner_id", "input_id", "id"],
        None,
    ),
    (
        "ix_legacy_report_premium_licenses",
        "premium_run_licenses",
        ["owner_id", "run_id", "id"],
        None,
    ),
    (
        "ix_legacy_report_history_membership",
        "historical_dependencies",
        ["owner_id", "input_id", "registered_evidence_id"],
        None,
    ),
    (
        "ix_legacy_report_scenario_versions",
        "scenario_run_sensitivity_versions",
        ["owner_id", "run_id", "id"],
        None,
    ),
    (
        "ix_legacy_report_scenario_observations",
        "scenario_run_sensitivity_observations",
        ["owner_id", "run_id", "id"],
        None,
    ),
    (
        "ix_legacy_report_scenario_evidence",
        "scenario_run_sensitivity_evidence",
        ["owner_id", "run_id", "id"],
        None,
    ),
]
_EPOCH_TABLES = (
    "enrichment_retention_work",
    "enrichment_expiry_events",
    "scenario_sensitivity_retention",
)

_DDL = r"""
CREATE TABLE legacy_report_retention_sweeps (
 id smallint NOT NULL CONSTRAINT pk_legacy_report_retention_sweeps PRIMARY KEY,after_id uuid,pending_after_id uuid,deferred boolean NOT NULL,
 CONSTRAINT ck_legacy_report_retention_sweeps_singleton CHECK(id=1)
);
CREATE TABLE legacy_report_retention_scans (
 owner_id uuid NOT NULL CONSTRAINT pk_legacy_report_retention_scans PRIMARY KEY CONSTRAINT fk_legacy_report_retention_scans_owner_id_owners REFERENCES owners(id) ON DELETE RESTRICT,
 account_id uuid NOT NULL,input_id uuid NOT NULL,run_id uuid NOT NULL,historical_input_id uuid,
 phase smallint NOT NULL,cursor uuid,evidence_id uuid,evidence_cursor uuid,
 policy_epoch bigint NOT NULL,evaluated_at timestamptz NOT NULL,earliest_deadline timestamptz,next_policy_at timestamptz,
 CONSTRAINT fk_legacy_report_scan_input FOREIGN KEY(owner_id,account_id,input_id) REFERENCES report_input_snapshots(owner_id,account_id,id) ON DELETE RESTRICT,
 CONSTRAINT ck_legacy_report_retention_scans_phase_bound CHECK(phase BETWEEN 1 AND 9 AND policy_epoch>=0),
 CONSTRAINT ck_legacy_report_retention_scans_evidence_phase CHECK((phase=5 OR (evidence_id IS NULL AND evidence_cursor IS NULL)) AND (evidence_cursor IS NULL OR evidence_id IS NOT NULL))
);
"""

_PROBES = r"""
CREATE FUNCTION legacy_report_license_probe(p_owner uuid,p_provider uuid,p_license uuid,p_origin timestamptz,p_until timestamptz,p_at timestamptz,p_mode text)
RETURNS TABLE(restricted boolean,next_deadline timestamptz) LANGUAGE plpgsql STABLE AS $$
DECLARE pinned provider_license_versions; current_license provider_license_versions; days integer;
BEGIN
 IF p_mode NOT IN ('permissions','v2','v3') THEN RAISE EXCEPTION 'Unknown legacy report licence mode' USING ERRCODE='23514'; END IF;
 SELECT * INTO pinned FROM provider_license_versions WHERE owner_id=p_owner AND provider_id=p_provider AND id=p_license;
 SELECT * INTO current_license FROM provider_license_versions WHERE owner_id=p_owner AND provider_id=p_provider AND effective_at<=p_at
  ORDER BY effective_at DESC,version_number DESC,id DESC LIMIT 1;
 restricted:=pinned.id IS NULL OR current_license.id IS NULL OR pinned.effective_at>p_at
  OR pinned.store_permission IS DISTINCT FROM 'allowed' OR pinned.display_permission IS DISTINCT FROM 'allowed' OR pinned.report_permission IS DISTINCT FROM 'allowed'
  OR current_license.store_permission IS DISTINCT FROM 'allowed' OR current_license.display_permission IS DISTINCT FROM 'allowed' OR current_license.report_permission IS DISTINCT FROM 'allowed';
 next_deadline:=NULL;
 IF p_mode<>'permissions' THEN
  restricted:=restricted OR pinned.retention_days IS NULL OR current_license.retention_days IS NULL;
  days:=least(pinned.retention_days,current_license.retention_days);
  IF p_mode='v3' THEN days:=least(30,days); END IF;
  next_deadline:=p_origin+days*interval '1 day';
  restricted:=restricted OR next_deadline<=p_at;
  IF p_mode='v3' THEN restricted:=restricted OR p_origin>p_at OR p_until<=p_at OR p_until>next_deadline; END IF;
 END IF;
 RETURN NEXT;
END $$;

CREATE FUNCTION legacy_report_physical_probe(p_owner uuid,p_input uuid,p_dependency uuid,p_at timestamptz)
RETURNS TABLE(restricted boolean,next_deadline timestamptz) LANGUAGE plpgsql STABLE AS $$
DECLARE dep report_input_dependencies; version integer; until_at timestamptz; actual record; permit record; marked boolean;
BEGIN
 SELECT * INTO dep FROM report_input_dependencies WHERE owner_id=p_owner AND input_id=p_input AND id=p_dependency;
 SELECT contract_version,expires_at INTO version,until_at FROM report_input_snapshots WHERE owner_id=p_owner AND id=p_input;
 restricted:=false;next_deadline:=NULL;
 IF dep.id IS NULL OR version IS NULL THEN RETURN NEXT;RETURN; END IF;
 SELECT * INTO actual FROM (
  SELECT provider_id,license_version_id,content_digest,created_at,expires_at FROM price_snapshots WHERE dep.kind='price' AND owner_id=p_owner AND id=dep.source_id
  UNION ALL SELECT provider_id,license_version_id,content_digest,created_at,expires_at FROM fx_snapshots WHERE dep.kind='fx' AND owner_id=p_owner AND id=dep.source_id
  UNION ALL SELECT provider_id,license_version_id,content_digest,created_at,expires_at FROM benchmark_snapshots WHERE dep.kind='benchmark' AND owner_id=p_owner AND id=dep.source_id
  UNION ALL SELECT provider_id,license_version_id,content_digest,created_at,expires_at FROM corporate_action_snapshots WHERE dep.kind='corporate_action' AND owner_id=p_owner AND id=dep.source_id
  UNION ALL SELECT provider_id,license_version_id,content_digest,created_at,expires_at FROM constituent_snapshots WHERE dep.kind='constituent' AND owner_id=p_owner AND id=dep.source_id
  UNION ALL SELECT provider_id,license_version_id,content_digest,created_at,expires_at FROM classification_snapshots WHERE dep.kind='classification' AND owner_id=p_owner AND id=dep.source_id
  UNION ALL SELECT provider_id,license_version_id,content_digest,created_at,expires_at FROM entity_evidence_versions WHERE dep.kind='entity_evidence' AND owner_id=p_owner AND id=dep.source_id
  UNION ALL SELECT provider_id,license_version_id,content_digest,created_at,expires_at FROM fund_definitions WHERE dep.kind='fund_definition' AND owner_id=p_owner AND id=dep.source_id
  UNION ALL SELECT provider_id,license_version_id,content_digest,created_at,expires_at FROM fund_source_mappings WHERE dep.kind='fund_mapping' AND owner_id=p_owner AND id=dep.source_id
 ) headers;
 next_deadline:=actual.expires_at;
 restricted:=actual.provider_id IS NULL OR actual.provider_id IS DISTINCT FROM dep.provider_id
  OR actual.license_version_id IS DISTINCT FROM dep.license_version_id OR actual.content_digest IS DISTINCT FROM dep.content_digest
  OR actual.expires_at IS DISTINCT FROM dep.expires_at OR actual.expires_at<=p_at;
 -- Generated closed typed-FK arms replace this marker token during authoring.
 SELECT EXISTS(
SELECT id FROM source_retention_work WHERE dep.kind='price' AND owner_id=p_owner AND price_snapshot_id=dep.source_id
UNION ALL SELECT id FROM source_expiry_events WHERE dep.kind='price' AND owner_id=p_owner AND price_snapshot_id=dep.source_id
UNION ALL SELECT id FROM source_retention_work WHERE dep.kind='fx' AND owner_id=p_owner AND fx_snapshot_id=dep.source_id
UNION ALL SELECT id FROM source_expiry_events WHERE dep.kind='fx' AND owner_id=p_owner AND fx_snapshot_id=dep.source_id
UNION ALL SELECT id FROM source_retention_work WHERE dep.kind='benchmark' AND owner_id=p_owner AND benchmark_snapshot_id=dep.source_id
UNION ALL SELECT id FROM source_expiry_events WHERE dep.kind='benchmark' AND owner_id=p_owner AND benchmark_snapshot_id=dep.source_id
UNION ALL SELECT id FROM source_retention_work WHERE dep.kind='corporate_action' AND owner_id=p_owner AND corporate_action_snapshot_id=dep.source_id
UNION ALL SELECT id FROM source_expiry_events WHERE dep.kind='corporate_action' AND owner_id=p_owner AND corporate_action_snapshot_id=dep.source_id
UNION ALL SELECT id FROM source_retention_work WHERE dep.kind='constituent' AND owner_id=p_owner AND constituent_snapshot_id=dep.source_id
UNION ALL SELECT id FROM source_expiry_events WHERE dep.kind='constituent' AND owner_id=p_owner AND constituent_snapshot_id=dep.source_id
UNION ALL SELECT id FROM enrichment_retention_work WHERE dep.kind='classification' AND owner_id=p_owner AND classification_snapshot_id=dep.source_id
UNION ALL SELECT id FROM enrichment_expiry_events WHERE dep.kind='classification' AND owner_id=p_owner AND classification_snapshot_id=dep.source_id
UNION ALL SELECT id FROM enrichment_retention_work WHERE dep.kind='entity_evidence' AND owner_id=p_owner AND entity_evidence_version_id=dep.source_id
UNION ALL SELECT id FROM enrichment_expiry_events WHERE dep.kind='entity_evidence' AND owner_id=p_owner AND entity_evidence_version_id=dep.source_id
UNION ALL SELECT id FROM enrichment_retention_work WHERE dep.kind='fund_definition' AND owner_id=p_owner AND fund_definition_id=dep.source_id
UNION ALL SELECT id FROM enrichment_expiry_events WHERE dep.kind='fund_definition' AND owner_id=p_owner AND fund_definition_id=dep.source_id
UNION ALL SELECT id FROM enrichment_retention_work WHERE dep.kind='fund_mapping' AND owner_id=p_owner AND fund_mapping_id=dep.source_id
UNION ALL SELECT id FROM enrichment_expiry_events WHERE dep.kind='fund_mapping' AND owner_id=p_owner AND fund_mapping_id=dep.source_id
) INTO marked;
 restricted:=restricted OR marked;
 IF NOT restricted AND version<>1 THEN
  SELECT * INTO permit FROM legacy_report_license_probe(p_owner,actual.provider_id,actual.license_version_id,actual.created_at,until_at,p_at,CASE WHEN version=2 THEN 'permissions' ELSE 'v3' END);
  restricted:=permit.restricted;next_deadline:=least(next_deadline,permit.next_deadline);
 END IF;
 RETURN NEXT;
END $$;

CREATE FUNCTION legacy_report_retention_probe(p_owner uuid,p_input uuid,p_kind text,p_subject uuid,p_at timestamptz)
RETURNS TABLE(restricted boolean,next_deadline timestamptz) LANGUAGE plpgsql STABLE AS $$
DECLARE inp record; dep report_input_premium_dependencies; root premium_runs; item record;
 history_id uuid; xray_input uuid; xray_run uuid; provider uuid; license_id uuid; origin timestamptz; until_at timestamptz; h historical_dependencies; permit record;
BEGIN
 restricted:=false;next_deadline:=NULL;
 IF p_kind='physical' THEN RETURN QUERY SELECT * FROM legacy_report_physical_probe(p_owner,p_input,p_subject,p_at);RETURN; END IF;
 IF p_kind IS NULL OR p_kind NOT IN ('root','report_license','premium_license','parents','history','version','observation','evidence') OR p_at IS NULL THEN RETURN NEXT;RETURN; END IF;
 SELECT account_id,contract_version,created_at,expires_at INTO inp FROM report_input_snapshots WHERE owner_id=p_owner AND id=p_input;
 SELECT * INTO dep FROM report_input_premium_dependencies WHERE owner_id=p_owner AND input_id=p_input AND kind IN ('risk','scenario');
 IF dep.id IS NULL OR inp.contract_version NOT IN (2,3) OR inp.account_id IS DISTINCT FROM dep.account_id THEN RETURN NEXT;RETURN; END IF;
 SELECT * INTO root FROM premium_runs WHERE owner_id=p_owner AND account_id=dep.account_id AND id=dep.run_id;
 IF p_kind='root' THEN
  IF p_subject IS DISTINCT FROM dep.run_id THEN RETURN NEXT;RETURN; END IF;
  next_deadline:=least(inp.expires_at,dep.expires_at,root.expires_at);
  restricted:=root.id IS NULL OR root.kind IS DISTINCT FROM dep.kind OR root.input_digest IS DISTINCT FROM dep.input_digest
   OR dep.expires_at>root.expires_at OR next_deadline<=p_at
   OR EXISTS(SELECT 1 FROM premium_retention_events WHERE owner_id=p_owner AND account_id=dep.account_id AND run_id=dep.run_id);
  RETURN NEXT;RETURN;
 END IF;
 IF root.id IS NULL THEN RETURN NEXT;RETURN; END IF;
 IF p_kind='report_license' THEN
  SELECT provider_id,license_version_id INTO provider,license_id FROM report_input_licenses WHERE owner_id=p_owner AND input_id=p_input AND id=p_subject;
  origin:=inp.created_at;until_at:=inp.expires_at;
 ELSIF p_kind='premium_license' THEN
  SELECT provider_id,license_version_id INTO provider,license_id FROM premium_run_licenses WHERE owner_id=p_owner AND account_id=dep.account_id AND run_id=dep.run_id AND id=p_subject;
  origin:=root.created_at;until_at:=root.expires_at;
 ELSE
  -- Immutable parent IDs were independently checked by the original admission
  -- guards. Maintenance checks current markers using these exact original rows.
  IF dep.kind='risk' THEN
   SELECT r.historical_input_id,x.input_id,r.xray_run_id INTO history_id,xray_input,xray_run FROM risk_runs r
    LEFT JOIN xray_runs x ON x.owner_id=r.owner_id AND x.id=r.xray_run_id
    WHERE r.owner_id=p_owner AND r.account_id=dep.account_id AND r.id=dep.run_id;
  ELSE
   SELECT historical_input_id,xray_input_id,xray_run_id INTO history_id,xray_input,xray_run FROM scenario_runs
    WHERE owner_id=p_owner AND account_id=dep.account_id AND id=dep.run_id;
  END IF;
  IF p_kind='parents' THEN
   IF p_subject IS DISTINCT FROM dep.run_id OR inp.contract_version<>3 THEN RETURN NEXT;RETURN; END IF;
   restricted:=(history_id IS NOT NULL AND EXISTS(SELECT 1 FROM historical_retention_events WHERE owner_id=p_owner AND input_id=history_id))
    OR (xray_input IS NOT NULL AND EXISTS(SELECT 1 FROM xray_retention_events WHERE owner_id=p_owner AND input_id=xray_input));
   RETURN NEXT;RETURN;
  ELSIF p_kind='history' THEN
   IF inp.contract_version<>3 OR history_id IS NULL THEN RETURN NEXT;RETURN; END IF;
   SELECT * INTO h FROM historical_dependencies WHERE owner_id=p_owner AND id=p_subject;
   IF h.id IS NULL OR (h.input_id=history_id OR (h.evidence_id IS NOT NULL AND EXISTS(
    SELECT 1 FROM historical_dependencies WHERE owner_id=p_owner AND input_id=history_id AND registered_evidence_id=h.evidence_id))) IS DISTINCT FROM true THEN RETURN NEXT;RETURN; END IF;
   IF h.classification_id IS NULL THEN RETURN NEXT;RETURN; END IF;
   SELECT l.provider_id,c.license_version_id,c.created_at INTO provider,license_id,origin FROM historical_classification_evidence c
    JOIN provider_license_versions l ON l.owner_id=c.owner_id AND l.id=c.license_version_id
    WHERE c.owner_id=p_owner AND c.id=h.classification_id;
   until_at:=inp.expires_at;
  ELSE
   IF dep.kind<>'scenario' OR inp.contract_version<>3 THEN RETURN NEXT;RETURN; END IF;
   IF p_kind='version' THEN
    SELECT v.provider_id,v.license_version_id,v.created_at,v.expires_at,v.id INTO item FROM scenario_run_sensitivity_versions c
     JOIN scenario_sensitivity_versions v ON v.owner_id=c.owner_id AND v.id=c.version_id
     WHERE c.owner_id=p_owner AND c.account_id=dep.account_id AND c.run_id=dep.run_id AND c.id=p_subject;
    IF item.id IS NULL THEN RETURN NEXT;RETURN; END IF;
    next_deadline:=item.expires_at;
    restricted:=item.expires_at<=p_at OR EXISTS(SELECT 1 FROM scenario_sensitivity_retention WHERE owner_id=p_owner AND version_id=item.id);
   ELSIF p_kind='observation' THEN
    SELECT v.provider_id,v.license_version_id,v.created_at,v.id INTO item FROM scenario_run_sensitivity_observations c
     JOIN scenario_sensitivity_observations v ON v.owner_id=c.owner_id AND v.id=c.observation_id
     WHERE c.owner_id=p_owner AND c.account_id=dep.account_id AND c.run_id=dep.run_id AND c.id=p_subject;
    IF item.id IS NULL THEN RETURN NEXT;RETURN; END IF;
   ELSE
    SELECT v.provider_id,v.license_version_id,v.created_at,v.id INTO item FROM scenario_run_sensitivity_evidence c
     JOIN scenario_sensitivity_evidence v ON v.owner_id=c.owner_id AND v.id=c.evidence_id
     WHERE c.owner_id=p_owner AND c.account_id=dep.account_id AND c.run_id=dep.run_id AND c.id=p_subject;
    IF item.id IS NULL THEN RETURN NEXT;RETURN; END IF;
   END IF;
   provider:=item.provider_id;license_id:=item.license_version_id;origin:=item.created_at;until_at:=root.expires_at;
  END IF;
 END IF;
 IF license_id IS NULL OR provider IS NULL THEN RETURN NEXT;RETURN; END IF;
 SELECT * INTO permit FROM legacy_report_license_probe(p_owner,provider,license_id,origin,until_at,p_at,
  CASE WHEN inp.contract_version=3 THEN 'v3' WHEN p_kind='premium_license' THEN 'v2' ELSE 'permissions' END);
 restricted:=restricted OR permit.restricted;next_deadline:=least(next_deadline,permit.next_deadline);
 RETURN NEXT;
END $$;

CREATE FUNCTION legacy_report_witness_restricted(p_owner uuid,p_input uuid,p_kind text,p_subject uuid,p_at timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT coalesce((SELECT restricted FROM legacy_report_retention_probe(p_owner,p_input,p_kind,p_subject,p_at)),false)
$$;
"""

_OWNED = r"""
CREATE OR REPLACE FUNCTION report_owned_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v jsonb; o jsonb; inp report_input_snapshots; jid uuid; jt text; job jsonb; physical uuid; actual_provider uuid; actual_license uuid;
BEGIN

 IF TG_TABLE_NAME='report_input_dependencies' THEN
  IF TG_OP='UPDATE' THEN
   IF (to_jsonb(NEW)-'copy_pending') IS DISTINCT FROM (to_jsonb(OLD)-'copy_pending') THEN RAISE EXCEPTION 'Report source identity is immutable' USING ERRCODE='23514'; END IF;
   IF OLD.copy_pending IS NULL AND NEW.copy_pending=report_capture_pending(OLD.owner_id,OLD.input_id) THEN RETURN NEW; END IF;
   IF OLD.copy_pending AND NOT NEW.copy_pending AND EXISTS(SELECT 1 FROM report_retention_work WHERE owner_id=OLD.owner_id AND input_id=OLD.input_id AND completed_at IS NULL)
    AND NOT report_capture_pending(OLD.owner_id,OLD.input_id) THEN RETURN NEW; END IF;
   RAISE EXCEPTION 'Report source copies remain or flag is immutable' USING ERRCODE='23514';
  ELSIF TG_OP='INSERT' AND NEW.copy_pending IS DISTINCT FROM true THEN
   RAISE EXCEPTION 'Report source copy must begin pending' USING ERRCODE='23514';
  END IF;
 END IF;
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Report canonical records are immutable'; END IF;
 v:=to_jsonb(NEW);
 IF v ? 'account_id' AND NOT report_account_scope(NEW.owner_id,(v->>'account_id')::uuid) THEN RAISE EXCEPTION 'Report account scope mismatch'; END IF;
 IF TG_TABLE_NAME='report_input_snapshots' THEN
  IF NOT EXISTS (SELECT 1 FROM portfolio_snapshots WHERE id=NEW.snapshot_id AND broker_account_id=NEW.account_id) THEN RAISE EXCEPTION 'Report snapshot scope mismatch'; END IF;
  IF TG_OP='INSERT' AND NEW.sealed_at IS NOT NULL THEN RAISE EXCEPTION 'Report capture must be built before sealing'; END IF;
  IF TG_OP='UPDATE' THEN
   o:=to_jsonb(OLD);
   IF OLD.sealed_at IS NULL THEN
    IF (v-'sealed_at'-'canonical_manifest'-'canonical_context'-'input_digest'-'document_digest'-'canonical_byte_length'-'chunk_count'-'pin_count'-'source_count'-'expires_at') IS DISTINCT FROM
       (o-'sealed_at'-'canonical_manifest'-'canonical_context'-'input_digest'-'document_digest'-'canonical_byte_length'-'chunk_count'-'pin_count'-'source_count'-'expires_at') THEN RAISE EXCEPTION 'Report capture identity changed'; END IF;
   ELSE
    IF v-'canonical_manifest'-'canonical_context'-'purged_at' IS DISTINCT FROM o-'canonical_manifest'-'canonical_context'-'purged_at'
       OR OLD.purged_at IS NOT NULL OR NEW.purged_at IS NULL OR NEW.canonical_manifest IS NOT NULL OR NEW.canonical_context IS NOT NULL
       OR NOT EXISTS (SELECT 1 FROM report_retention_work WHERE owner_id=NEW.owner_id AND input_id=NEW.id AND completed_at IS NULL) THEN
     RAISE EXCEPTION 'Report capture is immutable';
    END IF;
   END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF v ? 'input_id' THEN
  SELECT * INTO inp FROM report_input_snapshots WHERE id=(v->>'input_id')::uuid AND owner_id=NEW.owner_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'Report input scope mismatch'; END IF;
 END IF;
 IF TG_TABLE_NAME IN ('report_input_chunks','report_input_pins','report_input_dependencies','report_input_licenses') THEN
  IF TG_OP='INSERT' AND (inp.sealed_at IS NOT NULL OR inp.purged_at IS NOT NULL OR inp.expires_at<=CURRENT_TIMESTAMP) THEN RAISE EXCEPTION 'Report capture is closed'; END IF;
  IF TG_TABLE_NAME='report_input_licenses' THEN
   IF NOT EXISTS (SELECT 1 FROM provider_license_versions WHERE owner_id=NEW.owner_id AND provider_id=NEW.provider_id AND id=NEW.license_version_id) THEN RAISE EXCEPTION 'Report pinned license scope mismatch'; END IF;
  END IF;
  IF TG_TABLE_NAME='report_input_dependencies' THEN
   jt := CASE NEW.kind WHEN 'price' THEN 'price_snapshots' WHEN 'fx' THEN 'fx_snapshots' WHEN 'benchmark' THEN 'benchmark_snapshots'
    WHEN 'corporate_action' THEN 'corporate_action_snapshots' WHEN 'classification' THEN 'classification_snapshots'
    WHEN 'constituent' THEN 'constituent_snapshots' WHEN 'entity_evidence' THEN 'entity_evidence_versions'
    WHEN 'fund_definition' THEN 'fund_definitions' WHEN 'fund_mapping' THEN 'fund_source_mappings' END;
   EXECUTE format('SELECT provider_id,license_version_id FROM %I WHERE owner_id=$1 AND id=$2',jt)
     INTO actual_provider,actual_license USING NEW.owner_id,NEW.source_id;
   IF actual_provider IS DISTINCT FROM NEW.provider_id OR actual_license IS DISTINCT FROM NEW.license_version_id THEN RAISE EXCEPTION 'Report source license mismatch'; END IF;
  END IF;
  IF TG_OP='UPDATE' THEN
   IF TG_TABLE_NAME<>'report_input_chunks' THEN RAISE EXCEPTION 'Report source pins are immutable'; END IF;
   IF v-'payload'-'purged_at' IS DISTINCT FROM to_jsonb(OLD)-'payload'-'purged_at' OR OLD.purged_at IS NOT NULL OR NEW.purged_at IS NULL OR NEW.payload IS NOT NULL
    OR NOT EXISTS (SELECT 1 FROM report_retention_work WHERE owner_id=NEW.owner_id AND input_id=NEW.input_id AND completed_at IS NULL) THEN RAISE EXCEPTION 'Report chunk is immutable'; END IF;
  ELSIF TG_TABLE_NAME='report_input_chunks' THEN
   IF encode(sha256(NEW.payload),'hex')<>NEW.content_digest THEN RAISE EXCEPTION 'Report chunk hash mismatch'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME IN ('report_manifests','export_manifests','report_artifacts','export_artifacts') THEN
  jt := CASE WHEN TG_TABLE_NAME LIKE 'report_%' THEN 'report_jobs' ELSE 'export_jobs' END;
  EXECUTE format('SELECT to_jsonb(j) FROM %I j WHERE owner_id=$1 AND id=$2',jt) INTO job USING NEW.owner_id,NEW.job_id;
  IF job IS NULL THEN RAISE EXCEPTION 'Report publication job is absent'; END IF;
  SELECT * INTO inp FROM report_input_snapshots WHERE owner_id=NEW.owner_id AND id=(job->>'input_id')::uuid;
  IF TG_OP='UPDATE' THEN
   IF v-'payload'-'contents'-'purged_at' IS DISTINCT FROM to_jsonb(OLD)-'payload'-'contents'-'purged_at' OR OLD.purged_at IS NOT NULL OR NEW.purged_at IS NULL
    OR (v->>'payload') IS NOT NULL OR (v->>'contents') IS NOT NULL
    OR NOT EXISTS (SELECT 1 FROM report_retention_work WHERE owner_id=NEW.owner_id AND input_id=inp.id AND completed_at IS NULL) THEN RAISE EXCEPTION 'Report publication is immutable'; END IF;
   RETURN NEW;
  END IF;
  IF job->>'state'<>'running' OR (job->>'fence')::bigint<>NEW.publication_fence OR (job->>'lease_expires_at')::timestamptz<=CURRENT_TIMESTAMP
    OR inp.sealed_at IS NULL OR inp.purged_at IS NOT NULL OR inp.expires_at<=CURRENT_TIMESTAMP THEN RAISE EXCEPTION 'Report publication fence is stale'; END IF;
  IF TG_TABLE_NAME IN ('report_manifests','export_manifests') THEN
   IF NEW.input_id<>inp.id OR NEW.payload IS DISTINCT FROM inp.canonical_manifest OR encode(sha256(NEW.payload),'hex')<>NEW.content_digest THEN RAISE EXCEPTION 'Report manifest does not match capture'; END IF;
  ELSE
   IF NEW.account_id<>inp.account_id OR NEW.expires_at>(job->>'expires_at')::timestamptz OR encode(sha256(NEW.contents),'hex')<>NEW.content_digest THEN RAISE EXCEPTION 'Report artifact metadata mismatch'; END IF;
   jt := CASE WHEN TG_TABLE_NAME='report_artifacts' THEN 'report_manifests' ELSE 'export_manifests' END;
   EXECUTE format('SELECT to_jsonb(m) FROM %I m WHERE owner_id=$1 AND id=$2',jt) INTO job USING NEW.owner_id,NEW.manifest_id;
   IF job IS NULL OR (job->>'job_id')::uuid<>NEW.job_id OR (job->>'publication_fence')::bigint<>NEW.publication_fence THEN RAISE EXCEPTION 'Report artifact manifest mismatch'; END IF;
   IF NEW.mime_type<>(CASE NEW.format WHEN 'pdf' THEN 'application/pdf' WHEN 'csv' THEN 'text/csv; charset=utf-8' WHEN 'json' THEN 'application/json' WHEN 'xlsx' THEN 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' END) THEN RAISE EXCEPTION 'Report artifact MIME mismatch'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'Report canonical identity is immutable'; END IF;
 RETURN NEW;
END $$;
"""

_SOURCE = r"""
CREATE OR REPLACE FUNCTION report_source_copy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v jsonb := to_jsonb(NEW); entry record; family text; identifier uuid;
BEGIN
 IF TG_TABLE_NAME IN ('source_retention_work','enrichment_retention_work') THEN
  IF NEW.phase<>'complete' THEN RETURN NEW; END IF;
 END IF;
 FOR entry IN SELECT * FROM jsonb_each_text(v) LOOP
  family := CASE entry.key WHEN 'price_snapshot_id' THEN 'price' WHEN 'fx_snapshot_id' THEN 'fx'
   WHEN 'benchmark_snapshot_id' THEN 'benchmark' WHEN 'corporate_action_snapshot_id' THEN 'corporate_action'
   WHEN 'constituent_snapshot_id' THEN 'constituent' WHEN 'classification_snapshot_id' THEN 'classification'
   WHEN 'entity_evidence_version_id' THEN 'entity_evidence' WHEN 'fund_definition_id' THEN 'fund_definition'
   WHEN 'fund_mapping_id' THEN 'fund_mapping' ELSE NULL END;
  IF family IS NOT NULL AND entry.value IS NOT NULL THEN
   identifier := entry.value::uuid;
   IF EXISTS (SELECT 1 FROM report_input_dependencies d WHERE d.owner_id=NEW.owner_id
       AND d.kind=family AND d.source_id=identifier AND d.copy_pending) THEN
    RAISE EXCEPTION 'Report source copies remain';
   END IF;
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
"""

_RETENTION = r"""
CREATE OR REPLACE FUNCTION report_retention_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE inp report_input_snapshots;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Report retention records are immutable'; END IF;
 SELECT id,owner_id,account_id,expires_at,contract_version INTO inp.id,inp.owner_id,inp.account_id,inp.expires_at,inp.contract_version FROM report_input_snapshots WHERE owner_id=NEW.owner_id AND id=NEW.input_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Report retention input is absent'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'Retention must start pending'; END IF;
  IF NEW.projection_source_id IS NOT NULL AND inp.contract_version<>4 THEN RAISE EXCEPTION 'Unexpected projection report witness' USING ERRCODE='23514'; END IF;
  IF NEW.reason='ttl' AND inp.expires_at>CURRENT_TIMESTAMP THEN RAISE EXCEPTION 'Report has not expired'; END IF;
  IF NEW.reason='source' AND NOT report_premium_purge_authorized(NEW.owner_id,NEW.input_id) THEN
   IF NEW.legacy_source_kind IS NOT NULL THEN
    IF (inp.contract_version NOT IN (2,3) AND NEW.legacy_source_kind<>'physical') OR NOT legacy_report_witness_restricted(NEW.owner_id,NEW.input_id,NEW.legacy_source_kind,NEW.legacy_source_id,clock_timestamp()) THEN
     RAISE EXCEPTION 'No current legacy report source restriction' USING ERRCODE='23514'; END IF;
   ELSIF inp.contract_version=4 THEN
    IF NOT report_projection_witness_restricted(NEW.owner_id,NEW.input_id,NEW.projection_source_kind,NEW.projection_source_id,clock_timestamp()) THEN
     RAISE EXCEPTION 'No current projection report source restriction' USING ERRCODE='23514'; END IF;
   ELSE
    RAISE EXCEPTION 'Exact report source restriction witness is required' USING ERRCODE='23514';
   END IF;
  END IF;
  IF NEW.reason='owner' AND EXISTS (SELECT 1 FROM broker_accounts WHERE id=inp.account_id AND status='active') THEN
   RAISE EXCEPTION 'Owner termination requires inactive account';
  END IF;
 ELSE
  IF to_jsonb(NEW)-'completed_at' IS DISTINCT FROM to_jsonb(OLD)-'completed_at' OR OLD.completed_at IS NOT NULL THEN
   RAISE EXCEPTION 'Report retention identity is immutable';
  END IF;
 END IF;
 IF NEW.completed_at IS NOT NULL AND EXISTS(SELECT 1 FROM report_input_dependencies WHERE owner_id=NEW.owner_id AND input_id=NEW.input_id AND copy_pending) THEN RAISE EXCEPTION 'Report source flags remain' USING ERRCODE='23514'; END IF;
 IF NEW.completed_at IS NOT NULL AND report_capture_pending(NEW.owner_id,NEW.input_id) THEN RAISE EXCEPTION 'Report payload remains'; END IF;
 RETURN NEW;
END $$;
"""

_PREVIOUS_OWNED = r"""
CREATE OR REPLACE FUNCTION report_owned_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v jsonb; o jsonb; inp report_input_snapshots; jid uuid; jt text; job jsonb; physical uuid; actual_provider uuid; actual_license uuid;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Report canonical records are immutable'; END IF;
 v:=to_jsonb(NEW);
 IF v ? 'account_id' AND NOT report_account_scope(NEW.owner_id,(v->>'account_id')::uuid) THEN RAISE EXCEPTION 'Report account scope mismatch'; END IF;
 IF TG_TABLE_NAME='report_input_snapshots' THEN
  IF NOT EXISTS (SELECT 1 FROM portfolio_snapshots WHERE id=NEW.snapshot_id AND broker_account_id=NEW.account_id) THEN RAISE EXCEPTION 'Report snapshot scope mismatch'; END IF;
  IF TG_OP='INSERT' AND NEW.sealed_at IS NOT NULL THEN RAISE EXCEPTION 'Report capture must be built before sealing'; END IF;
  IF TG_OP='UPDATE' THEN
   o:=to_jsonb(OLD);
   IF OLD.sealed_at IS NULL THEN
    IF (v-'sealed_at'-'canonical_manifest'-'canonical_context'-'input_digest'-'document_digest'-'canonical_byte_length'-'chunk_count'-'pin_count'-'source_count'-'expires_at') IS DISTINCT FROM
       (o-'sealed_at'-'canonical_manifest'-'canonical_context'-'input_digest'-'document_digest'-'canonical_byte_length'-'chunk_count'-'pin_count'-'source_count'-'expires_at') THEN RAISE EXCEPTION 'Report capture identity changed'; END IF;
   ELSE
    IF v-'canonical_manifest'-'canonical_context'-'purged_at' IS DISTINCT FROM o-'canonical_manifest'-'canonical_context'-'purged_at'
       OR OLD.purged_at IS NOT NULL OR NEW.purged_at IS NULL OR NEW.canonical_manifest IS NOT NULL OR NEW.canonical_context IS NOT NULL
       OR NOT EXISTS (SELECT 1 FROM report_retention_work WHERE owner_id=NEW.owner_id AND input_id=NEW.id AND completed_at IS NULL) THEN
     RAISE EXCEPTION 'Report capture is immutable';
    END IF;
   END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF v ? 'input_id' THEN
  SELECT * INTO inp FROM report_input_snapshots WHERE id=(v->>'input_id')::uuid AND owner_id=NEW.owner_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'Report input scope mismatch'; END IF;
 END IF;
 IF TG_TABLE_NAME IN ('report_input_chunks','report_input_pins','report_input_dependencies','report_input_licenses') THEN
  IF TG_OP='INSERT' AND (inp.sealed_at IS NOT NULL OR inp.purged_at IS NOT NULL OR inp.expires_at<=CURRENT_TIMESTAMP) THEN RAISE EXCEPTION 'Report capture is closed'; END IF;
  IF TG_TABLE_NAME='report_input_licenses' THEN
   IF NOT EXISTS (SELECT 1 FROM provider_license_versions WHERE owner_id=NEW.owner_id AND provider_id=NEW.provider_id AND id=NEW.license_version_id) THEN RAISE EXCEPTION 'Report pinned license scope mismatch'; END IF;
  END IF;
  IF TG_TABLE_NAME='report_input_dependencies' THEN
   jt := CASE NEW.kind WHEN 'price' THEN 'price_snapshots' WHEN 'fx' THEN 'fx_snapshots' WHEN 'benchmark' THEN 'benchmark_snapshots'
    WHEN 'corporate_action' THEN 'corporate_action_snapshots' WHEN 'classification' THEN 'classification_snapshots'
    WHEN 'constituent' THEN 'constituent_snapshots' WHEN 'entity_evidence' THEN 'entity_evidence_versions'
    WHEN 'fund_definition' THEN 'fund_definitions' WHEN 'fund_mapping' THEN 'fund_source_mappings' END;
   EXECUTE format('SELECT provider_id,license_version_id FROM %I WHERE owner_id=$1 AND id=$2',jt)
     INTO actual_provider,actual_license USING NEW.owner_id,NEW.source_id;
   IF actual_provider IS DISTINCT FROM NEW.provider_id OR actual_license IS DISTINCT FROM NEW.license_version_id THEN RAISE EXCEPTION 'Report source license mismatch'; END IF;
  END IF;
  IF TG_OP='UPDATE' THEN
   IF TG_TABLE_NAME<>'report_input_chunks' THEN RAISE EXCEPTION 'Report source pins are immutable'; END IF;
   IF v-'payload'-'purged_at' IS DISTINCT FROM to_jsonb(OLD)-'payload'-'purged_at' OR OLD.purged_at IS NOT NULL OR NEW.purged_at IS NULL OR NEW.payload IS NOT NULL
    OR NOT EXISTS (SELECT 1 FROM report_retention_work WHERE owner_id=NEW.owner_id AND input_id=NEW.input_id AND completed_at IS NULL) THEN RAISE EXCEPTION 'Report chunk is immutable'; END IF;
  ELSIF TG_TABLE_NAME='report_input_chunks' THEN
   IF encode(sha256(NEW.payload),'hex')<>NEW.content_digest THEN RAISE EXCEPTION 'Report chunk hash mismatch'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME IN ('report_manifests','export_manifests','report_artifacts','export_artifacts') THEN
  jt := CASE WHEN TG_TABLE_NAME LIKE 'report_%' THEN 'report_jobs' ELSE 'export_jobs' END;
  EXECUTE format('SELECT to_jsonb(j) FROM %I j WHERE owner_id=$1 AND id=$2',jt) INTO job USING NEW.owner_id,NEW.job_id;
  IF job IS NULL THEN RAISE EXCEPTION 'Report publication job is absent'; END IF;
  SELECT * INTO inp FROM report_input_snapshots WHERE owner_id=NEW.owner_id AND id=(job->>'input_id')::uuid;
  IF TG_OP='UPDATE' THEN
   IF v-'payload'-'contents'-'purged_at' IS DISTINCT FROM to_jsonb(OLD)-'payload'-'contents'-'purged_at' OR OLD.purged_at IS NOT NULL OR NEW.purged_at IS NULL
    OR (v->>'payload') IS NOT NULL OR (v->>'contents') IS NOT NULL
    OR NOT EXISTS (SELECT 1 FROM report_retention_work WHERE owner_id=NEW.owner_id AND input_id=inp.id AND completed_at IS NULL) THEN RAISE EXCEPTION 'Report publication is immutable'; END IF;
   RETURN NEW;
  END IF;
  IF job->>'state'<>'running' OR (job->>'fence')::bigint<>NEW.publication_fence OR (job->>'lease_expires_at')::timestamptz<=CURRENT_TIMESTAMP
    OR inp.sealed_at IS NULL OR inp.purged_at IS NOT NULL OR inp.expires_at<=CURRENT_TIMESTAMP THEN RAISE EXCEPTION 'Report publication fence is stale'; END IF;
  IF TG_TABLE_NAME IN ('report_manifests','export_manifests') THEN
   IF NEW.input_id<>inp.id OR NEW.payload IS DISTINCT FROM inp.canonical_manifest OR encode(sha256(NEW.payload),'hex')<>NEW.content_digest THEN RAISE EXCEPTION 'Report manifest does not match capture'; END IF;
  ELSE
   IF NEW.account_id<>inp.account_id OR NEW.expires_at>(job->>'expires_at')::timestamptz OR encode(sha256(NEW.contents),'hex')<>NEW.content_digest THEN RAISE EXCEPTION 'Report artifact metadata mismatch'; END IF;
   jt := CASE WHEN TG_TABLE_NAME='report_artifacts' THEN 'report_manifests' ELSE 'export_manifests' END;
   EXECUTE format('SELECT to_jsonb(m) FROM %I m WHERE owner_id=$1 AND id=$2',jt) INTO job USING NEW.owner_id,NEW.manifest_id;
   IF job IS NULL OR (job->>'job_id')::uuid<>NEW.job_id OR (job->>'publication_fence')::bigint<>NEW.publication_fence THEN RAISE EXCEPTION 'Report artifact manifest mismatch'; END IF;
   IF NEW.mime_type<>(CASE NEW.format WHEN 'pdf' THEN 'application/pdf' WHEN 'csv' THEN 'text/csv; charset=utf-8' WHEN 'json' THEN 'application/json' WHEN 'xlsx' THEN 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' END) THEN RAISE EXCEPTION 'Report artifact MIME mismatch'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'Report canonical identity is immutable'; END IF;
 RETURN NEW;
END $$;
"""

_PREVIOUS_SOURCE = r"""
CREATE OR REPLACE FUNCTION report_source_copy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v jsonb := to_jsonb(NEW); entry record; family text; identifier uuid;
BEGIN
 IF TG_TABLE_NAME IN ('source_retention_work','enrichment_retention_work') THEN
  IF NEW.phase<>'complete' THEN RETURN NEW; END IF;
 END IF;
 FOR entry IN SELECT * FROM jsonb_each_text(v) LOOP
  family := CASE entry.key WHEN 'price_snapshot_id' THEN 'price' WHEN 'fx_snapshot_id' THEN 'fx'
   WHEN 'benchmark_snapshot_id' THEN 'benchmark' WHEN 'corporate_action_snapshot_id' THEN 'corporate_action'
   WHEN 'constituent_snapshot_id' THEN 'constituent' WHEN 'classification_snapshot_id' THEN 'classification'
   WHEN 'entity_evidence_version_id' THEN 'entity_evidence' WHEN 'fund_definition_id' THEN 'fund_definition'
   WHEN 'fund_mapping_id' THEN 'fund_mapping' ELSE NULL END;
  IF family IS NOT NULL AND entry.value IS NOT NULL THEN
   identifier := entry.value::uuid;
   IF EXISTS (SELECT 1 FROM report_input_dependencies d WHERE d.owner_id=NEW.owner_id
       AND d.kind=family AND d.source_id=identifier AND report_capture_pending(d.owner_id,d.input_id)) THEN
    RAISE EXCEPTION 'Report source copies remain';
   END IF;
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
"""

_PREVIOUS_RETENTION = r"""
CREATE OR REPLACE FUNCTION report_retention_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE inp report_input_snapshots;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Report retention records are immutable'; END IF;
 SELECT id,owner_id,account_id,expires_at,contract_version INTO inp.id,inp.owner_id,inp.account_id,inp.expires_at,inp.contract_version FROM report_input_snapshots WHERE owner_id=NEW.owner_id AND id=NEW.input_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Report retention input is absent'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'Retention must start pending'; END IF;
  IF NEW.projection_source_id IS NOT NULL AND inp.contract_version<>4 THEN RAISE EXCEPTION 'Unexpected projection report witness' USING ERRCODE='23514'; END IF;
  IF NEW.reason='ttl' AND inp.expires_at>CURRENT_TIMESTAMP THEN RAISE EXCEPTION 'Report has not expired'; END IF;
  IF NEW.reason='source' AND NOT report_premium_purge_authorized(NEW.owner_id,NEW.input_id) THEN
   IF inp.contract_version=4 THEN
    IF NOT report_projection_witness_restricted(NEW.owner_id,NEW.input_id,NEW.projection_source_kind,NEW.projection_source_id,clock_timestamp()) THEN
     RAISE EXCEPTION 'No current projection report source restriction' USING ERRCODE='23514'; END IF;
   ELSE
   IF NOT report_premium_restricted(NEW.owner_id,NEW.input_id,CURRENT_TIMESTAMP) AND NOT EXISTS (
   SELECT 1 FROM report_input_dependencies d WHERE d.input_id=inp.id AND d.owner_id=inp.owner_id AND (
    d.expires_at<=CURRENT_TIMESTAMP OR EXISTS (
     SELECT 1 FROM source_retention_work w WHERE w.owner_id=d.owner_id AND
       (w.price_snapshot_id=d.price_snapshot_id OR w.fx_snapshot_id=d.fx_snapshot_id
       OR w.benchmark_snapshot_id=d.benchmark_snapshot_id OR w.corporate_action_snapshot_id=d.corporate_action_snapshot_id
       OR w.constituent_snapshot_id=d.constituent_snapshot_id)) OR EXISTS (
     SELECT 1 FROM enrichment_retention_work w WHERE w.owner_id=d.owner_id AND
       (w.entity_evidence_version_id=d.entity_evidence_version_id OR w.classification_snapshot_id=d.classification_snapshot_id
       OR w.fund_definition_id=d.fund_definition_id OR w.fund_mapping_id=d.fund_mapping_id)))) THEN
   RAISE EXCEPTION 'No expired report source';
   END IF;
   END IF;
  END IF;
  IF NEW.reason='owner' AND EXISTS (SELECT 1 FROM broker_accounts WHERE id=inp.account_id AND status='active') THEN
   RAISE EXCEPTION 'Owner termination requires inactive account';
  END IF;
 ELSE
  IF to_jsonb(NEW)-'completed_at' IS DISTINCT FROM to_jsonb(OLD)-'completed_at' OR OLD.completed_at IS NOT NULL THEN
   RAISE EXCEPTION 'Report retention identity is immutable';
  END IF;
 END IF;
 IF NEW.completed_at IS NOT NULL AND report_capture_pending(NEW.owner_id,NEW.input_id) THEN RAISE EXCEPTION 'Report payload remains'; END IF;
 RETURN NEW;
END $$;
"""
