"""Explicit projection report profile with immutable original source bindings.

Revision ID: 20260915_0023
Revises: 20260915_0022

Existing profiles retain their guards and canonical bytes. Complete read/seal
source authorization is separate from the resumable REPORT-only cleanup scan.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0023"
down_revision = "20260915_0022"
branch_labels = None
depends_on = None

_PROJECTION_COPY_TABLES = (
    "projection_inputs",
    "projection_run_allocations",
    "projection_calendar_boundaries",
    "projection_run_pauses",
    "projection_run_schedule_entries",
    "projection_source_proofs",
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

_CHECKS = (
    (
        "report_definitions",
        "section_bound",
        "cardinality(sections) BETWEEN 1 AND 14",
        "cardinality(sections) BETWEEN 1 AND 15",
        "",
    ),
    (
        "report_input_snapshots",
        "contract_version_allowed",
        "contract_version IN (1,2,3)",
        "contract_version IN (1,2,3,4)",
        " AND (kind='report' OR contract_version=1)",
    ),
    (
        "report_jobs",
        "contract_version_allowed",
        "contract_version IN (1,2,3)",
        "contract_version IN (1,2,3,4)",
        "",
    ),
    (
        "report_input_premium_dependencies",
        "kind_allowed",
        "kind IN ('risk','scenario')",
        "kind IN ('risk','scenario','projection')",
        "",
    ),
    (
        "projection_retention_scans",
        "phase_bound",
        "purpose IN ('expiry','source_match')",
        "purpose IN ('expiry','report_expiry','source_match')",
        " AND phase IN ('source','walk','clear','restart','clean','matched')",
    ),
    (
        "projection_retention_scans",
        "target_bound",
        "(purpose='expiry' AND target_kind IS NULL AND target_id IS NULL)",
        "(purpose IN ('expiry','report_expiry') AND target_kind IS NULL AND target_id IS NULL)",
        " OR (purpose='source_match' AND target_kind IN ('price','fx','corporate_action','benchmark','historical') AND target_id IS NOT NULL)",
    ),
    (
        "projection_retention_sweeps",
        "purpose_bound",
        "purpose IN ('expiry','source_match','owner_erasure')",
        "purpose IN ('expiry','report_expiry','source_match','owner_erasure')",
        "",
    ),
    (
        "projection_retention_sweeps",
        "scope_bound",
        "(purpose='expiry' AND target_kind IS NULL AND target_id IS NULL)",
        "(purpose IN ('expiry','report_expiry') AND target_kind IS NULL AND target_id IS NULL)",
        " OR (purpose='owner_erasure' AND owner_id IS NOT NULL AND target_kind IS NULL AND target_id IS NULL) OR (purpose='source_match' AND owner_id IS NOT NULL AND target_kind IN ('price','fx','corporate_action','benchmark','historical') AND target_id IS NOT NULL)",
    ),
)


def _checks(*, previous: bool) -> None:
    for table, name, old, new, suffix in _CHECKS:
        constraint = op.f("ck_" + table + "_" + name)
        op.drop_constraint(constraint, table, type_="check")
        op.create_check_constraint(constraint, table, (old if previous else new) + suffix)


def upgrade() -> None:
    _checks(previous=False)
    op.add_column(
        "report_input_premium_dependencies", sa.Column("copy_pending", sa.Boolean(), nullable=True)
    )
    for name, table, columns, predicate in _PENDING_INDEXES:
        op.create_index(
            name,
            table,
            list(columns),
            **({"postgresql_where": sa.text(predicate)} if predicate else {}),
        )
    op.execute(_PENDING_GUARDS)
    op.add_column(
        "report_retention_work", sa.Column("projection_source_kind", sa.String(20), nullable=True)
    )
    op.add_column(
        "report_retention_work", sa.Column("projection_source_id", sa.Uuid(), nullable=True)
    )
    op.create_check_constraint(
        "projection_witness_bound",
        "report_retention_work",
        "(projection_source_kind IS NULL AND projection_source_id IS NULL) OR (reason='source' AND projection_source_kind IN ('price','fx','corporate_action','benchmark','historical','license','classification') AND projection_source_id IS NOT NULL)",
    )
    op.add_column(
        "projection_retention_scans", sa.Column("restriction_kind", sa.String(20), nullable=True)
    )
    op.add_column(
        "projection_retention_scans", sa.Column("restriction_id", sa.Uuid(), nullable=True)
    )
    op.create_check_constraint(
        "witness_bound",
        "projection_retention_scans",
        "(restriction_kind IS NULL AND restriction_id IS NULL) OR (purpose='report_expiry' AND restriction_kind IN ('price','fx','corporate_action','benchmark','historical','license','classification') AND restriction_id IS NOT NULL)",
    )
    op.execute(_WITNESS_GUARD)
    op.execute(_HELPERS)
    op.execute(_GUARDS)
    op.execute(_PARENT_COPIES)
    op.execute(_MEMBERSHIP_GUARD)
    # Existing immutable financial bytes are untouched. Only the new operational
    # flag is initialized from exact present copies while this column is nullable.
    op.execute(
        "UPDATE report_input_premium_dependencies SET copy_pending=report_capture_pending(owner_id,input_id)"
    )
    op.alter_column(
        "report_input_premium_dependencies",
        "copy_pending",
        nullable=False,
        server_default=sa.text("true"),
    )
    op.execute(_RETENTION_GUARD)
    op.execute(
        "CREATE TRIGGER report_premium_copy_finished AFTER UPDATE OF completed_at ON report_retention_work FOR EACH ROW EXECUTE FUNCTION report_premium_copy_finished()"
    )
    for table in _PROJECTION_COPY_TABLES:
        op.execute(
            f"CREATE TRIGGER reports_premium_copy_guard BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION report_premium_copy_guard()"
        )


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM report_definitions WHERE cardinality(sections)>14)
       OR EXISTS(SELECT 1 FROM report_input_snapshots WHERE contract_version=4)
       OR EXISTS(SELECT 1 FROM report_jobs WHERE contract_version=4)
       OR EXISTS(SELECT 1 FROM report_input_premium_dependencies WHERE kind='projection')
       OR EXISTS(SELECT 1 FROM projection_retention_scans WHERE purpose='report_expiry')
       OR EXISTS(SELECT 1 FROM projection_retention_sweeps WHERE purpose='report_expiry')
      THEN RAISE EXCEPTION 'Projection reports and their maintenance continuations must be absent before downgrade' USING ERRCODE='23514'; END IF;
    END $$""")
    for table in _PROJECTION_COPY_TABLES:
        op.execute(f"DROP TRIGGER reports_premium_copy_guard ON {table}")
    op.execute("DROP TRIGGER report_premium_copy_finished ON report_retention_work")
    op.execute(_PREVIOUS_GUARDS)
    op.execute(_PREVIOUS_PARENT_COPIES)
    op.execute(_PREVIOUS_MEMBERSHIP_GUARD)
    op.execute(_PREVIOUS_REPORT_RETENTION)
    op.execute(_PREVIOUS_REPORT_PENDING)
    op.execute(
        "DROP FUNCTION report_projection_witness_restricted(uuid,uuid,text,uuid,timestamptz)"
    )
    op.drop_constraint(
        op.f("ck_report_retention_work_projection_witness_bound"),
        "report_retention_work",
        type_="check",
    )
    op.drop_column("report_retention_work", "projection_source_id")
    op.drop_column("report_retention_work", "projection_source_kind")
    op.drop_constraint(
        op.f("ck_projection_retention_scans_witness_bound"),
        "projection_retention_scans",
        type_="check",
    )
    op.drop_column("projection_retention_scans", "restriction_id")
    op.drop_column("projection_retention_scans", "restriction_kind")
    op.execute("DROP FUNCTION report_premium_copy_finished()")
    op.execute("DROP FUNCTION report_premium_purge_authorized(uuid,uuid)")
    for name, table, columns, predicate in reversed(_PENDING_INDEXES):
        op.drop_index(name, table_name=table)
    op.drop_column("report_input_premium_dependencies", "copy_pending")
    for signature in (
        "report_projection_restricted(uuid,uuid,timestamptz)",
        "report_projection_manifest_valid(report_input_premium_dependencies,report_input_snapshots)",
        "report_projection_version_valid(jsonb,uuid,uuid,integer,uuid,text,text,text,timestamptz)",
        "report_projection_basis_valid(report_input_premium_dependencies,report_input_snapshots)",
        "projection_report_sources_restricted(uuid,timestamptz)",
        "projection_report_required_licenses(uuid,uuid,text)",
        "projection_report_history_until(uuid,uuid,timestamptz,timestamptz)",
        "projection_report_physical_until(uuid,text,uuid,timestamptz)",
        "projection_report_license_until(uuid,uuid,timestamptz,timestamptz)",
    ):
        op.execute(f"DROP FUNCTION {signature}")
    _checks(previous=True)


