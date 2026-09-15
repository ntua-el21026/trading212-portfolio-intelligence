"""Versioned private reports and immutable retained premium copy dependencies.

Revision ID: 20260915_0019
Revises: 20260914_0018

Previous constraints and retention authorization are frozen here. No canonical
financial bytes are rewritten, decoded, or imported from mutable application code.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0019"
down_revision = "20260914_0018"
branch_labels = None
depends_on = None

_PREVIOUS_COLLECTIONS = {
    "resource_allowed": "resource IN ('risk_definitions','risk_versions','risk_runs','intelligence_quality_sources','activity','dividends','instruments','positions_market_value','positions_weight','positions_ticker','portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','contribution_plans','plan_lines','actual_target_rows','plan_revisions','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings','reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations')",
    "resource_sort_match": "((resource IN ('intelligence_quality_sources','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings') AND sort_specification = 'ordinal_asc') OR (resource = 'activity' AND sort_specification = 'occurred_at_desc_id_desc') OR (resource = 'dividends' AND sort_specification = 'paid_on_desc_id_desc') OR (resource = 'instruments' AND sort_specification = 'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR (resource = 'positions_market_value' AND sort_specification = 'market_value_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_weight' AND sort_specification = 'direct_weight_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_ticker' AND sort_specification = 'ticker_asc_listing_id_asc') OR (resource = 'portfolios_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'portfolios_updated' AND sort_specification = 'updated_at_desc_id_desc') OR (resource = 'target_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource = 'target_events' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'target_nodes' AND sort_specification = 'depth_first_order_key') OR (resource = 'plan_revisions' AND sort_specification = 'revision_number_desc_id_desc') OR (resource = 'contribution_plans' AND sort_specification = 'created_at_desc_id_desc') OR (resource IN ('plan_lines','actual_target_rows','plan_revisions') AND sort_specification = 'ordinal_asc') OR (resource = 'market_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'benchmark_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'fx_source_status' AND sort_specification = 'base_quote_provider_asc') OR (resource = 'price_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'fx_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_defs_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'benchmark_defs_created' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'benchmark_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource IN ('reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations') AND sort_specification = 'created_at_desc_id_desc')) OR (resource IN ('risk_definitions','risk_runs') AND sort_specification='created_at_desc_id_desc') OR (resource='risk_versions' AND sort_specification='version_number_desc_id_desc')",
    "account_scope_match": "(((resource IN ('intelligence_quality_sources','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations','reports','exports','activity','dividends','positions_market_value','positions_weight','positions_ticker','contribution_plans','plan_lines','actual_target_rows','plan_revisions','historical_performance','historical_cash_flows','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities') AND broker_account_id IS NOT NULL) OR (resource = 'instruments' AND broker_account_id IS NULL) OR resource IN ('portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','composite_benchmark_points','constituent_holdings'))) OR (resource IN ('risk_definitions','risk_versions','risk_runs') AND broker_account_id IS NOT NULL)",
}

_PREVIOUS_COMMANDS = "command IN ('reports.generate.v1','exports.generate.v1','risk.definition.create.v1','risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1')"
_PREVIOUS_COMMAND_PARENT = "(command='reports.generate.v1' AND report_job_id IS NOT NULL AND export_job_id IS NULL AND premium_resource_id IS NULL AND premium_actor_id IS NULL AND premium_correlation_id IS NULL) OR (command='exports.generate.v1' AND export_job_id IS NOT NULL AND report_job_id IS NULL AND premium_resource_id IS NULL AND premium_actor_id IS NULL AND premium_correlation_id IS NULL) OR (command IN ('risk.definition.create.v1','risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1') AND report_job_id IS NULL AND export_job_id IS NULL AND premium_resource_id IS NOT NULL AND premium_actor_id IS NOT NULL AND premium_correlation_id IS NOT NULL)"

_PREVIOUS_RETENTION_GUARD = r"""CREATE OR REPLACE FUNCTION report_retention_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE inp report_input_snapshots;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Report retention records are immutable'; END IF;
 SELECT * INTO inp FROM report_input_snapshots WHERE owner_id=NEW.owner_id AND id=NEW.input_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Report retention input is absent'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'Retention must start pending'; END IF;
  IF NEW.reason='ttl' AND inp.expires_at>CURRENT_TIMESTAMP THEN RAISE EXCEPTION 'Report has not expired'; END IF;
  IF NEW.reason='source' AND NOT EXISTS (
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


def _check(table: str, name: str, value: str) -> None:
    constraint = op.f("ck_" + table + "_" + name)
    op.drop_constraint(constraint, table, type_="check")
    op.create_check_constraint(constraint, table, value)


def _contracts(*, premium: bool) -> None:
    for name, previous in _PREVIOUS_COLLECTIONS.items():
        value = (
            previous.replace("'reports','exports'", "'reports','premium_reports','exports'")
            if premium
            else previous
        )
        _check("collection_query_snapshots", name, value)
    _check(
        "application_command_identities",
        "command_allowed",
        _PREVIOUS_COMMANDS.replace(
            "'reports.generate.v1'", "'reports.generate.v1','reports.generate.v2'"
        )
        if premium
        else _PREVIOUS_COMMANDS,
    )
    _check(
        "application_command_identities",
        "parent_kind",
        _PREVIOUS_COMMAND_PARENT.replace(
            "command='reports.generate.v1'",
            "command IN ('reports.generate.v1','reports.generate.v2')",
        )
        if premium
        else _PREVIOUS_COMMAND_PARENT,
    )
    _check(
        "report_definitions",
        "section_bound",
        "cardinality(sections) BETWEEN 1 AND " + ("14" if premium else "13"),
    )


def upgrade() -> None:
    for table in ("report_input_snapshots", "report_jobs"):
        op.add_column(
            table, sa.Column("contract_version", sa.Integer(), nullable=False, server_default="1")
        )
    op.create_check_constraint(
        "contract_version_allowed",
        "report_input_snapshots",
        "contract_version IN (1,2) AND (kind='report' OR contract_version=1)",
    )
    op.create_unique_constraint(
        "uq_report_inputs_contract",
        "report_input_snapshots",
        ["owner_id", "account_id", "id", "contract_version"],
    )
    op.create_check_constraint(
        "contract_version_allowed", "report_jobs", "contract_version IN (1,2)"
    )
    op.create_foreign_key(
        "fk_report_jobs_input_contract",
        "report_jobs",
        "report_input_snapshots",
        ["owner_id", "account_id", "input_id", "contract_version"],
        ["owner_id", "account_id", "id", "contract_version"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_report_jobs_contract_created",
        "report_jobs",
        ["owner_id", "account_id", "contract_version", "requested_at", "id"],
    )
    _contracts(premium=True)
    op.create_table(
        "report_input_premium_dependencies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("result_digest", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["account_id"], ["broker_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "input_id"],
            [
                "report_input_snapshots.owner_id",
                "report_input_snapshots.account_id",
                "report_input_snapshots.id",
            ],
            name="fk_report_premium_input",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["premium_runs.owner_id", "premium_runs.account_id", "premium_runs.id"],
            name="fk_report_premium_run",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("owner_id", "id", name="uq_report_input_premium_dependencies_owner_id"),
        sa.UniqueConstraint("input_id", name="uq_report_premium_input"),
        sa.CheckConstraint("kind='risk'", name="kind_allowed"),
        sa.CheckConstraint(
            "input_digest ~ '^[0-9a-f]{64}$' AND result_digest ~ '^[0-9a-f]{64}$'",
            name="digest_format",
        ),
    )
    op.create_index(
        "ix_report_premium_run",
        "report_input_premium_dependencies",
        ["owner_id", "run_id", "input_id"],
    )
    op.execute(_GUARDS)
    op.execute(
        _PREVIOUS_RETENTION_GUARD.replace(
            "IF NEW.reason='source' AND NOT EXISTS (",
            "IF NEW.reason='source' AND NOT report_premium_restricted(NEW.owner_id,NEW.input_id,CURRENT_TIMESTAMP) AND NOT EXISTS (",
            1,
        )
    )
    op.execute(
        "CREATE TRIGGER report_premium_dependency BEFORE INSERT OR UPDATE OR DELETE ON report_input_premium_dependencies FOR EACH ROW EXECUTE FUNCTION report_premium_dependency_guard()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER report_premium_capture_complete AFTER INSERT OR UPDATE ON report_input_snapshots DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION report_premium_capture_complete()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER report_command_contract AFTER INSERT ON application_command_identities DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION report_command_contract_guard()"
    )
    for table in _PREMIUM_COPY_TABLES:
        operations = (
            "INSERT OR UPDATE" if table == "premium_retention_events" else "UPDATE OR DELETE"
        )
        op.execute(
            f"CREATE TRIGGER reports_premium_copy_guard BEFORE {operations} ON {table} FOR EACH ROW EXECUTE FUNCTION report_premium_copy_guard()"
        )


def downgrade() -> None:
    # Dropping a used profile would erase immutable meaning even after payload expiry.
    op.execute("""
      DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM report_input_snapshots WHERE contract_version=2)
          OR EXISTS (SELECT 1 FROM collection_query_snapshots WHERE resource='premium_reports')
          OR EXISTS (SELECT 1 FROM report_definitions WHERE cardinality(sections)>13)
        THEN RAISE EXCEPTION 'Premium report metadata prevents downgrade'; END IF;
      END $$;
    """)
    for table in _PREMIUM_COPY_TABLES:
        op.execute(f"DROP TRIGGER reports_premium_copy_guard ON {table}")
    op.execute("DROP FUNCTION report_premium_copy_guard()")
    op.execute("DROP TRIGGER report_command_contract ON application_command_identities")
    op.execute("DROP FUNCTION report_command_contract_guard()")
    op.execute("DROP TRIGGER report_premium_capture_complete ON report_input_snapshots")
    op.execute("DROP FUNCTION report_premium_capture_complete()")
    op.execute("DROP TRIGGER report_premium_dependency ON report_input_premium_dependencies")
    op.execute("DROP FUNCTION report_premium_dependency_guard()")
    op.execute(_PREVIOUS_RETENTION_GUARD)
    op.execute("DROP FUNCTION report_premium_restricted(uuid,uuid,timestamptz)")
    op.drop_table("report_input_premium_dependencies")
    _contracts(premium=False)
    op.drop_index("ix_report_jobs_contract_created", table_name="report_jobs")
    op.drop_constraint("fk_report_jobs_input_contract", "report_jobs", type_="foreignkey")
    op.drop_constraint(
        op.f("ck_report_jobs_contract_version_allowed"), "report_jobs", type_="check"
    )
    op.drop_constraint("uq_report_inputs_contract", "report_input_snapshots", type_="unique")
    op.drop_constraint(
        op.f("ck_report_input_snapshots_contract_version_allowed"),
        "report_input_snapshots",
        type_="check",
    )
    op.drop_column("report_jobs", "contract_version")
    op.drop_column("report_input_snapshots", "contract_version")


_PREMIUM_COPY_TABLES = (
    "premium_retention_events",
    "premium_runs",
    "risk_run_assets",
    "risk_results",
    "risk_series",
    "risk_intervals",
    "risk_matrix_cells",
    "risk_metrics",
    "risk_components",
)

_GUARDS = r"""
CREATE FUNCTION report_premium_restricted(p_owner uuid, p_input uuid, p_at timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT COALESCE((SELECT CASE WHEN i.contract_version=1 THEN false ELSE
   (SELECT count(*) FROM report_input_premium_dependencies d
      WHERE d.owner_id=i.owner_id AND d.account_id=i.account_id AND d.input_id=i.id)<>1
   OR EXISTS (
    SELECT 1 FROM report_input_premium_dependencies d
    LEFT JOIN premium_runs r ON r.owner_id=d.owner_id AND r.account_id=d.account_id AND r.id=d.run_id
    LEFT JOIN risk_runs rr ON rr.owner_id=r.owner_id AND rr.account_id=r.account_id AND rr.id=r.id
    LEFT JOIN risk_results result ON result.owner_id=r.owner_id AND result.account_id=r.account_id AND result.run_id=r.id
    LEFT JOIN premium_jobs j ON j.owner_id=r.owner_id AND j.account_id=r.account_id AND j.run_id=r.id
    WHERE d.owner_id=i.owner_id AND d.input_id=i.id AND (
      d.kind IS DISTINCT FROM 'risk' OR r.kind IS DISTINCT FROM 'risk'
      OR rr.sealed IS DISTINCT FROM true OR result.sealed IS DISTINCT FROM true
      OR j.state IS DISTINCT FROM 'succeeded'
      OR d.input_digest IS DISTINCT FROM r.input_digest
      OR d.result_digest IS DISTINCT FROM result.content_digest
      OR d.expires_at>r.expires_at OR d.expires_at<=d.created_at
      OR d.expires_at<=p_at OR r.expires_at<=p_at
      OR EXISTS (SELECT 1 FROM premium_retention_events e
          WHERE e.owner_id=d.owner_id AND e.run_id=d.run_id)
      OR EXISTS (
        SELECT 1 FROM premium_run_licenses lineage
        LEFT JOIN provider_license_versions pinned ON pinned.owner_id=lineage.owner_id
          AND pinned.provider_id=lineage.provider_id AND pinned.id=lineage.license_version_id
        LEFT JOIN LATERAL (
          SELECT l.id,l.store_permission,l.display_permission,l.report_permission,l.retention_days
          FROM provider_license_versions l WHERE l.owner_id=lineage.owner_id
            AND l.provider_id=lineage.provider_id AND l.effective_at<=p_at
          ORDER BY l.effective_at DESC,l.version_number DESC,l.id DESC LIMIT 1
        ) current_license ON true
        WHERE lineage.owner_id=d.owner_id AND lineage.account_id=d.account_id AND lineage.run_id=d.run_id
          AND (pinned.id IS NULL OR current_license.id IS NULL
            OR pinned.store_permission IS DISTINCT FROM 'allowed'
            OR pinned.display_permission IS DISTINCT FROM 'allowed'
            OR pinned.report_permission IS DISTINCT FROM 'allowed'
            OR current_license.store_permission IS DISTINCT FROM 'allowed'
            OR current_license.display_permission IS DISTINCT FROM 'allowed'
            OR current_license.report_permission IS DISTINCT FROM 'allowed'
            OR pinned.retention_days IS NULL OR current_license.retention_days IS NULL
            OR r.created_at+LEAST(pinned.retention_days,current_license.retention_days)*INTERVAL '1 day'<=p_at)
      )
    )
   ) END FROM report_input_snapshots i WHERE i.owner_id=p_owner AND i.id=p_input),true)
$$;

CREATE FUNCTION report_premium_dependency_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version integer; sealed timestamptz; purged timestamptz;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Premium report lineage is immutable' USING ERRCODE='23514'; END IF;
 PERFORM id FROM premium_runs WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id
   AND id=NEW.run_id FOR UPDATE;
 SELECT contract_version,sealed_at,purged_at INTO version,sealed,purged
   FROM report_input_snapshots WHERE id=NEW.input_id AND owner_id=NEW.owner_id
     AND account_id=NEW.account_id FOR UPDATE;
 IF version IS DISTINCT FROM 2 OR sealed IS NOT NULL OR purged IS NOT NULL THEN
   RAISE EXCEPTION 'Premium report capture is not open' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS (
   SELECT 1 FROM premium_runs r JOIN risk_runs rr
     ON rr.owner_id=r.owner_id AND rr.account_id=r.account_id AND rr.id=r.id
   JOIN risk_results result ON result.owner_id=r.owner_id AND result.account_id=r.account_id AND result.run_id=r.id
   JOIN premium_jobs j ON j.owner_id=r.owner_id AND j.account_id=r.account_id AND j.run_id=r.id
   WHERE r.owner_id=NEW.owner_id AND r.account_id=NEW.account_id AND r.id=NEW.run_id
     AND r.kind=NEW.kind AND rr.sealed AND result.sealed AND j.state='succeeded'
     AND r.input_digest=NEW.input_digest AND result.content_digest=NEW.result_digest
     AND NEW.expires_at<=r.expires_at AND NEW.expires_at>NEW.created_at AND NEW.expires_at>CURRENT_TIMESTAMP
     AND NOT EXISTS (SELECT 1 FROM premium_retention_events e WHERE e.owner_id=r.owner_id AND e.run_id=r.id)
 ) THEN RAISE EXCEPTION 'Premium report source binding mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION report_premium_capture_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version integer; deadline timestamptz; purged timestamptz; dependencies bigint;
BEGIN
 SELECT contract_version,expires_at,purged_at INTO version,deadline,purged
   FROM report_input_snapshots WHERE id=NEW.id AND owner_id=NEW.owner_id;
 SELECT count(*) INTO dependencies FROM report_input_premium_dependencies
   WHERE owner_id=NEW.owner_id AND input_id=NEW.id;
 IF (version=1 AND dependencies<>0) OR (version=2 AND dependencies<>1) THEN
   RAISE EXCEPTION 'Report contract lineage mismatch' USING ERRCODE='23514'; END IF;
 IF version=2 AND (EXISTS (SELECT 1 FROM report_input_premium_dependencies
     WHERE input_id=NEW.id AND expires_at<deadline)
   OR (purged IS NULL AND report_premium_restricted(NEW.owner_id,NEW.id,CURRENT_TIMESTAMP))) THEN
   RAISE EXCEPTION 'Premium report source is unavailable' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION report_command_contract_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version integer;
BEGIN
 IF NEW.command NOT IN ('reports.generate.v1','reports.generate.v2') THEN RETURN NEW; END IF;
 SELECT contract_version INTO version FROM report_jobs
   WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.report_job_id;
 IF version IS DISTINCT FROM (CASE NEW.command WHEN 'reports.generate.v1' THEN 1 ELSE 2 END) THEN
   RAISE EXCEPTION 'Report command contract mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION report_premium_copy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner uuid; run uuid;
BEGIN
 IF TG_TABLE_NAME='premium_retention_events' THEN
   owner:=NEW.owner_id; run:=NEW.run_id;
   PERFORM id FROM premium_runs WHERE owner_id=owner AND id=run FOR UPDATE;
   IF NEW.completed_at IS NULL THEN RETURN NEW; END IF;
 ELSIF TG_TABLE_NAME='premium_runs' THEN
   IF TG_OP='UPDATE' AND NEW.retained_bytes>=OLD.retained_bytes AND NEW.reserved_bytes>=OLD.reserved_bytes THEN RETURN NEW; END IF;
   owner:=OLD.owner_id; run:=OLD.id;
 ELSIF TG_TABLE_NAME IN ('risk_run_assets','risk_results') THEN
   owner:=OLD.owner_id; run:=OLD.run_id;
 ELSE
   owner:=OLD.owner_id;
   SELECT run_id INTO run FROM risk_results WHERE owner_id=owner AND id=OLD.result_id;
 END IF;
 PERFORM id FROM premium_runs WHERE owner_id=owner AND id=run FOR UPDATE;
 IF EXISTS (SELECT 1 FROM report_input_premium_dependencies d WHERE d.owner_id=owner
     AND d.run_id=run AND report_capture_pending(d.owner_id,d.input_id)) THEN
   RAISE EXCEPTION 'Premium report copies remain' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
"""