_PENDING_INDEXES = (
    (
        "ix_report_premium_pending",
        "report_input_premium_dependencies",
        ("owner_id", "run_id", "copy_pending", "input_id"),
        None,
    ),
    (
        "ix_report_chunks_pending",
        "report_input_chunks",
        ("owner_id", "input_id", "id"),
        "payload IS NOT NULL",
    ),
    (
        "ix_report_manifests_pending",
        "report_manifests",
        ("owner_id", "input_id", "id"),
        "payload IS NOT NULL",
    ),
    (
        "ix_export_manifests_pending",
        "export_manifests",
        ("owner_id", "input_id", "id"),
        "payload IS NOT NULL",
    ),
    (
        "ix_report_artifacts_pending",
        "report_artifacts",
        ("owner_id", "job_id", "id"),
        "contents IS NOT NULL",
    ),
    (
        "ix_export_artifacts_pending",
        "export_artifacts",
        ("owner_id", "job_id", "id"),
        "contents IS NOT NULL",
    ),
    (
        "ix_application_command_report_job",
        "application_command_identities",
        ("owner_id", "report_job_id", "account_id", "command_digest"),
        "report_job_id IS NOT NULL",
    ),
    (
        "ix_application_command_export_job",
        "application_command_identities",
        ("owner_id", "export_job_id", "account_id", "command_digest"),
        "export_job_id IS NOT NULL",
    ),
    (
        "ix_report_inputs_pending_ttl",
        "report_input_snapshots",
        ("expires_at", "id"),
        "purged_at IS NULL",
    ),
    (
        "ix_report_inputs_legacy_source_expiry",
        "report_input_snapshots",
        ("expires_at", "id"),
        "purged_at IS NULL AND contract_version IN (2,3)",
    ),
)

_HELPERS = r"""
CREATE FUNCTION projection_report_license_until(p_owner uuid,p_license uuid,p_original timestamptz,p_at timestamptz)
RETURNS timestamptz LANGUAGE plpgsql STABLE AS $$
DECLARE pinned provider_license_versions; current_license provider_license_versions;
BEGIN
 SELECT * INTO pinned FROM provider_license_versions WHERE id=p_license AND owner_id=p_owner;
 IF pinned.id IS NULL OR pinned.effective_at>p_at OR pinned.store_permission<>'allowed'
  OR pinned.display_permission<>'allowed' OR pinned.report_permission<>'allowed' OR pinned.retention_days IS NULL THEN RETURN NULL; END IF;
 SELECT * INTO current_license FROM provider_license_versions
 WHERE owner_id=p_owner AND provider_id=pinned.provider_id AND effective_at<=p_at
 ORDER BY effective_at DESC,version_number DESC,id DESC LIMIT 1;
 IF current_license.id IS NULL OR current_license.store_permission<>'allowed'
  OR current_license.display_permission<>'allowed' OR current_license.report_permission<>'allowed' OR current_license.retention_days IS NULL
  OR p_original>p_at THEN RETURN NULL; END IF;
 RETURN p_original+least(30,pinned.retention_days,current_license.retention_days)*interval '1 day';
END $$;

CREATE FUNCTION projection_report_physical_until(p_owner uuid,p_kind text,p_id uuid,p_at timestamptz)
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
 until_at:=projection_report_license_until(p_owner,pinned,original,p_at);
 IF until_at IS NULL THEN RETURN NULL; END IF;
 RETURN least(expiry,until_at);
END $$;

CREATE FUNCTION projection_report_history_until(p_owner uuid,p_input uuid,p_copy_at timestamptz,p_at timestamptz)
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
   until_at:=projection_report_physical_until(p_owner,physical_kind,physical_id,p_at);
   IF until_at IS NULL OR until_at<=p_at THEN RETURN NULL; END IF;
   expiry:=least(expiry,until_at);
   SELECT h.license_version_id INTO pinned FROM (
    SELECT license_version_id FROM price_snapshots WHERE physical_kind='price' AND owner_id=p_owner AND id=physical_id
    UNION ALL SELECT license_version_id FROM fx_snapshots WHERE physical_kind='fx' AND owner_id=p_owner AND id=physical_id
    UNION ALL SELECT license_version_id FROM corporate_action_snapshots WHERE physical_kind='corporate_action' AND owner_id=p_owner AND id=physical_id
    UNION ALL SELECT license_version_id FROM benchmark_snapshots WHERE physical_kind='benchmark' AND owner_id=p_owner AND id=physical_id
   ) h;
   IF pinned IS NULL THEN RETURN NULL; END IF;
   stamp:=original;
  END IF;
  IF pinned IS NOT NULL THEN
   until_at:=projection_report_license_until(p_owner,pinned,stamp,p_at);
   IF until_at IS NULL OR until_at<=p_at THEN RETURN NULL; END IF;
   expiry:=least(expiry,until_at);
   until_at:=projection_report_license_until(p_owner,pinned,original,p_at);
   IF until_at IS NULL OR until_at<=p_at THEN RETURN NULL; END IF;
   expiry:=least(expiry,until_at);
  END IF;
 END LOOP;
 RETURN expiry;
END $$;

-- Full read/capture authority, never an expiry candidate or continuation cache.
CREATE FUNCTION projection_report_required_licenses(p_owner uuid,p_subject uuid,p_kind text)
RETURNS uuid[] LANGUAGE plpgsql STABLE AS $$
DECLARE item historical_dependencies; result uuid[]:=ARRAY[]::uuid[]; identifier uuid;
 seen integer:=0;
BEGIN
 IF p_kind='portfolio_snapshot' THEN RETURN result; END IF;
 IF p_kind IN ('price_total_return','benchmark_total_return') THEN
  SELECT h.license_version_id INTO identifier FROM (
   SELECT license_version_id FROM price_snapshots WHERE p_kind='price_total_return' AND owner_id=p_owner AND id=p_subject
   UNION ALL SELECT license_version_id FROM benchmark_snapshots WHERE p_kind='benchmark_total_return' AND owner_id=p_owner AND id=p_subject
  ) h;
  IF identifier IS NULL THEN RETURN NULL; END IF;
  RETURN ARRAY[identifier];
 END IF;
 IF p_kind<>'historical_input' THEN RETURN NULL; END IF;
 FOR item IN SELECT * FROM projection_history_links(p_owner,p_subject) LOOP
  seen:=seen+1; IF seen>100000 THEN RETURN NULL; END IF;
  identifier:=item.license_version_id;
  IF item.price_snapshot_id IS NOT NULL THEN
   SELECT license_version_id INTO identifier FROM price_snapshots WHERE owner_id=p_owner AND id=item.price_snapshot_id;
  ELSIF item.fx_snapshot_id IS NOT NULL THEN
   SELECT license_version_id INTO identifier FROM fx_snapshots WHERE owner_id=p_owner AND id=item.fx_snapshot_id;
  ELSIF item.action_snapshot_id IS NOT NULL THEN
   SELECT license_version_id INTO identifier FROM corporate_action_snapshots WHERE owner_id=p_owner AND id=item.action_snapshot_id;
  ELSIF item.benchmark_snapshot_id IS NOT NULL THEN
   SELECT license_version_id INTO identifier FROM benchmark_snapshots WHERE owner_id=p_owner AND id=item.benchmark_snapshot_id;
  ELSIF item.classification_id IS NOT NULL THEN
   SELECT license_version_id INTO identifier FROM historical_classification_evidence WHERE owner_id=p_owner AND id=item.classification_id;
  END IF;
  IF identifier IS NULL AND num_nonnulls(item.license_version_id,item.price_snapshot_id,item.fx_snapshot_id,item.action_snapshot_id,item.benchmark_snapshot_id,item.classification_id)>0 THEN RETURN NULL; END IF;
  IF identifier IS NOT NULL AND NOT(identifier=ANY(result)) THEN
   result:=array_append(result,identifier);
   IF cardinality(result)>256 THEN RETURN NULL; END IF;
  END IF;
 END LOOP;
 RETURN result;
END $$;

CREATE FUNCTION projection_report_sources_restricted(p_run uuid,p_at timestamptz)
RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE root premium_runs; capture projection_runs; assumption assumption_versions;
 item projection_run_sources; lineage premium_run_licenses;
 seen integer:=0; observed integer:=0; calibrated integer:=0; matches integer;
 stamp timestamptz; source_digest text; until_at timestamptz; physical text; family text;
 required uuid[]; all_required uuid[]:=ARRAY[]::uuid[]; selected_license uuid; selected_provider uuid;
BEGIN
 SELECT * INTO root FROM premium_runs WHERE id=p_run AND kind='projection';
 SELECT * INTO capture FROM projection_runs WHERE id=p_run;
 IF p_at IS NULL OR root.id IS NULL OR capture.id IS NULL OR NOT capture.sealed OR root.expires_at<=p_at
  OR root.created_at>p_at OR root.owner_id IS DISTINCT FROM capture.owner_id
  OR root.account_id IS DISTINCT FROM capture.account_id
  OR root.input_digest IS DISTINCT FROM capture.capture_digest
  OR EXISTS(SELECT 1 FROM premium_retention_events WHERE owner_id=root.owner_id AND run_id=root.id)
 THEN RETURN true; END IF;
 SELECT * INTO assumption FROM assumption_versions WHERE owner_id=root.owner_id AND account_id=root.account_id AND id=capture.assumption_version_id;
 IF assumption.id IS NULL OR NOT assumption.sealed OR assumption.content_digest IS DISTINCT FROM capture.assumption_digest THEN RETURN true; END IF;
 FOR item IN SELECT * FROM projection_run_sources WHERE run_id=p_run AND owner_id=root.owner_id
  AND account_id=root.account_id ORDER BY id LIMIT 258 LOOP
  seen:=seen+1;
  IF seen>257 OR item.source_expires_at<=p_at OR root.expires_at>item.source_expires_at
   OR item.original_created_at>root.created_at THEN RETURN true; END IF;
  selected_license:=NULL; selected_provider:=NULL; stamp:=NULL; source_digest:=NULL;
  until_at:=root.created_at+interval '30 days';
  IF item.kind='initial_snapshot' THEN
   observed:=observed+1; family:='portfolio_snapshot';
   SELECT s.created_at,encode(sha256(convert_to('['||to_json(s.id::text)::text||','||to_json(c.output_fingerprint)::text||']','UTF8')),'hex')
   INTO stamp,source_digest FROM portfolio_snapshots s JOIN calculation_runs c ON c.id=s.calculation_run_id
   WHERE s.id=item.subject_id AND s.broker_account_id=root.account_id AND c.broker_account_id=root.account_id
    AND capture.initial_kind='observed_snapshot' AND capture.snapshot_id=s.id
    AND capture.snapshot_valuation_at=s.valuation_at;
   IF source_digest IS DISTINCT FROM capture.snapshot_digest THEN RETURN true; END IF;
  ELSIF item.kind='calibration' THEN
   calibrated:=calibrated+1;
   IF NOT EXISTS(SELECT 1 FROM projection_calibration_pins p WHERE p.owner_id=root.owner_id AND p.account_id=root.account_id
    AND p.version_id=capture.assumption_version_id AND p.subject_id=item.subject_id AND p.content_digest=item.content_digest) THEN RETURN true; END IF;
   SELECT count(*) INTO matches FROM (
    SELECT id FROM historical_input_snapshots WHERE owner_id=root.owner_id AND broker_account_id=root.account_id AND id=item.subject_id
    UNION ALL SELECT id FROM price_snapshots WHERE owner_id=root.owner_id AND id=item.subject_id
    UNION ALL SELECT id FROM benchmark_snapshots WHERE owner_id=root.owner_id AND id=item.subject_id
   ) choices;
   IF matches<>1 THEN RETURN true; END IF;
   SELECT created_at,input_digest INTO stamp,source_digest FROM historical_input_snapshots
    WHERE owner_id=root.owner_id AND broker_account_id=root.account_id AND id=item.subject_id;
   IF FOUND THEN
    family:='historical_input';
    until_at:=projection_report_history_until(root.owner_id,item.subject_id,root.created_at,p_at);
   ELSE
    SELECT h.created_at,h.content_digest,h.license_version_id,h.provider_id INTO stamp,source_digest,selected_license,selected_provider
    FROM price_snapshots h JOIN market_source_series s ON s.id=h.series_id AND s.owner_id=h.owner_id
    WHERE h.owner_id=root.owner_id AND h.id=item.subject_id AND s.kind='security_price' AND s.basis='total_return'
     AND s.provider_id=h.provider_id AND s.license_version_id=h.license_version_id;
    IF FOUND THEN physical:='price'; family:='price_total_return';
    ELSE
     SELECT h.created_at,h.content_digest,h.license_version_id,h.provider_id INTO stamp,source_digest,selected_license,selected_provider
     FROM benchmark_snapshots h JOIN market_source_series s ON s.id=h.series_id AND s.owner_id=h.owner_id
     WHERE h.owner_id=root.owner_id AND h.id=item.subject_id AND s.kind='benchmark_level' AND s.basis='total_return'
      AND s.provider_id=h.provider_id AND s.license_version_id=h.license_version_id;
     physical:='benchmark'; family:='benchmark_total_return';
    END IF;
    until_at:=projection_report_physical_until(root.owner_id,physical,item.subject_id,p_at);
   END IF;
  ELSE RETURN true; END IF;
  IF stamp IS NULL OR stamp IS DISTINCT FROM item.original_created_at OR source_digest IS DISTINCT FROM item.content_digest
   OR until_at IS NULL OR until_at<=p_at OR root.expires_at>until_at THEN RETURN true; END IF;
  required:=projection_report_required_licenses(root.owner_id,item.subject_id,family);
  IF required IS NULL OR (SELECT count(*) FROM projection_source_licenses l WHERE l.owner_id=root.owner_id
   AND l.account_id=root.account_id AND l.run_id=root.id AND l.source_id=item.id)<>cardinality(required)
  OR EXISTS(SELECT 1 FROM projection_source_licenses l LEFT JOIN premium_run_licenses r
    ON r.id=l.run_license_id AND r.owner_id=l.owner_id AND r.account_id=l.account_id AND r.run_id=l.run_id
   WHERE l.owner_id=root.owner_id AND l.account_id=root.account_id AND l.run_id=root.id AND l.source_id=item.id
    AND (r.id IS NULL OR NOT(r.license_version_id=ANY(required)))) THEN RETURN true; END IF;
  FOREACH selected_license IN ARRAY required LOOP
   IF NOT(selected_license=ANY(all_required)) THEN all_required:=array_append(all_required,selected_license); END IF;
   IF cardinality(all_required)>256 THEN RETURN true; END IF;
  END LOOP;
 END LOOP;
 IF seen<>capture.source_count OR calibrated<>assumption.calibration_count OR
  observed<>(CASE WHEN capture.initial_kind='observed_snapshot' THEN 1 ELSE 0 END)
  OR (SELECT count(*) FROM projection_calibration_pins WHERE owner_id=root.owner_id AND account_id=root.account_id AND version_id=assumption.id)<>calibrated
  OR (SELECT count(*) FROM premium_run_licenses WHERE owner_id=root.owner_id AND account_id=root.account_id AND run_id=root.id)<>cardinality(all_required)
 THEN RETURN true; END IF;
 FOR lineage IN SELECT * FROM premium_run_licenses WHERE owner_id=root.owner_id AND account_id=root.account_id AND run_id=root.id ORDER BY id LIMIT 257 LOOP
  IF NOT(lineage.license_version_id=ANY(all_required)) OR NOT EXISTS(SELECT 1 FROM provider_license_versions
   WHERE owner_id=root.owner_id AND id=lineage.license_version_id AND provider_id=lineage.provider_id) THEN RETURN true; END IF;
  until_at:=projection_report_license_until(root.owner_id,lineage.license_version_id,root.created_at,p_at);
  IF until_at IS NULL OR until_at<=p_at OR root.expires_at>until_at THEN RETURN true; END IF;
 END LOOP;
 RETURN false;
END $$;

CREATE FUNCTION report_projection_basis_valid(d report_input_premium_dependencies,i report_input_snapshots)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT COALESCE(i.contract_version=4 AND i.kind='report' AND d.kind='projection'
  AND d.owner_id=i.owner_id AND d.account_id=i.account_id AND d.input_id=i.id
  AND num_nonnulls(d.result_id,d.definition_version_id,d.definition_digest,d.snapshot_id,d.snapshot_digest,d.reporting_currency,d.source_cutoff_at,d.valuation_at)=8
  AND d.snapshot_id=i.snapshot_id AND d.reporting_currency=i.reporting_currency
  AND d.source_cutoff_at=i.source_cutoff_at AND d.valuation_at=i.valuation_at
  AND EXISTS(SELECT 1 FROM portfolio_snapshots s JOIN calculation_runs c ON c.id=s.calculation_run_id
   WHERE s.id=d.snapshot_id AND s.broker_account_id=d.account_id AND c.broker_account_id=d.account_id
    AND s.valuation_at=d.valuation_at AND s.source_cutoff_at<=d.source_cutoff_at AND s.valuation_at<=d.source_cutoff_at
    AND encode(sha256(convert_to('['||to_json(s.id::text)::text||','||to_json(c.output_fingerprint)::text||']','UTF8')),'hex')=d.snapshot_digest)
  AND EXISTS(SELECT 1 FROM report_input_pins p WHERE p.owner_id=d.owner_id AND p.input_id=d.input_id AND p.kind='snapshot:snapshot' AND p.subject_id=d.snapshot_id AND p.parent_id IS NULL AND p.content_digest=d.snapshot_digest)
  AND EXISTS(SELECT 1 FROM report_input_pins p WHERE p.owner_id=d.owner_id AND p.input_id=d.input_id AND p.kind='projection:input' AND p.subject_id=d.run_id AND p.parent_id IS NULL AND p.content_digest=d.input_digest)
  AND EXISTS(SELECT 1 FROM report_input_pins p WHERE p.owner_id=d.owner_id AND p.input_id=d.input_id AND p.kind='projection:result' AND p.subject_id=d.result_id AND p.parent_id=d.run_id AND p.content_digest=d.result_digest)
  AND (SELECT count(*) FROM report_input_pins p WHERE p.owner_id=d.owner_id AND p.input_id=d.input_id AND split_part(p.kind,':',1)='projection')=3
  AND NOT EXISTS(SELECT 1 FROM report_input_pins p WHERE p.owner_id=d.owner_id AND p.input_id=d.input_id AND split_part(p.kind,':',1) IN ('risk','scenario','research'))
  AND EXISTS(SELECT 1 FROM premium_runs root
   JOIN projection_runs run ON run.id=root.id AND run.owner_id=root.owner_id AND run.account_id=root.account_id
   JOIN assumption_versions a ON a.id=run.assumption_version_id AND a.owner_id=run.owner_id AND a.account_id=run.account_id
   JOIN projection_results result ON result.run_id=root.id AND result.owner_id=root.owner_id AND result.account_id=root.account_id
   JOIN premium_jobs job ON job.id=result.job_id AND job.run_id=root.id AND job.owner_id=root.owner_id AND job.account_id=root.account_id
   WHERE root.id=d.run_id AND root.owner_id=d.owner_id AND root.account_id=d.account_id AND root.kind='projection'
    AND root.input_digest=d.input_digest AND run.capture_digest=d.input_digest AND run.sealed AND result.sealed AND a.sealed
    AND run.numerical_input_digest=result.input_digest AND result.id=d.result_id AND result.content_digest=d.result_digest
    AND run.assumption_version_id=d.definition_version_id AND run.assumption_digest=d.definition_digest AND a.content_digest=d.definition_digest
    AND run.reporting_currency=d.reporting_currency AND a.reporting_currency=d.reporting_currency
    AND job.state='succeeded' AND job.completed_at IS NOT NULL
    AND EXISTS(SELECT 1 FROM projection_inputs source WHERE source.run_id=root.id AND source.owner_id=root.owner_id AND source.account_id=root.account_id)
    AND EXISTS(SELECT 1 FROM report_input_pins p WHERE p.owner_id=d.owner_id AND p.input_id=d.input_id AND p.kind='projection:policy' AND p.subject_id=a.id AND p.parent_id=a.set_id AND p.content_digest=a.content_digest)
    AND (SELECT count(*) FROM report_input_pins p WHERE p.owner_id=d.owner_id AND p.input_id=d.input_id AND split_part(p.kind,':',1)='goal')=(CASE WHEN run.goal_version_id IS NULL THEN 0 ELSE 1 END)
    AND (run.goal_version_id IS NULL OR EXISTS(SELECT 1 FROM goal_versions g JOIN report_input_pins p ON p.owner_id=g.owner_id AND p.subject_id=g.id
     WHERE g.id=run.goal_version_id AND g.owner_id=run.owner_id AND g.account_id=run.account_id AND g.sealed
      AND g.content_digest=run.goal_digest AND g.assumption_version_id=a.id
      AND p.input_id=i.id AND p.kind='goal:policy' AND p.parent_id=g.goal_id AND p.content_digest=g.content_digest))
  ),false)
$$;

CREATE FUNCTION report_projection_version_valid(p_binding jsonb,p_aggregate uuid,p_version uuid,p_number integer,p_predecessor uuid,p_name text,p_description text,p_digest text,p_created timestamptz)
RETURNS boolean LANGUAGE plpgsql STABLE AS $$
BEGIN
 RETURN COALESCE((p_binding-'created_at')=jsonb_build_object(
  'aggregate_id',p_aggregate,'version_id',p_version,'version_number',p_number,
  'predecessor_id',p_predecessor,'name',p_name,'description',p_description,'content_digest',p_digest)
  AND (p_binding->>'created_at')::timestamptz=p_created,false);
EXCEPTION WHEN data_exception THEN RETURN false;
END $$;

CREATE FUNCTION report_projection_manifest_valid(d report_input_premium_dependencies,i report_input_snapshots)
RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE manifest jsonb; document jsonb; binding jsonb; chosen jsonb; reference jsonb;
 root premium_runs; run projection_runs; result projection_results; job premium_jobs;
 assumption assumption_versions; goal goal_versions; source projection_run_sources;
 source_input uuid; terminal date; cutoff timestamptz; all_cutoffs boolean; source_total integer;
 prefix text; family text; wire_kind text; provider uuid; license uuid; source_refs integer:=0;
BEGIN
 IF NOT report_projection_basis_valid(d,i) OR i.canonical_manifest IS NULL OR octet_length(i.canonical_manifest)=0 THEN RETURN false; END IF;
 manifest:=convert_from(i.canonical_manifest,'UTF8')::jsonb;
 document:=manifest->'document'; binding:=document->'premium_binding'; chosen:=document->'selection';
 SELECT * INTO root FROM premium_runs WHERE id=d.run_id AND owner_id=d.owner_id AND account_id=d.account_id;
 SELECT * INTO run FROM projection_runs WHERE id=root.id AND owner_id=root.owner_id AND account_id=root.account_id;
 SELECT * INTO result FROM projection_results WHERE id=d.result_id AND run_id=root.id AND owner_id=root.owner_id AND account_id=root.account_id;
 SELECT * INTO job FROM premium_jobs WHERE id=result.job_id AND run_id=root.id AND owner_id=root.owner_id AND account_id=root.account_id;
 SELECT * INTO assumption FROM assumption_versions WHERE id=run.assumption_version_id AND owner_id=root.owner_id AND account_id=root.account_id;
 SELECT id INTO source_input FROM projection_inputs WHERE run_id=root.id AND owner_id=root.owner_id AND account_id=root.account_id;
 SELECT "on" INTO terminal FROM projection_calendar_boundaries WHERE run_id=root.id AND owner_id=root.owner_id AND account_id=root.account_id AND month=run.months;
 SELECT count(*),bool_and(value IS NOT NULL),max(value) INTO source_total,all_cutoffs,cutoff FROM (
  SELECT CASE WHEN s.kind='initial_snapshot' THEN snapshot.source_cutoff_at ELSE history.source_cutoff_at END AS value
  FROM projection_run_sources s
  LEFT JOIN portfolio_snapshots snapshot ON snapshot.id=s.subject_id AND snapshot.broker_account_id=root.account_id AND s.kind='initial_snapshot'
  LEFT JOIN historical_input_snapshots history ON history.id=s.subject_id AND history.owner_id=root.owner_id AND history.broker_account_id=root.account_id AND s.kind='calibration'
  WHERE s.owner_id=root.owner_id AND s.account_id=root.account_id AND s.run_id=root.id LIMIT 258
 ) clocks;
 IF source_total<>run.source_count THEN RETURN false; END IF;
 IF source_total=0 OR NOT all_cutoffs THEN cutoff:=NULL; END IF;
 IF document->>'document_schema_version' IS DISTINCT FROM '4.0.0' OR document->>'owner_id' IS DISTINCT FROM root.owner_id::text
  OR (document->>'valuation_at')::timestamptz IS DISTINCT FROM i.valuation_at
  OR chosen->>'profile_version' IS DISTINCT FROM 'report_sections_v4'
  OR chosen->>'account_id' IS DISTINCT FROM root.account_id::text OR chosen->>'snapshot_id' IS DISTINCT FROM i.snapshot_id::text
  OR chosen->>'reporting_currency' IS DISTINCT FROM i.reporting_currency
  OR (chosen->>'source_cutoff_at')::timestamptz IS DISTINCT FROM i.source_cutoff_at
  OR (chosen->>'start_date')::date IS DISTINCT FROM i.start_date OR (chosen->>'end_date')::date IS DISTINCT FROM i.end_date
  OR chosen->'premium_run' IS DISTINCT FROM jsonb_build_object('family','projection','run_id',root.id)
  OR NOT(chosen->'sections' @> '["projection"]'::jsonb)
  OR chosen->'sections' ?| ARRAY['risk','scenario','research'] THEN RETURN false; END IF;
 IF (binding-ARRAY['assumption','goal','observed','report_context','created_at','calculated_at','completed_at','expires_at','source_cutoff_at']) IS DISTINCT FROM jsonb_build_object(
  'root_id',root.id,'run_id',root.id,'input_id',source_input,'result_id',result.id,
  'capture_digest',root.input_digest,'numerical_input_digest',run.numerical_input_digest,'result_digest',result.content_digest,
  'owner_id',root.owner_id,'account_id',root.account_id,'reporting_currency',run.reporting_currency,
  'initial_kind',run.initial_kind,'anchor_date',run.anchor_date,'terminal_date',terminal,
  'months',run.months,'path_count',run.path_count,'retained_point_count',run.retained_point_count,
  'variant_count',run.variant_count,'asset_count',run.asset_count,'source_count',run.source_count,'family','projection','state','succeeded')
  OR (binding->>'created_at')::timestamptz IS DISTINCT FROM root.created_at
  OR (binding->>'calculated_at')::timestamptz IS DISTINCT FROM result.created_at
  OR (binding->>'completed_at')::timestamptz IS DISTINCT FROM job.completed_at
  OR (binding->>'expires_at')::timestamptz IS DISTINCT FROM root.expires_at
  OR NOT(binding ? 'source_cutoff_at') OR (binding->>'source_cutoff_at')::timestamptz IS DISTINCT FROM cutoff
  OR NOT report_projection_version_valid(binding->'assumption',assumption.set_id,assumption.id,assumption.version_number,assumption.predecessor_id,assumption.name,assumption.description,assumption.content_digest,assumption.created_at)
 THEN RETURN false; END IF;
 IF run.goal_version_id IS NULL THEN
  IF binding->'goal' IS DISTINCT FROM 'null'::jsonb OR chosen->'sections' ? 'goal' THEN RETURN false; END IF;
 ELSE
  SELECT * INTO goal FROM goal_versions WHERE id=run.goal_version_id AND owner_id=root.owner_id AND account_id=root.account_id;
  IF NOT report_projection_version_valid(binding->'goal',goal.goal_id,goal.id,goal.version_number,goal.predecessor_id,goal.name,goal.description,goal.content_digest,goal.created_at) THEN RETURN false; END IF;
 END IF;
 IF run.snapshot_id IS NULL THEN
  IF binding->'observed' IS DISTINCT FROM 'null'::jsonb THEN RETURN false; END IF;
 ELSIF ((binding->'observed')-'valuation_at') IS DISTINCT FROM jsonb_build_object('snapshot_id',run.snapshot_id,'snapshot_digest',run.snapshot_digest)
  OR (binding->'observed'->>'valuation_at')::timestamptz IS DISTINCT FROM run.snapshot_valuation_at THEN RETURN false; END IF;
 IF ((binding->'report_context')-ARRAY['valuation_at','source_cutoff_at']) IS DISTINCT FROM jsonb_build_object('snapshot_id',d.snapshot_id,'snapshot_digest',d.snapshot_digest)
  OR (binding->'report_context'->>'valuation_at')::timestamptz IS DISTINCT FROM d.valuation_at
  OR (binding->'report_context'->>'source_cutoff_at')::timestamptz IS DISTINCT FROM d.source_cutoff_at THEN RETURN false; END IF;
 IF jsonb_typeof(manifest->'source_references') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 prefix:='projection.'||root.id::text||'.source.';
 FOR source IN SELECT * FROM projection_run_sources WHERE owner_id=root.owner_id AND account_id=root.account_id AND run_id=root.id ORDER BY id LIMIT 258 LOOP
  provider:=NULL; license:=NULL;
  IF source.kind='initial_snapshot' THEN family:='portfolio_snapshot'; wire_kind:='portfolio_snapshot';
  ELSIF EXISTS(SELECT 1 FROM historical_input_snapshots WHERE owner_id=root.owner_id AND broker_account_id=root.account_id AND id=source.subject_id) THEN family:='historical_input'; wire_kind:='historical_input';
  ELSE
   SELECT provider_id,license_version_id INTO provider,license FROM price_snapshots WHERE owner_id=root.owner_id AND id=source.subject_id;
   IF FOUND THEN family:='price_total_return'; wire_kind:='price_snapshot';
   ELSE
    SELECT provider_id,license_version_id INTO provider,license FROM benchmark_snapshots WHERE owner_id=root.owner_id AND id=source.subject_id;
    family:='benchmark_total_return'; wire_kind:='benchmark';
   END IF;
  END IF;
  SELECT value INTO reference FROM jsonb_array_elements(manifest->'source_references') WHERE value->>'key'=prefix||family||'.'||source.subject_id::text;
  IF reference IS NULL OR reference->>'kind' IS DISTINCT FROM wire_kind OR reference->>'subject_id' IS DISTINCT FROM source.subject_id::text
   OR reference->>'content_digest' IS DISTINCT FROM source.content_digest OR reference->>'provider_id' IS DISTINCT FROM provider::text
   OR reference->>'license_version_id' IS DISTINCT FROM license::text THEN RETURN false; END IF;
  source_refs:=source_refs+1;
 END LOOP;
 IF (SELECT count(*) FROM jsonb_array_elements(manifest->'source_references') ref WHERE starts_with(ref->>'key',prefix))<>source_refs THEN RETURN false; END IF;
 RETURN true;
EXCEPTION WHEN data_exception OR cardinality_violation THEN RETURN false;
END $$;

CREATE FUNCTION report_projection_restricted(p_owner uuid,p_input uuid,p_at timestamptz)
RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE dependency report_input_premium_dependencies; capture report_input_snapshots;
BEGIN
 SELECT * INTO dependency FROM report_input_premium_dependencies WHERE owner_id=p_owner AND input_id=p_input;
 IF dependency.id IS NULL OR dependency.kind<>'projection' OR dependency.expires_at<=p_at
  OR dependency.expires_at<=dependency.created_at OR dependency.source_cutoff_at>p_at
  OR NOT EXISTS(SELECT 1 FROM premium_runs r WHERE r.id=dependency.run_id AND r.owner_id=p_owner
   AND r.account_id=dependency.account_id AND r.kind='projection' AND r.input_digest=dependency.input_digest
   AND dependency.expires_at<=r.expires_at) THEN RETURN true; END IF;
 -- Authorize the entire original lineage before selecting or decoding private
 -- report bytes. The maintenance continuation is deliberately not consulted.
 IF projection_report_sources_restricted(dependency.run_id,p_at) THEN RETURN true; END IF;
 -- The existing fixed helper's risk/scenario parent branches are inactive for
 -- projection. Its common report physical inventory and copied-licence checks
 -- remain exactly the same, including current REPORT and original copy bounds.
 IF report_premium_v3_sources_restricted(p_owner,p_input,dependency.run_id,'projection',p_at) THEN RETURN true; END IF;
 SELECT * INTO capture FROM report_input_snapshots WHERE owner_id=p_owner AND account_id=dependency.account_id AND id=p_input;
 RETURN capture.id IS NULL OR capture.contract_version<>4 OR capture.purged_at IS NOT NULL
  OR capture.expires_at<=p_at OR NOT report_projection_manifest_valid(dependency,capture);
END $$;
"""

_GUARDS = r"""
CREATE OR REPLACE FUNCTION report_premium_restricted(p_owner uuid, p_input uuid, p_at timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT COALESCE((SELECT CASE
  WHEN i.contract_version IN (1,2) THEN report_premium_restricted_v2(p_owner,p_input,p_at)
  WHEN i.contract_version=3 THEN
   (SELECT count(*) FROM report_input_premium_dependencies d WHERE d.owner_id=i.owner_id AND d.account_id=i.account_id AND d.input_id=i.id)<>1
   OR EXISTS(SELECT 1 FROM report_input_premium_dependencies d
    LEFT JOIN premium_runs root ON root.owner_id=d.owner_id AND root.account_id=d.account_id AND root.id=d.run_id
    WHERE d.owner_id=i.owner_id AND d.input_id=i.id AND (
     NOT report_premium_v3_basis_valid(d,i)
     OR root.kind IS DISTINCT FROM d.kind OR root.input_digest IS DISTINCT FROM d.input_digest
     OR d.expires_at>root.expires_at OR d.expires_at<=d.created_at OR d.expires_at<=p_at OR root.expires_at<=p_at
     OR EXISTS(SELECT 1 FROM premium_retention_events e WHERE e.owner_id=d.owner_id AND e.run_id=d.run_id)
     OR report_premium_v3_sources_restricted(d.owner_id,d.input_id,d.run_id,d.kind,p_at)))
  WHEN i.contract_version=4 THEN report_projection_restricted(p_owner,p_input,p_at)
  ELSE true END FROM report_input_snapshots i WHERE i.owner_id=p_owner AND i.id=p_input),true)
$$;

CREATE OR REPLACE FUNCTION report_premium_dependency_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE inp report_input_snapshots;
BEGIN
 IF TG_OP='UPDATE' AND (to_jsonb(NEW)-'copy_pending')=(to_jsonb(OLD)-'copy_pending') THEN
  IF OLD.copy_pending IS NULL AND NEW.copy_pending IS NOT NULL
   AND NEW.copy_pending=report_capture_pending(OLD.owner_id,OLD.input_id) THEN RETURN NEW; END IF;
  IF pg_trigger_depth()>1 AND OLD.copy_pending AND NOT NEW.copy_pending AND EXISTS(
   SELECT 1 FROM report_retention_work WHERE owner_id=OLD.owner_id AND input_id=OLD.input_id AND completed_at IS NOT NULL)
  THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Premium report lineage is immutable' USING ERRCODE='23514'; END IF;
 IF NEW.copy_pending IS DISTINCT FROM true THEN RAISE EXCEPTION 'Premium report copy must begin pending' USING ERRCODE='23514'; END IF;
 PERFORM id FROM premium_runs WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.run_id FOR UPDATE;
 SELECT * INTO inp FROM report_input_snapshots WHERE id=NEW.input_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
 IF inp.contract_version NOT IN (2,3,4) OR inp.id IS NULL OR inp.sealed_at IS NOT NULL OR inp.purged_at IS NOT NULL THEN
  RAISE EXCEPTION 'Premium report capture is not open' USING ERRCODE='23514'; END IF;
 IF inp.contract_version=2 THEN
  IF num_nonnulls(NEW.result_id,NEW.definition_version_id,NEW.definition_digest,NEW.snapshot_id,NEW.snapshot_digest,NEW.reporting_currency,NEW.source_cutoff_at,NEW.valuation_at)<>0 OR NOT EXISTS (
   SELECT 1 FROM premium_runs r JOIN risk_runs rr ON rr.owner_id=r.owner_id AND rr.account_id=r.account_id AND rr.id=r.id
   JOIN risk_results result ON result.owner_id=r.owner_id AND result.account_id=r.account_id AND result.run_id=r.id
   JOIN premium_jobs j ON j.owner_id=r.owner_id AND j.account_id=r.account_id AND j.run_id=r.id
   WHERE r.owner_id=NEW.owner_id AND r.account_id=NEW.account_id AND r.id=NEW.run_id
     AND r.kind=NEW.kind AND rr.sealed AND result.sealed AND j.state='succeeded'
     AND r.input_digest=NEW.input_digest AND result.content_digest=NEW.result_digest
     AND NEW.expires_at<=r.expires_at AND NEW.expires_at>NEW.created_at AND NEW.expires_at>CURRENT_TIMESTAMP
     AND NOT EXISTS (SELECT 1 FROM premium_retention_events e WHERE e.owner_id=r.owner_id AND e.run_id=r.id)
  ) THEN RAISE EXCEPTION 'Premium report source binding mismatch' USING ERRCODE='23514'; END IF;
 ELSIF inp.contract_version=3 THEN
  IF NOT report_premium_v3_basis_valid(NEW,inp) OR NOT EXISTS(
   SELECT 1 FROM premium_runs r WHERE r.id=NEW.run_id AND r.owner_id=NEW.owner_id AND r.account_id=NEW.account_id
    AND r.kind=NEW.kind AND r.input_digest=NEW.input_digest AND NEW.expires_at<=r.expires_at
    AND NEW.expires_at>NEW.created_at AND NEW.expires_at>CURRENT_TIMESTAMP
    AND NOT EXISTS(SELECT 1 FROM premium_retention_events e WHERE e.owner_id=r.owner_id AND e.run_id=r.id)
  ) THEN RAISE EXCEPTION 'Third-profile source binding mismatch' USING ERRCODE='23514'; END IF;
 ELSE
  IF NOT report_projection_basis_valid(NEW,inp) OR projection_report_sources_restricted(NEW.run_id,clock_timestamp())
   OR NEW.expires_at<=NEW.created_at OR NEW.expires_at<=clock_timestamp()
   OR NOT EXISTS(SELECT 1 FROM premium_runs r WHERE r.id=NEW.run_id AND r.owner_id=NEW.owner_id
    AND r.account_id=NEW.account_id AND NEW.expires_at<=r.expires_at)
  THEN RAISE EXCEPTION 'Projection report source binding mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION report_premium_capture_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version integer; deadline timestamptz; purged timestamptz; dependencies bigint;
BEGIN
 SELECT contract_version,expires_at,purged_at INTO version,deadline,purged FROM report_input_snapshots WHERE id=NEW.id AND owner_id=NEW.owner_id;
 SELECT count(*) INTO dependencies FROM report_input_premium_dependencies WHERE owner_id=NEW.owner_id AND input_id=NEW.id;
 IF (version=1 AND dependencies<>0) OR (version IN (2,3,4) AND dependencies<>1) THEN
  RAISE EXCEPTION 'Report contract lineage mismatch' USING ERRCODE='23514'; END IF;
 IF version IN (2,3,4) AND (EXISTS(SELECT 1 FROM report_input_premium_dependencies WHERE input_id=NEW.id AND expires_at<deadline)
   OR (purged IS NULL AND report_premium_restricted(NEW.owner_id,NEW.id,CURRENT_TIMESTAMP))) THEN
  RAISE EXCEPTION 'Premium report source is unavailable' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION report_command_contract_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version integer;
BEGIN
 IF NEW.command NOT IN ('reports.generate.v1','reports.generate.v2') THEN RETURN NEW; END IF;
 SELECT contract_version INTO version FROM report_jobs WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.report_job_id;
 IF version IS NULL OR (NEW.command='reports.generate.v1' AND version<>1) OR (NEW.command='reports.generate.v2' AND version NOT IN (2,3,4)) THEN
  RAISE EXCEPTION 'Report command contract mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION report_premium_copy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE selected_owner uuid; selected_run uuid;
BEGIN
 -- Financial row triggers may already hold that tuple; never wait for an owner
 -- whose normal purge holds its locks and is about to remove the same tuple.
 IF TG_TABLE_NAME LIKE 'projection_%' OR TG_TABLE_NAME IN ('scenario_run_payloads','scenario_results','scenario_components','scenario_applied_sensitivities') THEN
  IF NOT pg_try_advisory_xact_lock(hashtextextended('sources:'||OLD.owner_id::text,0)) THEN
   RAISE EXCEPTION 'Premium report source owner is busy' USING ERRCODE='55P03'; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_retention_events' THEN
  selected_owner:=NEW.owner_id; selected_run:=NEW.run_id;
  PERFORM id FROM premium_runs WHERE owner_id=selected_owner AND id=selected_run FOR UPDATE;
  IF NEW.completed_at IS NULL THEN RETURN NEW; END IF;
 ELSIF TG_TABLE_NAME='premium_runs' THEN
  IF TG_OP='UPDATE' AND NEW.retained_bytes>=OLD.retained_bytes AND NEW.reserved_bytes>=OLD.reserved_bytes THEN RETURN NEW; END IF;
  selected_owner:=OLD.owner_id; selected_run:=OLD.id;
 ELSIF TG_TABLE_NAME IN ('risk_run_assets','risk_results','scenario_run_payloads','scenario_results',
  'projection_inputs','projection_run_allocations','projection_calendar_boundaries','projection_run_pauses',
  'projection_run_schedule_entries','projection_source_proofs','projection_chunks','projection_paths',
  'projection_points','projection_point_assets','projection_results') THEN
  selected_owner:=OLD.owner_id; selected_run:=OLD.run_id;
 ELSIF TG_TABLE_NAME IN ('scenario_components','scenario_applied_sensitivities') THEN
  selected_owner:=OLD.owner_id;
  SELECT run_id INTO selected_run FROM scenario_results WHERE owner_id=selected_owner AND id=OLD.result_id;
 ELSIF TG_TABLE_NAME IN ('projection_zero_pivots','projection_distributions','projection_histograms','projection_goal_analyses') THEN
  selected_owner:=OLD.owner_id;
  SELECT run_id INTO selected_run FROM projection_results WHERE owner_id=selected_owner AND account_id=OLD.account_id AND id=OLD.result_id;
 ELSIF TG_TABLE_NAME='projection_distribution_quantiles' THEN
  selected_owner:=OLD.owner_id;
  SELECT r.run_id INTO selected_run FROM projection_distributions d JOIN projection_results r ON r.id=d.result_id AND r.owner_id=d.owner_id AND r.account_id=d.account_id
   WHERE d.owner_id=selected_owner AND d.account_id=OLD.account_id AND d.id=OLD.distribution_id;
 ELSIF TG_TABLE_NAME='projection_histogram_bins' THEN
  selected_owner:=OLD.owner_id;
  SELECT r.run_id INTO selected_run FROM projection_histograms h JOIN projection_results r ON r.id=h.result_id AND r.owner_id=h.owner_id AND r.account_id=h.account_id
   WHERE h.owner_id=selected_owner AND h.account_id=OLD.account_id AND h.id=OLD.histogram_id;
 ELSIF TG_TABLE_NAME='projection_goal_shortfall_quantiles' THEN
  selected_owner:=OLD.owner_id;
  SELECT r.run_id INTO selected_run FROM projection_goal_analyses g JOIN projection_results r ON r.id=g.result_id AND r.owner_id=g.owner_id AND r.account_id=g.account_id
   WHERE g.owner_id=selected_owner AND g.account_id=OLD.account_id AND g.id=OLD.analysis_id;
 ELSE
  selected_owner:=OLD.owner_id;
  SELECT run_id INTO selected_run FROM risk_results WHERE owner_id=selected_owner AND id=OLD.result_id;
 END IF;
 PERFORM id FROM premium_runs WHERE owner_id=selected_owner AND id=selected_run FOR UPDATE;
 IF EXISTS(SELECT 1 FROM report_input_premium_dependencies d WHERE d.owner_id=selected_owner AND d.run_id=selected_run AND d.copy_pending) THEN
  RAISE EXCEPTION 'Premium report copies remain' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION scenario_source_copy_pending(p_version uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM scenario_run_sensitivity_versions v WHERE v.version_id=p_version AND (
  scenario_run_has_payload(v.run_id) OR EXISTS(SELECT 1 FROM report_input_premium_dependencies d WHERE d.owner_id=v.owner_id AND d.run_id=v.run_id AND d.copy_pending)))
$$;
"""

_PARENT_COPIES = r"""
CREATE OR REPLACE FUNCTION projection_parent_has_copies(p_owner uuid,p_kind text,p_id uuid)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM projection_retained_source_memberships
 WHERE owner_id=p_owner AND source_kind=p_kind AND source_id=p_id)
$$;
"""

_PREVIOUS_GUARDS = r"""
CREATE OR REPLACE FUNCTION report_premium_restricted(p_owner uuid, p_input uuid, p_at timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT COALESCE((SELECT CASE
  WHEN i.contract_version IN (1,2) THEN report_premium_restricted_v2(p_owner,p_input,p_at)
  WHEN i.contract_version=3 THEN
   (SELECT count(*) FROM report_input_premium_dependencies d WHERE d.owner_id=i.owner_id AND d.account_id=i.account_id AND d.input_id=i.id)<>1
   OR EXISTS(SELECT 1 FROM report_input_premium_dependencies d
    LEFT JOIN premium_runs root ON root.owner_id=d.owner_id AND root.account_id=d.account_id AND root.id=d.run_id
    WHERE d.owner_id=i.owner_id AND d.input_id=i.id AND (
     NOT report_premium_v3_basis_valid(d,i)
     OR root.kind IS DISTINCT FROM d.kind OR root.input_digest IS DISTINCT FROM d.input_digest
     OR d.expires_at>root.expires_at OR d.expires_at<=d.created_at OR d.expires_at<=p_at OR root.expires_at<=p_at
     OR EXISTS(SELECT 1 FROM premium_retention_events e WHERE e.owner_id=d.owner_id AND e.run_id=d.run_id)
     OR report_premium_v3_sources_restricted(d.owner_id,d.input_id,d.run_id,d.kind,p_at)))
  ELSE true END FROM report_input_snapshots i WHERE i.owner_id=p_owner AND i.id=p_input),true)
$$;

CREATE OR REPLACE FUNCTION report_premium_dependency_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE inp report_input_snapshots;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Premium report lineage is immutable' USING ERRCODE='23514'; END IF;
 PERFORM id FROM premium_runs WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.run_id FOR UPDATE;
 SELECT * INTO inp FROM report_input_snapshots WHERE id=NEW.input_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
 IF inp.contract_version NOT IN (2,3) OR inp.id IS NULL OR inp.sealed_at IS NOT NULL OR inp.purged_at IS NOT NULL THEN
  RAISE EXCEPTION 'Premium report capture is not open' USING ERRCODE='23514'; END IF;
 IF inp.contract_version=2 THEN
  IF num_nonnulls(NEW.result_id,NEW.definition_version_id,NEW.definition_digest,NEW.snapshot_id,NEW.snapshot_digest,NEW.reporting_currency,NEW.source_cutoff_at,NEW.valuation_at)<>0 OR NOT EXISTS (
   SELECT 1 FROM premium_runs r JOIN risk_runs rr ON rr.owner_id=r.owner_id AND rr.account_id=r.account_id AND rr.id=r.id
   JOIN risk_results result ON result.owner_id=r.owner_id AND result.account_id=r.account_id AND result.run_id=r.id
   JOIN premium_jobs j ON j.owner_id=r.owner_id AND j.account_id=r.account_id AND j.run_id=r.id
   WHERE r.owner_id=NEW.owner_id AND r.account_id=NEW.account_id AND r.id=NEW.run_id
     AND r.kind=NEW.kind AND rr.sealed AND result.sealed AND j.state='succeeded'
     AND r.input_digest=NEW.input_digest AND result.content_digest=NEW.result_digest
     AND NEW.expires_at<=r.expires_at AND NEW.expires_at>NEW.created_at AND NEW.expires_at>CURRENT_TIMESTAMP
     AND NOT EXISTS (SELECT 1 FROM premium_retention_events e WHERE e.owner_id=r.owner_id AND e.run_id=r.id)
  ) THEN RAISE EXCEPTION 'Premium report source binding mismatch' USING ERRCODE='23514'; END IF;
 ELSE
  IF NOT report_premium_v3_basis_valid(NEW,inp) OR NOT EXISTS(
   SELECT 1 FROM premium_runs r WHERE r.id=NEW.run_id AND r.owner_id=NEW.owner_id AND r.account_id=NEW.account_id
    AND r.kind=NEW.kind AND r.input_digest=NEW.input_digest AND NEW.expires_at<=r.expires_at
    AND NEW.expires_at>NEW.created_at AND NEW.expires_at>CURRENT_TIMESTAMP
    AND NOT EXISTS(SELECT 1 FROM premium_retention_events e WHERE e.owner_id=r.owner_id AND e.run_id=r.id)
  ) THEN RAISE EXCEPTION 'Third-profile source binding mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION report_premium_capture_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version integer; deadline timestamptz; purged timestamptz; dependencies bigint;
BEGIN
 SELECT contract_version,expires_at,purged_at INTO version,deadline,purged FROM report_input_snapshots WHERE id=NEW.id AND owner_id=NEW.owner_id;
 SELECT count(*) INTO dependencies FROM report_input_premium_dependencies WHERE owner_id=NEW.owner_id AND input_id=NEW.id;
 IF (version=1 AND dependencies<>0) OR (version IN (2,3) AND dependencies<>1) THEN
  RAISE EXCEPTION 'Report contract lineage mismatch' USING ERRCODE='23514'; END IF;
 IF version IN (2,3) AND (EXISTS(SELECT 1 FROM report_input_premium_dependencies WHERE input_id=NEW.id AND expires_at<deadline)
   OR (purged IS NULL AND report_premium_restricted(NEW.owner_id,NEW.id,CURRENT_TIMESTAMP))) THEN
  RAISE EXCEPTION 'Premium report source is unavailable' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION report_command_contract_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version integer;
BEGIN
 IF NEW.command NOT IN ('reports.generate.v1','reports.generate.v2') THEN RETURN NEW; END IF;
 SELECT contract_version INTO version FROM report_jobs WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.report_job_id;
 IF version IS NULL OR (NEW.command='reports.generate.v1' AND version<>1) OR (NEW.command='reports.generate.v2' AND version NOT IN (2,3)) THEN
  RAISE EXCEPTION 'Report command contract mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION report_premium_copy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner uuid; run uuid;
BEGIN
 -- Direct financial DELETE/UPDATE already holds the target row. Do not wait
 -- on an owner whose normal cleanup may need that row while holding the root.
 IF TG_TABLE_NAME IN ('scenario_run_payloads','scenario_results','scenario_components','scenario_applied_sensitivities') THEN
  IF NOT pg_try_advisory_xact_lock(hashtextextended('sources:'||OLD.owner_id::text,0)) THEN
   RAISE EXCEPTION 'Scenario report source owner is busy' USING ERRCODE='55P03'; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_retention_events' THEN
  owner:=NEW.owner_id; run:=NEW.run_id;
  PERFORM id FROM premium_runs WHERE owner_id=owner AND id=run FOR UPDATE;
  IF NEW.completed_at IS NULL THEN RETURN NEW; END IF;
 ELSIF TG_TABLE_NAME='premium_runs' THEN
  IF TG_OP='UPDATE' AND NEW.retained_bytes>=OLD.retained_bytes AND NEW.reserved_bytes>=OLD.reserved_bytes THEN RETURN NEW; END IF;
  owner:=OLD.owner_id; run:=OLD.id;
 ELSIF TG_TABLE_NAME IN ('risk_run_assets','risk_results','scenario_run_payloads','scenario_results') THEN
  owner:=OLD.owner_id; run:=OLD.run_id;
 ELSIF TG_TABLE_NAME IN ('scenario_components','scenario_applied_sensitivities') THEN
  owner:=OLD.owner_id;
  SELECT run_id INTO run FROM scenario_results WHERE owner_id=owner AND id=OLD.result_id;
 ELSE
  owner:=OLD.owner_id;
  SELECT run_id INTO run FROM risk_results WHERE owner_id=owner AND id=OLD.result_id;
 END IF;
 PERFORM id FROM premium_runs WHERE owner_id=owner AND id=run FOR UPDATE;
 IF EXISTS(SELECT 1 FROM report_input_premium_dependencies d WHERE d.owner_id=owner AND d.run_id=run AND report_capture_pending(d.owner_id,d.input_id)) THEN
  RAISE EXCEPTION 'Premium report copies remain' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION scenario_source_copy_pending(p_version uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM scenario_run_sensitivity_versions v WHERE v.version_id=p_version AND (
  scenario_run_has_payload(v.run_id) OR EXISTS(SELECT 1 FROM report_input_premium_dependencies d WHERE d.owner_id=v.owner_id AND d.run_id=v.run_id AND report_capture_pending(d.owner_id,d.input_id))))
$$;
"""

_PREVIOUS_PARENT_COPIES = r"""
CREATE OR REPLACE FUNCTION projection_parent_has_copies(p_owner uuid,p_kind text,p_id uuid)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM projection_retained_source_memberships
 WHERE owner_id=p_owner AND source_kind=p_kind AND source_id=p_id)
$$;
"""

_PENDING_GUARDS = r"""
CREATE OR REPLACE FUNCTION report_capture_pending(p_owner uuid,p_input uuid) RETURNS boolean
LANGUAGE plpgsql STABLE AS $$
DECLARE selected_job uuid; artifact uuid;
BEGIN
 IF EXISTS(SELECT 1 FROM report_input_snapshots WHERE owner_id=p_owner AND id=p_input
  AND (canonical_manifest IS NOT NULL OR canonical_context IS NOT NULL))
 OR EXISTS(SELECT 1 FROM report_input_chunks WHERE owner_id=p_owner AND input_id=p_input AND payload IS NOT NULL)
 OR EXISTS(SELECT 1 FROM report_manifests WHERE owner_id=p_owner AND input_id=p_input AND payload IS NOT NULL)
 OR EXISTS(SELECT 1 FROM export_manifests WHERE owner_id=p_owner AND input_id=p_input AND payload IS NOT NULL) THEN RETURN true; END IF;
 -- Each input has at most one report job and one export job (unique FKs).
 -- Each job has at most four immutable format identities. Pending payload
 -- indices and grant prefix probes do not walk already-purged chunk histories.
 SELECT id INTO selected_job FROM report_jobs WHERE owner_id=p_owner AND input_id=p_input;
 IF selected_job IS NOT NULL THEN
  IF EXISTS(SELECT 1 FROM report_artifacts WHERE owner_id=p_owner AND job_id=selected_job AND contents IS NOT NULL) THEN RETURN true; END IF;
  FOR artifact IN SELECT id FROM report_artifacts WHERE owner_id=p_owner AND job_id=selected_job LOOP
   IF EXISTS(SELECT 1 FROM artifact_download_grants WHERE owner_id=p_owner AND report_artifact_id=artifact) THEN RETURN true; END IF;
  END LOOP;
 END IF;
 SELECT id INTO selected_job FROM export_jobs WHERE owner_id=p_owner AND input_id=p_input;
 IF selected_job IS NOT NULL THEN
  IF EXISTS(SELECT 1 FROM export_artifacts WHERE owner_id=p_owner AND job_id=selected_job AND contents IS NOT NULL) THEN RETURN true; END IF;
  FOR artifact IN SELECT id FROM export_artifacts WHERE owner_id=p_owner AND job_id=selected_job LOOP
   IF EXISTS(SELECT 1 FROM artifact_download_grants WHERE owner_id=p_owner AND export_artifact_id=artifact) THEN RETURN true; END IF;
  END LOOP;
 END IF;
 RETURN false;
END $$;

CREATE FUNCTION report_premium_copy_finished() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 -- report_retention_authorized has independently rejected any remaining copies
 -- before this AFTER trigger can run. This is the only normal false transition.
 IF OLD.completed_at IS NULL AND NEW.completed_at IS NOT NULL THEN
  UPDATE report_input_premium_dependencies SET copy_pending=false
   WHERE owner_id=NEW.owner_id AND input_id=NEW.input_id AND copy_pending;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION report_premium_purge_authorized(p_owner uuid,p_input uuid)
RETURNS boolean LANGUAGE plpgsql VOLATILE AS $$
DECLARE dependency report_input_premium_dependencies;
BEGIN
 SELECT * INTO dependency FROM report_input_premium_dependencies WHERE owner_id=p_owner AND input_id=p_input;
 IF dependency.id IS NULL THEN RETURN false; END IF;
 PERFORM id FROM premium_runs WHERE owner_id=dependency.owner_id AND account_id=dependency.account_id AND id=dependency.run_id FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 RETURN EXISTS(SELECT 1 FROM premium_runs WHERE owner_id=dependency.owner_id AND account_id=dependency.account_id AND id=dependency.run_id AND expires_at<=clock_timestamp())
 OR EXISTS(SELECT 1 FROM premium_retention_events WHERE owner_id=dependency.owner_id
  AND account_id=dependency.account_id AND run_id=dependency.run_id);
END $$;
"""

_RETENTION_GUARD = r"""
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

_PREVIOUS_REPORT_RETENTION = r"""
CREATE OR REPLACE FUNCTION report_retention_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE inp report_input_snapshots;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Report retention records are immutable'; END IF;
 SELECT * INTO inp FROM report_input_snapshots WHERE owner_id=NEW.owner_id AND id=NEW.input_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Report retention input is absent'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'Retention must start pending'; END IF;
  IF NEW.reason='ttl' AND inp.expires_at>CURRENT_TIMESTAMP THEN RAISE EXCEPTION 'Report has not expired'; END IF;
  IF NEW.reason='source' AND NOT report_premium_restricted(NEW.owner_id,NEW.input_id,CURRENT_TIMESTAMP) AND NOT EXISTS (
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

_PREVIOUS_REPORT_PENDING = r"""
CREATE OR REPLACE FUNCTION report_capture_pending(p_owner uuid, p_input uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
 SELECT EXISTS (SELECT 1 FROM report_input_snapshots WHERE owner_id=p_owner AND id=p_input
   AND (canonical_manifest IS NOT NULL OR canonical_context IS NOT NULL))
 OR EXISTS (SELECT 1 FROM report_input_chunks WHERE owner_id=p_owner AND input_id=p_input AND payload IS NOT NULL)
 OR EXISTS (SELECT 1 FROM report_manifests WHERE owner_id=p_owner AND input_id=p_input AND payload IS NOT NULL)
 OR EXISTS (SELECT 1 FROM export_manifests WHERE owner_id=p_owner AND input_id=p_input AND payload IS NOT NULL)
 OR EXISTS (SELECT 1 FROM report_artifacts a JOIN report_jobs j ON j.id=a.job_id AND j.owner_id=a.owner_id
   WHERE j.owner_id=p_owner AND j.input_id=p_input AND a.contents IS NOT NULL)
 OR EXISTS (SELECT 1 FROM export_artifacts a JOIN export_jobs j ON j.id=a.job_id AND j.owner_id=a.owner_id
   WHERE j.owner_id=p_owner AND j.input_id=p_input AND a.contents IS NOT NULL)
 OR EXISTS (SELECT 1 FROM artifact_download_grants g JOIN report_artifacts a ON a.id=g.report_artifact_id
   JOIN report_jobs j ON j.id=a.job_id WHERE g.owner_id=p_owner AND j.input_id=p_input)
 OR EXISTS (SELECT 1 FROM artifact_download_grants g JOIN export_artifacts a ON a.id=g.export_artifact_id
   JOIN export_jobs j ON j.id=a.job_id WHERE g.owner_id=p_owner AND j.input_id=p_input)
$$;
"""

_WITNESS_GUARD = r"""
CREATE FUNCTION report_projection_witness_restricted(p_owner uuid,p_input uuid,p_kind text,p_source uuid,p_at timestamptz)
RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE dependency report_input_premium_dependencies; original timestamptz; pinned_id uuid;
 physical_expiry timestamptz; physical_created timestamptz; physical_sealed boolean;
 pinned provider_license_versions; current_license provider_license_versions;
BEGIN
 IF p_kind NOT IN ('price','fx','corporate_action','benchmark','historical','license','classification') OR p_source IS NULL OR p_at IS NULL THEN RETURN false; END IF;
 SELECT * INTO dependency FROM report_input_premium_dependencies WHERE owner_id=p_owner AND input_id=p_input AND kind='projection';
 IF dependency.id IS NULL THEN RETURN false; END IF;
 -- This relation is immutable financial provenance, populated from the complete
 -- authorized source proof and independently checked against original lineage at
 -- projection seal. A mutable maintenance scan cannot manufacture this origin.
 SELECT original_created_at INTO original FROM projection_retained_source_memberships
 WHERE owner_id=p_owner AND account_id=dependency.account_id AND run_id=dependency.run_id
  AND source_kind=p_kind AND source_id=p_source;
 IF original IS NULL THEN RETURN false; END IF;
 IF p_kind='historical' THEN
  SELECT h.created_at,h.sealed INTO physical_created,physical_sealed FROM historical_input_snapshots h
   WHERE h.owner_id=p_owner AND h.broker_account_id=dependency.account_id AND h.id=p_source;
  RETURN physical_created IS NULL OR NOT physical_sealed OR physical_created>p_at
   OR EXISTS(SELECT 1 FROM premium_runs r WHERE r.owner_id=p_owner AND r.account_id=dependency.account_id AND r.id=dependency.run_id AND r.created_at+interval '30 days'<=p_at)
   OR EXISTS(SELECT 1 FROM historical_retention_events WHERE owner_id=p_owner AND input_id=p_source);
 ELSIF p_kind='license' THEN
  pinned_id:=p_source;
 ELSIF p_kind='classification' THEN
  SELECT license_version_id,created_at INTO pinned_id,physical_created FROM historical_classification_evidence
   WHERE owner_id=p_owner AND id=p_source;
  IF pinned_id IS NULL OR physical_created>p_at THEN RETURN true; END IF;
 ELSE
  SELECT h.license_version_id,h.created_at,h.expires_at INTO pinned_id,physical_created,physical_expiry FROM (
   SELECT license_version_id,created_at,expires_at FROM price_snapshots WHERE p_kind='price' AND owner_id=p_owner AND id=p_source
   UNION ALL SELECT license_version_id,created_at,expires_at FROM fx_snapshots WHERE p_kind='fx' AND owner_id=p_owner AND id=p_source
   UNION ALL SELECT license_version_id,created_at,expires_at FROM corporate_action_snapshots WHERE p_kind='corporate_action' AND owner_id=p_owner AND id=p_source
   UNION ALL SELECT license_version_id,created_at,expires_at FROM benchmark_snapshots WHERE p_kind='benchmark' AND owner_id=p_owner AND id=p_source
  ) h;
  IF pinned_id IS NULL OR physical_created>p_at OR physical_expiry<=p_at THEN RETURN true; END IF;
  IF EXISTS(
   SELECT id FROM source_retention_work WHERE p_kind='price' AND owner_id=p_owner AND price_snapshot_id=p_source
   UNION ALL SELECT id FROM source_retention_work WHERE p_kind='fx' AND owner_id=p_owner AND fx_snapshot_id=p_source
   UNION ALL SELECT id FROM source_retention_work WHERE p_kind='corporate_action' AND owner_id=p_owner AND corporate_action_snapshot_id=p_source
   UNION ALL SELECT id FROM source_retention_work WHERE p_kind='benchmark' AND owner_id=p_owner AND benchmark_snapshot_id=p_source
   UNION ALL SELECT id FROM source_expiry_events WHERE p_kind='price' AND owner_id=p_owner AND price_snapshot_id=p_source
   UNION ALL SELECT id FROM source_expiry_events WHERE p_kind='fx' AND owner_id=p_owner AND fx_snapshot_id=p_source
   UNION ALL SELECT id FROM source_expiry_events WHERE p_kind='corporate_action' AND owner_id=p_owner AND corporate_action_snapshot_id=p_source
   UNION ALL SELECT id FROM source_expiry_events WHERE p_kind='benchmark' AND owner_id=p_owner AND benchmark_snapshot_id=p_source
  ) THEN RETURN true; END IF;
 END IF;
 SELECT * INTO pinned FROM provider_license_versions WHERE owner_id=p_owner AND id=pinned_id;
 IF pinned.id IS NULL OR pinned.effective_at>p_at OR pinned.store_permission<>'allowed'
  OR pinned.display_permission<>'allowed' OR pinned.report_permission<>'allowed' OR pinned.retention_days IS NULL THEN RETURN true; END IF;
 SELECT * INTO current_license FROM provider_license_versions WHERE owner_id=p_owner AND provider_id=pinned.provider_id AND effective_at<=p_at
  ORDER BY effective_at DESC,version_number DESC,id DESC LIMIT 1;
 RETURN current_license.id IS NULL OR current_license.store_permission<>'allowed'
  OR current_license.display_permission<>'allowed' OR current_license.report_permission<>'allowed'
  OR current_license.retention_days IS NULL OR original>p_at
  OR original+least(30,pinned.retention_days,current_license.retention_days)*interval '1 day'<=p_at;
END $$;
"""

_MEMBERSHIP_GUARD = r"""
CREATE OR REPLACE FUNCTION projection_retained_source_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
 IF EXISTS(SELECT 1 FROM report_input_premium_dependencies WHERE owner_id=selected_owner AND run_id=selected_run AND copy_pending) THEN
  RAISE EXCEPTION 'Projection report copies remain before source membership removal' USING ERRCODE='23514'; END IF;
 RETURN OLD;
END $$;
"""

_PREVIOUS_MEMBERSHIP_GUARD = r"""
CREATE OR REPLACE FUNCTION projection_retained_source_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
"""
